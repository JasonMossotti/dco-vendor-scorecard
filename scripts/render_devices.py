#!/usr/bin/env python3
"""Render the Devices page: every named device, what it connects to, and where it is on the drawings.

Usage:
    python scripts/render_devices.py --html _site/devices/index.html

The directory itself is docs/site/devices.json, written by scripts/render_site.py from the site model
(src/scorecard/devices.py). scripts/build_site.py publishes this page at /devices/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import devices, sitenav  # noqa: E402


TEL = ROOT / "data" / "telemetry"


def telemetry_links() -> dict[str, str]:
    """Each device the Telemetry tab has a view of, and that view's address (relative to the Telemetry tab). Read
    from the committed telemetry manifests, so a planned rack or a hall with no telemetry gets no link."""
    out: dict[str, str] = {}
    rd = lambda name: json.loads((TEL / name / "manifest.json").read_text(encoding="utf-8")) if (TEL / name / "manifest.json").exists() else {}  # noqa: E731
    for rack in rd("gpu").get("racks", []):
        out[rack] = f"#{rack}"
    for cdu in rd("cdu").get("cdus", {}):
        out[cdu] = f"#{cdu}"
    for d, x in rd("power").get("devices", {}).items():
        if x.get("family") in ("ups", "busway", "tapoff", "generator"):
            out[d] = f"#{d}"
    for d, x in rd("network").get("devices", {}).items():
        if x["family"] == "leaf":
            out[d] = f"#{d}"
        elif x["family"] == "port":
            out[f"{x['leaf']} port {x['port']}"] = f"#{d}"
            out.setdefault(x["peer_host"], f"#{x['peer_host']}/0")
        elif x["family"] == "nvlink":
            out[d] = f"#{d}"
    for d, x in rd("mechanical").get("devices", {}).items():
        if x["family"] != "loop":                   # the loop's headers have no device card
            out[d] = f"#{d}"
    return out


def register() -> dict | None:
    """The asset register's page data (scripts/render_assets.py), trimmed to what the page shows."""
    if not (ROOT / "data" / "assets" / "manifest.json").exists():
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    import render_assets
    f = render_assets.prepare()
    rows = [r + (f["opening"].get(r[0]) or ["", "", "", ""]) for r in f["assets"]]
    return {"window": f["window"], "findings": f["findings"], "corroborations": f["corroborations"], "agreements": f["agreements"],
            "by_class": f["by_class"], "statuses": f["statuses"], "assets": rows, "history": f["history"],
            "reported": f["reported"], "total": f["total"], "transactions": f["transactions"]}


def predictions() -> dict[str, str]:
    """The predictive maintenance detectors' state at month end for each device they watch (CDU filters and pumps,
    GPUs on the memory watch list), as one sentence per device card. The same run as the Failure Patterns tab's view."""
    if not (TEL / "cdu" / "cdu_hourly.csv").exists():
        return {}
    from scorecard.predict import review
    n = review.now()
    st = {"healthy": "healthy", "watch": "on watch", "act": "work request proposed"}
    out: dict[str, str] = {}
    for f in n["cdu_filter"]:
        t = f"Filter {st[f['state']]} by condition: {f['level']:g} kPa at design flow"
        t += f", change limit projected {f['limit_on']}" if f["limit_on"] else ""
        t += f" (due by the calendar {f['next_change']}, still clean)." if f["overdue"] and f["state"] == "healthy" else "."
        out[f["cdu"]] = t
    for p in sorted(n["cdu_pump"], key=lambda p: (p["cdu"], p["pump"])):
        out[p["cdu"]] += f" Pump {p['pump']} {st[p['state']]}" + (
            f" (failed on {', '.join(t[:10] for t in p['failures'])} with no wear seen first; replaced)" if p["failures"] and not p["warned"] else "") + "."
    for g in n["gpu_memory"]:
        if not g["xid_before"] and not g["xid_after"]:
            out[g["host"]] = (f"GPU {g['gpu']} on the memory watch list since {g['flagged'][:10]} ({g['why']}): drain and swap the tray "
                              "at the next window.")
    return out


def html_page() -> str:
    from scorecard import training_portal as TP
    training = {"kinds": TP.kind_courses(), "titles": {c["id"]: c["title"] for c in TP.content()["courses"]["courses"]}}
    from scorecard import pm_coverage as PC
    data = {**devices.load(), "telemetry": telemetry_links(), "assets": register(), "predict": predictions(), "training": training,
            "pmc": PC.device_notes()}
    tpl = sitenav.inject((ROOT / "templates" / "devices.html").read_text(encoding="utf-8"), "devices")
    body = json.dumps(data, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    return sitenav.finish(tpl.replace("__DEVICES__", body))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--html", metavar="OUT", required=True)
    args = ap.parse_args()
    out = Path(args.html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_page(), encoding="utf-8", newline="\n")
    print(f"Wrote {out} ({len(devices.load()['devices'])} devices)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
