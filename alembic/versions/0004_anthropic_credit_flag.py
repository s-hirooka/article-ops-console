"""accounts.anthropic_credit_exhausted_at: surface credit exhaustion on the dashboard

Revision ID: 0004_anthropic_credit_flag
Revises: 0003_improve_article_kind
Create Date: 2026-09-16

Until now, "the Anthropic account ran out of credit" was only visible as a
per-job error message a user had to happen to click into. Adds a timestamp
set when a job hits that specific error and cleared the next time any LLM
call actually succeeds, so the AI予算 card can show a persistent warning
instead of the fact being buried in job history.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_anthropic_credit_flag"
down_revision = "0003_improve_article_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (smoke tests) already has this column: 0001_baseline creates
        # every table from the current models.py via Base.metadata.create_all,
        # which by now includes this field — adding it again would collide.
        return
    op.add_column(
        "accounts",
        sa.Column("anthropic_credit_exhausted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_column("accounts", "anthropic_credit_exhausted_at")
