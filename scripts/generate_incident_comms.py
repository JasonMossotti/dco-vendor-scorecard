#!/usr/bin/env python3
"""Generate the incident comms log for the committed sample: data/incident_comms/.

The joint bridge for each incident the Incident Commander runbook replays (config/incident_comms.yaml). Own random
stream; only the sample's seed is read, and data/sample is never written.

Usage:
    python scripts/generate_incident_comms.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.incident_comms import build, write  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "incident_comms"


def generate(dest: Path = OUT) -> dict:
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    return write(build(seed), dest, "config/incident_comms.yaml and the data/sample seed")


def main() -> int:
    counts = generate()
    print(f"Incident comms log -> {OUT.relative_to(ROOT)}")
    for rel, n in counts.items():
        print(f"  {rel:<24} {n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
