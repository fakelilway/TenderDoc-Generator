"""投标人企业档案的读写与生成注入。

档案是单行表 company_profile(data JSONB)。生成标书时通过
``company_profile_prompt_block`` 注入 prompt，让模型用真实企业信息填写
投标人基本状况表、投标函落款等内容，而不是留空白。
"""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from core.config import get_settings
from core.db import get_db_connection
from schemas.company import COMPANY_PROFILE_FIELD_LABELS, CompanyProfile

_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS company_profile (
    id BIGSERIAL PRIMARY KEY,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def get_company_profile() -> dict[str, Any]:
    """Return the saved profile merged with defaults; never raises on empty DB."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(_ENSURE_TABLE_SQL)
            conn.commit()
            cursor.execute(
                "SELECT data, updated_at FROM company_profile ORDER BY id LIMIT 1"
            )
            row = cursor.fetchone()
    saved = dict(row["data"]) if row and row.get("data") else {}
    profile = CompanyProfile(**{
        key: str(saved.get(key, "") or "")
        for key in CompanyProfile.model_fields
    })
    if not profile.company_name:
        profile.company_name = get_settings().company_name
    return {
        "profile": profile.model_dump(),
        "updated_at": row["updated_at"].isoformat() if row else None,
    }


def save_company_profile(data: dict[str, Any]) -> dict[str, Any]:
    clean = {
        key: str(data.get(key, "") or "").strip()
        for key in CompanyProfile.model_fields
    }
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(_ENSURE_TABLE_SQL)
            cursor.execute("SELECT id FROM company_profile ORDER BY id LIMIT 1")
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    "UPDATE company_profile SET data = %s, updated_at = NOW() "
                    "WHERE id = %s",
                    (Json(clean), row["id"]),
                )
            else:
                cursor.execute(
                    "INSERT INTO company_profile (data) VALUES (%s)",
                    (Json(clean),),
                )
            conn.commit()
    return get_company_profile()


def company_profile_prompt_block(profile: dict[str, Any] | None) -> str:
    """Render the profile as prompt lines; empty fields are omitted."""
    if not profile:
        return ""
    lines = [
        f"- {label}：{str(profile.get(key, '') or '').strip()}"
        for key, label in COMPANY_PROFILE_FIELD_LABELS.items()
        if str(profile.get(key, "") or "").strip()
    ]
    return "\n".join(lines)
