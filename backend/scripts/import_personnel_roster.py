"""把公司人员证书台账 xlsx 解析成结构化名册并存入 company_personnel。

用法:
    python -m scripts.import_personnel_roster <xlsx路径>            # 解析+预览,不入库
    python -m scripts.import_personnel_roster <xlsx路径> --save     # 解析+存库

名册供投标时按招标项目经理要求(建造师等级+专业+安全B证)选派,替代 company_profile
里写死的单个项目经理。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.personnel_roster_service import (  # noqa: E402
    kb_builder_candidates,
    merge_kb_builders,
    parse_roster_xlsx,
    save_personnel_roster,
)


def _summarize(members: list) -> None:
    pms = [m for m in members if m.is_pm_candidate]
    src = {}
    for member in pms:
        src[member.source] = src.get(member.source, 0) + 1
    print(
        f"名册共 {len(members)} 人;项目经理候选(有建造师证) {len(pms)} 人 "
        f"(来源 {src})"
    )
    combo: Counter = Counter()
    for member in pms:
        for cert in member.builder_certs:
            combo[(cert.level, cert.specialty)] += 1
    for (level, specialty), count in combo.most_common():
        print(f"   {level} / {specialty}: {count}")
    with_b = [m for m in pms if "B" in m.safety_cert_classes]
    print(f"   其中持安全B证(项目经理硬需求): {len(with_b)} 人")
    print(f"   有职称(高工/工程师/助工): {sum(1 for m in members if m.title)} 人")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入公司人员证书台账为结构化名册")
    parser.add_argument("xlsx", help="人员证书列表 xlsx 路径")
    parser.add_argument(
        "--save", action="store_true", help="存入 company_personnel(默认仅预览)"
    )
    parser.add_argument(
        "--no-kb",
        action="store_true",
        help="不并入知识库建造师(默认台账+知识库合并)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    members = parse_roster_xlsx(args.xlsx)
    if not args.no_kb:
        members = merge_kb_builders(members, kb_builder_candidates())
    _summarize(members)
    if args.save:
        save_personnel_roster(members)
        print(f"✅ 已存入 company_personnel:{len(members)} 人")
    else:
        print("(预览模式,未入库;加 --save 存库)")


if __name__ == "__main__":
    main()
