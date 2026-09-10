"""P3 smoke: write API + job runner + budget enforcement, all offline.

LLM_FAKE=1 so no Anthropic spend. Starlette's TestClient runs BackgroundTasks
synchronously, so a job is finished by the time POST /api/jobs returns.
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
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_tmp.name}"
os.environ["DEV_ACCOUNT_ID"] = "1"
os.environ["LLM_FAKE"] = "1"

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
        s.add(m.Account(id=1, name="Default", llm_monthly_budget_usd=20,
                        llm_job_ceiling_usd=2, llm_budget_action="block",
                        draft_model="claude-sonnet-5"))
        s.add(m.Account(id=2, name="Other"))
        s.add(m.User(id=1, email="owner@x.com", email_plain="owner@x.com"))
        s.flush()
        s.add(m.AccountMember(account_id=1, user_id=1, role="owner"))
        s.add(m.Domain(id=1, account_id=1, domain_key="seed",
                       base_url="https://seed.example", gsc_site_url="sc-domain:seed.example",
                       keyword_threshold=500))
        s.commit()


def main() -> int:
    print(f"db: {os.environ['DATABASE_URL']}")
    _migrate()
    _seed()

    from fastapi.testclient import TestClient
    from app.main import app

    c = TestClient(app)
    OWNER = {"X-User-Id": "1"}

    # 1. create domain
    r = c.post("/api/domains", headers=OWNER, json={
        "domain_key": "lifehouse2026", "base_url": "https://lifehouse2026.com",
        "gsc_site_url": "sc-domain:lifehouse2026.com", "keyword_threshold": 500})
    check("POST /api/domains -> 201", r.status_code == 201, r.text)
    did = r.json().get("id")
    check("  domain id returned", isinstance(did, int))

    r = c.post("/api/domains", headers=OWNER, json={
        "domain_key": "lifehouse2026", "base_url": "x", "gsc_site_url": "y"})
    check("duplicate domain_key -> 409", r.status_code == 409)

    # 2. prompt versions
    for i, txt in enumerate(["最初の版", "改訂版"], start=1):
        r = c.put(f"/api/domains/{did}/prompts/system_prompt", headers=OWNER,
                  json={"body": txt})
        check(f"PUT prompt v{i} -> 201", r.status_code == 201 and r.json()["version"] == i, r.text)
    r = c.put(f"/api/domains/{did}/prompts/bogus_component", headers=OWNER, json={"body": "x"})
    check("unknown component -> 422", r.status_code == 422)

    r = c.get(f"/api/domains/{did}/prompts")
    check("GET prompts shows v2 body", r.json().get("system_prompt", {}).get("version") == 2, r.text)
    r = c.get(f"/api/domains/{did}/prompts/system_prompt/history")
    check("history has 2 entries", len(r.json()) == 2)

    # 3. test_prompt job
    r = c.post("/api/jobs", headers=OWNER, json={"kind": "test_prompt", "domain_id": did})
    check("POST test_prompt job -> 202", r.status_code == 202, r.text)
    jid = r.json()["job_id"]
    r = c.get(f"/api/jobs/{jid}")
    j = r.json()
    check("test_prompt job succeeded", j["status"] == "succeeded", str(j))
    check("  system_preview present + uses改訂版",
          "改訂版" in (j["result"] or {}).get("system_preview", ""))

    # 4. article_generate job (fake LLM), volume supplied
    r = c.post("/api/jobs", headers=OWNER, json={
        "kind": "article_generate", "domain_id": did,
        "params": {"target_keyword": "CD 収納", "search_volume": 1600}})
    check("POST article_generate -> 202", r.status_code == 202, r.text)
    jid = r.json()["job_id"]
    j = c.get(f"/api/jobs/{jid}").json()
    check("article job succeeded", j["status"] == "succeeded", str(j))
    res = j.get("result") or {}
    check("  article_id present", isinstance(res.get("article_id"), int))
    check("  faked draft", res.get("faked") is True)
    check("  cost recorded > 0", (j.get("llm_cost_usd") or 0) > 0)

    r = c.get(f"/api/domains/{did}/articles")
    check("article shows in list as draft",
          any(a["status"] == "draft" and a["title"] for a in r.json()), r.text)

    r = c.get("/api/usage/llm")
    check("usage/llm spent matches job cost",
          abs(r.json()["spent_usd"] - (j["llm_cost_usd"])) < 1e-6, r.text)

    # 5. threshold gate: low volume, no force -> job fails
    r = c.post("/api/jobs", headers=OWNER, json={
        "kind": "article_generate", "domain_id": did,
        "params": {"target_keyword": "すごい ニッチ", "search_volume": 90}})
    j = c.get(f"/api/jobs/{r.json()['job_id']}").json()
    check("below-threshold job fails", j["status"] == "failed" and "閾値" in (j["error"] or ""), str(j))
    # with force -> succeeds
    r = c.post("/api/jobs", headers=OWNER, json={
        "kind": "article_generate", "domain_id": did,
        "params": {"target_keyword": "すごい ニッチ", "search_volume": 90, "force": True}})
    j = c.get(f"/api/jobs/{r.json()['job_id']}").json()
    check("force overrides threshold", j["status"] == "succeeded", str(j))

    # 6. budget block
    from app.db import models as m
    from app.db.session import SessionLocal
    with SessionLocal() as s:
        s.get(m.Account, 1).llm_monthly_budget_usd = 0
        s.commit()
    r = c.post("/api/jobs", headers=OWNER, json={
        "kind": "article_generate", "domain_id": did,
        "params": {"target_keyword": "予算 テスト", "search_volume": 1600}})
    j = c.get(f"/api/jobs/{r.json()['job_id']}").json()
    check("budget block stops job", j["status"] == "failed" and "予算" in (j["error"] or ""), str(j))

    # 7. member invite + account switching
    r = c.post("/api/accounts/1/members", headers=OWNER,
               json={"email": "editor@x.com", "role": "editor"})
    check("owner invites editor -> 201", r.status_code == 201, r.text)
    new_uid = r.json()["user_id"]
    r = c.get("/api/accounts", headers={"X-User-Id": str(new_uid)})
    check("invited user sees the account",
          any(a["id"] == 1 and a["role"] == "editor" for a in r.json()), r.text)
    r = c.post("/api/accounts/1/members", headers={"X-User-Id": str(new_uid)},
               json={"email": "z@x.com", "role": "viewer"})
    check("non-owner cannot invite -> 403", r.status_code == 403)

    # 8. tenant isolation on writes
    r = c.post("/api/domains", headers={"X-Account-Id": "2", "X-User-Id": "1"}, json={
        "domain_key": "acct2-only", "base_url": "x", "gsc_site_url": "y"})
    check("create domain under account 2 -> 201", r.status_code == 201)
    r = c.get("/api/domains")  # account 1
    check("account 1 does not see account 2's domain",
          all(d["domain_key"] != "acct2-only" for d in r.json()))

    try:
        os.unlink(_tmp.name)
    except OSError:
        pass

    if _fail:
        print(f"\n❌ {_fail} check(s) failed")
        return 1
    print("\n✅ PASS — P3 write API + jobs + budget + invites + isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
