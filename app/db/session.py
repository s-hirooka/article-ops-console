"""Engine + per-request session with tenant isolation.

Every request that touches account-scoped data runs inside a transaction that
first does ``SET LOCAL app.account_id = '<id>'`` (Postgres). The RLS policies in
migration 0001 then filter every row. ``SET LOCAL`` is transaction-scoped, so
pooled connections never leak an account id between requests.

On SQLite (local smoke tests) the ``SET LOCAL`` is skipped — RLS does not exist
there, so queries must still carry an explicit ``WHERE account_id == :id`` (the
read layer does). Never run production on SQLite.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppSettings

_settings = AppSettings.from_env()
_is_pg = _settings.database_url.startswith("postgresql")

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args={} if _is_pg else {"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def tenant_session(account_id: int) -> Iterator[Session]:
    """A session bound to one account for the life of a transaction."""
    session = SessionLocal()
    try:
        if _is_pg:
            # parameterised SET LOCAL is not allowed; account_id is an int so
            # format it directly after coercing.
            session.execute(text(f"SET LOCAL app.account_id = '{int(account_id)}'"))
        session.info["account_id"] = int(account_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_tenant_session(account_id: int) -> Iterator[Session]:
    """FastAPI dependency form."""
    with tenant_session(account_id) as s:
        yield s
