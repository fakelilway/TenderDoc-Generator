"""Gap evaluation between an AI-generated bid and a real bid reference (M63).

Given an AI-generated document (DOCX or Markdown) and a reference structure
(a real bid parsed into a :class:`BidTemplate`, or the template JSON), this
module reports the structural gap: missing main sections, missing construction
sub-sections, missing 施工附表, missing fixed forms, content-length difference
and manual-confirmation-point statistics. It produces a Markdown/JSON report
used as a regression metric after prompt/generator changes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from schemas.bid_template import BidTemplate

# Markers indicating a spot the bid leaves for human confirmation / completion.
CONFIRM_MARKERS = ("人工确认", "待补充", "待确认", "待填写", "【人工", "占位")

_PREFIX_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百零〇]+[章节]、?|"
    r"[一二三四五六七八九十]+、|"
    r"附表[一二三四五六七八九十]+、?|"
    r"（[一二三四五六七八九十]+）)"
)


def _normalize(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def section_key(title: str) -> str:
    """Reduce a section title to its matchable core (drop numbering prefixes)."""
    core = _PREFIX_RE.sub("", str(title or "").strip())
    return _normalize(core)


def extract_markdown_structure(markdown_text: str) -> dict[str, Any]:
    headings: list[str] = []
    section_lengths: dict[str, int] = {}
    manual_points: list[str] = []
    current: str | None = None
    total = 0
    content_parts: list[str] = []

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                headings.append(title)
                current = title
                section_lengths.setdefault(title, 0)
            continue
        content_parts.append(line)
        total += len(line)
        if current is not None:
            section_lengths[current] = section_lengths.get(current, 0) + len(line)
        if any(marker in line for marker in CONFIRM_MARKERS):
            manual_points.append(line)

    return {
        "sections": headings,
        "section_lengths": section_lengths,
        "total_chars": total,
        "manual_confirmation_points": manual_points,
        "text": " ".join(headings + content_parts),
    }


def extract_docx_structure(docx_path: str | Path) -> dict[str, Any]:
    from docx import Document

    document = Document(str(docx_path))
    headings: list[str] = []
    section_lengths: dict[str, int] = {}
    manual_points: list[str] = []
    current: str | None = None
    total = 0
    content_parts: list[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name if paragraph.style else ""
        if style_name and style_name.startswith("Heading"):
            headings.append(text)
            current = text
            section_lengths.setdefault(text, 0)
            continue
        content_parts.append(text)
        total += len(text)
        if current is not None:
            section_lengths[current] = section_lengths.get(current, 0) + len(text)
        if any(marker in text for marker in CONFIRM_MARKERS):
            manual_points.append(text)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                cell_text = cell.text.strip()
                total += len(cell_text)
                content_parts.append(cell_text)

    return {
        "sections": headings,
        "section_lengths": section_lengths,
        "total_chars": total,
        "manual_confirmation_points": manual_points,
        "text": " ".join(headings + content_parts),
    }


def _split_present_missing(
    sections: list[Any],
    blob: str,
) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    for section in sections:
        title = section.title if hasattr(section, "title") else str(section)
        key = section_key(title)
        if key and key in blob:
            present.append(title)
        else:
            missing.append(title)
    return present, missing


def _coverage(present: list[str], missing: list[str]) -> float:
    total = len(present) + len(missing)
    if total == 0:
        return 1.0
    return round(len(present) / total, 4)


def evaluate_gap(
    template: BidTemplate,
    ai_structure: dict[str, Any],
    reference_total_chars: int | None = None,
    ai_source: str = "",
) -> dict[str, Any]:
    blob = _normalize(ai_structure.get("text", ""))

    present_main, missing_main = _split_present_missing(template.main_sections, blob)
    present_con, missing_con = _split_present_missing(
        template.construction_design_sections, blob
    )
    present_app, missing_app = _split_present_missing(template.appendix_sections, blob)
    present_fixed, missing_fixed = _split_present_missing(
        template.fixed_form_sections, blob
    )

    ai_total = int(ai_structure.get("total_chars", 0))
    length_ratio = (
        round(ai_total / reference_total_chars, 4)
        if reference_total_chars
        else None
    )
    manual_points = ai_structure.get("manual_confirmation_points", [])

    issues: list[str] = []
    for title in missing_main:
        issues.append(f"缺少主章节：{title}")
    for title in missing_app:
        issues.append(f"缺少施工附表：{title}")
    if missing_fixed:
        issues.append(f"缺少固定表单 {len(missing_fixed)} 项")
    if missing_con:
        issues.append(f"缺少施工组织设计子章节 {len(missing_con)} 项")
    if length_ratio is not None and length_ratio < 0.5:
        issues.append(
            f"内容长度仅为真实投标文件的 {round(length_ratio * 100, 1)}%，篇幅明显不足"
        )

    return {
        "reference_template": template.template_name,
        "reference_page_count": template.page_count,
        "ai_source": ai_source,
        "missing_main_sections": missing_main,
        "present_main_sections": present_main,
        "missing_construction_sections": missing_con,
        "missing_appendix_sections": missing_app,
        "missing_fixed_form_sections": missing_fixed,
        "main_section_coverage": _coverage(present_main, missing_main),
        "construction_section_coverage": _coverage(present_con, missing_con),
        "appendix_coverage": _coverage(present_app, missing_app),
        "ai_total_chars": ai_total,
        "reference_total_chars": reference_total_chars,
        "length_ratio": length_ratio,
        "manual_confirmation_point_count": len(manual_points),
        "manual_confirmation_points": manual_points,
        "issues": issues,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# 真实投标文件差距评估报告",
        "",
        f"- 参照模板：{report.get('reference_template') or '-'}",
        f"- 参照页数：{report.get('reference_page_count') or '-'}",
        f"- AI 文件：{report.get('ai_source') or '-'}",
        "",
        "## 覆盖率",
        "",
        "| 维度 | 覆盖率 |",
        "| --- | --- |",
        f"| 主章节 | {report.get('main_section_coverage')} |",
        f"| 施工组织设计子章节 | {report.get('construction_section_coverage')} |",
        f"| 施工附表 | {report.get('appendix_coverage')} |",
        "",
        "## 内容篇幅",
        "",
        f"- AI 正文字数：{report.get('ai_total_chars')}",
        f"- 真实投标字数：{report.get('reference_total_chars') if report.get('reference_total_chars') is not None else '未知'}",
        f"- 篇幅比例：{report.get('length_ratio') if report.get('length_ratio') is not None else '未知'}",
        f"- 人工确认点：{report.get('manual_confirmation_point_count')} 处",
        "",
        "## 差距问题清单",
        "",
    ]
    issues = report.get("issues", [])
    if not issues:
        lines.append("（未发现明显结构差距）")
    for issue in issues:
        lines.append(f"- {issue}")
    return "\n".join(lines) + "\n"


def load_reference_template(reference_path: str | Path) -> tuple[BidTemplate, int | None]:
    """Load a reference structure from a template JSON or a real bid PDF.

    Returns the :class:`BidTemplate` and the reference total character count
    (only available when parsing a PDF, otherwise ``None``).
    """
    path = Path(reference_path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        template = BidTemplate.model_validate_json(path.read_text(encoding="utf-8"))
        return template, None
    if suffix == ".pdf":
        from pypdf import PdfReader

        from utils.bid_template_parser import parse_bid_template_pages

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        template = parse_bid_template_pages(
            pages, source_file=path.name, template_name=path.stem
        )
        reference_total_chars = sum(len(re.sub(r"\s+", "", page)) for page in pages)
        return template, reference_total_chars
    raise ValueError(f"不支持的参照文件类型：{suffix}")


def load_ai_structure(ai_path: str | Path) -> dict[str, Any]:
    path = Path(ai_path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx_structure(path)
    if suffix in {".md", ".markdown", ".txt"}:
        return extract_markdown_structure(path.read_text(encoding="utf-8"))
    raise ValueError(f"不支持的 AI 文件类型：{suffix}")
