"""GPU health review for Site AUS-1: the checks behind the GPU Health tab.

Reads the GPU health layer (``data/gpu_health/``, written by ``scripts/generate_gpu_health.py``) and
the month's telemetry and tickets (``data/sample/``). Synthetic data modeled on public DCGM-style
health checks; every threshold is in ``config/gpu_health.yaml``. Three checks:

1. Early warning: GPUs whose remapped rows or corrected memory errors are rising, before an
   uncorrectable memory XID (48, 94, 95) or with none yet (a drain-and-replace watch list).
2. Returned to service with a row remap pending: the scheduler put a node back in service while a
   GPU on it still needed a reset to complete a remap.
3. Thermal slowdown, walked across the cooling demarcation (DM-COOL): episodes while the CDU
   secondary was out of band are on the Landlord's side; a tray throttling while its CDU was in band
   is inside the rack, on the IT Partner's side.

A finding means the records do not reconcile with the telemetry, not that anyone misled. The checks
never read the answer key; ``evaluate`` compares their output with it afterwards.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scorecard.synthetic import gpu_health as G

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "gpu_health"
SAMPLE = ROOT / "data" / "sample"
DAY = timedelta(days=1)


def _rows(text: str) -> list[dict[str, Any]]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        x: dict[str, Any] = {}
        for k, v in r.items():
            if k in ("date", "hour", "host", "tray_serial", "cdu", "rack", "hall"):
                x[k] = v
            elif k in ("gpu", "sbe_day", "uce_day", "remapped_rows", "remap_pending", "trays_reporting", "flow_lpm", "flow_min_lpm"):
                x[k] = int(v)
            else:
                x[k] = float(v)
        out.append(x)
    return out


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def rack_of(host: str) -> str:
    return host.split("-")[0].upper()


@dataclass
class GpuData:
    watches: list[dict[str, Any]]
    counters: list[dict[str, Any]]
    episodes: list[dict[str, Any]]
    cdu: list[dict[str, Any]]
    racks: list[dict[str, Any]]
    sched: list[dict[str, Any]]
    tickets: list[dict[str, Any]]
    cdu_events: list[dict[str, Any]]
    window: dict[str, str]
    key: dict[str, Any] | None = None

    @property
    def start(self) -> datetime:
        return G.parse(self.window["start"])

    @property
    def end(self) -> datetime:
        return G.parse(self.window["end"])


def load(path: str | Path = DATA, sample: str | Path = SAMPLE) -> GpuData:
    p, s = Path(path), Path(sample)
    read = lambda name: (p / name).read_text(encoding="utf-8")   # noqa: E731
    key = p / "answer_key.json"
    tickets = s / "vendor" / "tickets.json"
    return GpuData(
        watches=_jsonl(p / "watches.jsonl"), counters=_rows(read("gpu_counters.csv")),
        episodes=_jsonl(p / "thermal_episodes.jsonl"), cdu=_rows(read("cdu_hourly.csv")), racks=_rows(read("rack_daily.csv")),
        sched=_jsonl(s / "telemetry" / "scheduler_node_states.jsonl"),
        tickets=json.loads(tickets.read_text(encoding="utf-8")) if tickets.exists() else [],
        cdu_events=_jsonl(s / "facility" / "cdu_redfish_events.jsonl"),
        window=json.loads(read("manifest.json"))["window"],
        key=json.loads(key.read_text(encoding="utf-8")) if key.exists() else None,
    )


@dataclass
class Finding:
    id: str
    type: str
    title: str
    summary: str
    party: str
    refs: list[str]
    evidence: list[str]
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ticket(d: GpuData, host: str, at: datetime) -> dict | None:
    """The IT Partner ticket on this tray that was open at ``at`` (or resolved within the hour after)."""
    for t in d.tickets:
        if t.get("configuration_item") != host or not t.get("opened_at"):
            continue
        a, b = G.parse(t["opened_at"]), G.parse(t["resolved_at"]) if t.get("resolved_at") else d.end
        if a - timedelta(hours=1) <= at <= b + timedelta(hours=1):
            return t
    return None


# --------------------------------------------------------------------------- #
# 1. Early warning
# --------------------------------------------------------------------------- #
def early_warning(d: GpuData, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """GPUs whose remapped rows or corrected errors are rising, flagged at the end of the first day they are."""
    c = cfg["checks"]
    memory = set(cfg["memory_xids"])
    series: dict[tuple[str, str, int], list[dict]] = {}
    for r in d.counters:
        series.setdefault((r["host"], r["tray_serial"], r["gpu"]), []).append(r)
    xids = [w for w in d.watches if w.get("xid") in memory]
    out = []
    for (host, serial, gpu), rows in sorted(series.items()):
        rows.sort(key=lambda r: r["date"])
        inc, prev, flag = [], None, None
        for i, r in enumerate(rows):
            day = G.parse(r["date"] + "T00:00:00Z")
            if prev is not None and G.parse(prev["date"] + "T00:00:00Z") == day - DAY:
                inc.append((day, r["remapped_rows"] - prev["remapped_rows"]))
            else:
                # first sight of this GPU (a new tray or a newly reporting rack): a remap counts as new only
                # when that day's errors explain it
                inc.append((day, r["remapped_rows"] if (r["sbe_day"] or r["uce_day"]) else 0))
            window = sum(n for t, n in inc if day - t < timedelta(days=c["rise_window_days"]))
            run = rows[max(0, i - c["sbe_rising_days"] + 1): i + 1]
            rising = (len(run) == c["sbe_rising_days"] and all(x["sbe_day"] >= c["sbe_floor"] for x in run)
                      and all(b["sbe_day"] > a["sbe_day"] for a, b in zip(run, run[1:]))
                      and all(G.parse(b["date"] + "T00:00:00Z") - G.parse(a["date"] + "T00:00:00Z") == DAY for a, b in zip(run, run[1:])))
            if window >= c["remap_rise_rows"] or rising:
                flag = (day + DAY, "remapped rows rising" if window >= c["remap_rise_rows"] else "corrected errors rising", r)
                break
            prev = r
        if not flag:
            continue
        at, why, r = flag
        mine = [w for w in xids if w["host"] == host and w["tray_serial"] == serial and w["gpu"] == gpu]
        before = [w for w in mine if G.parse(w["opened"]) <= at]
        after = [w for w in mine if G.parse(w["opened"]) > at]
        last = rows[-1]
        out.append({"host": host, "rack": rack_of(host), "tray_serial": serial, "gpu": gpu, "flagged": G.iso(at), "why": why,
                    "remapped_rows": last["remapped_rows"], "sbe_peak": max(x["sbe_day"] for x in rows),
                    "xid_before": before[0]["xid"] if before else None,
                    "xid_after": {"xid": after[0]["xid"], "at": after[0]["opened"],
                                  "lead_h": round((G.parse(after[0]["opened"]) - at).total_seconds() / 3600, 1)} if after else None,
                    "remap_pending": bool(last["remap_pending"]),
                    "series": [{"date": x["date"], "sbe": x["sbe_day"], "uce": x["uce_day"], "remapped": x["remapped_rows"]} for x in rows]})
    return out


def memory_xids(d: GpuData, cfg: dict[str, Any], flags: list[dict]) -> list[dict[str, Any]]:
    """Every uncorrectable memory XID this month, and whether an early warning came far enough ahead."""
    lead = cfg["checks"]["lead_hours"]
    out = []
    for w in d.watches:
        if w.get("xid") not in cfg["memory_xids"]:
            continue
        f = next((f for f in flags if (f["host"], f["tray_serial"], f["gpu"]) == (w["host"], w["tray_serial"], w["gpu"])
                  and f["xid_after"] and f["xid_after"]["at"] == w["opened"]), None)
        out.append({"host": w["host"], "gpu": w["gpu"], "xid": w["xid"], "at": w["opened"],
                    "warned": bool(f and f["xid_after"]["lead_h"] >= lead), "lead_h": f["xid_after"]["lead_h"] if f else None})
    return out


# --------------------------------------------------------------------------- #
# 2. Returned to service with a remap pending
# --------------------------------------------------------------------------- #
def rts_pending(d: GpuData) -> list[dict[str, Any]]:
    pend = [w for w in d.watches if w["system"] == "Memory" and w["message"].startswith("Row remap pending")]
    out = []
    for e in d.sched:
        if e["state"] != "idle" or e["reason"] != "returned to service":
            continue
        t = G.parse(e["timestamp"])
        for w in pend:
            if w["host"] == e["node"] and G.parse(w["opened"]) <= t and (w["cleared"] is None or G.parse(w["cleared"]) > t):
                seen = next((p for p in out if (p["host"], p["gpu"], p["pending_since"]) == (w["host"], w["gpu"], w["opened"])), None)
                if seen:
                    seen["again"].append(e["timestamp"])          # the same remap, still pending at a later return
                    continue
                tk = _ticket(d, e["node"], t)
                out.append({"host": e["node"], "rack": rack_of(e["node"]), "gpu": w["gpu"], "tray_serial": w["tray_serial"],
                            "rts": e["timestamp"], "pending_since": w["opened"], "cleared": w["cleared"],
                            "ticket": tk["number"] if tk else None, "close_code": tk.get("close_code") if tk else None, "again": []})
    return out


# --------------------------------------------------------------------------- #
# 3. Thermal slowdown across the cooling demarcation
# --------------------------------------------------------------------------- #
def _out_of_band(cfg: dict[str, Any], r: dict) -> bool:
    c = cfg["cdu"]
    return r["supply_max_c"] > c["alarm_high_c"] or r["flow_min_lpm"] < c["flow_band_min_lpm"]


def thermal(d: GpuData, cfg: dict[str, Any]) -> dict[str, Any]:
    c = cfg["checks"]
    cdu_of = {r["rack"]: r["cdu"] for r in d.racks}
    hours = {(r["cdu"], r["hour"]): r for r in d.cdu}
    landlord: dict[str, dict] = {}
    trays: dict[str, dict] = {}
    for e in d.episodes:
        rack = rack_of(e["host"])
        cdu = cdu_of.get(rack)
        s, f = G.parse(e["start"]), G.parse(e["end"])
        hr = hours.get((cdu, G.iso(s.replace(minute=0, second=0))))
        secs = (f - s).total_seconds()
        if hr and _out_of_band(cfg, hr):
            # contiguous out-of-band hours on one CDU make one event
            h0 = s.replace(minute=0, second=0)
            while (prev := hours.get((cdu, G.iso(h0 - timedelta(hours=1))))) and _out_of_band(cfg, prev):
                h0 -= timedelta(hours=1)
            k = f"{cdu}@{G.iso(h0)}"
            g = landlord.setdefault(k, {"cdu": cdu, "start": G.iso(h0), "racks": set(), "gpus": set(), "seconds": 0.0,
                                        "flow_min_lpm": 10 ** 6, "supply_max_c": 0.0, "end": G.iso(h0 + timedelta(hours=1))})
            h = h0
            while (x := hours.get((cdu, G.iso(h)))) and _out_of_band(cfg, x):
                g["flow_min_lpm"] = min(g["flow_min_lpm"], x["flow_min_lpm"])
                g["supply_max_c"] = max(g["supply_max_c"], x["supply_max_c"])
                h += timedelta(hours=1)
            g["end"] = G.iso(h)
            g["racks"].add(rack)
            g["gpus"].add((e["host"], e["gpu"]))
            g["seconds"] += secs
        else:
            t = trays.setdefault(e["host"], {"host": e["host"], "rack": rack, "cdu": cdu, "days": set(), "seconds": 0.0,
                                             "gpus": set(), "temp_max": 0.0, "first": e["start"], "last": e["end"]})
            t["days"].add(e["start"][:10])
            t["seconds"] += secs
            t["gpus"].add(e["gpu"])
            t["temp_max"] = max(t["temp_max"], e["gpu_temp_max_c"])
            t["last"] = max(t["last"], e["end"])
    hot = []
    for t in sorted(trays.values(), key=lambda t: -t["seconds"]):
        if len(t["days"]) >= c["thermal_days"] or t["seconds"] >= c["thermal_minutes"] * 60:
            sup = [r for r in d.cdu if r["cdu"] == t["cdu"] and t["first"][:10] <= r["hour"][:10] <= t["last"][:10]]
            tk = _ticket(d, t["host"], G.parse(t["last"]))
            hot.append({"host": t["host"], "rack": t["rack"], "cdu": t["cdu"], "days": len(t["days"]),
                        "minutes": round(t["seconds"] / 60), "gpus": sorted(t["gpus"]), "temp_max_c": t["temp_max"],
                        "first": t["first"], "last": t["last"],
                        "cdu_supply_max_c": max(r["supply_max_c"] for r in sup) if sup else None,
                        "cdu_flow_min_lpm": min(r["flow_min_lpm"] for r in sup) if sup else None,
                        "ticket": tk["number"] if tk else None})
    blips = sum(1 for t in trays.values() if t["host"] not in {h["host"] for h in hot})
    events = [{**g, "racks": sorted(g["racks"]), "gpus": len(g["gpus"]), "minutes": round(g["seconds"] / 60)}
              for g in sorted(landlord.values(), key=lambda g: g["start"])]
    for g in events:
        g.pop("seconds")
    return {"landlord": events, "hot_trays": hot, "brief_trays": blips, "cooling_events": cooling_events(d, cfg)}


def cooling_events(d: GpuData, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """The Landlord's CDU events this month (pump redundancy lost), with what the GPUs it serves saw."""
    cdu_of = {r["rack"]: r["cdu"] for r in d.racks}
    open_: dict[str, datetime] = {}
    spans = []
    for e in sorted(d.cdu_events, key=lambda e: e["timestamp"]):
        if e["property"] != "PumpRedundancy.Status.Health":
            continue
        t = G.parse(e["timestamp"])
        if e["value"] != "OK" and e["cdu"] not in open_:
            open_[e["cdu"]] = t
        elif e["value"] == "OK" and e["cdu"] in open_:
            spans.append((e["cdu"], open_.pop(e["cdu"]), t))
    spans += [(k, a, d.end) for k, a in open_.items()]
    out = []
    for cdu, a, b in sorted(spans, key=lambda s: s[1]):
        day = a.strftime("%Y-%m-%d")
        racks = sorted(r["rack"] for r in d.racks if r["cdu"] == cdu and r["date"] == day)
        hrs = [r for r in d.cdu if r["cdu"] == cdu and a - timedelta(hours=1) < G.parse(r["hour"]) < b]
        eps = [e for e in d.episodes if cdu_of.get(rack_of(e["host"])) == cdu and a <= G.parse(e["start"]) < b]
        out.append({"cdu": cdu, "start": G.iso(a), "end": G.iso(b), "racks_reporting": racks,
                    "flow_min_lpm": min((r["flow_min_lpm"] for r in hrs), default=None),
                    "supply_max_c": max((r["supply_max_c"] for r in hrs), default=None),
                    "in_band": not any(_out_of_band(cfg, r) for r in hrs), "slowdown_gpus": len({(e["host"], e["gpu"]) for e in eps})})
    return out


# --------------------------------------------------------------------------- #
# The status grid
# --------------------------------------------------------------------------- #
RANK = {"Pass": 0, "Warn": 1, "Fail": 2}


def grid(d: GpuData, flags: list[dict]) -> dict[str, dict[str, str]]:
    """Worst status per rack per day: Fail or Warn from any health watch active that day, Warn from a
    thermal slowdown or a GPU on the early-warning list; Pass otherwise; missing while not reporting."""
    out: dict[str, dict[str, str]] = {}
    for r in d.racks:
        out.setdefault(r["rack"], {})[r["date"]] = "Pass"

    def bump(rack: str, day: str, s: str) -> None:
        if day in out.get(rack, {}) and RANK[s] > RANK[out[rack][day]]:
            out[rack][day] = s
    for w in d.watches:
        a = G.parse(w["opened"])
        b = G.parse(w["cleared"]) if w["cleared"] else d.end
        day = a.replace(hour=0, minute=0, second=0)
        while day < b:
            bump(rack_of(w["host"]), day.strftime("%Y-%m-%d"), w["result"])
            day += DAY
    for e in d.episodes:
        bump(rack_of(e["host"]), e["start"][:10], "Warn")
    for f in flags:
        day = G.parse(f["flagged"])
        while day < d.end:
            bump(f["rack"], day.strftime("%Y-%m-%d"), "Warn")
            day += DAY
    return out


# --------------------------------------------------------------------------- #
# The whole review
# --------------------------------------------------------------------------- #
@dataclass
class Result:
    flags: list[dict[str, Any]]
    memory: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    thermal: dict[str, Any]
    grid: dict[str, dict[str, str]]
    findings: list[Finding]


def analyse(d: GpuData, cfg: dict[str, Any] | None = None) -> Result:
    cfg = cfg or G.load_config()
    flags = early_warning(d, cfg)
    mem = memory_xids(d, cfg, flags)
    pend = rts_pending(d)
    th = thermal(d, cfg)
    findings: list[Finding] = []
    n = 0

    def add(**kw: Any) -> None:
        nonlocal n
        n += 1
        findings.append(Finding(id=f"GH-F{n}", **kw))

    watch = [f for f in flags if not f["xid_before"] and not f["xid_after"]]
    if watch:
        add(type="watch_list", title=f"{len(watch)} GPU{'s' if len(watch) != 1 else ''} to drain and replace before {'they fail' if len(watch) != 1 else 'it fails'}",
            summary="Remapped rows or corrected memory errors are rising with no uncorrectable error yet. Each is a candidate to "
                    "drain at a convenient time and replace under the IT Partner's break-fix process, rather than wait for an XID.",
            party="IT Partner", refs=["CSL-01"],
            evidence=[f"{f['host']} GPU {f['gpu']}: {f['why']} from {f['flagged'][:10]}; {f['remapped_rows']} remapped rows, "
                      f"peak {f['sbe_peak']:,} corrected errors in a day" for f in watch],
            detail={"gpus": [{k: f[k] for k in ("host", "rack", "gpu", "tray_serial", "flagged")} for f in watch]})
    for p in pend:
        add(type="rts_pending", title=f"{p['host']} returned to service with a row remap pending",
            summary=f"The scheduler returned {p['host']} to service while GPU {p['gpu']} still needed a reset to complete a row "
                    f"remap from an uncorrectable memory error. Validation before return to service should include the GPU reset.",
            party="IT Partner", refs=["FC-GPU"],
            evidence=[f"Remap pending from {p['pending_since'][:16].replace('T', ' ')} UTC (health watch, Memory Warn)",
                      f"Returned to service {p['rts'][:16].replace('T', ' ')} UTC (scheduler)"]
                     + ([f"{p['ticket']} closed as '{p['close_code']}'"] if p["ticket"] else [])
                     + [f"Returned to service again at {a[:16].replace('T', ' ')} UTC, still pending" for a in p["again"]]
                     + [f"Pending until {p['cleared'][:16].replace('T', ' ')} UTC" if p["cleared"] else "Still pending at the end of the month"],
            detail=p)
    for h in th["hot_trays"]:
        add(type="hot_tray", title=f"{h['host']} throttling with its CDU in band",
            summary=f"GPUs on {h['host']} hit thermal slowdown on {h['days']} days ({h['minutes']} minutes) while {h['cdu']} held the rack "
                    "band, so the cause is inside the rack, downstream of the manifold isolation valves (DM-COOL): the tray's "
                    "quick-disconnects, hoses, or cold plates. " + ("A ticket covers it." if h["ticket"] else "No ticket is open for it."),
            party="IT Partner", refs=["DM-COOL", "FA-2"],
            evidence=[f"Slowdown on GPUs {', '.join(str(g) for g in h['gpus'])}, up to {h['temp_max_c']:.1f} C",
                      f"{h['cdu']} supply at most {h['cdu_supply_max_c']:.1f} C, flow at least {h['cdu_flow_min_lpm']:,} L/min over those days"]
                     + ([f"Ticket {h['ticket']}"] if h["ticket"] else []),
            detail=h)
    for g in th["landlord"]:
        add(type="cdu_excursion", title=f"{g['cdu']} out of band: {g['gpus']} GPUs throttled",
            summary=f"{g['cdu']}'s secondary left the rack band and GPUs in {len(g['racks'])} racks it serves hit thermal slowdown. "
                    "The walk from the source finds the first unhealthy component at the CDU, upstream of the rack manifold "
                    "isolation valves: Landlord side of DM-COOL.",
            party="Landlord", refs=["DM-COOL", "FA-1", "OT-CSL-03"],
            evidence=[f"{g['cdu']} flow down to {g['flow_min_lpm']:,} L/min, supply up to {g['supply_max_c']:.1f} C, "
                      f"{g['start'][:16].replace('T', ' ')} to {g['end'][11:16]} UTC", f"Racks {', '.join(g['racks'])}"],
            detail=g)
    return Result(flags, mem, pend, th, grid(d, flags), findings)


# --------------------------------------------------------------------------- #
# Self-check against the answer key
# --------------------------------------------------------------------------- #
@dataclass
class Evaluation:
    planted: int
    detected: int
    false_positives: list[str]
    missed: list[str]
    by_kind: dict[str, list[int]]


def evaluate(res: Result, key: dict[str, Any], cfg: dict[str, Any] | None = None) -> Evaluation:
    cfg = cfg or G.load_config()
    lead = cfg["checks"]["lead_hours"]
    by: dict[str, list[int]] = {}
    missed, fps = [], []

    def score(kind: str, hit: bool, what: str) -> None:
        by.setdefault(kind, [0, 0])
        by[kind][1] += 1
        by[kind][0] += hit
        if not hit:
            missed.append(f"{kind}: {what}")
    keyed = set()
    for k in key["early_warning"]:
        ident = (k["host"], k["tray_serial"], k["gpu"])
        keyed.add(ident)
        f = next((f for f in res.flags if (f["host"], f["tray_serial"], f["gpu"]) == ident), None)
        if k["kind"] == "precursor":
            ok = bool(f and f["xid_after"] and f["xid_after"]["at"] == k["xid_at"] and f["xid_after"]["lead_h"] >= lead)
        else:
            ok = f is not None
        score(k["kind"], ok, f"{k['host']} GPU {k['gpu']}")
    for f in res.flags:
        if (f["host"], f["tray_serial"], f["gpu"]) not in keyed and not f["xid_before"]:
            fps.append(f"early warning on {f['host']} GPU {f['gpu']}")
    for k in key["rts_pending"]:
        hit = any(p["host"] == k["host"] and abs((G.parse(p["rts"]) - G.parse(k["rts"])).total_seconds()) < 300 for p in res.pending)
        score(f"rts_pending ({k['kind']})", hit, f"{k['host']} at {k['rts']}")
    for p in res.pending:
        if not any(p["host"] == k["host"] and abs((G.parse(p["rts"]) - G.parse(k["rts"])).total_seconds()) < 300 for k in key["rts_pending"]):
            fps.append(f"remap pending at return to service on {p['host']}")
    for k in key["hot_trays"]:
        score("hot_tray", any(h["host"] == k["host"] for h in res.thermal["hot_trays"]), k["host"])
    for h in res.thermal["hot_trays"]:
        if not any(h["host"] == k["host"] for k in key["hot_trays"]):
            fps.append(f"hot tray {h['host']}")
    for k in key["excursions"]:
        a, b = G.parse(k["start"]), G.parse(k["end"])
        score("cdu_excursion", any(g["cdu"] == k["cdu"] and G.parse(g["start"]) <= b and G.parse(g["end"]) >= a
                                   for g in res.thermal["landlord"]), f"{k['cdu']} at {k['start']}")
    for g in res.thermal["landlord"]:
        if not any(g["cdu"] == k["cdu"] and G.parse(g["start"]) <= G.parse(k["end"]) and G.parse(g["end"]) >= G.parse(k["start"])
                   for k in key["excursions"]):
            fps.append(f"CDU excursion {g['cdu']} at {g['start']}")
    planted = sum(v[1] for v in by.values())
    return Evaluation(planted, sum(v[0] for v in by.values()), fps, missed, by)
