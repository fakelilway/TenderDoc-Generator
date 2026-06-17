"""读懂招标 → 投标规格(LLM 抽) + 组装项目的逐空核对报告。

build_tender_spec:用 LLM 把招标抽成 TenderSpec(可注入 complete 便于测试)。
build_project_conformance_report:取项目+档案+选派+证件库,跑核对引擎出报告。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from psycopg2.extras import RealDictCursor

from core.db import get_db_connection
from prompts.deep_parser_prompt import build_tender_spec_prompt
from schemas.tender import TenderRequirements
from schemas.tender_spec import (
    CertRequirement,
    ClauseItem,
    ConformanceReport,
    PerformanceRequirement,
    TenderSpec,
)
from services.company_profile_service import get_company_profile
from services.conformance_service import build_conformance_report
from services.personnel_selection_service import derive_pm_requirement

logger = logging.getLogger(__name__)

# 切片核心字段(工期/资质/附件)集中在投标人须知前附表+资格审查(章节1-3),取前段足够。
_SPEC_TEXT_CAP = 55000

Completion = Callable[[list[dict[str, str]]], str]


def _default_complete(messages: list[dict[str, str]]) -> str:
    from openai import OpenAI

    from agents.parser_agent import _get_llm_client_config
    from core.config import get_settings
    from core.llm_client import chat_completion

    api_key, base_url, model = _get_llm_client_config()
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = chat_completion(
        client,
        model=model,
        messages=messages,
        temperature=0.1,
        max_tokens=4000,
        timeout=float(getattr(get_settings(), "parser_llm_timeout_seconds", 60.0)),
    )
    return response.choices[0].message.content or ""


def _parse_json(raw: str) -> dict[str, Any]:
    from agents.parser_agent import (
        _extract_json_object,
        _remove_trailing_commas,
        _strip_markdown_fence,
    )

    try:
        cleaned = _remove_trailing_commas(_extract_json_object(_strip_markdown_fence(raw)))
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("投标规格 JSON 解析失败,返回空规格", exc_info=True)
        return {}


def _to_spec(data: dict[str, Any]) -> TenderSpec:
    """把 LLM 出的 dict 防御性地装进 TenderSpec(脏字段不炸,丢弃即可)。"""

    def _clauses(key: str) -> list[ClauseItem]:
        out = []
        for row in data.get(key) or []:
            if isinstance(row, dict):
                out.append(
                    ClauseItem(
                        clause_no=str(row.get("clause_no", "") or ""),
                        name=str(row.get("name", "") or ""),
                        content=str(row.get("content", "") or ""),
                    )
                )
        return out

    certs = []
    for row in data.get("cert_requirements") or []:
        if isinstance(row, dict) and row.get("required_value"):
            certs.append(
                CertRequirement(
                    cert_type=str(row.get("cert_type", "") or ""),
                    required_value=str(row.get("required_value", "") or ""),
                    source=str(row.get("source", "") or ""),
                )
            )

    perf = None
    praw = data.get("performance_requirement")
    if isinstance(praw, dict) and any(praw.values()):
        try:
            perf = PerformanceRequirement(
                since=str(praw.get("since", "") or ""),
                category=str(praw.get("category", "") or ""),
                min_amount_wan=float(praw.get("min_amount_wan", 0) or 0),
                min_count=int(praw.get("min_count", 0) or 0),
                time_basis=str(praw.get("time_basis", "交工") or "交工"),
            )
        except (TypeError, ValueError):
            perf = None

    attach = data.get("attachment_requirements")
    attach = attach if isinstance(attach, dict) else {}
    attach = {
        str(k): [str(v) for v in (vals or []) if v]
        for k, vals in attach.items()
    }

    return TenderSpec(
        duration=str(data.get("duration", "") or ""),
        bid_validity=str(data.get("bid_validity", "") or ""),
        cert_requirements=certs,
        performance_requirement=perf,
        attachment_requirements=attach,
        instructions_table=_clauses("instructions_table"),
        contract_appendix=_clauses("contract_appendix"),
    )


def build_tender_spec(tender_text: str, *, complete: Completion | None = None) -> TenderSpec:
    if not (tender_text or "").strip():
        return TenderSpec()
    messages = build_tender_spec_prompt(tender_text[:_SPEC_TEXT_CAP])
    raw = (complete or _default_complete)(messages)
    return _to_spec(_parse_json(raw))


def _available_cert_types() -> set[str]:
    """证件库里有哪些证件类型(供基本情况表附件核对)。"""
    types: set[str] = set()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT metadata_json->>'certificate_type' FROM documents "
                "WHERE project_id IS NULL AND metadata_json->>'certificate_type' <> ''"
            )
            types |= {str(r[0]) for r in cursor.fetchall() if r[0]}
            # 营业执照常在公司证件文件名里,不一定有 certificate_type
            cursor.execute(
                "SELECT 1 FROM documents WHERE project_id IS NULL "
                "AND (file_name ILIKE '%营业执照%' "
                "OR metadata_json->>'certificate_type' ILIKE '%营业执照%') LIMIT 1"
            )
            if cursor.fetchone():
                types.add("营业执照")
    return types


def build_project_conformance_report(
    project_id: int, *, complete: Completion | None = None
) -> ConformanceReport:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT tender_text, confirmed_parsed_json, parsed_json, "
                "selected_personnel FROM projects WHERE id = %s",
                (project_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise ValueError(f"Project {project_id} was not found")

    parsed = row.get("confirmed_parsed_json") or row.get("parsed_json") or {}
    requirements = (
        TenderRequirements.model_validate(parsed) if parsed else None
    )
    spec = build_tender_spec(row.get("tender_text") or "", complete=complete)
    profile = get_company_profile()["profile"]
    pm_requirement = derive_pm_requirement(requirements) if requirements else None
    selected_pm = (row.get("selected_personnel") or {}).get("project_manager")

    report = build_conformance_report(
        project_id=project_id,
        spec=spec,
        profile=profile,
        pm_requirement=pm_requirement,
        selected_pm=selected_pm,
        available_cert_types=_available_cert_types(),
    )
    # 追加:招标第三章「评标办法」的真实评审标准(逐条带条款号),让审查以招标明文标准为准,
    # 而非只靠写死的通用规则。best-effort —— 抽不到/失败时沿用上面的基础报告,绝不阻断。
    try:
        from services.review_method_service import (
            build_review_method,
            review_method_to_requirements,
        )

        review_method = build_review_method(row.get("tender_text") or "", complete=complete)
        report.items.extend(review_method_to_requirements(review_method))
    except Exception:
        logger.warning("追加招标评审标准失败,沿用基础核对报告", exc_info=True)
    return report
