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

Next: **P2** — deploy (Render + Neon), read-only dashboard.

## Layout

```
app/
  config.py                     env-driven settings (Google Ads, Google OAuth)
  integrations/
    google_ads_keywords.py      GenerateKeywordHistoricalMetrics (google-ads lib)
    google_oauth.py             authorization-code flow: authorize / exchange / refresh / revoke
    eyecatch.py                 Pillow banner rendering, Noto Sans JP
  security/
    crypto.py                   Fernet encrypt/decrypt for secrets at rest
  assets/fonts/                 NotoSansJP-VF.ttf (SIL OFL 1.1)
db/
  migrations/0001_multitenant_core.sql
scripts/
  check_keyword_parity.py       google-ads port vs .exe
  check_oauth_crypto.py         Fernet + auth-URL builder (offline)
```

## Local dev

```bash
python -m pip install -r requirements.txt
cp .env.example .env      # fill in APP_ENCRYPTION_KEY; point GOOGLE_ADS_DOTENV at the existing .env
python scripts/check_oauth_crypto.py
python scripts/check_keyword_parity.py      # spends ~1 Google Ads API call
```

Python 3.14 OK (`google-ads` 32.x, Pillow 12.x, cryptography 50.x all have wheels).
