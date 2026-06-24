from __future__ import annotations

import logging
import re
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn

logger = logging.getLogger(__name__)


FORMAT_CHAPTER_RE = re.compile(r"第[一二三四五六七八九十百\d]+章\s*(?:投标文件格式|响应文件格式)")
NEXT_CHAPTER_RE = re.compile(r"第[一二三四五六七八九十百\d]+章")
# A real next-chapter heading sits at the very start of a page (optionally after
# the page number), e.g. "106第八章评标办法". Anchoring here avoids treating a
# mid-sentence cross-reference ("…招标文件第二章…的要求") as a chapter boundary.
_NEXT_CHAPTER_HEAD_RE = re.compile(r"^\d{0,5}第[一二三四五六七八九十百\d]+章")
# Start of the 技术文件/报价文件 卷 inside the "投标文件格式" 章, e.g.
# "（标段名称）施工招标投标文件（技术文件）". The 商务卷 copy ends here.
_OTHER_VOLUME_START_RE = re.compile(r"投标文件\s*[（(]\s*(?:技术|报价|经济)")
# 技术卷附表区起始:页首(可带页码)就是"附表一 …"的那页才算起点,避免命中正文里
# 引用"附表一"的页或附表目录页(注:不可套 _skip_toc_pages——它会把稀疏附表误判成 TOC、丢表)。
_APPENDIX_START_RE = re.compile(r"^\d{0,5}附表一")
FORMAT_BODY_MARKERS = (
    "投标文件（商务文件）",
    "投标文件（技术文件）",
    "投标文件（报价文件）",
    "响应文件格式",
    "一、投标函",
)

# Maximum pages to scan after a chapter heading for TOC content
MAX_TOC_PAGES = 5


def build_original_format_docx(
    tender_docx_bytes: bytes,
    output_path: str | Path,
    *,
    profile: dict[str, Any] | None = None,
) -> str:
    """Copy the tender DOCX format chapter as OOXML, then fill known fields.

    This is intentionally not a markdown reconstruction path. Uses copy-then-prune
    (copy the source file, remove body children outside the format chapter) so the
    chapter keeps the tender's own Word XML AND its related parts — page
    headers/footers, embedded images, numbering — which a deepcopy into a fresh
    Document would drop. Merged cells, borders, underlines, alignment, spacing all
    survive.
    """
    source = Document(BytesIO(tender_docx_bytes))
    elements = list(source.element.body)
    start = _find_format_start(elements)
    if start is None:
        raise ValueError("未能在 DOCX 招标文件中定位“投标文件格式”章节，不能原样复制。")
    end = _find_format_end(elements, start)
    keep = set(range(start, end))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tender_docx_bytes)  # preserves headers/footers/images/parts

    target = Document(str(path))
    body = target.element.body
    for index, child in enumerate(list(body)):
        if child.tag == qn("w:sectPr"):
            continue  # keep the body section properties (and its header/footer refs)
        if index not in keep:
            body.remove(child)

    _replace_known_fields(target, profile or {})
    _strip_seal_images(target)  # 清招标原件带进来的招标人/代理红章(投标人章须人工手盖)
    target.save(str(path))
    return str(path)


def _clear_document_body(document: Document) -> None:
    body = document.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def _is_toc_line(text: str) -> bool:
    """A table-of-contents entry: dot/leader run, or leaders followed by a page no."""
    return bool(
        re.search(r"[.．·…]{4,}", text)
        or re.search(r"[.．·…]{2,}\s*\d{1,4}\s*$", text)
    )


def _find_format_start(elements: list[Any]) -> int | None:
    """Locate the start of the format chapter body.

    The chapter heading appears multiple times — in the TOC, in 须知 references,
    and as the actual chapter title. Use the LAST non-TOC heading (the real
    chapter usually follows the TOC and the body references), mirroring the PDF
    path's "use the last match". Falls back to the first body-form marker.
    """
    format_headings: list[int] = []
    first_body_marker: int | None = None
    for index, element in enumerate(elements):
        text = _element_text(element)
        if not text:
            continue
        compact = re.sub(r"\s+", "", text)
        if FORMAT_CHAPTER_RE.search(compact) and not _is_toc_line(text):
            format_headings.append(index)
        if first_body_marker is None and any(
            marker in compact for marker in FORMAT_BODY_MARKERS
        ):
            first_body_marker = index
    if format_headings:
        return format_headings[-1]
    return first_body_marker


def _find_format_end(elements: list[Any], start: int) -> int:
    for index in range(start + 1, len(elements)):
        text = _element_text(elements[index])
        if not text:
            continue
        compact = re.sub(r"\s+", "", text)
        if NEXT_CHAPTER_RE.match(compact) and not FORMAT_CHAPTER_RE.search(compact):
            return index
    return len(elements)


def _element_text(element: Any) -> str:
    return "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()


def _replace_known_fields(document: Document, profile: dict[str, Any]) -> None:
    replacements = _known_replacements(profile)
    if not any(replacements.values()):
        return  # No non-empty replacement targets — skip iteration entirely
    for paragraph in document.paragraphs:
        _replace_in_paragraph(paragraph, replacements)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _replace_in_paragraph(paragraph, replacements)


def _known_replacements(profile: dict[str, Any]) -> dict[str, str]:
    project_name = str(profile.get("项目名称") or profile.get("project_name") or "")
    tenderer = str(profile.get("招标人") or profile.get("tenderer_name") or "")
    company = str(profile.get("company_name") or profile.get("投标人") or "")
    duration = str(profile.get("工期") or profile.get("planned_duration") or "")
    quality = str(profile.get("质量") or profile.get("quality_standard") or "")
    safety = str(profile.get("安全") or profile.get("safety_target") or "")
    deadline = str(profile.get("投标有效期") or profile.get("投标截止时间") or profile.get("bid_deadline") or "")
    legal_rep = str(profile.get("legal_representative") or "")
    mapping = {
        "（招标人）": tenderer,
        "（招标人名称）": tenderer,
        "受益人（招标人）名称": tenderer,
        "(招标人名称)": tenderer,
        "（招标项目名称）": project_name,
        "（项目名称）": project_name,
        "（标段名称）": project_name,
        "（标段编号）": str(profile.get("标段编号") or profile.get("section_no") or ""),
        "（投标人名称）": company,
        "（工期）": duration,
        "（计划工期）": duration,
        "（质量标准）": quality,
        "（质量要求）": quality,
        "（质量目标）": quality,
        "（安全目标）": safety,
        "（安全生产目标）": safety,
        "（投标有效期）": deadline,
        "（投标截止时间）": deadline,
        "（开标时间）": deadline,
    }
    if legal_rep:
        # 授权委托书正文"本人（姓名）系…的法定代表人"——这里的（姓名）即法人,可填。
        # 仅锚定"本人"前缀,绝不全局替换（姓名）(人员表每行（姓名）不能都填成法人)。
        mapping["本人（姓名）"] = f"本人{legal_rep}"
        mapping["本人 （姓名）"] = f"本人 {legal_rep}"
    return mapping


def _replace_in_paragraph(paragraph, replacements: dict[str, str]) -> None:
    """Replace placeholder text while preserving per-run formatting.

    Instead of collapsing all runs into the first run (which destroys bold,
    italic, font size, etc.), this function performs replacements within
    each run individually. If a placeholder spans multiple runs, we fall
    back to paragraph-level replacement only for that specific placeholder.
    """
    if not paragraph.runs:
        return
    original = paragraph.text
    updated = original
    for source, target in replacements.items():
        if target:
            updated = updated.replace(source, target)
    if updated == original:
        return

    # Try per-run replacement first to preserve formatting
    changed = False
    for run in paragraph.runs:
        run_text = run.text
        new_text = run_text
        for source, target in replacements.items():
            if target:
                new_text = new_text.replace(source, target)
        if new_text != run_text:
            run.text = new_text
            changed = True

    if changed and paragraph.text == updated:
        return  # Per-run replacement succeeded — formatting preserved

    # Fallback: a placeholder spans multiple runs; collapse into first run
    first_run = paragraph.runs[0]
    for run in paragraph.runs[1:]:
        run.text = ""
    first_run.text = updated


# ── PDF original copy ──────────────────────────────────────────────────
# fitz (PyMuPDF) is imported lazily inside functions to avoid the ~2s module
# load overhead when only the DOCX path is used.


# Labels whose blank is segmented or date-like → never auto-fill(分段年/月/日 空)。
# 标签→值的映射统一走 _table_label_value(最长匹配 + 宽泛主体键防误填),不再用单字短键
# ("名"/"址")误把 法人/地址 乱配 —— PDF 烧录路径与可编辑表格路径共用同一套稳健映射。
_FILL_SKIP_KEYWORDS = ("成立", "日期", "经营期限", "别", "龄", "务", "年", "月", "日")


# ── 可编辑路径(pdf2docx)的表格自动填 ──────────────────────────────────
# 整页截图烧录只认下划线;可编辑路径产出真实 Word 表格(如投标人基本情况表),
# 这里按"标签单元格 → 同行右侧第一个空值格"填入公司档案。用**精确整标签**匹配
# (不用 _FILL_FIELD_ALIASES 的单字短键),避免技术负责人行的"姓名"被误填成法定
# 代表人。只写空格、不覆盖、不改表结构 → 保真。
_TABLE_FILL_LABELS: tuple[tuple[str, str], ...] = (
    ("投标人名称", "company_name"),
    ("投标人", "company_name"),
    ("注册地址", "registered_address"),
    ("单位性质", "company_type"),
    ("统一社会信用代码", "credit_code"),
    ("信用代码", "credit_code"),
    ("注册资本", "registered_capital"),
    ("企业资质等级", "qualification_grade"),
    ("资质等级", "qualification_grade"),
    ("投标人响应资质", "qualification_grade"),
    ("响应资质", "qualification_grade"),
    ("法定代表人", "legal_representative"),
    ("项目经理", "project_manager_name"),
    ("注册建造师", "project_manager_name"),
    ("安全生产许可证", "safety_license_no"),
    ("开户银行", "bank_name"),
    ("银行账号", "bank_account"),
    ("联系人", "contact_person"),
    ("经营范围", "business_scope"),
    ("成立时间", "establish_date"),
    ("成立日期", "establish_date"),
    # 扩标签别名:招标各家措辞不一(企业名称≠投标人名称…),覆盖常见同义写法,避免
    # 标签对不上而留空。靠最长匹配保证"注册地址">"注册地"、不会被短别名抢走。
    ("企业名称", "company_name"),
    ("公司名称", "company_name"),
    ("单位名称", "company_name"),
    ("投标人全称", "company_name"),
    ("法定代表", "legal_representative"),
    ("法人代表", "legal_representative"),
    ("住所", "registered_address"),
    ("注册地", "registered_address"),
    ("通讯地址", "registered_address"),
    ("联系地址", "registered_address"),
    ("联系电话", "contact_phone"),
    ("电话", "contact_phone"),
    ("手机", "contact_phone"),
    ("开户行", "bank_name"),
    ("开户银行名称", "bank_name"),
    ("账号", "bank_account"),
    # 项目级可推导字段:从招标解析得到,经 v2_generation_service.project_fields 以**中文键**
    # 并入 combined_profile(profile["项目名称"]/["工期"])。这里把表格标签映射到这些中文键,
    # 让基本情况表/投标函里的"项目名称""工期"格直接按招标值填上(不需公司档案)。
    ("项目名称", "项目名称"),
    ("工程名称", "项目名称"),
    ("标段名称", "项目名称"),
    ("项目工期", "工期"),
    ("计划工期", "工期"),
    ("总工期", "工期"),
    ("工期", "工期"),
    # 基本情况表补充字段(配合 company_profile 扩展字段;法人/技术负责人的职称电话走专项)
    ("邮政编码", "postal_code"),
    ("传真", "fax"),
    ("电子邮件", "email"),
    ("技术负责人", "tech_director_name"),
    ("高级职称人员", "senior_title_count"),
    ("中级职称人员", "mid_title_count"),
    ("初级职称人员", "junior_title_count"),
    ("技工", "technician_count"),
)
# 这些是"另一个人/需按行归属判断/格内填"的标签,通用"标签→右邻"逻辑绝不当作待填项。
# 技术职称/员工总人数 由 _fill_basic_info_subfields 专项按行上下文/格内处理(不走通用)。
_TABLE_FILL_SKIP = (
    "项目总工", "技术职称", "员工总人数",
)
# 子标签:行标签与值格之间的小标题(如 法定代表人 | 姓名 | [值]),右扫时跳过去找值格。
_TABLE_SUBLABELS = frozenset(
    {"姓名", "职称", "级别", "证号", "证书名称", "专业", "养老保险", "电话"}
)
# 留白/占位字符集。整格仅由这些组成 → 视为"空、该填"(下划线/省略号/点线签字线)。
# 关键取舍(经对抗验证):
#   · 空白/下划线/省略号 单个即算占位(它们从不作真实值用);
#   · 点线/破折号家族(. － — · 等)易与"无/不适用/小数/序号"混淆,要求连续≥2 才算占位,
#     孤立单个不判空(中文表里单格 "—"/"-" 常是人工填的"无");
#   · 句号 。(U+3002)永不判空(真标点,误判会覆盖真值);
#   · 含任何汉字/数字/字母 → 非空(绝不覆盖真值)。
_BLANK_SOLO_RE = re.compile(r"^[\s　_＿…‥]+$")
_BLANK_LEADER_CHARS = ".．·・‧․-－—–"
_BLANK_LEADER_RE = re.compile(
    rf"^[\s　_＿…‥{re.escape(_BLANK_LEADER_CHARS)}]+$"
)


def _is_blank_or_placeholder(text: str) -> bool:
    """整格仅由留白/占位字符组成 → 视为"空、该填"。详见 _BLANK_* 注释。"""
    s = (text or "").strip()
    if not s:
        return True
    if "。" in s:  # 句号是真标点,绝不当占位(防覆盖"…以上。"这类真内容)
        return False
    if _BLANK_SOLO_RE.match(s):
        return True
    if _BLANK_LEADER_RE.match(s):
        # 点线/破折号至少出现 2 个才算占位线,挡住孤立 "—"/"-"/"·"=「无/不适用」
        leader_count = sum(s.count(ch) for ch in _BLANK_LEADER_CHARS)
        return leader_count >= 2
    return False

# 宽泛"主体"键:标签里**含**它 ≠ 就该填它的名字。"投标人响应资质 / 项目经理身份证
# 号码 / …荣誉 / …业绩"含主体词但问的是别的字段——绝不能拿公司名/项目经理名去填(实测
# 122 商务卷正栽在这:项目经理身份证号被填成"江舟"、牵头人信用代码被填成公司名)。仅当
# 标签是"要名字"(键本身,或键+名称/姓名等名字尾巴)时才填,否则留空待人工。
# 注:不再按"保证金/保函"关键词留白——保证金承诺函里"投标人：(盖单位章)"、日期、邮编/电话/传真
# 都该正常填(用户实测要填);保证金金额/方式本无对应档案字段,本就填不上,无需特意留白。
_LEAVE_BLANK_KEYWORDS = ()

# 只有"联合体协议书"整章留白(单独投标无联合体,牵头人/成员名不填)。投标保证金不再整章留白。
_BLANK_SECTION_TITLES = ("联合体协议", "联合体共同")
_BLANK_SECTION_END_RE = __import__("re").compile(
    r"^[（(][一二三四五六七八九十百]+[)）]"  # （七）...
    r"|^[一二三四五六七八九十百]+[、.，]"  # 七、...
    r"|^第[一二三四五六七八九十]+[章节部]"  # 第七章
    r"|^\d+[、.]"  # 7. / 7、
)


def _blank_zone_step(para_text: str, in_blank: bool) -> bool:
    """状态机:按段顺序判断当前是否在"留白章节"(联合体协议书/投标保证金)内。

    遇到留白章节标题→进入;遇到下一个编号章节标题→退出。供填充循环实时跳过
    (不用 lxml 元素 id——它跨遍历不稳定)。
    """
    t = (para_text or "").strip()
    short = 0 < len(t) < 30
    if short and any(k in t for k in _BLANK_SECTION_TITLES):
        return True
    if (
        in_blank
        and short
        and _BLANK_SECTION_END_RE.search(t)
        and not any(k in t for k in _BLANK_SECTION_TITLES)
    ):
        return False
    return in_blank


# 福昕转换常把投标函/承诺函签名块的"投标人：__（盖单位章）"整行弄丢(只剩"法定代表人：（签字）")。
# 检测到签名块缺投标人行时,补一行"投标人：公司（盖单位章）"。法定代表人仍留人工签字。
_SIGN_REP_RE = __import__("re").compile(r"^法定代表人(或其?(授权|委托)代理人?)?[：:]")


def _fill_signature_bidder_line(document: Any, profile: dict[str, Any]) -> int:
    """签名块缺"投标人：__（盖单位章）"行时补上(福昕弄丢的)。联合体协议书区不补。"""
    company = str(profile.get("company_name") or "").strip()
    if not company:
        return 0
    paras = list(document.paragraphs)
    in_blank = False
    added = 0
    for idx, p in enumerate(paras):
        t = p.text.strip()
        in_blank = _blank_zone_step(t, in_blank)
        if in_blank:
            continue
        # 必须是签名块的"法定代表人："行(带 签字/盖章 标记)
        if not _SIGN_REP_RE.match(t) or not any(m in t for m in ("签字", "盖章")):
            continue
        # 往前看 ≤6 段有没有"投标人："行;遇标题/另一签名块/委托语境就停
        has_bidder = False
        skip_ctx = False  # 授权委托书/代理人语境 → 不补投标人(那里是委托人/代理人签字)
        empty_para = None
        steps = 0
        j = idx - 1
        while j >= 0 and steps < 6:
            pt = paras[j].text.strip()
            if pt == "":
                if empty_para is None:
                    empty_para = paras[j]
                j -= 1
                steps += 1
                continue
            if any(k in pt for k in ("委托", "代理人", "授权")):
                skip_ctx = True
                break
            if _BLANK_SECTION_END_RE.search(pt) or "法定代表人" in pt:
                break
            if pt.replace(" ", "").startswith("投标人") and ("：" in pt or ":" in pt):
                has_bidder = True
                break
            j -= 1
            steps += 1
        if has_bidder or skip_ctx:
            continue
        line = f"投 标 人： {company}（盖单位章）"
        if empty_para is not None:
            empty_para.add_run(line)  # 填进签名块前的空段(位置正好)
        else:
            p.insert_paragraph_before(line)  # 没空段就在法定代表人行前插一行
        added += 1
    return added


def _fill_legal_rep_columns(document: Any, profile: dict[str, Any]) -> int:
    """修福昕把法定代表人身份证明两列表单(姓名|性别、年龄|职务)压平、切断右列的问题。

    现象:"姓名：许明英性"(性别只剩'性'黏在名后)、"年龄：50职"(职务只剩'职')。
    做法:去掉末尾漏出的'性'/'职',补回"性别：法人性别"/"职务：法人职务"。值从档案/身份证OCR取。
    """
    gender = str(profile.get("法人性别") or "").strip()
    title = str(profile.get("法人职务") or "").strip()
    fixed = 0

    def _strip_tail_and_append(p, ch: str, appendix: str) -> bool:
        for r in reversed(p.runs):
            if not r.text:
                continue
            if r.text.endswith(ch):
                r.text = r.text[: -len(ch)]
                p.add_run(appendix)
                return True
            return False  # 末尾非空run但不以ch结尾 → 不动(安全)
        return False

    for p in document.paragraphs:
        norm = p.text.replace(" ", "").replace("　", "").strip()
        if not norm:
            continue
        # 姓名：X性 → 补 性别(右列被切,只剩'性')
        if norm.startswith("姓名") and norm.endswith("性") and "性别" not in norm and gender:
            if _strip_tail_and_append(p, "性", f"　　性别：{gender}"):
                fixed += 1
        # 年龄：X职 → 补 职务(只剩'职')
        elif norm.startswith("年龄") and norm.endswith("职") and "职务" not in norm and title:
            if _strip_tail_and_append(p, "职", f"　　职务：{title}"):
                fixed += 1
    return fixed


_BROAD_ENTITY_KEYS = frozenset({"投标人", "项目经理", "注册建造师"})
_NAME_TAILS = frozenset({"名称", "姓名", "名", "全称", "单位名称"})
# 判定"是否只剩名字尾巴"前,先剥掉这些主体周围的修饰词/装饰。
_ENTITY_MODIFIERS = (
    "独立", "或联合体", "联合体", "牵头人", "或", "单位", "本",
    "盖章", "公章", "签字", "（", "）", "(", ")",
)


def _label_to_profile_key(label: str) -> str:
    """标签 → 该填哪个档案字段(profile key);非可填标签返回 ""。

    取所有命中键里**最长(最具体)**的(让"统一社会信用代码"胜过宽泛"投标人",修
    first-in-list-order 误配);宽泛主体键(投标人/项目经理)只在标签"要名字"时才认,
    "投标人响应资质/项目经理身份证号"等子字段返回 ""(不乱填)。
    """
    norm = (
        label.replace(" ", "").replace("　", "").replace("：", "").replace(":", "").strip()
    )
    if not norm or any(skip in norm for skip in _TABLE_FILL_SKIP):
        return ""
    if any(kw in norm for kw in _LEAVE_BLANK_KEYWORDS):
        return ""  # 联合体/保证金 留白
    matches = [(key, pkey) for key, pkey in _TABLE_FILL_LABELS if key in norm]
    if not matches:
        return ""
    key, profile_key = max(matches, key=lambda kp: len(kp[0]))
    if key in _BROAD_ENTITY_KEYS:
        remainder = norm.replace(key, "", 1)
        for modifier in _ENTITY_MODIFIERS:
            remainder = remainder.replace(modifier, "")
        if remainder and remainder not in _NAME_TAILS:
            return ""
    return profile_key


def _table_label_value(label: str, profile: dict[str, Any]) -> str:
    profile_key = _label_to_profile_key(label)
    if not profile_key:
        return ""
    return str(profile.get(profile_key, "") or "").strip()


def unfilled_known_fields(
    document: Any, profile: dict[str, Any]
) -> list[tuple[str, str]]:
    """扫表格里"认得的标签、但公司档案无值 → 没法填"的字段,供显式告警(别静默留空)。

    返回 ``[(标签文本, profile_key), …]`` 去重。让出标前能提示"商务卷这些格因档案缺
    XX 字段没填上",而不是用户出完才发现一片空格。
    """
    seen: dict[str, str] = {}
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                profile_key = _label_to_profile_key(cell.text)
                if not profile_key or profile_key in seen:
                    continue
                if not str(profile.get(profile_key, "") or "").strip():
                    seen[profile_key] = cell.text.strip().replace("\n", " ")[:24]
    return [(label, profile_key) for profile_key, label in seen.items()]


def _log_unfilled_fields(document: Any, profile: dict[str, Any]) -> None:
    """显式告警:商务卷里认得的标签但档案无值 → 不静默留空,出标前留痕提示补档案。"""
    missing = unfilled_known_fields(document, profile)
    if missing:
        logger.warning(
            "商务卷有 %d 个可填字段因公司档案缺值未填(请在「公司档案」补全后重出):%s",
            len(missing),
            "、".join(label for label, _ in missing),
        )


def _set_cell_value(cell: Any, value: str) -> None:
    """Write a value into a table cell with a form-fitting font (宋体五号).

    新建空格默认会继承偏大的字号,在窄列(职务/证号 等)里被裁成"项目经""皖";
    显式设宋体 10.5pt 让 4 字职务/长证号能容下(过长则自动换行)。
    """
    from docx.shared import Pt

    paragraph = cell.paragraphs[0]
    runs = paragraph.runs
    if runs:
        run = runs[0]
        run.text = value
        for extra in runs[1:]:
            extra.text = ""
    else:
        run = paragraph.add_run(value)
    run.font.name = "Times New Roman"
    run.font.size = Pt(10.5)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(attr), "Times New Roman")
    rfonts.set(qn("w:eastAsia"), "SimSun")
    # 允许长串(如 17 位证号)在窄列里折行,而不是溢出被裁成"皖"
    from docx.oxml import OxmlElement

    p_pr = paragraph._p.get_or_add_pPr()
    if p_pr.find(qn("w:wordWrap")) is None:
        word_wrap = OxmlElement("w:wordWrap")
        word_wrap.set(qn("w:val"), "0")
        p_pr.append(word_wrap)


def _row_label_at(
    cells: Any, i: int, profile: dict[str, Any]
) -> tuple[str, int]:
    """从 cells[i] 起识别标签,支持被逐字拆进相邻短格的"碎标签"。

    中文公文表常把"投标人："逐字对齐成 `投|标|人：` 三格,单格匹配不到。
    这里把从 i 起连续的短格(≤3 字、非空)拼起来再匹配已知标签;一旦命中即返回
    ``(value, label_end_index)``(label_end 为标签占用的最后一格下标)。未命中返回
    ``("", i)``。只匹配 ``_TABLE_FILL_LABELS`` 里已有的标签,故不会凭空造出新标签。
    """
    text = cells[i].text.strip()
    value = _table_label_value(text, profile)
    if value:
        return value, i
    # 碎标签重组:仅拼接 ≤3 字的相邻短格(标签碎片如 投/标/人:),遇到值格/长文本即停。
    joined = text
    for k in range(i + 1, min(i + 4, len(cells))):
        if cells[k]._tc is cells[i]._tc:
            break  # 合并单元格,不算相邻碎片
        nxt = cells[k].text.strip()
        if not nxt or len(nxt) > 3:
            break
        joined += nxt
        v = _table_label_value(joined, profile)
        if v:
            return v, k
    return "", i


# ── 投标人基本情况表 专项填充 ─────────────────────────────────────────────
# 这张表 9 列、含"法定代表人|姓名|值|技术职称|值|电话|值"多子标签行,通用"标签→右邻"搞不定:
# ① 法人/技术负责人行的 技术职称/电话 必须按"本行归属"取值(否则通用会把"电话"当公司
# 联系电话 contact_phone 误填);② "员工总人数："是合并标签格、值要写格内冒号后。
# 故本函数须在 _fill_known_table_cells **之前**调用,先精确占位,通用逻辑再填其余空格。
_BASIC_INFO_PERSON_ROWS: dict[str, dict[str, str]] = {
    "法定代表人": {"技术职称": "legal_rep_title", "电话": "legal_rep_phone"},
    "技术负责人": {"技术职称": "tech_director_title", "电话": "tech_director_phone"},
}


def _append_to_cell(cell: Any, value: str) -> None:
    """在单元格已有文本(如"员工总人数：")后追加值,不覆盖标签。"""
    paras = cell.paragraphs
    if paras and paras[0].runs:
        paras[0].runs[-1].text = paras[0].runs[-1].text + value
    elif paras:
        paras[0].add_run(value)


def _fill_basic_info_subfields(document: Any, profile: dict[str, Any]) -> int:
    """投标人基本情况表专项:法人/技术负责人行的 技术职称·电话(按行归属),员工总人数(格内)。"""
    filled = 0
    for table in document.tables:
        full = " ".join(c.text for row in table.rows for c in row.cells)
        if "投标人名称" not in full or "员工总人数" not in full:
            continue
        for row in table.rows:
            cells = row.cells
            if not cells:
                continue
            submap = _BASIC_INFO_PERSON_ROWS.get(cells[0].text.strip())
            if submap:
                n = len(cells)
                for i in range(1, n):
                    key = submap.get(cells[i].text.strip())
                    if not key:
                        continue
                    val = str(profile.get(key, "") or "").strip()
                    if not val:
                        continue
                    for j in range(i + 1, n):
                        if cells[j]._tc is cells[i]._tc:
                            continue
                        if _is_blank_or_placeholder(cells[j].text.strip()):
                            _set_cell_value(cells[j], val)
                            filled += 1
                        break
            emp = str(profile.get("employee_total", "") or "").strip()
            if emp:
                for cell in cells:
                    t = cell.text.strip()
                    if t.startswith("员工总人数") and ("：" in t or ":" in t):
                        after = t.split("：")[-1].split(":")[-1].strip()
                        if not after:  # 冒号后还没值才填,避免重复追加
                            _append_to_cell(cell, emp)
                            filled += 1
                        break
            # 项目经理(或注册建造师)格:基本情况表此处填"人数",覆盖误填的人选名(语义=数量,非人名)
            pmc = str(profile.get("project_manager_count", "") or "").strip()
            if pmc:
                for ci, cell in enumerate(cells):
                    ct = cell.text.strip()
                    if ct.startswith("项目经理") and "职称" not in ct:
                        for j in range(ci + 1, len(cells)):
                            if cells[j]._tc is cell._tc:
                                continue
                            if cells[j].text.strip() in ("其中", "其 中"):
                                continue
                            _set_cell_value(cells[j], pmc)
                            filled += 1
                            break
                        break
    return filled


def _fill_establish_segmented(document: Any, profile: dict[str, Any]) -> int:
    """填"成立时间/日期：__年__月__日"这种分段空(法定代表人身份证明段)。

    establish_date 形如 2011-07-05 → 拆成 年=2011 / 月=7 / 日=5,分别填到"年/月/日"
    前最近的空槽(制表符/空格)。只动"成立时间/日期"标签之后、首组年月日,避免误填地址等处。
    """
    raw = str(profile.get("establish_date", "") or "").strip()
    m = re.match(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", raw)
    if not m:
        return 0
    parts = {"年": m.group(1), "月": str(int(m.group(2))), "日": str(int(m.group(3)))}
    filled = 0
    for para in document.paragraphs:
        if "成立时间" not in para.text and "成立日期" not in para.text:
            continue
        runs = para.runs
        started = False
        last_slot = None
        for i, r in enumerate(runs):
            t = r.text
            if not started:
                if any(k in t for k in ("成立时间", "立时间", "成立日期", "立日期")):
                    started = True
                continue
            stripped = t.strip()
            if stripped == "":  # 空格/制表符槽
                last_slot = i
            elif stripped[0] in parts:  # 命中 年/月/日
                if last_slot is not None and runs[last_slot].text.strip() == "":
                    runs[last_slot].text = parts[stripped[0]]
                    filled += 1
                last_slot = None
            else:
                last_slot = None  # 遇到其它实质文本,断开,避免跨太远误填
    return filled


# 投标日期=标书制作当天:这些是"别的日期",绝不当投标日期填(成立/有效期/截止/开标/出生/签发)。
_BID_DATE_SKIP = ("成立", "有效", "截止", "开标", "出生", "签发", "注册", "到期", "起止")


def _fill_bid_date_today(document: Any, today: Any = None) -> int:
    """把投标/签署日期的"__年__月__日"空槽填成标书制作当天(用户定)。

    只动:① 含"日期"标签的段(排除成立/有效期等);② 整段就是"年 月 日"+空槽的落款日期行。
    成立日期另由 _fill_establish_segmented 用 establish_date 填,这里跳过,不冲突。
    """
    import datetime as _dt

    d = today or _dt.date.today()
    parts = {"年": str(d.year), "月": str(d.month), "日": str(d.day)}
    filled = 0
    in_blank = False  # 联合体协议书/保证金章节内的日期不填(实时跟踪,lxml的id不稳)
    for para in document.paragraphs:
        text = para.text
        in_blank = _blank_zone_step(text, in_blank)
        if in_blank:
            continue
        if any(s in text for s in _BID_DATE_SKIP):
            continue
        has_ymd = "年" in text and "月" in text and "日" in text
        if not has_ymd:
            continue
        residue = re.sub(r"[年月日\s　_．.、]", "", text)
        # 落款日期行:整段只剩年月日+空槽(residue空),或明确含"日期"标签
        if not ("日期" in text or residue == ""):
            continue
        runs = para.runs
        # ① 拆 run 结构(福昕转换件常见):"__"是空 run、"年"是另一 run → 填前面的空槽
        last_slot = None
        for i, r in enumerate(runs):
            stripped = r.text.strip()
            if stripped == "":
                last_slot = i
            elif stripped[0] in parts:
                if last_slot is not None and runs[last_slot].text.strip() == "":
                    runs[last_slot].text = parts[stripped[0]]
                    filled += 1
                last_slot = None
            else:
                last_slot = None
        # ② 单 run 结构:"日期：__年_月_日"整串在一个 run → 正则就地把空槽换成今天
        for r in runs:
            t = r.text
            if not any(k in t for k in ("年", "月", "日")):
                continue
            new_t = re.sub(r"(?<![\d标])([_＿\s　]+)年", parts["年"] + "年", t)
            new_t = re.sub(r"(?<![\d])([_＿\s　]+)月", parts["月"] + "月", new_t)
            new_t = re.sub(r"(?<![\d])([_＿\s　]+)日", parts["日"] + "日", new_t)
            if new_t != t:
                r.text = new_t
                filled += 1
    return filled


def _fill_known_table_cells(document: Any, profile: dict[str, Any]) -> int:
    """基本情况表式网格自动填:标签格 → 同行右侧第一个空值格。

    只写空格、绝不覆盖、不改表结构(保真);未知标签和第二个人的子标签保持空白。
    支持标签被逐字拆进相邻格的"碎标签"(见 _row_label_at)。返回填入的格数。
    """
    if not any(profile.get(key) for _, key in _TABLE_FILL_LABELS):
        return 0
    filled = 0
    for table in document.tables:
        for row in table.rows:
            cells = row.cells
            n = len(cells)
            i = 0
            while i < n:
                value, label_end = _row_label_at(cells, i, profile)
                if not value:
                    i += 1
                    continue
                for j in range(label_end + 1, n):
                    target = cells[j]
                    if target._tc is cells[i]._tc:
                        continue  # 同一个合并单元格(含碎标签所在格)
                    text = target.text.strip()
                    if not _is_blank_or_placeholder(text) and _table_label_value(
                        text, profile
                    ):
                        break  # 右邻又是个已知标签,本标签不填
                    if text in _TABLE_SUBLABELS:
                        continue  # 子标签(姓名/职称等),跳过去找它后面的值格
                    if _is_blank_or_placeholder(text):
                        _set_cell_value(target, value)
                        filled += 1
                    break
                i = label_end + 1
    return filled


# 段落内联填空:"标签：<tab/下划线占位>" 这种写在正文里的空(投标函常用
# "工程质量：__，安全目标：__，工期：__日历天")。表格填空与 token 替换都不管它——
# 这是诊断早标注的"段落内联"缺口。只填白名单标签、只动 tab/占位 run、不覆盖已有值。
_INLINE_LABELS: tuple[tuple[str, str], ...] = (
    ("工程质量", "质量"),
    ("质量目标", "质量"),
    ("质量要求", "质量"),
    ("质量标准", "质量"),
    ("安全目标", "安全"),
    ("安全生产目标", "安全"),
    ("计划工期", "工期"),
    ("总工期", "工期"),
    ("工期", "工期"),
    ("项目名称", "项目名称"),
    ("工程名称", "项目名称"),
    # 正文表单(非签署块)里的可填名称/地址:法定代表人身份证明"投标人名称："等。
    # ⚠️已移除裸"投标人"/"法定代表人":它们只出现在签署块（盖单位章）/（签字）行,
    # 必须留人工盖章签字(用户明确要求,撤 c274972)。法人名走"姓名："语境特判 +
    # 基本情况表的表格路径,不在这里印到签字位。
    ("投标人名称", "company_name"),
    ("企业名称", "company_name"),
    ("公司名称", "company_name"),
    ("单位名称", "company_name"),
    ("投标人", "company_name"),  # 正文表单 + 签署块"投标人：__（盖单位章）"都填公司名(名字打前、标记保留)
    ("法定代表人或其委托代理人", "legal_representative"),
    ("法定代表人", "legal_representative"),  # 含签署块"法定代表人：__（签字或盖章）",名字打前、标记保留
    ("单位性质", "company_type"),
    ("企业性质", "company_type"),
    ("注册地址", "registered_address"),
    ("通讯地址", "registered_address"),
    ("联系地址", "registered_address"),
    ("住所", "registered_address"),
    ("地址", "registered_address"),  # 裸"地 址："(最长匹配保证 注册地址>地址,不抢具体标签)
    ("投标人响应资质", "qualification_grade"),
    ("响应资质", "qualification_grade"),
    ("经营期限", "business_term"),
    ("营业期限", "business_term"),
    # 基本账户/开户许可证段的正文空(原先只在表格里能填,正文段漏填):邮编/传真/电话/邮箱。
    # 法人语境的电话/联系方式由 _inline_value_for 的 id_proof 分支优先处理,不会被这里抢。
    ("邮政编码", "postal_code"),
    ("邮编", "postal_code"),
    ("传真", "fax"),
    ("电子邮件", "email"),
    ("电子邮箱", "email"),
    ("联系电话", "contact_phone"),
    ("电话", "contact_phone"),
)
_INLINE_DELIMS = "，,。.；;、\n\r"
# 模板里"标签：__单位"已带单位时,去掉值里重复的尾随单位(工期：90日历天日历天 → 90日历天)。
_INLINE_UNITS = ("日历天", "个月", "万元", "天", "元", "%")

# 紧跟槽位的签字/盖章标记 → 该槽永远留人工(撤 c274972 代签代盖)。这条单一规则同时
# 满足:①签署块不印名 ②正文表单(无此标记)照填。
_SIGN_MARKERS = (
    "（签字）", "(签字)", "（签 字）", "（签名）",
    "（盖单位章）", "(盖单位章)", "（盖章）", "(盖章)", "（盖公章）",
    "（签章）", "(签章)", "（公章）", "(公章)",
)
# 正文表单里成组出现的同级小标签:判定"标签：[空]下一个标签："→当前槽为空、可填。
_FORM_SIBLING_LABELS = (
    "投标人名称", "法定代表人", "姓名", "性别", "年龄", "职务", "职称",
    "电话", "传真", "邮政编码", "邮编", "地址", "住所", "联系人",
    "身份证号码", "身份证号",
)
# 槽位留白字符(空格/制表符/下划线/省略号/点线)。冒号后由这些组成的一段=待填槽。
_SLOT_CHARS = frozenset(" 　\t_＿…‥.．·・‧․-－—–")


def _looks_like_next_label(s: str) -> bool:
    """s 开头是否为"同级小标签 + 冒号"(如 性别：/性　别：)——判定前一个槽为空、可填。

    标签字之间常被排版拉开大空格("性　　别"),先去掉前若干字符里的空白再比对,
    否则"姓名"的填充会越过空格串进"性别",出现"许明英性别："。
    """
    # 去掉开头一段的空白(含全角)后再比对,容忍 "性  别：" 这类拉开的标签
    compact = s.replace(" ", "").replace("　", "").replace("\t", "")
    for lbl in _FORM_SIBLING_LABELS:
        if compact.startswith(lbl):
            rest = compact[len(lbl):]
            if rest[:1] in ("：", ":"):
                return True
    return False


def _iter_fillable_with_idproof(document: Any, track_idproof: bool):
    """按文档体顺序产出 (段落, 是否处于"法定代表人身份证明"章节)。含表格单元格段落。

    该章节里"姓名：性别：…职务："身份声明块的 姓名/性别/年龄=法人、可填;章节外(尤其人员表)
    绝不填,避免歧义误填(实测 122 卷"姓名"被误填法人)。以含"法定代表人身份证明"的短标题行为
    界,遇下一章节标题(协议书/保函/声明/资格审查)或 25 段/表后收口。
    **不跨遍历比对元素身份**——lxml 每次遍历新建代理、id() 不稳,故 section flag 随本遍历当场
    算出(否则段落版偶中、表格版必失效)。track_idproof=False(无法人名)时一律产出 False。
    """
    from docx.oxml.ns import qn as _qn
    from docx.table import Table as _Table
    from docx.text.paragraph import Paragraph as _Para

    inside = False
    count = 0
    for child in document.element.body.iterchildren():
        if child.tag == _qn("w:p"):
            p = _Para(child, document)
            if track_idproof:
                t = p.text.strip()
                # "授权委托书或法定代表人身份证明"是合并章标题,会把授权委托书段也圈进身份证明
                # 语境→委托代理人的身份证号/联系方式被误填成法人值。排除它,只认纯身份证明子标题。
                if "法定代表人身份证明" in t and "授权委托书" not in t and len(t) < 40:
                    inside, count = True, 0
                    yield p, True
                    continue
                if inside:
                    count += 1
                    if count > 25 or (
                        re.match(r"^[一二三四五六七八九（(]", t)
                        and any(w in t for w in ("协议书", "投标保", "声明函", "资格审查"))
                    ):
                        inside = False
            yield p, inside
        elif child.tag == _qn("w:tbl"):
            if track_idproof and inside:
                count += 1
            for row in _Table(child, document).rows:
                for cell in row.cells:
                    for cp in cell.paragraphs:
                        yield cp, inside


def _inline_value_for(
    seg: str,
    profile: dict[str, Any],
    para_text: str = "",
    id_proof_context: bool = False,
) -> str:
    """seg=冒号前刚累计的文字;其结尾是已知内联标签且档案有值 → 返回值,否则 ""。

    特例:正文"姓名："仅在法定代表人身份证明语境(本段含"的法定代表人",或处于身份证明
    章节的身份声明块)才填法人名,避免把人员表/其他人的"姓名"误填成法人。
    """
    norm = seg.replace(" ", "").replace("　", "")
    # 保证金/保函 留白:只看**标签本身**(如"投标保证金金额：")。绝不看整段——投标函正文
    # 里顺带提到"投标保证金"会把整段的质量/工期等空也误留白(实测回归)。章节级留白另由
    # _blank_zone_step 处理。
    if any(kw in norm for kw in _LEAVE_BLANK_KEYWORDS):
        return ""
    if norm.endswith("姓名") and (id_proof_context or "的法定代表人" in para_text):
        return str(profile.get("legal_representative", "") or "").strip()
    # 法定代表人身份证明表的 性别/年龄(从法人身份证 OCR 推导,见 v2._legal_rep_pii)。
    # 职务无据可填 → 不在此返回,留人工。仅在身份证明语境(章节归属 或 同段含"的法定
    # 代表人")填,避免误填人员表。
    _idp = id_proof_context or "的法定代表人" in para_text
    if _idp and norm.endswith("性别"):
        return str(profile.get("法人性别", "") or "").strip()
    if _idp and norm.endswith("年龄"):
        return str(profile.get("法人年龄", "") or "").strip()
    # 职务/联系方式/身份证号:OCR 取不到,由固定字段规则供值(见 commercial_fixed_fields)。
    # 仅在身份证明语境填,避免人员表"职务"列、委托代理人"联系方式/身份证号"被误填成法人值。
    if _idp and norm.endswith("职务"):
        return str(profile.get("法人职务", "") or "").strip()
    if _idp and (
        norm.endswith("联系方式")
        or norm.endswith("联系电话")
        or norm.endswith("手机号码")
        or norm.endswith("手机号")
    ):
        return str(profile.get("法人联系方式", "") or "").strip()
    if _idp and (norm.endswith("身份证号") or norm.endswith("身份证号码")):
        return str(profile.get("法人身份证号", "") or "").strip()
    best_label = ""
    for label, _key in _INLINE_LABELS:
        if norm.endswith(label) and len(label) > len(best_label):
            best_label = label
    if not best_label:
        return ""
    key = next(k for lbl, k in _INLINE_LABELS if lbl == best_label)
    return str(profile.get(key, "") or "").strip()


def _iter_fillable_paragraphs(document: Any):
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _fill_inline_labeled_blanks(document: Any, profile: dict[str, Any]) -> int:
    """填 "标签：<槽位>" 这类段落内联空(投标函工程质量/安全/工期、法代身份证明
    投标人名称/姓名 等)。返回填入数。

    **不依赖 run 边界**:把整段拼成全文 + 记每个字符归属哪个 run,在全文上识别
    "标签：<槽位>"。槽位 = 冒号后的一段留白(tab/下划线/省略号/点线),或空槽(冒号后
    直接接分隔符/括号/下一个同级小标签)。命中后把该段在所属 run 里替成值。
    **签字/盖章守卫**:槽位后若紧跟（签字）/（盖单位章）等标记,一律跳过留人工(撤
    c274972,不代签代盖)。标签须紧贴冒号、跨分隔符作废;只填空槽、绝不覆盖真值;单位去重。
    """
    has_legal_rep = bool(str(profile.get("legal_representative") or "").strip())
    has_data = any(profile.get(key) for _lbl, key in _INLINE_LABELS) or has_legal_rep
    if not has_data:
        return 0
    filled = 0
    in_blank = False  # 联合体协议书/保证金 章节整段留白(实时跟踪)
    for paragraph, id_proof_ctx in _iter_fillable_with_idproof(document, has_legal_rep):
        runs = paragraph.runs
        if not runs:
            continue
        para_text = paragraph.text
        in_blank = _blank_zone_step(para_text, in_blank)
        if in_blank:
            continue
        # 全文 + 每字符 (run下标, run内下标)
        chars: list[str] = []
        owner: list[tuple[int, int]] = []
        for ri, run in enumerate(runs):
            for li, ch in enumerate(run.text):
                chars.append(ch)
                owner.append((ri, li))
        s = "".join(chars)
        n = len(s)
        # (run下标, run内起, run内止, 值):把 run.text[起:止] 替成值(起==止 即插入)
        edits: list[tuple[int, int, int, str]] = []
        seg = ""
        i = 0
        while i < n:
            ch = s[i]
            if ch in "：:":
                label_seg = seg  # 当前标签(冒号前),用于签字处守卫
                value = _inline_value_for(seg, profile, para_text, id_proof_ctx)
                seg = ""
                if value:
                    j = i + 1
                    while j < n and s[j] in " 　":  # 跳过冒号后的空格/全角空格
                        j += 1
                    k = j
                    while k < n and s[k] in _SLOT_CHARS:  # 吃掉留白槽(tab/下划线/点线)
                        k += 1
                    # 用户定:法定代表人签字/盖章处留白(人工签),不打名字;投标人(盖单位章)照填公司名。
                    _lbl = label_seg.replace(" ", "").replace("　", "")
                    _is_legal_rep = _lbl.endswith(("法定代表人", "法人代表", "委托代理人"))
                    _after = s[k : k + 12]
                    _is_sign_spot = any(m in _after for m in _SIGN_MARKERS) or (
                        "签字" in _after or "签名" in _after
                    )
                    if _is_legal_rep and _is_sign_spot:
                        i += 1
                        continue  # 法人签字处留白
                    # 用户拍板(签字盖章块):投标人/法定代表人在「（盖单位章）」「（签字或盖章）」前
                    # 打上公司名/姓名,标记原样保留——填的是冒号后留白槽 s[j:k],标记在 s[k:] 不动,
                    # 故不再因签字/盖章标记跳过(区别于曾被否的 c274972"代签代盖":那是把标记替换掉)。
                    # 日期(年/月/日)无标签映射,仍留空给人工。
                    had_blank = k > j
                    empty_ok = (
                        k >= n
                        or s[k] in _INLINE_DELIMS
                        or s[k] in "（("
                        or _looks_like_next_label(s[k:])
                    )
                    if not (had_blank or empty_ok):
                        i += 1
                        continue  # 槽位后是真实值,不覆盖
                    after = s[k : k + 14].lstrip()
                    for unit in _INLINE_UNITS:  # 模板已带单位则去重
                        if after.startswith(unit) and value.endswith(unit):
                            value = value[: -len(unit)].strip()
                            break
                    if j == k:  # 空槽 → 在 j 处插入值
                        if j < n:
                            ri, li = owner[j]
                        else:
                            ri, li = len(runs) - 1, len(runs[-1].text)
                        edits.append((ri, li, li, value))
                    else:  # 留白槽 → 替换 s[j:k]
                        rj, lj = owner[j]
                        rk, lk = owner[k - 1]
                        if rj == rk:
                            edits.append((rj, lj, lk + 1, value))
                        else:  # 跨 run:值进首段,清掉其余留白段
                            edits.append((rj, lj, len(runs[rj].text), value))
                            for mid in range(rj + 1, rk):
                                edits.append((mid, 0, len(runs[mid].text), ""))
                            edits.append((rk, 0, lk + 1, ""))
                    filled += 1
                    i = k
                    continue
            elif ch in _INLINE_DELIMS:
                seg = ""
            else:
                seg += ch
            i += 1
        # 每个 run 从后往前应用,避免前面的替换移位后面的下标
        for ri, a, b, val in sorted(edits, key=lambda e: (e[0], -e[1])):
            run = runs[ri]
            text = run.text
            run.text = text[:a] + val + text[b:]
    return filled


# 项目经理(项目技术负责人)简历表的标签 → resume 字段键。只在简历表内填,不外溢。
_PM_RESUME_LABELS: tuple[tuple[str, str], ...] = (
    ("拟在本标段", "拟任职务"),  # 拟在本标段工程担任职务
    ("毕业学校", "毕业学校"),
    ("姓名", "姓名"),
    ("年龄", "年龄"),
    ("学历", "学历"),
    ("职称", "职称"),
    ("性别", "性别"),
    ("专业", "专业"),
)


def _fill_pm_resume_table(document: Any, resume: dict[str, Any]) -> int:
    """填"项目经理(项目技术负责人)简历"表:姓名/年龄/学历/职称/拟任职务/毕业学校/专业。

    只在简历表内(含"拟在本标段")按标签填右邻空格;经历/获奖等填不到的留白。返回填入格数。
    """
    if not resume or not resume.get("姓名"):
        return 0
    filled = 0
    for table in document.tables:
        full = " ".join(c.text for row in table.rows for c in row.cells)
        if "拟在本标段" not in full:  # 唯一锚:只认简历表
            continue
        for row in table.rows:
            cells = row.cells
            for i, cell in enumerate(cells):
                ctext = cell.text.strip()
                key = next(
                    (k for lbl, k in _PM_RESUME_LABELS if ctext.startswith(lbl) or ctext == lbl),
                    None,
                )
                if not key:
                    continue
                val = str(resume.get(key, "") or "").strip()
                if not val:
                    continue
                for j in range(i + 1, len(cells)):
                    if cells[j]._tc is cell._tc:
                        continue
                    if _is_blank_or_placeholder(cells[j].text.strip()):
                        _set_cell_value(cells[j], val)
                        filled += 1
                    break
    return filled


def _fill_authorization_letter(document: Any, profile: dict[str, Any]) -> int:
    """授权委托书:"本人 ___（姓名）系 ___（投标人名称）的法定代表人" 里第一个（姓名）填法人名。

    占位形态是"空白在前、括号提示在后"(___（姓名）),通用内联引擎只认"标签：___"故不覆盖。
    严格语境锚定:只在含"法定代表人"+"委托/代理人"的段、且匹配"本人…（姓名）系"才填,绝不全局
    填'（姓名）'(否则人员表/项目经理简历的姓名会被误填成法人)。委托代理人那个（姓名）留白(法人亲签)。
    (投标人名称已由 _known_replacements 的 '（投标人名称）'→company 处理,这里不碰。)
    """
    import re as _re
    from collections import defaultdict

    legal_rep = str(profile.get("legal_representative") or "").strip()
    if not legal_rep:
        return 0
    filled = 0
    for paragraph in document.paragraphs:
        runs = paragraph.runs
        if not runs:
            continue
        owner: list[tuple[int, int]] = []
        for ri, run in enumerate(runs):
            for li in range(len(run.text)):
                owner.append((ri, li))
        s = "".join(r.text for r in runs)
        if "法定代表人" not in s or ("委托" not in s and "代理人" not in s):
            continue
        m = _re.search(r"本人[ \t　_＿]*（\s*姓\s*名\s*）系", s)
        if not m:
            continue
        bg = m.start() + 2  # "本人" 之后
        paren = s.find("（", m.start())
        be = paren  # 空白槽 = s[bg:be]
        if s[bg:be].strip():  # 槽里已有实质内容(已填) → 不覆盖
            continue
        edits: list[tuple[int, int, int, str]] = []
        if be > bg:  # 有空白槽:首空白字符替成法人名,其余空白清掉
            ri0, li0 = owner[bg]
            edits.append((ri0, li0, li0 + 1, legal_rep))
            for k in range(bg + 1, be):
                rk, lk = owner[k]
                edits.append((rk, lk, lk + 1, ""))
        else:  # 无槽:插到"本人"之后
            ri0, li0 = owner[m.start() + 1]
            edits.append((ri0, li0 + 1, li0 + 1, legal_rep))
        by_run: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
        for ri, a, b, v in edits:
            by_run[ri].append((a, b, v))
        for ri, ops in by_run.items():
            t = runs[ri].text
            for a, b, v in sorted(ops, reverse=True):
                t = t[:a] + v + t[b:]
            runs[ri].text = t
        filled += 1
    return filled


def _fill_personnel_table(document: Any, profile: dict[str, Any]) -> bool:
    """填"项目管理机构人员组成表"的项目经理 + 总工两行(职务/姓名/职称/证号),从选派取。

    列表头驱动的多列表(职务|姓名|职称|证书名称|级别|证号|专业|养老保险|备注)。
    只填空格、首数据行已有人则整表留人工、不改表结构。返回是否填了。
    """
    pm_name = str(profile.get("project_manager_name") or "").strip()
    tech_name = str(profile.get("tech_director_name") or "").strip()
    if not pm_name and not tech_name:
        return False
    # 要填的人:(职务, 姓名, 证号, 职称)。总工职务=项目技术负责人(用户定)。
    people: list[tuple[str, str, str, str]] = []
    if pm_name:
        people.append((
            "项目经理", pm_name,
            str(profile.get("project_manager_cert") or "").strip(),
            str(profile.get("project_manager_title") or "").strip(),
        ))
    if tech_name:
        people.append((
            "项目技术负责人", tech_name,
            str(profile.get("tech_director_cert") or "").strip(),
            str(profile.get("tech_director_title") or "").strip(),
        ))

    for table in document.tables:
        try:
            rows = table.rows
            n_cols = len(table.columns)
            if len(rows) < 2 or n_cols < 3:
                continue

            def header(col: int, _rows=rows, _table=table) -> str:
                return " ".join(
                    _table.cell(r, col).text.strip() for r in range(min(2, len(_rows)))
                )

            headers = [header(c) for c in range(n_cols)]
            col_role = next((c for c, h in enumerate(headers) if "职务" in h), None)
            col_name = next((c for c, h in enumerate(headers) if "姓名" in h), None)
            col_cert = next(
                (c for c, h in enumerate(headers) if "证号" in h or "证书号" in h), None
            )
            col_title = next((c for c, h in enumerate(headers) if "职称" in h), None)
            if col_role is None or col_name is None:
                continue
            # 必须是"人员组成"表(含证书/资格证明列),别误填别的两列表
            if not any(("证书" in h or "资格证明" in h or "证号" in h) for h in headers):
                continue
            # 执业资格证明跨行、子列在第2行 → 表头占2行,数据从第3行起
            two_row_header = any(
                ("证书名称" in headers[c] or "级别" in headers[c] or "证号" in headers[c])
                for c in range(n_cols)
            )
            data_r = 2 if two_row_header else 1
            if data_r >= len(rows):
                continue

            if not _is_blank_or_placeholder(table.cell(data_r, col_name).text.strip()):
                continue  # 首数据行已有人,整表留人工
            filled_any = False
            ri = data_r
            for role, name, cert, title in people:
                # 找下一个姓名空的行
                while ri < len(rows) and not _is_blank_or_placeholder(
                    table.cell(ri, col_name).text.strip()
                ):
                    ri += 1
                if ri >= len(rows):
                    break
                _set_cell_value(table.cell(ri, col_name), name)
                if _is_blank_or_placeholder(table.cell(ri, col_role).text.strip()):
                    _set_cell_value(table.cell(ri, col_role), role)
                if col_cert is not None and cert and _is_blank_or_placeholder(
                    table.cell(ri, col_cert).text.strip()
                ):
                    _set_cell_value(table.cell(ri, col_cert), cert)
                if col_title is not None and title and _is_blank_or_placeholder(
                    table.cell(ri, col_title).text.strip()
                ):
                    _set_cell_value(table.cell(ri, col_title), title)
                filled_any = True
                ri += 1
            if filled_any:
                return True
        except Exception:
            continue
    return False


def _fill_performance_table(document: Any, profile: dict[str, Any]) -> int:
    """填"投标人业绩情况表"(业绩序号|项目名称（合同名称）|备注)的项目名称列,用选中的类似业绩。

    只填空格、首数据行已有内容则整表留人工(保真)。返回填入的行数。
    选中业绩来自 profile['selected_performance'](_apply_selected_project_manager 注入,已去重)。
    """
    perf = profile.get("selected_performance") or []
    names: list[str] = []
    seen: set[str] = set()
    for p in perf:
        nm = str(p.get("name", "")).strip()
        if nm and nm not in seen:  # 函数内也去重(双保险,防勾重)
            seen.add(nm)
            names.append(nm)
    if not names:
        return 0

    filled = 0
    for table in document.tables:
        try:
            rows = table.rows
            n_cols = len(table.columns)
            if len(rows) < 2 or n_cols < 2:
                continue
            headers = [table.cell(0, c).text.strip() for c in range(n_cols)]
            # 必须是"业绩情况表":含"业绩序号"列 + "项目名称/合同名称"列
            if not any("业绩序号" in h for h in headers):
                continue
            col_name = next(
                (c for c, h in enumerate(headers)
                 if "项目名称" in h or "合同名称" in h or "工程名称" in h),
                None,
            )
            col_seq = next((c for c, h in enumerate(headers) if "业绩序号" in h or "序号" in h), None)
            if col_name is None:
                continue
            # 首数据行项目名称已有内容 → 留人工
            if not _is_blank_or_placeholder(table.cell(1, col_name).text.strip()):
                continue
            i = 0
            for ri in range(1, len(rows)):
                if i >= len(names):
                    break
                cell = table.cell(ri, col_name)
                t = cell.text.strip()
                if t and t not in ("……", "…", "...", "．．．"):
                    continue  # 该行已有项目名,跳过
                _set_cell_value(cell, names[i])
                # 序号列若是 …… 或空,补成序号数字
                if col_seq is not None:
                    st = table.cell(ri, col_seq).text.strip()
                    if not st or st in ("……", "…", "..."):
                        _set_cell_value(table.cell(ri, col_seq), str(i + 1))
                i += 1
                filled += 1
        except Exception:
            continue
    return filled


def _image_is_seal(blob: bytes) -> bool:
    """True if the image is a red ink seal (公章/印章).

    印章=红印泥,整图红像素占比高(实测招标人/代理公章 22%~30%);证件扫描、附表
    线框图、页面截图近 0%(黑字白底,即便角上有小红章也 <2%)。阈值 5% 干净区分。
    """
    from io import BytesIO

    try:
        from PIL import Image

        im = Image.open(BytesIO(blob)).convert("RGBA")
    except Exception:
        return False
    w, h = im.size
    if w * h == 0:
        return False
    if w * h > 14400:  # 大图抽样提速,不影响占比估计
        im = im.resize((min(w, 120), min(h, 120)))
    pixels = list(im.getdata())
    red = sum(
        1
        for r, g, b, a in pixels
        if a > 40 and r > 110 and r - g > 40 and r - b > 40
    )
    return bool(pixels) and red / len(pixels) > 0.05


def _strip_tender_page_numbers(document: Any) -> int:
    """清掉福昕从招标原件搬进来的页码:① 清空页脚 ② 删正文里"纯数字"页码段(如 171)。

    投标文件应用自己的页码,不该带招标文件的。返回清掉的元素数。
    """
    import re as _re

    cleared = 0
    # ① 页脚清空(招标原件页码常在页脚)
    try:
        for section in document.sections:
            footer = section.footer
            footer.is_linked_to_previous = False
            for para in footer.paragraphs:
                for run in list(para.runs):
                    run._r.getparent().remove(run._r)
                    cleared += 1
    except Exception:
        pass
    # ② 正文里整段只有数字(可带"第 X 页/共 X 页")的页码行 → 删
    page_re = _re.compile(r"^第?\s*\d{1,4}\s*页?(\s*/?\s*共?\s*\d{1,4}\s*页?)?$")
    for para in list(document.paragraphs):
        t = para.text.strip()
        if t and (t.isdigit() and len(t) <= 4 or page_re.match(t)):
            el = para._p
            el.getparent().remove(el)
            cleared += 1
    return cleared


def _strip_seal_images(document: Any) -> int:
    """删除从招标原件复制进来的红色印章图(招标人/代理公章)。

    投标文件不该带招标人/代理的章,投标人自己的章必须人工手盖 → 任何自动出现的印章
    都要清掉。在**格式章构建阶段**调用(此时还没追加资格证明附录,故绝不会误删证件
    扫描件)。判据见 :func:`_image_is_seal`(整图红占比)。返回删除的图章引用数。
    """
    seal_rids = set()
    for rid, part in document.part.related_parts.items():
        if "image" not in (getattr(part, "content_type", "") or ""):
            continue
        blob = getattr(part, "blob", b"")
        if blob and _image_is_seal(blob):
            seal_rids.add(rid)
    if not seal_rids:
        return 0

    removed = 0
    blip_tag, embed_attr = qn("a:blip"), qn("r:embed")
    try:
        vml_tag, vml_id = qn("v:imagedata"), qn("r:id")
    except Exception:  # pragma: no cover - 'v' 命名空间缺失时退化为只处理 drawing
        vml_tag = vml_id = None
    for container in (qn("w:drawing"), qn("w:pict")):
        for element in list(document.element.iter(container)):
            rid = next(
                (b.get(embed_attr) for b in element.iter(blip_tag)), None
            )
            if rid is None and vml_tag is not None:
                rid = next(
                    (img.get(vml_id) for img in element.iter(vml_tag)), None
                )
            if rid in seal_rids:
                parent = element.getparent()
                if parent is not None:
                    parent.remove(element)
                    removed += 1
    return removed


def _table_has_real_borders(table: Any) -> bool:
    """True if any cell declares a real (non-nil) border.

    pdf2docx gives真实表格(基本情况表等)逐格 w:tcBorders=single;而把填空行误判出的
    "假表"边框为空。据此区分真表 vs 流式误判表。
    """
    sides = ("w:top", "w:bottom", "w:start", "w:end", "w:left", "w:right")
    for row in table.rows:
        for cell in row.cells:
            tc_pr = cell._tc.tcPr
            if tc_pr is None:
                continue
            borders = tc_pr.find(qn("w:tcBorders"))
            if borders is None:
                continue
            for side in sides:
                element = borders.find(qn(side))
                if element is not None and (
                    element.get(qn("w:val")) or ""
                ).lower() not in ("", "nil", "none"):
                    return True
    return False


def _drop_spurious_stream_tables(document: Any) -> int:
    """Flatten pdf2docx 的"假表"回普通段落。

    pdf2docx 偶尔把"标签+一段宽下划线空白"的填空行误判成 2 格无线表。这类
    (逻辑格数≤2 且 无真边框)还原成段落;真网格表(有边框,如基本情况表/图说明)保留。
    返回还原的表数。
    """
    from docx.oxml import OxmlElement

    dropped = 0
    for table in list(document.tables):
        if len(table.rows) * len(table.columns) > 2:
            continue
        if _table_has_real_borders(table):
            continue
        text = " ".join(
            cell.text.strip()
            for row in table.rows
            for cell in row.cells
            if cell.text.strip()
        )
        tbl = table._tbl
        paragraph = OxmlElement("w:p")
        if text:
            run = OxmlElement("w:r")
            node = OxmlElement("w:t")
            node.set(qn("xml:space"), "preserve")
            node.text = text
            run.append(node)
            paragraph.append(run)
        tbl.addprevious(paragraph)
        tbl.getparent().remove(tbl)
        dropped += 1
    return dropped


def _find_format_page_range_in_pdf(pdf_path: str) -> tuple[int, int] | None:
    """Find zero-based, end-exclusive format chapter page range."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        # Extract all page texts once — avoids re-extraction per page
        page_texts: list[str] = [
            doc[page_num].get_text() for page_num in range(doc.page_count)
        ]
        page_compacts: list[str] = [re.sub(r"\s+", "", text) for text in page_texts]

        # Find ALL occurrences of the format chapter heading — use the LAST one
        # (PDFs often have a TOC reference early; the actual chapter body is later)
        matches: list[int] = []
        for page_num, compact in enumerate(page_compacts):
            if FORMAT_CHAPTER_RE.search(compact):
                matches.append(page_num)

        if not matches:
            return None

        # Use the last match as the actual chapter start
        format_start = matches[-1]
        # Skip TOC pages following the chapter heading
        format_start = _skip_toc_pages(doc, format_start)

        # Find the end: the next real chapter heading, OR the start of the
        # 技术文件/报价文件 卷 (the format chapter packs all three volumes; the
        # 商务卷 copy must stop where 技术/报价 begins — those are生成/外部, not copied).
        format_end = doc.page_count
        for page_num in range(format_start + 1, doc.page_count):
            compact = page_compacts[page_num]
            if _looks_like_next_chapter_page(compact) or _looks_like_other_volume_start(
                compact
            ):
                format_end = page_num
                break

        return (format_start, max(format_start + 1, format_end))
    finally:
        doc.close()


def _find_appendix_page_range_in_pdf(pdf_path: str) -> tuple[int, int] | None:
    """定位技术卷附表区(附表一…)的零基、右开页范围。

    附表模板落在"投标文件格式"章的技术文件段;从"附表一"起,到报价文件卷起始或下一章止。
    商务范围(_find_format_page_range_in_pdf)已在技术卷起始处收尾、不含附表,故附表单独定位。
    """
    import fitz

    doc = fitz.open(pdf_path)
    try:
        compacts = [
            re.sub(r"\s+", "", doc[i].get_text()) for i in range(doc.page_count)
        ]
        start = next(
            (i for i, c in enumerate(compacts) if _APPENDIX_START_RE.search(c)), None
        )
        if start is None:
            return None
        end = doc.page_count
        for i in range(start + 1, doc.page_count):
            if _looks_like_other_volume_start(compacts[i]) or _looks_like_next_chapter_page(
                compacts[i]
            ):
                end = i
                break
        return (start, max(start + 1, end))
    finally:
        doc.close()


def _looks_like_next_chapter_page(compact_text: str) -> bool:
    """Detect a NEW chapter heading at the START of a PDF page.

    A real chapter heading sits at the very start of the page (optionally after a
    leading page number), e.g. "106第八章评标办法". A "第X章" embedded mid-sentence
    is a cross-reference (e.g. "投标人应根据招标文件第二章…的要求") and must NOT end
    the format chapter — searching the whole page head for it falsely cut the
    chapter and dropped later 商务 form pages (实测招标#122：p105 的
    "…招标文件第二章…" 把资格审查后半 + 八、其他资料切掉)。
    """
    head = compact_text[:40]
    if not _NEXT_CHAPTER_HEAD_RE.match(head):
        return False
    return not FORMAT_CHAPTER_RE.search(head)


def _looks_like_other_volume_start(compact_text: str) -> bool:
    """Detect the start of the 技术文件/报价文件 卷 within the format chapter.

    The "投标文件格式" 章 packs all three volumes; these volume headings (not
    "第X章") mark where the 商务卷 ends — 技术卷由 LLM 生成、报价卷外部,不照抄。
    """
    return bool(_OTHER_VOLUME_START_RE.search(compact_text[:60]))


def _skip_toc_pages(pdf: fitz.Document, from_page: int) -> int:
    """Skip TOC pages after finding the format chapter heading."""
    # Check next few pages — if they're TOC (contain "........" dots), skip them
    for offset in range(MAX_TOC_PAGES):
        page_num = from_page + offset
        if page_num >= pdf.page_count:
            return from_page
        text = pdf[page_num].get_text()
        # If page contains actual form content markers, it's not TOC
        if any(marker in text for marker in FORMAT_BODY_MARKERS):
            return page_num
        # If page has lots of dot leaders, it's TOC — skip
        if text.count("........") + text.count("……") + text.count("....") > 3:
            continue
        # If page has substantial unique text, it's probably content
        if len(set(text)) > 100:
            return page_num
    return from_page
