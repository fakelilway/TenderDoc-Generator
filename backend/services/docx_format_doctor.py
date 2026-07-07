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
    """孤字归位:X 粘在填空槽后 + 下文段首是"Y：" 且 XY 是已知两字标签 → X 搬回 Y 前。

    "粘在槽后"的精确特征 = 孤字 run 的前一个可见 run **带下划线**——填空前是带线空白槽、
    填空后是带线的值,两种状态都算(本 healer 跑在填值前,此时槽还是空白;曾错误地额外要求
    前 run 有非空文字=已填值,导致填前永不触发,萧县实测暴露)。段首单字(如"姓 名："的
    "姓",k==0)前面没有带线 run,绝不误搬。
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
            if k == 0 or not _is_underlined(runs[k - 1]):
                continue  # 前面不是带线 run(空槽/已填值均可) → 不是"粘在槽后"的孤字
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

def heal_filler_blank_runs(document: Any, profile: dict[str, Any] | None = None) -> int:
    """压缩福昕塞的大段连续空段(为凑原 PDF 版面塞的填充回车)。

    实测(用户截图):表单签名后跟着 20+ 个空段,而下一节本就由"分节符(下一页)"另起新页
    → 这些空段自己占满了一整页纯空白。规则:连续 ≥4 个**真空段**(无文字/无图/无换行符/
    无制表位/不带分节符——日期空槽那类"只有下划线制表位"的段绝不算空)压缩到剩 2 个。
    删的是零字符的空段,不碰任何内容。返回删除的空段数。
    """
    body = document.element.body

    def _is_truly_blank(p_el) -> bool:
        pPr = p_el.find(qn("w:pPr"))
        if pPr is not None and pPr.find(qn("w:sectPr")) is not None:
            return False  # 分节符段,动不得
        for tag in ("w:drawing", "w:pict", "w:br", "w:tab"):
            if next(iter(p_el.iter(qn(tag))), None) is not None:
                return False
        for t in p_el.iter(qn("w:t")):
            if (t.text or "").strip():
                return False
        return True

    removed = 0
    run: list = []
    for child in list(body) + [None]:
        if child is not None and child.tag == qn("w:p") and _is_truly_blank(child):
            run.append(child)
            continue
        if len(run) >= 4:
            for extra in run[2:]:  # 留2个保分隔感
                body.remove(extra)
                removed += 1
        run = []
    if removed:
        logger.info("格式体检:压缩福昕填充空段 %d 个", removed)
    return removed


def _iter_all_paragraphs_deep(container: Any):
    """正文 + 所有表格(含嵌套)单元格里的段落。福昕的表单常有嵌套表,须递归。"""
    for p in container.paragraphs:
        yield p
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_all_paragraphs_deep(cell)


def heal_line_spacing(document: Any, profile: dict[str, Any] | None = None) -> int:
    """治福昕的"叠行/行距忽紧忽松"。只改行距属性,一个字不动。

    福昕转 PDF→Word 时给部分段落设了"固定行高(lineRule=exact)+行高小于单倍"
    → 固定行高比字还矮,多行文字被压得叠在一起(用户实测:联合体协议书/投标函密集段
    第二行贴着第一行)。规则:
    · 固定行高(exact) → 改成自动行高(auto);行高值不足单倍(240)的提到 240,保证不叠;
    · 过松(auto 且 line>300,即 >1.25 倍)的正文行 → 收回单倍,消除忽紧忽松。
    行距是纯格式属性,改它不违反"绝不改文字"红线。返回调整的段数。
    """
    fixed = 0
    for p in _iter_all_paragraphs_deep(document):
        ppr = p._p.find(qn("w:pPr"))
        if ppr is None:
            continue
        sp = ppr.find(qn("w:spacing"))
        if sp is None:
            continue
        rule = sp.get(qn("w:lineRule"))
        line = sp.get(qn("w:line"))
        line_i = int(line) if (line and line.isdigit()) else None
        if rule == "exact":
            sp.set(qn("w:lineRule"), "auto")
            if line_i is not None and line_i < 240:
                sp.set(qn("w:line"), "240")
            fixed += 1
        elif rule == "auto" and line_i is not None and line_i > 300:
            sp.set(qn("w:line"), "240")
            fixed += 1
    if fixed:
        logger.info("格式体检:捋匀福昕叠行/过松行距 %d 段", fixed)
    return fixed


def _usable_width_twips(document: Any) -> int:
    """页面文字区宽度(twips)=页宽-左右边距。多节取最小(最保守);拿不到用 A4 常见值兜底。"""
    widths = []
    try:
        for sec in document.sections:
            w = int(sec.page_width.twips - sec.left_margin.twips - sec.right_margin.twips)
            if w > 2000:
                widths.append(w)
    except Exception:
        pass
    return min(widths) if widths else 9026  # A4(11906) - 边距(1440*2)


def _est_text_twips(text: str) -> int:
    """粗估文本渲染宽度(twips):CJK≈290/字,西文数字≈145/字。**故意估宽**——
    估窄了会再折行(实测),估宽了只是缩进/下划线槽略短,右对齐观感无碍。"""
    return sum(290 if ord(ch) > 0x2E80 else 145 for ch in text if ch != "\t")


def heal_signature_wrap(document: Any, profile: dict[str, Any] | None = None) -> int:
    """治落款块折行:「投标人：公司名（盖单位章）」「（签章）」被挤到下一行。

    根因(用户实测,埇桥商务卷):福昕为复刻原 PDF 落款靠右的位置,给这些段落设了
    巨大左缩进(实测 5486 twips≈9.7cm)+右对齐。招标原样是空下划线,短,排得下;
    值(公司名/28字地址)填进去后超宽 → "（盖单位章）""（签章）"折行、地址断三行。

    修法:这些段落是**右对齐**的——左缩进砍小后文字自动贴右、观感不变,但一行排得下。
    制表位画得太远(槽尾+"（签章）"超页宽)的,把制表位收进来。只动缩进/制表位,
    文字一个不动(红线)。返回调整的段数。
    """
    avail = _usable_width_twips(document)
    fixed = 0
    for p in document.paragraphs:
        text = p.text
        if not text.strip():
            continue
        ppr = p._p.find(qn("w:pPr"))
        if ppr is None:
            continue
        jc = ppr.find(qn("w:jc"))
        if jc is None or jc.get(qn("w:val")) not in ("right", "end"):
            continue
        ind = ppr.find(qn("w:ind"))
        if ind is None:
            continue
        try:
            left = int(ind.get(qn("w:left")) or 0)
            right = int(ind.get(qn("w:right")) or 0)
        except ValueError:
            continue
        if left < 1500:
            continue  # 没有福昕式大缩进,不是本病
        # 行需要的宽度:有制表位时 = 最远制表位 + 制表位之后的文字;否则 = 全文
        tabs_el = ppr.find(qn("w:tabs"))
        tab_positions = []
        if tabs_el is not None:
            for t in tabs_el.findall(qn("w:tab")):
                try:
                    tab_positions.append(int(t.get(qn("w:pos")) or 0))
                except ValueError:
                    pass
        if "\t" in text and tab_positions:
            tail = text.rsplit("\t", 1)[1]
            need = max(tab_positions) + _est_text_twips(tail)
        else:
            need = _est_text_twips(text)
        if left + need + right <= avail - 60:
            continue  # 排得下,原样保真
        # 折行了:左缩进直接砍到 0。段落是右对齐,砍缩进只是给足排版空间,
        # 文字照样贴右、观感不变;字宽是估算值,留一部分缩进赌"刚好够"会再折(实测)。
        ind.set(qn("w:left"), "0")
        # 左缩进归零还不够(制表位自己画出页外) → 把最远制表位收进来,余量给足
        if need + right > avail - 60 and tab_positions and "\t" in text:
            tail = text.rsplit("\t", 1)[1]
            head = text.rsplit("\t", 1)[0]
            new_pos = max(
                _est_text_twips(head) + 300,
                avail - right - _est_text_twips(tail) - 400,
            )
            farthest = max(
                tabs_el.findall(qn("w:tab")),
                key=lambda t: int(t.get(qn("w:pos")) or 0),
            )
            if new_pos < int(farthest.get(qn("w:pos")) or 0):
                farthest.set(qn("w:pos"), str(new_pos))
        fixed += 1
    if fixed:
        logger.info("格式体检:治落款折行(砍福昕大缩进/收制表位) %d 段", fixed)
    return fixed


# 句子在这些字符上收尾才算"说完了";其余结尾(逗号/裸汉字/"在")都是被福昕劈开的半句
_SENTENCE_END = "。？！；;：…" + "”\"』】)）"
# 新条目/新表单行的开头模式:绝不能把它并进上一段
_NEW_ITEM_RE = re.compile(
    r"^\s*(?:[0-9０-９]+\s*[．.、)）]|（[0-9０-９一二三四五六七八九十]+）"
    r"|[一二三四五六七八九十]+\s*[、.．]|附[表件]|第[一二三四五六七八九十百0-9]+[章节条部]"
    r"|[注致][：:]|投\s*标\s*人|法\s*定\s*代\s*表\s*人|地\s*址|网\s*址|电\s*话"
    r"|传\s*真|邮\s*政\s*编\s*码|开\s*立\s*人)"
)
# "短标签+冒号"开头(单位性质：/成立时间：/性别：…)=表单行,同样不许被吞并
_LABEL_START_RE = re.compile(r"^\s*[一-龥]{1,6}\s*[：:]")


def _is_form_line(text: str) -> bool:
    """短且带冒号的"标签：值"表单行。它天生不带句号,绝不能被句子合并当成
    "没说完的话"往后吞——实测回归:"投标人：公司名"吞掉"单位性质：…"、
    "地址：…"连吞"成立时间/经营期限",法定代表人身份证明整页挤成一坨。"""
    t = (text or "").strip()
    return bool(t) and len(t) <= 40 and ("：" in t or ":" in t)


def _para_alignment(p_el: Any) -> str | None:
    ppr = p_el.find(qn("w:pPr"))
    if ppr is None:
        return None
    jc = ppr.find(qn("w:jc"))
    return jc.get(qn("w:val")) if jc is not None else None


def _para_left_indent(p_el: Any) -> int:
    ppr = p_el.find(qn("w:pPr"))
    ind = ppr.find(qn("w:ind")) if ppr is not None else None
    try:
        return int(ind.get(qn("w:left")) or 0) if ind is not None else 0
    except ValueError:
        return 0


def _p_text(p_el: Any) -> str:
    return "".join(t.text or "" for t in p_el.iter(qn("w:t")))


def _unify_run_format(run_el: Any, host_rpr: Any) -> None:
    """把并入 run 的字体/字号/加粗统一成宿主段的(同一句话不能两种脸);
    下划线/颜色等保留——填空值的下划线不能被抹掉。host_rpr=None 表示宿主继承默认,
    则删掉并入 run 的这三项让它同样继承默认。"""
    rpr = run_el.find(qn("w:rPr"))
    for tag in ("w:rFonts", "w:sz", "w:szCs", "w:b", "w:bCs"):
        host_val = host_rpr.find(qn(tag)) if host_rpr is not None else None
        cur = rpr.find(qn(tag)) if rpr is not None else None
        if host_val is None:
            if cur is not None:
                rpr.remove(cur)
        else:
            if rpr is None:
                rpr = OxmlElement("w:rPr")
                run_el.insert(0, rpr)
                cur = None
            if cur is not None:
                rpr.remove(cur)
            rpr.append(deepcopy(host_val))


def _in_textbox(el: Any) -> bool:
    """元素是否在浮动文本框(txbxContent)内——那里的排版不归我们管。"""
    anc = el.getparent()
    while anc is not None:
        if anc.tag.endswith("}txbxContent"):
            return True
        anc = anc.getparent()
    return False


def heal_split_paragraphs(document: Any, profile: dict[str, Any] | None = None) -> int:
    """治福昕"一句话劈成几段"(用户实测投标函:一句被切三截、中间夹空行、粗细不一)。

    福昕把原 PDF 的视觉行转成独立段落:段尾停在逗号/裸字上、下一段接着说。规则:
    左对齐正文段结尾不是句末标点 → 把下一段并回来(runs 搬家,文字一个不丢),
    中间的零字符空段删掉,并入文字的字体/字号/加粗统一成宿主段的(下划线保留)。
    绝不并:编号/表单标签开头的下一段、居中/右对齐段、大缩进标题段、带分节符段、表格。
    正文和表格单元格内都治(埇桥p8/p9实测:附录表值格里一句话碎成4段夹空行)。
    """
    merged = 0
    containers = [document.element.body]
    for tc in document.element.body.iter(qn("w:tc")):
        if not _in_textbox(tc):
            containers.append(tc)
    for container in containers:
        merged += _merge_split_in(container)
    if merged:
        logger.info("格式体检:合并福昕劈开的半句 %d 处", merged)
    return merged


def _merge_split_in(body: Any) -> int:
    merged = 0
    children = list(body.iterchildren())
    i = 0
    while i < len(children):
        el = children[i]
        if el.tag != qn("w:p") or el.getparent() is None:
            i += 1
            continue
        text = _p_text(el).rstrip()
        if (
            not text.strip()
            or text[-1] in _SENTENCE_END
            or text.lstrip().startswith("致")  # "致：xxx"抬头独立成行,不许吞下一段
            or _is_form_line(text)  # 表单行不当宿主往后吞(短+带冒号)
            or _para_alignment(el) in ("center", "right", "end")
            or _para_left_indent(el) > 1500  # 视觉居中的标题段
            or el.find(f".//{qn('w:sectPr')}") is not None
        ):
            i += 1
            continue
        # 宿主段末个带文字 run 的格式 = 本句的"标准脸"
        host_rpr = None
        for r in reversed(el.findall(qn("w:r"))):
            if _p_text(r).strip():
                host_rpr = r.find(qn("w:rPr"))
                break
        # 往后找可并的段,最多接 8 截
        joins = 0
        j = i + 1
        while joins < 8 and j < len(children):
            nxt = children[j]
            if nxt.tag != qn("w:p"):
                break  # 表格/其他元素,这句到头了
            if nxt.find(f".//{qn('w:sectPr')}") is not None:
                break
            nxt_text = _p_text(nxt)
            if not nxt_text.strip():
                # 夹在半句中间的空段:零字符的删掉,含空白字符的把空白并进句里
                if not nxt_text:
                    has_content = any(
                        next(iter(nxt.iter(qn(t))), None) is not None
                        for t in ("w:drawing", "w:pict", "w:br", "w:tab")
                    )
                    if has_content:
                        break
                    body.remove(nxt)
                    j += 1
                    continue
                for r in list(nxt.findall(qn("w:r"))):
                    el.append(r)
                body.remove(nxt)
                j += 1
                continue
            if (
                _NEW_ITEM_RE.match(nxt_text)
                or _LABEL_START_RE.match(nxt_text)  # "单位性质：/性别：…"表单行不许被吞
                or _para_alignment(nxt) in ("center", "right", "end")
                or _para_left_indent(nxt) > 1500
            ):
                break
            # 并:runs 搬进宿主,统一字体,删空壳
            for r in list(nxt.findall(qn("w:r"))):
                _unify_run_format(r, host_rpr)
                el.append(r)
            body.remove(nxt)
            merged += 1
            joins += 1
            j += 1
            new_text = _p_text(el).rstrip()
            if new_text and new_text[-1] in _SENTENCE_END:
                break  # 句子说完了
        i = j if joins else i + 1
    return merged


def heal_midsentence_breaks(document: Any, profile: dict[str, Any] | None = None) -> int:
    """治福昕的"句中硬换行":一段里句子说到一半插 w:br 断行(还常连打两个变出空行)。

    (5)条实测:整条和后续几条都在同一段里,句中"…其他管[br][br]理和技术人员…"——
    段落合并治不了它。规则:左对齐正文段里,**前文没说完**(累计文字结尾不是句末标点)
    的换行符删掉,句子自然连排;句末标点后的换行保留(它是条目分隔);"致：…"抬头行的
    换行保留;分页符(type=page)和浮动文本框内部绝不碰。正文和表格单元格都治
    (埇桥p8/p9实测:附录表值格里句中断行碎成渣)。只删换行符,文字一个不动。
    """
    removed = 0
    for p_el in document.element.body.iter(qn("w:p")):
        if _in_textbox(p_el):
            continue
        if (
            _para_alignment(p_el) in ("center", "right", "end")
            or _para_left_indent(p_el) > 1500
            or p_el.find(f".//{qn('w:sectPr')}") is not None
        ):
            continue
        # 只走段落直属的 run(不钻进浮动文本框 w:drawing/txbxContent)
        prefix = ""
        for r in list(p_el.iterchildren(qn("w:r"))):
            for child in list(r.iterchildren()):
                if child.tag == qn("w:t"):
                    prefix += child.text or ""
                elif child.tag == qn("w:br"):
                    br_type = child.get(qn("w:type"))
                    if br_type and br_type != "textWrapping":
                        continue  # 分页/分栏符,神圣不可侵犯
                    tail = prefix.rstrip()
                    # 当前行(上一个换行之后的文字)是"致：/致:"抬头或表单行 → 换行是
                    # 格式,保留(实测回归:"致：xx中心"和"我公司…"连成一句;
                    # "投标人：公司名"和"单位性质：…"挤成一行)
                    cur_line = prefix.rsplit("\n", 1)[-1].strip()
                    if cur_line.startswith("致") or _is_form_line(cur_line):
                        prefix += "\n"
                        continue
                    if not tail or tail[-1] not in _SENTENCE_END:
                        r.remove(child)
                        removed += 1
                    else:
                        prefix += "\n"
    if removed:
        logger.info("格式体检:删福昕句中硬换行 %d 个", removed)
    return removed


def heal_phantom_images(document: Any, profile: dict[str, Any] | None = None) -> int:
    """删福昕的"幽灵小图":1x1 像素透明 PNG 被拉成 19x7pt 嵌在句子中间,把行切断。

    埇桥实测:同一张 86 字节透明图(rId10)全文埋了 10 处,投标函(5)条"…其他管[图]
    理和技术人员…"的断行元凶就是它——文字/换行/控制符全查过,最后 fitz 页面对象
    坐标锁定它。判定双保险:显示尺寸微小(高<10pt 且宽<26pt)**且**图片字节<1KB,
    才认定是残渣;真图(证照扫描几十 KB 起)绝不误伤。删图不删字。
    """
    a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    r_embed = (
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    )
    wp_ns = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    removed = 0
    try:
        rels = document.part.rels
    except Exception:
        rels = {}
    for d in list(document.element.body.iter(qn("w:drawing"))):
        node = d.find(f"{{{wp_ns}}}inline")
        if node is None:
            node = d.find(f"{{{wp_ns}}}anchor")
        if node is None:
            continue
        ext = node.find(f"{{{wp_ns}}}extent")
        if ext is None:
            continue
        try:
            cx_pt = int(ext.get("cx")) / 914400 * 72
            cy_pt = int(ext.get("cy")) / 914400 * 72
        except (TypeError, ValueError):
            continue
        if cy_pt >= 10 or cx_pt >= 26:
            continue  # 不是微型图
        if "".join(t.text or "" for t in d.iter(qn("w:t"))).strip():
            continue  # 带文字的(文本框)不碰
        blip = d.find(f".//{{{a_ns}}}blip")
        if blip is None:
            continue  # 无图纯形状(边框线等)不碰
        rid = blip.get(r_embed)
        try:
            blob_len = len(rels[rid].target_part.blob) if rid in rels else 10**9
        except Exception:
            blob_len = 10**9
        if blob_len >= 1024:
            continue  # 真图不碰
        holder = d.getparent()  # w:r
        if holder is not None and holder.getparent() is not None:
            holder.remove(d)
            if not _p_text(holder).strip() and holder.find(qn("w:br")) is None:
                holder.getparent().remove(holder)  # 空壳 run 一并清掉
            removed += 1
    if removed:
        logger.info("格式体检:删福昕幽灵小图 %d 个", removed)
    return removed


# (名称, healer)。healer 契约:输入 (document, profile),返回修复数;只改格式,绝不改文字。
_HEALERS: tuple[tuple[str, Callable[[Any, dict[str, Any] | None], int]], ...] = (
    ("underline_slots", heal_underline_slots),
    ("filler_blank_runs", heal_filler_blank_runs),
    ("phantom_images", heal_phantom_images),
    ("split_paragraphs", heal_split_paragraphs),
    ("midsentence_breaks", heal_midsentence_breaks),
    ("line_spacing", heal_line_spacing),
    ("signature_wrap", heal_signature_wrap),
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
