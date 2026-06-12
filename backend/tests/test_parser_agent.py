import json
from pathlib import Path
from types import SimpleNamespace

from agents.parser_agent import (
    _extract_project_name,
    _extract_rule_based_requirements,
    _merge_requirements,
    _prepare_tender_text,
    parse_tender,
    parse_tender_response,
)
from prompts.parser_prompt import build_parser_prompt
from schemas.tender import TenderRequirements
from utils.file_parser import SUPPORTED_EXTENSIONS, extract_text


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
    assert "角色扮演" in messages[0]["content"]
    assert "经验背书" in messages[0]["content"]
    assert "你的任务" in messages[0]["content"]
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


def test_supported_upload_extensions_include_office_and_images() -> None:
    assert {".pdf", ".doc", ".docx", ".txt", ".md", ".jpg", ".jpeg", ".png"}.issubset(
        SUPPORTED_EXTENSIONS
    )


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


def test_extract_project_name_uses_cover_title_before_placeholder() -> None:
    text = """
    萧县2025年农村公路提质改造联网路工程
    （项目编号：EP-XXGC2025024）
    招标文件
    第二章 投标人须知
    项目名称：见投标人须知前附表
    """

    assert _extract_project_name(text) == "萧县2025年农村公路提质改造联网路工程"


def test_extract_project_name_joins_wrapped_project_name() -> None:
    text = """
    第一章 招标公告
    一、项目编号：WH230GL26SG0209
    二、项目名称：南陵县三里镇 2026 年联网路工程(河南路、山施路)
    施工
    三、招标条件
    """

    assert _extract_project_name(text) == "南陵县三里镇 2026 年联网路工程(河南路、山施路)施工"


def test_rule_based_extraction_gets_core_project_fields() -> None:
    text = """
    萧县2025年农村公路提质改造联网路工程
    招标人：萧县交通运输局
    建设地点：萧县境内
    招标范围：农村公路提质改造、排水及交通安全设施工程施工
    计划工期：90日历天
    质量标准：符合国家现行工程质量验收标准规范合格标准
    安全目标：无安全责任事故发生
    投标截止时间：2026年7月1日09时30分
    """

    parsed = _extract_rule_based_requirements(text)

    assert parsed.tenderer_name == "萧县交通运输局"
    assert parsed.project_location == "萧县境内"
    assert "农村公路提质改造" in parsed.tender_scope
    assert parsed.planned_duration == "90日历天"
    assert "合格标准" in parsed.quality_standard
    assert parsed.safety_target == "无安全责任事故发生"
    assert "2026年7月1日" in parsed.bid_deadline


def test_merge_requirements_rejects_placeholder_project_name() -> None:
    rule_based = TenderRequirements(project_name="见投标人须知前附表")
    llm_based = TenderRequirements(
        project_name="萧县2025年农村公路提质改造联网路工程",
        tenderer_name="萧县交通运输局",
        planned_duration="90日历天",
    )

    merged = _merge_requirements(rule_based, llm_based)

    assert merged.project_name == "萧县2025年农村公路提质改造联网路工程"
    assert merged.tenderer_name == "萧县交通运输局"
    assert merged.planned_duration == "90日历天"


def test_parse_tender_falls_back_to_rules_when_llm_returns_non_json(
    monkeypatch,
) -> None:
    text = """
    萧县2025年农村公路提质改造联网路工程
    （项目编号：EP-XXGC2025024）
    项目名称：见投标人须知前附表
    本次招标要求投标人具备独立法人资格或其他组织，具有有效的公路工程施工总承包叁级及以上资质。
    且具备有效的安全生产许可证。
    施工组织设计：40分。
    投标人不按要求提交投标保证金的，评标委员会将否决其投标。
    """

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    monkeypatch.setattr(
        "agents.parser_agent._get_llm_client_config",
        lambda: ("test-key", "http://example.test", "test-model"),
    )
    monkeypatch.setattr("agents.parser_agent.OpenAI", lambda **kwargs: fake_client)

    parsed = parse_tender(text)

    assert parsed.project_name == "萧县2025年农村公路提质改造联网路工程"
    assert parsed.qualification_list
    assert parsed.technical_score_items
    assert parsed.invalid_bid_items


def test_parse_tender_uses_configured_parser_timeout(monkeypatch) -> None:
    captured: dict[str, float] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request_timeout"] = kwargs["timeout"]
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "project_name": "测试项目",
                                    "qualification_list": [],
                                    "technical_score_items": [],
                                    "invalid_bid_items": [],
                                },
                                ensure_ascii=False,
                            )
                        )
                    )
                ]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    def fake_openai(**kwargs):
        captured["client_timeout"] = kwargs["timeout"]
        return fake_client

    monkeypatch.setattr(
        "agents.parser_agent._get_llm_client_config",
        lambda: ("test-key", "http://example.test", "test-model"),
    )
    monkeypatch.setattr(
        "agents.parser_agent.get_settings",
        lambda: SimpleNamespace(parser_llm_timeout_seconds=12),
    )
    monkeypatch.setattr("agents.parser_agent.OpenAI", fake_openai)

    parsed = parse_tender("项目名称：测试项目")

    assert parsed.project_name == "测试项目"
    assert captured == {"client_timeout": 12.0, "request_timeout": 12.0}
