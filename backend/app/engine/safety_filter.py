import re
import unicodedata
from typing import Any

import aiosqlite

from app.database import SEED_RULES
from app.schemas import (
    AnalyzeRequestPayload,
    ClinicalDecisionOutput,
    SafetyAuditBadge,
)

BLOCKED_PREGNANCY_CATEGORIES = {
    "AVOID",
    "CONTRAINDICATED",
    "X",
}

MEDICATION_ALIASES = {
    "losartan": "C09CA01",
    "losartanpotassium": "C09CA01",
    "cozaar": "C09CA01",
    "lisinopril": "C09AA03",
    "zestril": "C09AA03",
    "ramipril": "C09AA05",
    "altace": "C09AA05",
    "amlodipine": "C08CA01",
    "norvasc": "C08CA01",
    "enalapril": "C09AA02",
    "vasotec": "C09AA02",
    "valsartan": "C09CA03",
    "diovan": "C09CA03",
    "irbesartan": "C09CA04",
    "candesartan": "C09CA06",
    "telmisartan": "C09CA07",
    "olmesartan": "C09CA08",
    "kefzol": "J01DB04",
    "cefazolin": "J01DB04",
    "cephazolin": "J01DB04",
    "sefazolin": "J01DB04",
    "cefuroxime": "J01DC02",
    "cefuroksim": "J01DC02",
    "cefixime": "J01DD08",
    "sefiksim": "J01DD08",
    "ceftriaxone": "J01DD04",
    "seftriakson": "J01DD04",
    "cephalexin": "J01DB01",
    "cefalexin": "J01DB01",
    "sefaleksin": "J01DB01",
    "cefotaxime": "J01DD01",
    "sefotaksim": "J01DD01",
    "cefaclor": "J01DC04",
    "sefaklor": "J01DC04",
    "cefadroxil": "J01DB05",
    "sefadroksil": "J01DB05",
    "ceftazidime": "J01DD02",
    "seftazidim": "J01DD02",
    "cefpodoxime": "J01DD13",
    "sefpodoksim": "J01DD13",
    "cefdinir": "J01DD15",
    "sefepime": "J01DE01",
    "sefepim": "J01DE01",
}

PENICILLIN_CROSS_REACTIVE_GROUPS = {"cephalosporin", "beta_lactam"}
FALLBACK_RULES = {
    atc_code: {
        "atc_code": atc_code,
        "drug_name": drug_name,
        "allergy_group": allergy_group,
        "min_egfr_threshold": min_egfr_threshold,
        "max_daily_dose_mg": max_daily_dose_mg,
        "pregnancy_category": pregnancy_category,
    }
    for (
        atc_code,
        drug_name,
        allergy_group,
        min_egfr_threshold,
        max_daily_dose_mg,
        pregnancy_category,
    ) in SEED_RULES
}


def _normalize_drug_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_name = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_name)


def _allergy_matches_rule(
    allergies: set[str], drug_name: str, allergy_group: str
) -> bool:
    normalized_allergies = {
        _normalize_drug_name(allergy) for allergy in allergies if allergy.strip()
    }
    normalized_group = _normalize_drug_name(allergy_group)
    if normalized_group and any(
        normalized_group == allergy
        or normalized_group in allergy
        or allergy in normalized_group
        for allergy in normalized_allergies
    ):
        return True

    normalized_drug = _normalize_drug_name(drug_name)
    if any(
        allergy in normalized_drug or normalized_drug in allergy
        for allergy in normalized_allergies
    ):
        return True

    is_cephalosporin = normalized_group in {
        "cephalosporin",
        "betalactam",
    }
    return is_cephalosporin and any(
        "penicillin" in allergy or "penisilin" in allergy
        for allergy in normalized_allergies
    )


async def _find_drug_rule(
    db: aiosqlite.Connection, atc_code: str, drug_name: str
) -> dict[str, Any] | None:
    normalized_name = _normalize_drug_name(drug_name)
    alias_atcs = dict.fromkeys(
        atc
        for alias, atc in sorted(
            MEDICATION_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
        )
        if _normalize_drug_name(alias) in normalized_name
    )
    for alias_atc in alias_atcs:
        cursor = await db.execute(
            """
            SELECT atc_code, drug_name, allergy_group, min_egfr_threshold,
                   max_daily_dose_mg, pregnancy_category
            FROM drug_safety_rules WHERE atc_code = ?
            """,
            (alias_atc,),
        )
        rule = await cursor.fetchone()
        if rule is not None:
            return dict(rule)
        if alias_atc in FALLBACK_RULES:
            return FALLBACK_RULES[alias_atc]

    normalized_atc = atc_code.strip().upper()
    if normalized_atc:
        cursor = await db.execute(
            """
            SELECT atc_code, drug_name, allergy_group, min_egfr_threshold,
                   max_daily_dose_mg, pregnancy_category
            FROM drug_safety_rules WHERE UPPER(atc_code) = ?
            """,
            (normalized_atc,),
        )
        rule = await cursor.fetchone()
        if rule is not None:
            return dict(rule)
        if normalized_atc in FALLBACK_RULES:
            return FALLBACK_RULES[normalized_atc]

    cursor = await db.execute(
        """
        SELECT atc_code, drug_name, allergy_group, min_egfr_threshold,
               max_daily_dose_mg, pregnancy_category
        FROM drug_safety_rules
        """
    )
    for candidate in await cursor.fetchall():
        candidate_name = _normalize_drug_name(candidate["drug_name"])
        if candidate_name and normalized_name.startswith(candidate_name):
            return dict(candidate)
    for fallback in FALLBACK_RULES.values():
        candidate_name = _normalize_drug_name(fallback["drug_name"])
        if candidate_name and normalized_name.startswith(candidate_name):
            cursor = await db.execute(
                """
                SELECT atc_code, drug_name, allergy_group, min_egfr_threshold,
                       max_daily_dose_mg, pregnancy_category
                FROM drug_safety_rules WHERE UPPER(atc_code) = ?
                """,
                (fallback["atc_code"],),
            )
            rule = await cursor.fetchone()
            return dict(rule) if rule is not None else fallback
    return None


async def enforce_clinical_safety(
    db: aiosqlite.Connection,
    payload: AnalyzeRequestPayload,
    clinical_output: ClinicalDecisionOutput,
) -> tuple[ClinicalDecisionOutput, SafetyAuditBadge]:
    patient = payload.patient_context
    allergies = {allergy.strip().casefold() for allergy in patient.known_allergies}
    safe_medications = []
    interventions: list[str] = []
    warnings: list[str] = []
    allergy_passed = patient.allergy_history_reviewed
    renal_passed = patient.egfr_ml_min is not None
    pregnancy_passed = patient.pregnancy_status is not None
    dose_passed = patient.age is not None and patient.weight_kg is not None
    blockers: list[str] = []

    required_patient_fields = {
        "age": patient.age,
        "biyolojik cinsiyet": patient.sex,
        "kilo": patient.weight_kg,
        "gebelik durumu": patient.pregnancy_status,
        "eGFR": patient.egfr_ml_min,
    }
    for label, value in required_patient_fields.items():
        if value is None:
            clinical_output.missing_clinical_information.append(
                f"Doğrulanmış {label} bilgisi"
            )
    if not patient.allergy_history_reviewed:
        clinical_output.missing_clinical_information.append(
            "Sorgulanmış alerji öyküsü"
        )
    required_vitals = {
        "ateş": payload.vitals.temperature_c,
        "sistolik kan basıncı": payload.vitals.bp_systolic,
        "diyastolik kan basıncı": payload.vitals.bp_diastolic,
        "nabız": payload.vitals.heart_rate_bpm,
        "SpO2": payload.vitals.spo2_percent,
    }
    for label, value in required_vitals.items():
        if value is None:
            clinical_output.missing_clinical_information.append(
                f"Ölçülmüş {label} bilgisi"
            )

    if payload.vitals.spo2_percent is not None and payload.vitals.spo2_percent < 92:
        flag = f"KRİTİK HİPOKSİ: SpO2 %{payload.vitals.spo2_percent} (<%92)."
        if flag not in clinical_output.red_flags_detected:
            clinical_output.red_flags_detected.insert(0, flag)
    if (
        payload.vitals.temperature_c is not None
        and payload.vitals.heart_rate_bpm is not None
        and payload.vitals.temperature_c >= 39
        and payload.vitals.heart_rate_bpm > 100
    ):
        flag = "SIRS / SEPSİS UYARISI: Ateş >= 39 C ve taşikardi (>100 bpm)."
        if flag not in clinical_output.red_flags_detected:
            clinical_output.red_flags_detected.insert(0, flag)

    if clinical_output.red_flags_detected:
        blockers.append(
            "Kritik bulgu mevcut; reçete uygunluğu için hekim tarafından öncelikli değerlendirme gerekir."
        )

    for medication in clinical_output.prescription_protocol:
        rule = await _find_drug_rule(db, medication.atc_code, medication.drug_name)
        reasons: list[str] = []

        if clinical_output.clinical_status != "READY_FOR_PRESCRIPTION":
            reasons.append("Klinik durum reçete için hazır değil")
        if clinical_output.missing_clinical_information:
            reasons.append("Hasta güvenlik bilgileri eksik")
        if clinical_output.red_flags_detected:
            reasons.append("Kritik klinik bulgu mevcut")
        if rule is None:
            allergy_passed = False
            renal_passed = False
            pregnancy_passed = False
            dose_passed = False
            reasons.append("İlaç için doğrulanmış yerel güvenlik kuralı bulunamadı")
        else:
            medication.atc_code = rule["atc_code"]
            allergy_group = (rule["allergy_group"] or "").strip()
            allergy_match = _allergy_matches_rule(
                allergies, rule["drug_name"], allergy_group
            )
            penicillin_cross_reaction = (
                allergy_group.casefold() in PENICILLIN_CROSS_REACTIVE_GROUPS
                and any(
                    "penicillin" in _normalize_drug_name(allergy)
                    or "penisilin" in _normalize_drug_name(allergy)
                    for allergy in allergies
                )
            )
            if allergy_match:
                allergy_passed = False
                allergy_detail = (
                    "Penisilin-sefalosporin çapraz alerji riski"
                    if penicillin_cross_reaction
                    else f"Alerji çakışması ({rule['allergy_group'] or rule['drug_name']})"
                )
                reasons.append(allergy_detail)
            atc_code = rule["atc_code"].upper()
            is_ace_arb = atc_code.startswith(("C09A", "C09B", "C09C", "C09D"))
            if (
                patient.egfr_ml_min is None
                or patient.egfr_ml_min < rule["min_egfr_threshold"]
            ):
                renal_passed = False
                if patient.egfr_ml_min is None:
                    reasons.append("Doğrulanmış eGFR bilgisi yok")
                else:
                    reasons.append(
                        f"Düşük eGFR ({patient.egfr_ml_min} < "
                        f"{rule['min_egfr_threshold']} mL/dk)"
                    )
            if medication.daily_dose_mg > rule["max_daily_dose_mg"]:
                dose_passed = False
                reasons.append(
                    f"Maksimum günlük doz aşıldı ({medication.daily_dose_mg} > "
                    f"{rule['max_daily_dose_mg']} mg)"
                )
            # Seeded ACE/ARB rules have no renal hard-stop; low eGFR triggers monitoring.
            if (
                patient.egfr_ml_min is not None
                and patient.egfr_ml_min < 60
                and is_ace_arb
            ):
                renal_warning = (
                    f"İZLEM UYARISI: {rule['drug_name']} ACE/ARB tedavisinde "
                    f"eGFR {patient.egfr_ml_min} mL/dk (<60); serum kreatinin ve "
                    "potasyum hekim tarafından izlenmelidir."
                )
                if patient.egfr_ml_min < 30:
                    renal_warning = (
                        f"YÜKSEK RİSKLİ İZLEM: {rule['drug_name']} ACE/ARB tedavisinde "
                        f"eGFR {patient.egfr_ml_min} mL/dk (<30); başlama/devam kararı, "
                        "doz ve potasyum/kreatinin izlemi hekim değerlendirmesi gerektirir."
                    )
                    warnings.append(renal_warning)
                    interventions.append(renal_warning)
            if patient.pregnancy_status is None:
                pregnancy_passed = False
                reasons.append("Gebelik durumu doğrulanmamış")
            if (
                patient.pregnancy_status is True
                and rule["pregnancy_category"].strip().upper()
                in BLOCKED_PREGNANCY_CATEGORIES
            ):
                pregnancy_passed = False
                reasons.append(
                    f"Gebelik uyarısı ({rule['pregnancy_category']})"
                )
            elif (
                patient.pregnancy_status is True
                and rule["pregnancy_category"].strip().upper() == "CAUTION"
            ):
                pregnancy_warning = (
                    f"HEKİM DEĞERLENDİRMESİ: {rule['drug_name']} gebelikte dikkat "
                    "gerektirir; otomatik kontrendikasyon olarak değerlendirilmedi."
                )
                warnings.append(pregnancy_warning)
                interventions.append(pregnancy_warning)

        if reasons:
            reason = "; ".join(reasons)
            warning = f"BLOKLANDI: {medication.drug_name} [{reason}]"
            warnings.append(warning)
            interventions.append(warning)
            blockers.append(warning)
            continue

        safe_medications.append(medication)

    clinical_output.prescription_protocol = safe_medications
    if clinical_output.missing_clinical_information:
        clinical_output.clinical_status = "NEEDS_TESTS"
        blockers.extend(clinical_output.missing_clinical_information)
    if blockers:
        clinical_output.clinical_status = "NEEDS_TESTS"
        clinical_output.clinical_blockers = list(
            dict.fromkeys([*clinical_output.clinical_blockers, *blockers])
        )
        clinical_output.prescription_protocol = []
    elif clinical_output.clinical_status == "NEEDS_TESTS":
        clinical_output.prescription_protocol = []

    return clinical_output, SafetyAuditBadge(
        allergy_check_passed=allergy_passed,
        renal_check_passed=renal_passed,
        pregnancy_check_passed=pregnancy_passed,
        dose_check_passed=dose_passed,
        warning_flags=warnings,
        interventions_applied=interventions,
    )
