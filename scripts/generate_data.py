#!/usr/bin/env python3
"""Generate a synthetic GB200 NVL72 partner-site dataset.

Examples:
    python scripts/generate_data.py                       # committed sample: data/sample
    python scripts/generate_data.py --latest              # 4 weeks ending last Sunday
    python scripts/generate_data.py --seed 7 --weeks 2 --start 2026-09-14 --out data/run2
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.sla_model import load_sla  # noqa: E402
from scorecard.synthetic import SiteGenerator, write_dataset  # noqa: E402

SAMPLE_START = date(2026, 8, 31)  # Fixed so the committed sample is reproducible


def last_complete_week_start(today: date, weeks: int) -> date:
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(weeks=weeks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(ROOT / "config" / "synthetic.yaml"))
    ap.add_argument("--seed", type=int, help="override the config seed")
    ap.add_argument("--weeks", type=int, help="override the config number of weeks")
    ap.add_argument("--start", type=date.fromisoformat, help="first Monday of the window (YYYY-MM-DD)")
    ap.add_argument("--latest", action="store_true", help="window ends with the most recent complete week")
    ap.add_argument("--out", default=str(ROOT / "data" / "sample"))
    args = ap.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    weeks = args.weeks or config["weeks"]
    if args.latest:
        start = last_complete_week_start(date.today(), weeks)
    else:
        start = args.start or SAMPLE_START

    gen = SiteGenerator(load_sla(), config, start=start, weeks=weeks, seed=args.seed)
    data = gen.run()
    counts = write_dataset(data, args.out)

    w = data["window"]
    print(f"Synthetic site data: {w['start']} to {w['end']} (seed {w['seed']}) -> {args.out}")
    for rel, n in counts.items():
        print(f"  {rel:<45} {n:>6}")
    types = {}
    for p in data["planted"]:
        types[p["type"]] = types.get(p["type"], 0) + 1
    print(f"Planted discrepancies: {len(data['planted'])} " + ", ".join(f"{k}={v}" for k, v in sorted(types.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
