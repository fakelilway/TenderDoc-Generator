from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_analyze_pdf_format_is_parameterized(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    script = _load_script("analyze_pdf_format", "scripts/analyze_pdf_format.py")
    pdf_path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72), "Tender file format sample", fontsize=14, fontname="helv"
    )
    document.save(pdf_path)
    document.close()

    report = script.analyze_pdf_format(pdf_path)

    assert report["source_file"] == str(pdf_path)
    assert report["total_pages"] == 1
    assert report["unique_styles"] >= 1
    assert "Tender file format sample" in report["styles"][0]["samples"][0]


