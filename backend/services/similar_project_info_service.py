"""类似项目信息表(员工整理的"资格审查业绩标准答案")读取与按人归属。

数据由 scripts/import_similar_project_info.py 从《投标人近年完成的类似项目信息表.docx》
入库:documents.metadata_json->>'document_category'='业绩信息表',全字段在 metadata_json。

业务规则(用户拍板):选定项目经理后,商务卷"近年完成的类似项目信息表"就按他名下的
记录原样填写,类似业绩不再人工挑——业绩跟经理走。项目总工同理按"技术负责人"字段归属
(匹配不到就留白,绝不拿别人的业绩凑)。
"""

from __future__ import annotations

import re
from typing import Any

from rag.vector_store import _connect

# 生成商务卷详细信息表时按这些字段原样取值(与导入脚本 FIELD_MAP 的值域一致)
RECORD_FIELDS = (
    "ledger_no", "project_name", "location", "owner_name", "owner_address",
    "owner_phone", "contract_price", "start_date", "end_date", "work_scope",
    "quality", "project_manager", "tech_leader", "supervisor_org",
    "chief_supervisor", "description", "remark",
    "project_type", "project_year", "amount_wan",
)


def _norm_person(name: str) -> str:
    """人名归一化:去空白(台账/名册里"李 刚"与"李刚"是同一人)。"""
    return re.sub(r"[\s　]+", "", name or "")


def _ledger_sort_key(record: dict[str, Any]) -> tuple:
    """按台账序号数值排序;序号缺/非数字的排最后按入库顺序。Python 侧排序,
    不在 SQL 里 ::int 强转(超长数字串会 int4 溢出把整个查询炸掉)。"""
    digits = re.sub(r"\D", "", str(record.get("ledger_no") or ""))
    if digits:
        return (0, int(digits), record["document_id"])
    return (1, 0, record["document_id"])


def list_similar_project_records() -> list[dict[str, Any]]:
    """全部业绩信息表记录(公司级),按台账序号排序,附 document_id。"""
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, metadata_json
            FROM documents
            WHERE project_id IS NULL
              AND metadata_json->>'document_category' = '业绩信息表'
            ORDER BY id
            """
        )
        rows = cursor.fetchall()
    records: list[dict[str, Any]] = []
    for doc_id, metadata in rows:
        metadata = metadata or {}
        record = {key: metadata.get(key) for key in RECORD_FIELDS}
        if not (record.get("project_name") or "").strip():
            continue
        record["document_id"] = int(doc_id)
        records.append(record)
    records.sort(key=_ledger_sort_key)
    return records


def records_for_manager(manager_name: str) -> list[dict[str, Any]]:
    """选定项目经理名下的业绩信息表记录(自动带出/填表都用这个)。"""
    target = _norm_person(manager_name)
    if not target:
        return []
    return [
        r for r in list_similar_project_records()
        if _norm_person(str(r.get("project_manager") or "")) == target
    ]


def records_for_tech_leader(tech_name: str) -> list[dict[str, Any]]:
    """选定总工按"技术负责人"字段归属的记录;没有就是空(留白,不硬凑)。"""
    target = _norm_person(tech_name)
    if not target:
        return []
    return [
        r for r in list_similar_project_records()
        if _norm_person(str(r.get("tech_leader") or "")) == target
    ]


