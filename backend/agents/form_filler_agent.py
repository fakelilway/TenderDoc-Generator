"""V2-M3 Form Filler Agent — auto-fill company info into format skeleton fields.

Design principle: fill known fields from company profile, leave unknowns as ________.
No LLM — this is a deterministic data-binding layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class FilledField:
    """A field that was recognized and filled (or left blank)."""
    label: str        # e.g. "投标人", "法定代表人", "项目经理"
    raw_text: str     # e.g. "（盖单位章）"
    matched: bool     # True if filled from profile
    value: str        # filled value or "________"


@dataclass
class FillResult:
    """Result of filling one section/template."""
    title: str
    raw_template: str
    filled_template: str
    fields: list[FilledField]
    missing: list[str]  # labels that couldn't be filled


# ── Field pattern matching ──────────────────────────────────────────────

# patterns: (regex to find in template, label, profile_key)
def generate_missing_checklist(results: list[FillResult]) -> list[str]:
    """Generate a human-readable missing-materials checklist."""
    all_missing: list[str] = []
    for r in results:
        if r.missing:
            all_missing.extend(f"【{r.title}】缺失: {', '.join(r.missing)}")

    if not all_missing:
        return ["所有已知字段已填写完毕。"]

    return all_missing
