from __future__ import annotations

import json
import re
from pathlib import Path

from openai import OpenAI

from agents.parser_agent import _has_real_key
from core.config import get_settings
from schemas.review import InvalidBidRule, ReviewFinding, ReviewLocation, ReviewReport
from schemas.tender import TenderRequirements


RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "invalid_bid_rules.json"


def load_invalid_bid_rules(path: str | Path = RULES_PATH) -> list[InvalidBidRule]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [InvalidBidRule.model_validate(item) for item in data]


def review(
    parsed_requirements: TenderRequirements,
    generated_markdown: str,
    use_llm: bool = False,
) -> ReviewReport:
    findings = _review_with_rules(parsed_requirements, generated_markdown)
    if use_llm:
        findings.extend(_review_with_llm(parsed_requirements, generated_markdown))
    return _build_report(findings)


def _review_with_rules(
    parsed_requirements: TenderRequirements,
    generated_markdown: str,
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    requirement_text = _requirements_text(parsed_requirements)

    for rule in load_invalid_bid_rules():
        triggered = _matches_any(rule.keyword_patterns, requirement_text)
        present = _matches_any(rule.keyword_patterns, generated_markdown)
        location = find_markdown_location(generated_markdown, rule.keyword_patterns)

        if triggered and not present:
            findings.append(
                ReviewFinding(
                    rule=rule.id,
                    status="fail",
                    severity=rule.severity,
                    suggestion=rule.suggestion,
                    evidence=f"招标要求涉及“{rule.field}”，但生成稿未明确响应。",
                    location=location,
                )
            )
        elif triggered and present:
            findings.append(
                ReviewFinding(
                    rule=rule.id,
                    status="pass",
                    severity=rule.severity,
                    suggestion="已在生成稿中找到相关响应。",
                    evidence=f"生成稿包含“{rule.field}”相关表述。",
                    location=location,
                )
            )

    for index, item in enumerate(parsed_requirements.invalid_bid_items):
        keywords = _keywords_from_text(f"{item.title} {item.description}")
        location = find_markdown_location(generated_markdown, keywords)
        if _matches_any(keywords, generated_markdown):
            status = "pass"
            evidence = "生成稿已覆盖该废标/否决风险。"
            suggestion = "保持该风险响应，并在最终标书中核对附件和承诺。"
        else:
            status = "fail"
            evidence = "生成稿未覆盖该废标/否决风险。"
            suggestion = f"补充响应：{item.description}"
        findings.append(
            ReviewFinding(
                rule=f"invalid_bid_item_{index + 1}",
                status=status,
                severity="high",
                suggestion=suggestion,
                evidence=evidence,
                location=location,
            )
        )

    if not findings:
        findings.append(
            ReviewFinding(
                rule="general_completeness",
                status="warning",
                severity="medium",
                suggestion="未解析出明确废标规则，请人工核对招标文件关键条款。",
                evidence="无可审查的结构化废标项。",
                location=find_markdown_location(generated_markdown, []),
            )
        )

    return findings


def find_markdown_location(
    markdown_text: str,
    patterns: list[str],
) -> ReviewLocation:
    lines = markdown_text.splitlines()
    for line_number, line in enumerate(lines, start=1):
        if _matches_any(patterns, line):
            return ReviewLocation(
                line_number=line_number,
                paragraph_index=_paragraph_index(markdown_text, line_number),
                snippet=line.strip()[:200],
            )

    first_content = next((line.strip() for line in lines if line.strip()), "")
    return ReviewLocation(
        line_number=1 if lines else None, paragraph_index=0, snippet=first_content[:200]
    )


def _review_with_llm(
    parsed_requirements: TenderRequirements,
    generated_markdown: str,
) -> list[ReviewFinding]:
    settings = get_settings()
    if _has_real_key(settings.openrouter_api_key):
        api_key = settings.openrouter_api_key
        base_url = settings.openrouter_base_url
        model = settings.openrouter_model
    elif _has_real_key(settings.deepseek_api_key):
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
        model = settings.deepseek_model
    else:
        return []

    prompt = _build_llm_review_prompt(parsed_requirements, generated_markdown)
    try:
        response = OpenAI(api_key=api_key, base_url=base_url).chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是技术标废标风险审查员，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=1200,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        return []

    findings: list[ReviewFinding] = []
    for item in data.get("findings", []):
        try:
            findings.append(ReviewFinding.model_validate(item))
        except Exception:
            continue
    return findings


def _build_report(findings: list[ReviewFinding]) -> ReviewReport:
    pass_count = sum(1 for item in findings if item.status == "pass")
    fail_count = sum(1 for item in findings if item.status == "fail")
    warning_count = sum(1 for item in findings if item.status == "warning")
    return ReviewReport(
        findings=findings,
        pass_count=pass_count,
        fail_count=fail_count,
        warning_count=warning_count,
        has_failures=fail_count > 0,
    )


def _requirements_text(requirements: TenderRequirements) -> str:
    parts = [requirements.project_name]
    for group in (
        requirements.qualification_list,
        requirements.technical_score_items,
        requirements.invalid_bid_items,
    ):
        for item in group:
            parts.extend([item.title, item.description, item.source.source_text])
    return "\n".join(part for part in parts if part)


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _keywords_from_text(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text)
    keywords = [token for token in tokens if token not in {"处理", "要求", "投标"}]
    return keywords[:6] or [text[:20]]


def _paragraph_index(markdown_text: str, line_number: int) -> int:
    paragraphs = [
        line
        for line in markdown_text.splitlines()[:line_number]
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return max(len(paragraphs) - 1, 0)


def _build_llm_review_prompt(
    parsed_requirements: TenderRequirements,
    generated_markdown: str,
) -> str:
    return f"""请检查生成标书是否遗漏废标/否决风险，仅输出 JSON：
{{
  "findings": [
    {{
      "rule": "llm_review",
      "status": "pass|fail|warning",
      "severity": "high|medium|low",
      "suggestion": "",
      "evidence": "",
      "location": {{"line_number": null, "paragraph_index": null, "snippet": ""}}
    }}
  ]
}}

解析结果：
{parsed_requirements.model_dump_json()}

生成标书：
{generated_markdown[:12000]}
"""
