"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Button, Card, ErrorNote, Pill, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime, fmtUsd } from "@/lib/format";
import type { ArticleDetail } from "@/lib/types";

export default function ArticlePage() {
  return (
    <Suspense fallback={<Spinner />}>
      <ArticleInner />
    </Suspense>
  );
}

function ArticleInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const articleId = Number(sp.get("id"));

  const [a, setA] = useState<ArticleDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  function load() {
    api
      .article(articleId)
      .then(setA)
      .catch((e) => setErr(e.message));
  }
  useEffect(() => {
    if (articleId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [articleId]);

  async function doPublish(status: "publish" | "draft") {
    setBusy(status);
    setMsg(null);
    try {
      const r = await api.publish(articleId, status);
      setMsg(
        status === "publish"
          ? `公開しました（wp_post_id ${r.wp_post_id}）` + (r.link ? ` — ${r.link}` : "")
          : `WordPress に下書き保存しました（wp_post_id ${r.wp_post_id}）`,
      );
      load();
    } catch (e) {
      setMsg(`失敗: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function doDelete() {
    const trashWp =
      !!a?.wp_post_id &&
      window.confirm(
        "WordPress 側もゴミ箱に移動しますか？\nOK: ゴミ箱へ  /  キャンセル: WP は下書きに戻して残す",
      );
    if (!window.confirm("この記事を削除します。よろしいですか？")) return;
    setBusy("delete");
    try {
      await api.deleteArticle(articleId, trashWp);
      const back = a?.domain_id ? `/domains?id=${a.domain_id}` : "/";
      router.push(back);
    } catch (e) {
      setMsg(`削除失敗: ${(e as Error).message}`);
      setBusy(null);
    }
  }

  if (!articleId) return <ErrorNote>記事が指定されていません。</ErrorNote>;
  if (err) return <ErrorNote>読み込みに失敗しました: {err}</ErrorNote>;
  if (!a) return <Spinner />;

  return (
    <>
      <div className="mb-1 text-[13px] text-ink2">
        <Link href="/" className="hover:underline">
          概要
        </Link>{" "}
        /{" "}
        <Link href={`/domains?id=${a.domain_id}`} className="hover:underline">
          ドメイン
        </Link>{" "}
        / 記事
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">{a.title || "（無題）"}</h1>
        <Pill
          tone={a.status === "published" ? "ok" : a.status === "failed" ? "crit" : "muted"}
        >
          {a.status}
        </Pill>
        {a.faked && <Pill tone="warn">フェイク生成</Pill>}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink2">
        <span>/{a.slug}</span>
        <span>対象KW: {a.target_keyword || "—"}</span>
        <span>想定検索数: {a.target_search_volume ?? "—"}</span>
        <span>作成: {fmtDateTime(a.created_at)}</span>
        {a.wp_post_id ? <span>投稿ID: {a.wp_post_id}</span> : null}
        {a.wp_link ? (
          <a href={a.wp_link} target="_blank" rel="noreferrer" className="text-accent hover:underline">
            WPで開く ↗
          </a>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button onClick={() => doPublish("publish")} disabled={!!busy}>
          {busy === "publish" ? "公開中…" : "WordPress に公開"}
        </Button>
        <Button variant="ghost" onClick={() => doPublish("draft")} disabled={!!busy}>
          {busy === "draft" ? "保存中…" : "WordPress に下書き保存"}
        </Button>
        <Button variant="ghost" onClick={doDelete} disabled={!!busy}>
          {busy === "delete" ? "削除中…" : "削除"}
        </Button>
        {msg && <span className="text-[12px] text-ink2">{msg}</span>}
      </div>

      {a.meta_description && (
        <div className="mt-3 rounded-lg border border-warn/40 bg-warn/5 p-3 text-[13px]">
          <div className="mb-1 font-medium text-ink2">
            メタディスクリプション（Cocoon の SEO 欄に手動貼り付け）
          </div>
          {a.meta_description}
        </div>
      )}

      {a.warnings.length > 0 && (
        <ul className="mt-3 list-disc rounded-lg border border-border bg-surface2 px-6 py-3 text-[12px] text-warn">
          {a.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      <SectionTitle>本文プレビュー</SectionTitle>
      {a.body_html ? (
        <Card>
          <div className="prose" dangerouslySetInnerHTML={{ __html: a.body_html }} />
        </Card>
      ) : (
        <ErrorNote>本文がありません。</ErrorNote>
      )}
    </>
  );
}
