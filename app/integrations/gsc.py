"""Google Search Console — Search Analytics query.

Direct REST call (``searchanalytics.query``) with a bearer token from
``google_token.get_access_token``. No google-api-python-client dependency.

``GSC_FAKE=1`` returns a small synthetic result so rank-sync runs offline.
"""
from __future__ import annotations

import os
import random

import requests

_ENDPOINT = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
_TIMEOUT = 60


class GscError(RuntimeError):
    pass


def _fake_rows(start_date: str, end_date: str) -> list[dict]:
    rng = random.Random(f"{start_date}{end_date}")
    kws = ["収納 アイデア", "押入れ 収納", "すきま 収納", "玄関 収納 賃貸"]
    out = []
    for d in (start_date, end_date):
        for kw in kws:
            out.append(
                {
                    "keys": [d, kw, f"https://example.com/{kw.split()[0]}"],
                    "clicks": rng.randint(0, 8),
                    "impressions": rng.randint(5, 120),
                    "ctr": round(rng.uniform(0.01, 0.09), 4),
                    "position": round(rng.uniform(3, 45), 1),
                }
            )
    return out


def query_search_analytics(
    access_token: str,
    site_url: str,
    start_date: str,
    end_date: str,
    *,
    dimensions: tuple[str, ...] = ("date", "query", "page"),
    row_limit: int = 25000,
) -> list[dict]:
    if os.environ.get("GSC_FAKE") == "1":
        return _fake_rows(start_date, end_date)

    from urllib.parse import quote

    url = _ENDPOINT.format(site=quote(site_url, safe=""))
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": list(dimensions),
        "rowLimit": row_limit,
        "dataState": "final",
    }
    try:
        resp = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GscError(f"GSC 接続失敗: {exc}") from exc
    if resp.status_code >= 400:
        raise GscError(f"GSC query -> {resp.status_code}: {resp.text[:500]}")
    return resp.json().get("rows", [])
