"""
Shared helpers used across PDF extraction, parsing, matching, and reports.

Interview note: keeping string cleanup, JSON checks, and file-name safety in one
place avoids duplicated logic and makes validation consistent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SKILL_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "nodejs": "node.js",
    "node": "node.js",
    "postgres": "postgresql",
    "tf": "tensorflow",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "ci/cd": "ci cd",
    "rest api": "rest",
    "apis": "api",
    "ms excel": "excel",
    "power bi": "powerbi",
    "gcp": "google cloud",
    "amazon web services": "aws",
}


def load_json_file(file_path: str | Path) -> dict[str, Any]:
    """Load a JSON file and return a dictionary."""
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def safe_json_loads(raw_text: str) -> dict[str, Any] | None:
    """
    Parse JSON text. Return None if the model (or file) did not return valid JSON.

    We do not guess missing fields here — callers decide how to fill defaults.
    """
    if not raw_text or not str(raw_text).strip():
        return None
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def normalize_text(value: str | None) -> str:
    """Lowercase text and collapse extra spaces for fair comparisons."""
    if not value:
        return ""
    cleaned = value.replace("\x00", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def normalize_skill(skill: str | None) -> str:
    """Normalize one skill label and apply a small alias map."""
    text = normalize_text(skill)
    text = text.replace("#", "sharp")
    text = re.sub(r"[^a-z0-9.+]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return SKILL_ALIASES.get(text, text)


def unique_normalized_list(values: list[str] | None) -> list[str]:
    """Keep original order while dropping empty and duplicate skills."""
    seen: set[str] = set()
    result: list[str] = []
    for item in values or []:
        if not isinstance(item, str):
            continue
        normalized = normalize_skill(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def as_string_list(value: Any) -> list[str]:
    """Turn messy model output into a list of short strings."""
    if value is None:
        return []
    if isinstance(value, str):
        pieces = re.split(r"[,;/]| and ", value)
        return [piece.strip() for piece in pieces if piece.strip()]
    if isinstance(value, list):
        cleaned: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                cleaned.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("skill") or item.get("title")
                if isinstance(name, str) and name.strip():
                    cleaned.append(name.strip())
        return cleaned
    return []


def first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def safe_filename(name: str | None, fallback: str = "resume.pdf") -> str:
    """
    Keep a readable filename for display and Excel export.

    This does not write files. It only sanitizes a label so reports stay safe.
    """
    if not name:
        return fallback
    cleaned = Path(name).name
    cleaned = re.sub(r"[^\w.\- ()]+", "_", cleaned)
    return cleaned[:180] or fallback


def percent(value: float) -> float:
    """Clamp a 0-1 ratio and convert it to 0-100."""
    if value < 0:
        value = 0.0
    if value > 1:
        value = 1.0
    return round(value * 100, 1)
