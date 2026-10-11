"""Tests of the entity language and device information."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.prezero_bielsko.const import (
    CONF_LANGUAGE,
    CONF_NUMBER,
    CONF_STREET,
    DOMAIN,
)

from .conftest import NUMBER, STREET, SYMBOL, FakeClient, make_schedule


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, language: str | None
) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={} if language is None else {CONF_LANGUAGE: language}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_polish_by_default(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Without a choice entities are Polish, also when Home Assistant is English."""
    assert hass.config.language == "en"
    await _setup(hass, config_entry, None)

    paper = hass.states.get("sensor.testowa_1_papier")
    assert paper.attributes["friendly_name"] == "Testowa 1 Papier"
    assert paper.attributes["fraction"] == "Papier"
    reminder = hass.states.get("binary_sensor.testowa_1_przypomnienie_papier")
    assert reminder.attributes["friendly_name"] == "Testowa 1 Przypomnienie: papier"
    assert hass.states.get("sensor.testowa_1_najblizszy_odbior").attributes[
        "fractions"
    ] == ["Papier", "Szkło"]
    calendar = hass.states.get("calendar.testowa_1_harmonogram_odbioru")
    assert calendar.attributes["message"] == "Papier"
    assert hass.states.get("button.testowa_1_odswiez_harmonogram") is not None
    assert hass.states.get("binary_sensor.testowa_1_problem_z_pobieraniem") is not None

    device = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)[
        0
    ]
    assert device.manufacturer is None
    assert device.model == "Harmonogram odbioru odpadów"
    assert device.name == "Testowa 1"


async def test_english(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
) -> None:
    """English names and device model when English is chosen."""
    await _setup(hass, config_entry, "en")
    assert hass.states.get("sensor.testowa_1_paper").attributes["fraction"] == "Paper"
    device = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)[
        0
    ]
    assert device.manufacturer is None
    assert device.model == "Waste collection schedule"


@pytest.mark.parametrize(
    ("ha_language", "entity_id", "name"),
    [
        ("pl", "sensor.testowa_1_papier", "Papier"),
        ("en", "sensor.testowa_1_paper", "Paper"),
        ("de", "sensor.testowa_1_paper", "Paper"),
    ],
)
async def test_home_assistant_language(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    ha_language: str,
    entity_id: str,
    name: str,
) -> None:
    """The auto option follows Home Assistant, falling back to English."""
    hass.config.language = ha_language
    await _setup(hass, config_entry, "auto")
    assert hass.states.get(entity_id).attributes["fraction"] == name


async def test_language_change_keeps_entity_ids(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
) -> None:
    """Changing the language renames entities without changing their IDs."""
    await _setup(hass, config_entry, "pl")
    hass.config_entries.async_update_entry(config_entry, options={CONF_LANGUAGE: "en"})
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    paper = hass.states.get("sensor.testowa_1_papier")
    assert paper.attributes["friendly_name"] == "Testowa 1 Paper"
    assert entity_registry.async_get("sensor.testowa_1_papier").original_name == "Paper"


async def test_unknown_fraction_polish(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> None:
    """Unknown fractions use the raw name in the Polish templates."""
    client.schedules[(SYMBOL, 2026)] = make_schedule(2026, [("2026-10-20", "elektro")])
    await _setup(hass, config_entry, "pl")
    assert hass.states.get("sensor.testowa_1_elektro").state == "9"
    assert (
        hass.states.get("binary_sensor.testowa_1_przypomnienie_elektro").attributes[
            "friendly_name"
        ]
        == "Testowa 1 Przypomnienie: Elektro"
    )


async def test_language_chosen_in_setup(
    hass: HomeAssistant, client: FakeClient, now: FrozenDateTimeFactory
) -> None:
    """The setup offers the language, stored in the options."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    fields = {str(key): key for key in result["data_schema"].schema}
    assert fields[CONF_LANGUAGE].default() == "pl"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STREET: STREET, CONF_LANGUAGE: "en"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: NUMBER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].options == {CONF_LANGUAGE: "en"}
    await hass.async_block_till_done()
    assert hass.states.get("sensor.testowa_1_paper") is not None


async def test_reconfigure_has_no_language(
    hass: HomeAssistant, client: FakeClient, init_integration: MockConfigEntry
) -> None:
    """Reconfiguring the address keeps the language."""
    result = await init_integration.start_reconfigure_flow(hass)
    assert CONF_LANGUAGE not in {str(key) for key in result["data_schema"].schema}


async def test_options_language(
    hass: HomeAssistant, client: FakeClient, init_integration: MockConfigEntry
) -> None:
    """The language can be changed in the options."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    fields = {str(key): key for key in result["data_schema"].schema}
    assert CONF_LANGUAGE in fields
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_LANGUAGE: "pl", "refresh": {}, "reminders": {}, "appearance": {}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert init_integration.options[CONF_LANGUAGE] == "pl"
    assert init_integration.runtime_data.fraction_name("makulatura") == "Papier"
