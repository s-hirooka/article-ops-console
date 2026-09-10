"""Runtime configuration.

Values come from environment variables. `load_dotenv` is called opportunistically
so local development can drop a `.env` next to the project (git-ignored). In the
cloud, Render / GitHub Actions inject the same variable names directly.

The Google Ads variable names deliberately match the existing
`G:\\KeywordInsightService\\.env`, so the migration can reuse those credentials
without copying secrets into this repo (point `GOOGLE_ADS_DOTENV` at that file).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # dotenv optional in prod
        return
    # 1) an explicit path (e.g. the existing KeywordInsightService/.env)
    explicit = os.environ.get("GOOGLE_ADS_DOTENV")
    if explicit and os.path.isfile(explicit):
        load_dotenv(explicit, override=False)
    # 2) a local .env in the project root
    load_dotenv(override=False)


_load_env()


def _digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


@dataclass(frozen=True)
class GoogleAdsSettings:
    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str        # digits only, may be ""
    default_customer_id: str      # digits only
    language_id: str              # criterion id, e.g. "1005" = Japanese
    geo_target_ids: tuple[str, ...]  # criterion ids, e.g. ("2392",) = Japan
    max_keywords_per_request: int
    use_proto_plus: bool = True

    @classmethod
    def from_env(cls) -> "GoogleAdsSettings":
        return cls(
            developer_token=os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"].strip(),
            client_id=os.environ["GOOGLE_ADS_OAUTH2_CLIENT_ID"].strip(),
            client_secret=os.environ["GOOGLE_ADS_OAUTH2_CLIENT_SECRET"].strip(),
            refresh_token=os.environ["GOOGLE_ADS_OAUTH2_REFRESH_TOKEN"].strip(),
            login_customer_id=_digits(os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")),
            default_customer_id=_digits(
                os.environ.get("GOOGLE_ADS_DEFAULT_CUSTOMER_ID")
                or os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
            ),
            language_id=os.environ.get("GOOGLE_ADS_LANGUAGE_ID", "1005").strip(),
            geo_target_ids=tuple(
                g.strip()
                for g in os.environ.get("GOOGLE_ADS_GEO_TARGET_IDS", "2392").split(",")
                if g.strip()
            ),
            max_keywords_per_request=int(
                os.environ.get("GOOGLE_ADS_MAX_KEYWORDS_PER_REQUEST", "30")
            ),
        )


@dataclass(frozen=True)
class GoogleOAuthSettings:
    """Server-side OAuth2 (authorization-code flow) for Search Console + Ads.

    Falls back to the existing desktop Ads OAuth client so a single Google Cloud
    project can serve both — but a *Web application* client (with the redirect
    URI registered) is required for the server flow.
    """
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> "GoogleOAuthSettings":
        return cls(
            client_id=(
                os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
                or os.environ["GOOGLE_ADS_OAUTH2_CLIENT_ID"]
            ).strip(),
            client_secret=(
                os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
                or os.environ["GOOGLE_ADS_OAUTH2_CLIENT_SECRET"]
            ).strip(),
            redirect_uri=os.environ.get(
                "GOOGLE_OAUTH_REDIRECT_URI",
                "http://localhost:8000/oauth/google/callback",
            ).strip(),
        )
