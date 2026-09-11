"""jobs.kind: drop the CHECK constraint instead of extending it again

Revision ID: 0003_improve_article_kind
Revises: 0002_topic_auto_generate_kind
Create Date: 2026-09-11

This is the second time in one day a new job kind (now "improve_article")
needed a matching migration just to update this list — a hand-written
Postgres CHECK(kind IN (...)) duplicating app/services/jobs.VALID_KINDS,
guaranteed to drift because nothing keeps the two in sync. 0002 already
paid for that once (a production outage: INSERT violated the constraint at
commit time, outside any try/except in the request path, surfacing as a
bare 500 with no diagnostic text).

VALID_KINDS already gates every job at the application layer (`enqueue()`
raises ValueError for anything not in it, and the API layer 422s before
that). The DB constraint adds no safety beyond that — only a second place
to forget to update — so this drops it for good rather than re-adding it
with one more value.
"""
from __future__ import annotations

from alembic import op

revision = "0003_improve_article_kind"
down_revision = "0002_topic_auto_generate_kind"
branch_labels = None
depends_on = None

_PREV_KINDS = (
    "article_generate", "rank_sync", "analysis", "eyecatch", "test_prompt",
    "topic_auto_generate",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_check")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK (kind IN ("
        + ", ".join(f"'{k}'" for k in _PREV_KINDS)
        + "))"
    )
