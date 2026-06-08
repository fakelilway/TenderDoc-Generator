"""Quality evaluation harness for the bid generation pipeline (M59).

The harness scores AI output against a reference evaluation set built from real
(desensitised) tender + human bid pairs. It computes five tracked indicators:

* ``parse_accuracy`` – how well the parser output matches the ground truth
* ``section_completeness`` – fraction of reference bid sections that appear
* ``invalid_detection_rate`` – fraction of 废标项 addressed in the draft (matched
  by each item's ``keyword``, i.e. the subject that appears once responded to)
* ``manual_edit_ratio`` – how far the AI draft is from the final human bid
* ``elapsed_seconds`` – per-case processing time (aggregated as total / average)

All scoring functions are pure so they run offline and deterministically; the
``scripts/run_quality_eval.py`` CLI wires the fixture set through them, renders a
Markdown/JSON report and appends each run to a history file for trend tracking.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any

RATIO_KEYS = (
    "parse_accuracy",
    "section_completeness",
    "invalid_detection_rate",
    "manual_edit_ratio",
)
METRIC_LABELS = {
    "parse_accuracy": "解析准确率",
    "section_completeness": "章节完整率",
    "invalid_detection_rate": "废标检出率",
    "manual_edit_ratio": "人工修改量",
    "avg_elapsed_seconds": "平均耗时(秒)",
    "total_elapsed_seconds": "总耗时(秒)",
}

_TITLE_MATCH_THRESHOLD = 0.6


def _normalize(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def text_similarity(left: Any, right: Any) -> float:
    left_norm, right_norm = _normalize(left), _normalize(right)
    if not left_norm and not right_norm:
        return 1.0
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _titles(items: list[Any]) -> list[str]:
    titles = []
    for item in items or []:
        if isinstance(item, dict):
            titles.append(_normalize(item.get("title", "")))
        else:
            titles.append(_normalize(item))
    return [title for title in titles if title]


def title_overlap_f1(predicted: list[Any], expected: list[Any]) -> float:
    predicted_titles = _titles(predicted)
    expected_titles = _titles(expected)
    if not predicted_titles and not expected_titles:
        return 1.0
    if not predicted_titles or not expected_titles:
        return 0.0

    matched_expected = sum(
        1
        for exp in expected_titles
        if any(text_similarity(exp, pred) >= _TITLE_MATCH_THRESHOLD for pred in predicted_titles)
    )
    matched_predicted = sum(
        1
        for pred in predicted_titles
        if any(text_similarity(exp, pred) >= _TITLE_MATCH_THRESHOLD for exp in expected_titles)
    )
    recall = matched_expected / len(expected_titles)
    precision = matched_predicted / len(predicted_titles)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def parse_accuracy(parsed: dict[str, Any], expected: dict[str, Any]) -> float:
    scores = [text_similarity(parsed.get("project_name"), expected.get("project_name"))]
    for field_name in ("qualification_list", "technical_score_items", "invalid_bid_items"):
        scores.append(
            title_overlap_f1(parsed.get(field_name) or [], expected.get(field_name) or [])
        )
    return round(mean(scores), 4)


def section_completeness(generated_markdown: str, reference_sections: list[str]) -> float:
    if not reference_sections:
        return 1.0
    text = _normalize(generated_markdown)
    matched = sum(1 for section in reference_sections if _normalize(section) in text)
    return round(matched / len(reference_sections), 4)


def invalid_detection_rate(
    generated_markdown: str,
    expected_invalid_items: list[Any],
) -> float:
    if not expected_invalid_items:
        return 1.0
    text = _normalize(generated_markdown)
    detected = 0
    for item in expected_invalid_items:
        if isinstance(item, dict):
            key = item.get("keyword") or item.get("title", "")
        else:
            key = item
        key_norm = _normalize(key)
        if key_norm and key_norm in text:
            detected += 1
    return round(detected / len(expected_invalid_items), 4)


def manual_edit_ratio(generated_markdown: str, reference_markdown: str) -> float:
    if not reference_markdown:
        return 0.0
    ratio = SequenceMatcher(None, generated_markdown or "", reference_markdown).ratio()
    return round(1 - ratio, 4)


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    generated = case.get("generated_markdown", "")
    metrics = {
        "parse_accuracy": parse_accuracy(
            case.get("parsed") or {}, case.get("expected_parsed") or {}
        ),
        "section_completeness": section_completeness(
            generated, case.get("reference_sections") or []
        ),
        "invalid_detection_rate": invalid_detection_rate(
            generated, case.get("expected_invalid_items") or []
        ),
        "manual_edit_ratio": manual_edit_ratio(
            generated, case.get("reference_markdown", "")
        ),
        "elapsed_seconds": round(float(case.get("elapsed_seconds", 0.0)), 4),
    }
    return {"name": case.get("name", ""), "metrics": metrics}


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    agg: dict[str, Any] = {}
    for key in RATIO_KEYS:
        values = [r["metrics"][key] for r in results if r["metrics"].get(key) is not None]
        agg[key] = round(mean(values), 4) if values else 0.0
    elapsed = [r["metrics"].get("elapsed_seconds", 0.0) for r in results]
    agg["total_elapsed_seconds"] = round(sum(elapsed), 4)
    agg["avg_elapsed_seconds"] = round(mean(elapsed), 4) if elapsed else 0.0
    agg["case_count"] = len(results)
    return agg


def build_report(
    results: list[dict[str, Any]],
    version: str = "",
    generated_at: str = "",
) -> dict[str, Any]:
    return {
        "version": version,
        "generated_at": generated_at,
        "case_count": len(results),
        "aggregate": aggregate(results),
        "cases": results,
    }


def run_eval(
    eval_set: list[dict[str, Any]],
    version: str = "",
    generated_at: str = "",
) -> dict[str, Any]:
    results = [evaluate_case(case) for case in eval_set]
    return build_report(results, version=version, generated_at=generated_at)


def load_eval_set(manifest_path: str | Path) -> list[dict[str, Any]]:
    """Load the evaluation set referenced by a manifest JSON file.

    The manifest is ``{"cases": ["case_a.json", ...]}`` with paths relative to
    the manifest's directory. Each case file is loaded as a case dict.
    """
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    base_dir = manifest_file.parent
    cases: list[dict[str, Any]] = []
    for entry in manifest.get("cases", []):
        case_path = base_dir / entry
        cases.append(json.loads(case_path.read_text(encoding="utf-8")))
    return cases


def render_markdown_report(
    report: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> str:
    aggregate_metrics = report.get("aggregate", {})
    lines = [
        "# 投标质量评估报告",
        "",
        f"- 版本：{report.get('version') or '-'}",
        f"- 生成时间：{report.get('generated_at') or '-'}",
        f"- 样本数：{report.get('case_count', 0)}",
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
    ]
    for key in ("parse_accuracy", "section_completeness", "invalid_detection_rate", "manual_edit_ratio", "avg_elapsed_seconds", "total_elapsed_seconds"):
        label = METRIC_LABELS.get(key, key)
        lines.append(f"| {label} | {aggregate_metrics.get(key, 0.0)} |")

    lines += ["", "## 样本明细", "", "| 样本 | 解析准确率 | 章节完整率 | 废标检出率 | 人工修改量 | 耗时(秒) |", "| --- | --- | --- | --- | --- | --- |"]
    for case in report.get("cases", []):
        metrics = case.get("metrics", {})
        lines.append(
            "| {name} | {pa} | {sc} | {idr} | {mer} | {elapsed} |".format(
                name=case.get("name", ""),
                pa=metrics.get("parse_accuracy", 0.0),
                sc=metrics.get("section_completeness", 0.0),
                idr=metrics.get("invalid_detection_rate", 0.0),
                mer=metrics.get("manual_edit_ratio", 0.0),
                elapsed=metrics.get("elapsed_seconds", 0.0),
            )
        )

    if history:
        lines += ["", "## 版本趋势", "", "| 版本 | 解析准确率 | 章节完整率 | 废标检出率 | 人工修改量 | 总耗时(秒) |", "| --- | --- | --- | --- | --- | --- |"]
        for entry in history[-10:]:
            agg = entry.get("aggregate", {})
            lines.append(
                "| {version} | {pa} | {sc} | {idr} | {mer} | {total} |".format(
                    version=entry.get("version") or entry.get("generated_at") or "-",
                    pa=agg.get("parse_accuracy", 0.0),
                    sc=agg.get("section_completeness", 0.0),
                    idr=agg.get("invalid_detection_rate", 0.0),
                    mer=agg.get("manual_edit_ratio", 0.0),
                    total=agg.get("total_elapsed_seconds", 0.0),
                )
            )

    return "\n".join(lines) + "\n"


def load_history(history_path: str | Path) -> list[dict[str, Any]]:
    path = Path(history_path)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def append_history(history_path: str | Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "version": report.get("version", ""),
        "generated_at": report.get("generated_at", ""),
        "case_count": report.get("case_count", 0),
        "aggregate": report.get("aggregate", {}),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return load_history(path)
