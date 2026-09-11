"""Article generation pipeline (spec §06).

    load domain + assembled prompt
      -> keyword-volume gate (google-ads; threshold from the domain's prompts)
      -> budget pre-check (spec §04 layers 1-2)
      -> LLM draft (anthropic, or fake offline)
      -> record llm_usage + cost, post-hoc ceiling check
      -> eyecatch render (non-fatal)
      -> write articles row (status='draft')

Publishing to WordPress is a separate, explicit step (P3 publish endpoint) so a
draft can be reviewed first.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db import models as m
from app.services import budget, prompt_assembly
from app.services.llm import DraftRequest, generate_draft
from app.services.pricing import estimate_article_cost
from app.services.product_fill import fill_products


class PipelineError(RuntimeError):
    pass


@dataclass
class ArticleResult:
    article_id: int
    title: str
    slug: str
    model: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    faked: bool
    search_volume: int | None
    keyword_threshold: int
    eyecatch_bytes: int
    warnings: list[str] = field(default_factory=list)


def _resolve_byok(domain: m.Domain) -> str | None:
    if not domain.anthropic_api_key_enc:
        return None
    try:
        from app.security.crypto import decrypt

        return decrypt(domain.anthropic_api_key_enc)
    except Exception:
        return None


def _lookup_volume(keyword: str) -> int | None:
    if os.environ.get("LLM_FAKE") == "1":
        return None
    try:
        from app.integrations.google_ads_keywords import fetch_historical_metrics

        rows = fetch_historical_metrics([keyword])
        for r in rows:
            if r.avg_monthly_searches is not None:
                return int(r.avg_monthly_searches)
    except Exception:
        return None
    return None


def _render_eyecatch(style: dict, title: str) -> int:
    """Byte length of the rendered banner, or 0 on failure. Same renderer the
    publish step uses, so the draft's size preview matches what gets uploaded.
    Deliberately defensive — a Pillow hiccup must not fail generation."""
    try:
        from app.services.eyecatch_render import render_banner

        return len(render_banner(title, style))
    except Exception:
        return 0


def run_article_generate(
    session: Session,
    *,
    account_id: int,
    domain_id: int,
    target_keyword: str,
    created_by: int | None = None,
    job_id: str | None = None,
    search_volume: int | None = None,
    force_below_threshold: bool = False,
    extra_instructions: str = "",
) -> ArticleResult:
    domain = session.get(m.Domain, domain_id)
    if domain is None or domain.account_id != account_id:
        raise PipelineError("domain が見つかりません（またはアカウント不一致）。")

    assembled = prompt_assembly.assemble(session, domain_id)
    warnings: list[str] = []

    volume = search_volume if search_volume is not None else _lookup_volume(target_keyword)
    if volume is None:
        warnings.append("月間検索数を取得できませんでした（閾値チェックをスキップ）。")
    elif volume < assembled.keyword_threshold and not force_below_threshold:
        raise PipelineError(
            f"「{target_keyword}」の月間検索数 {volume} が閾値 "
            f"{assembled.keyword_threshold} 未満です。force で上書きできます。"
        )

    acct = session.get(m.Account, account_id)
    model = (acct.draft_model if acct else None) or "claude-sonnet-5"

    est = estimate_article_cost(model)
    status = budget.precheck(session, account_id, est)
    if status.warning:
        warnings.append(status.warning)

    byok = _resolve_byok(domain)
    draft = generate_draft(
        DraftRequest(
            system=assembled.system,
            target_keyword=target_keyword,
            search_volume=volume,
            vc_auto_ads_defaults=assembled.vc_auto_ads_defaults,
            extra_instructions=extra_instructions,
        ),
        model=model,
        api_key=byok,
    )

    budget.record_usage(
        session,
        account_id=account_id,
        domain_id=domain_id,
        job_id=job_id,
        model=draft.model,
        input_tokens=draft.input_tokens,
        output_tokens=draft.output_tokens,
        cache_read_tokens=draft.cache_read_tokens,
        cache_write_tokens=draft.cache_write_tokens,
        cost_usd=draft.cost_usd,
    )
    try:
        budget.enforce_job_ceiling(session, account_id, draft.cost_usd)
    except budget.BudgetExceeded as exc:
        warnings.append(str(exc))

    eyecatch_bytes = _render_eyecatch(assembled.eyecatch_style, draft.title)

    # Replace [[PRODUCT_*:検索語]] tokens (see product_block_spec prompt) with
    # real Amazon products via the Creators API — the LLM never invents an
    # ASIN. A phrase with no hit is left as an HTML comment and flagged below
    # so the publish guard can catch it before it goes live with a gap.
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

    article = m.Article(
        account_id=account_id,
        domain_id=domain_id,
        job_id=job_id,
        status="draft",
        target_keyword=target_keyword,
        target_search_volume=volume,
        title=draft.title,
        slug=draft.slug,
        body_html=body_html,
        eyecatch_url=None,
        meta_json={
            "meta_description": draft.meta_description,
            "outline": draft.outline,
            "prompt_versions": assembled.versions,
            "faked": draft.faked,
            "eyecatch_bytes": eyecatch_bytes,
            "warnings": warnings,
        },
    )
    session.add(article)
    session.flush()

    return ArticleResult(
        article_id=article.id,
        title=draft.title,
        slug=draft.slug,
        model=draft.model,
        cost_usd=draft.cost_usd,
        input_tokens=draft.input_tokens,
        output_tokens=draft.output_tokens,
        faked=draft.faked,
        search_volume=volume,
        keyword_threshold=assembled.keyword_threshold,
        eyecatch_bytes=eyecatch_bytes,
        warnings=warnings,
    )
