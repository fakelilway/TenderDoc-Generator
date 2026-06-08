from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import bid_gap_eval

DEFAULT_OUT_DIR = BACKEND_DIR / "eval_results"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="对比 AI 生成投标文件与真实投标文件，输出结构差距报告。"
    )
    parser.add_argument(
        "--ai",
        required=True,
        help="AI 生成的投标文件路径（.docx / .md / .txt）。",
    )
    parser.add_argument(
        "--reference",
        required=True,
        help="真实投标参照（真实投标 .pdf 或已抽取的模板 .json）。",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="报告输出目录。",
    )
    args = parser.parse_args()

    template, reference_total_chars = bid_gap_eval.load_reference_template(
        args.reference
    )
    ai_structure = bid_gap_eval.load_ai_structure(args.ai)
    report = bid_gap_eval.evaluate_gap(
        template,
        ai_structure,
        reference_total_chars=reference_total_chars,
        ai_source=Path(args.ai).name,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "bid_gap_latest.json"
    md_path = out_dir / "bid_gap_latest.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(bid_gap_eval.render_markdown_report(report), encoding="utf-8")

    print(f"参照模板: {report['reference_template']}")
    print(f"主章节覆盖率: {report['main_section_coverage']}")
    print(f"施工附表覆盖率: {report['appendix_coverage']}")
    print(f"差距问题数: {len(report['issues'])}")
    for issue in report["issues"]:
        print(f"  - {issue}")
    print(f"Markdown 报告: {md_path}")
    print(f"JSON 报告: {json_path}")


if __name__ == "__main__":
    main()
