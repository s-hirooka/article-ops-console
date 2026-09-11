"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  SectionTitle,
  Spinner,
  Td,
  Th,
  TableWrap,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { DomainDetail, TopicCandidate, TopicIdeas } from "@/lib/types";

export default function TopicsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <TopicsInner />
    </Suspense>
  );
}

function TopicsInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const domainId = Number(sp.get("id"));

  const [d, setD] = useState<DomainDetail | null>(null);
  const [seedText, setSeedText] = useState("");
  const [running, setRunning] = useState(false);
  const [res, setRes] = useState<TopicIdeas | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [topRunning, setTopRunning] = useState(false);
  const [topRes, setTopRes] = useState<TopicIdeas | null>(null);
  const [topErr, setTopErr] = useState<string | null>(null);
  const [genKeyword, setGenKeyword] = useState<string | null>(null);
  const [genErr, setGenErr] = useState<string | null>(null);

  useEffect(() => {
    if (domainId) api.domain(domainId).then(setD).catch(() => setD(null));
  }, [domainId]);

  function seedsFromText(): string[] {
    return seedText
      .split(/[\n,、]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  async function search() {
    setRunning(true);
    setErr(null);
    setRes(null);
    try {
      setRes(await api.topicIdeas(domainId, { seeds: seedsFromText(), limit: 30 }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  async function showRecommended() {
    setTopRunning(true);
    setTopErr(null);
    setGenErr(null);
    setTopRes(null);
    try {
      setTopRes(await api.topicIdeas(domainId, { seeds: seedsFromText(), limit: 30 }));
    } catch (e) {
      setTopErr((e as Error).message);
    } finally {
      setTopRunning(false);
    }
  }

  async function generateFor(c: TopicCandidate) {
    setGenKeyword(c.keyword);
    setGenErr(null);
    try {
      // Fire-and-forget + poll, not a single blocking request: article
      // generation (LLM call) can run past a minute — longer than the
      // browser/Render's proxy reliably holds one request open for — which
      // otherwise surfaces as a bare "Failed to fetch" even though the job
      // keeps running server-side and finishes fine.
      const started = await api.runJob({
        kind: "article_generate",
        domain_id: domainId,
        params: {
          target_keyword: c.keyword,
          search_volume: c.avg_monthly_searches ?? undefined,
          _async: true,
        },
      });
      let job = await api.job(started.job_id);
      while (job.status === "queued" || job.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        job = await api.job(started.job_id);
      }
      if (job.status !== "succeeded") {
        setGenErr(job.error || "記事の作成に失敗しました。");
        return;
      }
      const articleId = (job.result as { article_id?: number } | null)?.article_id;
      if (articleId) router.push(`/articles?id=${articleId}`);
    } catch (e) {
      setGenErr((e as Error).message);
    } finally {
      setGenKeyword(null);
    }
  }

  if (!domainId) return <ErrorNote>ドメインが指定されていません。</ErrorNote>;

  return (
    <>
      <div className="mb-1 text-[13px] text-ink2">
        <Link href="/" className="hover:underline">
          概要
        </Link>{" "}
        /{" "}
        <Link href={`/domains?id=${domainId}`} className="hover:underline">
          {d?.domain_key ?? "ドメイン"}
        </Link>{" "}
        / 新規テーマ探索
      </div>
      <SectionTitle>新規テーマ探索</SectionTitle>

      <Card className="flex max-w-xl flex-col gap-3">
        <label className="flex flex-col gap-1 text-[13px]">
          <span className="font-medium text-ink2">シードキーワード（任意・改行区切り）</span>
          <textarea
            value={seedText}
            onChange={(e) => setSeedText(e.target.value)}
            rows={3}
            placeholder={"空欄なら既存の上位クエリから自動でシードします\n例: 一人暮らし 収納\n例: 賃貸 修繕"}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent"
          />
        </label>
        <div className="text-[12px] text-ink2">
          Google Ads のキーワードアイデアを取得し、既にランク済み・記事化済みの語と
          月間検索数 {d?.keyword_threshold ?? 500} 未満を除外します（API を1回消費）。
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={search} disabled={running || topRunning}>
            {running ? "探索中…" : "テーマを探す（一覧）"}
          </Button>
          <Button variant="ghost" onClick={showRecommended} disabled={running || topRunning}>
            {topRunning ? "探索中…" : "🔍 おすすめキーワードを見る（上位10件）"}
          </Button>
        </div>
        <div className="text-[12px] text-ink2">
          おすすめキーワードは検索数と競合のバランスが良い順に10件表示します。キーワードを
          クリックするとその語で記事生成まで実行します（Anthropic API の実課金が発生します）。
        </div>
      </Card>

      {topErr && (
        <div className="mt-4">
          <ErrorNote>{topErr}</ErrorNote>
        </div>
      )}
      {genErr && (
        <div className="mt-2">
          <ErrorNote>{genErr}</ErrorNote>
        </div>
      )}

      {topRes && (
        <>
          <SectionTitle>おすすめキーワード（上位{topRes.recommended_top.length}件）</SectionTitle>
          <div className="mb-2 text-[12px] text-ink2">
            シード: {topRes.seeds_used.join(" / ") || "—"} ・ アイデア {topRes.ideas_returned} 件から、
            既出 {topRes.covered_keywords} 語・閾値未満・カニバリ疑い {topRes.cannibalization_excluded} 件
            （WordPress既存記事 {topRes.wp_posts_checked} 件・下書き {topRes.own_drafts_checked} 件と照合）を除外
          </div>
          {topRes.recommended_top.length === 0 ? (
            <Empty>
              条件に合う新規候補は見つかりませんでした。シードを変えるか閾値を下げてください。
            </Empty>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {topRes.recommended_top.map((c, i) => (
                <button
                  key={i}
                  onClick={() => generateFor(c)}
                  disabled={!!genKeyword}
                  className="flex flex-col gap-1 rounded-lg border border-border bg-surface px-4 py-3 text-left transition hover:border-accent disabled:opacity-60"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{c.keyword}</span>
                    <span className="shrink-0 text-[11px] text-ink2">
                      {c.competition_level ?? "—"}
                      {c.competition_index != null ? ` (${c.competition_index})` : ""}
                    </span>
                  </div>
                  <div className="text-[12px] text-ink2">
                    月間検索数 {c.avg_monthly_searches?.toLocaleString() ?? "—"}
                  </div>
                  <div className="mt-1 text-[12px] text-accent">
                    {genKeyword === c.keyword ? "作成中…（30〜90秒）" : "この語で記事を作成 →"}
                  </div>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {err && (
        <div className="mt-4">
          <ErrorNote>{err}</ErrorNote>
        </div>
      )}

      {res && (
        <>
          <SectionTitle>候補（{res.candidates.length}）</SectionTitle>
          <div className="mb-2 text-[12px] text-ink2">
            シード: {res.seeds_used.join(" / ") || "—"} ・ アイデア {res.ideas_returned} 件から、
            既出 {res.covered_keywords} 語・閾値未満・カニバリ疑い {res.cannibalization_excluded} 件
            （WordPress既存記事 {res.wp_posts_checked} 件・下書き {res.own_drafts_checked} 件と照合）を除外
          </div>
          {res.candidates.length === 0 ? (
            <Empty>
              条件に合う新規候補は見つかりませんでした。シードを変えるか閾値を下げてください。
            </Empty>
          ) : (
            <TableWrap>
              <thead>
                <tr>
                  <Th>キーワード</Th>
                  <Th num>月間検索数</Th>
                  <Th>競合</Th>
                  <Th>アクション</Th>
                </tr>
              </thead>
              <tbody>
                {res.candidates.map((c, i) => (
                  <tr
                    key={i}
                    className={c.keyword === res.recommended?.keyword ? "bg-accent/5" : ""}
                  >
                    <Td>
                      {c.keyword}
                      {c.keyword === res.recommended?.keyword && (
                        <span className="ml-2 rounded-full bg-accent/15 px-2 py-0.5 text-[11px] text-accent">
                          おすすめ
                        </span>
                      )}
                    </Td>
                    <Td num>{c.avg_monthly_searches?.toLocaleString() ?? "—"}</Td>
                    <Td className="text-[12px] text-ink2">
                      {c.competition_level ?? "—"}
                      {c.competition_index != null ? ` (${c.competition_index})` : ""}
                    </Td>
                    <Td>
                      <Link
                        href={`/domains/new?id=${domainId}&keyword=${encodeURIComponent(
                          c.keyword,
                        )}&volume=${c.avg_monthly_searches ?? ""}`}
                        className="text-[12px] text-accent hover:underline"
                      >
                        この語で記事を作成 →
                      </Link>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
        </>
      )}
    </>
  );
}
