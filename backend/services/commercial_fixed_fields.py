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
- 换公司 / 换项目要改这里。
- 例外:「质量」等 TENDER_FIRST_FALLBACK_FIELDS 字段是"招标优先、固定兜底"——
  优先用招标解析值,解析不到才用固定值(2026-07-11 员工反馈后用户拍板改的)。
"""

from __future__ import annotations

from typing import Any, Iterator

# 公司名权威值(全文一致性基准)。PDF 里出现过的错别字写法,生成时一律纠正为权威值。
AUTHORITATIVE_COMPANY_NAME = "安徽正奇建设有限公司"
COMPANY_NAME_TYPOS: tuple[str, ...] = ("安徽正气建设有限公司",)

# 固定字段规则:键=引擎 profile 键,值=直接落进商务标的文字。
COMMERCIAL_FIXED_FIELDS: dict[str, str] = {
    # —— 投标函 ——
    "安全": "无安全事故",                  # 安全目标
    "company_name": AUTHORITATIVE_COMPANY_NAME,   # 投标人 / 投标人名称 / 名称
    "legal_representative": "许明英",      # 法定代表人或其委托代理人 / 姓名
    # —— 投标函附录 ——
    "credit_code": "91340100578516708N",  # 统一社会信用代码
    # 企业资质等级:全量清单(2026-07-12 用户定稿——此前只写总承包贰级一项是错的,
    # 投标人基本情况表要列全部10项资质)
    "qualification_grade": (
        "公路工程施工总承包贰级；市政公用工程施工总承包贰级；"
        "公路交通工程（公路安全设施）专业承包贰级；公路路面工程专业承包贰级；"
        "公路路基工程专业承包贰级；环保工程专业承包贰级；"
        "城市及道路照明工程专业承包贰级；施工劳务序列不分等级；"
        "路基路面养护甲级资质；交通安全设施养护资质"
    ),
    # —— 投标人基本情况表:关联企业情况(2026-07-12 用户定稿,此前整个字段无人填) ——
    "affiliated_companies": (
        "投标人应提供关联企业情况，包括：\n"
        "（1）投标人的所有股东名称及相应股权（出资额）比例；如投标人为上市公司，"
        "投标人应提供股权占公司股份总数%以上的所有股东名称及相应股权比例；"
        "江舟:94.83%;许明英:5.16%;\n"
        "（2）投标人投资（控股）或管理的下属企业名称、持有股权（出资额）比例；无\n"
        "（3）与投标人单位负责人（即法定代表人）为同一人的其他单位名称。无"
    ),
    # —— 法定代表人身份证明 ——
    "法人性别": "女",
    "法人年龄": "50",
    "法人职务": "总经理",
    "法人身份证号": "340111197605197542",
    "法人联系方式": "13305691967",
}

# 招标优先、固定值兜底的字段:优先用招标文件(parser)解析出的值,解析不到才用这里的
# 固定值。2026-07-11 员工反馈"工程质量:合格 与前附表要求不一致"后,用户拍板把
# 质量从全固定改为招标优先(此前的"全固定"决策就此作废)。
TENDER_FIRST_FALLBACK_FIELDS: dict[str, str] = {
    "质量": "合格",                       # 工程质量:招标前附表有要求就用它,否则填"合格"
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
    以保证「固定规则 > 其它来源」。招标优先字段(TENDER_FIRST_FALLBACK_FIELDS)
    例外:招标解析出的值保留,只在空缺时补固定兜底值。
    """
    profile.update(COMMERCIAL_FIXED_FIELDS)
    for key, fallback in TENDER_FIRST_FALLBACK_FIELDS.items():
        if not str(profile.get(key) or "").strip():
            profile[key] = fallback
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
