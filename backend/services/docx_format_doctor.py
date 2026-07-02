"""格式体检(format doctor):福昕转换+填值完成后,对整份 docx 做"格式合理化"修复。

设计红线(用户定,2026-07-02):**只修格式、绝不改文字内容**,且修完仍与招标原样一致。
每个 healer 只允许调整格式属性(如下划线),不得增删改任何字符;每段修完做"全段文字
逐字相同"校验;修复失败静默跳过,绝不阻断出标。

第一版 healer:治"下划线画了一半"。招标原文的填空槽是"带下划线的空白(空格/制表符)",
系统把值填进槽后,值 run 未继承下划线 → 值没线、槽两头残留短线,视觉上线断成两截。
两条规则(先白名单后兜底,都要求值紧挨着带线 run——那是填空槽的确定特征):
- 白名单:值文本(忽略空白)等于 profile 里我们自己填的值(公司名/项目名/法人名/工期…)
  → 补线;值和"："连在一个 run(如抬头"招标人名称：")→ 拆 run 只给值上线。
- 夹心兜底:「带线空白 + 无线文字 + 带线空白」的中间文字,≥6字、不含冒号、
  非"（…）"提示语 → 认作填进槽的值,补线。(短标签如"年/月/日"被线夹着是招标原样,
  长度阈值把它们挡在外面——不加这道闸就会给原文标签误加线。)

后续发现新的格式毛病,按同样契约往 _HEALERS 里加新 healer,别再散落各处打补丁。
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any, Callable, Iterable

from docx.oxml.ns import qn

logger = logging.getLogger(__name__)

# profile 里"会被填进文档"的值的键(中英都认);其余键不当白名单,免得误伤。
_VALUE_KEYS = (
    "项目名称", "project_name",
    "招标人", "tenderer_name",
    "company_name", "投标人", "公司名称",
    "legal_representative",
    "工期", "planned_duration",
    "质量", "quality_standard",
    "安全", "safety_target",
    "投标有效期", "bid_validity",
    "注册地址", "address", "registered_address",
    "tech_director_name", "project_manager_name",
    "单位性质", "company_type",
)

_WS_RE = re.compile(r"\s+")
_HINT_RE = re.compile(r"^（.*）[。，；]?$")  # （盖单位章）（签字或盖章）等原文提示语
_LABEL_TAILS = ("：", ":")


def _norm(text: str) -> str:
    """忽略空白比对(福昕爱在数字/英文两侧塞空格)。"""
    return _WS_RE.sub("", text or "")


def fill_values_from_profile(profile: dict[str, Any] | None) -> list[str]:
    """白名单:我们自己填进文档的值(去空白,≥2字),长值在前(优先配最长)。"""
    values: set[str] = set()
    for key in _VALUE_KEYS:
        v = _norm(str((profile or {}).get(key) or ""))
        if len(v) >= 2:
            values.add(v)
    return sorted(values, key=len, reverse=True)


def _iter_all_paragraphs(document: Any) -> Iterable[Any]:
    """遍历正文 + 所有表格单元格里的段落。"""
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _is_underlined(run: Any) -> bool:
    return bool(run.font.underline)


def _is_blank(run: Any) -> bool:
    return run.text != "" and run.text.strip() == ""


def _match_value_prefix(text: str, value_norm: str) -> int | None:
    """value(已去空白)是否为 text 忽略空白后的前缀;是则返回其在 text 中的结束下标。"""
    vi = 0
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        if vi < len(value_norm) and ch == value_norm[vi]:
            vi += 1
            if vi == len(value_norm):
                return i + 1
        else:
            return None
    return None


def _split_run_at(run: Any, idx: int) -> bool:
    """把 run 在字符 idx 处拆成两个 run(文字逐字保留)。仅处理单 w:t 的常规 run。"""
    r = run._r
    ts = r.findall(qn("w:t"))
    if len(ts) != 1:
        return False
    text = ts[0].text or ""
    if not 0 < idx < len(text):
        return False
    tail = deepcopy(r)
    ts[0].text = text[:idx]
    ts[0].set(qn("xml:space"), "preserve")
    tail_t = tail.findall(qn("w:t"))[0]
    tail_t.text = text[idx:]
    tail_t.set(qn("xml:space"), "preserve")
    r.addnext(tail)
    return True


def _heal_whitelist_values(paragraph: Any, values: list[str]) -> int:
    """白名单修复:无线的已填值紧挨带线 run → 补线;"值："同 run 则拆开只给值上线。"""
    healed = 0
    runs = paragraph.runs
    n = len(runs)
    for i, run in enumerate(runs):
        if _is_underlined(run) or not run.text.strip():
            continue
        prev_u = i > 0 and _is_underlined(runs[i - 1])
        next_u = i + 1 < n and _is_underlined(runs[i + 1])
        if not (prev_u or next_u):
            continue  # 不挨着线,不是填空槽
        norm = _norm(run.text)
        for v in values:
            if norm == v:
                run.font.underline = True
                healed += 1
                break
            # "值+尾巴"连在一个 run(抬头"招标人名称："、委托书"公司名的法定代表人，现委托")
            # → 拆 run 只给值上线,尾巴(招标原文)不动。值≥4字才拆,防短值误配。
            end = _match_value_prefix(run.text, v)
            if end is not None and len(v) >= 4:
                if _split_run_at(run, end):
                    run.font.underline = True  # 拆完 run 仍指向前半(值)
                    healed += 1
                break
    return healed


def heal_underline_slots(document: Any, profile: dict[str, Any] | None = None) -> int:
    """治"下划线画了一半"。先白名单,后夹心兜底;每段守"文字逐字不变"。"""
    values = fill_values_from_profile(profile)
    healed = 0
    for paragraph in _iter_all_paragraphs(document):
        before = paragraph.text
        healed += _heal_whitelist_values(paragraph, values)

        runs = paragraph.runs  # 白名单可能拆过 run,重取
        n = len(runs)
        i = 0
        while i < n:
            # 左侧:一个或多个 带线空白
            if not (_is_underlined(runs[i]) and _is_blank(runs[i])):
                i += 1
                continue
            left_end = i
            while left_end + 1 < n and _is_underlined(runs[left_end + 1]) and _is_blank(runs[left_end + 1]):
                left_end += 1
            # 中间:一个或多个 无线、有文字 的值 run
            mid_start = left_end + 1
            mid_end = mid_start - 1
            while (
                mid_end + 1 < n
                and runs[mid_end + 1].text.strip()
                and not _is_underlined(runs[mid_end + 1])
            ):
                mid_end += 1
            if mid_end < mid_start:
                i = left_end + 1
                continue
            # 右侧:必须紧跟 带线空白(槽的另一半边),才认定中间是槽里的值
            right = mid_end + 1
            if right < n and _is_underlined(runs[right]) and _is_blank(runs[right]):
                mid_text = _norm("".join(runs[k].text for k in range(mid_start, mid_end + 1)))
                # 闸:太短(年/月/日等原文标签)、带冒号(标签)、带句读(值+原文连排,如
                # "公司名的法定代表人，现委托"——整串上线会给招标原文误加线)、（…）提示语 → 不动
                if (
                    len(mid_text) >= 6
                    and not any(t in mid_text for t in _LABEL_TAILS)
                    and not any(t in mid_text for t in ("，", "。", "；", ","))
                    and not _HINT_RE.match(mid_text)
                ):
                    for k in range(mid_start, mid_end + 1):
                        runs[k].font.underline = True
                        healed += 1
                i = right
            else:
                i = mid_end + 1

        if paragraph.text != before:  # 铁律:一个字都不许变(只改 rPr/拆 run,理论到不了这)
            logger.error("格式体检:段落文字被改动,违约!before=%r after=%r", before[:50], paragraph.text[:50])
    return healed


# ── 填空前 healer:孤字归位(拼回被福昕劈成两半的两字标签) ──────────────────
# 病(真实文件实测,巢湖v7 身份证明两列区):招标原文两列布局
#   姓 名：许明英 | 性 别：女
# 福昕转完变成:左列一段"姓 名： 许明英[性]年 龄： 50[职]"(右列标签头字粘在值后),
# "别："/"务："各自孤零零成段。→ 视觉错乱,且标签残缺导致"性别/职务"的空永远填不上。
# 修:孤字(独立成 run 的单字)搬回下文"别："段首拼成"性别：",原位换成换行(恢复两行布局)。
# 全文档字符一个不多一个不少,只是把福昕劈乱的字归位;须在**填值之前**跑(标签完整才填得上)。

# 可拼回的两字标签(第一字=孤字,第二字+冒号=下文段首)。
_REJOIN_LABELS = (
    "性别", "职务", "职称", "电话", "传真", "姓名", "年龄", "学历", "专业", "备注",
)


def heal_orphan_split_labels(document: Any, profile: dict[str, Any] | None = None) -> int:
    """孤字归位:X 粘在已填值后 + 下文段首是"Y：" 且 XY 是已知两字标签 → X 搬回 Y 前。

    "粘在值后"的精确特征 = 孤字 run 的前一个可见 run 带下划线(填空槽里的值)——
    这一条挡住"姓 名："里的"姓"这类正常单字 run(它前面没有带线值),绝不误搬。
    """
    from docx.oxml import OxmlElement

    paras = list(_iter_all_paragraphs(document))
    healed = 0
    for idx, paragraph in enumerate(paras):
        runs = [r for r in paragraph.runs if r.text]
        for k, run in enumerate(runs):
            ch = run.text
            if len(ch) != 1 or not ("一" <= ch <= "鿿") or _is_underlined(run):
                continue
            if k == 0 or not _is_underlined(runs[k - 1]) or not runs[k - 1].text.strip():
                continue  # 前面不是带线的已填值 → 不是"粘在值后"的孤字
            # 在后面最多4个非空段里找"另一半":段首正是 Y：且 X+Y 是已知标签
            seen = 0
            for j in range(idx + 1, len(paras)):
                target = paras[j]
                ttext = target.text
                if not ttext.strip():
                    continue
                seen += 1
                if seen > 4:
                    break
                if len(ttext) >= 2 and ttext[1] in ("：", ":") and (ch + ttext[0]) in _REJOIN_LABELS:
                    t_run = target.runs[0] if target.runs else None
                    if t_run is None or not t_run.text.startswith(ttext[0]):
                        break
                    t_ts = t_run._r.findall(qn("w:t"))
                    if len(t_ts) != 1:
                        break
                    # 搬字:X 接到目标段首;原 run 清字、原位补换行(恢复两行布局;段尾孤字则不补)
                    t_ts[0].text = ch + (t_ts[0].text or "")
                    t_ts[0].set(qn("xml:space"), "preserve")
                    for t_el in run._r.findall(qn("w:t")):
                        run._r.remove(t_el)
                    if k < len(runs) - 1:
                        run._r.append(OxmlElement("w:br"))
                    healed += 1
                    break
    return healed


_PREFILL_HEALERS: tuple[tuple[str, Callable[[Any, dict[str, Any] | None], int]], ...] = (
    ("orphan_split_labels", heal_orphan_split_labels),
)

# (名称, healer)。healer 契约:输入 (document, profile),返回修复数;只改格式,绝不改文字。
_HEALERS: tuple[tuple[str, Callable[[Any, dict[str, Any] | None], int]], ...] = (
    ("underline_slots", heal_underline_slots),
)


def run_format_doctor_prefill(document: Any) -> dict[str, int]:
    """填值前的体检(标签修复类):孤字归位等。逐个容错,绝不阻断。"""
    report: dict[str, int] = {}
    for name, healer in _PREFILL_HEALERS:
        try:
            report[name] = healer(document, None)
        except Exception:
            logger.warning("格式体检(填前) healer %s 失败,跳过", name, exc_info=True)
            report[name] = 0
    fixed = {k: v for k, v in report.items() if v}
    if fixed:
        logger.info("格式体检(填前)修复: %s", fixed)
    return report


def run_format_doctor(document: Any, profile: dict[str, Any] | None = None) -> dict[str, int]:
    """跑全部 healer,返回 {名称: 修复数}。逐个容错:单个 healer 崩不阻断其余/出标。"""
    report: dict[str, int] = {}
    for name, healer in _HEALERS:
        try:
            report[name] = healer(document, profile)
        except Exception:
            logger.warning("格式体检 healer %s 失败,跳过", name, exc_info=True)
            report[name] = 0
    fixed = {k: v for k, v in report.items() if v}
    if fixed:
        logger.info("格式体检修复: %s", fixed)
    return report
