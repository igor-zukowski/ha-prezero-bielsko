"""Diagnostics of the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_NUMBER, CONF_STREET, CONF_SYMBOL
from .coordinator import PreZeroConfigEntry

TO_REDACT = {CONF_STREET, CONF_NUMBER, CONF_SYMBOL, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PreZeroConfigEntry
) -> dict[str, Any]:
    """Return diagnostics of a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "failures": coordinator.failures,
            "update_interval": str(coordinator.update_interval),
            "refresh_interval": str(coordinator.refresh_interval),
        },
        "data": {
            "last_success": data.last_success.isoformat()
            if data.last_success
            else None,
            "fractions": coordinator.fractions,
            "schedules": {
                year: {
                    "published": schedule.published.isoformat()
                    if schedule.published
                    else None,
                    "collections": len(schedule.collections),
                    "first": schedule.collections[0].date.isoformat()
                    if schedule.collections
                    else None,
                    "last": schedule.collections[-1].date.isoformat()
                    if schedule.collections
                    else None,
                }
                for year, schedule in data.schedules.items()
            },
        }
        if data
        else None,
    }
