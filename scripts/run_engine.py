#!/usr/bin/env python3
"""Run the discrepancy engine on a dataset and write the reports.

Examples:
    python scripts/run_engine.py                          # data/sample -> reports/
    python scripts/run_engine.py --data data/seed7 --out reports/seed7
    python scripts/run_engine.py --robustness 20          # also test 20 freshly generated months
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.connectors import FileConnector  # noqa: E402
from scorecard.engine import run_engine  # noqa: E402
from scorecard.engine.evaluate import evaluate  # noqa: E402
from scorecard.engine.report import to_json, to_markdown  # noqa: E402
from scorecard.sla_model import load_sla  # noqa: E402


def robustness(sla: dict, n: int) -> tuple[int, int, int]:
    from scorecard.synthetic import SiteGenerator, write_dataset
    cfg = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    planted = detected = fp = 0
    for seed in range(1, n + 1):
        with tempfile.TemporaryDirectory() as d:
            write_dataset(SiteGenerator(sla, cfg, start=date(2026, 8, 31), seed=seed).run(), d)
            e = evaluate(run_engine(sla, FileConnector(d)).findings, d)
            planted, detected, fp = planted + e.planted, detected + e.detected, fp + len(e.false_positives)
    return planted, detected, fp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(ROOT / "data" / "sample"))
    ap.add_argument("--out", default=str(ROOT / "reports"))
    ap.add_argument("--no-eval", action="store_true", help="skip scoring against ground_truth/")
    ap.add_argument("--robustness", type=int, default=0, metavar="N", help="also evaluate N generated months")
    args = ap.parse_args()

    sla = load_sla()
    result = run_engine(sla, FileConnector(args.data))       # the engine never sees ground_truth/
    has_key = (Path(args.data) / "ground_truth").exists()
    evaluation = evaluate(result.findings, args.data) if has_key and not args.no_eval else None

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "findings.json").write_text(json.dumps(to_json(result, evaluation), indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8", newline="\n")
    (out / "discrepancy_report.md").write_text(to_markdown(result, evaluation), encoding="utf-8", newline="\n")

    print(f"{len(result.findings)} findings from {len(result.context.tickets)} tickets -> {out}")
    for f in result.findings:
        print(f"  {f.id} {f.severity} {f.title:<46} {', '.join(f.tickets) or f.unit}")
    if evaluation:
        print(f"Answer key: detected {evaluation.detected}/{evaluation.planted}, "
              f"{len(evaluation.false_positives)} false positives, {len(evaluation.corroborating)} corroborating")
    if args.robustness:
        p, d, fp = robustness(sla, args.robustness)
        print(f"Robustness over {args.robustness} generated months: detected {d}/{p}, {fp} false positives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
