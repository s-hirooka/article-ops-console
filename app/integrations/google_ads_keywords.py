"""Google Ads keyword volume — Python port of KeywordQueryRunner.exe.

Faithfully mirrors ``Services/GoogleAdsKeywordMetricsService.cs``:

* endpoint  : KeywordPlanIdeaService.GenerateKeywordHistoricalMetrics
* language  : ``languageConstants/{language_id}``   (1005 = Japanese)
* geo       : ``geoTargetConstants/{id}`` list      (2392 = Japan)
* network   : GOOGLE_SEARCH
* bids      : ``*_micros`` / 1_000_000, rounded to 6 dp
* nullables : avg_monthly_searches / competition_index / bids are None when unset

Daily-usage limiting and caching are intentionally NOT here — in the cloud app
those move to the ``api_usage`` table (see spec §04). This module is the raw
fetch, matched 1:1 against the C# tool for parity testing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from app.config import GoogleAdsSettings


@dataclass(frozen=True)
class MonthlyVolume:
    year: int
    month: str          # enum name, e.g. "MARCH"
    monthly_searches: int


@dataclass(frozen=True)
class KeywordMetricRow:
    keyword: str
    avg_monthly_searches: int | None
    competition_level: str | None      # "LOW" / "MEDIUM" / "HIGH" / "UNSPECIFIED"...
    competition_index: int | None
    low_top_of_page_bid: Decimal | None
    high_top_of_page_bid: Decimal | None
    monthly_volumes: list[MonthlyVolume] = field(default_factory=list)


class GoogleAdsCredentialError(RuntimeError):
    pass


def _micros_to_decimal(micros: int | None) -> Decimal | None:
    if micros is None:
        return None
    return (Decimal(micros) / Decimal(1_000_000)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )


def _build_client(s: GoogleAdsSettings):
    from google.ads.googleads.client import GoogleAdsClient  # lazy: heavy import

    for name, value in (
        ("GOOGLE_ADS_DEVELOPER_TOKEN", s.developer_token),
        ("GOOGLE_ADS_OAUTH2_CLIENT_ID", s.client_id),
        ("GOOGLE_ADS_OAUTH2_CLIENT_SECRET", s.client_secret),
        ("GOOGLE_ADS_OAUTH2_REFRESH_TOKEN", s.refresh_token),
    ):
        if not value or value.upper().startswith("YOUR_"):
            raise GoogleAdsCredentialError(f"{name} が未設定です（.env を確認）。")

    cfg: dict = {
        "developer_token": s.developer_token,
        "client_id": s.client_id,
        "client_secret": s.client_secret,
        "refresh_token": s.refresh_token,
        "use_proto_plus": s.use_proto_plus,
    }
    if s.login_customer_id:
        cfg["login_customer_id"] = s.login_customer_id
    return GoogleAdsClient.load_from_dict(cfg)


def fetch_historical_metrics(
    keywords: list[str],
    settings: GoogleAdsSettings | None = None,
    customer_id: str | None = None,
) -> list[KeywordMetricRow]:
    """One call to GenerateKeywordHistoricalMetrics for up to ~30 keywords.

    Returns one row per keyword the API reports (order not guaranteed — key by
    ``keyword``). Counts as a single API call, exactly like one .exe invocation.
    """
    s = settings or GoogleAdsSettings.from_env()
    keywords = [k for k in (kw.strip() for kw in keywords) if k]
    if not keywords:
        raise ValueError("キーワードが未指定です。")
    if len(keywords) > s.max_keywords_per_request:
        raise ValueError(
            f"キーワードは1回あたり最大 {s.max_keywords_per_request} 件です"
            f"（{len(keywords)} 件指定）。"
        )
    cid = "".join(ch for ch in (customer_id or s.default_customer_id) if ch.isdigit())
    if not cid:
        raise GoogleAdsCredentialError("Customer ID が未指定です。")

    client = _build_client(s)
    svc = client.get_service("KeywordPlanIdeaService")
    enum = client.enums.KeywordPlanNetworkEnum

    request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    request.customer_id = cid
    request.language = f"languageConstants/{s.language_id}"
    request.geo_target_constants.extend(
        f"geoTargetConstants/{gid}" for gid in s.geo_target_ids
    )
    request.keyword_plan_network = enum.GOOGLE_SEARCH
    request.keywords.extend(keywords)

    response = svc.generate_keyword_historical_metrics(request=request)

    rows: list[KeywordMetricRow] = []
    for result in response.results:
        m = result.keyword_metrics
        # proto-plus always materialises a singular message; use field presence.
        has = "keyword_metrics" in result
        monthly = (
            [
                MonthlyVolume(
                    year=int(v.year),
                    month=v.month.name if hasattr(v.month, "name") else str(v.month),
                    monthly_searches=int(v.monthly_searches),
                )
                for v in m.monthly_search_volumes
            ]
            if has
            else []
        )
        rows.append(
            KeywordMetricRow(
                keyword=result.text or "",
                avg_monthly_searches=(
                    int(m.avg_monthly_searches)
                    if has and "avg_monthly_searches" in m
                    else None
                ),
                competition_level=(
                    m.competition.name
                    if has and hasattr(m.competition, "name")
                    else (str(m.competition) if has else None)
                ),
                competition_index=(
                    int(m.competition_index)
                    if has and "competition_index" in m
                    else None
                ),
                low_top_of_page_bid=_micros_to_decimal(
                    m.low_top_of_page_bid_micros
                    if has and "low_top_of_page_bid_micros" in m
                    else None
                ),
                high_top_of_page_bid=_micros_to_decimal(
                    m.high_top_of_page_bid_micros
                    if has and "high_top_of_page_bid_micros" in m
                    else None
                ),
                monthly_volumes=monthly,
            )
        )
    return rows


def to_tsv(rows: list[KeywordMetricRow]) -> str:
    """Same columns/order the .exe prints, for eyeball diffing."""
    out = ["Keyword\tAvgMonthlySearches\tCompetitionLevel\tCompetitionIndex\tLowBid\tHighBid"]
    for r in rows:
        out.append(
            "\t".join(
                (
                    r.keyword,
                    "" if r.avg_monthly_searches is None else str(r.avg_monthly_searches),
                    r.competition_level or "",
                    "" if r.competition_index is None else str(r.competition_index),
                    "" if r.low_top_of_page_bid is None else f"{r.low_top_of_page_bid}",
                    "" if r.high_top_of_page_bid is None else f"{r.high_top_of_page_bid}",
                )
            )
        )
    return "\n".join(out)
