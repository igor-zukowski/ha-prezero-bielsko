"""Binary sensors of the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .coordinator import PreZeroConfigEntry, PreZeroCoordinator
from .entity import PreZeroEntity, PreZeroFractionEntity, async_track_new_fractions
from .schedule import ReminderState

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PreZeroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [AnyReminderBinarySensor(coordinator), ProblemBinarySensor(coordinator)]
    )
    async_track_new_fractions(
        entry,
        lambda fractions: async_add_entities(
            ReminderBinarySensor(coordinator, fraction) for fraction in fractions
        ),
    )


class _ReminderEntity(PreZeroEntity, BinarySensorEntity):
    """Recalculate the state exactly when a reminder window starts or ends."""

    _unsub_timer: CALLBACK_TYPE | None = None

    def _calculate(self, now: datetime) -> ReminderState:
        """Return the reminder state at ``now``."""
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        """Start tracking reminder windows."""
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_timer)
        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Recalculate the state when data or the date changes."""
        self._update_state()
        super()._handle_coordinator_update()

    @callback
    def _cancel_timer(self) -> None:
        """Cancel the scheduled state change."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _update_state(self) -> None:
        """Calculate the state and schedule the next change."""
        self._cancel_timer()
        state = self._calculate(dt_util.now())
        self._apply(state)
        if state.next_change is not None:
            self._unsub_timer = async_track_point_in_utc_time(
                self.hass, self._async_timer_fired, dt_util.as_utc(state.next_change)
            )

    def _apply(self, state: ReminderState) -> None:
        """Apply a calculated state to the entity."""
        raise NotImplementedError

    @callback
    def _async_timer_fired(self, _now: datetime) -> None:
        """Handle a reminder window boundary."""
        self._unsub_timer = None
        self._update_state()
        self.async_write_ha_state()


class ReminderBinarySensor(PreZeroFractionEntity, _ReminderEntity):
    """Reminder of an upcoming collection of a fraction."""

    _unrecorded_attributes = frozenset({"collection_date", "days_before", "fraction"})
    _collection_date: date | None = None

    def __init__(self, coordinator: PreZeroCoordinator, fraction: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, fraction, "_reminder")

    def _calculate(self, now: datetime) -> ReminderState:
        return self.coordinator.reminder_state(self.fraction, now)

    def _apply(self, state: ReminderState) -> None:
        self._attr_is_on = state.is_on
        # The colored fraction picture marks an active reminder, the bell icon
        # is shown otherwise.
        self._attr_entity_picture = (
            self.coordinator.fraction_picture(self.fraction) if state.is_on else None
        )
        self._collection_date = (
            state.collection_dates[0] if state.collection_dates else None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the collection the reminder refers to."""
        return {
            "fraction": self.coordinator.fraction_name(self.fraction),
            "collection_date": self._collection_date.isoformat()
            if self._collection_date
            else None,
            "days_before": self.coordinator.reminder_days(self.fraction),
        }


class AnyReminderBinarySensor(_ReminderEntity):
    """On when a reminder of any fraction is active."""

    _attr_translation_key = "reminder"
    _unrecorded_attributes = frozenset(
        {"fractions", "fraction_keys", "collection_date"}
    )
    _active: list[tuple[str, date]]

    def __init__(self, coordinator: PreZeroCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "reminder")
        self._active = []

    def _calculate(self, now: datetime) -> ReminderState:
        coordinator = self.coordinator
        states = {
            fraction: coordinator.reminder_state(fraction, now)
            for fraction in coordinator.fractions
        }
        self._active = sorted(
            (
                (fraction, state.collection_dates[0])
                for fraction, state in states.items()
                if state.is_on
            ),
            key=lambda item: (item[1], item[0]),
        )
        changes = [state.next_change for state in states.values() if state.next_change]
        return ReminderState(
            bool(self._active),
            tuple(day for _, day in self._active),
            min(changes) if changes else None,
        )

    def _apply(self, state: ReminderState) -> None:
        self._attr_is_on = state.is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the fractions with an active reminder."""
        return {
            "fractions": [
                self.coordinator.fraction_name(fraction) for fraction, _ in self._active
            ],
            "fraction_keys": [fraction for fraction, _ in self._active],
            "collection_date": self._active[0][1].isoformat() if self._active else None,
        }


class ProblemBinarySensor(PreZeroEntity, BinarySensorEntity):
    """On when the last schedule download failed."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "update_problem"
    _unrecorded_attributes = frozenset({"error", "failures"})

    def __init__(self, coordinator: PreZeroCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, "update_problem")

    @property
    def available(self) -> bool:
        """Always report the download status."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the last download failed."""
        return not self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the last error."""
        error = self.coordinator.last_exception
        return {
            "error": str(error) if error and self.is_on else None,
            "failures": self.coordinator.failures,
        }
