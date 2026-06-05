from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from utils.bid_template_parser import parse_bid_template_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a reusable bid template JSON from a real bid PDF.")
    parser.add_argument("source", help="Path to the source bid PDF.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--name", default="", help="Human-readable template name.")
    args = parser.parse_args()

    template = parse_bid_template_pdf(args.source, template_name=args.name)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(template.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote template: {output_path}")
    print(f"Main sections: {len(template.main_sections)}")
    print(f"Construction sections: {len(template.construction_design_sections)}")
    print(f"Appendix sections: {len(template.appendix_sections)}")


if __name__ == "__main__":
    main()
