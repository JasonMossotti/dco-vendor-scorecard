#!/usr/bin/env python3
"""Render the GPU health review: reports/gpu_health.md and the GPU Health tab (/gpu/).

Synthetic health data modeled on public DCGM-style health checks (data/gpu_health/), read with the
month's XIDs, scheduler states, and tickets (data/sample/). Three checks: early warning before
memory failures, nodes returned to service with a row remap pending, and thermal slowdown walked
across the cooling demarcation (DM-COOL).

Usage:
    python scripts/render_gpu_health.py                    # write reports/gpu_health.md
    python scripts/render_gpu_health.py --check            # fail if it is stale (CI)
    python scripts/render_gpu_health.py --robustness 60    # plant and find the cases in 60 generated months
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

from scorecard import gpu_health as H  # noqa: E402
from scorecard import sitenav  # noqa: E402
from scorecard.synthetic import gpu_health as G  # noqa: E402

OUT = ROOT / "reports" / "gpu_health.md"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CODE = {"Pass": "p", "Warn": "w", "Fail": "f"}


def day(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{MON[int(m) - 1]} {int(d)}, {y}"


def short(iso: str) -> str:
    _, m, d = iso[:10].split("-")
    return f"{MON[int(m) - 1]} {int(d)}"


def at(iso: str) -> str:
    return f"{short(iso)} {iso[11:16]}"


def _issues(d: H.GpuData, r: H.Result) -> dict[str, list[dict]]:
    """Per rack, the trays with anything to show, each with its items (newest last)."""
    trays: dict[str, dict[str, list[dict]]] = {}

    def put(host: str, when: str, level: str, text: str, gpu: int | None = None) -> None:
        trays.setdefault(H.rack_of(host), {}).setdefault(host, []).append(
            {"when": when, "level": level, "text": text, "gpu": gpu})
    for w in d.watches:
        put(w["host"], w["opened"], w["result"],
            f"{w['system']} {w['result']}: {w['message']}" + (f"; cleared {at(w['cleared'])}" if w["cleared"] else "; still active"), w["gpu"])
    for f in r.flags:
        put(f["host"], f["flagged"], "Warn", f"Early warning: {f['why']} ({f['remapped_rows']} remapped rows, peak "
            f"{f['sbe_peak']:,} corrected errors in a day)", f["gpu"])
    by_tray: dict[str, list[dict]] = {}
    for e in d.episodes:
        by_tray.setdefault(e["host"], []).append(e)
    for host, eps in by_tray.items():
        mins = sum((G.parse(e["end"]) - G.parse(e["start"])).total_seconds() for e in eps) / 60
        days = sorted({e["start"][:10] for e in eps})
        put(host, eps[0]["start"], "Warn", f"Thermal slowdown on {len(days)} day{'s' if len(days) != 1 else ''}, "
            f"{mins:.0f} min in all, up to {max(e['gpu_temp_max_c'] for e in eps):.1f} C")
    return {rack: [{"host": h, "items": sorted(v, key=lambda x: x["when"])} for h, v in sorted(t.items())] for rack, t in trays.items()}


def prepare() -> dict:
    cfg = G.load_config()
    d = H.load()
    r = H.analyse(d, cfg)
    ev = H.evaluate(r, d.key, cfg) if d.key else None
    days = sorted({x["date"] for x in d.racks})
    racks = sorted({x["rack"] for x in d.racks}, key=lambda k: (k[0], int(k[1:])))
    meta = {x["rack"]: {"hall": x["hall"], "cdu": x["cdu"]} for x in d.racks}
    last = {x["rack"]: x for x in d.racks if x["date"] == days[-1]}
    peak = {}
    for x in d.racks:
        p = peak.setdefault(x["rack"], {"gpu": 0.0, "hbm": 0.0})
        p["gpu"], p["hbm"] = max(p["gpu"], x["gpu_temp_max_c"]), max(p["hbm"], x["hbm_temp_max_c"])
    grid = [{"rack": k, **meta[k], "status": "".join(CODE.get(r.grid.get(k, {}).get(day_), "-") for day_ in days),
             "trays": last.get(k, {}).get("trays_reporting", 0), "gpu_max": peak[k]["gpu"], "hbm_max": peak[k]["hbm"]}
            for k in racks]
    gpus = sum(x["trays"] for x in grid) * cfg["gpus_per_tray"]
    warned = [m for m in r.memory if m["warned"]]
    return {
        "framing": cfg["framing"], "sources": cfg["sources"],
        "window": d.window, "days": days, "grid": grid, "issues": _issues(d, r),
        "gpus": gpus, "watches": {"fail": sum(w["result"] == "Fail" for w in d.watches), "warn": sum(w["result"] == "Warn" for w in d.watches)},
        "flags": r.flags, "memory": r.memory, "warned": len(warned), "pending": r.pending,
        "thermal": r.thermal, "findings": [f.as_dict() for f in r.findings],
        "checks": cfg["checks"], "cdu_band": {"supply_max_c": cfg["cdu"]["alarm_high_c"], "flow_min_lpm": cfg["cdu"]["flow_band_min_lpm"]},
        "slowdown_c": cfg["thermal"]["slowdown_c"],
        "check": {"planted": ev.planted, "detected": ev.detected, "false_positives": len(ev.false_positives),
                  "decoys": d.key.get("decoys", {})} if ev else None,
    }


def markdown(f: dict) -> str:
    w = f["window"]
    end = G.iso(G.parse(w["end"]) - timedelta(hours=1))
    L = ["<!--", "  GENERATED FILE. DO NOT EDIT BY HAND.",
         "  Source: data/gpu_health/ (health layer), data/sample/ (XIDs, scheduler, tickets)  |  Generator: scripts/render_gpu_health.py",
         "-->", "", "# GPU Health Review: Site AUS-1", "",
         f"Sample month {day(w['start'])} to {day(end)} (UTC). {f['framing']} All names and serials are fictional; "
         "every threshold is an assumption in config/gpu_health.yaml.", "",
         "## Summary", "", "| Measure | Value |", "|---|---|",
         f"| GPUs reporting at the end of the month | {f['gpus']:,} |",
         f"| Health watches raised | {f['watches']['fail']} Fail, {f['watches']['warn']} Warn |",
         f"| Uncorrectable memory XIDs warned at least {f['checks']['lead_hours']} hours ahead | {f['warned']} of {len(f['memory'])} |",
         f"| GPUs on the early-warning list | {len(f['flags'])} |",
         f"| Returned to service with a row remap pending | {len(f['pending'])} |",
         f"| Trays throttling with the CDU in band | {len(f['thermal']['hot_trays'])} |",
         f"| CDU excursions that throttled GPUs | {len(f['thermal']['landlord'])} |", "",
         "## Findings", ""]
    if not f["findings"]:
        L.append("None.")
    for x in f["findings"]:
        L += [f"### {x['id']}: {x['title']}", "", x["summary"], "", f"- Owner: {x['party']}", f"- Contract: {', '.join(x['refs'])}"]
        L += [f"- {e}" for e in x["evidence"]]
        L.append("")
    L += ["## Early warning", "",
          f"A GPU is flagged at the end of the first day its remapped rows have risen by {f['checks']['remap_rise_rows']} within "
          f"{f['checks']['rise_window_days']} days, or its corrected memory errors have stayed above {f['checks']['sbe_floor']} a day and "
          f"risen {f['checks']['sbe_rising_days']} days running.", "",
          "| GPU | Flagged | Why | Remapped rows | Then |", "|---|---|---|---|---|"]
    for x in f["flags"]:
        then = (f"XID {x['xid_after']['xid']} {at(x['xid_after']['at'])} ({x['xid_after']['lead_h']:.0f} h later)" if x["xid_after"]
                else "No uncorrectable error yet")
        L.append(f"| {x['host']} GPU {x['gpu']} | {short(x['flagged'])} | {x['why']} | {x['remapped_rows']} | {then} |")
    L += ["", "| Uncorrectable memory XID | GPU | Warned ahead |", "|---|---|---|"]
    for m in f["memory"]:
        L.append(f"| XID {m['xid']} {at(m['at'])} | {m['host']} GPU {m['gpu']} | {'yes, ' + format(m['lead_h'], '.0f') + ' h' if m['warned'] else 'no'} |")
    L += ["", "## Cooling events and the GPUs they serve", "",
          "| CDU | Pump redundancy lost | Racks reporting | Lowest flow | Highest supply | In band | GPUs throttled |", "|---|---|---|---|---|---|---|"]
    for c in f["thermal"]["cooling_events"]:
        L.append(f"| {c['cdu']} | {at(c['start'])} to {at(c['end'])} | {len(c['racks_reporting'])} | {c['flow_min_lpm']:,} L/min | "
                 f"{c['supply_max_c']:.1f} C | {'yes' if c['in_band'] else 'no'} | {c['slowdown_gpus']} |")
    L += ["", f"Brief one-off slowdowns (a GPU touching {f['slowdown_c']:.0f} C for under two minutes) on "
              f"{f['thermal']['brief_trays']} trays are workload peaks, not findings."]
    if f["check"]:
        c = f["check"]
        dc = c["decoys"]
        L += ["", "## Engine self-check", "",
              f"Found **{c['detected']} of {c['planted']}** planted cases, **{c['false_positives']} false positives**. Decoys not flagged: "
              f"{dc.get('stable_remaps', 0)} GPUs with old, unchanging remapped rows, {dc.get('error_bursts', 0)} one-day error bursts, "
              f"{dc.get('brief_slowdowns', 0)} brief slowdowns. The checks cannot read the answer key."]
    L += ["", "## Sources", ""] + [f"- {s['name']}: {s['url']} (checked {s['checked']})" for s in f["sources"]]
    return "\n".join(L) + "\n"


def html_page() -> str:
    f = prepare()
    tpl = sitenav.inject((ROOT / "templates" / "gpu_health.html").read_text(encoding="utf-8"), "gpu")
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(f, sort_keys=True).replace("</", "<\\/")))


def robustness(n: int) -> int:
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    syn = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    cfg = G.load_config()
    tot: dict[str, list[int]] = {}
    fps, decoys = [], {}
    for k in range(n):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_dataset(SiteGenerator(load_sla(), syn, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run(), d)
            G.write_gpu_health(G.GpuHealthLayer(d, 2000 + k, cfg).run(), d / "gpu_health")
            data = H.load(d / "gpu_health", d)
            ev = H.evaluate(H.analyse(data, cfg), data.key, cfg)
        for kind, (a, b) in ev.by_kind.items():
            t = tot.setdefault(kind, [0, 0])
            t[0], t[1] = t[0] + a, t[1] + b
        for kind, v in data.key.get("decoys", {}).items():
            decoys[kind] = decoys.get(kind, 0) + v
        fps += [(k, x) for x in ev.false_positives]
        for m in ev.missed:
            print(f"  month {k}: missed {m}")
    print(f"GPU health checks on {n} generated months (cases moved and resized each month):")
    for kind, (a, b) in sorted(tot.items()):
        print(f"  {kind:<28} found {a}/{b}")
    print(f"  decoys                       {decoys.get('stable_remaps', 0)} stable remaps, {decoys.get('error_bursts', 0)} error bursts, "
          f"{decoys.get('brief_slowdowns', 0)} brief slowdowns; {len(fps)} false positives")
    for k, x in fps:
        print(f"  month {k}: false positive: {x}")
    return 0 if all(a == b for a, b in tot.values()) and not fps else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, metavar="N")
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness)
    f = prepare()
    text = markdown(f)
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_gpu_health.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(f['findings'])} findings")
    if f["check"]:
        print(f"Detected {f['check']['detected']} of {f['check']['planted']} planted, {f['check']['false_positives']} false positives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
