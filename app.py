"""
Streamlit front-end for the Resume Screening and Ranking System.

The UI collects a job description and PDF resumes, runs extraction + matching,
and shows evidence so a human can review every result.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.job_matcher import (
    extract_job_requirements,
    match_resume_to_job,
    rank_matches,
)
from src.pdf_extractor import extract_text_from_pdf_bytes
from src.report_generator import generate_excel_bytes
from src.resume_parser import empty_parsed_resume, parse_resume_text
from src.scoring_config import load_scoring_config

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
SAMPLE_JD_DIR = APP_DIR / "sample_data" / "job_descriptions"

DISCLAIMER = (
    "This tool ranks resumes by **job-related evidence overlap** with the job "
    "description. The score is **not a hiring decision** and **not a prediction "
    "of job performance**. Candidates are never auto-rejected. A person should "
    "review the evidence before any outcome."
)


def main() -> None:
    st.set_page_config(
        page_title="Resume Screening and Ranking",
        page_icon="📄",
        layout="wide",
    )
    _inject_styles()
    config = load_scoring_config()

    st.title("Resume Screening and Ranking System")
    st.caption("Transparent, evidence-based screening for human reviewers.")
    st.info(DISCLAIMER)

    with st.sidebar:
        st.header("Setup")
        api_key_present = bool(os.getenv("OPENAI_API_KEY"))
        if api_key_present:
            st.success("OpenAI API key loaded from environment.")
        else:
            st.error("OPENAI_API_KEY is not set. Copy `.env.example` to `.env`.")

        model_name = st.text_input(
            "OpenAI model",
            value=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            help="Used only for structured JSON extraction.",
        )

        st.header("Scoring weights")
        st.caption("These must stay job-related. They are re-normalized to 100%.")
        weights = {
            "required_skills": st.slider("Required skills", 0.0, 1.0, float(config["weights"]["required_skills"]), 0.05),
            "preferred_skills": st.slider("Preferred skills", 0.0, 1.0, float(config["weights"]["preferred_skills"]), 0.05),
            "relevant_experience": st.slider("Relevant experience", 0.0, 1.0, float(config["weights"]["relevant_experience"]), 0.05),
            "education": st.slider("Education / qualifications", 0.0, 1.0, float(config["weights"]["education"]), 0.05),
            "supporting_evidence": st.slider("Supporting evidence", 0.0, 1.0, float(config["weights"]["supporting_evidence"]), 0.05),
        }
        total = sum(weights.values()) or 1.0
        weights = {key: value / total for key, value in weights.items()}
        st.write(
            {
                key.replace("_", " ").title(): f"{value:.0%}"
                for key, value in weights.items()
            }
        )
        st.caption("Name, photos, and protected characteristics are never scoring inputs.")

    job_description = _job_description_section()
    uploaded_files = st.file_uploader(
        "Upload one or more PDF resumes",
        type=["pdf"],
        accept_multiple_files=True,
        help="Original files are read in memory and are never overwritten.",
    )

    start = st.button("Start resume screening", type="primary", use_container_width=True)

    if start:
        _run_screening(job_description, uploaded_files, weights, model_name)

    if "match_results" in st.session_state:
        _render_results()


def _job_description_section() -> str:
    st.subheader("Job description")
    sample_text = ""
    sample_files = sorted(SAMPLE_JD_DIR.glob("*.txt")) if SAMPLE_JD_DIR.exists() else []
    if sample_files:
        choices = ["(Paste your own)"] + [path.name for path in sample_files]
        selected = st.selectbox("Optional sample job description (fictional)", choices)
        if selected != "(Paste your own)":
            sample_text = (SAMPLE_JD_DIR / selected).read_text(encoding="utf-8")

    return st.text_area(
        "Paste or type the job description",
        value=sample_text,
        height=220,
        placeholder="Required skills, preferred skills, qualifications, and responsibilities...",
    )


def _run_screening(job_description, uploaded_files, weights, model_name) -> None:
    if not job_description.strip():
        st.error("Please enter a job description before screening.")
        return
    if not uploaded_files:
        st.error("Please upload at least one PDF resume.")
        return

    with st.status("Screening resumes...", expanded=True) as status:
        st.write("Extracting job requirements...")
        job_requirements = extract_job_requirements(job_description, model=model_name)
        if job_requirements.error_message:
            st.warning(job_requirements.error_message)

        matches = []
        extraction_rows = []
        for uploaded in uploaded_files:
            filename = uploaded.name
            st.write(f"Reading `{filename}`...")
            pdf_result = extract_text_from_pdf_bytes(uploaded.getvalue(), filename)
            extraction_rows.append(pdf_result)

            if not pdf_result.is_usable:
                parsed = empty_parsed_resume(filename, error_message=pdf_result.error_message)
                match = match_resume_to_job(parsed, job_requirements, pdf_result.text, weights)
                match.warnings.extend(pdf_result.warnings)
                match.screening_status = pdf_result.status
                match.overall_score = 0.0
                match.score_explanation.insert(
                    0,
                    "This resume could not be scored from evidenced text. A human should review the file directly.",
                )
                matches.append(match)
                continue

            st.write(f"Extracting structured fields from `{filename}`...")
            parsed = parse_resume_text(pdf_result.text, filename, model=model_name)
            match = match_resume_to_job(parsed, job_requirements, pdf_result.text, weights)
            match.warnings.extend(pdf_result.warnings)
            matches.append(match)

        ranked = rank_matches(matches)
        st.session_state["match_results"] = ranked
        st.session_state["job_requirements"] = job_requirements
        st.session_state["extraction_rows"] = extraction_rows
        status.update(label="Screening complete. Review the evidence below.", state="complete")


def _render_results() -> None:
    matches = st.session_state["match_results"]
    job_requirements = st.session_state["job_requirements"]

    st.subheader("Results dashboard")
    st.caption(
        "Required skills identified: "
        + (", ".join(job_requirements.required_skills) or "none extracted")
    )

    usable = [item for item in matches if item.screening_status == "ready_for_human_review"]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Resumes processed", len(matches))
    col2.metric("Ready for human review", len(usable))
    col3.metric("Highest job-match score", f"{max((m.overall_score for m in matches), default=0):.1f}")
    col4.metric("Required skills in JD", len(job_requirements.required_skills))

    for match in matches:
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.markdown(f"**#{match.rank} · {match.display_name}**")
            left.caption(f"Resume file: `{match.original_filename}` · Status: {match.screening_status}")
            right.metric("Job-match score", f"{match.overall_score:.1f}")
            st.write("**Matched skills:**", ", ".join(match.matched_skills) or "None evidenced")
            st.write(
                "**Missing or unverified required skills:**",
                ", ".join(match.missing_required_skills) or "None identified",
            )
            st.write("**Relevant experience:**", match.relevant_experience_summary)

    st.subheader("Candidate comparison table")
    table = pd.DataFrame([match.to_table_row() for match in matches])
    min_score = st.slider("Show scores at or above", 0.0, 100.0, 0.0, 1.0)
    skill_filter = st.text_input("Filter by matched skill (optional)").strip().lower()
    filtered = table[table["Job-match score"] >= min_score]
    if skill_filter:
        filtered = filtered[filtered["Matched skills"].str.lower().str.contains(skill_filter, na=False)]
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    st.subheader("Detailed evidence")
    for match in matches:
        title = f"{match.display_name} — {match.original_filename} (score {match.overall_score:.1f})"
        with st.expander(title):
            st.markdown("**How this score was calculated**")
            for line in match.score_explanation:
                st.write("- " + line)
            if match.warnings:
                st.warning("\n".join(match.warnings))
            parsed = match.parsed_resume
            if parsed:
                st.markdown("**Education**")
                st.json(parsed.education or [])
                st.markdown("**Experience**")
                st.json(parsed.experience or [])
                st.markdown("**Projects**")
                st.json(parsed.projects or [])
                st.markdown("**Certifications**")
                st.write(parsed.certifications or "None extracted")
            st.markdown("**Evidence quotes**")
            if match.evidence_quotes:
                for quote in match.evidence_quotes:
                    st.write(f"> {quote}")
            else:
                st.write("No verbatim evidence quotes were extracted.")

    excel_bytes = generate_excel_bytes(matches)
    st.download_button(
        "Download Excel screening report",
        data=excel_bytes,
        file_name="resume_screening_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
            .stApp { background: linear-gradient(180deg, #f4f7fb 0%, #ffffff 280px); color: #000000; }
            h1, h2, h3 { letter-spacing: -0.03em; color: #000000 !important; }
            div[data-testid="stMetric"] {
                background: #ffffff;
                border: 1px solid #d9e2ec;
                border-radius: 12px;
                padding: 8px 12px;
            }
            /* Job description section styling */
            div[data-testid="stTextArea"] textarea {
                color: #000000 !important;
                -webkit-text-fill-color: #000000 !important;
                background-color: #ffffff !important;
                border: 1px solid #d9e2ec !important;
            }
            div[data-testid="stTextArea"] textarea::placeholder {
                color: #6b7280 !important;
                -webkit-text-fill-color: #6b7280 !important;
            }
            div[data-testid="stTextArea"] label,
            div[data-testid="stTextArea"] label p {
                color: #000000 !important;
            }
            div[data-testid="stSelectbox"] label,
            div[data-testid="stSelectbox"] label p {
                color: #000000 !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
