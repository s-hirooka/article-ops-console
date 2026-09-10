"""Seed accounts/domains from the existing KeywordInsightService SQLite DB.

Creates one account (id from DEV_ACCOUNT_ID, default 1), one owner user, and a
``domains`` row per ``Sites`` row. Safe to re-run — upserts by natural key.

    DATABASE_URL=postgresql://...  python scripts/seed_from_sites.py \
        --owner-email you@example.com \
        --sqlite "G:\\KeywordInsightService\\keyword_metrics.db"
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text

from app.config import AppSettings
from app.db import models as m
from app.db.session import SessionLocal, engine

DEFAULT_SQLITE = r"G:\KeywordInsightService\keyword_metrics.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner-email", default="s.hirooka.ceo@gmail.com")
    ap.add_argument("--account-name", default="Default")
    ap.add_argument("--sqlite", default=DEFAULT_SQLITE)
    args = ap.parse_args()

    account_id = AppSettings.from_env().dev_account_id

    src = sqlite3.connect(args.sqlite)
    src.row_factory = sqlite3.Row
    sites = src.execute(
        "SELECT SiteKey, BaseUrl, GscSiteUrl FROM Sites ORDER BY SiteKey"
    ).fetchall()
    src.close()

    with SessionLocal() as s:
        # domains / domain_prompts are RLS-forced; set the tenant GUC so this
        # unscoped session can write them (accounts/users/members are exempt).
        if s.bind.dialect.name == "postgresql":
            s.execute(text(f"SET app.account_id = '{int(account_id)}'"))

        acct = s.get(m.Account, account_id)
        if acct is None:
            acct = m.Account(id=account_id, name=args.account_name)
            s.add(acct)
            s.flush()
            print(f"+ account {account_id} ({args.account_name})")

        user = s.scalar(select(m.User).where(m.User.email_plain == args.owner_email))
        if user is None:
            user = m.User(email=args.owner_email, email_plain=args.owner_email,
                          display_name="Owner")
            s.add(user)
            s.flush()
            print(f"+ user {args.owner_email}")

        if not s.get(m.AccountMember, (account_id, user.id)):
            s.add(m.AccountMember(account_id=account_id, user_id=user.id, role="owner"))
            print(f"+ member owner={args.owner_email}")

        for row in sites:
            existing = s.scalar(
                select(m.Domain).where(
                    m.Domain.account_id == account_id,
                    m.Domain.domain_key == row["SiteKey"],
                )
            )
            if existing:
                existing.base_url = row["BaseUrl"]
                existing.gsc_site_url = row["GscSiteUrl"]
                print(f"~ domain {row['SiteKey']}")
            else:
                s.add(m.Domain(
                    account_id=account_id,
                    domain_key=row["SiteKey"],
                    base_url=row["BaseUrl"],
                    gsc_site_url=row["GscSiteUrl"],
                ))
                print(f"+ domain {row['SiteKey']}")
        s.commit()

    print(f"\ndone: {len(sites)} site(s) → account {account_id} on {engine.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
