#!/usr/bin/env python3
"""Run the facility evidence tests against freshly generated months, not just the committed sample.

Usage:
    python scripts/check_facility_data.py            # 60 months
    python scripts/check_facility_data.py --months 10

Each month gets a new seed and start date. A planted record must stay unambiguous
in every month (for example, nobody badged into the room on a falsified
maintenance record), and honest records must always carry their evidence.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.sla_model import load_sla  # noqa: E402
from scorecard.synthetic import SiteGenerator, write_dataset  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--months", type=int, default=60)
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    failed = []
    for k in range(args.months):
        out = Path(tempfile.mkdtemp(prefix=f"facility_{k}_"))
        write_dataset(SiteGenerator(load_sla(), cfg, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=1000 + k).run(), out)
        env = dict(os.environ, FACILITY_DATASET=str(out), PYTHONPATH=str(ROOT / "src"))
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests" / "test_facility.py"),
                            "-k", "not other_seeds and not never_changes"], capture_output=True, text=True, env=env)
        if r.returncode:
            failed.append(k)
            print(f"month {k} (seed {1000 + k}): {r.stdout.strip().splitlines()[-1]}")
    print(f"{args.months - len(failed)}/{args.months} generated months pass every facility evidence test")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
