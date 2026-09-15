"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { JOB_KIND_LABEL } from "@/lib/types";

const ARTICLE_KINDS = new Set(["article_generate", "topic_auto_generate", "improve_article"]);
const POLL_MS = 8000;
const AUTO_DISMISS_MS = 12000;

interface Toast {
  id: string;
  text: string;
  ok: boolean;
}

function describe(kind: string, status: string, result: unknown, error: string | null): string {
  const label = JOB_KIND_LABEL[kind] ?? kind;
  if (status !== "succeeded") return `${label}が失敗しました${error ? `: ${error}` : ""}`;

  const r = (result || {}) as Record<string, unknown>;
  if (kind === "topic_auto_generate") {
    const created = typeof r.created_count === "number" ? r.created_count : 0;
    const articles = Array.isArray(r.articles) ? (r.articles as { title?: string }[]) : [];
    if (created === 0) return `${label}: 記事は作成されませんでした`;
    const titles = articles.map((a) => a.title).filter(Boolean).join("、");
    return `${label}: ${created}件の記事が完成しました（${titles}）`;
  }
  const title = typeof r.title === "string" ? r.title : null;
  return title ? `${label}: 「${title}」が完成しました` : `${label}が完了しました`;
}

// Polls recent jobs and pops a toast (top-right) whenever an
// article-producing job (started anywhere - this tab, another tab, the
// batch-generate page after you've navigated away) transitions into a
// terminal state, since those jobs run server-side and finish on their own
// schedule with no other way to learn you're done watching for them.
export default function JobToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const knownRef = useRef<Map<string, string>>(new Map());
  const primedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      let jobs;
      try {
        jobs = await api.jobs(15);
      } catch {
        return; // transient network/API error - try again next tick
      }
      if (cancelled) return;

      if (!primedRef.current) {
        // First poll only establishes the baseline so we don't toast for
        // jobs that already finished before this component mounted.
        for (const j of jobs) knownRef.current.set(j.id, j.status);
        primedRef.current = true;
        return;
      }

      for (const j of jobs) {
        const prev = knownRef.current.get(j.id);
        knownRef.current.set(j.id, j.status);
        const justFinished =
          (j.status === "succeeded" || j.status === "failed") &&
          prev !== "succeeded" &&
          prev !== "failed";
        if (!justFinished || !ARTICLE_KINDS.has(j.kind)) continue;

        const id = `${j.id}:${j.status}`;
        const text = describe(j.kind, j.status, j.result, j.error ?? null);
        setToasts((cur) => [...cur, { id, text, ok: j.status === "succeeded" }]);
        setTimeout(() => {
          setToasts((cur) => cur.filter((t) => t.id !== id));
        }, AUTO_DISMISS_MS);
      }
    }

    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed right-4 top-4 z-50 flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`rounded-lg border px-3 py-2 text-[13px] shadow-md backdrop-blur ${
            t.ok
              ? "border-ok/40 bg-surface/95 text-ok"
              : "border-crit/40 bg-surface/95 text-crit"
          }`}
        >
          {t.ok ? "✅ " : "⚠️ "}
          {t.text}
        </div>
      ))}
    </div>
  );
}
