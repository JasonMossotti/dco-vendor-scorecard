#!/usr/bin/env python3
"""Generate the GPU health layer for the committed sample: data/gpu_health/.

Health watches, daily GPU counters, thermal slowdown episodes, CDU secondary readings, and rack
daily peaks, modeled on public DCGM-style health checks. Own random stream; data/sample is read,
never written.

Usage:
    python scripts/generate_gpu_health.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.gpu_health import GpuHealthLayer, write_gpu_health  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "gpu_health"


def generate(dest: Path = OUT) -> dict:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    layer = GpuHealthLayer(SAMPLE, window["seed"])
    out = layer.run(excursion=layer.cfg["plants"]["sample_cdu_excursion"])
    return write_gpu_health(out, dest, "data/sample")


def main() -> int:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    counts = generate()
    print(f"GPU health layer for {window['start']} to {window['end']} -> {OUT.relative_to(ROOT)}")
    for rel, n in counts.items():
        print(f"  {rel:<28} {n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
