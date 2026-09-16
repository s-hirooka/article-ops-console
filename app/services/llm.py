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


def _translate_anthropic_error(exc) -> str:
    """The SDK's own exception text (and, further up the call stack, a full
    Python traceback) is technical and was surfacing verbatim in the UI —
    seen in production as a wall of stack-trace text where a one-line
    explanation belongs. Pull the actual message out of the response body
    and recognize the couple of cases a user can act on."""
    body = getattr(exc, "body", None)
    msg = ""
    if isinstance(body, dict):
        msg = ((body.get("error") or {}).get("message") or "") if isinstance(body.get("error"), dict) else ""
    msg = msg or str(exc)
    low = msg.lower()
    if "credit balance is too low" in low:
        return (
            "Anthropic APIのクレジット残高が不足しています。"
            "Claude Console（console.anthropic.com の Plans & Billing）でクレジットを"
            "追加するか、自動リロードを有効にしてください。"
        )
    if getattr(exc, "status_code", None) == 429 or "rate limit" in low:
        return "Anthropic APIのレート制限に達しました。しばらく待ってから再試行してください。"
    return f"Anthropic APIエラー（{getattr(exc, 'status_code', '?')}）: {msg[:200]}"


def _stream_final_message(client, kwargs: dict):
    """Every call site here runs the same streamed request with the same
    adaptive-thinking-unsupported fallback; centralized so the Anthropic
    API error translation only has to happen in one place."""
    import anthropic

    try:
        try:
            with client.messages.stream(thinking={"type": "adaptive"}, **kwargs) as stream:
                return stream.get_final_message()
        except TypeError:
            # SDK too old for the adaptive thinking kwarg — run without it.
            with client.messages.stream(**kwargs) as stream:
                return stream.get_final_message()
    except anthropic.APIStatusError as exc:
        raise RuntimeError(_translate_anthropic_error(exc)) from exc


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
    msg = _stream_final_message(client, kwargs)

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


_FILTER_KEYWORDS_TOOL = {
    "name": "submit_relevant_keywords",
    "description": "候補キーワードの中から、このサイトで実際に記事化する価値があるものだけを選んで提出する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "relevant": {
                "type": "array",
                "items": {"type": "string"},
                "description": "候補のうち、このサイトの実際のテーマに合う語（元の表記のまま）",
            },
        },
        "required": ["relevant"],
    },
}


@dataclass(frozen=True)
class KeywordFilterResult:
    keywords: list[str]
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    faked: bool = False


def filter_relevant_keywords(
    candidates: list[str],
    *,
    system: str,
    model: str = "claude-sonnet-5",
    api_key: str | None = None,
    max_tokens: int = 4000,
) -> KeywordFilterResult:
    """Which of these keyword-idea candidates actually fit this site's real
    editorial niche? Google Ads' keyword-idea expansion happily returns
    homonym/brand-collision matches — e.g. seed "オフィス" (office storage,
    on-topic for a 収納 site) turning up "オフィス 365" (Microsoft's
    product, off-topic) in production — that share a literal token with an
    on-topic seed but aren't the same search intent at all. Token/bigram
    overlap can't tell those apart; a model reading the site's own system
    prompt can.

    Also excludes a second, subtler case found in production: keywords that
    ARE topically adjacent but name a real-estate company/property-brand/
    listing-service ("積水ハウス 賃貸", "アットホーム 賃貸", "大和ハウス
    賃貸") — genuinely about 賃貸, but a company-comparison or listing-site
    search, not something lifehouse2026's actual article type (a reader
    fixing a housing problem themselves) answers. First cut of this filter
    only caught the homonym case and let these through."""
    if not candidates:
        return KeywordFilterResult([], model, 0, 0, 0, 0, 0.0, faked=True)
    if _use_fake(api_key):
        return KeywordFilterResult(list(candidates), model, 0, 0, 0, 0, 0.0, faked=True)

    import anthropic  # lazy: keep import cost off the fake path

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    listing = "\n".join(f"- {k}" for k in candidates)
    message = (
        "次のキーワード候補の中から、このサイトで実際に記事化する価値がある"
        "ものだけを選んでください。上記のサイト説明にある通りの記事タイプ"
        "（読者が自分で対応・解決するための実用ガイド）として書けるかどうかで"
        "判断してください。次の2種類は除外してください:\n\n"
        "1. たまたま同じ単語を含むだけで検索意図がまったく違う語\n"
        "   （例: 収納サイトに対する「オフィス 365」＝Microsoft Officeソフトの検索）\n"
        "2. 話題としては近くても、このサイトの記事タイプ（実用ガイド）では"
        "答えられない語 — 特に企業名・ブランド名・サービス名そのものを含む検索"
        "（例: 賃貸系サイトに対する「積水ハウス 賃貸」「アットホーム 賃貸」"
        "「大和ハウス 賃貸」のような、不動産会社・住宅メーカー・物件検索サイトの"
        "名前が入った語。これらは会社比較・物件探しの検索であり、トラブル解決"
        "ガイドの読者が検索する語ではない）\n\n"
        "この2種類に当てはまらない限りは残してください。\n\n"
        f"{listing}\n\n"
        "選んだら submit_relevant_keywords を呼び出してください。"
    )
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": message}],
        tools=[_FILTER_KEYWORDS_TOOL],
        tool_choice={"type": "auto"},
    )
    msg = _stream_final_message(client, kwargs)

    u = msg.usage
    in_tok = int(getattr(u, "input_tokens", 0) or 0)
    out_tok = int(getattr(u, "output_tokens", 0) or 0)
    cr = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    cw = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    cost = cost_usd(model, in_tok, out_tok, cr, cw)

    tool_use = next(
        (b for b in msg.content if getattr(b, "type", None) == "tool_use"
         and getattr(b, "name", None) == "submit_relevant_keywords"),
        None,
    )
    if tool_use is None:
        # fail open — a parse miss shouldn't silently zero out every
        # candidate, just skip the extra filtering for this run
        return KeywordFilterResult(list(candidates), model, in_tok, out_tok, cr, cw, cost)

    relevant = tool_use.input.get("relevant")
    if not isinstance(relevant, list):
        return KeywordFilterResult(list(candidates), model, in_tok, out_tok, cr, cw, cost)

    keep = {str(k).strip() for k in relevant}
    kept = [c for c in candidates if c in keep]
    return KeywordFilterResult(kept, model, in_tok, out_tok, cr, cw, cost)


_SUBMIT_KEYWORD_IDEAS_TOOL = {
    "name": "submit_keyword_ideas",
    "description": "このサイトで新しく記事化する価値がある検索キーワード候補を提出する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3〜4語程度の、実際にユーザーがGoogleに打ち込む形の検索キーワード候補",
            },
        },
        "required": ["keywords"],
    },
}


@dataclass(frozen=True)
class KeywordIdeasResult:
    keywords: list[str]
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    faked: bool = False


def generate_seed_keywords(
    *,
    system: str,
    covered: list[str],
    count: int = 30,
    model: str = "claude-sonnet-5",
    api_key: str | None = None,
    max_tokens: int = 4000,
) -> KeywordIdeasResult:
    """Brainstorm new, on-topic keyword candidates directly — this is the
    method the project's earlier terminal-based workflow actually used
    (an editor/LLM choosing topics from real knowledge of the site's niche
    and existing coverage, each then volume-checked with what's now
    fetch_historical_metrics — the Python port of the old KeywordQueryRunner
    .exe tool, which only ever checked volume for keywords already chosen;
    it never generated them). Compare with this app's other path,
    generate_keyword_ideas() + filter_relevant_keywords(): expanding a seed
    through Google Ads' algorithmic keyword-idea service first and filtering
    the noise out afterward — in production that surfaced a lot of
    off-topic/homonym/brand-name candidates needing heavy filtering to clean
    up. Generating on-topic from the start avoids the problem instead of
    correcting it downstream."""
    if _use_fake(api_key):
        return KeywordIdeasResult(
            [f"テスト キーワード 案{i}" for i in range(count)],
            model, 0, 0, 0, 0, 0.0, faked=True,
        )

    import anthropic  # lazy: keep import cost off the fake path

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    covered_list = "\n".join(f"- {k}" for k in covered) or "（なし）"
    message = (
        f"このサイトで新しく記事化する価値がある検索キーワードを{count}個、"
        "提案してください。次の条件をすべて満たすこと:\n\n"
        "- 実際にユーザーがGoogle検索窓に打ち込む形そのままにすること。日本語の検索は"
        "名詞・動詞の断片を3〜4語並べるのが普通で、「〜する方法」「〜のやり方」まで"
        "含めた文章的な言い回し全体を1つの検索語にはしない\n"
        "  - 悪い例:「蛇口 水漏れ 自分で直す方法」（6語相当、文章になっている）\n"
        "  - 良い例:「蛇口 水漏れ 直し方」「賃貸 壁 穴 補修」（3〜4語、検索窓に"
        "実際に打ち込まれる形）\n"
        "- 3〜4語程度の具体的なロングテールキーワード（1〜2語の一般的な語は"
        "競合が強すぎて小規模サイトでは上位化できないので避ける。逆に5語以上に"
        "なる場合は、実際に検索されそうな短い言い回しに削ること）\n"
        "- このサイトの実際の記事タイプ（読者が自分で対応・解決するための"
        "実用ガイド）として書ける検索語であること\n"
        "- 企業名・ブランド名・サービス名そのものを含む語は避ける"
        "（会社比較や物件・商品探しはこのサイトの記事タイプではない）\n"
        "- 下記の「既にカバー済みのキーワード」と同じテーマ・意図の語は避ける\n\n"
        f"--- 既にカバー済みのキーワード ---\n{covered_list}\n\n"
        "考えたら submit_keyword_ideas を呼び出してください。"
    )
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": message}],
        tools=[_SUBMIT_KEYWORD_IDEAS_TOOL],
        tool_choice={"type": "auto"},
    )
    msg = _stream_final_message(client, kwargs)

    u = msg.usage
    in_tok = int(getattr(u, "input_tokens", 0) or 0)
    out_tok = int(getattr(u, "output_tokens", 0) or 0)
    cr = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    cw = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    cost = cost_usd(model, in_tok, out_tok, cr, cw)

    tool_use = next(
        (b for b in msg.content if getattr(b, "type", None) == "tool_use"
         and getattr(b, "name", None) == "submit_keyword_ideas"),
        None,
    )
    if tool_use is None:
        return KeywordIdeasResult([], model, in_tok, out_tok, cr, cw, cost)

    kw = tool_use.input.get("keywords")
    if not isinstance(kw, list):
        return KeywordIdeasResult([], model, in_tok, out_tok, cr, cw, cost)

    keywords = [str(k).strip() for k in kw if str(k).strip()]
    return KeywordIdeasResult(keywords, model, in_tok, out_tok, cr, cw, cost)


def _use_fake(api_key: str | None) -> bool:
    if os.environ.get("LLM_FAKE") == "1":
        return True
    return not (api_key or os.environ.get("ANTHROPIC_API_KEY"))


def generate_draft(
    req: DraftRequest,
    *,
    model: str = "claude-sonnet-5",
    api_key: str | None = None,
    max_tokens: int = 20000,
) -> DraftResult:
    """max_tokens is generous relative to a typical article: extended
    thinking shares the same token budget as the tool-call output, and a
    revision brief embedding the *entire existing article* as context (see
    article_improve.py's "rewrite" path) pushes both input and the expected
    output well past a fresh-generation draft's size. Seen in production
    hitting stop_reason="max_tokens" with the old 12000 default — the model
    had filled title/slug/meta_description/outline and never got to
    body_html at all. Cost tracks tokens actually used, not the cap."""
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
    msg = _stream_final_message(client, kwargs)

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
