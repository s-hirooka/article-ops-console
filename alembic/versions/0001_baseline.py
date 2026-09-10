"""baseline: multitenant core + RLS

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-10

On PostgreSQL this executes db/migrations/0001_multitenant_core.sql verbatim
(identity columns, RLS policies, triggers, extensions). On SQLite — local smoke
tests only — it falls back to ORM ``create_all`` since RLS/DO-blocks don't exist
there.
"""
from __future__ import annotations

from pathlib import Path

from alembic import op
import sqlalchemy as sa

from app.db.models import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

_SQL = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0001_multitenant_core.sql"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # the .sql file wraps itself in BEGIN/COMMIT; alembic already opened a
        # transaction, so strip the outer BEGIN/COMMIT and let alembic own it.
        raw = _SQL.read_text(encoding="utf-8")
        raw = raw.replace("BEGIN;", "", 1)
        raw = "".join(raw.rsplit("COMMIT;", 1))
        # Run through the raw DBAPI cursor, NOT op.execute(sa.text(...)):
        # SQLAlchemy's text() escapes '%' for the pyformat driver, which would
        # mangle the RLS DO-block's format('%1$I', ...) calls. psycopg3 sends a
        # no-parameter string verbatim and accepts multiple statements.
        cur = bind.connection.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS citext")
        cur.execute(raw)
    else:
        Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    else:
        Base.metadata.drop_all(bind=bind)
