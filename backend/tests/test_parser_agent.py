import json
from pathlib import Path

from agents.parser_agent import (
    _extract_rule_based_requirements,
    _prepare_tender_text,
    parse_tender_response,
)
from prompts.parser_prompt import build_parser_prompt
from schemas.tender import TenderRequirements
from utils.file_parser import extract_text


FIXTURES = Path(__file__).parent / "fixtures"


def test_tender_schema_accepts_expected_fixture() -> None:
    data = json.loads((FIXTURES / "expected_parsed.json").read_text(encoding="utf-8"))

    parsed = TenderRequirements.model_validate(data)

    assert parsed.project_name == "星河湾二期高层住宅施工总承包项目"
    assert len(parsed.qualification_list) == 3
    assert len(parsed.technical_score_items) == 3
    assert len(parsed.invalid_bid_items) == 2


def test_build_parser_prompt_contains_tender_text() -> None:
    messages = build_parser_prompt("项目名称：测试项目")

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "项目名称：测试项目" in messages[1]["content"]
    assert "invalid_bid_items" in messages[1]["content"]


def test_parse_tender_response_strips_markdown_and_trailing_commas() -> None:
    content = """
    ```json
    {
      "project_name": "测试项目",
      "qualification_list": [],
      "technical_score_items": [],
      "invalid_bid_items": [],
    }
    ```
    """

    parsed = parse_tender_response(content)

    assert parsed.project_name == "测试项目"


def test_extract_text_from_txt_path_and_bytes() -> None:
    path_text = extract_text(FIXTURES / "sample_tender.txt")
    bytes_text = extract_text("项目名称：字节测试".encode("utf-8"), filename="sample.txt")

    assert "星河湾二期" in path_text
    assert bytes_text == "项目名称：字节测试"


def test_prepare_tender_text_keeps_relevant_sections() -> None:
    long_text = "\n".join(
        [
            "前言",
            *[f"普通行{i}" for i in range(200)],
            "投标人资格要求：具备施工资质",
            "项目经理须具备二级建造师",
            *[f"更多普通行{i}" for i in range(200)],
            "评分标准：施工组织设计 40 分",
            "否决投标：未提交保证金",
        ]
    )

    focused = _prepare_tender_text(long_text, max_chars=500)

    assert len(focused) <= 500
    assert "投标人资格要求" in focused
    assert "评分标准" in focused
    assert "否决投标" in focused


def test_rule_based_extraction_covers_real_fixture_baseline() -> None:
    cases = [
        FIXTURES / "tenders" / "1招标文件正文.pdf",
        FIXTURES / "tenders" / "2招标文件正文.pdf",
    ]

    for path in cases:
        parsed = _extract_rule_based_requirements(extract_text(path))

        assert parsed.project_name
        assert len(parsed.qualification_list) >= 4
        assert len(parsed.technical_score_items) >= 4
        assert len(parsed.invalid_bid_items) >= 4
