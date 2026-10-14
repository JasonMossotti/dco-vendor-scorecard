#!/usr/bin/env python3
"""Render the Telemetry tab (site health, GPUs, CDUs, power, network, mechanical, and the management network) and its
reports: reports/gpu_telemetry.md, cdu_telemetry.md, power_telemetry.md, network_telemetry.md, mechanical_telemetry.md,
management_telemetry.md, and site_health.md.

Reads the committed GPU telemetry (data/telemetry/gpu/), the per-GPU hourly tier (built into
build/telemetry/gpu_hourly/ by scripts/generate_telemetry.py if missing), and the records it must agree
with (data/gpu_health/, data/sample/). Synthetic data in the published format of NVIDIA's open-source DCGM
exporter; no vendor's internal tooling is implied.

Usage:
    python scripts/render_telemetry.py                    # write the seven reports
    python scripts/render_telemetry.py --check            # exit 1 if a report is out of date
    python scripts/render_telemetry.py --robustness 60    # every agreement on 60 generated months
    python scripts/render_telemetry.py --robustness 60 --jobs 4 --resume build/robustness/telemetry
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import gpu_health as H  # noqa: E402
from scorecard import sitenav  # noqa: E402
from scorecard import site_health as SH  # noqa: E402
from scorecard import site_model as S  # noqa: E402
from scorecard import telemetry as TM  # noqa: E402
from scorecard import telemetry_cdu as TC  # noqa: E402
from scorecard import telemetry_mechanical as TMM  # noqa: E402
from scorecard import telemetry_mgmt as TG  # noqa: E402
from scorecard import telemetry_network as TN  # noqa: E402
from scorecard import telemetry_power as TP  # noqa: E402
from scorecard import xid as X  # noqa: E402
from scorecard.synthetic import gpu_health as G  # noqa: E402
from scorecard.synthetic import telemetry as T  # noqa: E402
from scorecard.synthetic import telemetry_cdu as TCS  # noqa: E402
from scorecard.synthetic import telemetry_mechanical as TMS  # noqa: E402
from scorecard.synthetic import telemetry_mgmt as TGS  # noqa: E402
from scorecard.synthetic import telemetry_network as TNS  # noqa: E402
from scorecard.synthetic import telemetry_power as TPS  # noqa: E402

DATA = ROOT / "data" / "telemetry" / "gpu"
HEALTH = ROOT / "data" / "gpu_health"
SAMPLE = ROOT / "data" / "sample"
OUT = ROOT / "reports" / "gpu_telemetry.md"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HALL_NAME = {"HALL-A": "Hall A", "HALL-B": "Hall B"}


def day(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{MON[int(m) - 1]} {int(d)}, {y}"


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _rk(r: str) -> tuple[str, int]:
    return r[0], int(r[1:])


def hourly_dir() -> Path:
    import generate_telemetry
    return generate_telemetry.ensure_hourly()


def load() -> TM.Telemetry:
    return TM.load(DATA, hourly_dir(), HEALTH, SAMPLE)


def summarize(t: TM.Telemetry, cfg: dict) -> dict:
    halls: dict[str, dict] = {}
    for r in t.rack_hourly:
        h = halls.setdefault(r["hall"], {"samples": 0, "util": 0.0, "kwh": 0.0, "peak": 0, "power_s": 0, "thermal_s": 0, "xids": 0,
                                         "racks": set(), "hours_on": 0})
        n = int(r["samples"])
        h["samples"] += n
        h["kwh"] += float(r["power_kwh"])
        h["power_s"] += int(r["power_violation_s"])
        h["thermal_s"] += int(r["thermal_violation_s"])
        h["xids"] += int(r["xids"])
        h["racks"].add(r["rack"])
        if n:
            h["util"] += float(r["util_avg"]) * n
            h["peak"] = max(h["peak"], int(r["gpu_temp_max_c"]))
    out = {}
    for k, h in sorted(halls.items()):
        product = "gb200_nvl72" if k == "HALL-A" else "gb300_nvl72"
        P = cfg["products"][product]
        gpu_hours = h["samples"] / 60
        out[k] = {"name": HALL_NAME.get(k, k), "product": product, "model": P["model_name"], "racks": len(h["racks"]),
                  "util_avg": round(h["util"] / h["samples"], 1) if h["samples"] else 0,
                  "power_avg_w": round(h["kwh"] * 1000 / gpu_hours) if gpu_hours else 0,
                  "power_limit_w": P["power_limit_w"], "power_max_w": P["power_max_w"],
                  "at_cap_pct": round(100 * h["power_s"] / (h["samples"] * 60), 1) if h["samples"] else 0,
                  "thermal_min": round(h["thermal_s"] / 60), "peak_c": h["peak"], "mwh": round(h["kwh"] / 1000, 1),
                  "samples": h["samples"], "xids": h["xids"]}
    return out


def prepare(t: TM.Telemetry | None = None) -> dict:
    cfg, hcfg = T.load_config(), G.load_config()
    t = t or load()
    checks = TM.agreements(t, cfg, hcfg)
    d = H.load()
    r = H.analyse(d, hcfg)
    names = X.names()
    racks = []
    for k in sorted(t.hourly, key=_rk):
        g = t.hourly[k]
        P = cfg["products"][g["product"]]
        first = next((i for i, n in enumerate(zip(*[TM.unrle(x["n"]) for x in g["gpus"]])) if any(n)), None)
        racks.append({"rack": k, "hall": g["hall"], "cdu": g["cdu"], "product": g["product"], "model": P["model_name"],
                      "power_limit_w": P["power_limit_w"], "from_hour": first, "trays": len(g["gpus"]) // T.GPUS})
    events = []
    for e in _jsonl(SAMPLE / "telemetry" / "dcgm_xid_events.jsonl"):
        tk = H._ticket(d, e["host"], G.parse(e["timestamp"]))
        events.append({"t": e["timestamp"], "host": e["host"], "gpu": int(e["gpu_index"]), "kind": "xid", "xid": int(e["xid"]),
                       "text": f"XID {e['xid']}: {names.get(int(e['xid']), e['message'])}", "ticket": tk["number"] if tk else None})
    for e in _jsonl(HEALTH / "thermal_episodes.jsonl"):
        events.append({"t": e["start"], "end": e["end"], "host": e["host"], "gpu": int(e["gpu"]), "kind": "slowdown",
                       "text": f"Hardware thermal slowdown, up to {e['gpu_temp_max_c']:.1f} C"})
    sched = _jsonl(SAMPLE / "telemetry" / "scheduler_node_states.jsonl")
    for i, e in enumerate(sched):
        if e["state"] in ("drain", "down"):
            back = next((x["timestamp"] for x in sched[i + 1:] if x["node"] == e["node"] and x["state"] == "idle"), None)
            tk = H._ticket(d, e["node"], G.parse(e["timestamp"]))
            events.append({"t": e["timestamp"], "end": back, "host": e["node"], "gpu": None, "kind": "drain",
                           "text": f"Scheduler: {e['state']} ({e['reason']})", "ticket": tk["number"] if tk else None})
    for gp in t.gaps:
        events.append({"t": gp["from"], "end": gp["to"], "host": gp["host"], "gpu": gp["gpu"], "kind": "dark",
                       "text": f"No samples: {gp['reason']}"})
    findings = []
    for f in r.findings:
        hosts = sorted(set(re.findall(r"\b[ab]\d\d-ct\d\d\b", " ".join([f.title] + f.evidence))))
        findings.append({"id": f.id, "title": f.title, "party": f.party, "hosts": hosts})
    fields = [{**f, "beyond_default": f["name"] in cfg["collection"]["enabled_beyond_default"]} for f in cfg["fields"]]
    return {
        "framing": cfg["framing"], "sources": cfg["sources"], "collection": cfg["collection"], "fields": fields,
        "window": t.manifest["window"], "hours": t.hourly[next(iter(t.hourly))]["hours"], "gpus": t.manifest["gpus"],
        "racks": racks, "halls": summarize(t, cfg), "events": sorted(events, key=lambda e: (e["t"], e["host"])),
        "findings": findings, "windows": t.manifest["windows"],
        "slowdown_c": hcfg["thermal"]["slowdown_c"], "hbm_over_gpu_c": cfg["thermal"]["hbm_over_gpu_c"],
        "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks],
        "misses": [m for c in checks for m in c.misses][:20],
        "cdu": prepare_cdu(gpu=t),
        "power": prepare_power(),
        "network": prepare_network(),
        "mechanical": prepare_mechanical(),
        "mgmt": prepare_mgmt(),
        "site": prepare_site(),
    }


# --------------------------------------------------------------------------- CDUs
DATA_CDU = ROOT / "data" / "telemetry" / "cdu"
ENERGY = ROOT / "data" / "energy"
OUT_CDU = ROOT / "reports" / "cdu_telemetry.md"
PLANNED: list[str] = []          # device families still to come: shown greyed in the selector


def load_cdu() -> TC.CduData:
    minutes = hourly_dir().parent / "cdu_minutes"
    return TC.load(DATA_CDU, minutes, HEALTH, SAMPLE, ENERGY, DATA)


def _work_orders() -> list[dict]:
    d = json.loads((SAMPLE / "landlord" / "work_orders.json").read_text(encoding="utf-8"))
    return d if isinstance(d, list) else d.get("work_orders", [])


def _wo_for(wos: list[dict], units: list[str], at: str) -> str | None:
    t = G.parse(at)
    for w in wos:
        if w.get("unit") in units and w.get("opened") and abs((G.parse(w["opened"]) - t).total_seconds()) <= 3600:
            return w["wo"]
    return None


def _leak_ticket(note: str, at: str) -> str | None:
    """The IT Partner's leak ticket for a rack named in the leak point (a rope at a rack manifold), opened within the hour."""
    m = re.search(r"\b([AB]\d\d)\b", note)
    if not m:
        return None
    d = json.loads((SAMPLE / "vendor" / "tickets.json").read_text(encoding="utf-8"))
    t = G.parse(at)
    for x in (d if isinstance(d, list) else d.get("tickets", [])):
        if x.get("category") == "leak" and m.group(1) in x.get("configuration_item", "") and x.get("opened_at") \
                and abs((G.parse(x["opened_at"]) - t).total_seconds()) <= 3600:
            return x["number"]
    return None


def bms_points(fields: list[dict]) -> list[dict]:
    """An illustrative BMS point list in the usual points-list style (one BACnet analog input and one pair of Modbus
    input registers holding a 32-bit float per point). Not CoolIT's or any vendor's map: none is published."""
    return [{"key": f["key"], "bacnet": f"AI-{101 + i}", "modbus": 30001 + 2 * i} for i, f in enumerate(fields)]


def prepare_cdu(t: TC.CduData | None = None, gpu: TM.Telemetry | None = None) -> dict:
    ccfg, hcfg = TCS.load_config(), G.load_config()
    t = t or load_cdu()
    checks = TC.agreements(t, ccfg, hcfg)
    site = S.load_site()
    unit = S.product(site, "coolit_chx2000")
    wos = _work_orders()
    pm = {r["task_id"]: r for r in csv.DictReader((SAMPLE / "landlord" / "pm_records.csv").open(encoding="utf-8"))}
    hourly: dict[str, list[dict]] = {}
    for r in t.hourly:
        hourly.setdefault(r["cdu"], []).append(r)
    events: list[dict] = []
    for c in t.cdus:
        sts = [s for s in t.states if s["cdu"] == c]
        for i, s in enumerate(sts):
            res, prop, val = s["resource"].rsplit(f"/{c}", 1)[-1] or "/", s["property"], s["value"]
            later = [x for x in sts[i + 1:] if x["resource"] == s["resource"]]
            if "/Pumps/" in s["resource"] and prop == "Status.State" and val == "Disabled":
                p = res.rsplit("/", 1)[1]
                end = next((x["time"] for x in later if x["property"] == "Status.State" and x["value"] == "Enabled"), None)
                task = next((k for k, r in pm.items() if r["asset"] == c and end and r["completed_at"] == end), None)
                refs = [x for x in (task, pm[task]["mop_ref"] if task else None) if x]
                events.append({"t": s["time"], "end": end, "cdu": c, "kind": "pm",
                               "text": f"Pump {p} isolated for a filter change and coolant sample; filter changed when it was re-enabled",
                               "refs": refs})
            elif "/Pumps/" in s["resource"] and prop == "Status.Health" and val == "Critical":
                p = res.rsplit("/", 1)[1]
                end = next((x["time"] for x in later if x["property"] == "Status.Health" and x["value"] == "OK"), None)
                wo = _wo_for(wos, [c], s["time"])
                events.append({"t": s["time"], "end": end, "cdu": c, "kind": "pump",
                               "text": f"Pump {p} failed: the standby pump took over (flow dipped for a minute); pump redundancy lost until the repair tested OK",
                               "refs": [wo] if wo else []})
            elif prop == "DetectorState" and val == "Critical":
                det = res.rsplit("/", 1)[1]
                end = next((x["time"] for x in later if x["value"] == "OK"), None)
                units = [c, "TTDM-" + c[4] + "/C" + str(4 + int(c[5:]))] if det == "1" else [c]
                wo = _wo_for(wos, units, s["time"]) or _leak_ticket(s.get("note", ""), s["time"])
                events.append({"t": s["time"], "end": end, "cdu": c, "kind": "leak",
                               "text": f"Leak detector {det} ({'under the unit' if det == '1' else 'row leak rope'}): {s.get('note', '')}; the reservoir level fell until it was cleared",
                               "refs": [wo] if wo else []})
    for gp in (gpu.gaps if gpu else []):
        if gp["reason"] == "rack input power lost" and gp["gpu"] is None:
            rack = gp["host"][:3].upper()
            hall = "HALL-" + rack[0]
            if not any(e["kind"] == "rack" and e["rack"] == rack for e in events):
                events.append({"t": gp["from"], "end": gp["to"], "cdu": None, "hall": hall, "rack": rack, "kind": "rack",
                               "text": f"Rack {rack} lost input power: its heat left the {HALL_NAME.get(hall, hall)} header until it booted",
                               "refs": []})
    cdus = []
    for c in t.cdus:
        rows = hourly[c]
        fl = lambda k: [float(r[k]) for r in rows]          # noqa: E731
        x = t.minutes(c)
        raw = x["raw"]
        racks = [r["rack"] for r in S.racks(site, t.manifest["cdus"][c]["hall"]) if r["cdu"] == c]
        cdus.append({"id": c, "hall": t.manifest["cdus"][c]["hall"], "uri": t.manifest["cdus"][c]["uri"], "racks": racks,
                     "supply_avg": round(sum(fl("supply_c")) / len(rows), 2), "supply_max": max(fl("supply_max_c")),
                     "return_avg": round(sum(fl("return_c")) / len(rows), 2), "flow_avg": round(sum(fl("flow_lpm")) / len(rows)),
                     "flow_min": min(fl("flow_min_lpm")), "heat_avg_kw": round(sum(fl("heat_kwh")) / len(rows)),
                     "heat_peak_kw": round(max(fl("heat_kwh"))), "dp_avg": round(sum(fl("dp_kpa")) / len(rows), 1),
                     "filter_dp_end": float(rows[-1]["filter_dp_kpa"]), "filter_serviced": raw["filter_serviced"],
                     "reservoir_end": float(rows[-1]["reservoir_pct"]), "power_avg_kw": round(sum(fl("power_kwh")) / len(rows), 1),
                     "leak_min": sum(int(r["leak_min"]) for r in rows), "redundancy_lost_min": sum(int(r["redundancy_lost_min"]) for r in rows),
                     "pump_hours": [round(sum(1 for v in x[f"pump{p}_pct"] if v > 0) / 60) for p in (1, 2)],
                     "service_hours_start": raw["service_hours_start"]})
    halls = {}
    for h in site["halls"]:
        ids = [f"CDU-{h['letter']}{i}" for i in range(1, h["cooling"]["cdu_count"] + 1)]
        mine = [c for c in cdus if c["hall"] == h["id"]]
        cap = unit["capacity_kw"] * (len(ids) - h["cooling"]["cdu_redundancy"])
        heat = [sum(float(hourly[c["id"]][i]["heat_kwh"]) for c in mine) for i in range(len(hourly[mine[0]["id"]]))] if mine else []
        halls[h["id"]] = {"name": h["name"], "state": h.get("state", "in service"), "cdus": ids, "in_service": bool(mine),
                          "capacity_n_kw": cap, "heat_avg_kw": round(sum(heat) / len(heat)) if heat else 0,
                          "heat_peak_kw": round(max(heat)) if heat else 0}
    fields = ccfg["fields"]
    pts = {p["key"]: p for p in bms_points(fields)}
    return {"framing": ccfg["framing"], "sources": ccfg["sources"], "collection": ccfg["collection"],
            "fields": [{**f, "bacnet": pts[f["key"]]["bacnet"], "modbus": pts[f["key"]]["modbus"]} for f in fields],
            "states": ccfg["states"], "detectors": ccfg["unit"]["leak_detectors"],
            "unit": {"manufacturer": unit["manufacturer"], "model": unit["model"], "capacity_kw": unit["capacity_kw"],
                     "flow_lpm": unit["secondary_flow_lpm"], "coolant": unit["coolant"], "pumps": ccfg["unit"]["pumps"],
                     "rated_service_hours": ccfg["filter"]["rated_service_days"] * 24},
            "setpoint_c": hcfg["cdu"]["setpoint_c"], "alarm_high_c": hcfg["cdu"]["alarm_high_c"],
            "band_min_lpm": hcfg["cdu"]["flow_band_min_lpm"], "window": t.manifest["window"],
            "hours": len(next(iter(hourly.values()))), "cdus": cdus, "halls": halls, "planned": PLANNED,
            "events": sorted(events, key=lambda e: (e["t"], e.get("cdu") or "")),
            "redfish_states": [{k: s[k] for k in ("cdu", "m", "time", "resource", "property", "value", "record")} for s in t.states],
            "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks],
            "misses": [m for c in checks for m in c.misses][:20]}


def cdu_json(t: TC.CduData, cdu: str) -> dict:
    """One CDU's month by hour (from the committed cdu_hourly.csv): what the CDU view charts."""
    rows = [r for r in t.hourly if r["cdu"] == cdu]
    cols = [c for c in TCS.HOURLY_COLUMNS if c not in ("hour", "cdu", "hall")]
    return {"cdu": cdu, "start": t.manifest["window"]["start"], "hours": len(rows),
            "series": {c: [float(r[c]) if "." in r[c] else int(r[c]) for r in rows] for c in cols}}


def cdu_markdown(f: dict) -> str:
    L = ["# CDU telemetry (Site AUS-1, synthetic)", "",
         f"{f['framing']} Window {day(f['window']['start'])} to {day(f['window']['end'])}: one Redfish read a minute of each of "
         f"{len(f['cdus'])} {f['unit']['manufacturer']} {f['unit']['model']} units ({f['unit']['capacity_kw']:,} kW, "
         f"{f['unit']['flow_lpm']:,} L/min, {f['unit']['coolant']}), at `{f['collection']['base_uri']}/{{id}}` with the Customer's "
         f"{f['collection']['account']} account.", "",
         "Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py", "",
         "No CDU maker publishes its Modbus register map or BACnet point list, so the readings use the DMTF Redfish schema "
         "(the open standard); the BMS point numbers on the page are illustrative.", "",
         "## Fields", "", "| Resource | Property | Unit | Meaning |", "|---|---|---|---|"]
    for x in f["fields"]:
        L.append(f"| `{x['resource']}` | `{x['property']}` | {x['unit']} | {x['help']} |")
    L += ["", "## The month by CDU", "",
          "| CDU | Supply avg / max C | Return avg C | Flow avg / min L/min | Heat avg / peak kW | Filter dP at end kPa | Leak min | Redundancy lost min |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for c in f["cdus"]:
        L.append(f"| {c['id']} | {c['supply_avg']} / {c['supply_max']} | {c['return_avg']} | {c['flow_avg']:,} / {c['flow_min']:,.0f} | "
                 f"{c['heat_avg_kw']:,} / {c['heat_peak_kw']:,} | {c['filter_dp_end']} | {c['leak_min']} | {c['redundancy_lost_min']} |")
    L += ["", "## Halls", "", "| Hall | State | CDUs | Heat avg / peak kW | Capacity with one CDU down kW |", "|---|---|---|---:|---:|"]
    for k, h in f["halls"].items():
        L.append(f"| {h['name']} | {'in service' if h['in_service'] else h['state']} | {', '.join(h['cdus'])} | "
                 f"{h['heat_avg_kw']:,} / {h['heat_peak_kw']:,} | {h['capacity_n_kw']:,} |")
    L += ["", "## Events", "", "| From | To | CDU | What | Records |", "|---|---|---|---|---|"]
    for e in f["events"]:
        L.append(f"| {e['t']} | {e.get('end') or ''} | {e.get('cdu') or e.get('rack')} | {e['text']} | {', '.join(e['refs'])} |")
    L += ["", "## Agreement with the records", "", "| Check | Agrees |", "|---|---:|"]
    for a in f["agreements"]:
        L.append(f"| {a['title']} | {a['checked'] - a['misses']:,} of {a['checked']:,} |")
    if f["misses"]:
        L += ["", "Disagreements:", ""] + [f"- {m}" for m in f["misses"]]
    L += ["", "## Sources", ""] + [f"- {s['name']}: {s['url']} (checked {s['checked']})" for s in f["sources"]]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- power
DATA_POWER = ROOT / "data" / "telemetry" / "power"
OUT_POWER = ROOT / "reports" / "power_telemetry.md"
GPU_DIR = DATA


def load_power() -> TP.PowerData:
    return TP.load(DATA_POWER, hourly_dir().parent / "power_minutes", SAMPLE, ENERGY, DATA, DATA_CDU)


def _power_refs(device: str, units: list[str], a: str, b: str | None) -> list[str]:
    """The Landlord's records for an event: work orders on the unit open across it, their MOPs, and the PM task
    completed when it ended."""
    ta, tb = G.parse(a), G.parse(b) if b else G.parse(a)
    refs: list[str] = []
    for w in _work_orders():
        if w.get("unit") in units and w.get("opened"):
            wo, wc = G.parse(w["opened"]), G.parse(w.get("closed") or w["opened"])
            if wo - timedelta(hours=2) <= tb and ta <= wc + timedelta(minutes=30):
                refs += [w["wo"]] + ([w["mop_ref"]] if w.get("mop_ref") else []) + re.findall(r"\bMOP-\d+\b", w.get("notes") or "")
    for r in csv.DictReader((SAMPLE / "landlord" / "pm_records.csv").open(encoding="utf-8")):
        if r["asset"] == device and r.get("completed_at") and b and abs((G.parse(r["completed_at"]) - tb).total_seconds()) <= 120:
            refs += [r["task_id"]] + ([r["mop_ref"]] if r.get("mop_ref") else [])
    return list(dict.fromkeys(refs))


def power_events(t: TP.PowerData) -> list[dict]:
    """Each state change paired with the change that ends it, with the records that explain it."""
    out: list[dict] = []
    by_dev: dict[str, list[dict]] = {}
    for s in t.states:
        by_dev.setdefault(s["device"], []).append(s)
    dev = t.manifest["devices"]
    H = t.M // 60
    findings = {f["unit"]: f for f in json.loads((ROOT / "reports" / "landlord_findings.json").read_text(encoding="utf-8"))}
    wo_outage = next((w["wo"] for w in _work_orders() if w.get("unit") == "138 kV utility service"), None)
    for d, sts in sorted(by_dev.items()):
        sts = sorted(sts, key=lambda s: (s["time"], s["point"]))
        fam = sts[0]["family"]
        if fam == "ups":
            since: dict[str, dict] = {}
            for s in sts:
                v = s["value"]
                if v in ("switchedBypass", "onBattery") or (v.startswith("Power module") and v.endswith("fault")):
                    since[v] = s
                elif v == "onLine":
                    for k in ("switchedBypass", "onBattery"):
                        if k in since:
                            a = since.pop(k)
                            secs = (G.parse(s["time"]) - G.parse(a["time"])).total_seconds()
                            if k == "onBattery":
                                txt, kind = f"On battery for {secs:.0f} s: the utility failed and the generators took the load", "battery"
                                refs = [wo_outage] if wo_outage else []
                            else:
                                txt, kind = f"On bypass for {secs / 60:.0f} min: maintenance on the UPS (the load rode the bypass, unprotected)", "bypass"
                                refs = _power_refs(d, [d], a["time"], s["time"])
                            out.append({"t": a["time"], "end": s["time"], "device": d, "family": fam, "kind": kind, "text": txt, "refs": refs})
                elif v == "Power module redundancy restored":
                    k = next((x for x in since if x.startswith("Power module")), None)
                    if k:
                        a = since.pop(k)
                        out.append({"t": a["time"], "end": s["time"], "device": d, "family": fam, "kind": "module",
                                    "text": f"{a['value']}: one power cabinet out, the UPS ran without its spare cabinet until it was replaced",
                                    "refs": _power_refs(d, [d], a["time"], s["time"])})
        elif fam == "tapoff":
            opened = None
            for s in sts:
                if s["value"] == "open":
                    opened = s
                elif opened is not None:
                    named = re.search(r"names (\S+);", s.get("note") or "")
                    units = [dev[d]["run"], f"Rack {dev[d]['rack']}"] + ([named.group(1)] if named else [])
                    note = f" The CPM record names {named.group(1)}; the tap-off is on {dev[d]['run']}." if named else ""
                    other = f"TO-{dev[d]['rack']}-{'B' if dev[d]['side'] == 'A' else 'A'}"
                    both, o_open = False, None
                    for x in sorted(by_dev.get(other, []), key=lambda x: x["time"]):
                        if x["value"] == "open":
                            o_open = x["time"]
                        elif o_open is not None:
                            both = both or (o_open < s["time"] and opened["time"] < x["time"])
                            o_open = None
                    rk, h0 = dev[d]["rack"], opened["m"] // 60
                    drawing = any(t.tapoff_hourly["tapoffs"].get(f"TO-{rk}-{x}", {"wh": [0] * H})["wh"][h0] > 0 for x in "AB")
                    what = (f"rack {rk} was not yet drawing power, so no load moved" if not drawing
                            else f"rack {rk} lost both feeds while {other} was open too, and went dark" if both
                            else f"rack {rk} ran on its other feed")
                    out.append({"t": opened["time"], "end": s["time"], "device": d, "family": fam, "kind": "breaker",
                                "text": f"Tap-off breaker open: {what}.{note}",
                                "refs": _power_refs(d, units, opened["time"], s["time"])})
                    opened = None
        elif fam == "busway":
            lost = None
            for s in sts:
                if s["point"] == "cpmAcInfLineToLineVoltAve" and "out of tolerance" in s["value"]:
                    lost = s
                elif s["point"] == "cpmAcInfLineToLineVoltAve" and lost is not None:
                    h0 = lost["m"] // 60
                    live = [r for r in dev[d]["racks"] if any(t.tapoff_hourly["tapoffs"].get(f"TO-{r}-{x}", {"wh": [0] * H})["wh"][h0] > 0 for x in "AB")]
                    carried = (f"its {len(live)} racks drawing power ran on their other feed" if live else
                               "none of its racks was drawing power yet (not yet in service), so nothing moved")
                    out.append({"t": lost["time"], "end": s["time"], "device": d, "family": fam, "kind": "feed",
                                "text": f"Feed lost: the feeder breaker tripped and the run read 0 V; {carried}",
                                "refs": _power_refs(d, [d], lost["time"], s["time"])})
                    lost = None
        elif fam == "generator":
            start = None
            for s in sts:
                if s["value"] == "Starting":
                    start = s
                elif s["value"] == "Stopped" and start is not None:
                    test = s["record"].startswith("facility/emcp")
                    x = t.minutes(d)
                    a, b = start["m"], s["m"] + 1
                    pk = int(x["pct_kw"][a:b].max()) / 10
                    kw = int(x["kw"][a:b].max()) / 10
                    run_min = int((x["state"][a:b] == 2).sum())         # minutes in the Running state, as the EMCP record counts them
                    refs = _power_refs(d, [d], start["time"], s["time"]) if test else ([wo_outage] if wo_outage else [])
                    f = findings.get(d) if test else None
                    if f and not any(r in refs for r in (f.get("tickets") or [])):
                        f = None
                    txt = (f"Monthly loaded exercise: {run_min} min running, up to {kw:,.0f} kW ({pk:.1f}% of rated) on the load bank" if test
                           else f"Utility outage: {run_min} min running, carrying the site in parallel, up to {kw:,.0f} kW ({pk:.1f}% of rated)")
                    out.append({"t": start["time"], "end": s["time"], "device": d, "family": fam, "kind": "test" if test else "outage",
                                "text": txt, "refs": refs, "finding": {"id": f["id"], "title": f["title"], "summary": f["summary"]} if f else None,
                                "pct_max": pk, "kw_max": kw, "run_min": run_min})
                    start = None
    for o in t.manifest["outages"]:
        out.append({"t": o["trip"], "end": o["back"], "device": "SITE", "family": "site", "kind": "utility",
                    "text": "Utility outage: both MV mains tripped on undervoltage; the UPSs bridged 12 s on battery until the generator ties closed, "
                            "then the generators carried the site until the utility returned (closed-transition retransfer)",
                    "refs": [wo_outage] if wo_outage else []})
    for e in out:
        e["m"] = t.m_of(e["t"])
    return sorted(out, key=lambda e: (e["t"], e["device"]))


def prepare_power(t: TP.PowerData | None = None) -> dict:
    from scorecard.synthetic.energy import load_config as energy_config
    pcfg, ccfg = TPS.load_config(), TCS.load_config()
    t = t or load_power()
    checks = TP.agreements(t, pcfg, ccfg["rack_rest"], energy_config())
    site = S.load_site()
    dev = t.manifest["devices"]
    H = t.M // 60
    rating_a = S.product(site, "starline_1200t5")["rating_a"]
    ups_rows: dict[str, list[dict]] = {}
    for r in t.ups_hourly:
        ups_rows.setdefault(r["ups"], []).append(r)
    run_rows: dict[str, list[dict]] = {}
    for r in t.busway_hourly:
        run_rows.setdefault(r["run"], []).append(r)
    gen_rows: dict[str, list[dict]] = {}
    for r in t.generator_hourly:
        gen_rows.setdefault(r["generator"], []).append(r)
    fl = lambda rows, k: [float(r[k]) for r in rows]          # noqa: E731
    ups = []
    for u in sorted(ups_rows):
        rows, x = ups_rows[u], dev[u]
        out = fl(rows, "out_kwh")
        ups.append({"id": u, "hall": x["hall"], "kind": x["kind"], "model": x["model"], "rating_kw": x["rating_kw"], "modules": x["modules"],
                    "runs": sorted(r for r, y in dev.items() if y["family"] == "busway" and y["ups"] == u),
                    "out_avg_kw": round(sum(out) / len(out), 1), "out_peak_kw": round(max(out), 1),
                    "load_avg": round(sum(fl(rows, "load_avg_pct")) / len(rows), 1), "load_peak": max(fl(rows, "load_max_pct")),
                    "out_mwh": round(sum(out) / 1000, 1), "in_mwh": round(sum(fl(rows, "in_kwh")) / 1000, 1),
                    "bypass_min": sum(int(r["bypass_min"]) for r in rows), "battery_s": sum(int(r["battery_s"]) for r in rows),
                    "soc_min": min(int(float(r["soc_min_pct"])) for r in rows),
                    "modules_lost_h": sum(1 for r in rows if int(r["modules_min"]) < x["modules"])})
    runs = []
    for run in sorted(run_rows):
        rows, x = run_rows[run], dev[run]
        runs.append({"id": run, "hall": x["hall"], "ups": x["ups"], "segment": x["segment"], "side": x["side"], "row": run.split("-")[2],
                     "racks": x["racks"], "tapoffs": x["tapoffs"], "mwh": round(sum(fl(rows, "kwh")) / 1000, 1),
                     "amps_avg": round(sum(fl(rows, "amps_avg")) / len(rows), 1), "amps_peak": max(fl(rows, "amps_max")),
                     "v_min": min(float(r["v_min"]) for r in rows if int(r["dead_min"]) < 60) if any(int(r["dead_min"]) < 60 for r in rows) else 0,
                     "v_max": max(fl(rows, "v_max")), "dead_min": sum(int(r["dead_min"]) for r in rows), "encl_max": max(fl(rows, "encl_max_c"))})
    # single feed: if a run's partner feed fails, this run carries both: the segment's A plus B in that hour
    seg: dict[str, list[float]] = {}
    for r in runs:
        rows = run_rows[r["id"]]
        cur = seg.setdefault(r["segment"], [0.0] * len(rows))
        for i, row in enumerate(rows):
            cur[i] += float(row["amps_avg"])
    for r in runs:
        r["single_feed_peak_a"] = round(max(seg[r["segment"]]), 1)
    events = power_events(t)
    gens = []
    for g in sorted(gen_rows):
        rows = gen_rows[g]
        mine = [e for e in events if e["device"] == g]
        gens.append({"id": g, "run_min": sum(int(r["run_min"]) for r in rows), "mwh": round(sum(fl(rows, "kwh")) / 1000, 2),
                     "kw_max": max(fl(rows, "kw_max")), "pct_max": max(fl(rows, "pct_max")), "fuel_end": float(rows[-1]["fuel_pct"]),
                     "hours_end": float(rows[-1]["hours"]), "hours_start": round(float(rows[0]["hours"]) - (int(rows[0]["run_min"]) / 60), 2),
                     "runs": [{k: e[k] for k in ("t", "end", "kind", "run_min", "kw_max", "pct_max", "m")} for e in mine]})
    halls = {}
    for h in site["halls"]:
        if h["state"] not in ("production", "deployment"):
            continue
        ids = [u["id"] for u in ups if u["hall"] == h["id"] and u["kind"] == "it"]
        tot = [sum(float(ups_rows[u][i]["out_kwh"]) for u in ids) for i in range(H)]
        peak, rating = max(tot), dev[ids[0]]["rating_kw"]
        racks_live = sorted({r for rr in runs if rr["hall"] == h["id"] for r in rr["racks"]})
        halls[h["id"]] = {"name": h["name"], "state": h["state"], "ups": ids,
                          "mups": [u["id"] for u in ups if u["hall"] == h["id"] and u["kind"] == "mech"],
                          "rows": {row: [r["id"] for r in runs if r["hall"] == h["id"] and r["row"] == row]
                                   for row in sorted({r["row"] for r in runs if r["hall"] == h["id"]})},
                          "avg_kw": round(sum(tot) / len(tot), 1), "peak_kw": round(peak, 1), "peak_hour": tot.index(peak),
                          "rating_kw": rating, "n": len(ids), "need": h["power"].get("ups_needed", len(ids) - 1),
                          "one_down_pct": round(100 * peak / (len(ids) - 1) / rating, 1),
                          "design_kw": round(rating * (len(ids) - 1), 1), "racks": len(racks_live)}
    rack_feeds: dict[str, list[dict]] = {}
    for d, x in dev.items():
        if x["family"] == "tapoff":
            rack_feeds.setdefault(x["rack"], []).append({"tapoff": d, "side": x["side"], "run": x["run"], "ups": dev[x["run"]]["ups"]})
    for v in rack_feeds.values():
        v.sort(key=lambda z: z["side"])
    gc = pcfg["generator"]
    return {"framing": pcfg["framing"], "sources": pcfg["sources"], "collection": pcfg["collection"], "fields": pcfg["fields"],
            "electrical": {k: pcfg["electrical"][k] for k in ("ll_v", "ln_v", "hz", "gen_v_ll")},
            "rating_a": rating_a, "busway_limit": pcfg["checks"]["busway_limit"], "output_source": pcfg["ups"]["output_source"],
            "gen_states": gc["states"], "gen_switch": {str(k): v for k, v in gc["switch"].items()}, "gen_rated_kw": gc["rated_kw"],
            "battery": {"nominal_v": pcfg["ups"]["battery"]["nominal_v"]}, "window": t.manifest["window"], "hours": H,
            "ups": ups, "runs": runs, "gens": gens, "halls": halls, "rack_feeds": rack_feeds,
            "events": events, "outages": t.manifest["outages"], "windows": t.manifest["windows"],
            "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks],
            "misses": [m for c in checks for m in c.misses][:20]}


def power_json(t: TP.PowerData, device: str) -> dict:
    """One UPS's, run's, or generator's month by hour (from the committed hourly tables): what its view charts."""
    fam = t.manifest["devices"][device]["family"]
    table, key, cols = {"ups": (t.ups_hourly, "ups", TPS.UPS_HOURLY), "busway": (t.busway_hourly, "run", TPS.RUN_HOURLY),
                        "generator": (t.generator_hourly, "generator", TPS.GEN_HOURLY)}[fam]
    rows = [r for r in table if r[key] == device]
    keep = [c for c in cols if c not in ("hour", key, "hall", "kind", "ups")]
    return {"device": device, "family": fam, "start": t.manifest["window"]["start"], "hours": len(rows),
            "series": {c: [float(r[c]) if "." in r[c] else int(r[c]) for r in rows] for c in keep}}


def power_markdown(f: dict) -> str:
    w = f["window"]
    L = ["# Power telemetry (Site AUS-1, synthetic)", "",
         f"{f['framing']} Window {day(w['start'])} to {day(w['end'])}: one read a minute of every UPS (SNMPv3 through its network "
         f"management card), every busway run and tap-off (the Starline M70 meter, SNMP), and every generator (the EMCP 4.4 controller, Modbus TCP). "
         "All names and readings are fictional; no vendor's internal tooling is implied.", "",
         "Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py", "",
         "The series are built from the bottom up: each rack's power (its GPUs from the GPU telemetry plus the rest of the rack) splits "
         "across its A and B tap-offs, the tap-offs add up to their busway run, and the runs add up to the UPS that feeds them. "
         "Each hall's UPS output equals its energy meter every hour.", "",
         "## Halls", "", "| Hall | UPSs | Racks on busway | IT load avg / peak kW | Design load (4-make-3) kW | One UPS out: each other UPS at the peak |",
         "|---|---|---:|---:|---:|---:|"]
    for h in f["halls"].values():
        L.append(f"| {h['name']} | {', '.join(h['ups'])} | {h['racks']} | {h['avg_kw']:,} / {h['peak_kw']:,} | {h['design_kw']:,.0f} | "
                 f"{h['one_down_pct']}% of {h['rating_kw']:,} kW |")
    L += ["", "## UPSs", "", "| UPS | Model | Output avg / peak kW | Load avg / peak % | Energy out / in MWh | Bypass min | On battery s | Lowest charge % |",
          "|---|---|---:|---:|---:|---:|---:|---:|"]
    for u in f["ups"]:
        L.append(f"| {u['id']} | {u['model']} | {u['out_avg_kw']:,} / {u['out_peak_kw']:,} | {u['load_avg']} / {u['load_peak']} | "
                 f"{u['out_mwh']:,} / {u['in_mwh']:,} | {u['bypass_min']} | {u['battery_s']} | {u['soc_min']} |")
    L += ["", "## Busway runs", "", f"Rated {f['rating_a']:,} A; with one feed lost a run may carry up to {f['busway_limit'] * 100:.0f}% of that.", "",
          "| Run | UPS | Racks | Energy MWh | Amps avg / peak | Peak if its partner feed failed A | Voltage min / max | Minutes without feed |",
          "|---|---|---|---:|---:|---:|---:|---:|"]
    for r in f["runs"]:
        L.append(f"| {r['id']} | {r['ups']} | {r['racks'][0]} to {r['racks'][-1]} | {r['mwh']} | {r['amps_avg']} / {r['amps_peak']} | "
                 f"{r['single_feed_peak_a']} | {r['v_min']} / {r['v_max']} | {r['dead_min']} |")
    L += ["", "## Generators", "", "| Generator | Minutes running | Energy MWh | Peak kW (% of rated) | Fuel at month end % | Hour meter at month end |",
          "|---|---:|---:|---:|---:|---:|"]
    for g in f["gens"]:
        L.append(f"| {g['id']} | {g['run_min']} | {g['mwh']} | {g['kw_max']:,} ({g['pct_max']}%) | {g['fuel_end']} | {g['hours_end']:,} |")
    L += ["", "## Events", "", "| From | To | Device | What | Records |", "|---|---|---|---|---|"]
    for e in f["events"]:
        refs = list(e["refs"]) + ([e["finding"]["id"]] if e.get("finding") else [])
        L.append(f"| {e['t']} | {e.get('end') or ''} | {e['device']} | {e['text']} | {', '.join(refs)} |")
    L += ["", "## Agreement with the records", "", "| Check | Agrees |", "|---|---:|"]
    for a in f["agreements"]:
        L.append(f"| {a['title']} | {a['checked'] - a['misses']:,} of {a['checked']:,} |")
    if f["misses"]:
        L += ["", "Disagreements:", ""] + [f"- {m}" for m in f["misses"]]
    L += ["", "## Sources", ""] + [f"- {s['name']}: {s['url']} (checked {s['checked']})" for s in f["sources"]]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- network
DATA_NET = ROOT / "data" / "telemetry" / "network"
OUT_NET = ROOT / "reports" / "network_telemetry.md"
SYM_POINTS = ("Symbol Error (110)", "Symbol Error (110), threshold")


def load_network() -> TN.NetData:
    h = hourly_dir()
    return TN.load(DATA_NET, h.parent / "network_hourly", SAMPLE, h)


def _tickets() -> list[dict]:
    d = json.loads((SAMPLE / "vendor" / "tickets.json").read_text(encoding="utf-8"))
    return d if isinstance(d, list) else d.get("tickets", [])


def _deploy_wo(rack: str, step: str = "DEP-B-RK-05") -> str | None:
    """The IT Partner's Jira sub-task for a Hall B rack's deployment step (R-M5: network cabled and verified)."""
    p = ROOT / "data" / "deployments" / "jira" / "RSS-DEP.json"
    if not p.exists():
        return None
    for i in json.loads(p.read_text(encoding="utf-8"))["issues"]:
        f = i["fields"]
        if f.get("customfield_10102") == rack and f.get("customfield_10103") == step:
            return i["key"]
    return None


def network_events(states: list[dict], dev: dict, findings: list[dict], recur_h: int) -> list[dict]:
    """The fabric's records summarized for a reader: each faulty link's episode with its tickets and what each repair
    did, each rack power loss across its links, each Hall B rack's cabling, and each NVLink tray failure."""
    out: list[dict] = []
    tickets = _tickets()
    by_link: dict[str, list[dict]] = {}
    for s in states:
        if s["family"] == "port" and s.get("cause") == "fault":
            by_link.setdefault(s["device"], []).append(s)
    for lid, sts in sorted(by_link.items()):
        sts.sort(key=lambda s: (s["time"], s["point"]))
        groups: list[list[dict]] = []
        for s in sts:
            if groups and (G.parse(s["time"]) - G.parse(groups[-1][-1]["time"])) <= timedelta(hours=recur_h):
                groups[-1].append(s)
            else:
                groups.append([s])
        d = dev[lid]
        for g in groups:
            sym = [s for s in g if s["point"] in SYM_POINTS]
            downs = [s for s in g if s["point"].startswith("Link is Down")]
            fixes = [s for s in g if s["point"].startswith("Optic (")]
            parts = []
            if downs:
                parts.append(f"link dropped {len(downs)} time{'s' * (len(downs) > 1)}")
            if sym:
                thr = sum(1 for s in sym if s["point"].endswith("threshold"))
                parts.append(f"{len(sym)} symbol-error report{'s' * (len(sym) > 1)}, {sum(int(s['value']) for s in sym):,} errors"
                             + (f" (over the UFM threshold {thr} time{'s' * (thr > 1)})" if thr else ""))
            refs = []
            for f in fixes:
                tk = f["point"][len("Optic ("):-1]
                refs.append(tk)
                after = [s for s in g if s["time"] > f["time"] and (s["point"] in SYM_POINTS or s["point"].startswith("Link is Down"))]
                parts.append(f"{f['value']} ({tk}), {'errors continued' if after else 'errors stopped'}")
            # a ticket opened on the link before its first repair note (or without one) still belongs to the episode
            a, b = G.parse(g[0]["time"]), G.parse(g[-1]["time"])
            for x in tickets:
                if x["category"] == "optic_link" and x["short_description"].endswith(" <-> " + lid) and x["number"] not in refs \
                        and a - timedelta(hours=2) <= G.parse(x["opened_at"]) <= b + timedelta(hours=2):
                    refs.append(x["number"])
            if not fixes:
                parts.append("no repair on record this month" if not refs else "no part replaced")
            text = "; ".join(parts)
            fs = [f for f in findings if lid in json.dumps(f["evidence"]) or any(r in json.dumps(f["evidence"]) for r in refs)]
            out.append({"t": g[0]["time"], "end": g[-1]["time"] if len(g) > 1 else None, "device": lid, "family": "port", "kind": "optic",
                        "host": d["peer_host"], "rack": d["rack"], "text": text[0].upper() + text[1:], "refs": refs,
                        "findings": [{"id": f["id"], "title": f["title"]} for f in fs], "m": g[0]["m"]})
    for cause, kind in (("rack power lost", "power"), ("cabled", "cabled")):
        racks: dict[str, list[dict]] = {}
        for s in states:
            if s["family"] == "port" and s.get("cause") == cause:
                racks.setdefault(dev[s["device"]]["rack"], []).append(s)
        for rack, sts in sorted(racks.items()):
            sts.sort(key=lambda s: s["time"])
            links = sorted({s["device"] for s in sts})
            if kind == "power":
                dn = [s for s in sts if s["point"].startswith("Link is Down")]
                up = [s for s in sts if s["point"].startswith("Link is Up")]
                refs = [x["number"] for x in tickets if x["category"] == "rack_facility" and x.get("rack") == rack
                        and abs((G.parse(x["opened_at"]) - G.parse(sts[0]["time"])).total_seconds()) <= 3 * 3600]
                refs += [w["wo"] for w in _work_orders() if w.get("unit") == f"Rack {rack}" and w.get("opened")
                         and abs((G.parse(w["opened"]) - G.parse(sts[0]["time"])).total_seconds()) <= 3 * 3600]
                text = (f"Rack {rack} lost input power: its {len(links)} back-end links went down within "
                        f"{(G.parse(dn[-1]['time']) - G.parse(dn[0]['time'])).total_seconds():.0f} s (the trays' NICs lost power, so the "
                        f"fabric logged Link is Down on every port), and came back as the trays booted after power returned")
                out.append({"t": dn[0]["time"], "end": up[-1]["time"] if up else None, "device": rack, "family": "rack", "kind": kind,
                            "rack": rack, "links": len(links), "text": text, "refs": refs, "findings": [], "m": sts[0]["m"]})
            else:
                wo = _deploy_wo(rack)
                out.append({"t": sts[0]["time"], "end": sts[-1]["time"], "device": rack, "family": "rack", "kind": kind, "rack": rack,
                            "links": len(links), "text": f"Rack {rack} cabled: {len(links)} back-end links came up one tray at a time "
                                                          f"(Link is Up, 4 rails per tray)", "refs": [], "deploy": wo, "findings": [], "m": sts[0]["m"]})
    since: dict[str, dict] = {}
    for s in states:
        if s["family"] != "nvlink":
            continue
        if s["value"] == "failed":
            since[s["device"]] = s
        elif s["device"] in since:
            a = since.pop(s["device"])
            refs = [x["number"] for x in tickets if x["category"] == "switch_tray" and x["configuration_item"].endswith(s["device"])
                    and abs((G.parse(x["opened_at"]) - G.parse(a["time"])).total_seconds()) <= 3600]
            mins = (G.parse(s["time"]) - G.parse(a["time"])).total_seconds() / 60
            out.append({"t": a["time"], "end": s["time"], "device": s["device"], "family": "nvlink", "kind": "nvlink", "rack": s["device"][:3].upper(),
                        "text": f"NVLink switch tray unreachable for {mins:.0f} min (NMX: domain degraded); the rack's other trays carried its share",
                        "refs": refs, "findings": [], "m": a["m"]})
    return sorted(out, key=lambda e: (e["t"], e["device"]))


def prepare_network(t: TN.NetData | None = None) -> dict:
    cfg = TNS.load_config()
    t = t or load_network()
    from scorecard import devices as DV
    checks = TN.agreements(t, cfg, DV.load())
    dev, H = t.manifest["devices"], t.H
    states = _jsonl(DATA_NET / "states.jsonl") if t.dir == DATA_NET else _jsonl(t.dir / "states.jsonl")
    findings = json.loads((ROOT / "reports" / "findings.json").read_text(encoding="utf-8"))["findings"]
    events = network_events(states, dev, findings, cfg["checks"]["recur_hours"])
    flagged = {e["device"] for e in events if e["family"] == "port"}
    leaves = []
    for name, x in sorted(t.devices("leaf").items()):
        L = t.leaf(name)
        ports = L["ports"]
        sym = sum(int(TN.unpack(p["sym"]).sum()) for p in ports.values())
        downs = sum(int(TN.unpack(p["downs"]).sum()) for p in ports.values())
        up_min = [TN.unpack(p["up_min"]) for p in ports.values()]
        asic, pw = TN.unpack(L["chassis"]["asic_c"]), TN.unpack(L["chassis"]["power_w"])
        lids = [f"{name}:swp{p}" for p in x["ports"]]
        leaves.append({"id": name, "hall": x["hall"], "rail": x["rail"], "product": x["product"], "gbps": x["gbps"], "uplinks": x["uplinks"],
                       "racks": sorted({dev[lid]["rack"] for lid in lids}), "ports": len(lids),
                       "cabled_end": sum(1 for u in up_min if u[-1] > 0), "cabled_start": sum(1 for lid in lids if dev[lid]["cabled_at_start"]),
                       "tx_pb": round(sum(p["tx_words"] for p in ports.values()) * 4 / 1e15, 1), "sym": sym, "downs": downs,
                       "flagged": sorted((lid for lid in lids if lid in flagged), key=lambda s: int(s.split("swp")[1])),
                       "asic_max": int(asic.max()), "power_avg_w": int(round(float(pw.mean())))})
    halls = {}
    site = S.load_site()
    for h in site["halls"]:
        rows = [r for r in t.fabric_hourly if r["hall"] == h["id"]]
        if not rows:
            continue
        lv = [x for x in leaves if x["hall"] == h["id"]]
        series = {k: [0.0] * H for k in ("tx_tb", "links_up", "links_cabled", "symbol_errors", "link_downs", "switch_kw")}
        for r in rows:
            i = int((G.parse(r["hour"]) - t.start).total_seconds() // 3600)
            for k in series:
                series[k][i] += float(r[k])
        series["tx_pb"] = [v / 1000 for v in series.pop("tx_tb")]
        for k in series:
            series[k] = [round(v, 2) for v in series[k]]
        prod = cfg["products"][lv[0]["product"]]
        halls[h["id"]] = {"name": h["name"], "state": h["state"], "product": lv[0]["product"], "model": prod["model"], "gbps": prod["gbps"],
                          "leaves": len(lv), "links": sum(x["ports"] for x in lv), "cabled_start": sum(x["cabled_start"] for x in lv),
                          "cabled_end": sum(x["cabled_end"] for x in lv), "racks": len({r for x in lv for r in x["racks"]}),
                          "tx_pb": round(sum(x["tx_pb"] for x in lv), 1), "sym": sum(x["sym"] for x in lv), "downs": sum(x["downs"] for x in lv),
                          "switch_kw": round(sum(series["switch_kw"]) / H, 1), "hourly": series}
    nv: dict[str, dict] = {}
    for r in t.nvlink_hourly:
        x = nv.setdefault(r["rack"], {"rack": r["rack"], "hall": r["hall"], "tx_tb": 0.0, "asic_max": 0, "tray_minutes": 0, "hours_reporting": 0})
        x["tx_tb"] += float(r["tx_tb"])
        x["tray_minutes"] += int(r["tray_minutes"])
        x["hours_reporting"] += int(r["trays_reporting"]) > 0
        if r["asic_c_max"] != "":
            x["asic_max"] = max(x["asic_max"], int(r["asic_c_max"]))
    for x in nv.values():
        x["tx_tb"] = round(x["tx_tb"], 1)
        x["trays"] = sorted(k for k, d in dev.items() if d["family"] == "nvlink" and d["rack"] == x["rack"])
    return {"framing": cfg["framing"], "sources": cfg["sources"], "collection": cfg["collection"], "fields": cfg["fields"],
            "products": {k: {f: v[f] for f in ("model", "os", "speed", "gbps", "ports", "cages", "uplinks", "port_name", "fec", "host_nic") if f in v}
                         for k, v in cfg["products"].items()},
            "thresholds": cfg["optics"]["thresholds"], "warn_rx_dbm": cfg["optics"]["warn_rx_dbm"], "symbol_threshold": cfg["ufm_events"]["symbol_errors"]["threshold"],
            "symbol_report_min": cfg["symbol_report_min"],
            "window": t.manifest["window"], "hours": H, "halls": halls, "leaves": leaves, "nvlink": [nv[k] for k in sorted(nv, key=_rk)],
            "events": events, "windows": t.manifest["windows"],
            "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks],
            "misses": [m for c in checks for m in c.misses][:20]}


def leaf_json(t: TN.NetData, leaf: str) -> dict:
    """The publish-time leaf file plus each port's identity from the manifest (what the leaf and port views read)."""
    L = dict(t.leaf(leaf))
    dev = t.manifest["devices"]
    L["ports"] = {p: {**x, **{k: v for k, v in dev[f"{leaf}:swp{p}"].items() if k not in ("family", "leaf", "hall")}} for p, x in L["ports"].items()}
    L["node_guid"] = dev[leaf]["node_guid"]
    return L


def network_markdown(f: dict) -> str:
    w = f["window"]
    L = ["# Network telemetry (Site AUS-1, synthetic)", "",
         f"{f['framing']} Window {day(w['start'])} to {day(w['end'])}: every back-end InfiniBand leaf port read once a minute "
         "through the fabric manager's telemetry (UFM Telemetry, Prometheus endpoint), the tray end of each link through node_exporter, "
         "each leaf's chassis over SNMP (Quantum-2) or gNMI (Quantum-X800), and each NVL72 rack's NVLink switch trays through NMX-T. "
         "All names and readings are fictional; no vendor's internal tooling is implied.", "",
         "Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py", "",
         "Each GPU's tray has one link per rail to that rail's leaf (rail-optimized); a link carries traffic only while its tray's GPUs "
         "report and the link is up, and every fabric event, ticket, and device-directory connection agrees with the counters.", "",
         "## Halls", "", "| Hall | Leaf switch | Leaves | Racks | Links cabled (start / end) | Data sent PB | Symbol errors | Link drops | Leaf power avg kW |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for h in f["halls"].values():
        L.append(f"| {h['name']} | {h['model']} ({h['gbps']}G) | {h['leaves']} | {h['racks']} | {h['cabled_start']:,} / {h['cabled_end']:,} of {h['links']:,} | "
                 f"{h['tx_pb']:,} | {h['sym']:,} | {h['downs']:,} | {h['switch_kw']:,} |")
    L += ["", "## Leaf switches", "", "| Leaf | Rail | Racks | Links cabled | Data sent PB | Symbol errors | Link drops | ASIC max °C | Power avg W | Links with records |",
          "|---|---:|---|---:|---:|---:|---:|---:|---:|---|"]
    for x in f["leaves"]:
        L.append(f"| {x['id']} | {x['rail']} | {', '.join(x['racks'])} | {x['cabled_end']} of {x['ports']} | {x['tx_pb']:,} | {x['sym']:,} | {x['downs']:,} | "
                 f"{x['asic_max']} | {x['power_avg_w']:,} | {', '.join(s.split(':')[1] for s in x['flagged'])} |")
    L += ["", "## NVLink switch trays (per rack)", "", "| Rack | Trays | Data sent PB | Tray-minutes reporting | ASIC max °C |", "|---|---:|---:|---:|---:|"]
    for x in f["nvlink"]:
        L.append(f"| {x['rack']} | {len(x['trays'])} | {x['tx_tb'] / 1000:,.1f} | {x['tray_minutes']:,} | {x['asic_max']} |")
    L += ["", "## Events", "", "| From | To | Where | What | Records |", "|---|---|---|---|---|"]
    for e in f["events"]:
        refs = list(e["refs"]) + ([e["deploy"]] if e.get("deploy") else []) + [x["id"] for x in e["findings"]]
        L.append(f"| {e['t']} | {e.get('end') or ''} | {e['device']} | {e['text']} | {', '.join(refs)} |")
    L += ["", "## Agreement with the records", "", "| Check | Agrees |", "|---|---:|"]
    for a in f["agreements"]:
        L.append(f"| {a['title']} | {a['checked'] - a['misses']:,} of {a['checked']:,} |")
    if f["misses"]:
        L += ["", "Disagreements:", ""] + [f"- {m}" for m in f["misses"]]
    L += ["", "## Sources", ""] + [f"- {s['name']}: {s['url']} (checked {s['checked']})" for s in f["sources"]]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- mechanical
DATA_MECH = ROOT / "data" / "telemetry" / "mechanical"
OUT_MECH = ROOT / "reports" / "mechanical_telemetry.md"
# Chiller modes for the plant heatmap, one code per chiller-hour
MODES = {0: "Standby", 1: "Compressors only", 2: "Free cooling with compressors", 3: "Free cooling only", 4: "Tripped (Alarm Off)",
         5: "Held off by the BMS"}


def load_mech() -> TMM.MechData:
    return TMM.load(DATA_MECH, hourly_dir().parent / "mechanical_minutes", SAMPLE, ENERGY, DATA_CDU, DATA_POWER)


def chiller_mode(r: dict) -> int:
    """The hour's mode: a trip or a BMS hold first, then how the running chiller carried its load."""
    if int(r["alarm_min"]):
        return 4
    if int(r["bms_off_min"]):
        return 5
    if not int(r["run_min"]):
        return 0
    fc, mech = float(r["fc_kwh"]), float(r["mech_kwh"])
    return 3 if fc > 0 and mech == 0 else 2 if fc > 0 else 1


def _dur(a: int, b: int) -> str:
    n = b - a
    return f"{n} min" if n < 120 else f"{n / 60:.1f} h" if n < 48 * 60 else f"{n / 1440:.1f} days"


def mechanical_events(t: TMM.MechData, cfg: dict) -> list[dict]:
    """Each record span the telemetry carries, with what the readings show over it and the records that explain it."""
    spans = TMM.record_spans(t)
    lfind = {f["unit"]: f for f in json.loads((ROOT / "reports" / "landlord_findings.json").read_text(encoding="utf-8"))}
    from scorecard import energy as N
    from scorecard.synthetic.energy import load_config as energy_config
    efind = N.analyse(N.load(), energy_config()).findings if t.dir == DATA_MECH else []
    wo_outage = next((w["wo"] for w in _work_orders() if w.get("unit") == "138 kV utility service"), None)
    chillers = t.devices("chiller")
    stat = {v: k for k, v in cfg["chiller"]["unit_status"].items()}
    out: list[dict] = []
    at: dict[tuple[str, int], str] = {}
    for s in t.states:
        at.setdefault((s["device"], s["m"]), s["time"])

    def add(dev: str, fam: str, kind: str, a: int, b: int, text: str, refs: list[str], finding: dict | None = None) -> None:
        f = {"id": finding["id"], "title": finding["title"], "summary": finding.get("summary", "")} if finding else None
        out.append({"t": at.get((dev, a), _iso(t, a)), "end": at.get((dev, b), _iso(t, b)) if b < t.M else None, "device": dev,
                    "family": fam, "kind": kind,
                    "text": text, "refs": list(dict.fromkeys(r for r in refs if r)), "finding": f, "m": a})

    def lf(dev: str, refs: list[str]) -> dict | None:
        f = lfind.get(dev)
        return f if f and (not f.get("tickets") or any(r in refs for r in f["tickets"]) or dev.startswith("TW-")) else None

    for dev in chillers:
        sp, f = spans.get(dev, {}), t.minutes(dev)
        for a, b, _ in sp.get("trip", []):
            started = [c for c in chillers if c != dev and any(
                int(t.minutes(c)["status"][m]) == stat["Local On"] and int(t.minutes(c)["status"][m - 1]) != stat["Local On"]
                for m in range(max(1, a), min(t.M, a + 6)))]
            hp = int(f["hp1_bar"][max(0, a - 1)]) / 10
            refs = _power_refs(dev, [dev], _iso(t, a), _iso(t, b))
            add(dev, "chiller", "trip", a, b,
                f"Compressor trip: circuit 1 condensing pressure reached {hp:.1f} bar and BV 35 (High Condensing Pressure) went active; "
                f"the unit read Alarm Off for {_dur(a, b)}" + (f", and {', '.join(started)} started to carry its load" if started else ""),
                refs, lf(dev, refs))
        for a, b, rec in sp.get("off", []):
            refs = [rec.get("change_ref", "")] + _power_refs(dev, [dev], _iso(t, a), _iso(t, b))
            add(dev, "chiller", "hold", a, b, f"BMS hold: Chiller enable written Off at priority 8 (Manual Operator) for {_dur(a, b)}; "
                f"the unit read BMS Off with no load while the other chillers carried the plant, then the write was relinquished", refs)
        for a, b, rec in sp.get("fan100", []):
            add(dev, "chiller", "fan100", a, b, f"Condenser fan override: the BMS held the condenser fans at 100% for {_dur(a, b)}",
                [rec.get("change_ref", "")])
        for a, b, rec in sp.get("lock", []):
            ran = f["cap_kw"][a:b] > 0
            others = np.zeros(b - a, dtype=bool)
            for c in chillers:
                if c != dev:
                    others |= t.minutes(c)["fc"][a:b] == 1
            both = int((ran & others).sum())
            note = rec.get("note", "")
            refs = re.findall(r"\bPM-\d+\b", note)
            fi = next((x for x in efind if dev in x.title and "ree cooling" in x.title), None)
            add(dev, "chiller", "lockout", a, b,
                f"Free cooling inhibited (Stop or Inhibit FC activation = 1) for {_dur(a, b)}: the chiller ran {int(ran.sum()) / 60:.0f} h "
                f"on its compressors only" + (f", {both / 60:.0f} h of them while the other running chillers were free cooling" if both >= 60
                                                 else ", and the weather allowed little free cooling on the others meanwhile"),
                refs, {"id": fi.id, "title": fi.title} if fi else None)
    for dev in t.devices("wall") + t.devices("crah"):
        sp, f = spans.get(dev, {}), t.minutes(dev)
        fam = t.manifest["devices"][dev]["family"]
        for a, b, fan in sp.get("fan", []):
            refs = _power_refs(dev, [dev], _iso(t, a), _iso(t, b))
            add(dev, fam, "fan", a, b, f"Fan {fan} failed (FanSts_OV[{fan}] Alarm, Al_EvpFan active) for {_dur(a, b)}: the other five ran at "
                f"up to {int(f['fan_pct'][a:b].max())}% and held supply air at up to {int(f['sup_c'][a:b].max()) / 100:.1f} C", refs)
        for a, b, rec in sp.get("inhibit", []):
            hi = cfg["air"]["high_supply_c"]
            add(dev, fam, "inhibit", a, b,
                f"High supply temperature alarm inhibited (Event_Algorithm_Inhibit TRUE) for {_dur(a, b)} with no change record: supply air "
                f"read {int(f['sup_c'][a:b].min()) / 100:.1f} to {int(f['sup_c'][a:b].max()) / 100:.1f} C over the span, under the "
                f"{hi:.0f} C limit, so the inhibit hid no excursion", [rec.get("change_ref", "")], lf(dev, []))
    pf = stat["Power Failure"]
    for s in (x for x in t.states if x["device"] == "SITE" and x["value"].startswith("Trip")):
        a = s["m"]
        hit = [c for c in chillers if (t.minutes(c)["status"][a:a + 30] == pf).any()]
        if not hit:
            continue
        full = [int(t.minutes(c)["cap_kw"][a - 1]) for c in hit]
        back = max(next(i for i in range(1, 60) if int(t.minutes(c)["cap_kw"][a + i]) >= 0.95 * v) for c, v in zip(hit, full)) + 1
        sup = t.minutes("FW-LOOP")["supply_c"]
        rise = (int(sup[a:a + 20].max()) - int(sup[a - 5:a].mean())) / 100
        add("SITE", "site", "outage", a, a + back,
            f"Utility outage: the {len(hit)} running chillers read Power Failure until the generators carried the plant, and Quick Start "
            f"had them back to full capacity {back} min later; meanwhile the water in the loop took the heat, and the supply header "
            f"warmed {rise:.1f} C and recovered", [wo_outage] if wo_outage else [])
    return sorted(out, key=lambda e: (e["t"], e["device"]))


def _iso(t: TMM.MechData, m: int) -> str:
    return (t.start + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")


def prepare_mechanical(t: TMM.MechData | None = None) -> dict:
    from scorecard.synthetic.energy import load_config as energy_config
    cfg, ecfg = TMS.load_config(), energy_config()
    t = t or load_mech()
    site = S.load_site()
    checks = TMM.agreements(t, cfg, ecfg, site)
    H = t.M // 60
    fl = lambda rows, k: [float(r[k]) for r in rows]          # noqa: E731
    by = lambda rows, key: {k: [r for r in rows if r[key] == k] for k in dict.fromkeys(r[key] for r in rows)}   # noqa: E731
    met = [t.meters[t.hour(k)] for k in range(H)]
    loop = t.loop_hourly
    chs = by(t.chiller_hourly, "chiller")
    chillers = []
    for c, rows in chs.items():
        run = sum(int(r["run_min"]) for r in rows)
        kwh, cap = sum(fl(rows, "kwh")), sum(fl(rows, "cap_kwh"))
        chillers.append({"id": c, "run_h": round(run / 60, 1), "fc_h": round(sum(int(r["fc_min"]) for r in rows) / 60, 1),
                         "mwh": round(kwh / 1000, 1), "cap_mwh": round(cap / 1000, 1), "cop": round(cap / kwh, 2) if kwh else None,
                         "fc_share": round(100 * sum(fl(rows, "fc_kwh")) / cap, 1) if cap else 0,
                         "alarm_min": sum(int(r["alarm_min"]) for r in rows), "off_min": sum(int(r["bms_off_min"]) for r in rows),
                         "inhibit_h": round(sum(int(r["inhibit_min"]) for r in rows) / 60, 1),
                         "hp_max": max(fl(rows, "hp_max_bar")), "mode": "".join(str(chiller_mode(r)) for r in rows),
                         "inhibit": "".join("1" if int(r["inhibit_min"]) else "0" for r in rows)})
    pumps = []
    for p, rows in by(t.pump_hourly, "pump").items():
        runs = [r for r in rows if int(r["run_min"])]
        pumps.append({"id": p, "run_h": round(sum(int(r["run_min"]) for r in rows) / 60, 1), "mwh": round(sum(fl(rows, "kwh")) / 1000, 1),
                      "speed_avg": round(sum(fl(runs, "speed_pct")) / len(runs), 1) if runs else 0,
                      "flow_avg": round(sum(fl(runs, "flow_lps")) / len(runs), 1) if runs else 0})
    air = []
    for u, rows in by(t.air_hourly, "unit").items():
        air.append({"id": u, "hall": rows[0]["hall"], "kind": rows[0]["kind"], "sup_avg": round(sum(fl(rows, "sup_c")) / H, 2),
                    "sup_max": max(fl(rows, "sup_max_c")), "ret_avg": round(sum(fl(rows, "ret_c")) / H, 2),
                    "fan_avg": round(sum(fl(rows, "fan_pct")) / H, 1), "load_avg_kw": round(sum(fl(rows, "load_kwh")) / H, 1),
                    "kw_avg": round(sum(fl(rows, "kwh")) / H, 2), "mwh": round(sum(fl(rows, "kwh")) / 1000, 2),
                    "fans_min": min(int(r["fans_min"]) for r in rows), "alarm_min": sum(int(r["alarm_min"]) for r in rows),
                    "inhibit_h": round(sum(int(r["inhibit_min"]) for r in rows) / 60, 1)})
    halls = {}
    for h in site["halls"]:
        mine = [a for a in air if a["hall"] == h["id"]]
        c = h["cooling"]
        halls[h["id"]] = {"name": h["name"], "state": h["state"], "walls": [a["id"] for a in mine if a["kind"] == "wall"],
                          "crahs": [a["id"] for a in mine if a["kind"] == "crah"],
                          "wall_count": c.get("thermal_wall_count", 0), "crah_count": c.get("electrical_room_crah_count", 0),
                          "wall_load_kw": round(sum(a["load_avg_kw"] for a in mine if a["kind"] == "wall"), 1),
                          "wall_kw": round(sum(a["kw_avg"] for a in mine if a["kind"] == "wall"), 1)}
    events = mechanical_events(t, cfg)
    afc = S.product(site, "liebert_afc_1500")
    return {"framing": cfg["framing"], "sources": cfg["sources"], "collection": cfg["collection"], "objects": cfg["objects"],
            "enums": {"chiller_status": {str(k): v for k, v in cfg["chiller"]["unit_status"].items()},
                      "compressor": {str(k): v for k, v in cfg["chiller"]["compressor_status"].items()},
                      "air_status": {str(k): v for k, v in cfg["air"]["unit_status"].items()},
                      "fan_status": {str(k): v for k, v in cfg["air"]["fan_status"].items()}},
            "modes": {str(k): v for k, v in MODES.items()}, "window": t.manifest["window"], "hours": H,
            "limits": {"hp_alarm_bar": cfg["chiller"]["hp_alarm_bar"], "high_supply_c": cfg["air"]["high_supply_c"],
                       "supply_setpoint_c": cfg["air"]["supply_setpoint_c"], "chw_setpoint_c": cfg["chiller"]["setpoint_c"],
                       "dp_setpoint_kpa": cfg["pump"]["dp_setpoint_kpa"], "fans_per_wall": cfg["air"]["fans_per_wall"]},
            "free_cooling_c": [ecfg["plant"]["free_cooling_full_below_c"], ecfg["plant"]["free_cooling_none_above_c"]],
            "chiller_model": afc["model"], "chiller_kw": afc["capacity_kw"], "refrigerant": cfg["chiller"]["refrigerant"],
            "plant": {"outdoor": [float(m["outdoor_c"]) for m in met], "supply": fl(loop, "supply_c"), "return": fl(loop, "return_c"),
                      "flow": fl(loop, "flow_lps"), "heat": fl(loop, "heat_kwh"), "running": [int(r["chillers_running"]) for r in loop],
                      "needed": [int(r["chillers_needed"]) for r in loop], "dp": fl(loop, "dp_kpa"),
                      "chillers_kw": [float(m["chillers_kwh"]) for m in met], "pumps_kw": [float(m["pumps_kwh"]) for m in met]},
            "chillers": chillers, "pumps": pumps, "air": air, "halls": halls, "events": events, "windows": t.manifest["windows"],
            "loop": {"supply_avg": round(sum(fl(loop, "supply_c")) / H, 2), "return_avg": round(sum(fl(loop, "return_c")) / H, 2),
                     "flow_avg": round(sum(fl(loop, "flow_lps")) / H, 1), "flow_peak": max(fl(loop, "flow_lps")),
                     "heat_mwh": round(sum(fl(loop, "heat_kwh")) / 1000, 1), "heat_peak_kw": max(fl(loop, "heat_kwh")),
                     "running_max": max(int(r["chillers_running"]) for r in loop), "running_min": min(int(r["chillers_running"]) for r in loop),
                     "chillers_mwh": round(sum(float(m["chillers_kwh"]) for m in met) / 1000, 1),
                     "pumps_mwh": round(sum(float(m["pumps_kwh"]) for m in met) / 1000, 1)},
            "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks],
            "misses": [m for c in checks for m in c.misses][:20]}


def mech_json(t: TMM.MechData, device: str) -> dict:
    """One machine's month by hour (from the committed hourly tables): what its view charts."""
    fam = t.manifest["devices"][device]["family"]
    table, key, cols = {"chiller": (t.chiller_hourly, "chiller", TMS.CHILLER_HOURLY), "pump": (t.pump_hourly, "pump", TMS.PUMP_HOURLY),
                        "loop": (t.loop_hourly, None, TMS.LOOP_HOURLY), "wall": (t.air_hourly, "unit", TMS.AIR_HOURLY),
                        "crah": (t.air_hourly, "unit", TMS.AIR_HOURLY)}[fam]
    rows = [r for r in table if key is None or r[key] == device]
    keep = [c for c in cols if c not in ("hour", "chiller", "pump", "unit", "hall", "kind")]
    num = lambda v: v if not re.fullmatch(r"-?\d+(\.\d+)?", v) else float(v) if "." in v else int(v)    # noqa: E731
    return {"device": device, "family": fam, "start": t.manifest["window"]["start"], "hours": len(rows),
            "series": {c: [num(r[c]) for r in rows] for c in keep}}


def mechanical_markdown(f: dict) -> str:
    w, lp = f["window"], f["loop"]
    L = ["# Mechanical telemetry (Site AUS-1, synthetic)", "",
         f"{f['framing']} Window {day(w['start'])} to {day(w['end'])}: one read a minute of every chiller, facility water pump, the "
         "facility water loop, every thermal wall, and every electrical-room CRAH, over BACnet/IP from the Landlord's BMS server. "
         "All names and readings are fictional; no vendor's internal tooling is implied.", "",
         "Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py", "",
         "The series split the hourly energy meters into each machine. Each hall's thermal walls carry the heat its CDUs do not "
         "(the racks' air-side heat), and their fans plus the CDUs' pumps are that hall's mechanical UPS load. The chillers "
         "carry everything the plant rejects, staged by load with a weekly lead rotation.", "",
         "## Plant", "", "| Measure | Value |", "|---|---|",
         f"| Chillers | {len(f['chillers'])} x {f['chiller_model']} ({f['refrigerant']}) |",
         f"| Running | {lp['running_min']} to {lp['running_max']} at once |",
         f"| Facility water supply / return, mean | {lp['supply_avg']} C / {lp['return_avg']} C |",
         f"| Loop flow, mean / peak | {lp['flow_avg']} / {lp['flow_peak']} L/s |",
         f"| Heat rejected | {lp['heat_mwh']:,} MWh (peak {lp['heat_peak_kw']:,.0f} kW) |",
         f"| Chiller energy | {lp['chillers_mwh']:,} MWh |", f"| Pump energy | {lp['pumps_mwh']:,} MWh |", "",
         "## Chillers", "", "| Chiller | Running h | Free cooling h | Energy MWh | Heat MWh | Heat per kWh | Free-cooling share | "
         "Highest condensing bar | Tripped min | Held off min | FC inhibited h |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for c in f["chillers"]:
        L.append(f"| {c['id']} | {c['run_h']} | {c['fc_h']} | {c['mwh']} | {c['cap_mwh']} | {c['cop'] if c['cop'] else ''} | {c['fc_share']}% | "
                 f"{c['hp_max']} | {c['alarm_min']} | {c['off_min']} | {c['inhibit_h']} |")
    L += ["", "## Facility water pumps", "", "| Pump | Running h | Energy MWh | Speed when running % | Flow when running L/s |", "|---|---:|---:|---:|---:|"]
    for p in f["pumps"]:
        L.append(f"| {p['id']} | {p['run_h']} | {p['mwh']} | {p['speed_avg']} | {p['flow_avg']} |")
    L += ["", "## Thermal walls and CRAHs", "", "| Unit | Hall | Supply air mean / max C | Return air mean C | Fan speed mean % | "
          "Cooling mean kW | Draw mean kW | Fewest fans running | Fan alarm min | Alarm inhibited h |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for a in f["air"]:
        L.append(f"| {a['id']} | {f['halls'][a['hall']]['name']} | {a['sup_avg']} / {a['sup_max']} | {a['ret_avg']} | {a['fan_avg']} | "
                 f"{a['load_avg_kw']} | {a['kw_avg']} | {a['fans_min']} | {a['alarm_min']} | {a['inhibit_h']} |")
    L += ["", "## Events", "", "| From | To | Device | What | Records |", "|---|---|---|---|---|"]
    for e in f["events"]:
        refs = list(e["refs"]) + ([e["finding"]["id"]] if e.get("finding") else [])
        L.append(f"| {e['t']} | {e.get('end') or ''} | {e['device']} | {e['text']} | {', '.join(refs)} |")
    L += ["", "## Agreement with the records", "", "| Check | Agrees |", "|---|---:|"]
    for a in f["agreements"]:
        L.append(f"| {a['title']} | {a['checked'] - a['misses']:,} of {a['checked']:,} |")
    if f["misses"]:
        L += ["", "Disagreements:", ""] + [f"- {m}" for m in f["misses"]]
    L += ["", "## Sources", ""] + [f"- {s['name']}: {s['url']} (checked {s['checked']})" for s in f["sources"]]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- management network
DATA_MGMT = ROOT / "data" / "telemetry" / "mgmt"
OUT_MGMT = ROOT / "reports" / "management_telemetry.md"
def _pct(polls: int, failed: int) -> float | None:
    """Polls answered, to 0.001%, rounded down so a month with any failure never reads 100%."""
    return math.floor(100000 * (polls - failed) / polls) / 1000 if polls else None


MGMT_KIND = {"compute": "Compute tray BMCs", "switch": "NVLink switch tray BMCs", "shelf": "Power shelf controllers"}


def load_mgmt() -> TG.MgmtData:
    return TG.load(DATA_MGMT, SAMPLE)


def prepare_mgmt(t: TG.MgmtData | None = None) -> dict:
    cfg = TGS.load_config()
    t = t or load_mgmt()
    checks = TG.agreements(t, cfg)
    fs = TG.findings(t, cfg)
    events = TG.events(t, cfg, fs)
    devs = t.manifest["devices"]
    H = t.M // 60
    racks = []
    by_rack: dict[str, list[dict]] = {}
    for r in t.bmc_hourly:
        by_rack.setdefault(r["rack"], []).append(r)
    gaps_by: dict[str, int] = {}
    for g in t.gaps:
        if (g["minutes"] or 0) > cfg["checks"]["gap_min"]:
            gaps_by[devs[g["endpoint"]]["rack"]] = gaps_by.get(devs[g["endpoint"]]["rack"], 0) + 1
    sw_rows: dict[str, list[dict]] = {}
    for r in t.switch_hourly:
        sw_rows.setdefault(r["switch"], []).append(r)
    up_h = lambda s: round(sum(int(r["up_min"]) for r in sw_rows[s]) / 60, 1)   # noqa: E731
    for rid, rows in sorted(by_rack.items(), key=lambda kv: _rk(kv[0])):
        polls = sum(int(r["endpoints"]) * int(r["polled_min"]) for r in rows)
        fail = sum(int(r["failed_polls"]) for r in rows)
        eps = [n for n, x in devs.items() if x["family"] == "bmc" and x["rack"] == rid]
        firsts = [t.first[n] for n in eps if n in t.first and t.first[n]]
        racks.append({"rack": rid, "hall": devs[eps[0]]["hall"], "endpoints": len(eps),
                      "kinds": {k: sum(1 for n in eps if devs[n]["kind"] == k) for k in MGMT_KIND},
                      "in_service_from": min(firsts) if firsts else None, "never": sum(1 for n in eps if n in t.first and not t.first[n]),
                      "polls": polls, "failed": fail, "answered_pct": _pct(polls, fail),
                      "gaps": gaps_by.get(rid, 0), "mgmt1_up_h": up_h(f"{rid.lower()}-mgmt1"), "mgmt2_up_h": up_h(f"{rid.lower()}-mgmt2"),
                      "answering": [int(r["answering_min"]) if r["answering_min"] != "" else None for r in rows],
                      "in_service": [int(r["endpoints"]) for r in rows]})
    switches = []
    for s in t.devices("rack") + t.devices("agg") + t.devices("console"):
        x, rows = devs[s], sw_rows.get(s, [])
        temps = [float(r["temp_c"]) for r in rows if r["temp_c"] != ""]
        switches.append({"id": s, "family": x["family"], "role": x.get("role"), "rack": x.get("rack"), "hall": x["hall"],
                         "ports": len(x["ports"]), "up_h": up_h(s) if rows else None, "temp_max": max(temps) if temps else None,
                         "console": x.get("console"), "leaves": x.get("leaves") or []})
    halls = {}
    for h in S.load_site()["halls"]:
        rk = [r for r in racks if r["hall"] == h["id"]]
        if not rk:
            continue
        mg = h.get("management") or {}
        polls, fail = sum(r["polls"] for r in rk), sum(r["failed"] for r in rk)
        answering = [sum((r["answering"][i] or 0) for r in rk) for i in range(H)]
        halls[h["id"]] = {"name": h["name"], "state": h["state"], "racks": len(rk), "endpoints": sum(r["endpoints"] for r in rk),
                          "switches": sum(1 for s in switches if s["hall"] == h["id"] and s["family"] == "rack"),
                          "aggs": [s["id"] for s in switches if s["hall"] == h["id"] and s["family"] == "agg"],
                          "consoles": [s["id"] for s in switches if s["hall"] == h["id"] and s["family"] == "console"],
                          "product": mg.get("rack_switch_product"), "agg_product": mg.get("aggregation_product"),
                          "polls": polls, "failed": fail, "answered_pct": _pct(polls, fail),
                          "answering": answering, "in_service": [sum(r["in_service"][i] for r in rk) for i in range(H)]}
    kinds = {k: sum(1 for x in devs.values() if x["family"] == "bmc" and x["kind"] == k) for k in MGMT_KIND}
    return {"framing": cfg["framing"], "sources": cfg["sources"], "collection": cfg["collection"], "fields": cfg["fields"],
            "ports": cfg["ports"], "checks": cfg["checks"], "kind_names": MGMT_KIND, "kinds": kinds,
            "window": t.manifest["window"], "hours": H, "halls": halls, "racks": racks, "switches": switches,
            "console_ports": t.ports, "sessions": t.sessions, "collector": t.collector,
            "events": events, "findings": fs, "windows": t.manifest["windows"],
            "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks],
            "misses": [m for c in checks for m in c.misses][:20]}


def mgmt_json(t: TG.MgmtData, rack: str) -> dict:
    """One rack's month by hour: its BMC counts and both management switches' rows (what the rack view charts)."""
    num = lambda v: None if v == "" else float(v) if "." in v else int(v)    # noqa: E731
    rows = [r for r in t.bmc_hourly if r["rack"] == rack]
    out = {"rack": rack, "start": t.manifest["window"]["start"], "hours": len(rows),
           "bmc": {c: [num(r[c]) for r in rows] for c in ("endpoints", "polled_min", "answering_min", "answering_max", "failed_polls")},
           "switches": {}}
    for s in (f"{rack.lower()}-mgmt1", f"{rack.lower()}-mgmt2"):
        sr = [r for r in t.switch_hourly if r["switch"] == s]
        out["switches"][s] = {c: [num(r[c]) for r in sr] for c in ("up_min", "ports", "ports_up_min", "ports_up_max", "uplinks_up_min", "temp_c", "kbps")}
    return out


def mgmt_markdown(f: dict) -> str:
    w = f["window"]
    L = ["# Management network telemetry (Site AUS-1, synthetic)", "",
         f"{f['framing']} Window {day(w['start'])} to {day(w['end'])}: every BMC's Redfish service root polled once a minute by the "
         "Telemetry of Record, every management switch and console server read over SNMPv3 once a minute with its traps, and the "
         "console servers' session logs. All names and readings are fictional; no vendor's internal tooling is implied.", "",
         "Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py", "",
         "The management network is how the Telemetry of Record reaches every BMC and how the IT Partner works on a rack without "
         "walking to it. The IT Partner SLA measures its PSU and serial-swap clocks through the BMC, so a span with no answers is a "
         "span with no evidence. A gap is not a finding by itself; it becomes one when a record claims something the gap makes impossible.", "",
         "## Halls", "", "| Hall | Racks | BMC endpoints | Rack switches | Aggregation pair | Console servers | Polls answered |", "|---|---:|---:|---:|---|---:|---:|"]
    for h in f["halls"].values():
        L.append(f"| {h['name']} | {h['racks']} | {h['endpoints']:,} | {h['switches']} | {', '.join(h['aggs'])} | {len(h['consoles'])} | "
                 f"{h['answered_pct']}% of {h['polls']:,} |")
    L += ["", "## Racks", "", "| Rack | BMCs | In service from | Polls answered | Failed polls | Gaps over "
          f"{f['checks']['gap_min']} min | Out-of-band switch up h | In-band switch up h |", "|---|---:|---|---:|---:|---:|---:|---:|"]
    for r in f["racks"]:
        frm = "start of month" if r["in_service_from"] is None and not r["never"] else r["in_service_from"] or "not this month"
        pct = f"{r['answered_pct']}%" if r["answered_pct"] is not None else ""
        L.append(f"| {r['rack']} | {r['endpoints']} | {frm} | {pct} | {r['failed']:,} | {r['gaps']} | {r['mgmt1_up_h']} | {r['mgmt2_up_h']} |")
    L += ["", "## Findings", "", "Records that do not reconcile; each is a case to look into, not a claim that anyone misled.", ""]
    for x in f["findings"]:
        L += [f"### {x['id']}: {x['title']}", "", x["summary"], "", f"Owner: {x['owner']}. Contract: {x['contract']}.", ""]
        L += [f"- {ln}" for ln in x["lines"]] + [""]
    if not f["findings"]:
        L += ["None.", ""]
    L += ["## Events", "", "| From | To | Device | What | Records |", "|---|---|---|---|---|"]
    for e in f["events"]:
        refs = list(e["refs"]) + ([e["finding"]["id"]] if e.get("finding") else [])
        L.append(f"| {e['t']} | {e.get('end') or ''} | {e['device']} | {e['text']} | {', '.join(refs)} |")
    L += ["", "## Console sessions", "", "| Opened | Closed | Console port | Labelled | Prompt |", "|---|---|---|---|---|"]
    for s in f["sessions"]:
        L.append(f"| {s['opened_at']} | {s['closed_at']} | {s['console']} port {s['port']} | {s['label']} | `{s['prompt']}` |")
    L += ["", "## What is read", "", "| Field | Source | Unit | Meaning |", "|---|---|---|---|"]
    for x in f["fields"]:
        L.append(f"| `{x['name']}` | {x['source']} | {x['unit']} | {x['help']} |")
    L += ["", "## Agreement with the records", "", "| Check | Agrees |", "|---|---:|"]
    for a in f["agreements"]:
        L.append(f"| {a['title']} | {a['checked'] - a['misses']:,} of {a['checked']:,} |")
    if f["misses"]:
        L += ["", "Disagreements:", ""] + [f"- {m}" for m in f["misses"]]
    L += ["", "## Sources", ""] + [f"- {s['name']}: {s['url']} (checked {s['checked']})" for s in f["sources"]]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- site health
OUT_SITE = ROOT / "reports" / "site_health.md"


def prepare_site(dirs: SH.Dirs | None = None) -> dict:
    sh, data = SH.build(dirs)
    checks = SH.agreements(sh, data)
    out = SH.page_data(data)
    out["agreements"] = [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks]
    out["misses"] = [m for c in checks for m in c.misses][:20]
    return out


def _hours(H: int, spans: list[tuple[int, int]]) -> str:
    return f"{sum(b - a + 1 for a, b in spans):,} h" if spans else "none"


def site_markdown(f: dict) -> str:
    w, H = f["window"], f["hours"]
    hall = {x["id"]: x["name"] for x in f["halls"]}
    L = ["# Site health", "",
         f"Site AUS-1, {day(w['start'])} to {day(w['end'])} (the sample month). {f['framing'].strip()} Everything here is fictional.", "",
         "  Source: data/telemetry/ (every section's hourly tier and recorded state changes), site/site.yaml  |  "
         "Thresholds: config/site_health.yaml  |  Generator: scripts/render_telemetry.py", "",
         "## Redundancy over the month", "",
         "Units in service against the units the design needs; each hour counts its worst minute.", "",
         "| System | Where | Design | Hours with no redundant unit | Hours below N |", "|---|---|---|---:|---:|"]
    for g in f["groups"]:
        st = SH.unrle(g["state"])
        L.append(f"| {g['name']}{' (' + g['unit_word'] + ')' if g['unit_word'] else ''} | {hall.get(g['hall'], 'Site')} | {g['scheme']} | "
                 f"{st.count(SH.AMBER):,} | {st.count(SH.RED):,} |")
    L += ["", "## Each family's state", "", "| Family | Normal | Degraded | Lost |", "|---|---:|---:|---:|"]
    for x in f["families"]:
        st = SH.unrle(f["family_state"][x["key"]])
        L.append(f"| {x['name']} | {st.count(SH.GREEN):,} h | {st.count(SH.AMBER):,} h | {st.count(SH.RED):,} h |")
    L += ["", "## Conditions other than GPU racks", "",
          "GPU rack conditions (drained nodes, thermal slowdown, missing GPUs) are on the page's hall map and in the GPU telemetry report.", "",
          "| From | To | Family | Where | Condition |", "|---|---|---|---|---|"]
    fam = {x["key"]: x["name"] for x in f["families"]}
    start = G.parse(w["start"])
    at = lambda h: (start + timedelta(hours=h)).strftime("%b ") + str((start + timedelta(hours=h)).day) + (start + timedelta(hours=h)).strftime(" %H:%M")  # noqa: E731
    for i in f["issues"]:
        if i["family"] == "gpu" or i["text"].startswith("Hall") and "link drops" in i["text"]:
            continue
        L.append(f"| {at(i['from'])} | {at(i['to'] + 1)} | {fam[i['family']]} | {hall.get(i['hall'], 'Site')} | {i['text']} |")
    drops = [i for i in f["issues"] if "link drops" in i["text"]]
    L += ["", f"InfiniBand link drops: {len(drops)} spans in {sum(i['to'] - i['from'] + 1 for i in drops)} hours (each on the Network page)."]
    L += ["", "## Agreement with the hourly figures", "",
          "The dashboard's state comes from each section's recorded state changes; these checks hold it to the hourly figures each section publishes.", "",
          "| Check | Agrees |", "|---|---:|"]
    for a in f["agreements"]:
        L.append(f"| {a['title']} | {a['checked'] - a['misses']:,} of {a['checked']:,} |")
    if f["misses"]:
        L += ["", "Disagreements:", ""] + [f"- {m}" for m in f["misses"]]
    L += ["", "## Sources", ""] + [f"- {s['name']}: {s['url']} (checked {s['checked']})" for s in f["sources"]]
    return "\n".join(L) + "\n"


def racks_json(t: TM.Telemetry) -> dict:
    """Per rack per hour, from rack_hourly.csv, plus the CDU supply per hour (the page's fleet view)."""
    hours = t.hourly[next(iter(t.hourly))]["hours"]
    num = lambda v, f=float: None if v == "" else f(v)            # noqa: E731
    out: dict[str, dict] = {}
    for r in t.rack_hourly:
        x = out.setdefault(r["rack"], {k: [None] * hours for k in ("util", "kwh", "temp", "clock", "thermal_s", "power_s", "xids", "drained", "gpus")})
        i = int((G.parse(r["hour"]) - t.start).total_seconds() // 3600)
        x["util"][i], x["kwh"][i] = num(r["util_avg"]), float(r["power_kwh"])
        x["temp"][i], x["clock"][i] = num(r["gpu_temp_max_c"], int), num(r["sm_clock_min_loaded_mhz"], int)
        x["thermal_s"][i], x["power_s"][i], x["xids"][i] = int(r["thermal_violation_s"]), int(r["power_violation_s"]), int(r["xids"])
        x["drained"][i], x["gpus"][i] = int(r["nodes_drained"]), int(r["gpus_reporting"])
    cdu: dict[str, list] = {}
    for r in csv.DictReader((HEALTH / "cdu_hourly.csv").open(encoding="utf-8")):
        c = cdu.setdefault(r["cdu"], [None] * hours)
        i = int((G.parse(r["hour"]) - t.start).total_seconds() // 3600)
        if 0 <= i < hours:
            c[i] = float(r["supply_c"])
    return {"start": t.manifest["window"]["start"], "hours": hours, "racks": out, "cdu": cdu}


def html_page(f: dict | None = None) -> str:
    f = f or prepare()
    tpl = sitenav.inject((ROOT / "templates" / "telemetry.html").read_text(encoding="utf-8"), "telemetry")
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(f, sort_keys=True).replace("</", "<\\/")))


def write_site(out: Path) -> None:
    """out/index.html plus the files the page fetches: data/racks.json, data/gpu/<rack>.json, data/windows/*.json, and the
    CDU, power, network, and mechanical files (data/network/<leaf>.json, nvlink_<rack>.json, data/mechanical/<device>.json,
    windows/)."""
    t = load()
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html_page(prepare(t)), encoding="utf-8", newline="\n")
    data = out / "data"
    (data / "gpu").mkdir(parents=True, exist_ok=True)
    (data / "racks.json").write_text(json.dumps(racks_json(t), separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    for p in sorted(t.hourly_dir.glob("*.json")):
        shutil.copy2(p, data / "gpu" / p.name)
    if (data / "windows").exists():
        shutil.rmtree(data / "windows")
    shutil.copytree(DATA / "windows", data / "windows")
    c = load_cdu()
    for sub in ("cdu", "cdu_minutes"):
        if (data / sub).exists():
            shutil.rmtree(data / sub)
        (data / sub).mkdir(parents=True)
    for cdu in c.cdus:
        (data / "cdu" / f"{cdu}.json").write_text(json.dumps(cdu_json(c, cdu), separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
        shutil.copy2(c.minutes_dir / f"{cdu}.json", data / "cdu_minutes" / f"{cdu}.json")
    pw = load_power()
    for sub in ("power", "power_minutes"):
        if (data / sub).exists():
            shutil.rmtree(data / sub)
        (data / sub).mkdir(parents=True)
    for d, x in sorted(pw.manifest["devices"].items()):
        if x["family"] in ("ups", "busway", "generator"):
            (data / "power" / f"{d}.json").write_text(json.dumps(power_json(pw, d), separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    for name in pw.manifest["minutes"]:
        shutil.copy2(pw.minutes_dir / name, data / "power_minutes" / name)
    shutil.copytree(DATA_POWER / "windows", data / "power" / "windows")
    nt = load_network()
    if (data / "network").exists():
        shutil.rmtree(data / "network")
    (data / "network").mkdir(parents=True)
    for leaf in sorted(nt.devices("leaf")):
        (data / "network" / f"{leaf}.json").write_text(json.dumps(leaf_json(nt, leaf), separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    for name in nt.manifest["minutes"]:
        if name.startswith("nvlink_"):
            shutil.copy2(nt.minutes_dir / name, data / "network" / name)
    shutil.copytree(DATA_NET / "windows", data / "network" / "windows")
    mt = load_mech()
    for sub in ("mechanical", "mechanical_minutes"):
        if (data / sub).exists():
            shutil.rmtree(data / sub)
        (data / sub).mkdir(parents=True)
    for d in sorted(mt.manifest["devices"]):
        (data / "mechanical" / f"{d}.json").write_text(json.dumps(mech_json(mt, d), separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    for name in mt.manifest["minutes"]:
        shutil.copy2(mt.minutes_dir / name, data / "mechanical_minutes" / name)
    shutil.copytree(DATA_MECH / "windows", data / "mechanical" / "windows")
    gt = load_mgmt()
    if (data / "mgmt").exists():
        shutil.rmtree(data / "mgmt")
    (data / "mgmt").mkdir(parents=True)
    for r in sorted({x["rack"] for x in gt.manifest["devices"].values() if x["family"] == "bmc"}):
        (data / "mgmt" / f"{r}.json").write_text(json.dumps(mgmt_json(gt, r), separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    shutil.copytree(DATA_MGMT / "windows", data / "mgmt" / "windows")


def markdown(f: dict) -> str:
    w = f["window"]
    L = ["# GPU telemetry", "",
         f"Site AUS-1, {day(w['start'])} to {day(w['end'])} (the sample month). {f['framing']} Everything here is fictional.", "",
         "  Source: data/telemetry/gpu/ (committed tiers) and the per-GPU hourly tier built at publish time  |  "
         "Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py", "",
         "## What is collected", "",
         f"Every GPU ({f['gpus']:,} in {len(f['racks'])} racks) is scraped once a minute from the DCGM exporter on each tray "
         f"(port {f['collection']['exporter_port']}, collect interval {f['collection']['collect_interval_ms']:,} ms, the "
         f"exporter's published default). Fields, with the exporter's metric type:", "",
         "| Field | Type | Unit | Meaning |", "|---|---|---|---|"]
    for x in f["fields"]:
        L.append(f"| `{x['name']}` | {x['type']} | {x['unit']} | {x['help']}{' Enabled at this site; off in the default list.' if x['beyond_default'] else ''} |")
    L += ["", "## The month by hall", "", "| | " + " | ".join(h["name"] for h in f["halls"].values()) + " |",
          "|---|" + "---:|" * len(f["halls"])]
    rows = [("GPU model", lambda h: h["model"]), ("Racks reporting", lambda h: h["racks"]),
            ("Mean utilization", lambda h: f"{h['util_avg']}%"), ("Mean GPU power", lambda h: f"{h['power_avg_w']:,} W"),
            ("Power limit at this site", lambda h: f"{h['power_limit_w']:,} W (product maximum {h['power_max_w']:,} W)"),
            ("Time held at the power limit", lambda h: f"{h['at_cap_pct']}% of samples"),
            ("Hardware thermal slowdown", lambda h: f"{h['thermal_min']:,} GPU-minutes"),
            ("Peak GPU temperature", lambda h: f"{h['peak_c']} C"), ("GPU energy", lambda h: f"{h['mwh']:,} MWh"),
            ("XIDs", lambda h: h["xids"])]
    for name, fn in rows:
        L.append(f"| {name} | " + " | ".join(str(fn(h)) for h in f["halls"].values()) + " |")
    L += ["", "## Agreement with the records", "",
          "The telemetry is synthetic, so it is shaped never to contradict the records the other pages show. Each check reads only "
          "what the telemetry publishes and the existing records.", "", "| Check | Agrees |", "|---|---:|"]
    for a in f["agreements"]:
        L.append(f"| {a['title']} | {a['checked'] - a['misses']:,} of {a['checked']:,} |")
    if f["misses"]:
        L += ["", "Disagreements:", ""] + [f"- {m}" for m in f["misses"]]
    L += ["", "## Sources", ""] + [f"- {s['name']}: {s['url']} (checked {s['checked']})" for s in f["sources"]]
    return "\n".join(L) + "\n"


def robustness_month(k: int, keep: Path | None = None) -> dict:
    """Every GPU, CDU, power, network, mechanical, management, and site health agreement on generated month k (its own dataset, GPU Health layer,
    telemetry, and energy meters, in a temporary folder, or in keep to look at afterwards)."""
    import contextlib
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    from types import SimpleNamespace
    from scorecard.synthetic.energy import EnergyLayer, follow_devices, load_config as energy_config, write_energy
    syn = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    from scorecard import devices as DV
    cfg, hcfg, ccfg, ecfg, pcfg = T.load_config(), G.load_config(), TCS.load_config(), energy_config(), TPS.load_config()
    ncfg, mcfg, gcfg = TNS.load_config(), TMS.load_config(), TGS.load_config()
    with (contextlib.nullcontext(str(keep)) if keep else tempfile.TemporaryDirectory()) as tmp:
        d = Path(tmp)
        write_dataset(SiteGenerator(load_sla(), syn, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run(), d)
        G.write_gpu_health(G.GpuHealthLayer(d, 2000 + k, hcfg).run(), d / "gpu_health")
        pub = T.Published(T.GpuTelemetry(d, d / "gpu_health", 2000 + k, cfg, hcfg)).run()
        T.write_telemetry(pub, d / "telemetry", "", d / "hourly")
        checks = TM.agreements(TM.load(d / "telemetry", d / "hourly", d / "gpu_health", d), cfg, hcfg)
        built: dict = {}

        def cdu_build(edir: Path) -> SimpleNamespace:
            built["layer"] = TCS.CduTelemetry(pub.tel, pub, edir, None, ccfg)
            TCS.write_cdu(built["layer"], built["layer"].run(), d / "cdu", "", d / "cdu_min")
            return SimpleNamespace(dir=d / "cdu")
        el = EnergyLayer(d, 2000 + k, ecfg, rack_hourly=d / "telemetry" / "rack_hourly.csv")
        write_energy(follow_devices(el, None, d / "energy", cdu_build)[0], d / "energy")
        layer = built["layer"]
        cchecks = TC.agreements(TC.load(d / "cdu", d / "cdu_min", d / "gpu_health", d, d / "energy", d / "telemetry"), ccfg, hcfg)
        power = TPS.PowerTelemetry(pub.tel, pub, d / "energy", pcfg, energy_cfg=ecfg, rack_rest=ccfg["rack_rest"])
        TPS.write_power(power, power.run(), d / "power", "", d / "power_min")
        pchecks = TP.agreements(TP.load(d / "power", d / "power_min", d, d / "energy", d / "telemetry", d / "cdu"), pcfg, ccfg["rack_rest"], ecfg)
        net = TNS.NetworkTelemetry(pub.tel, pub, ncfg)
        TNS.write_network(net, net.run(), d / "network", "", d / "net_min")
        nchecks = TN.agreements(TN.load(d / "network", d / "net_min", d, d / "hourly"), ncfg, DV.load())
        mech = TMS.MechanicalTelemetry(d, 2000 + k, d / "energy", d / "cdu", mcfg, energy_cfg=ecfg)
        TMS.write_mechanical(mech, mech.run(), d / "mechanical", "", d / "mech_min")
        mchecks = TMM.agreements(TMM.load(d / "mechanical", d / "mech_min", d, d / "energy", d / "cdu", d / "power"), mcfg, ecfg, S.load_site())
        mg = TGS.MgmtTelemetry(d, 2000 + k, gcfg)
        TGS.write_mgmt(mg, mg.run(), d / "mgmt")
        gt = TG.load(d / "mgmt", d)
        gchecks, gfs = TG.agreements(gt, gcfg), TG.findings(gt, gcfg)
        gscore = TG.score(gfs, json.loads((d / "mgmt" / "answer_key.json").read_text(encoding="utf-8")))
        sh, shd = SH.build(SH.Dirs(d / "telemetry", d / "cdu", d / "power", d / "network", d / "mechanical", d, d / "mgmt"))
        schecks = SH.agreements(sh, shd)
    conflicts = [f"records disagree with each other: {pub.conflicts[:3]}"] * bool(pub.conflicts) \
        + [f"CDU records disagree with each other: {layer.conflicts[:3]}"] * bool(layer.conflicts) \
        + [f"power records disagree with each other: {power.conflicts[:3]}"] * bool(power.conflicts) \
        + [f"network records disagree with each other: {net.conflicts[:3]}"] * bool(net.conflicts) \
        + [f"mechanical records disagree with each other: {mech.conflicts[:3]}"] * bool(mech.conflicts)
    pack = lambda cs: {c.name: [c.checked - len(c.misses), c.checked, c.misses[:3]] for c in cs}      # noqa: E731
    return {"month": k, "gpu": pack(checks), "cdu": pack(cchecks), "power": pack(pchecks), "network": pack(nchecks), "mechanical": pack(mchecks),
            "mgmt": pack(gchecks), "mgmt_findings": gscore, "site": pack(schecks), "conflicts": conflicts}


def robustness(n: int, jobs: int = 1, resume: Path | None = None) -> int:
    """Every agreement on n generated months, jobs at a time. With resume, each month's result is kept in that folder
    and a rerun skips the months already there (a container restart need not start over)."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    t0 = time.time()
    done: dict[int, dict] = {}
    if resume:
        resume.mkdir(parents=True, exist_ok=True)
        for p in resume.glob("month_*.json"):
            r = json.loads(p.read_text(encoding="utf-8"))
            if r["month"] < n:
                done[r["month"]] = r
    todo = [k for k in range(n) if k not in done]

    def keep(r: dict) -> None:
        done[r["month"]] = r
        if resume:
            (resume / f"month_{r['month']:03d}.json").write_text(json.dumps(r) + "\n", encoding="utf-8")
        print(f"  month {r['month']} done ({time.time() - t0:.0f} s)", flush=True)

    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            for f in as_completed([ex.submit(robustness_month, k) for k in todo]):
                keep(f.result())
    else:
        for k in todo:
            keep(robustness_month(k))
    bad = 0
    ok = True
    for fam, title, w in (("gpu", "GPU", 12), ("cdu", "CDU", 15), ("power", "Power", 12), ("network", "Network", 14),
                         ("mechanical", "Mechanical", 12), ("mgmt", "Management", 12), ("site", "Site health", 12)):
        tot: dict[str, list[int]] = {}
        for k in range(n):
            if fam not in done[k]:
                ok = False
                print(f"  month {k}: no {fam} result (kept from before the {fam} checks existed; delete it and rerun)")
                continue
            for name, (a, b, misses) in done[k][fam].items():
                x = tot.setdefault(name, [0, 0])
                x[0], x[1] = x[0] + a, x[1] + b
                for m in misses:
                    print(f"  month {k}: {fam} {name}: {m}")
        print(f"{title}{'' if fam == 'site' else ' telemetry'} agreements on {n} generated months:")
        for name, (a, b) in tot.items():
            print(f"  {name:<{w}} {a:,}/{b:,}")
        ok = ok and all(a == b for a, b in tot.values())
    sc = {"planted": 0, "found": 0, "false_positives": 0}
    for k in range(n):
        for key in sc:
            sc[key] += done[k].get("mgmt_findings", {}).get(key, 0)
    print(f"Management findings on {n} generated months: {sc['found']} of {sc['planted']} planted found, {sc['false_positives']} false positives")
    ok = ok and sc["found"] == sc["planted"] and sc["false_positives"] == 0
    for k in range(n):
        for c in done[k]["conflicts"]:
            bad += 1
            print(f"  month {k}: {c}")
    return 0 if ok and not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, metavar="N")
    ap.add_argument("--jobs", type=int, default=1, help="months to run at once (robustness)")
    ap.add_argument("--resume", type=Path, metavar="DIR", help="keep each month's result here and skip months already done")
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness, args.jobs, args.resume)
    f = prepare()
    texts = {OUT: markdown(f), OUT_CDU: cdu_markdown(f["cdu"]), OUT_POWER: power_markdown(f["power"]), OUT_NET: network_markdown(f["network"]),
             OUT_MECH: mechanical_markdown(f["mechanical"]), OUT_MGMT: mgmt_markdown(f["mgmt"]), OUT_SITE: site_markdown(f["site"])}
    if args.check:
        stale = [p for p, text in texts.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        for p in stale:
            print(f"{p.relative_to(ROOT)} is out of date. Run: python scripts/render_telemetry.py")
        return 1 if stale else 0
    for p, text in texts.items():
        p.write_text(text, encoding="utf-8", newline="\n")
    for name, a in (("GPU", f["agreements"]), ("CDU", f["cdu"]["agreements"]), ("Power", f["power"]["agreements"]),
                    ("Network", f["network"]["agreements"]), ("Mechanical", f["mechanical"]["agreements"]),
                    ("Management", f["mgmt"]["agreements"]), ("Site health", f["site"]["agreements"])):
        ok = sum(x["checked"] - x["misses"] for x in a)
        print(f"{name}: {len(a)} agreements, {ok:,} of {sum(x['checked'] for x in a):,} cases agree")
    sc = TG.score(f["mgmt"]["findings"], json.loads((DATA_MGMT / "answer_key.json").read_text(encoding="utf-8")))
    print(f"Management findings: {len(f['mgmt']['findings'])}, {sc['found']} of {sc['planted']} planted, {sc['false_positives']} false positives")
    print("Wrote " + ", ".join(str(p.relative_to(ROOT)) for p in texts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
