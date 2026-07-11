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
    derive_tech_director_requirement,
    recommend_project_managers,
    recommend_tech_directors,
)

from . import _runtime
from ._helpers import _fetch_project, _project_requirements
from .errors import ProjectNotFoundError


def _load_roster() -> list[PersonnelMember]:
    raw = personnel_roster_service.get_personnel_roster()["roster"]
    return [PersonnelMember(**member) for member in raw]


def _performance_role_counts() -> tuple[dict[str, int], dict[str, int]]:
    """从《类似项目信息表》统计每人当过几个项目的经理/总工(归一化姓名→次数)。

    真带过项目=最硬的胜任证据:推荐时保底入选+按项目数加分。读不到就空(不拦推荐)。"""
    try:
        from services.similar_project_info_service import (
            _norm_person,
            list_similar_project_records,
        )

        pm_counts: dict[str, int] = {}
        td_counts: dict[str, int] = {}
        for record in list_similar_project_records():
            pm = _norm_person(str(record.get("project_manager") or ""))
            td = _norm_person(str(record.get("tech_leader") or ""))
            if pm:
                pm_counts[pm] = pm_counts.get(pm, 0) + 1
            if td:
                td_counts[td] = td_counts.get(td, 0) + 1
        return pm_counts, td_counts
    except Exception:
        return {}, {}


def recommend_project_personnel(project_id: int) -> dict[str, Any]:
    """派生招标项目经理要求 + 从公司名册推荐匹配候选(含当前选定)。"""
    project = _fetch_project(project_id)
    requirement = derive_pm_requirement(_project_requirements(project))
    pm_counts, _td_counts = _performance_role_counts()
    recommendations = recommend_project_managers(
        _load_roster(), requirement, performance_counts=pm_counts
    )
    selected = (project.get("selected_personnel") or {}).get("project_manager")
    return {
        "project_id": project_id,
        "requirement": requirement.model_dump(),
        "recommendations": [rec.model_dump() for rec in recommendations],
        "selected": selected,
    }


def recommend_tech_director_personnel(project_id: int) -> dict[str, Any]:
    """派生招标总工(项目技术负责人)要求 + 从公司名册推荐匹配候选(含当前选定)。"""
    project = _fetch_project(project_id)
    requirement = derive_tech_director_requirement(_project_requirements(project))
    _pm_counts, td_counts = _performance_role_counts()
    recommendations = recommend_tech_directors(
        _load_roster(), requirement, performance_counts=td_counts
    )
    selected = (project.get("selected_personnel") or {}).get("tech_director")
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


# 换人时要一并清掉的"该角色名下业绩勾选"列(勾选是对着旧人名下的候选做的)
_ROLE_PERF_COLUMN = {
    "project_manager": "selected_pm_performance",
    "tech_director": "selected_td_performance",
}


def _save_selected_role(
    project_id: int, role_key: str, member: dict[str, Any] | None
) -> dict[str, Any]:
    """存某角色(project_manager/tech_director)的选派,合并保留其它角色;None=清空该角色。

    人选变了(含清空)就把该角色的业绩勾选列重置为 NULL——旧勾选是对旧人名下候选做的,
    换人后无效;NULL=没勾(全部人工手选),生成留白,需对新人重新勾选。
    """
    clean = PersonnelMember(**member).model_dump() if member else None
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT selected_personnel FROM projects WHERE id = %s", (project_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ProjectNotFoundError(f"Project {project_id} was not found")
            payload: dict[str, Any] = dict(row["selected_personnel"] or {})
            old_name = str((payload.get(role_key) or {}).get("name") or "").strip()
            if clean:
                payload[role_key] = clean
            else:
                payload.pop(role_key, None)
            new_name = str((clean or {}).get("name") or "").strip()
            perf_column = _ROLE_PERF_COLUMN.get(role_key)
            reset_perf = bool(perf_column) and new_name != old_name
            perf_reset_sql = f", {perf_column} = NULL" if reset_perf else ""
            cursor.execute(
                f"""
                UPDATE projects
                SET selected_personnel = %s{perf_reset_sql}
                WHERE id = %s
                RETURNING id, selected_personnel
                """,
                (Json(payload), project_id),
            )
            row = cursor.fetchone()
    return {
        "project_id": int(row["id"]),
        "selected": row["selected_personnel"] or {},
    }


def save_selected_project_manager(
    project_id: int, member: dict[str, Any] | None
) -> dict[str, Any]:
    """存本项目选定的项目经理(member=名册里的一条记录;None=清空选派)。

    经理只决定"项目经理近年完成的类似项目"表填谁、以及人员表里的经理名/证件;
    **不碰用户在业绩面板选的类似业绩**(投标人业绩表跟用户选的走,见 similar_project_fill_service)。
    """
    return _save_selected_role(project_id, "project_manager", member)


def save_selected_tech_director(
    project_id: int, member: dict[str, Any] | None
) -> dict[str, Any]:
    """存本项目选定的总工/项目技术负责人(None=清空)。"""
    return _save_selected_role(project_id, "tech_director", member)
