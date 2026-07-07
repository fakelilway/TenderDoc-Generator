"""Import the staff-curated 类似项目信息表 docx into the knowledge base.

《投标人近年完成的类似项目信息表.docx》是公司员工整理好的"资格审查业绩标准答案":
每张表一个完整业绩(项目名称/所在地/发包人三要素/合同价格/开工交工日期/项目经理…),
按"项目经理"归属。选定项目经理后,商务卷"近年完成的类似项目信息表"就按他名下的表
原样填写,业绩不再人工挑(见 services/similar_project_info_service)。

与业绩台账(import_performance_ledger, 汇总 xlsx ~253条)的分工:台账是"有哪些业绩"
的总账;本表是其中挑出的 47 条"投标专用明细"(字段比台账全:发包人地址电话/监理/
总监/项目描述/工程质量),生成商务卷详细信息表只认这份。

用法(用仓库根 .venv,不是 backend/venv):
  预览(不写库):  PYTHONPATH=backend .venv/bin/python backend/scripts/import_similar_project_info.py <docx> --out preview.csv
  入库(幂等):    ... --import-to-kb --import-report report.csv
入库前先删旧的 document_category='业绩信息表' 记录再整批重写,员工更新 docx 后重跑即可。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 同目录台账脚本的金额/类型规则,保持两份数据口径一致
from import_performance_ledger import (  # noqa: E402
    _amount_band,
    _infer_type,
    _parse_amount,
    _safe_segment,
)

COMPANY_NAME = "安徽正奇建设有限公司"
CATEGORY = "业绩信息表"
IMPORT_TAG = "导入批次-类似项目信息表"

# 源表行标签(归一化后) → 字段名。表是 17 行两列的"标签|值"竖表。
FIELD_MAP = {
    "序号": "ledger_no",
    "项目名称": "project_name",
    "项目所在地": "location",
    "发包人名称": "owner_name",
    "发包人地址": "owner_address",
    "发包人电话": "owner_phone",
    "合同价格": "contract_price",
    "开工日期": "start_date",
    "交工日期": "end_date",
    "承担的工作": "work_scope",
    "工程质量": "quality",
    "项目经理(或注册建造师)": "project_manager",
    "技术负责人": "tech_leader",
    "监理单位及联系电话": "supervisor_org",
    "总监理工程师及电话": "chief_supervisor",
    "项目描述": "description",
    "备注": "remark",
}


@dataclass
class SimilarProjectRecord:
    ledger_no: str = ""
    project_name: str = ""
    location: str = ""
    owner_name: str = ""
    owner_address: str = ""
    owner_phone: str = ""
    contract_price: str = ""
    start_date: str = ""
    end_date: str = ""
    work_scope: str = ""
    quality: str = ""
    project_manager: str = ""
    tech_leader: str = ""
    supervisor_org: str = ""
    chief_supervisor: str = ""
    description: str = ""
    remark: str = ""
    # 派生字段(与台账口径一致,供选派/推荐/展示)
    project_type: str = ""
    project_year: int | None = None
    amount_wan: float | None = None
    suggested_filename: str = ""
    unknown_labels: list[str] = field(default_factory=list)


def _norm_label(s: str) -> str:
    """标签归一化:去空白换行、统一全半角括号(治"项目经理(或注册建\n造师)"被换行切开)。"""
    s = re.sub(r"[\s　]+", "", s or "")
    return s.replace("（", "(").replace("）", ")")


def _extract_year(*values: str) -> int | None:
    for value in values:
        m = re.search(r"(20\d{2})", value or "")
        if m:
            return int(m.group(1))
    return None


def parse_similar_projects(docx_path: str | Path) -> list[SimilarProjectRecord]:
    from docx import Document

    doc = Document(str(docx_path))
    records: list[SimilarProjectRecord] = []
    used_names: set[str] = set()
    for table in doc.tables:
        raw: dict[str, str] = {}
        unknown: list[str] = []
        for row in table.rows:
            cells = row.cells
            if len(cells) < 2:
                continue
            label = _norm_label(cells[0].text)
            # 值取本行最后一个格;合并单元格会把标签格重复吐出,值与标签相同视为空
            value = cells[-1].text.strip()
            if _norm_label(value) == label:
                value = ""
            key = FIELD_MAP.get(label)
            if key is None:
                if label:
                    unknown.append(label)
                continue
            raw[key] = value
        if not raw.get("project_name"):
            continue  # 空模板表/说明表,跳过
        record = SimilarProjectRecord(**{k: v for k, v in raw.items()})
        record.unknown_labels = unknown
        record.project_type = _infer_type(record.project_name, record.description)
        # 年份口径:类似业绩通常"以交工时间为准",交工日期缺了再退开工日期
        record.project_year = _extract_year(record.end_date, record.start_date)
        record.amount_wan = _parse_amount(record.contract_price)
        base = f"业绩信息表_{record.project_year or '年份待核'}_{_safe_segment(record.project_name)}"
        candidate = f"{base}.txt"
        index = 2
        while candidate in used_names:
            candidate = f"{base}_{index}.txt"
            index += 1
        used_names.add(candidate)
        record.suggested_filename = candidate
        records.append(record)
    return records


def build_record_text(record: SimilarProjectRecord) -> str:
    """可读正文(入 knowledge_chunks 供检索);结构化字段以 metadata_json 为准。"""
    amount = f"{record.amount_wan}万元" if record.amount_wan is not None else record.contract_price or "待核"
    lines = [
        f"业绩项目：{record.project_name}",
        f"项目类型：{record.project_type}",
        f"项目所在地：{record.location}",
        f"发包人：{record.owner_name}　地址：{record.owner_address}　电话：{record.owner_phone}",
        f"合同价格：{record.contract_price or '待核'}（约{amount}）",
        f"开工日期：{record.start_date or '待核'}　交工日期：{record.end_date or '待核'}",
        f"承担的工作：{record.work_scope}",
        f"工程质量：{record.quality}",
        f"项目经理：{record.project_manager or '待核'}　技术负责人：{record.tech_leader or '待核'}",
        f"监理单位及联系电话：{record.supervisor_org}",
        f"总监理工程师及电话：{record.chief_supervisor}",
        f"项目描述：{record.description}",
        f"用途：资格审查/详细评审 类似项目信息表(按项目经理归属自动填表)",
    ]
    return "\n".join(line for line in lines if line.split("：", 1)[-1].strip())


def _record_metadata(record: SimilarProjectRecord) -> dict[str, object]:
    """全字段进 metadata_json:生成商务卷详细信息表时逐字段原样取用。"""
    data = asdict(record)
    data.pop("suggested_filename", None)
    data.pop("unknown_labels", None)
    return data


def delete_existing_records() -> int:
    """幂等重跑:删掉上一批"业绩信息表"文档(员工更新 docx 后整批换新)。"""
    from rag.vector_store import _connect
    from services.knowledge_service import delete_knowledge_document

    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id FROM documents
            WHERE project_id IS NULL
              AND metadata_json->>'document_category' = %s
            """,
            (CATEGORY,),
        )
        ids = [int(r[0]) for r in cursor.fetchall()]
    for doc_id in ids:
        delete_knowledge_document(doc_id)
    return len(ids)


def import_records_to_kb(records: list[SimilarProjectRecord]) -> list[dict[str, object]]:
    from services import knowledge_service

    results: list[dict[str, object]] = []
    for record in records:
        text = build_record_text(record)
        tags = ["业绩", CATEGORY, IMPORT_TAG, record.project_type,
                _amount_band(record.amount_wan)]
        if record.project_manager:
            tags.append(f"项目经理-{record.project_manager}")
        try:
            indexed = knowledge_service.index_uploaded_knowledge(
                file_bytes=text.encode("utf-8"),
                filename=record.suggested_filename,
                content_type="text/plain",
                project_type=record.project_type,
                document_type="业绩信息表",
                document_category=CATEGORY,
                volume="资格文件",
                project_year=record.project_year,
                owner_type="公司",
                owner_name=COMPANY_NAME,
                usage_scope="可用于投标",
                verified_status="已核验",  # 员工整理定稿,即"标准答案"
                image_insertable=False,
                tags=tags,
                ingestion_mode="rag_text",
                extra_metadata=_record_metadata(record),
            )
            results.append(
                {
                    "project_name": record.project_name,
                    "project_manager": record.project_manager,
                    "status": "imported",
                    "document_id": indexed.get("document_id"),
                    "message": "",
                }
            )
        except Exception as error:  # noqa: BLE001 - per-row isolation
            results.append(
                {
                    "project_name": record.project_name,
                    "project_manager": record.project_manager,
                    "status": "failed",
                    "document_id": "",
                    "message": str(error),
                }
            )
    return results


def write_preview_csv(records: list[SimilarProjectRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [k for k in asdict(SimilarProjectRecord()).keys() if k != "unknown_labels"]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def write_import_report(results: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["project_name", "project_manager", "status", "document_id", "message"]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({key: result.get(key, "") for key in fieldnames})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse and optionally import the 类似项目信息表 docx.")
    parser.add_argument("docx", type=Path, help="投标人近年完成的类似项目信息表 .docx path")
    parser.add_argument("--out", type=Path, required=True, help="Preview CSV output path")
    parser.add_argument("--import-to-kb", action="store_true", help="Import records into the knowledge base (幂等:先删旧批)")
    parser.add_argument("--import-report", type=Path, help="CSV report for import results")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = parse_similar_projects(args.docx.expanduser().resolve())
    write_preview_csv(records, args.out.expanduser().resolve())
    managers: dict[str, int] = {}
    for record in records:
        managers[record.project_manager or "(缺项目经理)"] = managers.get(record.project_manager or "(缺项目经理)", 0) + 1
    print(f"Parsed {len(records)} similar-project records")
    print("按项目经理分布: " + "、".join(f"{m}{n}条" for m, n in sorted(managers.items(), key=lambda x: -x[1])))
    for record in records:
        if record.unknown_labels:
            print(f"  ⚠ {record.project_name[:30]} 未识别标签: {record.unknown_labels}")
        if not record.project_manager:
            print(f"  ⚠ {record.project_name[:30]} 缺项目经理,自动带出选不到它")
    print(f"Preview CSV: {args.out.expanduser().resolve()}")
    if args.import_to_kb:
        removed = delete_existing_records()
        if removed:
            print(f"Removed {removed} stale records (previous import batch)")
        results = import_records_to_kb(records)
        report_path = (
            args.import_report.expanduser().resolve()
            if args.import_report
            else args.out.expanduser().resolve().with_name("similar_project_import_report.csv")
        )
        write_import_report(results, report_path)
        imported = sum(1 for r in results if r["status"] == "imported")
        failed = sum(1 for r in results if r["status"] == "failed")
        print(f"Import: {imported} imported, {failed} failed")
        print(f"Import report: {report_path}")


if __name__ == "__main__":
    main()
