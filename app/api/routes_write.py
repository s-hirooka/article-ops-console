"""Write API (P3): domains, per-domain prompt versions, member invites, jobs.

Auth is still header-stubbed (see deps.py). ``X-User-Id`` (default 1) identifies
the caller for ``edited_by`` / ``created_by`` / owner checks; real sessions
replace this in a later pass.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db
from app.db import models as m
from app.db.session import SessionLocal
from app.services import jobs as jobsvc
from app.services.prompt_assembly import _TEXT_DEFAULTS  # component name set

router = APIRouter(prefix="/api", tags=["write"])

_COMPONENTS = set(_TEXT_DEFAULTS) | {
    "vc_auto_ads_defaults",
    "eyecatch_style",
    "keyword_threshold",
}


def caller_user_id(x_user_id: str | None = Header(default=None)) -> int:
    try:
        return int(x_user_id) if x_user_id else 1
    except ValueError:
        raise HTTPException(400, "X-User-Id は整数で指定してください。")


def _aid(s: Session) -> int:
    return int(s.info["account_id"])


# --- accounts (for switching) -------------------------------------------------
@router.get("/accounts")
def my_accounts(user_id: int = Depends(caller_user_id)) -> list[dict]:
    # membership crosses accounts, so this one query is intentionally unscoped.
    with SessionLocal() as s:
        rows = s.execute(
            select(m.Account.id, m.Account.name, m.AccountMember.role)
            .join(m.AccountMember, m.AccountMember.account_id == m.Account.id)
            .where(m.AccountMember.user_id == user_id)
            .order_by(m.Account.name)
        ).all()
    return [{"id": i, "name": n, "role": r} for i, n, r in rows]


# --- domains ----------------------------------------------------------------
class DomainIn(BaseModel):
    domain_key: str = Field(min_length=1, max_length=120)
    base_url: str
    gsc_site_url: str
    keyword_threshold: int = 500


@router.post("/domains", status_code=201)
def create_domain(body: DomainIn, session: Session = Depends(db)) -> dict:
    aid = _aid(session)
    dupe = session.scalar(
        select(m.Domain).where(
            m.Domain.account_id == aid, m.Domain.domain_key == body.domain_key
        )
    )
    if dupe:
        raise HTTPException(409, "同名の domain_key が既にあります。")
    d = m.Domain(
        account_id=aid,
        domain_key=body.domain_key,
        base_url=body.base_url,
        gsc_site_url=body.gsc_site_url,
        keyword_threshold=body.keyword_threshold,
    )
    session.add(d)
    session.flush()
    return {"id": d.id, "domain_key": d.domain_key}


# --- per-domain prompt components ------------------------------------------
class PromptIn(BaseModel):
    body: str = Field(min_length=1)


def _guard_domain(session: Session, domain_id: int) -> m.Domain:
    d = session.get(m.Domain, domain_id)
    if d is None or d.account_id != _aid(session):
        raise HTTPException(404, "domain が見つかりません。")
    return d


@router.get("/domains/{domain_id}/prompts")
def list_prompts(domain_id: int, session: Session = Depends(db)) -> dict:
    _guard_domain(session, domain_id)
    sub = (
        select(m.DomainPrompt.component, func.max(m.DomainPrompt.version).label("v"))
        .where(m.DomainPrompt.domain_id == domain_id)
        .group_by(m.DomainPrompt.component)
        .subquery()
    )
    rows = session.execute(
        select(m.DomainPrompt).join(
            sub,
            (m.DomainPrompt.component == sub.c.component)
            & (m.DomainPrompt.version == sub.c.v)
            & (m.DomainPrompt.domain_id == domain_id),
        )
    ).scalars().all()
    return {
        r.component: {"version": r.version, "body": r.body, "edited_by": r.edited_by}
        for r in rows
    }


@router.get("/domains/{domain_id}/prompts/{component}/history")
def prompt_history(
    domain_id: int, component: str, session: Session = Depends(db)
) -> list[dict]:
    _guard_domain(session, domain_id)
    rows = session.scalars(
        select(m.DomainPrompt)
        .where(
            m.DomainPrompt.domain_id == domain_id,
            m.DomainPrompt.component == component,
        )
        .order_by(m.DomainPrompt.version.desc())
    ).all()
    return [
        {"version": r.version, "body": r.body, "edited_by": r.edited_by,
         "created_at": r.created_at}
        for r in rows
    ]


@router.put("/domains/{domain_id}/prompts/{component}", status_code=201)
def save_prompt(
    domain_id: int,
    component: str,
    body: PromptIn,
    session: Session = Depends(db),
    user_id: int = Depends(caller_user_id),
) -> dict:
    _guard_domain(session, domain_id)
    if component not in _COMPONENTS:
        raise HTTPException(422, f"未知のコンポーネント: {component}")
    current = session.scalar(
        select(func.max(m.DomainPrompt.version)).where(
            m.DomainPrompt.domain_id == domain_id,
            m.DomainPrompt.component == component,
        )
    )
    version = (current or 0) + 1
    row = m.DomainPrompt(
        account_id=_aid(session),
        domain_id=domain_id,
        component=component,
        version=version,
        body=body.body,
        edited_by=user_id,
    )
    session.add(row)
    session.flush()
    return {"component": component, "version": version}


# --- member invites --------------------------------------------------------
class MemberIn(BaseModel):
    email: str
    role: str = Field(pattern="^(owner|editor|viewer)$")


@router.post("/accounts/{account_id}/members", status_code=201)
def add_member(
    account_id: int,
    body: MemberIn,
    session: Session = Depends(db),
    user_id: int = Depends(caller_user_id),
) -> dict:
    if account_id != _aid(session):
        raise HTTPException(403, "現在のアカウントと一致しません。")
    caller = session.get(m.AccountMember, (account_id, user_id))
    if caller is None or caller.role != "owner":
        raise HTTPException(403, "メンバー招待は owner のみ可能です。")

    with SessionLocal() as plain:
        user = plain.scalar(select(m.User).where(m.User.email_plain == body.email))
        if user is None:
            user = m.User(email=body.email, email_plain=body.email)
            plain.add(user)
            plain.commit()
            plain.refresh(user)
        target_user_id = user.id

    existing = session.get(m.AccountMember, (account_id, target_user_id))
    if existing:
        existing.role = body.role
    else:
        session.add(
            m.AccountMember(account_id=account_id, user_id=target_user_id, role=body.role)
        )
    session.flush()
    return {"account_id": account_id, "user_id": target_user_id, "role": body.role}


# --- jobs -----------------------------------------------------------------
class JobIn(BaseModel):
    kind: str
    domain_id: int | None = None
    params: dict = Field(default_factory=dict)


@router.post("/jobs", status_code=201)
def create_job(
    body: JobIn,
    background: BackgroundTasks,
    session: Session = Depends(db),
    user_id: int = Depends(caller_user_id),
) -> dict:
    """Create a job and run it.

    On Render's free plan BackgroundTasks are unreliable (the instance spins
    down after 15 min with no traffic, killing pending work, and there is no
    retry). So jobs run **synchronously** here: the request returns once the
    job has finished. ``article_generate`` therefore takes ~30-60s; pass
    ``?async=1`` to fire-and-forget instead (best effort).
    """
    if body.kind not in jobsvc.VALID_KINDS:
        raise HTTPException(422, f"未知のジョブ種別: {body.kind}")
    if body.domain_id is not None:
        _guard_domain(session, body.domain_id)
    if body.kind in ("article_generate",) and not body.params.get("target_keyword"):
        raise HTTPException(422, "article_generate には params.target_keyword が必要です。")

    job = jobsvc.enqueue(
        session,
        account_id=_aid(session),
        kind=body.kind,
        params=body.params,
        domain_id=body.domain_id,
        created_by=user_id,
    )
    job_id = job.id
    session.commit()  # persist before run_job opens its own session

    if body.params.get("_async"):
        background.add_task(jobsvc.run_job, job_id)
        return {"job_id": job_id, "status": "queued"}

    final = jobsvc.run_job(job_id)  # blocks until done; opens its own session
    return {"job_id": job_id, **final}


class PublishIn(BaseModel):
    status: str = Field(default="publish", pattern="^(publish|draft)$")


@router.post("/articles/{article_id}/publish")
def publish_article_endpoint(
    article_id: int,
    body: PublishIn | None = None,
    session: Session = Depends(db),
) -> dict:
    from app.services.publish import PublishError, publish_article

    try:
        return publish_article(
            session,
            account_id=_aid(session),
            article_id=article_id,
            status=(body.status if body else "publish"),
        )
    except PublishError as exc:
        raise HTTPException(422, str(exc))


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: Session = Depends(db)) -> dict:
    j = session.get(m.Job, job_id)
    if j is None or j.account_id != _aid(session):
        raise HTTPException(404, "job が見つかりません。")
    return {
        "id": j.id,
        "kind": j.kind,
        "status": j.status,
        "domain_id": j.domain_id,
        "params": j.params_json,
        "result": j.result_json,
        "error": j.error,
        "llm_cost_usd": float(j.llm_cost_usd or 0),
        "created_at": j.created_at,
        "started_at": j.started_at,
        "finished_at": j.finished_at,
    }
