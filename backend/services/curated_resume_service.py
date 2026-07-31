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


def save_curated_resumes(resumes: dict[str, dict[str, str]], source_file: str) -> int:
    """整体覆盖保存定稿(重跑导入=以最新文档为准)。返回人数。"""
    from rag.vector_store import get_db_connection

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
                (source_file, "", "json", json.dumps(payload, ensure_ascii=False)),
            )
        conn.commit()
    return len(resumes)


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
