#!/usr/bin/env python3
"""Generate the energy meters for the committed sample: data/energy/.

Hourly meters for the sample month, the chiller free-cooling log, the Landlord's monthly energy
report, the answer key, and 12 four-week periods of daily history before the month. Each hall's UPS
output is its racks' power from the GPU telemetry (data/telemetry/gpu/rack_hourly.csv), and each hall's
mechanical UPS output is its CDUs' draw (data/telemetry/cdu) plus its thermal walls', so the GPU and CDU
telemetry come first; scripts/generate_telemetry.py runs this same step. Own random stream;
data/sample is read, never written.

Usage:
    python scripts/generate_energy.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.energy import EnergyLayer, history, with_devices, write_energy  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "energy"
CDU = ROOT / "data" / "telemetry" / "cdu"


def generate(dest: Path = OUT) -> dict:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    layer = EnergyLayer(SAMPLE, window["seed"])
    kind = layer.cfg["plants"]["sample_report_error"]
    out = with_devices(layer, kind, layer.run(report_error=kind), CDU)
    hist = history(out["meters"], layer.start, window["seed"])
    return write_energy(out, dest, hist, "data/sample")


def main() -> int:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    counts = generate()
    print(f"Energy meters for {window['start']} to {window['end']} -> {OUT.relative_to(ROOT)}")
    for rel, n in counts.items():
        print(f"  {rel:<32} {n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
