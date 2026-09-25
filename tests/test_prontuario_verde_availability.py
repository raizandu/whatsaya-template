import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from prontuario_verde_availability import (
    AvailabilityError, Interval, OpeningSnapshot, available_starts,
)


TZ = ZoneInfo("America/Sao_Paulo")
DAY = date(2026, 10, 2)


def at(hour, minute=0):
    return datetime(2026, 10, 2, hour, minute, tzinfo=TZ)


def snapshot(**changes):
    values = dict(
        source_clinic_hash="clinic-hash",
        professional_id="professional-1",
        unit_id="unit-1",
        day=DAY,
        observed_at=at(8),
        openings=(Interval(at(9), at(12)), Interval(at(13), at(18))),
        blocking=(Interval(at(10), at(10, 30)),),
        candidate_starts=(at(9), at(9, 30), at(10), at(11, 45), at(12), at(13)),
        complete=True,
    )
    values.update(changes)
    return OpeningSnapshot(**values)


def check(value, **changes):
    request = dict(
        source_clinic_hash="clinic-hash", professional_id="professional-1",
        unit_id="unit-1", day=DAY, duration_minutes=40, now=at(8, 0),
    )
    request.update(changes)
    return available_starts(value, **request)


class OpeningSnapshotTests(unittest.TestCase):
    def test_only_live_source_candidates_fully_open_and_unblocked(self):
        self.assertEqual(check(snapshot()), (at(9), at(13)))

    def test_does_not_join_separate_openings_for_long_consultation(self):
        self.assertNotIn(at(11, 45), check(snapshot(), duration_minutes=60))

    def test_wrong_professional_or_unit_fails_closed(self):
        for change in ({"professional_id": "other"}, {"unit_id": "other"}):
            with self.subTest(change=change), self.assertRaises(AvailabilityError):
                check(snapshot(), **change)

    def test_incomplete_or_stale_source_fails_closed(self):
        with self.assertRaises(AvailabilityError):
            check(snapshot(complete=False))
        with self.assertRaises(AvailabilityError):
            check(snapshot(), now=at(8) + timedelta(seconds=61))

    def test_bad_duration_and_naive_source_fails_closed(self):
        with self.assertRaises(AvailabilityError):
            check(snapshot(), duration_minutes=0)
        with self.assertRaises(AvailabilityError):
            check(snapshot(observed_at=datetime(2026, 10, 2, 8)))


if __name__ == "__main__":
    unittest.main()
