"""Parity check: google-ads Python port vs KeywordQueryRunner.exe.

Runs the same keywords through both paths and diffs the results field-by-field.
This is the acceptance test for spec §10 P1(a) — "キーワード取得を google-ads
Python に移植し、.exe の出力と数件で突き合わせて一致確認".

Usage:
    python scripts/check_keyword_parity.py                 # built-in keyword set
    python scripts/check_keyword_parity.py "薬箱 収納" "水筒 スタンド"

Notes:
* Each side may spend one Google Ads API call. The .exe caches for 720h, so a
  keyword set already queried today is free on the C# side; the Python port
  always makes a live call.
* The .exe prints CP932 to stdout (Windows console default) — decoded as such.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.google_ads_keywords import fetch_historical_metrics  # noqa: E402

EXE = Path(
    r"G:\KeywordInsightService\Tools\KeywordQueryRunner\bin\Debug"
    r"\net8.0-windows\KeywordQueryRunner.exe"
)

# Keywords queried earlier today (cache hit on the .exe side → no C# API call).
DEFAULT_KEYWORDS = [
    "薬箱 収納ボックス 蓋付き",
    "ネクタイ 収納",
    "cd 収納",
    "マフラー 収納",
]


def run_exe(keywords: list[str]) -> dict[str, dict]:
    if not EXE.is_file():
        raise SystemExit(f"exe が見つかりません: {EXE}")
    proc = subprocess.run(
        [str(EXE), *keywords],
        capture_output=True,
        timeout=180,
    )
    stdout = proc.stdout.decode("cp932", errors="replace")
    stderr = proc.stderr.decode("cp932", errors="replace")
    dump = Path(__file__).resolve().parents[1] / "scratch"
    dump.mkdir(exist_ok=True)
    (dump / "parity_exe_stdout.txt").write_text(stdout, encoding="utf-8")
    if "ERROR" in stdout or proc.returncode != 0:
        print(stdout)
        print(stderr, file=sys.stderr)
        raise SystemExit(f".exe が異常終了しました (rc={proc.returncode})")

    rows: dict[str, dict] = {}
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    for ln in lines[1:]:  # skip header
        parts = ln.split("\t")
        if len(parts) < 6:
            continue
        kw, avg, comp, idx, low, high = parts[:6]
        rows[kw] = {
            "avg": _int_or_none(avg),
            "comp": comp or None,
            "idx": _int_or_none(idx),
            "low": _float_or_none(low),
            "high": _float_or_none(high),
        }
    return rows


def _int_or_none(s: str):
    s = s.strip()
    return int(s) if s and s.lstrip("-").isdigit() else None


def _float_or_none(s: str):
    s = s.strip()
    try:
        return round(float(s), 6)
    except ValueError:
        return None


def run_port(keywords: list[str]) -> dict[str, dict]:
    rows = fetch_historical_metrics(keywords)
    out: dict[str, dict] = {}
    for r in rows:
        out[r.keyword] = {
            "avg": r.avg_monthly_searches,
            "comp": r.competition_level,
            "idx": r.competition_index,
            "low": None if r.low_top_of_page_bid is None else round(float(r.low_top_of_page_bid), 6),
            "high": None if r.high_top_of_page_bid is None else round(float(r.high_top_of_page_bid), 6),
        }
    return out


def _cmp_scalar(a, b) -> bool:
    return a == b


def _cmp_comp(a, b) -> bool:
    return (a or "").casefold() == (b or "").casefold()


def _cmp_bid(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= 1e-6


def main() -> int:
    keywords = sys.argv[1:] or DEFAULT_KEYWORDS
    print(f"keywords ({len(keywords)}): {keywords}\n")

    exe_rows = run_exe(keywords)
    port_rows = run_port(keywords)

    all_kw = sorted(set(exe_rows) | set(port_rows))
    fields = [
        ("avg", "AvgMonthlySearches", _cmp_scalar),
        ("comp", "Competition", _cmp_comp),
        ("idx", "CompetitionIndex", _cmp_scalar),
        ("low", "LowBid", _cmp_bid),
        ("high", "HighBid", _cmp_bid),
    ]

    mismatches = 0
    for kw in all_kw:
        e = exe_rows.get(kw)
        p = port_rows.get(kw)
        if e is None or p is None:
            mismatches += 1
            where = "exe" if e is None else "port"
            print(f"[MISS] {kw!r} — {where} に行なし  (exe={e}, port={p})")
            continue
        diffs = []
        for key, label, cmp in fields:
            if not cmp(e[key], p[key]):
                diffs.append(f"{label}: exe={e[key]!r} port={p[key]!r}")
        if diffs:
            mismatches += 1
            print(f"[DIFF] {kw!r}")
            for d in diffs:
                print(f"        {d}")
        else:
            print(
                f"[OK]   {kw!r}  avg={e['avg']} comp={e['comp']} "
                f"idx={e['idx']} low={e['low']} high={e['high']}"
            )

    print()
    if mismatches:
        print(f"❌ FAIL — {mismatches}/{len(all_kw)} 件に不一致")
        return 1
    print(f"✅ PASS — {len(all_kw)}/{len(all_kw)} 件一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
