"""
Transparent job matching and ranking.

Algorithm (explain this in interviews):
1. Extract required skills, preferred skills, qualifications, and experience
   themes from the job description (OpenAI JSON, with a local keyword fallback).
2. Compare those requirements with evidence in the parsed resume.
3. Compute component scores between 0 and 1.
4. Combine them with configurable weights that sum to 1.0:
      final_score = 100 * sum(weight_i * component_i)
5. Rank by final_score only. Name, contact data, and protected attributes
   are never inputs to the score.

This is an evidence-overlap helper for human reviewers. It is not a hiring
decision and it does not predict job performance.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.resume_parser import ParsedResume
from src.scoring_config import load_scoring_config
from src.utils import (
    as_string_list,
    first_non_empty,
    normalize_skill,
    normalize_text,
    percent,
    safe_json_loads,
    unique_normalized_list,
)

load_dotenv()

# Small built-in vocabulary so the local JD fallback can still find common skills
# if the API is unavailable. This does not invent resume content.
COMMON_SKILLS = [
    "python", "java", "javascript", "typescript", "sql", "html", "css",
    "react", "node.js", "django", "flask", "fastapi", "pandas", "numpy",
    "scikit-learn", "tensorflow", "pytorch", "aws", "azure", "google cloud",
    "docker", "kubernetes", "git", "linux", "postgresql", "mysql", "mongodb",
    "excel", "tableau", "powerbi", "rest", "api", "ci cd", "pytest",
]


@dataclass
class JobRequirements:
    job_title: str | None
    required_skills: list[str]
    preferred_skills: list[str]
    required_qualifications: list[str]
    experience_themes: list[str]
    source: str
    error_message: str | None = None


@dataclass
class MatchResult:
    original_filename: str
    display_name: str
    overall_score: float
    rank: int | None
    component_scores: dict[str, float]
    weights: dict[str, float]
    matched_skills: list[str]
    missing_required_skills: list[str]
    unverified_preferred_skills: list[str]
    relevant_experience_summary: str
    evidence_quotes: list[str]
    score_explanation: list[str]
    warnings: list[str] = field(default_factory=list)
    parsed_resume: ParsedResume | None = None
    screening_status: str = "reviewed_for_humans"

    def to_table_row(self) -> dict[str, Any]:
        return {
            "Rank": self.rank,
            "Resume file": self.original_filename,
            "Candidate name": self.display_name,
            "Job-match score": self.overall_score,
            "Required-skill coverage": self.component_scores.get("required_skills", 0),
            "Preferred-skill coverage": self.component_scores.get("preferred_skills", 0),
            "Experience overlap": self.component_scores.get("relevant_experience", 0),
            "Education overlap": self.component_scores.get("education", 0),
            "Matched skills": ", ".join(self.matched_skills) if self.matched_skills else "None evidenced",
            "Missing/unverified required skills": ", ".join(self.missing_required_skills)
            if self.missing_required_skills
            else "None identified",
            "Relevant experience": self.relevant_experience_summary,
            "Status": self.screening_status,
        }


def extract_job_requirements(
    job_description: str,
    client: OpenAI | None = None,
    model: str | None = None,
) -> JobRequirements:
    """Extract structured requirements from the job description."""
    if not job_description.strip():
        return JobRequirements(
            job_title=None,
            required_skills=[],
            preferred_skills=[],
            required_qualifications=[],
            experience_themes=[],
            source="empty",
            error_message="The job description is empty.",
        )

    api_key = os.getenv("OPENAI_API_KEY")
    model_name = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if api_key:
        try:
            openai_client = client or OpenAI(api_key=api_key)
            response = openai_client.chat.completions.create(
                model=model_name,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract only job-related requirements. Do not infer protected "
                            "characteristics or personality. If a list is not stated, return []."
                        ),
                    },
                    {"role": "user", "content": _job_prompt(job_description)},
                ],
            )
            parsed = safe_json_loads(response.choices[0].message.content or "")
            if parsed:
                return JobRequirements(
                    job_title=first_non_empty(parsed.get("job_title")),
                    required_skills=unique_normalized_list(as_string_list(parsed.get("required_skills"))),
                    preferred_skills=unique_normalized_list(as_string_list(parsed.get("preferred_skills"))),
                    required_qualifications=as_string_list(parsed.get("required_qualifications")),
                    experience_themes=as_string_list(parsed.get("experience_themes")),
                    source="openai",
                )
        except Exception as error:  # noqa: BLE001
            fallback = extract_job_requirements_locally(job_description)
            fallback.error_message = (
                f"OpenAI job parsing failed ({error}). Used the local keyword fallback instead."
            )
            return fallback

    fallback = extract_job_requirements_locally(job_description)
    if not api_key:
        fallback.error_message = (
            "OPENAI_API_KEY is missing, so job requirements were extracted with the local keyword fallback."
        )
    return fallback


def extract_job_requirements_locally(job_description: str) -> JobRequirements:
    """
    Lightweight fallback: find known skill words and split required vs preferred
    using phrases such as 'required', 'must have', 'preferred', and 'nice to have'.
    """
    text = normalize_text(job_description)
    found = [skill for skill in COMMON_SKILLS if skill in text]

    required: list[str] = []
    preferred: list[str] = []
    for skill in found:
        required_hit = _skill_near_keywords(job_description, skill, ["required", "must have", "must-have"])
        preferred_hit = _skill_near_keywords(
            job_description,
            skill,
            ["preferred", "nice to have", "nice-to-have", "bonus"],
        )
        if required_hit and not preferred_hit:
            required.append(skill)
        elif preferred_hit and not required_hit:
            preferred.append(skill)
        else:
            required.append(skill)

    if not required and found:
        required = found[:]

    themes = []
    for theme in ["backend", "frontend", "data analysis", "machine learning", "cloud", "testing", "api"]:
        if theme in text:
            themes.append(theme)

    return JobRequirements(
        job_title=None,
        required_skills=unique_normalized_list(required),
        preferred_skills=unique_normalized_list(preferred),
        required_qualifications=[],
        experience_themes=themes,
        source="local_keywords",
    )


def match_resume_to_job(
    parsed_resume: ParsedResume,
    job_requirements: JobRequirements,
    resume_text: str,
    weights: dict[str, float] | None = None,
) -> MatchResult:
    """Compute an explainable job-match score from evidenced overlap."""
    config = load_scoring_config()
    used_weights = weights or config["weights"]

    resume_skills = parsed_resume.skill_labels
    extra_from_text = [skill for skill in job_requirements.required_skills + job_requirements.preferred_skills
                       if _skill_in_text(skill, resume_text)]
    evidenced_skills = unique_normalized_list(resume_skills + extra_from_text)

    matched_required, missing_required = _partition_skills(
        job_requirements.required_skills,
        evidenced_skills,
    )
    matched_preferred, missing_preferred = _partition_skills(
        job_requirements.preferred_skills,
        evidenced_skills,
    )

    required_score = _coverage(matched_required, job_requirements.required_skills)
    preferred_score = _coverage(matched_preferred, job_requirements.preferred_skills)
    experience_score, experience_summary, quotes = _experience_overlap(
        parsed_resume,
        job_requirements,
        resume_text,
    )
    education_score = _education_overlap(parsed_resume, job_requirements)
    evidence_score = _supporting_evidence_score(parsed_resume, matched_required + matched_preferred)

    component_scores = {
        "required_skills": percent(required_score),
        "preferred_skills": percent(preferred_score),
        "relevant_experience": percent(experience_score),
        "education": percent(education_score),
        "supporting_evidence": percent(evidence_score),
    }

    weighted_total = (
        used_weights["required_skills"] * required_score
        + used_weights["preferred_skills"] * preferred_score
        + used_weights["relevant_experience"] * experience_score
        + used_weights["education"] * education_score
        + used_weights["supporting_evidence"] * evidence_score
    )
    overall = round(weighted_total * 100, 1)

    explanation = [
        "This score measures overlap between the job description and evidenced resume content.",
        "It is not a hiring decision and it does not predict job performance.",
        f"Required-skill coverage: {percent(required_score)}% "
        f"(weight {used_weights['required_skills']:.0%}). Matched: {matched_required or ['none']}.",
        f"Preferred-skill coverage: {percent(preferred_score)}% "
        f"(weight {used_weights['preferred_skills']:.0%}).",
        f"Relevant-experience overlap: {percent(experience_score)}% "
        f"(weight {used_weights['relevant_experience']:.0%}).",
        f"Education/qualification overlap: {percent(education_score)}% "
        f"(weight {used_weights['education']:.0%}).",
        f"Supporting evidence for matched skills: {percent(evidence_score)}% "
        f"(weight {used_weights['supporting_evidence']:.0%}).",
        f"Overall = 100 × ("
        f"{used_weights['required_skills']:.2f}×{required_score:.2f} + "
        f"{used_weights['preferred_skills']:.2f}×{preferred_score:.2f} + "
        f"{used_weights['relevant_experience']:.2f}×{experience_score:.2f} + "
        f"{used_weights['education']:.2f}×{education_score:.2f} + "
        f"{used_weights['supporting_evidence']:.2f}×{evidence_score:.2f}).",
        "Ranking uses only these job-related components. Name and contact details are identifiers, not score inputs.",
    ]

    warnings = []
    if parsed_resume.error_message:
        warnings.append(parsed_resume.error_message)
    if job_requirements.error_message:
        warnings.append(job_requirements.error_message)
    if not job_requirements.required_skills:
        warnings.append("No required skills were identified, so skill coverage is conservative.")

    display_name = parsed_resume.candidate_name or "(Name not found in resume)"
    return MatchResult(
        original_filename=parsed_resume.original_filename,
        display_name=display_name,
        overall_score=overall,
        rank=None,
        component_scores=component_scores,
        weights=used_weights,
        matched_skills=unique_normalized_list(matched_required + matched_preferred),
        missing_required_skills=missing_required,
        unverified_preferred_skills=missing_preferred,
        relevant_experience_summary=experience_summary,
        evidence_quotes=quotes[:8],
        score_explanation=explanation,
        warnings=warnings,
        parsed_resume=parsed_resume,
        screening_status="ready_for_human_review",
    )


def rank_matches(matches: list[MatchResult]) -> list[MatchResult]:
    """Sort by job-match score. Ties keep original upload order."""
    ordered = sorted(matches, key=lambda item: item.overall_score, reverse=True)
    for index, item in enumerate(ordered, start=1):
        item.rank = index
    return ordered


def _job_prompt(job_description: str) -> str:
    return (
        "Extract job requirements as JSON with keys: "
        "job_title, required_skills, preferred_skills, required_qualifications, experience_themes.\n"
        "Use only the job description. Do not add skills that are not mentioned.\n\n"
        f"JOB DESCRIPTION:\n{job_description[:15000]}"
    )


def _partition_skills(needed: list[str], evidenced: list[str]) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    for skill in needed:
        if any(_skills_match(skill, other) for other in evidenced):
            matched.append(skill)
        else:
            missing.append(skill)
    return matched, missing


def _skills_match(left: str, right: str) -> bool:
    a = normalize_skill(left)
    b = normalize_skill(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and (a in b or b in a):
        return True
    return False


def _skill_in_text(skill: str, resume_text: str) -> bool:
    text = normalize_text(resume_text)
    token = re.escape(normalize_skill(skill))
    if not token:
        return False
    return re.search(rf"(?<![a-z0-9]){token}(?![a-z0-9])", text) is not None


def _coverage(matched: list[str], universe: list[str]) -> float:
    if not universe:
        return 0.0
    return len(matched) / len(universe)


def _experience_overlap(
    parsed_resume: ParsedResume,
    job_requirements: JobRequirements,
    resume_text: str,
) -> tuple[float, str, list[str]]:
    themes = [normalize_text(theme) for theme in job_requirements.experience_themes if theme]
    blobs: list[str] = []
    quotes: list[str] = []

    for row in parsed_resume.experience + parsed_resume.projects:
        parts = [
            row.get("title"),
            row.get("organization"),
            row.get("name"),
            row.get("description"),
            " ".join(row.get("highlights") or []),
        ]
        blob = " ".join(part for part in parts if isinstance(part, str))
        if blob.strip():
            blobs.append(blob)
        for quote in row.get("evidence_quotes") or []:
            if quote:
                quotes.append(quote)

    haystack = normalize_text(" ".join(blobs) + " " + resume_text)
    if not themes:
        summary = _fallback_experience_summary(parsed_resume)
        score = 0.4 if blobs else 0.0
        return score, summary, quotes

    hits = [theme for theme in themes if theme in haystack]
    score = len(hits) / len(themes)
    if hits:
        summary = "Experience themes evidenced: " + ", ".join(hits)
    else:
        summary = "No job experience themes were clearly evidenced in the resume."
    extra = _fallback_experience_summary(parsed_resume)
    if extra:
        summary = f"{summary} {extra}"
    return score, summary.strip(), quotes


def _fallback_experience_summary(parsed_resume: ParsedResume) -> str:
    titles = []
    for row in parsed_resume.experience:
        title = row.get("title")
        organization = row.get("organization")
        if title and organization:
            titles.append(f"{title} at {organization}")
        elif title:
            titles.append(str(title))
    if not titles:
        return "No work-history titles were extracted."
    return "Extracted roles: " + "; ".join(titles[:4]) + "."


def _education_overlap(parsed_resume: ParsedResume, job_requirements: JobRequirements) -> float:
    qualifications = [normalize_text(item) for item in job_requirements.required_qualifications if item]
    education_blob = normalize_text(
        " ".join(
            " ".join(str(value) for value in row.values() if value)
            for row in parsed_resume.education
        )
        + " "
        + " ".join(parsed_resume.certifications)
    )
    if not qualifications:
        return 0.5 if parsed_resume.education or parsed_resume.certifications else 0.0
    hits = sum(1 for item in qualifications if item and item in education_blob)
    return hits / len(qualifications)


def _supporting_evidence_score(parsed_resume: ParsedResume, matched_skills: list[str]) -> float:
    if not matched_skills:
        return 0.0
    evidence_blobs = []
    for row in parsed_resume.experience + parsed_resume.projects:
        evidence_blobs.extend(row.get("evidence_quotes") or [])
        evidence_blobs.extend(row.get("highlights") or [])
        evidence_blobs.extend(row.get("skills_used") or [])
    blob = normalize_text(" ".join(evidence_blobs))
    if not blob:
        return 0.2 if parsed_resume.experience or parsed_resume.projects else 0.0
    supported = sum(1 for skill in matched_skills if normalize_skill(skill) in blob)
    return supported / len(matched_skills)


def _skill_near_keywords(job_description: str, skill: str, keywords: list[str]) -> bool:
    lowered = job_description.lower()
    skill_pos = lowered.find(skill.lower())
    if skill_pos < 0:
        return False
    window = lowered[max(0, skill_pos - 80): skill_pos + 80]
    return any(keyword in window for keyword in keywords)
