#!/usr/bin/env python3
"""Render the Scorecards tab (/app/) as a static page: every partner's scorecard and the Service credits view.

The engines run here, when the site is built, on each shipped dataset (the committed sample, and the latest
four weeks when the weekly deploy has generated them), so the page opens without starting Python in the
browser. The Python app that can generate a new month moves to /app/lab/ (scripts/build_site.py).

Usage:
    python scripts/render_scorecards.py              # print the headline numbers the page shows
    python scripts/render_scorecards.py --out page.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import scorecards_page as SP  # noqa: E402
from scorecard import sitenav  # noqa: E402


def prepare() -> dict:
    return SP.build(ROOT)


def html_page(data: dict | None = None) -> str:
    f = prepare() if data is None else data
    tpl = sitenav.inject((ROOT / "templates" / "scorecards.html").read_text(encoding="utf-8"), "scorecards")
    # Not sort_keys: each table row keeps its columns in the order the app shows them.
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(f).replace("</", "<\\/")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="write the page here")
    args = ap.parse_args()
    f = prepare()
    for ds in f["datasets"]:
        parts = [f"IT Partner {ds['it']['tiles']['defaults']} defaults ${ds['it']['credits']['payable']:,.0f}"]
        for k, name in (("landlord", "Landlord"), ("security", "Security Partner")):
            if ds[k]:
                parts.append(f"{name} {ds[k]['tiles']['defaults']} defaults ${ds[k]['credits']['payable']:,.0f}")
        print(f"{ds['label']}: " + "; ".join(parts))
    if args.out:
        Path(args.out).write_text(html_page(f), encoding="utf-8", newline="\n")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
