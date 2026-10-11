"""Tests of setup, cache, actions, pictures and diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.prezero_bielsko.api import PreZeroConnectionError
from custom_components.prezero_bielsko.const import DOMAIN, SERVICE_GET_SCHEDULE
from custom_components.prezero_bielsko.models import ScheduleData

from .conftest import NUMBER, STREET, SYMBOL, TITLE, FakeClient, schedule_2026

STORAGE_KEY = "prezero_bielsko.{}"


def _cache(
    entry: MockConfigEntry,
    last_success: datetime,
    address: str = f"{STREET}|{NUMBER}|10000001",
) -> dict[str, Any]:
    return {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY.format(entry.entry_id),
        "data": {
            "address": address,
            "symbols": {"2026": SYMBOL},
            "data": ScheduleData(
                schedules={2026: schedule_2026()}, last_success=last_success
            ).as_dict(),
        },
    }


async def test_setup_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """All entities are created and unique ids are stable."""
    entries = er.async_entries_for_config_entry(
        entity_registry, init_integration.entry_id
    )
    by_domain: dict[str, int] = {}
    for item in entries:
        by_domain[item.domain] = by_domain.get(item.domain, 0) + 1
    assert by_domain == {"sensor": 11, "binary_sensor": 10, "button": 1, "calendar": 1}
    assert all(item.unique_id.startswith(init_integration.entry_id) for item in entries)
    assert hass.states.get("sensor.testowa_1_paper").state == "4"
    assert init_integration.state is ConfigEntryState.LOADED


async def test_setup_retry_without_cache(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """Setup is retried when there is no cache and no connection."""
    client.error = PreZeroConnectionError("down")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_fresh_cache_skips_download(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """A fresh cache is used without downloading, refresh happens when due."""
    hass_storage[STORAGE_KEY.format(config_entry.entry_id)] = _cache(
        config_entry, datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert client.calls == []
    assert hass.states.get("sensor.testowa_1_paper").state == "4"
    coordinator = config_entry.runtime_data
    # Downloaded at 08:00 UTC, now is 10:00 UTC: next download in 22 hours.
    assert coordinator.update_interval == timedelta(hours=22)


async def test_setup_offline_with_stale_cache(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """A stale cache keeps entities working when the service is down."""
    hass_storage[STORAGE_KEY.format(config_entry.entry_id)] = _cache(
        config_entry, datetime(2026, 10, 1, tzinfo=UTC)
    )
    client.error = PreZeroConnectionError("down")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.testowa_1_paper").state == "4"
    problem = hass.states.get("binary_sensor.testowa_1_download_problem")
    assert problem.state == "on"
    assert "down" in problem.attributes["error"]
    assert hass.states.get("sensor.testowa_1_last_successful_download").state == (
        "2026-10-01T00:00:00+00:00"
    )


@pytest.mark.parametrize(
    "stored",
    [
        {"address": "OTHER|1|1", "symbols": {}, "data": {}},
        {"address": f"{STREET}|{NUMBER}|10000001", "symbols": {}, "data": {"x": 1}},
        {"address": f"{STREET}|{NUMBER}|10000001", "symbols": [], "data": None},
        {
            "address": f"{STREET}|{NUMBER}|10000001",
            "symbols": {},
            "data": {"last_success": None, "schedules": {}},
        },
    ],
)
async def test_setup_ignores_unusable_cache(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
    stored: dict[str, Any],
) -> None:
    """Caches of another address or with invalid content are ignored."""
    hass_storage[STORAGE_KEY.format(config_entry.entry_id)] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY.format(config_entry.entry_id),
        "data": stored,
    }
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert client.calls_of("schedule") == [("schedule", SYMBOL, 2026)]


async def test_cache_saved(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Downloaded data is persisted."""
    stored = hass_storage[STORAGE_KEY.format(init_integration.entry_id)]["data"]
    assert stored["address"] == f"{STREET}|{NUMBER}|10000001"
    assert stored["symbols"] == {"2026": SYMBOL}
    assert len(stored["data"]["schedules"]["2026"]["collections"]) == 128


async def test_unload_and_remove(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    client: FakeClient,
    hass_storage: dict[str, Any],
    issue_registry: ir.IssueRegistry,
) -> None:
    """Unloading stops entities, removing deletes the cache and issues."""
    entry = init_integration
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"schedule_missing_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="schedule_missing",
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("sensor.testowa_1_paper").state == "unavailable"

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert STORAGE_KEY.format(entry.entry_id) not in hass_storage
    assert (
        issue_registry.async_get_issue(DOMAIN, f"schedule_missing_{entry.entry_id}")
        is None
    )


async def test_get_schedule_action(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The action returns upcoming collections."""
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        {"config_entry_id": init_integration.entry_id, "days": 9},
        blocking=True,
        return_response=True,
    )
    assert response == {
        "address": TITLE,
        "collections": [
            {
                "date": "2026-10-15",
                "days": 4,
                "fraction": "makulatura",
                "name": "Paper",
            },
            {"date": "2026-10-15", "days": 4, "fraction": "szklo", "name": "Glass"},
            {"date": "2026-10-19", "days": 8, "fraction": "kuchenne", "name": "Bio"},
            {
                "date": "2026-10-19",
                "days": 8,
                "fraction": "resztkowe",
                "name": "Mixed waste",
            },
        ],
    }


async def test_get_schedule_action_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Unknown or unloaded entries are rejected."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_SCHEDULE,
            {"config_entry_id": "missing"},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "entry_not_found"

    await hass.config_entries.async_unload(init_integration.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_SCHEDULE,
            {"config_entry_id": init_integration.entry_id},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "entry_not_loaded"


async def test_picture_view(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    """Colored pictures are served without authentication."""
    http = await hass_client_no_auth()
    picture = hass.states.get("sensor.testowa_1_paper").attributes["entity_picture"]
    assert picture == "/api/prezero_bielsko/icon/makulatura.svg?color=1565C0"

    response = await http.get(picture)
    assert response.status == 200
    assert response.content_type == "image/svg+xml"
    assert 'fill="#1565C0"' in await response.text()

    response = await http.get("/api/prezero_bielsko/icon/elektro.svg?color=zzz")
    assert response.status == 200
    assert "#607D8B" in await response.text()

    response = await http.get("/api/prezero_bielsko/icon/../secret")
    assert response.status == 404
    response = await http.get("/api/prezero_bielsko/icon/MAKULATURA.png")
    assert response.status == 404


async def test_diagnostics(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    """Diagnostics do not contain the address."""
    result = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    text = str(result)
    assert STREET not in text
    assert SYMBOL not in text
    assert result["entry"]["data"] == {
        "street": "**REDACTED**",
        "number": "**REDACTED**",
        "symbol": "**REDACTED**",
    }
    assert result["coordinator"]["last_update_success"] is True
    assert result["data"]["schedules"]["2026"]["collections"] == 128
    assert result["data"]["fractions"][0] == "resztkowe"
