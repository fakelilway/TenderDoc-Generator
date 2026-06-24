"""校验生成的 DOCX 里是否真的插入了图片(而不是只写了文件名)。

DOCX 本质是 zip,真插入的图片会落在 word/media/ 目录。该目录为空 = 没真插。
"""

from __future__ import annotations

import zipfile
from typing import Any


def count_docx_media(path: str) -> int:
    """返回 DOCX 里 word/media/ 下的图片文件数。"""
    with zipfile.ZipFile(path) as zf:
        return sum(
            1
            for n in zf.namelist()
            if n.startswith("word/media/") and not n.endswith("/")
        )


def list_docx_media(path: str) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return [
            n for n in zf.namelist()
            if n.startswith("word/media/") and not n.endswith("/")
        ]


def build_insert_report(
    path: str,
    expected_assets: list[dict[str, Any]],
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """生成插图 report:word/media 实有几张图,各资产是否插入成功。

    expected_assets: [{asset_name, asset_type, status}] 调用方按尝试结果填 status。
    """
    media = list_docx_media(path)
    inserted = [a for a in expected_assets if a.get("status") == "inserted"]
    missing = [a for a in expected_assets if a.get("status") != "inserted"]
    return {
        "docx_path": path,
        "word_media_count": len(media),
        "word_media_files": media,
        "inserted_image_count": len(inserted),
        "inserted_assets": inserted,
        "missing_assets": missing,
        "errors": errors or [],
        # 硬校验:真有图片落进 word/media 才算闭环成功
        "closed_loop_ok": len(media) > 0 and len(inserted) > 0,
    }
