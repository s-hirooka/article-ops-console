"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, Empty, ErrorNote, Pill, SectionTitle, Spinner, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime, fmtUsd, jobStatusTone } from "@/lib/format";
import type { DomainSummary, Job, UsageLlm } from "@/lib/types";

export default function Dashboard() {
  const [domains, setDomains] = useState<DomainSummary[] | null>(null);
  const [usage, setUsage] = useState<UsageLlm | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.domains(), api.usageLlm(), api.jobs(8)])
      .then(([d, u, j]) => {
        setDomains(d);
        setUsage(u);
        setJobs(j);
      })
      .catch((e) => setErr(e.message));
  }, []);

  if (err) return <ErrorNote>読み込みに失敗しました: {err}</ErrorNote>;
  if (!domains || !usage || !jobs) return <Spinner />;

  const pct = usage.budget_usd ? Math.round((100 * usage.spent_usd) / usage.budget_usd) : 0;

  return (
    <>
      <SectionTitle>AI予算（{usage.period}）</SectionTitle>
      <Card className="max-w-md">
        <div className="flex gap-6">
          <Stat value={fmtUsd(usage.spent_usd)} label="今月の消費" />
          <Stat value={fmtUsd(usage.budget_usd)} label="上限" />
          <Stat value={`${pct}%`} label="消化率" />
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded bg-surface2">
          <div
            className="h-full bg-accent"
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
        <div className="mt-2 text-[12px] text-ink2">
          超過時の動作 <code className="rounded bg-surface2 px-1.5 py-0.5 font-mono">{usage.budget_action}</code>
          {usage.remaining_usd != null && <> ・ 残り {fmtUsd(usage.remaining_usd)}</>}
        </div>
      </Card>

      <SectionTitle>ドメイン（{domains.length}）</SectionTitle>
      {domains.length === 0 ? (
        <Empty>ドメインがありません。</Empty>
      ) : (
        <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
          {domains.map((d) => (
            <Card key={d.id}>
              <h3 className="text-[14px] font-semibold">
                <Link href={`/domains/${d.id}`} className="text-accent hover:underline">
                  {d.domain_key}
                </Link>
              </h3>
              <div className="mt-0.5 break-all font-mono text-[12px] text-ink2">{d.base_url}</div>
              <div className="mt-3 flex gap-6">
                <Stat value={d.keyword_threshold} label="検索数の下限" />
              </div>
              <div className="mt-3 flex gap-2">
                <Link
                  href={`/domains/${d.id}/new`}
                  className="text-[12px] text-accent hover:underline"
                >
                  ＋ 新規記事
                </Link>
                <Link
                  href={`/domains/${d.id}/prompts`}
                  className="text-[12px] text-accent hover:underline"
                >
                  プロンプト編集
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}

      <SectionTitle>最近のジョブ</SectionTitle>
      {jobs.length === 0 ? (
        <Empty>ジョブ履歴はまだありません。</Empty>
      ) : (
        <div className="overflow-x-auto rounded-[10px] border border-border bg-surface">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                {["種別", "状態", "ドメイン", "コスト", "完了"].map((h, i) => (
                  <th
                    key={h}
                    className={`border-b border-border px-2.5 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink2 ${i > 1 ? "text-right" : "text-left"}`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td className="border-b border-border px-2.5 py-2">
                    <Link href={`/jobs?id=${j.id}`} className="font-mono text-accent hover:underline">
                      {j.kind}
                    </Link>
                  </td>
                  <td className="border-b border-border px-2.5 py-2">
                    <Pill tone={jobStatusTone(j.status)}>{j.status}</Pill>
                  </td>
                  <td className="border-b border-border px-2.5 py-2 text-right font-mono tabular-nums">
                    {j.domain_id ?? "—"}
                  </td>
                  <td className="border-b border-border px-2.5 py-2 text-right font-mono tabular-nums">
                    {fmtUsd(j.llm_cost_usd, 4)}
                  </td>
                  <td className="border-b border-border px-2.5 py-2 text-right font-mono tabular-nums">
                    {fmtDateTime(j.finished_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
