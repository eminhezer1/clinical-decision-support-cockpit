export type Sex = "M" | "F";
export type LabFlag = "LOW" | "NORMAL" | "HIGH" | "CRITICAL";
export type ApprovalAction =
  | "APPROVED_AS_IS"
  | "MODIFIED_AND_APPROVED"
  | "REJECTED";

export interface LabResultItem {
  test_code: string;
  value: number;
  unit: string;
  ref_range: string;
  flag: LabFlag;
}

export interface PatientContext {
  patient_tc_hash: string;
  age: number | null;
  sex: Sex | null;
  weight_kg: number | null;
  pregnancy_status: boolean | null;
  egfr_ml_min: number | null;
  known_allergies: string[];
  allergy_history_reviewed: boolean;
  chronic_conditions: string[];
}

export interface VitalsInput {
  temperature_c: number | null;
  bp_systolic: number | null;
  bp_diastolic: number | null;
  heart_rate_bpm: number | null;
  spo2_percent: number | null;
}

export interface AnalyzeRequestPayload {
  session_id: string;
  patient_context: PatientContext;
  vitals: VitalsInput;
  chief_complaint: string;
  lab_results: LabResultItem[];
  clinical_context: string;
}

export interface MedicationProposal {
  atc_code: string;
  drug_name: string;
  dosage: string;
  daily_dose_mg: number;
  duration_days: number;
  box_count: number;
  rationale: string;
}

export interface ClinicalDecisionOutput {
  clinical_status: "NEEDS_TESTS" | "READY_FOR_PRESCRIPTION";
  clinical_summary: string;
  differential_analysis: DifferentialDiagnosis[];
  required_tests: RequiredTest[];
  missing_clinical_information: string[];
  clinical_blockers: string[];
  red_flags_detected: string[];
  recommended_workup: string[];
  prescription_protocol: MedicationProposal[];
}

export interface DifferentialDiagnosis {
  rank: 1 | 2 | 3;
  icd10_code: string;
  condition_name: string;
  probability_score: number;
  assessment: "SUSPECTED" | "LESS_LIKELY" | "NOT_SUPPORTED";
  clinical_reasoning: string;
  evidence: string[];
  remaining_uncertainty: string;
}

export interface RequiredTest {
  test_name: string;
  category: "LAB" | "IMAGING" | "OTHER";
  purpose: string;
  urgency: "ROUTINE" | "URGENT" | "EMERGENCY";
}

export interface UploadedDocumentMetadata {
  media_type: "application/pdf" | "text/plain" | "image/png" | "image/jpeg";
  sha256: string;
  extracted_characters: number;
  page_count: number | null;
}

export interface UploadContextResponse {
  clinical_context: string;
  documents: UploadedDocumentMetadata[];
  total_characters: number;
}

export interface SafetyAuditBadge {
  allergy_check_passed: boolean;
  renal_check_passed: boolean;
  pregnancy_check_passed: boolean;
  dose_check_passed: boolean;
  warning_flags: string[];
  interventions_applied: string[];
}

export interface AnalyzeResponsePayload {
  session_id: string;
  processing_time_ms: number;
  safety_badges: SafetyAuditBadge;
  clinical_decision: ClinicalDecisionOutput;
}

export interface ApprovalRequestPayload {
  session_id: string;
  doctor_id: string;
  doctor_diploma_no: string;
  selected_diagnosis_rank: 1 | 2 | 3;
  approval_action: ApprovalAction;
  modified_prescription: MedicationProposal[] | null;
  review_duration_ms: number;
}

export interface ApprovalReceipt {
  session_id: string;
  audit_id: number;
  record_hash: string;
  prev_hash: string;
  approved_at: string;
}

export interface ClinicalDiagnostics {
  request_id: string;
  model: string;
  ollama_timeout_seconds: number;
  ollama_reachable: boolean;
  model_installed: boolean;
  installed_models: string[];
  ollama_error: string | null;
  database_ok: boolean;
  drug_safety_rule_count: number | null;
  database_error: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "";

function formatApiError(
  body: unknown,
  status: number,
  path: string,
  fallbackRequestId: string,
): string {
  let detail = "";
  let stage = "";
  let requestId = fallbackRequestId;
  if (typeof body === "object" && body !== null && "detail" in body) {
    const bodyDetail = body.detail;
    if (typeof bodyDetail === "string") {
      detail = bodyDetail;
    } else if (typeof bodyDetail === "object" && bodyDetail !== null) {
      if ("message" in bodyDetail && typeof bodyDetail.message === "string") {
        detail = bodyDetail.message;
      }
      if ("stage" in bodyDetail && typeof bodyDetail.stage === "string") {
        stage = bodyDetail.stage;
      }
      if ("request_id" in bodyDetail && typeof bodyDetail.request_id === "string") {
        requestId = bodyDetail.request_id;
      }
    } else if (Array.isArray(bodyDetail)) {
      const messages = bodyDetail.flatMap((item: unknown) => {
        if (typeof item !== "object" || item === null || !("msg" in item)) {
          return [];
        }
        return typeof item.msg === "string" ? [item.msg] : [];
      });
      detail = messages.join("; ");
    }
  }
  if (typeof body === "object" && body !== null && "request_id" in body) {
    if (typeof body.request_id === "string") requestId = body.request_id;
  }
  if (!detail && typeof body === "string") {
    detail = body;
  }
  const lines = [
    `HTTP ${status} · ${path}`,
    `İstek kimliği: ${requestId}`,
  ];
  if (stage) lines.push(`Aşama: ${stage}`);
  if (detail) {
    lines.push(detail.slice(0, 1200));
  } else {
    lines.push("Sunucu yanıtı hata ayrıntısı içermiyor; backend terminal loglarında bu istek kimliğini arayın.");
  }
  return lines.join("\n");
}

function createRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function readJsonResponse<TResponse>(
  response: Response,
  path: string,
  requestId: string,
): Promise<TResponse> {
  const responseText = await response.text();
  let body: unknown = responseText;
  if (responseText) {
    try {
      body = JSON.parse(responseText) as unknown;
    } catch {
      body = responseText;
    }
  }
  if (!response.ok) {
    const responseRequestId = response.headers.get("x-request-id") ?? requestId;
    throw new Error(
      formatApiError(body, response.status, path, responseRequestId),
    );
  }
  if (typeof body !== "object" || body === null) {
    throw new Error(`Sunucudan geçerli JSON yanıtı alınamadı · ${path} · ${requestId}`);
  }
  return body as TResponse;
}

async function postJson<TRequest, TResponse>(
  path: string,
  payload: TRequest,
): Promise<TResponse> {
  const requestId = createRequestId();
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    throw new Error(
      `API bağlantısı kurulamadı · ${path} · İstek kimliği: ${requestId} · ${error instanceof Error ? error.message : "ağ hatası"}`,
    );
  }
  return readJsonResponse<TResponse>(response, path, requestId);
}

export async function uploadClinicalContext(
  files: File[],
): Promise<UploadContextResponse> {
  const requestId = createRequestId();
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  const path = "/api/v1/clinical/upload-context";
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "X-Request-ID": requestId },
      body: formData,
    });
  } catch (error) {
    throw new Error(
      `API bağlantısı kurulamadı · ${path} · İstek kimliği: ${requestId} · ${error instanceof Error ? error.message : "ağ hatası"}`,
    );
  }
  return readJsonResponse<UploadContextResponse>(response, path, requestId);
}

export function analyzeClinicalCase(
  payload: AnalyzeRequestPayload,
): Promise<AnalyzeResponsePayload> {
  return postJson<AnalyzeRequestPayload, AnalyzeResponsePayload>(
    "/api/v1/clinical/analyze",
    payload,
  );
}

export function approveClinicalCase(
  payload: ApprovalRequestPayload,
): Promise<ApprovalReceipt> {
  return postJson<ApprovalRequestPayload, ApprovalReceipt>(
    "/api/v1/clinical/approve",
    payload,
  );
}

export async function getClinicalDiagnostics(): Promise<ClinicalDiagnostics> {
  const path = "/api/v1/clinical/diagnostics";
  const requestId = createRequestId();
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "X-Request-ID": requestId },
    });
  } catch (error) {
    throw new Error(
      `API bağlantısı kurulamadı · ${path} · İstek kimliği: ${requestId} · ${error instanceof Error ? error.message : "ağ hatası"}`,
    );
  }
  return readJsonResponse<ClinicalDiagnostics>(response, path, requestId);
}
