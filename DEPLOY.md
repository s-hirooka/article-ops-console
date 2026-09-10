# デプロイ手順（Render 無料枠 + Neon 無料枠）

所要時間の目安: 40〜60分。無料アカウントの作成が3つ（GitHub / Neon / Render）と、
Google Cloud の OAuth クライアント設定が必要です。

> 記号: 🧑 = あなたの操作 / 🤖 = Claude に頼めば代行できる部分

---

## 事前チェック

- ローカルに Python 3.12 系が使えること（3.14 でも開発は動くが、Render は 3.12 を使う）
- `article-ops-console/` で `python scripts/smoke_api.py` が ✅ になること
- `G:\KeywordInsightService\.env` に Google Ads の認証情報が入っていること（既存）

---

## 手順 1 — GitHub にリポジトリを push 🧑（コマンドは 🤖）

Render は GitHub 連携でデプロイします。まず空のリポジトリを作って push します。

1. GitHub で新規リポジトリを作成（例: `article-ops-console`）。**README や .gitignore は追加しない**（空で作る）。
2. ローカルでリモートを追加して push:

   ```bash
   cd G:/WordPressAPI/article-ops-console
   git remote add origin https://github.com/<あなた>/article-ops-console.git
   git push -u origin master
   ```

   `master` のままで問題ありません（Render はブランチ名を問いません）。

> 秘密情報は入っていません（`.gitignore` で `.env` 等を除外済み）。フォント
> `NotoSansJP-VF.ttf`（9.6MB, SIL OFL）は意図的に同梱しています。

---

## 手順 2 — Neon で Postgres を用意 🧑（Claude 実行済み: 2026-09-10）

Render の無料 Postgres は30日で消えるため、外部の Neon（無料・期限なし）を使います。
リージョンは Render と揃える（今回は **Singapore / ap-southeast-1**）。

**2つのロールを使い分けます**（重要）:

| ロール | 用途 | RLS |
|--------|------|-----|
| `neondb_owner` | マイグレーション（DDL）専用。**アプリには使わない** | `BYPASSRLS` を持つ = テナント分離が効かない |
| `app_user` | アプリ実行時の `DATABASE_URL` | `NOBYPASSRLS` = RLS でアカウント分離が効く |

1. <https://neon.tech> → **New Project**（名 `article-ops-console`、Singapore）。
2. `neondb_owner` の **Connection string** を控える（マイグレーション用）。
3. **SQL Editor** で拡張と `app_user` を作成:

   ```sql
   CREATE EXTENSION IF NOT EXISTS citext;

   CREATE ROLE app_user WITH LOGIN PASSWORD '<強いパスワード>'
     NOBYPASSRLS NOSUPERUSER NOCREATEROLE NOCREATEDB;
   GRANT USAGE ON SCHEMA public TO app_user;
   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
   GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public
     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public
     GRANT USAGE, SELECT ON SEQUENCES TO app_user;
   ```

   > `GRANT ... ON ALL TABLES` はスキーマ再作成で失われます。マイグレーションを
   > やり直したら `ALTER DEFAULT PRIVILEGES` 以外の GRANT を再実行してください。

4. 接続文字列は用途別に2本用意する:
   - **マイグレーション用**（`neondb_owner`、`-pooler` なしの直結を推奨）
     → 手順7で `MIGRATION_DATABASE_URL` として使う
   - **アプリ実行用**（`app_user`、`-pooler` 付き）
     → 手順5で Render の `DATABASE_URL` に設定

   どちらも `postgresql://.../neondb?sslmode=require` の形。アプリ側で
   `postgresql+psycopg://` に自動変換されます。

> Claude が 2026-09-10 に手順7まで実行済み: マイグレーション適用（15テーブル +
> RLS 12ポリシー）、`app_user` 作成、既存2ドメイン投入、RLS 分離をアプリ経由で確認。

---

## 手順 3 — Anthropic API キーと上限額 🧑

1. <https://console.anthropic.com> → **API Keys** → 新規キー発行。これが `ANTHROPIC_API_KEY`。
2. 同じコンソールの **Billing / Limits** で**毎月の上限額（hard limit）**を設定。
   これはアプリの予算ガード（月予算 / 1ジョブ上限）とは別の、最終防波堤です。
3. アプリ側の既定値（変更はデプロイ後に DB で）:
   - 月予算 `llm_monthly_budget_usd` = $20（超過時 `block`）
   - 1ジョブ上限 `llm_job_ceiling_usd` = $2
   - 既定モデル `claude-sonnet-5`（長文記事1本あたり約 $0.09）

---

## 手順 4 — 暗号鍵を生成 🤖（1コマンド）

OAuth リフレッシュトークンや WordPress パスワードを暗号化して保存するための鍵です。

```bash
cd G:/WordPressAPI/article-ops-console
python -c "from app.security.crypto import generate_key; print(generate_key())"
```

出力された1行が `APP_ENCRYPTION_KEY`。**紛失すると保存済みトークンが復号できません**。
1Password 等に控えておく。将来ローテーションする時はカンマ区切りで新しい鍵を先頭に置く。

---

## 手順 5 — Render で Web サービスを作成 🧑

1. <https://render.com> でサインアップ → GitHub 連携を許可。
2. **New +** → **Blueprint** → 手順1のリポジトリを選択。`render.yaml` が読み込まれる。
3. サービス名を決める（例: `article-ops-console`）。URL が
   `https://article-ops-console.onrender.com` のように確定する。**この URL を手順6で使う。**
4. **Environment** で環境変数を設定（`render.yaml` の `sync: false` の項目）:

   | 変数 | 値 |
   |------|-----|
   | `DATABASE_URL` | 手順2の **`app_user`（`-pooler` 付き）** 接続文字列。`neondb_owner` を入れないこと |
   | `APP_ENCRYPTION_KEY` | 手順4で生成した鍵 |
   | `ANTHROPIC_API_KEY` | 手順3のキー |
   | `GOOGLE_ADS_DEVELOPER_TOKEN` | `G:\KeywordInsightService\.env` から |
   | `GOOGLE_ADS_OAUTH2_CLIENT_ID` | 同上 |
   | `GOOGLE_ADS_OAUTH2_CLIENT_SECRET` | 同上 |
   | `GOOGLE_ADS_OAUTH2_REFRESH_TOKEN` | 同上 |
   | `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | 同上（数字のみでも可） |
   | `GOOGLE_ADS_DEFAULT_CUSTOMER_ID` | 同上 |
   | `GOOGLE_OAUTH_REDIRECT_URI` | `https://<サービス名>.onrender.com/oauth/google/callback` |
   | `GOOGLE_OAUTH_CLIENT_ID` | （手順6で作成、後から追加でも可） |
   | `GOOGLE_OAUTH_CLIENT_SECRET` | 同上 |

5. デプロイ実行。ビルドは `pip install -r requirements.txt` のみ。
   **マイグレーションはビルドで走りません**（`app_user` に DDL 権限がないため）。
   スキーマは手順7でワークステーションから適用します（初回は Claude が実施済み）。
6. デプロイ完了後、`https://<サービス名>.onrender.com/healthz` を開いて
   `{"status":"ok","db":true}` を確認。

> 無料枠の注意: 15分アクセスがないとスリープし、次回アクセスで30〜60秒のコールドスタート。
> RAM 512MB / 0.1CPU。OAuth の `state` はメモリ保持なので**インスタンスは1つのまま**にする。

---

## 手順 6 — Google Cloud で「ウェブアプリケーション」OAuth クライアント 🧑

既存の Google Ads 用クライアント（デスクトップアプリ型）とは別に、サーバー用の
Web クライアントが必要です。

1. <https://console.cloud.google.com> → 既存の Google Ads と**同じプロジェクト**を選択。
2. **API とサービス** → **OAuth 同意画面**:
   - User Type: **External**
   - スコープに以下を追加:
     - `https://www.googleapis.com/auth/webmasters.readonly`（Search Console）
     - `https://www.googleapis.com/auth/adwords`（Google Ads）
   - **公開ステータス**: 「本番環境」に**公開**することを推奨。
     - 理由: 「テスト」のままだとリフレッシュトークンが**7日で失効**し、毎週再連携が必要。
     - 本番公開しても、利用者が自分だけなら Google の審査は不要。連携時に
       「確認されていないアプリ」警告が出るが「詳細」→「移動」で進めます。
3. **認証情報** → **認証情報を作成** → **OAuth クライアント ID**:
   - アプリケーションの種類: **ウェブ アプリケーション**
   - 承認済みのリダイレクト URI:
     `https://<サービス名>.onrender.com/oauth/google/callback`
   - 作成後の**クライアント ID / シークレット**を Render の
     `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` に設定 →再デプロイ。

---

## 手順 7 — スキーマ適用・初期データ・接続 🧑（7-1/7-2 は Claude 実施済み）

すべてローカルの端末から実行します（`seed_from_sites.py` は
`G:\KeywordInsightService\keyword_metrics.db` を読むため、Render 上では動かない）。
**マイグレーションだけ `neondb_owner`、それ以外は `app_user` でも可**。

```bash
cd G:/WordPressAPI/article-ops-console

# 7-0. スキーマ適用（owner 接続で。以後スキーマ変更時も同じ）
export MIGRATION_DATABASE_URL="postgresql://neondb_owner:...@ep-xxxx.<region>.aws.neon.tech/neondb?sslmode=require"
python -m alembic upgrade head
#   スキーマを作り直した場合は app_user の GRANT を再実行（手順2の GRANT 5行）

export DATABASE_URL="postgresql://app_user:...@ep-xxxx-pooler.<region>.aws.neon.tech/neondb?sslmode=require"
export APP_ENCRYPTION_KEY="手順4の鍵"

# 7-1. 既存2ドメイン（Sites）を accounts/domains に取り込み  ← 実施済み
python scripts/seed_from_sites.py --owner-email s.hirooka.ceo@gmail.com

# 7-2. ドメインごとに WordPress 認証情報を登録  ← あなたが実施
python scripts/set_domain_secret.py --domain lifehouse2026 \
  --wp-base-url https://lifehouse2026.com --wp-username <WPユーザー名> \
  --wp-app-password "xxxx xxxx xxxx xxxx xxxx xxxx"
python scripts/set_domain_secret.py --domain comfortablelivinglab \
  --wp-base-url https://comfortablelivinglab.com --wp-username <WPユーザー名> \
  --wp-app-password "xxxx xxxx xxxx xxxx xxxx xxxx"
```

WordPress のアプリケーションパスワードは: WP管理画面 → ユーザー → プロフィール →
「アプリケーションパスワード」で発行（スペースはそのままでよい）。

続いてブラウザで:

1. `https://<サービス名>.onrender.com/` … ダッシュボードが開く
2. `https://<サービス名>.onrender.com/oauth/google/start` … Google 連携（Search Console + Ads）
3. `https://<サービス名>.onrender.com/api/oauth/google/status` … `{"connected": true}` を確認

---

## 手順 8（任意）— ランク同期の定期実行

`.github/workflows/rank_sync.yml` が毎日 04:17 JST に
`POST /internal/cron/rank-sync` を叩く設計です（エンドポイント自体は P5 で実装予定）。
それまでは手動で:

```bash
curl -X POST https://<サービス名>.onrender.com/api/jobs \
  -H 'Content-Type: application/json' -H 'X-User-Id: 1' \
  -d '{"kind":"rank_sync","domain_id":1}'
curl -X POST https://<サービス名>.onrender.com/api/jobs \
  -H 'Content-Type: application/json' -H 'X-User-Id: 1' \
  -d '{"kind":"analysis","domain_id":1}'
```

---

## 動作確認チェックリスト

| 確認 | 方法 |
|------|------|
| DB 接続 | `/healthz` が `db:true` |
| マイグレーション | Neon SQL Editor で `select tablename from pg_tables where schemaname='public'` に 15 業務テーブル + `alembic_version` |
| ドメイン取込 | `/api/domains` に2件 |
| Google 連携 | `/api/oauth/google/status` が `connected:true` |
| 記事生成 | `POST /api/jobs {"kind":"article_generate","domain_id":1,"params":{"target_keyword":"...","force":true}}` → `GET /api/jobs/{id}` が `succeeded` |
| 公開 | `POST /api/articles/{id}/publish` → WordPress に下書き/公開 |

---

## よくある詰まり

| 症状 | 対処 |
|------|------|
| 別アカウントのデータが見えてしまう | `DATABASE_URL` に `neondb_owner`（`BYPASSRLS`）を使っている。`app_user` に切り替える。 |
| `permission denied for table ...` | `app_user` に GRANT していない。手順2の GRANT 5行を再実行。 |
| `alembic upgrade head` が `must be owner` / `permission denied` | `MIGRATION_DATABASE_URL` に `neondb_owner` を設定してから実行。 |
| `invalid input syntax for type bigint: ""` | 古いマイグレーション。最新（`NULLIF(current_setting('app.account_id', true), '')`）に更新して再適用。 |
| `/healthz` が `db:false` | Neon 接続文字列末尾の `?sslmode=require` を消さない。Neon プロジェクトが起動しているか（無料枠はアイドルで一時停止）。 |
| Google 連携で `redirect_uri_mismatch` | Google Cloud のリダイレクト URI と `GOOGLE_OAUTH_REDIRECT_URI` が**完全一致**か（末尾スラッシュ・httpsまで）。 |
| 連携後すぐ切れる / 週1で再連携を要求される | OAuth 同意画面が「テスト」のまま。「本番環境」に公開する。 |
| `APP_ENCRYPTION_KEY` を変えてしまった | 保存済み OAuth トークンと WP パスワードは復号不可。`/oauth/google/start` で再連携し、`set_domain_secret.py` で再登録。 |
| 記事生成が `月間検索数 ... 閾値 ... 未満` で失敗 | 実際に検索数が少ない。`params.force: true` で上書き、または閾値を下げる。 |
| コールドスタートで最初のリクエストが遅い | 無料枠の仕様（15分アイドルでスリープ）。UptimeRobot 等で定期 ping する手もある。 |

---

## 手順 9（P5）— フロントエンド（Next.js）を Render Static Site に 🧑

`frontend/` は静的書き出し（`next build` → `frontend/out/`）される Next.js 製の
管理画面。**Render の無料 Static Site**（サーバーなし・スリープなし・$0）に置く。
Render のサーバーレンダリング画面（`/`）は簡易フォールバックとして残す。

### 9-1. Render で Static Site を作成

1. Render ダッシュボード → **New +** → **Static Site**
2. リポジトリ `s-hirooka/article-ops-console` を選択
3. 設定:
   | 項目 | 値 |
   |------|-----|
   | Root Directory | `frontend` |
   | Build Command | `npm install && npm run build` |
   | Publish Directory | `out` |
4. **Environment Variables**:
   | Key | Value |
   |-----|-------|
   | `NEXT_PUBLIC_API_BASE` | `https://article-ops-console.onrender.com`（バックエンドの URL） |
5. **Create Static Site** → デプロイ完了後の URL（例
   `https://article-ops-console-web.onrender.com`）が管理画面。

### 9-2. バックエンド側の CORS

`*.onrender.com` は既定で許可されるので、通常は設定不要。
独自ドメインを当てる場合のみ、バックエンド Web サービスの環境変数に
`CORS_ORIGINS`（カンマ区切りの完全な origin）を追加して Save and deploy。

### 9-3. ローカルで動かす場合

```bash
cd frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE を確認
npm run dev                  # http://localhost:3000
```

### 画面

| パス | 内容 |
|------|------|
| `/` | 概要（AI予算 / ドメイン一覧 / 最近のジョブ） |
| `/domains?id=N` | ドメイン詳細（順位推移グラフ / 次の打ち手 / アラート / 記事一覧） |
| `/domains/prompts?id=N` | 記事生成プロンプトの編集（Monaco、8コンポーネント、バージョン履歴） |
| `/domains/new?id=N` | 新規記事ウィザード（キーワード指定 → 生成 → WordPress 公開） |
| `/jobs` | ジョブ履歴と詳細 |

> 静的サイトなので動的ルートは使わず、`?id=` のクエリ方式。
> 認証は未実装（`X-Account-Id` / `X-User-Id` ヘッダのみ）。Render Static Site に
> Basic 認証を掛けるか、社内からのみアクセスする運用にすること。
