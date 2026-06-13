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


def has_format_skeleton(requirements: TenderRequirements) -> bool:
    """Return True when parser produced at least one usable volume tree."""
    return any(_volume_nodes(requirements, volume) for volume in VOLUME_ORDER)


def render_all_volume_skeletons(
    requirements: TenderRequirements,
    *,
    company_name: str = "",
    tender_text: str = "",
) -> dict[str, str]:
    """Render deterministic Markdown skeletons for all delivery volumes."""
    template_blocks = extract_format_template_blocks(requirements, tender_text)
    return {
        volume: render_volume_skeleton(
            requirements,
            volume=volume,
            company_name=company_name,
            tender_text=tender_text,
            template_blocks=template_blocks,
        )
        for volume in VOLUME_ORDER
    }


def render_volume_skeleton(
    requirements: TenderRequirements,
    *,
    volume: str,
    company_name: str = "",
    tender_text: str = "",
    template_blocks: dict[str, str] | None = None,
) -> str:
    """Render one volume's Markdown skeleton from the tender format tree.

    The skeleton is not a style template. It is the contract extracted from the
    current tender file: headings, order, and nesting. Writers may fill the
    blanks below the headings, but must not change the skeleton headings.
    """
    label = VOLUME_LABELS.get(volume, volume)
    project_name = requirements.project_name or "投标项目"
    template_blocks = template_blocks or extract_format_template_blocks(
        requirements, tender_text
    )
    lines = [f"# {project_name} {label}", ""]
    roots = _volume_nodes(requirements, volume)
    if not roots:
        lines.extend([_empty_volume_notice(label), ""])
        return "\n".join(lines).strip() + "\n"

    for node in roots:
        _render_node(
            lines,
            node,
            depth=2,
            volume=volume,
            requirements=requirements,
            company_name=company_name,
            template_blocks=template_blocks,
        )
    return "\n".join(lines).strip() + "\n"


def render_volume_node_list(requirements: TenderRequirements, volume: str) -> str:
    """Render one volume's format tree as an indented plain-text checklist."""
    roots = _volume_nodes(requirements, volume)
    if not roots:
        label = VOLUME_LABELS.get(volume, volume)
        return f"- 未提取到{label}格式树；按人工确认目录和格式要求生成。"
    lines: list[str] = []
    for node in roots:
        _render_list_node(lines, node, indent=0)
    return "\n".join(lines)


def expected_volume_titles(requirements: TenderRequirements, volume: str) -> list[str]:
    """Return the exact titles required for one volume, root container skipped."""
    titles: list[str] = []
    for node in _volume_nodes(requirements, volume):
        _collect_titles(titles, node)
    return titles


def extract_format_template_blocks(
    requirements: TenderRequirements,
    tender_text: str,
) -> dict[str, str]:
    """Extract original form/table blocks from the tender's format chapter."""
    format_text = _format_chapter_text(tender_text)
    if not format_text.strip():
        return {}

    lines = _clean_format_lines(format_text)
    if not lines:
        return {}

    entries = list(_iter_format_entries(requirements))
    matched: list[tuple[str, str, bool, int]] = []
    cursor = 0
    for volume, title, is_leaf in entries:
        index = _find_title_line(lines, title, start=cursor)
        if index == -1:
            continue
        matched.append((volume, title, is_leaf and not _is_generic_catchall(title), index))
        cursor = index + 1

    blocks: dict[str, str] = {}
    for pos, (volume, title, is_leaf, start) in enumerate(matched):
        if not is_leaf:
            continue
        end = len(lines)
        for _, _, _, next_start in matched[pos + 1 :]:
            if next_start > start:
                end = next_start
                break
        block = _format_template_block(lines[start:end])
        if block:
            blocks[_template_key(volume, title)] = block
    return blocks


def _volume_nodes(requirements: TenderRequirements, volume: str) -> list[Any]:
    nodes = requirements.format_outline_tree.get(volume, []) or []
    roots: list[Any] = []
    for node in nodes:
        title = _node_title(node)
        children = _node_children(node)
        if children and "投标文件" in title:
            roots.extend(children)
        elif title:
            roots.append(node)
    return roots


def _render_node(
    lines: list[str],
    node: Any,
    *,
    depth: int,
    volume: str,
    requirements: TenderRequirements,
    company_name: str,
    template_blocks: dict[str, str],
) -> None:
    title = _node_title(node)
    if not title:
        return
    lines.append(f"{'#' * min(depth, 6)} {title}")
    lines.append("")
    children = _node_children(node)
    if children:
        for child in children:
            _render_node(
                lines,
                child,
                depth=depth + 1,
                volume=volume,
                requirements=requirements,
                company_name=company_name,
                template_blocks=template_blocks,
            )
        return
    template_block = template_blocks.get(_template_key(volume, title), "")
    if template_block:
        lines.extend(template_block.splitlines())
    else:
        lines.extend(_leaf_placeholder(title, volume, requirements, company_name))
    lines.append("")


def _render_list_node(lines: list[str], node: Any, *, indent: int) -> None:
    title = _node_title(node)
    if not title:
        return
    lines.append(f"{'  ' * indent}- {title}")
    for child in _node_children(node):
        _render_list_node(lines, child, indent=indent + 1)


def _collect_titles(titles: list[str], node: Any) -> None:
    title = _node_title(node)
    if title:
        titles.append(title)
    for child in _node_children(node):
        _collect_titles(titles, child)


def _iter_format_entries(requirements: TenderRequirements) -> list[tuple[str, str, bool]]:
    entries: list[tuple[str, str, bool]] = []
    for volume in VOLUME_ORDER:
        for node in requirements.format_outline_tree.get(volume, []) or []:
            _collect_entries(entries, volume, node)
    return entries


def _collect_entries(
    entries: list[tuple[str, str, bool]],
    volume: str,
    node: Any,
) -> None:
    title = _node_title(node)
    if not title:
        return
    children = _node_children(node)
    entries.append((volume, title, not children))
    for child in children:
        _collect_entries(entries, volume, child)


def _format_chapter_text(tender_text: str) -> str:
    if not tender_text:
        return ""
    markers = (
        "投标文件格式",
        "投标文件组成",
        "投标文件的组成",
    )
    starts = [tender_text.rfind(marker) for marker in markers]
    start = max(starts)
    if start == -1:
        return tender_text
    return tender_text[start:]


def _clean_format_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"\d{1,4}", line):
            continue
        lines.append(line)
    return lines


def _find_title_line(lines: list[str], title: str, *, start: int) -> int:
    for index in range(max(start, 0), len(lines)):
        if _line_exact_title(lines[index], title) and not _is_probable_directory_hit(
            lines, index, title
        ):
            return index
    for index in range(max(start, 0), len(lines)):
        if _line_relaxed_title_match(
            lines[index], title
        ) and not _is_probable_directory_hit(lines, index, title):
            return index
    return -1


def _line_exact_title(line: str, title: str) -> bool:
    line_key = _canonical_title(line)
    title_key = _canonical_title(title)
    if not line_key or not title_key:
        return False
    return line_key == title_key


def _line_relaxed_title_match(line: str, title: str) -> bool:
    line_key = _canonical_title(line)
    title_key = _canonical_title(title)
    if not line_key or not title_key:
        return False
    if title_key in line_key:
        return len(line_key) <= len(title_key) + 18
    if line_key in title_key:
        return len(title_key) <= len(line_key) + 18
    return False


def _is_probable_directory_hit(lines: list[str], index: int, title: str) -> bool:
    if "投标文件" in title:
        return False
    if index + 1 >= len(lines):
        return False
    return bool(
        re.match(
            r"^([一二三四五六七八九十百千万\d]+[、.．]|[（(][一二三四五六七八九十百千万\d]+[）)])",
            lines[index + 1].strip(),
        )
    )


def _canonical_title(text: str) -> str:
    value = re.sub(r"\s+", "", text or "")
    value = re.sub(r"^[#\-*●•·]+", "", value)
    value = re.sub(r"^第[一二三四五六七八九十百千万\d]+[章节条部分卷信封]+[、.．]?", "", value)
    value = re.sub(r"^[一二三四五六七八九十百千万\d]+[、.．]", "", value)
    value = re.sub(r"^[（(][一二三四五六七八九十百千万\d]+[）)]", "", value)
    return value.strip("：:；;。")


def _format_template_block(lines: list[str]) -> str:
    compact = [line for line in lines if line.strip()]
    if not compact:
        return ""
    limited = compact[:80]
    return "\n".join(_replace_common_blanks(line) for line in limited).strip()


def _replace_common_blanks(line: str) -> str:
    line = re.sub(r"_{2,}", "________", line)
    line = re.sub(r"〔\s*〕", "〔________〕", line)
    return line


def _template_key(volume: str, title: str) -> str:
    return f"{volume}\0{_canonical_title(title)}"


def _is_generic_catchall(title: str) -> bool:
    key = _canonical_title(title)
    return key in {"其他", "其他内容", "其他材料", "其他资料"}


def _leaf_placeholder(
    title: str,
    volume: str,
    requirements: TenderRequirements,
    company_name: str,
) -> list[str]:
    normalized = title.replace(" ", "")
    if _looks_like_table(normalized):
        return [
            "| 项目 | 内容 | 备注 |",
            "| --- | --- | --- |",
            "| ________ | ________ | ________ |",
        ]
    if _looks_like_form(normalized):
        return [
            f"投标人：{company_name or '________'}",
            f"项目名称：{requirements.project_name or '________'}",
            f"招标人：{requirements.tenderer_name or '________'}",
            "内容：________",
            "",
            "法定代表人或其委托代理人：________（签字或盖章）",
            "日期：________年________月________日",
        ]
    if volume == "pricing":
        return ["详见已标价工程量清单。"]
    if volume == "technical":
        return ["本节按招标文件要求，结合项目实际施工部署编制。"]
    return ["________"]


def _looks_like_table(title: str) -> bool:
    return any(
        keyword in title
        for keyword in (
            "表",
            "清单",
            "汇总",
            "明细",
            "组成",
            "一览",
            "情况",
            "计划",
            "目录",
        )
    )


def _looks_like_form(title: str) -> bool:
    return any(
        keyword in title
        for keyword in (
            "投标函",
            "身份证明",
            "授权委托书",
            "承诺",
            "声明",
            "协议书",
            "保函",
            "保证金",
            "证明",
        )
    )


def _empty_volume_notice(label: str) -> str:
    return f"未提取到{label}格式目录。"


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


# ── V2-M1: Format Page Extractor ──────────────────────────────────────────


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


def _split_into_volumes(chapter_text: str) -> dict[str, list[FormatPage]]:
    """Split the format chapter into commercial/technical/pricing volumes."""
    volumes: dict[str, list[FormatPage]] = {
        "commercial": [], "technical": [], "pricing": []
    }

    # Identify volume boundaries
    volume_markers = [
        ("第一信封", "first_envelope"),
        ("第二信封", "second_envelope"),
        ("投标文件（商务文件）", "commercial"),
        ("投标文件（技术文件）", "technical"),
        ("投标文件（报价文件）", "pricing"),
        ("商务文件", "commercial"),
        ("技术文件", "technical"),
        ("报价文件", "pricing"),
        ("响应文件", "commercial"),  # 竞争性磋商通常是单卷
    ]

    # Find all volume boundaries
    boundaries: list[tuple[int, str]] = []
    for marker, vol in volume_markers:
        for m in re.finditer(re.escape(marker), chapter_text):
            boundaries.append((m.start(), vol))

    boundaries.sort(key=lambda x: x[0])

    if not boundaries:
        # No volume boundaries found — try to classify sections individually
        pages = _extract_section_pages(chapter_text, "commercial")
        volumes["commercial"] = pages
        return volumes

    # Split text by volume boundaries
    current_vol = "commercial"
    for i, (pos, vol) in enumerate(boundaries):
        next_pos = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(chapter_text)
        section_text = chapter_text[pos:next_pos]

        # Map envelope to volume
        if vol == "first_envelope":
            current_vol = "commercial"  # 商务+技术
        elif vol == "second_envelope":
            current_vol = "pricing"
        else:
            current_vol = vol

        pages = _extract_section_pages(section_text, current_vol)
        if current_vol == "commercial" and vol == "first_envelope":
            # Split first envelope into commercial and technical
            for page in pages:
                if "施工组织" in page.title or "技术" in page.title:
                    page.volume = "technical"
                    volumes["technical"].append(page)
                else:
                    volumes["commercial"].append(page)
        else:
            volumes[current_vol].extend(pages)

    return volumes


def _extract_section_pages(text: str, default_volume: str) -> list[FormatPage]:
    """Extract individual form/section pages from volume text."""
    pages: list[FormatPage] = []

    # Split by Chinese numbered headings (一、二、三、...)
    section_pattern = re.compile(r'(?:^|\n)\s*([一二三四五六七八九十]+)[、.．]\s*(.+?)(?:\n|$)')

    sections = list(section_pattern.finditer(text))
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

    return pages


def _classify_page_type(title: str, raw: str) -> str:
    """Classify a format page as letter, table, prose, or free."""
    title_lower = title.lower()
    raw_lower = (raw or "").lower()

    # Letters/forms
    letter_keywords = ['投标函', '承诺', '声明', '授权', '法定代表人', '委托', '联合体']
    for kw in letter_keywords:
        if kw in title or kw in raw:
            return "letter_template"

    # Tables
    table_indicators = ['|', '表格', '基本情况表', '汇总表', '附表', '清单']
    if any(kw in raw[:500] for kw in table_indicators):
        return "table_template"
    if raw.count('\n') > 10 and raw.count('｜') + raw.count('|') > 2:
        return "table_template"

    # Prose/construction plan
    if any(kw in title for kw in ['施工', '方案', '措施', '部署', '计划', '进度']):
        return "prose_section"

    if '说明' in title or '编制' in title:
        return "prose_section"

    return "free_material"
