"""rank_sync job — pull GSC Search Analytics into keyword_rank_history.

Port of RankPulse.rank_sync: same URL-fragment stripping and impression-weighted
position aggregation, writing to the Postgres table instead of SQLite. Post-ID
resolution against WordPress is skipped here (added when WP creds are wired per
domain); ``search_volume`` is backfilled from keyword_metrics_history.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import models as m
from app.integrations.gsc import query_search_analytics

GSC_LAG_DAYS = 3
DEFAULT_WINDOW_DAYS = 7


def _clean_url(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def _volume_map(session: Session, account_id: int, keywords: set[str]) -> dict[str, int]:
    if not keywords:
        return {}
    rows = session.execute(
        select(
            m.KeywordMetricsHistory.keyword,
            m.KeywordMetricsHistory.avg_monthly_searches,
            m.KeywordMetricsHistory.retrieved_at,
        )
        .where(
            m.KeywordMetricsHistory.account_id == account_id,
            m.KeywordMetricsHistory.keyword.in_(keywords),
            m.KeywordMetricsHistory.avg_monthly_searches.is_not(None),
        )
        .order_by(m.KeywordMetricsHistory.retrieved_at.desc())
    ).all()
    out: dict[str, int] = {}
    for kw, vol, _ in rows:
        out.setdefault(kw, int(vol))
    return out


def run_rank_sync(
    session: Session,
    *,
    account_id: int,
    domain_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    domain = session.get(m.Domain, domain_id)
    if domain is None or domain.account_id != account_id:
        raise ValueError("domain が見つかりません。")

    if end_date is None:
        end_date = (datetime.now() - timedelta(days=GSC_LAG_DAYS)).strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (
            datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=DEFAULT_WINDOW_DAYS)
        ).strftime("%Y-%m-%d")

    import os

    if os.environ.get("GSC_FAKE") == "1":
        access_token = "fake"
    else:
        from app.integrations.google_token import get_access_token

        access_token = get_access_token(session, account_id)

    rows = query_search_analytics(
        access_token, domain.gsc_site_url, start_date, end_date
    )

    agg: dict[tuple, dict] = defaultdict(
        lambda: {"clicks": 0.0, "impressions": 0.0, "pos_wsum": 0.0}
    )
    for r in rows:
        d_raw, keyword, page = r["keys"]
        d = d_raw if isinstance(d_raw, date) else datetime.strptime(d_raw, "%Y-%m-%d").date()
        key = (d, keyword, _clean_url(page))
        imp = float(r.get("impressions", 0.0))
        b = agg[key]
        b["clicks"] += float(r.get("clicks", 0.0))
        b["impressions"] += imp
        b["pos_wsum"] += float(r.get("position", 0.0)) * max(imp, 1.0)

    keywords = {k[1] for k in agg}
    volumes = _volume_map(session, account_id, keywords)
    now = datetime.now(timezone.utc)
    written = 0

    for (d, keyword, url), b in agg.items():
        imp = b["impressions"]
        position = (b["pos_wsum"] / imp) if imp > 0 else b["pos_wsum"]
        clicks = b["clicks"]
        ctr = (clicks / imp) if imp > 0 else 0.0
        values = dict(
            account_id=account_id,
            domain_id=domain_id,
            post_id=None,
            url=url,
            keyword=keyword,
            metric_date=d,
            gsc_average_position=round(position, 2),
            serp_rank=None,
            clicks=int(clicks),
            impressions=int(imp),
            ctr=round(ctr, 4),
            search_volume=volumes.get(keyword),
            created_at=now,
        )
        if session.bind.dialect.name == "postgresql":
            stmt = pg_insert(m.KeywordRankHistory).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["domain_id", "url", "keyword", "metric_date"],
                set_={
                    "gsc_average_position": stmt.excluded.gsc_average_position,
                    "clicks": stmt.excluded.clicks,
                    "impressions": stmt.excluded.impressions,
                    "ctr": stmt.excluded.ctr,
                    "search_volume": stmt.excluded.search_volume,
                },
            )
            session.execute(stmt)
        else:
            existing = session.scalar(
                select(m.KeywordRankHistory).where(
                    m.KeywordRankHistory.domain_id == domain_id,
                    m.KeywordRankHistory.url == url,
                    m.KeywordRankHistory.keyword == keyword,
                    m.KeywordRankHistory.metric_date == d,
                )
            )
            if existing:
                for f in ("gsc_average_position", "clicks", "impressions", "ctr", "search_volume"):
                    setattr(existing, f, values[f])
            else:
                session.add(m.KeywordRankHistory(**values))
        written += 1

    session.flush()
    return {
        "domain_id": domain_id,
        "range": [start_date, end_date],
        "gsc_rows": len(rows),
        "rows_written": written,
    }
