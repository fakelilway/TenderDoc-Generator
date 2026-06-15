from services.bid_tone_checker import find_forbidden_tone, line_has_forbidden_tone


def test_find_forbidden_tone_reports_system_language() -> None:
    markdown = """# 投标文件

本部分仅生成报价文件目录和编制说明。
本报价文件依据招标文件编制。
资料名称：营业执照
"""

    findings = find_forbidden_tone(markdown)

    assert [finding.phrase for finding in findings] == ["本部分仅生成", "资料名称："]
    assert findings[0].line_number == 3


def test_find_forbidden_tone_returns_empty_for_clean_text() -> None:
    markdown = """# 投标文件

本报价文件依据招标文件编制。
"""

    assert find_forbidden_tone(markdown) == []


def test_find_forbidden_tone_flags_each_phrase_on_a_single_line() -> None:
    markdown = "本部分仅生成内容，且由用户填写关键字段。"

    findings = find_forbidden_tone(markdown)

    assert [finding.phrase for finding in findings] == ["本部分仅生成", "由用户填写"]
    assert all(finding.line_number == 1 for finding in findings)
    assert all(finding.line == markdown for finding in findings)


def test_find_forbidden_tone_accepts_custom_phrases() -> None:
    markdown = "第一行正常。\n含有违禁词的行。\n"

    findings = find_forbidden_tone(markdown, forbidden_phrases=("违禁词",))

    assert len(findings) == 1
    assert findings[0].phrase == "违禁词"
    assert findings[0].line_number == 2
    assert findings[0].line == "含有违禁词的行。"


def test_line_has_forbidden_tone() -> None:
    assert line_has_forbidden_tone("系统不自动生成任何报价数值")
    assert not line_has_forbidden_tone("本报价文件依据招标文件编制")
