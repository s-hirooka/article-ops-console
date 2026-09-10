"""Server-side Google OAuth2 — authorization-code flow.

Replaces the local-Chrome / desktop-app consent the old tooling relied on. The
web app sends the owner to Google, Google redirects back to
``{APP}/oauth/google/callback?code=...&state=...``, we exchange the code for a
**refresh token**, and store it Fernet-encrypted in ``oauth_tokens`` (spec §09).
From then on every Search Console / Google Ads call mints a short-lived access
token from that refresh token — no browser, no Windows.

Scopes:
* ``webmasters.readonly`` — Search Console (rank_sync.py)
* ``adwords``             — Google Ads keyword volume (google_ads_keywords.py)

This module is transport only. Persistence, the ``state`` nonce check, and the
account/session wiring live in the API layer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from app.config import GoogleOAuthSettings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/adwords",
)

_TIMEOUT = 30


class OAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class TokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: float          # epoch seconds
    scope: str
    token_type: str

    @property
    def expires_in(self) -> int:
        return max(0, int(self.expires_at - time.time()))


def _bundle(payload: dict, *, fallback_refresh: str | None = None) -> TokenBundle:
    if "error" in payload:
        raise OAuthError(
            f"{payload.get('error')}: {payload.get('error_description', '')}".strip()
        )
    try:
        return TokenBundle(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token") or fallback_refresh,
            expires_at=time.time() + int(payload.get("expires_in", 3600)),
            scope=payload.get("scope", ""),
            token_type=payload.get("token_type", "Bearer"),
        )
    except KeyError as exc:
        raise OAuthError(f"想定外のトークン応答: missing {exc}") from exc


def build_authorization_url(
    state: str,
    settings: GoogleOAuthSettings | None = None,
    scopes: tuple[str, ...] = SCOPES,
    login_hint: str | None = None,
) -> str:
    """URL to send the user to. ``state`` must be a random nonce the caller
    stores and re-checks on the callback (CSRF)."""
    s = settings or GoogleOAuthSettings.from_env()
    params = {
        "client_id": s.client_id,
        "redirect_uri": s.redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",       # ask for a refresh token
        "prompt": "consent",            # force it even on re-consent
        "include_granted_scopes": "true",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code(
    code: str,
    settings: GoogleOAuthSettings | None = None,
) -> TokenBundle:
    """Callback handler: swap the one-time ``code`` for tokens."""
    s = settings or GoogleOAuthSettings.from_env()
    resp = requests.post(
        TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": s.client_id,
            "client_secret": s.client_secret,
            "redirect_uri": s.redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=_TIMEOUT,
    )
    payload = _safe_json(resp)
    bundle = _bundle(payload)
    if not bundle.refresh_token:
        raise OAuthError(
            "refresh_token が返りませんでした。Google アカウントの "
            "アクセス権を一度解除してから、consent 画面をやり直してください。"
        )
    return bundle


def refresh_access_token(
    refresh_token: str,
    settings: GoogleOAuthSettings | None = None,
) -> TokenBundle:
    """Mint a fresh access token. Google does not rotate the refresh token here,
    so ``bundle.refresh_token`` echoes the input."""
    s = settings or GoogleOAuthSettings.from_env()
    resp = requests.post(
        TOKEN_ENDPOINT,
        data={
            "refresh_token": refresh_token,
            "client_id": s.client_id,
            "client_secret": s.client_secret,
            "grant_type": "refresh_token",
        },
        timeout=_TIMEOUT,
    )
    return _bundle(_safe_json(resp), fallback_refresh=refresh_token)


def revoke(token: str) -> None:
    """Revoke a refresh or access token (account disconnect)."""
    resp = requests.post(
        REVOKE_ENDPOINT,
        data={"token": token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=_TIMEOUT,
    )
    if resp.status_code not in (200, 400):  # 400 = already invalid
        raise OAuthError(f"revoke に失敗しました: HTTP {resp.status_code}")


def _safe_json(resp: requests.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        raise OAuthError(
            f"トークンエンドポイントが非 JSON を返しました (HTTP {resp.status_code})"
        )
