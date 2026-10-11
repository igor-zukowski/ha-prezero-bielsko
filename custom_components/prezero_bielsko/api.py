"""Client for the PreZero Bielsko-Biała waste collection schedule service."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
import json
import logging
import re
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import aiohttp

from .const import API_URL, CITY
from .models import Collection, Customer, Schedule, symbol_key

_LOGGER = logging.getLogger(__name__)

SERVICE_TIME_ZONE = ZoneInfo("Europe/Warsaw")
DEFAULT_TIMEOUT = 30

_HEADERS = {
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://prezero-bielsko.pl/harmonogram-odbioru-odpadow/",
}
_EVAL_RE = re.compile(r"eval\s*\((.*)\)\s*;?", re.DOTALL)
# Matches a JSON string literal (kept as is) or a trailing comma before a closing bracket.
_TRAILING_COMMA_RE = re.compile(r'("(?:[^"\\]|\\.)*")|,(\s*[\]}])')


class PreZeroError(Exception):
    """Base error of the PreZero client."""


class PreZeroConnectionError(PreZeroError):
    """The service could not be reached or is temporarily unavailable."""


class PreZeroResponseError(PreZeroError):
    """The service returned a response that could not be understood."""


class PreZeroAddressNotFoundError(PreZeroError):
    """The configured address has no matching customer symbol."""


def parse_response(text: str) -> dict[str, Any]:
    """Parse the ``eval({...})`` payload returned by the service."""
    match = _EVAL_RE.fullmatch(text.strip())
    if match is None:
        raise PreZeroResponseError("Unexpected response format")
    body = _TRAILING_COMMA_RE.sub(
        lambda m: m.group(1) if m.group(1) is not None else m.group(2),
        match.group(1),
    )
    try:
        data = json.loads(body)
    except ValueError as err:
        raise PreZeroResponseError(f"Invalid response payload: {err}") from err
    if not isinstance(data, dict) or not isinstance(data.get("dane"), list):
        raise PreZeroResponseError("Response payload has no data list")
    return data


def parse_published(value: Any) -> datetime | None:
    """Parse the schedule publication time (``dd-mm-YYYY HH:MM``)."""
    if not isinstance(value, str):
        return None
    try:
        published = datetime.strptime(value.strip(), "%d-%m-%Y %H:%M")  # noqa: DTZ007
    except ValueError:
        return None
    if published.year <= 1970:
        # The service returns the Unix epoch when it has no schedule.
        return None
    return published.replace(tzinfo=SERVICE_TIME_ZONE)


def parse_schedule(data: dict[str, Any], symbol: str, year: int) -> Schedule:
    """Build a schedule from the ``daty`` view payload."""
    collections: set[Collection] = set()
    for item in data["dane"]:
        if not isinstance(item, dict):
            continue
        fraction = str(item.get("rodzaj", "")).strip().lower()
        try:
            day = date(year, int(item["data_m"]), int(item["data_d"]))
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Skipping invalid collection entry: %s", item)
            continue
        if not fraction:
            _LOGGER.warning("Skipping collection entry without a fraction: %s", item)
            continue
        collections.add(Collection(day, fraction))
    return Schedule(
        year=year,
        symbol=symbol,
        collections=tuple(sorted(collections)),
        published=parse_published(data.get("data_akt")),
    )


def _unique(values: list[str]) -> list[str]:
    """Return unique non empty values keeping their order."""
    return list(dict.fromkeys(value for value in values if value))


def select_customer(customers: list[Customer], key: str | None) -> Customer | None:
    """Select the configured customer from the customers of an address."""
    if key:
        normalized = symbol_key(key)
        for customer in customers:
            if customer.key == normalized:
                return customer
    if len(customers) == 1:
        return customers[0]
    return None


class PreZeroClient:
    """Asynchronous client of the schedule service."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        city: str = CITY,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._city = city
        self._timeout = timeout

    async def _request(self, **params: str | int) -> dict[str, Any]:
        """Send a request to the service and parse its response."""
        payload = {"option": "com_sita", **{k: str(v) for k, v in params.items()}}
        try:
            async with (
                asyncio.timeout(self._timeout),
                self._session.post(API_URL, data=payload, headers=_HEADERS) as response,
            ):
                if response.status == 429 or response.status >= 500:
                    raise PreZeroConnectionError(
                        f"Service unavailable (HTTP {response.status})"
                    )
                if response.status >= 400:
                    raise PreZeroResponseError(
                        f"Unexpected HTTP status {response.status}"
                    )
                text = await response.text()
        except TimeoutError as err:
            raise PreZeroConnectionError(
                "Timeout while contacting the service"
            ) from err
        except aiohttp.ClientError as err:
            raise PreZeroConnectionError(
                f"Error while contacting the service: {err}"
            ) from err
        return parse_response(text)

    async def async_get_streets(self, year: int) -> list[str]:
        """Return streets served in the city."""
        data = await self._request(view="ulice", q=self._city, rok=year)
        return _unique(
            [
                str(item.get("ulica", ""))
                for item in data["dane"]
                if isinstance(item, dict)
            ]
        )

    async def async_get_numbers(self, street: str, year: int) -> list[str]:
        """Return house numbers of a street."""
        data = await self._request(view="numery", q=self._city, ulica=street, rok=year)
        return _unique(
            [
                str(item.get("numer", ""))
                for item in data["dane"]
                if isinstance(item, dict)
            ]
        )

    async def async_get_customers(
        self, street: str, number: str, year: int
    ) -> list[Customer]:
        """Return customer symbols assigned to an address."""
        data = await self._request(
            view="typy", q=self._city, numer=number, ulica=street, rok=year
        )
        customers: dict[str, Customer] = {}
        for item in data["dane"]:
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            symbol = str(item["symbol"]).strip()
            customers.setdefault(symbol, Customer(symbol, str(item.get("typ", ""))))
        return list(customers.values())

    async def async_get_schedule(self, symbol: str, year: int) -> Schedule:
        """Return the collection schedule of a customer."""
        data = await self._request(view="daty", q=symbol, rok=year)
        return parse_schedule(data, symbol, year)

    @staticmethod
    def pdf_url(symbol: str, year: int) -> str:
        """Return the URL of the printable schedule."""
        query = urlencode(
            {
                "option": "com_sita",
                "view": "daty",
                "format": "pdf",
                "wersja": "lipiec",
                "q": symbol,
                "rok": year,
            }
        )
        return f"{API_URL}?{query}"
