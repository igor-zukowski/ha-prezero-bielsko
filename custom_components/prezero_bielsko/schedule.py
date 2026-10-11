"""Pure schedule calculations, independent of Home Assistant."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from .models import Collection


@dataclass(frozen=True, slots=True)
class ReminderState:
    """State of a reminder at a point in time."""

    is_on: bool
    collection_dates: tuple[date, ...]
    next_change: datetime | None


def upcoming(
    collections: Iterable[Collection], today: date, fraction: str | None = None
) -> list[Collection]:
    """Return collections from today on, optionally of a single fraction."""
    return sorted(
        item
        for item in collections
        if item.date >= today and (fraction is None or item.fraction == fraction)
    )


def next_collection(
    collections: Iterable[Collection], today: date
) -> tuple[date, list[str]] | None:
    """Return the nearest collection day and the fractions collected that day."""
    items = upcoming(collections, today)
    if not items:
        return None
    day = items[0].date
    return day, [item.fraction for item in items if item.date == day]


def reminder_window(
    collection_date: date,
    days_before: int,
    start: time,
    end: time,
    time_zone: tzinfo,
) -> tuple[datetime, datetime]:
    """Return the period in which a reminder of a collection is active.

    The reminder starts ``days_before`` days before the collection at ``start``
    and ends on the collection day at ``end``. With ``days_before`` equal to 0
    the reminder starts at midnight of the collection day.
    """
    if days_before > 0:
        window_start = datetime.combine(
            collection_date - timedelta(days=days_before), start, time_zone
        )
    else:
        window_start = datetime.combine(collection_date, time.min, time_zone)
    window_end = datetime.combine(collection_date, end, time_zone)
    if window_end <= window_start:
        window_end = datetime.combine(
            collection_date + timedelta(days=1), time.min, time_zone
        )
    return window_start, window_end


def reminder_state(
    dates: Iterable[date],
    now: datetime,
    *,
    days_before: int,
    start: time,
    end: time,
    time_zone: tzinfo,
) -> ReminderState:
    """Return whether a reminder is active at ``now`` and when this changes.

    Overlapping windows of consecutive collections are merged, so the
    reminder does not flicker when it is configured longer than the period
    between collections.
    """
    windows = sorted(
        window
        for window in (
            (*reminder_window(day, days_before, start, end, time_zone), day)
            for day in set(dates)
        )
        if window[1] > now
    )
    if not windows:
        return ReminderState(False, (), None)

    merged_start, merged_end, first_day = windows[0]
    merged_dates = [first_day]
    for window_start, window_end, day in windows[1:]:
        if window_start > merged_end:
            break
        merged_end = max(merged_end, window_end)
        merged_dates.append(day)

    if merged_start <= now:
        active = tuple(
            day
            for window_start, window_end, day in windows
            if window_start <= now < window_end
        )
        return ReminderState(True, active, merged_end)
    return ReminderState(False, tuple(merged_dates[:1]), merged_start)
