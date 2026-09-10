"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  Card,
  Empty,
  ErrorNote,
  Pill,
  SectionTitle,
  Spinner,
  Td,
  Th,
  TableWrap,
} from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime, fmtUsd, jobStatusTone } from "@/lib/format";
import type { Job } from "@/lib/types";

function JobsInner() {
  const sp = useSearchParams();
  const focusId = sp.get("id");

  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [detail, setDetail] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.jobs(50).then(setJobs).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    if (focusId) api.job(focusId).then(setDetail).catch(() => setDetail(null));
    else setDetail(null);
  }, [focusId]);

  if (err) return <ErrorNote>読み込みに失敗しました: {err}</ErrorNote>;
  if (!jobs) return <Spinner />;

  return (
    <>
      {detail && (
        <>
          <SectionTitle>ジョブ詳細</SectionTitle>
          <Card className="flex flex-col gap-2">
            <div className="flex items-center gap-3">
              <code className="font-mono text-[13px]">{detail.kind}</code>
              <Pill tone={jobStatusTone(detail.status)}>{detail.status}</Pill>
              <span className="text-[12px] text-ink2">
                {fmtDateTime(detail.started_at)} → {fmtDateTime(detail.finished_at)}
              </span>
              <span className="ml-auto font-mono text-[12px] text-ink2">
                {fmtUsd(detail.llm_cost_usd, 4)}
              </span>
            </div>
            {detail.error && (
              <pre className="overflow-x-auto rounded-lg border border-crit/40 bg-crit/5 p-2 text-[12px] text-crit">
                {detail.error}
              </pre>
            )}
            {detail.result && (
              <pre className="overflow-x-auto rounded-lg border border-border bg-surface2 p-2 text-[12px]">
                {JSON.stringify(detail.result, null, 2)}
              </pre>
            )}
            <div className="font-mono text-[11px] text-ink2">{detail.id}</div>
          </Card>
        </>
      )}

      <SectionTitle>ジョブ履歴</SectionTitle>
      {jobs.length === 0 ? (
        <Empty>ジョブ履歴はまだありません。</Empty>
      ) : (
        <TableWrap>
          <thead>
            <tr>
              <Th>種別</Th>
              <Th>状態</Th>
              <Th num>ドメイン</Th>
              <Th num>コスト</Th>
              <Th num>作成</Th>
              <Th num>完了</Th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr
                key={j.id}
                className={focusId === j.id ? "bg-accent/5" : ""}
              >
                <Td>
                  <a href={`/jobs?id=${j.id}`} className="font-mono text-accent hover:underline">
                    {j.kind}
                  </a>
                </Td>
                <Td>
                  <Pill tone={jobStatusTone(j.status)}>{j.status}</Pill>
                </Td>
                <Td num>{j.domain_id ?? "—"}</Td>
                <Td num>{fmtUsd(j.llm_cost_usd, 4)}</Td>
                <Td num>{fmtDateTime(j.created_at)}</Td>
                <Td num>{fmtDateTime(j.finished_at)}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </>
  );
}

export default function JobsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <JobsInner />
    </Suspense>
  );
}
