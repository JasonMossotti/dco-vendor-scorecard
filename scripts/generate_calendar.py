#!/usr/bin/env python3
"""Generate the forward maintenance and change schedule: data/calendar/ (own random stream "<seed>:calendar").

The jobs booked from the end of the data weeks to Hall C first compute, placed by the planner's rules, with one
planted conflict of each kind and the answer key. Reads the site model, the device lists, the Hall B Jira milestones,
and the Hall C commissioning plan; writes nothing else.

Usage:
    python scripts/generate_calendar.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.change_calendar import ForwardSchedule, write_calendar  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "calendar"


def main() -> int:
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    sched = ForwardSchedule(seed)
    man = write_calendar(sched, sched.run(), OUT, seed)
    print(f"Wrote data/calendar/: {man['files']['schedule.json']} forward jobs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
