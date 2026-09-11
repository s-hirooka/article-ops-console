"""Scheduled sync trigger (spec §手順8), called by .github/workflows/rank_sync.yml.

Render's free plan has no cron/worker dyno, so GitHub Actions is the
scheduler: a nightly workflow POSTs here with a shared-secret bearer token.
This just runs rank_sync then analysis, as real tracked jobs (same code path
as a manual run from the dashboard), for every domain under the single dev
account — no per-tenant cron scheduling exists yet, matching the rest of the
app's dev_account_id convenience.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from app.config import AppSettings
from app.db import models as m
from app.db.session import tenant_session
from app.services import jobs as jobsvc

router = APIRouter(prefix="/internal/cron", tags=["cron"])


def _check_token(authorization: str | None) -> None:
    expected = os.environ.get("CRON_TOKEN", "").strip()
    if not expected:
        raise HTTPException(503, "CRON_TOKEN が未設定です。")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not got or got != expected:
        raise HTTPException(401, "認証に失敗しました。")


@router.post("/rank-sync")
def cron_rank_sync(authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)

    account_id = AppSettings.from_env().dev_account_id
    results: list[dict] = []
    with tenant_session(account_id) as session:
        domain_ids = [
            d_id
            for (d_id,) in session.execute(
                select(m.Domain.id).where(m.Domain.account_id == account_id)
            ).all()
        ]

    for domain_id in domain_ids:
        entry: dict = {"domain_id": domain_id}
        for kind in ("rank_sync", "analysis"):
            with tenant_session(account_id) as session:
                job = jobsvc.enqueue(
                    session, account_id=account_id, kind=kind, domain_id=domain_id
                )
                job_id = job.id
            final = jobsvc.run_job(job_id, account_id)
            entry[kind] = {"status": final["status"], "error": final.get("error")}
        results.append(entry)

    return {"account_id": account_id, "domains": results}
