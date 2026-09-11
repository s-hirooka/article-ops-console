"""Fill `[[PRODUCT_*:keyword]]` tokens in generated body_html with real Amazon
products (Creators API), so the LLM never has to invent an ASIN.

The model is instructed (see scripts/seed_domain_prompts.py, lifehouse2026) to
emit three token forms wherever a product should appear:

    [[PRODUCT_TITLE:<search phrase>]]   -> <a href="...">商品名</a>
    [[PRODUCT_PRICE:<search phrase>]]   -> "¥1,836〜" (or a not-found note)
    [[PRODUCT_BLOCK:<search phrase>]]   -> full image+link+"Amazonで詳細を見る" block

All tokens sharing the same search phrase resolve to the same product (one
Amazon API call per unique phrase, not per token). A phrase that returns no
results is left as an HTML comment noting the miss, and the caller can see it
in `unresolved` to decide whether to block publish.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.integrations.amazon_products import AmazonProductsError, Product, search_products

_TOKEN_RE = re.compile(r"\[\[PRODUCT_(TITLE|PRICE|BLOCK):([^\]]+)\]\]")


@dataclass
class FillResult:
    html: str
    filled: list[str] = field(default_factory=list)      # search phrases resolved
    unresolved: list[str] = field(default_factory=list)   # search phrases with no hits


def _price_text(p: Product) -> str:
    return f"¥{p.price_yen:,}〜" if p.price_yen else "価格は商品ページでご確認ください"


def _block_html(p: Product) -> str:
    img = (
        f'<figure class="wp-block-image size-full" style="width:250px;margin:0 auto;">'
        f'<a href="{p.url}" target="_blank" rel="nofollow noopener sponsored">'
        f'<img src="{p.image_url}" alt="{p.title}" /></a></figure>'
        if p.image_url
        else ""
    )
    link = (
        f'<p><a href="{p.url}" target="_blank" rel="nofollow noopener sponsored">'
        f"Amazonで詳細を見る →</a></p>"
    )
    return img + "\n" + link


def fill_products(html: str, *, limit_per_lookup: int = 1) -> FillResult:
    phrases = {m.group(2).strip() for m in _TOKEN_RE.finditer(html)}
    cache: dict[str, Product | None] = {}
    filled: list[str] = []
    unresolved: list[str] = []

    for phrase in phrases:
        try:
            hits = search_products(phrase, limit=limit_per_lookup)
        except AmazonProductsError:
            hits = []
        if hits:
            cache[phrase] = hits[0]
            filled.append(phrase)
        else:
            cache[phrase] = None
            unresolved.append(phrase)

    def _sub(m: re.Match) -> str:
        kind, phrase = m.group(1), m.group(2).strip()
        p = cache.get(phrase)
        if p is None:
            return f"<!-- product not found for “{phrase}” -->"
        if kind == "TITLE":
            return f'<a href="{p.url}" target="_blank" rel="nofollow noopener sponsored">{p.title}</a>'
        if kind == "PRICE":
            return _price_text(p)
        return _block_html(p)  # BLOCK

    return FillResult(html=_TOKEN_RE.sub(_sub, html), filled=filled, unresolved=unresolved)
