#!/usr/bin/env python3
"""Render the Telemetry tab (GPUs) and its report: reports/gpu_telemetry.md.

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
from scorecard import telemetry as TM  # noqa: E402
from scorecard import xid as X  # noqa: E402
from scorecard.synthetic import gpu_health as G  # noqa: E402
from scorecard.synthetic import telemetry as T  # noqa: E402

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
    }


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
    cfg, hcfg = T.load_config(), G.load_config()
    tot: dict[str, list[int]] = {}
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
    return 0 if all(a == b for a, b in tot.values()) and not bad else 1


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
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_telemetry.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    ok = sum(a["checked"] - a["misses"] for a in f["agreements"])
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(f['agreements'])} agreements, {ok:,} of {sum(a['checked'] for a in f['agreements']):,} cases agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
