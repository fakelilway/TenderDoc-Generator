"""商务标固定字段规则测试。

重点守护 2026-07-11 的决策:「质量」是招标优先、固定值兜底——
招标解析出的质量标准不能再被固定值"合格"无条件覆盖(员工反馈的真实事故)。
"""

from services.commercial_fixed_fields import (
    COMMERCIAL_FIXED_FIELDS,
    TENDER_FIRST_FALLBACK_FIELDS,
    apply_fixed_fields,
)


def test_quality_from_tender_is_preserved():
    """招标解析出了质量标准 → 保留,不被固定值覆盖。"""
    profile = {"质量": "符合设计要求及验收规范,确保省优质工程"}
    apply_fixed_fields(profile)
    assert profile["质量"] == "符合设计要求及验收规范,确保省优质工程"


def test_quality_falls_back_to_fixed_when_missing():
    """招标里没解析到质量标准 → 兜底填固定值"合格"。"""
    for empty in ("", "  ", None):
        profile = {"质量": empty}
        apply_fixed_fields(profile)
        assert profile["质量"] == "合格"
    # 键完全不存在也要兜底
    profile = {}
    apply_fixed_fields(profile)
    assert profile["质量"] == "合格"


def test_quality_not_in_unconditional_fixed_fields():
    """「质量」必须待在招标优先清单里,不能回到无条件固定清单(防止改回老毛病)。"""
    assert "质量" not in COMMERCIAL_FIXED_FIELDS
    assert TENDER_FIRST_FALLBACK_FIELDS.get("质量") == "合格"


def test_truly_fixed_fields_still_override():
    """全固定字段(公司名/安全等)仍然无条件覆盖,行为不变。"""
    profile = {
        "company_name": "别的公司名",
        "安全": "招标里写的安全目标",
        "质量": "创优",
    }
    apply_fixed_fields(profile)
    assert profile["company_name"] == "安徽正奇建设有限公司"
    assert profile["安全"] == "无安全事故"
    # 同时确认质量不受牵连
    assert profile["质量"] == "创优"
