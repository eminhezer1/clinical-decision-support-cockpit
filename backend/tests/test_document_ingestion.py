import io
import unittest

import fitz
from fastapi import UploadFile

from app.engine.document_ingestion import (
    DocumentProcessingError,
    MAX_PDF_PAGES,
    _extract_document,
    extract_uploaded_documents,
)


class DocumentIngestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_text_is_extracted_and_hashed(self) -> None:
        upload = UploadFile(
            filename="laboratory.txt",
            file=io.BytesIO("CRP: 2 mg/L".encode("utf-8")),
        )

        context, metadata = await extract_uploaded_documents([upload])

        self.assertIn("CRP: 2 mg/L", context)
        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0].media_type, "text/plain")
        self.assertEqual(metadata[0].extracted_characters, len("CRP: 2 mg/L"))
        self.assertEqual(len(metadata[0].sha256), 64)

    async def test_pdf_extension_requires_valid_pdf_signature(self) -> None:
        with self.assertRaises(DocumentProcessingError):
            _extract_document("report.pdf", b"not a PDF")

    async def test_pdf_page_limit_is_enforced(self) -> None:
        document = fitz.open()
        for page_number in range(MAX_PDF_PAGES + 1):
            page = document.new_page()
            page.insert_text((72, 72), f"Test page {page_number + 1}")
        pdf_bytes = document.tobytes()
        document.close()

        with self.assertRaises(DocumentProcessingError) as raised:
            _extract_document("too-many-pages.pdf", pdf_bytes)

        self.assertEqual(raised.exception.status_code, 413)

    async def test_empty_document_batch_is_rejected(self) -> None:
        with self.assertRaises(DocumentProcessingError):
            await extract_uploaded_documents([])


if __name__ == "__main__":
    unittest.main()
