#!/usr/bin/env python3
"""Render the Telemetry tab (GPUs and CDUs) and its reports: reports/gpu_telemetry.md and reports/cdu_telemetry.md.

Reads the committed GPU telemetry (data/telemetry/gpu/), the per-GPU hourly tier (built into
build/telemetry/gpu_hourly/ by scripts/generate_telemetry.py if missing), and the records it must agree
with (data/gpu_health/, data/sample/). Synthetic data in the published format of NVIDIA's open-source DCGM
exporter; no vendor's internal tooling is implied.

Usage:
    python scripts/render_telemetry.py                    # write reports/gpu_telemetry.md
    python scripts/render_telemetry.py --check            # exit 1 if the report is out of date
    python scripts/render_telemetry.py --robustness 60    # every agreement on 60 generated months
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import gpu_health as H  # noqa: E402
from scorecard import sitenav  # noqa: E402
from scorecard import site_model as S  # noqa: E402
from scorecard import telemetry as TM  # noqa: E402
from scorecard import telemetry_cdu as TC  # noqa: E402
from scorecard import xid as X  # noqa: E402
from scorecard.synthetic import gpu_health as G  # noqa: E402
from scorecard.synthetic import telemetry as T  # noqa: E402
from scorecard.synthetic import telemetry_cdu as TCS  # noqa: E402

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
    }


# --------------------------------------------------------------------------- CDUs
DATA_CDU = ROOT / "data" / "telemetry" / "cdu"
ENERGY = ROOT / "data" / "energy"
OUT_CDU = ROOT / "reports" / "cdu_telemetry.md"
PLANNED = ["Power", "Network", "Mechanical"]          # device families still to come: shown greyed in the selector


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
    """out/index.html plus the files the page fetches: data/racks.json, data/gpu/<rack>.json, data/windows/*.json."""
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


def robustness(n: int) -> int:
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    syn = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    from scorecard.synthetic.energy import EnergyLayer, load_config as energy_config, write_energy
    cfg, hcfg, ccfg, ecfg = T.load_config(), G.load_config(), TCS.load_config(), energy_config()
    tot: dict[str, list[int]] = {}
    ctot: dict[str, list[int]] = {}
    bad = 0
    t0 = time.time()
    for k in range(n):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_dataset(SiteGenerator(load_sla(), syn, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run(), d)
            G.write_gpu_health(G.GpuHealthLayer(d, 2000 + k, hcfg).run(), d / "gpu_health")
            pub = T.Published(T.GpuTelemetry(d, d / "gpu_health", 2000 + k, cfg, hcfg)).run()
            T.write_telemetry(pub, d / "telemetry", "", d / "hourly")
            checks = TM.agreements(TM.load(d / "telemetry", d / "hourly", d / "gpu_health", d), cfg, hcfg)
            write_energy(EnergyLayer(d, 2000 + k, ecfg).run(), d / "energy")
            layer = TCS.CduTelemetry(pub.tel, pub, d / "energy", None, ccfg)
            TCS.write_cdu(layer, layer.run(), d / "cdu", "", d / "cdu_min")
            cchecks = TC.agreements(TC.load(d / "cdu", d / "cdu_min", d / "gpu_health", d, d / "energy", d / "telemetry"), ccfg, hcfg)
        if layer.conflicts:
            bad += 1
            print(f"  month {k}: CDU records disagree with each other: {layer.conflicts[:3]}")
        for c in cchecks:
            x = ctot.setdefault(c.name, [0, 0])
            x[0], x[1] = x[0] + c.checked - len(c.misses), x[1] + c.checked
            for m in c.misses[:3]:
                print(f"  month {k}: cdu {c.name}: {m}")
        if pub.conflicts:
            bad += 1
            print(f"  month {k}: records disagree with each other: {pub.conflicts[:3]}")
        for c in checks:
            x = tot.setdefault(c.name, [0, 0])
            x[0], x[1] = x[0] + c.checked - len(c.misses), x[1] + c.checked
            for m in c.misses[:3]:
                print(f"  month {k}: {c.name}: {m}")
        print(f"  month {k} done ({time.time() - t0:.0f} s)", flush=True)
    print(f"GPU telemetry agreements on {n} generated months:")
    for name, (a, b) in tot.items():
        print(f"  {name:<12} {a:,}/{b:,}")
    print(f"CDU telemetry agreements on {n} generated months:")
    for name, (a, b) in ctot.items():
        print(f"  {name:<15} {a:,}/{b:,}")
    return 0 if all(a == b for a, b in list(tot.values()) + list(ctot.values())) and not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, metavar="N")
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness)
    f = prepare()
    texts = {OUT: markdown(f), OUT_CDU: cdu_markdown(f["cdu"])}
    if args.check:
        stale = [p for p, text in texts.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        for p in stale:
            print(f"{p.relative_to(ROOT)} is out of date. Run: python scripts/render_telemetry.py")
        return 1 if stale else 0
    for p, text in texts.items():
        p.write_text(text, encoding="utf-8", newline="\n")
    for name, a in (("GPU", f["agreements"]), ("CDU", f["cdu"]["agreements"])):
        ok = sum(x["checked"] - x["misses"] for x in a)
        print(f"{name}: {len(a)} agreements, {ok:,} of {sum(x['checked'] for x in a):,} cases agree")
    print(f"Wrote {OUT.relative_to(ROOT)} and {OUT_CDU.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
