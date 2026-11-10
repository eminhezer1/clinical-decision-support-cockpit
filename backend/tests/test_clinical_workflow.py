import unittest

import aiosqlite

from app.database import CREATE_TABLES, SEED_RULES
from app.engine.audit_logger import (
    ApprovalNotAllowedError,
    GENESIS_HASH,
    record_doctor_approval,
    verify_audit_chain,
)
from app.engine.safety_filter import enforce_clinical_safety
from app.schemas import (
    AnalyzeRequestPayload,
    ClinicalDecisionOutput,
    DoctorApprovalRequest,
    MedicationProposal,
)


def create_case() -> AnalyzeRequestPayload:
    return AnalyzeRequestPayload.model_validate(
        {
            "session_id": "test-session",
            "patient_context": {
                "patient_tc_hash": "a" * 64,
                "age": 55,
                "sex": "M",
                "weight_kg": 80,
                "pregnancy_status": False,
                "egfr_ml_min": 45,
                "known_allergies": [],
                "allergy_history_reviewed": True,
                "chronic_conditions": [],
            },
            "vitals": {
                "temperature_c": 36.8,
                "bp_systolic": 125,
                "bp_diastolic": 78,
                "heart_rate_bpm": 72,
                "spo2_percent": 98,
            },
            "chief_complaint": "Test için sentetik klinik başvuru.",
            "lab_results": [],
            "clinical_context": "",
        }
    )


def medication(
    drug_name: str = "Losartan",
    atc_code: str = "C09CA01",
    daily_dose_mg: float = 50,
) -> MedicationProposal:
    return MedicationProposal(
        atc_code=atc_code,
        drug_name=drug_name,
        dosage="Günde bir kez",
        daily_dose_mg=daily_dose_mg,
        duration_days=30,
        box_count=1,
        rationale="Test amacıyla yapılandırılmış öneri.",
    )


def create_decision(
    prescription_protocol: list[MedicationProposal] | None = None,
) -> ClinicalDecisionOutput:
    return ClinicalDecisionOutput(
        clinical_status="READY_FOR_PRESCRIPTION",
        clinical_summary="Test için yapılandırılmış klinik özet.",
        differential_analysis=[
            {
                "rank": 1,
                "icd10_code": "I10",
                "condition_name": "Esansiyel hipertansiyon",
                "probability_score": 0.8,
                "assessment": "SUSPECTED",
                "clinical_reasoning": "Sentetik test gerekçesi.",
                "evidence": ["Test verisi."],
                "remaining_uncertainty": "",
            }
        ],
        required_tests=[],
        missing_clinical_information=[],
        clinical_blockers=[],
        red_flags_detected=[],
        recommended_workup=[],
        prescription_protocol=prescription_protocol or [],
    )


class ClinicalSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = await aiosqlite.connect(":memory:")
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(CREATE_TABLES)
        await self.db.executemany(
            """
            INSERT INTO drug_safety_rules (
                atc_code, drug_name, allergy_group, min_egfr_threshold,
                max_daily_dose_mg, pregnancy_category
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            SEED_RULES,
        )
        await self.db.commit()

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_ace_arb_below_egfr_60_warns_without_automatic_block(self) -> None:
        output, badges = await enforce_clinical_safety(
            self.db, create_case(), create_decision([medication()])
        )

        self.assertEqual(output.clinical_status, "READY_FOR_PRESCRIPTION")
        self.assertEqual(len(output.prescription_protocol), 1)
        self.assertTrue(badges.renal_check_passed)
        self.assertEqual(len(badges.warning_flags), 1)
        self.assertIn("eGFR 45", badges.warning_flags[0])

    async def test_unknown_drug_is_blocked_and_never_implicitly_approved(self) -> None:
        output, badges = await enforce_clinical_safety(
            self.db,
            create_case(),
            create_decision([medication("Unlisted Drug", "UNKNOWN")]),
        )

        self.assertEqual(output.clinical_status, "NEEDS_TESTS")
        self.assertEqual(output.prescription_protocol, [])
        self.assertFalse(badges.allergy_check_passed)
        self.assertTrue(any("güvenlik kuralı bulunamadı" in item for item in output.clinical_blockers))

    async def test_low_egfr_blocks_medicine_below_its_rule_threshold(self) -> None:
        case = create_case().model_copy(deep=True)
        case.patient_context.egfr_ml_min = 45

        output, badges = await enforce_clinical_safety(
            self.db,
            case,
            create_decision(
                [
                    medication(
                        "Ibuprofen",
                        "M01AE01",
                        400,
                    )
                ]
            ),
        )

        self.assertEqual(output.clinical_status, "NEEDS_TESTS")
        self.assertEqual(output.prescription_protocol, [])
        self.assertFalse(badges.renal_check_passed)

    async def test_approval_rejects_sessions_waiting_for_tests(self) -> None:
        case = create_case()
        needs_tests = ClinicalDecisionOutput(
            clinical_status="NEEDS_TESTS",
            clinical_summary="Ek test gereklidir.",
            differential_analysis=create_decision().differential_analysis,
            required_tests=[
                {
                    "test_name": "Kreatinin",
                    "category": "LAB",
                    "purpose": "Renal fonksiyon değerlendirmesi.",
                    "urgency": "ROUTINE",
                }
            ],
            missing_clinical_information=[],
            clinical_blockers=[],
            red_flags_detected=[],
            recommended_workup=[],
            prescription_protocol=[],
        )
        await self._insert_session(case, needs_tests)
        request = DoctorApprovalRequest(
            session_id=case.session_id,
            doctor_id="test-doctor",
            doctor_diploma_no="test-diploma",
            selected_diagnosis_rank=1,
            approval_action="APPROVED_AS_IS",
            modified_prescription=None,
            review_duration_ms=1000,
        )

        with self.assertRaises(ApprovalNotAllowedError):
            await record_doctor_approval(self.db, request)
        audit_rows = await (
            await self.db.execute("SELECT COUNT(*) AS count FROM doctor_approvals_audit")
        ).fetchone()
        self.assertEqual(audit_rows["count"], 0)

    async def test_modified_prescription_is_rechecked_before_audit(self) -> None:
        case = create_case()
        output = create_decision([medication()])
        await self._insert_session(case, output)
        request = DoctorApprovalRequest(
            session_id=case.session_id,
            doctor_id="test-doctor",
            doctor_diploma_no="test-diploma",
            selected_diagnosis_rank=1,
            approval_action="MODIFIED_AND_APPROVED",
            modified_prescription=[medication("Unlisted Drug", "UNKNOWN")],
            review_duration_ms=1000,
        )

        with self.assertRaises(ApprovalNotAllowedError):
            await record_doctor_approval(self.db, request)
        audit_rows = await (
            await self.db.execute("SELECT COUNT(*) AS count FROM doctor_approvals_audit")
        ).fetchone()
        self.assertEqual(audit_rows["count"], 0)

    async def test_successful_approval_appends_a_verifiable_hash(self) -> None:
        case = create_case()
        await self._insert_session(case, create_decision([medication()]))
        request = DoctorApprovalRequest(
            session_id=case.session_id,
            doctor_id="test-doctor",
            doctor_diploma_no="test-diploma",
            selected_diagnosis_rank=1,
            approval_action="APPROVED_AS_IS",
            modified_prescription=None,
            review_duration_ms=1000,
        )

        receipt = await record_doctor_approval(self.db, request)

        self.assertEqual(receipt["prev_hash"], GENESIS_HASH)
        self.assertEqual(len(receipt["record_hash"]), 64)
        self.assertTrue(await verify_audit_chain(self.db))

    async def _insert_session(
        self,
        case: AnalyzeRequestPayload,
        output: ClinicalDecisionOutput,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO clinical_sessions (
                session_id, patient_hash, input_payload, ai_output_payload,
                model_version, processing_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                case.session_id,
                case.patient_context.patient_tc_hash,
                case.model_dump_json(),
                output.model_dump_json(),
                "test-model",
                1,
            ),
        )
        await self.db.commit()


if __name__ == "__main__":
    unittest.main()
