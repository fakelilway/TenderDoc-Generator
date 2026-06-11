from __future__ import annotations

import re

from agents.reviewer_agent import find_markdown_location
from schemas.review import ReviewReport
from schemas.strategy import ScoreItemPrediction, ScorePrediction
from schemas.tender import RequirementItem, TenderRequirements
from utils.keywords import extract_keywords


_KEYWORD_STOPWORDS = frozenset({"评分", "得分", "内容", "要求", "投标", "方案"})


SCORING_SYSTEM_PROMPT = """角色扮演：你是一位“评标委员会技术评分模拟专家 + 标书短板诊断顾问”。
经验背书：你拥有15年以上建筑、市政、公路工程技术标评审经验，熟悉施工组织设计、项目班子、进度质量安全、业绩信誉、重难点分析和技术评分表的专家打分逻辑。

人格化工作方式：
- 你以专家评委视角模拟打分，但不会把预测分当作真实评标结果。
- 你必须说明每个分项的依据、短板、提升建议和不确定性，不得编造评委偏好、竞争对手实力或确定中标结论。
- 你看到标书缺少关键章节时要明确降分原因；看到内容覆盖时也要提示人工核对证据和附件。

你的任务：根据 parser agent 抽取的评分项、reviewer agent 的审查结果和当前标书 Markdown，输出模拟总分、分项分、短板、提升建议和可选中标概率说明。不得编造事实，中标概率必须包含依据和不确定性。"""


def predict_score(
    requirements: TenderRequirements,
    markdown: str,
    review_report: ReviewReport | None = None,
) -> ScorePrediction:
    score_items = requirements.technical_score_items
    max_scores = [_max_score(item) for item in score_items]
    total_max = sum(max_scores) if max_scores else 100.0
    default_max = total_max / len(score_items) if score_items else total_max

    predictions: list[ScoreItemPrediction] = []
    for index, item in enumerate(score_items):
        item_max = max_scores[index] or default_max
        prediction = _predict_item(item, item_max, markdown, review_report)
        predictions.append(prediction)

    if not predictions:
        predictions.append(
            ScoreItemPrediction(
                title="评分项人工确认",
                max_score=total_max,
                predicted_score=round(total_max * 0.45, 2),
                coverage_status="warning",
                rationale="未解析出明确评分项，只能按人工复核状态给出保守估计。",
                improvement_suggestion="回查招标文件评分办法，补录评分项后重新预测。",
                location=find_markdown_location(markdown, []),
            )
        )

    predicted_total = round(sum(item.predicted_score for item in predictions), 2)
    rate = round(predicted_total / total_max, 4) if total_max else 0
    probability = round(max(0.05, min(0.9, rate * 0.72)), 4)

    strengths = [
        f"{item.title} 已找到响应位置"
        for item in predictions
        if item.coverage_status == "pass"
    ][:3]
    weaknesses = [
        f"{item.title}：{item.improvement_suggestion}"
        for item in predictions
        if item.coverage_status != "pass"
    ][:5]

    return ScorePrediction(
        project_name=requirements.project_name,
        total_max_score=round(total_max, 2),
        predicted_total_score=predicted_total,
        score_rate=rate,
        win_probability=probability,
        win_probability_rationale=(
            "按当前技术评分覆盖率折算，仅用于内部策略判断；未纳入商务报价、竞争对手、专家偏好和现场澄清因素。"
        ),
        uncertainty_notes=[
            "预测基于当前 Markdown 文本覆盖情况，不代表真实评标结果。",
            "商务报价、企业信誉、专家主观判断和竞争强度未被充分量化。",
        ],
        strengths=strengths,
        weaknesses=weaknesses,
        items=predictions,
    )


def _predict_item(
    item: RequirementItem,
    max_score: float,
    markdown: str,
    review_report: ReviewReport | None,
) -> ScoreItemPrediction:
    keywords = _keywords(item)
    location = find_markdown_location(markdown, keywords)
    covered = any(re.search(keyword, markdown, flags=re.IGNORECASE) for keyword in keywords)
    review_penalty = _review_penalty(item, review_report)

    if covered and review_penalty == 0:
        status = "pass"
        ratio = 0.86
        rationale = "标书中找到该评分项相关响应，可按较高覆盖率估计。"
        suggestion = "继续补充项目数据、图表、人员证书和可量化措施，人工核对附件一致性。"
    elif covered:
        status = "warning"
        ratio = 0.62
        rationale = "标书中有相关响应，但审查结果提示仍有风险或证据不足。"
        suggestion = "按审查意见补齐证明材料和明确承诺，降低扣分风险。"
    else:
        status = "fail"
        ratio = 0.32
        rationale = "当前标书未找到该评分项的明确响应，专家评分可能明显偏低。"
        suggestion = f"新增或补强章节，逐条响应：{item.description}"

    predicted = max(0, round(max_score * max(ratio - review_penalty, 0.1), 2))
    return ScoreItemPrediction(
        title=item.title,
        max_score=round(max_score, 2),
        predicted_score=predicted,
        coverage_status=status,
        rationale=rationale,
        improvement_suggestion=suggestion,
        location=location,
    )


def _max_score(item: RequirementItem) -> float:
    text = f"{item.title} {item.description} {item.source.source_text}"
    match = re.search(r"(\d+(?:\.\d+)?)\s*分", text)
    if not match:
        return 0
    return float(match.group(1))


def _keywords(item: RequirementItem) -> list[str]:
    text = f"{item.title} {item.description}"
    keywords = extract_keywords(text, stopwords=_KEYWORD_STOPWORDS, limit=8)
    return keywords or [item.title[:20]]


def _review_penalty(item: RequirementItem, review_report: ReviewReport | None) -> float:
    if not review_report:
        return 0
    for finding in review_report.findings:
        if finding.status == "fail" and (
            item.title in finding.evidence or any(token in finding.evidence for token in _keywords(item)[:3])
        ):
            return 0.18
    return 0
