"""Anthropic draft generation.

One entry point, ``generate_draft``. It streams a single message (long output —
streaming avoids request timeouts, per the claude-api skill), asks for a strict
JSON object, and parses it into a ``DraftResult`` with token/cost accounting.

Fake mode — ``LLM_FAKE=1`` or no API key available — returns a deterministic
stub so the pipeline and its tests run offline with zero spend.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from app.services.pricing import cost_usd

_JSON_INSTRUCTION = (
    "出力は次のキーを持つ JSON オブジェクトのみ。前後に説明文やコードフェンスを"
    "付けないこと。\n"
    '{"title": str, "slug": str(ascii-kebab), "meta_description": str(120字以内), '
    '"outline": [str, ...], "body_html": str(WordPress本文, hタグと段落, '
    "ショートコードはそのまま文字列で)}"
)


@dataclass(frozen=True)
class DraftRequest:
    system: str
    target_keyword: str
    search_volume: int | None = None
    vc_auto_ads_defaults: dict | None = None
    extra_instructions: str = ""


@dataclass(frozen=True)
class DraftResult:
    title: str
    slug: str
    meta_description: str
    outline: list[str]
    body_html: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    faked: bool = False


def _user_message(req: DraftRequest) -> str:
    parts = [
        f"対象キーワード: {req.target_keyword}",
    ]
    if req.search_volume:
        parts.append(f"想定月間検索数: {req.search_volume}")
    if req.vc_auto_ads_defaults:
        parts.append(
            "商品ショートコードの既定属性: "
            + json.dumps(req.vc_auto_ads_defaults, ensure_ascii=False)
        )
    if req.extra_instructions:
        parts.append(req.extra_instructions)
    parts.append(_JSON_INSTRUCTION)
    return "\n\n".join(parts)


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _fake(req: DraftRequest, model: str) -> DraftResult:
    kw = req.target_keyword
    slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-") or "draft"
    body = (
        f"<h1>{kw}の選び方とおすすめ</h1>\n"
        f"<p>{kw}について、選ぶときのポイントとおすすめをまとめます。</p>\n"
        f"<h2>選び方のポイント</h2>\n<h3>設置スペースで選ぶ</h3>\n<p>...</p>\n"
        f"<h2>おすすめ</h2>\n<h3>省スペースタイプ</h3>\n"
        f'[vc_auto_ads keyword="{kw} コンパクト" source=all limit=3]\n<p>...</p>\n'
        f"<h2>まず結論｜早見表</h2>\n<table><tr><td>[[PRODUCT_TITLE:{kw} コンパクト]]</td>"
        f"<td>[[PRODUCT_PRICE:{kw} コンパクト]]</td></tr></table>\n"
        f"[[PRODUCT_BLOCK:{kw} コンパクト]]\n<p>...</p>\n"
        f"<h2>よくある質問</h2>\n<h3>Q. ...</h3>\n<p>A. ...</p>\n<h2>まとめ</h2>\n<p>...</p>\n"
        f"<h2>あわせて読みたい</h2>\n<ul>\n"
        f"<li><!-- 関連記事1: 実在のパーマリンクが確定したらここにリンクを追加してください --></li>\n"
        f"<li><!-- 関連記事2: 実在のパーマリンクが確定したらここにリンクを追加してください --></li>\n"
        f"</ul>"
    )
    return DraftResult(
        title=f"{kw}のおすすめと選び方【保存版】",
        slug=slug,
        meta_description=f"{kw}の選び方とおすすめを、設置スペース別に整理して紹介します。",
        outline=["導入", "選び方のポイント", "おすすめ", "よくある質問", "まとめ"],
        body_html=body,
        model=model,
        input_tokens=1200,
        output_tokens=1800,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=cost_usd(model, 1200, 1800),
        faked=True,
    )


def _use_fake(api_key: str | None) -> bool:
    if os.environ.get("LLM_FAKE") == "1":
        return True
    return not (api_key or os.environ.get("ANTHROPIC_API_KEY"))


def generate_draft(
    req: DraftRequest,
    *,
    model: str = "claude-sonnet-5",
    api_key: str | None = None,
    max_tokens: int = 12000,
) -> DraftResult:
    if _use_fake(api_key):
        return _fake(req, model)

    import anthropic  # lazy: keep import cost off the fake path

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _user_message(req)}],
    )
    try:
        with client.messages.stream(thinking={"type": "adaptive"}, **kwargs) as stream:
            msg = stream.get_final_message()
    except TypeError:
        # SDK too old for adaptive thinking kwarg — run without it.
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    data = _parse_json_object(text)

    u = msg.usage
    in_tok = int(getattr(u, "input_tokens", 0) or 0)
    out_tok = int(getattr(u, "output_tokens", 0) or 0)
    cr = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    cw = int(getattr(u, "cache_creation_input_tokens", 0) or 0)

    return DraftResult(
        title=str(data["title"]).strip(),
        slug=re.sub(r"[^a-z0-9-]+", "-", str(data.get("slug", "")).lower()).strip("-")
        or "draft",
        meta_description=str(data.get("meta_description", "")).strip(),
        outline=[str(x) for x in data.get("outline", [])],
        body_html=str(data["body_html"]),
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_read_tokens=cr,
        cache_write_tokens=cw,
        cost_usd=cost_usd(model, in_tok, out_tok, cr, cw),
        faked=False,
    )
