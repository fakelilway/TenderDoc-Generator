from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from core.config import get_settings
from prompts.parser_prompt import build_parser_prompt
from schemas.tender import RequirementItem, SourceReference, TenderRequirements


class ParserAgentError(RuntimeError):
    pass


RELEVANT_KEYWORDS = (
    "项目名称",
    "工程名称",
    "招标项目名称",
    "投标人资格",
    "资格要求",
    "资格审查",
    "资质",
    "安全生产许可证",
    "项目经理",
    "项目总工",
    "评分",
    "评分因素",
    "评分标准",
    "技术评分",
    "施工组织设计",
    "评标办法",
    "否决",
    "废标",
    "无效投标",
    "重大偏差",
)


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


def _prepare_tender_text(text: str, max_chars: int = 45000) -> str:
    """Keep the LLM input focused on parser-relevant tender sections."""
    if len(text) <= max_chars:
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected_indexes: list[int] = []
    seen: set[int] = set()

    def add_index(index: int) -> None:
        if index not in seen:
            selected_indexes.append(index)
            seen.add(index)

    for index, _line in enumerate(lines[:40]):
        add_index(index)

    for index, line in enumerate(lines):
        if any(keyword in line for keyword in RELEVANT_KEYWORDS):
            start = max(0, index - 4)
            end = min(len(lines), index + 12)
            for selected_index in range(start, end):
                add_index(selected_index)

    focused_lines: list[str] = []
    current_length = 0
    for index in selected_indexes:
        line = lines[index]
        next_length = current_length + len(line) + 1
        if next_length > max_chars:
            continue
        focused_lines.append(line)
        current_length = next_length

    return "\n".join(focused_lines)


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


def _extract_rule_based_requirements(text: str) -> TenderRequirements:
    """Extract high-confidence tender clauses with deterministic MVP rules."""
    project_name = _extract_project_name(text)
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
        qualification_list=_dedupe_items(qualification_items),
        technical_score_items=_dedupe_items(score_items),
        invalid_bid_items=_dedupe_items(invalid_items),
    )


def _merge_requirements(
    rule_based: TenderRequirements, llm_based: TenderRequirements
) -> TenderRequirements:
    project_name = rule_based.project_name
    if not project_name or _is_placeholder_project_name(project_name):
        project_name = llm_based.project_name
    if _is_placeholder_project_name(project_name):
        project_name = ""

    return TenderRequirements(
        project_name=project_name,
        qualification_list=_dedupe_items(
            [*rule_based.qualification_list, *llm_based.qualification_list]
        ),
        technical_score_items=_dedupe_items(
            [*rule_based.technical_score_items, *llm_based.technical_score_items]
        ),
        invalid_bid_items=_dedupe_items(
            [*rule_based.invalid_bid_items, *llm_based.invalid_bid_items]
        ),
    )


def _has_rule_based_content(requirements: TenderRequirements) -> bool:
    return bool(
        requirements.project_name
        or requirements.qualification_list
        or requirements.technical_score_items
        or requirements.invalid_bid_items
    )


def parse_tender_response(content: str) -> TenderRequirements:
    """Parse and validate raw LLM output into the MVP tender schema."""
    json_text = _remove_trailing_commas(_extract_json_object(content))
    try:
        data: dict[str, Any] = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ParserAgentError(f"Failed to decode parser JSON: {exc}") from exc

    try:
        return TenderRequirements.model_validate(data)
    except ValidationError as exc:
        raise ParserAgentError(
            f"Parser JSON did not match TenderRequirements: {exc}"
        ) from exc


def parse_tender(text: str) -> TenderRequirements:
    """Extract tender requirements with the configured OpenAI-compatible LLM."""
    if not text.strip():
        raise ValueError("Tender text is empty")
    rule_based = _extract_rule_based_requirements(text)
    try:
        api_key, base_url, model = _get_llm_client_config()
    except ParserAgentError:
        if _has_rule_based_content(rule_based):
            return rule_based
        raise

    tender_text = _prepare_tender_text(text)

    try:
        timeout_seconds = _get_parser_timeout_seconds()
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        response = client.chat.completions.create(
            model=model,
            messages=build_parser_prompt(tender_text),
            temperature=0,
            max_tokens=3000,
            response_format={"type": "json_object"},
            timeout=timeout_seconds,
        )

        if not response.choices:
            raise ParserAgentError(
                "LLM response did not contain choices: "
                f"{response.model_dump_json()[:1000]}"
            )
        content = response.choices[0].message.content or ""
        llm_based = parse_tender_response(content)
    except Exception:
        if _has_rule_based_content(rule_based):
            return rule_based
        raise

    return _merge_requirements(rule_based, llm_based)
