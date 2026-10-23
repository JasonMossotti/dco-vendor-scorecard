#!/usr/bin/env python3
"""Open every public reference the training portal cites (config/training/*.yaml) and report the ones that fail.

Usage:
    python scripts/check_training_links.py            # check every link (needs the internet; about a minute)
    python scripts/check_training_links.py --list     # list the links without opening them

Each reference carries the date it was last opened and found public (`checked`). A link that fails here is
replaced or removed, and the date is updated when it is opened again. Not run in CI: CI has no business
depending on other sites being up.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import training_portal as TP  # noqa: E402

AGENT = "Mozilla/5.0 (training link check; dco-vendor-scorecard)"
BLOCKED = {401, 403, 429}           # bot protection, not a missing page


def check(url: str) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,application/pdf,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, url
    except Exception as e:  # noqa: BLE001 (any network failure is a failed check)
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    refs = TP.references()
    if args.list:
        for k, r in sorted(refs.items()):
            print(f"{k:28} {r['checked']}  {r['url']}")
        return 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(zip(refs, ex.map(lambda r: check(r["url"]), refs.values())))
    bad = blocked = 0
    for k, (code, where) in sorted(results.items()):
        ok = code is not None and code < 400
        robot = code in BLOCKED                     # the site turns away scripts; open it in a browser instead
        bad += not ok and not robot
        blocked += robot
        tag = "ok  " if ok else "OPEN" if robot else "FAIL"
        print(f"{tag} {code or '---'} {k:28} {refs[k]['url']}" + ("" if ok or robot else f"  ({where})"))
    print(f"{len(refs) - bad - blocked} of {len(refs)} links open; {blocked} turn scripts away (OPEN: check those in a browser); {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
