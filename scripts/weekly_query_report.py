#!/usr/bin/env python3
"""Build a weekly SEO query report from Search Console CSV exports.

Expected CSV columns (case-insensitive):
- query (or top queries)
- clicks
- impressions
- ctr
- position
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable


@dataclass
class QueryMetrics:
    query: str
    clicks: float
    impressions: float
    ctr: float
    position: float


def _to_float(value: str) -> float:
    cleaned = (value or "").strip().replace(",", "")
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
        return float(cleaned) / 100.0
    if not cleaned:
        return 0.0
    return float(cleaned)


def _pick_value(row: dict[str, str], *keys: str) -> str:
    lowered = {k.strip().lower(): v for k, v in row.items()}
    for key in keys:
        if key in lowered:
            return lowered[key]
    return ""


def load_metrics(path: Path) -> Dict[str, QueryMetrics]:
    rows: Dict[str, QueryMetrics] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            query = _pick_value(raw_row, "query", "top queries").strip()
            if not query:
                continue
            clicks = _to_float(_pick_value(raw_row, "clicks"))
            impressions = _to_float(_pick_value(raw_row, "impressions"))
            ctr = _to_float(_pick_value(raw_row, "ctr"))
            position = _to_float(_pick_value(raw_row, "position"))
            rows[query] = QueryMetrics(query, clicks, impressions, ctr, position)
    return rows


def sort_desc(items: Iterable[QueryMetrics], key: str) -> list[QueryMetrics]:
    return sorted(items, key=lambda row: getattr(row, key), reverse=True)


def format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def build_report(
    current: Dict[str, QueryMetrics],
    previous: Dict[str, QueryMetrics],
    top_n: int,
    min_impressions: float,
    ctr_threshold: float,
) -> str:
    current_rows = list(current.values())
    previous_rows = previous

    top_impressions = sort_desc(current_rows, "impressions")[:top_n]

    click_drops: list[tuple[QueryMetrics, float]] = []
    for row in current_rows:
        prev = previous_rows.get(row.query)
        if not prev:
            continue
        delta = row.clicks - prev.clicks
        if delta < 0:
            click_drops.append((row, delta))
    click_drops.sort(key=lambda item: item[1])

    opportunities = [
        row
        for row in current_rows
        if row.impressions >= min_impressions and row.ctr < ctr_threshold
    ]
    opportunities = sort_desc(opportunities, "impressions")[:top_n]

    new_queries = [
        row
        for row in current_rows
        if row.query not in previous_rows and row.impressions >= min_impressions
    ]
    new_queries = sort_desc(new_queries, "impressions")[:top_n]

    lines: list[str] = []
    lines.append("# Weekly Query Report")
    lines.append("")
    lines.append("## Top Queries By Impressions")
    for row in top_impressions:
        lines.append(
            f"- `{row.query}` · {int(row.impressions)} impressions · {int(row.clicks)} clicks · CTR {format_pct(row.ctr)} · Position {row.position:.1f}"
        )
    if not top_impressions:
        lines.append("- No data")

    lines.append("")
    lines.append("## Biggest Click Drops (Week over Week)")
    for row, delta in click_drops[:top_n]:
        prev = previous_rows[row.query]
        lines.append(
            f"- `{row.query}` · {int(prev.clicks)} -> {int(row.clicks)} clicks ({delta:.0f}) · impressions {int(row.impressions)}"
        )
    if not click_drops:
        lines.append("- No click drops detected")

    lines.append("")
    lines.append("## High-Impression / Low-CTR Opportunities")
    for row in opportunities:
        lines.append(
            f"- `{row.query}` · {int(row.impressions)} impressions · CTR {format_pct(row.ctr)}"
        )
    if not opportunities:
        lines.append("- No opportunities above current thresholds")

    lines.append("")
    lines.append("## New Queries Worth Watching")
    for row in new_queries:
        lines.append(
            f"- `{row.query}` · {int(row.impressions)} impressions · CTR {format_pct(row.ctr)}"
        )
    if not new_queries:
        lines.append("- No high-impression new queries this week")

    lines.append("")
    lines.append("## Weekly Actions")
    lines.append("- Improve title/meta copy for top low-CTR queries.")
    lines.append("- Add internal links from relevant blog posts to /products, /security, and /#demo.")
    lines.append("- Request indexing for materially updated URLs.")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weekly query report from Search Console CSV exports")
    parser.add_argument("--current", required=True, help="Current-week CSV path")
    parser.add_argument("--previous", required=True, help="Previous-week CSV path")
    parser.add_argument("--output", default="", help="Optional report output path")
    parser.add_argument("--top", type=int, default=10, help="Top N rows per section")
    parser.add_argument("--min-impressions", type=float, default=100.0)
    parser.add_argument("--ctr-threshold", type=float, default=0.02)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    current = load_metrics(Path(args.current))
    previous = load_metrics(Path(args.previous))

    report = build_report(
        current=current,
        previous=previous,
        top_n=args.top,
        min_impressions=args.min_impressions,
        ctr_threshold=args.ctr_threshold,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"wrote report to {output_path}")
    else:
        print(report, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
