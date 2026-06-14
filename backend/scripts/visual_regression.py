"""导出 DOCX 的视觉回归冒烟检查（Phase 3 / M15）。

用 LibreOffice 把 DOCX 渲染成 PDF，再做结构断言：页数合理、无连续空白页、
关键 token（投标人名称/项目名）出现在文本层。任一断言失败则非零退出，
可接入 CI 作为冒烟。

用法：
    python backend/scripts/visual_regression.py <doc.docx> \
        [--expect 投标人] [--expect 项目名] [--max-blank-run 2]

LibreOffice 自动探测 PATH 与 macOS app 包路径；找不到时跳过渲染类断言。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def find_soffice() -> str | None:
    for candidate in ("soffice", "libreoffice"):
        found = shutil.which(candidate)
        if found:
            return found
    mac = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    return mac if os.path.exists(mac) else None


def render_to_pdf(docx_path: Path, soffice: str, out_dir: Path) -> Path | None:
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx_path)],
            check=True,
            capture_output=True,
            timeout=240,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    pdfs = list(out_dir.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def check(docx_path: Path, expect_tokens: list[str], max_blank_run: int) -> list[str]:
    """Return a list of failure messages (empty = all checks passed)."""
    failures: list[str] = []
    soffice = find_soffice()
    if not soffice:
        print("⚠️  未找到 soffice，跳过渲染类断言（页数/空白页/文本层）。")
        return failures

    with tempfile.TemporaryDirectory() as tmp:
        pdf = render_to_pdf(docx_path, soffice, Path(tmp))
        if not pdf:
            return [f"LibreOffice 渲染失败：{docx_path}"]

        import fitz

        doc = fitz.open(str(pdf))
        try:
            page_count = doc.page_count
            texts = [doc[i].get_text() for i in range(page_count)]
        finally:
            doc.close()

        if page_count == 0:
            failures.append("渲染后页数为 0")

        # consecutive blank pages
        run = 0
        worst = 0
        for t in texts:
            if len(t.strip()) < 5:
                run += 1
                worst = max(worst, run)
            else:
                run = 0
        if worst > max_blank_run:
            failures.append(f"出现 {worst} 连续空白页（上限 {max_blank_run}）")

        # key tokens present somewhere in the text layer
        full = "\n".join(texts)
        for token in expect_tokens:
            if token and token not in full:
                failures.append(f"关键 token 未出现在文本层：{token}")

        print(f"页数={page_count}  最长连续空白={worst}  文本层字数={len(full)}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 DOCX 视觉回归冒烟检查。")
    parser.add_argument("docx")
    parser.add_argument("--expect", action="append", default=[], help="必须出现在文本层的 token，可多次")
    parser.add_argument("--max-blank-run", type=int, default=2)
    args = parser.parse_args()

    failures = check(Path(args.docx), args.expect, args.max_blank_run)
    if failures:
        print("❌ 视觉回归失败：")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("✅ 视觉回归通过")


if __name__ == "__main__":
    main()
