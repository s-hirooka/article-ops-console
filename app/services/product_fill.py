"""Fill `[[PRODUCT_*:keyword]]` tokens in generated body_html with real Amazon
products (Creators API), so the LLM never has to invent an ASIN.

The model is instructed (see scripts/seed_domain_prompts.py, lifehouse2026) to
emit three token forms wherever a product should appear:

    [[PRODUCT_TITLE:<search phrase>]]   -> <a href="...">商品名</a>
    [[PRODUCT_PRICE:<search phrase>]]   -> "¥1,836〜" (or a not-found note)
    [[PRODUCT_BLOCK:<search phrase>]]   -> full image+link+"Amazonで詳細を見る" block

All tokens sharing the same search phrase resolve to the same product (one
Amazon API call per unique phrase, not per token). A phrase that returns no
results is left as an HTML comment noting the miss (with its token kind, so
a later retry can render it correctly), and the caller can see it in
`unresolved` to decide whether to block publish. That marker is itself
retriable — re-running fill_products (e.g. via the "fill-products" endpoint)
searches it again rather than treating "not found" as final, since a miss is
often a transient search failure, not a real absence of the product.

Also understands the older ``<!-- product_slot: 商品カテゴリ="..." ... -->
<p>[プレースホルダー]</p>`` format (seeded on Neon before this token design
existed) and fills it the same way, as a real Amazon block — so articles
already generated against that prompt version (or generated later if the
prompt hasn't been re-seeded yet) still get real links instead of sitting
with a permanent placeholder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db import models as m
from app.integrations.amazon_products import AmazonProductsError, Product, search_products


class ProductFillError(RuntimeError):
    pass

_TOKEN_RE = re.compile(r"\[\[PRODUCT_(TITLE|PRICE|BLOCK):([^\]]+)\]\]")
_LEGACY_RE = re.compile(
    r'<!--\s*product_slot:.*?商品カテゴリ="([^"]*)".*?-->\s*'
    r"<p>\[この商品ブロックは公開前に実在の商品情報に差し替えてください\]</p>",
    re.S,
)
# A previous run's "not found" marker. Kept retriable (kind embedded) rather
# than a dead end — an Amazon search failure is often transient (network
# blip, cold start), and "再実行" should actually be able to recover it
# instead of always re-reporting the same miss.
_NOTFOUND_RE = re.compile(
    r"<!-- product not found \((TITLE|PRICE|BLOCK)\) for “([^”]+)” -->"
)


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


def _render(kind: str, p: Product) -> str:
    if kind == "TITLE":
        return f'<a href="{p.url}" target="_blank" rel="nofollow noopener sponsored">{p.title}</a>'
    if kind == "PRICE":
        return _price_text(p)
    return _block_html(p)  # BLOCK


def fill_products(html: str, *, limit_per_lookup: int = 1) -> FillResult:
    phrases = {m.group(2).strip() for m in _TOKEN_RE.finditer(html)}
    phrases |= {m.group(1).strip() for m in _LEGACY_RE.finditer(html)}
    phrases |= {m.group(2).strip() for m in _NOTFOUND_RE.finditer(html)}
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

    def _sub_token(m: re.Match) -> str:
        kind, phrase = m.group(1), m.group(2).strip()
        p = cache.get(phrase)
        if p is None:
            return f"<!-- product not found ({kind}) for “{phrase}” -->"
        return _render(kind, p)

    def _sub_legacy(m: re.Match) -> str:
        phrase = m.group(1).strip()
        p = cache.get(phrase)
        if p is None:
            return f"<!-- product not found (BLOCK) for “{phrase}” -->"
        return _block_html(p)

    def _sub_notfound(m: re.Match) -> str:
        kind, phrase = m.group(1), m.group(2).strip()
        p = cache.get(phrase)
        if p is None:
            return m.group(0)  # still not found — leave the marker as-is
        return _render(kind, p)

    html = _LEGACY_RE.sub(_sub_legacy, html)
    html = _TOKEN_RE.sub(_sub_token, html)
    html = _NOTFOUND_RE.sub(_sub_notfound, html)
    return FillResult(html=html, filled=filled, unresolved=unresolved)


def edit_article(
    session: Session,
    *,
    account_id: int,
    article_id: int,
    body_html: str | None = None,
    title: str | None = None,
    meta_description: str | None = None,
) -> dict:
    """Manual edit of an already-generated article (e.g. hand-fixing a section
    the automated product fill couldn't resolve). Local-only change — call the
    publish endpoint separately to push it to WordPress."""
    art = session.get(m.Article, article_id)
    if art is None or art.account_id != account_id:
        raise ProductFillError("article が見つかりません。")

    if body_html is not None:
        art.body_html = body_html
    if title is not None:
        art.title = title
    if meta_description is not None:
        meta = dict(art.meta_json or {})
        meta["meta_description"] = meta_description
        art.meta_json = meta
    session.flush()
    return {"article_id": art.id, "updated": True}


def refill_article(session: Session, *, account_id: int, article_id: int) -> dict:
    """Re-run product-token AND related-article-link resolution against an
    existing article's current body_html and save the result. For an article
    stuck with placeholders — generated before these features existed,
    generated while Amazon search or the WordPress lookup was down, or still
    carrying legacy product_slot / freeform-comment placeholders because the
    domain's prompts haven't been re-seeded to the token format yet."""
    art = session.get(m.Article, article_id)
    if art is None or art.account_id != account_id:
        raise ProductFillError("article が見つかりません。")

    before = art.body_html or ""
    result = fill_products(before)
    body = result.html
    related_linked: list[str] = []
    related_empty = 0

    domain = session.get(m.Domain, art.domain_id)
    if domain is not None:
        try:
            from app.integrations.wordpress import WordPressClient
            from app.services.internal_link_fill import fill_related_links
            from app.services.publish import wp_creds_for_domain

            wp = WordPressClient(wp_creds_for_domain(domain))
            related = fill_related_links(
                body,
                wp=wp,
                topic_text=f"{art.title or ''} {art.target_keyword or ''}",
                exclude_post_id=art.wp_post_id,
            )
            body = related.html
            related_linked = related.linked
            related_empty = related.slots_left_empty
        except Exception:
            pass

    art.body_html = body
    meta = dict(art.meta_json or {})
    warnings = [
        w
        for w in meta.get("warnings", [])
        if "商品が見つからなかった検索語" not in w and "あわせて読みたい" not in w
    ]
    if result.unresolved:
        warnings.append(
            "商品が見つからなかった検索語があります（公開前に本文を確認）: "
            + "、".join(result.unresolved)
        )
    if related_empty:
        warnings.append(
            f"あわせて読みたい: 一致する関連記事が見つからない枠が{related_empty}件あります"
            "（公開前に本文を確認）。"
        )
    meta["warnings"] = warnings
    art.meta_json = meta
    session.flush()

    return {
        "article_id": art.id,
        "changed": body != before,
        "filled": result.filled,
        "unresolved": result.unresolved,
        "related_linked": related_linked,
        "related_slots_left_empty": related_empty,
    }
