"""
Load scoring weights from config/scoring.json and keep them easy to explain.

The weights must add up to 1.0. Users can change them in the Streamlit sidebar.
The score is a job-requirement overlap measure, not a hiring decision.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from src.utils import load_json_file


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "scoring.json"

DEFAULT_WEIGHTS = {
    "required_skills": 0.45,
    "preferred_skills": 0.15,
    "relevant_experience": 0.25,
    "education": 0.10,
    "supporting_evidence": 0.05,
}


def load_scoring_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        return {
            "weights": deepcopy(DEFAULT_WEIGHTS),
            "notes": {},
        }
    data = load_json_file(path)
    weights = data.get("weights") or deepcopy(DEFAULT_WEIGHTS)
    return {
        "weights": _normalize_weights(weights),
        "notes": data.get("notes") or {},
        "thresholds": data.get("thresholds") or {},
    }


def _normalize_weights(weights: dict[str, Any]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for key, default_value in DEFAULT_WEIGHTS.items():
        try:
            cleaned[key] = float(weights.get(key, default_value))
        except (TypeError, ValueError):
            cleaned[key] = default_value

    total = sum(cleaned.values())
    if total <= 0:
        return deepcopy(DEFAULT_WEIGHTS)
    return {key: value / total for key, value in cleaned.items()}
