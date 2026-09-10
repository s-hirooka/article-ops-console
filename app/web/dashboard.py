"""Server-rendered read-only dashboard (P2).

Minimal, styled, no build step — a holding surface until the Next.js frontend
(spec §08) lands. Reads through the same tenant session as the API.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db
from app.config import AppSettings
from app.db import models as m

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_settings = AppSettings.from_env()


def _aid(s: Session) -> int:
    return int(s.info["account_id"])


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(db)) -> HTMLResponse:
    aid = _aid(session)
    account = session.get(m.Account, aid)
    domains = session.scalars(
        select(m.Domain).where(m.Domain.account_id == aid).order_by(m.Domain.domain_key)
    ).all()

    period = date.today().strftime("%Y-%m")
    spent = float(
        session.scalar(
            select(func.coalesce(func.sum(m.LlmUsage.cost_usd), 0)).where(
                m.LlmUsage.account_id == aid, m.LlmUsage.billing_period == period
            )
        )
        or 0
    )

    cards = []
    for d in domains:
        arts = session.scalar(
            select(func.count()).select_from(m.Article).where(m.Article.domain_id == d.id)
        )
        last_sync = session.scalar(
            select(func.max(m.KeywordRankHistory.metric_date)).where(
                m.KeywordRankHistory.domain_id == d.id
            )
        )
        open_alerts = session.scalar(
            select(func.count())
            .select_from(m.RankAlert)
            .where(
                m.RankAlert.domain_id == d.id,
                m.RankAlert.detected_date >= date.today() - timedelta(days=30),
            )
        )
        cards.append(
            {
                "d": d,
                "articles": arts or 0,
                "last_sync": last_sync,
                "open_alerts": open_alerts or 0,
            }
        )

    jobs = session.scalars(
        select(m.Job).where(m.Job.account_id == aid).order_by(m.Job.created_at.desc()).limit(8)
    ).all()

    budget = float(account.llm_monthly_budget_usd) if account else 0.0
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "app_name": _settings.app_name,
            "account": account,
            "cards": cards,
            "jobs": jobs,
            "period": period,
            "spent": round(spent, 2),
            "budget": round(budget, 2),
            "budget_pct": round(100 * spent / budget) if budget else 0,
        },
    )


@router.get("/domains/{domain_id}", response_class=HTMLResponse)
def domain_detail(
    domain_id: int, request: Request, session: Session = Depends(db)
) -> HTMLResponse:
    aid = _aid(session)
    d = session.get(m.Domain, domain_id)
    if d is None or d.account_id != aid:
        return HTMLResponse("<h1>404</h1><p>domain が見つかりません。</p>", status_code=404)

    latest_day = session.scalar(
        select(func.max(m.OpportunityScore.score_date)).where(
            m.OpportunityScore.domain_id == domain_id
        )
    )
    opportunities = (
        session.scalars(
            select(m.OpportunityScore)
            .where(
                m.OpportunityScore.domain_id == domain_id,
                m.OpportunityScore.score_date == latest_day,
            )
            .order_by(m.OpportunityScore.score.desc())
            .limit(15)
        ).all()
        if latest_day
        else []
    )
    alerts = session.scalars(
        select(m.RankAlert)
        .where(
            m.RankAlert.domain_id == domain_id,
            m.RankAlert.detected_date >= date.today() - timedelta(days=30),
        )
        .order_by(m.RankAlert.detected_date.desc())
        .limit(20)
    ).all()
    arts = session.scalars(
        select(m.Article)
        .where(m.Article.domain_id == domain_id)
        .order_by(m.Article.created_at.desc())
        .limit(20)
    ).all()
    prompt_versions = dict(
        session.execute(
            select(m.DomainPrompt.component, func.max(m.DomainPrompt.version))
            .where(m.DomainPrompt.domain_id == domain_id)
            .group_by(m.DomainPrompt.component)
        ).all()
    )

    return templates.TemplateResponse(
        request,
        "domain.html",
        {
            "app_name": _settings.app_name,
            "d": d,
            "opportunities": opportunities,
            "alerts": alerts,
            "articles": arts,
            "prompt_versions": prompt_versions,
            "latest_day": latest_day,
        },
    )
