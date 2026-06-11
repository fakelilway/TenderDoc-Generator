from __future__ import annotations

from dataclasses import dataclass


DEFAULT_FORBIDDEN_PHRASES = (
    "系统不自动",
    "本部分仅生成",
    "真实投标模板要求",
    "真实投标模板",
    "由用户填写",
    "由造价人员填写",
    "由造价人员",
    "由项目技术负责人复核填写",
    "由项目技术负责人按最终施工部署复核填写",
    "AI",
    "RAG",
    "prompt",
    "metadata",
    "资料名称：",
    "图片用途：",
)


@dataclass(frozen=True)
class ToneFinding:
    phrase: str
    line_number: int
    line: str


def find_forbidden_tone(
    markdown: str,
    forbidden_phrases: tuple[str, ...] = DEFAULT_FORBIDDEN_PHRASES,
) -> list[ToneFinding]:
    findings: list[ToneFinding] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        for phrase in forbidden_phrases:
            if phrase and phrase in line:
                findings.append(
                    ToneFinding(phrase=phrase, line_number=line_number, line=line)
                )
    return findings


def line_has_forbidden_tone(
    line: str,
    forbidden_phrases: tuple[str, ...] = DEFAULT_FORBIDDEN_PHRASES,
) -> bool:
    return any(phrase and phrase in line for phrase in forbidden_phrases)
