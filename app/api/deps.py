"""Request dependencies: resolve the active account, hand back a tenant session.

Auth is not built yet (P3). Until then the account is taken from the
``X-Account-Id`` header if present, else ``DEV_ACCOUNT_ID`` (default 1). When
real auth lands this is the single place that changes: verify the session/JWT,
look up ``account_members``, and 403 if the user is not a member.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.db.session import tenant_session

_settings = AppSettings.from_env()


def get_account_id(x_account_id: str | None = Header(default=None)) -> int:
    if x_account_id:
        try:
            return int(x_account_id)
        except ValueError:
            raise HTTPException(400, "X-Account-Id は整数で指定してください。")
    return _settings.dev_account_id


def db(x_account_id: str | None = Header(default=None)) -> Iterator[Session]:
    account_id = get_account_id(x_account_id)
    with tenant_session(account_id) as session:
        yield session
