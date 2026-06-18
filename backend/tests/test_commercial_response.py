"""商务文件「通读整本招标 → 生成商务响应」的提示词与服务测试(注入假 LLM,不真调)。"""

from __future__ import annotations

from prompts.commercial_response_prompt import build_commercial_response_prompt
from services import commercial_response_service
from schemas.tender import TenderRequirements, RequirementItem


def _req() -> TenderRequirements:
    return TenderRequirements(
        project_name="某公路提质改造工程",
        tenderer_name="某县交通运输局",
        planned_duration="90 日历天",
        bid_deadline="2026-07-01",
        qualification_list=[
            RequirementItem(title="施工资质", description="公路工程施工总承包三级及以上"),
        ],
    )


_PROFILE = {
    "company_name": "安徽正奇建设有限公司",
    "qualification_grade": "公路工程施工总承包二级",
    "credit_code": "91340000MA2ABCDE3K",
    "project_manager_name": "李明",
    "project_manager_cert": "皖一级建造师A123456",
}


def test_prompt_feeds_full_tender_and_covers_four_areas() -> None:
    tender = "第二章 投标人须知前附表\n工期：90 日历天；投标有效期：90 天；缺陷责任期：2 年。"
    messages = build_commercial_response_prompt(
        requirements=_req().model_dump(), tender_text=tender, profile=_PROFILE
    )
    user = messages[-1]["content"]
    # 招标全文整本进 prompt(含具体条款)
    assert "## 招标文件全文" in user
    assert "缺陷责任期：2 年" in user
    # 四块都在
    assert "一、资格审查响应" in user
    assert "二、商务条款偏离表" in user
    assert "三、声明与承诺" in user
    assert "四、投标函关键值一致性" in user
    # 我方档案事实 + 解析出的资格条件
    assert "公路工程施工总承包二级" in user
    assert "公路工程施工总承包三级及以上" in user
    # 关键硬规则:不编造金额/留人工确认
    assert "________" in user and "待人工确认" in user


def test_service_wraps_llm_markdown_with_appendix_header() -> None:
    captured: dict = {}

    def fake_complete(messages):
        captured["messages"] = messages
        return "## 一、资格审查响应\n\n| 招标资格要求 | 我方情况 |\n| --- | --- |\n| 公路三级及以上 | 公路二级，满足 |\n"

    out = commercial_response_service.generate_commercial_responses(
        _req(), "招标全文：公路三级及以上。", _PROFILE, complete=fake_complete
    )
    # 包了附录标题 + 定位声明,正文带进来了
    assert "## 附录：商务响应（AI 通读招标文件生成" in out
    assert "正式商务表以上方原格式页为准" in out
    assert "公路二级，满足" in out
    # 招标全文确实喂给了 LLM
    assert "公路三级及以上" in captured["messages"][-1]["content"]


def test_service_returns_empty_when_no_tender_text() -> None:
    # 无招标全文 → 不调 LLM、返回 ""(调用方据此回退模板)
    called = {"n": 0}

    def fake_complete(_m):
        called["n"] += 1
        return "不该被调用"

    assert commercial_response_service.generate_commercial_responses(
        _req(), "   ", _PROFILE, complete=fake_complete
    ) == ""
    assert called["n"] == 0


def test_service_best_effort_swallows_llm_failure() -> None:
    def boom(_m):
        raise RuntimeError("llm down")

    # LLM 失败 → 返回 ""(不抛、不阻断出标)
    assert commercial_response_service.generate_commercial_responses(
        _req(), "招标全文。", _PROFILE, complete=boom
    ) == ""


def test_service_returns_empty_on_blank_llm_output() -> None:
    assert commercial_response_service.generate_commercial_responses(
        _req(), "招标全文。", _PROFILE, complete=lambda _m: "   "
    ) == ""
