# Resume Screening and Ranking System

Beginner-friendly Streamlit app that reads PDF resumes, extracts job-related facts with the OpenAI API, scores evidenced overlap with a job description, and exports an Excel report for **human review**.

The score is **not a hiring decision** and **not a prediction of job performance**. Candidates are never auto-rejected.

## Folder structure

```
Resume_Screening_System/
  app.py                      Streamlit user interface
  requirements.txt            Python packages
  .env.example                API key template (no real secret)
  config/scoring.json         Default scoring weights
  src/pdf_extractor.py        PyMuPDF text extraction
  src/resume_parser.py        OpenAI structured JSON extraction
  src/job_matcher.py          Transparent matching and ranking
  src/report_generator.py     Excel export with Pandas + OpenPyXL
  src/utils.py                Shared helpers
  src/scoring_config.py       Weight loading and normalization
  tests/                      Automated tests (no paid API calls)
  sample_data/                Fictional job descriptions and resumes
  scripts/create_sample_pdfs.py
```

## What you need before running

1. **Python 3.10+**
2. An **OpenAI API key** stored in a local `.env` file (never in source code)
3. Text-based PDF resumes (not image-only scans, unless you OCR them yourself first)

This project does not use any paid API except the OpenAI API you configure.

## Install (run these yourself)

I have not installed packages into your environment. From the project folder:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure the API key securely

1. Copy `.env.example` to `.env`
2. Replace `your_openai_api_key_here` with your real key
3. Keep `.env` private. It is already listed in `.gitignore`

Optional:

```
OPENAI_MODEL=gpt-4o-mini
```

`gpt-4o-mini` is usually cheaper for JSON extraction. You are billed by OpenAI for every screening run.

## Run the app

```bash
streamlit run app.py
```

Then:

1. Paste a job description (or pick a fictional sample in the dropdown)
2. Upload one or more PDFs
3. Optionally change scoring weights in the sidebar
4. Click **Start resume screening**
5. Review matched skills, missing skills, evidence, and the comparison table
6. Download the Excel report

## Create sample PDFs from the fictional text resumes

```bash
python scripts/create_sample_pdfs.py
```

This writes PDFs into `sample_data/resumes_pdf/`. Those files are synthetic. They are **not real people**.

## Run tests

Tests cover PDF extraction, missing data, scoring, and Excel export. They do **not** call OpenAI.

```bash
pytest
```

## How the algorithm works (interview-ready)

### 1. PDF extraction

PyMuPDF (`fitz`) reads selectable text from PDF bytes in memory. Original files are never saved over.

If the file is empty, encrypted, corrupted, or looks like a scan (images with almost no text), the app **stops** and explains that OCR would be required. It does not invent resume content.

### 2. Structured extraction

The OpenAI API is asked for JSON only: name (if present), optional contact fields, education, skills, tools, experience, projects, certifications, and evidence quotes.

Validation happens after the response:

- Invalid JSON → no fields are guessed
- Missing values stay `null` or `[]`

Contact details are **not ranking features**. They are omitted from the Excel export.

### 3. Job matching score

```
overall = 100 × (
    w_required    × required_skill_coverage
  + w_preferred   × preferred_skill_coverage
  + w_experience  × experience_theme_overlap
  + w_education   × qualification_overlap
  + w_evidence    × matched_skills_backed_by_quotes
)
```

Default weights live in `config/scoring.json` and can be changed in the sidebar. Weights are re-normalized so they always add up to 100%.

**Required-skill coverage** = matched required skills ÷ required skills in the job description.

A skill “matches” if the normalized labels are equal, or one contains the other (length ≥ 4), or it appears as a whole word in the resume text. A small alias list maps names such as `js` → `javascript`.

**Ranking** sorts by this score only. Name is a display label, not a feature. Protected characteristics and personality traits are not extracted and not scored.

### 4. Human review

Every result shows evidence quotes and missing/unverified skills. Low scores mean “less evidenced overlap with this job description,” not “reject.”

## Privacy and uploaded files

- Resumes are processed in memory for the Streamlit session
- The app does not overwrite your original PDFs
- Text is sent to OpenAI for extraction if you provide an API key — follow your employer’s privacy rules before uploading real resumes
- Excel export excludes email and phone

## Limitations

- Scanned PDFs need OCR first (not included)
- Extraction quality depends on the model and the resume layout
- The local job-description fallback only recognizes a small skill list
- Keyword overlap can miss equivalent experience described in different words
- API use costs money and sends resume text to OpenAI

## Troubleshooting

| Problem | What to try |
|---|---|
| `OPENAI_API_KEY is missing` | Create `.env` from `.env.example` and restart Streamlit |
| `The PDF could not be opened` | File may be corrupted or not a real PDF |
| `needs OCR` | Export a text-based PDF from Word, or run OCR in another tool |
| `The model did not return valid JSON` | Retry; check API status; try another model name |
| `ModuleNotFoundError` | Activate the virtual environment and `pip install -r requirements.txt` |
| Tests fail on PDF creation | Confirm `pymupdf` installed |

## Design decisions worth explaining in an interview

- **Modular architecture:** UI, extraction, parsing, scoring, and reporting are separate so each piece can be tested.
- **Structured outputs:** JSON is validated before scoring so a messy model reply cannot silently become fake skills.
- **Explainable score:** weighted coverage is easier to defend than a black-box embedding similarity score.
- **Fail closed on bad PDFs:** missing text becomes a warning, not a guessed resume.
- **Human in the loop:** ranking is a review aid, not an automated reject list.
- **Least-privilege export:** spreadsheets omit extra contact data.

Sample names, jobs, and resumes in `sample_data/` are fictional and labeled as such.
