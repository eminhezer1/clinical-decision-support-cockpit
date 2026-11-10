import asyncio
import io
import os
import re
from dataclasses import dataclass
from hashlib import sha256

import fitz
import pytesseract
from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.schemas import UploadedDocumentMetadata

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_DOCUMENTS = 8
MAX_CONTEXT_CHARACTERS = 30_000
OCR_PAGE_TIMEOUT_SECONDS = 12
OCR_LANGUAGE = "tur+eng"
TESSERACT_COMMAND = os.getenv("TESSERACT_CMD")
if TESSERACT_COMMAND:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_COMMAND

_PDF_SUFFIXES = {".pdf"}
_TEXT_SUFFIXES = {".txt"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


class DocumentProcessingError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    metadata: UploadedDocumentMetadata


async def extract_uploaded_documents(
    uploads: list[UploadFile],
) -> tuple[str, list[UploadedDocumentMetadata]]:
    if not uploads:
        raise DocumentProcessingError("En az bir PDF, TXT veya görsel dosyası ekleyin.")
    if len(uploads) > MAX_DOCUMENTS:
        raise DocumentProcessingError(
            f"Tek istekte en fazla {MAX_DOCUMENTS} belge yüklenebilir.", 413
        )

    extracted: list[ExtractedDocument] = []
    total_characters = 0
    try:
        for upload in uploads:
            data = await _read_limited(upload)
            document = await asyncio.to_thread(
                _extract_document, upload.filename or "", data
            )
            total_characters += len(document.text)
            if total_characters > MAX_CONTEXT_CHARACTERS:
                raise DocumentProcessingError(
                    f"Belgelerden çıkarılan toplam metin "
                    f"{MAX_CONTEXT_CHARACTERS} karakter sınırını aşıyor.",
                    413,
                )
            extracted.append(document)
    finally:
        for upload in uploads:
            await upload.close()

    sections = [
        f"[Belge {index} | SHA-256: {item.metadata.sha256}]\n{item.text}"
        for index, item in enumerate(extracted, start=1)
    ]
    context = "\n\n".join(sections)
    if len(context) > MAX_CONTEXT_CHARACTERS:
        raise DocumentProcessingError(
            f"Belge başlıklarıyla birlikte toplam metin "
            f"{MAX_CONTEXT_CHARACTERS} karakter sınırını aşıyor.",
            413,
        )
    return context, [item.metadata for item in extracted]


async def _read_limited(upload: UploadFile) -> bytes:
    content = bytearray()
    while chunk := await upload.read(64 * 1024):
        content.extend(chunk)
        if len(content) > MAX_FILE_BYTES:
            raise DocumentProcessingError(
                f"Bir dosya {MAX_FILE_BYTES // (1024 * 1024)} MB sınırını aşıyor.",
                413,
            )
    if not content:
        raise DocumentProcessingError("Boş dosya yüklenemez.")
    return bytes(content)


def _extract_document(filename: str, data: bytes) -> ExtractedDocument:
    suffix = _suffix(filename)
    if suffix in _PDF_SUFFIXES:
        if not data.startswith(_PDF_MAGIC):
            raise DocumentProcessingError("PDF dosya içeriği geçersiz.")
        return _extract_pdf(data)
    if suffix in _TEXT_SUFFIXES:
        return _extract_text(data)
    if suffix in _IMAGE_SUFFIXES:
        return _extract_image(data)
    raise DocumentProcessingError(
        "Desteklenen biçimler PDF, TXT, PNG ve JPEG'dir."
    )


def _suffix(filename: str) -> str:
    clean_name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    return "." + clean_name.rsplit(".", maxsplit=1)[-1].casefold() if "." in clean_name else ""


def _metadata(
    media_type: str, data: bytes, text: str, page_count: int | None
) -> UploadedDocumentMetadata:
    if not text.strip():
        raise DocumentProcessingError(
            "Belgeden okunabilir metin çıkarılamadı; kaynak dosyayı kontrol edin."
        )
    if len(text) > MAX_CONTEXT_CHARACTERS:
        raise DocumentProcessingError(
            f"Belge metni {MAX_CONTEXT_CHARACTERS} karakter sınırını aşıyor.", 413
        )
    return UploadedDocumentMetadata(
        media_type=media_type,
        sha256=sha256(data).hexdigest(),
        extracted_characters=len(text),
        page_count=page_count,
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def _extract_text(data: bytes) -> ExtractedDocument:
    try:
        text = _normalize_text(data.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise DocumentProcessingError(
            "TXT dosyaları UTF-8 kodlamasında olmalıdır."
        ) from exc
    return ExtractedDocument(
        text=text,
        metadata=_metadata("text/plain", data, text, page_count=None),
    )


def _ocr_image(image: Image.Image) -> str:
    try:
        return pytesseract.image_to_string(
            image, lang=OCR_LANGUAGE, timeout=OCR_PAGE_TIMEOUT_SECONDS
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise DocumentProcessingError(
            "Tesseract OCR kurulu değil. Sunucuya Tesseract ve tur/eng dil "
            "verilerini kurup servisi yeniden başlatın.",
            503,
        ) from exc
    except pytesseract.TesseractError as exc:
        raise DocumentProcessingError(
            "Görsel OCR işlemi tamamlanamadı; dosya kalitesi veya OCR dil "
            "kurulumu kontrol edilmeli."
        ) from exc
    except RuntimeError as exc:
        raise DocumentProcessingError(
            "OCR zaman aşımına uğradı. Daha net veya daha küçük bir görsel deneyin.",
            503,
        ) from exc


def _extract_image(data: bytes) -> ExtractedDocument:
    if data.startswith(_PNG_MAGIC):
        media_type = "image/png"
    elif data.startswith(_JPEG_MAGIC):
        media_type = "image/jpeg"
    else:
        raise DocumentProcessingError("PNG/JPEG dosya içeriği geçersiz.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 60_000_000:
                raise DocumentProcessingError(
                    "Görsel 60 megapiksel sınırını aşıyor.", 413
                )
            image.load()
            text = _normalize_text(_ocr_image(image.convert("RGB")))
    except DocumentProcessingError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise DocumentProcessingError("Görsel açılamadı veya bozuk.") from exc
    return ExtractedDocument(
        text=text,
        metadata=_metadata(media_type, data, text, page_count=1),
    )


def _extract_pdf(data: bytes) -> ExtractedDocument:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except (fitz.FileDataError, RuntimeError) as exc:
        raise DocumentProcessingError("PDF açılamadı veya bozuk.") from exc
    try:
        if document.is_encrypted:
            raise DocumentProcessingError(
                "Parola korumalı PDF çözümlenemiyor; korumasız bir kopya yükleyin."
            )
        if len(document) == 0:
            raise DocumentProcessingError("PDF içinde sayfa bulunamadı.")
        if len(document) > MAX_PDF_PAGES:
            raise DocumentProcessingError(
                f"PDF en fazla {MAX_PDF_PAGES} sayfa olabilir.", 413
            )
        pages: list[str] = []
        for page in document:
            page_text = page.get_text("text")
            if not page_text.strip():
                rectangle = page.rect
                if rectangle.width * rectangle.height * 2.25 > 20_000_000:
                    raise DocumentProcessingError(
                        "PDF sayfa boyutu OCR için izin verilen piksel sınırını aşıyor.",
                        413,
                    )
                try:
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(1.5, 1.5), alpha=False
                    )
                except (fitz.MuPDFError, MemoryError) as exc:
                    raise DocumentProcessingError(
                        "PDF sayfası OCR için güvenli biçimde işlenemedi."
                    ) from exc
                try:
                    with Image.open(io.BytesIO(pixmap.tobytes("png"))) as image:
                        page_text = _ocr_image(image.convert("RGB"))
                except (UnidentifiedImageError, OSError) as exc:
                    raise DocumentProcessingError(
                        "Taranmış PDF sayfası OCR için işlenemedi."
                    ) from exc
            pages.append(_normalize_text(page_text))
        text = "\n\n".join(page for page in pages if page)
    finally:
        document.close()
    return ExtractedDocument(
        text=text,
        metadata=_metadata("application/pdf", data, text, page_count=len(pages)),
    )
