"""
PDF resume text extraction with PyMuPDF (imported as `fitz`).

Design choices:
- Work from in-memory bytes so original user files are never overwritten.
- Detect empty, corrupted, and likely-scanned PDFs instead of inventing text.
- Keep the original filename as metadata only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import fitz

from src.utils import safe_filename


# If a page has images but almost no characters, OCR would be required.
SCANNED_TEXT_CHAR_LIMIT = 40
MIN_USEFUL_TEXT_CHARS = 80


@dataclass
class PdfExtractionResult:
    original_filename: str
    text: str
    page_count: int
    status: str
    warnings: list[str] = field(default_factory=list)
    needs_ocr: bool = False
    error_message: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.status == "ok" and len(self.text.strip()) >= MIN_USEFUL_TEXT_CHARS


def extract_text_from_pdf_bytes(
    pdf_bytes: bytes,
    original_filename: str | None = None,
) -> PdfExtractionResult:
    """
    Extract selectable text from a PDF stored in memory.

    PyMuPDF can read digital (text-based) PDFs well. It cannot reliably read
    scanned image-only pages unless a separate OCR tool is added. This project
    does not guess OCR text.
    """
    filename = safe_filename(original_filename)

    if not pdf_bytes:
        return PdfExtractionResult(
            original_filename=filename,
            text="",
            page_count=0,
            status="empty_file",
            warnings=["The uploaded file had no bytes."],
            error_message="The PDF file is empty.",
        )

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as error:  # noqa: BLE001 - show a beginner-friendly reason
        return PdfExtractionResult(
            original_filename=filename,
            text="",
            page_count=0,
            status="unreadable",
            warnings=["PyMuPDF could not open this file as a PDF."],
            error_message=f"The PDF could not be opened. Details: {error}",
        )

    try:
        return _extract_from_open_document(document, filename)
    finally:
        document.close()


def _extract_from_open_document(document: fitz.Document, filename: str) -> PdfExtractionResult:
    if document.is_encrypted:
        return PdfExtractionResult(
            original_filename=filename,
            text="",
            page_count=document.page_count,
            status="encrypted",
            warnings=["This PDF is password-protected."],
            error_message="Encrypted PDFs are not screened. Upload an unlocked copy.",
        )

    page_texts: list[str] = []
    image_only_pages = 0
    warnings: list[str] = []

    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        page_text = page.get_text("text") or ""
        page_texts.append(page_text)

        image_count = len(page.get_images())
        if image_count > 0 and len(page_text.strip()) < SCANNED_TEXT_CHAR_LIMIT:
            image_only_pages += 1

    full_text = "\n".join(page_texts).strip()
    needs_ocr = image_only_pages > 0 and len(full_text) < MIN_USEFUL_TEXT_CHARS

    if document.page_count == 0:
        return PdfExtractionResult(
            original_filename=filename,
            text="",
            page_count=0,
            status="empty_file",
            warnings=["The PDF has no pages."],
            error_message="The PDF has no pages to read.",
        )

    if needs_ocr:
        warnings.append(
            "This looks like a scanned/image PDF. Optical Character Recognition (OCR) "
            "would be needed to read it. This app does not run OCR and will not invent text."
        )
        return PdfExtractionResult(
            original_filename=filename,
            text=full_text,
            page_count=document.page_count,
            status="needs_ocr",
            warnings=warnings,
            needs_ocr=True,
            error_message="No selectable text was found. Use a text-based PDF or OCR first.",
        )

    if len(full_text) < MIN_USEFUL_TEXT_CHARS:
        warnings.append("Very little text was extracted. The resume may be a scan or a graphic.")
        return PdfExtractionResult(
            original_filename=filename,
            text=full_text,
            page_count=document.page_count,
            status="insufficient_text",
            warnings=warnings,
            needs_ocr=image_only_pages > 0,
            error_message="Not enough text was extracted to screen this resume fairly.",
        )

    return PdfExtractionResult(
        original_filename=filename,
        text=full_text,
        page_count=document.page_count,
        status="ok",
        warnings=warnings,
    )


def make_simple_pdf_bytes(text: str) -> bytes:
    """
    Create a tiny text PDF in memory. Used by tests and sample generators.

    This never writes to the user's original resume files.
    """
    document = fitz.open()
    page = document.new_page()
    # A text box wraps long sample resumes so tests get enough selectable characters.
    page.insert_textbox(page.rect + (36, 36, -36, -36), text, fontsize=11)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes
