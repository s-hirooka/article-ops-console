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
import type { DomainDetail, TopicIdeas } from "@/lib/types";

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
  const [autoBusy, setAutoBusy] = useState(false);
  const [autoErr, setAutoErr] = useState<string | null>(null);

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

  async function autoGenerate() {
    setAutoBusy(true);
    setAutoErr(null);
    try {
      const r = await api.runJob({
        kind: "topic_auto_generate",
        domain_id: domainId,
        params: { seeds: seedsFromText() },
      });
      if (r.status !== "succeeded") {
        setAutoErr(r.error || "記事の自動作成に失敗しました。");
        return;
      }
      const articleId = (r.result as { article_id?: number } | null)?.article_id;
      if (articleId) router.push(`/articles?id=${articleId}`);
    } catch (e) {
      setAutoErr((e as Error).message);
    } finally {
      setAutoBusy(false);
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
          <Button onClick={search} disabled={running || autoBusy}>
            {running ? "探索中…" : "テーマを探す"}
          </Button>
          <Button variant="ghost" onClick={autoGenerate} disabled={running || autoBusy}>
            {autoBusy ? "作成中…（30〜60秒）" : "🔍 おすすめキーワードで記事を自動作成"}
          </Button>
        </div>
        <div className="text-[12px] text-ink2">
          自動作成は候補の中から検索数と競合のバランスが良い1件を選び、そのまま記事生成まで
          実行します（Anthropic API の実課金が発生します）。
        </div>
      </Card>

      {autoErr && (
        <div className="mt-4">
          <ErrorNote>{autoErr}</ErrorNote>
        </div>
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
            既出 {res.covered_keywords} 語と閾値未満を除外
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
