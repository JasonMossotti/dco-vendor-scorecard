#!/usr/bin/env python3
"""Build the vendor SLA scorecard (runs the discrepancy engine first).

Examples:
    python scripts/build_scorecard.py                     # data/sample -> reports/
    python scripts/build_scorecard.py --data data/seed7 --out reports/seed7
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.builder import build_scorecard  # noqa: E402
from scorecard.connectors import FileConnector  # noqa: E402
from scorecard.engine import run_engine  # noqa: E402
from scorecard.scorecard_report import scorecard_json, scorecard_markdown  # noqa: E402
from scorecard.sla_model import load_sla  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(ROOT / "data" / "sample"))
    ap.add_argument("--out", default=str(ROOT / "reports"))
    args = ap.parse_args()

    sla = load_sla()
    sc = build_scorecard(sla, run_engine(sla, FileConnector(args.data)))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps(scorecard_json(sc), indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8", newline="\n")
    (out / "scorecard.md").write_text(scorecard_markdown(sc), encoding="utf-8", newline="\n")

    t, cr = sc["totals"], sc["credits"]
    print(f"Scorecard -> {out}")
    print(f"  {t['incidents']} incidents, {t['findings']} findings, {t['defaults']} Minimum defaults, {t['s1']} S1 items")
    print(f"  Credits: ${cr['uncapped']:,.0f} uncapped, ${cr['payable']:,.0f} payable")
    print(f"  Corrective action plans: {len(sc['corrective_actions'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
