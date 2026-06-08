from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.template_service import DEFAULT_TEMPLATE_PATH, seed_template_from_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a checked-in BidTemplate JSON into the template library."
    )
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE_PATH))
    parser.add_argument("--name")
    parser.add_argument("--project-type", default="公路工程")
    parser.add_argument("--specialty", default="道路")
    parser.add_argument("--envelope-type")
    parser.add_argument("--region")
    parser.add_argument("--project-year", type=int)
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        help="Template tag. May be repeated.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = seed_template_from_json(
        template_path=args.template,
        name=args.name,
        project_type=args.project_type,
        specialty=args.specialty,
        envelope_type=args.envelope_type,
        region=args.region,
        project_year=args.project_year,
        tags=args.tags,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
