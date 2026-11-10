import os
from pathlib import Path
from collections.abc import AsyncIterator

import aiosqlite
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
configured_db_path = Path(os.getenv("CLINICAL_DB_PATH", "clinical.db"))
DB_PATH = (
    configured_db_path
    if configured_db_path.is_absolute()
    else BACKEND_DIR / configured_db_path
)

SEED_RULES = (
    ("J01CR02", "Amoksisilin/Klavulanat", "PENICILLIN", 30, 2000, "LOW_RISK"),
    ("J01FA09", "Klaritromisin", "MACROLIDE", 30, 1000, "CAUTION"),
    ("J01MA02", "Siprofloksasin", "FLUOROQUINOLONE", 30, 1500, "AVOID"),
    ("N02BE01", "Parasetamol", "PARACETAMOL", 10, 4000, "LOW_RISK"),
    ("M01AE01", "İbuprofen", "NSAID", 60, 1200, "AVOID"),
    ("M01AE17", "Deksketoprofen", "NSAID", 60, 75, "AVOID"),
    ("R05CB01", "Asetilsistein", "ACETYLCYSTEINE", 0, 1200, "CAUTION"),
    ("A10BA02", "Metformin", "BIGUANIDE", 30, 2550, "CAUTION"),
    ("A02BC02", "Pantoprazol", "PROTON_PUMP_INHIBITOR", 0, 80, "LOW_RISK"),
    ("B01AB05", "Enoksaparin", "HEPARIN", 15, 180, "CAUTION"),
    ("C09CA01", "Losartan", "ARB", 0, 100, "AVOID"),
    ("C09AA03", "Lisinopril", "ACE_INHIBITOR", 0, 40, "AVOID"),
    ("C09AA05", "Ramipril", "ACE_INHIBITOR", 0, 10, "AVOID"),
    ("C08CA01", "Amlodipin", "CALCIUM_CHANNEL_BLOCKER", 0, 10, "CAUTION"),
    ("C09AA02", "Enalapril", "ACE_INHIBITOR", 0, 40, "AVOID"),
    ("C09CA03", "Valsartan", "ARB", 0, 320, "AVOID"),
    ("C09CA04", "Irbesartan", "ARB", 0, 300, "AVOID"),
    ("C09CA06", "Kandesartan", "ARB", 0, 32, "AVOID"),
    ("C09CA07", "Telmisartan", "ARB", 0, 80, "AVOID"),
    ("C09CA08", "Olmesartan", "ARB", 0, 40, "AVOID"),
    ("J01DB04", "Sefazolin (Kefzol)", "CEPHALOSPORIN", 0, 6000, "LOW_RISK"),
    ("J01DC02", "Sefuroksim", "CEPHALOSPORIN", 0, 3000, "LOW_RISK"),
    ("J01DD08", "Sefiksim", "CEPHALOSPORIN", 0, 400, "LOW_RISK"),
    ("J01DD04", "Seftriakson", "CEPHALOSPORIN", 0, 4000, "LOW_RISK"),
    ("J01DB01", "Sefaleksin", "CEPHALOSPORIN", 0, 4000, "LOW_RISK"),
    ("J01DD01", "Sefotaksim", "CEPHALOSPORIN", 0, 12000, "LOW_RISK"),
    ("J01DC04", "Sefaklor", "CEPHALOSPORIN", 0, 1500, "LOW_RISK"),
    ("J01DB05", "Sefadroksil", "CEPHALOSPORIN", 0, 4000, "LOW_RISK"),
    ("J01DD02", "Seftazidim", "CEPHALOSPORIN", 0, 6000, "LOW_RISK"),
    ("J01DD13", "Sefpodoksim", "CEPHALOSPORIN", 0, 800, "LOW_RISK"),
    ("J01DD15", "Sefdinir", "CEPHALOSPORIN", 0, 600, "LOW_RISK"),
    ("J01DE01", "Sefepim", "CEPHALOSPORIN", 0, 6000, "LOW_RISK"),
)

SEED_ALLERGY_GROUPS = tuple(
    (allergy_group, atc_code)
    for atc_code, _, allergy_group, _, _, _ in SEED_RULES
    if allergy_group
)

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS clinical_sessions (
    session_id TEXT PRIMARY KEY,
    patient_hash TEXT NOT NULL,
    input_payload TEXT NOT NULL,
    ai_output_payload TEXT NOT NULL,
    model_version TEXT NOT NULL,
    processing_time_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS doctor_approvals_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES clinical_sessions(session_id),
    doctor_id TEXT NOT NULL,
    doctor_diploma_no TEXT NOT NULL,
    selected_diagnosis_rank INTEGER NOT NULL CHECK (selected_diagnosis_rank BETWEEN 1 AND 3),
    modified_prescription TEXT,
    approval_action TEXT NOT NULL,
    review_duration_ms INTEGER NOT NULL,
    prev_record_hash TEXT NOT NULL,
    current_record_hash TEXT NOT NULL,
    approved_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_doctor_approvals_session
    ON doctor_approvals_audit(session_id);

CREATE INDEX IF NOT EXISTS idx_doctor_approvals_prev_hash
    ON doctor_approvals_audit(prev_record_hash);

CREATE TABLE IF NOT EXISTS drug_safety_rules (
    atc_code TEXT PRIMARY KEY,
    drug_name TEXT NOT NULL,
    allergy_group TEXT,
    min_egfr_threshold REAL NOT NULL DEFAULT 0,
    max_daily_dose_mg REAL NOT NULL,
    pregnancy_category TEXT NOT NULL
);
"""


async def connect_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    return db


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        await db.executescript(CREATE_TABLES)
        await db.executemany(
            """
            INSERT OR IGNORE INTO drug_safety_rules (
                atc_code, drug_name, allergy_group, min_egfr_threshold,
                max_daily_dose_mg, pregnancy_category
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            SEED_RULES,
        )
        await db.executemany(
            """
            UPDATE drug_safety_rules SET allergy_group = ?
            WHERE atc_code = ? AND (allergy_group IS NULL OR allergy_group = '')
            """,
            SEED_ALLERGY_GROUPS,
        )
        await db.commit()


async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await connect_db()
    try:
        yield db
    finally:
        await db.close()
