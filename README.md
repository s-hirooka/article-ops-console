# Article Ops Console

複数のWordPressサイトに対して、
SEO分析・AI記事生成・WordPress公開・Search Console分析を
一元管理するためのAI業務自動化Webアプリです。

## What it solves

- キーワード調査の自動化
- SEO分析から記事生成までの効率化
- WordPressへの記事公開自動化
- 複数サイトの一元管理
- AI利用コストの予算管理

## Tech Stack

- Backend: Python / FastAPI / SQLAlchemy
- Frontend: Next.js / Tailwind
- Database: PostgreSQL / Neon
- AI: Anthropic Claude API
- APIs: Google Ads API / Search Console API / WordPress REST API
- Infra: Render / GitHub Actions

## AI / Automation Architecture

Google Ads / GSC
→ keyword analysis
→ opportunity scoring
→ Claude draft generation
→ cost / budget control
→ eyecatch generation
→ WordPress publishing
→ rank monitoring
→ improvement recommendations

Spec (living doc):
https://claude.ai/code/artifact/4264f415-3aff-4a8e-a941-fc43d272b76b

---

## Status — P1: 「Windows依存を外す」

ここから今のREADMEを続ける

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

**Deploy:** step-by-step in [`DEPLOY.md`](DEPLOY.md) (手順1〜8). Needs you to
create GitHub + Neon + Render accounts and a Google Cloud *Web* OAuth client;
everything else is scripted.

## Status — P3: 「記事ウィザード + プロンプト編集 + アカウント運用」

| Piece | State |
|-------|-------|
| Write API (`app/api/routes_write.py`): create domain, prompt versions (PUT, auto-increment), member invite, job create/get, account list | ✅ |
| Job runner (`app/services/jobs.py`) — in-process `BackgroundTasks`, per-job `tenant_session`, status/result/error on the `jobs` row | ✅ |
| Prompt assembly (`app/services/prompt_assembly.py`) — 8 components → one system prompt, built-in defaults for a fresh domain | ✅ |
| Article pipeline (`app/services/article_pipeline.py`) — volume gate → budget precheck → LLM draft → usage ledger → eyecatch → `articles` row | ✅ |
| LLM wrapper (`app/services/llm.py`) — Anthropic streaming + strict-JSON parse; `LLM_FAKE=1` / no key → deterministic offline stub | ✅ |
| Budget enforcement (`app/services/budget.py`, `pricing.py`) — monthly budget (block/warn) + per-job ceiling + usage recording | ✅ |
| `scripts/smoke_p3.py` — 26 checks: domains, prompt versioning, test_prompt + article_generate jobs, threshold gate + force, budget block, owner-only invite, account switching, write-path tenant isolation | ✅ **PASS** |

Real article generation needs `ANTHROPIC_API_KEY` (or a per-domain BYOK key in
`domains.anthropic_api_key_enc`); everything else runs offline.

## Status — P4: 「公開・GSC連携・解析」

| Piece | State |
|-------|-------|
| WordPress publish — `POST /api/articles/{id}/publish`, `app/services/publish.py` (re-render eyecatch → upload media → featured image → create/update post → write back `wp_post_id` / `status` / `eyecatch_url`) | ✅ `WP_FAKE=1` for offline |
| Self-contained WP REST client (`app/integrations/wordpress.py`) | ✅ |
| Google OAuth connect — `GET /oauth/google/start` → `/oauth/google/callback` → `oauth_tokens` (Fernet), `GET /api/oauth/google/status` | ✅ |
| Access-token refresh (`app/integrations/google_token.py`) — decrypt → refresh when stale → re-encrypt | ✅ |
| GSC Search Analytics client (`app/integrations/gsc.py`), `GSC_FAKE=1` | ✅ |
| `rank_sync` job (`app/services/rank_sync.py`) — port of RankPulse's fragment-strip + impression-weighted aggregation → `keyword_rank_history` upsert | ✅ |
| `analysis` job (`app/services/analysis.py`) — compact port of opportunity score + rank alerts → `opportunity_scores` / `rank_alerts` | ✅ |
| `eyecatch` job + shared `app/services/eyecatch_render.py` (used by pipeline + publish) | ✅ |
| `scripts/smoke_p4.py` — 17 checks: generate→publish→re-publish-rejected, rank_sync rows, analysis scores+alerts, eyecatch bytes, oauth status | ✅ **PASS** |

Live use needs: `ANTHROPIC_API_KEY`, a Google OAuth Web client (for
`/oauth/google/start`), and per-domain WordPress creds
(`domains.wp_base_url` / `wp_username` / `wp_app_password_enc`).
OAuth `state` is in-process — keep the Render web service at 1 instance, or add
Redis.

## Status — P5: 「Next.js フロントエンド」

`frontend/` — Next.js (App Router) + Tailwind, calls the FastAPI on Render.
The server-rendered dashboard at `/` stays as a fallback.

| 画面 | |
|------|--|
| `/` | 概要（AI予算 / ドメイン一覧 / 最近のジョブ） |
| `/domains/[id]` | 順位推移グラフ（Recharts）/ 次の打ち手 / アラート / 記事一覧 |
| `/domains/[id]/prompts` | プロンプト編集（Monaco、8コンポーネント、バージョン履歴） |
| `/domains/[id]/new` | 新規記事ウィザード（キーワード → 生成 → WordPress 公開） |
| `/jobs` | ジョブ履歴・詳細 |

静的書き出し（`output: "export"` → `frontend/out/`）。動的ルートは使わず `?id=N`
クエリ方式。Backend に `CORSMiddleware`（既定で `*.onrender.com` / `*.vercel.app` /
localhost 許可、`CORS_ORIGINS` で上書き）。

**Deploy: Render Static Site**（無料・スリープなし）— Root Directory `frontend`,
Build `npm install && npm run build`, Publish `out`, `NEXT_PUBLIC_API_BASE` =
バックエンド URL。詳細は `DEPLOY.md` 手順9。`next build`（静的書き出し）通過済み、
本番 API に接続して確認済み。

Next: 認証、通知、`rank_sync` の定期実行（GitHub Actions ワークフロー）。

## Layout

```
app/
  main.py                       FastAPI entrypoint (+ /healthz)
  config.py                     env settings: GoogleAds / GoogleOAuth / App
  api/
    deps.py                     account resolution + tenant session dep
    routes_read.py              read-only endpoints
    routes_write.py             domains / prompts / members / jobs / publish
    routes_oauth.py             Google connect flow
  services/
    prompt_assembly.py          8 components -> one system prompt
    llm.py                      Anthropic draft (streaming; LLM_FAKE stub)
    pricing.py  budget.py       cost table + monthly/job budget enforcement
    article_pipeline.py         volume gate -> draft -> ledger -> eyecatch -> row
    eyecatch_render.py          deterministic banner -> PNG (pipeline + publish)
    publish.py                  draft -> WordPress post (WP_FAKE stub)
    rank_sync.py  analysis.py   GSC pull -> rank history -> opp scores + alerts
    jobs.py                     enqueue + in-process background runner
  db/
    models.py                   SQLAlchemy 2.0 ORM (mirrors 0001 migration)
    session.py                  engine + tenant_session(account_id)
  web/
    dashboard.py, templates/    server-rendered read-only UI
  integrations/
    google_ads_keywords.py      GenerateKeywordHistoricalMetrics (google-ads lib)
    google_oauth.py             authorization-code flow
    google_token.py             stored refresh token -> live access token
    gsc.py                      Search Console searchAnalytics.query
    wordpress.py                WP REST client (posts + media)
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
  smoke_p3.py                   write API + jobs + budget (offline, LLM_FAKE)
  smoke_p4.py                   publish + rank_sync + analysis (offline, *_FAKE)
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
