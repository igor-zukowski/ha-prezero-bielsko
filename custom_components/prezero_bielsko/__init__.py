"""The PreZero Bielsko-Biała waste collection schedule integration."""

from __future__ import annotations

from datetime import timedelta
import re

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import PreZeroClient
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DAYS,
    DOMAIN,
    ICON_URL,
    ISSUES,
    SERVICE_GET_SCHEDULE,
    STORAGE_VERSION,
)
from .coordinator import PreZeroConfigEntry, PreZeroCoordinator, issue_id, storage_key
from .pictures import default_color, render_svg
from .schedule import upcoming

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

GET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_DAYS, default=30): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=400)
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    hass.http.register_view(FractionPictureView())

    async def _async_get_schedule(call: ServiceCall) -> ServiceResponse:
        """Return upcoming collections of a configured address."""
        entry: PreZeroConfigEntry | None = hass.config_entries.async_get_entry(
            call.data[ATTR_CONFIG_ENTRY_ID]
        )
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_found"
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        coordinator = entry.runtime_data
        today = dt_util.now().date()
        until = today + timedelta(days=call.data[ATTR_DAYS])
        return {
            "address": entry.title,
            "collections": [
                {
                    "date": item.date.isoformat(),
                    "days": (item.date - today).days,
                    "fraction": item.fraction,
                    "name": coordinator.fraction_name(item.fraction),
                }
                for item in upcoming(coordinator.data.collections, today)
                if item.date < until
            ],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        _async_get_schedule,
        schema=GET_SCHEDULE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PreZeroConfigEntry) -> bool:
    """Set up a configured address."""
    coordinator = PreZeroCoordinator(
        hass, entry, PreZeroClient(async_get_clientsession(hass))
    )
    await coordinator.async_setup()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PreZeroConfigEntry) -> bool:
    """Unload a configured address."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PreZeroConfigEntry) -> None:
    """Remove the cache and repair issues of a removed address."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
    for issue in ISSUES:
        ir.async_delete_issue(hass, DOMAIN, issue_id(issue, entry.entry_id))


class FractionPictureView(HomeAssistantView):
    """Serve colored fraction pictures used as entity pictures."""

    url = ICON_URL + "/{fraction}"
    name = f"api:{DOMAIN}:icon"
    requires_auth = False

    _FRACTION_RE = re.compile(r"([a-z0-9]{1,32})\.svg")

    async def get(self, request: web.Request, fraction: str) -> web.Response:
        """Return the SVG picture of a fraction."""
        if (match := self._FRACTION_RE.fullmatch(fraction)) is None:
            return web.Response(status=404)
        key = match.group(1)
        svg = render_svg(key, request.query.get("color", default_color(key)))
        return web.Response(
            text=svg,
            content_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=604800"},
        )
