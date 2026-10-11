"""Tests of the config and options flows."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.prezero_bielsko.api import (
    PreZeroConnectionError,
    PreZeroResponseError,
)
from custom_components.prezero_bielsko.const import (
    CONF_COLORED_PICTURES,
    CONF_NUMBER,
    CONF_REFRESH_INTERVAL,
    CONF_REMINDER_END,
    CONF_REMINDER_START,
    CONF_STREET,
    CONF_SYMBOL,
    DOMAIN,
    SECTION_APPEARANCE,
    SECTION_REFRESH,
    SECTION_REMINDERS,
)

from .conftest import NUMBER, STREET, SYMBOL, FakeClient


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_full_flow(hass: HomeAssistant, client: FakeClient, now) -> None:
    """A single schedule address is configured in two steps."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: "  testowa "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "number"
    assert result["description_placeholders"] == {"street": "Testowa"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Testowa 1"
    assert result["data"] == {
        CONF_STREET: STREET,
        CONF_NUMBER: NUMBER,
        CONF_SYMBOL: SYMBOL,
    }
    assert result["result"].unique_id == "testowa|1|10000001"
    assert client.calls_of("schedule")[0] == ("schedule", SYMBOL, 2026)


async def test_multiple_schedules(hass: HomeAssistant, client: FakeClient, now) -> None:
    """An address with multiple schedules asks for the symbol."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: "2a"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "customer"
    assert result["description_placeholders"] == {"address": "Testowa 2A"}

    client.schedules.pop(("BBA/10000003", 2026))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYMBOL: "BBA/10000003"}
    )
    assert result["errors"] == {"base": "no_schedule"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYMBOL: "BBA/10000002"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SYMBOL] == "BBA/10000002"
    assert result["result"].unique_id == "testowa|2a|10000002"


async def test_invalid_street_and_number(
    hass: HomeAssistant, client: FakeClient, now
) -> None:
    """Values not on the lists are rejected."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: "Nieistniejąca"}
    )
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_STREET: "invalid_street"}

    # Fields are not preselected, an empty submission is rejected.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {CONF_STREET: "invalid_street"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: "999"}
    )
    assert result["step_id"] == "number"
    assert result["errors"] == {CONF_NUMBER: "invalid_number"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {CONF_NUMBER: "invalid_number"}


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (PreZeroConnectionError("down"), "cannot_connect"),
        (PreZeroResponseError("changed"), "invalid_response"),
    ],
)
async def test_streets_error_recovers(
    hass: HomeAssistant, client: FakeClient, now, error: Exception, key: str
) -> None:
    """A failed street download shows an error and can be retried."""
    client.error = error
    result = await _start(hass)
    assert result["errors"] == {"base": key}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    assert result["errors"] == {"base": key}

    client.error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    assert result["step_id"] == "number"


async def test_empty_street_list(hass: HomeAssistant, client: FakeClient, now) -> None:
    """An empty street list is reported as an invalid response."""
    client.streets = []
    result = await _start(hass)
    assert result["errors"] == {"base": "invalid_response"}


async def test_number_step_errors(hass: HomeAssistant, client: FakeClient, now) -> None:
    """Errors of the number step are shown on the number form."""
    result = await _start(hass)
    client.numbers["1 MAJA"] = []
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: "1 maja"}
    )
    assert result["step_id"] == "number"
    assert result["errors"] == {"base": "no_numbers"}

    # Going back to a street is not possible, start a new flow instead.
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    client.error = PreZeroConnectionError("down")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    client.error = None
    client.customers[(STREET, NUMBER)] = []
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["errors"] == {"base": "no_customer"}

    client.customers[(STREET, NUMBER)] = FakeClient().customers[(STREET, NUMBER)]
    client.schedules.pop((SYMBOL, 2026))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["errors"] == {"base": "no_schedule"}


async def test_numbers_download_error(
    hass: HomeAssistant, client: FakeClient, now
) -> None:
    """A failed number download is retried on submit."""
    result = await _start(hass)
    client.error = PreZeroResponseError("changed")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    assert result["errors"] == {"base": "invalid_response"}
    client.error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_schedule_validation_error(
    hass: HomeAssistant, client: FakeClient, now
) -> None:
    """A failed schedule download shows an error."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    original = client.async_get_schedule

    async def failing(symbol: str, year: int):
        raise PreZeroConnectionError("down")

    client.async_get_schedule = failing  # type: ignore[method-assign]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    client.async_get_schedule = original  # type: ignore[method-assign]


async def test_already_configured(
    hass: HomeAssistant, client: FakeClient, config_entry: MockConfigEntry, now
) -> None:
    """The same address cannot be added twice."""
    config_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant, client: FakeClient, init_integration: MockConfigEntry
) -> None:
    """The address can be changed keeping the entry."""
    entry = init_integration
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    assert schema_keys[CONF_STREET].description == {"suggested_value": STREET}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET}
    )
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    assert schema_keys[CONF_NUMBER].description == {"suggested_value": NUMBER}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "testowa|1|10000001"

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: "1 MAJA"}
    )
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    assert schema_keys[CONF_NUMBER].description is None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: "5"}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.unique_id == "1 maja|5|10000005"
    assert entry.title == "1 Maja 5"
    assert entry.data == {
        CONF_STREET: "1 MAJA",
        CONF_NUMBER: "5",
        CONF_SYMBOL: "BBA/10000005",
    }


async def test_reconfigure_to_existing_address(
    hass: HomeAssistant, client: FakeClient, init_integration: MockConfigEntry
) -> None:
    """Reconfiguring to an address of another entry is rejected."""
    MockConfigEntry(domain=DOMAIN, unique_id="1 maja|5|10000005").add_to_hass(hass)
    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: "1 MAJA"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: "5"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(
    hass: HomeAssistant, client: FakeClient, init_integration: MockConfigEntry
) -> None:
    """Options are stored in sections and reload the entry."""
    entry = init_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    sections = {str(key): value for key, value in result["data_schema"].schema.items()}
    reminder_fields = {str(key) for key in sections[SECTION_REMINDERS].schema.schema}
    # Only fractions of this address are offered (all eight in the sample).
    assert "days_makulatura" in reminder_fields
    assert len([key for key in reminder_fields if key.startswith("days_")]) == 8

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            SECTION_REFRESH: {CONF_REFRESH_INTERVAL: "weekly"},
            SECTION_REMINDERS: {
                CONF_REMINDER_START: "19:30:00",
                CONF_REMINDER_END: "08:00:00",
                "days_makulatura": 2.0,
            },
            SECTION_APPEARANCE: {
                CONF_COLORED_PICTURES: False,
                "color_makulatura": [0, 0, 255],
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[SECTION_REMINDERS]["days_makulatura"] == 2
    assert isinstance(entry.options[SECTION_REMINDERS]["days_makulatura"], int)
    coordinator = entry.runtime_data
    assert coordinator.refresh_interval.days == 7
    assert coordinator.reminder_days("makulatura") == 2
    assert coordinator.reminder_days("szklo") == 1
    assert coordinator.reminder_start.hour == 19
    assert coordinator.fraction_color("makulatura") == "#0000FF"
    assert coordinator.fraction_picture("makulatura") is None


async def test_options_flow_entry_not_loaded(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """All fractions are offered when the entry is not loaded."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    sections = {str(key): value for key, value in result["data_schema"].schema.items()}
    fields = {str(key) for key in sections[SECTION_APPEARANCE].schema.schema}
    assert len([key for key in fields if key.startswith("color_")]) == 8
