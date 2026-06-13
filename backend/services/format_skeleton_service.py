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
