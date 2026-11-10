import json
import unittest
from unittest.mock import AsyncMock, patch

from app.engine.clinical_analyzer import (
    OllamaInferenceError,
    _repair_decision_state,
    generate_clinical_decision,
)
from app.schemas import AnalyzeRequestPayload


def create_case() -> AnalyzeRequestPayload:
    return AnalyzeRequestPayload(
        session_id="analyzer-test",
        patient_context={
            "patient_tc_hash": "d" * 64,
            "age": 45,
            "sex": "M",
            "weight_kg": 75,
            "pregnancy_status": False,
            "egfr_ml_min": 90,
            "known_allergies": [],
            "allergy_history_reviewed": True,
            "chronic_conditions": [],
        },
        vitals={
            "temperature_c": 36.8,
            "bp_systolic": 120,
            "bp_diastolic": 80,
            "heart_rate_bpm": 72,
            "spo2_percent": 98,
        },
        chief_complaint="Synthetic analyzer test request.",
    )


def needs_tests_without_reason() -> str:
    return json.dumps(
        {
            "clinical_status": "NEEDS_TESTS",
            "clinical_summary": "Ek değerlendirme gerekiyor.",
            "differential_analysis": [
                {
                    "rank": 1,
                    "icd10_code": "R50.9",
                    "condition_name": "Ateş",
                    "probability_score": 0.5,
                    "assessment": "SUSPECTED",
                    "clinical_reasoning": "Sentetik test girdisi.",
                    "evidence": [],
                    "remaining_uncertainty": "",
                }
            ],
            "required_tests": [],
            "missing_clinical_information": [],
            "clinical_blockers": [],
            "red_flags_detected": [],
            "recommended_workup": [],
            "prescription_protocol": [],
        }
    )


class ClinicalAnalyzerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unjustified_needs_tests_is_repaired_without_second_model_call(self) -> None:
        content = needs_tests_without_reason()
        repaired = _repair_decision_state(content)

        self.assertIsNotNone(repaired)
        assert repaired is not None
        self.assertEqual(repaired.clinical_status, "NEEDS_TESTS")
        self.assertEqual(repaired.prescription_protocol, [])
        self.assertTrue(repaired.clinical_blockers)

        with patch(
            "app.engine.clinical_analyzer._request_ollama",
            new_callable=AsyncMock,
            return_value=content,
        ) as request:
            result, _, _ = await generate_clinical_decision(create_case())

        self.assertEqual(result.clinical_status, "NEEDS_TESTS")
        self.assertTrue(result.clinical_blockers)
        self.assertEqual(request.await_count, 1)

    async def test_invalid_state_that_cannot_be_repaired_raises_service_error(self) -> None:
        content = needs_tests_without_reason().replace(
            '"clinical_status": "NEEDS_TESTS"',
            '"clinical_status": "INVALID"',
        )
        with patch(
            "app.engine.clinical_analyzer._request_ollama",
            new_callable=AsyncMock,
            return_value=content,
        ) as request:
            with self.assertRaises(OllamaInferenceError):
                await generate_clinical_decision(create_case())

        self.assertEqual(request.await_count, 2)

    def test_needs_tests_repair_removes_any_proposed_prescription(self) -> None:
        data = json.loads(needs_tests_without_reason())
        data["prescription_protocol"] = [
            {
                "atc_code": "N02BE01",
                "drug_name": "Paracetamol",
                "dosage": "daily",
                "daily_dose_mg": 500,
                "duration_days": 3,
                "box_count": 1,
                "rationale": "Synthetic test data.",
            }
        ]

        repaired = _repair_decision_state(json.dumps(data))

        self.assertIsNotNone(repaired)
        assert repaired is not None
        self.assertEqual(repaired.prescription_protocol, [])
        self.assertTrue(repaired.clinical_blockers)


if __name__ == "__main__":
    unittest.main()
