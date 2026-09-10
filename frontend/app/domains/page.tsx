"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
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
import { fmtDate, num, severityTone } from "@/lib/format";
import { HINT_LABEL } from "@/lib/types";
import type {
  Alert,
  Article,
  DomainDetail,
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
  const domainId = Number(sp.get("id"));

  const [d, setD] = useState<DomainDetail | null>(null);
  const [rank, setRank] = useState<RankRow[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [articles, setArticles] = useState<Article[]>([]);
  const [rec, setRec] = useState<Recommendations | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!domainId) return;
    Promise.all([
      api.domain(domainId),
      api.rankHistory(domainId, 90),
      api.alerts(domainId, 30),
      api.articles(domainId),
      api.recommendations(domainId),
    ])
      .then(([dd, rk, al, ar, rc]) => {
        setD(dd);
        setRank(rk);
        setAlerts(al);
        setArticles(ar);
        setRec(rc);
      })
      .catch((e) => setErr(e.message));
  }, [domainId]);

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
        <div className="mt-3 flex gap-3 text-[13px]">
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
        </div>
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
          <div className="mb-2 text-[12px] text-ink2">{rec.note}</div>
          <TableWrap>
            <thead>
              <tr>
                <Th>キーワード</Th>
                <Th num>スコア</Th>
                <Th num>順位</Th>
                <Th>打ち手</Th>
                <Th>該当ページ</Th>
              </tr>
            </thead>
            <tbody>
              {rec.improvement_candidates.map((o, i) => (
                <tr key={i}>
                  <Td>{o.keyword}</Td>
                  <Td num>{num(o.score)}</Td>
                  <Td num>{num(o.position, 0)}</Td>
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
                </tr>
              ))}
            </tbody>
          </TableWrap>
        </>
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
              <Th num>投稿ID</Th>
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
                    href={`/domains/new?id=${domainId}&article=${a.id}`}
                    className="text-accent hover:underline"
                  >
                    {a.title || "（無題）"}
                  </Link>
                </Td>
                <Td>{a.target_keyword || "—"}</Td>
                <Td num>{a.target_search_volume ?? "—"}</Td>
                <Td num>{a.wp_post_id ?? "—"}</Td>
                <Td num>{fmtDate(a.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </>
  );
}
