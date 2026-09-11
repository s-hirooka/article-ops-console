"""Execute one "次の打ち手" (improvement) recommendation with AI.

Takes a candidate from GET /domains/{id}/recommendations — keyword, the
page's URL, and an action_hint (ctr / rewrite / weak / review) — and:

  1. Finds the matching `articles` row, importing one from WordPress first
     if the page predates the console (written before this app existed, so
     was never tracked — the common case for real recommendation targets,
     since those are pages that already rank).
  2. Asks Claude to revise it — two different shapes depending on
     action_hint, not one prompt asked to sometimes skip a field:
       - "ctr" (already ranks well, needs a better click): a title/meta-only
         call (generate_title_revision — a tool with no body_html property
         at all). body_html is left exactly as-is in code, never round-
         tripped through the model. Earlier this asked generate_draft() to
         "leave body_html unchanged" and just echo it back — the model
         sometimes omitted the (required) field instead of echoing 10,000+
         characters back verbatim, crashing the parse (seen in production
         as a bare KeyError). Not asking for it removes the failure mode.
       - "rewrite"/"weak" (needs to move up first): the full generate_draft()
         pass — same tool-use structured output fresh generation uses — via
         DraftRequest.extra_instructions carrying the current content plus
         a revision brief.
  3. For a body_html-changing revision, runs the same product-token /
     internal-link auto-fill fresh generation gets, so it can't regress to
     placeholder gaps. Skipped for a title-only revision (nothing changed).
  4. Updates the row and republishes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.integrations.wordpress import WordPressClient, WordPressError
from app.services import budget, prompt_assembly
from app.services.article_pipeline import resolve_byok_key
from app.services.internal_link_fill import fill_related_links
from app.services.llm import DraftRequest, generate_draft, generate_title_revision
from app.services.pricing import estimate_article_cost
from app.services.product_fill import fill_products
from app.services.publish import PublishError, publish_article, wp_creds_for_domain


class ImproveError(RuntimeError):
    pass


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def _find_or_import(
    session: Session, *, account_id: int, domain_id: int, domain: m.Domain, url: str
) -> m.Article:
    slug = _slug_from_url(url)
    if slug:
        art = session.scalar(
            select(m.Article).where(
                m.Article.account_id == account_id,
                m.Article.domain_id == domain_id,
                m.Article.slug == slug,
            )
        )
        if art is not None:
            return art

    # every article this console has ever published also carries its live
    # link in meta_json — check that too, independent of slug drift
    for art in session.scalars(
        select(m.Article).where(
            m.Article.account_id == account_id,
            m.Article.domain_id == domain_id,
            m.Article.wp_post_id.is_not(None),
        )
    ):
        if (art.meta_json or {}).get("wp_link") == url:
            return art

    if not slug:
        raise ImproveError(f"URLからスラッグを取得できません: {url}")

    client = WordPressClient(wp_creds_for_domain(domain))
    try:
        post = client.find_post_by_slug(slug)
    except WordPressError as exc:
        raise ImproveError(f"WordPress からの取得に失敗しました: {exc}") from exc
    if post is None:
        raise ImproveError(f"WordPress に該当記事が見つかりません（slug={slug}）。")

    art = m.Article(
        account_id=account_id,
        domain_id=domain_id,
        wp_post_id=post.get("id"),
        status="published",
        title=(post.get("title") or {}).get("rendered"),
        slug=slug,
        body_html=(post.get("content") or {}).get("rendered") or "",
        meta_json={"wp_link": post.get("link"), "imported": True},
    )
    session.add(art)
    session.flush()
    return art


def run_improve(
    session: Session,
    *,
    account_id: int,
    domain_id: int,
    url: str,
    keyword: str,
    action_hint: str,
    job_id: str | None = None,
) -> dict:
    domain = session.get(m.Domain, domain_id)
    if domain is None or domain.account_id != account_id:
        raise ImproveError("domain が見つかりません。")

    art = _find_or_import(
        session, account_id=account_id, domain_id=domain_id, domain=domain, url=url
    )
    # snapshot the pre-edit state — nothing else keeps a revision history, so
    # this is what lets a later "did it help?" view show a real before/after
    # instead of just the after
    title_before = art.title
    meta_description_before = (art.meta_json or {}).get("meta_description")

    assembled = prompt_assembly.assemble(session, domain_id)
    acct = session.get(m.Account, account_id)
    model = (acct.draft_model if acct else None) or "claude-sonnet-5"

    est = estimate_article_cost(model)
    precheck = budget.precheck(session, account_id, est)
    warnings: list[str] = [precheck.warning] if precheck.warning else []

    byok = resolve_byok_key(domain)

    if action_hint == "ctr":
        extra = (
            "この記事は既に検索順位が良好（10位前後）ですが、クリック率が低いと"
            f"見られます。タイトルとメタディスクリプションだけを「{keyword}」という"
            "検索語に対してより具体的でクリックされやすい表現に改善してください。\n\n"
            f"--- 既存タイトル ---\n{art.title or ''}\n\n"
            f"--- 本文冒頭（参考。変更対象ではない） ---\n{(art.body_html or '')[:2000]}"
        )
        rev = generate_title_revision(
            DraftRequest(system=assembled.system, target_keyword=keyword,
                         extra_instructions=extra),
            model=model, api_key=byok,
        )
        cost_usd, faked = rev.cost_usd, rev.faked
        budget.record_usage(
            session, account_id=account_id, domain_id=domain_id, job_id=job_id,
            model=rev.model, input_tokens=rev.input_tokens, output_tokens=rev.output_tokens,
            cache_read_tokens=rev.cache_read_tokens, cache_write_tokens=rev.cache_write_tokens,
            cost_usd=rev.cost_usd,
        )
        art.title = rev.title
        # body_html deliberately untouched — nothing to re-fill/re-check
        meta = dict(art.meta_json or {})
        meta["meta_description"] = rev.meta_description
    else:
        extra = (
            f"この記事はまだ「{keyword}」で十分な順位が取れていません。既存本文の"
            "良い部分は活かしつつ、このキーワードに対する網羅性・具体性を高めて"
            "内容を拡充・再構成してください。見出し構成を見直して情報を追加しても"
            "構いません。\n\n--- 既存タイトル ---\n"
            f"{art.title or ''}\n\n--- 既存本文(body_html) ---\n{art.body_html or ''}\n\n"
            "上記を踏まえた改訂後の記事全体を submit_draft で提出してください。"
        )
        draft = generate_draft(
            DraftRequest(system=assembled.system, target_keyword=keyword,
                         vc_auto_ads_defaults=assembled.vc_auto_ads_defaults,
                         extra_instructions=extra),
            model=model, api_key=byok,
            # extra headroom beyond generate_draft's own default: this
            # embeds the *entire existing article* as context on top of the
            # revision brief, so both input and expected output run larger
            # than a fresh-generation draft.
            max_tokens=28000,
        )
        cost_usd, faked = draft.cost_usd, draft.faked
        budget.record_usage(
            session, account_id=account_id, domain_id=domain_id, job_id=job_id,
            model=draft.model, input_tokens=draft.input_tokens, output_tokens=draft.output_tokens,
            cache_read_tokens=draft.cache_read_tokens, cache_write_tokens=draft.cache_write_tokens,
            cost_usd=draft.cost_usd,
        )

        body_html = draft.body_html
        try:
            fill = fill_products(body_html)
            body_html = fill.html
            if fill.unresolved:
                warnings.append(
                    "商品が見つからなかった検索語があります（公開前に本文を確認）: "
                    + "、".join(fill.unresolved)
                )
        except Exception as exc:
            warnings.append(f"Amazon 商品自動挿入に失敗しました（プレースホルダーのまま）: {exc}")

        try:
            wp = WordPressClient(wp_creds_for_domain(domain))
            related = fill_related_links(
                body_html, wp=wp, topic_text=f"{draft.title} {keyword}",
                exclude_post_id=art.wp_post_id,
            )
            body_html = related.html
            if related.slots_left_empty:
                warnings.append(
                    f"あわせて読みたい: 一致する関連記事が見つからない枠が"
                    f"{related.slots_left_empty}件あります（公開前に本文を確認）。"
                )
        except Exception as exc:
            warnings.append(f"関連記事の自動リンク付けに失敗しました（プレースホルダーのまま）: {exc}")

        art.title = draft.title
        art.body_html = body_html
        meta = dict(art.meta_json or {})
        meta["meta_description"] = draft.meta_description

    try:
        budget.enforce_job_ceiling(session, account_id, cost_usd)
    except budget.BudgetExceeded as exc:
        warnings.append(str(exc))

    meta["warnings"] = warnings
    meta["improved_for_keyword"] = keyword
    meta["improve_action_hint"] = action_hint
    # a running log on the article itself — app/services/improve_history.py
    # reads this list to build the before/after view without needing to
    # reconstruct it from job rows
    history = list(meta.get("improve_history") or [])
    history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "keyword": keyword,
        "action_hint": action_hint,
        "title_before": title_before,
        "title_after": art.title,
        "meta_description_before": meta_description_before,
        "meta_description_after": meta.get("meta_description"),
        "body_changed": action_hint != "ctr",
        "cost_usd": cost_usd,
    })
    meta["improve_history"] = history[-20:]  # cap growth on a heavily-iterated article
    art.meta_json = meta
    session.flush()

    try:
        pub = publish_article(session, account_id=account_id, article_id=art.id, status="publish")
    except PublishError as exc:
        raise ImproveError(str(exc)) from exc

    return {
        "article_id": art.id,
        "title": art.title,
        "title_before": title_before,
        "keyword": keyword,
        "action_hint": action_hint,
        "cost_usd": cost_usd,
        "faked": faked,
        "warnings": warnings,
        "wp_link": pub.get("link"),
    }
