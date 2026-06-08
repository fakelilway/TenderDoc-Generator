from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import quality_eval

DEFAULT_MANIFEST = (
    BACKEND_DIR / "tests" / "fixtures" / "quality_eval" / "manifest.json"
)
DEFAULT_OUT_DIR = BACKEND_DIR / "eval_results"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="一键运行投标质量评估并输出 Markdown/JSON 报告。"
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="评估集 manifest.json 路径。",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="报告与历史输出目录。",
    )
    parser.add_argument(
        "--version",
        default="",
        help="本次评估的版本号/标签，默认使用时间戳。",
    )
    args = parser.parse_args()

    generated_at = datetime.now().isoformat(timespec="seconds")
    version = args.version or generated_at

    eval_set = quality_eval.load_eval_set(args.manifest)
    report = quality_eval.run_eval(
        eval_set, version=version, generated_at=generated_at
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path = out_dir / "quality_eval_history.jsonl"
    history = quality_eval.append_history(history_path, report)

    json_path = out_dir / "quality_eval_latest.json"
    md_path = out_dir / "quality_eval_latest.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(
        quality_eval.render_markdown_report(report, history=history),
        encoding="utf-8",
    )

    aggregate = report["aggregate"]
    print(f"评估样本数: {report['case_count']}")
    print(f"解析准确率: {aggregate['parse_accuracy']}")
    print(f"章节完整率: {aggregate['section_completeness']}")
    print(f"废标检出率: {aggregate['invalid_detection_rate']}")
    print(f"人工修改量: {aggregate['manual_edit_ratio']}")
    print(f"总耗时(秒): {aggregate['total_elapsed_seconds']}")
    print(f"Markdown 报告: {md_path}")
    print(f"JSON 报告: {json_path}")
    print(f"历史记录(共 {len(history)} 条): {history_path}")


if __name__ == "__main__":
    main()
