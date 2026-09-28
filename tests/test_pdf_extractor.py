"""PDF extraction tests. These create tiny PDFs in memory and never touch user files."""

from src.pdf_extractor import extract_text_from_pdf_bytes, make_simple_pdf_bytes


def test_extracts_text_from_simple_pdf():
    pdf_bytes = make_simple_pdf_bytes(
        "Fictional sample resume. Skills include Python, SQL, Docker, and intern experience "
        "on backend APIs. This paragraph exists so the extractor has enough selectable text."
    )
    result = extract_text_from_pdf_bytes(pdf_bytes, "alex.pdf")
    assert result.status == "ok"
    assert result.original_filename == "alex.pdf"
    assert "python" in result.text.lower()
    assert result.is_usable


def test_empty_bytes_are_handled():
    result = extract_text_from_pdf_bytes(b"", "empty.pdf")
    assert result.status == "empty_file"
    assert result.text == ""
    assert result.error_message
    assert not result.is_usable


def test_corrupted_pdf_is_handled():
    result = extract_text_from_pdf_bytes(b"this is not a pdf", "broken.pdf")
    assert result.status == "unreadable"
    assert result.original_filename == "broken.pdf"
    assert not result.is_usable


def test_filename_is_preserved_as_metadata_only():
    pdf_bytes = make_simple_pdf_bytes("Enough selectable text for screening a fictional resume sample.")
    result = extract_text_from_pdf_bytes(pdf_bytes, r"..\unsafe\My Resume (1).pdf")
    assert result.original_filename.endswith("My Resume (1).pdf")
    assert ".." not in result.original_filename
