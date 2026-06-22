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
from agents.form_filler_agent import (
    FillResult,
    generate_missing_checklist,
)
from agents.content_writer_agent import fill_technical_volume, VolumeFillResult
from services.v2_audit_service import (
    full_audit,
    AuditResult,
    AuditIssue,
)
_RE_CJK_RUN = re.compile(r"[一-鿿A-Za-z0-9]+")


def _cjk_bigrams(text: str) -> set[str]:
    """Character bigrams over CJK/alphanumeric runs.

    Chinese has no word boundaries and the shared tokenizer returns whole runs,
    so exact-token overlap rarely matches. Bigram overlap is a cheap, robust
    similarity signal for matching requirement items to node titles.
    """
    grams: set[str] = set()
    for run in _RE_CJK_RUN.findall(text or ""):
        if len(run) == 1:
            grams.add(run)
            continue
        for i in range(len(run) - 1):
            grams.add(run[i : i + 2])
    return grams


def _distribute_requirement_items(
    titles: list[str],
    items: list[Any],
) -> dict[str, list[dict[str, str]]]:
    """Map each评分项/废标项 to the technical node it best matches by bigram overlap.

    Every item is assigned to exactly one node (its best match, or a catch-all
    node when there is no overlap) so the writer responds to all scored criteria
    without duplicating every item into every section.
    """
    result: dict[str, list[dict[str, str]]] = {t: [] for t in titles}
    if not titles or not items:
        return result

    title_grams = {t: _cjk_bigrams(t) for t in titles}
    # Catch-all for items that match no node title.
    catch_all = next(
        (t for t in titles if ("施工组织" in t or "技术" in t or "组织设计" in t)),
        titles[0],
    )

    for item in items:
        item_title = str(getattr(item, "title", "") or "")
        item_desc = str(getattr(item, "description", "") or "")
        item_grams = _cjk_bigrams(f"{item_title} {item_desc}")
        best_title, best_overlap = None, 0
        for t in titles:
            overlap = len(item_grams & title_grams[t])
            if overlap > best_overlap:
                best_overlap, best_title = overlap, t
        target = best_title or catch_all
        result[target].append({"title": item_title, "description": item_desc})

    return result


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
    appendix_docx_path: str | None = None  # 技术卷附表(福昕可编辑空表,拼到技术卷末)
    audit_blocked: bool = False  # True when critical audit issues found (content still saved for preview)

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


def _audit_built_format_docx(docx_path: str) -> list[str]:
    """最低内容体检:复制出来的招标格式章 DOCX 不能是空壳。

    PDF 原格式路径绕过了基于页面的格式审查(原格式模式下 filled_pages 为空),
    一旦 pdf2docx/截图链静默产出一个几乎没有内容的文档,过去会一路绿灯发布。
    这里做**保守**检查:只在产物近乎为空(无有效段落、无表格、无任何图片)时判失败,
    不对版式/对齐做判断(那属 P1 渲染基线的范畴),以免误伤正常产出。返回严重问题列表。
    """
    from docx import Document

    try:
        doc = Document(docx_path)
    except Exception as exc:  # noqa: BLE001 - surface as a content issue
        return [f"格式章 DOCX 无法打开：{exc}"]

    has_text = any(p.text.strip() for p in doc.paragraphs)
    table_count = len(doc.tables)
    inline_images = len(doc.inline_shapes)
    # 整页截图路径用的是浮动图/VML imagedata,不计入 inline_shapes,需扫 body xml。
    try:
        body_xml = doc.element.body.xml
    except Exception:  # noqa: BLE001
        body_xml = ""
    embedded_images = body_xml.count("<a:blip") + body_xml.count("imagedata")

    if not (has_text or table_count or inline_images or embedded_images):
        return ["格式章复制产物为空（无段落/表格/图片）——复制链可能已失败"]
    return []


def _knowledge_chunk_payload(chunk: Any) -> dict[str, Any]:
    """把检索结果(RetrievalResult / dict / str)规整成写作 prompt 认的载荷。

    必须保留 ``metadata``——generator_prompt 靠 ``metadata['document_category']``
    才能把公司历史施组片段标成【公司同类施工方案·仅参照写法/工艺/深度】;旧代码
    只留 content,导致该深度标注永不触发(料即使接通也被当普通素材)。
    """
    if isinstance(chunk, dict):
        content = str(chunk.get("content", "") or chunk.get("snippet", ""))
        metadata = chunk.get("metadata") or {}
    elif isinstance(chunk, str):
        content, metadata = chunk, {}
    else:
        content = str(getattr(chunk, "content", chunk) or "")
        metadata = getattr(chunk, "metadata", {}) or {}
    return {"content": content, "metadata": metadata}


def _flatten_retrieved_chunks(retrieved: dict[str, list] | None) -> list[Any]:
    """检索结果按"章节标题"归类(见 workflow_service._retrieve_for_outline);
    汇总各节素材、按 chunk_id 去重成一份共享语料,喂给每个写作节点。

    历史致命 bug:旧代码 ``retrieved.get("technical")`` / ``get("施工组织")`` 取的
    key 在该字典里永不存在(键是中文章节标题),检索到的公司施组语料被静默丢弃,
    技术卷退化成 LLM 空写——这正是技术卷偏薄的根因。按 values() 汇总即与键名解耦。
    """
    flattened: list[Any] = []
    seen: set = set()
    for section_chunks in (retrieved or {}).values():
        for chunk in section_chunks or []:
            key = getattr(chunk, "chunk_id", None)
            if key is None:
                key = id(chunk)
            if key in seen:
                continue
            seen.add(key)
            flattened.append(chunk)
    return flattened


def generate_v2_bid_package(
    requirements: TenderRequirements,
    retrieved_chunks_by_section: dict[str, list] | None = None,
    *,
    company_name: str = "",
    tender_text: str = "",
    company_profile: dict[str, str] | None = None,
    original_format_docx_available: bool = False,
    tender_bytes: bytes | None = None,
    confirmed_technical_outline: list[dict] | None = None,
    project_id: int | None = None,
    boq_text: str = "",
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

    # Build combined profile with project-specific fields from requirements.
    # These must be available BEFORE Phase 0 so the PDF format copy can fill
    # placeholders with Parser-extracted values (质量标准, 安全目标, etc.).
    project_fields = {
        "招标人": str(requirements.tenderer_name or ""),
        "项目名称": str(requirements.project_name or ""),
        "工期": str(requirements.planned_duration or ""),
        "质量": str(requirements.quality_standard or "符合国家现行工程质量验收标准规范合格标准"),
        "安全": str(requirements.safety_target or "无安全责任事故发生"),
        "投标有效期": str(requirements.bid_deadline or ""),
        "投标截止时间": str(requirements.bid_deadline or ""),
        "开标时间": str(requirements.bid_deadline or ""),
    }
    combined_profile = {**profile, **project_fields}
    # 法人性别/年龄(从法人身份证 OCR 推导)→ 填法定代表人身份证明表的 性别/年龄 栏。
    combined_profile.update(_legal_rep_pii(str(combined_profile.get("legal_representative", ""))))

    # ── Phase 0: 招标商务格式章 PDF → 福昕云转可编辑 Word(唯一路径,无降级) ──
    built_format_docx: str | None = None
    built_appendix_docx: str | None = None
    if original_format_docx_available and tender_bytes:
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp_path = tmp.name
        tmp.close()

        # 唯一路径:福昕云转换(定位"投标文件格式"商务区页 → 福昕转可编辑 Word + 自动填公司
        # 档案)。已删 pdf2docx 可编辑 / 整页图+域烧录 / 纯整页截图 三档备胎——福昕失败即硬报错,
        # 绝不降级出不可编辑/近似稿(避免再迷糊"到底走哪条")。
        if str(getattr(settings, "cloud_pdf_convert", "off") or "off").lower() != "foxit":
            raise ValueError(
                "PDF 招标格式转换仅支持福昕云:请在 .env 配置 CLOUD_PDF_CONVERT=foxit 及 "
                "FOXIT_CLOUD_CLIENT_ID / FOXIT_CLOUD_SECRET 后重试。"
            )
        try:
            from services.cloud_pdf_convert import convert_format_pages_via_cloud

            built_format_docx = convert_format_pages_via_cloud(
                tender_bytes, tmp_path, profile=combined_profile
            )
        except Exception as exc:
            logger.error("福昕云转换失败(无降级路径)", exc_info=True)
            raise ValueError(
                f"PDF 招标文件原格式复制失败:福昕云转换出错,系统不回退近似格式。({exc})"
            ) from exc

    # Content-level audit of the copied format chapter. The PDF path bypasses
    # the page-based format audit (filled_pages stays empty in original mode), so
    # a silently-empty/broken copy would otherwise ship unchecked. Per the铁律
    # (格式复制失败=硬报错,不输出空壳/近似稿) we fail loudly here.
    if original_format_docx_available and built_format_docx:
        fmt_issues = _audit_built_format_docx(built_format_docx)
        if fmt_issues:
            raise ValueError(
                "V2 生成失败：招标格式章复制产物未通过内容体检"
                "（系统不输出空壳/近似稿，请检查 PDF 格式章或转换链）："
                + "；".join(fmt_issues)
            )

    # 技术卷附表:福昕把招标附表区(附表一~八)转成可编辑空表,导出时拼到技术卷末。
    # best-effort——失败则技术卷不含附表(投标人另行补),不影响主流程。
    if (
        original_format_docx_available
        and tender_bytes
        and str(getattr(settings, "cloud_pdf_convert", "off") or "off").lower() == "foxit"
    ):
        try:
            import tempfile as _tempfile

            from services.cloud_pdf_convert import convert_appendix_pages_via_cloud

            _ap = _tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
            _ap.close()
            built_appendix_docx = convert_appendix_pages_via_cloud(tender_bytes, _ap.name)
        except Exception:
            logger.warning("附表云转换失败 — 技术卷不含附表", exc_info=True)
            built_appendix_docx = None

    # 福昕原格式模式:格式页直接照抄招标 DOCX,无需文本提取/正则填表。下列容器恒空,
    # 下游装配/审查据此跳过"文本格式页"渲染、只审 prose 正文(v1 文本重建/正则填表路径已删)。
    filled_pages: dict[str, list[tuple[str, str, str]]] = {
        "commercial": [],
        "technical": [],
        "pricing": [],
    }
    fill_results: list[FillResult] = []
    page_pairs: list[tuple[str, str]] = []

    # ── Phase 3: Write prose content ──
    tech_content = ""
    prose_results: VolumeFillResult | None = None
    # A human-confirmed outline (bid_outline_json) drives the technical目录 when
    # present & substantive; otherwise fall back to tender outline / canonical.
    confirmed_sections = _sections_from_confirmed_outline(confirmed_technical_outline)

    # 工程量清单(第五章 BOQ)→ 分部分项占比,驱动技术卷"按占比定详略"+把工程量喂给对应施工方案。
    # best-effort:抽不到/失败返回空 TenderBOQ,写作退回原行为(不阻断出标)。
    try:
        from services import boq_service

        # 优先用本项目上传的工程量清单(另册)全文,占比按真实数量/金额算;没传才从招标正文估。
        boq = boq_service.build_boq(tender_text, boq_text=boq_text)
    except Exception:
        logger.warning("工程量清单抽取异常,技术卷跳过 BOQ 驱动(不阻断)", exc_info=True)
        boq = None

    def _call_content_writer(
        sections: list[dict],
    ) -> tuple[VolumeFillResult | None, str]:
        """Write prose for every technical section in one bounded-concurrency pass.

        Each section still gets its own focused LLM call (with its must-cover
        guidance, distributed 评分项/废标项 and per-section length budget) for
        winning-bid depth (~25 deep sub-sections), but the calls now run
        concurrently inside ``fill_technical_volume`` (capped by
        ``BID_WRITER_CONCURRENCY``), cutting the volume from ~25 min to ~5-6 min."""
        titles = [s["title"] for s in sections]
        # FIX(喂料接通):retrieved 按章节标题归类,旧代码取 "technical"/"施工组织"
        # 这两个永不存在的 key → 公司施组语料被静默丢弃、技术卷沦为 LLM 空写。
        # 改为汇总去重后喂每个写作节点,并保留 metadata(让"公司同类施工方案"标注生效)。
        chunks = _flatten_retrieved_chunks(retrieved)
        knowledge_chunks = [
            _knowledge_chunk_payload(c) for c in chunks[:MAX_KNOWLEDGE_CHUNKS]
        ]
        # Distribute scored/废标 criteria across nodes once, so each node only
        # carries the items it should respond to (avoids cross-section bloat).
        score_by_title = _distribute_requirement_items(
            titles, requirements.technical_score_items
        )
        invalid_by_title = _distribute_requirement_items(
            titles, requirements.invalid_bid_items
        )
        guidance_by_title = {s["title"]: str(s.get("must_cover", "")) for s in sections}
        min_chars_by_title = {
            s["title"]: int(s.get("target_chars", 0) or 0) for s in sections
        }

        # BOQ 驱动:每节喂"造价占比总览+本节对应清单项+工程量",并按占比调详略(主导加厚、极小压缩)。
        boq_by_title: dict[str, str] = {}
        if boq is not None and not boq.is_empty():
            from services import boq_service

            for t in titles:
                brief = boq_service.section_node_brief(boq, t)
                if brief:
                    boq_by_title[t] = brief
                min_chars_by_title[t] = boq_service.adjust_min_chars(
                    boq, t, min_chars_by_title.get(t, 0)
                )

        result = fill_technical_volume(
            node_titles=titles,
            project_name=requirements.project_name or "投标项目",
            requirements=requirements.model_dump(),
            company_name=company_name,
            knowledge_chunks=knowledge_chunks,
            tender_text=tender_text,
            score_items_by_title=score_by_title,
            invalid_items_by_title=invalid_by_title,
            guidance_by_title=guidance_by_title,
            min_chars_by_title=min_chars_by_title,
            boq_by_title=boq_by_title,
            max_workers=max(1, int(getattr(settings, "bid_writer_concurrency", 5) or 1)),
        )

        # Reassemble in section order; the format-tree title is the only top-level
        # heading per section (writer bodies are already cleaned of echoed ones).
        all_results: list[str] = []
        for title, node in zip(titles, result.nodes):
            section_body = _strip_writer_top_level_headings(
                f"\n## {title}\n\n{node.content}\n"
            )
            all_results.append(f"## {title}\n\n{section_body}")
        combined = "\n\n".join(all_results)
        return result, combined

    tech_sections = confirmed_sections or _collect_technical_sections(requirements)
    try:
        prose_results, tech_content = _call_content_writer(tech_sections)
    except Exception as exc:
        logger.error("Content writer failed", exc_info=True)
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
            content = _RE_UNDERSCORE.sub("________", content)
            content = _render_locked_format_content(
                title,
                original,
                content,
                combined_profile,
            )

            lines.append("\n<!-- tdg:pagebreak -->\n")
            lines.append(f"\n## {title}\n\n{content}\n")

        # Fallback: when volume_pages is empty (original format mode),
        # the for-loop above never runs. Insert tech_content directly
        # so the LLM output is not silently discarded.
        if vol == "technical" and tech_content and not technical_content_inserted:
            lines.append("\n<!-- tdg:pagebreak -->\n")
            lines.append(
                f"\n{_add_pagebreaks_before_headings(_clean_for_markdown(tech_content))}\n"
            )
            technical_content_inserted = True

        return "\n".join(lines)

    commercial_md = _assemble_markdown("commercial")
    technical_md = _assemble_markdown("technical")
    pricing_md = _assemble_markdown("pricing")

    # ── Phase 4b: Enrich commercial/pricing markdown in original format mode ──
    # When original_format_docx_available=True, format pages come from the
    # original DOCX, but the markdown preview still needs compliance content.
    if original_format_docx_available:
        commercial_md = _enrich_commercial_markdown(
            commercial_md,
            requirements,
            combined_profile,
            tender_text=tender_text,
            project_id=project_id,
        )
        # Remove commercial sections from technical markdown if the LLM
        # over-generated them (资格响应, 投标保证金, 项目管理机构 etc.)
        technical_md = _strip_commercial_sections(technical_md)
        notes_md = _build_audit_notes(requirements)
    else:
        notes_md = ""

    # ② 本项目定制插入图(航拍图/本项目图纸):按 target_section 插到技术卷对应节。
    technical_md = _inject_project_images(technical_md, project_id)

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
    audit_blocked = False
    if not audit.passed:
        # Critical issues block the downstream review/export pipeline,
        # but we still return the generated content so the user can preview it.
        has_critical = any(
            issue.severity == "critical"
            for issue in audit.all_issues
        )
        if has_critical:
            logger.warning(
                "Audit found critical issues — blocking review pipeline, "
                "but returning content for preview: %s",
                _format_audit_failure_message(audit),
            )
            audit_blocked = True

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
        notes=notes_md,
    )

    return V2BidPackage(
        commercial_markdown=commercial_md,
        technical_markdown=technical_md,
        pricing_markdown=pricing_md,
        combined_markdown=combined,
        missing_checklist=missing,
        audit_result=audit,
        format_docx_path=built_format_docx,
        appendix_docx_path=built_appendix_docx,
        audit_blocked=audit_blocked,
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


# Tender format trees usually list 技术卷 only as a coarse form requirement
# ("一、施工组织设计 / 二、其他内容"). These are not a content outline — the
# 施工组织设计 is authored by the bidder. When the tree is this thin, expand to
# the canonical deep outline so the technical volume reaches winning-bid depth.
_GENERIC_TECH_TITLES = (
    "施工组织设计", "技术文件", "技术标", "技术方案", "其他内容", "其他材料", "正文",
)


def _collect_technical_sections(requirements: TenderRequirements) -> list[dict]:
    """LEGACY fallback for the technical目录 — only when no confirmed
    ``bid_outline_json`` drives generation (see ``_sections_from_confirmed_outline``).

    Honour the tender's own technical outline at whatever granularity it has
    (列几条就几条). When the tender specifies nothing usable, return a minimal
    neutral shell rather than imposing the detailed canonical outline — 招标各不
    相同，有的技术标目录就很简单，套统一模板反而画蛇添足/不响应。真正的结构由
    人工在大纲编辑器里按本招标定稿。
    """
    titles = _collect_technical_titles(requirements)
    specific = [
        t for t in titles
        if not any(g in t for g in _GENERIC_TECH_TITLES)
    ]
    if specific:
        # Tender provides its own technical outline — honor it as-is.
        return [{"title": t, "must_cover": "", "target_chars": 1500} for t in titles]
    # Nothing specified → minimal neutral shell, NOT a detailed template.
    return [{"title": "施工组织设计", "must_cover": "", "target_chars": 1500}]


# Default per-section length budget for a human-confirmed outline, matching the
# "specific tender outline" path in _collect_technical_sections.
_CONFIRMED_OUTLINE_TARGET_CHARS = 1500


def _sections_from_confirmed_outline(
    confirmed: list[dict] | None,
) -> list[dict] | None:
    """Map a human-confirmed technical outline into content-writer sections.

    ``confirmed`` is the project's ``bid_outline_json`` (a list of
    ``BidSectionOutline`` dicts: title / focus_points / …). When the bidder has
    confirmed a real outline we honour it verbatim — its titles become the
    technical目录 and its ``focus_points`` become each section's must-cover
    guidance — instead of falling back to the canonical hardcoded outline. This
    is the wire that makes "改大纲 → 改生成目录" actually true.

    Returns ``None`` (so the caller falls back to
    :func:`_collect_technical_sections`) when the outline is absent or too thin
    to drive a full technical volume, preserving existing behaviour for projects
    without a real confirmed outline.
    """
    if not confirmed:
        return None
    sections: list[dict] = []
    for item in confirmed:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        focus = item.get("focus_points") or []
        must_cover = "\n".join(str(p).strip() for p in focus if str(p).strip())
        sections.append(
            {
                "title": title,
                "must_cover": must_cover,
                "target_chars": int(item.get("target_chars", 0) or 0)
                or _CONFIRMED_OUTLINE_TARGET_CHARS,
            }
        )
    # Honour a human-confirmed outline at whatever size it is — a deliberately
    # simple 2-3 section目录 is valid (招标各不相同). Only fall back when empty.
    if not sections:
        return None
    return sections


def _strip_writer_top_level_headings(markdown: str) -> str:
    """Keep format-tree titles as the only top-level headings.

    Content writer calls are scoped to a single node, but models often echo
    ``#`` headings anyway. Remove only ``#`` (H1) headings and ``##`` headings
    that duplicate the node title — preserve meaningful sub-section ``##`` headings
    like "施工方法", "质量保证措施" etc.
    """
    lines = []
    first_heading_stripped = False
    for line in markdown.splitlines():
        # Always strip H1 (# ) — the volume heading is added by _assemble_markdown
        if re.match(r"^\s*#\s+", line) and not re.match(r"^\s*##\s+", line):
            continue
        # Strip only the FIRST ## heading (usually the node title echo),
        # keep all subsequent ## headings as valid sub-sections
        if re.match(r"^\s*##\s+", line) and not first_heading_stripped:
            first_heading_stripped = True
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
    critical = [i for i in audit.all_issues if i.severity == "critical"]
    details = "；".join(f"{i.location}: {i.problem}" for i in critical[:8])
    return "V2 生成失败：审查发现严重问题。" f"{details}"


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


def _enrich_commercial_markdown(
    commercial_md: str,
    requirements: TenderRequirements,
    profile: dict[str, str],
    tender_text: str = "",
    project_id: int | None = None,
) -> str:
    """Add compliance response sections to commercial volume in original format mode.

    When the format pages come from the original DOCX, the markdown preview
    would only show a header. This function appends deterministic compliance
    text derived from the parsed requirements so the preview is informative.
    """
    # Only enrich if the markdown is just a header (original format mode)
    lines = commercial_md.splitlines()
    non_empty = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    if non_empty:
        return commercial_md  # Already has content from form filling

    parts = [commercial_md.rstrip()]

    # 商务通读整本招标 → LLM 生成四块商务响应(资格响应/偏离表/声明承诺/投标函一致性)。
    # best-effort:无招标全文或 LLM 失败返回 "",回退到下方模板化资格响应要点(原行为)。
    llm_response_md = ""
    try:
        from services.commercial_response_service import generate_commercial_responses

        llm_response_md = generate_commercial_responses(requirements, tender_text, profile)
    except Exception:
        llm_response_md = ""

    if llm_response_md:
        parts.append(llm_response_md)
    elif requirements.qualification_list:
        # 回退:LLM 不可用(无招标全文/失败)时,仍给出模板化资格响应要点
        parts.append("\n<!-- tdg:pagebreak -->\n")
        parts.append(
            "\n## 附录：商务响应补充说明（系统自动生成，供编制参考；非招标文件格式原文）\n"
        )
        parts.append(
            "\n> 正式商务表格以上方原格式页为准；以下仅为依据招标文件解析自动生成的资格响应要点。\n"
        )
        for item in requirements.qualification_list:
            parts.append(f"\n### {item.title}\n")
            parts.append(f"\n{item.description}\n")
            # Try to match with profile data
            profile_value = _match_profile_field(item.title, profile)
            if profile_value:
                parts.append(f"\n**响应：** {profile_value}\n")

    # 资格符合性 + 投标函三处一致性 硬校验(确定性核对引擎,达标/废标级)。best-effort,
    # 与上方 LLM 软响应并列:软响应给"怎么写",硬校验给"达标没/有没有废标级"。
    if project_id is not None:
        try:
            from services.tender_spec_service import build_conformance_hardcheck_markdown

            hardcheck_md = build_conformance_hardcheck_markdown(project_id)
        except Exception:
            hardcheck_md = ""
        if hardcheck_md:
            parts.append(hardcheck_md)

    # Bid bond section
    parts.append("\n<!-- tdg:pagebreak -->\n")
    parts.append("\n## 投标保证金\n")
    bond_info = []
    if profile.get("bid_bond_amount"):
        bond_info.append(f"金额：{profile['bid_bond_amount']}")
    if requirements.bid_deadline:
        bond_info.append(f"有效期至：{requirements.bid_deadline}")
    if bond_info:
        parts.append(f"\n{'，'.join(bond_info)}。\n")
    else:
        parts.append(
            "\n投标保证金按招标文件要求提交，具体金额、方式和有效期详见投标保证金保函/凭证。\n"
        )

    # Project manager section
    parts.append("\n<!-- tdg:pagebreak -->\n")
    parts.append("\n## 项目管理机构\n")
    pm_fields = []
    # CompanyProfile 的字段名是 project_manager_name / project_manager_cert
    # (旧代码取 project_manager / pm_certificate,schema 里不存在 → 恒空)。
    # 保留旧键名作 fallback,避免对可能传入旧键的调用方回归。
    pm_name = profile.get("project_manager_name") or profile.get("project_manager")
    if pm_name:
        pm_fields.append(f"项目经理：{pm_name}")
    pm_cert = profile.get("project_manager_cert") or profile.get("pm_certificate")
    if pm_cert:
        pm_fields.append(f"注册建造师证书：{pm_cert}")
    if profile.get("pm_specialty"):
        pm_fields.append(f"专业：{profile['pm_specialty']}")
    if pm_fields:
        parts.append(f"\n{'，'.join(pm_fields)}。承诺在本项目实施期间在岗，不在其他项目兼职。\n")
    else:
        parts.append(
            "\n拟派项目经理具备相应专业注册建造师证书，在岗承诺详见附件。"
            "安全生产许可证有效且覆盖本项目施工活动。\n"
        )

    # 资格证明材料:从知识库自动插入营业执照/资质/安许/业绩等图片(B)
    evidence_md = _qualification_evidence_markdown()
    if evidence_md:
        parts.append(evidence_md)

    # 法人身份证复印件(正反)→ 法定代表人身份证明 后(招标P120;法人亲签,不附代理人)
    legal_rep = str(
        profile.get("legal_representative") or profile.get("法定代表人") or ""
    ).strip()
    legal_id_md = _legal_rep_id_evidence_markdown(legal_rep)
    if legal_id_md:
        parts.append(legal_id_md)

    # 类似业绩 + 主要人员:从知识库台账/人员证书自动汇总成表(C1,附加参考,不动原表)
    kb_tables_md = _kb_qualification_tables_markdown()
    if kb_tables_md:
        parts.append(kb_tables_md)

    # A3:类似业绩证明链——每个业绩附 中标通知书+合同+交工验收 扫描(import_performance_evidence)
    perf_evidence_md = _performance_evidence_markdown()
    if perf_evidence_md:
        parts.append(perf_evidence_md)

    return "\n".join(parts)


_NAME_NOISE_TOKENS = (
    "证书", "工程", "公路", "养护", "专管", "劳资", "微信", "图片", "年度",
    "施工员", "材料员", "质量员", "资料员", "机械员", "照片", "人员",
)


def _kb_qualification_tables_markdown() -> str:
    """C1:把知识库的业绩台账/主要人员汇总成 markdown 表,作为资格响应附录的参考。

    纯附加内容(不填招标原表),无数据则返回空。
    """
    try:
        from services.knowledge_service import (
            list_key_personnel,
            list_performance_records,
        )
    except Exception:
        return ""

    parts: list[str] = []

    try:
        records = list_performance_records(limit=15)
    except Exception:
        records = []
    if records:
        lines = [
            "",
            "### 近年承建业绩（系统自知识库汇总，请按招标类似业绩要求筛选）",
            "",
            "| 项目名称 | 中标金额 | 年份 | 类型 |",
            "| --- | --- | --- | --- |",
        ]
        for record in records:
            name = (record["name"] or "—").replace("|", "/")[:40]
            lines.append(
                f"| {name} | {record['amount'] or '—'} | "
                f"{record['year'] or '—'} | {record['type'] or '—'} |"
            )
        parts.append("\n".join(lines))

    try:
        personnel = list_key_personnel(limit=40)
    except Exception:
        personnel = []
    personnel = [
        person
        for person in personnel
        if person["name"]
        and 2 <= len(person["name"]) <= 4
        and not any(token in person["name"] for token in _NAME_NOISE_TOKENS)
    ]
    if personnel:
        lines = [
            "",
            "### 主要注册人员（系统自知识库汇总，供编制参考）",
            "",
            "| 姓名 | 持有证书 |",
            "| --- | --- |",
        ]
        for person in personnel[:30]:
            lines.append(f"| {person['name']} | {person['certs'].replace('|', '/')} |")
        parts.append("\n".join(lines))

    if not parts:
        return ""
    return (
        "\n<!-- tdg:pagebreak -->\n"
        "\n## 附录：类似业绩与主要人员（系统按知识库自动汇总，供编制参考）\n"
        + "\n".join(parts)
        + "\n"
    )


def _inject_project_images(technical_md: str, project_id: int | None) -> str:
    """② 本项目定制插入图(航拍图/本项目图纸):按 ``target_section`` 把项目图片插到技术卷
    对应节末尾;未指定或未匹配到节的统一收到末尾"本项目附图"。靠现成 ``{{knowledge_image}}``
    渲染器插入(下游 _render_markdown_body 从 MinIO 取图)。
    """
    if not project_id or not technical_md.strip():
        return technical_md
    try:
        from services.knowledge_service import list_project_insert_images

        images = list_project_insert_images(project_id)
    except Exception:
        return technical_md
    if not images:
        return technical_md

    def _marker(image: dict) -> str:
        caption = str(image.get("caption") or "").replace('"', "")
        return (
            f'\n\n{{{{knowledge_image:document_id={image["document_id"]} '
            f'caption="{caption}" width_cm=14}}}}\n'
        )

    used: set[int] = set()
    parts = re.split(r"(?m)^(##\s.+)$", technical_md)
    rebuilt = [parts[0]]
    idx = 1
    while idx < len(parts):
        heading = parts[idx]
        body = parts[idx + 1] if idx + 1 < len(parts) else ""
        title = heading.lstrip("#").strip()
        block = heading + body
        for image in images:
            target = str(image.get("target_section") or "").strip()
            doc_id = image["document_id"]
            if target and doc_id not in used and (target in title or title in target):
                block += _marker(image)
                used.add(doc_id)
        rebuilt.append(block)
        idx += 2
    result = "".join(rebuilt)

    leftover = [img for img in images if img["document_id"] not in used]
    if leftover:
        result = result.rstrip() + "\n\n## 本项目附图\n"
        for image in leftover:
            result += _marker(image)
    return result


# A2 资格证明材料分组:按真实标书"资格审查"结构成组插**全**公司证件(不止 4 类各 1 张)。
# (组标题, 该组证件类型, 该组最多插几张)。过期证件已在 list_knowledge_image_references 滤掉。
# (组标题, 证件类型, 组上限, 落位锚点)。anchor=招标要求该组插在哪张表后:营业执照/资质/安许/
# 开户/体系→投标人基本情况表后(须知3.5.1);荣誉与信誉→信誉情况表后(3.5.4)。空 anchor=卷尾。
_EVIDENCE_GROUPS: tuple[tuple[str, tuple[str, ...], int, str], ...] = (
    ("营业执照", ("营业执照",), 2, "基本情况表"),
    ("企业资质证书", ("资质证书", "施工劳务资质证书"), 16, "基本情况表"),
    ("安全生产许可证", ("安全生产许可证",), 2, "基本情况表"),
    ("基本账户开户许可证", ("开户许可证",), 2, "基本情况表"),
    ("管理体系认证证书", ("体系证书",), 10, "基本情况表"),
    ("企业荣誉与信誉证明", ("荣誉证书", "信用证书"), 20, "信誉情况表"),
    ("专利与工法证书", ("专利证书", "工法证书"), 15, "基本情况表"),
)


def _qualification_evidence_markdown(limit: int = 80) -> str:
    """生成资格证明材料的图片标记(A2:成组插全公司证件)。

    从知识库按"公司证件 + 确切证件类型"精确选图(不靠模糊评分,免把人员建安证误当公司安许),
    按 _EVIDENCE_GROUPS 分组、每组插全(到组上限),产出 {{knowledge_image:...}} 标记;渲染时
    image_resolver 从 MinIO 取图插入。无匹配返回空,不留死占位。limit=全局张数上限(防失控)。
    """
    try:
        from services.knowledge_service import list_knowledge_image_references

        refs = list_knowledge_image_references("", limit=5000)
    except Exception:
        return ""

    by_type: dict[str, list[dict]] = {}
    for ref in refs:
        if str(ref.get("document_category")) != "公司证件":
            continue
        cert_type = str(ref.get("certificate_type") or "")
        if cert_type:
            by_type.setdefault(cert_type, []).append(ref)  # refs 已 created_at DESC

    blocks: list[str] = []
    seen: set[int] = set()
    for title, cert_types, group_cap, anchor in _EVIDENCE_GROUPS:
        group_refs: list[dict] = []
        for cert_type in cert_types:
            group_refs.extend(by_type.get(cert_type, []))
        emitted: list[str] = []
        for ref in group_refs:
            if len(emitted) >= group_cap or len(seen) >= limit:
                break
            doc_id = int(ref.get("document_id", 0) or 0)
            if doc_id <= 0 or doc_id in seen:
                continue
            seen.add(doc_id)
            specialty = str(ref.get("specialty") or "").strip().replace('"', "")
            if specialty and specialty not in title:
                caption = f"{title}（{specialty}）"
            elif group_cap > 1:
                caption = f"{title}（{len(emitted) + 1}）"
            else:
                caption = title
            emitted.append(
                f'\n{{{{knowledge_image:document_id={doc_id} '
                f'anchor="{anchor}" caption="{caption}" width_cm=14}}}}\n'
            )
        if emitted:
            blocks.append(f"\n### {title}\n")
            blocks.extend(emitted)
        if len(seen) >= limit:
            break

    if not blocks:
        return ""
    return (
        "\n<!-- tdg:pagebreak -->\n"
        "\n## 附录：资格证明材料（系统按知识库自动插入，请人工核验/补充）\n"
        + "".join(blocks)
    )


def _legal_rep_pii(legal_rep_name: str) -> dict[str, str]:
    """从法人身份证 OCR 取身份证号,推导 法人性别/法人年龄/法人出生。无则返回 {}。

    填法定代表人身份证明表的 性别/年龄 栏(职务无据可填、留人工)。身份证号第17位奇男偶女、
    7-14位为出生 YYYYMMDD。仅推导、不外泄到正文之外。
    """
    import datetime

    name = (legal_rep_name or "").strip()
    if not name:
        return {}
    try:
        from rag.vector_store import _connect

        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT kc.content FROM knowledge_chunks kc "
                "JOIN documents d ON kc.document_id = d.id "
                "WHERE d.metadata_json->>'owner_name' = %s "
                "AND d.metadata_json->>'certificate_type' LIKE %s LIMIT 30",
                (name, "%身份证%"),
            )
            rows = cur.fetchall()
    except Exception:
        return {}
    today = datetime.date.today()
    for (content,) in rows:
        m = re.search(
            r"(?<![\dXx])(\d{6})(\d{4})(\d{2})(\d{2})(\d{2})(\d)([\dXx])(?![\dXx])",
            content or "",
        )
        if not m:
            continue
        try:
            y, mo, da = int(m.group(2)), int(m.group(3)), int(m.group(4))
            if not (1900 < y <= today.year and 1 <= mo <= 12 and 1 <= da <= 31):
                continue
            gender = "男" if int(m.group(6)) % 2 == 1 else "女"
            age = today.year - y - ((today.month, today.day) < (mo, da))
            return {
                "法人性别": gender,
                "法人年龄": str(age),
                "法人出生": f"{y:04d}-{mo:02d}-{da:02d}",
                "法人身份证号": "".join(m.groups()),
            }
        except (ValueError, IndexError):
            continue
    return {}


def _legal_rep_id_evidence_markdown(legal_rep_name: str) -> str:
    """法人身份证复印件(正反)→ 法定代表人身份证明 后(招标 P120 硬要求)。

    法人亲签路线:只附法定代表人本人身份证(不附委托代理人,本项目未指定代理人)。
    按 owner_name=法人 + 证件类型含'身份证'精确取,正反取前2张,无则返回空。
    """
    name = (legal_rep_name or "").strip()
    if not name:
        return ""
    try:
        from services.knowledge_service import list_knowledge_image_references

        refs = list_knowledge_image_references("", limit=5000)
    except Exception:
        return ""
    cards = [
        r
        for r in refs
        if str(r.get("owner_name") or "").strip() == name
        and "身份证" in str(r.get("certificate_type") or "")
        and str(r.get("image_insertable")) not in ("False", "false", "0", "None")
    ]
    blocks: list[str] = []
    for i, r in enumerate(cards[:2], 1):
        doc_id = int(r.get("document_id", 0) or 0)
        if doc_id <= 0:
            continue
        cap = f"法定代表人（{name}）身份证" + (f"（{i}）" if len(cards) > 1 else "")
        blocks.append(
            f'\n{{{{knowledge_image:document_id={doc_id} '
            f'anchor="法定代表人身份证明" caption="{cap}" width_cm=12}}}}\n'
        )
    if not blocks:
        return ""
    return (
        "\n<!-- tdg:pagebreak -->\n"
        "\n## 附录：法定代表人身份证明材料（系统自动插入，请人工核验）\n"
        + "".join(blocks)
    )


# A3b 业绩证明链:每个类似业绩附 中标通知书 + 合同 + 交工验收 扫描(import_performance_evidence
# 已入库,document_category=业绩证明、metadata 带 performance_project/evidence_type/evidence_seq)。
_PERF_EVIDENCE_ORDER = ("中标通知书", "合同", "交工验收")
_PERF_PER_TYPE_CAP = {"中标通知书": 2, "合同": 2, "交工验收": 4}


def _build_performance_evidence_md(
    rows: list[tuple], limit_projects: int = 6
) -> str:
    """纯函数:业绩证明行 [(doc_id, 项目, 类型, 年, 序号)] → 按项目成组的插图 markdown。

    选片规则:有完整链(中标+交工)优先,再按年份新→旧取前 limit_projects 个项目;每个项目
    每类按序号取前几张(中标2/合同2/交工4)。
    """
    projects: dict[str, dict] = {}
    for doc_id, proj, etype, year, seq in rows:
        if not proj or not etype:
            continue
        try:
            doc_id = int(doc_id)
        except (TypeError, ValueError):
            continue
        bucket = projects.setdefault(proj, {"year": 0, "by_type": {}})
        try:
            bucket["year"] = max(bucket["year"], int(year or 0))
        except (TypeError, ValueError):
            pass
        try:
            seq_i = int(seq) if seq is not None else 0
        except (TypeError, ValueError):
            seq_i = 0
        bucket["by_type"].setdefault(etype, []).append((seq_i, doc_id))

    def has_chain(bucket: dict) -> bool:
        return {"中标通知书", "交工验收"} <= set(bucket["by_type"])

    ordered = sorted(
        projects.items(),
        key=lambda kv: (has_chain(kv[1]), kv[1]["year"]),
        reverse=True,
    )
    blocks: list[str] = []
    for i, (proj, bucket) in enumerate(ordered[:limit_projects], 1):
        title = str(proj).replace('"', "")[:48]
        seg = [f"\n### 类似业绩 {i}：{title}\n"]
        any_img = False
        for etype in _PERF_EVIDENCE_ORDER:
            imgs = sorted(bucket["by_type"].get(etype, []))[: _PERF_PER_TYPE_CAP[etype]]
            for j, (_seq, doc_id) in enumerate(imgs, 1):
                cap = f"{title}-{etype}" + (f"（{j}）" if len(imgs) > 1 else "")
                seg.append(
                    f'\n{{{{knowledge_image:document_id={doc_id} '
                    f'anchor="类似项目情况表" caption="{cap}" width_cm=14}}}}\n'
                )
                any_img = True
        if any_img:
            blocks.append("".join(seg))

    if not blocks:
        return ""
    return (
        "\n<!-- tdg:pagebreak -->\n"
        "\n## 附录：类似业绩证明材料（中标通知书·合同·交工验收，系统自动插入，请人工核验筛选）\n"
        + "".join(blocks)
    )


def _performance_evidence_markdown(limit_projects: int = 6) -> str:
    """A3b:从知识库取业绩证明扫描,按项目成组插中标通知书/合同/交工验收。无数据返回空。"""
    try:
        from rag.vector_store import get_db_connection

        with get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, metadata_json->>'performance_project', "
                "metadata_json->>'evidence_type', metadata_json->>'project_year', "
                "metadata_json->>'evidence_seq' FROM documents "
                "WHERE project_id IS NULL "
                "AND metadata_json->>'document_category' = '业绩证明' "
                "AND coalesce(metadata_json->>'image_insertable', '') <> 'false'"
            )
            rows = cursor.fetchall()
    except Exception:
        return ""
    return _build_performance_evidence_md(list(rows), limit_projects)


def _match_profile_field(title: str, profile: dict[str, str]) -> str:
    """Try to find a matching profile value for a requirement title."""
    title_lower = title.lower()
    # CompanyProfile 真实字段名放首位(qualification_grade / safety_license_no /
    # credit_code),旧的不存在键名保留作 fallback,避免改动破坏其它传入路径。
    mapping = {
        "资质": ["qualification_grade", "qualification_level", "qualification", "资质等级"],
        "营业执照": ["credit_code", "business_license", "license", "营业执照号"],
        "安全生产": ["safety_license_no", "safety_license", "safety_production_license", "安全生产许可证"],
        "财务": ["financial", "财务状况"],
        "业绩": ["performance", "业绩"],
        "信誉": ["credit", "信誉"],
    }
    for keyword, keys in mapping.items():
        if keyword in title_lower:
            for key in keys:
                val = profile.get(key, "")
                if val:
                    return val
    return ""


def _build_audit_notes(requirements: TenderRequirements) -> str:
    """Build the notes volume with audit correction items from requirements.

    This generates the 审查修正说明 section with compliance responses
    derived from the parsed invalid_bid_items, qualification requirements,
    and other compliance fields.
    """
    parts = ["## 审查修正说明\n"]

    # Individual compliance items from requirements fields
    compliance_items: list[tuple[str, str]] = []

    # Project manager certificate
    if any("项目经理" in (item.title + item.description) for item in requirements.qualification_list):
        compliance_items.append((
            "project_manager_certificate",
            "在项目管理机构或人员配置章节明确项目经理注册建造师证书、专业、有效期和在岗承诺。",
        ))

    # Safety production license
    if any("安全" in (item.title + item.description) for item in requirements.qualification_list):
        compliance_items.append((
            "safety_production_license",
            "在资格响应或安全文明施工章节写明安全生产许可证有效、覆盖本项目施工活动。",
        ))

    # Bid bond
    compliance_items.append((
        "bid_bond",
        "补充投标保证金或保函提交方式、金额、有效期和到账/开具时间响应。",
    ))

    # Qualification level
    if requirements.qualification_list:
        compliance_items.append((
            "qualification_level",
            "在资格响应章节明确企业施工资质等级，并与招标文件要求保持一致。",
        ))

    # Schedule response
    if requirements.planned_duration:
        compliance_items.append((
            "schedule_response",
            "在进度计划章节补充总工期、关键节点、资源投入和延期风险控制措施。",
        ))

    # Quality response
    if requirements.quality_standard:
        compliance_items.append((
            "quality_response",
            "在质量保证章节补充质量目标、三检制、隐蔽工程验收和资料归档措施。",
        ))

    # Invalid bid items
    for idx, item in enumerate(requirements.invalid_bid_items, start=1):
        compliance_items.append((
            f"invalid_bid_item_{idx}",
            item.description or item.title,
        ))

    # Render
    for key, desc in compliance_items:
        parts.append(f"\n-针对 `{key}`：{desc}\n")

    return "\n".join(parts)


_COMMERCIAL_SECTION_KEYWORDS = (
    "资格响应",
    "投标保证金",
    "项目管理机构",
    "资格审查",
    "投标函",
    "诚信投标",
    "法定代表人",
    "授权委托",
)


def _canonical_tech_titles() -> set[str]:
    from prompts.construction_plan_outline import CONSTRUCTION_PLAN_OUTLINE

    return {re.sub(r"\s+", "", str(s["title"])) for s in CONSTRUCTION_PLAN_OUTLINE}


def _strip_commercial_sections(technical_md: str) -> str:
    """Remove commercial compliance sections that the LLM may have
    over-generated into the technical volume.

    In original format mode, commercial content (资格响应, 投标保证金,
    项目管理机构 etc.) belongs in the commercial volume, not the
    technical one. The LLM sometimes "helpfully" generates these in
    the construction plan output — strip them here.

    A canonical technical section title is never stripped, so e.g.
    "项目管理机构与岗位职责" (a legit 施工组织设计 section) is not removed by
    the "项目管理机构" commercial keyword.
    """
    tech_titles = _canonical_tech_titles()
    lines = technical_md.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        # Check if this line starts a ## heading that matches a commercial section
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            is_canonical_tech = re.sub(r"\s+", "", heading) in tech_titles
            if not is_canonical_tech and any(
                kw in heading for kw in _COMMERCIAL_SECTION_KEYWORDS
            ):
                skipping = True
                continue
            else:
                skipping = False
        elif stripped.startswith("# ") and not stripped.startswith("## "):
            # H1 heading — stop skipping
            skipping = False
        if not skipping:
            kept.append(line)
    return "\n".join(kept)
