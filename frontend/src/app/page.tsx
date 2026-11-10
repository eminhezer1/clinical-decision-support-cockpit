"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  analyzeClinicalCase,
  approveClinicalCase,
  getClinicalDiagnostics,
  uploadClinicalContext,
  type AnalyzeResponsePayload,
  type ApprovalReceipt,
  type ClinicalDiagnostics,
  type DifferentialDiagnosis,
  type MedicationProposal,
  type UploadedDocumentMetadata,
} from "@/lib/clinical-api";
import { formatToEpicrisisText } from "@/lib/epicrisis";

type Sex = "M" | "F";
type PatientNumber =
  | "age"
  | "weight_kg"
  | "egfr_ml_min"
  | "temperature_c"
  | "bp_systolic"
  | "bp_diastolic"
  | "heart_rate_bpm"
  | "spo2_percent";

interface PatientDraft {
  age: number | "";
  sex: Sex | "";
  weight_kg: number | "";
  pregnancy_status: boolean | null;
  egfr_ml_min: number | "";
  known_allergies: string;
  allergy_history_reviewed: boolean;
  temperature_c: number | "";
  bp_systolic: number | "";
  bp_diastolic: number | "";
  heart_rate_bpm: number | "";
  spo2_percent: number | "";
}

const EMPTY_PATIENT: PatientDraft = {
  age: "",
  sex: "",
  weight_kg: "",
  pregnancy_status: null,
  egfr_ml_min: "",
  known_allergies: "",
  allergy_history_reviewed: false,
  temperature_c: "",
  bp_systolic: "",
  bp_diastolic: "",
  heart_rate_bpm: "",
  spo2_percent: "",
};

function isNumber(value: number | ""): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function hasCompleteSafetyContext(patient: PatientDraft): boolean {
  const ranges: Record<PatientNumber, [number, number, boolean]> = {
    age: [0, 130, true],
    weight_kg: [1, 300, false],
    egfr_ml_min: [0, 200, false],
    temperature_c: [30, 45, false],
    bp_systolic: [40, 300, true],
    bp_diastolic: [20, 200, true],
    heart_rate_bpm: [20, 260, true],
    spo2_percent: [50, 100, true],
  };
  const numbers = Object.keys(ranges) as PatientNumber[];
  return (
    numbers.every((field) => {
      const value = patient[field];
      const [minimum, maximum, integer] = ranges[field];
      return (
        isNumber(value) &&
        (field === "weight_kg" ? value > minimum : value >= minimum) &&
        value <= maximum &&
        (!integer || Number.isInteger(value))
      );
    }) &&
    (patient.sex === "M" || patient.sex === "F") &&
    patient.pregnancy_status !== null &&
    patient.allergy_history_reviewed
  );
}

function toNullableNumber(value: number | ""): number | null {
  return value === "" ? null : value;
}

function toNullableTextNumber(value: string): number | "" {
  return value.trim() === "" ? "" : Number(value);
}

function formatTestRequest(analysis: AnalyzeResponsePayload): string {
  const decision = analysis.clinical_decision;
  const tests = decision.required_tests.length
    ? decision.required_tests
        .map(
          (test, index) =>
            `${index + 1}. ${test.test_name} (${test.category}, ${test.urgency})\n   Amaç: ${test.purpose}`,
        )
        .join("\n")
    : "Sistem belirli bir test önermedi.";
  const missing = decision.missing_clinical_information.length
    ? `\nEksik doğrulanmış bilgiler:\n- ${decision.missing_clinical_information.join("\n- ")}`
    : "";
  const blockers = decision.clinical_blockers.length
    ? `\nKlinik engeller:\n- ${decision.clinical_blockers.join("\n- ")}`
    : "";
  return [
    "KLİNİK TEST İSTEM TASLAĞI — HBYS'YE GÖNDERİLMEDİ",
    `Özet: ${decision.clinical_summary}`,
    `Ayırıcı tanıda belirsizliği gidermek için:\n${tests}${missing}${blockers}`,
    `Red flag: ${decision.red_flags_detected.length ? decision.red_flags_detected.join("; ") : "Bildirilmedi"}`,
    "Bu metin yapay zekâ destekli taslaktır; klinik değerlendirme ve gerçek istem için hekim/HBYS işlemi gerekir.",
  ].join("\n\n");
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  min,
  max,
  step,
  suffix,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  type?: "text" | "number";
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">
        {label}
      </span>
      <span className="relative block">
        <input
          className={`h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 focus:border-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-700/10 ${suffix ? "pr-14" : ""}`}
          type={type}
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(event) => onChange(event.target.value)}
        />
        {suffix && (
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-slate-400">
            {suffix}
          </span>
        )}
      </span>
    </label>
  );
}

function DifferentialCard({
  diagnosis,
  selected,
  onSelect,
}: {
  diagnosis: DifferentialDiagnosis;
  selected: boolean;
  onSelect: () => void;
}) {
  const assessmentLabel =
    diagnosis.assessment === "SUSPECTED"
      ? "Öncelikli olasılık"
      : diagnosis.assessment === "LESS_LIKELY"
        ? "Daha düşük olasılık"
        : "Mevcut veriyle desteklenmiyor";
  const percent = Math.round(diagnosis.probability_score * 100);
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`block w-full rounded-xl border p-4 text-left ${selected ? "border-teal-700 bg-teal-50/60" : "border-slate-200 bg-white"}`}
    >
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-sm font-bold text-slate-700">
          {diagnosis.rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-[10px] font-bold text-slate-500">
              ICD-10 · {diagnosis.icd10_code}
            </span>
            <span className="text-sm font-extrabold text-teal-800">{percent}%</span>
          </div>
          <h3 className="mt-1 text-sm font-bold text-slate-900">
            {diagnosis.condition_name}
          </h3>
          <p className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            {assessmentLabel}
          </p>
          <div className="my-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-teal-700" style={{ width: `${percent}%` }} />
          </div>
          <p className="text-xs leading-5 text-slate-700">
            {diagnosis.clinical_reasoning}
          </p>
          {diagnosis.evidence.length > 0 && (
            <ul className="mt-2 list-inside list-disc space-y-0.5 text-[11px] text-slate-600">
              {diagnosis.evidence.map((item, index) => (
                <li key={`${diagnosis.rank}-evidence-${index}`}>{item}</li>
              ))}
            </ul>
          )}
          {diagnosis.remaining_uncertainty && (
            <p className="mt-2 text-[11px] leading-4 text-amber-800">
              Belirsizlik: {diagnosis.remaining_uncertainty}
            </p>
          )}
        </div>
      </div>
    </button>
  );
}

export default function DoctorCockpit() {
  const [complaint, setComplaint] = useState("");
  const [patient, setPatient] = useState<PatientDraft>(EMPTY_PATIENT);
  const [uploadedContext, setUploadedContext] = useState("");
  const [documents, setDocuments] = useState<UploadedDocumentMetadata[]>([]);
  const [uploading, setUploading] = useState(false);
  const [doctorId, setDoctorId] = useState("");
  const [diplomaNo, setDiplomaNo] = useState("");
  const [analysis, setAnalysis] = useState<AnalyzeResponsePayload | null>(null);
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [prescription, setPrescription] = useState<MedicationProposal[]>([]);
  const [originalPrescription, setOriginalPrescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState("");
  const [diagnostics, setDiagnostics] = useState<ClinicalDiagnostics | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [receipt, setReceipt] = useState<ApprovalReceipt | null>(null);
  const [copyWarning, setCopyWarning] = useState("");
  const [epicrisisText, setEpicrisisText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const openedAt = useRef(0);
  const requestGeneration = useRef(0);
  const approvalInFlight = useRef(false);

  const runDiagnostics = async () => {
    setDiagnosticsLoading(true);
    setDiagnostics(null);
    try {
      setDiagnostics(await getClinicalDiagnostics());
    } catch (caught) {
      setError((current) =>
        [
          current,
          caught instanceof Error ? caught.message : "Tanılama isteği başarısız oldu.",
        ]
          .filter(Boolean)
          .join("\n\n"),
      );
    } finally {
      setDiagnosticsLoading(false);
    }
  };

  const differential = useMemo(
    () =>
      [...(analysis?.clinical_decision.differential_analysis ?? [])].sort(
        (left, right) => left.rank - right.rank,
      ),
    [analysis],
  );
  const selectedDiagnosis =
    differential.find((item) => item.rank === selectedRank) ?? null;
  const safety = analysis?.safety_badges;
  const safetyChecksPassed = Boolean(
    safety?.allergy_check_passed &&
      safety.renal_check_passed &&
      safety.pregnancy_check_passed &&
      safety.dose_check_passed,
  );
  const readyForPrescription =
    analysis?.clinical_decision.clinical_status === "READY_FOR_PRESCRIPTION" &&
    hasCompleteSafetyContext(patient) &&
    safetyChecksPassed &&
    analysis.clinical_decision.red_flags_detected.length === 0;
  const hasEditedPrescription =
    JSON.stringify(prescription) !== originalPrescription;

  const clearAnalysis = useCallback(() => {
    requestGeneration.current += 1;
    setLoading(false);
    setAnalysis(null);
    setSelectedRank(null);
    setPrescription([]);
    setOriginalPrescription("");
    setReceipt(null);
    setEpicrisisText("");
    setCopyWarning("");
    setNotice("");
  }, []);

  const updatePatient = <K extends keyof PatientDraft>(
    key: K,
    value: PatientDraft[K],
  ) => {
    setPatient((current) => ({ ...current, [key]: value }));
    clearAnalysis();
  };

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0) return;
    if (documents.length + files.length > 8) {
      setError("En fazla 8 belge yüklenebilir.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const uploaded = await uploadClinicalContext(files);
      const combined = [uploadedContext, uploaded.clinical_context]
        .filter(Boolean)
        .join("\n\n");
      if (combined.length > 30_000) {
        throw new Error("Belgelerden çıkarılan toplam metin 30.000 karakteri aşıyor.");
      }
      setUploadedContext(combined);
      setDocuments((current) => [...current, ...uploaded.documents]);
      clearAnalysis();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Belge yüklenirken beklenmeyen bir hata oluştu.",
      );
    } finally {
      setUploading(false);
    }
  };

  const clearDocuments = () => {
    setDocuments([]);
    setUploadedContext("");
    clearAnalysis();
  };

  const runAnalysis = async () => {
    if (complaint.trim().length < 3) {
      setError("Klinik analiz için anamnez/şikayet bilgisini girin.");
      return;
    }
    const currentGeneration = ++requestGeneration.current;
    setLoading(true);
    setError("");
    setDiagnostics(null);
    setNotice("");
    setAnalysis(null);
    setPrescription([]);
    setSelectedRank(null);
    setReceipt(null);
    try {
      const sessionId = crypto.randomUUID();
      const patientHash = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(`${sessionId}:${crypto.randomUUID()}`),
      );
      const result = await analyzeClinicalCase({
        session_id: sessionId,
        patient_context: {
          patient_tc_hash: Array.from(new Uint8Array(patientHash))
            .map((byte) => byte.toString(16).padStart(2, "0"))
            .join(""),
          age: toNullableNumber(patient.age),
          sex: patient.sex || null,
          weight_kg: toNullableNumber(patient.weight_kg),
          pregnancy_status: patient.pregnancy_status,
          egfr_ml_min: toNullableNumber(patient.egfr_ml_min),
          known_allergies: patient.known_allergies
            .split(",")
            .map((allergy) => allergy.trim())
            .filter(Boolean),
          allergy_history_reviewed: patient.allergy_history_reviewed,
          chronic_conditions: [],
        },
        vitals: {
          temperature_c: toNullableNumber(patient.temperature_c),
          bp_systolic: toNullableNumber(patient.bp_systolic),
          bp_diastolic: toNullableNumber(patient.bp_diastolic),
          heart_rate_bpm: toNullableNumber(patient.heart_rate_bpm),
          spo2_percent: toNullableNumber(patient.spo2_percent),
        },
        chief_complaint: complaint.trim(),
        lab_results: [],
        clinical_context: uploadedContext,
      });
      if (currentGeneration !== requestGeneration.current) return;
      setAnalysis(result);
      const initialPrescription =
        result.clinical_decision.prescription_protocol;
      setPrescription(initialPrescription);
      setOriginalPrescription(JSON.stringify(initialPrescription));
      setSelectedRank(result.clinical_decision.differential_analysis[0]?.rank ?? null);
      openedAt.current = performance.now();
    } catch (caught) {
      if (currentGeneration === requestGeneration.current) {
        setError(
          caught instanceof Error
            ? caught.message
            : "Klinik analiz sırasında beklenmeyen bir hata oluştu.",
        );
      }
    } finally {
      if (currentGeneration === requestGeneration.current) setLoading(false);
    }
  };

  const updatePrescription = (
    index: number,
    field: "dosage" | "daily_dose_mg" | "duration_days" | "box_count",
    value: string,
  ) => {
    setPrescription((current) =>
      current.map((item, itemIndex) => {
        if (itemIndex !== index) return item;
        if (field === "dosage") return { ...item, dosage: value };
        const numeric = Number(value);
        return { ...item, [field]: Number.isFinite(numeric) ? numeric : 0 };
      }),
    );
  };

  const approve = useCallback(async () => {
    if (
      !analysis ||
      !readyForPrescription ||
      !selectedDiagnosis ||
      approving ||
      approvalInFlight.current ||
      receipt
    ) {
      return;
    }
    if (!doctorId.trim() || !diplomaNo.trim()) {
      setError("Onay için hekim sicil ve diploma numarası gereklidir.");
      return;
    }
    const patientAge = patient.age;
    const patientSex = patient.sex;
    const temperature = patient.temperature_c;
    const systolic = patient.bp_systolic;
    const diastolic = patient.bp_diastolic;
    const heartRate = patient.heart_rate_bpm;
    const oxygenSaturation = patient.spo2_percent;
    if (
      !isNumber(patientAge) ||
      (patientSex !== "M" && patientSex !== "F") ||
      !isNumber(temperature) ||
      !isNumber(systolic) ||
      !isNumber(diastolic) ||
      !isNumber(heartRate) ||
      !isNumber(oxygenSaturation)
    ) {
      setError("Epikriz için hasta yaşı, cinsiyet ve tüm vital bulgular doğrulanmalıdır.");
      return;
    }
    approvalInFlight.current = true;
    setApproving(true);
    setError("");
    try {
      const approved = await approveClinicalCase({
        session_id: analysis.session_id,
        doctor_id: doctorId.trim(),
        doctor_diploma_no: diplomaNo.trim(),
        selected_diagnosis_rank: selectedDiagnosis.rank,
        approval_action: hasEditedPrescription
          ? "MODIFIED_AND_APPROVED"
          : "APPROVED_AS_IS",
        modified_prescription: hasEditedPrescription ? prescription : null,
        review_duration_ms: Math.max(
          0,
          Math.round(performance.now() - openedAt.current),
        ),
      });
      setReceipt(approved);
      const epicrisis = formatToEpicrisisText(
        complaint,
        { age: patientAge, sex: patientSex },
        {
          temperature_c: temperature,
          bp_systolic: systolic,
          bp_diastolic: diastolic,
          heart_rate_bpm: heartRate,
          spo2_percent: oxygenSaturation,
        },
        selectedDiagnosis,
        prescription,
        analysis.clinical_decision.recommended_workup,
      );
      setEpicrisisText(epicrisis);
      try {
        await navigator.clipboard.writeText(epicrisis);
      } catch {
        setCopyWarning("Onay kaydedildi; pano erişimi reddedildi. Epikrizi ayrıca kopyalayın.");
      }
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Hekim onayı kaydedilemedi.",
      );
    } finally {
      approvalInFlight.current = false;
      setApproving(false);
    }
  }, [
    analysis,
    approving,
    complaint,
    diplomaNo,
    doctorId,
    hasEditedPrescription,
    patient,
    prescription,
    readyForPrescription,
    receipt,
    selectedDiagnosis,
  ]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target.closest("input, textarea, select, [contenteditable='true']"))
      ) {
        return;
      }
      if (["1", "2", "3"].includes(event.key)) {
        const rank = Number(event.key);
        if (differential.some((item) => item.rank === rank)) {
          event.preventDefault();
          setSelectedRank(rank);
        }
      } else if (event.key === " " || event.key === "Enter") {
        if (target instanceof HTMLElement && target.closest("button")) return;
        if (readyForPrescription) {
          event.preventDefault();
          void approve();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [approve, differential, readyForPrescription]);

  const handleTestDraft = async () => {
    if (!analysis) return;
    try {
      await navigator.clipboard.writeText(formatTestRequest(analysis));
      setNotice("Test istem taslağı panoya kopyalandı; HBYS'ye gönderilmedi.");
    } catch {
      setError("Test istem taslağı panoya kopyalanamadı.");
    }
  };

  const handleCopyEpicrisis = async () => {
    try {
      await navigator.clipboard.writeText(epicrisisText);
      setCopyWarning("");
    } catch {
      setCopyWarning("Pano erişimi reddedildi; epikriz kopyalanamadı.");
    }
  };

  const handleComplaintChange = (value: string) => {
    setComplaint(value);
    clearAnalysis();
  };

  const handlePrescriptionField = (
    event: ChangeEvent<HTMLInputElement>,
    index: number,
    field: "dosage" | "daily_dose_mg" | "duration_days" | "box_count",
  ) => updatePrescription(index, field, event.target.value);

  const status = analysis?.clinical_decision.clinical_status;
  const needsTests = status === "NEEDS_TESTS";

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-5 text-slate-900 sm:px-6 lg:px-8">
      <header className="mx-auto mb-5 flex max-w-[1500px] flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-teal-800">
            Klinik Muhakeme ve Ayırıcı Tanı
          </p>
          <h1 className="mt-1 text-xl font-extrabold tracking-tight">
            Doktor Değerlendirme Kokpiti
          </h1>
          <p className="mt-1 text-xs text-slate-500">
            Yapay zekâ çıktısı taslaktır; tanı, test emri ve reçete hekim sorumluluğundadır.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Hekim sicil no" value={doctorId} onChange={setDoctorId} />
          <Field label="Diploma no" value={diplomaNo} onChange={setDiplomaNo} />
        </div>
      </header>

      {(error || notice) && (
        <div
          role={error ? "alert" : "status"}
          className={`mx-auto mb-4 max-w-[1500px] rounded-xl border px-4 py-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="whitespace-pre-wrap break-words">{error || notice}</p>
              {error && (
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-xs font-bold underline">
                  <button
                    type="button"
                    disabled={diagnosticsLoading}
                    onClick={() => void runDiagnostics()}
                  >
                    {diagnosticsLoading ? "Tanılama çalışıyor..." : "Sistem tanılamasını çalıştır"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const report = [
                        error,
                        diagnostics
                          ? `Tanılama:\n${JSON.stringify(diagnostics, null, 2)}`
                          : "",
                      ]
                        .filter(Boolean)
                        .join("\n\n");
                      void navigator.clipboard.writeText(report).catch(() => {
                        setNotice("Hata ayrıntısı panoya kopyalanamadı.");
                      });
                    }}
                  >
                    Hata ve tanılamayı kopyala
                  </button>
                </div>
              )}
              {diagnostics && error && (
                <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white/80 p-3 font-mono text-xs">
                  {JSON.stringify(diagnostics, null, 2)}
                </pre>
              )}
            </div>
            <button
              type="button"
              className="shrink-0 font-bold"
              onClick={() => { setError(""); setNotice(""); }}
            >
              Kapat
            </button>
          </div>
        </div>
      )}

      {receipt && (
        <section className="mx-auto mb-4 max-w-[1500px] rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-950">
          <p className="text-sm font-bold">Hekim onayı kaydedildi · Denetim #{receipt.audit_id}</p>
          <p className="mt-2 break-all rounded bg-white p-2 font-mono text-[11px]">
            SHA-256 AUDIT HASH: {receipt.record_hash}
          </p>
          {copyWarning && <p className="mt-2 text-xs text-amber-800">{copyWarning}</p>}
          <button type="button" className="mt-2 rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-bold" onClick={() => void handleCopyEpicrisis()}>
            Epikrizi panoya kopyala
          </button>
        </section>
      )}

      <div className="mx-auto grid max-w-[1500px] gap-4 xl:grid-cols-[minmax(310px,0.8fr)_minmax(0,1.55fr)]">
        <aside className="space-y-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-bold">Anamnez ve dış kaynaklar</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              e-Nabız bağlantısı yoktur. Yalnızca aşağıya yazdığınız bilgiler ve yüklediğiniz belgeler değerlendirilir.
            </p>
            <label className="mt-4 block">
              <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Şikayet, anamnez ve mevcut klinik notlar
              </span>
              <textarea
                className="min-h-40 w-full resize-y rounded-xl border border-slate-200 p-3 text-sm leading-5 focus:border-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-700/10"
                maxLength={2000}
                value={complaint}
                onChange={(event) => handleComplaintChange(event.target.value)}
              />
              <span className="mt-1 block text-right text-[10px] text-slate-400">
                {complaint.length}/2000
              </span>
            </label>
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4">
              <p className="text-xs font-bold">Dış tahlil / rapor yükle</p>
              <p className="mt-1 text-[11px] leading-4 text-slate-500">
                PDF, TXT, PNG veya JPEG · dosya başına 15 MB · en fazla 8 dosya. Taranmış sayfalarda yerel Tesseract OCR kullanılır.
              </p>
              <input
                ref={inputRef}
                className="sr-only"
                type="file"
                multiple
                accept=".pdf,.txt,.png,.jpg,.jpeg,application/pdf,text/plain,image/png,image/jpeg"
                onChange={(event) => void handleUpload(event)}
              />
              <button
                type="button"
                disabled={uploading}
                onClick={() => inputRef.current?.click()}
                className="mt-3 rounded-lg bg-slate-900 px-4 py-2 text-xs font-bold text-white disabled:opacity-50"
              >
                {uploading ? "Belgeler okunuyor…" : "Belge seç"}
              </button>
              {documents.length > 0 && (
                <div className="mt-3 rounded-lg bg-white p-3">
                  <p className="text-xs font-semibold">{documents.length} belge işlendi · {uploadedContext.length} karakter</p>
                  <p className="mt-1 break-all font-mono text-[9px] text-slate-500">
                    SHA-256: {documents.map((document) => document.sha256).join(", ")}
                  </p>
                  <button type="button" onClick={clearDocuments} className="mt-2 text-xs font-bold text-red-700">
                    Yüklenen bağlamı temizle
                  </button>
                </div>
              )}
            </div>
          </section>

          <details className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <summary className="cursor-pointer text-sm font-bold">
              Reçete güvenliği için doğrulanmış hasta verileri
            </summary>
            <p className="mb-4 mt-2 text-xs leading-5 text-amber-800">
              Bu veriler bilinmiyorsa sistem reçete önerisini kapatır. Belgede geçmesi tek başına doğrulanmış sayılmaz.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Yaş" type="number" min={0} max={130} step={1} value={patient.age} onChange={(value) => updatePatient("age", toNullableTextNumber(value))} />
              <Field label="Kilo" type="number" min={1.1} max={300} step={0.1} suffix="kg" value={patient.weight_kg} onChange={(value) => updatePatient("weight_kg", toNullableTextNumber(value))} />
              <label className="block">
                <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Biyolojik cinsiyet</span>
                <select className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm" value={patient.sex} onChange={(event) => updatePatient("sex", event.target.value as Sex | "")}>
                  <option value="">Seçin</option><option value="F">Kadın</option><option value="M">Erkek</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Gebelik</span>
                <select className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm" value={patient.pregnancy_status === null ? "" : String(patient.pregnancy_status)} onChange={(event) => updatePatient("pregnancy_status", event.target.value === "" ? null : event.target.value === "true")}>
                  <option value="">Seçin</option><option value="false">Yok</option><option value="true">Var</option>
                </select>
              </label>
              <Field label="eGFR" type="number" min={0} max={200} step={0.1} suffix="mL/dk" value={patient.egfr_ml_min} onChange={(value) => updatePatient("egfr_ml_min", toNullableTextNumber(value))} />
              <label className="col-span-2 block">
                <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Bilinen alerjiler</span>
                <input className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm" value={patient.known_allergies} onChange={(event) => updatePatient("known_allergies", event.target.value)} />
              </label>
              <label className="col-span-2 flex items-start gap-2 text-xs text-slate-600">
                <input type="checkbox" className="mt-0.5 accent-teal-700" checked={patient.allergy_history_reviewed} onChange={(event) => updatePatient("allergy_history_reviewed", event.target.checked)} />
                Alerji öyküsü hasta/kayıt üzerinden sorgulandı; bilinen alerjiler yukarıda belirtildi.
              </label>
            </div>
            <div className="mt-4 border-t border-slate-100 pt-4">
              <p className="mb-3 text-xs font-bold">Ölçülmüş vital bulgular</p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Ateş" type="number" min={30} max={45} step={0.1} suffix="°C" value={patient.temperature_c} onChange={(value) => updatePatient("temperature_c", toNullableTextNumber(value))} />
                <Field label="Sistolik TA" type="number" min={40} max={300} step={1} suffix="mmHg" value={patient.bp_systolic} onChange={(value) => updatePatient("bp_systolic", toNullableTextNumber(value))} />
                <Field label="Diyastolik TA" type="number" min={20} max={200} step={1} suffix="mmHg" value={patient.bp_diastolic} onChange={(value) => updatePatient("bp_diastolic", toNullableTextNumber(value))} />
                <Field label="Nabız" type="number" min={20} max={260} step={1} suffix="/dk" value={patient.heart_rate_bpm} onChange={(value) => updatePatient("heart_rate_bpm", toNullableTextNumber(value))} />
                <Field label="SpO₂" type="number" min={50} max={100} step={1} suffix="%" value={patient.spo2_percent} onChange={(value) => updatePatient("spo2_percent", toNullableTextNumber(value))} />
              </div>
            </div>
          </details>

          <button
            type="button"
            disabled={loading || uploading || complaint.trim().length < 3}
            onClick={() => void runAnalysis()}
            className="h-12 w-full rounded-xl bg-teal-800 px-4 text-sm font-bold text-white shadow-sm hover:bg-teal-900 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Ayırıcı tanı analizi sürüyor…" : "Klinik muhakemeyi başlat"}
          </button>
          <p className="text-center text-[10px] text-slate-500">
            Yüklenen orijinal dosyalar saklanmaz; analiz metni geçici iletilir.
          </p>
        </aside>

        <section className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(280px,0.85fr)] xl:items-start">
          {!analysis && (
            <div className="flex min-h-80 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center xl:col-span-2">
              <h2 className="text-base font-bold">Klinik değerlendirme bekleniyor</h2>
              <p className="mt-2 max-w-lg text-sm leading-6 text-slate-500">
                Anamnez ve varsa dış tahlilleri girip analizi başlatın. Tanısal belirsizlikte sistem reçete yerine ayrıştırıcı testleri önceliklendirmelidir.
              </p>
            </div>
          )}

          {analysis && (
            <>
              <div className={`rounded-2xl border p-5 xl:col-span-2 ${needsTests ? "border-amber-300 bg-amber-50" : "border-emerald-300 bg-emerald-50"}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-widest">
                      {needsTests ? "Test / bilgi gerekli" : "Reçete değerlendirmesine hazır"}
                    </p>
                    <h2 className="mt-1 text-lg font-extrabold">
                      {needsTests ? "Ayırıcı tanı netleştirilmeden reçete oluşturulmaz" : "Klinik değerlendirme ve reçete taslağı"}
                    </h2>
                  </div>
                  <span className="rounded-full bg-white px-3 py-1 text-xs font-bold">
                    {analysis.processing_time_ms} ms
                  </span>
                </div>
                <p className="mt-3 text-sm leading-6">{analysis.clinical_decision.clinical_summary}</p>
              </div>

              {analysis.clinical_decision.red_flags_detected.length > 0 && (
                <section className="rounded-2xl border border-red-300 bg-red-50 p-5 xl:col-span-2" role="alert">
                  <h2 className="text-sm font-extrabold text-red-900">Acil değerlendirme gerektiren bulgular</h2>
                  <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-red-800">
                    {analysis.clinical_decision.red_flags_detected.map((flag, index) => <li key={`${flag}-${index}`}>{flag}</li>)}
                  </ul>
                </section>
              )}

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-sm font-bold">Ayırıcı tanı ve klinik muhakeme</h2>
                  <span className="text-[10px] text-slate-500">1 / 2 / 3 ile seçim · olasılıklar model tahminidir</span>
                </div>
                <div className="space-y-3">
                  {differential.map((diagnosis) => (
                    <DifferentialCard
                      key={`${diagnosis.rank}-${diagnosis.icd10_code}`}
                      diagnosis={diagnosis}
                      selected={selectedRank === diagnosis.rank}
                      onSelect={() => setSelectedRank(diagnosis.rank)}
                    />
                  ))}
                </div>
              </section>

              {needsTests ? (
                <section className="rounded-2xl border border-amber-200 bg-white p-5 shadow-sm">
                  <h2 className="text-sm font-extrabold text-amber-950">
                    Şu ihtimalleri ayırmak için gerekenler
                  </h2>
                  {analysis.clinical_decision.required_tests.length > 0 ? (
                    <ul className="mt-3 space-y-3">
                      {analysis.clinical_decision.required_tests.map((test, index) => (
                        <li key={`${test.test_name}-${index}`} className="rounded-xl bg-amber-50 p-3">
                          <div className="flex flex-wrap justify-between gap-2">
                            <span className="text-sm font-bold">{test.test_name}</span>
                            <span className="text-[10px] font-bold uppercase">{test.category} · {test.urgency}</span>
                          </div>
                          <p className="mt-1 text-xs leading-5">{test.purpose}</p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs text-slate-600">
                      Laboratuvar/görüntüleme testinden önce eksik klinik bilgiler tamamlanmalıdır.
                    </p>
                  )}
                  {analysis.clinical_decision.missing_clinical_information.length > 0 && (
                    <div className="mt-4">
                      <h3 className="text-xs font-bold">Eksik doğrulanmış bilgiler</h3>
                      <ul className="mt-1 list-inside list-disc text-xs leading-5 text-slate-700">
                        {analysis.clinical_decision.missing_clinical_information.map((item, index) => <li key={`missing-${index}`}>{item}</li>)}
                      </ul>
                    </div>
                  )}
                  {analysis.clinical_decision.clinical_blockers.length > 0 && (
                    <ul className="mt-3 list-inside list-disc text-xs leading-5 text-red-800">
                      {analysis.clinical_decision.clinical_blockers.map((item, index) => <li key={`block-${index}`}>{item}</li>)}
                    </ul>
                  )}
                  <button type="button" onClick={() => void handleTestDraft()} className="mt-4 rounded-xl border border-amber-400 bg-amber-100 px-4 py-3 text-sm font-extrabold text-amber-950 hover:bg-amber-200">
                    Test istem taslağını kopyala
                  </button>
                  <p className="mt-2 text-[10px] text-slate-500">
                    HBYS entegrasyonu yoktur; bu işlem hastane sistemine test emri göndermez.
                  </p>
                </section>
              ) : (
                <div className="space-y-4">
                  <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                    <h2 className="text-sm font-bold">Deterministik ilaç güvenliği</h2>
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {[
                        ["Alerji", safety?.allergy_check_passed],
                        ["Renal / eGFR", safety?.renal_check_passed],
                        ["Gebelik", safety?.pregnancy_check_passed],
                        ["Doz", safety?.dose_check_passed],
                      ].map(([label, passed]) => (
                        <div key={String(label)} className={`rounded-lg border p-3 text-xs font-semibold ${passed ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-red-200 bg-red-50 text-red-900"}`}>
                          {label}: {passed ? "Kontrol edildi" : "Başarısız / doğrulanamadı"}
                        </div>
                      ))}
                    </div>
                    {[...(safety?.warning_flags ?? []), ...(safety?.interventions_applied ?? [])].length > 0 && (
                      <ul className="mt-3 list-inside list-disc space-y-1 text-xs text-amber-900">
                        {[...(safety?.warning_flags ?? []), ...(safety?.interventions_applied ?? [])].map((warning, index) => <li key={`warning-${index}`}>{warning}</li>)}
                      </ul>
                    )}
                  </section>

                  <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <div>
                        <h2 className="text-sm font-bold">Reçete protokolü (taslak)</h2>
                        <p className="mt-1 text-[11px] text-slate-500">Düzenlenen reçete onaydan önce tekrar güvenlik kontrolü gerektirir.</p>
                      </div>
                      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold">{prescription.length} ilaç</span>
                    </div>
                    {prescription.length === 0 ? (
                      <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">Bu değerlendirmede reçeteli ilaç önerilmedi.</p>
                    ) : (
                      <div className="space-y-3">
                        {prescription.map((medication, index) => (
                          <article key={`${medication.atc_code}-${index}`} className="rounded-xl border border-slate-200 p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <h3 className="text-sm font-bold">{medication.drug_name}</h3>
                                <p className="font-mono text-[10px] text-slate-500">ATC {medication.atc_code}</p>
                              </div>
                              <button type="button" onClick={() => setPrescription((current) => current.filter((_, itemIndex) => itemIndex !== index))} className="text-xs font-bold text-red-700">Kaldır</button>
                            </div>
                            <div className="mt-3 grid grid-cols-2 gap-2">
                              <label className="text-[10px] font-semibold">Kullanım<input className="mt-1 h-9 w-full rounded border px-2 text-xs" value={medication.dosage} onChange={(event) => handlePrescriptionField(event, index, "dosage")} /></label>
                              <label className="text-[10px] font-semibold">Günlük doz (mg)<input type="number" min={0} className="mt-1 h-9 w-full rounded border px-2 text-xs" value={medication.daily_dose_mg} onChange={(event) => handlePrescriptionField(event, index, "daily_dose_mg")} /></label>
                              <label className="text-[10px] font-semibold">Süre (gün)<input type="number" min={1} className="mt-1 h-9 w-full rounded border px-2 text-xs" value={medication.duration_days} onChange={(event) => handlePrescriptionField(event, index, "duration_days")} /></label>
                              <label className="text-[10px] font-semibold">Kutu<input type="number" min={1} className="mt-1 h-9 w-full rounded border px-2 text-xs" value={medication.box_count} onChange={(event) => handlePrescriptionField(event, index, "box_count")} /></label>
                            </div>
                            <p className="mt-2 text-[11px] leading-4 text-slate-600">{medication.rationale}</p>
                          </article>
                        ))}
                      </div>
                    )}
                    <div className="mt-5 grid gap-2 sm:grid-cols-2">
                      <button
                        type="button"
                        disabled={!readyForPrescription || approving || Boolean(receipt)}
                        onClick={() => void approve()}
                        className="rounded-xl bg-slate-900 px-4 py-3 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {approving ? "Onay kaydediliyor…" : "Tanı ve reçete taslağını onayla · Space"}
                      </button>
                      <span className="self-center text-[10px] leading-4 text-slate-500">
                        {readyForPrescription ? "Onay hekim kimliğiyle denetim zincirine kaydedilir." : "Onay için tüm güvenlik bilgileri ve deterministik kontroller tamamlanmalıdır."}
                      </span>
                    </div>
                  </section>
                </div>
              )}
            </>
          )}
        </section>
      </div>
      <footer className="mx-auto mt-5 max-w-[1500px] text-center text-[10px] text-slate-500">
        Klinik karar desteği hekim kararının yerine geçmez · 1/2/3 tanı seçimi · Space/Enter onay
      </footer>
    </main>
  );
}
