"""商务标固定字段规则。

来源:《商务文件固定格式.pdf》(用户定稿)。这些字段在任何项目都填同一个固定值,
**优先级最高**:固定规则 > 公司档案库 > 招标文件 parser > AI/OCR 推导。生成商务标时
直接填、不让 AI 推理、不留空。背景见 memory `commercial-fixed-fields-locked`。

关键约定:
- 字典的 **键** 必须是填充引擎(original_docx_format_service)认识的 profile 键——
  英文档案键(company_name/credit_code/...)、中文项目键(质量/安全)、或法人键
  (法人性别/法人职务/...)。值就是要直接写进商务标的最终文字。
- 公司名权威值锁定「安徽正奇建设有限公司」;PDF 法人证明里那处「安徽正气建设有限公司」
  是错别字,生成时统一纠正(见 enforce_company_name_consistency)。
- 换公司 / 换项目要改这里(用户明确:这些字段全固定,不随招标要求变)。
"""

from __future__ import annotations

from typing import Any, Iterator

# 公司名权威值(全文一致性基准)。PDF 里出现过的错别字写法,生成时一律纠正为权威值。
AUTHORITATIVE_COMPANY_NAME = "安徽正奇建设有限公司"
COMPANY_NAME_TYPOS: tuple[str, ...] = ("安徽正气建设有限公司",)

# 固定字段规则:键=引擎 profile 键,值=直接落进商务标的文字。
COMMERCIAL_FIXED_FIELDS: dict[str, str] = {
    # —— 投标函 ——
    "质量": "合格",                       # 工程质量
    "安全": "无安全事故",                  # 安全目标
    "company_name": AUTHORITATIVE_COMPANY_NAME,   # 投标人 / 投标人名称 / 名称
    "legal_representative": "许明英",      # 法定代表人或其委托代理人 / 姓名
    # —— 投标函附录 ——
    "credit_code": "91340100578516708N",  # 统一社会信用代码
    "qualification_grade": "公路工程施工总承包贰级",  # 投标人响应资质
    # —— 法定代表人身份证明 ——
    "法人性别": "女",
    "法人年龄": "50",
    "法人职务": "总经理",
    "法人身份证号": "340111197605197542",
    "法人联系方式": "13305691967",
}

# 一致性检查里要"全文一致"核对的字段(键 → 中文名,仅用于告警可读)。
_CONSISTENCY_FIELDS: tuple[tuple[str, str], ...] = (
    ("company_name", "公司名称"),
    ("legal_representative", "法定代表人"),
    ("credit_code", "统一社会信用代码"),
)


def apply_fixed_fields(profile: dict[str, Any]) -> dict[str, Any]:
    """把固定字段规则以最高优先级覆盖进 profile(就地修改并返回)。

    必须在公司档案、招标 parser 派生字段、法人 OCR 推导都装配完之后再调用,
    以保证「固定规则 > 其它来源」。
    """
    profile.update(COMMERCIAL_FIXED_FIELDS)
    return profile


# ── 填充后收尾:错别字纠正 + 一致性核对 ────────────────────────────────────
# 下面两函数只吃 python-docx 的 Document 对象,不依赖填充引擎,避免循环导入。


def _iter_all_paragraphs(document: Any) -> Iterator[Any]:
    """文档正文 + 所有表格单元格里的段落。"""
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def enforce_company_name_consistency(document: Any) -> int:
    """全文把公司名错别字(安徽正气…)纠正为权威值(安徽正奇…)。返回纠正的段落数。

    优先逐 run 替换以保留格式;占位词跨 run 时回退到合并首 run。
    """
    fixed = 0
    for para in _iter_all_paragraphs(document):
        runs = para.runs
        if not runs:
            continue
        original = para.text
        updated = original
        for typo in COMPANY_NAME_TYPOS:
            updated = updated.replace(typo, AUTHORITATIVE_COMPANY_NAME)
        if updated == original:
            continue
        changed = False
        for run in runs:
            new_text = run.text
            for typo in COMPANY_NAME_TYPOS:
                new_text = new_text.replace(typo, AUTHORITATIVE_COMPANY_NAME)
            if new_text != run.text:
                run.text = new_text
                changed = True
        if not (changed and para.text == updated):
            # 占位词跨 run:合并到首 run
            runs[0].text = updated
            for run in runs[1:]:
                run.text = ""
        fixed += 1
    return fixed


def audit_commercial_fixed_fields(document: Any) -> list[str]:
    """填充后核对固定字段,返回问题清单(供日志/报告;空列表=全部通过)。

    检查:① 公司名/法人/信用代码的固定值有没有出现在商务标里(没出现=很可能没填上);
    ② 全文是否还残留公司名错别字。
    """
    full_text = "\n".join(p.text for p in _iter_all_paragraphs(document))
    issues: list[str] = []
    for typo in COMPANY_NAME_TYPOS:
        if typo in full_text:
            issues.append(
                f"全文仍出现错误公司名「{typo}」,应统一为「{AUTHORITATIVE_COMPANY_NAME}」"
            )
    for key, cn in _CONSISTENCY_FIELDS:
        value = COMMERCIAL_FIXED_FIELDS.get(key, "")
        if value and value not in full_text:
            issues.append(f"固定字段「{cn}={value}」未在商务标中出现(可能未填上,请检查)")
    return issues
