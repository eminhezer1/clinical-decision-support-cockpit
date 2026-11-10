import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.engine.safety_filter import enforce_clinical_safety
from app.schemas import (
    AnalyzeRequestPayload,
    ClinicalDecisionOutput,
    DoctorApprovalRequest,
)

GENESIS_HASH = "0" * 64


class ApprovalNotAllowedError(ValueError):
    """The requested approval is not permitted by the stored clinical decision."""


def _approval_hash(
    *,
    session_id: str,
    doctor_id: str,
    doctor_diploma_no: str,
    selected_diagnosis_rank: int,
    modified_prescription: str | None,
    approval_action: str,
    review_duration_ms: int,
    ai_output_payload: str,
    approved_at: str,
    previous_hash: str,
) -> str:
    event = {
        "session_id": session_id,
        "doctor_id": doctor_id,
        "doctor_diploma_no": doctor_diploma_no,
        "selected_diagnosis_rank": selected_diagnosis_rank,
        "modified_prescription": modified_prescription,
        "approval_action": approval_action,
        "review_duration_ms": review_duration_ms,
        "ai_output_payload": ai_output_payload,
        "approved_at": approved_at,
        "prev_record_hash": previous_hash,
    }
    canonical_event = json.dumps(
        event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical_event.encode("utf-8")).hexdigest()


async def record_doctor_approval(
    db: aiosqlite.Connection, request: DoctorApprovalRequest
) -> dict[str, Any]:
    await db.execute("BEGIN IMMEDIATE")
    try:
        session_cursor = await db.execute(
            "SELECT ai_output_payload FROM clinical_sessions WHERE session_id = ?",
            (request.session_id,),
        )
        session = await session_cursor.fetchone()
        if session is None:
            raise LookupError(f"Clinical session not found: {request.session_id}")

        clinical_output = ClinicalDecisionOutput.model_validate_json(
            session["ai_output_payload"]
        )
        if not any(
            diagnosis.rank == request.selected_diagnosis_rank
            for diagnosis in clinical_output.differential_analysis
        ):
            raise ApprovalNotAllowedError(
                "Seçilen tanı analiz oturumunda bulunamadı."
            )

        if (
            request.approval_action == "REJECTED"
            and request.modified_prescription is not None
        ):
            raise ApprovalNotAllowedError(
                "Reddedilen karara reçete değişikliği eklenemez."
            )

        if request.approval_action != "REJECTED":
            if clinical_output.clinical_status != "READY_FOR_PRESCRIPTION":
                raise ApprovalNotAllowedError(
                    "Test veya klinik bilgi bekleyen analiz onaylanamaz."
                )
            if request.approval_action == "MODIFIED_AND_APPROVED":
                if request.modified_prescription is None:
                    raise ApprovalNotAllowedError(
                        "Değiştirilmiş onay için reçete listesi gereklidir."
                    )
            elif request.modified_prescription is not None:
                raise ApprovalNotAllowedError(
                    "Değiştirilmemiş onay yeni bir reçete listesi içeremez."
                )

            input_cursor = await db.execute(
                "SELECT input_payload FROM clinical_sessions WHERE session_id = ?",
                (request.session_id,),
            )
            input_row = await input_cursor.fetchone()
            if input_row is None:
                raise LookupError(f"Clinical session input not found: {request.session_id}")
            clinical_input = AnalyzeRequestPayload.model_validate_json(
                input_row["input_payload"]
            )
            decision_to_check = clinical_output.model_copy(deep=True)
            if request.modified_prescription is not None:
                decision_to_check.prescription_protocol = list(
                    request.modified_prescription
                )
            rechecked_output, safety_badges = await enforce_clinical_safety(
                db, clinical_input, decision_to_check
            )
            if (
                rechecked_output.clinical_status != "READY_FOR_PRESCRIPTION"
                or rechecked_output.clinical_blockers
                or rechecked_output.missing_clinical_information
                or rechecked_output.red_flags_detected
                or not all(
                    (
                        safety_badges.allergy_check_passed,
                        safety_badges.renal_check_passed,
                        safety_badges.pregnancy_check_passed,
                        safety_badges.dose_check_passed,
                    )
                )
            ):
                raise ApprovalNotAllowedError(
                    "Reçete güvenlik kontrollerini geçemedi; onay kaydedilmedi."
                )

        previous_cursor = await db.execute(
            "SELECT current_record_hash FROM doctor_approvals_audit "
            "ORDER BY audit_id DESC LIMIT 1"
        )
        previous = await previous_cursor.fetchone()
        previous_hash = previous["current_record_hash"] if previous else GENESIS_HASH
        approved_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        ai_output = session["ai_output_payload"]
        prescription = (
            json.dumps(
                [item.model_dump(mode="json") for item in request.modified_prescription],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if request.modified_prescription is not None
            else None
        )
        current_hash = _approval_hash(
            session_id=request.session_id,
            doctor_id=request.doctor_id,
            doctor_diploma_no=request.doctor_diploma_no,
            selected_diagnosis_rank=request.selected_diagnosis_rank,
            modified_prescription=prescription,
            approval_action=request.approval_action,
            review_duration_ms=request.review_duration_ms,
            ai_output_payload=ai_output,
            approved_at=approved_at,
            previous_hash=previous_hash,
        )
        cursor = await db.execute(
            """
            INSERT INTO doctor_approvals_audit (
                session_id, doctor_id, doctor_diploma_no,
                selected_diagnosis_rank, modified_prescription, approval_action,
                review_duration_ms, prev_record_hash, current_record_hash, approved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.session_id,
                request.doctor_id,
                request.doctor_diploma_no,
                request.selected_diagnosis_rank,
                prescription,
                request.approval_action,
                request.review_duration_ms,
                previous_hash,
                current_hash,
                approved_at,
            ),
        )
        await db.commit()
    finally:
        if db.in_transaction:
            await db.rollback()

    return {
        "session_id": request.session_id,
        "audit_id": int(cursor.lastrowid),
        "record_hash": current_hash,
        "prev_hash": previous_hash,
        "approved_at": approved_at,
    }


async def verify_audit_chain(db: aiosqlite.Connection) -> bool:
    cursor = await db.execute(
        """
        SELECT audit.audit_id, audit.session_id, audit.doctor_id,
               audit.doctor_diploma_no, audit.selected_diagnosis_rank,
               audit.modified_prescription, audit.approval_action,
               audit.review_duration_ms, audit.prev_record_hash,
               audit.current_record_hash, audit.approved_at,
               sessions.ai_output_payload
        FROM doctor_approvals_audit AS audit
        JOIN clinical_sessions AS sessions USING (session_id)
        ORDER BY audit.audit_id
        """
    )
    previous_hash = GENESIS_HASH
    for row in await cursor.fetchall():
        if row["prev_record_hash"] != previous_hash:
            return False
        expected_hash = _approval_hash(
            session_id=row["session_id"],
            doctor_id=row["doctor_id"],
            doctor_diploma_no=row["doctor_diploma_no"],
            selected_diagnosis_rank=row["selected_diagnosis_rank"],
            modified_prescription=row["modified_prescription"],
            approval_action=row["approval_action"],
            review_duration_ms=row["review_duration_ms"],
            ai_output_payload=row["ai_output_payload"],
            approved_at=row["approved_at"],
            previous_hash=previous_hash,
        )
        if row["current_record_hash"] != expected_hash:
            return False
        previous_hash = row["current_record_hash"]
    return True
