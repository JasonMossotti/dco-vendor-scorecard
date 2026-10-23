#!/usr/bin/env python3
"""Generate the opening PM register: data/pm_coverage/ (own random stream "<seed>:pm").

Each device-task line's last completion before the PM records begin, with one planted record problem of each kind
and the answer key. Reads the PM program, the PM records, the forward schedule, and the asset register; writes
nothing else.

Usage:
    python scripts/generate_pm.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.pm_coverage import OpeningRegister, write_opening  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "pm_coverage"


def main() -> int:
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    out = OpeningRegister(seed).run()
    man = write_opening(out, OUT, seed)
    print(f"Wrote data/pm_coverage/: {man['files']['opening.csv']} opening lines, {len(out['key']['planted'])} planted, "
          f"{len(out['key']['as_found'])} as found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
