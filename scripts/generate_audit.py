#!/usr/bin/env python3
"""Generate the quality audit layer for the sample month: data/audit/ (own random stream "<seed>:audit").

The Customer's sample draw (published seed), the walk-down readings of every sampled record, and the RMA cage scan,
with the planted workmanship defects and the answer key. Reads data/sample, never writes it.

Usage:
    python scripts/generate_audit.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.audit import AuditLayer, write_audit  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "audit"


def main() -> int:
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = AuditLayer(SAMPLE, seed)
    man = write_audit(layer, layer.run(), OUT, "data/sample")
    print("Wrote data/audit/: " + ", ".join(f"{n} {k}" for k, n in man["files"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
