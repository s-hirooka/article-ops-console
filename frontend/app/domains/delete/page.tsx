"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, ErrorNote, Field, Input, SectionTitle, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { DomainSummary } from "@/lib/types";

export default function DeleteDomainPage() {
  const router = useRouter();

  const [domains, setDomains] = useState<DomainSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | "">("");
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  useEffect(() => {
    api.domains().then(setDomains).catch((e) => setErr(e.message));
  }, []);

  const selected = domains?.find((d) => d.id === selectedId) ?? null;
  const canDelete = !!selected && confirmText === selected.domain_key;

  async function del() {
    if (!selected || !canDelete) return;
    setDeleting(true);
    setDeleteErr(null);
    try {
      await api.deleteDomain(selected.id, confirmText);
      router.push("/");
    } catch (e) {
      setDeleteErr((e as Error).message);
      setDeleting(false);
    }
  }

  if (err) return <ErrorNote>読み込みに失敗しました: {err}</ErrorNote>;
  if (!domains) return <Spinner />;

  return (
    <>
      <div className="mb-1 text-[13px] text-ink2">
        <Link href="/" className="hover:underline">
          概要
        </Link>{" "}
        / ドメイン削除
      </div>
      <SectionTitle>ドメインを削除</SectionTitle>

      <Card className="flex max-w-xl flex-col gap-3">
        <Field label="削除するドメイン">
          <select
            value={selectedId}
            onChange={(e) => {
              setSelectedId(e.target.value ? Number(e.target.value) : "");
              setConfirmText("");
              setDeleteErr(null);
            }}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent"
          >
            <option value="">選択してください</option>
            {domains.map((d) => (
              <option key={d.id} value={d.id}>
                {d.domain_key}（{d.base_url}）
              </option>
            ))}
          </select>
        </Field>

        {selected && (
          <>
            <div className="rounded-lg border border-crit/30 bg-crit/5 p-3 text-[12px] text-ink2">
              記事・順位履歴・プロンプト設定を含め、このドメインに関するデータが全て削除されます。
              元に戻せません（WordPress側の投稿は残ります）。確認のため、ドメインキー「
              <span className="font-mono">{selected.domain_key}</span>
              」を入力してください。
            </div>
            <Field label="ドメインキーを入力">
              <Input
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={selected.domain_key}
              />
            </Field>
            <div>
              <Button
                onClick={del}
                disabled={!canDelete || deleting}
                className="border border-crit/40 !bg-crit text-white hover:brightness-110"
              >
                {deleting ? "削除中…" : "削除する"}
              </Button>
            </div>
            {deleteErr && <ErrorNote>{deleteErr}</ErrorNote>}
          </>
        )}
      </Card>
    </>
  );
}
