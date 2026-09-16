"""Job queue + runner.

P2 constraints: Render's free plan has no worker dyno, so jobs run in-process
via FastAPI ``BackgroundTasks``. The ``jobs`` row is the source of truth for
status; a crash mid-run leaves it 'running' and a sweep (P4) can requeue.

``run_job`` reads the job's ``account_id`` with an unscoped session, then does
the real work inside ``tenant_session(account_id)`` so RLS applies.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import SessionLocal, tenant_session
from app.services import prompt_assembly
from app.services.article_pipeline import PipelineError, run_article_generate
from app.services.budget import BudgetExceeded
from app.services.llm import CreditExhaustedError

VALID_KINDS = {
    "article_generate", "rank_sync", "analysis", "eyecatch", "test_prompt",
    "topic_auto_generate", "improve_article",
}

# A job stuck "queued" with no started_at this long never actually got its
# BackgroundTasks callback run — most often a cold-start race, where the
# request that created it lands on a free-tier instance mid-spin-up and the
# scheduled task is silently lost. Confirmed in production 2026-09-15/16:
# two topic_auto_generate jobs created 2.8s apart after a 4h+ idle gap, the
# first stuck at started_at=null forever, the second (landing once the
# instance had finished waking up) ran fine.
_STALE_QUEUE_SECONDS = 90


def enqueue(
    session: Session,
    *,
    account_id: int,
    kind: str,
    params: dict | None = None,
    domain_id: int | None = None,
    created_by: int | None = None,
) -> m.Job:
    if kind not in VALID_KINDS:
        raise ValueError(f"未知のジョブ種別: {kind}")
    job = m.Job(
        id=str(uuid.uuid4()),
        account_id=account_id,
        domain_id=domain_id,
        kind=kind,
        status="queued",
        params_json=params or {},
        created_by=created_by,
    )
    session.add(job)
    session.flush()
    return job


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _flag_credit_exhausted(s: Session, account_id: int) -> None:
    acct = s.get(m.Account, account_id)
    if acct is not None:
        acct.anthropic_credit_exhausted_at = _now()


def requeue_stale(account_id: int) -> list[str]:
    """Opportunistic self-heal, called from the job-listing endpoints (which
    get hit constantly — the dashboard, the jobs page, JobToasts' 8s poll —
    so a stuck job gets noticed within seconds of crossing the threshold,
    not left queued forever). Claims each stale job by stamping started_at
    *before* spawning anything, in the same transaction as the SELECT, so a
    second sweep call landing moments later (plausible given how often this
    runs) can't also claim it and run it twice. Dispatches via a plain
    daemon thread rather than another BackgroundTasks call, since that
    mechanism is what dropped it the first time."""
    with tenant_session(account_id) as s:
        cutoff = _now() - timedelta(seconds=_STALE_QUEUE_SECONDS)
        stale = s.scalars(
            select(m.Job).where(
                m.Job.account_id == account_id,
                m.Job.status == "queued",
                m.Job.started_at.is_(None),
                m.Job.created_at < cutoff,
            )
        ).all()
        job_ids = [j.id for j in stale]
        for j in stale:
            j.status = "running"
            j.started_at = _now()  # claim now; run_job() will overwrite both
        s.flush()

    for job_id in job_ids:
        threading.Thread(target=run_job, args=(job_id, account_id), daemon=True).start()
    return job_ids


def run_job(job_id: str, account_id: int | None = None) -> dict:
    """Run one job to completion. Returns its final state
    ``{status, result, error, llm_cost_usd}`` (also persisted on the row).

    ``account_id`` should be passed by the caller (it already knows it) — the
    jobs table is RLS-guarded, so a lookup without the tenant GUC set sees
    nothing. It is only inferred (superuser-style, dev/SQLite) when omitted.
    """
    if account_id is None:
        with SessionLocal() as bootstrap:
            row = bootstrap.get(m.Job, job_id)
            if row is None:
                return {"status": "missing", "result": None,
                        "error": "job not found (account_id not supplied)",
                        "llm_cost_usd": 0.0}
            account_id = row.account_id

    with tenant_session(int(account_id)) as s:
        job = s.get(m.Job, job_id)
        if job is None or job.status not in ("queued", "running"):
            return {"status": getattr(job, "status", "gone"),
                    "result": getattr(job, "result_json", None),
                    "error": getattr(job, "error", None),
                    "llm_cost_usd": float(getattr(job, "llm_cost_usd", 0) or 0)}
        job.status = "running"
        job.started_at = _now()
        s.flush()

        try:
            result = _dispatch(s, job)
            job.result_json = result
            job.status = "succeeded"
        except (PipelineError, BudgetExceeded, ValueError, RuntimeError) as exc:
            # RuntimeError covers NoGoogleConnection / GscError / PublishError /
            # WordPressError — all carry a user-readable message.
            job.status = "failed"
            job.error = str(exc)
            if isinstance(exc, CreditExhaustedError):
                _flag_credit_exhausted(s, job.account_id)
        except Exception as exc:  # pragma: no cover - unexpected
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}"
        finally:
            job.finished_at = _now()

        return {
            "status": job.status,
            "result": job.result_json,
            "error": job.error,
            "llm_cost_usd": float(job.llm_cost_usd or 0),
        }


def _dispatch(s: Session, job: m.Job) -> dict:
    p = job.params_json or {}
    if job.kind == "article_generate":
        res = run_article_generate(
            s,
            account_id=job.account_id,
            domain_id=job.domain_id or int(p["domain_id"]),
            target_keyword=p["target_keyword"],
            created_by=job.created_by,
            job_id=job.id,
            search_volume=p.get("search_volume"),
            force_below_threshold=bool(p.get("force")),
            extra_instructions=p.get("extra_instructions", ""),
        )
        job.llm_cost_usd = res.cost_usd
        return {
            "article_id": res.article_id,
            "title": res.title,
            "slug": res.slug,
            "model": res.model,
            "cost_usd": res.cost_usd,
            "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens,
            "faked": res.faked,
            "search_volume": res.search_volume,
            "keyword_threshold": res.keyword_threshold,
            "eyecatch_bytes": res.eyecatch_bytes,
            "warnings": res.warnings,
        }

    if job.kind == "topic_auto_generate":
        from app.services import topic_research

        domain_id = job.domain_id or int(p["domain_id"])
        count = max(1, min(int(p.get("count") or 1), 20))
        articles: list[dict] = []
        errors: list[str] = []
        total_cost = 0.0
        # Re-runs discover() fresh each iteration (rather than picking N
        # candidates from one discover() call) so each pick sees the
        # previous iteration's newly-created article as "already covered" —
        # otherwise back-to-back generations for the same domain could pick
        # the same keyword twice.
        for i in range(count):
            try:
                discovery = topic_research.discover(
                    s,
                    account_id=job.account_id,
                    domain_id=domain_id,
                    seeds=p.get("seeds") or [],
                    page_url=p.get("page_url"),
                )
                best = discovery.get("recommended")
                if best is None:
                    errors.append(f"{i + 1}件目: 新規テーマの候補が見つかりませんでした。")
                    break
                res = run_article_generate(
                    s,
                    account_id=job.account_id,
                    domain_id=domain_id,
                    target_keyword=best["keyword"],
                    created_by=job.created_by,
                    job_id=job.id,
                    search_volume=best.get("avg_monthly_searches"),
                )
                total_cost += res.cost_usd
                articles.append({
                    "selected_keyword": best,
                    "article_id": res.article_id,
                    "title": res.title,
                    "slug": res.slug,
                    "cost_usd": res.cost_usd,
                    "faked": res.faked,
                    "warnings": res.warnings,
                })
            except (PipelineError, BudgetExceeded, RuntimeError) as exc:
                errors.append(f"{i + 1}件目: {exc}")
                if isinstance(exc, CreditExhaustedError):
                    _flag_credit_exhausted(s, job.account_id)
                break
        job.llm_cost_usd = total_cost
        if not articles and errors:
            raise PipelineError("; ".join(errors))
        return {
            "requested_count": count,
            "created_count": len(articles),
            "articles": articles,
            "errors": errors,
            "cost_usd": total_cost,
        }

    if job.kind == "improve_article":
        from app.services.article_improve import ImproveError, run_improve

        domain_id = job.domain_id or int(p["domain_id"])
        try:
            res = run_improve(
                s,
                account_id=job.account_id,
                domain_id=domain_id,
                url=p["url"],
                keyword=p["keyword"],
                action_hint=p.get("action_hint", "rewrite"),
                job_id=job.id,
            )
        except ImproveError as exc:
            raise PipelineError(str(exc)) from exc
        job.llm_cost_usd = res["cost_usd"]
        return res

    if job.kind == "test_prompt":
        domain_id = job.domain_id or int(p["domain_id"])
        a = prompt_assembly.assemble(s, domain_id)
        return {
            "domain_id": domain_id,
            "system_preview": a.system[:1200],
            "system_chars": len(a.system),
            "versions": a.versions,
            "keyword_threshold": a.keyword_threshold,
        }

    if job.kind == "rank_sync":
        from app.services.rank_sync import run_rank_sync

        return run_rank_sync(
            s,
            account_id=job.account_id,
            domain_id=job.domain_id or int(p["domain_id"]),
            start_date=p.get("start_date"),
            end_date=p.get("end_date"),
        )

    if job.kind == "analysis":
        from app.services.analysis import run_analysis

        return run_analysis(
            s,
            account_id=job.account_id,
            domain_id=job.domain_id or int(p["domain_id"]),
        )

    if job.kind == "eyecatch":
        from app.services.eyecatch_render import render_banner

        png = render_banner(p.get("title", "記事"), p.get("style", {}))
        return {"bytes": len(png)}

    raise ValueError(f"dispatch 未対応: {job.kind}")
