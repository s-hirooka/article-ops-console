"""Lightweight Japanese text similarity — no embeddings, no extra API calls.

Character-bigram Jaccard overlap. Japanese isn't space-delimited, so word-level
overlap needs tokenization (MeCab/janome, not available here); bigrams need
nothing and are good enough to catch "same topic, different phrasing" cases
(shared by internal_link_fill.py's related-article matching and
topic_research.py's cannibalization check).
"""
from __future__ import annotations

import re
import unicodedata

_STRIP = re.compile(r"[|｜・:：,、。!?！？()（）\[\]【】\s\-—/]+")


def bigrams(text: str) -> set[str]:
    t = unicodedata.normalize("NFKC", text or "")
    t = _STRIP.sub("", t)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i : i + 2] for i in range(len(t) - 1)}


def overlap_score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
