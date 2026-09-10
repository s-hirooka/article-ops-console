"""End-to-end smoke test on a throwaway SQLite DB.

Boots the real FastAPI app, runs Alembic to head, seeds a tiny dataset, then
exercises every read endpoint + both dashboard pages. No network, no Postgres.

    python scripts/smoke_api.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for st in (sys.stdout, sys.stderr):
    try:
        st.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_tmp.name}"
os.environ.setdefault("DEV_ACCOUNT_ID", "1")


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")


def _seed() -> None:
    from app.db import models as m
    from app.db.session import SessionLocal

    now = datetime.now()
    with SessionLocal() as s:
        s.add(m.Account(id=1, name="Default"))
        s.add(m.User(id=1, email="o@x.com", email_plain="o@x.com", display_name="Owner"))
        s.flush()
        s.add(m.AccountMember(account_id=1, user_id=1, role="owner"))
        s.add(m.Domain(id=1, account_id=1, domain_key="lifehouse2026",
                       base_url="https://lifehouse2026.com",
                       gsc_site_url="sc-domain:lifehouse2026.com",
                       keyword_threshold=500))
        s.flush()
        s.add(m.DomainPrompt(account_id=1, domain_id=1, component="system_prompt",
                             version=1, body="...", edited_by=1))
        for i in range(3):
            s.add(m.KeywordRankHistory(
                account_id=1, domain_id=1, url="https://lifehouse2026.com/a",
                keyword="収納 アイデア", metric_date=date.today() - timedelta(days=i),
                gsc_average_position=12.0 + i, clicks=2, impressions=40, ctr=0.05,
                search_volume=1600))
        s.add(m.OpportunityScore(
            account_id=1, domain_id=1, url="https://lifehouse2026.com/a",
            keyword="押入れ 収納", score_date=date.today(), score=87.5,
            component_breakdown_json={"volume": 40, "gap": 47.5}))
        s.add(m.RankAlert(
            account_id=1, domain_id=1, url="https://lifehouse2026.com/a",
            keyword="収納 アイデア", detected_date=date.today(),
            alert_type="position_drop", severity="high",
            from_position=11.0, to_position=44.0))
        s.add(m.Article(
            account_id=1, domain_id=1, status="published", title="CD収納アイデア10選",
            slug="cd-storage", wp_post_id=123, target_keyword="cd 収納",
            target_search_volume=6600, published_at=now))
        job = m.Job(id="00000000-0000-0000-0000-000000000001", account_id=1,
                    domain_id=1, kind="analysis", status="succeeded",
                    params_json={}, llm_cost_usd=0)
        s.add(job)
        s.add(m.LlmUsage(account_id=1, domain_id=1, model="claude-sonnet-5",
                         input_tokens=6000, output_tokens=8000, cost_usd=0.092,
                         billing_period=date.today().strftime("%Y-%m")))
        s.add(m.ApiUsage(account_id=1, provider="google_ads", operation="historical_metrics",
                         call_count=3, usage_date=date.today(), meta_json={}))
        s.commit()


def _exercise() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    checks: list[tuple[str, int, str]] = [
        ("/healthz", 200, '"db":true'),
        ("/api/domains", 200, "lifehouse2026"),
        ("/api/domains/1", 200, "prompt_versions"),
        ("/api/domains/1/rank-history?days=30", 200, "収納 アイデア"),
        ("/api/domains/1/opportunities", 200, "押入れ 収納"),
        ("/api/domains/1/alerts", 200, "position_drop"),
        ("/api/domains/1/articles", 200, "CD収納アイデア10選"),
        ("/api/domains/1/recommendations", 200, "new_article_ideas"),
        ("/api/jobs", 200, "analysis"),
        ("/api/usage/llm", 200, '"spent_usd":0.092'),
        ("/api/usage/api", 200, "historical_metrics"),
        ("/", 200, "AI予算"),
        ("/domains/1", 200, "次の打ち手"),
        ("/api/domains/999", 404, ""),
    ]
    failures = 0
    for path, want_status, want_sub in checks:
        r = c.get(path)
        ok = r.status_code == want_status and (want_sub in r.text if want_sub else True)
        print(f"  {'OK ' if ok else 'FAIL'}  {r.status_code:<3} {path}")
        if not ok:
            failures += 1
            if r.status_code != want_status:
                print(f"        expected {want_status}")
            if want_sub and want_sub not in r.text:
                print(f"        missing substring: {want_sub!r}")
    # cross-tenant isolation: account 2 sees nothing
    r = c.get("/api/domains", headers={"X-Account-Id": "2"})
    iso_ok = r.status_code == 200 and r.json() == []
    print(f"  {'OK ' if iso_ok else 'FAIL'}  tenant isolation (account 2 → [])")
    failures += 0 if iso_ok else 1

    if failures:
        raise SystemExit(f"\n❌ {failures} check(s) failed")
    print("\n✅ PASS — all read endpoints + dashboard + isolation")


def main() -> int:
    print(f"db: {os.environ['DATABASE_URL']}")
    _migrate()
    _seed()
    _exercise()
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
