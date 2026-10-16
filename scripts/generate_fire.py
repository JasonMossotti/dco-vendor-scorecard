#!/usr/bin/env python3
"""Generate the fire protection layer for the sample month: data/fire/ (own random stream "<seed>:fire").

The fire panel's history log, the Landlord's impairment log, and the Customer's record of impairment notices, with two
planted discrepancies and the answer key. Reads data/sample, never writes it.

Usage:
    python scripts/generate_fire.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.fire import FireLayer, write_fire  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "fire"


def main() -> int:
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = FireLayer(SAMPLE, seed)
    man = write_fire(layer, layer.run(), OUT, "data/sample")
    print("Wrote data/fire/: " + ", ".join(f"{n} {k}" for k, n in man["files"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
