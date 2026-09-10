"use client";

import { ReactNode } from "react";

type Tone = "ok" | "warn" | "crit" | "muted" | "accent";

const toneClass: Record<Tone, string> = {
  ok: "text-ok border-ok/40",
  warn: "text-warn border-warn/40",
  crit: "text-crit border-crit/40",
  muted: "text-ink2 border-border",
  accent: "text-accent border-accent/40",
};

export function Pill({ children, tone = "muted" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-[1px] text-[11px] font-medium ${toneClass[tone]}`}
    >
      {children}
    </span>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-[10px] border border-border bg-surface p-4 ${className}`}>
      {children}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-3 mt-8 text-[12px] font-semibold uppercase tracking-[0.08em] text-ink2">
      {children}
    </h2>
  );
}

export function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="flex flex-col">
      <b className="text-lg font-semibold tabular-nums">{value}</b>
      <span className="text-[11px] uppercase tracking-[0.06em] text-ink2">{label}</span>
    </div>
  );
}

export function Button({
  children,
  onClick,
  type = "button",
  variant = "primary",
  disabled,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "ghost";
  disabled?: boolean;
  className?: string;
}) {
  const base =
    "inline-flex items-center justify-center rounded-lg px-3.5 py-2 text-[13px] font-medium transition disabled:opacity-50 disabled:cursor-not-allowed";
  const styles =
    variant === "primary"
      ? "bg-accent text-white hover:brightness-110"
      : "border border-border bg-surface hover:bg-surface2";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-[13px]">
      <span className="font-medium text-ink2">{label}</span>
      {children}
      {hint ? <span className="text-[11px] text-ink2">{hint}</span> : null}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`rounded-lg border border-border bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent ${props.className || ""}`}
    />
  );
}

export function TableWrap({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-[10px] border border-border bg-surface">
      <table className="w-full border-collapse text-[13px]">{children}</table>
    </div>
  );
}

export function Th({
  children,
  num,
}: {
  children: ReactNode;
  num?: boolean;
}) {
  return (
    <th
      className={`border-b border-border px-2.5 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink2 ${num ? "text-right" : "text-left"}`}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  num,
  className = "",
}: {
  children: ReactNode;
  num?: boolean;
  className?: string;
}) {
  return (
    <td
      className={`border-b border-border px-2.5 py-2 align-top ${num ? "text-right font-mono tabular-nums" : ""} ${className}`}
    >
      {children}
    </td>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-1 py-3 text-[13px] text-ink2">{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-[13px] text-ink2">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-border border-t-accent" />
      {label || "読み込み中…"}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-crit/40 bg-crit/5 px-3 py-2 text-[13px] text-crit">
      {children}
    </div>
  );
}
