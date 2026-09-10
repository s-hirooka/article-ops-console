"""Google OAuth connect flow (P4).

  GET /oauth/google/start      -> redirect to Google consent
  GET /oauth/google/callback   -> exchange code, store encrypted tokens
  GET /api/oauth/google/status  -> is this account connected?

The CSRF ``state`` is **stateless**: a signed, timestamped token
(``account_id.ts.nonce.hmac``) verified with HMAC-SHA256 keyed on
APP_ENCRYPTION_KEY. No server-side store, so it survives the free instance
spinning down or redeploying between /start and /callback.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import db, get_account_id
from app.integrations import google_oauth
from app.integrations.google_token import store_tokens

router = APIRouter(tags=["oauth"])

_STATE_TTL = 900  # seconds


def _secret() -> bytes:
    key = os.environ.get("APP_ENCRYPTION_KEY", "").split(",")[0].strip()
    if not key:
        raise HTTPException(500, "APP_ENCRYPTION_KEY が未設定です。")
    return hashlib.sha256(("oauth-state:" + key).encode()).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def sign_state(account_id: int) -> str:
    payload = f"{int(account_id)}.{int(time.time())}.{secrets.token_urlsafe(8)}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64(sig)}"


def verify_state(state: str | None) -> int:
    if not state or state.count(".") != 3:
        raise HTTPException(400, "state が無効です。やり直してください。")
    account_id_s, ts_s, nonce, sig_b64 = state.split(".")
    payload = f"{account_id_s}.{ts_s}.{nonce}"
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()
    try:
        got = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    except Exception:
        raise HTTPException(400, "state の署名が不正です。")
    if not hmac.compare_digest(expected, got):
        raise HTTPException(400, "state の署名が一致しません。やり直してください。")
    if abs(time.time() - int(ts_s)) > _STATE_TTL:
        raise HTTPException(400, "state の有効期限が切れました。やり直してください。")
    return int(account_id_s)


@router.get("/oauth/google/start")
def google_start(account_id: int = Depends(get_account_id)) -> RedirectResponse:
    try:
        url = google_oauth.build_authorization_url(sign_state(account_id))
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
    if not code:
        raise HTTPException(400, "認可コードがありません。")

    account_id = verify_state(state)
    if account_id != int(session.info["account_id"]):
        raise HTTPException(400, "アカウントが一致しません。")

    try:
        bundle = google_oauth.exchange_code(code)
    except google_oauth.OAuthError as exc:
        return HTMLResponse(f"<h1>トークン取得失敗</h1><p>{exc}</p>", status_code=400)

    try:
        store_tokens(
            session,
            account_id,
            refresh_token=bundle.refresh_token,
            access_token=bundle.access_token,
            expires_at=bundle.expires_at,
            scopes=bundle.scope or " ".join(google_oauth.SCOPES),
            google_email=None,
        )
    except Exception as exc:  # crypto / DB — show it instead of a bare 500
        return HTMLResponse(
            f"<h1>トークン保存に失敗しました</h1><p>{type(exc).__name__}: {exc}</p>",
            status_code=500,
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
