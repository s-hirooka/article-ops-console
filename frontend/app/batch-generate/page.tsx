"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, Card, Empty, ErrorNote, Field, Input, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { DomainSummary } from "@/lib/types";

export default function BatchGeneratePage() {
  const [domains, setDomains] = useState<DomainSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<number, string>>({});
  const [starting, setStarting] = useState(false);
  const [startErr, setStartErr] = useState<string | null>(null);
  const [started, setStarted] = useState<{ domain_key: string; count: number; job_id: string }[] | null>(
    null,
  );

  useEffect(() => {
    api.domains().then(setDomains).catch((e) => setErr(e.message));
  }, []);

  function setCount(id: number, value: string) {
    setCounts((prev) => ({ ...prev, [id]: value.replace(/[^0-9]/g, "") }));
  }

  const selections = (domains || [])
    .map((d) => ({ domain: d, count: Number(counts[d.id] || 0) }))
    .filter((x) => x.count > 0);
  const totalArticles = selections.reduce((sum, x) => sum + x.count, 0);

  async function start() {
    if (selections.length === 0) return;
    setStarting(true);
    setStartErr(null);
    setStarted(null);
    try {
      // Fire one at a time, not Promise.all: creating two "_async" jobs in
      // the same instant has been observed to silently drop one of the two
      // background tasks on Render's free plan (it never starts, stuck at
      // "queued" forever) -- a brief gap between requests avoids the race.
      const results: { domain_key: string; count: number; job_id: string }[] = [];
      for (const { domain, count } of selections) {
        if (results.length > 0) await new Promise((resolve) => setTimeout(resolve, 1500));
        const r = await api.runJob({
          kind: "topic_auto_generate",
          domain_id: domain.id,
          params: { count, _async: true },
        });
        results.push({ domain_key: domain.domain_key, count, job_id: r.job_id });
      }
      setStarted(results);
      setCounts({});
    } catch (e) {
      setStartErr((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  if (err) return <ErrorNote>読み込みに失敗しました: {err}</ErrorNote>;
  if (!domains) return <Spinner />;

  return (
    <>
      <SectionTitle>一括記事生成</SectionTitle>
      <div className="mb-3 max-w-xl text-[12px] text-ink2">
        ドメインごとに作成する記事数を入力してください。キーワードはAIがサイトのテーマから
        毎回自動で選びます（既に使ったキーワードは選び直されません）。開始すると全てバックグラウンドで
        実行されるので、このページを閉じても記事の作成は続きます。進捗は
        <Link href="/jobs" className="text-accent hover:underline">
          ジョブ
        </Link>
        ページで確認できます。
      </div>

      {domains.length === 0 ? (
        <Empty>ドメインがありません。</Empty>
      ) : (
        <Card className="flex max-w-xl flex-col gap-3">
          {domains.map((d) => (
            <div key={d.id} className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[13px] font-medium">{d.domain_key}</div>
                <div className="font-mono text-[11px] text-ink2">{d.base_url}</div>
              </div>
              <Field label="記事数">
                <Input
                  value={counts[d.id] ?? ""}
                  onChange={(e) => setCount(d.id, e.target.value)}
                  placeholder="0"
                  inputMode="numeric"
                  className="w-20 text-right"
                />
              </Field>
            </div>
          ))}
        </Card>
      )}

      <div className="mt-3 flex max-w-xl flex-wrap items-center gap-3">
        <Button onClick={start} disabled={starting || totalArticles === 0}>
          {starting
            ? "開始中…"
            : totalArticles > 0
              ? `合計 ${totalArticles} 件を作成開始`
              : "記事数を入力してください"}
        </Button>
        <span className="text-[12px] text-ink2">
          Anthropic API の実課金が発生します（1記事あたり目安 $0.05〜0.20）。
        </span>
      </div>

      {startErr && (
        <div className="mt-3 max-w-xl">
          <ErrorNote>{startErr}</ErrorNote>
        </div>
      )}

      {started && (
        <div className="mt-4 max-w-xl rounded-lg border border-ok/40 bg-ok/10 px-3 py-2 text-[13px] text-ok">
          ✅ {started.length}ドメインでジョブを開始しました:{" "}
          {started.map((s) => `${s.domain_key}(${s.count}件)`).join("、")}。
          <Link href="/jobs" className="ml-1 font-medium text-accent hover:underline">
            ジョブ一覧で進捗を見る →
          </Link>
        </div>
      )}
    </>
  );
}
