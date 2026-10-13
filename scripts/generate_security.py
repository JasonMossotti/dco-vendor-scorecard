#!/usr/bin/env python3
"""Generate the security layer for the committed sample: data/security/.

The Customer's access control, video, and identity records for the Customer halls, and the Security Partner's post
log, tours, dispatch log, visitor log, and chain-of-custody log beside them, with four planted discrepancies and the
answer key. Own random stream; data/sample is read, never written.

Usage:
    python scripts/generate_security.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.security import generate  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "security"


def main(out: Path = OUT) -> int:
    counts = generate(SAMPLE, out, "data/sample")
    print(f"Security layer -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    for rel, n in counts.items():
        print(f"  {rel:<40} {n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
