"""Tests of sensors, reminders, the calendar and the refresh button."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.prezero_bielsko.api import PreZeroConnectionError
from custom_components.prezero_bielsko.binary_sensor import ReminderBinarySensor
from custom_components.prezero_bielsko.const import (
    CONF_DAYS_PREFIX,
    CONF_REMINDER_END,
    CONF_REMINDER_START,
    SECTION_REMINDERS,
)
from custom_components.prezero_bielsko.models import Collection
from custom_components.prezero_bielsko.sensor import (
    FractionDaysSensor,
    NextCollectionSensor,
)

from .conftest import SYMBOL, FakeClient, make_schedule

REMINDER_PAPER = "binary_sensor.testowa_1_reminder_paper"
REMINDER_ANY = "binary_sensor.testowa_1_collection_reminder"


def at(value: str) -> datetime:
    """Return a Warsaw time."""
    return datetime.fromisoformat(f"{value}+02:00")


async def _move(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, value: str
) -> None:
    freezer.move_to(at(value))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_fraction_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Fraction sensors show days until the next collection."""
    expected = {
        "paper": "4",
        "glass": "4",
        "bio": "8",
        "mixed_waste": "8",
        "metals_and_plastics": "11",
        "ash": "12",
        "green_waste": "17",
        "bulky_waste": "72",
    }
    for name, days in expected.items():
        assert hass.states.get(f"sensor.testowa_1_{name}").state == days, name

    paper = hass.states.get("sensor.testowa_1_paper")
    assert paper.attributes == {
        "fraction": "Paper",
        "next_date": "2026-10-15",
        "upcoming": ["2026-10-15", "2026-11-20", "2026-12-15"],
        "color": "#1565C0",
        "unit_of_measurement": "d",
        "entity_picture": "/api/prezero_bielsko/icon/makulatura.svg?color=1565C0",
        "friendly_name": "Testowa 1 Paper",
    }


async def test_next_collection_sensor(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The next collection sensor lists the fractions of the nearest day."""
    state = hass.states.get("sensor.testowa_1_next_collection")
    assert state.state == "2026-10-15"
    assert state.attributes["fractions"] == ["Paper", "Glass"]
    assert state.attributes["fraction_keys"] == ["makulatura", "szklo"]
    assert state.attributes["days"] == 4
    assert state.attributes["pdf_url"].endswith("&q=BBA%2F10000001&rok=2026")


async def test_diagnostic_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Diagnostic sensors show download and publication times."""
    assert hass.states.get("sensor.testowa_1_last_successful_download").state == (
        "2026-10-11T10:00:00+00:00"
    )
    assert hass.states.get("sensor.testowa_1_schedule_published").state == (
        "2026-09-22T07:56:00+00:00"
    )
    problem = hass.states.get("binary_sensor.testowa_1_download_problem")
    assert problem.state == "off"
    assert problem.attributes["error"] is None


async def test_sensors_without_upcoming_collections(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """Fractions without future collections have unknown states."""
    client.schedules[(SYMBOL, 2026)] = make_schedule(
        2026, [("2026-01-02", "makulatura"), ("2026-10-12", "szklo")]
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    paper = hass.states.get("sensor.testowa_1_paper")
    assert paper.state == "unknown"
    assert paper.attributes["next_date"] is None
    assert paper.attributes["upcoming"] == []
    await _move(hass, now, "2026-10-13T00:00:05")
    assert hass.states.get("sensor.testowa_1_next_collection").state == "unknown"
    assert (
        hass.states.get("sensor.testowa_1_next_collection").attributes["days"] is None
    )


async def test_new_and_unknown_fractions_added(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
) -> None:
    """Fractions appearing later get entities, unknown ones use the raw name."""
    schedule = client.schedules[(SYMBOL, 2026)]
    client.schedules[(SYMBOL, 2026)] = make_schedule(
        2026,
        [(item.date.isoformat(), item.fraction) for item in schedule.collections]
        + [("2026-10-20", "elektro")],
    )
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.testowa_1_elektro")
    assert state.state == "9"
    assert state.attributes["entity_picture"].startswith(
        "/api/prezero_bielsko/icon/elektro.svg?color=607D8B"
    )
    assert hass.states.get("binary_sensor.testowa_1_reminder_elektro").state == "off"
    events = await _calendar_events(hass, "2026-10-20T00:00:00", "2026-10-21T00:00:00")
    assert [event["summary"] for event in events] == ["Elektro"]


async def test_reminder_transitions(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    now: FrozenDateTimeFactory,
) -> None:
    """Reminders turn on and off exactly at the window boundaries."""
    state = hass.states.get(REMINDER_PAPER)
    assert state.state == "off"
    assert state.attributes["collection_date"] == "2026-10-15"
    assert state.attributes["days_before"] == 1
    assert hass.states.get(REMINDER_ANY).state == "off"

    await _move(hass, now, "2026-10-14T17:59:59")
    assert hass.states.get(REMINDER_PAPER).state == "off"

    assert "entity_picture" not in hass.states.get(REMINDER_PAPER).attributes

    await _move(hass, now, "2026-10-14T18:00:00")
    assert hass.states.get(REMINDER_PAPER).state == "on"
    assert hass.states.get(REMINDER_PAPER).attributes["entity_picture"] == (
        "/api/prezero_bielsko/icon/makulatura.svg?color=1565C0"
    )
    assert hass.states.get("binary_sensor.testowa_1_reminder_glass").state == "on"
    assert hass.states.get("binary_sensor.testowa_1_reminder_bio").state == "off"
    any_state = hass.states.get(REMINDER_ANY)
    assert any_state.state == "on"
    assert any_state.attributes["fractions"] == ["Paper", "Glass"]
    assert any_state.attributes["fraction_keys"] == ["makulatura", "szklo"]
    assert any_state.attributes["collection_date"] == "2026-10-15"

    await _move(hass, now, "2026-10-15T09:59:59")
    assert hass.states.get(REMINDER_PAPER).state == "on"

    await _move(hass, now, "2026-10-15T10:00:00")
    assert hass.states.get(REMINDER_PAPER).state == "off"
    assert hass.states.get(REMINDER_PAPER).attributes["collection_date"] == "2026-11-20"
    assert hass.states.get(REMINDER_ANY).state == "off"
    assert hass.states.get(REMINDER_ANY).attributes["fractions"] == []


async def test_reminder_options(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """Per fraction days and times from options are used."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            **config_entry.options,
            SECTION_REMINDERS: {
                CONF_REMINDER_START: "07:00:00",
                CONF_REMINDER_END: "12:00:00",
                f"{CONF_DAYS_PREFIX}makulatura": 4,
            },
        },
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    # 4 days before 15.10 at 07:00 is 11.10 07:00, now is 11.10 12:00.
    assert hass.states.get(REMINDER_PAPER).state == "on"
    assert hass.states.get(REMINDER_PAPER).attributes["days_before"] == 4
    assert hass.states.get("binary_sensor.testowa_1_reminder_glass").state == "off"
    await _move(hass, now, "2026-10-15T12:00:00")
    assert hass.states.get(REMINDER_PAPER).state == "off"


async def test_reminder_on_after_restart(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A reminder is on right away when set up inside its window."""
    freezer.move_to(at("2026-10-14T20:00:00"))
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(REMINDER_PAPER).state == "on"


async def test_reminder_rescheduled_after_update(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """A changed schedule moves the reminder timer."""
    schedule = client.schedules[(SYMBOL, 2026)]
    client.schedules[(SYMBOL, 2026)] = make_schedule(
        2026,
        [
            (item.date.isoformat(), item.fraction)
            for item in schedule.collections
            if item != Collection(date(2026, 10, 15), "makulatura")
        ]
        + [("2026-10-13", "makulatura")],
    )
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(REMINDER_PAPER).attributes["collection_date"] == "2026-10-13"
    await _move(hass, now, "2026-10-12T18:00:00")
    assert hass.states.get(REMINDER_PAPER).state == "on"
    await _move(hass, now, "2026-10-14T18:00:00")
    # Paper moved, glass stays on 15.10.
    assert hass.states.get(REMINDER_PAPER).state == "off"
    assert hass.states.get(REMINDER_ANY).attributes["fraction_keys"] == ["szklo"]


async def _calendar_events(hass: HomeAssistant, start: str, end: str) -> list[dict]:
    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {
            ATTR_ENTITY_ID: "calendar.testowa_1_collection_schedule",
            "start_date_time": at(start),
            "end_date_time": at(end),
        },
        blocking=True,
        return_response=True,
    )
    return response["calendar.testowa_1_collection_schedule"]["events"]


async def test_calendar(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """The calendar has all day events of collections."""
    state = hass.states.get("calendar.testowa_1_collection_schedule")
    assert state.state == "off"
    assert state.attributes["message"] == "Paper"
    assert state.attributes["all_day"] is True
    assert state.attributes["start_time"] == "2026-10-15 00:00:00"
    assert state.attributes["location"] == "Testowa 1"

    events = await _calendar_events(hass, "2026-10-15T12:00:00", "2026-10-20T00:00:00")
    assert events == [
        {
            "start": "2026-10-15",
            "end": "2026-10-16",
            "summary": "Paper",
            "location": "Testowa 1",
        },
        {
            "start": "2026-10-15",
            "end": "2026-10-16",
            "summary": "Glass",
            "location": "Testowa 1",
        },
        {
            "start": "2026-10-19",
            "end": "2026-10-20",
            "summary": "Bio",
            "location": "Testowa 1",
        },
        {
            "start": "2026-10-19",
            "end": "2026-10-20",
            "summary": "Mixed waste",
            "location": "Testowa 1",
        },
    ]
    assert (
        await _calendar_events(hass, "2026-10-16T00:00:00", "2026-10-19T00:00:00") == []
    )


async def test_calendar_state_on_collection_day(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    now: FrozenDateTimeFactory,
) -> None:
    """The calendar is on during a collection day."""
    await _move(hass, now, "2026-10-15T00:00:05")
    assert hass.states.get("calendar.testowa_1_collection_schedule").state == "on"


@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_calendar_trigger_automation(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    now: FrozenDateTimeFactory,
) -> None:
    """A calendar trigger with an offset fires the evening before."""
    calls = async_mock_service(hass, "test", "automation")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "trigger": {
                    "platform": "calendar",
                    "event": "start",
                    "entity_id": "calendar.testowa_1_collection_schedule",
                    "offset": "-6:00:00",
                },
                "action": {
                    "service": "test.automation",
                    "data": {"summary": "{{ trigger.calendar_event.summary }}"},
                },
            }
        },
    )
    await hass.async_block_till_done()
    for minute in range(0, 24 * 60 * 4, 15):
        now.move_to(at("2026-10-11T12:00:00") + timedelta(minutes=minute))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        if calls:
            break
    assert sorted(call.data["summary"] for call in calls) == ["Glass", "Paper"]
    assert dt_util.now() >= at("2026-10-14T18:00:00")


async def test_refresh_button(
    hass: HomeAssistant, init_integration: MockConfigEntry, client: FakeClient
) -> None:
    """The button downloads the schedule right away."""
    await hass.services.async_call(
        "button",
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: "button.testowa_1_refresh_schedule"},
        blocking=True,
    )
    assert len(client.calls_of("schedule")) == 2


async def test_refresh_button_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, client: FakeClient
) -> None:
    """A failed manual refresh is reported to the user."""
    client.error = PreZeroConnectionError("down")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "button",
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: "button.testowa_1_refresh_schedule"},
            blocking=True,
        )
    assert err.value.translation_key == "refresh_failed"
    assert err.value.translation_placeholders == {"error": "down"}
    assert hass.states.get("binary_sensor.testowa_1_download_problem").state == "on"
    assert hass.states.get("sensor.testowa_1_paper").state == "4"


def test_unrecorded_attributes() -> None:
    """Attributes derived from the schedule are excluded from the recorder."""
    assert {"next_date", "upcoming", "color", "fraction"} <= (
        FractionDaysSensor._unrecorded_attributes
    )
    assert {"fractions", "days", "pdf_url"} <= (
        NextCollectionSensor._unrecorded_attributes
    )
    assert {"collection_date", "days_before"} <= (
        ReminderBinarySensor._unrecorded_attributes
    )
