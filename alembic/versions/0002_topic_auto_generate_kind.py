"""jobs.kind: allow 'topic_auto_generate'

Revision ID: 0002_topic_auto_generate_kind
Revises: 0001_baseline
Create Date: 2026-09-11

The jobs table's CHECK(kind IN (...)) was hand-written in the raw SQL
migration (db/migrations/0001_multitenant_core.sql) and never re-visited when
app/services/jobs.VALID_KINDS grew a new value — the Python-side allow-list
and the Postgres constraint silently drifted apart. First POST to
/api/jobs with kind='topic_auto_generate' hit the DB constraint at commit
time; since that commit happens outside any try/except in the request path,
it surfaced as a bare, undiagnosable 500 instead of a normal 422.

SQLite (local smoke tests) never had this constraint at all — migration
0001 falls back to ORM create_all() there, which doesn't emit inline CHECKs
— which is exactly why the smoke suite never caught this.
"""
from __future__ import annotations

from alembic import op

revision = "0002_topic_auto_generate_kind"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_KINDS = (
    "article_generate", "rank_sync", "analysis", "eyecatch", "test_prompt",
    "topic_auto_generate",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite has no such constraint to update
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK (kind IN ("
        + ", ".join(f"'{k}'" for k in _KINDS)
        + "))"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_check")
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK (kind IN ("
        + ", ".join(
            f"'{k}'" for k in
            ("article_generate", "rank_sync", "analysis", "eyecatch", "test_prompt")
        )
        + "))"
    )
