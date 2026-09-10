"""Minimal WordPress REST client (self-contained cloud port of RankPulse.wp_client).

Credentials are passed in (decrypted from the ``domains`` row), not loaded from a
file. Basic auth with an application password. ``WP_FAKE=1`` returns synthetic
responses so the publish path runs offline.

Cocoon note (carried over from RankPulse): the meta description cannot be set
through REST — it stays a manual paste into the SEO metabox.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

import requests

_TIMEOUT = 45


class WordPressError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class WordPressCreds:
    base_url: str
    username: str
    app_password: str


def _fake() -> bool:
    return os.environ.get("WP_FAKE") == "1"


class WordPressClient:
    def __init__(self, creds: WordPressCreds):
        self._c = WordPressCreds(
            base_url=creds.base_url.rstrip("/"),
            username=creds.username,
            app_password=creds.app_password,
        )

    def _headers(self, extra: dict | None = None) -> dict:
        token = base64.b64encode(
            f"{self._c.username}:{self._c.app_password}".encode()
        ).decode()
        return {"Authorization": f"Basic {token}", **(extra or {})}

    def _request(self, method: str, path: str, *, data: bytes | None = None,
                 headers: dict | None = None) -> dict:
        url = f"{self._c.base_url}{path}"
        try:
            resp = requests.request(
                method, url, data=data, headers=self._headers(headers), timeout=_TIMEOUT
            )
        except requests.RequestException as exc:
            raise WordPressError(f"WordPress 接続失敗: {exc}") from exc
        if resp.status_code >= 400:
            raise WordPressError(
                f"WordPress {method} {path} -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text[:800],
            )
        return resp.json() if resp.content else {}

    # --- posts -------------------------------------------------------------
    def create_post(self, *, title: str, content: str, slug: str | None = None,
                    status: str = "draft", featured_media: int | None = None,
                    **extra) -> dict:
        if _fake():
            return {"id": 900001, "link": f"{self._c.base_url}/?p=900001",
                    "status": status, "slug": slug or "faked"}
        payload: dict = {"title": title, "content": content, "status": status}
        if slug:
            payload["slug"] = slug
        if featured_media:
            payload["featured_media"] = featured_media
        payload.update(extra)
        return self._request(
            "POST", "/wp-json/wp/v2/posts",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

    def update_post(self, post_id: int, **fields) -> dict:
        if _fake():
            return {"id": post_id, "link": f"{self._c.base_url}/?p={post_id}", **fields}
        return self._request(
            "POST", f"/wp-json/wp/v2/posts/{post_id}",
            data=json.dumps(fields).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

    def get_post(self, post_id: int, fields: list[str] | None = None) -> dict:
        if _fake():
            return {"id": post_id, "link": f"{self._c.base_url}/?p={post_id}"}
        q = f"?_fields={','.join(fields)}" if fields else ""
        return self._request("GET", f"/wp-json/wp/v2/posts/{post_id}{q}")

    # --- media -----------------------------------------------------------
    def upload_media_bytes(self, data: bytes, filename: str,
                           content_type: str = "image/png") -> dict:
        if _fake():
            return {"id": 800001,
                    "source_url": f"{self._c.base_url}/wp-content/uploads/{filename}"}
        return self._request(
            "POST", "/wp-json/wp/v2/media", data=data,
            headers={
                "Content-Type": content_type,
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
