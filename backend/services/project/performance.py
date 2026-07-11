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


# 角色业绩勾选:role → (存储列, selected_personnel 里的人员键, 中文名)
_ROLE_PERF = {
    "pm": ("selected_pm_performance", "project_manager", "项目经理"),
    "td": ("selected_td_performance", "tech_director", "项目总工"),
}


def recommend_role_performance(project_id: int, role: str) -> dict[str, Any]:
    """选派的项目经理/总工名下的业绩候选(来自员工整理的《类似项目信息表》),供人工勾选。

    候选=该人作为项目经理/技术负责人的全部记录;勾选存对应列,生成时该角色的
    "近年完成的类似项目"表只填勾中的。**全部人工手选**(用户拍板,不默认全选):
    没勾(None/[])=生成留白。未选派该角色时 person=None、候选为空。
    """
    if role not in _ROLE_PERF:
        raise ValueError(f"unknown role: {role}")
    column, person_key, _label = _ROLE_PERF[role]
    project = _fetch_project(project_id)
    person = (project.get("selected_personnel") or {}).get(person_key) or {}
    person_name = str(person.get("name") or "").strip()

    recommendations: list[dict[str, Any]] = []
    if person_name:
        from services import performance_archive_service as pa
        from services import similar_project_info_service as spi
        from services.performance_selection_service import _curated_as_item

        records = (
            spi.records_for_manager(person_name)
            if role == "pm"
            else spi.records_for_tech_leader(person_name)
        )
        try:
            evidence_norms = {pa._norm(n) for n in pa.list_evidence_groups()}
        except Exception:
            evidence_norms = set()
        for record in records:
            item = _curated_as_item(record)
            has_ev = pa._norm(item["name"]) in evidence_norms
            item["has_evidence"] = has_ev
            item["matched"] = ["有证明扫描"] if has_ev else []
            item["gaps"] = [] if has_ev else ["缺证明扫描"]
            recommendations.append(item)

    # 信息表里当过该角色的人员分布(名字+条数):面板空时直接告诉用户"谁有业绩可选",
    # 免得选了个47表里没带过项目的人、看到空面板以为系统坏了(2026-07-12用户实测困惑)
    role_holders: list[dict[str, Any]] = []
    try:
        from collections import Counter

        from services import similar_project_info_service as spi2

        field = "project_manager" if role == "pm" else "tech_leader"
        counts = Counter(
            str(r.get(field) or "").strip()
            for r in spi2.list_similar_project_records()
        )
        counts.pop("", None)
        role_holders = [
            {"name": n, "count": c} for n, c in counts.most_common()
        ]
    except Exception:
        role_holders = []

    return {
        "project_id": project_id,
        "role": role,
        "person": person_name or None,
        "recommendations": recommendations,
        "selected": project.get(column),  # None/[]=没勾(留白);全部人工手选
        "role_holders": role_holders,
    }


def get_selected_role_performance(project_id: int, role: str) -> dict[str, Any]:
    """读某角色(pm/td)的业绩勾选。selected: None=没勾过(生成全填名下);[]=清空(留白)。"""
    if role not in _ROLE_PERF:
        raise ValueError(f"unknown role: {role}")
    column, _person_key, _label = _ROLE_PERF[role]
    project = _fetch_project(project_id)
    return {"project_id": project_id, "role": role, "selected": project.get(column)}


def save_selected_role_performance(
    project_id: int, role: str, items: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """存项目经理/总工业绩勾选(多选;空列表=清空→该角色表留白)。"""
    if role not in _ROLE_PERF:
        raise ValueError(f"unknown role: {role}")
    column, _person_key, _label = _ROLE_PERF[role]
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
                f"""
                UPDATE projects
                SET {column} = %s
                WHERE id = %s
                RETURNING id, {column}
                """,
                (Json(clean), project_id),
            )
            row = cursor.fetchone()
    if not row:
        raise ProjectNotFoundError(f"Project {project_id} was not found")
    return {
        "project_id": int(row["id"]),
        "role": role,
        "selected": row[column] or [],
    }


# 业绩证明选页(员工意见7):默认规则每类取前几张,盖章页排后面会被截掉;
# 人工选页后以勾选为准。与生成侧 v2_generation._PERF_PER_TYPE_CAP 保持同一默认口径。
_EVIDENCE_TYPE_ORDER = ("中标通知书", "合同", "交工验收")
_EVIDENCE_TYPE_CAP = {"中标通知书": 2, "合同": 2, "交工验收": 4}


def get_evidence_page_options(project_id: int, name: str) -> dict[str, Any]:
    """某条业绩的全部证明扫描页(按 中标→合同→交工、页序排列)+当前选页+默认会取哪几页。

    selected: None=没选过(生成走默认规则,界面按默认预勾);列表=以勾选为准。
    页从业绩证明库按项目名(归一化)匹配;库里没有则 pages 为空。
    """
    from services import performance_archive_service as pa

    project = _fetch_project(project_id)
    name = str(name or "").strip()
    if not name:
        raise ValueError("业绩项目名不能为空")

    pages: list[dict[str, Any]] = []
    try:
        groups = pa.list_evidence_groups()
        wanted = pa._norm(name)
        group = next(
            (g for key, g in groups.items() if pa._norm(str(key)) == wanted), None
        )
        if group:
            evidence: dict[str, list] = group.get("evidence") or {}
            known = [t for t in _EVIDENCE_TYPE_ORDER if t in evidence]
            others = [t for t in evidence if t not in _EVIDENCE_TYPE_ORDER]
            for etype in known + sorted(others):
                for doc in evidence.get(etype) or []:
                    pages.append(
                        {
                            "document_id": int(doc["document_id"]),
                            "file_name": str(doc.get("file_name") or ""),
                            "evidence_type": etype,
                            "evidence_seq": int(doc.get("evidence_seq") or 0),
                        }
                    )
    except Exception:
        pages = []

    default_ids: list[int] = []
    taken: dict[str, int] = {}
    for pg in pages:
        et = pg["evidence_type"]
        cap = _EVIDENCE_TYPE_CAP.get(et)
        if cap is None:
            continue  # 默认规则只取三类主链
        if taken.get(et, 0) < cap:
            taken[et] = taken.get(et, 0) + 1
            default_ids.append(pg["document_id"])

    stored = project.get("selected_evidence_pages") or {}
    selected = stored.get(name)
    if selected is None:  # 兼容:名字写法有出入时按归一化名再找一次
        from services.performance_archive_service import _norm

        selected = next(
            (v for k, v in stored.items() if _norm(str(k)) == pa._norm(name)), None
        )

    return {
        "project_id": project_id,
        "name": name,
        "pages": pages,
        "selected": selected,
        "default_ids": default_ids,
    }


def save_evidence_page_selection(
    project_id: int, name: str, document_ids: list[int] | None
) -> dict[str, Any]:
    """存某条业绩的证明选页。document_ids=None 恢复默认规则(删键);列表=只插这些页。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("业绩项目名不能为空")
    with _runtime.connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT selected_evidence_pages FROM projects WHERE id = %s",
                (project_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ProjectNotFoundError(f"Project {project_id} was not found")
            payload: dict[str, Any] = dict(row["selected_evidence_pages"] or {})
            if document_ids is None:
                payload.pop(name, None)
            else:
                clean: list[int] = []
                for d in document_ids:
                    try:
                        clean.append(int(d))
                    except (TypeError, ValueError):
                        continue
                payload[name] = clean
            cursor.execute(
                """
                UPDATE projects
                SET selected_evidence_pages = %s
                WHERE id = %s
                RETURNING id, selected_evidence_pages
                """,
                (Json(payload), project_id),
            )
            row = cursor.fetchone()
    return {
        "project_id": int(row["id"]),
        "name": name,
        "selected": (row["selected_evidence_pages"] or {}).get(name),
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
