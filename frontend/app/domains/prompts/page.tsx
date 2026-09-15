"use client";

import Editor from "@monaco-editor/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Button, Card, ErrorNote, Empty, Input, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { COMPONENT_LABELS, PROMPT_COMPONENTS, type PromptComponent } from "@/lib/types";

export default function PromptsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <PromptsInner />
    </Suspense>
  );
}

function PromptsInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const domainId = Number(sp.get("id"));

  const [domainKey, setDomainKey] = useState<string | null>(null);
  const [prompts, setPrompts] = useState<Record<string, PromptComponent> | null>(null);
  const [active, setActive] = useState<string>(PROMPT_COMPONENTS[0]);
  const [draft, setDraft] = useState<string>("");
  const [baseline, setBaseline] = useState<string>("");
  const [history, setHistory] = useState<
    { version: number; body: string; created_at: string }[]
  >([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!domainId) return;
    api
      .prompts(domainId)
      .then(setPrompts)
      .catch((e) => setErr(e.message));
    api.domain(domainId).then((d) => setDomainKey(d.domain_key)).catch(() => setDomainKey(null));
  }, [domainId]);

  useEffect(() => {
    if (!prompts || !domainId) return;
    const body = prompts[active]?.body ?? "";
    setDraft(body);
    setBaseline(body);
    setMsg(null);
    api.promptHistory(domainId, active).then(setHistory).catch(() => setHistory([]));
  }, [active, prompts, domainId]);

  const dirty = draft !== baseline;
  const isJson = active === "vc_auto_ads_defaults" || active === "eyecatch_style";
  const language = isJson ? "json" : "markdown";

  const jsonError = useMemo(() => {
    if (!isJson || !draft.trim()) return null;
    try {
      JSON.parse(draft);
      return null;
    } catch (e) {
      return (e as Error).message;
    }
  }, [draft, isJson]);

  async function save() {
    if (jsonError || !domainId) return;
    setSaving(true);
    setErr(null);
    try {
      const r = await api.savePrompt(domainId, active, draft);
      setMsg(`v${r.version} を保存しました`);
      setBaseline(draft);
      const [p, h] = await Promise.all([
        api.prompts(domainId),
        api.promptHistory(domainId, active),
      ]);
      setPrompts(p);
      setHistory(h);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!domainId) return <ErrorNote>ドメインが指定されていません。</ErrorNote>;
  if (err && !prompts) return <ErrorNote>読み込みに失敗しました: {err}</ErrorNote>;
  if (!prompts) return <Spinner />;

  return (
    <>
      <div className="mb-1 text-[13px] text-ink2">
        <Link href="/" className="hover:underline">
          概要
        </Link>{" "}
        /{" "}
        <Link href={`/domains?id=${domainId}`} className="hover:underline">
          ドメイン
        </Link>{" "}
        / プロンプト編集
      </div>
      <SectionTitle>記事生成プロンプト</SectionTitle>

      <div className="flex flex-wrap gap-1.5">
        {PROMPT_COMPONENTS.map((c) => {
          const v = prompts[c]?.version;
          return (
            <button
              key={c}
              onClick={() => setActive(c)}
              className={`rounded-lg border px-2.5 py-1.5 text-[12px] transition ${
                active === c
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border bg-surface text-ink2 hover:bg-surface2"
              }`}
            >
              {COMPONENT_LABELS[c] || c}
              {v ? <span className="ml-1 font-mono text-[11px] opacity-70">v{v}</span> : null}
            </button>
          );
        })}
      </div>

      <div className="mt-3 overflow-hidden rounded-[10px] border border-border">
        <Editor
          height="360px"
          language={language}
          value={draft}
          onChange={(v) => setDraft(v ?? "")}
          theme="vs-dark"
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            wordWrap: "on",
            scrollBeyondLastLine: false,
            padding: { top: 12, bottom: 12 },
          }}
        />
      </div>

      {jsonError && (
        <div className="mt-2 text-[12px] text-crit">JSON エラー: {jsonError}</div>
      )}

      <div className="mt-3 flex items-center gap-3">
        <Button onClick={save} disabled={!dirty || saving || !!jsonError}>
          {saving ? "保存中…" : dirty ? "新しいバージョンを保存" : "変更なし"}
        </Button>
        {dirty && (
          <button
            onClick={() => setDraft(baseline)}
            className="text-[12px] text-ink2 hover:text-ink"
          >
            元に戻す
          </button>
        )}
        {msg && <span className="text-[12px] text-ok">{msg}</span>}
        {err && <span className="text-[12px] text-crit">{err}</span>}
      </div>

      <SectionTitle>バージョン履歴</SectionTitle>
      {history.length === 0 ? (
        <Empty>まだ保存されていません（保存すると v1 が作られます）。</Empty>
      ) : (
        <div className="flex flex-col gap-2">
          {history.map((h) => (
            <Card key={h.version} className="flex items-center gap-3">
              <span className="font-mono text-[13px] text-accent">v{h.version}</span>
              <span className="text-[12px] text-ink2">{fmtDateTime(h.created_at)}</span>
              <button
                onClick={() => setDraft(h.body)}
                className="ml-auto text-[12px] text-accent hover:underline"
              >
                この版をエディタに読み込む
              </button>
            </Card>
          ))}
        </div>
      )}

      <DangerZone domainId={domainId} domainKey={domainKey} router={router} />
    </>
  );
}

function DangerZone({
  domainId,
  domainKey,
  router,
}: {
  domainId: number;
  domainKey: string | null;
  router: ReturnType<typeof useRouter>;
}) {
  const [open, setOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function del() {
    if (!domainKey || confirmText !== domainKey) return;
    setDeleting(true);
    setErr(null);
    try {
      await api.deleteDomain(domainId, confirmText);
      router.push("/");
    } catch (e) {
      setErr((e as Error).message);
      setDeleting(false);
    }
  }

  return (
    <div className="mt-20 border-t border-border pt-3 text-[11px] text-ink2/60">
      {!open ? (
        <button onClick={() => setOpen(true)} className="hover:underline">
          ドメインの管理
        </button>
      ) : (
        <div className="max-w-md rounded-lg border border-crit/30 p-3">
          <div className="text-[12px] font-medium text-crit">
            このドメインを削除
          </div>
          <p className="mt-1 text-[12px] text-ink2">
            記事・順位履歴・プロンプト設定を含め、このドメインに関するデータが全て削除されます。
            元に戻せません（WordPress側の投稿は残ります）。続ける場合はドメインキー「
            <span className="font-mono">{domainKey}</span>」を入力してください。
          </p>
          <Input
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={domainKey ?? ""}
            className="mt-2 w-full"
          />
          <div className="mt-2 flex items-center gap-2">
            <Button
              variant="ghost"
              onClick={del}
              disabled={deleting || !domainKey || confirmText !== domainKey}
              className="border-crit/40 text-crit hover:bg-crit/5"
            >
              {deleting ? "削除中…" : "完全に削除する"}
            </Button>
            <button
              onClick={() => {
                setOpen(false);
                setConfirmText("");
                setErr(null);
              }}
              className="text-[12px] text-ink2 hover:text-ink"
            >
              キャンセル
            </button>
          </div>
          {err && <div className="mt-2 text-[12px] text-crit">{err}</div>}
        </div>
      )}
    </div>
  );
}
