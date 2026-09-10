"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RankRow } from "@/lib/types";

/**
 * Average GSC position per day (lower = better), so the Y axis is reversed.
 */
export default function RankChart({ rows }: { rows: RankRow[] }) {
  const data = useMemo(() => {
    const byDate = new Map<string, { sum: number; n: number }>();
    for (const r of rows) {
      const pos = Number(r.gsc_average_position);
      if (r.gsc_average_position == null || Number.isNaN(pos)) continue;
      const b = byDate.get(r.metric_date) || { sum: 0, n: 0 };
      b.sum += pos;
      b.n += 1;
      byDate.set(r.metric_date, b);
    }
    return [...byDate.entries()]
      .map(([date, b]) => ({ date: date.slice(5), pos: +(b.sum / b.n).toFixed(1) }))
      .sort((a, b) => (a.date < b.date ? -1 : 1));
  }, [rows]);

  if (data.length < 2) {
    return (
      <div className="px-1 py-3 text-[13px] text-ink2">
        推移を描くにはデータが不足しています（rank_sync を数日走らせると出ます）。
      </div>
    );
  }

  return (
    <div className="h-56 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis
            dataKey="date"
            tick={{ fill: "var(--ink-2)", fontSize: 11 }}
            stroke="var(--border)"
          />
          <YAxis
            reversed
            tick={{ fill: "var(--ink-2)", fontSize: 11 }}
            stroke="var(--border)"
            width={40}
            label={{
              value: "平均掲載順位",
              angle: -90,
              position: "insideLeft",
              fill: "var(--ink-2)",
              fontSize: 11,
            }}
          />
          <Tooltip
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--ink)",
            }}
          />
          <Line
            type="monotone"
            dataKey="pos"
            stroke="var(--accent)"
            strokeWidth={2}
            dot={{ r: 2 }}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
