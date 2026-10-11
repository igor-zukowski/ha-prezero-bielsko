"""Sensors of the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import PreZeroConfigEntry, PreZeroCoordinator
from .entity import PreZeroEntity, PreZeroFractionEntity, async_track_new_fractions
from .schedule import next_collection, upcoming

PARALLEL_UPDATES = 0

UPCOMING_COUNT = 3


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PreZeroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            NextCollectionSensor(coordinator),
            LastUpdateSensor(coordinator),
            PublishedSensor(coordinator),
        ]
    )
    async_track_new_fractions(
        entry,
        lambda fractions: async_add_entities(
            FractionDaysSensor(coordinator, fraction) for fraction in fractions
        ),
    )


class FractionDaysSensor(PreZeroFractionEntity, SensorEntity):
    """Days until the next collection of a fraction."""

    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_suggested_display_precision = 0
    _unrecorded_attributes = frozenset({"next_date", "upcoming", "color", "fraction"})

    def __init__(self, coordinator: PreZeroCoordinator, fraction: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, fraction)

    @property
    def native_value(self) -> int | None:
        """Return the number of days until the next collection."""
        today = dt_util.now().date()
        items = upcoming(self.coordinator.data.collections, today, self.fraction)
        return (items[0].date - today).days if items else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the next collection dates."""
        items = upcoming(
            self.coordinator.data.collections, dt_util.now().date(), self.fraction
        )
        return {
            "fraction": self.coordinator.fraction_name(self.fraction),
            "next_date": items[0].date.isoformat() if items else None,
            "upcoming": [item.date.isoformat() for item in items[:UPCOMING_COUNT]],
            "color": self.coordinator.fraction_color(self.fraction),
        }


class NextCollectionSensor(PreZeroEntity, SensorEntity):
    """Date of the nearest collection of any fraction."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "next_collection"
    _unrecorded_attributes = frozenset(
        {"fractions", "fraction_keys", "days", "pdf_url"}
    )

    def __init__(self, coordinator: PreZeroCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "next_collection")

    @property
    def native_value(self) -> date | None:
        """Return the nearest collection date."""
        nearest = next_collection(
            self.coordinator.data.collections, dt_util.now().date()
        )
        return nearest[0] if nearest else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return fractions collected on the nearest collection day."""
        today = dt_util.now().date()
        nearest = next_collection(self.coordinator.data.collections, today)
        fractions = nearest[1] if nearest else []
        return {
            "fractions": [self.coordinator.fraction_name(item) for item in fractions],
            "fraction_keys": fractions,
            "days": (nearest[0] - today).days if nearest else None,
            "pdf_url": self.coordinator.pdf_url,
        }


class LastUpdateSensor(PreZeroEntity, SensorEntity):
    """Time of the last successful download."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_update"

    def __init__(self, coordinator: PreZeroCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "last_update")

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last successful download."""
        return self.coordinator.data.last_success


class PublishedSensor(PreZeroEntity, SensorEntity):
    """Publication time of the current schedule reported by the service."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "published"

    def __init__(self, coordinator: PreZeroCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "published")

    @property
    def native_value(self) -> datetime | None:
        """Return the publication time of the current schedule."""
        schedule = self.coordinator.current_schedule
        return schedule.published if schedule else None
