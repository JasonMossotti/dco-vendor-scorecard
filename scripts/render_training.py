#!/usr/bin/env python3
"""The Training page (/training/): the certification register and work gate (the opening view), the register by person,
renewals, and requirements.

Usage:
    python scripts/render_training.py --out _site/training     # write the page (build_site.py does this for the Pages build)

The page reads scorecard.certifications.page_data (the same data as reports/certifications.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import certifications as C  # noqa: E402
from scorecard import sitenav  # noqa: E402


def prepare() -> dict:
    return {"certs": C.page_data()}


def html_page() -> str:
    f = prepare()
    tpl = sitenav.inject((ROOT / "templates" / "training.html").read_text(encoding="utf-8"), "training")
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(f, sort_keys=True).replace("</", "<\\/")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "_site" / "training"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html_page(), encoding="utf-8", newline="\n")
    print(f"Wrote {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
