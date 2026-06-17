"""把公司历史施工方案(~/Desktop/施工方案)抽文字、按专业打标,灌入全局知识库。

这是材料架构里 [公司级 × 接地] 那一格:历史施组作为**公司级可复用的写作参考**,给所有
项目的技术卷生成接地(LLM 参照写法/深度,不照抄)。按文件夹名打 specialty 标签,生成时
技术卷检索按本项目专业优先(见 workflow._retrieve_for_outline)。

抽取:.docx 用 python-docx;.doc 用 macOS 自带 textutil(本地数据准备步骤)。
用法:
    python -m scripts.import_construction_plans ~/Desktop/施工方案            # 预览
    python -m scripts.import_construction_plans ~/Desktop/施工方案 --save     # 入库(可重复跑,按文件名跳过已入)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IMPORT_TAG = "导入批次-施工方案语料"
MIN_CHARS = 120  # 太短(空壳/封面)不灌
MAX_FILE_BYTES = 2_500_000  # 超大 .doc 多是嵌图/对象膨胀(实测 8.6MB 那个把嵌入卡死),跳过
MAX_CHARS = 50_000  # 抽出的文字截断上限,防个别超长文档炸出几百 chunk 拖垮嵌入

# 顶层文件夹 → 规范专业标签(检索时与本项目专业做关键词匹配)。
_SPECIALTY_MAP = {
    "市政": "市政公用工程",
    "公路": "公路工程",
    "桥涵工程": "桥涵工程",
    "排水工程": "排水工程",
    "电力电缆": "电力工程",
    "绿化工程": "绿化工程",
    "防护工程": "防护工程",
    "安保及防护工程": "安全防护",
    "保证体系、安全体系等方案": "通用",
    "施组（陈家林）": "综合施组",
}


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            from docx import Document

            return "\n".join(p.text for p in Document(str(path)).paragraphs)
        except Exception:
            return ""
    if suffix == ".doc":
        try:
            out = subprocess.run(
                ["textutil", "-convert", "txt", "-stdout", str(path)],
                capture_output=True,
                timeout=90,
            )
            return out.stdout.decode("utf-8", "ignore").replace("\x00", "")
        except Exception:
            return ""
    return ""


def _specialty_of(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    top = rel.parts[0] if len(rel.parts) > 1 else "通用"
    return _SPECIALTY_MAP.get(top, top)


def _existing_filenames() -> set[str]:
    from core.db import get_db_connection

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT file_name FROM documents WHERE project_id IS NULL "
                "AND metadata_json->>'document_category' = '施工方案'"
            )
            return {row[0] for row in cursor.fetchall()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入历史施工方案为公司写作语料")
    parser.add_argument("dir", help="施工方案根目录")
    parser.add_argument("--save", action="store_true", help="入库(默认仅预览)")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个(调试)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.dir).expanduser()
    files = sorted(
        p
        for p in root.rglob("*")
        if p.suffix.lower() in (".doc", ".docx") and not p.name.startswith("~$")
    )
    if args.limit:
        files = files[: args.limit]

    existing = _existing_filenames() if args.save else set()
    by_specialty: Counter = Counter()
    imported = skipped_short = skipped_dup = skipped_big = 0

    for path in files:
        specialty = _specialty_of(path, root)
        file_name = f"施工方案_{specialty}_{path.stem}.txt"
        if file_name in existing:
            skipped_dup += 1
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            skipped_big += 1  # 超大件(嵌图/对象膨胀)跳过,避免抽取/嵌入卡死
            print(f"  跳过超大件 {path.stat().st_size // 1024}KB: {path.name}")
            continue
        text = _extract_text(path)[:MAX_CHARS]
        if len(text.strip()) < MIN_CHARS:
            skipped_short += 1
            continue
        by_specialty[specialty] += 1
        if args.save:
            from services import knowledge_service

            knowledge_service.index_uploaded_knowledge(
                file_bytes=text.encode("utf-8"),
                filename=file_name,
                content_type="text/plain",
                document_category="施工方案",
                document_type="施工方案",
                specialty=specialty,
                volume="技术文件",
                tags=[IMPORT_TAG],
                ingestion_mode="rag_text",
            )
            imported += 1

    print(f"扫描 {len(files)} 个文件;按专业(可入库): {dict(by_specialty)}")
    print(f"太短跳过 {skipped_short};超大跳过 {skipped_big};已存在跳过 {skipped_dup}")
    if args.save:
        print(f"✅ 入库 {imported} 篇,tag={IMPORT_TAG}")
    else:
        print("(预览,未入库;加 --save 入库)")


if __name__ == "__main__":
    main()
