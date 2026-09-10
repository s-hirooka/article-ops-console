"""Offline checks for P1(b): Fernet crypto + Google auth-URL builder.

No network, no Google account. Verifies the parts that don't need a live
consent screen — the code exchange itself is exercised in staging.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check_crypto() -> None:
    from app.security import crypto

    k1 = crypto.generate_key()
    k2 = crypto.generate_key()

    os.environ["APP_ENCRYPTION_KEY"] = k1
    crypto.reset_cache()
    secret = "1//0abcDEF_refresh-token.ヨ"  # non-ASCII on purpose
    enc = crypto.encrypt(secret)
    assert enc != secret and crypto.decrypt(enc) == secret, "roundtrip failed"
    assert crypto.encrypt(secret) != enc, "Fernet should be non-deterministic"

    # rotation: old ciphertext still decrypts when the new key is primary
    os.environ["APP_ENCRYPTION_KEY"] = f"{k2},{k1}"
    crypto.reset_cache()
    assert crypto.decrypt(enc) == secret, "old key must still decrypt"
    rotated = crypto.rotate(enc)
    assert crypto.decrypt(rotated) == secret, "rotated ciphertext must decrypt"

    # a ciphertext from an unrelated key must fail cleanly
    os.environ["APP_ENCRYPTION_KEY"] = crypto.generate_key()
    crypto.reset_cache()
    try:
        crypto.decrypt(enc)
    except crypto.EncryptionKeyError:
        pass
    else:
        raise AssertionError("decrypt with wrong key should raise")
    print("[OK]   crypto: roundtrip / non-determinism / rotation / wrong-key")


def check_auth_url() -> None:
    from app.config import GoogleOAuthSettings
    from app.integrations import google_oauth as go

    s = GoogleOAuthSettings(
        client_id="cid.apps.googleusercontent.com",
        client_secret="shhh",
        redirect_uri="https://app.example.com/oauth/google/callback",
    )
    url = go.build_authorization_url("nonce-123", settings=s, login_hint="a@b.com")
    q = parse_qs(urlparse(url).query)

    assert url.startswith(go.AUTH_ENDPOINT), url
    assert q["access_type"] == ["offline"], q
    assert q["prompt"] == ["consent"], q
    assert q["state"] == ["nonce-123"], q
    assert q["redirect_uri"] == [s.redirect_uri], q
    assert q["response_type"] == ["code"], q
    assert set(q["scope"][0].split()) == set(go.SCOPES), q["scope"]
    assert q["login_hint"] == ["a@b.com"], q
    print("[OK]   auth URL: endpoint / offline+consent / state / scopes / redirect")


def main() -> int:
    check_crypto()
    check_auth_url()
    print("\n✅ PASS — P1(b) offline checks")
    return 0


if __name__ == "__main__":
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    raise SystemExit(main())
