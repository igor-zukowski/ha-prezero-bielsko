"""Tests of the pure schedule calculations."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.prezero_bielsko.models import Collection, Schedule, ScheduleData
from custom_components.prezero_bielsko.schedule import (
    next_collection,
    reminder_state,
    reminder_window,
    upcoming,
)

TZ = ZoneInfo("Europe/Warsaw")
START = time(18, 0)
END = time(10, 0)

COLLECTIONS = [
    Collection(date(2026, 10, 15), "makulatura"),
    Collection(date(2026, 10, 15), "szklo"),
    Collection(date(2026, 10, 19), "kuchenne"),
    Collection(date(2026, 10, 5), "kuchenne"),
    Collection(date(2027, 1, 4), "kuchenne"),
]


def at(value: str) -> datetime:
    """Return a Warsaw time."""
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def state(dates: list[date], now: datetime, days_before: int = 1):
    """Return the reminder state with default times."""
    return reminder_state(
        dates, now, days_before=days_before, start=START, end=END, time_zone=TZ
    )


# B1, B2, B3


def test_upcoming() -> None:
    """Past collections are skipped, today is included."""
    today = date(2026, 10, 15)
    assert [item.date for item in upcoming(COLLECTIONS, today)] == [
        date(2026, 10, 15),
        date(2026, 10, 15),
        date(2026, 10, 19),
        date(2027, 1, 4),
    ]
    assert upcoming(COLLECTIONS, today, "kuchenne") == [
        Collection(date(2026, 10, 19), "kuchenne"),
        Collection(date(2027, 1, 4), "kuchenne"),
    ]
    assert upcoming(COLLECTIONS, date(2027, 2, 1)) == []


def test_next_collection() -> None:
    """The nearest day lists all fractions collected that day."""
    assert next_collection(COLLECTIONS, date(2026, 10, 11)) == (
        date(2026, 10, 15),
        ["makulatura", "szklo"],
    )
    assert next_collection(COLLECTIONS, date(2026, 10, 20)) == (
        date(2027, 1, 4),
        ["kuchenne"],
    )
    assert next_collection(COLLECTIONS, date(2027, 1, 5)) is None


def test_collections_across_years() -> None:
    """Collections of multiple years are merged and sorted."""
    data = ScheduleData(
        schedules={
            2027: Schedule(2027, "A", (Collection(date(2027, 1, 2), "mix"),)),
            2026: Schedule(2026, "A", (Collection(date(2026, 12, 30), "mix"),)),
        }
    )
    assert [item.date for item in data.collections] == [
        date(2026, 12, 30),
        date(2027, 1, 2),
    ]


# B4: windows


@pytest.mark.parametrize(
    ("days_before", "start", "end", "expected"),
    [
        (1, START, END, ("2026-10-14T18:00", "2026-10-15T10:00")),
        (7, START, END, ("2026-10-08T18:00", "2026-10-15T10:00")),
        (0, START, END, ("2026-10-15T00:00", "2026-10-15T10:00")),
        (0, START, time(0, 0), ("2026-10-15T00:00", "2026-10-16T00:00")),
        (1, time(6, 0), time(23, 59), ("2026-10-14T06:00", "2026-10-15T23:59")),
    ],
)
def test_reminder_window(
    days_before: int, start: time, end: time, expected: tuple[str, str]
) -> None:
    """Windows start days before at the start time and end on the day."""
    assert reminder_window(date(2026, 10, 15), days_before, start, end, TZ) == (
        at(expected[0]),
        at(expected[1]),
    )


def test_reminder_boundaries() -> None:
    """The reminder is on in [start, end) with exact next changes."""
    dates = [date(2026, 10, 15), date(2026, 10, 29)]
    before = state(dates, at("2026-10-14T17:59:59"))
    assert before.is_on is False
    assert before.next_change == at("2026-10-14T18:00")
    assert before.collection_dates == (date(2026, 10, 15),)

    started = state(dates, at("2026-10-14T18:00"))
    assert started.is_on is True
    assert started.next_change == at("2026-10-15T10:00")
    assert started.collection_dates == (date(2026, 10, 15),)

    ended = state(dates, at("2026-10-15T10:00"))
    assert ended.is_on is False
    assert ended.next_change == at("2026-10-28T18:00")
    assert ended.collection_dates == (date(2026, 10, 29),)

    done = state(dates, at("2026-10-29T10:00"))
    assert done == state([], at("2026-10-29T10:00"))
    assert done.is_on is False
    assert done.next_change is None


# B5: daylight saving time


def test_reminder_dst_autumn() -> None:
    """Wall clock times are kept when the clock goes back on 2026-10-25."""
    window = reminder_window(date(2026, 10, 25), 1, START, END, TZ)
    assert window[0].astimezone(UTC) == datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
    assert window[1].astimezone(UTC) == datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def test_reminder_dst_spring() -> None:
    """Wall clock times are kept when the clock goes forward on 2027-03-28."""
    window = reminder_window(date(2027, 3, 29), 1, START, END, TZ)
    assert window[0].astimezone(UTC) == datetime(2027, 3, 28, 16, 0, tzinfo=UTC)
    assert window[1].astimezone(UTC) == datetime(2027, 3, 29, 8, 0, tzinfo=UTC)


# B6: collection today after the end time


def test_reminder_after_end_today() -> None:
    """After the end time on the collection day the next collection is used."""
    result = state(
        [date(2026, 10, 15), date(2026, 10, 22)], at("2026-10-15T12:00"), days_before=0
    )
    assert result.is_on is False
    assert result.collection_dates == (date(2026, 10, 22),)
    assert result.next_change == at("2026-10-22T00:00")


# B7: overlapping windows


def test_reminder_overlapping_windows() -> None:
    """Overlapping windows of weekly collections are merged."""
    dates = [date(2026, 10, 8), date(2026, 10, 15), date(2026, 10, 29)]
    # 7 days before: the window of 15.10 starts on 08.10 18:00, after the
    # window of 08.10 ends at 10:00, so the reminder turns off in between.
    gap = state(dates, at("2026-10-08T09:00"), days_before=7)
    assert gap.is_on is True
    assert gap.collection_dates == (date(2026, 10, 8),)
    assert gap.next_change == at("2026-10-08T10:00")

    # 8 days before: the window of 15.10 starts on 07.10 18:00, so both merge.
    both = state(dates, at("2026-10-08T09:00"), days_before=8)
    assert both.is_on is True
    assert both.collection_dates == (date(2026, 10, 8), date(2026, 10, 15))
    assert both.next_change == at("2026-10-15T10:00")

    upcoming_state = state(dates, at("2026-10-01T18:00"), days_before=7)
    assert upcoming_state.is_on is True
    assert upcoming_state.collection_dates == (date(2026, 10, 8),)


def test_schedule_serialization_roundtrip() -> None:
    """Schedules survive serialization."""
    data = ScheduleData(
        schedules={
            2026: Schedule(
                2026,
                "BBA/1",
                tuple(sorted(COLLECTIONS[:4])),
                at("2026-09-22T09:56"),
            )
        },
        last_success=datetime(2026, 10, 11, 10, 0, tzinfo=UTC),
    )
    assert ScheduleData.from_dict(data.as_dict()) == data
    empty = ScheduleData()
    assert ScheduleData.from_dict({**empty.as_dict(), "schedules": {}}) == empty
