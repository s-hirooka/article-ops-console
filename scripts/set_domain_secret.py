"""Set a per-domain encrypted secret (WordPress app password or BYOK Anthropic key).

There is no UI for this yet, and the columns are write-through (never read back
by the app), so this script is the supported way to populate them.

    # against the deployed DB
    DATABASE_URL=postgresql://...  APP_ENCRYPTION_KEY=...  \
      python scripts/set_domain_secret.py --domain lifehouse2026 \
      --wp-base-url https://lifehouse2026.com --wp-username editor \
      --wp-app-password "xxxx xxxx xxxx xxxx xxxx xxxx"

    # per-domain Anthropic key instead of the shared one
    ... python scripts/set_domain_secret.py --domain lifehouse2026 \
      --anthropic-key sk-ant-...

Reads DEV_ACCOUNT_ID (default 1) to pick the account.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import AppSettings
from app.db import models as m
from app.db.session import SessionLocal
from app.security.crypto import encrypt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True, help="domain_key")
    ap.add_argument("--wp-base-url")
    ap.add_argument("--wp-username")
    ap.add_argument("--wp-app-password")
    ap.add_argument("--anthropic-key")
    args = ap.parse_args()

    if not any([args.wp_app_password, args.anthropic_key, args.wp_base_url, args.wp_username]):
        ap.error("設定する項目を1つ以上指定してください。")

    account_id = AppSettings.from_env().dev_account_id
    with SessionLocal() as s:
        d = s.scalar(
            select(m.Domain).where(
                m.Domain.account_id == account_id,
                m.Domain.domain_key == args.domain,
            )
        )
        if d is None:
            print(f"domain '{args.domain}' が account {account_id} に見つかりません。")
            return 1

        if args.wp_base_url:
            d.wp_base_url = args.wp_base_url.rstrip("/")
        if args.wp_username:
            d.wp_username = args.wp_username
        if args.wp_app_password:
            d.wp_app_password_enc = encrypt(args.wp_app_password)
            print("+ wp_app_password_enc set")
        if args.anthropic_key:
            d.anthropic_api_key_enc = encrypt(args.anthropic_key)
            print("+ anthropic_api_key_enc set")
        s.commit()

    print(f"done: domain '{args.domain}' updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
