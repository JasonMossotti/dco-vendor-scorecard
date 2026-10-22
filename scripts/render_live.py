#!/usr/bin/env python3
"""Render the Live tab (/live/): the whole site minute by minute on the simulated live clock.

It reads what the telemetry already publishes (Site health's conditions and redundancy, the utility mains and the
ride-through, every UPS and generator by the minute, the busway by the hour, the Alarm Board's alarms and trouble
tickets, the fire panel, the security records) and generates nothing. The page's files are built with the site;
data/live/manifest.json commits their checksums and the reconciliation with Site health, so a stale page fails CI.

Usage:
    python scripts/render_live.py            # write data/live/manifest.json
    python scripts/render_live.py --check    # fail if it is stale (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import live_status as LS  # noqa: E402
from scorecard import site_health as SH  # noqa: E402
from scorecard import sitenav  # noqa: E402

OUT = ROOT / "data" / "live" / "manifest.json"


def prepare(dirs: SH.Dirs | None = None) -> tuple[dict, list[dict], list]:
    """The month index, the day files, and the agreements."""
    import render_alarms
    import render_fire
    import render_telemetry
    sh, data = SH.build(dirs)
    pw = render_telemetry.load_power()
    ut = render_telemetry.load_utility(pw)
    idx = LS.index(sh, data, pw, ut, render_alarms.prepare(), render_fire.prepare())
    idx["offset_h"] = render_alarms.OFFSET.total_seconds() / 3600
    day_files = LS.days(pw, ut)
    return idx, day_files, LS.agreements(sh, data, idx, day_files, ut)


def html_page(idx: dict | None = None) -> str:
    from scorecard import emergency
    idx = idx or prepare()[0]
    p1 = [{k: e[k] for k in ("id", "records", "start", "end", "summary")} for e in emergency.events(emergency.load_config())]
    page = {**idx, "p1": p1}   # the P1 banner; the page only, so index.json and the manifest are unchanged
    tpl = sitenav.inject((ROOT / "templates" / "live.html").read_text(encoding="utf-8"), "live")
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(page, sort_keys=True).replace("</", "<\\/")))


def write_site(out: Path, built: tuple | None = None) -> None:
    """out/index.html, out/data/index.json (the Telemetry pages' live strips read it), out/data/day_NN.json, and
    out/data/now_sample.json (a sample minute in the feed contract, docs/live/NOW_SCHEMA.md)."""
    idx, day_files, _ = built or prepare()
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html_page(idx), encoding="utf-8", newline="\n")
    (out / "data" / "index.json").write_text(LS.dumps(idx), encoding="utf-8", newline="\n")
    for d in day_files:
        (out / "data" / f"day_{d['day']:02d}.json").write_text(LS.dumps(d), encoding="utf-8", newline="\n")
    (out / "data" / "now_sample.json").write_text(LS.dumps(LS.now_doc(idx, day_files, LS.sample_minute(idx))), encoding="utf-8", newline="\n")


def manifest_text(built: tuple | None = None) -> str:
    idx, day_files, checks = built or prepare()
    return json.dumps(LS.manifest(idx, day_files, checks), indent=1, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    built = prepare()
    text = manifest_text(built)
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_live.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    checks = built[2]
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(built[0]['conditions'])} conditions, {len(built[1])} day files; "
          + ", ".join(f"{c.name} {c.checked - len(c.misses):,}/{c.checked:,}" for c in checks))
    return 1 if any(c.misses for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
