"""AI budget enforcement (spec §04「AI予算」).

Four layers; this module owns layers 1-2 (the ones the app enforces):

  1. account monthly budget   — Σ llm_usage.cost_usd for the period vs
     accounts.llm_monthly_budget_usd. action 'block' refuses; 'warn' proceeds
     with a flag.
  2. per-job ceiling          — accounts.llm_job_ceiling_usd caps a single job,
     checked against the pre-flight estimate and again against actual spend.
  3. BYOK                      — a per-domain / per-account Anthropic key means
     spend lands on the customer's own Anthropic bill (handled in llm.py).
  4. Anthropic Console hard limit — external backstop the owner sets; documented,
     not enforced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m


class BudgetExceeded(RuntimeError):
    def __init__(self, message: str, *, layer: str):
        super().__init__(message)
        self.layer = layer


@dataclass(frozen=True)
class BudgetStatus:
    period: str
    spent_usd: float
    budget_usd: float
    job_ceiling_usd: float
    action: str            # 'block' | 'warn'
    est_job_usd: float
    would_exceed_monthly: bool
    warning: str | None


def _period(when: date | None = None) -> str:
    return (when or date.today()).strftime("%Y-%m")


def month_to_date_spend(session: Session, account_id: int, period: str | None = None) -> float:
    period = period or _period()
    total = session.scalar(
        select(func.coalesce(func.sum(m.LlmUsage.cost_usd), 0)).where(
            m.LlmUsage.account_id == account_id,
            m.LlmUsage.billing_period == period,
        )
    )
    return float(total or 0)


def precheck(
    session: Session,
    account_id: int,
    est_job_usd: float,
    *,
    period: str | None = None,
) -> BudgetStatus:
    """Call before starting an LLM job. Raises BudgetExceeded when a hard limit
    would be broken; otherwise returns a status (possibly carrying a warning)."""
    period = period or _period()
    acct = session.get(m.Account, account_id)
    if acct is None:
        raise BudgetExceeded("account が存在しません。", layer="account")

    budget = float(acct.llm_monthly_budget_usd)
    ceiling = float(acct.llm_job_ceiling_usd)
    action = acct.llm_budget_action
    spent = month_to_date_spend(session, account_id, period)
    would_exceed = (spent + est_job_usd) > budget

    if est_job_usd > ceiling:
        raise BudgetExceeded(
            f"この処理の見積り ${est_job_usd:.2f} が1ジョブ上限 ${ceiling:.2f} を超えています。",
            layer="job_ceiling",
        )
    if would_exceed and action == "block":
        raise BudgetExceeded(
            f"今月の消費 ${spent:.2f} + 見積り ${est_job_usd:.2f} が "
            f"月間予算 ${budget:.2f} を超えます（動作: block）。",
            layer="monthly",
        )

    warning = None
    if would_exceed and action == "warn":
        warning = (
            f"月間予算 ${budget:.2f} を超過見込み"
            f"（消費 ${spent:.2f} + 見積り ${est_job_usd:.2f}）。"
        )

    return BudgetStatus(
        period=period,
        spent_usd=round(spent, 4),
        budget_usd=budget,
        job_ceiling_usd=ceiling,
        action=action,
        est_job_usd=round(est_job_usd, 4),
        would_exceed_monthly=would_exceed,
        warning=warning,
    )


def record_usage(
    session: Session,
    *,
    account_id: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_usd: float,
    domain_id: int | None = None,
    job_id: str | None = None,
    period: str | None = None,
) -> m.LlmUsage:
    row = m.LlmUsage(
        account_id=account_id,
        domain_id=domain_id,
        job_id=job_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost_usd,
        billing_period=period or _period(),
    )
    session.add(row)
    return row


def enforce_job_ceiling(session: Session, account_id: int, actual_job_usd: float) -> None:
    """Post-hoc check: a job that blew its ceiling is recorded but flagged."""
    acct = session.get(m.Account, account_id)
    if acct and actual_job_usd > float(acct.llm_job_ceiling_usd):
        raise BudgetExceeded(
            f"実コスト ${actual_job_usd:.2f} が1ジョブ上限 "
            f"${float(acct.llm_job_ceiling_usd):.2f} を超過しました。",
            layer="job_ceiling",
        )
