#!/usr/bin/env python3
"""Run the predictive maintenance detectors on a site's own exports and write a watch list and work requests.

Usage:
    python scripts/predict.py --source exports/ --out predictions/
    python scripts/predict.py --source exports/ --out predictions/ --since 2026-09-01   # only requests raised since
    python scripts/predict.py --demo --out predictions/      # this site's synthetic history, exported in the same files

--source is a folder holding any of these CSV files (the input contract, docs/predict/README.md); each
detector runs only when its file is there:

    optic_dom.csv        date, serial, location, peer, bias_ma, tx_dbm, rx_dbm   (one row per module per day)
    gpu_memory.csv       date, host, tray_serial, gpu, sbe_day, uce_day, remapped_rows, remap_pending
    gpu_xids.csv         opened, host, tray_serial, gpu, xid   (optional: what followed a warning)
    cdu_readings.csv     timestamp, cdu, flow_lpm, filter_dp_kpa, pump1_pct, pump2_pct
    cdu_events.csv       timestamp, cdu, resource, property, value   (Redfish pump health events)
    filter_changes.csv   cdu, completed_at   (optional: the last filter change before the readings)

--out receives watch_list.csv (every device not healthy on the last day), work_requests.csv (one row per
"act", in a shape any maintenance system can import), and predictions.json (everything, with the evidence).
Thresholds come from config/predict.yaml (--config to use another). Nothing is written anywhere else, and
nothing is sent to any device: the inputs are files the site has already exported.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.predict import detectors as D  # noqa: E402
from scorecard.predict import review as R  # noqa: E402

OPTIC_PARAMS = ("bias_ma", "tx_dbm", "rx_dbm")


def _csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def optic_modules(rows: list[dict]) -> list[dict]:
    """Long rows (one per module per day) into one series per module. A missing day carries the last reading forward."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["serial"], []).append(r)
    out = []
    for serial, rs in sorted(by.items()):
        rs.sort(key=lambda r: r["date"])
        d0, d1 = date.fromisoformat(rs[0]["date"]), date.fromisoformat(rs[-1]["date"])
        at = {r["date"]: r for r in rs}
        series = {p: [] for p in OPTIC_PARAMS}
        last = rs[0]
        for i in range((d1 - d0).days + 1):
            last = at.get((d0 + timedelta(days=i)).isoformat(), last)
            for p in OPTIC_PARAMS:
                series[p].append(float(last[p]))
        out.append({"serial": serial, "location": rs[-1]["location"], "peer": rs[-1]["peer"], "first_day": d0.isoformat(), **series})
    return out


def run(source: Path, cfg: dict, gh: dict) -> dict:
    det = cfg["detectors"]
    res: dict = {}
    if (source / "optic_dom.csv").exists():
        mods = optic_modules(_csv(source / "optic_dom.csv"))
        res["optics"] = D.optics(mods, det["optics"])
        res["optics_last_day"] = max((date.fromisoformat(m["first_day"]) + timedelta(days=len(m["rx_dbm"]) - 1)).isoformat() for m in mods)
    if (source / "gpu_memory.csv").exists():
        from scorecard.gpu_health import _rows
        counters = _rows((source / "gpu_memory.csv").read_text(encoding="utf-8"))
        xids = [{"opened": r["opened"], "host": r["host"], "tray_serial": r["tray_serial"], "gpu": int(r["gpu"]), "xid": int(r["xid"])}
                for r in _csv(source / "gpu_xids.csv")] if (source / "gpu_xids.csv").exists() else []
        res["gpu_memory"] = D.gpu_memory(counters, xids, gh)
    if (source / "cdu_readings.csv").exists():
        rows = _csv(source / "cdu_readings.csv")
        last = {r["cdu"]: r["completed_at"] for r in _csv(source / "filter_changes.csv")} if (source / "filter_changes.csv").exists() else None
        events = _csv(source / "cdu_events.csv") if (source / "cdu_events.csv").exists() else []
        res["cdu_filter"] = D.cdu_filter(rows, det["cdu_filter"], last)
        res["cdu_pump"] = D.cdu_pump(rows, events, det["cdu_pump"])
    return res


def watch_list(res: dict) -> list[dict]:
    """Every device whose state on its last reading is watch or act."""
    out = []
    last = res.get("optics_last_day", "")
    for f in res.get("optics", []):
        if f["now"] != "healthy" and f["last_day"] == last:   # a module that left before the export's last day is gone
            a = f["first_act"] or f["first_watch"]
            out.append({"detector": "optics", "device": f["location"], "serial": f["serial"], "state": f["now"], "since": a["day"],
                        "detail": f"{R.PARAM[a['param']][0]} reaches its warning by {a['warn_by']}"})
    for f in res.get("gpu_memory", []):
        if not f["xid_before"] and not f["xid_after"]:
            out.append({"detector": "gpu_memory", "device": f"{f['host']} GPU {f['gpu']}", "serial": f["tray_serial"], "state": "act",
                        "since": f["flagged"][:10], "detail": f"{f['why']}; {f['remapped_rows']} remapped rows"})
    for cdu, v in sorted(res.get("cdu_filter", {}).items()):
        n = v["now"]
        if n and n["state"] != "healthy":
            out.append({"detector": "cdu_filter", "device": cdu, "serial": "", "state": n["state"], "since": n["date"],
                        "detail": f"{n['level']} kPa at design flow; change limit on {n['limit_on']}"})
    for v in res.get("cdu_pump", {}).values():
        if v["now"] != "healthy":
            p = v["points"][-1]
            out.append({"detector": "cdu_pump", "device": f"{v['cdu']} pump {v['pump']}", "serial": "", "state": v["now"], "since": p["t"][:10],
                        "detail": f"{p['residual_pct']:+g}% speed for the flow; CUSUM {p['cusum']:g}"})
    return out


def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", help="folder with the exported CSV files")
    ap.add_argument("--demo", action="store_true", help="export this repository's synthetic condition history to OUT/inputs and run on it")
    ap.add_argument("--out", required=True, help="folder for watch_list.csv, work_requests.csv, predictions.json")
    ap.add_argument("--since", help="only work requests raised on or after this date (YYYY-MM-DD)")
    ap.add_argument("--config", default=str(ROOT / "config" / "predict.yaml"))
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.demo:
        args.source = str(Path(args.out) / "inputs")
        print("Exported the synthetic history as " + ", ".join(R.export_contract(R.PREDICT, R.HISTORY, Path(args.source))))
    if not args.source:
        ap.error("give --source (or --demo)")
    res = run(Path(args.source), cfg, R.gpu_health_config())
    if not res:
        print(f"No input files found in {args.source} (see the list in this script's help).")
        return 1
    reqs = [r for r in R.work_requests(res, cfg) if not args.since or r["flagged"][:10] >= args.since]
    for r in reqs:
        r.pop("key", None)
        r["owner_party"], r["accountable"], r["raci_component"] = r["owner"]["responsible"], r["owner"]["accountable"], r["owner"]["component"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wl = watch_list(res)
    _write(out / "watch_list.csv", wl, ["detector", "device", "serial", "state", "since", "detail"])
    _write(out / "work_requests.csv", reqs, ["id", "flagged", "detector", "device", "serial", "mode", "evidence", "due_by",
                                             "owner_party", "accountable", "raci_component"])
    (out / "predictions.json").write_text(json.dumps({"results": res, "watch_list": wl, "work_requests": reqs}, indent=1, sort_keys=True, default=str) + "\n",
                                          encoding="utf-8", newline="\n")
    print(f"Ran {', '.join(k for k in sorted(res) if k in R.PARTS)}: {len(wl)} on the watch list, {len(reqs)} work request{'' if len(reqs) == 1 else 's'} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
