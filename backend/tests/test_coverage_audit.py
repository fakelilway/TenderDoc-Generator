"""招标覆盖校验测试。

判定按类型不对称:评分项漏=major告警;废标项漏=未覆盖,严重度由 coverage_audit_block_invalid
控制(默认 False=major告警,防规则类废标项锁死;True=critical硬拦)。judge 全部注入假实现,不打真 LLM。
"""

from __future__ import annotations

from services import v2_audit_service as A
from prompts.coverage_audit_prompt import parse_coverage_verdicts
from prompts.generator_prompt import build_node_fill_prompt


def _req() -> dict:
    return {
        "invalid_bid_items": [
            {"title": "投标保证金", "description": "未按要求提交投标保证金即否决"},
            {"title": "工期承诺", "description": "工期超过招标最高限即废标"},
        ],
        "technical_score_items": [
            {"title": "安全文明施工", "description": "安全文明施工措施评分"},
        ],
    }


def _judge_only_baojin(prose, items):
    """假判定器:仅"投标保证金"判为已覆盖,其余未覆盖。"""
    return ["保证金" in it["title"] for it in items]


def _force_block(monkeypatch, block: bool = True) -> None:
    """强制废标项硬拦模式(coverage_audit_block_invalid=True)。默认是告警模式(防规则类废标项锁死)。"""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(
            enable_coverage_audit=True, coverage_audit_block_invalid=block
        ),
    )


def test_warn_mode_default_invalid_is_major_not_blocking() -> None:
    """默认告警模式:废标项漏=major(不拦),避免'初步评审不通过/报价超限价'等规则类废标项把每份标锁死。"""
    rep = A.audit_coverage_layer("正文", _req(), judge=_judge_only_baojin)
    assert rep.passed is False  # 有问题
    assert rep.critical_count == 0  # 但无 critical → 不会硬拦出标
    assert all(i.severity == "major" for i in rep.issues)


def test_block_mode_blocks_on_missing_invalid_warns_on_missing_score(monkeypatch) -> None:
    _force_block(monkeypatch)
    rep = A.audit_coverage_layer("正文", _req(), judge=_judge_only_baojin)
    assert rep.passed is False
    # 废标"工期承诺"漏 → critical;评分"安全文明施工"漏 → major;保证金已覆盖无 issue。
    sev = sorted((i.severity, i.location) for i in rep.issues)
    assert sev == [("critical", "工期承诺"), ("major", "安全文明施工")]
    assert rep.critical_count == 1


def test_coverage_layer_all_covered_passes() -> None:
    rep = A.audit_coverage_layer("正文", _req(), judge=lambda p, items: [True] * len(items))
    assert rep.passed is True and rep.issues == []


def test_coverage_layer_no_items_passes() -> None:
    rep = A.audit_coverage_layer("正文", {}, judge=_judge_only_baojin)
    assert rep.passed is True


def test_evaluate_coverage_returns_aligned_verdicts() -> None:
    verdicts = A.evaluate_coverage(
        "正文",
        _req()["invalid_bid_items"],
        _req()["technical_score_items"],
        judge=_judge_only_baojin,
    )
    assert [v.kind for v in verdicts] == ["废标", "废标", "评分"]
    assert [v.covered for v in verdicts] == [True, False, False]


def test_judge_exception_falls_back_to_heuristic_not_crash() -> None:
    def boom(prose, items):
        raise RuntimeError("LLM down")

    # judge 抛错时不应整条崩,而是降级到 bigram 兜底并给出等长、全布尔的结论。
    prose = "本工程工期承诺为 540 日历天，满足招标最高限，投标保证金已按要求提交。"
    verdicts = A.evaluate_coverage(
        prose, _req()["invalid_bid_items"], _req()["technical_score_items"], judge=boom
    )
    assert len(verdicts) == 3
    assert all(isinstance(v.covered, bool) for v in verdicts)


def test_heuristic_covers_when_text_strongly_overlaps() -> None:
    # 正文几乎照抄废标项表述 → bigram 重叠高 → 兜底判已覆盖。
    flags = A._heuristic_coverage(
        "本工程已按要求提交投标保证金，满足投标保证金的否决条款。",
        [{"kind": "废标", "title": "投标保证金", "description": "未按要求提交投标保证金即否决"}],
    )
    assert flags == [True]


def test_heuristic_strict_on_invalid_when_absent() -> None:
    # 正文完全不含废标项相关表述 → 兜底判未覆盖(从严)。
    flags = A._heuristic_coverage(
        "这里只写了无关的绿化苗木种植内容。",
        [{"kind": "废标", "title": "投标保证金", "description": "未提交投标保证金即否决"}],
    )
    assert flags == [False]


def test_full_audit_includes_coverage_and_blocks(monkeypatch) -> None:
    _force_block(monkeypatch)
    clean_prose = (
        "测试公路项目施工组织设计正文。\n本工程采用分层填筑。\n质量目标为合格。\n"
        "安全目标为零事故。\n施工部署如下所述。\n进度计划见后。\n"
    )
    result = A.full_audit(
        pages=[],
        filled_pages=[],
        prose_text=clean_prose,
        project_name="测试公路项目",
        requirements=_req(),
        filled_fields=[],
        profile={},
        coverage_text="本工程投标保证金已提交。",  # 仅保证金覆盖
        coverage_judge=_judge_only_baojin,
    )
    assert result.passed is False
    assert any(i.severity == "critical" for i in result.coverage_issues)
    # 覆盖问题进入 all_issues,使下游 audit_blocked(看 critical)能拦住出标。
    assert any(
        i.severity == "critical" and i.location == "工期承诺" for i in result.all_issues
    )


def test_parse_coverage_verdicts_strict_and_none_on_failure() -> None:
    raw = '{"verdicts":[{"index":0,"covered":true},{"index":2,"covered":true}]}'
    # 3 条,但只回了 index 0/2 → index1 缺省为 False(从严)。
    assert parse_coverage_verdicts(raw, 3) == [True, False, True]
    # covered 从严:字符串 "false" 不再被当真;"true"/"yes" 才算覆盖。
    raw2 = '{"verdicts":[{"index":0,"covered":"false"},{"index":1,"covered":"true"}]}'
    assert parse_coverage_verdicts(raw2, 2) == [False, True]
    # index 容忍字符串数字。
    assert parse_coverage_verdicts('{"verdicts":[{"index":"1","covered":true}]}', 2) == [
        False,
        True,
    ]
    # 解析失败/非dict/无verdicts → None(交上层 bigram 兜底,绝不静默全判未覆盖)。
    assert parse_coverage_verdicts("not json", 2) is None
    assert parse_coverage_verdicts('{"foo":1}', 2) is None
    assert parse_coverage_verdicts('{"verdicts":[]}', 2) is None


def test_invalid_items_never_bigram_rescued_block_when_llm_unavailable(monkeypatch) -> None:
    """安全铁律:LLM判定不可用(judge None)时,废标项一律判未覆盖→(硬拦模式下)critical,绝不靠 bigram 放行。

    即便正文几乎照抄了废标条款原文(bigram 高重叠),也不能把废标项救成已覆盖——
    抄禁止句≠实质规避违规,靠 bigram 放行=放走真违规。
    """
    _force_block(monkeypatch)
    prose = "我方承诺：未按要求提交投标保证金即否决，本工程已按要求提交投标保证金。" * 2
    req = {
        "invalid_bid_items": [
            {"title": "投标保证金", "description": "未按要求提交投标保证金即否决"}
        ],
        "technical_score_items": [],
    }
    rep = A.audit_coverage_layer(prose, req, judge=lambda p, items: None)
    assert rep.passed is False and rep.critical_count == 1


def test_bigram_rescue_applies_to_score_not_invalid(monkeypatch) -> None:
    """LLM 判未覆盖时,bigram 只救评分项(major),绝不救废标项(硬拦模式下 critical)。"""
    _force_block(monkeypatch)
    prose = (
        "我方承诺未按要求提交投标保证金即否决，已提交投标保证金；"
        "安全文明施工措施完善，安全文明施工费用专款专用。"
    ) * 2
    req = {
        "invalid_bid_items": [
            {"title": "投标保证金", "description": "未按要求提交投标保证金即否决"}
        ],
        "technical_score_items": [
            {"title": "安全文明施工", "description": "安全文明施工措施评分"}
        ],
    }
    # judge 对两项都判 False(模拟截断/没看到);bigram 对两项都高重叠。
    rep = A.audit_coverage_layer(prose, req, judge=lambda p, items: [False, False])
    # 废标项不被 bigram 救 → critical;评分项被 bigram 救 → 无 major。
    assert sorted(i.severity for i in rep.issues) == ["critical"]
    assert rep.critical_count == 1


def test_coverage_items_accepts_pydantic_like_objects() -> None:
    """要求项是对象(非dict)时不能被静默丢弃,否则 0 项→直接放行→废标漏'该拦没拦'。"""
    from types import SimpleNamespace

    items = A._coverage_items(
        [SimpleNamespace(title="投标保证金", description="否决")], []
    )
    assert items == [{"kind": "废标", "title": "投标保证金", "description": "否决"}]


def test_config_switch_disables_coverage(monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(enable_coverage_audit=False),
    )
    rep = A.audit_coverage_layer("正文", _req(), judge=lambda p, items: [False] * len(items))
    assert rep.passed is True and rep.issues == []


def test_node_prompt_carries_tender_first_priority() -> None:
    msgs = build_node_fill_prompt(
        node_title="路基工程施工方案",
        project_name="测试公路",
        requirements={},
        company_name="某公司",
        score_items=[{"title": "评分A", "description": "desc"}],
        invalid_items=[{"title": "废标A", "description": "desc"}],
    )
    user = msgs[-1]["content"]
    assert "最高准则" in user
    assert "漏答一条" in user and "整体废标" in user  # 评分/废标标题已强化
