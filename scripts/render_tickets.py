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

# The incident with a completed post-incident review (the rack A07 outage, PIR-2026-001).
PIR_REF = yaml.safe_load((ROOT / "pir" / "reviews" / "PIR-2026-001.yaml").read_text(encoding="utf-8"))["ref"]


def data() -> dict:
    d = T.build()
    d.update(class_text=CLASS_TEXT, pir_ref=PIR_REF)
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
