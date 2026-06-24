"""身份证正反面分类器测试(用真实 OCR 文本样本)。"""

from __future__ import annotations

from services.id_card_ocr import classify_id_card_text

FRONT = "姓名江舟性别男民族汉出生1970年11月29日住址安徽省合肥市庐阳区凤台路88号上城国际丁香苑8幢701室公民身份号码340104197011291554"
BACK = "中华人民共和国居民身份证签发机关合肥市公安局庐阳分局有效期限2013.04.23-2033.04.23"
BOTH = FRONT + "中华人民共和国居民身份证签发机关合肥市公安局庐阳分局有效期限2013.04.23-2033.04.23"


def test_front_detected_with_name_and_id() -> None:
    out = classify_id_card_text(FRONT)
    assert out["side"] == "front"
    assert out["name"] == "江舟"
    assert out["id_number"] == "340104197011291554"


def test_back_detected_no_name() -> None:
    out = classify_id_card_text(BACK)
    assert out["side"] == "back"
    assert out["name"] == ""
    assert out["id_number"] == ""


def test_both_sides_combined_scan() -> None:
    out = classify_id_card_text(BOTH)
    assert out["side"] == "both"
    assert out["name"] == "江舟"
    assert out["id_number"] == "340104197011291554"


def test_unknown_when_not_id_card() -> None:
    out = classify_id_card_text("这是一张营业执照统一社会信用代码91340100xxxx")
    assert out["side"] == "unknown"


def test_id_number_with_x_checkdigit() -> None:
    out = classify_id_card_text("姓名张三性别女公民身份号码11010119900307123X")
    assert out["side"] == "front"
    assert out["name"] == "张三"
    assert out["id_number"] == "11010119900307123X"
