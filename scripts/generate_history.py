#!/usr/bin/env python3
"""Generate the failure history for the failure pattern review (the half-year before the sample month).

Usage:
    python scripts/generate_history.py                      # -> data/history/ (committed)
    python scripts/generate_history.py --seed 7 --vary --out data/history-7   # a robustness history

The history has its own random stream and reads only the committed fleet
(data/sample/site/topology.json), so it never changes the sample month.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.history import HistoryGenerator, write_history  # noqa: E402


def generate(seed: int | None = None, vary: bool = False, config: Path = ROOT / "config" / "history.yaml") -> dict:
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    topology = json.loads((ROOT / "data" / "sample" / "site" / "topology.json").read_text(encoding="utf-8"))
    return HistoryGenerator(topology, cfg, seed=seed, vary=vary).run()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, help="override the config seed")
    ap.add_argument("--vary", action="store_true", help="move and resize the planted patterns (robustness runs)")
    ap.add_argument("--out", default=str(ROOT / "data" / "history"))
    args = ap.parse_args()
    data = generate(args.seed, args.vary)
    counts = write_history(data, args.out)
    w = data["window"]
    print(f"Failure history: {w['start'][:10]} to {w['end'][:10]} (seed {w['seed']}, {w['hall']}) -> {args.out}")
    for rel, n in counts.items():
        print(f"  {rel:<40} {n:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
