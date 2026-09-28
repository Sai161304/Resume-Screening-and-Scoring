"""
Turn resume text into structured JSON using the OpenAI API.

Rules:
- Ask the model not to guess missing facts.
- Validate JSON before it is used by the matcher.
- Contact details are optional and are not ranking features.
- Protected characteristics and personality traits are never requested.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.utils import as_string_list, first_non_empty, safe_json_loads, unique_normalized_list

load_dotenv()

RESUME_SCHEMA_HINT = """
Return a JSON object with exactly these keys:
{
  "candidate_name": string or null,
  "email": string or null,
  "phone": string or null,
  "education": [
    {"degree": string or null, "field": string or null, "institution": string or null, "year": string or null}
  ],
  "technical_skills": [string],
  "tools": [string],
  "experience": [
    {
      "title": string or null,
      "organization": string or null,
      "duration": string or null,
      "highlights": [string],
      "evidence_quotes": [string]
    }
  ],
  "projects": [
    {
      "name": string or null,
      "description": string or null,
      "skills_used": [string],
      "evidence_quotes": [string]
    }
  ],
  "certifications": [string],
  "extraction_notes": string,
  "unverified_fields": [string]
}
"""


@dataclass
class ParsedResume:
    original_filename: str
    candidate_name: str | None
    email: str | None
    phone: str | None
    education: list[dict[str, Any]]
    technical_skills: list[str]
    tools: list[str]
    experience: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    certifications: list[str]
    extraction_notes: str
    unverified_fields: list[str]
    raw_json: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    @property
    def skill_labels(self) -> list[str]:
        return unique_normalized_list(self.technical_skills + self.tools)


def parse_resume_text(
    resume_text: str,
    original_filename: str,
    client: OpenAI | None = None,
    model: str | None = None,
) -> ParsedResume:
    """Call OpenAI and validate the structured resume JSON."""
    if not resume_text.strip():
        return empty_parsed_resume(
            original_filename,
            error_message="No resume text was available to parse.",
        )

    api_key = os.getenv("OPENAI_API_KEY")
    model_name = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        return empty_parsed_resume(
            original_filename,
            error_message="OPENAI_API_KEY is missing. Copy .env.example to .env and add your key.",
        )

    openai_client = client or OpenAI(api_key=api_key)
    prompt = _build_resume_prompt(resume_text)

    try:
        response = openai_client.chat.completions.create(
            model=model_name,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract job-related facts from resumes for human review. "
                        "Use only information present in the text. If a field is missing, use null or []. "
                        "Never invent employers, dates, skills, grades, or contact details. "
                        "Never infer age, gender, religion, caste, race, disability, marital status, "
                        "national origin, or personality traits. Do not use a name to infer anything."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw_content = response.choices[0].message.content or ""
    except Exception as error:  # noqa: BLE001
        return empty_parsed_resume(
            original_filename,
            error_message=f"OpenAI extraction failed: {error}",
        )

    parsed = safe_json_loads(raw_content)
    if parsed is None:
        return empty_parsed_resume(
            original_filename,
            error_message="The model did not return valid JSON. No fields were invented.",
        )

    return parsed_resume_from_dict(parsed, original_filename)


def parsed_resume_from_dict(data: dict[str, Any], original_filename: str) -> ParsedResume:
    """Validate and normalize model JSON. Unknown extra keys are ignored."""
    education = _as_object_list(
        data.get("education"),
        allowed_keys=("degree", "field", "institution", "year"),
    )
    experience = _as_object_list(
        data.get("experience"),
        allowed_keys=("title", "organization", "duration", "highlights", "evidence_quotes"),
        list_keys=("highlights", "evidence_quotes"),
    )
    projects = _as_object_list(
        data.get("projects"),
        allowed_keys=("name", "description", "skills_used", "evidence_quotes"),
        list_keys=("skills_used", "evidence_quotes"),
    )

    return ParsedResume(
        original_filename=original_filename,
        candidate_name=first_non_empty(data.get("candidate_name")),
        email=first_non_empty(data.get("email")),
        phone=first_non_empty(data.get("phone")),
        education=education,
        technical_skills=as_string_list(data.get("technical_skills")),
        tools=as_string_list(data.get("tools")),
        experience=experience,
        projects=projects,
        certifications=as_string_list(data.get("certifications")),
        extraction_notes=first_non_empty(data.get("extraction_notes")) or "",
        unverified_fields=as_string_list(data.get("unverified_fields")),
        raw_json=data,
    )


def empty_parsed_resume(original_filename: str, error_message: str | None = None) -> ParsedResume:
    return ParsedResume(
        original_filename=original_filename,
        candidate_name=None,
        email=None,
        phone=None,
        education=[],
        technical_skills=[],
        tools=[],
        experience=[],
        projects=[],
        certifications=[],
        extraction_notes="",
        unverified_fields=["all_fields"],
        raw_json={},
        error_message=error_message,
    )


def _build_resume_prompt(resume_text: str) -> str:
    clipped = resume_text[:20000]
    return (
        "Extract structured job-related information from this resume text.\n"
        f"{RESUME_SCHEMA_HINT}\n"
        "evidence_quotes must be short verbatim snippets from the resume.\n"
        "If contact details are not clearly present, set them to null.\n\n"
        f"RESUME TEXT:\n{clipped}"
    )


def _as_object_list(
    value: Any,
    allowed_keys: tuple[str, ...],
    list_keys: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for key in allowed_keys:
            raw = item.get(key)
            if key in list_keys:
                row[key] = as_string_list(raw)
            else:
                row[key] = first_non_empty(raw)
        rows.append(row)
    return rows
