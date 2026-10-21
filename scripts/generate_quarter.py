#!/usr/bin/env python3
"""Generate the quarter's earlier months for the quarterly business review: data/quarter/<start>/.

The same site generator and Security Partner layer as the sample month, each month with its own seed and its planted
counts drawn by chance around their usual rates (config/qbr.yaml). The sample month is read from data/sample and never
written.

Usage:
    python scripts/generate_quarter.py           # write data/quarter/
    python scripts/generate_quarter.py --check   # exit 1 if data/quarter/ is not what the generator writes
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.quarter import OUT, generate_all  # noqa: E402


def _differ(a: Path, b: Path) -> list[str]:
    fa = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
    fb = sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file())
    if fa != fb:
        return sorted(set(fa) ^ set(fb))
    return [f for f in fa if not filecmp.cmp(a / f, b / f, shallow=False)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            generate_all(Path(tmp))
            bad = _differ(Path(tmp), OUT) if OUT.exists() else ["data/quarter/ is missing"]
        if bad:
            print("data/quarter/ is out of date. Run: python scripts/generate_quarter.py")
            for b in bad[:10]:
                print("  " + b)
            return 1
        print("data/quarter/ is current.")
        return 0
    if OUT.exists():
        shutil.rmtree(OUT)
    for s in generate_all(OUT):
        print(f"Month {s['start']} (seed {s['seed']}) -> data/quarter/{s['start']}/: {s['planted']} planted IT and Landlord "
              f"records, Security Partner plants {', '.join(s['security']) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
