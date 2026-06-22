"""证件档案:人员证件按"人"归、公司证件按"证件类型"归,供面板查看/改归属/改名。

跟业绩档案(performance_archive_service)一个套路,但证件的关联键是 owner_name:
  - 人员证件:owner_name=人名(300人,89张没主人待认领);grouping=人 → 证件类型 → 各张。
  - 公司证件:owner_name=公司,按 certificate_type 分组。

去重红线(用户强调):正反面/正副本/多页都不是重复,本服务一律不折叠、不删,只分组展示。
真重复(字节相同)留待后续按 hash 单独处理,这里不碰。
"""

from __future__ import annotations

from rag.vector_store import _connect

PERSON_CATEGORY = "人员证件"
COMPANY_CATEGORIES = ("公司证件", "企业证件")

# 人员证件类型展示顺序(资格审查常用的排前)
PERSON_TYPE_ORDER = [
    "身份证",
    "一级建造师证",
    "二级建造师证",
    "职称证书",
    "交安证",
    "建安证",
    "安全考核证",
    "造价工程师证",
    "八大员证书",
    "特种作业证",
    "养护工证书",
    "毕业证",
    "人员证件",
]


def _type_sort_key(cert_type: str) -> int:
    try:
        return PERSON_TYPE_ORDER.index(cert_type)
    except ValueError:
        return len(PERSON_TYPE_ORDER)


def list_person_archive() -> dict[str, object]:
    """人员证件按人归。返回 {persons:[{name,total,types,certs}], unassigned:[doc...], person_names:[...]}。"""
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, file_name, file_path,
                   coalesce(metadata_json->>'owner_name','') AS owner,
                   coalesce(metadata_json->>'certificate_type','人员证件') AS ctype
            FROM documents
            WHERE project_id IS NULL
              AND metadata_json->>'document_category' = %s
            ORDER BY owner, ctype, id
            """,
            (PERSON_CATEGORY,),
        )
        rows = cursor.fetchall()

    persons: dict[str, dict[str, object]] = {}
    unassigned: list[dict[str, object]] = []
    for doc_id, file_name, file_path, owner, ctype in rows:
        doc = {
            "document_id": int(doc_id),
            "file_name": file_name,
            "file_path": file_path,
            "cert_type": ctype,
        }
        if not owner.strip():
            unassigned.append(doc)
            continue
        person = persons.setdefault(owner, {"name": owner, "certs": {}, "total": 0})
        person["certs"].setdefault(ctype, []).append(doc)  # type: ignore[index]
        person["total"] = int(person["total"]) + 1  # type: ignore[arg-type]

    person_list = []
    for person in persons.values():
        certs = person["certs"]  # type: ignore[assignment]
        person["types"] = {t: len(v) for t, v in certs.items()}  # type: ignore[union-attr]
        person_list.append(person)
    person_list.sort(key=lambda p: str(p["name"]))

    return {
        "persons": person_list,
        "unassigned": unassigned,
        "person_names": [str(p["name"]) for p in person_list],
        "stats": {
            "person_count": len(person_list),
            "cert_total": sum(int(p["total"]) for p in person_list),
            "unassigned": len(unassigned),
        },
    }


def list_company_archive() -> dict[str, object]:
    """公司证件按 certificate_type 分组。"""
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, file_name, file_path,
                   coalesce(metadata_json->>'certificate_type','(未分类)') AS ctype
            FROM documents
            WHERE project_id IS NULL
              AND metadata_json->>'document_category' = ANY(%s)
            ORDER BY ctype, id
            """,
            (list(COMPANY_CATEGORIES),),
        )
        rows = cursor.fetchall()

    groups: dict[str, list[dict[str, object]]] = {}
    for doc_id, file_name, file_path, ctype in rows:
        groups.setdefault(ctype, []).append(
            {
                "document_id": int(doc_id),
                "file_name": file_name,
                "file_path": file_path,
                "cert_type": ctype,
            }
        )
    return {
        "groups": [
            {"cert_type": t, "docs": docs, "total": len(docs)}
            for t, docs in sorted(groups.items(), key=lambda kv: -len(kv[1]))
        ],
        "cert_types": sorted(groups.keys()),
        "stats": {"type_count": len(groups), "cert_total": sum(len(v) for v in groups.values())},
    }


def reassign_person_cert(document_ids: list[int], target_person: str) -> int:
    """把人员证件改挂到某人名下(改归属/合并人/认领,唯一写原语)。改 owner_name。"""
    target = (target_person or "").strip()
    if not target:
        raise ValueError("target_person 不能为空")
    ids = [int(i) for i in document_ids if str(i).strip()]
    if not ids:
        raise ValueError("document_ids 不能为空")
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE documents
            SET metadata_json = jsonb_set(
                jsonb_set(COALESCE(metadata_json,'{}'::jsonb),
                          '{owner_name}', to_jsonb(%s::text)),
                '{owner_type}', to_jsonb('人员'::text))
            WHERE id = ANY(%s) AND project_id IS NULL
              AND metadata_json->>'document_category' = %s
            """,
            (target, ids, PERSON_CATEGORY),
        )
        changed = cursor.rowcount
        cursor.execute(
            "UPDATE knowledge_chunks SET metadata = COALESCE(metadata,'{}'::jsonb) "
            "|| jsonb_build_object('owner_name', %s::text) WHERE document_id = ANY(%s)",
            (target, ids),
        )
        conn.commit()
    return int(changed)


def retype_company_cert(document_ids: list[int], target_type: str) -> int:
    """改公司证件的类型(归错类时纠正)。改 certificate_type。"""
    target = (target_type or "").strip()
    if not target:
        raise ValueError("target_type 不能为空")
    ids = [int(i) for i in document_ids if str(i).strip()]
    if not ids:
        raise ValueError("document_ids 不能为空")
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE documents
            SET metadata_json = jsonb_set(COALESCE(metadata_json,'{}'::jsonb),
                '{certificate_type}', to_jsonb(%s::text))
            WHERE id = ANY(%s) AND project_id IS NULL
              AND metadata_json->>'document_category' = ANY(%s)
            """,
            (target, ids, list(COMPANY_CATEGORIES)),
        )
        changed = cursor.rowcount
        conn.commit()
    return int(changed)


def rename_cert(document_id: int, title: str) -> None:
    """给单张证件改名(只改 file_name)。人员/公司证件通用。"""
    new_title = (title or "").strip()
    if not new_title:
        raise ValueError("名称不能为空")
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE documents SET file_name = %s WHERE id = %s AND project_id IS NULL "
            "AND metadata_json->>'document_category' = ANY(%s)",
            (new_title, int(document_id), [PERSON_CATEGORY, *COMPANY_CATEGORIES]),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"证件 {document_id} 不存在")
        conn.commit()
