import json
from pathlib import Path

from agents.parser_agent import parse_tender_response
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
