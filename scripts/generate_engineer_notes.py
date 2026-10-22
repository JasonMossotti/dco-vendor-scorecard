#!/usr/bin/env python3
"""Generate the engineer notes for every Incident Portal record: data/engineer_notes/ (own stream "<seed>:engineer_notes").

The fields a technician, engineer, or officer fills in by hand in each partner system (config/engineer_notes.yaml),
composed from each record's own facts, plus the hand-written notes in tickets/engineer_notes.yaml. Reads the sample
and its layers, never writes them; the Incident Portal shows the notes in a collapsible section on each record.

Usage:
    python scripts/generate_engineer_notes.py                  # write data/engineer_notes/
    python scripts/generate_engineer_notes.py --check          # fail if the notes are stale or do not reconcile
    python scripts/generate_engineer_notes.py --robustness 60  # compose and check notes on 60 generated months
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import engineer_notes as E  # noqa: E402
from scorecard import tickets as T  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "data" / "engineer_notes"
DISCLAIMER = ("Synthetic engineer, technician, and officer notes for a portfolio demonstration, composed from each "
              "record's own facts. All records are fictional; people are shown by person ID.")


def build() -> dict:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    records = T.build()["records"]
    notes = E.build(records, window["seed"], hand=E.hand_written(), plants=E.audit_plants())
    bad = E.check(records, notes, names=list(T.Redactor(SAMPLE).ids))
    return {"disclaimer": DISCLAIMER, "source": "data/sample", "window": window,
            "counts": dict(sorted(Counter(n["type"] for n in notes.values()).items())),
            "hand_written": sorted(k for k, n in notes.items() if n["source"] == "hand-written"),
            "notes": dict(sorted(notes.items()))}, bad


def text(d: dict) -> str:
    return json.dumps(d, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def robustness_month(k: int) -> dict:
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    from scorecard.synthetic.changes import ChangeLayer, write_changes
    from scorecard.synthetic.fire import FireLayer, write_fire
    from scorecard.synthetic.security import generate
    syn = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        data = SiteGenerator(load_sla(), syn, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run()
        write_dataset(data, d)
        write_changes(ChangeLayer(d, 2000 + k).run(plant=True), d / "changes", data["window"], 2000 + k, "generated")
        generate(d, d / "security")
        fl = FireLayer(d, 2000 + k)
        write_fire(fl, fl.run(), d / "fire")
        records = T.build(d, d / "changes", reports=d / "reports")["records"]
        notes = E.build(records, 2000 + k)
        bad = E.check(records, notes, names=list(T.Redactor(d).ids))
    return {"month": k, "records": len(records), "types": dict(Counter(r["type"] for r in records)),
            "clean": len(records) - len({b.split(":")[0] for b in bad}), "problems": bad[:5]}


def robustness(n: int, jobs: int = 1) -> int:
    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            res = list(ex.map(robustness_month, range(n)))
    else:
        res = [robustness_month(k) for k in range(n)]
    total, clean = sum(r["records"] for r in res), sum(r["clean"] for r in res)
    types = Counter()
    for r in res:
        types.update(r["types"])
    print(f"Engineer notes on {n} generated months (the wording was written on the sample month only):")
    print(f"  records with notes that reconcile with their record  {clean}/{total}")
    print("  by type: " + ", ".join(f"{k} {v}" for k, v in sorted(types.items())))
    for r in res:
        for p in r["problems"]:
            print(f"  month {r['month']}: {p}")
    return 0 if clean == total else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, metavar="N")
    ap.add_argument("--jobs", type=int, default=1)
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness, args.jobs)
    d, bad = build()
    if bad:
        print("Notes that do not reconcile with their record:\n  " + "\n  ".join(bad))
        return 1
    path = OUT / "notes.json"
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != text(d):
            print("data/engineer_notes/notes.json is out of date. Run: python scripts/generate_engineer_notes.py")
            return 1
        print(f"data/engineer_notes/ is current: {len(d['notes'])} records, every note reconciles with its record.")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(text(d), encoding="utf-8", newline="\n")
    print(f"Wrote data/engineer_notes/notes.json: {len(d['notes'])} records ("
          + ", ".join(f"{k} {v}" for k, v in d["counts"].items()) + f"), {len(d['hand_written'])} hand-written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
