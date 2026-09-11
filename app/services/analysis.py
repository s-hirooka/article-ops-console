"""analysis job — opportunity scores + rank alerts from keyword_rank_history.

A compact port of RankPulse.opportunity_score / RankPulse.alerts. The scoring
*shape* (position band, reference CTR curve, log-scaled impression/volume) is
kept; the weights and band bounds are defaults here rather than loaded from a
settings file — tune later by lifting them to the account or a config table.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m

# --- tunables (RankPulse defaults) -----------------------------------------
W = {"position": 0.35, "ctr_gap": 0.25, "impression": 0.15, "volume": 0.15, "trend": 0.10}
POS_LOW, POS_SWEET, POS_HIGH = 4.0, 8.0, 20.0
IMPRESSION_CEILING, VOLUME_CEILING = 5000.0, 50000.0
DROP_7D_ALERT = 5.0          # positions worse over ~7 days
TOP10, TOP3 = 10, 3

_CTR_CURVE = {1: .28, 2: .15, 3: .11, 4: .08, 5: .06, 6: .05, 7: .04, 8: .03, 9: .03, 10: .02}
_CTR_TAIL = 0.01


def _expected_ctr(pos: float) -> float:
    if pos <= 1:
        return _CTR_CURVE[1]
    if pos >= 10:
        return _CTR_TAIL
    lo = int(math.floor(pos))
    return _CTR_CURVE.get(lo, _CTR_TAIL) + (
        _CTR_CURVE.get(lo + 1, _CTR_TAIL) - _CTR_CURVE.get(lo, _CTR_TAIL)
    ) * (pos - lo)


def _position_score(pos: float) -> float:
    if pos < POS_LOW:
        return 30.0
    edge = 40.0
    if pos <= POS_HIGH:
        span = max(POS_SWEET - POS_LOW, POS_HIGH - POS_SWEET) or 1.0
        return max(0.0, 100.0 - abs(pos - POS_SWEET) * (100.0 - edge) / span)
    width = (POS_HIGH - POS_LOW) or 1.0
    return max(0.0, edge - (pos - POS_HIGH) * (edge / width))


def _ctr_gap_score(pos: float, ctr: float) -> float:
    exp = _expected_ctr(pos)
    if exp <= 0:
        return 0.0
    return max(0.0, min(100.0, (exp - ctr) / exp * 100.0))


def _log_scaled(value: float | None, ceiling: float) -> float:
    if not value or value <= 0:
        return 0.0
    return max(0.0, min(100.0, math.log10(value + 1) / math.log10(ceiling + 1) * 100.0))


def _trend_score(change_7d: float | None) -> float:
    if change_7d is None:
        return 50.0
    if change_7d <= -10:
        return 100.0
    if change_7d <= -3:
        return 75.0
    if change_7d >= 10:
        return 20.0
    if change_7d >= 3:
        return 35.0
    return 50.0


def _score(pos, imp, ctr, volume, change_7d, clicks=None) -> tuple[float, dict]:
    parts = {
        "position_score": round(_position_score(pos), 1),
        "ctr_gap_score": round(_ctr_gap_score(pos, ctr), 1),
        "impression_score": round(_log_scaled(imp, IMPRESSION_CEILING), 1),
        "volume_score": round(_log_scaled(volume, VOLUME_CEILING), 1),
        "trend_score": round(_trend_score(change_7d), 1),
    }
    total = (
        W["position"] * parts["position_score"]
        + W["ctr_gap"] * parts["ctr_gap_score"]
        + W["impression"] * parts["impression_score"]
        + W["volume"] * parts["volume_score"]
        + W["trend"] * parts["trend_score"]
    )
    parts["weights"] = W
    parts["inputs"] = {"position": pos, "impressions": imp, "clicks": clicks, "ctr": ctr,
                       "search_volume": volume, "change_7d": change_7d}
    return round(max(0.0, min(100.0, total)), 1), parts


def _position_near(session, domain_id, url, keyword, target_date, tol_days=3) -> float | None:
    """Closest tracked position within +/- tol_days of target_date."""
    lo = target_date - timedelta(days=tol_days)
    hi = target_date + timedelta(days=tol_days)
    rows = session.execute(
        select(
            m.KeywordRankHistory.metric_date,
            m.KeywordRankHistory.gsc_average_position,
        ).where(
            m.KeywordRankHistory.domain_id == domain_id,
            m.KeywordRankHistory.url == url,
            m.KeywordRankHistory.keyword == keyword,
            m.KeywordRankHistory.metric_date >= lo,
            m.KeywordRankHistory.metric_date <= hi,
        )
    ).all()
    if not rows:
        return None
    best = min(rows, key=lambda row: abs((row[0] - target_date).days))
    return float(best[1]) if best[1] is not None else None


def run_analysis(session: Session, *, account_id: int, domain_id: int) -> dict:
    domain = session.get(m.Domain, domain_id)
    if domain is None or domain.account_id != account_id:
        raise ValueError("domain が見つかりません。")

    latest = session.scalar(
        select(func.max(m.KeywordRankHistory.metric_date)).where(
            m.KeywordRankHistory.domain_id == domain_id
        )
    )
    if latest is None:
        return {"domain_id": domain_id, "scored": 0, "alerts": 0, "note": "履歴なし"}

    rows = session.scalars(
        select(m.KeywordRankHistory).where(
            m.KeywordRankHistory.domain_id == domain_id,
            m.KeywordRankHistory.metric_date == latest,
        )
    ).all()

    now = datetime.now(timezone.utc)
    scored = alerts = 0
    prior_target = latest - timedelta(days=7)

    for r in rows:
        pos = float(r.gsc_average_position or 0)
        prev = _position_near(session, domain_id, r.url, r.keyword, prior_target)
        change_7d = (pos - float(prev)) * -1 if prev is not None else None
        # change_7d > 0 means improved (position number went down)

        value, breakdown = _score(
            pos, float(r.impressions or 0), float(r.ctr or 0),
            float(r.search_volume) if r.search_volume else None, change_7d,
            clicks=int(r.clicks or 0),
        )
        _upsert_score(session, account_id, domain_id, r, latest, value, breakdown, now)
        scored += 1

        if prev is not None:
            delta = pos - float(prev)  # positive = got worse
            if delta >= DROP_7D_ALERT:
                alerts += _add_alert(
                    session, account_id, domain_id, r, latest,
                    "position_drop", _severity(delta), float(prev), pos, now
                )
            if float(prev) <= TOP10 < pos:
                alerts += _add_alert(
                    session, account_id, domain_id, r, latest,
                    "dropped_out_of_top10", "high", float(prev), pos, now
                )
            if float(prev) <= TOP3 < pos:
                alerts += _add_alert(
                    session, account_id, domain_id, r, latest,
                    "dropped_out_of_top3", "high", float(prev), pos, now
                )

    session.flush()
    return {"domain_id": domain_id, "date": str(latest), "scored": scored, "alerts": alerts}


def _severity(delta: float) -> str:
    if delta >= 20:
        return "high"
    if delta >= 10:
        return "medium"
    return "low"


def _upsert_score(session, account_id, domain_id, r, date, value, breakdown, now) -> None:
    existing = session.scalar(
        select(m.OpportunityScore).where(
            m.OpportunityScore.domain_id == domain_id,
            m.OpportunityScore.url == r.url,
            m.OpportunityScore.keyword == r.keyword,
            m.OpportunityScore.score_date == date,
        )
    )
    if existing:
        existing.score = value
        existing.component_breakdown_json = breakdown
        existing.post_id = r.post_id
    else:
        session.add(m.OpportunityScore(
            account_id=account_id, domain_id=domain_id, post_id=r.post_id,
            url=r.url, keyword=r.keyword, score_date=date, score=value,
            component_breakdown_json=breakdown, created_at=now,
        ))


def _add_alert(session, account_id, domain_id, r, date, alert_type, severity,
               from_pos, to_pos, now) -> int:
    dupe = session.scalar(
        select(m.RankAlert.id).where(
            m.RankAlert.domain_id == domain_id,
            m.RankAlert.url == r.url,
            m.RankAlert.keyword == r.keyword,
            m.RankAlert.detected_date == date,
            m.RankAlert.alert_type == alert_type,
        )
    )
    if dupe:
        return 0
    session.add(m.RankAlert(
        account_id=account_id, domain_id=domain_id, post_id=r.post_id,
        url=r.url, keyword=r.keyword, detected_date=date, alert_type=alert_type,
        severity=severity, from_position=round(from_pos, 2), to_position=round(to_pos, 2),
        created_at=now,
    ))
    return 1
