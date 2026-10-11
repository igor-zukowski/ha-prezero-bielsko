"""Config flow of the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    ColorRGBSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import PreZeroClient, PreZeroConnectionError, PreZeroError
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
    DOMAIN,
    FRACTIONS,
    LANGUAGES,
    MAX_REMINDER_DAYS,
    REFRESH_INTERVALS,
    SECTION_APPEARANCE,
    SECTION_REFRESH,
    SECTION_REMINDERS,
)
from .coordinator import PreZeroConfigEntry
from .models import Customer
from .pictures import hex_to_rgb


def _normalize(value: str) -> str:
    """Normalize a value for case and whitespace insensitive comparison."""
    return " ".join(value.split()).casefold()


def _match(value: str, choices: list[str]) -> str | None:
    """Return the choice matching a typed or selected value."""
    wanted = _normalize(value)
    return next((choice for choice in choices if _normalize(choice) == wanted), None)


def _language_selector() -> SelectSelector:
    """Return the selector of the entity language."""
    return SelectSelector(
        SelectSelectorConfig(
            options=list(LANGUAGES),
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=CONF_LANGUAGE,
        )
    )


def _error_key(err: PreZeroError) -> str:
    """Return the form error of a client error."""
    return (
        "cannot_connect"
        if isinstance(err, PreZeroConnectionError)
        else "invalid_response"
    )


class PreZeroConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure an address."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._client: PreZeroClient | None = None
        self._year = dt_util.now().year
        self._streets: list[str] = []
        self._street = ""
        self._numbers: list[str] = []
        self._number = ""
        self._customers: list[Customer] = []
        self._language = DEFAULT_LANGUAGE

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: PreZeroConfigEntry) -> PreZeroOptionsFlow:
        """Return the options flow."""
        return PreZeroOptionsFlow()

    @property
    def client(self) -> PreZeroClient:
        """Return the service client."""
        if self._client is None:
            self._client = PreZeroClient(async_get_clientsession(self.hass))
        return self._client

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the street."""
        return await self._async_step_street("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a new street of a configured address."""
        return await self._async_step_street("reconfigure", user_input)

    async def _async_step_street(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Select the street."""
        errors: dict[str, str] = {}
        if not self._streets:
            try:
                self._streets = await self.client.async_get_streets(self._year)
            except PreZeroError as err:
                errors["base"] = _error_key(err)
            else:
                if not self._streets:
                    errors["base"] = "invalid_response"

        if user_input is not None and not errors:
            self._language = user_input.get(CONF_LANGUAGE, self._language)
            street = _match(user_input.get(CONF_STREET, ""), self._streets)
            if street is None:
                errors[CONF_STREET] = "invalid_street"
            else:
                if street != self._street:
                    self._numbers = []
                self._street = street
                return await self.async_step_number()

        suggested = self._street
        if not suggested and self.source == SOURCE_RECONFIGURE:
            suggested = self._get_reconfigure_entry().data[CONF_STREET]
        street_selector: SelectSelector | TextSelector = (
            SelectSelector(
                SelectSelectorConfig(
                    options=self._streets,
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                    sort=False,
                )
            )
            if self._streets
            else TextSelector()
        )
        # Optional, so the frontend does not preselect the first street;
        # an empty value is rejected above.
        fields: dict[Any, Any] = {vol.Optional(CONF_STREET): street_selector}
        if step_id == "user":
            # Reconfiguring keeps the language, it can be changed in the options.
            fields[vol.Required(CONF_LANGUAGE, default=self._language)] = (
                _language_selector()
            )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), {CONF_STREET: suggested} if suggested else {}
            ),
            errors=errors,
        )

    async def async_step_number(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the house number."""
        errors: dict[str, str] = {}
        if not self._numbers:
            try:
                self._numbers = await self.client.async_get_numbers(
                    self._street, self._year
                )
            except PreZeroError as err:
                errors["base"] = _error_key(err)
            else:
                if not self._numbers:
                    errors["base"] = "no_numbers"

        if user_input is not None and not errors:
            number = _match(user_input.get(CONF_NUMBER, ""), self._numbers)
            if number is None:
                errors[CONF_NUMBER] = "invalid_number"
            else:
                self._number = number
                try:
                    customers = await self.client.async_get_customers(
                        self._street, number, self._year
                    )
                except PreZeroError as err:
                    errors["base"] = _error_key(err)
                else:
                    if not customers:
                        errors["base"] = "no_customer"
                    elif len(customers) > 1:
                        self._customers = customers
                        return await self.async_step_customer()
                    elif (error := await self._async_validate(customers[0])) is None:
                        return await self._async_finish(customers[0])
                    else:
                        errors["base"] = error

        suggested = self._number
        if not suggested and self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            if entry.data[CONF_STREET] == self._street:
                suggested = entry.data[CONF_NUMBER]
        schema = vol.Schema(
            {
                vol.Optional(CONF_NUMBER): SelectSelector(
                    SelectSelectorConfig(
                        options=self._numbers,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                        sort=False,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="number",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_NUMBER: suggested} if suggested else {}
            ),
            errors=errors,
            description_placeholders={"street": self._street.title()},
        )

    async def async_step_customer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select one of multiple schedules assigned to the address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # The selector only accepts listed symbols.
            customer = next(
                item
                for item in self._customers
                if item.symbol == user_input[CONF_SYMBOL]
            )
            if (error := await self._async_validate(customer)) is None:
                return await self._async_finish(customer)
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_SYMBOL): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=item.symbol, label=item.symbol)
                            for item in self._customers
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="customer",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "address": f"{self._street.title()} {self._number}"
            },
        )

    async def _async_validate(self, customer: Customer) -> str | None:
        """Check that a schedule exists, return a form error otherwise."""
        try:
            schedule = await self.client.async_get_schedule(customer.symbol, self._year)
        except PreZeroError as err:
            return _error_key(err)
        return None if schedule.collections else "no_schedule"

    async def _async_finish(self, customer: Customer) -> ConfigFlowResult:
        """Create or update the config entry."""
        unique_id = _normalize(f"{self._street}|{self._number}|{customer.key}")
        title = f"{self._street.title()} {self._number}"
        data = {
            CONF_STREET: self._street,
            CONF_NUMBER: self._number,
            CONF_SYMBOL: customer.symbol,
        }
        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            if unique_id != entry.unique_id:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
            return self.async_update_reload_and_abort(
                entry, unique_id=unique_id, title=title, data=data
            )
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=title, data=data, options={CONF_LANGUAGE: self._language}
        )


class PreZeroOptionsFlow(OptionsFlowWithReload):
    """Configure refreshing, reminders and appearance."""

    def _fractions(self) -> list[str]:
        """Return configurable fractions, preferring those of this address."""
        entry: PreZeroConfigEntry = self.config_entry
        if entry.state is ConfigEntryState.LOADED:
            present = [key for key in entry.runtime_data.fractions if key in FRACTIONS]
            if present:
                return present
        return list(FRACTIONS)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        options = self.config_entry.options
        if user_input is not None:
            reminders = {
                key: int(value) if key.startswith(CONF_DAYS_PREFIX) else value
                for key, value in user_input[SECTION_REMINDERS].items()
            }
            return self.async_create_entry(
                data={
                    CONF_LANGUAGE: user_input[CONF_LANGUAGE],
                    SECTION_REFRESH: user_input[SECTION_REFRESH],
                    SECTION_REMINDERS: {
                        **options.get(SECTION_REMINDERS, {}),
                        **reminders,
                    },
                    SECTION_APPEARANCE: {
                        **options.get(SECTION_APPEARANCE, {}),
                        **user_input[SECTION_APPEARANCE],
                    },
                }
            )

        fractions = self._fractions()
        days_selector = NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=MAX_REMINDER_DAYS,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="d",
            )
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LANGUAGE, default=DEFAULT_LANGUAGE
                ): _language_selector(),
                vol.Required(SECTION_REFRESH): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL
                            ): SelectSelector(
                                SelectSelectorConfig(
                                    options=list(REFRESH_INTERVALS),
                                    mode=SelectSelectorMode.DROPDOWN,
                                    translation_key=CONF_REFRESH_INTERVAL,
                                )
                            )
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_REMINDERS): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_REMINDER_START,
                                default=DEFAULT_REMINDER_START.isoformat(),
                            ): TimeSelector(),
                            vol.Required(
                                CONF_REMINDER_END,
                                default=DEFAULT_REMINDER_END.isoformat(),
                            ): TimeSelector(),
                            **{
                                vol.Required(
                                    f"{CONF_DAYS_PREFIX}{key}",
                                    default=DEFAULT_REMINDER_DAYS,
                                ): days_selector
                                for key in fractions
                            },
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_APPEARANCE): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_COLORED_PICTURES, default=DEFAULT_COLORED_PICTURES
                            ): BooleanSelector(),
                            **{
                                vol.Required(
                                    f"{CONF_COLOR_PREFIX}{key}",
                                    default=hex_to_rgb(FRACTIONS[key].color),
                                ): ColorRGBSelector()
                                for key in fractions
                            },
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, options),
        )
