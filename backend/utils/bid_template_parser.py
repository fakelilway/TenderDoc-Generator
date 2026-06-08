from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader

from schemas.bid_template import BidTemplate, BidTemplateSection


MAIN_SECTION_TITLES = [
    "一、投标函及投标函附录",
    "二、授权委托书或法定代表人身份证明",
    "三、联合体协议书",
    "四、投标保证金",
    "五、施工组织设计",
    "六、项目管理机构",
    "七、拟分包项目情况表",
    "八、资格审查资料",
    "九、中小企业声明函",
]

CHINESE_NUMERALS = "一二三四五六七八九十百零〇"
TOC_LINE_RE = re.compile(
    rf"(?P<title>(?:第[{CHINESE_NUMERALS}]+[章节]、|[{CHINESE_NUMERALS}]+、|附表[{CHINESE_NUMERALS}]+、)[^.\n]{{2,120}}?)"
    r"(?:\.{3,}|…{2,}|\s{2,})"
    r"(?P<page>\d{1,4})\s*$"
)


def parse_bid_template_pdf(
    file_path: str | Path,
    template_name: str = "",
) -> BidTemplate:
    path = Path(file_path)
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return parse_bid_template_pages(
        pages,
        source_file=path.name,
        template_name=template_name or path.stem,
    )


def parse_bid_template_bytes(
    file_bytes: bytes,
    source_file: str = "",
    template_name: str = "",
) -> BidTemplate:
    reader = PdfReader(BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return parse_bid_template_pages(
        pages,
        source_file=source_file,
        template_name=template_name or Path(source_file).stem,
    )


def parse_bid_template_pages(
    pages: list[str],
    source_file: str = "",
    template_name: str = "",
) -> BidTemplate:
    page_count = len(pages)
    cover_text = _cover_page_text(pages[:3])
    main_sections = _extract_main_sections(pages)
    construction_start = _section_start(main_sections, "五、施工组织设计") or 0
    construction_offset = construction_start if construction_start else 0
    toc_window = _construction_toc_window(pages, construction_start)
    construction_sections = _extract_toc_sections(
        toc_window,
        pages,
        construction_offset=construction_offset,
        section_type="construction_design",
    )
    appendix_sections = [
        section
        for section in construction_sections
        if section.title.startswith("附表")
    ]
    construction_sections = [
        section
        for section in construction_sections
        if not section.title.startswith("附表")
    ]
    fixed_form_sections = [
        section
        for section in main_sections
        if section.section_type in {"fixed_form", "qualification", "declaration"}
    ]

    return BidTemplate(
        template_name=template_name or "bid-template",
        source_file=source_file,
        page_count=page_count,
        project_name=_extract_project_name(cover_text),
        company_name=_extract_company_name(cover_text),
        envelope_type=_extract_envelope_type(cover_text),
        document_type=_extract_document_type(cover_text),
        main_sections=main_sections,
        construction_design_sections=construction_sections,
        appendix_sections=appendix_sections,
        fixed_form_sections=fixed_form_sections,
        notes=[
            "Page numbers are 1-based PDF page numbers.",
            "Construction design TOC page labels are converted to PDF page numbers when possible.",
            "Use this JSON as a structural reference; company-specific names, people, certificates, prices, and dates must still come from user-approved materials.",
        ],
    )


def _extract_main_sections(pages: list[str]) -> list[BidTemplateSection]:
    found: list[BidTemplateSection] = []

    for title in MAIN_SECTION_TITLES:
        page_number = _find_heading_page(pages, title, start_index=3)
        section_type = _main_section_type(title)
        found.append(
            BidTemplateSection(
                title=title,
                start_page=page_number,
                level=1,
                section_type=section_type,
                sample_snippet=_page_snippet(pages, page_number),
            )
        )

    known_starts = [section.start_page for section in found if section.start_page]
    for section in found:
        if not section.start_page:
            continue
        next_starts = [page for page in known_starts if page > section.start_page]
        section.end_page = min(next_starts) - 1 if next_starts else len(pages)

    return found


def _extract_toc_sections(
    toc_pages: Iterable[tuple[int, str]],
    pages: list[str],
    construction_offset: int,
    section_type: str,
) -> list[BidTemplateSection]:
    sections: list[BidTemplateSection] = []
    seen: set[str] = set()

    for _, text in toc_pages:
        for raw_line in text.splitlines():
            line = _clean_line(raw_line)
            match = TOC_LINE_RE.search(line)
            if not match:
                continue
            title = _normalize_title(match.group("title"))
            if title in seen:
                continue
            seen.add(title)
            source_page = match.group("page")
            start_page = _toc_page_to_pdf_page(source_page, construction_offset, len(pages))
            sections.append(
                BidTemplateSection(
                    title=title,
                    start_page=start_page,
                    level=_toc_level(title),
                    section_type="appendix" if title.startswith("附表") else section_type,
                    source_page_label=source_page,
                    sample_snippet=_page_snippet(pages, start_page),
                )
            )

    starts = [section.start_page for section in sections if section.start_page]
    for section in sections:
        if not section.start_page:
            continue
        next_starts = [page for page in starts if page > section.start_page]
        section.end_page = min(next_starts) - 1 if next_starts else section.start_page

    return sections


def _construction_toc_window(
    pages: list[str],
    construction_start_page: int,
) -> list[tuple[int, str]]:
    if not construction_start_page:
        return []
    start_index = max(construction_start_page - 1, 0)
    end_index = min(start_index + 20, len(pages))
    return [(idx + 1, pages[idx]) for idx in range(start_index, end_index)]


def _find_heading_page(
    pages: list[str],
    title: str,
    start_index: int = 0,
) -> int | None:
    for idx, text in enumerate(pages[start_index:], start=start_index):
        lines = [_clean_line(line) for line in text.splitlines()[:8]]
        if any(title in line for line in lines):
            return idx + 1
    return None


def _cover_page_text(pages: list[str]) -> str:
    for page in pages:
        if "项目名称" in page or "投标人" in page:
            return page
    return _first_nonempty_page(pages)


def _first_nonempty_page(pages: list[str]) -> str:
    for page in pages:
        if page.strip():
            return page
    return ""


def _extract_project_name(text: str) -> str:
    match = re.search(r"(.+?工程)（项目名称）", text)
    if match:
        return _clean_line(match.group(1))
    for line in text.splitlines():
        cleaned = _clean_line(line)
        if "项目名称" in cleaned:
            return cleaned.replace("（项目名称）", "").strip()
    return ""


def _extract_company_name(text: str) -> str:
    match = re.search(r"投标人[:：]\s*(.+?)(?:（|$)", text)
    return _clean_line(match.group(1)) if match else ""


def _extract_envelope_type(text: str) -> str:
    match = re.search(r"第[一二]信封", text)
    return match.group(0) if match else ""


def _extract_document_type(text: str) -> str:
    lines = [_clean_line(line) for line in text.splitlines()]
    for idx, line in enumerate(lines):
        if line == "投标文件" and idx + 1 < len(lines):
            return f"{line}{lines[idx + 1]}"
        if "商务及技术文件" in line:
            return "投标文件（商务及技术文件）"
    return "投标文件" if "投标文件" in text else ""


def _section_start(
    sections: list[BidTemplateSection],
    title: str,
) -> int | None:
    for section in sections:
        if section.title == title:
            return section.start_page
    return None


def _toc_page_to_pdf_page(
    source_page_label: str,
    construction_offset: int,
    page_count: int,
) -> int | None:
    try:
        source_page = int(source_page_label)
    except ValueError:
        return None
    candidate = source_page + construction_offset
    if 1 <= candidate <= page_count:
        return candidate
    if 1 <= source_page <= page_count:
        return source_page
    return None


def _page_snippet(pages: list[str], page_number: int | None, limit: int = 360) -> str:
    if not page_number or not (1 <= page_number <= len(pages)):
        return ""
    text = _redact_sensitive(_clean_page_text(pages[page_number - 1]))
    return text[:limit]


def _main_section_type(title: str) -> str:
    if title.startswith("五、"):
        return "construction_design"
    if title.startswith("八、"):
        return "qualification"
    if title.startswith("九、"):
        return "declaration"
    return "fixed_form"


def _toc_level(title: str) -> int:
    if title.startswith("第") and "章、" in title:
        return 1
    if title.startswith("第") and "节、" in title:
        return 2
    if title.startswith("附表"):
        return 2
    return 3


def _normalize_title(title: str) -> str:
    return _clean_line(title).rstrip(".")


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _clean_page_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        cleaned = _clean_line(line)
        if not cleaned:
            continue
        if re.search(r"第\d+页[/／]共\d+页", cleaned):
            continue
        if re.search(r"第\d+页共\d+页", cleaned):
            continue
        lines.append(cleaned)
    return "\n".join(lines)


def _redact_sensitive(text: str) -> str:
    redacted = re.sub(r"\d{17}[\dXx]", "【身份证号已脱敏】", text)
    redacted = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "【手机号已脱敏】", redacted)
    redacted = re.sub(r"\d{3,4}-\d{7,8}", "【电话已脱敏】", redacted)
    redacted = re.sub(r"[\w.\-]+@[\w.\-]+", "【邮箱已脱敏】", redacted)
    redacted = re.sub(r"本人([\u4e00-\u9fa5]{2,4})（姓名）", "本人【姓名已脱敏】（姓名）", redacted)
    redacted = re.sub(r"现委托([\u4e00-\u9fa5]{2,4})（姓名）", "现委托【姓名已脱敏】（姓名）", redacted)
    redacted = re.sub(r"(联系人\s*)[\u4e00-\u9fa5]{2,4}", r"\1【姓名已脱敏】", redacted)
    redacted = re.sub(r"(姓名\s*)[\u4e00-\u9fa5]{2,4}", r"\1【姓名已脱敏】", redacted)
    return redacted
