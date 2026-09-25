"""Config-driven booking eligibility classification.

The policy values belong to client configuration. This module only interprets
the shared policy schema and never claims that an appointment was created.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


# Professional identifiers are configured per clinic, so the template does
# not impose clinic-specific names or a closed list.
Professional = str


class Disposition(str, Enum):
    AUTO_BOOK = "auto_book"
    TEAM = "team"


@dataclass(frozen=True)
class Appointment:
    """Appointment details supplied for a reschedule.

    The caller must verify these details against the live appointment; making
    this record does not establish that the appointment exists.
    """

    appointment_type: str | None
    professional: str
    duration_minutes: int


@dataclass(frozen=True)
class BookingDecision:
    disposition: Disposition
    appointment_type: str | None
    duration_minutes: int | None
    professional: str | None
    eligible_professionals: tuple[str, ...]
    reason_code: str

    @property
    def auto_book(self) -> bool:
        return self.disposition is Disposition.AUTO_BOOK


_KNOWN_REQUIREMENTS = {"established_patient", "in_treatment", "no_added_procedure", "chart_verified"}
_TYPE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


def _appointment_type(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if _TYPE_KEY.fullmatch(normalized) else None


def _professional(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def _team_result(
    appointment_type: str | None,
    duration: int | None = None,
    eligible: tuple[str, ...] = (),
    reason: str = "policy_unavailable",
    professional: str | None = None,
) -> BookingDecision:
    return BookingDecision(Disposition.TEAM, appointment_type, duration, professional, eligible, reason)


def _rule(policy: Mapping[str, Any] | None, appointment_type: str):
    """Return parsed rule fields, or ``None`` for missing/malformed config."""
    if not isinstance(policy, Mapping):
        return None
    appointments = policy.get("appointments")
    if not isinstance(appointments, Mapping):
        return None
    raw = appointments.get(appointment_type)
    if not isinstance(raw, Mapping):
        return None

    duration = raw.get("duration_minutes")
    if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0):
        return None
    professionals = raw.get("eligible_professionals")
    if not isinstance(professionals, list) or any(not isinstance(value, str) or not value.strip() for value in professionals):
        return None
    eligible = tuple(value.strip().lower() for value in professionals)
    if len(set(eligible)) != len(eligible):
        return None
    auto_book = raw.get("auto_book")
    if not isinstance(auto_book, bool):
        return None
    requires = raw.get("requires", [])
    if not isinstance(requires, list) or any(value not in _KNOWN_REQUIREMENTS for value in requires):
        return None
    reason = raw.get("reason_code", "team_confirmation_required")
    if not isinstance(reason, str) or not reason.strip():
        return None
    if auto_book and (duration is None or not eligible):
        return None
    return duration, eligible, auto_book, tuple(requires), reason.strip()


def _requirements_met(requirements: tuple[str, ...], context: Mapping[str, bool]) -> bool:
    return all(context.get(requirement) is True for requirement in requirements)


def classify_booking(
    appointment_type: str | None = None,
    *,
    policy: Mapping[str, Any] | None = None,
    professional: str | None = None,
    established_patient: bool = False,
    in_treatment: bool = False,
    no_added_procedure: bool = False,
    chart_verified: bool = False,
    urgent: bool = False,
    emergency: bool = False,
    reschedule_of: Appointment | None = None,
) -> BookingDecision:
    """Classify a request using a client policy mapping.

    Missing, invalid, or unconfigured type keys and malformed policy data
    always route to the team. For reschedules, the caller must first verify
    the original details against the live appointment.
    """
    requested_type = _appointment_type(appointment_type)
    requested_professional = _professional(professional)

    if requested_type is None:
        return _team_result(None, reason="unknown_type", professional=requested_professional)
    if professional is not None and requested_professional is None:
        return _team_result(requested_type, reason="professional_unrecognized")
    if urgent or emergency:
        return _team_result(requested_type, reason="urgent_team_handoff", professional=requested_professional)

    if reschedule_of is not None:
        original_type = _appointment_type(reschedule_of.appointment_type)
        original_professional = _professional(reschedule_of.professional)
        original_rule = _rule(policy, original_type) if original_type is not None else None
        reschedule_policy = policy.get("reschedule") if isinstance(policy, Mapping) else None
        team_only = reschedule_policy.get("team_only_types") if isinstance(reschedule_policy, Mapping) else None
        if (
            original_type is None
            or original_rule is None
            or not isinstance(reschedule_policy, Mapping)
            or reschedule_policy.get("auto_book_known_original") is not True
            or not isinstance(team_only, list)
            or any(not isinstance(value, str) for value in team_only)
        ):
            return _team_result(original_type, reason="original_appointment_unverified", professional=original_professional)
        _, eligible, _, _, reason = original_rule
        if (
            original_professional is None
            or original_professional not in eligible
            or not isinstance(reschedule_of.duration_minutes, int)
            or isinstance(reschedule_of.duration_minutes, bool)
            or reschedule_of.duration_minutes <= 0
        ):
            return _team_result(original_type, reason="original_appointment_unverified", professional=original_professional)
        if requested_professional is not None and requested_professional != original_professional:
            return _team_result(original_type, reschedule_of.duration_minutes, (original_professional,), "professional_mismatch", original_professional)
        if original_type in team_only:
            return _team_result(original_type, reschedule_of.duration_minutes, (original_professional,), reason, original_professional)
        return BookingDecision(
            Disposition.AUTO_BOOK,
            original_type,
            reschedule_of.duration_minutes,
            original_professional,
            (original_professional,),
            "reschedule_preserves_original_appointment",
        )

    rule = _rule(policy, requested_type)
    if rule is None:
        appointments = policy.get("appointments") if isinstance(policy, Mapping) else None
        reason = "unknown_type" if isinstance(appointments, Mapping) and requested_type not in appointments else "policy_unavailable"
        return _team_result(requested_type, reason=reason, professional=requested_professional)
    duration, eligible, auto_book, requires, reason = rule
    if requested_professional is not None and requested_professional not in eligible:
        return _team_result(requested_type, duration, eligible, "professional_mismatch", requested_professional)
    if not auto_book or not _requirements_met(requires, {
        "established_patient": established_patient is True,
        "in_treatment": in_treatment is True,
        "no_added_procedure": no_added_procedure is True,
        "chart_verified": chart_verified is True,
    }):
        return _team_result(requested_type, duration, eligible, reason, requested_professional)

    return BookingDecision(
        Disposition.AUTO_BOOK,
        requested_type,
        duration,
        requested_professional,
        eligible,
        "eligible_for_auto_booking",
    )
