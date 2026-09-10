"""SQLAlchemy 2.0 ORM — mirrors db/migrations/0001_multitenant_core.sql.

Table and column names match the SQL migration exactly; the migration remains
the source of truth for DDL (constraints, RLS, triggers). These classes are for
querying. JSON columns use the portable ``JSON`` type with a ``JSONB`` variant
on Postgres.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP

JSONish = JSON().with_variant(JSONB(), "postgresql")
TS = TIMESTAMP(timezone=True)
# BigInteger identity PK on Postgres; plain INTEGER rowid on SQLite so local
# smoke tests get autoincrement.
BigPK = BigInteger().with_variant(Integer, "sqlite")
# Native `uuid` on Postgres (matches the 0001 migration), CHAR(32) on SQLite.
# as_uuid=False keeps the Python value a str so callers pass str(uuid4()).
JobId = Uuid(as_uuid=False)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    llm_monthly_budget_usd: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="20.00"
    )
    llm_budget_action: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="block"
    )
    llm_job_ceiling_usd: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="2.00"
    )
    draft_model: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="claude-sonnet-5"
    )

    members: Mapped[list["AccountMember"]] = relationship(back_populates="account")
    domains: Mapped[list["Domain"]] = relationship(back_populates="account")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(Text)
    email_plain: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class AccountMember(Base):
    __tablename__ = "account_members"

    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)  # owner|editor|viewer
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    account: Mapped[Account] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="google")
    google_email: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    access_expires_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (UniqueConstraint("account_id", "provider"),)


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    gsc_site_url: Mapped[str] = mapped_column(Text, nullable=False)

    wp_base_url: Mapped[str | None] = mapped_column(Text)
    wp_username: Mapped[str | None] = mapped_column(Text)
    wp_app_password_enc: Mapped[str | None] = mapped_column(Text)
    anthropic_api_key_enc: Mapped[str | None] = mapped_column(Text)

    keyword_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="500"
    )
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (UniqueConstraint("account_id", "domain_key"),)

    account: Mapped[Account] = relationship(back_populates="domains")
    prompts: Mapped[list["DomainPrompt"]] = relationship(back_populates="domain")


class DomainPrompt(Base):
    __tablename__ = "domain_prompts"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    component: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (UniqueConstraint("domain_id", "component", "version"),)

    domain: Mapped[Domain] = relationship(back_populates="prompts")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(JobId, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    params_json: Mapped[dict] = mapped_column(JSONish, nullable=False, default=dict)
    result_json: Mapped[dict | None] = mapped_column(JSONish)
    error: Mapped[str | None] = mapped_column(Text)
    llm_cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0"
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(JobId, ForeignKey("jobs.id", ondelete="SET NULL"))
    wp_post_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    target_keyword: Mapped[str | None] = mapped_column(Text)
    target_search_volume: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    slug: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    eyecatch_url: Mapped[str | None] = mapped_column(Text)
    meta_json: Mapped[dict] = mapped_column(JSONish, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(TS)


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="SET NULL")
    )
    job_id: Mapped[str | None] = mapped_column(JobId, ForeignKey("jobs.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")
    billing_period: Mapped[str] = mapped_column(Text, nullable=False)  # 'YYYY-MM'
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class ApiUsage(Base):
    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    meta_json: Mapped[dict] = mapped_column(JSONish, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("account_id", "provider", "operation", "usage_date"),
    )


# --- RankPulse tables (re-homed) ---------------------------------------------
class KeywordMetricsHistory(Base):
    __tablename__ = "keyword_metrics_history"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    avg_monthly_searches: Mapped[int | None] = mapped_column(Integer)
    competition_level: Mapped[str | None] = mapped_column(Text)
    competition_index: Mapped[int | None] = mapped_column(Integer)
    low_top_of_page_bid: Mapped[float | None] = mapped_column(Numeric(12, 6))
    high_top_of_page_bid: Mapped[float | None] = mapped_column(Numeric(12, 6))
    retrieved_at: Mapped[datetime] = mapped_column(TS, nullable=False)


class KeywordRankHistory(Base):
    __tablename__ = "keyword_rank_history"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    gsc_average_position: Mapped[float | None] = mapped_column(Numeric(6, 2))
    serp_rank: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ctr: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False, server_default="0")
    search_volume: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("domain_id", "url", "keyword", "metric_date"),
    )


class OpportunityScore(Base):
    __tablename__ = "opportunity_scores"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    score_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    component_breakdown_json: Mapped[dict] = mapped_column(
        JSONish, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("domain_id", "url", "keyword", "score_date"),
    )


class RankAlert(Base):
    __tablename__ = "rank_alerts"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    detected_date: Mapped[date] = mapped_column(Date, nullable=False)
    alert_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    from_position: Mapped[float | None] = mapped_column(Numeric(6, 2))
    to_position: Mapped[float | None] = mapped_column(Numeric(6, 2))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class RewriteHistory(Base):
    __tablename__ = "rewrite_history"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    change_date: Mapped[date] = mapped_column(Date, nullable=False)
    title_before: Mapped[str | None] = mapped_column(Text)
    title_after: Mapped[str | None] = mapped_column(Text)
    change_types_json: Mapped[list] = mapped_column(JSONish, nullable=False, default=list)
    target_keyword: Mapped[str | None] = mapped_column(Text)
    position_before: Mapped[float | None] = mapped_column(Numeric(6, 2))
    ctr_before: Mapped[float | None] = mapped_column(Numeric(6, 4))
    clicks_before: Mapped[int | None] = mapped_column(Integer)
    impressions_before: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


ACCOUNT_SCOPED = (
    OAuthToken, Domain, DomainPrompt, Job, Article, LlmUsage, ApiUsage,
    KeywordMetricsHistory, KeywordRankHistory, OpportunityScore, RankAlert,
    RewriteHistory,
)
