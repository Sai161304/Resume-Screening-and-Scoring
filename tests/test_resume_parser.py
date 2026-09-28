"""Structured JSON validation tests. These do not call OpenAI."""

from src.resume_parser import empty_parsed_resume, parsed_resume_from_dict
from src.utils import safe_json_loads


def test_invalid_json_returns_none():
    assert safe_json_loads("not json") is None
    assert safe_json_loads("") is None
    assert safe_json_loads("[1, 2, 3]") is None


def test_valid_json_object_parses():
    data = safe_json_loads('{"candidate_name": "Alex Rivera", "technical_skills": ["Python"]}')
    assert data["candidate_name"] == "Alex Rivera"


def test_parser_fills_missing_fields_without_guessing():
    parsed = parsed_resume_from_dict({"candidate_name": None}, "file.pdf")
    assert parsed.candidate_name is None
    assert parsed.technical_skills == []
    assert parsed.experience == []
    assert parsed.original_filename == "file.pdf"


def test_empty_resume_records_error():
    parsed = empty_parsed_resume("blank.pdf", error_message="No resume text was available to parse.")
    assert parsed.error_message
    assert parsed.skill_labels == []
