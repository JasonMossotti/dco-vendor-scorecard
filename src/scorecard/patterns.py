"""Failure pattern analysis: which failures cluster beyond chance, why, and who owns the fix.

Facts only. Failures come from the Telemetry of Record (DCGM, UFM, Redfish),
never from ticket text; tickets supply only the fix that was applied. Each
failure signature is grouped by location (rack, the row a CDU serves, tray
slot), by asset lot (optics), and by fix (does a reseat or clean hold?), and
each group is compared with the rest of the fleet:

* location and lot: exact binomial test of the group's share of failures
  against its share of the installed base (exposure);
* fix effectiveness: one-sided Fisher exact test of 30-day recurrence after
  that fix against every other repair.

A group is a **pattern** only with at least ``MIN_EVENTS`` failures, a rate at
least ``MIN_RATIO`` times the rest, and a p-value under ``ALPHA`` divided by
the number of tests in its family (Bonferroni). Groups with a high ratio that
chance could still explain are **watch items**. For each pattern the analysis
then checks the evidence for a cause on either side of the Interface
Agreement's demarcation and looks the component up in the RACI. Judgment
(root cause statements, lessons, standard-work changes, actions) is written by
people in ``patterns/lessons.yaml`` and tested against these facts.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import yaml

UTC = timezone.utc
ALPHA = 0.05
MIN_EVENTS = 5
MIN_RATIO = 2.0
WATCH_P = 0.01         # uncorrected; about 1 test in 100 reaches this by chance alone
RECURRENCE_DAYS = 30
TICKET_MATCH = timedelta(hours=3)
DRIFT_C = 1.0          # degrees above setpoint that count as "running warm" (daily mean)
GAP_DAYS = 3
CONDITION_SIGS = ["thermal"]   # the failure modes a coolant temperature rise physically explains

SIGNATURES = {
    "xid_79": "XID 79 (GPU has fallen off the bus)",
    "xid_94": "XID 94 (contained ECC error)",
    "xid_48": "XID 48 (double-bit ECC error)",
    "xid_119": "XID 119 (GSP RPC timeout)",
    "xid_145": "XID 145 (NVLink error)",
    "xid_149": "XID 149 (NVLink error)",
    "thermal": "GPU thermal slowdown",
    "optic_module": "Optic module failure (DOM alarm)",
    "optic_fiber": "Link fault with no module alarm (fiber or connector)",
    "psu": "PSU failure",
}
ALL = "all"            # every failure together: what a ticket-count league table ranks
TRAY_SIGS = [s for s in SIGNATURES if s.startswith("xid_")] + ["thermal"]
COMPONENT = {   # signature -> Interface Agreement RACI component on the IT side
    **{s: "Compute tray (GPU, CPU, memory, cold plate)" for s in TRAY_SIGS},
    "optic_module": "Back-end fabric optics, cables, and fiber",
    "optic_fiber": "Back-end fabric optics, cables, and fiber",
    "psu": "Rack power shelves, PSUs, and whips from the tap-off output",
}
COOLING_COMPONENT = "CDUs and the hall secondary header"
DIMENSIONS = {"rack": "Rack", "cdu_row": "Row (racks a CDU serves)", "cdu_warm": "Racks a CDU serves, while it ran warm", "tray_slot": "Tray slot", "optic_lot": "Optic lot", "fix": "Fix applied"}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- statistics (standard library only)
def _lchoose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def binom_upper(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return min(1.0, sum(math.exp(_lchoose(n, i) + i * math.log(p) + (n - i) * math.log1p(-p)) for i in range(k, n + 1)))


def fisher_upper(a: int, n1: int, c: int, n2: int) -> float:
    """One-sided Fisher exact: P(group successes >= a) given a of n1 and c of n2, margins fixed."""
    total, succ = n1 + n2, a + c
    lo, hi = max(0, succ - n2), min(succ, n1)
    denom = _lchoose(total, succ)
    return min(1.0, sum(math.exp(_lchoose(n1, i) + _lchoose(n2, succ - i) - denom) for i in range(max(a, lo), hi + 1)))


# --------------------------------------------------------------------------- data
class History:
    def __init__(self, data_dir: str | Path, topology_path: str | Path, sla_dir: str | Path):
        d = Path(data_dir)
        jl = lambda f: [json.loads(x) for x in (d / f).read_text(encoding="utf-8").splitlines() if x.strip()]
        self.manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        self.xid = jl("telemetry/dcgm_xid_events.jsonl")
        self.thermal = jl("telemetry/dcgm_thermal_events.jsonl")
        self.ufm = jl("telemetry/ufm_port_events.jsonl")
        self.redfish = jl("telemetry/redfish_events.jsonl")
        self.cdu = jl("facility/cdu_secondary.jsonl")
        self.pm = list(csv.DictReader((d / "landlord/pm_records.csv").open(encoding="utf-8")))
        self.inventory = list(csv.DictReader((d / "customer/optic_inventory.csv").open(encoding="utf-8")))
        self.tickets = json.loads((d / "vendor/tickets.json").read_text(encoding="utf-8"))
        topo = json.loads(Path(topology_path).read_text(encoding="utf-8"))
        hall = self.manifest["window"]["hall"]
        self.racks = [r for r in topo["racks"] if r["hall"] == hall]
        sla = Path(sla_dir)
        self.ia = yaml.safe_load((sla / "interface_agreement.yaml").read_text(encoding="utf-8"))
        self.cdu_cfg = json.loads((d / "facility/cdu_setpoints.json").read_text(encoding="utf-8"))
        self.start, self.end = _t(self.manifest["window"]["start"]), _t(self.manifest["window"]["end"])


def _raci(ia: dict, component: str) -> dict[str, Any]:
    row = next(r for r in ia["raci"] if r["component"] == component)
    parties = [p for p in ia["raci_parties"]]
    acc = [p for p in parties if "A" in row[p].split("/")]
    resp = [p for p in parties if "R" in row[p].split("/")]
    return {"component": component, "accountable": acc[0], "responsible": resp[0], "consulted": [p for p in parties if row[p] == "C"]}


def failures(h: History) -> list[dict]:
    """One record per failure, from telemetry only."""
    rack_of = {r["rack"]: r for r in h.racks}
    slot_of = {t["host"]: t["slot"] for r in h.racks for t in r["compute_trays"]}
    cdu_of = {r["rack"]: r["cdu"] for r in h.racks}
    lot_of = {row["serial"]: row["lot"] for row in h.inventory}
    out = []
    for e in h.xid:
        rack = e["host"].split("-")[0].upper()
        out.append({"sig": f"xid_{e['xid']}", "t": e["timestamp"], "unit": e["host"], "rack": rack, "cdu_row": cdu_of[rack],
                    "tray_slot": slot_of[e["host"]], "source": "DCGM"})
    for e in h.thermal:
        rack = e["host"].split("-")[0].upper()
        out.append({"sig": "thermal", "t": e["timestamp"], "unit": e["host"], "rack": rack, "cdu_row": cdu_of[rack],
                    "tray_slot": slot_of[e["host"]], "source": "DCGM"})
    alarms = [e for e in h.ufm if e["event"] == "module_alarm"]
    alarmed_downs: set[int] = set()
    downs = [(i, e) for i, e in enumerate(h.ufm) if e["event"] == "link_down"]
    for a in alarms:
        loc = a["location"]
        # The link that went down within an hour of the module's alarm, at either end.
        i, d = next((i, d) for i, d in downs if i not in alarmed_downs and 0 <= (_t(d["timestamp"]) - _t(a["timestamp"])).total_seconds() <= 3600
                    and loc in (f"{d['peer_host']}:{d['peer_hca']}", f"{d['switch']}:swp{d['port']}"))
        alarmed_downs.add(i)
        rack = d["peer_host"].split("-")[0].upper()
        out.append({"sig": "optic_module", "t": d["timestamp"], "unit": f"{d['peer_host']}:{d['peer_hca']}", "rack": rack,
                    "cdu_row": cdu_of[rack], "optic_lot": lot_of[a["module_serial"]], "module": a["module_serial"], "source": "UFM"})
    for i, d in downs:
        if i in alarmed_downs:
            continue
        rack = d["peer_host"].split("-")[0].upper()
        out.append({"sig": "optic_fiber", "t": d["timestamp"], "unit": f"{d['peer_host']}:{d['peer_hca']}", "rack": rack,
                    "cdu_row": cdu_of[rack], "source": "UFM"})
    for e in h.redfish:
        if e["property"] == "Status.Health" and e["value"] == "Critical" and "/PowerSupplies/" in e["resource"]:
            m = re.search(r"/Chassis/([A-Z]\d+)_PowerShelf_(\d+)/PowerSubsystem/PowerSupplies/(\d+)", e["resource"])
            rack, shelf, psu = m.group(1), m.group(2), m.group(3)
            out.append({"sig": "psu", "t": e["timestamp"], "unit": f"PSU {psu} in {rack} power shelf {shelf}", "rack": rack,
                        "cdu_row": cdu_of[rack], "source": "Redfish"})
    assert all(r in rack_of for r in (f["rack"] for f in out))
    return sorted(out, key=lambda f: (f["t"], f["unit"]))


def _ticket_key(t: dict) -> str:
    if t["category"] == "optic_link":
        return t["short_description"].split(" ")[1]
    return t["configuration_item"]


def attach_repairs(fs: list[dict], tickets: list[dict]) -> None:
    """The ticket that repaired each failure (same unit, opened within three hours), and whether it recurred."""
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for t in tickets:
        by_unit[_ticket_key(t)].append(t)
    used: set[str] = set()
    for f in fs:
        cands = [t for t in by_unit[f["unit"]] if t["number"] not in used and timedelta(0) <= _t(t["opened_at"]) - _t(f["t"]) <= TICKET_MATCH]
        t = min(cands, key=lambda t: t["opened_at"]) if cands else None
        f["ticket"] = t["number"] if t else None
        f["fix"] = t["close_code"] if t else None
        f["resolved"] = t["resolved_at"] if t else None
        f["parts"] = [p["part"] for p in t["parts_used"]] if t else []
        if t:
            used.add(t["number"])
    by_unit_f: dict[str, list[dict]] = defaultdict(list)
    for f in fs:
        by_unit_f[f["unit"]].append(f)
    for f in fs:
        f["recurred"] = None
        if f["resolved"]:
            r = _t(f["resolved"])
            nxt = next((g for g in by_unit_f[f["unit"]] if _t(g["t"]) > r), None)
            f["recurred"] = bool(nxt and _t(nxt["t"]) - r <= timedelta(days=RECURRENCE_DAYS))
            f["recurrence"] = nxt["t"] if f["recurred"] else None


# --------------------------------------------------------------------------- exposure
def exposure(h: History, dim: str, sig: str) -> dict[str, float]:
    """Installed base per group: trays, modules (module-days for lots), or PSUs."""
    if dim == "optic_lot":
        days: dict[str, float] = defaultdict(float)
        for row in h.inventory:
            a = max(_t(row["installed"] + "T00:00:00Z"), h.start)
            b = min(_t(row["removed"] + "T00:00:00Z"), h.end) if row["removed"] else h.end
            if b > a:
                days[row["lot"]] += (b - a).total_seconds() / 86400
        return dict(days)
    per_rack = {"optic_module": 144.0, "optic_fiber": 72.0, "psu": 48.0, ALL: 1.0}.get(sig, 18.0)
    if dim == "rack":
        return {r["rack"]: per_rack for r in h.racks}
    if dim == "cdu_row":
        c = Counter(r["cdu"] for r in h.racks)
        return {k: v * per_rack for k, v in c.items()}
    if dim == "tray_slot":
        return {t["slot"]: float(len(h.racks)) for t in h.racks[0]["compute_trays"]}
    raise ValueError(dim)


def warm_episodes(h: History) -> list[dict]:
    """Runs of at least 7 days in which a CDU's daily mean secondary supply sat DRIFT_C or more above setpoint
    (gaps of up to GAP_DAYS days below it, as a slow drift crosses the line, do not split a run)."""
    sp, out = h.cdu_cfg["setpoint_c"], []
    for cdu in h.cdu_cfg["cdus"]:
        daily: dict[str, list[float]] = defaultdict(list)
        for r in h.cdu:
            if r["cdu"] == cdu:
                daily[r["timestamp"][:10]].append(r["supply_c"])
        days = sorted(daily)
        warm = [sum(daily[d]) / len(daily[d]) - sp >= DRIFT_C for d in days]
        for i in range(len(warm)):   # fill short gaps between warm days
            if not warm[i] and any(warm[max(0, i - GAP_DAYS):i]) and any(warm[i + 1:i + 1 + GAP_DAYS]):
                warm[i] = True
        i = 0
        while i < len(days):
            if warm[i]:
                j = i
                while j + 1 < len(days) and warm[j + 1]:
                    j += 1
                if j - i + 1 >= 7:
                    out.append({"cdu": cdu, "from": days[i] + "T00:00:00Z", "to": _iso(_t(days[j] + "T00:00:00Z") + timedelta(days=1)),
                                "days": j - i + 1, "racks": sorted(r["rack"] for r in h.racks if r["cdu"] == cdu)})
                i = j + 1
            else:
                i += 1
    return out


def first_failures(fs: list[dict]) -> list[dict]:
    """The first failure of each unit for each signature. Location and lot tests count failing units, not events,
    so one unit failing again and again (a repeat failure, measured by CSL-08) cannot make a location look like a pattern."""
    seen, out = set(), []
    for f in fs:
        k = (f["sig"], f.get("module") or f["unit"])   # an optic module is the asset; a replaced one is a new asset
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def _tests(h: History, all_fs: list[dict], episodes: list[dict]) -> list[dict]:
    tests = []
    fs = first_failures(all_fs)
    window_days = (h.end - h.start).total_seconds() / 86400
    for ep in episodes:
        # Facility condition: did failures concentrate where and while the CDU ran warm?
        share = len(ep["racks"]) / len(h.racks) * ep["days"] / window_days
        for sig in CONDITION_SIGS:
            ev = [f for f in fs if f["sig"] == sig]
            k = sum(1 for f in ev if f["rack"] in ep["racks"] and ep["from"] <= f["t"] < ep["to"])
            rest = (len(ev) - k) / (1 - share)
            ratio = (k / share) / rest if rest else (math.inf if k else 0)
            tests.append({"family": "facility condition", "sig": sig, "dim": "cdu_warm", "group": ep["cdu"], "episode": ep,
                          "events": k, "expected": round(len(ev) * share, 2), "exposure": share, "ratio": ratio,
                          "p": binom_upper(k, len(ev), share), "total": len(ev)})
    for sig in [ALL, *SIGNATURES]:
        ev = fs if sig == ALL else [f for f in fs if f["sig"] == sig]
        dims = ["rack", "cdu_row"] + (["tray_slot"] if sig in TRAY_SIGS else []) + (["optic_lot"] if sig == "optic_module" else [])
        for dim in dims:
            exp = exposure(h, dim, sig)
            total_x, total_k = sum(exp.values()), len(ev)
            counts = Counter(f[dim] for f in ev)
            for g, x in exp.items():
                k = counts.get(g, 0)
                share = x / total_x
                rest = (total_k - k) / (total_x - x) if total_x > x else 0
                ratio = (k / x) / rest if rest else (math.inf if k else 0)
                tests.append({"family": "asset lot" if dim == "optic_lot" else "location", "sig": sig, "dim": dim, "group": g,
                              "events": k, "expected": round(total_k * share, 2), "exposure": x, "ratio": ratio,
                              "p": binom_upper(k, total_k, share), "total": total_k})
    # Fix effectiveness: every repair that had a full 30 days to show a recurrence.
    cut = h.end - timedelta(days=RECURRENCE_DAYS)
    rep = [f for f in all_fs if f["fix"] and _t(f["resolved"]) <= cut]
    for sig in SIGNATURES:
        for fix in sorted({f["fix"] for f in rep if f["sig"] == sig}):
            grp = [f for f in rep if f["sig"] == sig and f["fix"] == fix]
            oth = [f for f in rep if not (f["sig"] == sig and f["fix"] == fix)]
            a, c = sum(f["recurred"] for f in grp), sum(f["recurred"] for f in oth)
            r_rest = c / len(oth) if oth else 0
            ratio = (a / len(grp)) / r_rest if r_rest else (math.inf if a else 0)
            tests.append({"family": "fix", "sig": sig, "dim": "fix", "group": fix, "events": a, "repairs": len(grp),
                          "expected": round(len(grp) * r_rest, 2), "ratio": ratio, "p": fisher_upper(a, len(grp), c, len(oth)),
                          "rest_rate": r_rest})
    return tests


def _classify(tests: list[dict]) -> None:
    m = Counter(t["family"] for t in tests)
    for t in tests:
        t["threshold"] = ALPHA / m[t["family"]]
        if t["events"] >= MIN_EVENTS and t["ratio"] >= MIN_RATIO and t["p"] < t["threshold"]:
            t["verdict"] = "pattern"
        elif t["events"] >= MIN_EVENTS and t["ratio"] >= MIN_RATIO and t["p"] < WATCH_P:
            t["verdict"] = "watch"
        else:
            t["verdict"] = "none"


def _fold_nested(h: History, tests: list[dict], fs: list[dict]) -> None:
    """A rack inside a row that is already a pattern for the same signature is part of that pattern,
    unless it stands out within the row as well."""
    row_of = {r["rack"]: r["cdu"] for r in h.racks}
    warm = {(t["sig"], t["group"]) for t in tests if t["dim"] == "cdu_warm" and t["verdict"] == "pattern"}
    for t in tests:
        if t["dim"] == "cdu_row" and t["verdict"] != "none" and (t["sig"], t["group"]) in warm:
            t["verdict"], t["folded_into"] = "none", t["group"]
    rows = {(t["sig"], t["group"]) for t in tests if t["dim"] in ("cdu_row", "cdu_warm") and t["verdict"] == "pattern"}
    for t in tests:
        if t["dim"] == "rack" and t["verdict"] != "none" and (t["sig"], row_of[t["group"]]) in rows:
            row_k = sum(1 for f in fs if (t["sig"] == ALL or f["sig"] == t["sig"]) and f["cdu_row"] == row_of[t["group"]])
            n_racks = sum(1 for r in h.racks if r["cdu"] == row_of[t["group"]])
            if binom_upper(t["events"], row_k, 1 / n_racks) >= t["threshold"]:
                t["verdict"], t["folded_into"] = "none", row_of[t["group"]]


# --------------------------------------------------------------------------- evidence for a cause
def _supply_at(h: History) -> Any:
    """The CDU's daily mean secondary supply on the day of a failure, and the raw 4-hour series."""
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    daily: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in h.cdu:
        series[r["cdu"]].append((_t(r["timestamp"]), r["supply_c"]))
        daily[(r["cdu"], r["timestamp"][:10])].append(r["supply_c"])

    def at(cdu: str, t: str) -> float:
        v = daily[(cdu, t[:10])]
        return sum(v) / len(v)
    return at, series


def _select(fs: list[dict], t: dict) -> tuple[list[dict], list[dict]]:
    """The failures in a tested group, and the same signature's failures outside it."""
    same = fs if t["sig"] == ALL else [f for f in fs if f["sig"] == t["sig"]]
    if t["dim"] == "cdu_warm":
        ep = t["episode"]
        inside = lambda f: f["rack"] in ep["racks"] and ep["from"] <= f["t"] < ep["to"]  # noqa: E731
    elif t["dim"] == "fix":
        inside = lambda f: f["fix"] == t["group"]  # noqa: E731
        same = [f for f in same if f["fix"]]
    else:
        inside = lambda f: f.get(t["dim"]) == t["group"]  # noqa: E731
    return [f for f in same if inside(f)], [f for f in same if not inside(f)]


def _cooling_evidence(h: History, t: dict, fs: list[dict], episodes: list[dict]) -> dict[str, Any]:
    """Was the cooling upstream of the rack manifold (the Landlord's side of DM-COOL) unusual when these failures happened?"""
    at, series = _supply_at(h)
    sp, alarm = h.cdu_cfg["setpoint_c"], h.cdu_cfg["alarm_high_c"]
    grp, oth = _select(fs, t)
    rise_g = [at(f["cdu_row"], f["t"]) - sp for f in grp]
    rise_o = [at(f["cdu_row"], f["t"]) - sp for f in oth]
    warm = lambda xs: sum(1 for x in xs if x >= DRIFT_C)  # noqa: E731
    cdu = Counter(f["cdu_row"] for f in grp).most_common(1)[0][0]
    ep = t.get("episode") or next((e for e in episodes if e["cdu"] == cdu), None)
    ev: dict[str, Any] = {"kind": "cooling", "cdu": cdu, "setpoint_c": sp, "alarm_high_c": alarm,
                          "events": len(grp), "events_warm": warm(rise_g), "others": len(oth), "others_warm": warm(rise_o),
                          "median_rise_group": round(median(rise_g), 1),
                          "median_rise_others": round(median(rise_o), 1) + 0.0 if rise_o else None, "episode": ep}
    if ep:
        inside = [(ts, v) for ts, v in series[cdu] if ep["from"] <= _iso(ts) < ep["to"]]
        peak_t, peak_v = max(inside, key=lambda x: x[1])
        changes = sorted(r["completed_at"] for r in h.pm if r["asset"] == cdu and r["system"] == "CDUs")
        before = [c for c in changes if c < ep["from"]]
        ended_by = next((c for c in changes if abs((_t(c) - _t(ep["to"])).total_seconds()) <= 2 * 86400), None)
        row = ep["racks"]
        same = [f for f in fs if f["sig"] == t["sig"] and f["rack"] in row]
        flows = [(r["timestamp"], r["flow_lpm"]) for r in h.cdu if r["cdu"] == cdu]
        f_before = [v for ts, v in flows if _iso(_t(ep["from"]) - timedelta(days=28)) <= ts < ep["from"]]
        f_end = [v for ts, v in flows if _iso(_t(ep["to"]) - timedelta(days=7)) <= ts < ep["to"]]
        ev.update({"flow_before_lpm": round(median(f_before)) if f_before else None, "flow_end_lpm": round(median(f_end)),
                   "flow_drop_pct": round(100 * (1 - median(f_end) / median(f_before)), 1) if f_before else None,
                   "racks_count": len(ep["racks"]), "peak_c": round(peak_v, 1), "peak_at": _iso(peak_t), "below_alarm": max(v for _, v in series[cdu]) < alarm,
                   "others_peak_c": round(max(v for c, sr in series.items() if c != cdu for _, v in sr), 1),
                   "previous_filter_change": before[-1] if before else None, "ended_by_filter_change": ended_by,
                   "ongoing_at_window_end": ep["to"] >= _iso(h.end),
                   "events_after": sum(1 for f in same if f["t"] >= ep["to"]),
                   "days_after": max(0, round((h.end - _t(ep["to"])).total_seconds() / 86400)),
                   "tray_swaps": sum(1 for f in grp if f["fix"] == "Hardware replaced"),
                   "reseats": sum(1 for f in grp if f["fix"] == "Cleaned/reseated")})
    # The facility explains the pattern when the failures sat in a warm episode and the same failures elsewhere did not.
    explained = t["dim"] == "cdu_warm" or (bool(grp) and warm(rise_g) / len(grp) >= 0.6 and (warm(rise_o) / len(oth) if oth else 0) <= 0.2)
    ev["explained"] = explained
    ev["cause_side"] = "Landlord" if explained else "IT Partner"
    return ev


def _lot_evidence(h: History, p: dict, fs: list[dict]) -> dict[str, Any]:
    grp = [f for f in fs if f["sig"] == "optic_module" and f["optic_lot"] == p["group"]]
    installed = [r for r in h.inventory if r["lot"] == p["group"]]
    at_start = sum(1 for r in installed if r["installed"] <= h.start.date().isoformat())
    remaining = sum(1 for r in installed if not r["removed"])
    total_start = sum(1 for r in h.inventory if r["installed"] <= h.start.date().isoformat())
    spares = sorted({r["lot"] for r in h.inventory if r["installed"] > h.start.date().isoformat()})
    return {"kind": "asset_lot", "lot": p["group"], "racks": len({f["rack"] for f in grp}), "rack_total": len(h.racks),
            "share_of_failures": round(100 * len(grp) / p["total"]), "share_of_base": round(100 * at_start / total_start),
            "installed_at_start": at_start, "still_installed": remaining, "in_spares": p["group"] in spares,
            "host_end": sum(1 for f in grp if _end(h, f) == "host"),
            "switch_end": sum(1 for f in grp if _end(h, f) == "switch"), "cause_side": "IT Partner"}


def _end(h: History, f: dict) -> str:
    return next(r["end"] for r in h.inventory if r["serial"] == f["module"])


def _fix_evidence(h: History, p: dict, fs: list[dict]) -> dict[str, Any]:
    cut = h.end - timedelta(days=RECURRENCE_DAYS)
    grp = [f for f in fs if f["sig"] == p["sig"] and f["fix"] == p["group"] and _t(f["resolved"]) <= cut]
    alt = [f for f in fs if f["sig"] == p["sig"] and f["fix"] and f["fix"] != p["group"] and _t(f["resolved"]) <= cut]
    gaps = sorted((_t(f["recurrence"]) - _t(f["resolved"])).days for f in grp if f["recurred"])
    return {"kind": "fix", "fix": p["group"], "repairs": len(grp), "recurred": sum(f["recurred"] for f in grp),
            "alt_fix": alt[0]["fix"] if alt else None, "alt_repairs": len(alt), "alt_recurred": sum(f["recurred"] for f in alt),
            "median_days_to_recur": median(gaps) if gaps else None, "units": len({f["unit"] for f in grp if f["recurred"]}),
            "cause_side": "IT Partner"}


def _is_repeat(f: dict, fs: list[dict]) -> bool:
    """The unit had already failed and been repaired in the 30 days before this failure."""
    return any(g["unit"] == f["unit"] and g["resolved"] and g["resolved"] < f["t"] and
               _t(f["t"]) - _t(g["resolved"]) <= timedelta(days=RECURRENCE_DAYS) for g in fs)


# --------------------------------------------------------------------------- the review
def _fmt_ratio(r: float) -> str:
    return "∞" if math.isinf(r) else f"{r:.1f}×"


def _fmt_p(p: float) -> str:
    return "< 0.000001" if p < 1e-6 else f"{p:.6f}" if p < 0.001 else f"{p:.3f}"


def _title(t: dict) -> str:
    sig = "All failures" if t["sig"] == ALL else SIGNATURES[t["sig"]]
    return {"cdu_warm": f"{sig} in racks served by {t['group']} while it ran warm",
            "fix": f"'{t['group']}' repairs of {sig} do not hold",
            "optic_lot": f"{sig} in lot {t['group']}",
            "cdu_row": f"{sig} in racks served by {t['group']}",
            "tray_slot": f"{sig} in tray slot {t['group']}"}.get(t["dim"], f"{sig} on rack {t['group']}")


def _weekly(h: History, fs: list[dict], t: dict) -> list[dict]:
    """Per week: failures in the group and in the rest of the hall; for a fix, the repairs that recurred and that held."""
    if t["dim"] == "cdu_warm":
        t = {**t, "dim": "cdu_row"}
    grp, oth = _select(fs, t)
    cut = _iso(h.end - timedelta(days=RECURRENCE_DAYS))
    out = []
    for w in range(int((h.end - h.start).days // 7)):
        a, b = _iso(h.start + timedelta(weeks=w)), _iso(h.start + timedelta(weeks=w + 1))
        if t["dim"] == "fix":
            reps = [f for f in grp if a <= f["t"] < b and f["resolved"] <= cut]
            out.append({"week": a[:10], "group": sum(1 for f in reps if f["recurred"]), "rest": sum(1 for f in reps if not f["recurred"])})
        else:
            out.append({"week": a[:10], "group": sum(1 for f in grp if a <= f["t"] < b), "rest": sum(1 for f in oth if a <= f["t"] < b)})
    return out


def _cdu_weekly(h: History, cdu: str) -> list[dict]:
    weeks = int((h.end - h.start).days // 7)
    out = []
    for w in range(weeks):
        a, b = h.start + timedelta(weeks=w), h.start + timedelta(weeks=w + 1)
        mine = [r["supply_c"] for r in h.cdu if r["cdu"] == cdu and a <= _t(r["timestamp"]) < b]
        oth = [r["supply_c"] for r in h.cdu if r["cdu"] != cdu and a <= _t(r["timestamp"]) < b]
        out.append({"week": a.date().isoformat(), "cdu": round(sum(mine) / len(mine), 2), "others": round(sum(oth) / len(oth), 2)})
    return out


def build_review(h: History) -> dict[str, Any]:
    fs = failures(h)
    attach_repairs(fs, h.tickets)
    episodes = warm_episodes(h)
    tests = _tests(h, fs, episodes)
    _classify(tests)
    _fold_nested(h, tests, first_failures(fs))
    flagged = sorted((t for t in tests if t["verdict"] == "pattern"), key=lambda t: t["p"])
    patterns = []
    for i, t in enumerate(flagged, 1):
        if t["dim"] == "fix":
            ev = _fix_evidence(h, t, fs)
        elif t["dim"] == "optic_lot":
            ev = _lot_evidence(h, t, fs)
        elif t["sig"] in TRAY_SIGS:
            ev = _cooling_evidence(h, t, fs, episodes)
        else:
            ev = {"kind": "location", "cause_side": "IT Partner"}
        comp = COOLING_COMPONENT if ev.get("kind") == "cooling" and ev["explained"] else COMPONENT.get(t["sig"], COMPONENT["xid_79"])
        raci = _raci(h.ia, comp)
        sel, _ = _select(fs, t)
        hours = sum((_t(f["resolved"]) - _t(f["t"])).total_seconds() / 3600 for f in sel if f["resolved"])
        key = f"{t['sig']}/{t['dim']}/{t['group']}"
        p = {"key": key, "number": f"P{i}", "title": _title(t), "signature": t["sig"], "signature_name": SIGNATURES[t["sig"]],
             "dimension": t["dim"], "dimension_name": DIMENSIONS[t["dim"]], "group": str(t["group"]), "family": t["family"],
             "events": t["events"], "expected": t["expected"], "ratio": round(t["ratio"], 2), "ratio_txt": _fmt_ratio(t["ratio"]),
             "p": t["p"], "p_txt": _fmt_p(t["p"]), "threshold_txt": _fmt_p(t["threshold"]),
             "failures": len(sel), "units": len({f["unit"] for f in sel}),
             "tickets": len({f["ticket"] for f in sel if f["ticket"]}), "unit_hours": round(hours),
             "first": min(f["t"] for f in sel), "last": max(f["t"] for f in sel),
             "evidence": ev, "raci": raci,
             "weekly": _weekly(h, fs, t)}
        if t["dim"] == "fix":
            p["repairs"], p["rest_rate_pct"] = t["repairs"], round(100 * t["rest_rate"], 1)
            p["rate_pct"] = round(100 * t["events"] / t["repairs"], 1)
        if ev.get("kind") == "cooling":
            p["cdu_weekly"] = _cdu_weekly(h, ev["cdu"])
        if t["dim"] in ("cdu_row", "cdu_warm"):
            p["racks"] = sorted(r["rack"] for r in h.racks if r["cdu"] == t["group"])
        patterns.append(p)
        p["_sel"] = {id(f) for f in sel}
    watch = []
    for t in sorted((t for t in tests if t["verdict"] == "watch"), key=lambda t: t["p"]):
        sel, _ = _select(fs, t)
        overlap = {p["number"]: n for p in patterns if (n := sum(1 for f in sel if id(f) in p["_sel"]))}
        watch.append({"key": f"{t['sig']}/{t['dim']}/{t['group']}", "title": _title(t), "signature": t["sig"], "dimension": t["dim"],
                      "group": str(t["group"]), "events": t["events"], "failures": len(sel), "expected": t["expected"],
                      "ratio_txt": _fmt_ratio(t["ratio"]), "p_txt": _fmt_p(t["p"]), "threshold_txt": _fmt_p(t["threshold"]),
                      "in_patterns": overlap, "repeats": sum(1 for f in sel if f["sig"] != ALL and _is_repeat(f, fs))})
    for p in patterns:
        del p["_sel"]
    tickets_on = Counter(x["rack"] for x in h.tickets)
    league = sorted((t for t in tests if t["sig"] == ALL and t["dim"] == "rack"), key=lambda t: (-tickets_on[t["group"]], t["group"]))[:5]
    league = [{"rack": t["group"], "units": t["events"], "failures": sum(1 for f in fs if f["rack"] == t["group"]),
               "tickets": sum(1 for x in h.tickets if x["rack"] == t["group"]), "expected": t["expected"],
               "ratio_txt": _fmt_ratio(t["ratio"]), "p_txt": _fmt_p(t["p"]), "verdict": t["verdict"],
               "signatures": len({f["sig"] for f in fs if f["rack"] == t["group"]})} for t in league]
    fam = Counter(t["family"] for t in tests)
    by_sig = Counter(f["sig"] for f in fs)
    return {
        "id": "FPR-" + h.start.strftime("%Y") + ("-H1" if h.start.month <= 6 else "-H2"),
        "window": {"start": h.manifest["window"]["start"], "end": h.manifest["window"]["end"], "hall": h.manifest["window"]["hall"],
                   "weeks": (h.end - h.start).days // 7, "racks": len(h.racks)},
        "method": {"chance_watch": round(len(tests) * WATCH_P), "alpha": ALPHA, "min_events": MIN_EVENTS, "min_ratio": MIN_RATIO, "watch_p": WATCH_P,
                   "recurrence_days": RECURRENCE_DAYS, "drift_c": DRIFT_C, "tests": dict(fam), "tests_total": len(tests),
                   "thresholds": {k: _fmt_p(ALPHA / v) for k, v in fam.items()}},
        "totals": {"failures": len(fs), "tickets": len(h.tickets), "matched": sum(1 for f in fs if f["ticket"]),
                   "by_signature": [{"sig": s, "name": SIGNATURES[s], "events": by_sig.get(s, 0)} for s in SIGNATURES]},
        "patterns": patterns,
        "watch": watch,
        "league": league,
        "episodes": episodes,
    }


def _matches(a: dict, p: dict) -> bool:
    dims = ("cdu_row", "cdu_warm") if a["dimension"] == "cdu_row" else (a["dimension"],)
    return p["signature"] == a["signature"] and p["dimension"] in dims and p["group"] == a["group"]


def score(review: dict, answer_key: list[dict]) -> dict[str, Any]:
    """Robustness scoring against a generated history's answer key."""
    planted = [a for a in answer_key if a["type"] != "decoy"]
    found, owner_ok = [], 0
    for a in planted:
        hit = next((p for p in review["patterns"] if _matches(a, p)), None)
        if hit:
            found.append(a)
            owner_ok += hit["raci"]["responsible" if a["owner"] == "IT Partner" else "accountable"] == a["owner"]
    decoys = [a for a in answer_key if a["type"] == "decoy"
              and any(p["dimension"] == "rack" and p["group"] == a["group"] for p in review["patterns"])]
    extra = [p["key"] for p in review["patterns"] if not any(_matches(a, p) for a in planted)]
    return {"planted": len(planted), "found": len(found), "owner_ok": owner_ok, "decoys_flagged": len(decoys),
            "other_flags": extra, "missed": [a["type"] for a in planted if a not in found]}


def followup(review: dict, tickets: list[dict], after: str) -> dict[str, list[dict]]:
    """Tickets in a later dataset that show a fix pattern still in use after the review meeting."""
    out: dict[str, list[dict]] = {}
    for p in review["patterns"]:
        if p["dimension"] != "fix" or not p["signature"].startswith("xid_"):
            continue
        xid = p["signature"].split("_")[1]
        out[p["key"]] = [{"number": t["number"], "opened_at": t["opened_at"], "unit": t["configuration_item"]}
                         for t in sorted(tickets, key=lambda t: t["opened_at"])
                         if t["opened_at"][:10] > after and t["close_code"] == p["group"]
                         and re.search(rf"\bXID {xid}\b", t["short_description"])]
    return out
