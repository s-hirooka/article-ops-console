"""Symmetric encryption for secrets at rest (OAuth refresh tokens, BYOK keys).

Uses Fernet (AES-128-CBC + HMAC-SHA256, timestamped). Keys come from the
``APP_ENCRYPTION_KEY`` env var — one or more base64 Fernet keys, newest first,
comma-separated. Multiple keys enable rotation: encryption always uses the
first key; decryption tries each in turn.

    # generate a key for the env var
    python -c "from app.security.crypto import generate_key; print(generate_key())"

In Postgres these ciphertext strings live in ``oauth_tokens.refresh_token_enc``
and ``domains.anthropic_api_key_enc`` (see spec §09). The columns are
write-through: the UI never reads them back.
"""
from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

_ENV_VAR = "APP_ENCRYPTION_KEY"


class EncryptionKeyError(RuntimeError):
    pass


def generate_key() -> str:
    """A fresh base64 Fernet key, suitable for APP_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode("ascii")


@lru_cache(maxsize=1)
def _cipher() -> MultiFernet:
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        raise EncryptionKeyError(
            f"{_ENV_VAR} が未設定です。`python -c \"from app.security.crypto "
            f"import generate_key; print(generate_key())\"` で生成してください。"
        )
    keys = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            keys.append(Fernet(part))
        except (ValueError, TypeError) as exc:
            raise EncryptionKeyError(f"{_ENV_VAR} の鍵が不正です: {exc}") from exc
    if not keys:
        raise EncryptionKeyError(f"{_ENV_VAR} に有効な鍵がありません。")
    return MultiFernet(keys)


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        raise ValueError("encrypt(None) は不可です。")
    return _cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionKeyError(
            "復号に失敗しました（鍵の入れ替わり、または壊れた暗号文）。"
        ) from exc


def rotate(token: str) -> str:
    """Re-encrypt an existing ciphertext under the current primary key."""
    return _cipher().rotate(token.encode("ascii")).decode("ascii")


def reset_cache() -> None:
    """Drop the cached cipher (call after changing APP_ENCRYPTION_KEY in tests)."""
    _cipher.cache_clear()
