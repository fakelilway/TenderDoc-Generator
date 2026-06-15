from pathlib import Path

from openpyxl import Workbook

from scripts import import_performance_ledger as ledger
from scripts.import_performance_ledger import (
    PerformanceRecord,
    build_record_text,
    import_records_to_kb,
    parse_ledger,
)

_COL = {
    "contract_no": 1,
    "project_name": 2,
    "project_manager": 3,
    "chief_engineer": 4,
    "bid_date": 5,
    "duration": 11,
    "amount": 12,
    "summary": 13,
    "scan_award": 14,
    "scan_contract": 15,
    "scan_handover": 16,
    "owner": 19,
}


def _row(**values) -> list:
    row = [None] * 20
    for key, value in values.items():
        row[_COL[key]] = value
    return row


def _make_ledger(path: Path, data_rows: list[list]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "汇总表"
    worksheet.append(["安徽正奇建设有限公司业绩原件表"])  # row 1 title
    worksheet.append(["序号", "合同编号", "合同名称"])  # row 2 header
    worksheet.append([None, None, None, "项目经理", "项目总工"])  # row 3 header
    for row in data_rows:  # data starts at row 4
        worksheet.append(row)
    workbook.save(path)


def test_parse_ledger_extracts_structured_records(tmp_path: Path) -> None:
    xlsx = tmp_path / "ledger.xlsx"
    _make_ledger(
        xlsx,
        [
            _row(
                contract_no="JUSTODD-SGA2021",
                project_name="G343大卢段公路改建工程",
                project_manager="王兴祥",
                chief_engineer="李刚",
                bid_date="2021.4.14",
                duration="180日历天",
                amount=41107670,
                summary="二级公路路面改建,沥青混凝土",
                scan_award="有",
                scan_contract="有",
                scan_handover=None,
                owner="安徽省交通运输厅",
            ),
            _row(
                project_name="某县危桥加固改造工程",
                bid_date="2022.6",
                amount=8000000,
                summary="危桥加固",
                scan_award="有",
            ),
        ],
    )

    records = {r.project_name: r for r in parse_ledger(xlsx)}
    assert len(records) == 2

    road = records["G343大卢段公路改建工程"]
    assert road.project_type == "公路工程"
    assert road.amount_wan == 4110.77  # 41,107,670 元 → 万元
    assert road.amount_band == "金额-3000万至1亿"
    assert road.project_year == 2021
    assert road.project_manager == "王兴祥"
    assert road.has_award_scan is True
    assert road.has_handover_scan is False  # empty cell
    assert road.suggested_filename.startswith("业绩_2021_") and road.suggested_filename.endswith(".txt")

    bridge = records["某县危桥加固改造工程"]
    assert bridge.project_type == "桥梁工程"
    assert bridge.amount_band == "金额-500至1000万"  # 800万
    assert bridge.project_year == 2022


def test_amount_parsing_handles_wrapped_and_empty() -> None:
    assert ledger._parse_amount(1340380) == 134.04
    assert ledger._parse_amount("1798910.9\n1041") == 179.89  # take first wrapped token
    assert ledger._parse_amount("/") is None
    assert ledger._parse_amount(None) is None


def test_type_inference_prefers_specific_lens() -> None:
    # 交安/养护 lenses win over the generic 公路 rule (which "路面" would also match).
    assert ledger._infer_type("农村公路安全生命防护工程", "波形梁护栏") == "交安工程"
    assert ledger._infer_type("某养护大修工程", "路面预防性养护") == "公路养护"
    assert ledger._infer_type("某二级公路改建", "路面改建") == "公路工程"
    assert ledger._infer_type("未知类别项目", "") == "其他工程"


def test_build_record_text_includes_key_fields() -> None:
    record = PerformanceRecord(
        project_name="测试公路工程",
        project_type="公路工程",
        amount_wan=2446.0,
        bid_date="2022.01.26",
        project_year=2022,
        duration="365日历天",
        project_manager="江舟",
    )
    text = build_record_text(record)
    assert "测试公路工程" in text
    assert "2446.0万元" in text
    assert "2022年" in text
    assert "江舟" in text


def test_import_records_calls_indexer_with_performance_metadata(monkeypatch) -> None:
    captured: dict = {}

    def fake_index(**kwargs):
        captured.update(kwargs)
        return {"document_id": 7, "indexing_status": "indexed"}

    monkeypatch.setattr(
        "services.knowledge_service.index_uploaded_knowledge", fake_index
    )

    record = PerformanceRecord(
        project_name="X公路工程",
        project_type="公路工程",
        amount_wan=1500.0,
        amount_band="金额-1000至3000万",
        project_year=2023,
        suggested_filename="业绩_2023_X公路工程.txt",
    )

    results = import_records_to_kb([record])

    assert results[0]["status"] == "imported"
    assert results[0]["document_id"] == 7
    assert captured["document_category"] == "业绩"
    assert captured["project_year"] == 2023
    assert captured["ingestion_mode"] == "rag_text"
    assert captured["image_insertable"] is False
    assert "金额-1000至3000万" in captured["tags"]
    assert ledger.LEDGER_TAG in captured["tags"]
