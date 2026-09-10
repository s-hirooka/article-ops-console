"""Turn a stored, encrypted refresh token into a live access token.

``oauth_tokens`` holds one row per account (provider='google') with the refresh
token Fernet-encrypted. This module decrypts it, refreshes when the cached
access token is stale, re-encrypts the (possibly unchanged) refresh token, and
hands back a bearer string for Search Console / Ads calls.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.integrations.google_oauth import refresh_access_token
from app.security.crypto import decrypt, encrypt

_SKEW = 120  # refresh a bit early


class NoGoogleConnection(RuntimeError):
    pass


def _row(session: Session, account_id: int) -> m.OAuthToken | None:
    return session.scalar(
        select(m.OAuthToken).where(
            m.OAuthToken.account_id == account_id,
            m.OAuthToken.provider == "google",
        )
    )


def get_access_token(session: Session, account_id: int) -> str:
    tok = _row(session, account_id)
    if tok is None:
        raise NoGoogleConnection(
            "この account は Google 連携が未設定です（/oauth/google/start から接続）。"
        )

    now = time.time()
    if (
        tok.access_token_enc
        and tok.access_expires_at
        and tok.access_expires_at.timestamp() - _SKEW > now
    ):
        return decrypt(tok.access_token_enc)

    refresh = decrypt(tok.refresh_token_enc)
    bundle = refresh_access_token(refresh)

    tok.access_token_enc = encrypt(bundle.access_token)
    tok.access_expires_at = datetime.fromtimestamp(bundle.expires_at, tz=timezone.utc)
    if bundle.refresh_token and bundle.refresh_token != refresh:
        tok.refresh_token_enc = encrypt(bundle.refresh_token)
    session.flush()
    return bundle.access_token


def store_tokens(
    session: Session,
    account_id: int,
    *,
    refresh_token: str,
    access_token: str | None,
    expires_at: float | None,
    scopes: str,
    google_email: str | None,
) -> m.OAuthToken:
    tok = _row(session, account_id)
    if tok is None:
        tok = m.OAuthToken(
            account_id=account_id,
            provider="google",
            scopes=scopes,
            refresh_token_enc=encrypt(refresh_token),
        )
        session.add(tok)
    else:
        tok.refresh_token_enc = encrypt(refresh_token)
        tok.scopes = scopes
    tok.google_email = google_email
    tok.access_token_enc = encrypt(access_token) if access_token else None
    tok.access_expires_at = (
        datetime.fromtimestamp(expires_at, tz=timezone.utc) if expires_at else None
    )
    session.flush()
    return tok
