from types import SimpleNamespace

from schemas.tender_spec import CertRequirement, TenderSpec
from services import conformance_service as cs


def _spec(**kw) -> TenderSpec:
    return TenderSpec(**kw)


PROFILE = {
    # 正奇真实:公路/市政都是贰级
    "qualification_grade": "公路工程施工总承包贰级；市政公用工程施工总承包贰级",
}


def test_qualification_meets_when_grade_high_enough() -> None:
    spec = _spec(
        cert_requirements=[
            CertRequirement(
                cert_type="企业资质",
                required_value="公路工程施工总承包二级",
                source="资格审查附录1",
            )
        ]
    )
    r = cs.check_qualification(spec, PROFILE)
    assert r.status == "符合" and r.action == "填"


def test_qualification_fails_and_warns_when_grade_too_low() -> None:
    # 招标要一级,正奇只有贰级 → 不符合(废标级),告警不蒙混
    spec = _spec(
        cert_requirements=[
            CertRequirement(
                cert_type="企业资质",
                required_value="公路工程施工总承包一级",
                source="资格审查附录1",
            )
        ]
    )
    r = cs.check_qualification(spec, PROFILE)
    assert r.status == "不符合" and r.action == "告警"
    assert "没资格" in r.note


def test_duration_filled_from_source() -> None:
    spec = _spec(duration="90日历天")
    r = cs.check_duration(spec)
    assert r.status == "一致" and r.action == "填" and r.required == "90日历天"
    assert cs.check_duration(_spec()) is None  # 招标没规定工期 → 不产条目


def test_project_manager_conformance() -> None:
    req = SimpleNamespace(builder_level="一级建造师", builder_specialty="公路工程")
    # 达标
    ok = cs.check_project_manager(
        req,
        {"name": "江舟", "builder_certs": [{"level": "一级建造师", "specialty": "公路工程"}]},
    )
    assert ok.status == "符合"
    # 等级不够
    low = cs.check_project_manager(
        req,
        {"name": "李四", "builder_certs": [{"level": "二级建造师", "specialty": "公路工程"}]},
    )
    assert low.status == "不符合" and "等级" in low.note
    # 未选派
    none = cs.check_project_manager(req, None)
    assert none.status == "待人工"


def test_basic_info_attachments_flags_missing_cert() -> None:
    spec = _spec()
    # 缺安许
    miss = cs.check_basic_info_attachments(spec, {"营业执照", "资质证书"})
    assert miss.status == "缺料" and "安全生产许可证" in miss.note
    # 齐全
    full = cs.check_basic_info_attachments(
        spec, {"营业执照", "资质证书", "安全生产许可证"}
    )
    assert full.status == "待人工"


def test_build_report_aggregates_and_flags_blocking() -> None:
    spec = _spec(
        duration="90日历天",
        cert_requirements=[
            CertRequirement(
                cert_type="企业资质", required_value="公路工程施工总承包一级"
            )
        ],
    )
    req = SimpleNamespace(builder_level="一级建造师", builder_specialty="公路工程")
    report = cs.build_conformance_report(
        project_id=126,
        spec=spec,
        profile=PROFILE,
        pm_requirement=req,
        selected_pm=None,
        available_cert_types={"营业执照", "资质证书"},
    )
    fields = {i.field for i in report.items}
    assert fields == {"工期", "企业资质", "项目经理", "投标人基本情况表附件"}
    # 资质不达标 → 有废标级阻断
    assert report.has_blocking is True
    assert any(w.field == "企业资质" for w in report.warnings)


# ── 证件有效期(#6):选派项目经理的建造师证过期=废标级、临近=预警 ────────────
from datetime import date as _date


def _pm(valid_to: str, *, level="一级建造师", specialty="公路工程") -> dict:
    return {
        "name": "江舟",
        "builder_certs": [{"level": level, "specialty": specialty, "valid_to": valid_to}],
    }


def test_parse_valid_to_handles_chinese_and_range_and_year_only() -> None:
    assert cs._parse_valid_to("2023至2028") == "2028-12-31"  # 只有年→当年末
    assert cs._parse_valid_to("2028年5月15日") == "2028-05-15"
    assert cs._parse_valid_to("2023-12-28至2028-12-28") == "2028-12-28"
    assert cs._parse_valid_to("2028.5") == "2028-05-28"  # 只有年月→该月28
    assert cs._parse_valid_to("长期") == ""  # 抠不出日期


def test_pm_cert_expired_is_blocking() -> None:
    today = _date(2026, 6, 17)
    r = cs.check_pm_cert_expiry(_pm("2025年1月1日"), today)
    assert r.status == "不符合" and r.action == "告警"
    assert "已过期" in r.note and "废标" in r.note


def test_pm_cert_expiring_soon_warns() -> None:
    today = _date(2026, 6, 17)
    r = cs.check_pm_cert_expiry(_pm("2026年8月1日"), today)  # 45天后到期(<90)
    assert r.status == "缺料" and r.action == "告警"
    assert "到期" in r.note


def test_pm_cert_valid_passes() -> None:
    today = _date(2026, 6, 17)
    r = cs.check_pm_cert_expiry(_pm("2023至2030"), today)
    assert r.status == "符合" and r.action == "留空"


def test_pm_cert_no_validity_info_is_manual() -> None:
    today = _date(2026, 6, 17)
    r = cs.check_pm_cert_expiry(_pm("长期"), today)
    assert r.status == "待人工"
    assert "无有效期信息" in r.our_value


def test_pm_cert_expiry_skipped_when_unselected_or_no_certs() -> None:
    today = _date(2026, 6, 17)
    assert cs.check_pm_cert_expiry(None, today) is None
    assert cs.check_pm_cert_expiry({"name": "江舟", "builder_certs": []}, today) is None


def test_build_report_includes_pm_expiry_item_when_pm_selected() -> None:
    today = _date(2026, 6, 17)
    report = cs.build_conformance_report(
        project_id=1,
        spec=_spec(),
        profile=PROFILE,
        pm_requirement=SimpleNamespace(builder_level="一级建造师", builder_specialty="公路工程"),
        selected_pm=_pm("2025年1月1日"),
        today=today,
    )
    fields = [i.field for i in report.items]
    assert "项目经理证件有效期" in fields
    assert report.has_blocking  # 过期证件 → 废标级阻断
