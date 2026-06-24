"""AssetResolver:按 owner_name / asset_type 解析出资料库里**真实的图片文件**。

关键:返回的不是"徐志身份证.jpg"这个名字,而是带 file_path / storage_key 的真实定位,
并能据此从 MinIO 读到字节。只认图片(jpg/jpeg/png);PDF/DOCX 证书本阶段不处理。

数据来源:documents 表(project_id IS NULL = 公司级),file_path 是 MinIO 对象 key
(形如 knowledge/{uuid}_xxx.jpg),后端/Docker 均可读,非开发者本地路径。
"""

from __future__ import annotations

from typing import Any

from rag.vector_store import _connect
from services.knowledge_service import get_knowledge_document_file_bytes

IMAGE_EXTS = ("jpg", "jpeg", "png")

# owner_type 入参既接受英文也接受中文,映射到 document_category
_OWNER_TYPE_TO_CATEGORY = {
    "personnel": ["人员证件"],
    "人员": ["人员证件"],
    "company": ["公司证件", "企业证件"],
    "公司": ["公司证件", "企业证件"],
}

_MIME_BY_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


def _mime_of(file_name: str, file_type: str | None) -> str:
    ext = (file_type or file_name.rsplit(".", 1)[-1] if "." in file_name else "").lower()
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def _row_to_asset(row: tuple, matched: bool = True) -> dict[str, Any]:
    doc_id, file_name, file_path, file_type, md = row
    md = md or {}
    return {
        "matched": matched,
        "asset_id": f"asset_{doc_id}",
        "document_id": int(doc_id),
        "asset_name": file_name,
        "asset_type": md.get("certificate_type") or md.get("document_type") or "",
        "owner_type": md.get("owner_type") or "",
        "owner_name": md.get("owner_name") or "",
        "role": md.get("role") or "",
        "file_path": file_path,  # MinIO 对象 key
        "storage_key": file_path,  # 同一个值,语义化别名
        "mime_type": _mime_of(file_name or "", file_type),
    }


def resolve_asset(
    owner_name: str | None = None,
    asset_type: str | None = None,
    owner_type: str | None = None,
    document_id: int | None = None,
) -> dict[str, Any]:
    """解析单个资产。匹配优先级:document_id > (owner_name + asset_type) > asset_type。

    返回 {matched, asset_name, document_id, file_path, storage_key, mime_type, ...};
    匹配不到返回 {"matched": False, "reason": ...}。
    """
    base = (
        "SELECT id, file_name, file_path, file_type, metadata_json FROM documents "
        "WHERE project_id IS NULL "
        f"AND lower(file_type) IN ({','.join(['%s'] * len(IMAGE_EXTS))}) "
        "AND coalesce(metadata_json->>'image_insertable','') <> 'false'"
    )
    params: list[Any] = list(IMAGE_EXTS)

    if document_id is not None:
        sql = base + " AND id = %s LIMIT 1"
        params.append(int(document_id))
    else:
        clauses = ""
        if owner_type:
            cats = _OWNER_TYPE_TO_CATEGORY.get(owner_type.strip().lower())
            if cats:
                clauses += f" AND metadata_json->>'document_category' IN ({','.join(['%s'] * len(cats))})"
                params.extend(cats)
        if owner_name:
            clauses += " AND metadata_json->>'owner_name' = %s"
            params.append(owner_name.strip())
        if asset_type:
            # 证件类型精确,或文件名含该类型(兜底)
            clauses += " AND (metadata_json->>'certificate_type' = %s OR file_name ILIKE %s)"
            params.extend([asset_type.strip(), f"%{asset_type.strip()}%"])
        if not clauses:
            return {"matched": False, "reason": "至少要给 owner_name / asset_type / document_id 之一"}
        sql = base + clauses + " ORDER BY created_at DESC, id DESC LIMIT 1"

    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()

    if not row:
        return {
            "matched": False,
            "reason": "资料库没有匹配的图片",
            "query": {"owner_name": owner_name, "asset_type": asset_type, "owner_type": owner_type},
        }
    return _row_to_asset(row)


def read_asset_bytes(document_id: int) -> bytes:
    """据 document_id 从 MinIO 读取真实图片字节(复用知识库的取字节逻辑)。"""
    return get_knowledge_document_file_bytes(int(document_id))


def _list_id_card_candidates(owner_name: str) -> list[tuple]:
    sql = (
        "SELECT id, file_name, file_path, file_type, metadata_json FROM documents "
        "WHERE project_id IS NULL "
        f"AND lower(file_type) IN ({','.join(['%s'] * len(IMAGE_EXTS))}) "
        "AND coalesce(metadata_json->>'image_insertable','') <> 'false' "
        "AND metadata_json->>'certificate_type' = '身份证' "
        "AND metadata_json->>'owner_name' = %s "
        "ORDER BY id"
    )
    with _connect() as conn, conn.cursor() as cursor:
        cursor.execute(sql, [*IMAGE_EXTS, owner_name.strip()])
        return cursor.fetchall()


def resolve_id_card(owner_name: str, side: str = "front") -> dict[str, Any]:
    """按 OCR 内容精确取某人的身份证**指定面**(正面有姓名,别抓错)。

    side: front(正面/人像面) / back(背面/国徽面) / both(正反合一)。
    会 OCR 每张候选图判面,并核对 OCR 出的姓名是否等于 owner_name。
    返回单张资产(同 resolve_asset 结构),额外带 side / ocr_name / name_verified。
    OCR 在每次调用时进行(身份证一般每人寥寥数张,可接受);要规模化可预先把面写进 metadata。
    """
    from services.id_card_ocr import classify_id_card

    rows = _list_id_card_candidates(owner_name)
    if not rows:
        return {"matched": False, "reason": f"资料库没有 {owner_name} 的身份证图片"}

    want = side.strip().lower()
    exact: dict | None = None
    both_fallback: dict | None = None
    for row in rows:
        asset = _row_to_asset(row)
        try:
            blob = read_asset_bytes(asset["document_id"])
            cls = classify_id_card(blob)
        except Exception:  # noqa: BLE001
            continue
        asset["side"] = cls["side"]
        asset["ocr_name"] = cls["name"]
        asset["id_number"] = cls["id_number"]
        asset["name_verified"] = bool(cls["name"]) and cls["name"] == owner_name.strip()
        if cls["side"] == want and exact is None:
            exact = asset
        if cls["side"] == "both" and both_fallback is None:
            both_fallback = asset

    chosen = exact or both_fallback  # 想要的面没单独的,正反合一也能用
    if not chosen:
        return {
            "matched": False,
            "reason": f"{owner_name} 的身份证里没找到「{side}」面(OCR判面后)",
            "candidates": len(rows),
        }
    return chosen


def pick_id_card_documents(owner_name: str) -> list[dict[str, Any]]:
    """某人身份证的**最小覆盖**选图:有完整版(正反合一)只取它1张;否则取正面+背面各1张。

    避免"完整版+正面+背面"重复堆插。返回 [asset,...](带 side),OCR 判面。
    """
    from services.id_card_ocr import classify_id_card

    classified: list[dict[str, Any]] = []
    for row in _list_id_card_candidates(owner_name):
        asset = _row_to_asset(row)
        try:
            cls = classify_id_card(read_asset_bytes(asset["document_id"]))
        except Exception:  # noqa: BLE001
            continue
        asset["side"] = cls["side"]
        asset["ocr_name"] = cls["name"]
        classified.append(asset)

    both = [a for a in classified if a["side"] == "both"]
    if both:
        return [both[0]]  # 完整版够了,正反都在一张上
    picked: list[dict[str, Any]] = []
    front = next((a for a in classified if a["side"] == "front"), None)
    back = next((a for a in classified if a["side"] == "back"), None)
    if front:
        picked.append(front)
    if back:
        picked.append(back)
    return picked
