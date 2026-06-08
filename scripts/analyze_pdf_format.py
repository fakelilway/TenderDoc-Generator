#!/usr/bin/env python3
"""Analyze font, size, color, and sample text styles in a PDF.

Usage:
    python scripts/analyze_pdf_format.py /path/to/bid.pdf \
      --out-json data/pdf_format_analysis.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def is_bold(fontname: str) -> bool:
    """Heuristic: PDF font names often encode weight in the font name."""
    bold_keywords = ("Bold", "Heavy", "Black", "ExtBold", "Semibold", "Demi", "Hei")
    font_lower = fontname.lower()
    return any(keyword.lower() in font_lower for keyword in bold_keywords)


def is_italic(fontname: str) -> bool:
    italic_keywords = ("Italic", "Oblique", "Kursiv")
    font_lower = fontname.lower()
    return any(keyword.lower() in font_lower for keyword in italic_keywords)


def color_int_to_hex(color_value: int) -> str:
    red = (color_value >> 16) & 0xFF
    green = (color_value >> 8) & 0xFF
    blue = color_value & 0xFF
    return f"#{red:02X}{green:02X}{blue:02X}"


def analyze_pdf_format(
    pdf_path: str | Path,
    *,
    max_pages: int = 0,
    sample_limit: int = 5,
) -> dict[str, Any]:
    """Return a structured summary of text styles used by a PDF."""
    try:
        import fitz  # PyMuPDF
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "PyMuPDF is required for PDF format analysis. Install backend requirements "
            "or run: pip install PyMuPDF"
        ) from error

    path = Path(pdf_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {path}")

    style_stats: dict[tuple[str, float, bool, bool, str], dict[str, Any]] = defaultdict(
        lambda: {"span_count": 0, "total_chars": 0, "samples": [], "pages": set()}
    )

    with fitz.open(path) as document:
        total_pages = document.page_count
        pages_to_process = min(total_pages, max_pages) if max_pages > 0 else total_pages

        for page_index in range(pages_to_process):
            page = document[page_index]
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue

                        fontname = span.get("font", "Unknown")
                        size = round(float(span.get("size", 0)), 1)
                        bold = is_bold(fontname)
                        italic = is_italic(fontname)
                        color_hex = color_int_to_hex(int(span.get("color", 0)))
                        key = (fontname, size, bold, italic, color_hex)

                        stats = style_stats[key]
                        stats["span_count"] += 1
                        stats["total_chars"] += len(text)
                        stats["pages"].add(page_index + 1)
                        if len(stats["samples"]) < sample_limit:
                            stats["samples"].append(_sanitize_sample(text))

    styles = []
    for (font, size, bold, italic, color), stats in sorted(
        style_stats.items(),
        key=lambda item: item[1]["total_chars"],
        reverse=True,
    ):
        styles.append(
            {
                "font": font,
                "size": size,
                "bold": bold,
                "italic": italic,
                "color": color,
                "span_count": stats["span_count"],
                "total_chars": stats["total_chars"],
                "pages": sorted(stats["pages"]),
                "samples": stats["samples"],
            }
        )

    return {
        "source_file": str(path),
        "total_pages": total_pages,
        "processed_pages": pages_to_process,
        "unique_styles": len(styles),
        "styles": styles,
    }


def print_markdown_summary(report: dict[str, Any], *, limit: int = 30) -> None:
    print(f"Source: {report['source_file']}")
    print(f"Processed {report['processed_pages']}/{report['total_pages']} pages")
    print(f"Found {report['unique_styles']} unique text styles\n")
    print("| # | Font | Size | Bold | Italic | Color | Spans | Chars | Pages | Sample |")
    print("|---|------|------|------|--------|-------|-------|-------|-------|--------|")
    for index, style in enumerate(report["styles"][:limit], start=1):
        pages = style["pages"]
        page_text = (
            f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0]) if pages else "-"
        )
        font_short = style["font"].split("+")[-1][:30]
        sample = style["samples"][0] if style["samples"] else "-"
        print(
            "| {index} | {font} | {size}pt | {bold} | {italic} | {color} | "
            "{spans} | {chars} | {pages} | {sample} |".format(
                index=index,
                font=font_short,
                size=style["size"],
                bold="Y" if style["bold"] else "",
                italic="Y" if style["italic"] else "",
                color=style["color"],
                spans=style["span_count"],
                chars=style["total_chars"],
                pages=page_text,
                sample=sample[:60].replace("|", "/"),
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze text formatting styles in a PDF bid/tender document."
    )
    parser.add_argument("pdf_path", help="PDF file to analyze")
    parser.add_argument(
        "--out-json",
        help="Optional path for the structured JSON report",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Limit pages for quick analysis; 0 means all pages",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=5,
        help="Maximum sample snippets kept per style",
    )
    parser.add_argument(
        "--table-limit",
        type=int,
        default=30,
        help="Maximum styles printed in the console summary",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = analyze_pdf_format(
        args.pdf_path,
        max_pages=args.max_pages,
        sample_limit=args.sample_limit,
    )

    print_markdown_summary(report, limit=args.table_limit)

    if args.out_json:
        output_path = Path(args.out_json).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON report saved: {output_path}")


def _sanitize_sample(text: str) -> str:
    return " ".join(text.split())[:120]


if __name__ == "__main__":
    main()
