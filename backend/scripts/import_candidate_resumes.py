"""解析《拟委任的项目经理和项目总工资历表.doc》→ 资历表定稿数据源。

一人一张表,字段:姓名/年龄/专业/技术职称/学历/工作年限/类似施工经验年限/毕业学校/
获奖情况(拟任职务不入库——按选派角色定,不照抄文档)。.doc 自动经 LibreOffice 转 docx。

用法:
  PYTHONPATH=backend .venv/bin/python backend/scripts/import_candidate_resumes.py \
      "~/Desktop/拟委任的项目经理和项目总工资历表.doc" [--save]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 表内标签 → 定稿字段键。"拟在本标段"刻意不收:拟任职务由选派角色决定。
_LABELS: tuple[tuple[str, str], ...] = (
    ("姓名", "姓名"),
    ("年龄", "年龄"),
    ("专业", "专业"),
    ("技术职称", "职称"),
    ("学历", "学历"),
    ("工作年限", "工作年限"),
    ("类似施工经验年限", "类似施工经验年限"),
    ("毕业学校", "毕业学校"),
    ("获奖情况", "获奖情况"),
)
_LABEL_SET = {lbl for lbl, _ in _LABELS}


def _norm(s: str) -> str:
    return re.sub(r"[\s\t　]+", "", s or "")


def _to_docx(path: Path) -> Path:
    if path.suffix.lower() == ".docx":
        return path
    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    outdir = Path(tempfile.mkdtemp())
    subprocess.run(
        [soffice, "--headless", "--convert-to", "docx", "--outdir", str(outdir), str(path)],
        check=True, capture_output=True, timeout=120,
    )
    return outdir / (path.stem + ".docx")


def parse_resume_table(table) -> dict[str, str]:
    """一张资历表 → {字段:值}。按"标签格→右邻值格"扫,合并格去重。"""
    fields: dict[str, str] = {}
    for row in table.rows:
        cells: list[str] = []
        for c in row.cells:  # 相邻合并格会重复出现,去重
            t = c.text.strip()
            if not cells or _norm(cells[-1]) != _norm(t):
                cells.append(t)
        i = 0
        while i < len(cells):
            label = _norm(cells[i])
            key = next(
                (k for lbl, k in _LABELS if label == _norm(lbl) or label.startswith(_norm(lbl))),
                None,
            )
            # "专业"是"道路与桥梁工程"这类值格的表头;别把值格当标签
            if key and i + 1 < len(cells) and _norm(cells[i + 1]) not in _LABEL_SET:
                value = re.sub(r"\s+", " ", cells[i + 1]).strip()
                if key == "年龄":
                    m = re.search(r"\d{2}", value)
                    value = m.group(0) if m else value
                if value and value not in ("/", "-"):
                    fields[key] = value
                i += 2
            else:
                i += 1
    return fields


def main() -> None:
    parser = argparse.ArgumentParser(description="导入资历表定稿")
    parser.add_argument("path", help="资历表 .doc/.docx 路径")
    parser.add_argument("--save", action="store_true", help="写库(默认仅预览)")
    args = parser.parse_args()

    from docx import Document

    src = Path(args.path).expanduser()
    if not src.exists():
        raise SystemExit(f"文件不存在:{src}")
    doc = Document(str(_to_docx(src)))

    resumes: dict[str, dict[str, str]] = {}
    for table in doc.tables:
        fields = parse_resume_table(table)
        name = fields.pop("姓名", "").strip()
        if name:
            resumes[name] = fields

    print(f"解析出 {len(resumes)} 人:")
    for name, f in resumes.items():
        print(f"  {name}: " + "、".join(f"{k}={v[:24]}" for k, v in f.items()))

    if args.save:
        from services.curated_resume_service import save_curated_resumes

        docx_path = _to_docx(src)
        n = save_curated_resumes(resumes, src.name, docx_bytes=docx_path.read_bytes())
        print(f"✅ 已存为资历表定稿({n}人,含整份模版docx),生成时按选派人选整表照搬")
    else:
        print("(预览模式,加 --save 写库)")


if __name__ == "__main__":
    main()
