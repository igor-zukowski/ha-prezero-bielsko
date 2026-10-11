"""Tests of downloading, retries, repair issues, events and the year change."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.prezero_bielsko.api import (
    PreZeroConnectionError,
    PreZeroResponseError,
)
from custom_components.prezero_bielsko.const import (
    CONF_REFRESH_INTERVAL,
    DOMAIN,
    EVENT_SCHEDULE_UPDATED,
    SECTION_REFRESH,
)
from custom_components.prezero_bielsko.models import Collection, Customer

from .conftest import NUMBER, STREET, SYMBOL, FakeClient, make_schedule

PAPER = "sensor.testowa_1_paper"
PROBLEM = "binary_sensor.testowa_1_download_problem"


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_single_request_per_refresh(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """A refresh downloads only the schedule once the symbol is known."""
    assert client.calls == [("schedule", SYMBOL, 2026)]
    await _tick(hass, now, timedelta(days=1))
    assert client.calls == [("schedule", SYMBOL, 2026)] * 2


async def test_midnight_updates_without_download(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """Days until a collection decrease at midnight without downloading."""
    assert hass.states.get(PAPER).state == "4"
    now.move_to(datetime.fromisoformat("2026-10-12T00:00:05+02:00"))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(PAPER).state == "3"
    assert len(client.calls) == 1


async def test_retry_backoff_and_recovery(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Failures are retried with increasing delays, then recover."""
    coordinator = init_integration.runtime_data
    issue = f"fetch_failed_{init_integration.entry_id}"
    client.error = PreZeroConnectionError("down")

    await _tick(hass, now, timedelta(days=1))
    assert hass.states.get(PROBLEM).state == "on"
    assert hass.states.get(PAPER).state == "3"  # cached data is kept
    assert coordinator.update_interval == timedelta(minutes=30)

    expected = [timedelta(hours=1), timedelta(hours=2), timedelta(hours=4)]
    for delay in [timedelta(minutes=30), timedelta(hours=1), timedelta(hours=2)]:
        await _tick(hass, now, delay)
        assert coordinator.update_interval == expected.pop(0)
    assert coordinator.failures == 4
    assert issue_registry.async_get_issue(DOMAIN, issue) is None

    for _ in range(4):
        await _tick(hass, now, coordinator.update_interval)
    assert coordinator.update_interval == timedelta(hours=6)
    # Failing since more than a day: a repair issue is raised.
    assert issue_registry.async_get_issue(DOMAIN, issue) is not None
    assert hass.states.get(PROBLEM).attributes["failures"] >= 5

    client.error = None
    await _tick(hass, now, timedelta(hours=6))
    assert hass.states.get(PROBLEM).state == "off"
    assert coordinator.update_interval == timedelta(days=1)
    assert coordinator.failures == 0
    assert issue_registry.async_get_issue(DOMAIN, issue) is None


async def test_retry_capped_by_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """Retry delays never exceed the configured interval."""
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data
    coordinator.refresh_interval = timedelta(minutes=45)
    client.error = PreZeroResponseError("changed")
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(minutes=45)


async def test_schedule_missing_issue(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    """An empty schedule of the current year raises an issue until published."""
    issue = f"schedule_missing_{init_integration.entry_id}"
    original = client.schedules.pop((SYMBOL, 2026))
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue) is not None
    assert hass.states.get(PAPER).state == "unknown"
    assert hass.states.get(PROBLEM).state == "off"
    # The symbol was re-resolved because the schedule was empty.
    assert client.calls_of("customers")

    client.schedules[(SYMBOL, 2026)] = original
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue) is None
    assert hass.states.get(PAPER).state == "4"


async def test_address_not_found_issue(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A vanished address raises an issue and is a failed download."""
    issue = f"address_not_found_{init_integration.entry_id}"
    client.schedules.pop((SYMBOL, 2026))
    client.customers[(STREET, NUMBER)] = []
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue) is not None
    assert hass.states.get(PROBLEM).state == "on"
    assert hass.states.get(PAPER).state == "4"

    client.customers[(STREET, NUMBER)] = [Customer(SYMBOL)]
    client.schedules[(SYMBOL, 2026)] = FakeClient().schedules[(SYMBOL, 2026)]
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(DOMAIN, issue) is None


async def test_schedule_updated_event(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """A changed schedule fires an event with the differences."""
    events = async_capture_events(hass, EVENT_SCHEDULE_UPDATED)
    coordinator = init_integration.runtime_data

    await coordinator.async_refresh()
    assert events == []

    old = client.schedules[(SYMBOL, 2026)]
    moved = Collection(date(2026, 10, 15), "makulatura")
    client.schedules[(SYMBOL, 2026)] = replace(
        old,
        collections=tuple(
            sorted(
                {
                    *old.collections,
                    Collection(date(2026, 10, 16), "makulatura"),
                }
                - {moved}
            )
        ),
        published=old.published + timedelta(days=1),
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1
    data = events[0].data
    assert data["config_entry_id"] == init_integration.entry_id
    assert data["address"] == "Testowa 1"
    assert data["added"] == [{"date": "2026-10-16", "fraction": "makulatura"}]
    assert data["removed"] == [{"date": "2026-10-15", "fraction": "makulatura"}]
    assert data["published"] == "2026-09-23T09:56:00+02:00"
    assert data["previous_published"] == "2026-09-22T09:56:00+02:00"
    assert hass.states.get(PAPER).state == "5"


async def test_december_prefetches_next_year(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """In December the next year is downloaded and used after New Year."""
    freezer.move_to("2026-12-31T12:00:00+01:00")
    # The symbol format changes in the new year.
    client.customers[(STREET, NUMBER)] = [Customer("10000001")]
    client.schedules[("10000001", 2027)] = make_schedule(
        2027, [("2027-01-04", "kuchenne"), ("2027-01-11", "makulatura")], "10000001"
    )
    await _setup(hass, config_entry)
    assert client.calls == [
        ("schedule", SYMBOL, 2026),
        ("customers", STREET, NUMBER, 2027),
        ("schedule", "10000001", 2027),
    ]
    assert hass.states.get("sensor.testowa_1_bio").state == "4"
    assert hass.states.get("sensor.testowa_1_paper").state == "11"

    freezer.move_to("2027-01-01T00:00:05+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(client.calls) == 3  # nothing to download at New Year
    assert hass.states.get("sensor.testowa_1_bio").state == "3"

    # The next regular refresh drops the old year and uses the known symbol.
    client.calls.clear()
    freezer.move_to("2027-01-01T12:00:10+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert client.calls == [("schedule", "10000001", 2027)]
    assert set(config_entry.runtime_data.data.schedules) == {2027}


async def test_new_year_without_prefetch(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    """At New Year a missing schedule is downloaded right away."""
    freezer.move_to("2026-12-31T12:00:00+01:00")
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            SECTION_REFRESH: {CONF_REFRESH_INTERVAL: "monthly"},
        },
    )
    await _setup(hass, config_entry)
    assert 2027 not in config_entry.runtime_data.data.schedules
    issue = f"schedule_missing_{config_entry.entry_id}"

    client.calls.clear()
    freezer.move_to("2027-01-01T00:00:05+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=11))  # debounce
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert ("schedule", SYMBOL, 2027) in client.calls
    assert issue_registry.async_get_issue(DOMAIN, issue) is not None
    assert hass.states.get(PAPER).state == "unknown"


async def test_december_daily_attempts_with_long_interval(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With a weekly interval the next year is still checked every December day."""
    freezer.move_to("2026-12-10T12:00:00+01:00")
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            SECTION_REFRESH: {CONF_REFRESH_INTERVAL: "weekly"},
        },
    )
    await _setup(hass, config_entry)
    assert client.calls_of("customers") == [("customers", STREET, NUMBER, 2027)]

    freezer.move_to("2026-12-11T00:00:05+01:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(client.calls_of("customers")) == 2

    # Not more than once a day.
    await config_entry.runtime_data.async_refresh()
    freezer.move_to("2026-12-11T00:00:30+01:00")
    config_entry.runtime_data._async_day_changed(dt_util.now())
    await hass.async_block_till_done()
    assert len(client.calls_of("customers")) == 3


async def test_next_year_errors_are_ignored(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Problems with the next year do not fail the refresh."""
    freezer.move_to("2026-12-30T12:00:00+01:00")
    client.customers[(STREET, NUMBER)] = []
    await _setup(hass, config_entry)
    assert hass.states.get(PROBLEM).state == "off"
    assert set(config_entry.runtime_data.data.schedules) == {2026}
