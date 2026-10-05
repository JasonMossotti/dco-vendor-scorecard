#!/usr/bin/env python3
"""Run the read-only live collector and append to a dataset folder.

Usage:
    pip install -r requirements-live.txt
    export CDU_RO_USER=... CDU_RO_PASSWORD=...
    python scripts/collect.py --config /secure/collector.yaml --out data/live --once
    python scripts/collect.py --config /secure/collector.yaml --out data/live          # poll until stopped

The output folder follows docs/DATA_MODEL.md, so the engines run on it unchanged:
    python scripts/run_landlord.py   (pointed at the live folder)
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.live.collector import Collector  # noqa: E402
from scorecard.live.config import load_config  # noqa: E402
from scorecard.live.writer import DatasetWriter  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--once", action="store_true", help="poll every device once and exit")
    args = ap.parse_args()
    cfg = load_config(args.config)
    collector = Collector(cfg)
    writer = DatasetWriter(args.out, datetime.now(timezone.utc))
    while True:
        now = datetime.now(timezone.utc)
        records = collector.poll_once()
        writer.append(records, now)
        bad = [r for r in records.get("collector/feed_health.jsonl", []) if not r["ok"]]
        print(f"{now:%Y-%m-%d %H:%M:%S}Z polled {len(cfg['devices'])} devices; "
              f"{sum(len(v) for k, v in records.items() if not k.startswith('collector/'))} records; {len(bad)} feed errors")
        for r in bad:
            print(f"  {r['device']}: {r['error']}")
        if args.once:
            return 0
        time.sleep(cfg["poll_interval_s"])


if __name__ == "__main__":
    sys.exit(main())
