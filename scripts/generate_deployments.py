#!/usr/bin/env python3
"""Generate the deployment program record for the committed sample: data/deployments/.

The partners' Jira projects (Jira Cloud search export shape), the Customer's own step records, sign-offs by
role, inspections, permits, and determinations for the Hall B GB300 rollout. Own random stream; data/sample is
read, never written.

Usage:
    python scripts/generate_deployments.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.deployments import DeploymentRecordLayer, write_deployments  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "deployments"


def generate(dest: Path = OUT) -> dict:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    return write_deployments(DeploymentRecordLayer(SAMPLE, window["seed"]).run(), dest, "data/sample")


def main() -> int:
    counts = generate()
    print(f"Deployment program record -> {OUT.relative_to(ROOT)}")
    for rel, n in counts.items():
        print(f"  {rel:<28} {n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
