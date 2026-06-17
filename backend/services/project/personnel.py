"""本项目人员选派:按招标项目经理要求从公司名册推荐 + 存取选定人选。

数据流:招标要求(派生) + 公司名册 → 推荐候选 → 用户选定 → 存 projects.selected_personnel
→ 生成时覆盖 company_profile 的单个项目经理,填进商务卷人员表(见 v2_generation)。
"""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from schemas.personnel import PersonnelMember
from services import personnel_roster_service
from services.personnel_selection_service import (
    derive_pm_requirement,
    recommend_project_managers,
)

from . import _runtime
from ._helpers import _fetch_project, _project_requirements
from .errors import ProjectNotFoundError


def _load_roster() -> list[PersonnelMember]:
    raw = personnel_roster_service.get_personnel_roster()["roster"]
    return [PersonnelMember(**member) for member in raw]


def recommend_project_personnel(project_id: int) -> dict[str, Any]:
    """派生招标项目经理要求 + 从公司名册推荐匹配候选(含当前选定)。"""
    project = _fetch_project(project_id)
    requirement = derive_pm_requirement(_project_requirements(project))
    recommendations = recommend_project_managers(_load_roster(), requirement)
    selected = (project.get("selected_personnel") or {}).get("project_manager")
    return {
        "project_id": project_id,
        "requirement": requirement.model_dump(),
        "recommendations": [rec.model_dump() for rec in recommendations],
        "selected": selected,
    }


def get_selected_personnel(project_id: int) -> dict[str, Any]:
    project = _fetch_project(project_id)
    return {
        "project_id": project_id,
        "selected": project.get("selected_personnel") or {},
    }


def save_selected_project_manager(
    project_id: int, member: dict[str, Any] | None
) -> dict[str, Any]:
    """存本项目选定的项目经理(member=名册里的一条记录;None=清空选派)。"""
    # 校验:非空时必须能被 PersonnelMember 接住(防脏数据写库)。
    clean = PersonnelMember(**member).model_dump() if member else None
    payload: dict[str, Any] = {"project_manager": clean} if clean else {}
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                UPDATE projects
                SET selected_personnel = %s
                WHERE id = %s
                RETURNING id, selected_personnel
                """,
                (Json(payload), project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {
        "project_id": int(row["id"]),
        "selected": row["selected_personnel"] or {},
    }
