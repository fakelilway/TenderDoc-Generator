"""每项目「工程量清单(另册)」上传:抽出全文存进 projects.boq_text,供 build_boq 优先使用。

工程量清单常是另册(PDF/Word),不在招标正文里。上传后抽全文单独存,生成技术卷时按真实
分部分项占比定详略、把真实工程量喂给对应施工方案;没上传则回退"从招标正文估占比"。
"""

from __future__ import annotations

from utils.file_parser import extract_text

from . import _runtime


def set_project_boq(
    project_id: int, file_bytes: bytes, filename: str, content_type: str | None
) -> dict:
    """抽出工程量清单全文,存进 projects.boq_text。返回 {chars, text}。"""
    text = (extract_text(file_bytes, filename, content_type) or "").strip()
    with _runtime.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET boq_text = %s WHERE id = %s",
                (text, project_id),
            )
    return {"chars": len(text), "text": text}


def clear_project_boq(project_id: int) -> None:
    with _runtime.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET boq_text = NULL WHERE id = %s", (project_id,)
            )


def get_project_boq_chars(project_id: int) -> int:
    with _runtime.connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT length(coalesce(boq_text, '')) FROM projects WHERE id = %s",
                (project_id,),
            )
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
