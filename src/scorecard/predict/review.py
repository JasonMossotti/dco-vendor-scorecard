"""Predictive maintenance review for Site AUS-1: this repository's wiring around the detectors.

* **Backtest**: run every detector over the 26-week condition history (``data/predict/``, on the failure
  history in ``data/history/``) as if it had been running then, and compare each warning with what the
  records show happened next. Nobody acted on the warnings, so every failure still happens.
* **Now**: run the same detectors on the sample month's telemetry (``data/telemetry/cdu/``, the GPU
  Health layer) as of its last day.
* **Fleet outlook**: a Weibull fit of optic module lifetimes and the GPU memory failure rate, against
  the spares minimums in the IT Partner SLA.

Outcomes come from the records (DOM alarms, XIDs, Redfish pump events, the filter's own pressure drop),
never from ``answer_key.json``; ``score`` compares the detectors with the key afterwards (robustness).
A prediction is a forecast that proposes work. It is not a finding and changes no SLA result.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from . import detectors as D
from .methods import weibull_conditional, weibull_fit

ROOT = Path(__file__).resolve().parents[3]
PREDICT = ROOT / "data" / "predict"
HISTORY = ROOT / "data" / "history"
UTC = timezone.utc
DAY = timedelta(days=1)
PARAM = {"bias_ma": ("Laser bias", "mA"), "tx_dbm": ("Transmit power", "dBm"), "rx_dbm": ("Receive power", "dBm")}
PARTS = ("optics", "gpu_memory", "cdu_filter", "cdu_pump")
MODE = {"bias_ma": "laser wearing out (bias rising)", "tx_dbm": "laser output falling", "rx_dbm": "receive power falling"}


def parse(s: str) -> datetime:
    if len(s) == 10:
        return datetime.fromisoformat(s).replace(tzinfo=UTC)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def config() -> dict:
    return yaml.safe_load((ROOT / "config" / "predict.yaml").read_text(encoding="utf-8"))


def gpu_health_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "gpu_health.yaml").read_text(encoding="utf-8"))


def raci(component: str) -> dict[str, str]:
    ia = yaml.safe_load((ROOT / "sla" / "interface_agreement.yaml").read_text(encoding="utf-8"))
    row = next(r for r in ia["raci"] if r["component"] == component)
    parties = ia["raci_parties"]
    return {"component": component, "accountable": next(p for p in parties if "A" in row[p].split("/")),
            "responsible": next(p for p in parties if "R" in row[p].split("/"))}


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
def modules(pdir: Path) -> list[dict]:
    out = []
    for r in _csv(pdir / "optic_dom_daily.csv"):
        m = dict(r)
        for p in PARAM:
            m[p] = [int(x) / 10 for x in r[p].split()]
        out.append(m)
    return out


def memory_counters(path: Path) -> list[dict]:
    from scorecard.gpu_health import _rows
    return _rows(path.read_text(encoding="utf-8"))


def memory_xids(hdir: Path, memory: list[int]) -> list[dict]:
    return [{"xid": e["xid"], "host": e["host"], "tray_serial": e["tray_serial"], "gpu": e["gpu_index"], "opened": e["timestamp"]}
            for e in _jsonl(hdir / "telemetry" / "dcgm_xid_events.jsonl") if e["xid"] in memory]


def run_detectors(pdir: Path, hdir: Path, cfg: dict, gh: dict) -> dict[str, Any]:
    """Every detector over the condition history. Reads data only, never the answer key."""
    det = cfg["detectors"]
    cdu = _csv(pdir / "cdu_condition.csv")
    return {
        "optics": D.optics(modules(pdir), det["optics"]),
        "gpu_memory": D.gpu_memory(memory_counters(pdir / "gpu_memory_daily.csv"), memory_xids(hdir, gh["memory_xids"]), gh),
        "cdu_filter": D.cdu_filter(cdu, det["cdu_filter"]),
        "cdu_pump": D.cdu_pump(cdu, _jsonl(pdir / "pump_events.jsonl"), det["cdu_pump"]),
    }


# --------------------------------------------------------------------------- #
# Backtest outcomes, from the records
# --------------------------------------------------------------------------- #
def _hours(a: str, b: str) -> float:
    return (parse(b) - parse(a)).total_seconds() / 3600


def filter_crossings(rows: list[dict], c: dict) -> dict[str, list[str]]:
    """Each time a CDU's filter pressure drop (at design flow) first reached the change limit, per change interval."""
    out: dict[str, list[str]] = {}
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["cdu"], []).append(r)
    for cdu, rs in by.items():
        rs.sort(key=lambda r: r["timestamp"])
        over, prev = False, None
        for r in rs:
            q = float(r["flow_lpm"]) / c["design_flow_lpm"]
            v = float(r["filter_dp_kpa"]) / (q * q)
            if prev is not None and prev - v >= c["step_kpa"]:
                over = False
            if v >= c["change_kpa"] and not over:
                out.setdefault(cdu, []).append(r["timestamp"])
                over = True
            prev = v
    return out


def work_requests(res: dict[str, Any], cfg: dict, number_from: int = 1) -> list[dict[str, Any]]:
    """One proposed work request per "act": the device, the failure mode, the evidence a person can check, a
    due-by date, and the owner from the Interface Agreement RACI. Shared by the backtest and scripts/predict.py."""
    det = cfg["detectors"]
    oc, fc, pc = det["optics"], det["cdu_filter"], det["cdu_pump"]
    out = []
    for f in res.get("optics", []):
        a = f["first_act"]
        if a:
            out.append({"detector": "optics", "device": f["location"], "serial": f["serial"], "flagged": a["flagged"],
                        "due_by": a["warn_by"], "mode": MODE[a["param"]],
                        "evidence": f"{PARAM[a['param']][0]} {a['level']:g} {PARAM[a['param']][1]}, moving {a['slope_per_day']:+g} a day: "
                                    f"reaches its warning ({oc['limits'][a['param']]['warn']:g}) in about {a['days_to_warn']:g} days",
                        "key": f["serial"]})
    for f in res.get("gpu_memory", []):
        if not f["xid_before"]:
            out.append({"detector": "gpu_memory", "device": f"{f['host']} GPU {f['gpu']}", "serial": f["tray_serial"],
                        "flagged": f["flagged"], "due_by": f["flagged"][:10], "mode": "uncorrectable memory error likely",
                        "evidence": f"{f['why'].capitalize()}: {f['remapped_rows']} remapped rows, corrected errors peaking at {f['sbe_peak']:,} a day",
                        "key": (f["host"], f["tray_serial"], f["gpu"], f["flagged"])})
    for cdu, r in sorted(res.get("cdu_filter", {}).items()):
        for a in r["acts"]:
            out.append({"detector": "cdu_filter", "device": cdu, "serial": "", "flagged": a["flagged"], "due_by": a["limit_on"],
                        "mode": "filter reaching its change limit before the next scheduled change",
                        "evidence": f"Filter pressure drop {a['level']:g} kPa at design flow, rising {a['slope_per_day']:g} kPa a day: "
                                    f"{fc['change_kpa']:g} kPa on {a['limit_on']}, next scheduled change {a['next_change'] or 'not on record'}",
                        "key": (cdu, a["flagged"])})
    for r in res.get("cdu_pump", {}).values():
        for a in r["acts"]:
            out.append({"detector": "cdu_pump", "device": f"{r['cdu']} pump {r['pump']}", "serial": "", "flagged": a["t"],
                        "due_by": (parse(a["t"]) + pc["lead_days"] * DAY).date().isoformat(), "mode": "pump wearing (more speed for the same flow)",
                        "evidence": f"Running {a['speed_pct']:g}% for a flow that needed {a['expected_pct']:g}% when it was new: "
                                    f"{a['residual_pct']:+g}% (work request at {pc['act_pct']:g}%)",
                        "key": (r["cdu"], r["pump"], a["t"])})
    out.sort(key=lambda r: (r["flagged"], r["detector"], r["device"]))
    owners = cfg["work_requests"]["raci"]
    for i, r in enumerate(out, number_from):
        r["id"] = f"{cfg['work_requests']['prefix']}-{i:04d}"
        r["owner"] = raci(owners[r["detector"]])
    return out


def backtest(pdir: Path = PREDICT, hdir: Path = HISTORY, cfg: dict | None = None, gh: dict | None = None,
             results: dict | None = None) -> dict[str, Any]:
    cfg, gh = cfg or config(), gh or gpu_health_config()
    det = cfg["detectors"]
    res = results or run_detectors(pdir, hdir, cfg, gh)
    man = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
    start = parse(man["window"]["start"])
    out: dict[str, Any] = {"window": man["window"]}
    outcome: dict[Any, str] = {}

    # Optics: every module failure (its own DOM alarm) and whether a warning came a day ahead.
    oc = det["optics"]
    alarms = [e for e in _jsonl(hdir / "telemetry" / "ufm_port_events.jsonl") if e["event"] == "module_alarm"]
    by_serial = {f["serial"]: f for f in res["optics"]}
    early = start + (oc["trend_days"] + 1) * DAY
    peer = {m["serial"]: m["peer"] for m in modules(pdir)}
    rows = []
    for a in alarms:
        f = by_serial.get(a["module_serial"])
        act = f["first_act"] if f else None
        lead = _hours(act["flagged"], a["timestamp"]) if act and act["flagged"] <= a["timestamp"] else None
        rows.append({"serial": a["module_serial"], "location": a["location"], "alarm": a["alarm"], "at": a["timestamp"],
                     "warned": lead is not None and lead >= oc["lead_hours"], "lead_h": round(lead, 1) if lead is not None else None,
                     "too_early": parse(a["timestamp"]) < early, "param": act["param"] if act else None, "peer": peer.get(a["module_serial"])})
    failed = {a["module_serial"] for a in alarms}
    false = [f for f in res["optics"] if f["first_act"] and f["serial"] not in failed]
    out["optics"] = {"failures": rows, "false_alarms": false}
    for f in res["optics"]:
        outcome[f["serial"]] = _outcome_opt(next((r for r in rows if r["serial"] == f["serial"]), None))

    # GPU memory: every uncorrectable memory XID, and whether the early-warning rule came a day ahead.
    lead = det["gpu_memory"]["lead_hours"]
    xids = memory_xids(hdir, gh["memory_xids"])
    gm = res["gpu_memory"]
    xrows = []
    for x in xids:
        f = next((f for f in gm if (f["host"], f["tray_serial"], f["gpu"]) == (x["host"], x["tray_serial"], x["gpu"])
                  and f["xid_after"] and f["xid_after"]["at"] == x["opened"]), None)
        xrows.append({"host": x["host"], "gpu": x["gpu"], "xid": x["xid"], "at": x["opened"],
                      "warned": bool(f and f["xid_after"]["lead_h"] >= lead), "lead_h": f["xid_after"]["lead_h"] if f else None})
    out["gpu_memory"] = {"failures": xrows, "false_alarms": [f for f in gm if not f["xid_after"] and not f["xid_before"]],
                         "after_the_fact": len([f for f in gm if f["xid_before"]])}
    for f in gm:
        outcome[(f["host"], f["tray_serial"], f["gpu"], f["flagged"])] = (
            f"XID {f['xid_after']['xid']} {f['xid_after']['lead_h'] / 24:.1f} days later" if f["xid_after"] else "No memory XID by the end of the window")

    # CDU filters: each time the pressure drop reached the change limit, and the warning before it.
    fc = det["cdu_filter"]
    cross = filter_crossings(_csv(pdir / "cdu_condition.csv"), fc)
    frows, ffalse = [], []
    for cdu, r in sorted(res["cdu_filter"].items()):
        for at in cross.get(cdu, []):
            act = next((a for a in r["acts"] if a["flagged"] <= at and _hours(a["flagged"], at) <= fc["horizon_days"] * 24), None)
            lh = _hours(act["flagged"], at) if act else None
            frows.append({"cdu": cdu, "at": at, "warned": lh is not None and lh >= fc["lead_days"] * 24,
                          "lead_h": round(lh, 1) if lh is not None else None})
        for a in r["acts"]:
            hit = next((x for x in cross.get(cdu, []) if x >= a["flagged"] and _hours(a["flagged"], x) <= fc["horizon_days"] * 24), None)
            if not hit:
                ffalse.append({"cdu": cdu, **a})
            outcome[(cdu, a["flagged"])] = f"Reached the limit {_hours(a['flagged'], hit) / 24:.0f} days later" if hit else "Did not reach the limit"
    out["cdu_filter"] = {"crossings": frows, "false_alarms": ffalse}

    # CDU pumps: every pump failure (Redfish health Critical), and the warning before it.
    pc = det["cdu_pump"]
    prow, pfalse = [], []
    for k, r in sorted(res["cdu_pump"].items()):
        for at in r["failures"]:
            act = next((a for a in r["acts"] if a["t"] <= at and _hours(a["t"], at) <= pc["horizon_days"] * 24), None)
            lh = _hours(act["t"], at) if act else None
            prow.append({"cdu": r["cdu"], "pump": r["pump"], "at": at, "warned": lh is not None and lh >= pc["lead_days"] * 24,
                         "lead_h": round(lh, 1) if lh is not None else None})
        for a in r["acts"]:
            hit = next((x for x in r["failures"] if x >= a["t"] and _hours(a["t"], x) <= pc["horizon_days"] * 24), None)
            if not hit:
                pfalse.append({"cdu": r["cdu"], "pump": r["pump"], **a})
            outcome[(r["cdu"], r["pump"], a["t"])] = (f"Failed {_hours(a['t'], hit) / 24:.0f} days later" if hit
                                                      else f"No failure within {pc['horizon_days']} days")
    out["cdu_pump"] = {"failures": prow, "false_alarms": pfalse}

    out["requests"] = work_requests(res, cfg)
    for r in out["requests"]:
        r["outcome"] = outcome[r.pop("key")]
    out["results"] = res
    return out


def _outcome_opt(hit: dict | None) -> str:
    if not hit:
        return "No module alarm by the end of the window"
    return f"Module alarm ({hit['alarm']}) {hit['lead_h'] / 24:.1f} days later" if hit["lead_h"] is not None else f"Module alarm ({hit['alarm']})"


def summary(bt: dict, cfg: dict) -> dict[str, Any]:
    """The headline per detector, from the records."""
    det = cfg["detectors"]
    o, g, f, p = bt["optics"], bt["gpu_memory"], bt["cdu_filter"], bt["cdu_pump"]

    def leads(rows: list[dict]) -> float | None:
        x = [r["lead_h"] / 24 for r in rows if r["warned"]]
        return round(median(x), 1) if x else None
    scored = [r for r in o["failures"] if not r["too_early"]]
    return {
        "optics": {"failures": len(o["failures"]), "scored": len(scored), "too_early": len(o["failures"]) - len(scored),
                   "warned": sum(r["warned"] for r in scored), "median_lead_days": leads(scored), "false_alarms": len(o["false_alarms"]),
                   "lead_rule": f"{det['optics']['lead_hours']} hours"},
        "gpu_memory": {"failures": len(g["failures"]), "warned": sum(r["warned"] for r in g["failures"]),
                       "median_lead_days": leads(g["failures"]), "false_alarms": len(g["false_alarms"]),
                       "after_the_fact": g["after_the_fact"], "lead_rule": f"{det['gpu_memory']['lead_hours']} hours"},
        "cdu_filter": {"failures": len(f["crossings"]), "warned": sum(r["warned"] for r in f["crossings"]),
                       "median_lead_days": leads(f["crossings"]), "false_alarms": len(f["false_alarms"]),
                       "lead_rule": f"{det['cdu_filter']['lead_days']} days"},
        "cdu_pump": {"failures": len(p["failures"]), "warned": sum(r["warned"] for r in p["failures"]),
                     "median_lead_days": leads(p["failures"]), "false_alarms": len(p["false_alarms"]),
                     "lead_rule": f"{det['cdu_pump']['lead_days']} days"},
    }


# --------------------------------------------------------------------------- #
# Scoring against the answer key (robustness and tests only)
# --------------------------------------------------------------------------- #
def score(bt: dict, key: dict, cfg: dict) -> dict[str, Any]:
    """Planted wear-outs warned in time, sudden failures (nothing to see), and false alarms on decoys."""
    det = cfg["detectors"]
    start = parse(bt["window"]["start"])
    early = start + (det["optics"]["trend_days"] + 1) * DAY
    warned = {r["serial"]: r for r in bt["optics"]["failures"]}
    opt = [k for k in key["optics"]["failures"] if k["precursor"] and parse(k["alarm_at"]) >= early]
    # A receive-power alarm while the far end's transmitter was wearing is the same fault seen from the other end: the
    # detector names the far end (peer attribution), so it counts as warned there when the far end's failure was.
    far = {r["location"]: r for r in bt["optics"]["failures"] if r["warned"]}
    peer_of = {r["location"]: r["peer"] for r in bt["optics"]["failures"]}

    def far_end(k: dict) -> bool:
        f = far.get(peer_of.get(k["location"], ""))
        return k["alarm"] == "RX power low" and f is not None and abs(_hours(f["at"], k["alarm_at"])) <= 72
    om = [k for k in opt if not warned[k["serial"]]["warned"] and not far_end(k)]
    o_far = sum(1 for k in opt if not warned[k["serial"]]["warned"] and far_end(k))
    sudden_warned = [k for k in key["optics"]["failures"] if not k["precursor"] and warned[k["serial"]]["warned"]]
    step_locs = {loc for s in key["optics"]["step_decoys"] for loc in s["link"]}
    gw = {(r["host"], r["gpu"], r["at"]): r for r in bt["gpu_memory"]["failures"]}
    # An error in the first days of data had its precursor before the data starts: too early to judge (as for optics).
    gearly = start + (gpu_health_config()["checks"]["sbe_rising_days"] + 1) * DAY
    gp = [k for k in key["gpu_memory"]["failures"] if k["precursor"] and parse(k["at"]) >= gearly]
    g_early = sum(1 for k in key["gpu_memory"]["failures"] if k["precursor"] and parse(k["at"]) < gearly)
    gm = [k for k in gp if not gw[(k["host"], k["gpu"], k["at"])]["warned"]]
    fk = key["cdu_filter"]
    # The measured crossing is the first reading over the limit; reading scatter puts it up to about half a day before
    # the planted (noiseless) one, so the two are matched within a day (one crossing per change interval at most).
    fhit = next((r for r in bt["cdu_filter"]["crossings"] if r["cdu"] == fk["cdu"] and fk["limit_at"] and abs(_hours(r["at"], fk["limit_at"])) <= 24), None)
    pumps = []
    for k in key["cdu_pumps"]:
        r = next((r for r in bt["cdu_pump"]["failures"] if (r["cdu"], r["pump"], r["at"]) == (k["cdu"], k["pump"], k["fails_at"])), None)
        pumps.append({"precursor": k["precursor"], "warned": bool(r and r["warned"])})
    return {
        "optics": {"planted": len(opt), "warned": len(opt) - len(om), "far_end": o_far, "missed": [k["serial"] for k in om],
                   "sudden_warned": len(sudden_warned), "false_alarms": len(bt["optics"]["false_alarms"]),
                   "steps_flagged": len([f for f in bt["optics"]["false_alarms"] if f["location"] in step_locs])},
        "gpu_memory": {"planted": len(gp), "warned": len(gp) - len(gm), "too_early": g_early, "false_alarms": len(bt["gpu_memory"]["false_alarms"])},
        "cdu_filter": {"planted": 1 if fk["limit_at"] else 0, "warned": int(bool(fhit and fhit["warned"])),
                       "false_alarms": len(bt["cdu_filter"]["false_alarms"])},
        "cdu_pump": {"planted": sum(p["precursor"] for p in pumps), "warned": sum(p["warned"] for p in pumps if p["precursor"]),
                     "sudden_warned": sum(p["warned"] for p in pumps if not p["precursor"]),
                     "false_alarms": len(bt["cdu_pump"]["false_alarms"])},
    }


# --------------------------------------------------------------------------- #
# Now: the same detectors on the sample month
# --------------------------------------------------------------------------- #
def now(sample: Path = ROOT / "data", hdir: Path = HISTORY, cfg: dict | None = None, gh: dict | None = None,
        until: str | None = None, flags: list[dict] | None = None) -> dict[str, Any]:
    """The detectors on the sample month's own feeds: every CDU filter and pump, and the GPU memory watch list.
    With until (an ISO time), only readings and flags before it count: the state at the end of a week."""
    cfg, gh = cfg or config(), gh or gpu_health_config()
    det = cfg["detectors"]
    rows = [{"timestamp": r["hour"], "cdu": r["cdu"], "flow_lpm": r["flow_lpm"], "filter_dp_kpa": r["filter_dp_kpa"],
             "pump1_pct": r["pump1_pct"], "pump2_pct": r["pump2_pct"]} for r in _csv(sample / "telemetry" / "cdu" / "cdu_hourly.csv")
            if not until or r["hour"] < until]
    last: dict[str, str] = {}
    for r in _csv(hdir / "landlord" / "pm_records.csv"):
        if "Filter" in r["task"]:
            last[r["asset"]] = max(last.get(r["asset"], ""), r["completed_at"])
    filters = D.cdu_filter(rows, det["cdu_filter"], last)
    pumps = D.cdu_pump(rows, [e for e in _jsonl(sample / "sample" / "facility" / "cdu_redfish_events.jsonl")
                              if not until or e["timestamp"] < until], det["cdu_pump"])
    if flags is None:
        flags = gpu_memory_flags(sample, gh)
    if until:
        flags = [f for f in flags if f["flagged"] < until]
    as_of = max(r["timestamp"] for r in rows)[:10]
    return {
        "as_of": as_of,
        "cdu_filter": [{"cdu": k, "level": v["now"]["level"], "slope_per_day": v["now"]["slope_per_day"], "limit_on": v["now"]["limit_on"],
                        "since_change_days": v["now"]["since_change_days"], "next_change": v["now"]["next_change"], "state": v["now"]["state"],
                        "changed_this_month": [c for c in v["changes"] if c[:10] >= rows[0]["timestamp"][:10]],
                        "overdue": bool(v["now"]["next_change"] and v["now"]["next_change"] <= as_of),
                        "daily": [d["level"] for d in v["days"]]}
                       for k, v in filters.items()],
        "cdu_pump": [{"cdu": v["cdu"], "pump": v["pump"], "state": v["now"], "baseline": v["baseline_pct_at_design"],
                      "residual_pct": v["points"][-1]["residual_pct"] if v["points"] else None,
                      "readings": len(v["points"]), "failures": v["failures"], "warned": bool(v["first_watch"])} for v in pumps.values()],
        "gpu_memory": [{"host": f["host"], "gpu": f["gpu"], "tray_serial": f["tray_serial"], "flagged": f["flagged"], "why": f["why"],
                        "remapped_rows": f["remapped_rows"], "remap_pending": f["remap_pending"],
                        "xid_after": f["xid_after"] if f["xid_after"] and (not until or f["xid_after"]["at"] < until) else None,
                        "xid_before": f["xid_before"]} for f in flags],
    }


def gpu_memory_flags(sample: Path = ROOT / "data", gh: dict | None = None) -> list[dict]:
    """The GPU Health tab's early-warning flags on the sample month (one run serves every week)."""
    from scorecard import gpu_health
    return gpu_health.early_warning(gpu_health.load(sample / "gpu_health", sample / "sample"), gh or gpu_health_config())


def week_line(state: dict[str, Any]) -> dict[str, Any]:
    """The weekly pack's predictive maintenance line, from now() at the end of the week."""
    f, p = state["cdu_filter"], state["cdu_pump"]
    gpu = [g for g in state["gpu_memory"] if not g["xid_before"] and not g["xid_after"]]
    return {"as_of": state["as_of"],
            "filters": {"healthy": sum(x["state"] == "healthy" for x in f), "of": len(f),
                        "act": sorted(x["cdu"] for x in f if x["state"] == "act"),
                        "watch": sorted(x["cdu"] for x in f if x["state"] == "watch"),
                        "due_by_calendar": sorted(x["cdu"] for x in f if x["overdue"] and x["state"] == "healthy")},
            "pumps": {"healthy": sum(x["state"] == "healthy" for x in p), "of": len(p),
                      "not_healthy": sorted(f"{x['cdu']} pump {x['pump']}" for x in p if x["state"] != "healthy")},
            "gpu_watch": sorted(f"{g['host']} GPU {g['gpu']}" for g in gpu)}


# --------------------------------------------------------------------------- #
# Fleet outlook
# --------------------------------------------------------------------------- #
def poisson_range(lam: float, lo: float = 0.05, hi: float = 0.95) -> tuple[int, int]:
    def cdf(k: int) -> float:
        return sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k + 1))
    a = next(k for k in range(1000) if cdf(k) >= lo)
    b = next(k for k in range(1000) if cdf(k) >= hi)
    return a, b


def fleet(hdir: Path = HISTORY, gh: dict | None = None, horizon_days: int = 30) -> dict[str, Any]:
    gh = gh or gpu_health_config()
    man = json.loads((hdir / "manifest.json").read_text(encoding="utf-8"))
    start, end = parse(man["window"]["start"]), parse(man["window"]["end"])
    inv = _csv(hdir / "customer" / "optic_inventory.csv")
    alarms = {e["module_serial"]: parse(e["timestamp"]) for e in _jsonl(hdir / "telemetry" / "ufm_port_events.jsonl") if e["event"] == "module_alarm"}
    times, failed, entry, ages_now, lots = [], [], [], [], {}
    for r in inv:
        t0 = parse(r["installed"])
        stop = alarms.get(r["serial"]) or (parse(r["removed"]) if r["removed"] else end)
        times.append((stop - t0).total_seconds() / 86400)
        failed.append(r["serial"] in alarms)
        entry.append(max(0.0, (start - t0).total_seconds() / 86400))
        lot = lots.setdefault(r["lot"], {"lot": r["lot"], "module_days": 0.0, "failures": 0, "installed_now": 0})
        lot["module_days"] += (stop - max(t0, start)).total_seconds() / 86400 if stop > start else 0
        lot["failures"] += r["serial"] in alarms
        if not r["removed"]:
            ages_now.append((end - t0).total_seconds() / 86400)
            lot["installed_now"] += 1
    fit = weibull_fit(times, failed, entry)
    exp_opt = sum(weibull_conditional(fit, a, horizon_days) for a in ages_now) if fit else None
    for lot in lots.values():
        rate = lot["failures"] / lot["module_days"] if lot["module_days"] else 0
        lot["per_module_year"] = round(rate * 365.25, 3)
        lot["expected"] = round(rate * horizon_days * lot["installed_now"], 1)
    xids = [e for e in _jsonl(hdir / "telemetry" / "dcgm_xid_events.jsonl") if e["xid"] in gh["memory_xids"]]
    topo = json.loads((ROOT / "data" / "sample" / "site" / "topology.json").read_text(encoding="utf-8"))
    gpus = sum(4 * len(r["compute_trays"]) for r in topo["racks"] if r["hall"] == man["window"]["hall"])
    days = (end - start).days
    rate = len(xids) / (gpus * days)
    exp_mem = rate * gpus * horizon_days
    # How often a memory XID ended in a tray replacement: the repair ticket opened for it used a compute tray.
    tickets = json.loads((hdir / "vendor" / "tickets.json").read_text(encoding="utf-8"))
    swapped = 0
    for x in xids:
        t = parse(x["timestamp"])
        tk = min((k for k in tickets if k.get("configuration_item") == x["host"] and parse(k["opened_at"]) >= t - timedelta(minutes=1)),
                 key=lambda k: k["opened_at"], default=None)
        swapped += bool(tk and any(p["part"] == "Compute tray" for p in tk["parts_used"]))
    share = swapped / len(xids) if xids else 0.0
    it = yaml.safe_load((ROOT / "sla" / "it_partner.yaml").read_text(encoding="utf-8"))
    mins = {m["fru"]: m["minimum"] for m in _find(it, "minimum_stock_per_hall")}
    return {"horizon_days": horizon_days, "hall": man["window"]["hall"],
            "optics": {"fit": {k: round(v, 3) if isinstance(v, float) else v for k, v in fit.items()} if fit else None,
                       "installed": len(ages_now), "expected": round(exp_opt, 1) if exp_opt is not None else None,
                       "range": poisson_range(exp_opt) if exp_opt else None, "shelf_minimum": mins.get("800G OSFP optic"),
                       "lots": sorted(lots.values(), key=lambda x: -x["per_module_year"])},
            "gpu_memory": {"gpus": gpus, "failures": len(xids), "days": days, "per_1000_gpu_months": round(rate * 1000 * 30, 2),
                           "expected": round(exp_mem, 1), "range": poisson_range(exp_mem), "swap_share_pct": round(100 * share),
                           "expected_swaps": round(exp_mem * share, 1), "shelf_minimum": mins.get("Compute tray")}}


def _find(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find(v, key)
            if r is not None:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = _find(v, key)
            if r is not None:
                return r
    return None


# --------------------------------------------------------------------------- #
# The condition history in the input contract's shape (scripts/predict.py --demo, and the tests)
# --------------------------------------------------------------------------- #
def export_contract(pdir: Path, hdir: Path, out: Path) -> list[str]:
    """Write the synthetic condition history as the files a site would export (docs/predict/README.md)."""
    out.mkdir(parents=True, exist_ok=True)

    def write(name: str, rows: list[dict], fields: list[str]) -> None:
        with open(out / name, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    long = []
    for m in modules(pdir):
        d0 = datetime.fromisoformat(m["first_day"]).date()
        for i in range(len(m["rx_dbm"])):
            long.append({"date": (d0 + timedelta(days=i)).isoformat(), "serial": m["serial"], "location": m["location"], "peer": m["peer"],
                         **{p: m[p][i] for p in PARAM}})
    write("optic_dom.csv", long, ["date", "serial", "location", "peer", *PARAM])
    write("gpu_memory.csv", _csv(pdir / "gpu_memory_daily.csv"),
          ["date", "host", "tray_serial", "gpu", "sbe_day", "uce_day", "remapped_rows", "remap_pending"])
    write("gpu_xids.csv", memory_xids(hdir, gpu_health_config()["memory_xids"]), ["opened", "host", "tray_serial", "gpu", "xid"])
    write("cdu_readings.csv", _csv(pdir / "cdu_condition.csv"), ["timestamp", "cdu", "flow_lpm", "filter_dp_kpa", "pump1_pct", "pump2_pct"])
    write("cdu_events.csv", _jsonl(pdir / "pump_events.jsonl"), ["timestamp", "cdu", "resource", "property", "value"])
    return sorted(p.name for p in out.iterdir())
