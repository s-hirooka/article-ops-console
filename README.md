# Article Ops Console

Web app to run and monitor the AI article-creation / SEO-analysis pipeline for
multiple WordPress domains, from any computer. Spec (living doc):
<https://claude.ai/code/artifact/4264f415-3aff-4a8e-a941-fc43d272b76b>

Architecture 案3 — **full cloud**, no Windows dependencies. FastAPI backend
(wraps RankPulse) + Next.js frontend, Postgres (Neon), on Render's free tier
first.

## Status — P1: 「Windows依存を外す」

| Sub-task | State |
|----------|-------|
| (a) keyword volume: `KeywordQueryRunner.exe` → `google-ads` Python | ✅ ported + parity-verified (`scripts/check_keyword_parity.py`) |
| (b) local-Chrome OAuth → server-side authorization-code flow | ✅ transport + crypto done, offline-verified (`scripts/check_oauth_crypto.py`); live code-exchange needs a Web OAuth client at deploy |
| (c) Yu Gothic → Noto Sans JP (bundled) in eyecatch generation | ✅ ported (`app/integrations/eyecatch.py`), render-checked |
| (d) `accounts` / `account_members` + `account_id` + RLS | ✅ migration authored (`db/migrations/0001_multitenant_core.sql`); applied at P2 against Neon |

## Status — P2: 「サーバー側 + 読み取り専用ダッシュボード」

| Piece | State |
|-------|-------|
| FastAPI app (`app/main.py`), `/healthz` with DB probe | ✅ |
| SQLAlchemy 2.0 models mirroring the migration (`app/db/models.py`) | ✅ |
| Per-request tenant session — `SET LOCAL app.account_id` on Postgres (`app/db/session.py`) | ✅ |
| Read-only API — domains / rank-history / opportunities / alerts / articles / recommendations / jobs / usage (`app/api/routes_read.py`) | ✅ |
| Server-rendered dashboard + domain detail (`app/web/`) | ✅ styled, light/dark |
| Alembic wired to the raw SQL baseline (`alembic/`) | ✅ |
| `render.yaml` (Render free) + `.github/workflows/rank_sync.yml` (GH Actions cron) | ✅ authored |
| Seed from existing `Sites` (`scripts/seed_from_sites.py`) | ✅ |
| End-to-end smoke on throwaway SQLite (`scripts/smoke_api.py`) | ✅ **PASS** — 14 checks + tenant isolation |

**Deploy blockers (need you):** create Neon (Postgres) + Render accounts, a
Google Cloud *Web* OAuth client, then set env vars per `render.yaml` and
`git push`.

Next: **P3** — article wizard, per-domain prompt editing, account switching /
invites, job triggering.

## Layout

```
app/
  main.py                       FastAPI entrypoint (+ /healthz)
  config.py                     env settings: GoogleAds / GoogleOAuth / App
  api/
    deps.py                     account resolution + tenant session dep
    routes_read.py              read-only endpoints
  db/
    models.py                   SQLAlchemy 2.0 ORM (mirrors 0001 migration)
    session.py                  engine + tenant_session(account_id)
  web/
    dashboard.py, templates/    server-rendered read-only UI
  integrations/
    google_ads_keywords.py      GenerateKeywordHistoricalMetrics (google-ads lib)
    google_oauth.py             authorization-code flow
    eyecatch.py                 Pillow banner rendering, Noto Sans JP
  security/crypto.py            Fernet encrypt/decrypt for secrets at rest
  assets/fonts/                 NotoSansJP-VF.ttf (SIL OFL 1.1)
alembic/                        migrations runner (baseline = db/migrations/0001)
db/migrations/0001_multitenant_core.sql
render.yaml   .github/workflows/rank_sync.yml
scripts/
  check_keyword_parity.py       google-ads port vs .exe
  check_oauth_crypto.py         Fernet + auth-URL builder (offline)
  seed_from_sites.py            Sites → accounts/domains
  smoke_api.py                  boot app on SQLite, hit every read route
```

## Local dev

```bash
python -m pip install -r requirements.txt
cp .env.example .env      # APP_ENCRYPTION_KEY; DATABASE_URL (omit → ./local.db SQLite); GOOGLE_ADS_DOTENV
python scripts/smoke_api.py                 # no network
python scripts/check_oauth_crypto.py        # no network
python scripts/check_keyword_parity.py      # spends ~1 Google Ads API call

# run the app
alembic upgrade head
python scripts/seed_from_sites.py
uvicorn app.main:app --reload               # http://localhost:8000
```

Local dev runs on SQLite; **production must be Postgres** (RLS). Python 3.14 OK
locally; `render.yaml` pins 3.12 (widest wheel coverage).
