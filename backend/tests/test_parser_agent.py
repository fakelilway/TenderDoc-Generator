import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_prepare_tender_text_keeps_bid_format_sections() -> None:
    long_text = "\n".join(
        [
            "前言",
            *[f"普通行{i}" for i in range(200)],
            "第八章 投标文件格式",
            "投标文件（商务文件）",
            "一、投标函",
            "二、法定代表人身份证明",
            "投标文件（技术文件）",
            "施工组织设计",
            "投标文件（报价文件）",
            *[f"更多普通行{i}" for i in range(200)],
        ]
    )

    focused = _prepare_tender_text(long_text, max_chars=500)

    assert len(focused) <= 500
    assert "第八章 投标文件格式" in focused
    assert "投标文件（商务文件）" in focused
    assert "法定代表人身份证明" in focused


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


def test_parse_tender_raises_when_llm_returns_non_json(
    monkeypatch,
) -> None:
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

    with pytest.raises(Exception, match="Parser LLM failed"):
        parse_tender("项目名称：测试项目")


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


def test_parse_tender_repairs_invalid_json_once(monkeypatch) -> None:
    calls: list[list[dict[str, str]]] = []
    broken_json = '{"project_name": "测试项目" "qualification_list": []}'
    repaired_json = json.dumps(
        {
            "project_name": "测试项目",
            "qualification_list": [],
            "technical_score_items": [],
            "invalid_bid_items": [],
        },
        ensure_ascii=False,
    )

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs["messages"])
            content = broken_json if len(calls) == 1 else repaired_json
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    monkeypatch.setattr(
        "agents.parser_agent._get_llm_client_config",
        lambda: ("test-key", "http://example.test", "test-model"),
    )
    monkeypatch.setattr("agents.parser_agent.OpenAI", lambda **kwargs: fake_client)

    parsed = parse_tender("项目名称：测试项目")

    assert parsed.project_name == "测试项目"
    assert len(calls) == 2
    assert "JSON 修复器" in calls[1][0]["content"]


def test_extract_format_requirements_captures_format_chapter():
    from agents.parser_agent import _extract_format_requirements

    text = (
        "第三章 评标办法\n"
        "评标采用综合评估法。\n"
        "投标文件的组成\n"
        "投标文件应包括下列内容：\n"
        "（一）投标函及投标函附录；\n"
        "（二）法定代表人身份证明或授权委托书；\n"
        "（三）投标保证金缴纳凭证。\n"
        "投标文件正本一份，副本四份。\n"
    )
    result = _extract_format_requirements(text)
    assert "投标文件的组成" in result
    assert "投标函及投标函附录" in result
    assert "副本四份" in result


def test_extract_format_requirements_prefers_real_format_chapter_over_toc_noise():
    from agents.parser_agent import _extract_format_requirements

    text = (
        "目录\n"
        "5.投标文件的递交...............................................................6\n"
        "第八章 投标文件格式...........................................................167\n"
        "投标文件（商务文件）.........................................................168\n"
        "5.投标文件的递交\n"
        "投标文件递交的截止时间为 2025 年 07 月 16 日 10 时 00 分。\n"
        "第八章 投标文件格式\n"
        "投标文件（商务文件）\n"
        "一、投标函\n"
        "二、法定代表人身份证明\n"
        "三、授权委托书\n"
        "四、投标保证金\n"
        "五、资格审查资料\n"
        "投标文件（技术文件）\n"
        "一、施工组织设计\n"
        "投标文件（报价文件）\n"
        "一、投标函\n"
        "二、已标价工程量清单\n"
        "第九章 其他资料\n"
        "其他内容。\n"
    )

    result = _extract_format_requirements(text)

    assert "格式章节：第八章 投标文件格式" in result
    assert "商务文件组成：投标函、法定代表人身份证明、授权委托书、投标保证金、资格审查资料。" in result
    assert "技术文件组成：施工组织设计。" in result
    assert "报价文件组成：投标函、已标价工程量清单。" in result
    assert "投标文件的递交................................" not in result
    assert "投标文件递交的截止时间为" not in result
    assert "第九章 其他资料" not in result


def test_extract_format_requirements_fallback_ignores_delivery_and_guarantee_noise():
    from agents.parser_agent import _extract_format_requirements

    text = (
        "5.投标文件的递交...............................................................6\n"
        "第八章 投标文件格式...........................................................167\n"
        "投标文件递交的截止时间为 2025 年 07 月 16 日 10 时 00 分。\n"
        "13.投标保证金账户）：\n"
        "徽商银行 户名：长丰县公共资源交易中心\n"
        "投标报价的其 投标人报价文件投标函填写的投标总报价精确到分\n"
        "3.7.4 非加密投标文 ☑不允许。\n"
        "非加密投标文件由投标人自行确定是否递交。\n"
        "非加密投标文件介质：光盘或U盘\n"
        "非加密投标文件封套：\n"
        "4.1.2 件密封和标记 （招标项目名称） 标段投标文件\n"
        "要求 （非加密投标文件）\n"
    )

    result = _extract_format_requirements(text)

    assert "投标文件的递交" not in result
    assert "投标文件递交的截止时间" not in result
    assert "投标保证金账户" not in result
    assert "户名：长丰县公共资源交易中心" not in result
    assert "投标总报价精确到分" not in result
    assert "非加密投标文件封套" in result
    assert "密封和标记" in result


def test_extract_format_requirements_summarizes_format_chapter_not_raw_forms():
    from agents.parser_agent import _extract_format_requirements

    text = (
        "第九章 投标文件格式\n"
        "投标文件（商务文件）\n"
        "目 录\n"
        "一、投标函\n"
        "二、法定代表人身份证明或授权委托书\n"
        "三、投标保证金\n"
        "致：（招标人）\n"
        "1.我方已仔细研究（招标项目名称） 标段招标文件的全部内容。\n"
        "投标人： （盖单位章）\n"
        "法定代表人： （签字或盖章）\n"
        "投标文件（技术文件）\n"
        "一、施工组织设计\n"
        "投标文件（报价文件）\n"
        "一、投标函\n"
        "二、已标价工程量清单\n"
        "注：投标制作软件中“投标函（商务文件）”节点内容与招标文件中本项“投标函”部分内容不一致。\n"
        "第十章 其他资料\n"
    )

    result = _extract_format_requirements(text)

    assert "格式章节：第九章 投标文件格式" in result
    assert "商务文件组成：投标函、法定代表人身份证明或授权委托书、投标保证金。" in result
    assert "技术文件组成：施工组织设计。" in result
    assert "报价文件组成：投标函、已标价工程量清单。" in result
    assert "签字盖章" in result
    assert "投标制作软件" in result
    assert "我方已仔细研究" not in result
    assert "第十章 其他资料" not in result


def test_extract_format_requirements_captures_scattered_format_clauses():
    from agents.parser_agent import _extract_format_requirements

    text = (
        "第二章 投标人须知\n"
        "3.7.1 投标文件由商务及技术文件、报价文件组成。\n"
        "投标文件应包括投标函、法定代表人身份证明、授权委托书、投标保证金、资格审查资料、承诺函。\n"
        "3.7.3 投标文件应用不褪色材料书写或打印，并由投标人的法定代表人或其委托代理人签字或盖章。\n"
        "3.7.4 投标文件正本一份，副本四份。\n"
        "4.1 密封和标记：投标文件封套应加盖投标人单位章。\n"
        "电子投标文件应按交易系统要求加密上传，未成功解密的按无效投标处理。\n"
        "第三章 评标办法\n"
        "评标采用综合评估法。\n"
    )

    result = _extract_format_requirements(text)

    assert "商务及技术文件、报价文件组成" in result
    assert "法定代表人身份证明" in result
    assert "授权委托书" in result
    assert "签字或盖章" in result
    assert "正本一份，副本四份" in result
    assert "加密上传" in result


def test_merge_requirements_combines_llm_and_rule_format_requirements():
    rule_based = TenderRequirements(
        project_name="测试工程",
        bid_format_requirements="- 投标文件正本一份，副本四份\n- 密封和标记：封套加盖单位章",
    )
    llm_based = TenderRequirements(
        project_name="测试工程",
        bid_format_requirements="- 投标文件包括投标函、授权委托书\n- 投标文件正本一份，副本四份",
    )

    merged = _merge_requirements(rule_based, llm_based)

    assert "投标文件包括投标函、授权委托书" in merged.bid_format_requirements
    assert "投标文件正本一份，副本四份" in merged.bid_format_requirements
    assert "密封和标记：封套加盖单位章" in merged.bid_format_requirements
    assert merged.bid_format_requirements.count("投标文件正本一份，副本四份") == 1


def test_extract_format_requirements_empty_when_no_chapter():
    from agents.parser_agent import _extract_format_requirements

    assert _extract_format_requirements("本项目位于萧县，计划工期90日历天。") == ""
