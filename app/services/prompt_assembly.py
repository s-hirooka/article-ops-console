"""Compose a domain's editable prompt components into one system prompt.

The 8 components (spec §05) and how they're used:

| component            | role in generation                         |
|----------------------|--------------------------------------------|
| system_prompt        | persona / house rules (top of system)      |
| article_structure    | required section skeleton                   |
| product_block_spec   | how to place [vc_auto_ads] product blocks  |
| vc_auto_ads_defaults | default shortcode attrs (JSON) — passed to renderer, not the model |
| eyecatch_style       | banner params (JSON) — passed to eyecatch.py |
| internal_link_policy | "あわせて読みたい" linking rules             |
| title_format         | title / H1 constraints                      |
| keyword_threshold    | min monthly searches (int) — gate, not prompt |

Missing components fall back to built-in defaults so a brand-new domain works.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m

_TEXT_DEFAULTS: dict[str, str] = {
    "system_prompt": (
        "あなたは日本語の実用ブログ記事を書く編集者です。編集部名義で執筆し、"
        "実体験として断定できることだけを一次情報として書き、購入検証・資格・"
        "監修を主張しないでください。読者は特定の悩みを解決したい個人です。"
    ),
    "article_structure": (
        "# 導入（読者の悩みと結論の先出し）\n"
        "## 選び方のポイント（3〜5項目、h3）\n"
        "## おすすめ（各項目にh3、特徴・メリット・注意点）\n"
        "## よくある質問（3件、h3）\n"
        "## まとめ"
    ),
    "product_block_spec": (
        "「おすすめ」の各h3直後に商品ブロックを置く。ショートコード "
        "[vc_auto_ads keyword=\"<具体的な検索語>\" source=all limit=3] を使い、"
        "keyword はジャンル名だけでなく用途・形状を含めた3語程度にする。"
    ),
    "internal_link_policy": (
        "本文末尾に「あわせて読みたい」を作り、同ドメインの関連記事を2〜3本、"
        "実在のパーマリンクで挙げる。日付やスラッグを推測しない。"
    ),
    "title_format": (
        "タイトルは32文字前後。対象キーワードを前方に含め、"
        "「〜選」「〜のコツ」等の具体語を1つ入れる。H1はタイトルと同一。"
    ),
}
_JSON_DEFAULTS: dict[str, object] = {
    "vc_auto_ads_defaults": {"source": "all", "limit": 3, "slot": 1},
    "eyecatch_style": {"preset": "warm_flat", "width": 1536, "height": 1024},
}


@dataclass(frozen=True)
class AssembledPrompt:
    system: str
    versions: dict[str, int]
    vc_auto_ads_defaults: dict
    eyecatch_style: dict
    keyword_threshold: int
    components: dict[str, str] = field(default_factory=dict)


def _latest_bodies(session: Session, domain_id: int) -> tuple[dict[str, str], dict[str, int]]:
    sub = (
        select(
            m.DomainPrompt.component,
            func.max(m.DomainPrompt.version).label("v"),
        )
        .where(m.DomainPrompt.domain_id == domain_id)
        .group_by(m.DomainPrompt.component)
        .subquery()
    )
    rows = session.execute(
        select(m.DomainPrompt).join(
            sub,
            (m.DomainPrompt.component == sub.c.component)
            & (m.DomainPrompt.version == sub.c.v)
            & (m.DomainPrompt.domain_id == domain_id),
        )
    ).scalars().all()
    bodies = {r.component: r.body for r in rows}
    versions = {r.component: r.version for r in rows}
    return bodies, versions


def _as_json(raw: str | None, default: object) -> object:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def assemble(session: Session, domain_id: int) -> AssembledPrompt:
    domain = session.get(m.Domain, domain_id)
    if domain is None:
        raise ValueError(f"domain {domain_id} が見つかりません。")

    bodies, versions = _latest_bodies(session, domain_id)

    def text(component: str) -> str:
        return bodies.get(component) or _TEXT_DEFAULTS[component]

    system = "\n\n".join(
        [
            text("system_prompt"),
            "## 記事構成（必須セクション）\n" + text("article_structure"),
            "## 商品ブロックの入れ方\n" + text("product_block_spec"),
            "## 内部リンク方針\n" + text("internal_link_policy"),
            "## タイトル・見出しの形式\n" + text("title_format"),
        ]
    )

    threshold_raw = bodies.get("keyword_threshold")
    try:
        threshold = int(threshold_raw) if threshold_raw else domain.keyword_threshold
    except (ValueError, TypeError):
        threshold = domain.keyword_threshold

    return AssembledPrompt(
        system=system,
        versions=versions,
        vc_auto_ads_defaults=_as_json(
            bodies.get("vc_auto_ads_defaults"), _JSON_DEFAULTS["vc_auto_ads_defaults"]
        ),
        eyecatch_style=_as_json(
            bodies.get("eyecatch_style"), _JSON_DEFAULTS["eyecatch_style"]
        ),
        keyword_threshold=threshold,
        components={
            k: (bodies.get(k) or _TEXT_DEFAULTS.get(k, "")) for k in _TEXT_DEFAULTS
        },
    )
