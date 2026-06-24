"""身份证正反面识别(OCR):分清人像面(正面,有姓名/身份证号)与国徽面(背面)。

为什么必须 OCR:身份证正反两面文件名都叫"…身份证…",光看名字分不出。投标资格审查
通常正反两面都要,且姓名只在正面——抓错面就出问题。本模块 OCR 读内容后按关键词判面:
  - 正面(人像面):公民身份号码 / 姓名 / 住址 / 出生
  - 背面(国徽面):签发机关 / 有效期限
两面齐全(正反合一扫描)判为 both。同时抽取 姓名 / 身份证号,供核对归属。
"""

from __future__ import annotations

import re
from typing import Any

# 强特征:出现即高度确定是该面
_FRONT_STRONG = ("公民身份号码", "住址")
_FRONT_WEAK = ("姓名", "性别", "民族", "出生")
_BACK_MARKERS = ("签发机关", "有效期限", "有效期")


def classify_id_card_text(text: str) -> dict[str, Any]:
    """纯函数:给 OCR 文本,判正反面并抽姓名/身份证号。便于单测,不依赖 OCR 引擎。

    side ∈ front(正面) / back(背面) / both(正反合一) / unknown。
    """
    t = (text or "").replace(" ", "").replace("\n", "").replace("\t", "")

    has_front = any(m in t for m in _FRONT_STRONG) or sum(
        m in t for m in _FRONT_WEAK
    ) >= 2
    has_back = any(m in t for m in _BACK_MARKERS)

    if has_front and has_back:
        side = "both"
    elif has_front:
        side = "front"
    elif has_back:
        side = "back"
    else:
        side = "unknown"

    name = ""
    m = re.search(r"姓名([一-龥·]{1,10}?)(?:性别|$)", t)
    if m:
        name = m.group(1)

    id_number = ""
    m = re.search(r"(\d{17}[\dXx])", t)
    if m:
        id_number = m.group(1).upper()

    return {"side": side, "name": name, "id_number": id_number, "ocr_text": t}


def classify_id_card(image_bytes: bytes) -> dict[str, Any]:
    """对图片字节做 OCR 再判面。OCR 不可用时 side=unknown 并带 error。"""
    try:
        from utils.file_parser import extract_text_from_image

        text = extract_text_from_image(image_bytes) or ""
    except Exception as exc:  # noqa: BLE001
        return {"side": "unknown", "name": "", "id_number": "", "ocr_text": "", "error": str(exc)}
    return classify_id_card_text(text)
