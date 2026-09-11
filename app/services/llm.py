"""Anthropic draft generation.

One entry point, ``generate_draft``. It streams a single message (long output —
streaming avoids request timeouts, per the claude-api skill) and gets the
draft back as a tool call's structured input, not free-text JSON — body_html
is raw HTML full of unescaped double quotes (``<a href="...">``,
``class="..."``), and asking the model to hand-embed that as a valid JSON
*string value* is fragile by construction: any imperfectly-escaped quote
breaks ``json.loads`` (seen in production as ``Expecting ',' delimiter``).
Anthropic's tool-use JSON encoding handles that correctly, so this sidesteps
the whole failure class instead of trying to parse around it.

Fake mode — ``LLM_FAKE=1`` or no API key available — returns a deterministic
stub so the pipeline and its tests run offline with zero spend.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from app.services.pricing import cost_usd

_SUBMIT_DRAFT_TOOL = {
    "name": "submit_draft",
    "description": "生成した記事下書きを提出する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "slug": {"type": "string", "description": "ascii-kebab-case"},
            "meta_description": {"type": "string", "description": "120字以内"},
            "outline": {"type": "array", "items": {"type": "string"}},
            "body_html": {
                "type": "string",
                "description": "WordPress本文。hタグと段落、ショートコードはそのまま文字列で。",
            },
        },
        "required": ["title", "slug", "meta_description", "outline", "body_html"],
    },
}
_TOOL_INSTRUCTION = "書き終えたら submit_draft ツールを呼び出し、上記の内容を渡してください。"

# For a title/meta-only revision (article_improve.py's "ctr" action_hint):
# a *separate*, smaller tool that doesn't ask for body_html at all. Reusing
# submit_draft with instructions to "leave body_html unchanged" sounds
# equivalent but isn't reliable in practice — a model told a field doesn't
# need changing sometimes omits it from the tool call entirely, and
# body_html is a required property, so that omission crashed the parse
# (seen in production as a bare KeyError). Not asking for it at all removes
# the failure mode instead of hoping the model always includes it anyway.
_SUBMIT_TITLE_TOOL = {
    "name": "submit_title_revision",
    "description": "改善したタイトルとメタディスクリプションを提出する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "slug": {"type": "string", "description": "ascii-kebab-case"},
            "meta_description": {"type": "string", "description": "120字以内"},
        },
        "required": ["title", "slug", "meta_description"],
    },
}
_TITLE_TOOL_INSTRUCTION = (
    "書き終えたら submit_title_revision ツールを呼び出し、上記の内容を渡してください。"
    "本文(body_html)は変更しないので出力不要です。"
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
    parts.append(_TOOL_INSTRUCTION)
    return "\n\n".join(parts)


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


@dataclass(frozen=True)
class TitleRevisionResult:
    title: str
    slug: str
    meta_description: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    faked: bool = False


def _fake_title(req: DraftRequest, model: str) -> TitleRevisionResult:
    kw = req.target_keyword
    slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-") or "draft"
    return TitleRevisionResult(
        title=f"{kw}｜クリックしたくなる改善版タイトル",
        slug=slug,
        meta_description=f"{kw}について、より具体的でクリックされやすい説明文に改善しました。",
        model=model,
        input_tokens=300,
        output_tokens=150,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=cost_usd(model, 300, 150),
        faked=True,
    )


def generate_title_revision(
    req: DraftRequest,
    *,
    model: str = "claude-sonnet-5",
    api_key: str | None = None,
    max_tokens: int = 8000,
) -> TitleRevisionResult:
    """Title + meta_description only — for a CTR-focused revision that
    deliberately leaves body_html untouched (see _SUBMIT_TITLE_TOOL).

    max_tokens is generous relative to the tiny actual output: extended
    thinking shares the same token budget as the response, and a first cut
    at 1000 hit stop_reason="max_tokens" in production before the model ever
    reached the tool call — cost tracks tokens actually used, not the cap,
    so a high ceiling here is free insurance, not a bigger bill."""
    if _use_fake(api_key):
        return _fake_title(req, model)

    import anthropic  # lazy: keep import cost off the fake path

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    parts = [f"対象キーワード: {req.target_keyword}"]
    if req.extra_instructions:
        parts.append(req.extra_instructions)
    parts.append(_TITLE_TOOL_INSTRUCTION)
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
        tools=[_SUBMIT_TITLE_TOOL],
        tool_choice={"type": "auto"},
    )
    try:
        with client.messages.stream(thinking={"type": "adaptive"}, **kwargs) as stream:
            msg = stream.get_final_message()
    except TypeError:
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

    tool_use = next(
        (b for b in msg.content if getattr(b, "type", None) == "tool_use"
         and getattr(b, "name", None) == "submit_title_revision"),
        None,
    )
    if tool_use is None:
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        raise RuntimeError(
            f"モデルが submit_title_revision を呼び出しませんでした"
            f"（stop_reason={msg.stop_reason}）: {text[:300]}"
        )
    data = tool_use.input

    u = msg.usage
    in_tok = int(getattr(u, "input_tokens", 0) or 0)
    out_tok = int(getattr(u, "output_tokens", 0) or 0)
    cr = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    cw = int(getattr(u, "cache_creation_input_tokens", 0) or 0)

    return TitleRevisionResult(
        title=str(data.get("title", "")).strip(),
        slug=re.sub(r"[^a-z0-9-]+", "-", str(data.get("slug", "")).lower()).strip("-")
        or "draft",
        meta_description=str(data.get("meta_description", "")).strip(),
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_read_tokens=cr,
        cache_write_tokens=cw,
        cost_usd=cost_usd(model, in_tok, out_tok, cr, cw),
        faked=False,
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
        tools=[_SUBMIT_DRAFT_TOOL],
        # extended thinking only allows "auto" tool_choice (a forced choice
        # isn't accepted alongside thinking) — fine here, one tool offered
        # with clear instructions is reliably picked.
        tool_choice={"type": "auto"},
    )
    try:
        with client.messages.stream(thinking={"type": "adaptive"}, **kwargs) as stream:
            msg = stream.get_final_message()
    except TypeError:
        # SDK too old for adaptive thinking kwarg — run without it.
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

    tool_use = next(
        (b for b in msg.content if getattr(b, "type", None) == "tool_use"
         and getattr(b, "name", None) == "submit_draft"),
        None,
    )
    if tool_use is None:
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        raise RuntimeError(
            f"モデルが submit_draft を呼び出しませんでした（stop_reason={msg.stop_reason}）: "
            f"{text[:300]}"
        )
    data = tool_use.input
    if not data.get("title") or not data.get("body_html"):
        raise RuntimeError(
            f"submit_draft の必須項目（title/body_html）が欠けています: "
            f"{list(data.keys())}"
        )

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
