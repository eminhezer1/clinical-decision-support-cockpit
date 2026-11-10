from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClinicalSessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    patient_hash: str = Field(min_length=64, max_length=64)
    input_payload: dict[str, Any]
    ai_output_payload: dict[str, Any]
    model_version: str = Field(min_length=1)
    processing_time_ms: int = Field(ge=0)


class DoctorApprovalAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    doctor_id: str = Field(min_length=1, max_length=128)
    doctor_diploma_no: str = Field(min_length=1, max_length=128)
    selected_diagnosis_rank: int = Field(ge=1, le=3)
    modified_prescription: str | None
    approval_action: str = Field(min_length=1)
    review_duration_ms: int = Field(ge=0)
    prev_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_at: str = Field(min_length=1)


class DrugSafetyRuleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atc_code: str = Field(min_length=1, max_length=7)
    drug_name: str = Field(min_length=1)
    allergy_group: str | None
    min_egfr_threshold: float = Field(ge=0)
    max_daily_dose_mg: float = Field(gt=0)
    pregnancy_category: str = Field(min_length=1)
