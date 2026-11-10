import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlsplit

import aiosqlite
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import get_db, init_db
from app.engine.audit_logger import ApprovalNotAllowedError, record_doctor_approval
from app.engine.clinical_analyzer import (
    MODEL_NAME,
    OLLAMA_TIMEOUT_SECONDS,
    OllamaInferenceError,
    generate_clinical_decision,
)
from app.engine.document_ingestion import (
    DocumentProcessingError,
    extract_uploaded_documents,
)
from app.engine.safety_filter import enforce_clinical_safety
from app.schemas import (
    AnalyzeRequestPayload,
    AnalyzeResponsePayload,
    ApprovalResponse,
    DoctorApprovalRequest,
    UploadContextResponse,
)

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
)


def _configured_cors_origins() -> list[str]:
    configured = os.getenv("CORS_ORIGINS")
    origins = (
        [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
        if configured is not None
        else list(DEFAULT_CORS_ORIGINS)
    )
    if not origins:
        raise ValueError("CORS_ORIGINS must contain at least one trusted origin.")
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            origin == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"Invalid CORS origin: {origin!r}")
    return origins


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="Clinical Decision & Auto-Approval Engine", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    return str(uuid.uuid4())


@app.middleware("http")
async def add_request_diagnostics(request: Request, call_next):
    supplied_id = request.headers.get("x-request-id", "")
    request_id = (
        supplied_id
        if supplied_id
        and len(supplied_id) <= 64
        and all(
            character.isascii()
            and (character.isalnum() or character in "-_.:")
            for character in supplied_id
        )
        else str(uuid.uuid4())
    )
    request.state.request_id = request_id
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.exception(
            "request_id=%s method=%s path=%s elapsed_ms=%d unhandled_request_error",
            request_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%d elapsed_ms=%d",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    logger.exception(
        "request_id=%s path=%s unhandled_application_error",
        request_id,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Beklenmeyen sunucu hatası. Sunucu loglarında istek kimliğiyle arayın.",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


@app.post(
    "/api/v1/clinical/upload-context",
    response_model=UploadContextResponse,
)
async def upload_clinical_context(
    files: list[UploadFile] = File(..., description="PDF, TXT, PNG veya JPEG belgeleri"),
) -> UploadContextResponse:
    try:
        context, metadata = await extract_uploaded_documents(files)
    except DocumentProcessingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return UploadContextResponse(
        clinical_context=context,
        documents=metadata,
        total_characters=len(context),
    )


@app.get("/api/v1/clinical/diagnostics")
async def get_diagnostics(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, object]:
    request_id = _request_id(request)
    ollama_reachable = False
    installed_models: list[str] = []
    ollama_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0)) as client:
            response = await client.get("http://127.0.0.1:11434/api/tags")
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("models"), list):
            installed_models = [
                item["name"]
                for item in payload["models"]
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            ollama_reachable = True
        else:
            ollama_error = "Ollama /api/tags response has an unexpected shape."
    except (httpx.HTTPError, ValueError) as exc:
        ollama_error = f"{type(exc).__name__}: {exc}"

    database_ok = False
    drug_rule_count: int | None = None
    database_error: str | None = None
    try:
        cursor = await db.execute("SELECT COUNT(*) AS count FROM drug_safety_rules")
        row = await cursor.fetchone()
        drug_rule_count = int(row["count"]) if row is not None else 0
        database_ok = True
    except aiosqlite.Error as exc:
        database_error = f"{type(exc).__name__}: {exc}"

    return {
        "request_id": request_id,
        "model": MODEL_NAME,
        "ollama_timeout_seconds": OLLAMA_TIMEOUT_SECONDS,
        "ollama_reachable": ollama_reachable,
        "model_installed": MODEL_NAME in installed_models
        or f"{MODEL_NAME}:latest" in installed_models,
        "installed_models": installed_models,
        "ollama_error": ollama_error,
        "database_ok": database_ok,
        "drug_safety_rule_count": drug_rule_count,
        "database_error": database_error,
    }


@app.post("/api/v1/clinical/analyze", response_model=AnalyzeResponsePayload)
async def analyze_clinical_case(
    payload: AnalyzeRequestPayload,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> AnalyzeResponsePayload:
    request_id = _request_id(request)
    started_at = time.perf_counter()
    logger.info(
        "request_id=%s stage=analysis_started patient_hash_present=%s document_characters=%d",
        request_id,
        bool(payload.patient_context.patient_tc_hash),
        len(payload.clinical_context),
    )
    existing = await (
        await db.execute(
            "SELECT 1 FROM clinical_sessions WHERE session_id = ?",
            (payload.session_id,),
        )
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="session_id daha önce kullanılmış.")

    try:
        clinical_output, _, model_version = await generate_clinical_decision(
            payload, request_id=request_id
        )
    except OllamaInferenceError as exc:
        logger.warning(
            "request_id=%s stage=ollama_inference_failed error=%s",
            request_id,
            str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": str(exc),
                "request_id": request_id,
                "stage": "ollama_inference",
            },
            headers={"X-Request-ID": request_id},
        ) from exc
    except Exception as exc:
        logger.exception(
            "request_id=%s stage=ollama_inference_unhandled",
            request_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Klinik analiz motorunda beklenmeyen hata.",
                "request_id": request_id,
                "stage": "clinical_analysis",
            },
            headers={"X-Request-ID": request_id},
        ) from exc

    try:
        clinical_output, safety_badges = await enforce_clinical_safety(
            db, payload, clinical_output
        )
    except aiosqlite.Error as exc:
        logger.exception(
            "request_id=%s stage=safety_filter_database_failed", request_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "İlaç güvenlik kuralları veritabanından okunamadı.",
                "request_id": request_id,
                "stage": "safety_filter",
            },
            headers={"X-Request-ID": request_id},
        ) from exc
    processing_time_ms = int((time.perf_counter() - started_at) * 1000)
    ai_output_payload = clinical_output.model_dump_json()
    response = AnalyzeResponsePayload(
        session_id=payload.session_id,
        processing_time_ms=processing_time_ms,
        safety_badges=safety_badges,
        clinical_decision=clinical_output,
    )

    persisted_input = payload.model_dump(mode="json", exclude={"clinical_context"})
    persisted_input["clinical_context_sha256"] = hashlib.sha256(
        payload.clinical_context.encode("utf-8")
    ).hexdigest()
    persisted_input["clinical_context_char_count"] = len(payload.clinical_context)
    try:
        await db.execute(
            """
            INSERT INTO clinical_sessions (
                session_id, patient_hash, input_payload, ai_output_payload,
                model_version, processing_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.session_id,
                payload.patient_context.patient_tc_hash,
                json.dumps(
                    persisted_input, ensure_ascii=False, separators=(",", ":")
                ),
                ai_output_payload,
                model_version,
                processing_time_ms,
            ),
        )
        await db.commit()
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="session_id daha önce kullanılmış.") from exc
    except aiosqlite.Error as exc:
        logger.exception("request_id=%s stage=clinical_session_persist_failed", request_id)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Klinik analiz oturumu kaydedilemedi.",
                "request_id": request_id,
                "stage": "persistence",
            },
            headers={"X-Request-ID": request_id},
        ) from exc
    return response


@app.post("/api/v1/clinical/approve", response_model=ApprovalResponse)
async def approve_clinical_case(
    payload: DoctorApprovalRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> ApprovalResponse:
    try:
        receipt = await record_doctor_approval(db, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Klinik oturum bulunamadı.") from exc
    except ApprovalNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Onay denetim kaydı oluşturulamadı.") from exc
    except aiosqlite.Error as exc:
        logger.exception("Doctor approval audit record could not be stored")
        raise HTTPException(
            status_code=500, detail="Onay denetim kaydı kaydedilemedi."
        ) from exc
    return ApprovalResponse(**receipt)
