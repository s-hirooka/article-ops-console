# Database

PostgreSQL 15+ (Neon free tier in production). Plain `.sql` migrations for now;
Alembic is introduced in P2 when the FastAPI/SQLAlchemy app lands.

## Migrations

| File | What |
|------|------|
| `migrations/0001_multitenant_core.sql` | accounts / users / membership, Google OAuth token store, domains + per-domain prompts, jobs / articles, LLM + API usage ledgers, RankPulse tables re-homed with `account_id`, and Row-Level Security. |

Run against an empty database:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/0001_multitenant_core.sql
```

Prereqs on the target (Neon has both): `CREATE EXTENSION citext;` and
`pgcrypto` (the migration creates `pgcrypto` itself).

## Tenancy model (spec §04, §11)

* Every account-scoped table has a **non-normalised `account_id`** and an RLS
  policy: `account_id = current_setting('app.account_id')::bigint`.
* The API, after checking `account_members`, opens a transaction and runs
  `SET LOCAL app.account_id = '<id>'` before any tenant query. `SET LOCAL`
  scopes the GUC to that transaction, so pooled connections stay clean.
* `accounts` and `account_members` are **not** RLS-guarded (a user can belong to
  several accounts); they are filtered in the query layer by `user_id`.
* The application DB role must be **non-superuser** and **without `BYPASSRLS`**,
  otherwise `FORCE ROW LEVEL SECURITY` is still bypassed.

Defence in depth = base-query `WHERE account_id = ?` **and** RLS **and** a test
that a second account cannot read the first account's rows.

## Secrets at rest

`oauth_tokens.refresh_token_enc`, `domains.anthropic_api_key_enc`,
`domains.wp_app_password_enc` hold **Fernet ciphertext**
(`app/security/crypto.py`). Columns are write-through — the UI never reads them
back. Key material is the `APP_ENCRYPTION_KEY` env var (comma-separated for
rotation, newest first).
