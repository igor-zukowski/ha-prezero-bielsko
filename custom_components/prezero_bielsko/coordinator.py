"""Data update coordinator of the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PreZeroAddressNotFoundError,
    PreZeroClient,
    PreZeroError,
    select_customer,
)
from .const import (
    CONF_COLOR_PREFIX,
    CONF_COLORED_PICTURES,
    CONF_DAYS_PREFIX,
    CONF_LANGUAGE,
    CONF_NUMBER,
    CONF_REFRESH_INTERVAL,
    CONF_REMINDER_END,
    CONF_REMINDER_START,
    CONF_STREET,
    CONF_SYMBOL,
    DEFAULT_COLORED_PICTURES,
    DEFAULT_LANGUAGE,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_REMINDER_END,
    DEFAULT_REMINDER_START,
    DEVICE_MODELS,
    DOMAIN,
    EVENT_SCHEDULE_UPDATED,
    FETCH_FAILED_ISSUE_AFTER,
    FETCH_FAILED_ISSUE_MIN_FAILURES,
    FRACTIONS,
    ICON_URL,
    ISSUE_ADDRESS_NOT_FOUND,
    ISSUE_FETCH_FAILED,
    ISSUE_SCHEDULE_MISSING,
    LANGUAGE_AUTO,
    MAX_REMINDER_DAYS,
    REFRESH_INTERVALS,
    RETRY_DELAYS,
    SCHEDULE_URL,
    SECTION_APPEARANCE,
    SECTION_REFRESH,
    SECTION_REMINDERS,
    STORAGE_VERSION,
)
from .models import Collection, Schedule, ScheduleData, symbol_key
from .pictures import default_color, normalize_color
from .schedule import ReminderState, reminder_state

_LOGGER = logging.getLogger(__name__)

type PreZeroConfigEntry = ConfigEntry[PreZeroCoordinator]


def storage_key(entry_id: str) -> str:
    """Return the storage key of a config entry."""
    return f"{DOMAIN}.{entry_id}"


def issue_id(issue: str, entry_id: str) -> str:
    """Return the repair issue id of a config entry."""
    return f"{issue}_{entry_id}"


def _parse_time(value: Any, default: time) -> time:
    """Parse a time option."""
    if isinstance(value, str) and (parsed := dt_util.parse_time(value)) is not None:
        return parsed
    return default


class PreZeroCoordinator(DataUpdateCoordinator[ScheduleData]):
    """Download the schedule, keep a persistent cache and track problems."""

    config_entry: PreZeroConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: PreZeroConfigEntry, client: PreZeroClient
    ) -> None:
        """Initialize the coordinator."""
        options = entry.options
        refresh = options.get(SECTION_REFRESH, {})
        reminders = options.get(SECTION_REMINDERS, {})
        appearance = options.get(SECTION_APPEARANCE, {})

        self.refresh_interval = REFRESH_INTERVALS.get(
            refresh.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            REFRESH_INTERVALS[DEFAULT_REFRESH_INTERVAL],
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=self.refresh_interval,
            always_update=False,
        )
        self.client = client
        self.street: str = entry.data[CONF_STREET]
        self.number: str = entry.data[CONF_NUMBER]
        self.symbol_key = symbol_key(entry.data[CONF_SYMBOL])
        self.reminder_start = _parse_time(
            reminders.get(CONF_REMINDER_START), DEFAULT_REMINDER_START
        )
        self.reminder_end = _parse_time(
            reminders.get(CONF_REMINDER_END), DEFAULT_REMINDER_END
        )
        self._reminder_days: dict[str, int] = {
            key.removeprefix(CONF_DAYS_PREFIX): max(
                0, min(MAX_REMINDER_DAYS, int(value))
            )
            for key, value in reminders.items()
            if key.startswith(CONF_DAYS_PREFIX) and isinstance(value, (int, float))
        }
        self.colored_pictures: bool = appearance.get(
            CONF_COLORED_PICTURES, DEFAULT_COLORED_PICTURES
        )
        self._colors: dict[str, Any] = {
            key.removeprefix(CONF_COLOR_PREFIX): value
            for key, value in appearance.items()
            if key.startswith(CONF_COLOR_PREFIX)
        }
        self.failures = 0
        self._failing_since: datetime | None = None
        self._next_year_attempt: date | None = None
        self._symbols: dict[int, str] = {}
        self.language_option: str = options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        self.language = DEFAULT_LANGUAGE
        self._translations: dict[str, str] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )

    @property
    def address_key(self) -> str:
        """Return a key identifying the configured address."""
        return f"{self.street}|{self.number}|{self.symbol_key}"

    @property
    def fractions(self) -> list[str]:
        """Return fractions present in the schedule, known ones first."""
        present = (
            {item.fraction for item in self.data.collections} if self.data else set()
        )
        known = [key for key in FRACTIONS if key in present]
        return known + sorted(present - set(FRACTIONS))

    @property
    def current_schedule(self) -> Schedule | None:
        """Return the schedule of the current year."""
        if self.data is None:
            return None
        return self.data.schedules.get(dt_util.now().year)

    @property
    def pdf_url(self) -> str | None:
        """Return the URL of the printable schedule of the current year."""
        if (schedule := self.current_schedule) is None:
            return None
        return self.client.pdf_url(schedule.symbol, schedule.year)

    @property
    def device_model(self) -> str:
        """Return the device model in the configured language."""
        return DEVICE_MODELS.get(self.language.split("-")[0], DEVICE_MODELS["en"])

    def entity_name(
        self, domain: str, key: str, placeholders: Mapping[str, str] | None = None
    ) -> str | None:
        """Return an entity name in the configured language."""
        name = self._translations.get(f"component.{DOMAIN}.entity.{domain}.{key}.name")
        if name is None:
            return None
        for placeholder, value in (placeholders or {}).items():
            name = name.replace(f"{{{placeholder}}}", value)
        return name

    def fraction_name(self, fraction: str) -> str:
        """Return the name of a fraction in the configured language."""
        name = self.entity_name("sensor", fraction) if fraction in FRACTIONS else None
        return name or fraction.capitalize()

    def fraction_color(self, fraction: str) -> str:
        """Return the configured color of a fraction."""
        default = default_color(fraction)
        return normalize_color(self._colors.get(fraction), default)

    def fraction_picture(self, fraction: str) -> str | None:
        """Return the URL of the colored picture of a fraction."""
        if not self.colored_pictures:
            return None
        color = self.fraction_color(fraction).lstrip("#")
        safe = "".join(char for char in fraction if char.isascii() and char.isalnum())
        return f"{ICON_URL}/{safe or 'unknown'}.svg?color={color}"

    def reminder_days(self, fraction: str) -> int:
        """Return how many days before a collection its reminder starts."""
        return self._reminder_days.get(fraction, DEFAULT_REMINDER_DAYS)

    def reminder_state(self, fraction: str, now: datetime) -> ReminderState:
        """Return the reminder state of a fraction at ``now``."""
        collections = self.data.collections if self.data else ()
        return reminder_state(
            (item.date for item in collections if item.fraction == fraction),
            now,
            days_before=self.reminder_days(fraction),
            start=self.reminder_start,
            end=self.reminder_end,
            time_zone=dt_util.get_default_time_zone(),
        )

    async def async_setup(self) -> None:
        """Restore the cache and load the initial data.

        Raises ConfigEntryNotReady when there is neither a cache nor a connection.
        """
        await self._async_load_translations()
        self._symbols[dt_util.now().year] = self.config_entry.data[CONF_SYMBOL]
        cached = await self._async_restore()
        if cached is None:
            await self.async_config_entry_first_refresh()
        else:
            self.data = cached
            now = dt_util.utcnow()
            if self._needs_refresh(cached, now):
                await self.async_refresh()
            else:
                age = now - (cached.last_success or now)
                self.update_interval = max(
                    self.refresh_interval - age, timedelta(minutes=1)
                )
        self.config_entry.async_on_unload(
            async_track_time_change(
                self.hass, self._async_day_changed, hour=0, minute=0, second=5
            )
        )

    async def _async_load_translations(self) -> None:
        """Load entity translations of the configured language.

        Names follow the language chosen in the options, independent of the
        Home Assistant language, unless the Home Assistant language is chosen.
        """
        self.language = (
            self.hass.config.language
            if self.language_option == LANGUAGE_AUTO
            else self.language_option
        )
        self._translations = await async_get_translations(
            self.hass, self.language, "entity", {DOMAIN}
        )

    async def _async_restore(self) -> ScheduleData | None:
        """Restore cached data of the configured address."""
        try:
            stored = await self._store.async_load()
            if not stored or stored.get("address") != self.address_key:
                return None
            data = ScheduleData.from_dict(stored["data"])
            self._symbols.update(
                {int(year): str(symbol) for year, symbol in stored["symbols"].items()}
            )
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            _LOGGER.warning("Ignoring invalid cached schedule: %s", err)
            return None
        if data.last_success is None:
            return None
        return data

    def _needs_refresh(self, data: ScheduleData, now: datetime) -> bool:
        """Return whether cached data should be refreshed right away."""
        today = dt_util.as_local(now).date()
        if (
            data.last_success is None
            or now - data.last_success >= self.refresh_interval
        ):
            return True
        if today.year not in data.schedules:
            return True
        return (
            today.month == 12
            and today.year + 1 not in data.schedules
            and self._next_year_attempt != today
        )

    @callback
    def _async_day_changed(self, now: datetime) -> None:
        """Update date based states and handle the year change."""
        self.async_update_listeners()
        if self.data is None or not self.last_update_success:
            return
        if self._needs_refresh(self.data, dt_util.as_utc(now)):
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), f"{DOMAIN} day change refresh"
            )

    async def _async_update_data(self) -> ScheduleData:
        """Download the schedule."""
        previous = self.data
        try:
            data = await self._async_fetch()
        except PreZeroError as err:
            self._handle_failure(err)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err

        self.failures = 0
        self._failing_since = None
        self.update_interval = self.refresh_interval
        self._delete_issue(ISSUE_FETCH_FAILED)
        self._delete_issue(ISSUE_ADDRESS_NOT_FOUND)
        await self._store.async_save(
            {
                "address": self.address_key,
                "symbols": {
                    str(year): symbol for year, symbol in self._symbols.items()
                },
                "data": data.as_dict(),
            }
        )
        if previous is not None:
            self._fire_update_event(previous, data)
        return data

    async def _async_fetch(self) -> ScheduleData:
        """Download schedules of the current and, in December, the next year."""
        today = dt_util.now().date()
        schedules = {
            year: schedule
            for year, schedule in (self.data.schedules if self.data else {}).items()
            if year > today.year
        }
        current = await self._async_fetch_year(today.year)
        schedules[today.year] = current
        if current.collections:
            self._delete_issue(ISSUE_SCHEDULE_MISSING)
        else:
            self._create_issue(ISSUE_SCHEDULE_MISSING, ir.IssueSeverity.WARNING)

        if today.month == 12:
            self._next_year_attempt = today
            try:
                upcoming = await self._async_fetch_year(today.year + 1)
            except PreZeroError as err:
                _LOGGER.debug(
                    "Schedule of %s is not available: %s", today.year + 1, err
                )
            else:
                if upcoming.collections:
                    schedules[today.year + 1] = upcoming

        return ScheduleData(
            schedules=dict(sorted(schedules.items())), last_success=dt_util.utcnow()
        )

    async def _async_fetch_year(self, year: int) -> Schedule:
        """Download the schedule of one year, resolving the symbol when needed."""
        symbol = self._symbols.get(year)
        schedule: Schedule | None = None
        if symbol:
            schedule = await self.client.async_get_schedule(symbol, year)
            if schedule.collections:
                return schedule

        customers = await self.client.async_get_customers(
            self.street, self.number, year
        )
        customer = select_customer(customers, self.symbol_key)
        if customer is None:
            if year == dt_util.now().year:
                self._create_issue(ISSUE_ADDRESS_NOT_FOUND, ir.IssueSeverity.ERROR)
            raise PreZeroAddressNotFoundError(
                f"No schedule symbol found for the configured address in {year}"
            )
        if schedule is not None and customer.symbol == symbol:
            return schedule
        schedule = await self.client.async_get_schedule(customer.symbol, year)
        self._symbols[year] = customer.symbol
        return schedule

    def _handle_failure(self, err: PreZeroError) -> None:
        """Schedule a retry and raise a repair issue for persistent failures."""
        now = dt_util.utcnow()
        self.failures += 1
        if self._failing_since is None:
            self._failing_since = now
        delay = RETRY_DELAYS[min(self.failures, len(RETRY_DELAYS)) - 1]
        self.update_interval = min(delay, self.refresh_interval)
        if (
            self.failures >= FETCH_FAILED_ISSUE_MIN_FAILURES
            and now - self._failing_since >= FETCH_FAILED_ISSUE_AFTER
        ):
            self._create_issue(
                ISSUE_FETCH_FAILED, ir.IssueSeverity.WARNING, {"error": str(err)}
            )

    def _fire_update_event(self, previous: ScheduleData, data: ScheduleData) -> None:
        """Fire an event when the published schedule has changed."""
        year = dt_util.now().year
        old = previous.schedules.get(year)
        new = data.schedules.get(year)
        if old is None or new is None:
            return
        if old.published == new.published and old.collections == new.collections:
            return
        old_items = set(old.collections)
        new_items = set(new.collections)

        def _serialize(items: set[Collection]) -> list[dict[str, str]]:
            return [
                {"date": item.date.isoformat(), "fraction": item.fraction}
                for item in sorted(items)
            ]

        self.hass.bus.async_fire(
            EVENT_SCHEDULE_UPDATED,
            {
                "config_entry_id": self.config_entry.entry_id,
                "address": self.config_entry.title,
                "year": year,
                "published": new.published.isoformat() if new.published else None,
                "previous_published": old.published.isoformat()
                if old.published
                else None,
                "added": _serialize(new_items - old_items),
                "removed": _serialize(old_items - new_items),
            },
        )

    def _create_issue(
        self,
        issue: str,
        severity: ir.IssueSeverity,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        """Create a repair issue of this config entry."""
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id(issue, self.config_entry.entry_id),
            is_fixable=False,
            severity=severity,
            translation_key=issue,
            translation_placeholders={
                "address": self.config_entry.title,
                "url": SCHEDULE_URL,
                **(placeholders or {}),
            },
        )

    def _delete_issue(self, issue: str) -> None:
        """Delete a repair issue of this config entry."""
        ir.async_delete_issue(
            self.hass, DOMAIN, issue_id(issue, self.config_entry.entry_id)
        )
