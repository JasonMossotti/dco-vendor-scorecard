#!/usr/bin/env python3
"""Generate the certification layer for the sample month: data/certs/ (own random stream "<seed>:certs").

Every person's credentials and each partner's monthly credential report, with the planted record problems and the
answer key. Reads data/sample, data/security, and data/ehs, never writes them.

Usage:
    python scripts/generate_certs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.certs import CertsLayer, write_certs  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "certs"


def main() -> int:
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = CertsLayer(SAMPLE, seed, ROOT / "data" / "security", ROOT / "data" / "ehs")
    man = write_certs(layer, layer.run(), OUT, "data/sample, data/security, data/ehs")
    print("Wrote data/certs/: " + ", ".join(f"{n} {k}" for k, n in man["files"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
