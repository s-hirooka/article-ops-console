"""Seed per-domain article-generation prompts (the 8 editable components).

These reproduce the conventions the two sites' articles were actually written
to (Gutenberg block markup, comparison table first, per-item product block,
E-E-A-T editorial-name policy, Cocoon meta-description note, internal-link
rules). Run once; edits afterwards happen in the UI (a new version each save).

    DATABASE_URL=postgresql://app_user:...  APP_ENCRYPTION_KEY=...(unused here) \
      python scripts/seed_domain_prompts.py

Idempotent: if the latest saved body already matches, it is skipped.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text

from app.config import AppSettings
from app.db import models as m
from app.db.session import SessionLocal

# ---------------------------------------------------------------------------
# 共通方針（両サイト）
# ---------------------------------------------------------------------------
_EEAT = (
    "著者は編集部名義（実名・ペンネームは使わない）。事実として主張してよいのは"
    "「賃貸／一人暮らしの実体験」だけ。次は書かない: 紹介商品を実際に購入・使用して"
    "検証したという主張、公的資料・一次情報を確認したという新規の主張、保有資格、"
    "専門家による監修。「実際に使ってみた」「編集部が検証した」等の表現は禁止。"
)
_COCOON = (
    "本文は Gutenberg のブロックコメント記法（<!-- wp:paragraph --> 等）で書く。"
    "メタディスクリプションは Cocoon の SEO 欄が REST API 非対応のため本文には含めず、"
    "meta_description フィールドに 120 字以内で別途出力する（手動貼り付け用）。"
)
_INTERNAL_LINK = (
    "本文末尾に「あわせて読みたい」の見出しを作り、同ドメインの関連記事を 2〜3 本、"
    "<ul> のリンクで挙げる。URL は必ず実在のパーマリンクだけを使い、日付・スラッグを"
    "推測して組み立てない（不明なら空欄にして、あとで人が補う前提のコメントを残す）。"
)
_CANNIBALIZATION = (
    "既存記事と食い合わないよう、同義キーワードや近接テーマの h3 見出しと重複しない"
    "切り口にする。"
)

# ---------------------------------------------------------------------------
# lifehouse2026.com — 住まいトラブル回避ナビ 編集部
#   住まいの修理・交換・トラブル解決（賃貸目線）／Amazon アソシエイトで収益化
# ---------------------------------------------------------------------------
LIFEHOUSE = {
    "system_prompt": (
        "あなたは「住まいトラブル回避ナビ 編集部」として、賃貸・持ち家の住まいの"
        "トラブル（水回り・建具・鍵・窓・電気設備など）を自分で解決するための"
        "実用記事を書く編集者です。読者は「洗ってもうろこが取れない」「立て付けが悪い」"
        "など具体的な不具合を今すぐ直したい個人。まず結論（交換すべきか・自分でできるか）"
        "を先に示し、その後で製品比較に入ります。誇張せず、できない場合の代替策"
        "（管理会社・大家への連絡、業者依頼の目安）も一言添えます。\n\n"
        f"{_EEAT}\n\n{_COCOON}"
    ),
    "article_structure": (
        "1) 冒頭に PR 表記: <p class=\"has-text-align-right wp-block-paragraph\">"
        "<span class=\"fz-12px\">※本記事はPRを含みます。</span></p>\n"
        "2) 導入（症状の具体描写 → クリーナー等で改善しないなら交換が早い、等の結論の方向性）\n"
        "3) <h2>まず結論｜早見表</h2> … <table> 3列（商品名 / 価格の目安 / 特徴）で "
        "3〜5 商品分。商品名セルは [[PRODUCT_TITLE:検索語]]、価格セルは [[PRODUCT_PRICE:検索語]]"
        "（トークンの仕様は product_block_spec のルールに従う。<a href> は自分で書かない）\n"
        "4) <h2>商品ごとの詳細</h2> … 商品ごとに <h3>1. 商品カテゴリ</h3> を作り、"
        "[[PRODUCT_BLOCK:検索語]] → 2〜3 文の説明 → <ul> で「価格帯」「こんな人に」\n"
        "5) <h2>選ぶ前に確認したいこと</h2> … 取り付け金具の規格・賃貸での原状回復・"
        "自分で作業できる範囲の目安\n"
        "6) <h2>よくある質問</h2> … h3 で 3 問\n"
        "7) <h2>まとめ</h2>\n"
        "8) 「あわせて読みたい」\n\n"
        f"{_CANNIBALIZATION}"
    ),
    "product_block_spec": (
        "【重要】ASIN・Amazon商品URL・商品画像URL・価格を絶対に自分で作らない・推測しない。"
        "実在しないASIN（例: B0001XXXXA のような連番）や適当な価格を書くと、公開後に"
        "リンク切れ・商品が表示されない不具合になる。これは内部リンクの実在URLルールと同じ扱い。\n\n"
        "商品は3〜5点。各商品につき、次の3種類のトークンをそのまま出力する"
        "（公開前の自動処理でAmazonの実在商品に置き換わる。<a href>・<img>は自分で書かない）:\n"
        "  [[PRODUCT_TITLE:<検索に使える具体的な商品カテゴリ、例: 浴室鏡 交換用 曇り止め>]]"
        " … 商品名＋実在リンクに置き換わる\n"
        "  [[PRODUCT_PRICE:<同じ検索語>]] … 実勢価格に置き換わる（自分で価格を書かない）\n"
        "  [[PRODUCT_BLOCK:<同じ検索語>]] … 商品画像＋実在リンクのブロックに置き換わる\n\n"
        "同じ商品を指すトークンは検索語（コロンの後ろ）を一字一句同じ文字列にする"
        "（表記が違うと別商品として扱われてしまう）。検索語はジャンル名だけでなく"
        "「浴室鏡 交換用 曇り止め」のように用途・形状を含めた具体的なフレーズにする。"
        "vc_auto_ads ショートコードはこのサイトでは使わない。"
    ),
    "internal_link_policy": _INTERNAL_LINK,
    "title_format": (
        "32 文字前後。対象キーワードを前方に置き、"
        "「おすすめ〇選比較」「〜のときの買い替えに」「〜が取れないときは」など、"
        "症状 or 行動を示す語を1つ入れる。区切りは全角の｜。H1 はタイトルと同一。"
    ),
    "vc_auto_ads_defaults": (
        '{\n  "_note": "lifehouse2026 は vc_auto_ads を使わず Amazon 手動リンク。'
        '本フィールドは未使用。",\n  "enabled": false\n}'
    ),
    "eyecatch_style": (
        '{\n  "preset": "navy_check",\n  "width": 1376,\n  "height": 768,\n'
        '  "badge": "住まいのトラブル解決"\n}'
    ),
    "keyword_threshold": "500",
}

# ---------------------------------------------------------------------------
# comfortablelivinglab.com — ひとり暮らしの買い物メモ 編集部
#   一人暮らしの収納・便利グッズ／[vc_auto_ads] ショートコードで収益化
# ---------------------------------------------------------------------------
_VC_EXCLUDE = "ふるさと納税,ままごと,おままごと,キャンプ,アウトドア,バーベキュー,BBQ,おもちゃ,玩具"

COMFORTABLE = {
    "system_prompt": (
        "あなたは「ひとり暮らしの買い物メモ 編集部」として、一人暮らしの収納・"
        "整理・便利グッズを紹介する実用記事を書く編集者です。読者は収納スペースが"
        "限られたワンルームで、特定のモノ（CD・水筒・書類など）の置き場所に困っている人。"
        "「まず手持ちを分類する → 用途に合うグッズを選ぶ」という順で、省スペースと"
        "取り出しやすさの両立を軸にアイデアを列挙します。全部そろえる必要はない、と"
        "毎回釘を刺します。\n\n"
        f"{_EEAT}\n\n{_COCOON}"
    ),
    "article_structure": (
        "1) 導入（散らかりの具体描写 → この記事で紹介するアイデア数と選定軸）\n"
        "2) <h2>まず結論｜◯◯収納グッズ比較表</h2> … <table> 3列"
        "（収納グッズ / 解決できる悩み / 向いている人）で 5 行前後\n"
        "3) <h2>◯◯収納で最初に考えるべきこと</h2> … 手持ちを 3 グループに分ける <ul>、"
        "「よく使う分は手前、それ以外は省スペースに」というルール\n"
        "4) <h2>◯◯収納アイデア10選</h2> … <h3>1. △△で□□する</h3> の形で 10 項目。"
        "各 h3 は「2〜3 文の説明 → 商品ブロック → 選ぶポイント1文」の順\n"
        "5) <h2>よくある質問</h2> … h3 で 3 問\n"
        "6) <h2>まとめ</h2>\n"
        "7) 「あわせて読みたい」\n\n"
        f"{_CANNIBALIZATION}"
    ),
    "product_block_spec": (
        "「アイデア10選」の各 <h3> 直後に、商品ブロックのショートコードを1つ置く:\n"
        "[vc_auto_ads keyword=\"<用途・形状を含む3語程度>\" source=\"all\" limit=\"3\" "
        f"exclude=\"{_VC_EXCLUDE}\" slot=\"<英数字のユニークID>\" title=\"<その項目の要約>\"]\n"
        "keyword はジャンル名だけにせず「CD収納ラック タワー型」「水切りかご 食器 コンパクト」"
        "のように用途・形状を足す。関係ない商品（ジュエリー・雑誌など）が出たら keyword を"
        "言い換える。slot は項目ごとに変える。"
    ),
    "internal_link_policy": _INTERNAL_LINK,
    "title_format": (
        "32 文字前後。対象キーワードを前方に置き、「アイデア10選」「すっきり整理するコツ」"
        "など件数 or ベネフィットの語を入れる。区切りは全角の｜で"
        "「◯◯収納アイデア10選｜一人暮らしの△△をすっきり整理するコツ」の型。H1 はタイトルと同一。"
    ),
    "vc_auto_ads_defaults": (
        '{\n  "source": "all",\n  "limit": 3,\n  "slot": 1,\n'
        f'  "exclude": "{_VC_EXCLUDE}"\n}}'
    ),
    "eyecatch_style": (
        '{\n  "preset": "warm_flat",\n  "width": 1536,\n  "height": 1024,\n'
        '  "badge": "一人暮らしの収納アイデア"\n}'
    ),
    "keyword_threshold": "500",
}

DOMAIN_PROMPTS = {
    "lifehouse2026": LIFEHOUSE,
    "comfortablelivinglab": COMFORTABLE,
}


def main() -> int:
    account_id = AppSettings.from_env().dev_account_id
    added = skipped = 0
    with SessionLocal() as s:
        if s.bind.dialect.name == "postgresql":
            s.execute(text(f"SET app.account_id = '{int(account_id)}'"))

        for domain_key, components in DOMAIN_PROMPTS.items():
            domain = s.scalar(
                select(m.Domain).where(
                    m.Domain.account_id == account_id,
                    m.Domain.domain_key == domain_key,
                )
            )
            if domain is None:
                print(f"! domain '{domain_key}' が見つかりません（seed_from_sites を先に）")
                continue

            for component, body in components.items():
                latest = s.scalar(
                    select(m.DomainPrompt)
                    .where(
                        m.DomainPrompt.domain_id == domain.id,
                        m.DomainPrompt.component == component,
                    )
                    .order_by(m.DomainPrompt.version.desc())
                )
                if latest is not None and latest.body.strip() == body.strip():
                    skipped += 1
                    continue
                version = (latest.version if latest else 0) + 1
                s.add(
                    m.DomainPrompt(
                        account_id=account_id,
                        domain_id=domain.id,
                        component=component,
                        version=version,
                        body=body,
                        edited_by=None,
                    )
                )
                added += 1
                print(f"+ {domain_key} / {component} v{version}")
        s.commit()

    print(f"\ndone: {added} 版を追加、{skipped} 件は既存と同一でスキップ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
