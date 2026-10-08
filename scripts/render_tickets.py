#!/usr/bin/env python3
"""Render the Incident Portal: every partner ticket, change, work order, MOP, and PM task with its timeline.

Usage:
    python scripts/render_tickets.py                   # print a summary of the records
    python scripts/render_tickets.py --html OUT.html   # write the page (scripts/build_site.py does this)
    python scripts/render_tickets.py --robustness 60   # score the related-record suggestions on 60 generated months
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import sitenav  # noqa: E402
from scorecard import tickets as T  # noqa: E402
from scorecard.alarms import CLASS_TEXT  # noqa: E402

def reviewed(records: list[dict]) -> dict[str, str]:
    """Record number -> the completed review of it, for every record a review's incident covers (its ticket, its
    work order, and the records they are linked to in the records, so the outage's MOP is not called reviewed)."""
    import render_pir
    out = {}
    for r in render_pir.reviews():
        rec = next((x for x in records if x["id"] == r["ref"]), None)
        if not rec:
            continue
        for ref in [r["ref"]] + [x for x in rec["related"] if not x.startswith(("MOP-", "PM-"))]:
            out.setdefault(ref, r["id"])
    return out


def data() -> dict:
    d = T.build()
    d.update(class_text=CLASS_TEXT, reviewed=reviewed(d["records"]))
    return d


def relations(records: list[dict]) -> dict:
    """What the page needs for related records: the curated relations, the suggestions, and the types."""
    from scorecard import relations as RL
    cfg = RL.config()
    curated = RL.load_curated()
    return {"curated": {k: v for k, v in RL.apply_curated(records, curated).items() if v},
            "suggestions": {k: v for k, v in RL.suggest(records, cfg=cfg, curated=curated).items() if v},
            "types": cfg["types"], "threshold": cfg["threshold"]}


def html_page() -> str:
    tpl = sitenav.inject((ROOT / "templates" / "tickets.html").read_text(encoding="utf-8"), "tickets")
    d = data()
    payload = json.dumps(d, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    rel = json.dumps(relations(d["records"]), sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    return sitenav.finish(tpl.replace("__DATA__", payload).replace("__RELATIONS__", rel))


def robustness(n: int) -> int:
    """Score the related-record suggestions on months the weights were not set on: recall against the links
    the records themselves make, and false positives against decoy pairs (see ``relations.evaluate``)."""
    import yaml

    from scorecard import relations as RL
    from scorecard import tickets as T
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    from scorecard.synthetic.changes import ChangeLayer, write_changes
    cfg = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    links = found = pairs = 0
    decoys: dict[str, int] = {}
    misses: list[str] = []
    false: list[str] = []
    for k in range(n):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = SiteGenerator(load_sla(), cfg, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run()
            write_dataset(data, d)
            out = ChangeLayer(d, 2000 + k).run(plant=True)
            write_changes(out, d / "changes", data["window"], 2000 + k, "generated")
            # No engine reports for a generated month, so the records carry their own links only.
            records = T.build(d, d / "changes", reports=d / "reports")["records"]
            e = RL.evaluate(records)
            links += e["links"]
            found += e["found"]
            pairs += e["suggested_pairs"]
            for key, v in e["decoys"].items():
                decoys[key] = decoys.get(key, 0) + v
            misses += [f"month {k}: {' and '.join(m['pair'])} scored {m['score']} ({m['raw']} before the place-and-time rule)" for m in e["missed"]]
            false += [f"month {k}: {kind}: {' and '.join(x['pair'])} scored {x['score']}" for kind, v in e["false"].items() for x in v]
    print(f"Related-record suggestions on {n} generated months (the weights were set on the sample month only):")
    print(f"  links in the records   suggested {found}/{links}")
    for key, v in sorted(decoys.items()):
        bad = sum(1 for f in false if f": {key}:" in f)
        print(f"  {key:<22} not suggested {v - bad}/{v}")
    print(f"  suggestions shown      {pairs} pairs in {n} months ({pairs / n:.1f} a month)")
    for m in misses[:20] + false[:20]:
        print("   ", m)
    return 1 if misses or false else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--html", metavar="OUT")
    ap.add_argument("--robustness", type=int, metavar="N")
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness)
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(html_page(), encoding="utf-8", newline="\n")
        print(f"Wrote {args.html}")
        return 0
    d = data()
    print("Incident Portal records: " + ", ".join(f"{d['types'][k]['plural'].lower()} {v}" for k, v in d["counts"].items()) + f" ({len(d['records'])} in all)")
    print(f"  with a finding {sum(1 for r in d['records'] if r['findings'])}, with alarms {sum(1 for r in d['records'] if r['alarms'])}, "
          f"measured {sum(1 for r in d['records'] if r['measured'])}")
    rel = relations(d["records"])
    print(f"Related records: {sum(len(r['related']) for r in d['records']) // 2} linked in the records, "
          f"{sum(len(v) for v in rel['curated'].values()) // 2} confirmed by people, "
          f"{sum(len(v) for v in rel['suggestions'].values()) // 2} suggested at {rel['threshold']} or more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
