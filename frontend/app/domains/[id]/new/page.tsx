"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";
import {
  Button,
  Card,
  ErrorNote,
  Field,
  Input,
  SectionTitle,
  Spinner,
} from "@/components/ui";
import { api } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import type { Article, DomainDetail } from "@/lib/types";

type GenResult = {
  article_id?: number;
  title?: string;
  slug?: string;
  model?: string;
  cost_usd?: number;
  faked?: boolean;
  search_volume?: number | null;
  keyword_threshold?: number;
  warnings?: string[];
};

export default function NewArticlePage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<Spinner />}>
      <NewArticleInner params={params} />
    </Suspense>
  );
}

function NewArticleInner({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const domainId = Number(id);
  const sp = useSearchParams();

  const [d, setD] = useState<DomainDetail | null>(null);
  const [keyword, setKeyword] = useState(sp.get("keyword") ?? "");
  const [volume, setVolume] = useState("");
  const [force, setForce] = useState(false);
  const [extra, setExtra] = useState("");

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<GenResult | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const [article, setArticle] = useState<Article | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishMsg, setPublishMsg] = useState<string | null>(null);

  useEffect(() => {
    api.domain(domainId).then(setD).catch(() => setD(null));
    const aId = sp.get("article");
    if (aId) {
      api
        .articles(domainId)
        .then((rows) => setArticle(rows.find((r) => r.id === Number(aId)) ?? null))
        .catch(() => {});
    }
  }, [domainId, sp]);

  async function generate() {
    setRunning(true);
    setFailed(null);
    setResult(null);
    setArticle(null);
    setPublishMsg(null);
    try {
      const params: Record<string, unknown> = { target_keyword: keyword.trim() };
      if (volume.trim()) params.search_volume = Number(volume);
      if (force) params.force = true;
      if (extra.trim()) params.extra_instructions = extra.trim();
      const r = await api.runJob({ kind: "article_generate", domain_id: domainId, params });
      if (r.status === "succeeded") {
        setResult((r.result as GenResult) ?? {});
        const aid = (r.result as GenResult)?.article_id;
        if (aid) {
          const rows = await api.articles(domainId);
          setArticle(rows.find((x) => x.id === aid) ?? null);
        }
      } else {
        setFailed(r.error || `ジョブが ${r.status} で終了しました`);
      }
    } catch (e) {
      setFailed((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  async function publish() {
    if (!article) return;
    setPublishing(true);
    setPublishMsg(null);
    try {
      const r = await api.publish(article.id, "publish");
      setPublishMsg(
        `公開しました（wp_post_id ${r.wp_post_id}）` +
          (r.link ? ` — ${r.link}` : "") +
          (r.warnings?.length ? ` / 注意: ${r.warnings.join(" ")}` : ""),
      );
      const rows = await api.articles(domainId);
      setArticle(rows.find((x) => x.id === article.id) ?? article);
    } catch (e) {
      setPublishMsg(`公開に失敗: ${(e as Error).message}`);
    } finally {
      setPublishing(false);
    }
  }

  return (
    <>
      <div className="mb-1 text-[13px] text-ink2">
        <Link href="/" className="hover:underline">
          概要
        </Link>{" "}
        /{" "}
        <Link href={`/domains/${domainId}`} className="hover:underline">
          {d?.domain_key ?? "ドメイン"}
        </Link>{" "}
        / 新規記事
      </div>
      <SectionTitle>新規記事を作成</SectionTitle>

      <Card className="flex max-w-xl flex-col gap-3">
        <Field label="対象キーワード">
          <Input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="例: CD 収納"
          />
        </Field>
        <div className="flex gap-3">
          <Field
            label="月間検索数（任意）"
            hint="未入力なら google-ads で取得を試みます"
          >
            <Input
              value={volume}
              onChange={(e) => setVolume(e.target.value.replace(/[^0-9]/g, ""))}
              placeholder={d ? String(d.keyword_threshold) : "500"}
              inputMode="numeric"
            />
          </Field>
          <label className="mt-6 flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={force}
              onChange={(e) => setForce(e.target.checked)}
            />
            閾値を無視して生成
          </label>
        </div>
        <Field label="追加指示（任意）">
          <textarea
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
            rows={3}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent"
            placeholder="トーンや必須で触れてほしい点など"
          />
        </Field>
        <div>
          <Button onClick={generate} disabled={running || !keyword.trim()}>
            {running ? "生成中…（30〜60秒）" : "記事を生成"}
          </Button>
        </div>
        {running && (
          <div className="text-[12px] text-ink2">
            LLM が本文を生成しています。このタブを開いたままお待ちください。
          </div>
        )}
      </Card>

      {failed && (
        <div className="mt-4">
          <ErrorNote>生成に失敗しました: {failed}</ErrorNote>
        </div>
      )}

      {result && (
        <>
          <SectionTitle>生成結果</SectionTitle>
          <Card className="flex flex-col gap-2">
            <div className="text-[15px] font-semibold">{result.title}</div>
            <div className="font-mono text-[12px] text-ink2">/{result.slug}</div>
            <div className="mt-1 flex flex-wrap gap-4 text-[12px] text-ink2">
              <span>モデル {result.model}</span>
              <span>コスト {fmtUsd(result.cost_usd, 4)}</span>
              <span>検索数 {result.search_volume ?? "—"}</span>
              {result.faked && <span className="text-warn">（フェイク生成）</span>}
            </div>
            {result.warnings && result.warnings.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-[12px] text-warn">
                {result.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      {article && (
        <>
          <SectionTitle>WordPress 公開</SectionTitle>
          <Card className="flex flex-col gap-3">
            <div className="text-[13px]">
              状態 <b>{article.status}</b>
              {article.wp_post_id ? ` · 投稿ID ${article.wp_post_id}` : ""}
            </div>
            <div>
              <Button
                onClick={publish}
                disabled={publishing || article.status === "published"}
              >
                {publishing
                  ? "公開中…"
                  : article.status === "published"
                    ? "公開済み"
                    : "WordPress に公開"}
              </Button>
            </div>
            {publishMsg && <div className="text-[12px] text-ink2">{publishMsg}</div>}
          </Card>
        </>
      )}

      {!d && <Spinner />}
    </>
  );
}
