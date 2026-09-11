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

    def list_posts(self, *, per_page: int = 100, exclude: int | None = None) -> list[dict]:
        """Published posts (id/link/title only) for internal-link matching.
        Public REST data — works with any valid credentials regardless of
        their write scope."""
        if _fake():
            base = self._c.base_url
            return [
                {"id": 101, "link": f"{base}/fake-related-a/",
                 "title": {"rendered": "フェイク関連記事A｜収納のコツ"}},
                {"id": 102, "link": f"{base}/fake-related-b/",
                 "title": {"rendered": "フェイク関連記事B｜収納グッズ比較"}},
                {"id": 103, "link": f"{base}/fake-related-c/",
                 "title": {"rendered": "フェイク関連記事C｜掃除のコツ"}},
            ]
        q = f"?per_page={per_page}&status=publish&_fields=id,link,title"
        if exclude:
            q += f"&exclude={exclude}"
        result = self._request("GET", f"/wp-json/wp/v2/posts{q}")
        return result if isinstance(result, list) else []

    def find_post_by_slug(self, slug: str) -> dict | None:
        """Full post (incl. content) by slug — for importing a page that
        predates the console (published outside it, so has no `articles`
        row) into one so it can be revised/republished through the app."""
        if _fake():
            return {
                "id": 900003,
                "link": f"{self._c.base_url}/{slug}/",
                "title": {"rendered": slug},
                "content": {"rendered": "<p>fake existing content</p>"},
            }
        q = f"?slug={slug}&_fields=id,link,title,content"
        result = self._request("GET", f"/wp-json/wp/v2/posts{q}")
        return result[0] if isinstance(result, list) and result else None

    def trash_post(self, post_id: int) -> dict:
        """Move a post to the trash (recoverable). Not a permanent delete."""
        if _fake():
            return {"id": post_id, "status": "trash"}
        return self._request("DELETE", f"/wp-json/wp/v2/posts/{post_id}")

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
