"""业绩证明**视觉查重**:同一材料既有 jpg 扫描又有 PDF 版时,删掉 PDF 转出的重复页。

2026-07-31 用户发现:全量补导把"同一份文件的 pdf 版和 jpg 版"都收了 → 生成时同一页
附两遍。规则(守住去重红线——正反面/多页≠重复,只有**视觉上同一页**才算重复):
- 只考虑删 **PDF 转图页**(file_name 形如 xxx_第N页.jpg 的全量补导产物);
  jpg/png 原件绝不动。
- 感知哈希(dhash 8x8 + 16x16 双指纹)比对:与组内任一保留图距离 ≤ 阈值 = 同一页。
  实测校准(萧县/G343):真重复 0-7,不同内容 ≥10 → 阈值取 7/30。
- PDF 页之间也互查(G343 实测"业绩证明材料.pdf"就是合同+竣工证书的重新装订合集):
  按序保留第一份,后来的重复页删。
- 只删 documents 行(生成就看不见了),MinIO 字节不动——可回溯。

用法:
  预览: PYTHONPATH=backend .venv/bin/python backend/scripts/dedup_evidence_visual.py
  执行: ... --delete
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_PDF_PAGE_RE = re.compile(r"_第\d+页\.jpg$")
_D8_THRESHOLD = 7
_D16_THRESHOLD = 30


def _dhash(blob: bytes, size: int) -> int:
    from PIL import Image

    im = Image.open(io.BytesIO(blob)).convert("L").resize((size + 1, size))
    px = list(im.getdata())
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | (1 if px[r * (size + 1) + c] > px[r * (size + 1) + c + 1] else 0)
    return bits


def _ham(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def main() -> None:
    parser = argparse.ArgumentParser(description="业绩证明视觉查重(删PDF重复页)")
    parser.add_argument("--delete", action="store_true", help="真删(默认仅预览)")
    parser.add_argument("--project", default="", help="只处理某个项目(调试)")
    args = parser.parse_args()

    from core.config import settings
    from rag.vector_store import get_db_connection
    from utils.minio_client import minio_client

    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT metadata_json->>'performance_project', id, file_name, file_path "
            "FROM documents WHERE project_id IS NULL "
            "AND metadata_json->>'document_category'='业绩证明' "
            "ORDER BY metadata_json->>'performance_project', "
            "  (file_name ~ '_第[0-9]+页\\.jpg$'), file_name"
        )
        rows = cur.fetchall()

    groups: dict[str, list[tuple[int, str, str]]] = {}
    for proj, did, fname, fpath in rows:
        groups.setdefault(proj or "", []).append((int(did), fname, fpath))

    to_delete: list[tuple[int, str, str, str]] = []  # (id, proj, fname, 对应保留图)
    scanned = 0
    for proj, docs in groups.items():
        if args.project and args.project not in proj:
            continue
        if not any(_PDF_PAGE_RE.search(f) for _i, f, _p in docs):
            continue
        kept: list[tuple[int, int, str]] = []  # (d8, d16, fname) 已保留图指纹
        for did, fname, fpath in docs:  # 排序保证:原件在前,PDF页在后
            try:
                blob = minio_client.download_bytes(settings.minio_bucket, fpath)
                d8, d16 = _dhash(blob, 8), _dhash(blob, 16)
                scanned += 1
            except Exception:
                continue
            if _PDF_PAGE_RE.search(fname):
                dup_of = next(
                    (kf for k8, k16, kf in kept
                     if _ham(d8, k8) <= _D8_THRESHOLD and _ham(d16, k16) <= _D16_THRESHOLD),
                    None,
                )
                if dup_of is not None:
                    to_delete.append((did, proj, fname, dup_of))
                    continue
            kept.append((d8, d16, fname))

    print(f"扫描 {scanned} 张;判定重复的 PDF 页:{len(to_delete)} 张")
    by_proj: dict[str, int] = {}
    for _i, proj, _f, _k in to_delete:
        by_proj[proj] = by_proj.get(proj, 0) + 1
    for proj, n in sorted(by_proj.items(), key=lambda x: -x[1])[:15]:
        print(f"  {proj[:36]}: 删 {n} 张重复PDF页")

    if not args.delete:
        print("(预览模式,加 --delete 真删;只删库记录,MinIO字节保留可回溯)")
        return
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for did, _p, _f, _k in to_delete:
                cur.execute("DELETE FROM documents WHERE id=%s", (did,))
        conn.commit()
    print(f"✅ 已删除 {len(to_delete)} 条重复PDF页记录")


if __name__ == "__main__":
    main()
