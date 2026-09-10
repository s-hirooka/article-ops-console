export function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return String(s);
  return d.toLocaleDateString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit" });
}

export function fmtDateTime(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return String(s);
  return d.toLocaleString("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtUsd(
  n: number | string | null | undefined,
  digits = 2,
): string {
  if (n === null || n === undefined || n === "") return "—";
  const v = typeof n === "string" ? parseFloat(n) : n;
  if (Number.isNaN(v)) return "—";
  return `$${v.toFixed(digits)}`;
}

export function num(n: number | string | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return "—";
  const v = typeof n === "string" ? parseFloat(n) : n;
  if (Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export function severityTone(sev: string): "ok" | "warn" | "crit" | "muted" {
  const s = sev.toLowerCase();
  if (["high", "critical"].includes(s)) return "crit";
  if (s === "medium") return "warn";
  return "muted";
}

export function jobStatusTone(status: string): "ok" | "warn" | "crit" | "muted" {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "crit";
  if (status === "running") return "warn";
  return "muted";
}
