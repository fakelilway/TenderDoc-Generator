"""业绩档案对账报告(只读):台账 ↔ 证明 对号情况 + 需人工抽查清单。

用法: PYTHONPATH=backend backend/venv/bin/python backend/scripts/performance_archive_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import performance_archive_service as pa  # noqa: E402


def main() -> None:
    arc = pa.build_archive()
    s = arc["stats"]
    print("=" * 56)
    print("业绩档案对账报告")
    print("=" * 56)
    print(f"业绩台账(项目卡)   : {s['ledger_total']} 个")
    print(f"业绩证明(分组项目) : {s['evidence_projects']} 个 / {s['evidence_images']} 张图")
    print("-" * 56)
    print(f"✅ 台账↔证明 已配对 : {s['matched']} 个")
    print(f"   其中证据链完整(中标+交工都有): {s['matched_complete_chain']} 个")
    print(f"   ⚠️ 名字有出入需抽查        : {s['matched_need_review']} 个")
    print(f"📷 有证明对不上台账 : {s['evidence_only']} 个  (待人工认领)")
    print(f"📄 有台账没找到证明 : {s['ledger_only']} 个  (证据链缺口)")

    print("\n" + "-" * 56)
    print("⚠️ 需抽查的低置信配对(名字对得勉强,前15条):")
    for m in [x for x in arc["matched"] if x["needs_review"]][:15]:
        types = "、".join(f"{t}×{n}" for t, n in m["types"].items())
        print(f"  [{m['score']}] 证明:{m['evidence_project'][:34]}")
        print(f"          ↔ 台账:{str(m['ledger']['name'])[:34]}  ({types})")

    print("\n" + "-" * 56)
    print("📷 有证明、对不上台账(前15条,需认领):")
    for e in arc["evidence_only"][:15]:
        types = "、".join(f"{t}×{n}" for t, n in e["types"].items())
        guess = f"  猜:{e['best_guess'][:24]}({e['best_score']})" if e["best_guess"] else ""
        print(f"  {e['evidence_project'][:34]}  ({types}){guess}")

    print("\n" + "-" * 56)
    print("📄 有台账、没证明(前15条,证据链缺口):")
    for led in arc["ledger_only"][:15]:
        print(f"  {str(led['name'])[:40]}  {led.get('year','')}  {led.get('amount','')}")
    print("=" * 56)


if __name__ == "__main__":
    main()
