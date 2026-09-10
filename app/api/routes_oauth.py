"""Google OAuth connect flow (P4).

  GET /oauth/google/start     -> redirect to Google consent
  GET /oauth/google/callback  -> exchange code, store encrypted tokens
  GET /api/oauth/google/status -> is this account connected?

State is held in-process ({state: (account_id, ts)}). Single free web instance,
so this is fine; a multi-instance deploy needs Redis (noted in render.yaml).
Requires APP_ENCRYPTION_KEY to be set (tokens are stored Fernet-encrypted).
"""
from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import db, get_account_id
from app.integrations import google_oauth
from app.integrations.google_token import store_tokens

router = APIRouter(tags=["oauth"])

_STATE: dict[str, tuple[int, float]] = {}
_STATE_TTL = 600


def _gc() -> None:
    now = time.time()
    for k in [k for k, (_, ts) in _STATE.items() if now - ts > _STATE_TTL]:
        _STATE.pop(k, None)


@router.get("/oauth/google/start")
def google_start(account_id: int = Depends(get_account_id)) -> RedirectResponse:
    _gc()
    state = secrets.token_urlsafe(24)
    _STATE[state] = (account_id, time.time())
    try:
        url = google_oauth.build_authorization_url(state)
    except KeyError as exc:
        raise HTTPException(500, f"OAuth 設定が未完了です: {exc}")
    return RedirectResponse(url, status_code=307)


@router.get("/oauth/google/callback")
def google_callback(
    session: Session = Depends(db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
) -> HTMLResponse:
    if error:
        return HTMLResponse(f"<h1>連携失敗</h1><p>{error}</p>", status_code=400)
    if not code or not state or state not in _STATE:
        raise HTTPException(400, "state が無効または期限切れです。やり直してください。")
    account_id, _ = _STATE.pop(state)
    if account_id != int(session.info["account_id"]):
        raise HTTPException(400, "アカウントが一致しません。")

    try:
        bundle = google_oauth.exchange_code(code)
    except google_oauth.OAuthError as exc:
        return HTMLResponse(f"<h1>トークン取得失敗</h1><p>{exc}</p>", status_code=400)

    store_tokens(
        session,
        account_id,
        refresh_token=bundle.refresh_token,
        access_token=bundle.access_token,
        expires_at=bundle.expires_at,
        scopes=bundle.scope or " ".join(google_oauth.SCOPES),
        google_email=None,
    )
    return HTMLResponse(
        "<h1>Google 連携が完了しました</h1>"
        '<p><a href="/">ダッシュボードへ戻る</a></p>'
    )


@router.get("/api/oauth/google/status")
def google_status(session: Session = Depends(db)) -> dict:
    from sqlalchemy import select

    from app.db import models as m

    tok = session.scalar(
        select(m.OAuthToken).where(
            m.OAuthToken.account_id == int(session.info["account_id"]),
            m.OAuthToken.provider == "google",
        )
    )
    if tok is None:
        return {"connected": False}
    return {
        "connected": True,
        "google_email": tok.google_email,
        "scopes": tok.scopes,
        "access_expires_at": tok.access_expires_at,
    }
