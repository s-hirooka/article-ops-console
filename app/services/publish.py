"""Publish a draft article to WordPress (spec §06 final step, made explicit).

Draft -> live post. Re-renders the eyecatch from (title, style), uploads it as
media, sets it as the featured image, then creates (or updates) the post.
Writes ``wp_post_id`` / ``eyecatch_url`` / ``status='published'`` back.

Needs the domain's WordPress credentials (``wp_base_url`` / ``wp_username`` /
``wp_app_password_enc``). ``WP_FAKE=1`` bypasses the real API.
"""
from __future__ import annotations

import os
import re

from sqlalchemy.orm import Session

from app.db import models as m
from app.integrations.wordpress import WordPressClient, WordPressCreds, WordPressError
from app.services.eyecatch_render import render_banner


class PublishError(RuntimeError):
    pass


def wp_creds_for_domain(domain: m.Domain) -> WordPressCreds:
    if os.environ.get("WP_FAKE") == "1":
        return WordPressCreds(domain.wp_base_url or domain.base_url, "fake", "fake")
    if not (domain.wp_base_url and domain.wp_username and domain.wp_app_password_enc):
        raise PublishError(
            "この domain に WordPress 認証情報が設定されていません。"
        )
    try:
        from app.security.crypto import decrypt

        pw = decrypt(domain.wp_app_password_enc)
    except Exception as exc:
        raise PublishError(f"WordPress パスワードの復号に失敗しました: {exc}") from exc
    return WordPressCreds(domain.wp_base_url, domain.wp_username, pw)


def publish_article(
    session: Session,
    *,
    account_id: int,
    article_id: int,
    status: str = "publish",
) -> dict:
    art = session.get(m.Article, article_id)
    if art is None or art.account_id != account_id:
        raise PublishError("article が見つかりません。")
    # No "already published" guard: wp_post_id existing means this always takes
    # the update_post path below, so re-running is exactly how you push an
    # edited body_html (e.g. corrected links) to the live post, or move a
    # published post back to draft.

    body = art.body_html or ""
    if status == "publish" and "[[PRODUCT_" in body:
        raise PublishError(
            "本文に未処理の商品トークン（[[PRODUCT_...]]）が残っています。生成時に"
            "Amazon商品検索が失敗した可能性があります。公開前に本文を確認してください"
            "（下書き保存は可能です）。"
        )
    if status == "publish" and "<!-- product not found" in body:
        raise PublishError(
            "本文に「商品が見つかりませんでした」の未解決箇所が残っています。AIは実在の"
            "商品URL/ASINを生成できないため、公開前に本文中の該当箇所を実在の商品リンクに"
            "手動で置き換えてください（下書き保存は可能です）。"
        )
    if status == "publish" and "product_slot" in body:
        raise PublishError(
            "本文に旧形式の商品プレースホルダー（product_slot）が残っています。"
            "「Amazon商品を自動挿入」を再実行するか、本文を手動で修正してください"
            "（下書き保存は可能です）。"
        )
    if status == "publish" and "[[RELATED_ARTICLE" in body:
        raise PublishError(
            "本文に未処理の関連記事トークン（[[RELATED_ARTICLE...]]）が残っています。"
            "「Amazon商品を自動挿入」を再実行するか、本文を手動で修正してください"
            "（下書き保存は可能です）。"
        )
    if status == "publish" and re.search(r"<li>\s*<!--", body):
        raise PublishError(
            "本文の「あわせて読みたい」に、リンクのない未解決の箇所（コメントのみの"
            "<li>）が残っています。「Amazon商品を自動挿入」を再実行するか、本文を"
            "手動で修正してください（下書き保存は可能です）。"
        )

    domain = session.get(m.Domain, art.domain_id)
    if domain is None:
        raise PublishError("domain が見つかりません。")

    client = WordPressClient(wp_creds_for_domain(domain))
    meta = dict(art.meta_json or {})
    style = {}
    # domain's eyecatch_style prompt component, if any
    try:
        from app.services.prompt_assembly import assemble

        style = assemble(session, domain.id).eyecatch_style
    except Exception:
        pass

    featured_media = None
    eyecatch_url = art.eyecatch_url
    try:
        png = render_banner(art.title or art.target_keyword or "記事", style)
        slug = art.slug or re.sub(r"[^a-z0-9-]+", "-", (art.title or "eyecatch").lower())
        media = client.upload_media_bytes(png, f"{slug[:60] or 'eyecatch'}.png")
        featured_media = media.get("id")
        eyecatch_url = media.get("source_url") or eyecatch_url
    except (WordPressError, OSError) as exc:
        meta.setdefault("warnings", []).append(f"アイキャッチのアップロード失敗: {exc}")

    try:
        if art.wp_post_id:
            resp = client.update_post(
                art.wp_post_id,
                title=art.title,
                content=art.body_html or "",
                status=status,
                **({"featured_media": featured_media} if featured_media else {}),
            )
        else:
            resp = client.create_post(
                title=art.title or "（無題）",
                content=art.body_html or "",
                slug=art.slug or None,
                status=status,
                featured_media=featured_media,
            )
    except WordPressError as exc:
        detail = f": {exc.body[:400]}" if getattr(exc, "body", None) else ""
        hint = ""
        if exc.status_code == 403:
            hint = (
                " ｜ 403 はサーバー側の拒否です。日本の共有ホスティングの"
                "「国外IPアクセス制限」やセキュリティプラグイン(WAF)が REST API の"
                "書き込みを海外(Render)からブロックしている可能性が高いです。"
                "国外IP制限を解除するか、/wp-json/ を除外設定してください。"
            )
        raise PublishError(
            f"WordPress への投稿に失敗しました ({exc.status_code}){detail}{hint}"
        ) from exc

    art.wp_post_id = int(resp.get("id") or art.wp_post_id or 0) or None
    art.eyecatch_url = eyecatch_url
    art.status = "published" if status == "publish" else "draft"
    if art.status == "published":
        from datetime import datetime, timezone

        art.published_at = datetime.now(timezone.utc)
    meta["wp_link"] = resp.get("link")
    art.meta_json = meta
    session.flush()

    return {
        "article_id": art.id,
        "wp_post_id": art.wp_post_id,
        "link": resp.get("link"),
        "status": art.status,
        "featured_media": featured_media,
        "eyecatch_url": art.eyecatch_url,
        "warnings": meta.get("warnings", []),
    }


def delete_article(
    session: Session,
    *,
    account_id: int,
    article_id: int,
    trash_wp: bool = False,
) -> dict:
    """Delete the local article row. If it has a WordPress post: move that post
    to draft by default, or to the trash when ``trash_wp`` is set."""
    art = session.get(m.Article, article_id)
    if art is None or art.account_id != account_id:
        raise PublishError("article が見つかりません。")

    wp_action = "none"
    warnings: list[str] = []
    if art.wp_post_id:
        domain = session.get(m.Domain, art.domain_id)
        try:
            client = WordPressClient(wp_creds_for_domain(domain)) if domain else None
            if client is None:
                warnings.append("domain 不明のため WordPress 側は未変更。")
            elif trash_wp:
                client.trash_post(art.wp_post_id)
                wp_action = "trashed"
            else:
                client.update_post(art.wp_post_id, status="draft")
                wp_action = "set_to_draft"
        except (PublishError, WordPressError) as exc:
            warnings.append(f"WordPress 側の処理に失敗（投稿は残っています）: {exc}")

    wp_post_id = art.wp_post_id
    session.delete(art)
    session.flush()
    return {
        "deleted": True,
        "article_id": article_id,
        "wp_post_id": wp_post_id,
        "wp_action": wp_action,
        "warnings": warnings,
    }
