export interface EpicrisisVitals {
  temperature_c: number;
  bp_systolic: number;
  bp_diastolic: number;
  heart_rate_bpm: number;
  spo2_percent: number;
}

export interface EpicrisisDiagnosis {
  icd10_code: string;
  condition_name: string;
}

export interface EpicrisisMedication {
  drug_name: string;
  dosage: string;
  duration_days: number;
}

export function formatToEpicrisisText(
  chiefComplaint: string,
  patient: { age: number; sex: "M" | "F" },
  vitals: EpicrisisVitals,
  selectedDiagnosis: EpicrisisDiagnosis,
  medications: EpicrisisMedication[],
  workup: string[],
): string {
  const medicationLines = medications.length
    ? medications
        .map(
          (medication, index) =>
            `${index + 1}. ${medication.drug_name} - ${medication.dosage} (${medication.duration_days} gün)`,
        )
        .join("\n")
    : "Reçete düzenlenmedi.";
  const workupLines = workup.length
    ? workup.join(", ")
    : "Ek tetkik planlanmadı.";

  return [
    "EPİKRİZ VE REÇETE METNİ",
    `ANAMNEZ: ${patient.age} yaş, ${patient.sex === "F" ? "Kadın" : "Erkek"}. ${chiefComplaint}`,
    `VİTAL BULGULAR: Ateş ${vitals.temperature_c} °C | TA ${vitals.bp_systolic}/${vitals.bp_diastolic} mmHg | Nabız ${vitals.heart_rate_bpm}/dk | SpO₂ %${vitals.spo2_percent}`,
    `TANI (ICD-10): ${selectedDiagnosis.icd10_code} - ${selectedDiagnosis.condition_name}`,
    `İSTENEN TETKİKLER: ${workupLines}`,
    `REÇETE / TEDAVİ PROTOKOLÜ:\n${medicationLines}`,
    "NOT: Klinik karar destek sistemi eşliğinde hekim tarafından değerlendirilip onaylanmıştır.",
  ].join("\n\n");
}
