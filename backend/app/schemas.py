from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LabResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_code: str
    value: float
    unit: str
    ref_range: str
    flag: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]


class VitalsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature_c: float | None = Field(default=None, ge=30, le=45)
    bp_systolic: int | None = Field(default=None, ge=40, le=300)
    bp_diastolic: int | None = Field(default=None, ge=20, le=200)
    heart_rate_bpm: int | None = Field(default=None, ge=20, le=260)
    spo2_percent: int | None = Field(default=None, ge=50, le=100)


class PatientContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_tc_hash: str = Field(min_length=64, max_length=64)
    age: int | None = Field(default=None, ge=0, le=130)
    sex: Literal["M", "F"] | None = None
    weight_kg: float | None = Field(default=None, gt=1, le=300)
    pregnancy_status: bool | None = None
    egfr_ml_min: float | None = Field(default=None, ge=0, le=200)
    known_allergies: list[str] = Field(default_factory=list)
    allergy_history_reviewed: bool = False
    chronic_conditions: list[str] = Field(default_factory=list)


class AnalyzeRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    patient_context: PatientContext
    vitals: VitalsInput
    chief_complaint: str = Field(min_length=3, max_length=2000)
    lab_results: list[LabResultItem] = Field(default_factory=list)
    clinical_context: str = Field(default="", max_length=30_000)


class DiagnosisCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1, le=3)
    icd10_code: str
    condition_name: str
    probability_score: float = Field(ge=0, le=1)
    supporting_evidence: list[str]


class MedicationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atc_code: str
    drug_name: str
    dosage: str
    daily_dose_mg: float = Field(gt=0)
    duration_days: int = Field(ge=1, le=90)
    box_count: int = Field(ge=1, le=10)
    rationale: str


class DifferentialDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1, le=3)
    icd10_code: str
    condition_name: str
    probability_score: float = Field(ge=0, le=1)
    assessment: Literal["SUSPECTED", "LESS_LIKELY", "NOT_SUPPORTED"]
    clinical_reasoning: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(default_factory=list, max_length=20)
    remaining_uncertainty: str = Field(default="", max_length=1000)


class RequiredTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_name: str = Field(min_length=1, max_length=200)
    category: Literal["LAB", "IMAGING", "OTHER"]
    purpose: str = Field(min_length=1, max_length=1000)
    urgency: Literal["ROUTINE", "URGENT", "EMERGENCY"]


class ClinicalDecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clinical_status: Literal["NEEDS_TESTS", "READY_FOR_PRESCRIPTION"]
    clinical_summary: str = Field(min_length=1, max_length=3000)
    differential_analysis: list[DifferentialDiagnosis] = Field(min_length=1, max_length=3)
    required_tests: list[RequiredTest] = Field(default_factory=list, max_length=20)
    missing_clinical_information: list[str] = Field(default_factory=list, max_length=20)
    clinical_blockers: list[str] = Field(default_factory=list, max_length=20)
    red_flags_detected: list[str]
    recommended_workup: list[str]
    prescription_protocol: list[MedicationProposal] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_clinical_state(self) -> "ClinicalDecisionOutput":
        ranks = [diagnosis.rank for diagnosis in self.differential_analysis]
        if len(ranks) != len(set(ranks)):
            raise ValueError("Differential diagnosis ranks must be unique.")
        if self.clinical_status == "NEEDS_TESTS":
            if self.prescription_protocol:
                raise ValueError(
                    "Prescription protocol must be empty when clinical status is NEEDS_TESTS."
                )
            if not (
                self.required_tests
                or self.missing_clinical_information
                or self.clinical_blockers
            ):
                raise ValueError(
                    "NEEDS_TESTS requires tests, missing information, or a clinical blocker."
                )
        elif self.required_tests or self.missing_clinical_information or self.clinical_blockers:
            raise ValueError(
                "READY_FOR_PRESCRIPTION cannot include unresolved tests or clinical blockers."
            )
        return self


class SafetyAuditBadge(BaseModel):
    allergy_check_passed: bool
    renal_check_passed: bool
    pregnancy_check_passed: bool
    dose_check_passed: bool
    warning_flags: list[str] = Field(default_factory=list)
    interventions_applied: list[str] = Field(default_factory=list)


class AnalyzeResponsePayload(BaseModel):
    session_id: str
    processing_time_ms: int
    safety_badges: SafetyAuditBadge
    clinical_decision: ClinicalDecisionOutput


class UploadedDocumentMetadata(BaseModel):
    media_type: Literal["application/pdf", "text/plain", "image/png", "image/jpeg"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    extracted_characters: int = Field(ge=0, le=30_000)
    page_count: int | None = Field(default=None, ge=1, le=30)


class UploadContextResponse(BaseModel):
    clinical_context: str = Field(min_length=1, max_length=30_000)
    documents: list[UploadedDocumentMetadata] = Field(min_length=1, max_length=8)
    total_characters: int = Field(ge=1, le=30_000)


class DoctorApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    doctor_id: str = Field(min_length=1, max_length=128)
    doctor_diploma_no: str = Field(min_length=1, max_length=128)
    selected_diagnosis_rank: Literal[1, 2, 3]
    approval_action: Literal["APPROVED_AS_IS", "MODIFIED_AND_APPROVED", "REJECTED"]
    modified_prescription: list[MedicationProposal] | None = None
    review_duration_ms: int = Field(ge=0)


class ApprovalResponse(BaseModel):
    session_id: str
    audit_id: int
    record_hash: str
    prev_hash: str
    approved_at: str


def json_payload(payload: BaseModel) -> dict[str, Any]:
    return payload.model_dump(mode="json")
