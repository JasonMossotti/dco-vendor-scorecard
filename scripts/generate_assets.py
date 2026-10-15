#!/usr/bin/env python3
"""Generate the asset register for the sample month: data/assets/ (own random stream "<seed>:assets").

Reads data/sample, data/security, data/telemetry/mgmt and data/telemetry/storage; writes only data/assets/.

Usage:
    python scripts/generate_assets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.assets import AssetLayer, write_assets  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
SECURITY = ROOT / "data" / "security"
MGMT = ROOT / "data" / "telemetry" / "mgmt"
STORAGE = ROOT / "data" / "telemetry" / "storage"
OUT = ROOT / "data" / "assets"
SOURCE = "data/sample + data/security + data/telemetry/mgmt + data/telemetry/storage + docs/site/devices.json"


def main() -> int:
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = AssetLayer(SAMPLE, seed, SECURITY, MGMT, STORAGE)
    man = write_assets(layer, layer.run(), OUT, SOURCE)
    print("Wrote data/assets/: " + ", ".join(f"{n} {k}" for k, n in man["files"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
