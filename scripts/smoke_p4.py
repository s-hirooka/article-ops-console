"""P4 smoke: WordPress publish, GSC rank-sync, analysis, eyecatch — all offline.

WP_FAKE=1 / GSC_FAKE=1 / LLM_FAKE=1 so nothing leaves the box.
"""
from __future__ import annotations

import os
import sys
import tempfile
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
os.environ.update(
    DATABASE_URL=f"sqlite+pysqlite:///{_tmp.name}",
    DEV_ACCOUNT_ID="1",
    LLM_FAKE="1",
    WP_FAKE="1",
    GSC_FAKE="1",
    GADS_FAKE="1",
)

_fail = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global _fail
    print(f"  {'OK  ' if cond else 'FAIL'} {name}{'  ' + extra if extra and not cond else ''}")
    if not cond:
        _fail += 1


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")


def _seed() -> None:
    from app.db import models as m
    from app.db.session import SessionLocal

    with SessionLocal() as s:
        s.add(m.Account(id=1, name="Default", llm_monthly_budget_usd=50,
                        llm_job_ceiling_usd=5, draft_model="claude-sonnet-5"))
        s.add(m.User(id=1, email="o@x.com", email_plain="o@x.com"))
        s.flush()
        s.add(m.AccountMember(account_id=1, user_id=1, role="owner"))
        s.add(m.Domain(id=1, account_id=1, domain_key="lifehouse2026",
                       base_url="https://lifehouse2026.com",
                       gsc_site_url="sc-domain:lifehouse2026.com",
                       wp_base_url="https://lifehouse2026.com",
                       wp_username="editor", wp_app_password_enc=None,
                       keyword_threshold=500))
        s.commit()


def main() -> int:
    print(f"db: {os.environ['DATABASE_URL']}")
    _migrate()
    _seed()

    from fastapi.testclient import TestClient
    from app.main import app

    c = TestClient(app)
    H = {"X-User-Id": "1"}

    # --- article -> publish -------------------------------------------------
    r = c.post("/api/jobs", headers=H, json={
        "kind": "article_generate", "domain_id": 1,
        "params": {"target_keyword": "CD 収納", "search_volume": 1600}})
    jid = r.json()["job_id"]
    art_id = c.get(f"/api/jobs/{jid}").json()["result"]["article_id"]
    check("article generated", isinstance(art_id, int))

    r = c.post(f"/api/articles/{art_id}/publish", headers=H, json={"status": "publish"})
    check("POST publish -> 200", r.status_code == 200, r.text)
    pub = r.json()
    check("  wp_post_id assigned", bool(pub.get("wp_post_id")))
    check("  link returned", bool(pub.get("link")))

    a = next(a for a in c.get("/api/domains/1/articles").json() if a["id"] == art_id)
    check("article now 'published'", a["status"] == "published", str(a))

    r = c.post(f"/api/articles/{art_id}/publish", headers=H, json={"status": "publish"})
    check("re-publish rejected -> 422", r.status_code == 422)

    # --- rank_sync -------------------------------------------------------
    r = c.post("/api/jobs", headers=H, json={"kind": "rank_sync", "domain_id": 1})
    j = c.get(f"/api/jobs/{r.json()['job_id']}").json()
    check("rank_sync succeeded", j["status"] == "succeeded", str(j))
    check("  rows written > 0", (j["result"] or {}).get("rows_written", 0) > 0, str(j))

    rh = c.get("/api/domains/1/rank-history?days=3650").json()
    check("rank-history endpoint shows rows", len(rh) > 0)

    # --- analysis -----------------------------------------------------
    r = c.post("/api/jobs", headers=H, json={"kind": "analysis", "domain_id": 1})
    j = c.get(f"/api/jobs/{r.json()['job_id']}").json()
    check("analysis succeeded", j["status"] == "succeeded", str(j))
    check("  scored > 0", (j["result"] or {}).get("scored", 0) > 0, str(j))
    check("  alerts is int", isinstance((j["result"] or {}).get("alerts"), int))

    opp = c.get("/api/domains/1/opportunities").json()
    check("opportunities endpoint shows scores", len(opp) > 0)
    check("  breakdown carries weights",
          bool(opp and opp[0]["component_breakdown_json"].get("weights")))

    rec = c.get("/api/domains/1/recommendations").json()
    check("recommendations computed", "improvement_candidates" in rec and "declining" in rec)

    # --- topic ideas (新規テーマ) ----------------------------------
    r = c.post("/api/domains/1/topic-ideas", headers=H, json={"seeds": ["すきま収納"], "limit": 10})
    check("topic-ideas -> 200", r.status_code == 200, r.text)
    ti = r.json()
    kws = [x["keyword"] for x in ti["candidates"]]
    norm = [k.replace(" ", "") for k in kws]
    check("  candidates present", len(kws) >= 2, str(kws))
    check("  permutations deduped", sum(1 for n in norm if "収納アイデア" in n) <= 1, str(kws))
    check("  below-threshold excluded", not any("低予算" in k for k in kws))
    check("  already-ranked excluded (収納アイデア in GSC fake)", "収納アイデア" not in norm, str(kws))
    check("  api_usage recorded", any(
        u["provider"] == "google_ads" and u["operation"] == "keyword_ideas"
        for u in c.get("/api/usage/api").json()
    ))

    # --- eyecatch job -----------------------------------------------
    r = c.post("/api/jobs", headers=H, json={
        "kind": "eyecatch", "domain_id": 1,
        "params": {"title": "すきま収納アイデア", "style": {"preset": "navy_check"}}})
    j = c.get(f"/api/jobs/{r.json()['job_id']}").json()
    check("eyecatch job produced bytes", (j["result"] or {}).get("bytes", 0) > 2000, str(j))

    # --- oauth status (not connected) --------------------------------
    r = c.get("/api/oauth/google/status")
    check("oauth status -> not connected", r.status_code == 200 and r.json()["connected"] is False)

    try:
        os.unlink(_tmp.name)
    except OSError:
        pass

    if _fail:
        print(f"\n❌ {_fail} check(s) failed")
        return 1
    print("\n✅ PASS — P4 publish + rank_sync + analysis + eyecatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
