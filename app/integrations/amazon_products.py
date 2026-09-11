"""Amazon Creators API (successor to Product Advertising API / PA-API).

Wraps `python-amazon-paapi` (importable as ``amazon_creatorsapi``), which
handles the OAuth2 client-credentials exchange and request signing. Verified
live 2026-09 against real credentials — see app/services/product_fill.py for
how this replaces LLM-invented (fake) ASINs in generated articles.

Credentials come from the Amazon Associates Central → Creators API console:
CREDENTIAL_ID / CREDENTIAL_SECRET (a Login-with-Amazon style OAuth client,
*not* the old AWS-style access/secret key), the API VERSION shown there
(region-specific, e.g. "3.3" = Far East / JP), and the PARTNER_TAG (tracking
ID). ``AMAZON_FAKE=1`` returns a synthetic result so tests run offline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class AmazonProductsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Product:
    asin: str
    title: str
    url: str                 # detail page URL, tag already applied
    image_url: str | None
    price_yen: int | None    # whole yen; None if unavailable


def _settings() -> dict:
    cid = os.environ.get("AMAZON_CREDENTIAL_ID", "").strip()
    secret = os.environ.get("AMAZON_CREDENTIAL_SECRET", "").strip()
    tag = os.environ.get("AMAZON_PARTNER_TAG", "").strip()
    version = os.environ.get("AMAZON_API_VERSION", "3.3").strip()
    country = os.environ.get("AMAZON_COUNTRY", "JP").strip().upper()
    if not (cid and secret and tag):
        raise AmazonProductsError(
            "AMAZON_CREDENTIAL_ID / AMAZON_CREDENTIAL_SECRET / AMAZON_PARTNER_TAG "
            "が未設定です（Amazon アソシエイト・セントラル → Creators API）。"
        )
    return {"credential_id": cid, "credential_secret": secret, "version": version,
            "tag": tag, "country": country}


def _fake_search(keywords: str, limit: int) -> list[Product]:
    slug = "".join(ch for ch in keywords if ch.isalnum())[:10] or "item"
    tag = os.environ.get("AMAZON_PARTNER_TAG", "swork_seo-22")
    return [
        Product(
            asin=f"B0FAKE{i:04d}",
            title=f"{keywords}（テスト商品{i}）",
            url=f"https://www.amazon.co.jp/dp/B0FAKE{i:04d}?tag={tag}",
            image_url=f"https://example.com/fake/{slug}-{i}.jpg",
            price_yen=1000 * (i + 1),
        )
        for i in range(min(limit, 3))
    ]


def search_products(keywords: str, limit: int = 3) -> list[Product]:
    """Real products for a keyword, ranked by Amazon's own relevance/sort."""
    if os.environ.get("AMAZON_FAKE") == "1":
        return _fake_search(keywords, limit)

    from amazon_creatorsapi import AmazonCreatorsApi, Country
    from amazon_creatorsapi.models import SearchItemsResource

    cfg = _settings()
    try:
        country = getattr(Country, cfg["country"])
    except AttributeError:
        raise AmazonProductsError(f"未対応の国コード: {cfg['country']}")

    api = AmazonCreatorsApi(
        credential_id=cfg["credential_id"],
        credential_secret=cfg["credential_secret"],
        version=cfg["version"],
        tag=cfg["tag"],
        country=country,
    )
    try:
        result = api.search_items(
            keywords=keywords,
            item_count=max(1, min(limit, 10)),
            resources=[
                SearchItemsResource.ITEM_INFO_DOT_TITLE,
                SearchItemsResource.IMAGES_DOT_PRIMARY_DOT_LARGE,
                SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_PRICE,
            ],
        )
    except Exception as exc:  # library raises its own error types
        raise AmazonProductsError(f"Amazon 商品検索に失敗しました: {exc}") from exc

    out: list[Product] = []
    for item in result.items or []:
        title = None
        if item.item_info and item.item_info.title:
            title = item.item_info.title.display_value
        image = None
        if item.images and item.images.primary and item.images.primary.large:
            image = item.images.primary.large.url
        price = None
        try:
            price = int(round(item.offers_v2.listings[0].price.money.amount))
        except Exception:
            pass
        out.append(
            Product(
                asin=item.asin,
                title=title or keywords,
                url=item.detail_page_url,
                image_url=image,
                price_yen=price,
            )
        )
    return out
