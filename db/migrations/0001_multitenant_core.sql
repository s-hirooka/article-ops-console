-- =============================================================================
-- 0001_multitenant_core  —  Article Ops Console
-- PostgreSQL 15+ (Neon).  Idempotent-ish: safe to run once on an empty database.
--
-- Establishes:
--   * account / user / membership core           (spec §04)
--   * per-account Google OAuth token storage      (spec §02, §09)
--   * domains + per-domain editable prompts       (spec §05)
--   * jobs / articles / LLM + API usage ledgers   (spec §06, §04 AI予算)
--   * RankPulse tables, re-homed with account_id  (spec §09 ALTER ...)
--   * Row-Level Security keyed on app.account_id  (spec §11)
--
-- Every account-scoped table carries a non-normalised account_id and an RLS
-- policy `account_id = current_setting('app.account_id')::bigint`. The API sets
--   SET LOCAL app.account_id = '<id>';
-- at the start of each transaction, after checking account_members.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- --- helper: updated_at trigger --------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 1. Accounts / users / membership
-- =============================================================================
CREATE TABLE accounts (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name                text        NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),

  -- AI budget (spec §04 「AI予算」) — defaults are the product-wide guard rails
  llm_monthly_budget_usd  numeric(10,2) NOT NULL DEFAULT 20.00,
  llm_budget_action       text          NOT NULL DEFAULT 'block'
                          CHECK (llm_budget_action IN ('block','warn')),
  llm_job_ceiling_usd     numeric(10,2) NOT NULL DEFAULT 2.00,
  draft_model             text          NOT NULL DEFAULT 'claude-sonnet-5'
);

CREATE TABLE users (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email         citext,                         -- see note below re: citext
  email_plain   text        NOT NULL UNIQUE,    -- fallback if citext unavailable
  display_name  text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
-- If the `citext` extension is not enabled on the target, drop the citext column
-- and rely on email_plain + lower() uniqueness. Neon supports citext:
--   CREATE EXTENSION IF NOT EXISTS citext;  (run before this migration)

CREATE TABLE account_members (
  account_id  bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  user_id     bigint NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
  role        text   NOT NULL CHECK (role IN ('owner','editor','viewer')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, user_id)
);
CREATE INDEX account_members_user_idx ON account_members(user_id);

-- =============================================================================
-- 2. Google OAuth tokens (one connection per account per provider scope-set)
-- =============================================================================
CREATE TABLE oauth_tokens (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id         bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  provider           text   NOT NULL DEFAULT 'google',
  google_email       text,
  scopes             text   NOT NULL,               -- space-joined
  refresh_token_enc  text   NOT NULL,               -- Fernet ciphertext (write-through)
  access_token_enc   text,
  access_expires_at  timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, provider)
);
CREATE TRIGGER oauth_tokens_touch BEFORE UPDATE ON oauth_tokens
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 3. Domains (supersedes KeywordInsightService.Sites) + per-domain prompts
-- =============================================================================
CREATE TABLE domains (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id     bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  domain_key     text   NOT NULL,                    -- was Sites.SiteKey
  base_url       text   NOT NULL,                    -- was Sites.BaseUrl
  gsc_site_url   text   NOT NULL,                    -- was Sites.GscSiteUrl

  wp_base_url    text,
  wp_username    text,
  wp_app_password_enc text,                          -- Fernet ciphertext

  -- BYOK: per-domain Anthropic key overrides the account key (spec §04)
  anthropic_api_key_enc text,

  keyword_threshold      integer NOT NULL DEFAULT 500,   -- monthly-search floor
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, domain_key)
);
CREATE INDEX domains_account_idx ON domains(account_id);
CREATE TRIGGER domains_touch BEFORE UPDATE ON domains
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 8 editable components (spec §05). Versioned: history kept, newest = MAX(version).
CREATE TABLE domain_prompts (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id    bigint NOT NULL REFERENCES accounts(id)  ON DELETE CASCADE,
  domain_id     bigint NOT NULL REFERENCES domains(id)   ON DELETE CASCADE,
  component     text   NOT NULL CHECK (component IN (
                  'system_prompt','article_structure','product_block_spec',
                  'vc_auto_ads_defaults','eyecatch_style','internal_link_policy',
                  'title_format','keyword_threshold')),
  version       integer NOT NULL,
  body          text    NOT NULL,
  edited_by     bigint  REFERENCES users(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (domain_id, component, version)
);
CREATE INDEX domain_prompts_lookup_idx
  ON domain_prompts(domain_id, component, version DESC);

-- =============================================================================
-- 4. Jobs + articles
-- =============================================================================
CREATE TABLE jobs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id    bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  domain_id     bigint REFERENCES domains(id) ON DELETE SET NULL,
  kind          text   NOT NULL CHECK (kind IN (
                  'article_generate','rank_sync','analysis','eyecatch','test_prompt')),
  status        text   NOT NULL DEFAULT 'queued' CHECK (status IN (
                  'queued','running','succeeded','failed','cancelled')),
  params_json   jsonb  NOT NULL DEFAULT '{}'::jsonb,
  result_json   jsonb,
  error         text,
  llm_cost_usd  numeric(10,4) NOT NULL DEFAULT 0,
  created_by    bigint REFERENCES users(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  started_at    timestamptz,
  finished_at   timestamptz
);
CREATE INDEX jobs_account_created_idx ON jobs(account_id, created_at DESC);
CREATE INDEX jobs_status_idx ON jobs(status) WHERE status IN ('queued','running');

CREATE TABLE articles (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id    bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  domain_id     bigint NOT NULL REFERENCES domains(id)  ON DELETE CASCADE,
  job_id        uuid   REFERENCES jobs(id) ON DELETE SET NULL,
  wp_post_id    integer,
  status        text   NOT NULL DEFAULT 'draft' CHECK (status IN (
                  'draft','published','failed')),
  target_keyword       text,
  target_search_volume integer,
  title         text,
  slug          text,
  body_html     text,
  eyecatch_url  text,
  meta_json     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  published_at  timestamptz
);
CREATE INDEX articles_domain_idx ON articles(domain_id, created_at DESC);
CREATE TRIGGER articles_touch BEFORE UPDATE ON articles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 5. Usage ledgers
-- =============================================================================
CREATE TABLE llm_usage (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id         bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  domain_id          bigint REFERENCES domains(id) ON DELETE SET NULL,
  job_id             uuid   REFERENCES jobs(id) ON DELETE SET NULL,
  model              text   NOT NULL,
  input_tokens       integer NOT NULL DEFAULT 0,
  output_tokens      integer NOT NULL DEFAULT 0,
  cache_read_tokens  integer NOT NULL DEFAULT 0,
  cache_write_tokens integer NOT NULL DEFAULT 0,
  cost_usd           numeric(10,6) NOT NULL DEFAULT 0,
  billing_period     text   NOT NULL,          -- 'YYYY-MM' for cheap budget sums
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_usage_budget_idx ON llm_usage(account_id, billing_period);

CREATE TABLE api_usage (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id     bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  provider       text   NOT NULL CHECK (provider IN (
                   'google_ads','search_console','wordpress','product_feed')),
  operation      text   NOT NULL,
  call_count     integer NOT NULL DEFAULT 1,
  usage_date     date   NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Tokyo')::date,
  meta_json      jsonb  NOT NULL DEFAULT '{}'::jsonb,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX api_usage_daily_idx
  ON api_usage(account_id, provider, operation, usage_date);
-- replaces KeywordInsightService DailyUsageLimiter / daily_usage.json

-- =============================================================================
-- 6. RankPulse tables — re-homed from keyword_metrics.db (SQLite) with
--    account_id + domain_id. Column names kept close to the originals so the
--    P2 data migration is a straight copy.  (spec §09 "ALTER ... ADD account_id")
-- =============================================================================
CREATE TABLE keyword_metrics_history (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id            bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  keyword               text    NOT NULL,
  avg_monthly_searches  integer,
  competition_level     text,
  competition_index     integer,
  low_top_of_page_bid   numeric(12,6),
  high_top_of_page_bid  numeric(12,6),
  retrieved_at          timestamptz NOT NULL
);
CREATE INDEX kmh_account_kw_idx ON keyword_metrics_history(account_id, keyword, retrieved_at DESC);

CREATE TABLE keyword_rank_history (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id            bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  domain_id             bigint NOT NULL REFERENCES domains(id)  ON DELETE CASCADE,
  post_id               integer,
  url                   text NOT NULL,
  keyword               text NOT NULL,
  metric_date           date NOT NULL,
  gsc_average_position  numeric(6,2),
  serp_rank             integer,
  clicks                integer NOT NULL DEFAULT 0,
  impressions           integer NOT NULL DEFAULT 0,
  ctr                   numeric(6,4) NOT NULL DEFAULT 0,
  search_volume         integer,
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (domain_id, url, keyword, metric_date)
);
CREATE INDEX krh_domain_date_idx ON keyword_rank_history(domain_id, metric_date DESC);

CREATE TABLE opportunity_scores (
  id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id              bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  domain_id               bigint NOT NULL REFERENCES domains(id)  ON DELETE CASCADE,
  post_id                 integer,
  url                     text NOT NULL,
  keyword                 text NOT NULL,
  score_date              date NOT NULL,
  score                   numeric(8,4) NOT NULL,
  component_breakdown_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (domain_id, url, keyword, score_date)
);
CREATE INDEX os_domain_score_idx ON opportunity_scores(domain_id, score_date DESC, score DESC);

CREATE TABLE rank_alerts (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id     bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  domain_id      bigint NOT NULL REFERENCES domains(id)  ON DELETE CASCADE,
  post_id        integer,
  url            text NOT NULL,
  keyword        text NOT NULL,
  detected_date  date NOT NULL,
  alert_type     text NOT NULL,
  severity       text NOT NULL,
  from_position  numeric(6,2),
  to_position    numeric(6,2),
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ra_domain_detected_idx ON rank_alerts(domain_id, detected_date DESC);

CREATE TABLE rewrite_history (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id          bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  domain_id           bigint NOT NULL REFERENCES domains(id)  ON DELETE CASCADE,
  post_id             integer NOT NULL,
  url                 text NOT NULL,
  change_date         date NOT NULL,
  title_before        text,
  title_after         text,
  change_types_json   jsonb NOT NULL DEFAULT '[]'::jsonb,
  target_keyword      text,
  position_before     numeric(6,2),
  ctr_before          numeric(6,4),
  clicks_before       integer,
  impressions_before  integer,
  notes               text,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX rw_domain_change_idx ON rewrite_history(domain_id, change_date DESC);

-- =============================================================================
-- 7. Row-Level Security
-- =============================================================================
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'oauth_tokens','domains','domain_prompts','jobs','articles',
    'llm_usage','api_usage','keyword_metrics_history','keyword_rank_history',
    'opportunity_scores','rank_alerts','rewrite_history'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', t);
    EXECUTE format($f$
      CREATE POLICY %1$s_isolation ON %1$I
        USING (account_id = current_setting('app.account_id')::bigint)
        WITH CHECK (account_id = current_setting('app.account_id')::bigint);
    $f$, t);
  END LOOP;
END $$;

-- accounts / account_members are filtered in the query layer (a user may belong
-- to several accounts); they are not RLS-guarded on account_id.

COMMIT;

-- =============================================================================
-- Per-request preamble the API must run inside every transaction:
--
--   SET LOCAL app.account_id = :account_id;   -- after verifying membership
--
-- The DB role used by the app must NOT be a superuser and must NOT have BYPASSRLS.
-- =============================================================================
