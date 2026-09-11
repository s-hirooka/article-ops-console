"use client";

import { useMemo } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RankRow } from "@/lib/types";

/**
 * Daily averages across all tracked keywords: GSC position (reversed — lower
 * is better, left axis), plus clicks/impressions (right axis, same scale —
 * impressions naturally dwarfs clicks, same as GSC's own dashboard).
 */
export default function RankChart({ rows }: { rows: RankRow[] }) {
  const data = useMemo(() => {
    const byDate = new Map<
      string,
      { posSum: number; posN: number; clicks: number; impressions: number }
    >();
    for (const r of rows) {
      const b = byDate.get(r.metric_date) || {
        posSum: 0,
        posN: 0,
        clicks: 0,
        impressions: 0,
      };
      const pos = Number(r.gsc_average_position);
      if (r.gsc_average_position != null && !Number.isNaN(pos)) {
        b.posSum += pos;
        b.posN += 1;
      }
      b.clicks += r.clicks || 0;
      b.impressions += r.impressions || 0;
      byDate.set(r.metric_date, b);
    }
    return [...byDate.entries()]
      .map(([date, b]) => ({
        date: date.slice(5),
        pos: b.posN ? +(b.posSum / b.posN).toFixed(1) : null,
        clicks: b.clicks,
        impressions: b.impressions,
      }))
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
    <div className="h-64 w-full">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis
            dataKey="date"
            tick={{ fill: "var(--ink-2)", fontSize: 11 }}
            stroke="var(--border)"
          />
          <YAxis
            yAxisId="pos"
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
          <YAxis
            yAxisId="count"
            orientation="right"
            tick={{ fill: "var(--ink-2)", fontSize: 11 }}
            stroke="var(--border)"
            width={48}
            label={{
              value: "クリック / 表示回数",
              angle: 90,
              position: "insideRight",
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
            formatter={(value: number, name: string) => {
              const label =
                name === "pos" ? "平均掲載順位" : name === "clicks" ? "クリック数" : "表示回数";
              return [value.toLocaleString(), label];
            }}
          />
          <Bar
            yAxisId="count"
            dataKey="impressions"
            fill="var(--border)"
            radius={[2, 2, 0, 0]}
            barSize={10}
          />
          <Line
            yAxisId="count"
            type="monotone"
            dataKey="clicks"
            stroke="#22a06b"
            strokeWidth={2}
            dot={{ r: 2 }}
            activeDot={{ r: 4 }}
          />
          <Line
            yAxisId="pos"
            type="monotone"
            dataKey="pos"
            stroke="var(--accent)"
            strokeWidth={2}
            dot={{ r: 2 }}
            activeDot={{ r: 4 }}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-1 flex flex-wrap gap-4 px-1 text-[11px] text-ink2">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-accent" />
          平均掲載順位（左軸・低いほど良い）
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: "#22a06b" }} />
          クリック数（右軸）
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-border" />
          表示回数（右軸）
        </span>
      </div>
    </div>
  );
}
