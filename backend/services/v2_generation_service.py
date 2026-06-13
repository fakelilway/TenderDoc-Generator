"""V2 Generation Pipeline — orchestrates the only bid generation architecture.

Wire format extraction → form filling → content writing → audit → export
into a single package for workflow/export.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Named constants for magic numbers
MAX_KNOWLEDGE_CHUNKS = 10  # Max RAG chunks per content writer call

# Pre-compiled regex patterns for _clean_for_markdown
_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_CRLF = re.compile(r"\r\n")
_RE_CR = re.compile(r"\r")
_RE_BLANK_LINES = re.compile(r"\n{3,}")
_RE_PAGE_NUM = re.compile(r"\n\s*\d{1,3}\s*\n")
_RE_UNDERSCORE = re.compile(r"_{3,}")

from schemas.tender import TenderRequirements
from services.format_skeleton_service import (
    extract_format_pages,
    assign_page_volumes,
)
from agents.form_filler_agent import (
    fill_page_template,
    FillResult,
    generate_missing_checklist,
)
from agents.content_writer_agent import fill_technical_volume, VolumeFillResult
from services.v2_audit_service import (
    full_audit,
    AuditResult,
    AuditIssue,
)


@dataclass
class V2BidPackage:
    """Generated bid package produced by the V2 original-format pipeline."""

    commercial_markdown: str = ""
    technical_markdown: str = ""
    pricing_markdown: str = ""
    combined_markdown: str = ""
    missing_checklist: list[str] = field(default_factory=list)
    audit_result: AuditResult | None = None
    format_docx_path: str | None = None  # Pre-built format DOCX from PDF

    VOLUME_ORDER = ("commercial", "technical", "pricing")
    VOLUME_HEADINGS = {
        "commercial": "商务文件",
        "technical": "技术文件",
        "pricing": "报价文件",
    }

    def volume_map(self) -> dict[str, str]:
        return {
            "commercial": self.commercial_markdown,
            "technical": self.technical_markdown,
            "pricing": self.pricing_markdown,
        }

    @property
    def generation_mode(self) -> str:
        return "v2_format_copy"


def generate_v2_bid_package(
    requirements: TenderRequirements,
    retrieved_chunks_by_section: dict[str, list] | None = None,
    *,
    company_name: str = "",
    tender_text: str = "",
    company_profile: dict[str, str] | None = None,
    original_format_docx_available: bool = False,
    tender_bytes: bytes | None = None,
) -> V2BidPackage:
    """V2 generation: extract → fill → write → audit.

    If tender_bytes is provided and is a PDF, the format chapter is converted
    directly to DOCX during generation — no separate export step needed.
    """
    from core.config import get_settings

    settings = get_settings()
    company_name = company_name or settings.company_name
    profile = company_profile or _load_company_profile()
    profile["company_name"] = company_name
    retrieved = retrieved_chunks_by_section or {}

    # ── Phase 0: Build original format DOCX if PDF ──
    built_format_docx: str | None = None
    if original_format_docx_available and tender_bytes:
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            from services.original_docx_format_service import (
                build_original_format_docx_from_pdf,
            )

            built_format_docx = build_original_format_docx_from_pdf(
                tender_bytes, tmp_path, profile=profile
            )
        except Exception:
            logger.error("PDF format conversion failed", exc_info=True)
            raise ValueError("PDF 招标文件原格式复制失败，系统不会回退生成近似格式文件。")

    # ── Phase 1: Extract format pages (skip if using original format DOCX) ──
    if original_format_docx_available:
        # Original format (OOXML copy or PDF images) is pixel-perfect.
        # Skip text-based format extraction — only need prose content.
        all_pages: dict = {"commercial": [], "technical": [], "pricing": []}
    else:
        all_pages = extract_format_pages(tender_text)
        if not all_pages.get("commercial"):
            raise ValueError("V2 生成失败：未能从招标文件提取格式章节。请确认格式章节存在。")

    classified = assign_page_volumes(all_pages["commercial"], requirements)

    # Build combined profile with project-specific fields from requirements
    project_fields = {
        "招标人": str(requirements.tenderer_name or ""),
        "项目名称": str(requirements.project_name or ""),
        "工期": str(requirements.planned_duration or ""),
        "质量": "符合国家现行工程质量验收标准规范合格标准",
        "安全": "无安全责任事故发生",
    }

    # ── Phase 2: Fill form templates (skip in original format mode) ──
    combined_profile = {**profile, **project_fields}

    filled_pages: dict[str, list[tuple[str, str, str]]] = {
        "commercial": [],
        "technical": [],
        "pricing": [],
    }
    fill_results: list[FillResult] = []
    page_pairs: list[tuple[str, str]] = []

    if not original_format_docx_available:
        for vol in ("commercial", "technical", "pricing"):
            for page in classified.get(vol, []):
                if page.raw_template:
                    result = fill_page_template(
                        page.raw_template, combined_profile, page.title
                    )
                    filled_pages[vol].append(
                        (page.title, page.raw_template, result.filled_template)
                    )
                    fill_results.append(result)
                    if page.page_type != "prose_section":
                        page_pairs.append((page.title, page.raw_template))

    # ── Phase 3: Write prose content ──
    tech_content = ""
    prose_results: VolumeFillResult | None = None

    def _call_content_writer(titles: list[str]) -> tuple[VolumeFillResult | None, str]:
        """Write prose content per-node for depth. Each node gets a dedicated LLM call
        for 2000+ character sections with engineering parameters and emergency plans."""
        chunks = retrieved.get("technical", []) or retrieved.get("施工组织", []) or []
        all_results: list[str] = []
        first_result = None
        for title in titles:
            result = fill_technical_volume(
                node_titles=[title],  # Single node for deep coverage
                project_name=requirements.project_name or "投标项目",
                requirements=requirements.model_dump(),
                company_name=company_name,
                knowledge_chunks=[
                    {
                        "content": str(c)
                        if isinstance(c, str)
                        else str(getattr(c, "content", c))
                    }
                    for c in chunks[:MAX_KNOWLEDGE_CHUNKS]
                ],
                tender_text=tender_text,
            )
            if first_result is None:
                first_result = result
            section_body = _strip_writer_top_level_headings(result.combined)
            all_results.append(f"## {title}\n\n{section_body}")
        combined = "\n\n".join(all_results)
        return first_result, combined

    if not original_format_docx_available and classified.get("technical"):
        for page in classified["technical"]:
            if page.page_type == "prose_section" or "施工" in page.title:
                tech_titles = _collect_technical_titles(requirements)
                if not tech_titles:
                    tech_titles = [page.title]
                prose_results, tech_content = _call_content_writer(tech_titles)
                break
    elif original_format_docx_available:
        tech_titles = _collect_technical_titles(requirements) or ["施工组织设计"]
        try:
            prose_results, tech_content = _call_content_writer(tech_titles)
        except Exception as exc:
            logger.error("Content writer failed in original format mode", exc_info=True)
            raise ValueError(
                "V2 生成失败：施工方案正文生成失败。系统不会输出占位正文，请检查 LLM 配置、" "招标文件文本或知识库资料后重新生成。"
            ) from exc

    # ── Phase 4: Assemble markdown per volume ──

    def _assemble_markdown(vol: str) -> str:
        lines: list[str] = []
        project = requirements.project_name or "投标项目"
        label = V2BidPackage.VOLUME_HEADINGS.get(vol, vol)
        lines.append(f"# {project} {label}\n")
        technical_content_inserted = False
        volume_pages = filled_pages.get(vol, [])

        if volume_pages:
            lines.append("\n<!-- tdg:pagebreak -->\n")
            lines.append(_render_volume_directory(volume_pages))
            lines.append("\n<!-- tdg:pagebreak -->\n")

        for idx, (title, original, filled) in enumerate(volume_pages):
            if vol == "technical" and ("施工" in title or _is_prose_page(title)):
                if tech_content and not technical_content_inserted:
                    lines.append("\n<!-- tdg:pagebreak -->\n")
                    lines.append(
                        f"\n{_add_pagebreaks_before_headings(_clean_for_markdown(tech_content))}\n"
                    )
                    technical_content_inserted = True
                elif not tech_content:
                    content = _clean_for_markdown(filled)
                    content = _RE_UNDERSCORE.sub("________", content)
                    lines.append("\n<!-- tdg:pagebreak -->\n")
                    lines.append(f"\n## {title}\n\n{content}\n")
                continue
            else:
                content = filled

            # Clean content: strip HTML, keep plain markdown
            content = _clean_for_markdown(content)
            content = re.sub(r"_{3,}", "________", content)
            content = _render_locked_format_content(
                title,
                original,
                content,
                combined_profile,
            )

            lines.append("\n<!-- tdg:pagebreak -->\n")
            lines.append(f"\n## {title}\n\n{content}\n")

        return "\n".join(lines)

    commercial_md = _assemble_markdown("commercial")
    technical_md = _assemble_markdown("technical")
    pricing_md = _assemble_markdown("pricing")

    # ── Phase 5: Audit ──
    filled_page_pairs = []
    for vol in ("commercial", "technical", "pricing"):
        for title, original, filled in filled_pages.get(vol, []):
            rendered = _render_locked_format_content(
                title,
                original,
                _clean_for_markdown(filled),
                combined_profile,
            )
            filled_page_pairs.append((title, rendered))

    audit = full_audit(
        pages=page_pairs,
        filled_pages=filled_page_pairs,
        prose_text=tech_content,
        project_name=requirements.project_name or "",
        requirements=requirements.model_dump(),
        filled_fields=_collect_filled_fields(fill_results),
        profile=profile,
    )
    if not audit.passed and (
        not original_format_docx_available
        or audit.content_issues
        or audit.evidence_issues
    ):
        raise ValueError(_format_audit_failure_message(audit))

    # ── Phase 6: Assemble final package ──
    missing = generate_missing_checklist(fill_results)

    # Use explicit tdg:volume:xxx markers so split_delivery_markdown can recover
    # the three volumes losslessly. Plain "---" separators make it fall back to
    # a heading-keyword heuristic that loses content when volumes share titles.
    from utils.docx_exporter import combine_delivery_volumes

    combined = combine_delivery_volumes(
        doc_title=requirements.project_name or "投标项目",
        volumes={
            "commercial": commercial_md,
            "technical": technical_md,
            "pricing": pricing_md,
        },
        notes="",
    )

    return V2BidPackage(
        commercial_markdown=commercial_md,
        technical_markdown=technical_md,
        pricing_markdown=pricing_md,
        combined_markdown=combined,
        missing_checklist=missing,
        audit_result=audit,
        format_docx_path=built_format_docx,
    )


def _load_company_profile() -> dict[str, str]:
    """Load company profile, falling back to defaults."""
    try:
        from services.company_profile_service import get_company_profile

        data = get_company_profile()
        profile = data.get("profile", {})
        if isinstance(profile, dict):
            return {str(k): str(v) for k, v in profile.items()}
    except Exception:
        pass
    return {}


def _collect_technical_titles(requirements: TenderRequirements) -> list[str]:
    """Collect construction plan section titles from format tree."""
    titles: list[str] = []
    seen: set[str] = set()

    def add_title(value: str) -> None:
        clean = (value or "").strip()
        if not clean or "投标文件" in clean:
            return
        key = re.sub(r"\s+", "", clean)
        if key in seen:
            return
        seen.add(key)
        titles.append(clean)

    nodes = requirements.format_outline_tree.get("technical", [])
    for node in nodes:
        t = getattr(node, "title", "") or (
            node.get("title", "") if isinstance(node, dict) else ""
        )
        add_title(t)
        children = getattr(node, "children", []) or (
            node.get("children", []) if isinstance(node, dict) else []
        )
        for child in children:
            ct = getattr(child, "title", "") or (
                child.get("title", "") if isinstance(child, dict) else ""
            )
            add_title(ct)
    if not titles:
        titles = ["施工组织设计"]
    return titles


def _strip_writer_top_level_headings(markdown: str) -> str:
    """Keep format-tree titles as the only top-level headings.

    Content writer calls are scoped to a single node, but models often echo
    ``#``/``##`` headings anyway. Removing those headings prevents generated
    prose from adding or duplicating tender-format nodes.
    """
    lines = []
    for line in markdown.splitlines():
        if re.match(r"^\s*#{1,2}\s+", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _is_prose_page(title: str) -> bool:
    return any(kw in title for kw in ["施工", "方案", "措施", "部署", "计划", "进度", "质量", "安全"])


def _render_locked_format_content(
    title: str,
    original: str,
    content: str,
    profile: dict[str, str],
) -> str:
    """Keep locked commercial/pricing form pages structured.

    Locked commercial/pricing forms must not be approximated. If PDF text
    extraction flattens a required table, the audit layer fails generation
    instead of letting a reconstructed layout masquerade as the tender format.
    """
    if _has_markdown_table(content):
        return content
    if _requires_figure_placeholder(title, original):
        return "【图表占位：请按招标文件要求插入对应组织机构图、进度计划图、施工总平面图或知识库图片资料】"
    return content


def _format_audit_failure_message(audit: AuditResult) -> str:
    issues = audit.all_issues[:8]
    details = "；".join(f"{issue.location}: {issue.problem}" for issue in issues)
    return "V2 生成失败：审查未通过。" "系统不会输出近似重画格式、占位正文或证据不一致的半成品，以免形成废标风险。" f"{details}"


def _render_volume_directory(pages: list[tuple[str, str, str]]) -> str:
    lines = ["## 目 录", ""]
    for title, _original, _filled in pages:
        lines.append(title)
    return "\n".join(lines)


def _add_pagebreaks_before_headings(markdown: str) -> str:
    lines: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if lines and lines[-1].strip() != "<!-- tdg:pagebreak -->":
                lines.extend(["", "<!-- tdg:pagebreak -->", ""])
        lines.append(line)
    return "\n".join(lines)


def _has_markdown_table(content: str) -> bool:
    lines = [line.strip() for line in content.splitlines()]
    for index, line in enumerate(lines[:-1]):
        if (
            line.startswith("|")
            and lines[index + 1].startswith("|")
            and "---" in lines[index + 1]
        ):
            return True
    return False


def _requires_figure_placeholder(title: str, original: str) -> bool:
    text = f"{title}\n{original}"
    return any(
        keyword in text
        for keyword in (
            "组织机构图",
            "框图",
            "施工总平面图",
            "平面布置图",
            "进度计划图",
            "网络图",
            "横道图",
            "附图",
            "图表",
        )
    )


def _collect_filled_fields(results: list[FillResult]) -> list[dict[str, Any]]:
    """Extract filled fields for evidence audit."""
    fields: list[dict[str, Any]] = []
    for r in results:
        for f in r.fields:
            fields.append(
                {
                    "label": f.label,
                    "value": f.value,
                    "matched": f.matched,
                    "profile_key": "",
                }
            )
    return fields


def _clean_for_markdown(text: str) -> str:
    """Strip HTML tags and normalize text for Markdown/DOCX rendering."""
    text = _RE_HTML_TAG.sub("", text)
    text = _RE_CRLF.sub("\n", text)
    text = _RE_CR.sub("\n", text)
    text = _RE_BLANK_LINES.sub("\n\n", text)
    text = _RE_PAGE_NUM.sub("\n", text)
    return text.strip()
