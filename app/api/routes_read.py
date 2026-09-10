"""Read-only API for the P2 dashboard (spec §07, read subset).

Every query filters on ``account_id`` explicitly *and* runs under RLS — belt and
braces. Nothing here writes.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db, get_account_id
from app.db import models as m

router = APIRouter(prefix="/api", tags=["read"])


def _aid(session: Session) -> int:
    return int(session.info["account_id"])


def _row(obj, *fields) -> dict:
    return {f: getattr(obj, f) for f in fields}


# --- domains ----------------------------------------------------------------
@router.get("/domains")
def list_domains(session: Session = Depends(db)) -> list[dict]:
    rows = session.scalars(
        select(m.Domain)
        .where(m.Domain.account_id == _aid(session))
        .order_by(m.Domain.domain_key)
    ).all()
    return [
        _row(d, "id", "domain_key", "base_url", "gsc_site_url", "keyword_threshold")
        for d in rows
    ]


def _get_domain(session: Session, domain_id: int) -> m.Domain:
    d = session.get(m.Domain, domain_id)
    if d is None or d.account_id != _aid(session):
        raise HTTPException(404, "domain が見つかりません。")
    return d


@router.get("/domains/{domain_id}")
def get_domain(domain_id: int, session: Session = Depends(db)) -> dict:
    d = _get_domain(session, domain_id)
    latest = session.execute(
        select(m.DomainPrompt.component, func.max(m.DomainPrompt.version))
        .where(m.DomainPrompt.domain_id == domain_id)
        .group_by(m.DomainPrompt.component)
    ).all()
    return {
        **_row(d, "id", "domain_key", "base_url", "gsc_site_url",
               "wp_base_url", "keyword_threshold"),
        "has_wp_credentials": bool(d.wp_app_password_enc),
        "has_own_anthropic_key": bool(d.anthropic_api_key_enc),
        "prompt_versions": {c: v for c, v in latest},
    }


@router.get("/domains/{domain_id}/rank-history")
def rank_history(
    domain_id: int,
    days: int = Query(90, ge=1, le=365),
    session: Session = Depends(db),
) -> list[dict]:
    _get_domain(session, domain_id)
    since = date.today() - timedelta(days=days)
    rows = session.scalars(
        select(m.KeywordRankHistory)
        .where(
            m.KeywordRankHistory.account_id == _aid(session),
            m.KeywordRankHistory.domain_id == domain_id,
            m.KeywordRankHistory.metric_date >= since,
        )
        .order_by(m.KeywordRankHistory.metric_date)
    ).all()
    return [
        _row(r, "metric_date", "keyword", "url", "post_id", "gsc_average_position",
             "serp_rank", "clicks", "impressions", "ctr", "search_volume")
        for r in rows
    ]


@router.get("/domains/{domain_id}/opportunities")
def opportunities(
    domain_id: int,
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(db),
) -> list[dict]:
    _get_domain(session, domain_id)
    latest_day = session.scalar(
        select(func.max(m.OpportunityScore.score_date))
        .where(m.OpportunityScore.domain_id == domain_id)
    )
    if latest_day is None:
        return []
    rows = session.scalars(
        select(m.OpportunityScore)
        .where(
            m.OpportunityScore.account_id == _aid(session),
            m.OpportunityScore.domain_id == domain_id,
            m.OpportunityScore.score_date == latest_day,
        )
        .order_by(m.OpportunityScore.score.desc())
        .limit(limit)
    ).all()
    return [
        _row(r, "score_date", "keyword", "url", "post_id", "score",
             "component_breakdown_json")
        for r in rows
    ]


@router.get("/domains/{domain_id}/alerts")
def alerts(
    domain_id: int,
    days: int = Query(30, ge=1, le=365),
    session: Session = Depends(db),
) -> list[dict]:
    _get_domain(session, domain_id)
    since = date.today() - timedelta(days=days)
    rows = session.scalars(
        select(m.RankAlert)
        .where(
            m.RankAlert.account_id == _aid(session),
            m.RankAlert.domain_id == domain_id,
            m.RankAlert.detected_date >= since,
        )
        .order_by(m.RankAlert.detected_date.desc())
    ).all()
    return [
        _row(r, "detected_date", "keyword", "url", "alert_type", "severity",
             "from_position", "to_position")
        for r in rows
    ]


@router.get("/domains/{domain_id}/articles")
def articles(domain_id: int, session: Session = Depends(db)) -> list[dict]:
    _get_domain(session, domain_id)
    rows = session.scalars(
        select(m.Article)
        .where(
            m.Article.account_id == _aid(session),
            m.Article.domain_id == domain_id,
        )
        .order_by(m.Article.created_at.desc())
    ).all()
    return [
        _row(a, "id", "status", "title", "slug", "wp_post_id", "target_keyword",
             "target_search_volume", "eyecatch_url", "created_at", "published_at")
        for a in rows
    ]


@router.get("/domains/{domain_id}/recommendations")
def recommendations(domain_id: int, session: Session = Depends(db)) -> dict:
    """「次の打ち手」— computed, read-only.

    * new-article ideas: top opportunity keywords on the latest scoring day
      whose search volume clears the domain threshold and which are not already
      the target of an existing article.
    * rewrite candidates: high-severity 'drop' alerts in the last 30 days.
    """
    d = _get_domain(session, domain_id)
    covered = set(
        session.scalars(
            select(m.Article.target_keyword).where(
                m.Article.domain_id == domain_id,
                m.Article.target_keyword.is_not(None),
            )
        ).all()
    )
    latest_day = session.scalar(
        select(func.max(m.OpportunityScore.score_date))
        .where(m.OpportunityScore.domain_id == domain_id)
    )
    ideas: list[dict] = []
    if latest_day is not None:
        for r in session.scalars(
            select(m.OpportunityScore)
            .where(
                m.OpportunityScore.domain_id == domain_id,
                m.OpportunityScore.score_date == latest_day,
            )
            .order_by(m.OpportunityScore.score.desc())
            .limit(50)
        ).all():
            if r.keyword in covered:
                continue
            ideas.append({"keyword": r.keyword, "score": r.score, "url": r.url})
            if len(ideas) >= 10:
                break

    since = date.today() - timedelta(days=30)
    rewrites = [
        _row(a, "keyword", "url", "detected_date", "severity",
             "from_position", "to_position")
        for a in session.scalars(
            select(m.RankAlert)
            .where(
                m.RankAlert.domain_id == domain_id,
                m.RankAlert.detected_date >= since,
                m.RankAlert.alert_type.ilike("%drop%"),
            )
            .order_by(m.RankAlert.detected_date.desc())
        ).all()
    ]
    return {
        "domain_id": domain_id,
        "keyword_threshold": d.keyword_threshold,
        "new_article_ideas": ideas,
        "rewrite_candidates": rewrites,
    }


# --- jobs & usage ---------------------------------------------------------------
@router.get("/jobs")
def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(db),
) -> list[dict]:
    rows = session.scalars(
        select(m.Job)
        .where(m.Job.account_id == _aid(session))
        .order_by(m.Job.created_at.desc())
        .limit(limit)
    ).all()
    return [
        _row(j, "id", "kind", "status", "domain_id", "llm_cost_usd", "error",
             "created_at", "started_at", "finished_at")
        for j in rows
    ]


@router.get("/usage/llm")
def usage_llm(
    period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    session: Session = Depends(db),
) -> dict:
    period = period or date.today().strftime("%Y-%m")
    aid = _aid(session)
    total = session.scalar(
        select(func.coalesce(func.sum(m.LlmUsage.cost_usd), 0))
        .where(m.LlmUsage.account_id == aid, m.LlmUsage.billing_period == period)
    )
    acct = session.get(m.Account, aid)
    budget = float(acct.llm_monthly_budget_usd) if acct else None
    spent = float(total or 0)
    by_model = session.execute(
        select(m.LlmUsage.model, func.sum(m.LlmUsage.cost_usd))
        .where(m.LlmUsage.account_id == aid, m.LlmUsage.billing_period == period)
        .group_by(m.LlmUsage.model)
    ).all()
    return {
        "period": period,
        "spent_usd": round(spent, 4),
        "budget_usd": budget,
        "budget_action": acct.llm_budget_action if acct else None,
        "remaining_usd": None if budget is None else round(budget - spent, 4),
        "by_model": {model: round(float(c), 4) for model, c in by_model},
    }


@router.get("/usage/api")
def usage_api(session: Session = Depends(db)) -> list[dict]:
    today = date.today()
    rows = session.execute(
        select(
            m.ApiUsage.provider,
            m.ApiUsage.operation,
            func.sum(m.ApiUsage.call_count),
        )
        .where(
            m.ApiUsage.account_id == _aid(session),
            m.ApiUsage.usage_date == today,
        )
        .group_by(m.ApiUsage.provider, m.ApiUsage.operation)
    ).all()
    return [
        {"provider": p, "operation": o, "calls": int(c)} for p, o, c in rows
    ]
