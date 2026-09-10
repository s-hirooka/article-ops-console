"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getAccountId, setAccountId } from "@/lib/api";
import type { Account } from "@/lib/types";

const NAV = [
  { href: "/", label: "概要" },
  { href: "/jobs", label: "ジョブ" },
];

export default function Header() {
  const pathname = usePathname();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [current, setCurrent] = useState<number>(1);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    setCurrent(getAccountId());
    api.accounts().then(setAccounts).catch(() => setAccounts([]));
    api
      .health()
      .then((h) => setOnline(h.db))
      .catch(() => setOnline(false));
  }, []);

  function switchAccount(id: number) {
    setAccountId(id);
    setCurrent(id);
    window.location.href = "/";
  }

  return (
    <header className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border bg-surface px-5 py-3 sm:px-7">
      <Link href="/" className="text-[15px] font-semibold tracking-[0.01em]">
        Article Ops Console
      </Link>
      <nav className="flex gap-4 text-[13px]">
        {NAV.map((n) => {
          const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              className={active ? "text-accent" : "text-ink2 hover:text-ink"}
            >
              {n.label}
            </Link>
          );
        })}
      </nav>
      <div className="ml-auto flex items-center gap-3 text-[12px] text-ink2">
        <span
          className={`h-2 w-2 rounded-full ${
            online === null ? "bg-border" : online ? "bg-ok" : "bg-crit"
          }`}
          title={online ? "API online" : online === false ? "API unreachable" : "checking"}
        />
        {accounts.length > 0 ? (
          <select
            value={current}
            onChange={(e) => switchAccount(Number(e.target.value))}
            className="rounded-md border border-border bg-surface px-2 py-1 text-[12px] outline-none focus:border-accent"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.role})
              </option>
            ))}
          </select>
        ) : (
          <span>account {current}</span>
        )}
      </div>
    </header>
  );
}
