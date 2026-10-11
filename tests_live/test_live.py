"""Contract tests against the real website.

Run with ``pytest tests_live -p no:homeassistant -o addopts=""``.
"""

from __future__ import annotations

from datetime import date

import aiohttp
import pytest

from custom_components.prezero_bielsko.api import PreZeroClient

STREET = "3 MAJA"


@pytest.fixture
async def api():
    """Return a client with a real session."""
    async with aiohttp.ClientSession() as session:
        yield PreZeroClient(session)


async def test_live_contract(api: PreZeroClient) -> None:
    """The website still answers in the expected format."""
    year = date.today().year  # noqa: DTZ011
    streets = await api.async_get_streets(year)
    assert len(streets) > 500
    assert STREET in streets

    numbers = await api.async_get_numbers(STREET, year)
    assert numbers

    customers = []
    for number in numbers[:10]:
        customers = await api.async_get_customers(STREET, number, year)
        if customers:
            break
    assert customers

    schedule = await api.async_get_schedule(customers[0].symbol, year)
    assert schedule.collections
    assert all(item.date.year == year for item in schedule.collections)


async def test_live_pdf(api: PreZeroClient) -> None:
    """The printable schedule is a PDF."""
    year = date.today().year  # noqa: DTZ011
    numbers = await api.async_get_numbers(STREET, year)
    customers = await api.async_get_customers(STREET, numbers[0], year)
    async with (
        aiohttp.ClientSession() as session,
        session.get(api.pdf_url(customers[0].symbol, year)) as response,
    ):
        assert response.status == 200
        assert response.content_type == "application/pdf"
