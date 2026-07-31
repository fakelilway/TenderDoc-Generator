"""空白页硬闸:出卷前把商务卷里的整页空白**全部**消掉。

用户 2026-07-30 下的死命令:"不允许任何空白页"。此前靠"少插空段/少加分页"这类
间接手段治标不治本,因为空白页的成因有好几种(连着两个分页符、分节符另起页、
段前分页落在本来就是新页的段上、卷尾多余空段),改哪一处都可能漏。

这里换成**闭环**做法:渲染成 PDF 逐页看 → 找出真空白页 → 用"下一页的头一行文字"
当锚点定位到 docx 里那一段 → 拆掉它前面那个多余的分页动作 → 重新渲染复查,
直到一页空白都不剩(或用尽轮次/时间预算)。

判空必须用 ``get_text("dict")`` 里 type==1 的图块判断有没有图——``page.get_images()``
是页资源表,LibreOffice 会把整份文档的图挂到每一页上,用它判断会把所有空白页漏掉
(2026-07-30 实测:同一份卷,错的方法报 0 页空白,对的方法报 11 页)。
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from docx.oxml.ns import qn

logger = logging.getLogger(__name__)

_MAX_ITERS = 6
_TIME_BUDGET_SECONDS = 420

# 页眉/页码这类每页都印的东西不算页面内容
_NOISE_PATTERNS = (
    re.compile(r"第\s*\d+\s*页\s*(?:/|共)?\s*(?:共)?\s*\d*\s*页?"),
    re.compile(r".{0,20}招标示范文本[（(]\s*\d{4}\s*年版\s*[）)]"),
    re.compile(r"^\s*\d{1,4}\s*$", re.MULTILINE),
)


def _soffice() -> str | None:
    for cand in (
        shutil.which("soffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if cand and Path(cand).exists():
            return cand
    return None


def _render_pdf(soffice: str, docx_path: Path, outdir: Path, timeout: int) -> Path | None:
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(outdir), str(docx_path)],
            check=True, capture_output=True, timeout=timeout,
        )
    except Exception:
        logger.warning("空白页闸:LibreOffice 渲染失败/超时", exc_info=True)
        return None
    pdf = outdir / (docx_path.stem + ".pdf")
    return pdf if pdf.exists() else None


def _page_body_text(page: Any) -> str:
    text = page.get_text()
    for pat in _NOISE_PATTERNS:
        text = pat.sub("", text)
    return re.sub(r"\s+", "", text)


def _page_has_image(page: Any) -> bool:
    """页面上**实际画出**的图块。不能用 get_images():那是页资源表,LibreOffice
    会把整份文档的图挂到每页 → 恒为真,空白页全漏。"""
    return any(b.get("type") == 1 for b in page.get_text("dict").get("blocks", []))


def find_blank_pages(pdf_path: Path) -> list[dict[str, Any]]:
    """返回空白页信息:[{page:0基页号, next_anchor:下一页首行, prev_anchor:上一页末行}]。"""
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        body = [_page_body_text(doc[i]) for i in range(doc.page_count)]
        has_img = [_page_has_image(doc[i]) for i in range(doc.page_count)]

        def _lines(i: int) -> list[str]:
            if i < 0 or i >= doc.page_count:
                return []
            raw = doc[i].get_text()
            for pat in _NOISE_PATTERNS:
                raw = pat.sub("", raw)
            return [ln.strip() for ln in raw.splitlines() if ln.strip()]

        out: list[dict[str, Any]] = []
        for i in range(doc.page_count):
            if body[i] or has_img[i]:
                continue
            nxt = _lines(i + 1)
            prv = _lines(i - 1)
            out.append({
                "page": i,
                "next_anchor": nxt[0] if nxt else "",
                "prev_anchor": prv[-1] if prv else "",
            })
        return out
    finally:
        doc.close()


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _is_empty_para(el: Any) -> bool:
    """空段:没文字、没图、没分节符(分节符段是版式骨架,不能当空段删)。"""
    if el.tag != qn("w:p"):
        return False
    if _norm("".join(el.itertext())):
        return False
    if el.findall(".//" + qn("w:drawing")) or el.findall(".//" + qn("w:pict")):
        return False
    pPr = el.find(qn("w:pPr"))
    if pPr is not None and pPr.find(qn("w:sectPr")) is not None:
        return False
    return True


def _page_breaks_in(el: Any) -> list[Any]:
    return [
        br for br in el.findall(".//" + qn("w:br"))
        if br.get(qn("w:type")) == "page"
    ]


def _has_page_break_before(el: Any) -> bool:
    pPr = el.find(qn("w:pPr"))
    return pPr is not None and pPr.find(qn("w:pageBreakBefore")) is not None


def _drop_page_break_before(el: Any) -> bool:
    pPr = el.find(qn("w:pPr"))
    if pPr is None:
        return False
    node = pPr.find(qn("w:pageBreakBefore"))
    if node is None:
        return False
    pPr.remove(node)
    return True


def _section_break_para(el: Any) -> Any | None:
    """段落里挂着"另起一页"型分节符 → 返回该 sectPr,否则 None。"""
    if el.tag != qn("w:p"):
        return None
    pPr = el.find(qn("w:pPr"))
    if pPr is None:
        return None
    sectPr = pPr.find(qn("w:sectPr"))
    if sectPr is None:
        return None
    type_el = sectPr.find(qn("w:type"))
    kind = type_el.get(qn("w:val")) if type_el is not None else "nextPage"
    return sectPr if kind in (None, "nextPage", "oddPage", "evenPage") else None


def _make_section_continuous(sectPr: Any) -> bool:
    """把"另起一页"的分节符改成"接续本页"——版式(页眉/页码/纸张)全部保留,只是不再翻页。"""
    from docx.oxml import OxmlElement

    type_el = sectPr.find(qn("w:type"))
    if type_el is None:
        type_el = OxmlElement("w:type")
        sectPr.insert(0, type_el)
    type_el.set(qn("w:val"), "continuous")
    return True


_MINIMIZED_SZ = "4"  # 2pt(half-point 单位):压扁后的隐形段落字号


def _minimize_para_height(el: Any) -> bool:
    """把一个不可见段落(空文字/只挂分节符)压到几乎零高度:2pt字号+2pt固定行距+零段距。

    场景:相邻两节页眉页脚不同,分节符即使是"接续"型渲染器也会强制翻页——表尾垫底的
    分节符空段自己就够占一行,若上一页刚好被表格填满,这一行会被甩到新页 → 整页只有
    一个看不见的段落 = 空白页。删不得(分节符是版式骨架),那就把它压扁到塞得进上一页。
    已压过的返回 False(防止死循环)。
    """
    from docx.oxml import OxmlElement

    pPr = el.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        el.insert(0, pPr)
    spacing = pPr.find(qn("w:spacing"))
    if spacing is not None and spacing.get(qn("w:line")) == _MINIMIZED_SZ:
        return False  # 已压扁
    # ⚠️ CT_PPr 的子元素顺序是强制的:spacing 必须在 sectPr/rPr **之前**,rPr 在 sectPr
    # 之前。直接 append 会落到 sectPr 后面 → Word/LibreOffice 静默忽略,压扁不生效
    # (2026-07-30 实测:appended 版压扁后该段仍占一整行)。
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pStyle = pPr.find(qn("w:pStyle"))
        if pStyle is not None:
            pStyle.addnext(spacing)
        else:
            pPr.insert(0, spacing)
    spacing.set(qn("w:line"), _MINIMIZED_SZ)
    spacing.set(qn("w:lineRule"), "exact")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    rPr = pPr.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        sectPr = pPr.find(qn("w:sectPr"))
        if sectPr is not None:
            sectPr.addprevious(rPr)
        else:
            pPr.append(rPr)
    for tag in ("w:sz", "w:szCs"):
        node = rPr.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            rPr.append(node)
        node.set(qn("w:val"), _MINIMIZED_SZ)
    return True


def _next_section_props(body_children: list[Any], after: int) -> Any | None:
    """``after`` 之后管辖后续内容的 sectPr:下一个段落级 sectPr,或正文级 sectPr。"""
    for j in range(after + 1, len(body_children)):
        el = body_children[j]
        if el.tag == qn("w:sectPr"):
            return el
        if el.tag == qn("w:p"):
            pPr = el.find(qn("w:pPr"))
            if pPr is not None:
                sect = pPr.find(qn("w:sectPr"))
                if sect is not None:
                    return sect
    return None


_MARGIN_TOLERANCE_TWIPS = 300  # ≈0.53cm:边距差在此以内视为同版式,可并节


def _same_page_geometry(a: Any, b: Any) -> bool:
    """两个 sectPr 是否"同版式":纸张必须一致,页边距允许 ≤0.5cm 的差。

    巢湖实测:附表节与后节只差右边距 0.5cm(1118 vs 1389 twips),按"完全一致"判就
    并不了节、空白页除不掉。表格宽度是绝对值,半厘米边距差对版面无可见影响。
    """
    if a is None or b is None:
        return False

    def _attrs(sect: Any, tag: str) -> dict[str, str]:
        el = sect.find(qn(tag))
        return dict(el.attrib) if el is not None else {}

    if _attrs(a, "w:pgSz") != _attrs(b, "w:pgSz"):
        return False
    ma, mb = _attrs(a, "w:pgMar"), _attrs(b, "w:pgMar")
    for key in set(ma) | set(mb):
        try:
            va, vb = int(ma.get(key, 0) or 0), int(mb.get(key, 0) or 0)
        except ValueError:
            if ma.get(key) != mb.get(key):
                return False
            continue
        if abs(va - vb) > _MARGIN_TOLERANCE_TWIPS:
            return False
    return True


def _remove_one_break_before(body_children: list[Any], idx: int) -> str | None:
    """拆掉 body_children[idx] 之前那个多余的翻页动作,返回所用手段;没得拆返回 None。"""
    el = body_children[idx]
    if _drop_page_break_before(el):
        return "段前分页"

    j = idx - 1
    removed_empty = 0
    while j >= 0 and _is_empty_para(body_children[j]):
        parent = body_children[j].getparent()
        if parent is not None:
            parent.remove(body_children[j])
            removed_empty += 1
        j -= 1
    if j >= 0:
        prev = body_children[j]
        brs = _page_breaks_in(prev)
        if brs:
            br = brs[-1]
            br.getparent().remove(br)
            return f"硬分页符(顺带清{removed_empty}个空段)"
        sectPr = _section_break_para(prev)
        if sectPr is not None and _make_section_continuous(sectPr):
            return f"分节符改接续(顺带清{removed_empty}个空段)"
        # 已是接续型分节符但仍翻页(相邻节页眉页脚不同,渲染器强制换页):
        # 把分节符段压扁 + 清掉它前面的垫底空段,让它塞回上一页尾。
        pPr = prev.find(qn("w:pPr")) if prev.tag == qn("w:p") else None
        if pPr is not None and pPr.find(qn("w:sectPr")) is not None:
            shrunk = _minimize_para_height(prev)
            k = j - 1
            cleared = 0
            while k >= 0 and _is_empty_para(body_children[k]):
                parent = body_children[k].getparent()
                if parent is not None:
                    parent.remove(body_children[k])
                    cleared += 1
                k -= 1
            if shrunk or cleared:
                return f"分节符段压扁(清{cleared}个垫底空段)"
            # 压扁也救不了:渲染器在"页面样式变化"处始终硬翻页,这个只挂分节符的隐形段
            # 自己独占一页(招标原件附表区的固有排版,原件里就是空白页)。若它与**下一节**
            # 的纸张/页边距完全一致,则整段删除、两节合并——版式由后节接管,页脚页码
            # 本就是我们统一注入的同款,视觉无变化,空白页消失。
            sect_here = pPr.find(qn("w:sectPr"))
            sect_next = _next_section_props(body_children, j)
            if sect_next is not None and _same_page_geometry(sect_here, sect_next):
                prev.getparent().remove(prev)
                return "冗余分节符段删除(并节)"
            # 几何不同不敢并节:退而求其次,往回删一个垫底空段腾出一行。
            for back in range(k, max(-1, k - 3), -1):
                if back >= 0 and _is_empty_para(body_children[back]):
                    parent = body_children[back].getparent()
                    if parent is not None:
                        parent.remove(body_children[back])
                        return "内容块前垫段清1(腾出一行)"
                    break
    if removed_empty:
        return f"{removed_empty}个空段"
    return None


def _locate_all(body_children: list[Any], anchor: str, doc: Any) -> list[int]:
    """按锚点文字找出**所有**匹配的 body 元素下标(段落或表格首格),从后往前排。

    同一句话常在卷里出现多次(正文里的附表名称清单 vs 真正的附表页;目录 vs 正文),
    只取第一个会定位到错的地方——实测"附表五外供电力需求计划表"先命中的是技术卷正文里
    的名称清单,离真正那张表差着几百个元素,于是拆不到任何分页动作。改成返回全部候选,
    由调用方逐个试:谁前面真有多余的翻页动作就拆谁。从后往前试(真内容通常在清单之后)。
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    target = _norm(anchor)
    if not target:
        return []
    key = target[:14]
    hits: list[int] = []
    for i, el in enumerate(body_children):
        if el.tag == qn("w:p"):
            if _norm(Paragraph(el, doc).text).startswith(key):
                hits.append(i)
        elif el.tag == qn("w:tbl"):
            tbl = Table(el, doc)
            if tbl.rows and _norm(tbl.rows[0].cells[0].text).startswith(key):
                hits.append(i)
    return list(reversed(hits))


def heal_blank_pages(docx_path: str) -> dict[str, Any]:
    """把 docx 里的整页空白全部消掉(就地改写)。返回 {before, after, removed, iterations}。

    渲染不可用(没装 LibreOffice)时返回 ran=False,绝不阻断出标。
    """
    report: dict[str, Any] = {
        "ran": False, "iterations": 0, "before": None, "after": None, "removed": []
    }
    soffice = _soffice()
    if not soffice:
        logger.info("空白页闸:未找到 LibreOffice,跳过")
        return report

    from docx import Document

    deadline = time.monotonic() + _TIME_BUDGET_SECONDS
    src = Path(docx_path)
    with tempfile.TemporaryDirectory() as td:
        outdir = Path(td)
        for it in range(_MAX_ITERS):
            if time.monotonic() > deadline:
                logger.warning("空白页闸:时间预算用尽,停在第%d轮", it)
                break
            pdf = _render_pdf(
                soffice, src, outdir, timeout=max(30, int(deadline - time.monotonic()))
            )
            if pdf is None:
                break
            blanks = find_blank_pages(pdf)
            report["ran"] = True
            report["iterations"] = it + 1
            if report["before"] is None:
                report["before"] = [b["page"] + 1 for b in blanks]
            report["after"] = [b["page"] + 1 for b in blanks]
            if not blanks:
                logger.info("空白页闸:第%d轮复查,零空白页 ✓", it + 1)
                break

            doc = Document(str(src))
            body_children = list(doc.element.body)
            healed = 0
            # 从后往前处理:先改后面的,前面元素的下标不受影响
            for info in sorted(blanks, key=lambda b: -b["page"]):
                candidates = _locate_all(body_children, info["next_anchor"], doc)
                if not candidates:
                    # 空白页在卷尾:清掉末尾多余的空段与分页
                    j = len(body_children) - 1
                    while j >= 0 and _is_empty_para(body_children[j]):
                        body_children[j].getparent().remove(body_children[j])
                        healed += 1
                        j -= 1
                    if j >= 0:
                        for br in _page_breaks_in(body_children[j]):
                            br.getparent().remove(br)
                            healed += 1
                    continue
                for idx in candidates:  # 逐个候选试,谁前面有可拆的翻页动作就拆谁
                    how = _remove_one_break_before(body_children, idx)
                    if how:
                        healed += 1
                        report["removed"].append(f"第{info['page'] + 1}页:{how}")
                        break
            if not healed:
                logger.warning(
                    "空白页闸:仍有 %d 页空白但已无可拆的分页动作,停手(页号 %s)",
                    len(blanks), [b["page"] + 1 for b in blanks],
                )
                break
            doc.save(str(src))
    if report["after"]:
        logger.warning("空白页闸:仍残留空白页 %s", report["after"])
    return report
