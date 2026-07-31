"""导入正奇业绩库里的**业绩证明扫描件**(中标通知书/合同/交工验收)到知识库。

import_performance_ledger.py 只导了结构化业绩台账(253条),刻意没导扫描件。但真实标书
资格审查里每个类似业绩后面要附**中标通知书+合同+交工验收**几十~几百页——A3 证据链需要这些
扫描件按业绩可查、可插。本脚本:遍历 ~/Desktop/知识库材料/正奇业绩库 的每个 `N#项目名` 文件夹,
按**文件名关键词**把图片归类成 中标通知书/合同/交工验收,写库时打 performance_project(项目名)+
evidence_type 元数据,生成时按业绩把对应扫描件成组插入资格审查卷。

只导图片(jpg/png,可直接插入);PDF 计入统计但本轮不导(需栅格化,留后续)。

用法:
  预览(不写库,默认):  PYTHONPATH=backend .venv/bin/python backend/scripts/import_performance_evidence.py "~/Desktop/知识库材料/正奇业绩库"
  入库:               ... --import-to-kb [--limit-projects N]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

COMPANY_NAME = "安徽正奇建设有限公司"
EVIDENCE_TAG = "导入批次-业绩证明扫描"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
# 单文件上限:扫描件一般 <8MB;超大跳过(防卡 MinIO/OCR)。
MAX_FILE_BYTES = 12_000_000

# 文件名关键词 → 证据类型(顺序=优先级,先命中先归类)。
# "中标"裸词垫底:真实文件名有"火龙街道永善路中标.jpg""中标公告.jpg"这种简写
# (2026-07-12对账发现漏导),放最后防误吞"中标通知书"等长词该归的。
_EVIDENCE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("中标通知书", ("中标通知书", "中标结果", "中标公示", "成交通知", "中标公告", "中标")),
    ("交工验收", ("交工", "竣工", "完工证明", "验收证书", "验收报告", "工程验收")),
    ("合同", ("合同", "协议书")),
)
# 这些不是核心证据链(变更/开工令/缩略图等),不导。
_SKIP_KEYWORDS = ("变更", "开工令", "缩略", "thumb", "副本")


def classify(filename: str) -> str | None:
    name = filename.lower()
    if any(k.lower() in name for k in _SKIP_KEYWORDS):
        return None
    for evidence_type, keywords in _EVIDENCE_RULES:
        if any(k in filename for k in keywords):
            return evidence_type
    return None


# ── 全量模式(2026-07-30 用户拍板:"文件夹里所有的图片都要附,PDF子文件夹也要") ──
# 与关键词模式的差别:①没命中关键词的文件不再丢弃,归"其他";②PDF 逐页栅格化成图入库;
# ③只跳真垃圾(缩略图/系统文件),"变更/开工令"等此前被排除的也全收。
_JUNK_KEYWORDS = ("缩略", "thumb")
_JUNK_NAMES = ("thumbs.db", ".ds_store", "desktop.ini")


def classify_all(filename: str) -> str | None:
    """全量模式归类:垃圾文件返回 None,关键词命中归对应类,其余一律"其他"。"""
    low = filename.lower()
    if low in _JUNK_NAMES or any(k in low for k in _JUNK_KEYWORDS):
        return None
    for evidence_type, keywords in _EVIDENCE_RULES:
        if any(k in filename for k in keywords):
            return evidence_type
    return "其他"


def pdf_page_images(pdf_path: Path, max_pages: int = 40) -> list[tuple[str, bytes]]:
    """PDF 逐页栅格化 → [(页文件名, jpg字节)]。~150DPI,标书插图看清公章足够。"""
    import fitz

    out: list[tuple[str, bytes]] = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return out
    try:
        for page_no in range(min(doc.page_count, max_pages)):
            pix = doc[page_no].get_pixmap(matrix=fitz.Matrix(2.08, 2.08))
            blob = pix.tobytes("jpg")
            # fitz 直出的 JFIF 头 DPI=0 → python-docx 插图算尺寸除零(2026-07-31 实测
            # 22张交工验收全成占位符)。PIL 重编码写上 150DPI 断根。
            try:
                import io as _io

                from PIL import Image as _PILImage

                im = _PILImage.open(_io.BytesIO(blob))
                buf = _io.BytesIO()
                im.save(buf, format="JPEG", quality=90, dpi=(150, 150))
                blob = buf.getvalue()
            except Exception:
                pass  # 重编码失败就用原字节(插图侧还有除零兜底)
            if blob and len(blob) <= MAX_FILE_BYTES:
                out.append((f"{pdf_path.stem}_第{page_no + 1}页.jpg", blob))
    finally:
        doc.close()
    return out


def scan_all(base: Path) -> dict:
    """全量遍历(含 PDF 子文件夹):{project: [(evidence_type, Path), ...]},文件名序。"""
    out: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    exts = IMAGE_EXTS | {".pdf"}
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        proj = _project_name(folder.name)
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in exts:
                continue
            evidence_type = classify_all(path.name)
            if evidence_type:
                out[proj].append((evidence_type, path))
    return out


def _existing_file_names() -> set[tuple[str, str]]:
    """已入库的 (项目, 原文件名),全量模式的幂等键(序号键会因排序漂移误判)。"""
    from rag.vector_store import get_db_connection

    out: set[tuple[str, str]] = set()
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT metadata_json->>'performance_project', file_name "
            "FROM documents WHERE project_id IS NULL "
            "AND metadata_json->>'document_category' = '业绩证明'"
        )
        for proj, fname in cursor.fetchall():
            if proj and fname:
                out.add((str(proj), str(fname)))
    return out


def _next_seq_by_type() -> dict[tuple[str, str], int]:
    """每 (项目,类型) 的下一个可用序号(接在已入库的最大序号后,不与旧图撞号)。"""
    from rag.vector_store import get_db_connection

    out: dict[tuple[str, str], int] = {}
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT metadata_json->>'performance_project', metadata_json->>'evidence_type', "
            "COALESCE(MAX((metadata_json->>'evidence_seq')::int), -1) "
            "FROM documents WHERE project_id IS NULL "
            "AND metadata_json->>'document_category' = '业绩证明' "
            "AND metadata_json->>'evidence_seq' ~ '^[0-9]+$' "
            "GROUP BY 1, 2"
        )
        for proj, etype, mx in cursor.fetchall():
            if proj and etype:
                out[(str(proj), str(etype))] = int(mx) + 1
    return out


def import_all(base: Path, limit_projects: int = 0) -> None:
    """全量入库:图片直收,PDF 逐页转图;按 (项目,文件名) 幂等,可断点续跑。"""
    from services.knowledge_service import index_uploaded_knowledge

    data = scan_all(base)
    existing = _existing_file_names()
    next_seq = _next_seq_by_type()
    print(f"全量模式:{len(data)} 个项目文件夹,已入库 {len(existing)} 个文件名。")
    projects = list(data.items())
    if limit_projects:
        projects = projects[:limit_projects]
    done = skipped = failed = 0

    def _put(proj: str, fname: str, blob: bytes, etype: str, year: int | None) -> None:
        nonlocal done
        seq = next_seq.get((proj, etype), 0)
        next_seq[(proj, etype)] = seq + 1
        index_uploaded_knowledge(
            file_bytes=blob,
            filename=fname,
            document_category="业绩证明",
            document_type=etype,
            owner_type="公司",
            owner_name=COMPANY_NAME,
            project_year=year,
            image_insertable=True,
            ingestion_mode="evidence_only",
            ocr_images=False,
            tags=["业绩证明", etype, EVIDENCE_TAG, "全量补导"],
            extra_metadata={
                "performance_project": proj,
                "evidence_type": etype,
                "evidence_seq": seq,
            },
        )
        done += 1
        if done % 100 == 0:
            print(f"   …已导 {done} 张")

    for proj, items in projects:
        year = _project_year(proj)
        for etype, path in items:
            try:
                if path.suffix.lower() == ".pdf":
                    pages = pdf_page_images(path)
                    if not pages:
                        failed += 1
                        continue
                    for fname, blob in pages:
                        if (proj, fname) in existing:
                            skipped += 1
                            continue
                        _put(proj, fname, blob, etype, year)
                else:
                    if (proj, path.name) in existing:
                        skipped += 1
                        continue
                    blob = path.read_bytes()
                    if not blob or len(blob) > MAX_FILE_BYTES:
                        failed += 1
                        continue
                    _put(proj, path.name, blob, etype, year)
            except Exception as exc:  # noqa: BLE001 - 单文件失败不断整批
                failed += 1
                print(f"   ⚠️ {proj[:20]}/{path.name}: {exc}")
    print(f"✅ 全量入库完成:新导 {done}、跳过已存 {skipped}、失败 {failed}")


def _project_name(folder: str) -> str:
    """`240#萧县…三标段` → 萧县…三标段;裸数字前缀 `221萧县…` 也剥(2026-07-30 清洗发现:
    不剥会与老库名分家,同一项目两个名字、生成时只匹配到一半图)。`2022年…`年份开头不动。"""
    name = re.sub(r"^\d+[-#＃]+", "", folder).strip()
    name = re.sub(r"^\d{1,3}(?=[^\d年])", "", name).strip()
    return name or folder


def _project_year(name: str) -> int | None:
    match = re.search(r"(20\d{2})", name)
    return int(match.group(1)) if match else None


def _existing_keys() -> set[tuple[str, str, int]]:
    """已入库的业绩证明 (项目, 类型, 序号),供幂等跳过。"""
    from rag.vector_store import get_db_connection

    out: set[tuple[str, str, int]] = set()
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT metadata_json->>'performance_project', "
            "metadata_json->>'evidence_type', metadata_json->>'evidence_seq' "
            "FROM documents WHERE project_id IS NULL "
            "AND metadata_json->>'document_category' = '业绩证明'"
        )
        for proj, etype, seq in cursor.fetchall():
            if proj and etype and seq is not None:
                try:
                    out.add((str(proj), str(etype), int(seq)))
                except (TypeError, ValueError):
                    continue
    return out


def scan(base: Path) -> dict:
    """遍历业绩库,返回 {project_name: {evidence_type: [Path,...]}} 仅图片。"""
    out: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        proj = _project_name(folder.name)
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                continue
            evidence_type = classify(path.name)
            if evidence_type:
                out[proj][evidence_type].append(path)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入业绩证明扫描件(中标/合同/交工验收)")
    parser.add_argument("base", help="正奇业绩库根目录")
    parser.add_argument("--import-to-kb", action="store_true", help="真入库(默认仅预览)")
    parser.add_argument("--limit-projects", type=int, default=0, help="只导前N个项目(测试用)")
    parser.add_argument(
        "--all-files", action="store_true",
        help="全量模式:所有文件都收(无关键词归'其他'),PDF逐页转图(2026-07-30用户拍板)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base = Path(args.base).expanduser()
    if not base.is_dir():
        raise SystemExit(f"目录不存在:{base}")

    if args.all_files:
        if args.import_to_kb:
            import_all(base, args.limit_projects)
        else:
            data_all = scan_all(base)
            total = sum(len(v) for v in data_all.values())
            pdfs = sum(1 for v in data_all.values() for t, p in v if p.suffix.lower() == ".pdf")
            print(f"全量预览:{len(data_all)} 个项目,{total} 个文件(其中 PDF {pdfs} 个)")
            print("(加 --import-to-kb 真入库)")
        return

    data = scan(base)
    type_counter: Counter = Counter()
    projects_with_chain = 0
    total_files = 0
    for proj, by_type in data.items():
        for evidence_type, paths in by_type.items():
            type_counter[evidence_type] += len(paths)
            total_files += len(paths)
        if {"中标通知书", "交工验收"} <= set(by_type):  # 至少有中标+交工=完整链
            projects_with_chain += 1

    print(f"业绩项目(有可归类扫描件): {len(data)} 个")
    print(f"其中中标+交工都齐(完整证据链): {projects_with_chain} 个")
    print(f"可导图片总数: {total_files} 张")
    for evidence_type, count in type_counter.most_common():
        print(f"   {evidence_type}: {count} 张")
    print("\n样例(前5个项目):")
    for proj, by_type in list(data.items())[:5]:
        summary = "、".join(f"{t}×{len(p)}" for t, p in by_type.items())
        print(f"   {proj[:40]}: {summary}")

    if not args.import_to_kb:
        print("\n(预览模式,未写库;加 --import-to-kb 入库)")
        return

    from services.knowledge_service import index_uploaded_knowledge

    existing = _existing_keys()  # (项目,类型,序号) 已入库 → 跳过(幂等,可断点续跑)
    print(f"已入库业绩证明 {len(existing)} 条,跳过重复。")
    projects = list(data.items())
    if args.limit_projects:
        projects = projects[: args.limit_projects]
    done = 0
    skipped = 0
    for proj, by_type in projects:
        year = _project_year(proj)
        for evidence_type, paths in by_type.items():
            for idx, path in enumerate(sorted(paths)):
                if (proj, evidence_type, idx) in existing:
                    skipped += 1
                    continue
                try:
                    blob = path.read_bytes()
                except OSError:
                    continue
                if not blob or len(blob) > MAX_FILE_BYTES:
                    continue
                index_uploaded_knowledge(
                    file_bytes=blob,
                    filename=path.name,
                    document_category="业绩证明",
                    document_type=evidence_type,
                    owner_type="公司",
                    owner_name=COMPANY_NAME,
                    project_year=year,
                    image_insertable=True,
                    ingestion_mode="evidence_only",
                    ocr_images=False,  # 扫描件只插不搜,跳 OCR 提速(1900+张)
                    tags=["业绩证明", evidence_type, EVIDENCE_TAG],
                    extra_metadata={
                        "performance_project": proj,
                        "evidence_type": evidence_type,
                        "evidence_seq": idx,
                    },
                )
                done += 1
                if done % 100 == 0:
                    print(f"   …已导 {done} 张")
    print(
        f"✅ 入库完成:新导 {done} 张、跳过已存 {skipped} 张"
        f"(across {len(projects)} 个项目)"
    )


if __name__ == "__main__":
    main()
