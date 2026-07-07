"""本项目业绩选择(多选):按招标类似业绩要求从台账推荐 + 存取选定业绩。

数据流:招标要求(派生) + 公司台账 → 推荐匹配 → 用户**多选** → 存 projects.selected_performance
→ 生成时只插选中的业绩 + 其证明链(中标/合同/交工),不再一股脑全堆。
"""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from services.performance_selection_service import (
    derive_performance_requirement,
    recommend_curated_performance,
)

from . import _runtime
from ._helpers import _fetch_project, _project_requirements
from .errors import ProjectNotFoundError


def recommend_project_performance(project_id: int) -> dict[str, Any]:
    """投标人业绩候选池:员工整理的《类似项目信息表》全部记录,按招标要求打分排序供多选。

    用户选中哪几条,生成时"投标人近年完成的类似项目信息表"就原样填哪几条(字段全、
    图片跟名走)。跟项目经理是谁无关——经理只决定经理表。附当前已选。"""
    project = _fetch_project(project_id)
    try:
        requirement = derive_performance_requirement(_project_requirements(project))
    except ValueError:
        # 招标尚未解析:业绩候选不该被解析状态卡死,用空要求兜底(=不筛,列全部供选)
        requirement = derive_performance_requirement(None)
    selected = project.get("selected_performance") or []
    recommendations = recommend_curated_performance(requirement)

    return {
        "project_id": project_id,
        "requirement": requirement.model_dump(),
        "recommendations": recommendations,
        "selected": selected,
    }


def get_selected_performance(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    return {
        "project_id": project_id,
        "selected": project.get("selected_performance") or [],
    }


def save_selected_performance(
    project_id: int, items: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """存本项目选定的业绩(多选;items=台账推荐里的若干条;空=清空)。"""
    clean = [
        {
            "name": str(it.get("name", "")),
            "year": str(it.get("year", "")),
            "amount": str(it.get("amount", "")),
            "type": str(it.get("type", "")),
            "document_id": it.get("document_id"),
        }
        for it in (items or [])
        if it.get("name")
    ]
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET selected_performance = %s
                WHERE id = %s
                RETURNING id, selected_performance
                """,
                (Json(clean), project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {
        "project_id": int(row["id"]),
        "selected": row["selected_performance"] or [],
    }
