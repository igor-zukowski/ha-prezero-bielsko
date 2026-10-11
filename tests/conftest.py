"""Fixtures for PreZero Bielsko-Biała tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.prezero_bielsko.api import (
    PreZeroClient,
    parse_response,
    parse_schedule,
)
from custom_components.prezero_bielsko.const import (
    CONF_LANGUAGE,
    CONF_NUMBER,
    CONF_STREET,
    CONF_SYMBOL,
    DOMAIN,
)
from custom_components.prezero_bielsko.models import Collection, Customer, Schedule

FIXTURES = Path(__file__).parent / "fixtures"

SYMBOL = "BBA/10000001"
STREET = "TESTOWA"
NUMBER = "1"
TITLE = "Testowa 1"
# Sunday; next collections: paper and glass on Thursday 2026-10-15.
NOW = "2026-10-11T12:00:00+02:00"


def load_fixture(name: str) -> str:
    """Load a fixture file."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def schedule_2026(symbol: str = SYMBOL) -> Schedule:
    """Return the sample schedule of 2026."""
    return parse_schedule(parse_response(load_fixture("daty_2026.txt")), symbol, 2026)


def make_schedule(
    year: int, items: list[tuple[str, str]], symbol: str = SYMBOL
) -> Schedule:
    """Return a schedule built from ``(iso date, fraction)`` pairs."""
    return Schedule(
        year=year,
        symbol=symbol,
        collections=tuple(
            sorted(
                Collection(date.fromisoformat(day), fraction) for day, fraction in items
            )
        ),
    )


class FakeClient:
    """In-memory replacement of the service client."""

    pdf_url = staticmethod(PreZeroClient.pdf_url)

    def __init__(self) -> None:
        """Initialize the fake client with sample data."""
        self.streets = ["1 MAJA", "ADAMA MICKIEWICZA", STREET]
        self.numbers: dict[str, list[str]] = {
            STREET: [NUMBER, "2A", "27/1,3,5"],
            "1 MAJA": ["5"],
        }
        self.customers: dict[tuple[str, str], list[Customer]] = {
            (STREET, NUMBER): [Customer(SYMBOL, "0")],
            (STREET, "2A"): [
                Customer("BBA/10000002", "0"),
                Customer("BBA/10000003", "0"),
            ],
            ("1 MAJA", "5"): [Customer("BBA/10000005", "0")],
        }
        self.schedules: dict[tuple[str, int], Schedule] = {
            (SYMBOL, 2026): schedule_2026(),
            ("BBA/10000002", 2026): schedule_2026("BBA/10000002"),
            ("BBA/10000003", 2026): schedule_2026("BBA/10000003"),
            ("BBA/10000005", 2026): schedule_2026("BBA/10000005"),
        }
        self.error: Exception | None = None
        self.calls: list[tuple[Any, ...]] = []

    def _call(self, *call: Any) -> None:
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    def calls_of(self, kind: str) -> list[tuple[Any, ...]]:
        """Return recorded calls of one kind."""
        return [call for call in self.calls if call[0] == kind]

    async def async_get_streets(self, year: int) -> list[str]:
        """Return streets."""
        self._call("streets", year)
        return list(self.streets)

    async def async_get_numbers(self, street: str, year: int) -> list[str]:
        """Return numbers."""
        self._call("numbers", street, year)
        return list(self.numbers.get(street, []))

    async def async_get_customers(
        self, street: str, number: str, year: int
    ) -> list[Customer]:
        """Return customers."""
        self._call("customers", street, number, year)
        return list(self.customers.get((street, number), []))

    async def async_get_schedule(self, symbol: str, year: int) -> Schedule:
        """Return a schedule."""
        self._call("schedule", symbol, year)
        return self.schedules.get((symbol, year), Schedule(year, symbol, ()))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture(autouse=True)
async def warsaw_time_zone(request: pytest.FixtureRequest) -> None:
    """Use the time zone of the service in Home Assistant tests."""
    if "hass" in request.fixturenames:
        hass: HomeAssistant = request.getfixturevalue("hass")
        await hass.config.async_set_time_zone("Europe/Warsaw")


@pytest.fixture
def now(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time at the default test moment."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def client() -> Generator[FakeClient]:
    """Patch the service client used by the integration and the config flow."""
    fake = FakeClient()
    with (
        patch("custom_components.prezero_bielsko.PreZeroClient", return_value=fake),
        patch(
            "custom_components.prezero_bielsko.config_flow.PreZeroClient",
            return_value=fake,
        ),
    ):
        yield fake


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a configured address."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        unique_id=f"{STREET}|{NUMBER}|10000001".casefold(),
        data={CONF_STREET: STREET, CONF_NUMBER: NUMBER, CONF_SYMBOL: SYMBOL},
        # Most tests check English names; the Polish default is tested separately.
        options={CONF_LANGUAGE: "en"},
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: FakeClient,
    now: FrozenDateTimeFactory,
) -> MockConfigEntry:
    """Set up the integration with sample data."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
