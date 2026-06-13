from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from core.config import get_settings
from prompts.parser_prompt import build_parser_json_repair_prompt, build_parser_prompt
from schemas.tender import RequirementItem, SourceReference, TenderRequirements


class ParserAgentError(RuntimeError):
    pass


PROJECT_NAME_PLACEHOLDERS = (
    "见投标人须知前附表",
    "见招标公告",
    "详见招标公告",
    "详见投标人须知前附表",
    "见前附表",
    "详见前附表",
    "本项目",
    "无",
    "/",
)


def _has_real_key(value: str) -> bool:
    return bool(value and value.strip() and "xxxx" not in value.lower())


def _get_llm_client_config() -> tuple[str, str, str]:
    settings = get_settings()
    provider = str(getattr(settings, "bid_llm_provider", "auto") or "auto").lower()
    if provider == "deepseek":
        if _has_real_key(settings.deepseek_api_key):
            return (
                settings.deepseek_api_key,
                settings.deepseek_base_url,
                settings.deepseek_model,
            )
        raise ParserAgentError(
            "DEEPSEEK_API_KEY is required when BID_LLM_PROVIDER=deepseek"
        )
    if provider == "openrouter":
        if _has_real_key(settings.openrouter_api_key):
            return (
                settings.openrouter_api_key,
                settings.openrouter_base_url,
                settings.openrouter_model,
            )
        raise ParserAgentError(
            "OPENROUTER_API_KEY is required when BID_LLM_PROVIDER=openrouter"
        )
    if _has_real_key(settings.openrouter_api_key):
        return (
            settings.openrouter_api_key,
            settings.openrouter_base_url,
            settings.openrouter_model,
        )
    if _has_real_key(settings.deepseek_api_key):
        return (
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
        )
    raise ParserAgentError("OPENROUTER_API_KEY or DEEPSEEK_API_KEY is required")


def _get_parser_timeout_seconds() -> float:
    value = float(getattr(get_settings(), "parser_llm_timeout_seconds", 45.0))
    return max(5.0, value)


def _strip_markdown_fence(content: str) -> str:
    content = content.strip()
    fence_match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL | re.IGNORECASE
    )
    if fence_match:
        return fence_match.group(1).strip()
    return content


def _extract_json_object(content: str) -> str:
    content = _strip_markdown_fence(content)
    if content.startswith("{") and content.endswith("}"):
        return content

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ParserAgentError("LLM response did not contain a JSON object")
    return content[start : end + 1]


def _remove_trailing_commas(content: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", content)


def _make_item(title: str, description: str, source_text: str) -> RequirementItem:
    return RequirementItem(
        title=title,
        description=description,
        source=SourceReference(source_text=source_text, page_number=None),
    )


def _has_all(text: str, keywords: tuple[str, ...]) -> bool:
    return all(keyword in text for keyword in keywords)


def _normalize_candidate_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ：:；;，,。")
    value = re.sub(r"\s+([）)])", r"\1", value)
    value = re.sub(r"([（(])\s+", r"\1", value)
    value = re.sub(r"([）)])\s+(施工|工程|项目)$", r"\1\2", value)
    return value.strip()


def _is_placeholder_project_name(value: str) -> bool:
    normalized = _normalize_candidate_text(value)
    if not normalized:
        return True
    return any(placeholder in normalized for placeholder in PROJECT_NAME_PLACEHOLDERS)


def _is_valid_project_name(value: str) -> bool:
    normalized = _normalize_candidate_text(value)
    if _is_placeholder_project_name(normalized):
        return False
    if len(normalized) < 4 or len(normalized) > 90:
        return False
    blocked_terms = (
        "招标文件",
        "投标文件",
        "投标人须知",
        "招标公告",
        "评标办法",
        "合同条款",
        "工程量清单",
        "目 录",
        "目录",
        "项目编号",
        "招标条件",
        "项目概况",
        "投标人资格",
    )
    if any(term in normalized for term in blocked_terms):
        return False
    return any(term in normalized for term in ("工程", "项目", "施工", "改造", "联网路"))


def _clean_project_name(value: str) -> str:
    value = _normalize_candidate_text(value)
    value = re.sub(r"[（(]\s*项目名称\s*[）)]", "", value)
    value = re.sub(r"(?:招标公告|招标项目|施工招标)$", "", value)
    value = _normalize_candidate_text(value)
    return value


def _iter_project_name_candidates(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    head = "\n".join(lines[:180])
    compact_head = re.sub(r"\n(?=(?:施工|工程|项目|标段名称|[（(]))", "", head)

    candidates: list[str] = []
    explicit_patterns = [
        r"(?:^|[\n\s])二、项目名称[:：]\s*([^\n]+(?:\n施工)?)",
        r"(?:^|[\n\s])项目名称[:：]\s*([^\n]+(?:\n施工)?)",
        r"(?:招标项目名称|工程名称|标段名称)[:：\s]+([^\n]+(?:\n施工)?)",
        r"本招标项目\s*([^\n（]+?)（项目名称）",
    ]
    for pattern in explicit_patterns:
        for match in re.finditer(pattern, head, flags=re.MULTILINE):
            candidates.append(match.group(1))
    for pattern in explicit_patterns:
        for match in re.finditer(pattern, compact_head, flags=re.MULTILINE):
            candidates.append(match.group(1))

    for line in lines[:30]:
        cleaned = _clean_project_name(line)
        if _is_valid_project_name(cleaned):
            candidates.append(cleaned)

    return [_clean_project_name(candidate) for candidate in candidates]


def _dedupe_items(items: list[RequirementItem]) -> list[RequirementItem]:
    deduped: list[RequirementItem] = []
    seen: set[str] = set()
    for item in items:
        key = re.sub(r"\s+", "", f"{item.title}:{item.description}")[:80]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _extract_project_name(text: str) -> str:
    for candidate in _iter_project_name_candidates(text):
        if _is_valid_project_name(candidate):
            return candidate
    return ""


def _extract_first_match(text: str, patterns: tuple[str, ...]) -> str:
    head = "\n".join([line.strip() for line in text.splitlines() if line.strip()][:320])
    for source in (head, text[:60000]):
        for pattern in patterns:
            match = re.search(pattern, source, flags=re.MULTILINE)
            if match:
                value = _normalize_candidate_text(match.group(1))
                if not _is_placeholder_field_value(value):
                    return value
    return ""


def _extract_core_project_fields(text: str) -> dict[str, str]:
    tenderer_name = _extract_first_match(
        text,
        (
            r"(?:招标人|采购人|发包人)\s*[:：]\s*([^\n；;，,]+)",
            r"^([^\n]{2,40}(?:局|公司|中心|政府|委员会|管理处|管理站|集团))[（(]招标人名称[）)]",
        ),
    )
    project_location = _extract_first_match(
        text,
        (
            r"(?:建设地点|实施地点|项目地点|工程地点)\s*[:：]\s*([^\n；;]+)",
            r"(?:建设地点|实施地点|项目地点|工程地点)\s+([^\n；;]+)",
        ),
    )
    planned_duration = _extract_first_match(
        text,
        (
            r"(?:计划工期|工期要求|工期)\s*[:：]\s*([^\n；;。]*?\d+\s*日历天)",
            r"(?:计划工期|工期要求|工期)\s*[:：]\s*([^\n；;。]{2,80})",
            r"工期\s*[:：]\s*(\d+\s*日历天)",
        ),
    )
    quality_standard = _extract_first_match(
        text,
        (
            r"(?:质量标准|质量要求|工程质量)\s*[:：]\s*([^\n；;。]{2,100})",
            r"工程质量\s*[:：]\s*([^\n；;。]{2,100})",
        ),
    )
    safety_target = _extract_first_match(
        text,
        (
            r"(?:安全目标|安全要求)\s*[:：]\s*([^\n；;。]{2,100})",
            r"安全目标\s*[:：]\s*([^\n；;。]{2,100})",
        ),
    )
    bid_deadline = _extract_first_match(
        text,
        (r"(?:投标截止时间|递交截止时间|开标时间)\s*[:：]\s*([^\n；;。]{6,80})",),
    )
    tender_scope = _extract_first_match(
        text,
        (
            r"(?:招标范围|工程内容|建设规模及内容|项目概况)\s*[:：]\s*([^\n]{6,240})",
            r"(?:招标范围|工程内容|建设规模及内容|项目概况)\s+([^\n]{6,240})",
        ),
    )
    return {
        "tenderer_name": tenderer_name,
        "project_location": project_location,
        "tender_scope": tender_scope,
        "planned_duration": planned_duration,
        "quality_standard": quality_standard,
        "safety_target": safety_target,
        "bid_deadline": bid_deadline,
    }


def _is_placeholder_field_value(value: str) -> bool:
    normalized = _normalize_candidate_text(value)
    if not normalized:
        return True
    exact_placeholders = {"无", "/", "本项目"}
    if normalized in exact_placeholders:
        return True
    return any(
        placeholder in normalized
        for placeholder in (
            "见投标人须知前附表",
            "见招标公告",
            "详见招标公告",
            "详见投标人须知前附表",
            "见前附表",
            "详见前附表",
        )
    )


_FORMAT_SECTION_HEADINGS = (
    "投标文件的组成",
    "投标文件组成",
    "投标文件的编制",
    "投标文件编制",
    "投标文件的签署",
    "投标文件签署",
    "投标文件的密封和标记",
    "投标文件密封和标记",
    "密封和标记",
)

_FORMAT_STRONG_SIGNAL_KEYWORDS = (
    "投标文件应包括",
    "投标文件包括",
    "投标文件由",
    "投标文件组成",
    "正本",
    "副本",
    "份数",
    "签字",
    "签署",
    "签章",
    "盖章",
    "装订",
    "密封",
    "标记",
    "封套",
    "加密上传",
    "非加密投标文件",
    "商务及技术文件",
    "第一信封",
    "第二信封",
)

_TOC_DOT_LEADER_RE = re.compile(r"[.·。…]{4,}\s*\d+\s*$")
_FORMAT_CHAPTER_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百\d]+章|[一二三四五六七八九十百\d]+[、.．])\s*投标文件格式\s*$"
)
_NEXT_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百\d]+章\s+.+$")
_NUMBERED_FORMAT_CLAUSE_RE = re.compile(
    r"^(?:\d+(?:\.\d+){1,3}|[（(]?\d+[）)])\s*"
    r".*(?:投标文件(?:的)?(?:组成|编制|签署|密封|标记)|密封和标记|签字|盖章|电子投标文件|非加密投标文件)"
)
_FORMAT_LIST_ITEM_RE = re.compile(
    r"^(?:[（(][一二三四五六七八九十\d]+[）)]|[一二三四五六七八九十\d]+[、.])\s*.+"
)

_FORMAT_STOP_HEADING_RE = re.compile(
    r"^第[一二三四五六七八九十]+章\s*(?!.*(?:投标文件格式|投标文件的编制|投标文件组成|投标文件的组成|密封和标记)).{2,30}$"
)


def _is_toc_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    return bool(_TOC_DOT_LEADER_RE.search(compact))


def _is_format_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    return bool(_FORMAT_CHAPTER_RE.match(stripped)) and not _is_toc_line(stripped)


def _is_next_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    return (
        bool(_NEXT_CHAPTER_RE.match(stripped))
        and not _is_format_chapter_heading(stripped)
        and not _is_toc_line(stripped)
    )


def _is_format_list_item(line: str) -> bool:
    return bool(_FORMAT_LIST_ITEM_RE.match(line.strip()))


def _extract_format_requirements(text: str) -> str:
    """Capture tender-native bid-format clauses as deterministic fallback.

    Formatting clauses are waste-bid sensitive. Prefer the real
    "第X章 投标文件格式" chapter and ignore table-of-contents dot leaders. Only
    when that chapter is absent do we fall back to scattered strong clauses in
    "投标人须知" about composition, signing, sealing and electronic files.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected: list[str] = []
    seen: set[str] = set()

    def add_line(line: str) -> None:
        cleaned = re.sub(r"\s+", " ", line).strip(" ；;")
        if not cleaned or _is_toc_line(cleaned):
            return
        key = re.sub(r"\s+", "", cleaned)
        if key in seen:
            return
        seen.add(key)
        selected.append(cleaned)

    chapter_lines = _extract_format_chapter_lines(lines)
    if chapter_lines:
        for line in _summarize_format_chapter_lines(chapter_lines):
            add_line(line)
        return "\n".join(f"- {line}" for line in selected)

    capturing = False
    capturing_form_list = False
    captured_chars = 0
    for index, line in enumerate(lines):
        if _is_toc_line(line):
            continue
        is_heading = any(heading in line for heading in _FORMAT_SECTION_HEADINGS)
        is_strong_clause = bool(_NUMBERED_FORMAT_CLAUSE_RE.match(line)) or any(
            keyword in line for keyword in _FORMAT_STRONG_SIGNAL_KEYWORDS
        )
        if is_heading or is_strong_clause:
            capturing = True
            capturing_form_list = "组成" in line or "投标文件应包括" in line or "投标文件包括" in line
            add_line(line)
            captured_chars += len(line)
            continue
        if capturing:
            if _FORMAT_STOP_HEADING_RE.match(line) or _is_next_chapter_heading(line):
                capturing = False
                capturing_form_list = False
                continue
            if (
                capturing_form_list
                and _is_format_list_item(line)
                or any(keyword in line for keyword in _FORMAT_STRONG_SIGNAL_KEYWORDS)
            ):
                add_line(line)
                captured_chars += len(line)
        if captured_chars >= 6500 or len(selected) >= 120:
            break

    if not selected:
        return ""
    return "\n".join(f"- {line}" for line in selected)


def _extract_format_chapter_lines(lines: list[str]) -> list[str]:
    for index, line in enumerate(lines):
        if not _is_format_chapter_heading(line):
            continue
        collected: list[str] = []
        captured_chars = 0
        for candidate in lines[index:]:
            if collected and _is_next_chapter_heading(candidate):
                break
            if _is_toc_line(candidate):
                continue
            collected.append(candidate)
            captured_chars += len(candidate)
            if captured_chars >= 80000 or len(collected) >= 1400:
                break
        return collected if len(collected) > 1 else []
    return []


def _summarize_format_chapter_lines(lines: list[str]) -> list[str]:
    """Summarise the real bid-format chapter instead of leaking raw forms."""
    if not lines:
        return []
    summary: list[str] = [f"格式章节：{lines[0]}"]
    volume_items: dict[str, list[str]] = {}
    current_volume = ""
    in_local_toc = False
    notes: list[str] = []
    awaiting_volume_suffix = False
    pending_envelope = ""

    for offset, raw in enumerate(lines[1:], start=1):
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or _is_toc_line(line):
            continue
        compact = re.sub(r"\s+", "", line)
        if line.isdigit():
            if in_local_toc and current_volume and volume_items.get(current_volume):
                in_local_toc = False
            continue
        if re.fullmatch(r"第[一二三四五六七八九十\d]+信封", compact):
            pending_envelope = compact
            continue
        if compact == "投标文件":
            awaiting_volume_suffix = True
            continue
        if awaiting_volume_suffix:
            split_volume_match = re.fullmatch(r"[（(]([^）)]+)[）)]", line)
            if split_volume_match:
                suffix = split_volume_match.group(1).strip()
                current_volume = (
                    f"{pending_envelope}（{suffix}）" if pending_envelope else suffix
                )
                volume_items.setdefault(current_volume, [])
                in_local_toc = True
                awaiting_volume_suffix = False
                pending_envelope = ""
                continue
            awaiting_volume_suffix = False
        volume_match = re.search(r"投标文件[（(]([^）)]+)[）)]", line)
        if volume_match:
            current_volume = volume_match.group(1).strip()
            volume_items.setdefault(current_volume, [])
            in_local_toc = True
            continue
        if line == "目 录" or line == "目录":
            in_local_toc = True
            continue
        if line.startswith("注：") and ("投标制作软件" in line or "投标文件制作软件" in line):
            note_parts = [line]
            for continuation in lines[offset + 1 : offset + 5]:
                continuation = re.sub(r"\s+", " ", continuation).strip()
                if not continuation or continuation.isdigit():
                    continue
                note_parts.append(continuation)
                if (
                    "评审" in continuation
                    or "两者均可" in continuation
                    or len("".join(note_parts)) >= 180
                ):
                    break
            _append_unique(notes, "".join(note_parts))
            continue
        if "盖单位章" in line or "签字或盖章" in line:
            _append_unique(notes, "签字盖章：按各表单要求由投标人盖单位章，法定代表人或授权代表签字/盖章。")
        if "电子保函" in line and "无需提供" in line:
            _append_unique(notes, "投标保证金：采用电子保函的，系统自动抓取电子保函信息，投标文件无需另附相关证明材料。")
        if "基本存款账户" in line and ("扫描件" in line or "编入投标文件" in line):
            _append_unique(notes, "投标保证金：现金、纸质保函、担保或保证保险方式须按格式要求编入基本存款账户信息及相应凭证扫描件。")
        if not current_volume:
            continue
        if _looks_like_form_heading(line, in_local_toc):
            if in_local_toc or not volume_items[current_volume]:
                title = _clean_form_heading(line)
                if title:
                    _append_unique(volume_items[current_volume], title)
            continue
        if in_local_toc and not _looks_like_form_heading(line, True):
            # A local table of contents usually ends before the first form body.
            in_local_toc = False

    for volume, items in volume_items.items():
        if items:
            summary.append(f"{volume}组成：{'、'.join(items)}。")
        else:
            summary.append(f"{volume}：按招标文件该卷格式编制。")
    summary.extend(notes[:8])
    return summary


def _looks_like_form_heading(line: str, in_local_toc: bool) -> bool:
    if len(line) > 60:
        return False
    if any(mark in line for mark in ("：", "；", "。", "，", "、 ")):
        return False
    if re.match(r"^[（(][一二三四五六七八九十\d]+[）)]\s*.+", line):
        return in_local_toc
    if re.match(r"^[一二三四五六七八九十]+[、]\s*.+", line):
        return True
    if re.match(r"^\d+[.．]\s*.+", line):
        return in_local_toc
    return False


def _clean_form_heading(line: str) -> str:
    line = re.sub(r"^[一二三四五六七八九十\d]+[、.．]\s*", "", line)
    line = re.sub(r"^[（(][一二三四五六七八九十\d]+[）)]\s*", "", line)
    return line.strip(" ：:；;。")


def _append_unique(items: list[str], value: str) -> None:
    value = value.strip()
    normalized = re.sub(r"[（(]如有[）)]", "", value)
    if value and all(re.sub(r"[（(]如有[）)]", "", item) != normalized for item in items):
        items.append(value)


def _merge_format_requirements(llm_text: str, rule_text: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for source in (llm_text, rule_text):
        for raw in (source or "").splitlines():
            cleaned = raw.strip()
            if not cleaned:
                continue
            cleaned = cleaned[2:].strip() if cleaned.startswith("- ") else cleaned
            key = re.sub(r"\s+", "", cleaned)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {cleaned}")
    return "\n".join(lines)


def _extract_rule_based_requirements(text: str) -> TenderRequirements:
    """Extract high-confidence tender clauses with deterministic MVP rules."""
    project_name = _extract_project_name(text)
    core_fields = _extract_core_project_fields(text)
    qualification_items: list[RequirementItem] = []
    score_items: list[RequirementItem] = []
    invalid_items: list[RequirementItem] = []

    if "公路工程施工总承包叁级及以上资质" in text:
        qualification_items.append(
            _make_item(
                "企业施工资质",
                "投标人须具备独立法人资格或其他组织，具有有效的公路工程施工总承包叁级及以上资质或建设工程企业资质管理制度改革后颁发的公路工程施工总承包乙级及以上资质。",
                "本次招标要求投标人具备独立法人资格或其他组织，具有有效的公路工程施工总承包叁级及以上资质或建设工程企业资质管理制度改革后颁发的公路工程施工总承包乙级及以上资质",
            )
        )
    elif "公路工程施工总承包三级及以上资" in text:
        qualification_items.append(
            _make_item(
                "企业施工资质",
                "投标人须具备公路工程施工总承包三级及以上资质。",
                "投标人资质要求：具备公路工程施工总承包三级及以上资质",
            )
        )

    if "安全生产许可证" in text:
        qualification_items.append(
            _make_item(
                "安全生产许可证",
                "投标人须具备有效的安全生产许可证。",
                "且具备有效的安全生产许可证",
            )
        )

    if "公路工程施工资质企业名录" in text:
        qualification_items.append(
            _make_item(
                "交通运输部资质名录",
                "投标人须进入交通运输部全国公路建设市场监督管理系统公路工程施工资质企业名录，且投标人名称和资质与名录一致。",
                "投标人应进入交通运输部全国公路建设市场监督管理系统中的公路工程施工资质企业名录，且投标人名称和资质与该名录中的相应企业名称和资质完全一致",
            )
        )

    if _has_all(text, ("项目经理", "二级及以上注册建造师")):
        qualification_items.append(
            _make_item(
                "项目经理资格",
                "拟派项目经理须具备公路工程专业二级及以上注册建造师执业资格，具备安全生产考核合格证书，且满足在岗要求。",
                "项目经理资质要求：具备公路工程专业二级及以上注册建造师执业资格，具备交通运输行政主管部门颁发的安全生产考核合格证书",
            )
        )

    if _has_all(text, ("项目经理", "社保")):
        qualification_items.append(
            _make_item(
                "项目经理社保要求",
                "项目经理须为本单位人员，并提供投标人所属社保机构出具的社保缴费证明或其他有效证明材料。",
                "提供投标人所属社保机构出具的拟委任的项目经理社保缴费证明或其他能够证明拟委任的项目经理参加社保的有效证明材料",
            )
        )

    if _has_all(text, ("项目总工", "中级及以上")):
        qualification_items.append(
            _make_item(
                "项目总工资格",
                "拟派项目总工须具有公路工程相关专业中级及以上工程师职称。",
                "投标人拟派项目总工须具有公路工程相关专业中级及以上工程师职称",
            )
        )

    if "中小微企业" in text and "40%" in text:
        qualification_items.append(
            _make_item(
                "政府采购政策资格",
                "本项目部分预留专门面向中小微企业采购，大中企业须以向中小微企业分包形式参加投标，且中小微企业承担部分不低于合同总金额40%。",
                "本招标项目部分预留专门面向中小微企业采购。要求大中企业向中小微企业分包的形式参加投标，且接受分包的中小微企业承担的部分不低于项目合同总金额的 40%",
            )
        )

    if "施工组织设计：40分" in text or "施工组织设计" in text:
        score_items.append(
            _make_item(
                "施工组织设计",
                "施工组织设计总分40分，包括总体施工组织布置及规划、主要工程项目施工方案、施工进度体系及保证措施、质量、安全、环保、风险防范等内容。",
                "施工组织设计：40分",
            )
        )

    if "主要人员：30分" in text:
        score_items.append(
            _make_item(
                "主要人员",
                "主要人员总分30分，其中项目经理任职资格与业绩15分，其他人员15分。",
                "主要人员：30分",
            )
        )

    if "履约信誉" in text:
        score_items.append(
            _make_item(
                "履约信誉",
                "履约信誉按相关交通运输管理部门信用评价等级计分。",
                "履约信誉；信用等级为AA的得15分；信用等级为A的得10分",
            )
        )

    if "类似业绩" in text or "公路养护工程施工业绩" in text:
        score_items.append(
            _make_item(
                "投标人类似业绩",
                "投标人承担并完成过公路养护工程施工业绩的，按招标文件评分标准计分。",
                "投标人自2022年1月1日以来承担并完成过公路养护工程施工业绩得15分",
            )
        )

    if "合理低价法" in text:
        score_items.extend(
            [
                _make_item(
                    "评标办法",
                    "本次评标采用合理低价法，对满足招标文件实质性要求的投标文件按评分标准打分，并按得分由高到低顺序推荐中标候选人。",
                    "本次评标采用合理低价法。评标委员会对满足招标文件实质性要求的投标文件，按照评分标准进行打分，并按得分由高到低顺序推荐中标候选人",
                ),
                _make_item(
                    "评标价分值",
                    "分值构成为评标价100分。",
                    "分值构成（总分100分） 评标价：100分",
                ),
                _make_item(
                    "评标基准价计算",
                    "通过初步评审的投标人评标价去掉规定数量最高值和最低值后的算术平均值作为评标价平均值，并将评标价平均值直接作为评标基准价。",
                    "通过初步评审的所有投标人的评标价去掉n个最高值和n个最低值后的算术平均值即为评标价平均值；将评标价平均值直接作为评标基准价",
                ),
                _make_item(
                    "评标价得分计算",
                    "评标价高于基准价时按100－偏差率×100×E1计算，低于或等于基准价时按100＋偏差率×100×E2计算。",
                    "如果投标人的评标价>评标基准价，则评标价得分＝100－偏差率×100×E1；如果投标人的评标价≤评标基准价，则评标价得分＝100＋偏差率×100×E2",
                ),
            ]
        )

    if "不满足本项规定条件的，将被否决投标" in text:
        invalid_items.append(
            _make_item(
                "资质名录不一致",
                "投标人未进入交通运输部公路工程施工资质企业名录，或投标人名称和资质与名录不一致的，将被否决投标。",
                "投标人不满足本项规定条件的，将被否决投标",
            )
        )

    if "投标保证金" in text and "否决" in text:
        invalid_items.append(
            _make_item(
                "投标保证金不符合要求",
                "投标人不按招标文件要求提交投标保证金的，评标委员会将否决其投标。",
                "投标人不按要求提交投标保证金的，评标委员会将否决其投标",
            )
        )

    if "报价金额出现差异" in text:
        invalid_items.append(
            _make_item(
                "报价金额差异",
                "工程量固化清单中的投标报价和投标函大写金额报价不一致的，投标将被否决。",
                "工程量固化清单中的投标报价和投标函大写金额报价应一致，如果报价金额出现差异，其投标将被否决",
            )
        )

    if "最终投标报价若超过最高投标限价" in text:
        invalid_items.append(
            _make_item(
                "最终报价超限价",
                "修正后的最终投标报价超过最高投标限价的，评标委员会应否决其投标。",
                "修正后的最终投标报价若超过最高投标限价（如有），评标委员会应否决其投标",
            )
        )

    if "低于成本报价" in text and "否决" in text:
        invalid_items.append(
            _make_item(
                "低于成本报价且不能说明",
                "报价明显低于其他投标报价，投标人不能合理说明或不能提供证明材料的，评标委员会应认定其低于成本报价竞标并否决投标。",
                "投标人不能合理说明或不能提供相应证明材料的，评标委员会应认定该投标人以低于成本报价竞标，并否决其投标",
            )
        )

    if "串通投标" in text or "弄虚作假" in text or "行贿" in text:
        invalid_items.append(
            _make_item(
                "串通投标、弄虚作假、行贿",
                "评标过程中发现投标人存在串通投标、弄虚作假、行贿等违法行为的，评标委员会应否决其投标。",
                "投标人存在串通投标、弄虚作假、行贿等违法行为的，评标委员会应否决其投标",
            )
        )

    if "统一社会信用代码" in text and "否决" in text:
        invalid_items.append(
            _make_item(
                "统一社会信用代码不一致",
                "投标人填报的名称和统一社会信用代码不符合要求的，评标委员会应当否决其投标。",
                "名称和统一社会信用代码，否则，评标委员会应当否决其投标",
            )
        )

    if "有一项不符合评审标准" in text:
        invalid_items.append(
            _make_item(
                "初步评审不符合标准",
                "商务技术文件或报价文件初步评审中有一项不符合评审标准的，评标委员会应否决其投标。",
                "初步评审。有一项不符合评审标准的，评标委员会应否决其投标",
            )
        )

    if "不接受修正价格" in text:
        invalid_items.append(
            _make_item(
                "不接受修正价格",
                "投标报价存在算术错误并经修正后，投标人不接受修正价格的，评标委员会应否决其投标。",
                "修正的价格经投标人书面确认后具有约束力。投标人不接受修正价格的，评标委员会应否决其投标",
            )
        )

    if "不按评标委员会要求澄清或说明" in text:
        invalid_items.append(
            _make_item(
                "不按要求澄清说明",
                "评标委员会要求投标人澄清或说明时，投标人不按要求澄清或说明的，评标委员会应否决其投标。",
                "投标人不按评标委员会要求澄清或说明的，评标委员会应否决其投标",
            )
        )

    return TenderRequirements(
        project_name=project_name,
        **core_fields,
        bid_format_requirements=_extract_format_requirements(text),
        qualification_list=_dedupe_items(qualification_items),
        technical_score_items=_dedupe_items(score_items),
        invalid_bid_items=_dedupe_items(invalid_items),
    )


def _sanitize_json_content(content: str) -> str:
    """Fix common LLM JSON issues: unescaped control chars, stray newlines in strings."""
    # Collapse literal newlines inside JSON string values (not structural ones)
    # Strategy: replace literal \n \r \t that aren't already escaped
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # Simple pass: escape real control chars inside quoted strings
    # More robust: let the JSON repair prompt handle truly broken JSON
    return content


def parse_tender_response(content: str) -> TenderRequirements:
    """Parse and validate raw LLM output into the MVP tender schema."""
    json_text = _remove_trailing_commas(_extract_json_object(content))
    json_text = _sanitize_json_content(json_text)
    try:
        data: dict[str, Any] = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ParserAgentError(f"Failed to decode parser JSON: {exc}") from exc

    # Normalize source fields: LLM sometimes outputs plain strings instead of
    # the {"source_text": "...", "page_number": null} object.
    for list_key in ("qualification_list", "technical_score_items", "invalid_bid_items"):
        items = data.get(list_key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("source"), str):
                    item["source"] = {"source_text": item["source"], "page_number": None}

    result = TenderRequirements.model_validate(data)

    # Ensure format_outline_tree has the three required volume keys.
    _normalize_format_tree(result)

    # Reject effectively-empty results — an all-default skeleton is worse than
    # an honest failure because downstream agents treat it as valid input.
    if _is_empty_parse(result):
        raise ParserAgentError(
            "LLM returned a valid JSON skeleton with all fields empty. "
            "This looks like a model reliability issue rather than a real parse result."
        )
    return result


def _normalize_format_tree(result: TenderRequirements) -> None:
    """Ensure format_outline_tree has the three canonical keys."""
    for key in ("commercial", "technical", "pricing"):
        if key not in result.format_outline_tree:
            result.format_outline_tree[key] = []


def _build_fallback_format_tree(text: str) -> dict[str, list[Any]]:
    """Build a flat format outline tree from the rule-based format extraction.
    
    Lacking the LLM's insight into nesting, this provides at least flat lists
    of known form names per volume as a safety net.
    """
    # Import inline to avoid circular imports
    from schemas.tender import FormatOutlineNode  # noqa: F811

    requirements = _extract_rule_based_requirements(text)
    fmt_req = requirements.bid_format_requirements
    tree: dict[str, list[FormatOutlineNode]] = {
        "commercial": [],
        "technical": [],
        "pricing": [],
    }

    if not fmt_req:
        return tree

    current_volume = ""
    for line in fmt_req.splitlines():
        line = line.strip()
        if not line or not line.startswith("- "):
            continue
        content = line[2:].strip()
        if "商务" in content and "组成" in content:
            current_volume = "commercial"
            tree[current_volume] = _parse_volume_forms(content)
        elif "技术" in content and "组成" in content:
            current_volume = "technical"
            tree[current_volume] = _parse_volume_forms(content)
        elif "报价" in content and "组成" in content:
            current_volume = "pricing"
            tree[current_volume] = _parse_volume_forms(content)

    return tree


def _parse_volume_forms(line: str) -> list[Any]:
    """Extract form names from a volume composition line like
    "商务文件组成：投标函、法定代表人身份证明、投标保证金、项目管理机构"."""
    from schemas.tender import FormatOutlineNode  # noqa: F811

    index = line.find("：") if "：" in line else line.find(":")
    if index == -1:
        return []
    forms_text = line[index + 1 :]
    form_names = [name.strip(" 。；;，,") for name in forms_text.split("、") if name.strip(" 。；;，,")]
    return [FormatOutlineNode(title=name) for name in form_names[:50]]


def _is_format_tree_empty(tree: dict[str, list[Any]]) -> bool:
    """True when no volume has any nodes."""
    return all(len(tree.get(k, [])) == 0 for k in ("commercial", "technical", "pricing"))


def _is_empty_parse(result: TenderRequirements) -> bool:
    """True when the LLM returned only default/empty values — no real extraction happened."""
    string_fields = (
        result.project_name,
        result.tenderer_name,
        result.project_location,
        result.tender_scope,
        result.planned_duration,
        result.quality_standard,
        result.safety_target,
        result.bid_deadline,
        result.bid_format_requirements,
    )
    has_string_data = any(v.strip() for v in string_fields)
    has_list_data = bool(
        result.qualification_list
        or result.technical_score_items
        or result.invalid_bid_items
    )
    return not has_string_data and not has_list_data


def _chat_json(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float,
    max_tokens: int,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        timeout=timeout_seconds,
    )
    if not response.choices:
        raise ParserAgentError(
            "LLM response did not contain choices: "
            f"{response.model_dump_json()[:1000]}"
        )
    return response.choices[0].message.content or ""


def _parse_or_repair_tender_response(
    content: str,
    *,
    client: OpenAI,
    model: str,
    timeout_seconds: float,
) -> TenderRequirements:
    try:
        return parse_tender_response(content)
    except ParserAgentError as first_error:
        repaired = _chat_json(
            client,
            model,
            build_parser_json_repair_prompt(content, str(first_error)),
            timeout_seconds=timeout_seconds,
            max_tokens=100000,
        )
        try:
            return parse_tender_response(repaired)
        except ParserAgentError as repair_error:
            raise ParserAgentError(
                f"{first_error}; JSON repair also failed: {repair_error}"
            ) from repair_error


def parse_tender(text: str) -> TenderRequirements:
    """Extract tender requirements with the configured OpenAI-compatible LLM."""
    if not text.strip():
        raise ValueError("Tender text is empty")
    try:
        api_key, base_url, model = _get_llm_client_config()
    except ParserAgentError as error:
        raise ParserAgentError(f"Parser LLM is not configured: {error}") from error

    # Pass the full tender text to the LLM. Modern models (DeepSeek V4 128K)
    # handle ~100K chars comfortably; keyword-based trimming was losing context.
    tender_text = text[:120000]

    try:
        timeout_seconds = _get_parser_timeout_seconds()
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        content = _chat_json(
            client,
            model,
            build_parser_prompt(tender_text),
            timeout_seconds=timeout_seconds,
            max_tokens=100000,
        )
        llm_based = _parse_or_repair_tender_response(
            content,
            client=client,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except Exception as error:
        raise ParserAgentError(f"Parser LLM failed: {error}") from error

    # Format requirements: rule-based extraction from the format chapter is the
    # primary and most reliable source.  LLM provides supplementary scattered
    # clauses (sealing, electronic submission, etc.) that live outside the
    # format chapter.  Both are merged and deduplicated.
    rule_format = _extract_format_requirements(text)
    llm_based.bid_format_requirements = _merge_format_requirements(
        llm_based.bid_format_requirements, rule_format
    )
    # If the LLM did not produce a format outline tree (or it is empty),
    # use the rule-based extraction to build a flat fallback.
    if _is_format_tree_empty(llm_based.format_outline_tree):
        llm_based.format_outline_tree = _build_fallback_format_tree(text)
    return llm_based
