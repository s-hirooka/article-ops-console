""""AIで実行" で行った改訂の履歴と、その前後でSEO指標がどう動いたか。

Each entry in articles.meta_json.improve_history (written by
article_improve.run_improve) is a point-in-time edit record — keyword,
action_hint, title before/after. This pairs it with keyword_rank_history
around that date to answer 良くなった？悪くなった？: average position /
clicks / impressions for the same keyword in the window before the edit vs
the window after. GSC reports with ~3 day lag (matches rank_sync's own
GSC_LAG_DAYS), so a very recent edit won't have enough "after" data yet —
that's surfaced as its own verdict rather than guessed at from a thin or
empty sample.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m

_WINDOW_DAYS = 7
_GSC_LAG_DAYS = 3  # keep in sync with app/services/rank_sync.GSC_LAG_DAYS


def _avg(rows: list[m.KeywordRankHistory]) -> dict:
    if not rows:
        return {"position": None, "clicks": None, "impressions": None, "days": 0}
    positions = [float(r.gsc_average_position) for r in rows if r.gsc_average_position is not None]
    return {
        "position": round(sum(positions) / len(positions), 1) if positions else None,
        "clicks": round(sum(r.clicks for r in rows) / len(rows), 1),
        "impressions": round(sum(r.impressions for r in rows) / len(rows), 1),
        "days": len(rows),
    }


def list_improve_history(session: Session, *, account_id: int, domain_id: int) -> list[dict]:
    articles = session.scalars(
        select(m.Article).where(
            m.Article.account_id == account_id,
            m.Article.domain_id == domain_id,
        )
    ).all()

    entries: list[dict] = []
    for art in articles:
        for rec in (art.meta_json or {}).get("improve_history") or []:
            entries.append({**rec, "article_id": art.id, "article_title": art.title})
    entries.sort(key=lambda e: e.get("at") or "", reverse=True)

    today = date.today()
    out: list[dict] = []
    for e in entries:
        try:
            edit_date = datetime.fromisoformat(e["at"]).date()
        except (KeyError, ValueError, TypeError):
            out.append({**e, "before": _avg([]), "after": _avg([]), "verdict": "unknown",
                        "data_ready_at": None})
            continue

        keyword = e.get("keyword")
        rows = session.scalars(
            select(m.KeywordRankHistory).where(
                m.KeywordRankHistory.account_id == account_id,
                m.KeywordRankHistory.domain_id == domain_id,
                m.KeywordRankHistory.keyword == keyword,
            )
        ).all()
        before_rows = [
            r for r in rows
            if edit_date - timedelta(days=_WINDOW_DAYS) <= r.metric_date < edit_date
        ]
        after_rows = [
            r for r in rows
            if edit_date <= r.metric_date <= edit_date + timedelta(days=_WINDOW_DAYS)
        ]

        ready_since = edit_date + timedelta(days=_GSC_LAG_DAYS)
        data_ready = today >= ready_since

        before = _avg(before_rows)
        after = _avg(after_rows) if data_ready else _avg([])

        if not data_ready:
            verdict = "too_early"
        elif not after_rows:
            verdict = "no_data"
        elif before["position"] is None or after["position"] is None:
            verdict = "no_data"
        else:
            delta = before["position"] - after["position"]  # lower position is better
            if delta > 0.5:
                verdict = "improved"
            elif delta < -0.5:
                verdict = "declined"
            else:
                verdict = "flat"

        out.append({
            **e,
            "before": before,
            "after": after,
            "verdict": verdict,
            "data_ready_at": ready_since.isoformat(),
        })
    return out
