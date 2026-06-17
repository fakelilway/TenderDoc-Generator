"""评标办法抽取服务测试:定位章节、解析、转核对项、注入式抽取(不打真实 LLM)。"""

import json

from services.review_method_service import (
    build_review_method,
    locate_review_method_text,
    review_method_to_requirements,
    _to_review_method,
)


def test_locate_review_method_text_takes_body_not_toc() -> None:
    tender = (
        "目录\n第三章 评标办法\n第四章 合同条款\n"  # 目录里的幻影
        "正文大段……\n"
        "第三章 评标办法\n评标办法前附表\n2.1.1 形式评审标准:投标函已盖章。\n"
        "2.2 分值构成:施工组织设计40分。\n"
        "第四章 合同条款\n合同正文……"
    )
    text = locate_review_method_text(tender)
    assert "评标办法前附表" in text  # 命中正文那段
    assert "合同正文" not in text  # 到下一章就停


def test_locate_returns_empty_when_no_review_method() -> None:
    assert locate_review_method_text("一段没有评标办法的招标正文") == ""


def test_to_review_method_parses_three_buckets() -> None:
    rm = _to_review_method(
        {
            "method_name": "技术评分最低标价法",
            "total_score": 100,
            "criteria": [
                {
                    "category": "形式评审",
                    "clause_no": "2.1.1（3）",
                    "factor": "投标文件签字盖章",
                    "standard": "投标函由法定代表人或委托代理人签字并加盖单位章",
                    "is_reject": True,
                }
            ],
            "score_items": [
                {"clause_no": "2.2.1", "factor": "施工组织设计", "max_score": 40, "rule": "总体布置基本分2.4，加0-1.6"}
            ],
            "rejection_rules": [
                {"clause_no": "3.1", "rule": "有任何一项形式评审不合格的，否决其投标"}
            ],
        }
    )
    assert rm.method_name == "技术评分最低标价法"
    assert rm.total_score == 100
    assert len(rm.criteria) == 1 and rm.criteria[0].is_reject is True
    assert rm.score_items[0].max_score == 40
    assert rm.rejection_rules[0].clause_no == "3.1"
    assert rm.is_empty() is False


def test_to_review_method_drops_dirty_rows() -> None:
    rm = _to_review_method({"criteria": [{}, {"standard": "ok"}], "score_items": ["x"]})
    assert len(rm.criteria) == 1  # 空 dict 丢弃
    assert rm.score_items == []  # 非 dict 丢弃


def test_review_method_to_requirements_carries_clause_source() -> None:
    rm = _to_review_method(
        {
            "criteria": [
                {"category": "资格评审", "clause_no": "附录5", "factor": "项目经理", "standard": "公路工程二级建造师", "is_reject": True}
            ],
            "score_items": [{"clause_no": "2.2.1", "factor": "类似业绩", "max_score": 15, "rule": "近年公路工程得15"}],
            "rejection_rules": [{"clause_no": "3.1", "rule": "串通投标的否决"}],
        }
    )
    reqs = review_method_to_requirements(rm)
    assert len(reqs) == 3
    crit = reqs[0]
    assert crit.source == "附录5"  # 带真实条款号出处
    assert "公路工程二级建造师" in crit.required
    assert "否决" in crit.note  # is_reject 标注
    assert reqs[1].field.startswith("评分项")
    assert "满分15分" in reqs[1].required
    assert reqs[2].field == "否决情形" and reqs[2].source == "3.1"


def test_build_review_method_injected_complete() -> None:
    payload = json.dumps(
        {"criteria": [{"factor": "投标报价", "standard": "唯一报价", "clause_no": "2.1.3"}]}
    )
    rm = build_review_method(
        "第三章 评标办法\n评审标准如下……", complete=lambda messages: payload
    )
    assert len(rm.criteria) == 1
    assert rm.criteria[0].factor == "投标报价"


def test_build_review_method_empty_skips_llm_when_no_chapter() -> None:
    called = {"n": 0}

    def fake(messages):
        called["n"] += 1
        return "{}"

    rm = build_review_method("没有评标办法的正文", complete=fake)
    assert rm.is_empty() is True
    assert called["n"] == 0  # 没定位到章节就不打 LLM
