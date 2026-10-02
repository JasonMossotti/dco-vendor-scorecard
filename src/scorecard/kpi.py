"""Service level measurement from the Telemetry of Record.

Turns the engine's Context into *scored incidents* (one per Ticket of Record)
and computes every Critical Service Level and Key Measurement that the demo
data supports, for any time period. The same functions produce the monthly
view and each weekly view, and the browser app calls them with modified SLA
values to show what-if results.

Simplifications (stated in the report):
* No approved clock pauses exist in the data, so all lost capacity is
  Supplier-attributable.
* The 4-week data window is treated as the Measurement Period.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from scorecard.engine.core import _HOST_RE, Context, Finding, minutes_between

INTEGRITY_TYPES = {"clock_shift", "ticket_split", "ghost_engagement", "skipped_validation", "unverified_swap"}


@dataclass
class ScoredIncident:
    """One Ticket of Record, measured from telemetry."""

    key: str
    fault_class: str
    priority: str
    unit: str
    rack: str
    tickets: list[str]
    t0: datetime
    rts: datetime
    intervals: list[tuple[datetime, datetime]]
    gpus: int
    factor: float
    engaged_at: datetime | None
    early_failures: int = 0
    reopens: int = 0
    linked_child: bool = False
    is_child: bool = False
    validated: bool = True
    integrity_issue: bool = False
    vendor_restore_min: list[float] = field(default_factory=list)

    @property
    def measured_min(self) -> float:
        return sum(minutes_between(a, b) for a, b in self.intervals)

    @property
    def engaged_min(self) -> float | None:
        return minutes_between(self.t0, self.engaged_at) if self.engaged_at else None

    @property
    def first_time_fix(self) -> bool:
        return self.early_failures == 0 and self.reopens == 0 and not self.linked_child

    def lost_gpu_hours(self, start: datetime, end: datetime) -> float:
        total = 0.0
        for a, b in self.intervals:
            lo, hi = max(a, start), min(b, end)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600 * self.gpus * self.factor
        return total


# --------------------------------------------------------------------------- #
# Building scored incidents
# --------------------------------------------------------------------------- #
def _badge_engaged(ctx: Context, ticket: dict, t0: datetime, until: datetime) -> datetime | None:
    door = f"HALL-{ticket['hall'][-1]}"
    ins = [b["timestamp"] for b in ctx.badges_by_person.get(ticket["assigned_to"], [])
           if b["door"] == door and b["direction"] == "in" and t0 - timedelta(minutes=5) <= b["timestamp"] <= until]
    return min(ins) if ins else None


def _vendor_minutes(t: dict) -> float:
    return minutes_between(t["reported_outage_start"], t["resolved_at"])


def build_incidents(ctx: Context, findings: list[Finding]) -> list[ScoredIncident]:
    unvalidated = {n for f in findings if f.type == "skipped_validation" for n in f.tickets}
    integrity = {n for f in findings if f.type in INTEGRITY_TYPES for n in f.tickets}
    covered: set[str] = set()
    out: list[ScoredIncident] = []

    for fc_id in ("FC-GPU", "FC-LINK"):
        for tor in ctx.tors[fc_id]:
            refs = list(dict.fromkeys(tor.vendor_ticket_refs))
            if not refs or tor.final_rts is None:
                continue
            first = ctx.ticket_by_no[refs[0]]
            degraded = fc_id == "FC-LINK" and first["priority"] == "P3"
            out.append(ScoredIncident(
                key=refs[0], fault_class=fc_id, priority=first["priority"], unit=tor.unit_key, rack=first["rack"],
                tickets=refs, t0=tor.t0, rts=tor.final_rts, intervals=[(a, b) for a, b in tor.intervals],
                gpus=4, factor=0.25 if degraded else 1.0,
                engaged_at=_badge_engaged(ctx, first, tor.t0, tor.final_rts),
                early_failures=tor.early_failures, reopens=tor.reopens, linked_child=tor.has_linked_child,
                is_child=tor.parent_index is not None,
                validated=not (set(refs) & unvalidated), integrity_issue=bool(set(refs) & integrity),
                vendor_restore_min=[_vendor_minutes(ctx.ticket_by_no[n]) for n in refs],
            ))
            covered |= set(refs)

    for t in ctx.tickets:
        if t["number"] in covered:
            continue
        t0 = ctx.telemetry_t0(t)[0] or t["opened_at"]
        target, _ = ctx.validation_target(t)
        checks = [h["completed_at"] for h in ctx.health_by_target.get(target, [])
                  if t0 <= h["started_at"] and h["completed_at"] <= t["resolved_at"] + timedelta(minutes=15)]
        rts = max(checks) if checks else t["resolved_at"]
        cat = t["category"]
        gpus = 72 if cat == "switch_tray" else (4 if _HOST_RE.match(t["configuration_item"]) else 72) if cat == "leak" else 0
        out.append(ScoredIncident(
            key=t["number"], fault_class=t["_class"], priority=t["priority"], unit=t["_unit"], rack=t["rack"],
            tickets=[t["number"]], t0=t0, rts=rts, intervals=[(t0, rts)], gpus=gpus, factor=1.0,
            engaged_at=_badge_engaged(ctx, t, t0, rts), validated=t["number"] not in unvalidated,
            integrity_issue=t["number"] in integrity, vendor_restore_min=[_vendor_minutes(t)],
        ))
    out.sort(key=lambda i: i.t0)
    return out


# --------------------------------------------------------------------------- #
# Capacity
# --------------------------------------------------------------------------- #
def installed_gpu_hours(ctx: Context, start: datetime, end: datetime) -> dict[str, float]:
    """Installed production GPU-hours per rack. Deployment racks count from Validated Handoff."""
    handoff: dict[str, datetime] = {}
    for s in ctx.sched:
        if s["reason"] == "validated handoff":
            rack = s["node"].split("-")[0].upper()
            handoff[rack] = min(handoff.get(rack, s["timestamp"]), s["timestamp"])
    per_rack = ctx.sla["site"]["per_rack"]["gpus"]
    out = {}
    for r in ctx.src.get("topology")["racks"]:
        rid = r["rack"]
        begin = start if r["state"] == "production" else handoff.get(rid)
        if begin is None:
            continue
        lo = max(begin, start)
        if end > lo:
            out[rid] = (end - lo).total_seconds() / 3600 * per_rack
    return out


# --------------------------------------------------------------------------- #
# Period measurement
# --------------------------------------------------------------------------- #
def _pct(ok: int, n: int) -> float | None:
    return round(100.0 * ok / n, 3) if n else None


def _business_days(a: datetime, b: datetime) -> int:
    days, d = 0, a.date()
    while d < b.date():
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def measure_period(ctx: Context, incidents: list[ScoredIncident], findings: list[Finding],
                   start: datetime, end: datetime, sla: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Measure every supported CSL and KM for [start, end).

    Returns {metric_id: {"actual", "events", "misses", "detail"}}; actual is None
    when the period had nothing to measure.
    """
    sla = sla or ctx.sla          # an explicit SLA lets the app run what-if scenarios
    target = {p["id"]: p["restore_min"] for p in sla["priorities"]}
    in_p = [i for i in incidents if start <= i.t0 < end]
    m: dict[str, dict[str, Any]] = {}

    def put(mid: str, ok: int, n: int, detail: str, invert: bool = False) -> None:
        actual = _pct(n - ok if invert else ok, n)
        m[mid] = {"actual": actual, "events": n, "misses": (n - ok), "detail": detail}

    # CSL-01 / CSL-12: capacity-weighted availability, fleet and worst rack.
    installed = installed_gpu_hours(ctx, start, end)
    lost: dict[str, float] = defaultdict(float)
    for i in incidents:
        lost[i.rack] += i.lost_gpu_hours(start, end)
    total_inst, total_lost = sum(installed.values()), sum(lost[r] for r in installed)
    m["CSL-01"] = {"actual": round(100 * (1 - total_lost / total_inst), 3) if total_inst else None,
                   "events": None, "misses": None,
                   "detail": f"{total_lost:,.0f} capacity-weighted GPU-hours lost of {total_inst:,.0f} installed"}
    rack_avail = {r: 100 * (1 - lost[r] / h) for r, h in installed.items() if h}
    worst = min(rack_avail, key=rack_avail.get) if rack_avail else None
    m["CSL-12"] = {"actual": round(rack_avail[worst], 3) if worst else None, "events": None, "misses": None,
                   "detail": f"Worst rack {worst}: {lost[worst]:,.0f} GPU-hours lost" if worst else "n/a",
                   "rack": worst}

    # CSL-02 / KM-01 / KM-03: badge-verified engagement.
    for mid, prio, limit in (("CSL-02", "P1", 15), ("KM-01", "P2", 30), ("KM-03", "P3", 240)):
        xs = [i for i in in_p if i.priority == prio]
        ok = sum(1 for i in xs if i.engaged_min is not None and i.engaged_min <= limit)
        put(mid, ok, len(xs), f"{ok} of {len(xs)} {prio} incidents with a badge-verified technician within {limit} min")

    # CSL-03..05: restoration per Ticket of Record (TR-1/TR-2 applied).
    for mid, prio in (("CSL-03", "P1"), ("CSL-04", "P2"), ("CSL-05", "P3")):
        xs = [i for i in in_p if i.priority == prio]
        ok = sum(1 for i in xs if i.measured_min <= target[prio])
        put(mid, ok, len(xs), f"{ok} of {len(xs)} {prio} Tickets of Record restored within {target[prio] // 60} hrs")

    # CSL-06 first-time fix, CSL-08 repeat failure (any new fault within 30 days), KM-18 reopen rate.
    ok = sum(1 for i in in_p if i.first_time_fix)
    put("CSL-06", ok, len(in_p), f"{ok} of {len(in_p)} repairs fixed the first time")
    by_unit = defaultdict(list)
    for i in incidents:
        by_unit[i.unit].append(i)
    repeat = [i for i in in_p if i.early_failures or i.reopens or any(
        o is not i and i.rts < o.t0 <= i.rts + timedelta(days=30) for o in by_unit[i.unit])]
    m["CSL-08"] = {"actual": _pct(len(repeat), len(in_p)), "events": len(in_p), "misses": len(repeat),
                   "detail": f"{len(repeat)} of {len(in_p)} repaired units failed again within 30 days"}
    reopened = [i for i in in_p if i.early_failures or i.reopens]
    m["KM-18"] = {"actual": _pct(len(reopened), len(in_p)), "events": len(in_p), "misses": len(reopened),
                  "detail": f"{len(reopened)} Tickets of Record reopened under TR-1 or TR-2"}

    # CSL-07 validated return to service.
    rts_in = [i for i in incidents if start <= i.rts < end]
    ok = sum(1 for i in rts_in if i.validated)
    put("CSL-07", ok, len(rts_in), f"{ok} of {len(rts_in)} returns to service had the full validation checklist")

    # CSL-09 deployment milestones (Validated Handoff from the scheduler vs committed date).
    handoff: dict[str, datetime] = {}
    for s in ctx.sched:
        if s["reason"] == "validated handoff":
            rack = s["node"].split("-")[0].upper()
            handoff[rack] = min(handoff.get(rack, s["timestamp"]), s["timestamp"])
    due = [p for p in ctx.src.get("deployment_plan") if start <= p["committed_handoff"] < end]
    ok = sum(1 for p in due if p["rack"] in handoff and handoff[p["rack"]] <= p["committed_handoff"])
    put("CSL-09", ok, len(due), f"{ok} of {len(due)} racks due this period reached Validated Handoff on time")

    # CSL-10 staffing fill (badge-verified technician hours vs committed).
    committed = present = 0.0
    for r in ctx.roster:
        if r["role"] != "technician":
            continue
        lo, hi = max(r["shift_start"], start), min(r["shift_end"], end)
        if hi <= lo:
            continue
        hrs = (hi - lo).total_seconds() / 3600
        committed += hrs
        if any(b["door"] == "OPS-MAIN" and b["direction"] == "in"
               and r["shift_start"] - timedelta(hours=1) <= b["timestamp"] <= r["shift_end"]
               for b in ctx.badges_by_person.get(r["person_id"], [])):
            present += hrs
    m["CSL-10"] = {"actual": round(100 * present / committed, 3) if committed else None, "events": None,
                   "misses": None, "detail": f"{present:,.0f} of {committed:,.0f} committed technician hours badge-verified"}

    # CSL-11 record integrity (tickets resolved in period with no integrity finding).
    bad = {n for f in findings if f.type in INTEGRITY_TYPES for n in f.tickets}
    closed = [t for t in ctx.tickets if start <= t["resolved_at"] < end]
    ok = sum(1 for t in closed if t["number"] not in bad)
    put("CSL-11", ok, len(closed), f"{len(closed) - ok} of {len(closed)} closed tickets did not reconcile with telemetry")

    # KM-02 leak containment within 60 minutes.
    leaks = [i for i in in_p if i.fault_class == "FC-LEAK"]
    ok = 0
    for i in leaks:
        iso = [e["timestamp"] for e in ctx.redfish if e["event_type"] == "LeakIsolated" and e["rack"] == i.rack
               and i.t0 <= e["timestamp"] <= i.rts]
        ok += bool(iso and minutes_between(i.t0, min(iso)) <= 60)
    put("KM-02", ok, len(leaks), f"{ok} of {len(leaks)} leaks contained within 60 minutes")

    # KM-06 / KM-07 spares.
    minimum = {s["fru"]: s["minimum"] for s in sla["spares"]["minimum_stock_per_hall"]}
    counts = [c for c in ctx.cycle_counts if start <= c["counted_at"] < end]
    ok = sum(1 for c in counts if c["counted_qty"] >= minimum.get(c["fru"], 0))
    put("KM-06", ok, len(counts), f"{ok} of {len(counts)} counted spares classes at or above minimum")
    ok = sum(1 for c in counts if c["counted_qty"] == c["system_qty"])
    put("KM-07", ok, len(counts), f"{ok} of {len(counts)} cycle counts matched the ledger")

    # KM-08 RMA turnaround.
    rmas = [r for r in ctx.rma if start <= r["removed_at"] < end]
    ok = sum(1 for r in rmas if _business_days(r["removed_at"], r["shipped_at"]) <= 5)
    put("KM-08", ok, len(rmas), f"{ok} of {len(rmas)} failed parts shipped to the OEM within 5 business days")

    # KM-09 lemon units escalated.
    lemons = [f for f in findings if f.type == "lemon_unit" and f.observed_at and start <= f.observed_at < end]
    m["KM-09"] = {"actual": 0.0 if lemons else None, "events": len(lemons), "misses": len(lemons),
                  "detail": f"{len(lemons)} lemon unit(s) not escalated" if lemons else "No lemon units this period"}

    # KM-10 change compliance.
    fw = [e for e in ctx.inventory if e["property"] == "FirmwareVersion" and start <= e["observed_at"] < end]
    ok = sum(1 for e in fw if any(c["rack"] == e["rack"] and c["state"] == "Approved"
                                  and c["window_start"] <= e["observed_at"] <= c["window_end"] for c in ctx.cab))
    put("KM-10", ok, len(fw), f"{ok} of {len(fw)} firmware changes covered by an approved change record")

    # KM-16 chronic units (> 12 down-hours in the period).
    down = defaultdict(float)
    for i in incidents:
        down[i.unit] += sum(max(0.0, (min(b, end) - max(a, start)).total_seconds() / 3600) for a, b in i.intervals)
    chronic = sorted(u for u, h in down.items() if h > 12)
    m["KM-16"] = {"actual": float(len(chronic)), "events": None, "misses": None,
                  "detail": ", ".join(chronic) if chronic else "None"}

    # KM-17 redundancy exposure hours (power shelf and CDU pump).
    hrs = 0.0
    for i in in_p:
        if i.fault_class in ("FC-SHELF", "FC-CDU"):
            if i.fault_class == "FC-SHELF":
                ends = [e["timestamp"] for e in ctx.redfish if e["event_type"] == "PowerRedundancyRestored"
                        and e["rack"] == i.rack and e["timestamp"] >= i.t0]
            else:
                ends = [e["timestamp"] for e in ctx.bms if e["alarm"] == "PumpRedundancyLost" and e["state"] == "cleared"
                        and e["timestamp"] >= i.t0]
            hrs += ((min(ends) if ends else i.rts) - i.t0).total_seconds() / 3600
    m["KM-17"] = {"actual": round(hrs, 1), "events": None, "misses": None,
                  "detail": f"{hrs:.1f} hours running without power or cooling redundancy"}
    return m
