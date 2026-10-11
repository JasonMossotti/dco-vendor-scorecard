#!/usr/bin/env python3
"""Generate the Hall C readiness record for the committed sample: data/readiness/.

The commissioning agent's scripts (L1 to L5) with their runs and signatures by role, the issues log, the
Customer's readiness items, and the pilot spares receipts. Own random stream; only the sample's as-of date and
seed are read, and data/sample is never written.

Usage:
    python scripts/generate_readiness.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.readiness import ReadinessRecordLayer, write_readiness  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "readiness"


def generate(dest: Path = OUT) -> dict:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    return write_readiness(ReadinessRecordLayer(window["end"], window["seed"]).run(), dest, "data/sample (as-of date and seed)")


def main() -> int:
    counts = generate()
    print(f"Hall C readiness record -> {OUT.relative_to(ROOT)}")
    for rel, n in counts.items():
        print(f"  {rel:<24} {n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
