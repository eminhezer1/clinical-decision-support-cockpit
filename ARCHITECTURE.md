# Clinical Decision Support Cockpit

## Scope and safety

This repository contains a local-first clinical decision-support prototype. The
LLM creates a structured draft; it does not diagnose, prescribe, or approve
care. Every recommendation must be reviewed by a licensed clinician. Passing
automated tests is not clinical validation or production-readiness certification.

Do not enter identifiable patient information into an installation that has not
been approved and secured for that use. Before real clinical deployment, provide
authentication and authorization, encrypted transport and storage, privacy and
retention controls, operational monitoring/backups, clinical validation, and
regulatory review appropriate to the deployment.

## Implemented layout

```text
backend/
  app/
    main.py                       FastAPI application and HTTP routes
    schemas.py                    Pydantic request/response validation
    database.py                   SQLite WAL schema, connection, and seed rules
    engine/
      clinical_analyzer.py        Async Ollama structured-output client
      safety_filter.py            Deterministic medication safety checks
      audit_logger.py             SHA-256 approval audit chain
      document_ingestion.py       PDF/TXT/image extraction and local OCR
frontend/
  src/app/page.tsx                 Three-column clinician cockpit
  src/lib/clinical-api.ts           Typed HTTP client
  src/lib/epicrisis.ts              Epicrisis text formatter
```

The SQLite database is created at `backend/clinical.db`. `database.py` initializes
the three application tables: `clinical_sessions`, `doctor_approvals_audit`,
and `drug_safety_rules`; it enables WAL and foreign-key enforcement and seeds
curated medication rules. There is no separate SQL schema file or ICD-10 catalog
table in the current implementation.

## Clinical request and safety flow

1. `POST /api/v1/clinical/analyze` validates the request against the Pydantic
   schemas.
2. The backend sends the case to the configured local Ollama model using
   structured JSON output and `temperature=0.0`. `OLLAMA_MODEL` selects the
   model and `OLLAMA_TIMEOUT_SECONDS` sets the inference timeout (default 300
   seconds).
3. `safety_filter.py` applies local rules for allergy group, eGFR, pregnancy,
   dose, and red flags before the session is stored and returned. It resolves
   known medication aliases and falls back only to curated seed rules. Unknown
   medications without a recognized rule are blocked; they are not implicitly
   approved.
4. ACE inhibitors and ARBs are not automatically blocked solely for eGFR below
   60. The filter surfaces a monitoring warning below 60 and escalates the
   clinician-evaluation warning below 30. Other medicine-specific renal rules
   still apply.
5. `POST /api/v1/clinical/upload-context` accepts PDF, TXT, PNG, and JPEG files.
   PDF text is extracted with PyMuPDF; scanned pages and images use local
   Tesseract OCR with Turkish and English language data. Uploads are processed
   in memory, are not written to disk, and are limited to 15 MB per file, 30
   pages per PDF, 8 files, and 30,000 extracted characters per analysis.
6. The frontend starts with an empty case and asks for a free-text history,
   optional documents, and clinician-verified safety data and vitals. It does
   not load synthetic example cases or claim access to e-Nabız.
7. `NEEDS_TESTS` displays the differential, missing data, blockers, and
   requested tests; it hides the prescription and only copies a local test-order
   draft. There is no HBYS connection and no test order is transmitted.
   `READY_FOR_PRESCRIPTION` displays the medication safety checks and editable
   prescription draft.
8. A clinician selects a listed diagnosis and submits approval. The backend
   rejects approvals for unresolved analyses and re-runs deterministic safety
   rules against an edited prescription before recording it. The frontend
   measures review time, displays the returned audit hash, and copies the
   formatted epicrisis when browser clipboard permissions allow it.

The approval audit is a tamper-evident SHA-256 chain whose hash includes the
approval details, analysis output, timestamp, and previous record hash. The
Python function `verify_audit_chain` is available in `audit_logger.py`; there
is currently no HTTP audit-verification route.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/clinical/upload-context` | Extract temporary text and SHA-256 metadata from uploaded PDF/TXT/PNG/JPEG files. |
| `POST` | `/api/v1/clinical/analyze` | Validate a case, run Ollama inference, apply safety rules, and persist the analysis session. Ollama failures return HTTP 503. |
| `POST` | `/api/v1/clinical/approve` | Validate the selected diagnosis, re-check edited medication safety, and append an allowed approval to the hash chain. |
| `GET` | `/api/v1/clinical/diagnostics` | Check Ollama reachability/model availability and SQLite drug-rule availability without sending patient data. |

Every API response includes an `X-Request-ID`. The cockpit logs inference
stages with that ID, and the error panel can run the diagnostics endpoint and
copy its report alongside the HTTP error. Search the backend terminal output
for the same ID to correlate the browser failure with the server-side stage.
Diagnostic output contains service/configuration status only; it does not
include patient or model prompt content.

The browser sends API calls to the current frontend origin. Next.js proxies
`/api/v1/clinical/*` to `BACKEND_INTERNAL_URL`, defaulting to
`http://127.0.0.1:8000`. This avoids embedding a machine-specific address in
the browser bundle. Its proxy timeout is 630 seconds, enough for two backend
Ollama inference attempts at the default 300 seconds each. The backend
`CORS_ORIGINS` remains restricted to local development origins; wildcard
origins are rejected.

## Unified startup

From the project root, run `python start.py`. The script creates the backend
virtual environment if needed, installs Python and npm dependencies, builds the
frontend, starts Ollama if its local API is unavailable, pulls the configured
model if missing, then launches the backend and frontend on loopback. Use
`python start.py --dev` to run the Next.js development server without a
production build. Press Ctrl+C to stop the services started by the script.

Python 3.10+, Node.js/npm, and Ollama must be installed. For scanned PDF and
image OCR, install Tesseract with `tur` and `eng` language data; set
`TESSERACT_CMD` in `backend/.env` if its executable is not on `PATH`. The SQLite
database is initialized automatically on first startup and is kept in
`backend/data/clinical.db`.

The older platform-specific scripts `run-linux.sh` and `run-windows.ps1` are
also present, but `start.py` is the single recommended startup entry point.

The launch scripts intentionally bind to loopback only. This avoids exposing
unauthenticated clinical APIs to the network. A public deployment still
requires a TLS reverse proxy and real authentication/authorization before any
patient data is entered; there is no domain-independent safe way to make this
application publicly accessible over plain HTTP.

## Manual Windows PowerShell setup

Requirements: Python 3.11 or newer, Node.js/npm, and Ollama installed and
running locally. From the repository root:

```powershell
# Ollama model (download the chosen model once)
ollama pull qwen2.5:7b-instruct

# Backend
Set-Location .\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For a different Ollama model, ensure it is installed (`ollama pull <model>`) and
set `OLLAMA_MODEL=<model>` in `backend\.env` before starting the API.

In a second PowerShell terminal, from the repository root:

```powershell
Set-Location .\frontend
npm ci
npm run build
npm start
```

The production frontend defaults to port 3000. For local development, use
`npm run dev` instead of `npm start`.

## Configuration and verification

- `backend/.env`: `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`, `CORS_ORIGINS`,
  `CLINICAL_DB_PATH`, and optional `TESSERACT_CMD`.
- `frontend/.env.local`: internal backend proxy URL.
- Backend tests: from `backend`, run
  `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` on Windows or
  `./.venv/bin/python -m unittest discover -s tests -v` on Linux.
- Frontend type check: from `frontend`, run `npm run lint`.
- Frontend production compile: from `frontend`, run `npm run build`.

The deployment archive contains runtime `.env` configuration and excludes
`backend/tests/` and the local SQLite database. Review and replace all runtime
configuration for the target server before exposing even a localhost service.
The root `.gitignore` excludes environment files, the local SQLite database and
sidecars, Python caches, `node_modules`, and Next.js build output.

Local-only Ollama inference, SQLite persistence, and automated checks do not
provide high availability, clinical effectiveness evidence, or a complete
enterprise security boundary. Production deployment requires those concerns to
be addressed and independently reviewed.
