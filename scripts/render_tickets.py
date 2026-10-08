#!/usr/bin/env python3
"""Render the Incident Portal: every partner ticket, change, work order, MOP, and PM task with its timeline.

Usage:
    python scripts/render_tickets.py                  # print a summary of the records
    python scripts/render_tickets.py --html OUT.html  # write the page (scripts/build_site.py does this)
"""

from __future__ import annotations

import argparse
import json
import sys
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


def html_page() -> str:
    tpl = sitenav.inject((ROOT / "templates" / "tickets.html").read_text(encoding="utf-8"), "tickets")
    payload = json.dumps(data(), sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    return sitenav.finish(tpl.replace("__DATA__", payload))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--html", metavar="OUT")
    args = ap.parse_args()
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(html_page(), encoding="utf-8", newline="\n")
        print(f"Wrote {args.html}")
        return 0
    d = data()
    print("Incident Portal records: " + ", ".join(f"{d['types'][k]['plural'].lower()} {v}" for k, v in d["counts"].items()) + f" ({len(d['records'])} in all)")
    print(f"  with a finding {sum(1 for r in d['records'] if r['findings'])}, with alarms {sum(1 for r in d['records'] if r['alarms'])}, "
          f"measured {sum(1 for r in d['records'] if r['measured'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
