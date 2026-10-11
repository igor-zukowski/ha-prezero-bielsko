"""Data models for the PreZero Bielsko-Biała integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True, order=True)
class Collection:
    """Single collection of one waste fraction on one day."""

    date: date
    fraction: str


@dataclass(frozen=True, slots=True)
class Customer:
    """Customer (schedule) symbol assigned to an address."""

    symbol: str
    type: str = ""

    @property
    def key(self) -> str:
        """Return the year independent part of the symbol."""
        return symbol_key(self.symbol)


@dataclass(frozen=True, slots=True)
class Schedule:
    """Collection schedule of one customer for one year."""

    year: int
    symbol: str
    collections: tuple[Collection, ...]
    published: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize the schedule for storage."""
        return {
            "year": self.year,
            "symbol": self.symbol,
            "published": self.published.isoformat() if self.published else None,
            "collections": [
                [item.date.isoformat(), item.fraction] for item in self.collections
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schedule:
        """Deserialize a schedule from storage."""
        published = data.get("published")
        return cls(
            year=int(data["year"]),
            symbol=str(data["symbol"]),
            published=datetime.fromisoformat(published) if published else None,
            collections=tuple(
                sorted(
                    Collection(date.fromisoformat(day), str(fraction))
                    for day, fraction in data["collections"]
                )
            ),
        )


@dataclass(slots=True)
class ScheduleData:
    """Data held by the coordinator."""

    schedules: dict[int, Schedule] = field(default_factory=dict)
    last_success: datetime | None = None

    @property
    def collections(self) -> tuple[Collection, ...]:
        """Return all known collections sorted by date."""
        return tuple(
            sorted(
                item
                for schedule in self.schedules.values()
                for item in schedule.collections
            )
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize the data for storage."""
        return {
            "last_success": self.last_success.isoformat()
            if self.last_success
            else None,
            "schedules": {
                str(year): schedule.as_dict()
                for year, schedule in self.schedules.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleData:
        """Deserialize the data from storage."""
        last_success = data.get("last_success")
        return cls(
            schedules={
                int(year): Schedule.from_dict(schedule)
                for year, schedule in data["schedules"].items()
            },
            last_success=datetime.fromisoformat(last_success) if last_success else None,
        )


def symbol_key(symbol: str) -> str:
    """Return the year independent part of a customer symbol.

    The service prefixes symbols differently between years,
    for example ``12345678`` in 2025 and ``BBA/12345678`` in 2026.
    """
    return symbol.rsplit("/", 1)[-1].strip().upper()
