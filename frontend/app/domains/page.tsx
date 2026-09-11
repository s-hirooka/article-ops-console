"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import RankChart from "@/components/RankChart";
import {
  Card,
  Empty,
  ErrorNote,
  Pill,
  SectionTitle,
  Spinner,
  Stat,
  Td,
  Th,
  TableWrap,
} from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, fmtDateTime, num, severityTone } from "@/lib/format";
import { HINT_LABEL, VERDICT_LABEL } from "@/lib/types";
import type {
  Alert,
  Article,
  DomainDetail,
  ImproveHistoryEntry,
  ImproveVerdict,
  RankRow,
  Recommendations,
} from "@/lib/types";

export default function DomainPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <DomainInner />
    </Suspense>
  );
}

function DomainInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const domainId = Number(sp.get("id"));

  const [d, setD] = useState<DomainDetail | null>(null);
  const [rank, setRank] = useState<RankRow[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [articles, setArticles] = useState<Article[]>([]);
  const [rec, setRec] = useState<Recommendations | null>(null);
  const [improveHist, setImproveHist] = useState<ImproveHistoryEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [improving, setImproving] = useState<string | null>(null);
  const [improveErr, setImproveErr] = useState<string | null>(null);

  function load() {
    if (!domainId) return;
    Promise.all([
      api.domain(domainId),
      api.rankHistory(domainId, 90),
      api.alerts(domainId, 30),
      api.articles(domainId),
      api.recommendations(domainId),
      api.improveHistory(domainId),
    ])
      .then(([dd, rk, al, ar, rc, ih]) => {
        setD(dd);
        setRank(rk);
        setAlerts(al);
        setArticles(ar);
        setRec(rc);
        setImproveHist(ih);
      })
      .catch((e) => setErr(e.message));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domainId]);

  async function runJobAndWait(kind: string, params: Record<string, unknown> = {}) {
    const started = await api.runJob({
      kind,
      domain_id: domainId,
      params: { ...params, _async: true },
    });
    let job = await api.job(started.job_id);
    while (job.status === "queued" || job.status === "running") {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      job = await api.job(started.job_id);
    }
    return job;
  }

  async function syncNow() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const rs = await runJobAndWait("rank_sync");
      if (rs.status !== "succeeded") {
        setSyncMsg(`Search Console 同期に失敗: ${rs.error || rs.status}`);
        return;
      }
      const an = await runJobAndWait("analysis");
      if (an.status !== "succeeded") {
        setSyncMsg(`同期は完了、分析に失敗: ${an.error || an.status}`);
        load();
        return;
      }
      const rows = (rs.result as { rows_written?: number } | null)?.rows_written ?? 0;
      setSyncMsg(`同期完了（${rows}行）・分析も更新しました。`);
      load();
    } catch (e) {
      setSyncMsg((e as Error).message);
    } finally {
      setSyncing(false);
    }
  }

  async function improveNow(o: Recommendations["improvement_candidates"][number]) {
    setImproving(o.url);
    setImproveErr(null);
    try {
      const job = await runJobAndWait("improve_article", {
        url: o.url,
        keyword: o.keyword,
        action_hint: o.action_hint,
      });
      if (job.status !== "succeeded") {
        setImproveErr(job.error || "AIによる修正に失敗しました。");
        return;
      }
      const articleId = (job.result as { article_id?: number } | null)?.article_id;
      if (articleId) router.push(`/articles?id=${articleId}`);
    } catch (e) {
      setImproveErr((e as Error).message);
    } finally {
      setImproving(null);
    }
  }

  if (!domainId) return <ErrorNote>ドメインが指定されていません。</ErrorNote>;
  if (err) return <ErrorNote>読み込みに失敗しました: {err}</ErrorNote>;
  if (!d) return <Spinner />;

  return (
    <>
      <div className="mb-1 text-[13px] text-ink2">
        <Link href="/" className="hover:underline">
          概要
        </Link>{" "}
        / {d.domain_key}
      </div>

      <SectionTitle>{d.domain_key}</SectionTitle>
      <Card>
        <div className="font-mono text-[12px] text-ink2">
          {d.base_url} · GSC: {d.gsc_site_url}
        </div>
        <div className="mt-3.5 flex flex-wrap gap-6">
          <Stat value={d.keyword_threshold} label="月間検索数の下限" />
          <Stat value={d.has_wp_credentials ? "あり" : "なし"} label="WP認証" />
          <Stat value={d.has_own_anthropic_key ? "専用" : "共有"} label="APIキー" />
        </div>
        <div className="mt-3 flex flex-wrap gap-3 text-[13px]">
          <Link
            href={`/domains/topics?id=${domainId}`}
            className="text-accent hover:underline"
          >
            🔎 新規テーマを探す
          </Link>
          <Link
            href={`/domains/new?id=${domainId}`}
            className="text-accent hover:underline"
          >
            ＋ 新規記事を作成
          </Link>
          <Link
            href={`/domains/prompts?id=${domainId}`}
            className="text-accent hover:underline"
          >
            プロンプトを編集
          </Link>
          <button
            onClick={syncNow}
            disabled={syncing}
            className="text-accent hover:underline disabled:opacity-60"
          >
            {syncing ? "同期中…" : "🔄 Search Console と今すぐ同期"}
          </button>
        </div>
        {syncMsg && <div className="mt-2 text-[12px] text-ink2">{syncMsg}</div>}
      </Card>

      <SectionTitle>掲載順位の推移（90日・平均）</SectionTitle>
      <Card>
        <RankChart rows={rank} />
      </Card>

      <SectionTitle>次の打ち手 — 既存ページの改善候補</SectionTitle>
      {!rec || rec.improvement_candidates.length === 0 ? (
        <Empty>機会スコアがまだありません（analysis ジョブ未実行）。</Empty>
      ) : (
        <>
          <div className="mb-2 text-[12px] text-ink2">
            {rec.note} 「AIで実行」を押すと現状の記事をAIが読み、打ち手（タイトル改善 or
            本文リライト）に沿って改訂し、そのまま公開します（Anthropic API の実課金が発生します）。
          </div>
          {improveErr && (
            <div className="mb-2">
              <ErrorNote>{improveErr}</ErrorNote>
            </div>
          )}
          <TableWrap>
            <thead>
              <tr>
                <Th>キーワード</Th>
                <Th num>スコア</Th>
                <Th num>順位</Th>
                <Th num>表示回数</Th>
                <Th num>クリック数</Th>
                <Th>打ち手</Th>
                <Th>該当ページ</Th>
                <Th>アクション</Th>
              </tr>
            </thead>
            <tbody>
              {rec.improvement_candidates.map((o, i) => (
                <tr key={i}>
                  <Td>{o.keyword}</Td>
                  <Td num>{num(o.score)}</Td>
                  <Td num>{num(o.position, 0)}</Td>
                  <Td num>{o.impressions ?? "—"}</Td>
                  <Td num>{o.clicks ?? "—"}</Td>
                  <Td className="text-[12px]">{HINT_LABEL[o.action_hint]}</Td>
                  <Td>
                    <a
                      href={o.url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-[12px] text-accent hover:underline"
                    >
                      開く ↗
                    </a>
                  </Td>
                  <Td>
                    <button
                      onClick={() => improveNow(o)}
                      disabled={!!improving}
                      className="text-[12px] text-accent hover:underline disabled:opacity-60"
                    >
                      {improving === o.url ? "AI修正中…（30〜90秒）" : "🤖 AIで実行"}
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        </>
      )}

      <SectionTitle>AIによる改訂履歴（良くなった／悪くなった）</SectionTitle>
      {improveHist.length === 0 ? (
        <Empty>「AIで実行」を使うとここに記録されます。</Empty>
      ) : (
        <div className="flex flex-col gap-2">
          {improveHist.map((h, i) => (
            <Card key={i}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-[12px] text-ink2">
                  <span>{fmtDateTime(h.at)}</span>
                  <span>・{h.keyword}</span>
                  <span>・{h.body_changed ? "本文リライト" : "タイトル改善"}</span>
                </div>
                <Pill tone={verdictTone(h.verdict)}>{VERDICT_LABEL[h.verdict]}</Pill>
              </div>
              <div className="mt-2 text-[13px]">
                <div className="text-ink2 line-through decoration-ink2/40">
                  {h.title_before || "（タイトルなし）"}
                </div>
                <div className="font-medium">{h.title_after}</div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-3 text-[12px]">
                <MetricCompare label="平均掲載順位" before={h.before.position} after={h.after.position}
                                lowerIsBetter unit="" />
                <MetricCompare label="クリック数/日" before={h.before.clicks} after={h.after.clicks} unit="" />
                <MetricCompare label="表示回数/日" before={h.before.impressions} after={h.after.impressions} unit="" />
              </div>
              {(h.verdict === "too_early") && (
                <div className="mt-2 text-[11px] text-ink2">
                  GSCの反映ラグのため、{h.data_ready_at ? fmtDate(h.data_ready_at) : "数日後"}
                  以降に効果が確認できます。
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {rec && rec.declining.length > 0 && (
        <>
          <SectionTitle>順位が下落したページ（直近30日）</SectionTitle>
          <TableWrap>
            <thead>
              <tr>
                <Th>検知日</Th>
                <Th>キーワード</Th>
                <Th>深刻度</Th>
                <Th num>順位</Th>
                <Th>該当ページ</Th>
              </tr>
            </thead>
            <tbody>
              {rec.declining.map((r, i) => (
                <tr key={i}>
                  <Td num>{fmtDate(r.detected_date)}</Td>
                  <Td>{r.keyword}</Td>
                  <Td>
                    <Pill tone={severityTone(r.severity)}>{r.severity}</Pill>
                  </Td>
                  <Td num>
                    {num(r.from_position, 0)} → {num(r.to_position, 0)}
                  </Td>
                  <Td>
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-[12px] text-accent hover:underline"
                    >
                      開く ↗
                    </a>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        </>
      )}

      <SectionTitle>アラート（直近30日）</SectionTitle>
      {alerts.length === 0 ? (
        <Empty>アラートはありません。</Empty>
      ) : (
        <TableWrap>
          <thead>
            <tr>
              <Th>検知日</Th>
              <Th>キーワード</Th>
              <Th>種別</Th>
              <Th>深刻度</Th>
              <Th num>順位変化</Th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a, i) => (
              <tr key={i}>
                <Td num>{fmtDate(a.detected_date)}</Td>
                <Td>{a.keyword}</Td>
                <Td>
                  <code className="rounded bg-surface2 px-1.5 py-0.5 font-mono text-[12px]">
                    {a.alert_type}
                  </code>
                </Td>
                <Td>
                  <Pill tone={severityTone(a.severity)}>{a.severity}</Pill>
                </Td>
                <Td num>
                  {num(a.from_position, 0)} → {num(a.to_position, 0)}
                </Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}

      <SectionTitle>記事（最新20件）</SectionTitle>
      {articles.length === 0 ? (
        <Empty>記事はまだありません。</Empty>
      ) : (
        <TableWrap>
          <thead>
            <tr>
              <Th>状態</Th>
              <Th>タイトル</Th>
              <Th>対象KW</Th>
              <Th num>検索数</Th>
              <Th num>作成</Th>
            </tr>
          </thead>
          <tbody>
            {articles.map((a) => (
              <tr key={a.id}>
                <Td>
                  <Pill
                    tone={
                      a.status === "published" ? "ok" : a.status === "failed" ? "crit" : "muted"
                    }
                  >
                    {a.status}
                  </Pill>
                </Td>
                <Td>
                  <Link
                    href={`/articles?id=${a.id}`}
                    className="text-accent hover:underline"
                  >
                    {a.title || "（無題）"}
                  </Link>
                </Td>
                <Td>{a.target_keyword || "—"}</Td>
                <Td num>{a.target_search_volume ?? "—"}</Td>
                <Td num>{fmtDate(a.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </>
  );
}

function verdictTone(v: ImproveVerdict): "ok" | "warn" | "crit" | "muted" {
  if (v === "improved") return "ok";
  if (v === "declined") return "crit";
  return "muted";
}

function MetricCompare({
  label,
  before,
  after,
  unit,
  lowerIsBetter = false,
}: {
  label: string;
  before: number | null;
  after: number | null;
  unit: string;
  lowerIsBetter?: boolean;
}) {
  const hasBoth = before != null && after != null;
  const delta = hasBoth ? after! - before! : null;
  const improved = delta != null && (lowerIsBetter ? delta < 0 : delta > 0);
  const worsened = delta != null && delta !== 0 && !improved;
  return (
    <div>
      <div className="text-ink2">{label}</div>
      <div className="mt-0.5 flex items-center gap-1 font-mono">
        <span>{before ?? "—"}{unit}</span>
        <span className="text-ink2">→</span>
        <span
          className={
            improved ? "text-ok" : worsened ? "text-crit" : undefined
          }
        >
          {after ?? "—"}{unit}
        </span>
      </div>
    </div>
  );
}
