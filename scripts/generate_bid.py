#!/usr/bin/env python3
"""Generate a sanitized bid Markdown/DOCX from structured requirements.

This script is a formal CLI wrapper around the production generator and DOCX
exporter. It does not hard-code project names, bidder names, contacts, prices,
or local file paths.

Examples:
    python scripts/generate_bid.py \
      --requirements data/sample_requirements.json \
      --template backend/templates/bid_templates/road_first_envelope_template.json \
      --output-dir data/output

    python scripts/generate_bid.py --demo --output-dir data/output/demo
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_TEMPLATE = BACKEND_DIR / "templates/bid_templates/road_first_envelope_template.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data/output"
DEFAULT_COMPANY_NAME = "投标人名称（脱敏）"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents import generator_agent  # noqa: E402
from schemas.bid_template import BidTemplate  # noqa: E402
from schemas.tender import RequirementItem, TenderRequirements  # noqa: E402
from utils.docx_exporter import build_export_filename, markdown_to_docx  # noqa: E402


def load_requirements(path: str | Path | None, *, demo: bool = False) -> TenderRequirements:
    if demo:
        return TenderRequirements(
            project_name="脱敏示例项目",
            qualification_list=[
                RequirementItem(title="企业资质", description="具备与项目类型匹配的施工资质。"),
                RequirementItem(title="项目负责人", description="项目负责人资格证书、社保和业绩需人工核对。"),
            ],
            technical_score_items=[
                RequirementItem(title="施工组织设计", description="施工部署、质量、安全、进度措施完整。"),
                RequirementItem(title="重难点分析", description="结合项目特点提出针对性技术措施。"),
                RequirementItem(title="项目管理机构", description="项目班子配置合理，职责清晰。"),
            ],
            invalid_bid_items=[
                RequirementItem(title="投标保证金", description="未按招标文件要求提交保证金可能导致否决投标。"),
                RequirementItem(title="签章要求", description="投标文件签字盖章不完整可能导致否决投标。"),
            ],
        )

    if not path:
        raise ValueError("Provide --requirements or use --demo")

    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "parsed_json" in payload:
        payload = payload["parsed_json"]
    return TenderRequirements.model_validate(payload)


def load_template(path: str | Path | None) -> BidTemplate | None:
    if not path:
        return None
    template_path = Path(path).expanduser()
    if not template_path.is_absolute():
        template_path = PROJECT_ROOT / template_path
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    return BidTemplate.model_validate_json(template_path.read_text(encoding="utf-8"))


def load_retrieved_chunks(path: str | Path | None) -> dict[str, list[str]]:
    if not path:
        return {}
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--retrieved-chunks must be a JSON object keyed by section title")
    return {
        str(key): [str(item) for item in value]
        for key, value in payload.items()
        if isinstance(value, list)
    }


def generate_bid_artifacts(
    requirements: TenderRequirements,
    *,
    output_dir: str | Path,
    template: BidTemplate | None = None,
    retrieved_chunks: dict[str, list[str]] | None = None,
    company_name: str = DEFAULT_COMPANY_NAME,
    enable_llm_generation: bool = False,
    markdown_name: str | None = None,
    docx_name: str | None = None,
    export_docx: bool = True,
) -> dict[str, str | None]:
    """Generate Markdown and optionally DOCX using production components."""
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    original_get_settings = generator_agent.get_settings
    _configure_generator_runtime(
        company_name=company_name,
        enable_llm_generation=enable_llm_generation,
    )
    try:
        markdown = generator_agent.generate_bid_document(
            requirements,
            retrieved_chunks or {},
            bid_template=template,
        )
    finally:
        generator_agent.get_settings = original_get_settings

    prefix = _safe_prefix(requirements.project_name or "投标文件")
    markdown_path = output_path / (markdown_name or f"{prefix}.md")
    markdown_path.write_text(markdown, encoding="utf-8")

    docx_path: Path | None = None
    if export_docx:
        docx_path = output_path / (
            docx_name
            or build_export_filename(requirements.project_name or "投标文件", suffix="docx")
        )
        markdown_to_docx(
            markdown,
            docx_path,
            title=f"{requirements.project_name or '投标文件'} 投标文件",
            subtitle="技术标及商务标",
            cover=True,
            toc=True,
            header_text=requirements.project_name or "投标文件",
            page_numbers=True,
            metadata={"投标人": company_name},
        )

    return {
        "markdown_path": str(markdown_path),
        "docx_path": str(docx_path) if docx_path else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate sanitized bid Markdown/DOCX from TenderRequirements JSON."
    )
    parser.add_argument(
        "--requirements",
        help="Path to TenderRequirements JSON or project result JSON containing parsed_json",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use sanitized demo requirements instead of a real requirements file",
    )
    parser.add_argument(
        "--template",
        default=str(DEFAULT_TEMPLATE),
        help="BidTemplate JSON path; pass an empty string to disable template loading",
    )
    parser.add_argument(
        "--retrieved-chunks",
        help="Optional JSON object mapping section titles to retrieved text chunks",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for generated files",
    )
    parser.add_argument(
        "--company-name",
        default=DEFAULT_COMPANY_NAME,
        help="Bidder name to render on the cover; default is sanitized",
    )
    parser.add_argument(
        "--markdown-name",
        help="Optional Markdown output filename",
    )
    parser.add_argument(
        "--docx-name",
        help="Optional DOCX output filename",
    )
    parser.add_argument(
        "--no-docx",
        action="store_true",
        help="Only write Markdown",
    )
    parser.add_argument(
        "--enable-llm-generation",
        action="store_true",
        help="Allow generator_agent to call the configured LLM; disabled by default",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    template_arg = args.template.strip() if args.template else ""
    requirements = load_requirements(args.requirements, demo=args.demo)
    template = load_template(template_arg) if template_arg else None
    retrieved_chunks = load_retrieved_chunks(args.retrieved_chunks)

    artifacts = generate_bid_artifacts(
        requirements,
        output_dir=args.output_dir,
        template=template,
        retrieved_chunks=retrieved_chunks,
        company_name=args.company_name,
        enable_llm_generation=args.enable_llm_generation,
        markdown_name=args.markdown_name,
        docx_name=args.docx_name,
        export_docx=not args.no_docx,
    )

    print(json.dumps(artifacts, ensure_ascii=False, indent=2))


def _configure_generator_runtime(
    *,
    company_name: str,
    enable_llm_generation: bool,
) -> None:
    # Keep the CLI independent from .env infrastructure credentials. The
    # generator fallback path only needs these two attributes.
    generator_agent.get_settings = lambda: SimpleNamespace(
        company_name=company_name,
        enable_llm_generation=enable_llm_generation,
    )


def _safe_prefix(value: str) -> str:
    text = re.sub(r"[^\w.\-一-鿿]+", "_", value.strip(), flags=re.UNICODE)
    return text.strip("._") or "投标文件"


if __name__ == "__main__":
    main()
