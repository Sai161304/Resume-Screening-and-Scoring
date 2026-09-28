"""Scoring tests with synthetic, fictional candidate data. No API calls."""

from pathlib import Path

from src.job_matcher import (
    JobRequirements,
    extract_job_requirements_locally,
    match_resume_to_job,
    rank_matches,
)
from src.resume_parser import empty_parsed_resume, parsed_resume_from_dict


def _job():
    return JobRequirements(
        job_title="Junior Backend Engineer",
        required_skills=["python", "sql", "git", "docker"],
        preferred_skills=["fastapi", "aws"],
        required_qualifications=["computer science"],
        experience_themes=["backend", "api"],
        source="test",
    )


def test_strong_skill_overlap_scores_higher_than_unrelated_resume():
    strong = parsed_resume_from_dict(
        {
            "candidate_name": "Alex Rivera",
            "technical_skills": ["Python", "SQL", "Git", "Docker", "FastAPI"],
            "tools": ["pytest"],
            "education": [{"degree": "B.S.", "field": "Computer Science", "institution": "Northlake", "year": "2023"}],
            "experience": [
                {
                    "title": "Intern",
                    "organization": "Harbor Apps",
                    "highlights": ["Built backend REST APIs"],
                    "evidence_quotes": ["Built REST APIs in Python"],
                }
            ],
            "projects": [],
            "certifications": [],
        },
        "alex.pdf",
    )
    weak = parsed_resume_from_dict(
        {
            "candidate_name": "Sam Patel",
            "technical_skills": ["Figma", "Photoshop"],
            "tools": [],
            "education": [{"degree": "Diploma", "field": "Graphic Design", "institution": "Riverside", "year": "2021"}],
            "experience": [{"title": "Design intern", "highlights": ["Created posters"]}],
            "projects": [],
            "certifications": [],
        },
        "sam.pdf",
    )
    resume_text_strong = "Python SQL Git Docker FastAPI backend API intern"
    resume_text_weak = "Figma posters graphic design"
    strong_match = match_resume_to_job(strong, _job(), resume_text_strong)
    weak_match = match_resume_to_job(weak, _job(), resume_text_weak)
    assert strong_match.overall_score > weak_match.overall_score
    assert "python" in strong_match.matched_skills
    assert "python" in weak_match.missing_required_skills


def test_missing_resume_data_does_not_crash_and_does_not_invent_skills():
    empty = empty_parsed_resume("blank.pdf", error_message="No text")
    match = match_resume_to_job(empty, _job(), "")
    assert match.overall_score >= 0
    assert match.matched_skills == []
    assert "python" in match.missing_required_skills
    assert match.display_name == "(Name not found in resume)"


def test_ranking_uses_score_not_name():
    low = match_resume_to_job(
        parsed_resume_from_dict({"technical_skills": ["figma"]}, "a.pdf"),
        _job(),
        "figma",
    )
    high = match_resume_to_job(
        parsed_resume_from_dict({"technical_skills": ["python", "sql", "git", "docker"]}, "z.pdf"),
        _job(),
        "python sql git docker backend api",
    )
    ranked = rank_matches([low, high])
    assert ranked[0].original_filename == "z.pdf"
    assert ranked[0].rank == 1


def test_local_job_parser_finds_required_python():
    sample = Path(__file__).resolve().parents[1] / "sample_data" / "job_descriptions" / "backend_python.txt"
    text = sample.read_text(encoding="utf-8")
    requirements = extract_job_requirements_locally(text)
    assert "python" in requirements.required_skills
