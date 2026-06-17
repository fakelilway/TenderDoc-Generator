from __future__ import annotations

import re
from typing import Any

from schemas.tender import TenderRequirements


VOLUME_LABELS = {
    "commercial": "商务文件",
    "technical": "技术文件",
    "pricing": "报价文件",
}

VOLUME_ORDER = ("commercial", "technical", "pricing")


# ── 共用助手(格式页提取与卷归类共用) ───────────────────────────────────────


def _node_title(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("title") or "").strip()
    return str(getattr(node, "title", "") or "").strip()


def _node_children(node: Any) -> list[Any]:
    if isinstance(node, dict):
        children = node.get("children") or []
    else:
        children = getattr(node, "children", []) or []
    return children if isinstance(children, list) else []


def _canonical_title(text: str) -> str:
    value = re.sub(r"\s+", "", text or "")
    value = re.sub(r"^[#\-*●•·]+", "", value)
    value = re.sub(r"^第[一二三四五六七八九十百千万\d]+[章节条部分卷信封]+[、.．]?", "", value)
    value = re.sub(r"^[一二三四五六七八九十百千万\d]+[、.．]", "", value)
    value = re.sub(r"^[（(][一二三四五六七八九十百千万\d]+[）)]", "", value)
    return value.strip("：:；;。")


# ── V2-M1: 格式页提取器(从招标格式章抽出每个表单/表格页,供 v2 生成复制原格式) ──


class FormatPage:
    """One page/form/section from the format chapter."""
    title: str
    raw_template: str
    page_type: str  # letter_template | table_template | prose_section | free_material
    volume: str     # commercial | technical | pricing
    children: list[FormatPage]

    def __init__(self, title: str, raw: str = "", ptype: str = "free_material",
                 volume: str = "commercial", children: list[FormatPage] | None = None):
        self.title = title
        self.raw_template = raw
        self.page_type = ptype
        self.volume = volume
        self.children = children or []


def extract_format_pages(tender_text: str) -> dict[str, list[FormatPage]]:
    """Extract actual form template pages from the tender's format chapter.

    Uses format_outline_tree for accurate volume classification, then overlays
    raw template text extracted from the format chapter.
    """
    chapter_text = _locate_format_chapter(tender_text)
    if not chapter_text:
        return {"commercial": [], "technical": [], "pricing": []}

    # Extract all raw pages from the chapter
    all_pages = _extract_section_pages(chapter_text, "commercial")

    # Return as flat list initially — volume assignment happens later
    # when we cross-reference with format_outline_tree
    return {"commercial": all_pages, "technical": [], "pricing": []}


def assign_page_volumes(
    pages: list[FormatPage],
    requirements: TenderRequirements,
) -> dict[str, list[FormatPage]]:
    """Cross-reference extracted pages with format_outline_tree to assign volumes."""
    result = {"commercial": [], "technical": [], "pricing": []}

    # Build a set of known node titles per volume from format_outline_tree
    volume_titles: dict[str, set[str]] = {"commercial": set(), "technical": set(), "pricing": set()}

    def collect_titles(nodes: list, volume: str):
        for n in nodes:
            t = _node_title(n)
            if t:
                # Normalize: remove numbering prefixes for matching
                key = re.sub(r'^[一二三四五六七八九十]+[、.．]?\s*', '', t)
                volume_titles[volume].add(t)
                volume_titles[volume].add(key)
            ch = _node_children(n)
            if ch:
                collect_titles(ch, volume)

    for vol in ("commercial", "technical", "pricing"):
        collect_titles(requirements.format_outline_tree.get(vol, []), vol)

    for page in pages:
        title_clean = re.sub(r'^[一二三四五六七八九十]+[、.．]?\s*', '', page.title)
        assigned = False
        for vol in ("commercial", "technical", "pricing"):
            if page.title in volume_titles[vol] or title_clean in volume_titles[vol]:
                page.volume = vol
                result[vol].append(page)
                assigned = True
                break
        if not assigned:
            # Best guess: check title content
            if any(kw in page.title for kw in ['施工', '技术', '方案', '进度', '质量', '安全']):
                result["technical"].append(page)
            elif any(kw in page.title for kw in ['报价', '清单', '投标总价', '经济']):
                result["pricing"].append(page)
            else:
                result["commercial"].append(page)

    return result


def _locate_format_chapter(text: str) -> str:
    """Find the format chapter body, bypassing TOC phantom content.

    PDF text extraction often places TOC entries far from actual chapter bodies.
    We find the chapter heading, then scan forward for actual form content markers
    (投标函 templates, volume headers, blank fields).
    """
    patterns = [
        r'第[一二三四五六七八九十百\d]+章\s*[投响]应?文件格式',
        r'第[一二三四五六七八九十百\d]+章\s*响应文件格式',
        r'第[一二三四五六七八九十百\d]+章\s*投标文件格式',
    ]

    # Find ALL matches — there may be TOC entries and actual chapter bodies
    matches: list[tuple[int, str]] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            matches.append((m.start(), m.group()))
    matches.sort(key=lambda x: x[0])

    if not matches:
        return ""

    # Use the LAST match as the actual chapter body (furthest in document)
    chapter_start = matches[-1][0]

    # Scan forward for actual form content
    body_start = _find_chapter_body(text, chapter_start)
    if body_start < chapter_start:
        body_start = chapter_start

    # Find the end: next chapter OR end of useful content
    next_ch = re.search(
        r'第[一二三四五六七八九十百\d]+章\s+(?!投[标响]应?文件格式)(?!响应文件格式)',
        text[body_start + 10:]
    )
    end = body_start + 10 + (next_ch.start() if next_ch else min(50000, len(text) - body_start))

    return text[body_start:end]


def _find_chapter_body(text: str, chapter_start: int) -> int:
    """Skip past table-of-contents entries to find actual form content."""
    # Look for volume markers: first envelope, second envelope, or 投标文件（
    key_markers = [
        r'第一信封', r'第二信封',
        r'投标文件[（(]商务文件[）)]', r'投标文件[（(]技术文件[）)]',
        r'投标文件[（(]报价文件[）)]',
        r'一、投标函', r'一、磋商响应函',
        r'商务文件', r'技术文件', r'报价文件',
    ]
    for marker_pat in key_markers:
        m = re.search(marker_pat, text[chapter_start:chapter_start + 15000])
        if m:
            # Found actual format content — walk back to find section start
            pos = chapter_start + m.start()
            # Walk back past blank lines to get clean start
            back = pos
            while back > chapter_start and text[back - 1] in '\n\r ':
                back -= 1
            return max(chapter_start, back)
    return chapter_start + 10


def _extract_section_pages(text: str, default_volume: str) -> list[FormatPage]:
    """Extract individual form/section pages from volume text."""
    # Strip PDF page numbers — standalone 1-3 digit numbers on their own line
    text = re.sub(r'(?:^|\n)\s*\d{1,3}\s*(?:\n|$)', '\n', text)

    pages: list[FormatPage] = []

    # Split by Chinese numbered headings (一、二、三、...)
    section_pattern = re.compile(r'(?:^|\n)\s*([一二三四五六七八九十]+)[、.．]\s*(.+?)(?=\n|$)')

    sections = [
        match for match in section_pattern.finditer(text)
        if _is_top_level_format_heading(match.group(2).strip())
    ]
    if not sections:
        return pages

    for i, m in enumerate(sections):
        title = f"{m.group(1)}、{m.group(2).strip()}"
        start = m.end()
        end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        raw = text[start:end].strip()

        # Determine page type
        ptype = _classify_page_type(title, raw)

        page = FormatPage(
            title=title,
            raw=raw,
            ptype=ptype,
            volume=default_volume,
        )

        # Extract sub-sections if present
        if ptype in ("letter_template", "prose_section"):
            sub_pattern = re.compile(r'(?:^|\n)\s*[（(][一二三四五六七八九十]+[）)]\s*(.+?)(?:\n|$)')
            for sm in sub_pattern.finditer(raw):
                sub_title = f"（{sm.group(0).strip().lstrip('（(').rstrip('）)')}）{sm.group(1).strip()}"[:60]
                page.children.append(FormatPage(
                    title=sub_title[:60],
                    raw="",
                    ptype=ptype,
                    volume=default_volume,
                ))

        pages.append(page)

    return _dedupe_format_pages(pages)


def _dedupe_format_pages(pages: list[FormatPage]) -> list[FormatPage]:
    """Drop TOC phantom nodes and keep the substantive page for duplicate titles."""
    best_by_title: dict[str, tuple[int, int, FormatPage]] = {}
    order: list[str] = []
    for index, page in enumerate(pages):
        key = _canonical_title(page.title)
        if not key or key == "目录":
            continue
        score = _format_page_score(page)
        if key not in best_by_title:
            best_by_title[key] = (score, index, page)
            order.append(key)
            continue
        old_score, old_index, _old_page = best_by_title[key]
        if score > old_score or (score == old_score and index > old_index):
            best_by_title[key] = (score, index, page)
    return [best_by_title[key][2] for key in order if key in best_by_title]


def _is_top_level_format_heading(title_body: str) -> bool:
    title = (title_body or "").strip()
    if not title:
        return False
    if len(title) > 36:
        return False
    if any(mark in title for mark in ("，", "。", "；", "：", ":", "、")):
        return False
    if title.startswith(("如采用", "如果", "按照", "发生")):
        return False
    return True


def _format_page_score(page: FormatPage) -> int:
    raw = page.raw_template or ""
    score = len(raw)
    if any(marker in raw for marker in ("致：", "投 标 人", "（盖单位章）", "（签字", "身份证", "开户", "承诺")):
        score += 500
    if any(marker in raw for marker in ("表", "清单", "序号", "备注", "项目", "内容")):
        score += 200
    if len(raw) < 30:
        score -= 500
    return score


def _classify_page_type(title: str, raw: str) -> str:
    """Classify a format page as letter, table, prose, or free."""
    # Letters/forms
    letter_keywords = ['投标函', '承诺', '声明', '授权', '法定代表人', '委托', '联合体']
    for kw in letter_keywords:
        if kw in title or kw in raw:
            return "letter_template"

    # Tables
    table_indicators = ['|', '表格', '基本情况表', '汇总表', '附表', '清单', '情况表', '组成表']
    if any(kw in title or kw in raw[:500] for kw in table_indicators):
        return "table_template"
    if raw.count('\n') > 10 and raw.count('｜') + raw.count('|') > 2:
        return "table_template"

    # Prose/construction plan
    if any(kw in title for kw in ['施工', '方案', '措施', '部署', '计划', '进度']):
        return "prose_section"

    if '说明' in title or '编制' in title:
        return "prose_section"

    return "free_material"
