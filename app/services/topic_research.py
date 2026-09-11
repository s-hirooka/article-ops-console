"""Discover genuinely new article topics for a domain.

GSC only surfaces queries a page already ranks for. To find *uncovered* topics
we expand seed terms via Google Ads' GenerateKeywordIdeas, then subtract:
  * keywords the domain already ranks for (keyword_rank_history)
  * keywords an existing/queued article already targets (articles.target_keyword)
  * single broad head-term keywords (ビッグキーワード) — too competitive for
    a small site, kept to 2+ significant words
and keep those clearing the domain's monthly-search threshold.

One Google Ads API call per run; recorded in api_usage.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.integrations.google_ads_keywords import generate_keyword_ideas
from app.services.text_similarity import bigrams, overlap_score

# Above this character-bigram overlap between a candidate keyword and an
# existing WordPress post title, treat the topic as already covered. Chosen
# from a real case: a genuinely duplicate pair ("賃貸の床の傷｜補修グッズで
# 直せる？" vs the already-published "賃貸のフローリングの傷、自分で直して
# いい？補修グッズ5選比較") scored 0.178, while clearly-adjacent-but-distinct
# pairs on the same site scored 0.036-0.078 — 0.12 sits cleanly between them.
_CANNIBALIZATION_THRESHOLD = 0.12


_PARTICLES = {"の", "を", "に", "は", "が", "で", "と", "も", "や", "へ", "から", "まで"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", "", s).lower()


def _token_key(s: str) -> frozenset[str]:
    """Order-independent identity: {一人暮らし, 食器, 収納} for every word-order
    permutation, so Google Ads' near-duplicate ideas collapse to one."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    toks = [t for t in re.split(r"\s+", s) if t and t not in _PARTICLES]
    return frozenset(toks) if toks else frozenset([_norm(s)])


def _covered_raw(session: Session, account_id: int, domain_id: int) -> list[str]:
    """Every keyword the domain already ranks for (GSC) or has targeted."""
    out = [
        k
        for (k,) in session.execute(
            select(m.KeywordRankHistory.keyword.distinct()).where(
                m.KeywordRankHistory.domain_id == domain_id
            )
        ).all()
        if k
    ]
    out += [
        k
        for (k,) in session.execute(
            select(m.Article.target_keyword.distinct()).where(
                m.Article.domain_id == domain_id,
                m.Article.target_keyword.is_not(None),
            )
        ).all()
        if k
    ]
    return out




def _derive_seeds(session: Session, domain_id: int, domain_key: str) -> list[str]:
    """Seeds for Google Ads' idea service when the caller doesn't supply any.

    Deliberately NOT the top GSC queries themselves: asking for "ideas like
    <a long-tail query we already rank for>" mostly returns near-duplicates
    of that same query, which then all get filtered out as already-covered —
    the auto-discovery flow would return zero candidates almost every time.
    Instead, seed with the significant *tokens* behind those queries (impression-
    weighted), which are broad enough to surface genuinely different themes;
    token-key coverage-matching only excludes an idea that shares the *entire*
    token set with something covered, so a single shared token is harmless.
    """
    rows = session.execute(
        select(
            m.KeywordRankHistory.keyword,
            func.sum(m.KeywordRankHistory.impressions).label("imp"),
        )
        .where(m.KeywordRankHistory.domain_id == domain_id)
        .group_by(m.KeywordRankHistory.keyword)
        .order_by(func.sum(m.KeywordRankHistory.impressions).desc())
        .limit(20)
    ).all()
    if not rows:
        return [domain_key.replace("-", " ")]

    weight: dict[str, int] = {}
    for kw, imp in rows:
        for tok in re.split(r"\s+", unicodedata.normalize("NFKC", kw or "")):
            if len(tok) < 2 or tok in _PARTICLES:
                continue
            weight[tok] = weight.get(tok, 0) + int(imp or 0)
    seeds = [t for t, _ in sorted(weight.items(), key=lambda kv: -kv[1])[:8]]
    return seeds or [domain_key.replace("-", " ")]


def _own_article_titles(session: Session, domain_id: int) -> list[str]:
    """This domain's own articles in the console — including drafts.

    Real gap this closes: a draft that hasn't been published yet has no
    WordPress post (so `_wp_post_titles` can't see it) and its
    `target_keyword` often won't exact/token-match a *new* candidate keyword
    for the same topic (e.g. target_keyword="オフィス" vs a fresh candidate
    "オフィス 365" — different token sets, same real-world topic once written
    up). Checking the actual generated *titles* by bigram overlap catches
    that the way it already catches WordPress-post duplicates.
    """
    return [
        t
        for (t,) in session.execute(
            select(m.Article.title).where(
                m.Article.domain_id == domain_id,
                m.Article.title.is_not(None),
            )
        ).all()
        if t
    ]


def _wp_post_titles(domain: m.Domain) -> list[str]:
    """The domain's published post titles, straight from WordPress — catches
    topics already covered by posts that predate this console (so were never
    written to `articles`) or haven't started ranking yet (so aren't in
    `keyword_rank_history` either). First 100 published posts only; fine for
    now, revisit if a domain's post count grows past that."""
    try:
        from app.integrations.wordpress import WordPressClient
        from app.services.publish import wp_creds_for_domain

        wp = WordPressClient(wp_creds_for_domain(domain))
        posts = wp.list_posts(per_page=100)
    except Exception:
        return []
    return [t for p in posts if (t := (p.get("title") or {}).get("rendered"))]


def _balance_score(c: dict) -> float:
    """Reach vs. difficulty — favors high volume with low competition rather
    than just the highest-volume idea (which is usually also the most
    competitive one)."""
    vol = c.get("avg_monthly_searches") or 0
    idx = c.get("competition_index")
    idx = idx if idx is not None else 50
    return vol / (1 + idx)


def rank_top(candidates: list[dict], limit: int = 10) -> list[dict]:
    """Candidates sorted best-first by the same balance score, capped to
    ``limit`` — the shortlist a human should actually choose from."""
    return sorted(candidates, key=_balance_score, reverse=True)[:limit]


def pick_best(candidates: list[dict]) -> dict | None:
    """A single recommended candidate — the top of `rank_top`."""
    top = rank_top(candidates, limit=1)
    return top[0] if top else None


def discover(
    session: Session,
    *,
    account_id: int,
    domain_id: int,
    seeds: list[str] | None = None,
    page_url: str | None = None,
    limit: int = 25,
) -> dict:
    domain = session.get(m.Domain, domain_id)
    if domain is None or domain.account_id != account_id:
        raise ValueError("domain が見つかりません。")

    seeds = [s.strip() for s in (seeds or []) if s.strip()]
    if not seeds and not page_url:
        seeds = _derive_seeds(session, domain_id, domain.domain_key)

    ideas = generate_keyword_ideas(seeds, page_url=page_url, limit=400)

    covered_raw = _covered_raw(session, account_id, domain_id)
    covered = {_norm(k) for k in covered_raw}
    covered_keys = {_token_key(k) for k in covered_raw}
    threshold = domain.keyword_threshold

    wp_titles = _wp_post_titles(domain)
    own_titles = _own_article_titles(session, domain_id)
    wp_title_bigrams = [bigrams(t) for t in wp_titles + own_titles]

    # keep the best (highest-volume) idea per order-independent token set
    best: dict[frozenset[str], dict] = {}
    cannibalization_excluded = 0
    single_word_excluded = 0
    for idea in ideas:
        vol = idea.avg_monthly_searches or 0
        if vol < threshold:
            continue
        nk = _norm(idea.keyword)
        key = _token_key(idea.keyword)
        # single broad head terms ("本棚", "ラック", "オフィス") draw the
        # biggest, best-established competitors — a small site doesn't win
        # those. Requiring 2+ significant words pushes toward the longer-tail
        # phrases an individual/small-team site actually has a shot at.
        if len(key) < 2:
            single_word_excluded += 1
            continue
        # already ranking / already targeted: exact term, or the same set of
        # significant tokens (word-order / particle variants).
        if not nk or nk in covered or key in covered_keys:
            continue
        # already has dedicated WordPress coverage, even if GSC/articles
        # don't know about it yet (imported content, not-yet-ranking posts)
        idea_bigrams = bigrams(idea.keyword)
        if any(overlap_score(idea_bigrams, tb) >= _CANNIBALIZATION_THRESHOLD
               for tb in wp_title_bigrams):
            cannibalization_excluded += 1
            continue
        cur = best.get(key)
        if cur is None or vol > (cur["avg_monthly_searches"] or 0):
            best[key] = {
                "keyword": idea.keyword,
                "avg_monthly_searches": idea.avg_monthly_searches,
                "competition_level": idea.competition_level,
                "competition_index": idea.competition_index,
            }

    candidates = sorted(
        best.values(),
        key=lambda c: (
            -(c["avg_monthly_searches"] or 0),
            c["competition_index"] if c["competition_index"] is not None else 50,
        ),
    )[:limit]

    _record_api_usage(session, account_id, len(ideas))

    return {
        "domain_id": domain_id,
        "seeds_used": seeds,
        "threshold": threshold,
        "ideas_returned": len(ideas),
        "covered_keywords": len(covered),
        "wp_posts_checked": len(wp_titles),
        "own_drafts_checked": len(own_titles),
        "cannibalization_excluded": cannibalization_excluded,
        "single_word_excluded": single_word_excluded,
        "candidates": candidates,
        "recommended": pick_best(candidates),
        "recommended_top": rank_top(candidates, limit=10),
    }


def _record_api_usage(session: Session, account_id: int, idea_count: int) -> None:
    today = date.today()  # match /api/usage/api (routes_read.usage_api)
    row = session.scalar(
        select(m.ApiUsage).where(
            m.ApiUsage.account_id == account_id,
            m.ApiUsage.provider == "google_ads",
            m.ApiUsage.operation == "keyword_ideas",
            m.ApiUsage.usage_date == today,
        )
    )
    if row:
        row.call_count += 1
        row.meta_json = {**(row.meta_json or {}), "last_idea_count": idea_count}
    else:
        session.add(
            m.ApiUsage(
                account_id=account_id,
                provider="google_ads",
                operation="keyword_ideas",
                call_count=1,
                usage_date=today,
                meta_json={"last_idea_count": idea_count},
            )
        )
    session.flush()
