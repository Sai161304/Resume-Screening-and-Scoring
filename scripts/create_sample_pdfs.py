"""
Turn the fictional .txt resumes into PDFs using PyMuPDF.

Run after installing requirements:
    python scripts/create_sample_pdfs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pdf_extractor import make_simple_pdf_bytes  # noqa: E402


def main() -> None:
    source_dir = ROOT / "sample_data" / "resumes"
    output_dir = ROOT / "sample_data" / "resumes_pdf"
    output_dir.mkdir(parents=True, exist_ok=True)

    created = []
    for text_file in sorted(source_dir.glob("*.txt")):
        content = text_file.read_text(encoding="utf-8")
        pdf_bytes = make_simple_pdf_bytes(content)
        output_path = output_dir / f"{text_file.stem}.pdf"
        output_path.write_bytes(pdf_bytes)
        created.append(output_path.name)

    readme = output_dir / "README.txt"
    readme.write_text(
        "These PDFs are generated from fictional sample resumes. They are not real people.\n",
        encoding="utf-8",
    )
    print("Created sample PDFs:", ", ".join(created))


if __name__ == "__main__":
    main()
