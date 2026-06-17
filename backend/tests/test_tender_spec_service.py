from services.tender_spec_service import build_tender_spec, _to_spec, _parse_json


FAKE_JSON = """{
  "duration": "90日历天",
  "bid_validity": "90天",
  "cert_requirements": [
    {"cert_type": "企业资质", "required_value": "公路工程施工总承包一级", "source": "资格审查附录1"}
  ],
  "attachment_requirements": {"投标人基本情况表": ["营业执照", "资质证书", "安全生产许可证"]},
  "instructions_table": [{"clause_no": "1.3.2", "name": "计划工期", "content": "90日历天"}],
  "contract_appendix": [{"clause_no": "1.1.4.5", "name": "缺陷责任期", "content": "自实际交工日期起2年"}],
  "performance_requirement": {"since": "2022年以来", "category": "公路", "min_amount_wan": 500, "min_count": 2, "time_basis": "交工"}
}"""


def test_build_tender_spec_maps_llm_json() -> None:
    spec = build_tender_spec("招标全文……", complete=lambda messages: FAKE_JSON)
    assert spec.duration == "90日历天"
    assert spec.bid_validity == "90天"
    assert spec.cert_requirements[0].required_value == "公路工程施工总承包一级"
    assert spec.attachment_requirements["投标人基本情况表"] == [
        "营业执照",
        "资质证书",
        "安全生产许可证",
    ]
    assert spec.contract_appendix[0].name == "缺陷责任期"
    assert spec.performance_requirement.min_amount_wan == 500


def test_build_tender_spec_empty_and_garbage_are_safe() -> None:
    assert build_tender_spec("").duration == ""  # 空文本→空规格
    # LLM 吐了带 markdown 围栏的脏 JSON,也要稳
    dirty = "```json\n{\"duration\": \"60天\",}\n```"
    assert build_tender_spec("x", complete=lambda m: dirty).duration == "60天"
    # 彻底坏的→空规格不炸
    assert _to_spec(_parse_json("not json at all")).duration == ""
