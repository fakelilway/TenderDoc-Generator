"""Shared keyword extraction for matching requirements against bid markdown."""

from __future__ import annotations

import re


TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}")


def extract_keywords(
    text: str,
    stopwords: frozenset[str] = frozenset(),
    limit: int = 8,
) -> list[str]:
    """Return up to ``limit`` CJK/alphanumeric tokens (2+ chars) from ``text``.

    ``stopwords`` are dropped before the limit is applied. May return an empty
    list; callers decide their own fallback.
    """
    tokens = TOKEN_PATTERN.findall(text)
    return [token for token in tokens if token not in stopwords][:limit]
