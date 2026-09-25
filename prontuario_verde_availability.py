"""Fail-closed checks over an exact native agenda opening snapshot.

The caller must obtain openings, every blocking interval, and candidate start
times from the same live PV clinic/professional/unit/day view. This module does
not infer openings from gaps in the appointment feed or weekly business hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


LOCAL_ZONE = ZoneInfo("America/Sao_Paulo")
MAX_SNAPSHOT_AGE = timedelta(seconds=60)


class AvailabilityError(ValueError):
    """The source has not established an exact, current opening."""


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class OpeningSnapshot:
    source_clinic_hash: str
    professional_id: str
    unit_id: str
    day: date
    observed_at: datetime
    openings: tuple[Interval, ...]
    blocking: tuple[Interval, ...]
    candidate_starts: tuple[datetime, ...]
    complete: bool


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AvailabilityError("invalid_timestamp")
    return value.astimezone(LOCAL_ZONE)


def _interval(value: Interval) -> tuple[datetime, datetime]:
    if not isinstance(value, Interval):
        raise AvailabilityError("invalid_interval")
    start, end = _instant(value.start), _instant(value.end)
    if start >= end:
        raise AvailabilityError("invalid_interval")
    return start, end


def available_starts(
    snapshot: OpeningSnapshot,
    *,
    source_clinic_hash: str,
    professional_id: str,
    unit_id: str,
    day: date,
    duration_minutes: int,
    now: datetime,
) -> tuple[datetime, ...]:
    """Return only source-supplied starts fully open for the requested duration.

    ``complete`` is a provider assertion that openings and all blockers for this
    exact view were read successfully. It is never inferred from an empty list.
    The caller must fetch a new snapshot immediately before committing a write.
    """
    if not isinstance(snapshot, OpeningSnapshot) or snapshot.complete is not True:
        raise AvailabilityError("opening_unverified")
    if (
        not source_clinic_hash or not professional_id or not unit_id
        or snapshot.source_clinic_hash != source_clinic_hash
        or snapshot.professional_id != professional_id
        or snapshot.unit_id != unit_id
        or not isinstance(day, date) or isinstance(day, datetime)
        or snapshot.day != day
    ):
        raise AvailabilityError("source_mismatch")
    if type(duration_minutes) is not int or duration_minutes <= 0:
        raise AvailabilityError("invalid_duration")
    observed, current = _instant(snapshot.observed_at), _instant(now)
    if observed > current or current - observed > MAX_SNAPSHOT_AGE:
        raise AvailabilityError("stale_opening")

    if not all(isinstance(values, tuple) for values in (
        snapshot.openings, snapshot.blocking, snapshot.candidate_starts,
    )):
        raise AvailabilityError("opening_unverified")

    openings = tuple(_interval(value) for value in snapshot.openings)
    blocking = tuple(_interval(value) for value in snapshot.blocking)
    starts = tuple(_instant(value) for value in snapshot.candidate_starts)
    duration = timedelta(minutes=duration_minutes)
    result: set[datetime] = set()
    for start in starts:
        end = start + duration
        if start.date() != day or end.date() != day or start < current:
            continue
        if not any(open_start <= start and end <= open_end for open_start, open_end in openings):
            continue
        if any(start < busy_end and busy_start < end for busy_start, busy_end in blocking):
            continue
        result.add(start)
    return tuple(sorted(result))
