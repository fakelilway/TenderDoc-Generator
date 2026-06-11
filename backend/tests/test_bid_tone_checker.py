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


def test_line_has_forbidden_tone() -> None:
    assert line_has_forbidden_tone("系统不自动生成任何报价数值")
    assert not line_has_forbidden_tone("本报价文件依据招标文件编制")
