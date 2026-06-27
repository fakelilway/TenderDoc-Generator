"""V2-M5 Three-Layer Audit — format, content, and evidence verification.

Layer 1 (Format Audit): Deterministic comparison of original template vs filled output.
Layer 2 (Content Audit): LLM-based check for 废标 risks, AI meta-text, factual errors.
Layer 3 (Evidence Audit): Deterministic verification that filled fields match knowledge base.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class AuditIssue:
    layer: str  # "format" | "content" | "evidence"
    severity: str  # "critical" | "major" | "minor"
    location: str  # section/node title
    problem: str
    detail: str = ""


@dataclass
class AuditReport:
    passed: bool
    issues: list[AuditIssue] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def summary(self) -> str:
        if self.passed:
            return "审查全部通过，未发现格式、内容或证据问题。"
        parts = [f"格式审计: {self._count_by_layer('format')} 问题, "
                 f"内容审计: {self._count_by_layer('content')} 问题, "
                 f"证据审计: {self._count_by_layer('evidence')} 问题"]
        return "；".join(parts)

    def _count_by_layer(self, layer: str) -> int:
        return sum(1 for i in self.issues if i.layer == layer)


def audit_format_layer(
    pages: list[tuple[str, str]],  # (title, original_template)
    filled_pages: list[tuple[str, str]],  # (title, filled_template)
) -> AuditReport:
    """Layer 1: Verify format integrity via deterministic text comparison.

    Checks:
    - Page count matches
    - Title matches (form name preserved)
    - Key structural elements preserved (signature blocks, table headers, 下划线)
    """
    issues: list[AuditIssue] = []
    original_map = {t: o for t, o in pages}
    filled_map = {t: f for t, f in filled_pages}

    # Check page count
    if len(pages) != len(filled_pages):
        issues.append(AuditIssue(
            layer="format", severity="critical", location="全局",
            problem=f"格式页数量不匹配: 原始 {len(pages)} 页, 填充后 {len(filled_pages)} 页"
        ))

    for title, original in original_map.items():
        filled = filled_map.get(title, "")

        if not filled:
            issues.append(AuditIssue(
                layer="format", severity="critical", location=title,
                problem="该格式页在填充后丢失"
            ))
            continue

        # Check signature/seal blocks preserved
        seal_indicators = ['（盖单位章）', '(盖单位章)', '（签字）', '(签字)', '（盖章）']
        for indicator in seal_indicators:
            if indicator in original and indicator not in filled:
                issues.append(AuditIssue(
                    layer="format", severity="critical", location=title,
                    problem=f"签字盖章位丢失: {indicator}",
                    detail=f"原始包含 '{indicator}'，填充后缺失"
                ))

        # Check ________ blanks not completely removed
        original_blanks = len(re.findall(r'[_＿]{3,}', original))
        filled_blanks = len(re.findall(r'[_＿]{3,}', filled))
        if original_blanks > 0 and filled_blanks == 0 and original_blanks > 3:
            # All blanks filled — could mean LLM fabricated data
            issues.append(AuditIssue(
                layer="format", severity="major", location=title,
                problem=f"所有空白位被填满（共 {original_blanks} 处），可能编造了数据",
                detail="请人工核实填入数据的真实性"
            ))

        if _requires_table_layout(title, original) and not _has_table_layout(filled):
            issues.append(AuditIssue(
                layer="format",
                severity="critical",
                location=title,
                problem="表格格式被拍扁为普通文本",
                detail="该节点在招标文件中属于表格/清单/附表，生成结果必须保留表格网格、字段位置和空白填写位。"
            ))

        if _uses_reconstructed_layout(filled):
            issues.append(AuditIssue(
                layer="format",
                severity="critical",
                location=title,
                problem="锁定格式被系统重画，不是招标文件原样复制",
                detail="商务/报价锁定格式必须来自招标文件原始格式块；禁止用系统内置表格或近似版式替代。"
            ))

        if _requires_fill_in_lines(original) and not _has_fill_in_lines(filled):
            issues.append(AuditIssue(
                layer="format",
                severity="major",
                location=title,
                problem="下划线填写位未保留",
                detail="招标文件格式包含下划线/空白填写位，生成结果应保留可人工填写的下划线或等价占位。"
            ))

        if _requires_figure_or_chart(title, original) and not _has_figure_or_chart(filled):
            issues.append(AuditIssue(
                layer="format",
                severity="critical",
                location=title,
                problem="图表/图片要求未落实",
                detail="招标文件要求提供图、表、组织机构图、进度图或平面布置图，生成结果必须插入对应图表或保留明确图片占位。"
            ))

        # Check for AI meta-text in form pages (should not appear in locked zones)
        ai_markers = ['人工确认点', '待补充', 'TODO', 'AI生成', '根据提示', '元话语']
        for marker in ai_markers:
            if marker in filled and marker not in original:
                issues.append(AuditIssue(
                    layer="content", severity="minor", location=title,
                    problem=f"锁定区出现 AI 元文本: '{marker}'"
                ))

    return AuditReport(passed=len(issues) == 0, issues=issues)


def _requires_table_layout(title: str, original: str) -> bool:
    text = f"{title}\n{original}"
    table_keywords = (
        "基本情况表",
        "人员组成表",
        "项目管理机构",
        "拟分包",
        "汇总表",
        "明细表",
        "一览表",
        "附表",
        "清单",
    )
    if any(keyword in text for keyword in table_keywords):
        return True
    return "|" in original or "｜" in original


def _has_table_layout(filled: str) -> bool:
    lines = [line.strip() for line in filled.splitlines() if line.strip()]
    pipe_rows = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(pipe_rows) >= 2:
        return True
    table_border_chars = "┌┬┐├┼┤└┴┘"
    return any(char in filled for char in table_border_chars)


def _requires_fill_in_lines(original: str) -> bool:
    return bool(re.search(r'[_＿]{3,}|〔\s*〕|（\s*）|\(\s*\)', original))


def _has_fill_in_lines(filled: str) -> bool:
    return bool(re.search(r'[_＿]{3,}|<u>.+?</u>|〔[^〕]+〕', filled))


def _uses_reconstructed_layout(filled: str) -> bool:
    return "{{tdg_table:" in filled


def _requires_figure_or_chart(title: str, original: str) -> bool:
    text = f"{title}\n{original}"
    figure_keywords = (
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
    return any(keyword in text for keyword in figure_keywords)


def _has_figure_or_chart(filled: str) -> bool:
    return bool(
        "{{knowledge_image:" in filled
        or re.search(r'!\[[^\]]*\]\([^)]+\)', filled)
        or "【图表占位" in filled
        or "【图片占位" in filled
    )


def audit_evidence_layer(
    filled_fields: list[dict[str, Any]],  # {label, value, expected_from_profile}
    profile: dict[str, str],
) -> AuditReport:
    """Layer 3: Verify filled fields match company profile/knowledge base.

    Checks:
    - Filled values match known profile data
    - Mandatory fields are not left empty
    - No fabricated values that contradict known data
    """
    issues: list[AuditIssue] = []

    critical_fields = ['投标人', '法定代表人', '营业执照号', '安全生产许可证', '项目经理']

    for field in filled_fields:
        label = str(field.get("label", ""))
        value = str(field.get("value", ""))
        profile_key = str(field.get("profile_key", ""))
        expected = profile.get(profile_key, "")

        # Missing critical field
        if value in ("________", "") and label in critical_fields:
            issues.append(AuditIssue(
                layer="evidence", severity="critical", location=label,
                problem=f"关键字段未填写: {label}",
                detail="填入人工确认点或补充公司档案资料"
            ))

        # Filled value doesn't match known profile
        if expected and value and value != "________":
            # Strip whitespace and compare
            if value.strip() != expected.strip():
                issues.append(AuditIssue(
                    layer="evidence", severity="major", location=label,
                    problem=f"填入值与公司档案不一致",
                    detail=f"填入: '{value[:40]}', 档案: '{expected[:40]}'"
                ))

    return AuditReport(passed=len(issues) == 0, issues=issues)


def audit_content_layer(
    prose_text: str,
    project_name: str,
    requirements: dict[str, Any],
) -> AuditReport:
    """Layer 2: Check prose content via deterministic heuristics.

    No LLM — uses pattern matching to detect common content issues.
    LLM-based content audit should be added as a separate pass when needed.
    """
    issues: list[AuditIssue] = []

    # Minimum content check
    meaningful = [l for l in prose_text.splitlines()
                  if l.strip() and not l.strip().startswith('#')]
    if len(meaningful) < 5:
        issues.append(AuditIssue(
            layer="content", severity="critical", location="施工方案",
            problem=f"施工方案内容过少（仅 {len(meaningful)} 行有效文本）"
        ))

    # AI meta-text
    ai_patterns = [
        (r'人工确认点', '包含"人工确认点"元话语'),
        (r'TODO|待补充', '包含待办标记'),
        (r'AI生成|由AI|人工智能', '出现AI自指'),
        (r'作为.*助手|根据您的要求', 'AI助手语气'),
        (r'我们建议|建议您|建议采用|推荐采用.*方案', '推测性建议（可能不符实际）'),
    ]
    for pattern, desc in ai_patterns:
        if re.search(pattern, prose_text):
            issues.append(AuditIssue(
                layer="content", severity="major", location="施工方案",
                problem=desc
            ))

    # Fabricated data patterns
    if re.search(r'\d{18}[0-9Xx]', prose_text):
        issues.append(AuditIssue(
            layer="content", severity="critical", location="施工方案",
            problem="检测到身份证号（可能编造个人信息）"
        ))

    if re.search(r'(?:¥|￥)\s*\d[\d,.]*\s*(?:万|元)', prose_text):
        issues.append(AuditIssue(
            layer="content", severity="major", location="施工方案",
            problem="检测到金额数据（施工方案不应含报价）"
        ))

    # Project name consistency
    if project_name and project_name not in prose_text[:1000]:
        issues.append(AuditIssue(
            layer="content", severity="minor", location="施工方案",
            problem="正文开头未提及项目名称，缺乏针对性"
        ))

    return AuditReport(passed=len(issues) == 0, issues=issues)


# ── Layer 2b: 招标覆盖校验(交卷前硬闸) ─────────────────────────────────
#
# 逐条核对"招标评分点是否正面响应、废标项是否实质规避"。这是出标前最后一道闸:
#   废标项未实质规避 → critical(阻断出标);评分项未正面响应 → major(告警不阻断)。
# 与上面三层(格式/内容/证据)只看排版/PII 不同,这一层直接对招标硬要求做覆盖判定。
# judge 默认走 LLM 语义判定(prompts/coverage_audit_prompt);LLM 不可用/异常时降级为
# bigram 重叠的强匹配,且对废标项从严。judge 可注入,便于测试不打真 LLM。

CoverageJudge = Callable[[str, list[dict[str, Any]]], "list[bool] | None"]


@dataclass
class CoverageVerdict:
    kind: str  # "废标" | "评分"
    title: str
    description: str
    covered: bool


def _coverage_items(
    invalid_items: list[Any], score_items: list[Any]
) -> list[dict[str, Any]]:
    """归一化要求项。兼容 dict 与 Pydantic 对象(RequirementItem)——后者若被静默丢弃,
    会出现"0 项→直接放行→废标项漏'该拦没拦'"的危险假阴性。"""
    items: list[dict[str, Any]] = []
    for kind, src in (("废标", invalid_items), ("评分", score_items)):
        for it in src or []:
            if isinstance(it, dict):
                title = str(it.get("title", "") or "")
                desc = str(it.get("description", "") or "")
            else:
                title = str(getattr(it, "title", "") or "")
                desc = str(getattr(it, "description", "") or "")
            if title or desc:
                items.append({"kind": kind, "title": title, "description": desc})
    return items


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text or "")
    return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else set()


def _heuristic_coverage(prose_text: str, items: list[dict[str, Any]]) -> list[bool]:
    """LLM 不可用/被截断时的兜底:按 bigram 重叠判覆盖。废标项阈值更高(从严)。

    title 与 description 各自求 bigram 再并集——避免拼接边界处生出跨界假 bigram。
    """
    prose_bg = _bigrams(prose_text)
    flags: list[bool] = []
    for it in items:
        item_bg = _bigrams(it.get("title", "") or "") | _bigrams(
            it.get("description", "") or ""
        )
        if not item_bg:
            flags.append(False)
            continue
        overlap = len(item_bg & prose_bg) / len(item_bg)
        threshold = 0.55 if it.get("kind") == "废标" else 0.45
        flags.append(overlap >= threshold)
    return flags


def _coverage_complete(messages: list[dict[str, str]], *, item_count: int = 0) -> str:
    from openai import OpenAI

    from agents.parser_agent import _get_llm_client_config
    from core.config import get_settings
    from core.llm_client import chat_completion

    settings = get_settings()
    api_key, base_url, model = _get_llm_client_config()
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = chat_completion(
        client,
        model=model,
        messages=messages,
        temperature=0.0,
        # 输出仅 index+covered,但条目多时仍要留足,否则 JSON 被截断→解析失败→全量误拦。
        max_tokens=min(16000, 1200 + 80 * max(0, item_count)),
        timeout=float(getattr(settings, "bid_long_context_timeout_seconds", 300) or 300),
    )
    return response.choices[0].message.content or ""


def _default_coverage_judge(
    prose_text: str, items: list[dict[str, Any]]
) -> list[bool] | None:
    from prompts.coverage_audit_prompt import (
        build_coverage_audit_prompt,
        parse_coverage_verdicts,
    )

    raw = _coverage_complete(
        build_coverage_audit_prompt(prose_text, items), item_count=len(items)
    )
    # 解析失败/无 verdicts → None,交由 evaluate_coverage 降级 bigram(不可静默全判未覆盖)。
    return parse_coverage_verdicts(raw, len(items))


def evaluate_coverage(
    prose_text: str,
    invalid_items: list[Any],
    score_items: list[Any],
    *,
    judge: CoverageJudge | None = None,
) -> list[CoverageVerdict]:
    """逐条判断标书正文是否实质响应了招标评分点/废标项。返回 verdict 列表(供闸/补写共用)。

    判定**按类型不对称**(这是安全核心):
    - **废标项(critical)**:只认 LLM 从严判 True。LLM 不可用/解析失败/长度不符/未判到 →
      一律判**未覆盖**→critical 硬拦(用户铁律"废标宁可误拦不可漏拦")。**绝不靠 bigram 判通过**——
      废标项的 title/description 是否决条款原文,标书常把禁止条款抄进"我方承诺不…",bigram 只衡量
      "话题是否出现"而非"是否实质规避",靠它放行会把真违规误判成已覆盖→放走废标。
    - **评分项(major,仅告警)**:LLM 判 True 或 bigram 命中即算覆盖。误判代价小,放宽以减少
      LLM 不可用/被截断时的虚假告警。

    这样"防 LLM 解析失败永久卡死"的放宽只施加在评分项上,绝不外溢到废标项。
    """
    from core.config import get_settings

    if not getattr(get_settings(), "enable_coverage_audit", True):
        return []  # 配置关闭整套招标覆盖校验(成本/时延逃生开关)

    items = _coverage_items(invalid_items, score_items)
    if not items:
        return []
    full_prose = prose_text or ""
    try:
        llm_flags = (judge or _default_coverage_judge)(full_prose, items)
    except Exception:
        logger.warning("招标覆盖校验 LLM 判定异常,废标项从严判未覆盖", exc_info=True)
        llm_flags = None

    have_llm = isinstance(llm_flags, list) and len(llm_flags) == len(items)
    # bigram 只用于"放宽评分项";废标项绝不参与(见 docstring)。
    bigram_flags = _heuristic_coverage(full_prose, items)

    verdicts: list[CoverageVerdict] = []
    for i, it in enumerate(items):
        llm_cov = have_llm and bool(llm_flags[i])
        if it["kind"] == "废标":
            covered = llm_cov  # 仅 LLM 明确判 True;否则未覆盖→critical
        else:  # 评分:LLM 判 True 或 bigram 命中
            covered = llm_cov or bool(bigram_flags[i])
        verdicts.append(
            CoverageVerdict(
                kind=it["kind"],
                title=it["title"],
                description=it["description"],
                covered=covered,
            )
        )
    return verdicts


def audit_coverage_layer(
    prose_text: str,
    requirements: dict[str, Any],
    *,
    judge: CoverageJudge | None = None,
) -> AuditReport:
    """Layer 2b: 招标覆盖校验。废标项漏=critical(阻断),评分项漏=major(告警)。"""
    verdicts = evaluate_coverage(
        prose_text,
        requirements.get("invalid_bid_items") or [],
        requirements.get("technical_score_items") or [],
        judge=judge,
    )
    # 废标项未规避默认 critical(硬拦);但当前废标项里混有"初步评审不通过/报价超限价"等规则类
    # 条款,任何标书都不会专门写段去响应→会对每份标误拦锁死。故由 coverage_audit_block_invalid
    # 控制:False(默认)=降为 major 告警不拦(防锁死),P1 把废标项分类后再设 True 切回硬拦。
    from core.config import get_settings

    invalid_severity = (
        "critical"
        if getattr(get_settings(), "coverage_audit_block_invalid", False)
        else "major"
    )
    issues: list[AuditIssue] = []
    for v in verdicts:
        if v.covered:
            continue
        label = v.title or (v.description[:30] if v.description else v.kind)
        if v.kind == "废标":
            issues.append(
                AuditIssue(
                    layer="content",
                    severity=invalid_severity,
                    location=v.title or "废标项",
                    problem=f"废标红线未实质规避：{label}",
                    detail=(v.description or "")[:200],
                )
            )
        else:
            issues.append(
                AuditIssue(
                    layer="content",
                    severity="major",
                    location=v.title or "评分点",
                    problem=f"评分点未正面响应：{label}",
                    detail=(v.description or "")[:200],
                )
            )
    return AuditReport(passed=len(issues) == 0, issues=issues)


# ── Convenience: single-pass audit ────────────────────────────────────

@dataclass
class AuditResult:
    passed: bool
    format_issues: list[AuditIssue]
    content_issues: list[AuditIssue]
    evidence_issues: list[AuditIssue]
    coverage_issues: list[AuditIssue] = field(default_factory=list)

    @property
    def all_issues(self) -> list[AuditIssue]:
        return (
            self.format_issues
            + self.content_issues
            + self.evidence_issues
            + self.coverage_issues
        )


def full_audit(
    *,
    pages: list[tuple[str, str]],
    filled_pages: list[tuple[str, str]],
    prose_text: str,
    project_name: str,
    requirements: dict[str, Any],
    filled_fields: list[dict[str, Any]],
    profile: dict[str, str],
    coverage_text: str = "",
    coverage_judge: CoverageJudge | None = None,
) -> AuditResult:
    """Run all audit layers and aggregate. ``coverage_text`` 默认用 ``prose_text``;
    传入"商务+技术+报价"全卷正文可避免"某废标项在商务卷已响应却被误判漏"的假阳性。"""
    format_result = audit_format_layer(pages, filled_pages)
    content_result = audit_content_layer(prose_text, project_name, requirements)
    evidence_result = audit_evidence_layer(filled_fields, profile)
    coverage_result = audit_coverage_layer(
        coverage_text or prose_text, requirements, judge=coverage_judge
    )

    return AuditResult(
        passed=(
            format_result.passed
            and content_result.passed
            and evidence_result.passed
            and coverage_result.passed
        ),
        format_issues=format_result.issues,
        content_issues=content_result.issues,
        evidence_issues=evidence_result.issues,
        coverage_issues=coverage_result.issues,
    )
