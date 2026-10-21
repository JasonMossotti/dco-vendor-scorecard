#!/usr/bin/env python3
"""The Operations page (/ops/): the maintenance and change calendar (#calendar) and Safety (#ehs).

Usage:
    python scripts/render_ops.py --out _site/ops     # write the page (build_site.py does this for the Pages build)

The page reads scorecard.change_calendar.page_data and scorecard.ehs.page_data (the same data as reports/change_calendar.md
and reports/ehs.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import sitenav  # noqa: E402
from scorecard import change_calendar as CC  # noqa: E402
from scorecard import ehs as EHS  # noqa: E402


def prepare() -> dict:
    return {"calendar": CC.page_data(), "ehs": EHS.page_data()}


def html_page() -> str:
    f = prepare()
    tpl = sitenav.inject((ROOT / "templates" / "ops.html").read_text(encoding="utf-8"), "ops")
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(f, sort_keys=True).replace("</", "<\\/")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "_site" / "ops"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html_page(), encoding="utf-8", newline="\n")
    print(f"Wrote {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
