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
    page.insert_text((72, 72), "Tender file format sample", fontsize=14, fontname="helv")
    document.save(pdf_path)
    document.close()

    report = script.analyze_pdf_format(pdf_path)

    assert report["source_file"] == str(pdf_path)
    assert report["total_pages"] == 1
    assert report["unique_styles"] >= 1
    assert "Tender file format sample" in report["styles"][0]["samples"][0]


def test_generate_bid_script_uses_template_and_sanitized_defaults(tmp_path: Path) -> None:
    script = _load_script("generate_bid", "scripts/generate_bid.py")
    requirements = script.load_requirements(None, demo=True)
    template = script.load_template(
        PROJECT_ROOT / "backend/templates/bid_templates/road_first_envelope_template.json"
    )

    artifacts = script.generate_bid_artifacts(
        requirements,
        output_dir=tmp_path,
        template=template,
        export_docx=False,
    )

    markdown_path = Path(artifacts["markdown_path"])
    markdown = markdown_path.read_text(encoding="utf-8")

    assert markdown_path.exists()
    assert "脱敏示例项目" in markdown
    assert "投标人名称（脱敏）" in markdown
    assert "第一章、总体施工组织布置及规划" in markdown
    assert "安徽正奇建设有限公司" not in markdown
    assert "张正奇" not in markdown
    assert "0551-65650939" not in markdown
