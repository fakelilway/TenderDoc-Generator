"""人员资历表**定稿**数据源(2026-07-31 用户提供《拟委任的项目经理和项目总工资历表.doc》)。

员工整理好的一人一张资历表,是简历字段的最高优先级来源——比台账/证件OCR都可靠
("下次按照我选的人选,从这里面找那个人,按照这个填")。解析入口见
scripts/import_candidate_resumes.py;生成侧 build_pm_resume_fields 优先取这里。

存储:documents 表单行(project_id NULL, document_category='资历表定稿'),
全部人员字段放 metadata_json['resumes']={姓名: {字段:值}}——不动表结构,随迁移包走。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_CATEGORY = "资历表定稿"
_TEMPLATE_OBJECT = "curated/resume_templates.docx"  # 整份成品模版docx存MinIO,生成时按人取表


def save_curated_resumes(
    resumes: dict[str, dict[str, str]],
    source_file: str,
    docx_bytes: bytes | None = None,
) -> int:
    """整体覆盖保存定稿(重跑导入=以最新文档为准)。返回人数。

    ``docx_bytes``:转成docx的整份模版原件 → 存MinIO。2026-08-01 用户拍板"整表照搬":
    生成时不再抽字段填空白表,而是把选派人选的那张成品表原样搬进标书,故必须留住原件。
    """
    from core.config import settings
    from rag.vector_store import get_db_connection
    from utils.minio_client import minio_client

    file_path = ""
    if docx_bytes:
        minio_client.upload_file(settings.minio_bucket, docx_bytes, _TEMPLATE_OBJECT)
        file_path = _TEMPLATE_OBJECT
    payload = {
        "document_category": _CATEGORY,
        "resumes": resumes,
        "source_file": source_file,
    }
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM documents WHERE project_id IS NULL "
                "AND metadata_json->>'document_category' = %s",
                (_CATEGORY,),
            )
            cur.execute(
                "INSERT INTO documents (file_name, file_path, file_type, metadata_json) "
                "VALUES (%s, %s, %s, %s::jsonb)",
                (source_file, file_path, "docx", json.dumps(payload, ensure_ascii=False)),
            )
        conn.commit()
    return len(resumes)


def curated_names() -> set[str]:
    """有成品模版的人名集合(前端标绿/缺简历提示用)。查不到返回空集,绝不抛。"""
    try:
        from rag.vector_store import get_db_connection

        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT metadata_json->'resumes' FROM documents "
                "WHERE project_id IS NULL AND metadata_json->>'document_category' = %s "
                "ORDER BY id DESC LIMIT 1",
                (_CATEGORY,),
            )
            row = cur.fetchone()
        return set((row[0] or {}).keys()) if row else set()
    except Exception:  # noqa: BLE001
        return set()


def get_template_table_el(name: str) -> Any | None:
    """取某人的成品资历表 <w:tbl> 元素深拷贝;没有返回 None,绝不抛。

    按表内"姓名"标签右邻格匹配人名。每次现拷,调用方可放心改(拟任职务/经历)。
    """
    target = (name or "").strip()
    if not target:
        return None
    try:
        from copy import deepcopy
        from io import BytesIO

        from docx import Document

        from core.config import settings
        from utils.minio_client import minio_client

        blob = minio_client.download_bytes(settings.minio_bucket, _TEMPLATE_OBJECT)
        doc = Document(BytesIO(blob))
        for table in doc.tables:
            for row in table.rows[:2]:
                cells = row.cells
                for i, c in enumerate(cells):
                    if "姓" in c.text and "名" in c.text and i + 1 < len(cells):
                        if cells[i + 1].text.strip() == target:
                            return deepcopy(table._tbl)
        return None
    except Exception:  # noqa: BLE001
        logger.warning("成品资历表取用失败(%s),退回字段填充", target, exc_info=True)
        return None


def get_curated_resume(name: str) -> dict[str, str]:
    """按姓名取一个人的定稿字段;没有返回 {}。绝不抛(生成侧当可选增强用)。"""
    target = (name or "").strip()
    if not target:
        return {}
    try:
        from rag.vector_store import get_db_connection

        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT metadata_json->'resumes' FROM documents "
                "WHERE project_id IS NULL AND metadata_json->>'document_category' = %s "
                "ORDER BY id DESC LIMIT 1",
                (_CATEGORY,),
            )
            row = cur.fetchone()
        resumes = row[0] if row and row[0] else {}
        got = resumes.get(target) or {}
        return {str(k): str(v) for k, v in got.items() if str(v or "").strip()}
    except Exception:  # noqa: BLE001
        logger.warning("资历表定稿读取失败,退回台账/OCR", exc_info=True)
        return {}
