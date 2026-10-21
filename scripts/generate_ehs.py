#!/usr/bin/env python3
"""Generate the EHS layer for the sample month: data/ehs/ (own random stream "<seed>:ehs").

The work permits every job in the records needs, every worker's training, and the reported safety events, with the
planted record problems and the answer key. Reads data/sample and data/security, never writes them.

Usage:
    python scripts/generate_ehs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.ehs import EhsLayer, write_ehs  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "ehs"


def main() -> int:
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = EhsLayer(SAMPLE, seed, security_dir=ROOT / "data" / "security")
    man = write_ehs(layer, layer.run(), OUT, "data/sample, data/security")
    print("Wrote data/ehs/: " + ", ".join(f"{n} {k}" for k, n in man["files"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
