"""Tests of the service client and response parser."""

from __future__ import annotations

from datetime import date, datetime

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.prezero_bielsko.api import (
    SERVICE_TIME_ZONE,
    PreZeroClient,
    PreZeroConnectionError,
    PreZeroResponseError,
    parse_published,
    parse_response,
    parse_schedule,
    select_customer,
)
from custom_components.prezero_bielsko.const import API_URL
from custom_components.prezero_bielsko.models import Collection, Customer, symbol_key

from .conftest import load_fixture


@pytest.fixture
def api(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> PreZeroClient:
    """Return a client using the mocked session."""
    return PreZeroClient(async_get_clientsession(hass))


# A1, A3, A4: parser


def test_parse_trailing_commas_and_strings() -> None:
    """Trailing commas are removed, commas and brackets inside strings are kept."""
    data = parse_response(
        'eval({"dane": [{"numer": "27/1,3,5"},{"numer": "a,]"},{"numer": "q\\",}"},]})'
    )
    assert data == {
        "dane": [{"numer": "27/1,3,5"}, {"numer": "a,]"}, {"numer": 'q",}'}]
    }


def test_parse_whitespace_and_semicolon() -> None:
    """Surrounding whitespace and a trailing semicolon are accepted."""
    assert parse_response('\n eval( {"dane": [ ] , } );\n') == {"dane": []}


def test_parse_unicode() -> None:
    """Polish characters are preserved."""
    data = parse_response(load_fixture("ulice.txt"))
    assert {"ulica": "ADAMA MICKIEWICZA"} in data["dane"]


@pytest.mark.parametrize(
    "text",
    [
        load_fixture("not_found.html"),
        "",
        "garbage",
        'eval({"dane": [}',
        'eval({"dane": [})',
        "eval(not json)",
        'eval({"other": []})',
        'eval({"dane": "x"})',
        "eval([1, 2])",
    ],
)
def test_parse_invalid(text: str) -> None:
    """Unexpected payloads raise a response error."""
    with pytest.raises(PreZeroResponseError):
        parse_response(text)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("22-09-2026 09:56", datetime(2026, 9, 22, 9, 56, tzinfo=SERVICE_TIME_ZONE)),
        ("01-01-1970 01:00", None),
        ("2026-09-22", None),
        (None, None),
        (5, None),
    ],
)
def test_parse_published(value: object, expected: datetime | None) -> None:
    """The publication time is parsed, the epoch means no schedule."""
    assert parse_published(value) == expected


def test_parse_schedule_sample() -> None:
    """The sample schedule is parsed completely."""
    schedule = parse_schedule(
        parse_response(load_fixture("daty_2026.txt")), "BBA/1", 2026
    )
    assert len(schedule.collections) == 128
    assert schedule.collections[0] == Collection(date(2026, 1, 13), "kuchenne")
    assert schedule.collections == tuple(sorted(schedule.collections))
    assert {item.fraction for item in schedule.collections} == {
        "gabaryty",
        "kuchenne",
        "makulatura",
        "mix",
        "popiol",
        "resztkowe",
        "szklo",
        "zielone",
    }
    assert schedule.published == datetime(2026, 9, 22, 9, 56, tzinfo=SERVICE_TIME_ZONE)


def test_parse_schedule_empty() -> None:
    """An empty schedule has no collections and no publication time."""
    schedule = parse_schedule(
        parse_response(load_fixture("daty_empty.txt")), "BBA/1", 2027
    )
    assert schedule.collections == ()
    assert schedule.published is None


# A6, A7: invalid entries, duplicates, unknown fractions


def test_parse_schedule_invalid_entries(caplog: pytest.LogCaptureFixture) -> None:
    """Invalid entries are skipped, duplicates removed, unknown fractions kept."""
    data = {
        "dane": [
            {"data_m": "02", "data_d": "9", "rodzaj": "kuchenne"},
            {"data_m": "2", "data_d": "09", "rodzaj": "KUCHENNE "},
            {"data_m": "02", "data_d": "31", "rodzaj": "kuchenne"},
            {"data_m": "x", "data_d": "1", "rodzaj": "kuchenne"},
            {"data_d": "1", "rodzaj": "kuchenne"},
            {"data_m": "03", "data_d": "1", "rodzaj": ""},
            {"data_m": "03", "data_d": "2", "rodzaj": "elektro"},
            "not a dict",
        ]
    }
    schedule = parse_schedule(data, "BBA/1", 2026)
    assert schedule.collections == (
        Collection(date(2026, 2, 9), "kuchenne"),
        Collection(date(2026, 3, 2), "elektro"),
    )
    assert "Skipping invalid collection entry" in caplog.text
    assert "without a fraction" in caplog.text


# A9: symbols across years


def test_symbol_key() -> None:
    """Symbol prefixes are ignored."""
    assert symbol_key("BBA/12345678") == symbol_key("12345678") == "12345678"
    assert Customer("bba/123a").key == "123A"


def test_select_customer() -> None:
    """The configured customer is matched by its year independent key."""
    first = Customer("BBA/1")
    second = Customer("BBA/2")
    assert select_customer([first, second], "2") is second
    assert select_customer([first, second], "BBA/1") is first
    assert select_customer([first, second], "3") is None
    assert select_customer([first, second], None) is None
    assert select_customer([Customer("NEW/9")], "1") == Customer("NEW/9")
    assert select_customer([], "1") is None


# A2, A8: requests


async def test_requests(
    api: PreZeroClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Requests send the same form fields as the website."""
    aioclient_mock.post(API_URL, text=load_fixture("ulice.txt"))
    assert await api.async_get_streets(2026) == [
        "1 MAJA",
        "ADAMA MICKIEWICZA",
        "DR. HENRYKA JORDANA",
        "TESTOWA",
    ]
    assert aioclient_mock.mock_calls[-1][2] == {
        "option": "com_sita",
        "view": "ulice",
        "q": "Bielsko-Biała",
        "rok": "2026",
    }
    headers = aioclient_mock.mock_calls[-1][3]
    assert headers["X-Requested-With"] == "XMLHttpRequest"

    aioclient_mock.clear_requests()
    aioclient_mock.post(API_URL, text=load_fixture("numery.txt"))
    assert await api.async_get_numbers("A & B", 2026) == ["1", "2A", "27/1,3,5", "b/n"]
    assert aioclient_mock.mock_calls[-1][2] == {
        "option": "com_sita",
        "view": "numery",
        "q": "Bielsko-Biała",
        "ulica": "A & B",
        "rok": "2026",
    }

    aioclient_mock.clear_requests()
    aioclient_mock.post(API_URL, text=load_fixture("typy_multiple.txt"))
    assert await api.async_get_customers("TESTOWA", "27/1,3,5", 2026) == [
        Customer("BBA/10000002", "0"),
        Customer("BBA/10000003", "0"),
    ]
    assert aioclient_mock.mock_calls[-1][2] == {
        "option": "com_sita",
        "view": "typy",
        "q": "Bielsko-Biała",
        "numer": "27/1,3,5",
        "ulica": "TESTOWA",
        "rok": "2026",
    }

    aioclient_mock.clear_requests()
    aioclient_mock.post(API_URL, text=load_fixture("daty_2026.txt"))
    schedule = await api.async_get_schedule("BBA/10000001", 2026)
    assert len(schedule.collections) == 128
    assert schedule.symbol == "BBA/10000001"
    assert aioclient_mock.mock_calls[-1][2] == {
        "option": "com_sita",
        "view": "daty",
        "q": "BBA/10000001",
        "rok": "2026",
    }


def test_pdf_url() -> None:
    """The printable schedule URL is encoded."""
    assert PreZeroClient.pdf_url("BBA/1", 2026) == (
        f"{API_URL}?option=com_sita&view=daty&format=pdf&wersja=lipiec"
        "&q=BBA%2F1&rok=2026"
    )


# A5: errors


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"exc": aiohttp.ClientError()}, PreZeroConnectionError),
        ({"exc": TimeoutError()}, PreZeroConnectionError),
        ({"status": 500}, PreZeroConnectionError),
        ({"status": 503}, PreZeroConnectionError),
        ({"status": 429}, PreZeroConnectionError),
        ({"status": 404, "text": load_fixture("not_found.html")}, PreZeroResponseError),
        ({"text": load_fixture("not_found.html")}, PreZeroResponseError),
    ],
)
async def test_request_errors(
    api: PreZeroClient,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict[str, object],
    error: type[Exception],
) -> None:
    """Transport problems and unexpected responses raise typed errors."""
    aioclient_mock.post(API_URL, **kwargs)
    with pytest.raises(error):
        await api.async_get_schedule("BBA/1", 2026)


async def test_customers_skip_invalid(
    api: PreZeroClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Entries without a symbol are ignored."""
    aioclient_mock.post(
        API_URL,
        text='eval({"dane": [{"typ": "0"},{"symbol": " BBA/1 "},"x",]})',
    )
    assert await api.async_get_customers("A", "1", 2026) == [Customer("BBA/1", "")]
