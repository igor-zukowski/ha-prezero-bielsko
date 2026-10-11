"""Calendar of the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import PreZeroConfigEntry, PreZeroCoordinator
from .entity import PreZeroEntity
from .models import Collection
from .schedule import upcoming

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PreZeroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar."""
    async_add_entities([PreZeroCalendar(entry.runtime_data)])


class PreZeroCalendar(PreZeroEntity, CalendarEntity):
    """All day events of waste collections."""

    _attr_translation_key = "schedule"

    def __init__(self, coordinator: PreZeroCoordinator) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator, "calendar")

    def _event(self, item: Collection) -> CalendarEvent:
        """Return the calendar event of a collection."""
        return CalendarEvent(
            start=item.date,
            end=item.date + timedelta(days=1),
            summary=self.coordinator.fraction_name(item.fraction),
            location=self.coordinator.config_entry.title,
            uid=f"{self.coordinator.config_entry.entry_id}_{item.date.isoformat()}_{item.fraction}",
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next collection."""
        items = upcoming(self.coordinator.data.collections, dt_util.now().date())
        return self._event(items[0]) if items else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return collections in a time range."""
        return [
            self._event(item)
            for item in self.coordinator.data.collections
            if dt_util.start_of_local_day(item.date) < end_date
            and dt_util.start_of_local_day(item.date + timedelta(days=1)) > start_date
        ]
