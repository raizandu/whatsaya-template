import unittest

from appointment_policy import Appointment, Disposition, classify_booking


# Representative client config fixture. The shared module contains no clinic
# names, durations, staff lists, or auto-booking choices.
CUIDAR_POLICY = {
    "appointments": {
        "general_evaluation": {"duration_minutes": 40, "eligible_professionals": ["liliane", "bruna"], "auto_book": True},
        "orthodontic_evaluation": {"duration_minutes": 30, "eligible_professionals": ["bruna"], "auto_book": True},
        "invisible_aligner_evaluation": {"duration_minutes": 30, "eligible_professionals": ["bruna"], "auto_book": True},
        "maintenance": {"duration_minutes": 30, "eligible_professionals": ["bruna"], "auto_book": True, "requires": ["established_patient", "no_added_procedure"], "reason_code": "maintenance_requires_eligibility"},
        "cleaning": {"duration_minutes": 60, "eligible_professionals": ["liliane", "bruna"], "auto_book": True, "requires": ["established_patient", "in_treatment"], "reason_code": "cleaning_requires_eligibility"},
        "restoration": {"duration_minutes": 60, "eligible_professionals": ["liliane", "bruna"], "auto_book": True, "requires": ["established_patient", "chart_verified"], "reason_code": "restoration_requires_eligibility"},
        "root_canal": {"duration_minutes": 90, "eligible_professionals": ["liliane"], "auto_book": False, "reason_code": "root_canal_team_confirmation"},
        "prosthesis": {"duration_minutes": 60, "eligible_professionals": ["liliane"], "auto_book": False, "reason_code": "prosthesis_team_confirmation"},
        "urgent": {"duration_minutes": None, "eligible_professionals": [], "auto_book": False, "reason_code": "urgent_team_handoff"},
        "unspecified": {"duration_minutes": None, "eligible_professionals": [], "auto_book": False, "reason_code": "unspecified_team_review"},
    },
    "reschedule": {"auto_book_known_original": True, "team_only_types": ["prosthesis", "urgent", "unspecified"]},
}


class BookingPolicyTests(unittest.TestCase):
    def classify(self, appointment_type=None, **kwargs):
        return classify_booking(appointment_type, policy=CUIDAR_POLICY, **kwargs)

    def test_general_evaluation_is_40_minutes_and_allows_both_professionals(self):
        result = self.classify("general_evaluation")
        self.assertEqual(result.disposition, Disposition.AUTO_BOOK)
        self.assertEqual(result.duration_minutes, 40)
        self.assertEqual(result.eligible_professionals, ("liliane", "bruna"))

    def test_orthodontic_and_invisible_evaluations_are_bruna_only(self):
        for appointment_type in ("orthodontic_evaluation", "invisible_aligner_evaluation"):
            with self.subTest(appointment_type=appointment_type):
                result = self.classify(appointment_type)
                self.assertTrue(result.auto_book)
                self.assertEqual(result.duration_minutes, 30)
                self.assertEqual(result.eligible_professionals, ("bruna",))
                self.assertEqual(self.classify(appointment_type, professional="liliane").reason_code, "professional_mismatch")

    def test_maintenance_requires_established_patient_and_no_added_procedure(self):
        self.assertFalse(self.classify("maintenance").auto_book)
        self.assertFalse(self.classify("maintenance", established_patient=True).auto_book)
        eligible = self.classify("maintenance", established_patient=True, no_added_procedure=True)
        self.assertTrue(eligible.auto_book)
        self.assertEqual(eligible.duration_minutes, 30)

    def test_cleaning_requires_confirmed_established_in_treatment_status(self):
        self.assertFalse(self.classify("cleaning").auto_book)
        self.assertFalse(self.classify("cleaning", established_patient=True).auto_book)
        eligible = self.classify("cleaning", established_patient=True, in_treatment=True)
        self.assertTrue(eligible.auto_book)
        self.assertEqual(eligible.duration_minutes, 60)

    def test_restoration_auto_books_only_after_established_patient_chart_verification(self):
        self.assertFalse(self.classify("restoration").auto_book)
        self.assertFalse(self.classify("restoration", established_patient=True).auto_book)
        result = self.classify("restoration", established_patient=True, chart_verified=True)
        self.assertTrue(result.auto_book)
        self.assertEqual(result.duration_minutes, 60)
        self.assertEqual(result.eligible_professionals, ("liliane", "bruna"))

    def test_manual_categories_keep_configured_duration_and_professional(self):
        cases = (
            ("root_canal", 90, ("liliane",)),
            ("prosthesis", 60, ("liliane",)),
            ("unspecified", None, ()),
            ("urgent", None, ()),
        )
        for appointment_type, duration, eligible in cases:
            with self.subTest(appointment_type=appointment_type):
                result = self.classify(appointment_type)
                self.assertFalse(result.auto_book)
                self.assertEqual(result.duration_minutes, duration)
                self.assertEqual(result.eligible_professionals, eligible)

    def test_urgency_and_emergency_flags_override_auto_eligibility(self):
        for kwargs in ({"urgent": True}, {"emergency": True}):
            with self.subTest(kwargs=kwargs):
                result = self.classify("general_evaluation", **kwargs)
                self.assertEqual(result.disposition, Disposition.TEAM)
                self.assertEqual(result.reason_code, "urgent_team_handoff")

    def test_missing_or_malformed_config_fails_closed(self):
        self.assertEqual(classify_booking("general_evaluation").reason_code, "policy_unavailable")
        malformed = {"appointments": {"general_evaluation": {"auto_book": True}}}
        self.assertFalse(classify_booking("general_evaluation", policy=malformed).auto_book)

    def test_unknown_type_and_professional_mismatch_route_to_team(self):
        self.assertEqual(self.classify("something new").reason_code, "unknown_type")
        self.assertEqual(self.classify().reason_code, "unknown_type")
        mismatch = self.classify("maintenance", professional="liliane")
        self.assertEqual(mismatch.reason_code, "professional_mismatch")
        unrecognized = self.classify("general_evaluation", professional="someone else")
        self.assertEqual(unrecognized.reason_code, "professional_mismatch")

    def test_configured_normalized_type_keys_need_no_template_enum(self):
        policy = {
            **CUIDAR_POLICY,
            "appointments": {
                **CUIDAR_POLICY["appointments"],
                "custom_review_2": {
                    "duration_minutes": 25,
                    "eligible_professionals": ["provider_a"],
                    "auto_book": True,
                },
            },
        }
        result = classify_booking(" Custom_Review_2 ", policy=policy, professional="provider_a")
        self.assertTrue(result.auto_book)
        self.assertEqual(result.appointment_type, "custom_review_2")
        self.assertEqual(classify_booking("invalid-key", policy=policy).reason_code, "unknown_type")

    def test_reschedule_preserves_original_details_and_rejects_changes(self):
        original = Appointment("general_evaluation", "liliane", 45)
        result = self.classify("unspecified", professional="liliane", reschedule_of=original)
        self.assertTrue(result.auto_book)
        self.assertEqual(result.appointment_type, "general_evaluation")
        self.assertEqual(result.professional, "liliane")
        self.assertEqual(result.duration_minutes, 45)
        self.assertEqual(
            self.classify("general_evaluation", professional="bruna", reschedule_of=original).reason_code,
            "professional_mismatch",
        )

    def test_team_only_or_unverified_original_reschedule_routes_to_team(self):
        for kind in ("prosthesis", "urgent", "unspecified"):
            original = Appointment(kind, "liliane", 60)
            with self.subTest(kind=kind):
                self.assertFalse(self.classify(kind, reschedule_of=original).auto_book)
        bad_duration = Appointment("general_evaluation", "liliane", 0)
        self.assertEqual(self.classify("general_evaluation", reschedule_of=bad_duration).reason_code,
                         "original_appointment_unverified")


if __name__ == "__main__":
    unittest.main()
