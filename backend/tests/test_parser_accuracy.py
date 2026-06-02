from __future__ import annotations

from pathlib import Path
import os
from unicodedata import normalize

import pytest

from agents.parser_agent import _has_real_key, parse_tender
from core.config import get_settings
from schemas.tender import RequirementItem, TenderRequirements
from utils.file_parser import extract_text


FIXTURES = Path(__file__).parent / "fixtures"
CASES = [
    (
        FIXTURES / "tenders" / "1招标文件正文.pdf",
        FIXTURES / "expected" / "tender_01_expected.json",
    ),
    (
        FIXTURES / "tenders" / "2招标文件正文.pdf",
        FIXTURES / "expected" / "tender_02_expected.json",
    ),
]
MIN_ACCURACY = 0.80


def _compact(text: str) -> str:
    return "".join(normalize("NFKC", text).lower().split())


def _char_recall(expected: str, actual: str) -> float:
    expected_chars = set(_compact(expected))
    actual_chars = set(_compact(actual))
    if not expected_chars:
        return 1.0
    return len(expected_chars & actual_chars) / len(expected_chars)


def _item_text(item: RequirementItem) -> str:
    return f"{item.title} {item.description} {item.source.source_text}"


def _item_hit(expected: RequirementItem, actual_items: list[RequirementItem]) -> bool:
    expected_text = _item_text(expected)
    for actual in actual_items:
        actual_text = _item_text(actual)
        if _char_recall(expected_text, actual_text) >= 0.55:
            return True
    return False


def _list_hits(
    expected_items: list[RequirementItem], actual_items: list[RequirementItem]
) -> tuple[int, int, list[str]]:
    if not expected_items:
        return 0, 0, []
    misses = [
        expected.title
        for expected in expected_items
        if not _item_hit(expected, actual_items)
    ]
    return len(expected_items) - len(misses), len(expected_items), misses


def _accuracy_report(expected: TenderRequirements, actual: TenderRequirements) -> str:
    hits = 0
    total = 0
    misses: list[str] = []

    total += 1
    if _char_recall(expected.project_name, actual.project_name) >= 0.80:
        hits += 1
    else:
        misses.append("project_name")

    for category, expected_items, actual_items in [
        ("qualification_list", expected.qualification_list, actual.qualification_list),
        (
            "technical_score_items",
            expected.technical_score_items,
            actual.technical_score_items,
        ),
        ("invalid_bid_items", expected.invalid_bid_items, actual.invalid_bid_items),
    ]:
        list_hits, list_total, list_misses = _list_hits(expected_items, actual_items)
        hits += list_hits
        total += list_total
        misses.extend(f"{category}:{title}" for title in list_misses)

    accuracy = hits / total if total else 1.0
    return f"accuracy={accuracy:.2%}; hits={hits}/{total}; misses={misses}"


def _has_live_llm_key() -> bool:
    settings = get_settings()
    return _has_real_key(settings.openrouter_api_key) or _has_real_key(
        settings.deepseek_api_key
    )


@pytest.mark.live_llm
@pytest.mark.parametrize(("tender_path", "expected_path"), CASES)
def test_parser_accuracy_against_real_tenders(
    tender_path: Path, expected_path: Path
) -> None:
    if os.getenv("RUN_LIVE_LLM") != "1":
        pytest.skip("Set RUN_LIVE_LLM=1 to run live parser accuracy checks")
    if not _has_live_llm_key():
        pytest.skip("OPENROUTER_API_KEY or DEEPSEEK_API_KEY is required")

    tender_text = extract_text(tender_path)
    expected = TenderRequirements.model_validate_json(
        expected_path.read_text(encoding="utf-8")
    )

    actual = parse_tender(tender_text)
    report = _accuracy_report(expected, actual)
    accuracy_text = report.split(";", 1)[0].split("=", 1)[1].strip().rstrip("%")
    accuracy = float(accuracy_text) / 100

    assert accuracy >= MIN_ACCURACY, (
        f"{tender_path.name} {report}, expected at least {MIN_ACCURACY:.0%}. "
        f"Parsed: {actual.model_dump_json()}"
    )
