#!/usr/bin/env python3
"""Generate the condition history for predictive maintenance (the half-year before the sample month).

Usage:
    python scripts/generate_predict.py                       # -> data/predict/ (committed)
    python scripts/generate_predict.py --history data/history-7 --seed 7 --vary --out data/predict-7

It reads only the failure history (data/history/) and the committed fleet, from its own random
stream, so no other file changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.predict import PredictGenerator, write_predict  # noqa: E402


def generate(history: Path = ROOT / "data" / "history", seed: int | None = None, vary: bool = False) -> dict:
    cfg = yaml.safe_load((ROOT / "config" / "predict.yaml").read_text(encoding="utf-8"))
    cdu = yaml.safe_load((ROOT / "config" / "telemetry_cdu.yaml").read_text(encoding="utf-8"))
    topology = json.loads((ROOT / "data" / "sample" / "site" / "topology.json").read_text(encoding="utf-8"))
    return PredictGenerator(history, topology, cfg, cdu, seed=seed, vary=vary).run()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--history", default=str(ROOT / "data" / "history"))
    ap.add_argument("--seed", type=int, help="override the history's seed")
    ap.add_argument("--vary", action="store_true", help="move the planted pump failures (robustness runs)")
    ap.add_argument("--out", default=str(ROOT / "data" / "predict"))
    args = ap.parse_args()
    data = generate(Path(args.history), args.seed, args.vary)
    counts = write_predict(data, args.out)
    w = data["window"]
    print(f"Condition history: {w['start'][:10]} to {w['end'][:10]} (seed {w['seed']}, {w['hall']}) -> {args.out}")
    for rel, n in counts.items():
        print(f"  {rel:<26} {n:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
