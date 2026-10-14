"""Fleet availability and repair turnaround for Site AUS-1: the rollup behind the Availability tab.

Reads only records that already exist (``data/sample/``) and the engine's own measurement; it scores
nothing new, so no headline number moves. Four views:

1. Availability from the scheduler's side: GPU-hours a job could not land on, from the scheduler's
   node states, against installed GPU-hours (Hall B racks count from their validated handoff).
2. GPU-hours lost by owner under the contracts: the IT Partner's share is exactly CSL-01's
   capacity-weighted loss; the Landlord's is each rack power loss up to the handoff (Interface
   Agreement FA-1 and FA-3). A bridge walks the scheduler's total to the contracts' total, so every
   GPU-hour of difference has a named reason.
3. Repair turnaround per ticket, in stages: fault signal, ticket, acknowledged, technician badged into
   the hall, repair, validated return to service. A stage with no record says so; nothing is guessed.
4. Spares and RMA: on-hand stock against the minimums, cycle counts, and failed parts shipped to the OEM,
   reconciled with the parts the tickets say were removed.

Beside the bridge, not in it: GPU-hours idle on storage (the storage telemetry, src/scorecard/telemetry_storage.py).
The scheduler kept those nodes in service while their jobs waited on I/O, so neither total counts them.

A finding means records do not reconcile, not that anyone misled.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scorecard.connectors import FileConnector
from scorecard.engine import run_engine
from scorecard.engine.core import _HOST_RE
from scorecard.kpi import _business_days, build_incidents, installed_gpu_hours, measure_period
from scorecard.sla_model import load_sla

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample"
DAY = timedelta(days=1)
GPUS_PER_NODE = 4

CAUSES = {   # ticket category -> (cause label, order)
    "tray_gpu": "Compute tray (GPU)", "optic_link": "Optic or link", "switch_tray": "NVLink switch tray",
    "leak": "Coolant leak", "rack_facility": "Rack power loss", "psu": "PSU", "power_shelf": "Power shelf",
    "cdu_pump": "CDU pump",
}
OWNERS = ["IT Partner", "Landlord", "OEM", "Customer", "Planned work"]
BRIDGE = {
    "before_drain": "The contract clock starts at the first fault signal; the scheduler drained the node a little later",
    "not_held": "A repair that did not hold (TR-1, TR-2): the contract counts from the first fault, through the time the node ran between the failed repair and the repeat fault",
    "in_service": "Counted by the contract while the scheduler kept the node in service",
    "overlap": "Two incidents overlapped on the same node; the contract counts each one's hours",
    "degraded": "Degraded links count at 25% under the contract; the scheduler kept the node in service",
    "after_rts": "The node went back to the scheduler after its validated return to service",
    "unmatched": "Drained with no incident or Landlord event on record",
}
STAGES = [("detect", "Detect", "Fault signal to ticket"), ("ack", "Acknowledge", "Ticket to acknowledged"),
          ("travel", "Reach the rack", "Acknowledged to on site (badge into the hall)"), ("repair", "Repair", "On site to repair done"),
          ("validate", "Validate", "Repair to validated return to service")]


def _iso(t: datetime | None) -> str | None:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _min(a: datetime | None, b: datetime | None) -> float | None:
    return round((b - a).total_seconds() / 60, 1) if a and b else None


def _hrs(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def _union(iv: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[list[datetime]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _overlap(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> float:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return _hrs(lo, hi) if hi > lo else 0.0


def _pctile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo = int(k)
    return round(s[lo] + (s[min(lo + 1, len(s) - 1)] - s[lo]) * (k - lo), 1)


def _med(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


class Rollup:
    """Runs the IT engine once and keeps what every view needs."""

    def __init__(self, data_dir: Path = SAMPLE) -> None:
        self.data_dir = Path(data_dir)
        self.sla = load_sla()
        self.run = run_engine(self.sla, FileConnector(self.data_dir))
        self.ctx = ctx = self.run.context
        self.findings = self.run.findings
        self.incidents = build_incidents(ctx, self.findings)
        self.start, self.end = ctx.window_start, ctx.window_end
        topo = ctx.src.get("topology")["racks"]
        self.hall = {r["rack"]: r["hall"] for r in topo}
        self.nodes = {r["rack"]: [t["host"] for t in r["compute_trays"]] for r in topo}
        self.begin = self._installed_from()
        self.outages = self._outages()
        self.landlord = [x for x in ctx.rack_power_loss if x["rack"] in self.begin]
        self.finding_by_ticket: dict[str, list[str]] = defaultdict(list)
        for f in self.findings:
            for n in f.tickets:
                self.finding_by_ticket[n].append(f.id)

    # ------------------------------------------------------------------ capacity
    def _installed_from(self) -> dict[str, datetime]:
        """When each rack starts counting as installed: the window start, or a Hall B rack's validated handoff."""
        handoff: dict[str, datetime] = {}
        for s in self.ctx.sched:
            if s["reason"] == "validated handoff":
                rack = self.node_rack(s["node"])
                handoff[rack] = min(handoff.get(rack, s["timestamp"]), s["timestamp"])
        out = {}
        for r in self.ctx.src.get("topology")["racks"]:
            begin = self.start if r["state"] == "production" else handoff.get(r["rack"])
            if begin is not None and begin < self.end:
                out[r["rack"]] = max(begin, self.start)
        return out

    def installed(self, a: datetime, b: datetime) -> dict[str, float]:
        return installed_gpu_hours(self.ctx, a, b)

    def node_rack(self, node: str) -> str:
        return node.split("-")[0].upper()

    def _outages(self) -> list[dict[str, Any]]:
        """Scheduler outages: a node drained or down until it went back to idle, clipped to its rack's installed time."""
        by_node: dict[str, list[dict]] = defaultdict(list)
        for s in self.ctx.sched:
            by_node[s["node"]].append(s)
        out = []
        for node, xs in by_node.items():
            rack = self.node_rack(node)
            if rack not in self.begin:
                continue
            down = None
            for s in sorted(xs, key=lambda s: s["timestamp"]):
                if s["state"] in ("drain", "down"):
                    down = down or s
                elif down is not None:
                    out.append({"node": node, "rack": rack, "a": down["timestamp"], "b": s["timestamp"], "reason": down["reason"]})
                    down = None
            if down is not None:
                out.append({"node": node, "rack": rack, "a": down["timestamp"], "b": self.end, "reason": down["reason"]})
        for o in out:
            o["a"], o["b"] = max(o["a"], self.begin[o["rack"]], self.start), min(o["b"], self.end)
        return [o for o in out if o["b"] > o["a"]]

    # ------------------------------------------------------------------ incidents to nodes
    def incident_nodes(self, i) -> list[str]:
        if i.gpus == 0:
            return []
        t = self.ctx.ticket_by_no[i.key]
        if i.gpus == GPUS_PER_NODE:
            ci = t["configuration_item"]
            return [ci] if _HOST_RE.match(ci) else []
        return list(self.nodes.get(i.rack, []))

    def contract_intervals(self) -> dict[str, list[dict[str, Any]]]:
        """Per node, every interval the contracts count as lost: IT incidents and Landlord rack power losses."""
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for i in self.incidents:
            if i.rack not in self.begin:
                continue
            repeat = bool(i.early_failures or i.reopens or i.linked_child)
            for n in self.incident_nodes(i):
                for a, b in i.intervals:
                    a, b = max(a, self.start), min(b, self.end)
                    if b > a:
                        out[n].append({"a": a, "b": b, "owner": "IT Partner", "key": i.key, "factor": i.factor, "repeat": repeat,
                                       "first": i.intervals[0][0]})
        for x in self.landlord:
            for n in self.nodes[x["rack"]]:
                a, b = max(x["t0"], self.start), min(x["handoff"], self.end)
                if b > a:
                    out[n].append({"a": a, "b": b, "owner": "Landlord", "key": x["rack"], "factor": 1.0, "repeat": False, "first": x["t0"]})
        return out

    # ------------------------------------------------------------------ availability
    def lost_by_owner(self, a: datetime, b: datetime) -> dict[str, float]:
        it = sum(i.lost_gpu_hours(a, b) for i in self.incidents if i.rack in self.begin)
        ll = 0.0
        for x in self.landlord:
            lo, hi = max(x["t0"], a), min(x["handoff"], b)
            if hi > lo:
                ll += _hrs(lo, hi) * self.sla["site"]["per_rack"]["gpus"]
        return {"IT Partner": it, "Landlord": ll, "OEM": 0.0, "Customer": 0.0, "Planned work": 0.0}

    def sched_lost(self, a: datetime, b: datetime, hall: str | None = None) -> float:
        return sum(_overlap((o["a"], o["b"]), (a, b)) * GPUS_PER_NODE for o in self.outages
                   if hall is None or self.hall[o["rack"]] == hall)

    def bridge(self) -> dict[str, Any]:
        """Walk the scheduler's GPU-hours to the contracts' GPU-hours, node by node, so every difference has a reason."""
        con = self.contract_intervals()
        sched: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        for o in self.outages:
            sched[o["node"]].append((o["a"], o["b"]))
        degraded: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        for n, xs in con.items():
            for x in xs:
                if x["factor"] < 1:
                    degraded[n].append((x["a"], x["b"]))
        b = Counter()
        g = GPUS_PER_NODE
        for n in set(con) | set(sched):
            full = [x for x in con.get(n, []) if x["factor"] >= 1]
            for x in con.get(n, []):
                if x["factor"] < 1:
                    b["degraded"] += _hrs(x["a"], x["b"]) * g * x["factor"]
            cu = _union([(x["a"], x["b"]) for x in full])
            b["overlap"] += (sum(_hrs(x["a"], x["b"]) for x in full) - sum(_hrs(p, q) for p, q in cu)) * g
            su = _union(sched.get(n, []))
            cuts = sorted({t for iv in cu + su for t in iv})
            for p, q in zip(cuts, cuts[1:]):
                in_c = any(x <= p and q <= y for x, y in cu)
                in_s = any(x <= p and q <= y for x, y in su)
                h = _hrs(p, q) * g
                if in_c and in_s:
                    b["both"] += h
                elif in_c:
                    cover = [x for x in full if x["a"] <= p and q <= x["b"]]
                    drained_later = any(s_a >= q and any(s_a < x["b"] for x in cover) for s_a, _ in su)
                    if drained_later and not any(s_b <= p and s_b > x["first"] for _, s_b in su for x in cover):
                        b["before_drain"] += h
                    elif any(x["repeat"] for x in cover):
                        b["not_held"] += h
                    else:
                        b["in_service"] += h
                elif in_s:
                    ends = [y for _, y in cu if y <= p]
                    if ends and _hrs(max(ends), p) <= 24:
                        b["after_rts"] += h
                    elif any(x <= p and q <= y for x, y in degraded.get(n, [])):
                        b["degraded_drained"] += h
                    else:
                        b["unmatched"] += h
        sched_total = self.sched_lost(self.start, self.end)
        owner = self.lost_by_owner(self.start, self.end)
        contract_total = sum(owner.values())
        rows = [{"key": "sched", "label": "GPU-hours the scheduler could not place work on", "hours": round(sched_total, 1)}]
        for k, sign in (("after_rts", -1), ("unmatched", -1), ("degraded_drained", -1), ("before_drain", 1), ("not_held", 1),
                        ("in_service", 1), ("overlap", 1), ("degraded", 1)):
            if round(b[k], 1):
                rows.append({"key": k, "label": BRIDGE.get(k, "Drained during a degraded-link incident"), "hours": round(sign * b[k], 1)})
        rows.append({"key": "contract", "label": "GPU-hours lost under the contracts (all owners)", "hours": round(contract_total, 1)})
        walked = sched_total + sum(r["hours"] for r in rows[1:-1])
        return {"rows": rows, "closes": abs(walked - contract_total) < 0.15, "gap": round(contract_total - walked, 2)}

    # ------------------------------------------------------------------ causes and days
    def by_cause(self) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for i in self.incidents:
            if i.rack not in self.begin:
                continue
            cat = self.ctx.ticket_by_no[i.key]["category"]
            r = rows.setdefault(cat, {"cause": CAUSES.get(cat, cat), "category": cat, "incidents": 0, "it": 0.0, "landlord": 0.0,
                                      "gpus_out": 0, "racks": Counter()})
            r["incidents"] += 1
            h = i.lost_gpu_hours(self.start, self.end)
            r["it"] += h
            r["racks"][i.rack] += h
            r["gpus_out"] += bool(i.gpus)
        for x in self.landlord:
            r = rows.setdefault("rack_facility", {"cause": CAUSES["rack_facility"], "category": "rack_facility", "incidents": 0,
                                                  "it": 0.0, "landlord": 0.0, "gpus_out": 0, "racks": Counter()})
            h = max(0.0, _hrs(max(x["t0"], self.start), min(x["handoff"], self.end))) * self.sla["site"]["per_rack"]["gpus"]
            r["landlord"] += h
            r["racks"][x["rack"]] += h
        total = sum(r["it"] + r["landlord"] for r in rows.values()) or 1.0
        out = []
        for r in rows.values():
            worst = r["racks"].most_common(1)[0] if r["racks"] and r["racks"].most_common(1)[0][1] > 0 else None
            out.append({"cause": r["cause"], "category": r["category"], "incidents": r["incidents"],
                        "it": round(r["it"], 1), "landlord": round(r["landlord"], 1), "total": round(r["it"] + r["landlord"], 1),
                        "share": round(100 * (r["it"] + r["landlord"]) / total, 1),
                        "worst_rack": worst[0] if worst else None, "worst_hours": round(worst[1], 1) if worst else None})
        return sorted(out, key=lambda r: (-r["total"], r["cause"]))

    def days(self) -> list[dict[str, Any]]:
        out = []
        d = self.start
        cause_of = {i.key: self.ctx.ticket_by_no[i.key]["category"] for i in self.incidents}
        while d < self.end:
            e = min(d + DAY, self.end)
            inst = self.installed(d, e)
            row: dict[str, Any] = {"date": d.strftime("%Y-%m-%d"), "halls": {}}
            for hall in sorted(set(self.hall.values())):
                ih = sum(h for r, h in inst.items() if self.hall[r] == hall)
                lh = self.sched_lost(d, e, hall)
                row["halls"][hall] = {"installed": round(ih, 1), "sched_lost": round(lh, 2),
                                      "pct": round(100 * (1 - lh / ih), 3) if ih else None}
            causes: Counter = Counter()
            for i in self.incidents:
                if i.rack in self.begin:
                    causes[cause_of[i.key]] += i.lost_gpu_hours(d, e)
            ll = self.lost_by_owner(d, e)["Landlord"]
            row["it_by_cause"] = {k: round(v, 2) for k, v in causes.items() if v > 0}
            row["landlord"] = round(ll, 2)
            tot_i = sum(inst.values())
            tot_s = self.sched_lost(d, e)
            row["installed"] = round(tot_i, 1)
            row["sched_lost"] = round(tot_s, 2)
            row["pct"] = round(100 * (1 - tot_s / tot_i), 3) if tot_i else None
            out.append(row)
            d = e
        return out

    def weeks(self) -> list[dict[str, Any]]:
        """The weekly review's weeks: scheduler availability, CSL-01 as the scorecards measure it, and the self-report."""
        out = []
        for w in self.ctx.vendor_weekly:
            a, b = w["week_start"], w["week_end"]
            inst = sum(self.installed(a, b).values())
            m = measure_period(self.ctx, self.incidents, self.findings, a, b)
            own = self.lost_by_owner(a, b)
            sl = self.sched_lost(a, b)
            out.append({"start": _iso(a), "end": _iso(b), "installed": round(inst, 1),
                        "sched_lost": round(sl, 1), "sched_pct": round(100 * (1 - sl / inst), 3) if inst else None,
                        "csl01": m["CSL-01"]["actual"], "it_lost": round(own["IT Partner"], 1), "landlord_lost": round(own["Landlord"], 1),
                        "reported": w.get("gpu_availability_pct")})
        return out

    # ------------------------------------------------------------------ repair turnaround
    def _validated(self, t: dict, t0: datetime) -> datetime | None:
        target, _ = self.ctx.validation_target(t)
        checks = [h["completed_at"] for h in self.ctx.health_by_target.get(target, [])
                  if t0 <= h["started_at"] and h["completed_at"] <= t["resolved_at"] + timedelta(minutes=15)]
        return max(checks) if checks else None

    def _on_site(self, t: dict, after: datetime) -> datetime | None:
        door = f"HALL-{t['hall'][-1]}"
        ins = [b["timestamp"] for b in self.ctx.badges_by_person.get(t["assigned_to"], [])
               if b["door"] == door and b["direction"] == "in" and after - timedelta(minutes=5) <= b["timestamp"] <= t["resolved_at"]]
        return min(ins) if ins else None

    @staticmethod
    def _repair_note(t: dict) -> datetime | None:
        for n in t["work_notes"]:
            first = n["text"].split()[0] if n["text"] else ""
            if first not in ("Acknowledged.", "On", "Validation"):
                return n["at"] if isinstance(n["at"], datetime) else datetime.fromisoformat(n["at"].replace("Z", "+00:00"))
        return None

    def tickets(self) -> list[dict[str, Any]]:
        out = []
        tor = {n: i for i in self.incidents for n in i.tickets}
        for t in self.ctx.tickets:
            if not (self.start <= t["opened_at"] < self.end):
                continue
            t0 = self.ctx.telemetry_t0(t)[0]
            start = t0 or t["opened_at"]
            on = self._on_site(t, t["opened_at"])
            rep = self._repair_note(t)
            val = self._validated(t, start)
            marks = {"t0": t0, "opened": t["opened_at"], "ack": t["acknowledged_at"], "on_site": on, "repair": rep, "validated": val}
            # The stages run one after another: each boundary is the later of its own record and the boundary before it, so
            # the stages add up to the measured time. A record earlier than the one before it (a technician badged in
            # before acknowledging the ticket) makes its stage zero and is listed.
            stages: dict[str, float | None] = {}
            early: list[str] = []
            prev = start
            for k, mark in (("detect", t["opened_at"]), ("ack", t["acknowledged_at"]), ("travel", on), ("repair", rep), ("validate", val)):
                if mark is None:
                    stages[k] = None
                    continue
                if mark < prev:
                    early.append(k)
                stages[k] = _min(prev, max(prev, mark))
                prev = max(prev, mark)
            missing = [k for k, v in (("fault signal", t0), ("badge into the hall", on), ("repair note", rep), ("validation record", val)) if v is None]
            i = tor.get(t["number"])
            out.append({
                "ticket": t["number"], "priority": t["priority"], "category": t["category"], "cause": CAUSES.get(t["category"], t["category"]),
                "rack": t["rack"], "hall": t["hall"], "ci": t["configuration_item"], "person": t["assigned_to"],
                "close_code": t["close_code"], "parts": [p["part"] for p in t.get("parts_used") or []],
                "marks": {k: _iso(v) for k, v in marks.items()}, "stages": stages,
                "measured_min": _min(start, val or t["resolved_at"]),
                "reported_min": _min(t["reported_outage_start"], t["resolved_at"]),
                "missing": missing, "early": early,
                "fa3": t["category"] == "rack_facility" and t0 is not None and t0 > t["opened_at"],
                "tor": i.key if i and len(i.tickets) > 1 else None, "findings": sorted(set(self.finding_by_ticket.get(t["number"], []))),
            })
        return out

    @staticmethod
    def stage_summary(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for t in tickets:
            groups[t["cause"]].append(t)
        rows = []
        for cause, ts in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            r: dict[str, Any] = {"cause": cause, "tickets": len(ts), "stages": {}}
            for k, _, _ in STAGES:
                xs = [t["stages"][k] for t in ts if t["stages"][k] is not None and t["stages"][k] >= 0]
                r["stages"][k] = {"median": _med(xs), "p90": _pctile(xs, 0.9), "n": len(xs)}
            meas = [t["measured_min"] for t in ts if t["measured_min"] is not None]
            rep = [t["reported_min"] for t in ts if t["reported_min"] is not None]
            r["measured"] = {"median": _med(meas), "p90": _pctile(meas, 0.9)}
            r["reported"] = {"median": _med(rep), "p90": _pctile(rep, 0.9)}
            r["missing"] = sum(1 for t in ts if t["missing"])
            rows.append(r)
        return rows

    def restoration(self) -> list[dict[str, Any]]:
        """Restoration per Ticket of Record, as CSL-03 to CSL-05 measure it, against the IT Partner's own ticket times."""
        groups: dict[str, list] = defaultdict(list)
        for i in self.incidents:
            if self.start <= i.t0 < self.end:
                groups[CAUSES.get(self.ctx.ticket_by_no[i.key]["category"], i.key)].append(i)
        rows = []
        for cause, xs in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            meas = [i.measured_min for i in xs]
            rep = [m for i in xs for m in i.vendor_restore_min]
            rows.append({"cause": cause, "tors": len(xs), "tickets": sum(len(i.tickets) for i in xs),
                         "merged": sum(1 for i in xs if len(i.tickets) > 1),
                         "measured": {"median": _med(meas), "p90": _pctile(meas, 0.9), "max": round(max(meas), 1)},
                         "reported": {"median": _med(rep), "p90": _pctile(rep, 0.9), "max": round(max(rep), 1)}})
        return rows

    # ------------------------------------------------------------------ spares and RMA
    def spares(self) -> dict[str, Any]:
        ctx = self.ctx
        minimum = {s["fru"]: s["minimum"] for s in self.sla["spares"]["minimum_stock_per_hall"]}
        ledger: dict[str, list[dict]] = defaultdict(list)
        for x in ctx.ledger:
            ledger[x["fru"]].append(x)
        counts: dict[str, list[dict]] = defaultdict(list)
        for c in ctx.cycle_counts:
            counts[c["fru"]].append(c)
        frus = sorted(set(minimum) | set(ledger) | set(counts), key=lambda f: (f not in minimum, f))
        rows = []
        n_days = (self.end - self.start).days
        for f in frus:
            xs = sorted(ledger.get(f, []), key=lambda x: x["timestamp"])
            cs = sorted(counts.get(f, []), key=lambda c: c["counted_at"])
            if xs:
                opening = xs[0]["balance_after"] - xs[0]["qty"]
            elif cs:
                opening = cs[0]["system_qty"]
            else:
                opening = None
            daily, bal = [], opening
            for k in range(n_days):
                de = self.start + (k + 1) * DAY
                lows = [bal] if bal is not None else []
                for x in xs:
                    if self.start + k * DAY <= x["timestamp"] < de:
                        bal = x["balance_after"]
                        lows.append(bal)
                daily.append(min(lows) if lows else None)
            mn = minimum.get(f)
            below = sum(1 for v in daily if mn is not None and v is not None and v < mn)
            rows.append({"fru": f, "minimum": mn, "opening": opening, "closing": bal, "low": min((v for v in daily if v is not None), default=None),
                         "daily_low": daily, "days_below": below if mn is not None else None,
                         "issued": -sum(x["qty"] for x in xs if x["transaction"] == "issue"),
                         "received": sum(x["qty"] for x in xs if x["transaction"] == "receive"),
                         "adjusted": sum(x["qty"] for x in xs if x["transaction"] not in ("issue", "receive")),
                         "counts": [{"at": _iso(c["counted_at"]), "system": c["system_qty"], "counted": c["counted_qty"]} for c in cs]})
        # RMA: failed parts the tickets say were removed, against the shipments to the OEM.
        removed = [(t["number"], p) for t in ctx.tickets if self.start <= t["opened_at"] < self.end
                   for p in t.get("parts_used") or [] if p.get("removed_serial")]
        shipped = {r["serial"]: r for r in ctx.rma}
        rma = []
        for r in sorted(ctx.rma, key=lambda r: r["removed_at"]):
            if not (self.start <= r["removed_at"] < self.end):
                continue
            days = _business_days(r["removed_at"], r["shipped_at"]) if r["shipped_at"] else None
            rma.append({"ticket": r["ticket"], "fru": r["fru"], "removed": _iso(r["removed_at"]), "shipped": _iso(r["shipped_at"]),
                        "business_days": days, "open_at_end": r["shipped_at"] is None or r["shipped_at"] >= self.end})
        no_rma = [{"ticket": n, "part": p["part"]} for n, p in removed if p["removed_serial"] not in shipped]
        by_fru: dict[str, list[int]] = defaultdict(list)
        for r in rma:
            if r["business_days"] is not None:
                by_fru[r["fru"]].append(r["business_days"])
        m = measure_period(ctx, self.incidents, self.findings, self.start, self.end)
        kms = []
        for kid in ("KM-06", "KM-07", "KM-08"):
            k = next(x for x in self.sla["key_measurements"] if x["id"] == kid)
            kms.append({"id": kid, "name": k["name"], "target": k["target"], "actual": m[kid]["actual"], "detail": m[kid]["detail"],
                        "met": None if m[kid]["actual"] is None else m[kid]["actual"] >= k["target"]})
        return {"rows": rows, "rma": rma, "no_rma": no_rma, "removed": len(removed),
                "rma_by_fru": [{"fru": f, "shipped": len(v), "median_days": _med(v), "max_days": max(v), "within_5": sum(1 for d in v if d <= 5)}
                               for f, v in sorted(by_fru.items())],
                "kms": kms, "days": n_days}


def storage_idle(data_dir: Path = SAMPLE) -> dict[str, Any] | None:
    """GPU-hours running jobs waited on storage behind a flapping storage fabric uplink (None without storage telemetry)."""
    tel = ROOT / "data" / "telemetry" if Path(data_dir).resolve() == SAMPLE.resolve() else Path(data_dir)
    if not (tel / "storage" / "manifest.json").exists() or not (tel / "mgmt" / "manifest.json").exists():
        return None
    import yaml
    from scorecard import telemetry_storage as TS
    t = TS.load(tel / "storage", data_dir, tel / "mgmt")
    cfg = yaml.safe_load((ROOT / "config" / "telemetry_storage.yaml").read_text(encoding="utf-8"))
    eps = sorted(TS.stall_hours(t, cfg), key=lambda x: x["a"])
    return {"gpu_hours": round(sum(x["gpu_hours"] for x in eps), 1),
            "episodes": [{"from": t.iso(x["a"]), "minutes": x["b"] - x["a"], "uplink": f"{x['switch']} {x['ifName']}", "racks": x["racks"],
                          "nodes": x["nodes"], "gpu_hours": x["gpu_hours"]} for x in eps]}


def build(data_dir: Path = SAMPLE) -> dict[str, Any]:
    """Everything the Availability tab, the report, the Overview tile, and the weekly line need."""
    R = Rollup(data_dir)
    m = measure_period(R.ctx, R.incidents, R.findings, R.start, R.end)
    installed = R.installed(R.start, R.end)
    total_inst = sum(installed.values())
    sched = R.sched_lost(R.start, R.end)
    owner = R.lost_by_owner(R.start, R.end)
    tickets = R.tickets()
    halls = {}
    for hall in sorted(set(R.hall.values())):
        ih = sum(h for r, h in installed.items() if R.hall[r] == hall)
        lh = R.sched_lost(R.start, R.end, hall)
        halls[hall] = {"installed": round(ih, 1), "sched_lost": round(lh, 1), "pct": round(100 * (1 - lh / ih), 3) if ih else None,
                       "racks": sum(1 for r in installed if R.hall[r] == hall)}
    by_reason: Counter = Counter()
    for o in R.outages:
        by_reason[o["reason"].split(" (")[0]] += _hrs(o["a"], o["b"]) * GPUS_PER_NODE
    return {
        "window": {"start": _iso(R.start), "end": _iso(R.end)},
        "installed": round(total_inst, 1), "halls": halls,
        "sched": {"lost": round(sched, 1), "pct": round(100 * (1 - sched / total_inst), 3), "outages": len(R.outages),
                  "by_reason": [{"reason": k, "hours": round(v, 1)} for k, v in by_reason.most_common()]},
        "csl01": {"actual": m["CSL-01"]["actual"], "detail": m["CSL-01"]["detail"],
                  "minimum": next(c for c in R.sla["critical_service_levels"] if c["id"] == "CSL-01")["minimum"]},
        "csl12": {"actual": m["CSL-12"]["actual"], "rack": m["CSL-12"].get("rack"), "detail": m["CSL-12"]["detail"]},
        "owners": [{"owner": k, "hours": round(owner[k], 1)} for k in OWNERS],
        "contract_lost": round(sum(owner.values()), 1),
        "bridge": R.bridge(),
        "storage_idle": storage_idle(data_dir),
        "causes": R.by_cause(),
        "landlord_events": [{"rack": x["rack"], "t0": _iso(x["t0"]), "handoff": _iso(x["handoff"]),
                             "hours": round(_hrs(max(x["t0"], R.start), min(x["handoff"], R.end)) * R.sla["site"]["per_rack"]["gpus"], 1)}
                            for x in R.landlord],
        "days": R.days(), "weeks": R.weeks(),
        "stages": [{"key": k, "short": a, "name": n} for k, a, n in STAGES],
        "tickets": tickets, "stage_summary": R.stage_summary(tickets), "restoration": R.restoration(),
        "spares": R.spares(),
        "findings": {f.id: {"type": f.type, "title": f.title} for f in R.findings},
    }
