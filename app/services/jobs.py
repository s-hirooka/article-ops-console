"""Job queue + runner.

P2 constraints: Render's free plan has no worker dyno, so jobs run in-process
via FastAPI ``BackgroundTasks``. The ``jobs`` row is the source of truth for
status; a crash mid-run leaves it 'running' and a sweep (P4) can requeue.

``run_job`` reads the job's ``account_id`` with an unscoped session, then does
the real work inside ``tenant_session(account_id)`` so RLS applies.
"""
from __future__ import annotations

import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import SessionLocal, tenant_session
from app.services import prompt_assembly
from app.services.article_pipeline import PipelineError, run_article_generate
from app.services.budget import BudgetExceeded

VALID_KINDS = {"article_generate", "rank_sync", "analysis", "eyecatch", "test_prompt"}


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


def run_job(job_id: str) -> None:
    with SessionLocal() as bootstrap:
        row = bootstrap.get(m.Job, job_id)
        if row is None:
            return
        account_id = row.account_id

    with tenant_session(account_id) as s:
        job = s.get(m.Job, job_id)
        if job is None or job.status not in ("queued", "running"):
            return
        job.status = "running"
        job.started_at = _now()
        s.flush()

        try:
            result = _dispatch(s, job)
            job.result_json = result
            job.status = "succeeded"
        except (PipelineError, BudgetExceeded, ValueError) as exc:
            job.status = "failed"
            job.error = str(exc)
        except Exception as exc:  # pragma: no cover - unexpected
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}"
        finally:
            job.finished_at = _now()


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

    if job.kind in ("rank_sync", "analysis", "eyecatch"):
        return {"note": f"{job.kind}: RankPulse 連携は P4 で実装予定（現状はno-op）。"}

    raise ValueError(f"dispatch 未対応: {job.kind}")
