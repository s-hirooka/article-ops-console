"""Fill the "あわせて読みたい" related-articles list with real, already-published
WordPress posts.

Same root problem as Amazon ASINs (see product_fill.py): the LLM cannot know
a real permalink any more than it can know a real ASIN, so
``internal_link_policy`` tells it to leave the list as an unresolved
placeholder rather than invent a date/slug. This step does the real lookup —
fetches the domain's published posts once and picks the most relevant ones
for this article's topic.

Understands two placeholder shapes:
  - ``<li>[[RELATED_ARTICLE]]</li>`` (or ``[[RELATED_ARTICLE:topic hint]]``) —
    the token form domain prompts should move to.
  - ``<li>...an HTML comment and nothing else...</li>`` — what the prompt
    version currently live on lifehouse2026/comfortablelivinglab actually
    produces (freeform wording, no fixed token), caught as a best-effort
    fallback so this works before every domain is re-seeded to the token form.

Matching is a lightweight character-bigram overlap between each candidate
post's title and the target article's own title/keyword — no embeddings, no
extra API calls beyond one WordPress post listing per article.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.integrations.wordpress import WordPressClient

_TOKEN_RE = re.compile(r"<li>\s*\[\[RELATED_ARTICLE(?::([^\]]*))?\]\]\s*</li>")
_LEGACY_RE = re.compile(r"<li>\s*<!--.*?-->\s*</li>", re.S)
_STRIP = re.compile(r"[|｜・:：,、。！？!?()（）\[\]【】\s\-—/]+")


def _bigrams(text: str) -> set[str]:
    t = unicodedata.normalize("NFKC", text or "")
    t = _STRIP.sub("", t)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class RelatedFillResult:
    html: str
    linked: list[str] = field(default_factory=list)      # titles actually used
    slots_left_empty: int = 0                             # no relevant match found


def fill_related_links(
    html: str,
    *,
    wp: WordPressClient,
    topic_text: str,
    exclude_post_id: int | None = None,
    max_links: int = 3,
) -> RelatedFillResult:
    slots = len(_TOKEN_RE.findall(html)) + len(_LEGACY_RE.findall(html))
    if slots == 0:
        return RelatedFillResult(html=html)

    try:
        posts = wp.list_posts(per_page=100, exclude=exclude_post_id)
    except Exception:
        posts = []

    topic_bigrams = _bigrams(topic_text)
    scored: list[tuple[float, str, str]] = []
    for p in posts:
        title = (p.get("title") or {}).get("rendered") or ""
        link = p.get("link")
        if not link or not title:
            continue
        scored.append((_score(topic_bigrams, _bigrams(title)), title, link))
    scored.sort(key=lambda row: row[0], reverse=True)
    picks = [(title, link) for score, title, link in scored[:max_links] if score > 0]

    used = 0

    def _sub(_m: re.Match) -> str:
        nonlocal used
        if used < len(picks):
            title, link = picks[used]
            used += 1
            return f'<li><a href="{link}">{title}</a></li>'
        return "<!-- 関連記事なし（自動リンク付けで一致する記事が見つかりませんでした） -->"

    html = _TOKEN_RE.sub(_sub, html)
    html = _LEGACY_RE.sub(_sub, html)

    return RelatedFillResult(
        html=html,
        linked=[title for title, _ in picks[:used]],
        slots_left_empty=max(slots - used, 0),
    )
