"""Base entity of the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.typing import UndefinedType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FRACTIONS, SCHEDULE_URL
from .coordinator import PreZeroConfigEntry, PreZeroCoordinator


class PreZeroEntity(CoordinatorEntity[PreZeroCoordinator]):
    """Entity bound to one configured address."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PreZeroCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            model=coordinator.device_model,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=SCHEDULE_URL,
        )

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name in the language configured for the integration."""
        if (
            self.platform_data
            and self.translation_key
            and (
                name := self.coordinator.entity_name(
                    self.platform_data.domain,
                    self.translation_key,
                    self.translation_placeholders,
                )
            )
        ):
            return name
        return super().name

    @property
    def available(self) -> bool:
        """Stay available with cached data when a download fails."""
        return self.coordinator.data is not None


class PreZeroFractionEntity(PreZeroEntity):
    """Entity bound to one waste fraction."""

    def __init__(
        self, coordinator: PreZeroCoordinator, fraction: str, key_suffix: str = ""
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, f"{fraction}{key_suffix}")
        self.fraction = fraction
        prefix = key_suffix.strip("_")
        if fraction in FRACTIONS:
            self._attr_translation_key = f"{prefix}_{fraction}" if prefix else fraction
        else:
            self._attr_translation_key = f"{prefix}_other" if prefix else "other"
            self._attr_translation_placeholders = {"fraction": fraction.capitalize()}
        self._attr_entity_picture = coordinator.fraction_picture(fraction)


@callback
def async_track_new_fractions(
    entry: PreZeroConfigEntry,
    add_entities: Callable[[list[str]], None],
) -> None:
    """Call ``add_entities`` with fractions not seen before, now and on updates."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _check() -> None:
        new = [fraction for fraction in coordinator.fractions if fraction not in known]
        if new:
            known.update(new)
            add_entities(new)

    _check()
    entry.async_on_unload(coordinator.async_add_listener(_check))
