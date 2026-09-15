"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorNote, Field, Input, SectionTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

export default function AddDomainPage() {
  const router = useRouter();

  const [domainKey, setDomainKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [gscSiteUrl, setGscSiteUrl] = useState("");
  const [threshold, setThreshold] = useState("500");

  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function create() {
    setSaving(true);
    setErr(null);
    try {
      const r = await api.createDomain({
        domain_key: domainKey.trim(),
        base_url: baseUrl.trim(),
        gsc_site_url: gscSiteUrl.trim(),
        keyword_threshold: Number(threshold) || 500,
      });
      router.push(`/domains/prompts?id=${r.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const valid = domainKey.trim() && baseUrl.trim() && gscSiteUrl.trim();

  return (
    <>
      <div className="mb-1 text-[13px] text-ink2">
        <Link href="/" className="hover:underline">
          概要
        </Link>{" "}
        / 新規ドメイン追加
      </div>
      <SectionTitle>新規ドメインを追加</SectionTitle>

      <Card className="flex max-w-xl flex-col gap-3">
        <Field label="ドメインキー" hint="英数字・ハイフンなど。他のドメインと重複不可（例: mynewsite2026）">
          <Input
            value={domainKey}
            onChange={(e) => setDomainKey(e.target.value)}
            placeholder="mynewsite2026"
          />
        </Field>
        <Field label="サイトURL">
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://mynewsite2026.com"
          />
        </Field>
        <Field
          label="Search Console のサイトURL"
          hint="Search Console に登録したプロパティのURL（sc-domain:形式 or https://形式）"
        >
          <Input
            value={gscSiteUrl}
            onChange={(e) => setGscSiteUrl(e.target.value)}
            placeholder="sc-domain:mynewsite2026.com"
          />
        </Field>
        <Field label="月間検索数の下限" hint="この数値未満のキーワードはおすすめから除外されます">
          <Input
            value={threshold}
            onChange={(e) => setThreshold(e.target.value.replace(/[^0-9]/g, ""))}
            inputMode="numeric"
            className="w-28"
          />
        </Field>
        <div>
          <Button onClick={create} disabled={saving || !valid}>
            {saving ? "作成中…" : "ドメインを作成"}
          </Button>
        </div>
        <div className="text-[12px] text-ink2">
          作成後、次のページ（プロンプト編集）でこのドメインの記事の書き方を設定してください。
          WordPressの接続情報（ユーザー名・アプリケーションパスワード）はこの画面では設定できません
          — 必要な場合はお知らせください。
        </div>
      </Card>

      {err && (
        <div className="mt-4 max-w-xl">
          <ErrorNote>{err}</ErrorNote>
        </div>
      )}
    </>
  );
}
