from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from commercial_followups import (  # noqa: E402
    CADENCES,
    BusinessHours,
    DEFAULT_HOURS,
    FollowupEngine,
    add_business_days,
    add_business_minutes,
    cadence_due_times,
    engine_options_from_profile,
    next_business_time,
    next_window_open,
)

THERAPIFY_PROFILE = json.loads(
    (REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json").read_text(encoding="utf-8")
)
THERAPIFY_HOURS = BusinessHours.from_profile(THERAPIFY_PROFILE)
SP = ZoneInfo("America/Sao_Paulo")


def sp(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SP)


class BusinessHoursDefaultsTests(unittest.TestCase):
    def test_default_hours_generic(self):
        self.assertEqual(DEFAULT_HOURS.open, time(8, 0))
        self.assertEqual(DEFAULT_HOURS.close, time(18, 0))
        self.assertEqual(DEFAULT_HOURS.holidays, frozenset())
        self.assertEqual(DEFAULT_HOURS.tz, ZoneInfo("America/Sao_Paulo"))

    def test_from_profile_missing_or_invalid_is_default(self):
        self.assertEqual(BusinessHours.from_profile(None), DEFAULT_HOURS)
        self.assertEqual(BusinessHours.from_profile({}), DEFAULT_HOURS)
        self.assertEqual(BusinessHours.from_profile({"schedule": "não é um dict"}), DEFAULT_HOURS)
        self.assertEqual(BusinessHours.from_profile({"schedule": {"open": "25:99"}}), DEFAULT_HOURS)


class BusinessHoursTherapifyTests(unittest.TestCase):
    def test_open_close_and_holidays(self):
        self.assertEqual(THERAPIFY_HOURS.open, time(9, 0))
        self.assertEqual(THERAPIFY_HOURS.close, time(21, 0))
        self.assertTrue(THERAPIFY_HOURS.is_off_day(date(2026, 9, 7)))  # segunda, feriado
        self.assertTrue(THERAPIFY_HOURS.is_off_day(date(2026, 9, 5)))  # sábado
        self.assertFalse(THERAPIFY_HOURS.is_off_day(date(2026, 9, 8)))  # terça normal

    def test_next_business_time_skips_holiday_that_falls_on_monday(self):
        friday_after_close = sp(2026, 9, 4, 21, 30)
        expected = sp(2026, 9, 8, 9, 0).astimezone(UTC)
        self.assertEqual(next_business_time(friday_after_close, THERAPIFY_HOURS), expected)

    def test_add_business_days_skips_holiday_weekend(self):
        friday_morning = sp(2026, 9, 4, 10, 0)
        expected = sp(2026, 9, 8, 10, 0).astimezone(UTC)
        self.assertEqual(add_business_days(friday_morning, 1, THERAPIFY_HOURS), expected)


class NextWindowOpenTests(unittest.TestCase):
    def test_weekend_counts_as_valid_day_when_not_skipping(self):
        saturday_night = sp(2026, 9, 5, 23, 0)
        expected = sp(2026, 9, 6, 9, 0).astimezone(UTC)
        self.assertEqual(next_window_open(saturday_night, THERAPIFY_HOURS, skip_off_days=False), expected)

    def test_within_hours_returns_same_instant(self):
        saturday_morning = sp(2026, 9, 5, 10, 0)
        expected = saturday_morning.astimezone(UTC)
        self.assertEqual(next_window_open(saturday_morning, THERAPIFY_HOURS, skip_off_days=False), expected)


class CadenceDueTimesOverrideTests(unittest.TestCase):
    def test_profile_cadence_override_replaces_only_that_cadence(self):
        profile = {"followup_cadences": {"silence": [["business_minutes", 5], ["business_days", 1]]}}
        options = engine_options_from_profile(profile)
        cadences = options["cadences"]
        self.assertEqual(cadences["silence"], (("business_minutes", 5), ("business_days", 1)))
        self.assertEqual(cadences["proposal"], CADENCES["proposal"])

        basis = sp(2026, 1, 5, 10, 0)  # segunda, dentro do expediente genérico
        due = cadence_due_times("silence", basis, cadences=cadences)
        self.assertEqual(due, [add_business_minutes(basis, 5), add_business_days(basis, 1)])


class EngineOptionsFromProfileTests(unittest.TestCase):
    def test_none_or_invalid_profile_falls_back(self):
        self.assertEqual(engine_options_from_profile(None), {"hours": DEFAULT_HOURS})
        self.assertEqual(engine_options_from_profile({"schedule": "nope"}), {"hours": DEFAULT_HOURS})

    def test_invalid_resume_per_tick_is_ignored(self):
        for bad in (0, 21, "2", True, 1.5):
            options = engine_options_from_profile({"schedule": {"resume_per_tick": bad}})
            self.assertNotIn("resume_per_tick", options)

    def test_valid_resume_per_tick(self):
        options = engine_options_from_profile({"schedule": {"resume_per_tick": 5}})
        self.assertEqual(options["resume_per_tick"], 5)

    def test_fully_invalid_cadence_entries_fall_back_to_default(self):
        profile = {
            "followup_cadences": {
                "silence": [["bogus_mode", 5]],
                "payment": "not-a-list",
                "proposal": [["business_days", -1]],
            }
        }
        options = engine_options_from_profile(profile)
        self.assertNotIn("cadences", options)

    def test_partial_invalid_cadences_keep_only_valid_override(self):
        profile = {
            "followup_cadences": {
                "silence": [["business_minutes", 5]],
                "payment": "not-a-list",
            }
        }
        options = engine_options_from_profile(profile)
        self.assertEqual(options["cadences"]["silence"], (("business_minutes", 5),))
        self.assertEqual(options["cadences"]["payment"], CADENCES["payment"])

    def test_therapify_profile_brings_the_reactivation_cadence(self):
        options = engine_options_from_profile(THERAPIFY_PROFILE)
        self.assertEqual(
            options["cadences"]["reactivation"],
            (("business_days", 1), ("business_days", 2), ("business_days", 3)),
        )
        self.assertEqual(options["cadences"]["silence"], CADENCES["silence"])
        self.assertEqual(options["fixed_text_cadences"], frozenset({"reactivation"}))
        self.assertEqual(options["resume_per_tick"], 2)
        self.assertEqual(options["hours"], THERAPIFY_HOURS)

    def test_fixed_text_cadences_missing_or_invalid_is_absent(self):
        for bad in (None, [], ["", "  "], "reactivation", {"reactivation": True}):
            options = engine_options_from_profile({"fixed_text_cadences": bad})
            self.assertNotIn("fixed_text_cadences", options)


class ExistingCadenceBehaviorTests(unittest.TestCase):
    """`note_outbound` com cadência genérica continua funcionando como antes do refactor."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = FollowupEngine(Path(self._tmp.name) / "followups.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_note_outbound_silence_schedules_three_steps(self):
        now = sp(2026, 1, 5, 10, 0)
        self.engine.configure_lead(
            "lead-x",
            automation_enabled=True,
            stage="qualification",
            cadence_kind="silence",
            context_kind="business",
            context_fact="lead perguntou sobre o produto",
            context_source_message_id="msg-1",
            context_verified=True,
            now=now,
        )
        ids = self.engine.note_outbound("lead-x", message_id="bridge-out-1", at=now + timedelta(seconds=1))
        self.assertEqual(len(ids), 3)
        jobs = [j for j in self.engine.get_jobs("lead-x") if j["cadence_kind"] == "silence"]
        self.assertEqual(len(jobs), 3)
        for job in jobs:
            self.assertEqual(job["status"], "pending")


class FixedTextCadenceTests(unittest.TestCase):
    """Cadência de texto literal (Fase 7): sem gate de contexto, com passo pulável."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.engine = FollowupEngine(
            Path(self._tmp.name) / "followups.db",
            **engine_options_from_profile(THERAPIFY_PROFILE),
        )
        self.now = sp(2026, 9, 8, 10, 0)  # terça, dentro do expediente da Therapify

    def _arm(self, chat_id: str, cadence: str) -> list[int]:
        self.engine.configure_lead(
            chat_id,
            automation_enabled=True,
            stage="qualification",
            cadence_kind=cadence,
            now=self.now,
        )
        return self.engine.note_outbound(chat_id, message_id=f"bridge-{chat_id}", at=self.now)

    def test_reactivation_schedules_three_steps_without_context(self):
        self.assertEqual(len(self._arm("lead-r", "reactivation")), 3)
        jobs = self.engine.get_jobs("lead-r")
        self.assertEqual([j["step_no"] for j in jobs], [1, 2, 3])
        self.assertEqual(
            [datetime.fromisoformat(j["due_utc"]) for j in jobs],
            [add_business_days(self.now, days, THERAPIFY_HOURS) for days in (1, 2, 3)],
        )
        self.assertTrue(all(not j["context_fact"] for j in jobs))

    def test_generic_cadence_still_needs_context(self):
        self.assertEqual(self._arm("lead-g", "silence"), [])
        self.assertEqual(self.engine.get_jobs("lead-g"), [])

    def test_lead_inbound_cancels_the_open_steps(self):
        self._arm("lead-i", "reactivation")
        self.engine.note_inbound("lead-i", message_id="m1", at=self.now + timedelta(minutes=5))
        self.assertTrue(all(j["status"] == "cancelled" for j in self.engine.get_jobs("lead-i")))

    def test_skipped_step_does_not_block_the_next_one(self):
        self._arm("lead-s", "reactivation")
        due = {j["step_no"]: datetime.fromisoformat(j["due_utc"]) for j in self.engine.get_jobs("lead-s")}

        first = self.engine.claim_due(now=due[1])[0]
        self.engine.mark_sent(first["id"], "bridge-d1", first["lease_token"], at=due[1])
        second = self.engine.claim_due(now=due[2])[0]
        self.assertEqual(second["step_no"], 2)
        self.assertTrue(self.engine.skip_step(second["id"], second["lease_token"], "downsell_ja_oferecido", at=due[2]))

        # Um passo pulado é um passo resolvido: o toque final sai no vencimento dele.
        self.assertEqual(self.engine.claim_due(now=due[2] + timedelta(minutes=1)), [])
        third = self.engine.claim_due(now=due[3])
        self.assertEqual([j["step_no"] for j in third], [3])
        skipped = next(j for j in self.engine.get_jobs("lead-s") if j["step_no"] == 2)
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["last_error"], "downsell_ja_oferecido")

    def test_skip_step_with_wrong_token_changes_nothing(self):
        self._arm("lead-w", "reactivation")
        due = min(datetime.fromisoformat(j["due_utc"]) for j in self.engine.get_jobs("lead-w"))
        claimed = self.engine.claim_due(now=due)[0]
        self.assertFalse(self.engine.skip_step(claimed["id"], "token-errado", "x", at=due))
        job = next(j for j in self.engine.get_jobs("lead-w") if j["id"] == claimed["id"])
        self.assertEqual(job["status"], "leased")


class ResumeJobTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = FollowupEngine(Path(self._tmp.name) / "followups.db", resume_per_tick=2)

    def tearDown(self):
        self._tmp.cleanup()

    def test_scheduled_once_per_generation(self):
        now = sp(2026, 1, 5, 10, 0)
        due = now + timedelta(minutes=20)
        first = self.engine.schedule_resume("lead-1", due=due, reason="lead_novo", at=now)
        second = self.engine.schedule_resume("lead-1", due=due, reason="lead_novo", at=now)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        jobs = self.engine.get_jobs("lead-1")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["cadence_kind"], "resume")

    def test_survives_note_inbound(self):
        now = sp(2026, 1, 5, 10, 0)
        job_id = self.engine.schedule_resume("lead-2", due=now + timedelta(minutes=20), reason="lead_novo", at=now)
        self.engine.note_inbound("lead-2", message_id="m1", at=now + timedelta(seconds=5))
        job = next(j for j in self.engine.get_jobs("lead-2") if j["id"] == job_id)
        self.assertEqual(job["status"], "pending")

    def test_cancelled_by_note_outbound(self):
        now = sp(2026, 1, 5, 10, 0)
        job_id = self.engine.schedule_resume("lead-3", due=now + timedelta(minutes=20), reason="lead_novo", at=now)
        self.engine.note_outbound("lead-3", message_id="bridge-1", at=now + timedelta(seconds=5))
        job = next(j for j in self.engine.get_jobs("lead-3") if j["id"] == job_id)
        self.assertEqual(job["status"], "cancelled")

    def test_cancelled_by_note_human_takeover(self):
        now = sp(2026, 1, 5, 10, 0)
        job_id = self.engine.schedule_resume("lead-4", due=now + timedelta(minutes=20), reason="lead_novo", at=now)
        self.engine.note_human_takeover("lead-4", at=now + timedelta(seconds=5))
        job = next(j for j in self.engine.get_jobs("lead-4") if j["id"] == job_id)
        self.assertEqual(job["status"], "cancelled")

    def test_refused_for_takeover_and_opt_out(self):
        now = sp(2026, 1, 5, 10, 0)
        self.engine.note_human_takeover("lead-5", at=now)
        self.assertIsNone(self.engine.schedule_resume("lead-5", due=now + timedelta(minutes=5), reason="x", at=now))

        self.engine.configure_lead("lead-6", opt_out=True, now=now)
        self.assertIsNone(self.engine.schedule_resume("lead-6", due=now + timedelta(minutes=5), reason="x", at=now))

    def test_claim_due_outside_business_time_reschedules(self):
        off_hours = sp(2026, 1, 3, 20, 0)  # sábado à noite, fora do DEFAULT_HOURS
        self.engine.schedule_resume("lead-7", due=off_hours, reason="lead_novo", at=off_hours)
        claimed = self.engine.claim_due(now=off_hours)
        self.assertEqual(claimed, [])
        jobs = self.engine.get_jobs("lead-7")
        self.assertEqual(jobs[0]["status"], "pending")
        expected_due = next_business_time(off_hours, DEFAULT_HOURS)
        self.assertEqual(datetime.fromisoformat(jobs[0]["due_utc"]), expected_due)

    def test_per_tick_cap(self):
        now = sp(2026, 1, 5, 10, 0)
        for i in range(3):
            self.engine.schedule_resume(f"lead-cap-{i}", due=now, reason="lead_novo", at=now)
        claimed = self.engine.claim_due(now=now, limit=20)
        resume_claimed = [c for c in claimed if c["cadence_kind"] == "resume"]
        self.assertEqual(len(resume_claimed), 2)
        pending_left = sum(
            1
            for i in range(3)
            for j in self.engine.get_jobs(f"lead-cap-{i}")
            if j["status"] == "pending"
        )
        self.assertEqual(pending_left, 1)

    def test_off_days_ok_resume_goes_out_on_saturday_within_hours(self):
        # Fase 1 de Lead Novo pode sair no sábado dentro da janela (DEFAULT_HOURS 8h-18h)
        saturday = sp(2026, 1, 3, 10, 0)
        self.engine.schedule_resume("lead-wk", due=saturday, reason="lead_novo", at=saturday, off_days_ok=True)
        claimed = self.engine.claim_due(now=saturday)
        self.assertEqual([c["chat_id"] for c in claimed], ["lead-wk"])
        self.assertTrue(self.engine.revalidate_claim(claimed[0]["id"], claimed[0]["lease_token"], now=saturday))

    def test_off_days_ok_resume_at_night_waits_for_next_morning_even_on_weekend(self):
        saturday_night = sp(2026, 1, 3, 20, 0)
        self.engine.schedule_resume("lead-wk2", due=saturday_night, reason="lead_novo", at=saturday_night, off_days_ok=True)
        self.assertEqual(self.engine.claim_due(now=saturday_night), [])
        job = self.engine.get_jobs("lead-wk2")[0]
        self.assertEqual(datetime.fromisoformat(job["due_utc"]), sp(2026, 1, 4, 8, 0))  # domingo 8h

    def test_resume_without_off_days_ok_waits_for_monday(self):
        saturday = sp(2026, 1, 3, 10, 0)
        self.engine.schedule_resume("lead-wk3", due=saturday, reason="fila_manha", at=saturday)
        self.assertEqual(self.engine.claim_due(now=saturday), [])
        job = self.engine.get_jobs("lead-wk3")[0]
        self.assertEqual(datetime.fromisoformat(job["due_utc"]), sp(2026, 1, 5, 8, 0))  # segunda 8h

    def test_note_outbound_resume_raises(self):
        now = sp(2026, 1, 5, 10, 0)
        with self.assertRaises(ValueError):
            self.engine.note_outbound("lead-8", message_id="m", cadence_kind="resume", at=now)

    def test_second_schedule_after_note_inbound_still_one_open_job(self):
        now = sp(2026, 1, 5, 10, 0)
        first = self.engine.schedule_resume("lead-9", due=now + timedelta(minutes=20), reason="lead_novo", at=now)
        self.engine.note_inbound("lead-9", message_id="m1", at=now + timedelta(minutes=1))
        second = self.engine.schedule_resume(
            "lead-9", due=now + timedelta(minutes=25), reason="diagnostic", at=now + timedelta(minutes=1)
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        jobs = [j for j in self.engine.get_jobs("lead-9") if j["cadence_kind"] == "resume"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], first)

    def test_extend_cap_s_pushes_due_later(self):
        now = sp(2026, 1, 5, 10, 0)
        job_id = self.engine.schedule_resume(
            "lead-10", due=now + timedelta(seconds=120), reason="diagnostic", at=now
        )
        extended = self.engine.schedule_resume(
            "lead-10",
            due=now + timedelta(seconds=200),
            reason="diagnostic",
            at=now + timedelta(seconds=60),
            extend_cap_s=300,
        )
        self.assertEqual(extended, job_id)
        job = next(j for j in self.engine.get_jobs("lead-10") if j["id"] == job_id)
        self.assertEqual(datetime.fromisoformat(job["due_utc"]), now + timedelta(seconds=200))

    def test_extend_cap_s_respects_cap(self):
        now = sp(2026, 1, 5, 10, 0)
        job_id = self.engine.schedule_resume("lead-11", due=now + timedelta(seconds=60), reason="diagnostic", at=now)
        extended = self.engine.schedule_resume(
            "lead-11",
            due=now + timedelta(seconds=600),
            reason="diagnostic",
            at=now + timedelta(seconds=60),
            extend_cap_s=300,
        )
        self.assertEqual(extended, job_id)
        job = next(j for j in self.engine.get_jobs("lead-11") if j["id"] == job_id)
        self.assertEqual(datetime.fromisoformat(job["due_utc"]), now + timedelta(seconds=300))

    def test_extend_on_leased_job_returns_none_and_leaves_due(self):
        now = sp(2026, 1, 5, 10, 0)
        job_id = self.engine.schedule_resume("lead-12", due=now, reason="diagnostic", at=now)
        claimed = self.engine.claim_due(now=now)
        self.assertEqual([c["id"] for c in claimed], [job_id])
        extended = self.engine.schedule_resume(
            "lead-12", due=now + timedelta(seconds=999), reason="diagnostic", at=now, extend_cap_s=300
        )
        self.assertIsNone(extended)
        job = next(j for j in self.engine.get_jobs("lead-12") if j["id"] == job_id)
        self.assertEqual(job["status"], "leased")
        self.assertEqual(datetime.fromisoformat(job["due_utc"]), now)

    def test_cancel_claimed_marks_cancelled_and_keeps_automation(self):
        now = sp(2026, 1, 5, 10, 0)
        self.engine.configure_lead("lead-13", automation_enabled=True, now=now)
        job_id = self.engine.schedule_resume("lead-13", due=now, reason="diagnostic", at=now)
        claimed = self.engine.claim_due(now=now)
        lease_token = claimed[0]["lease_token"]
        result = self.engine.cancel_claimed(job_id, lease_token, "no_pending_message", at=now)
        self.assertTrue(result)
        job = next(j for j in self.engine.get_jobs("lead-13") if j["id"] == job_id)
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["last_error"], "no_pending_message")
        lead = self.engine.get_lead("lead-13")
        self.assertTrue(bool(lead["automation_enabled"]))

    def test_cancel_claimed_wrong_token_returns_false(self):
        now = sp(2026, 1, 5, 10, 0)
        job_id = self.engine.schedule_resume("lead-14", due=now, reason="diagnostic", at=now)
        self.engine.claim_due(now=now)
        result = self.engine.cancel_claimed(job_id, "wrong-token", "no_pending_message", at=now)
        self.assertFalse(result)
        job = next(j for j in self.engine.get_jobs("lead-14") if j["id"] == job_id)
        self.assertEqual(job["status"], "leased")


if __name__ == "__main__":
    unittest.main()
