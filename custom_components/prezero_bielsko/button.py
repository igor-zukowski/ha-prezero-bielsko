"""Buttons of the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import PreZeroConfigEntry, PreZeroCoordinator
from .entity import PreZeroEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PreZeroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    async_add_entities([RefreshButton(entry.runtime_data)])


class RefreshButton(PreZeroEntity, ButtonEntity):
    """Download the latest schedule now."""

    _attr_translation_key = "refresh"

    def __init__(self, coordinator: PreZeroCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "refresh")

    @property
    def available(self) -> bool:
        """Allow refreshing also when there is no data."""
        return True

    async def async_press(self) -> None:
        """Download the schedule."""
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success:
            error = self.coordinator.last_exception
            # Report the client error, not the translated update failure.
            cause = error.__cause__ if error and error.__cause__ else error
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_failed",
                translation_placeholders={"error": str(cause or "")},
            )
