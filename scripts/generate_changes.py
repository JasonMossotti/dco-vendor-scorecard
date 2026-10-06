#!/usr/bin/env python3
"""Generate the change-work layer for the committed sample: data/changes/.

Impact declarations for every change record in data/sample, the partners'
notification delivery logs, and the answer key. Own random stream; data/sample
is read, never written.

Usage:
    python scripts/generate_changes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.changes import ChangeLayer, write_changes  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "changes"


def main() -> int:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    out = ChangeLayer(SAMPLE, window["seed"]).run(plant=False)
    counts = write_changes(out, OUT, window, window["seed"], "data/sample")
    print(f"Change-work layer for {window['start']} to {window['end']} -> {OUT.relative_to(ROOT)}")
    for rel, n in counts.items():
        print(f"  {rel:<40} {n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
