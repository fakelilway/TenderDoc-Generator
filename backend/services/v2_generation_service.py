"""V2 Generation Pipeline — orchestrates the full V2 architecture.

Wire format extraction → form filling → content writing → audit → export
into a single function that returns BidPackage (same API as V1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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
    """V2 equivalent of BidPackage — keeps API compatibility."""
    commercial_markdown: str = ""
    technical_markdown: str = ""
    pricing_markdown: str = ""
    combined_markdown: str = ""
    missing_checklist: list[str] = field(default_factory=list)
    audit_result: AuditResult | None = None

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
) -> V2BidPackage:
    """V2 generation: extract → fill → write → audit.

    Same external contract as generate_bid_package() but using the
    original-copy skeleton architecture.
    """
    from core.config import get_settings
    settings = get_settings()
    company_name = company_name or settings.company_name
    profile = company_profile or _load_company_profile()
    profile["company_name"] = company_name
    retrieved = retrieved_chunks_by_section or {}

    # ── Phase 1: Extract format pages ──
    all_pages = extract_format_pages(tender_text)
    if not all_pages.get("commercial"):
        raise ValueError("V2 生成失败：未能从招标文件提取格式章节。请确认格式章节存在。")

    classified = assign_page_volumes(all_pages["commercial"], requirements)

    # ── Phase 2: Fill form templates ──
    filled_pages: dict[str, list[tuple[str, str, str]]] = {
        "commercial": [], "technical": [], "pricing": []
    }
    fill_results: list[FillResult] = []
    page_pairs: list[tuple[str, str]] = []  # (title, original) for audit

    for vol in ("commercial", "technical", "pricing"):
        for page in classified.get(vol, []):
            if page.raw_template:
                result = fill_page_template(page.raw_template, profile, page.title)
                filled_pages[vol].append((page.title, page.raw_template, result.filled_template))
                fill_results.append(result)
                if page.page_type != "prose_section":
                    page_pairs.append((page.title, page.raw_template))

    # ── Phase 3: Write prose content (technical volume only) ──
    tech_content = ""
    prose_results: VolumeFillResult | None = None
    for page in classified.get("technical", []):
        if page.page_type == "prose_section" or "施工" in page.title:
            # Collect sub-section titles from format tree
            tech_titles = _collect_technical_titles(requirements)
            if not tech_titles:
                tech_titles = [page.title]

            chunks = retrieved.get("technical", []) or retrieved.get("施工组织", []) or []
            prose_results = fill_technical_volume(
                node_titles=tech_titles,
                project_name=requirements.project_name or "投标项目",
                requirements=requirements.model_dump(),
                company_name=company_name,
                knowledge_chunks=[{"content": str(c) if isinstance(c, str) else str(getattr(c, "content", c))}
                                  for c in chunks[:10]],
                tender_text=tender_text,
            )
            tech_content = prose_results.combined
            break

    # ── Phase 4: Assemble markdown per volume ──

    def _assemble_markdown(vol: str) -> str:
        lines: list[str] = []
        project = requirements.project_name or "投标项目"
        label = V2BidPackage.VOLUME_HEADINGS.get(vol, vol)
        lines.append(f"# {project} {label}\n")

        for idx, (title, original, filled) in enumerate(filled_pages.get(vol, [])):
            if vol == "technical" and ("施工" in title or _is_prose_page(title)):
                content = tech_content if tech_content and idx == 0 else filled
            else:
                content = filled

            # Clean content: strip HTML, keep plain markdown
            content = _clean_for_markdown(content)
            content = re.sub(r'_{3,}', '________', content)

            lines.append(f"\n## {title}\n\n{content}\n")

        return "\n".join(lines)

    commercial_md = _assemble_markdown("commercial")
    technical_md = _assemble_markdown("technical")
    pricing_md = _assemble_markdown("pricing")

    # ── Phase 5: Audit ──
    filled_page_pairs = []
    for vol in ("commercial", "technical", "pricing"):
        for title, original, filled in filled_pages.get(vol, []):
            filled_page_pairs.append((title, filled))

    audit = full_audit(
        pages=page_pairs,
        filled_pages=filled_page_pairs,
        prose_text=tech_content,
        project_name=requirements.project_name or "",
        requirements=requirements.model_dump(),
        filled_fields=_collect_filled_fields(fill_results),
        profile=profile,
    )

    # ── Phase 6: Assemble final package ──
    missing = generate_missing_checklist(fill_results)

    return V2BidPackage(
        commercial_markdown=commercial_md,
        technical_markdown=technical_md,
        pricing_markdown=pricing_md,
        combined_markdown=f"{commercial_md}\n\n---\n\n{technical_md}\n\n---\n\n{pricing_md}",
        missing_checklist=missing,
        audit_result=audit,
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
    nodes = requirements.format_outline_tree.get("technical", [])
    for node in nodes:
        t = getattr(node, "title", "") or (node.get("title", "") if isinstance(node, dict) else "")
        if t:
            titles.append(t)
        children = getattr(node, "children", []) or (node.get("children", []) if isinstance(node, dict) else [])
        for child in children:
            ct = getattr(child, "title", "") or (child.get("title", "") if isinstance(child, dict) else "")
            if ct:
                titles.append(ct)
    return titles or ["施工组织设计"]


def _is_prose_page(title: str) -> bool:
    return any(kw in title for kw in ["施工", "方案", "措施", "部署", "计划", "进度", "质量", "安全"])


def _collect_filled_fields(results: list[FillResult]) -> list[dict[str, Any]]:
    """Extract filled fields for evidence audit."""
    fields: list[dict[str, Any]] = []
    for r in results:
        for f in r.fields:
            fields.append({
                "label": f.label,
                "value": f.value,
                "matched": f.matched,
                "profile_key": "",
            })
    return fields


def _clean_for_markdown(text: str) -> str:
    """Strip HTML tags and normalize text for Markdown/DOCX rendering."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Normalize line endings
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\r', '\n', text)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove page numbers (standalone digits at line start/end)
    text = re.sub(r'\n\s*\d{1,3}\s*\n', '\n', text)
    return text.strip()
