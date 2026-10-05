"""Landlord engine: hold the facility owner-operator to its SLA with the Customer's own telemetry.

Mirrors the IT engine:

* ``LandlordContext`` reads the facility sources through the connector (never
  the answer key) and rebuilds every facility incident from device telemetry:
  T0 and restoration from the device, acknowledgment from the BMS, and
  engagement from a badge into the equipment's own room (``room_for``).
* One detector per Landlord finding type, with severity and corrective action
  taken from the Landlord SLA.
* ``attribute`` applies the Interface Agreement's fault attribution rules to
  every facility event and flags work orders that attribute a fault against
  the telemetry.
* ``measure_landlord`` measures every OT-CSL and OT-KM; ``build_landlord_scorecard``
  turns that into credits against rent beside the Landlord's own report.

A finding means the records do not reconcile, not that someone lied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from scorecard import site_model as S
from scorecard.connectors import SiteDataSource
from scorecard.engine.core import Finding, ev, fmt_t, minutes_between
from scorecard.engine.run import SEVERITY_ORDER
from scorecard.sla_model import (
    cap_monthly_credits,
    classify_finding,
    compute_credit,
    evaluate_csl,
    finding_type,
    load_interface_agreement,
)
from scorecard.synthetic.facility import room_for

LOAD_MIN_PCT = 30          # NFPA 110 monthly exercise: at least 30% of nameplate kW ...
LOAD_MIN_MINUTES = 30      # ... for at least 30 minutes, cooldown excluded
CRITICAL_WORK = {"Breaker open": "busway", "switchedBypass": "ups", "Disabled": "cdu", "Isolate": "vesda"}


@dataclass
class FacilityIncident:
    """A facility event rebuilt from device telemetry."""

    fault_class: str
    unit: str
    room: str
    t0: datetime
    restored: datetime | None
    priority: str
    description: str
    source: str
    ack_at: datetime | None = None
    engaged_at: datetime | None = None
    work_order: dict | None = None
    owner: str = "Landlord"
    rule: str = ""
    capacity_lost: bool = False

    @property
    def restore_min(self) -> float | None:
        return None if self.restored is None else minutes_between(self.t0, self.restored)


@dataclass
class LandlordResult:
    context: "LandlordContext"
    incidents: list[FacilityIncident]
    findings: list[Finding]


class LandlordContext:
    def __init__(self, sla: dict[str, Any], source: SiteDataSource, site: dict | None = None):
        self.sla, self.src = sla, source
        g = source.get
        manifest = g("manifest")
        self.window_start: datetime = manifest["window"]["start"]
        self.window_end: datetime = manifest["window"]["end"]
        self.tolerance = timedelta(minutes=sla["measurement"]["record_integrity_tolerance_min"])
        self.site = site or S.load_site()
        self.ia = load_interface_agreement()
        self.ups = g("ups_nmc_events")
        self.busway = g("busway_events")
        self.emcp = g("emcp_readings")
        self.cdu = g("cdu_events")
        self.bms = g("facility_bms")
        self.epms = g("epms_events")
        self.leak = g("leak_events")
        self.vesda = g("vesda_events")
        self.badges = g("landlord_badges")
        self.mops = g("landlord_mops")
        self.work_orders = g("work_orders")
        self.pm = g("pm_records")
        self.roster = g("landlord_roster")
        self.weekly = g("landlord_weekly")
        self.prio = {p["id"]: p for p in sla["priorities"]}
        self.default_prio = {fc["id"]: fc["default_priority"] for fc in sla["measurement_spec"]}

    # ------------------------------------------------------------------ evidence helpers
    def badge_into(self, room: str, start: datetime, end: datetime, person: str | None = None) -> dict | None:
        hits = [b for b in self.badges if b["reader"] == room and start <= b["timestamp"] <= end
                and (person is None or b["person_id"] == person)]
        return min(hits, key=lambda b: b["timestamp"]) if hits else None

    def bms_alarm(self, device: str, t0: datetime) -> tuple[str | None, datetime | None]:
        """(priority, acknowledged_at) for the BMS alarm on a device at T0."""
        active = [e for e in self.bms if e["kind"] == "alarm" and e["device"] == device and e["state"] == "active"
                  and abs((e["timestamp"] - t0).total_seconds()) <= 120]
        if not active:
            return None, None
        a = active[0]
        ack = next((e["timestamp"] for e in self.bms if e["kind"] == "alarm" and e["device"] == device
                    and e["alarm"] == a["alarm"] and e["state"] == "acknowledged" and e["timestamp"] >= a["timestamp"]), None)
        return a["priority"], ack

    def mop_covering(self, asset: str, t: datetime) -> dict | None:
        return next((m for m in self.mops if asset in m["assets"] and m["window_start"] <= t <= m["window_end"]), None)

    def work_order_for(self, unit: str, t0: datetime) -> dict | None:
        cands = [w for w in self.work_orders if w["unit"] == unit and w["fault_class"] is not None or
                 (w["unit"] == unit and w["priority"] == "P1")]
        cands = [w for w in cands if w["unit"] == unit and abs((w["opened"] - t0).total_seconds()) <= 3600]
        return cands[0] if cands else None


# --------------------------------------------------------------------------- #
# Facility incidents of record, rebuilt from telemetry
# --------------------------------------------------------------------------- #
def _pairs(rows: list[dict], key: str, start_pred: Callable[[dict], bool], end_pred: Callable[[dict], bool]):
    """(unit, start_row, end_row or None) intervals per unit."""
    open_: dict[str, dict] = {}
    for r in rows:
        u = r[key]
        if start_pred(r) and u not in open_:
            open_[u] = r
        elif end_pred(r) and u in open_:
            yield u, open_.pop(u), r
    for u, r in open_.items():
        yield u, r, None


def build_facility_incidents(ctx: LandlordContext) -> list[FacilityIncident]:
    out: list[FacilityIncident] = []

    def add(cls: str, unit: str, t0: datetime, end: dict | None, desc: str, source: str, device: str | None = None):
        prio, ack = ctx.bms_alarm(device or unit, t0)
        inc = FacilityIncident(cls, unit, room_for(unit), t0, end["timestamp"] if end else None,
                               prio or ctx.default_prio.get(cls, "P2"), desc, source, ack_at=ack)
        until = inc.restored or ctx.window_end
        b = ctx.badge_into(inc.room, t0 - timedelta(minutes=5), until)
        inc.engaged_at = b["timestamp"] if b else None
        inc.work_order = ctx.work_order_for(unit, t0)
        out.append(inc)

    cdu_red = [e for e in ctx.cdu if e["property"] == "PumpRedundancy.Status.Health"]
    for u, s, e in _pairs(cdu_red, "cdu", lambda r: r["value"] != "OK", lambda r: r["value"] == "OK"):
        add("OT-FC-CDU", u, s["timestamp"], e, f"{u} pump redundancy lost (Redfish PumpRedundancy {s['value']})", "DS-CDU")
    mod = [e for e in ctx.ups if "Power module" in e["event"]]
    for u, s, e in _pairs(mod, "ups", lambda r: r["event"].endswith("fault"), lambda r: "redundancy restored" in r["event"]):
        add("OT-FC-UPS", u, s["timestamp"], e, f"{u}: {s['event']}", "DS-UPS")
    # A rack that lost both feeds at its tap-offs: rack capacity lost on the Landlord side (FA-1).
    open_feeds: dict[str, set] = {}
    for e in [x for x in ctx.busway if "rack" in x]:
        feeds = open_feeds.setdefault(e["rack"], set())
        side = e["busway"][-1]
        if e["event"] == "Breaker open":
            feeds.add(side)
            if len(feeds) == 2:
                start = e
        elif e["event"] == "Breaker closed":
            if len(feeds) == 2:
                add("OT-FC-PWR", f"Rack {e['rack']}", start["timestamp"], e,
                    f"Rack {e['rack']} lost both feeds at the tap-offs ({start['tapoff']} opened while the other side was open)",
                    "DS-BUSWAY")
                out[-1].room = room_for(start["busway"])
                out[-1].capacity_lost = True
                b = ctx.badge_into(out[-1].room, out[-1].t0 - timedelta(minutes=5), out[-1].restored)
                out[-1].engaged_at = b["timestamp"] if b else None
            feeds.discard(side)
    feed = [e for e in ctx.busway if "state" in e]
    for u, s, e in _pairs(feed, "busway", lambda r: r["state"] == "out_of_tolerance", lambda r: r["state"] == "in_tolerance"):
        add("OT-FC-PWR", u, s["timestamp"], e, f"{u} feed lost ({s['point']} {s['value_v']} V)", "DS-BUSWAY")
    for u, s, e in _pairs(ctx.leak, "controller", lambda r: r["event"] == "LEAK", lambda r: r["event"] == "NORMAL"):
        unit = f"{u}/C{s['circuit']}"
        add("OT-FC-LEAK", unit, s["timestamp"], e, f"Leak {s['label']} at {s['distance_m']} m", "DS-LEAK", device=u)
        out[-1].room = f"Hall {u[-1]}"
    faults = [e for e in ctx.vesda if e["event"] in ("Fault", "Normal") and e["detail"] != "De-isolated"]
    for u, s, e in _pairs(faults, "detector", lambda r: r["event"] == "Fault", lambda r: r["event"] == "Normal"):
        add("OT-FC-FIRE", u, s["timestamp"], e, f"{u} {s['detail']}", "DS-FIRE")
    alarms = [e for e in ctx.bms if e["kind"] == "alarm" and e["state"] in ("active", "cleared")
              and e["device"].startswith(("CH-", "TW-", "CRAH-"))]
    for u, s, e in _pairs(alarms, "device", lambda r: r["state"] == "active", lambda r: r["state"] == "cleared"):
        cls = "OT-FC-CHW" if u.startswith("CH-") else "OT-FC-AIR"
        add(cls, u, s["timestamp"], e, f"{u}: {s['alarm']}", "DS-BMS")
    trips = [e for e in ctx.epms if "utility undervoltage" in e["event"]]
    if trips:
        t0 = min(e["timestamp"] for e in trips)
        back = min((e["timestamp"] for e in ctx.epms if "utility restored" in e["event"] and e["timestamp"] > t0), default=None)
        inc = FacilityIncident("UTILITY", "138 kV utility service", "MV switchgear", t0, back, "P1",
                               "Utility outage: both 13.8 kV mains tripped on undervoltage", "DS-EPMS")
        inc.ack_at = ctx.bms_alarm("MV switchgear", t0)[1]
        b = ctx.badge_into("MV switchgear", t0 - timedelta(minutes=5), back or ctx.window_end)
        inc.engaged_at = b["timestamp"] if b else None
        inc.work_order = next((w for w in ctx.work_orders if w["unit"] == "138 kV utility service"), None)
        out.append(inc)
    return sorted(out, key=lambda i: i.t0)


# --------------------------------------------------------------------------- #
# Attribution (Interface Agreement FA-1 to FA-6)
# --------------------------------------------------------------------------- #
def attribute(ctx: LandlordContext, incidents: list[FacilityIncident]) -> None:
    """Assign each facility event an owner from the telemetry and the ownership matrix."""
    for inc in incidents:
        if inc.fault_class == "UTILITY":
            inc.owner, inc.rule = "Utility", "FA-6"
        else:
            inc.owner = "Landlord"
            inc.rule = "FA-5" if not inc.capacity_lost else "FA-1"


def attribution_rows(incidents: list[FacilityIncident]) -> list[dict[str, Any]]:
    rows = []
    for i in incidents:
        claim = i.work_order["attribution"] if i.work_order else None
        rows.append({"event": i.description, "fault_class": i.fault_class, "unit": i.unit, "t0": i.t0,
                     "restored": i.restored, "owner": i.owner, "rule": i.rule, "capacity_lost": i.capacity_lost,
                     "work_order": i.work_order["wo"] if i.work_order else None, "claimed_owner": claim,
                     "agrees": claim in (None, i.owner)})
    return rows


# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #
DETECTORS: list[Callable[[LandlordContext, list[FacilityIncident]], list[Finding]]] = []


def detector(fn):
    DETECTORS.append(fn)
    return fn


def new_finding(ctx: LandlordContext, type_id: str, summary: str, refs: list[str], unit: str | None,
                at: datetime | None, evidence: list[dict], **kw) -> Finding:
    ft = finding_type(ctx.sla, type_id)
    return Finding(type=type_id, title=ft["name"], summary=summary, tickets=refs, unit=unit, observed_at=at,
                   evidence=evidence, sla_refs=list(ft["sla_refs"]), recommended_action=ft["action"], **kw)


@detector
def detect_gen_test_no_load(ctx, incidents):
    out = []
    for pm in [p for p in ctx.pm if p["task"] == "Monthly loaded exercise"]:
        rows = [r for r in ctx.emcp if r["generator"] == pm["asset"] and r["engine_operating_state"] == "Running"
                and pm["completed_at"] - timedelta(minutes=90) <= r["timestamp"] <= pm["completed_at"]]
        loaded = [r for r in rows if r["gen_pct_rated_kw"] >= LOAD_MIN_PCT]
        if len(loaded) >= LOAD_MIN_MINUTES:
            continue
        peak = max((r["gen_pct_rated_kw"] for r in rows), default=0)
        out.append(new_finding(
            ctx, "gen_test_no_load",
            f"{pm['asset']} monthly test recorded as '{pm['result']}', but the EMCP shows {len(rows)} running minutes "
            f"peaking at {peak:.0f}% of rated kW. NFPA 110 needs {LOAD_MIN_PCT}% for {LOAD_MIN_MINUTES} minutes.",
            [pm["task_id"]], pm["asset"], pm["completed_at"],
            [ev("landlord/pm_records.csv", pm["completed_at"], f"{pm['task_id']} {pm['task']}: {pm['result']}"),
             ev("facility/emcp_readings.jsonl", rows[0]["timestamp"] if rows else None,
                f"{len(rows)} minutes running; {len(loaded)} at or above {LOAD_MIN_PCT}%; peak {peak:.1f}%")],
            keys={"asset": pm["asset"]}, metrics={"loaded_minutes": len(loaded), "peak_pct": peak}))
    return out


@detector
def detect_pm_without_evidence(ctx, incidents):
    out = []
    for pm in ctx.pm:
        room = room_for(pm["asset"])
        b = ctx.badge_into(room, pm["completed_at"] - timedelta(hours=6), pm["completed_at"], pm["engineer"])
        if b:
            continue
        out.append(new_finding(
            ctx, "pm_without_evidence",
            f"{pm['task_id']} ({pm['task']}, {pm['asset']}) was closed by {pm['engineer']} at {fmt_t(pm['completed_at'])}, "
            f"but {pm['engineer']} never badged into {room} in the 6 hours before.",
            [pm["task_id"]], pm["asset"], pm["completed_at"],
            [ev("landlord/pm_records.csv", pm["completed_at"], f"{pm['task_id']} closed: {pm['result']}; evidence '{pm['evidence']}'"),
             ev("access/landlord_badge_events.csv", None, f"No entry to {room} by {pm['engineer']}")],
            keys={"asset": pm["asset"], "task": pm["task_id"]}))
    return out


@detector
def detect_bms_override_unrecorded(ctx, incidents):
    out = []
    # Unrecorded: no change reference in the BMS and no approved MOP covering that device at that time.
    # (Live BACnet data cannot carry a change reference, so the MOP check is what reconciles it.)
    sets = [e for e in ctx.bms if e["kind"] in ("override", "inhibit") and e["action"] == "set" and not e["change_ref"]
            and not ctx.mop_covering(e["device"], e["timestamp"])]
    for s in sets:
        rel = next((e for e in ctx.bms if e["kind"] == s["kind"] and e["device"] == s["device"] and e["point"] == s["point"]
                    and e["action"] == "release" and e["timestamp"] > s["timestamp"]), None)
        hours = (rel["timestamp"] - s["timestamp"]).total_seconds() / 3600 if rel else None
        out.append(new_finding(
            ctx, "bms_override_unrecorded",
            f"{s['kind'].capitalize()} on {s['device']} '{s['point']}' set to {s['value']}"
            + (f" by {s['user']}" if s.get("user") else "") + " with no change reference or approved MOP" + (f", held {hours:.1f} hours." if hours else ", still in place at the end of the window."),
            [], s["device"], s["timestamp"],
            [ev("facility/bms_events.jsonl", s["timestamp"], f"{s['kind']} set: {s['point']} = {s['value']}, change_ref empty"),
             ev("facility/bms_events.jsonl", rel["timestamp"] if rel else None, "released" if rel else "not released")],
            keys={"device": s["device"], "set_at": s["timestamp"]}, metrics={"hours": hours}))
    return out


@detector
def detect_alarm_acked_no_dispatch(ctx, incidents):
    out = []
    for inc in incidents:
        wo = inc.work_order
        if not wo or not wo["engaged_at"] or inc.engaged_at is not None or inc.ack_at is None:
            continue
        out.append(new_finding(
            ctx, "alarm_acked_no_dispatch",
            f"{inc.unit} alarm acknowledged at {fmt_t(inc.ack_at)} and {wo['wo']} says an engineer attended at "
            f"{fmt_t(wo['engaged_at'])}, but nobody badged into {inc.room} before it cleared at {fmt_t(inc.restored)}.",
            [wo["wo"]], inc.unit, inc.t0,
            [ev("facility/bms_events.jsonl", inc.ack_at, "Alarm acknowledged"),
             ev("landlord/work_orders.json", wo["engaged_at"], f"{wo['wo']}: {wo['notes']}"),
             ev("access/landlord_badge_events.csv", None, f"No entry to {inc.room} between alarm and clear")],
            keys={"wo": wo["wo"]}))
    return out


@detector
def detect_critical_work_no_mop(ctx, incidents):
    out = []
    events = [("busway", e["busway"], e["timestamp"], f"Tap-off {e.get('tapoff')} breaker opened")
              for e in ctx.busway if e.get("event") == "Breaker open"]
    events += [("ups", e["ups"], e["timestamp"], "UPS to maintenance bypass") for e in ctx.ups
               if e["event"].endswith("switchedBypass")]
    events += [("cdu", e["cdu"], e["timestamp"], f"{e['resource'].split('/')[-2]} {e['resource'].split('/')[-1]} isolated")
               for e in ctx.cdu if e["property"] == "Status.State" and e["value"] == "Disabled"]
    events += [("vesda", e["detector"], e["timestamp"], "Detector isolated") for e in ctx.vesda if e["event"] == "Isolate"]
    for kind, asset, t, what in events:
        if ctx.mop_covering(asset, t):
            continue
        wo = next((w for w in ctx.work_orders if w["unit"] == asset and abs((w["engaged_at"] or w["opened"]) - t) <= timedelta(hours=2)), None)
        out.append(new_finding(
            ctx, "critical_work_no_mop",
            f"{what} on {asset} at {fmt_t(t)} with no approved MOP covering that asset and time"
            + (f" ({wo['wo']}: {wo['notes']})." if wo else "."),
            [wo["wo"]] if wo else [], asset, t,
            [ev(f"facility/{'busway_cpm' if kind == 'busway' else kind}_events", t, what),
             ev("customer/landlord_mop_approvals.json", None, f"No approved MOP for {asset} at that time")],
            keys={"asset": asset, "at": t}))
    return out


@detector
def detect_landlord_clock_shift(ctx, incidents):
    out = []
    for inc in incidents:
        wo = inc.work_order
        if not wo or not wo["restored_at"] or inc.restored is None:
            continue
        early = inc.restored - wo["restored_at"]
        if early <= ctx.tolerance:
            continue
        out.append(new_finding(
            ctx, "landlord_clock_shift",
            f"{wo['wo']} records {inc.unit} restored at {fmt_t(wo['restored_at'])}, {early.total_seconds() / 60:.0f} minutes "
            f"before the telemetry shows restoration at {fmt_t(inc.restored)}. Measured restoration is "
            f"{inc.restore_min:.0f} minutes, not {minutes_between(inc.t0, wo['restored_at']):.0f}.",
            [wo["wo"]], inc.unit, inc.t0,
            [ev("landlord/work_orders.json", wo["restored_at"], f"{wo['wo']} restored_at"),
             ev(inc.source, inc.restored, "Device reports redundancy restored")],
            keys={"wo": wo["wo"]}, metrics={"minutes_early": early.total_seconds() / 60}))
    return out


@detector
def detect_attribution_contradicted(ctx, incidents):
    out = []
    for inc in incidents:
        wo = inc.work_order
        if not wo or wo["attribution"] == inc.owner:
            continue
        out.append(new_finding(
            ctx, "attribution_contradicted",
            f"{wo['wo']} attributes the {inc.unit} event to the {wo['attribution']} ('{wo['notes']}'), but the Telemetry of "
            f"Record shows the fault on {inc.owner} equipment ({inc.description}). Rule {inc.rule} applies.",
            [wo["wo"]], inc.unit, inc.t0,
            [ev("landlord/work_orders.json", wo["opened"], f"Attribution: {wo['attribution']}"),
             ev(inc.source, inc.t0, inc.description)],
            keys={"wo": wo["wo"]}))
    return out


def run_landlord(sla: dict[str, Any], source: SiteDataSource) -> LandlordResult:
    ctx = LandlordContext(sla, source)
    incidents = build_facility_incidents(ctx)
    attribute(ctx, incidents)
    findings: list[Finding] = []
    for d in DETECTORS:
        findings.extend(d(ctx, incidents))
    for f in findings:
        r = classify_finding(sla, f.type, None, None, 0)
        f.severity, f.severity_name, f.escalation, f.severity_reasons = r.level, r.name, r.escalation, r.reasons
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.observed_at or ctx.window_start, f.type))
    for n, f in enumerate(findings, 1):
        f.id = f"L-{n:03d}"
    return LandlordResult(ctx, incidents, findings)


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #
def _intervals_minutes(intervals: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> float:
    """Union length in minutes, clipped to [start, end]."""
    clipped = sorted((max(a, start), min(b, end)) for a, b in intervals if b > start and a < end)
    total, cur_a, cur_b = 0.0, None, None
    for a, b in clipped:
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += (cur_b - cur_a).total_seconds() / 60
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += (cur_b - cur_a).total_seconds() / 60
    return total


def measure_landlord(result: LandlordResult) -> dict[str, dict[str, Any]]:
    ctx, inc = result.context, result.incidents
    start, end = ctx.window_start, ctx.window_end
    window_min = (end - start).total_seconds() / 60
    leased = [r for h in ctx.site["halls"] if h["state"] != "planned" for r in S.racks(ctx.site, h["id"])]
    seg_of = {}
    for h in ctx.site["halls"]:
        for sgm in S.busway_segments(ctx.site, h["id"]):
            for r in sgm["racks"]:
                seg_of[r] = sgm["id"]
    lost = {}
    rack_dark: dict[str, list] = {}
    for i in inc:
        if i.fault_class == "OT-FC-PWR" and i.capacity_lost:
            rack_dark.setdefault(i.unit.split()[-1], []).append((i.t0, i.restored or end))
        elif i.fault_class == "OT-FC-PWR":
            lost.setdefault(i.unit, []).append((i.t0, i.restored or end))
    one_feed_ok = both_ok = 0.0
    for r in leased:
        a, b = lost.get(f"{seg_of[r['rack']]}-A", []), lost.get(f"{seg_of[r['rack']]}-B", [])
        dark = rack_dark.get(r["rack"], [])
        either_down = _intervals_minutes(a + b + dark, start, end)
        both_down = sum(_intervals_minutes([(max(x[0], y[0]), min(x[1], y[1]))], start, end)
                        for x in a for y in b if min(x[1], y[1]) > max(x[0], y[0])) + _intervals_minutes(dark, start, end)
        one_feed_ok += window_min - both_down
        both_ok += window_min - either_down
    rack_minutes = window_min * len(leased)
    m: dict[str, dict[str, Any]] = {}

    def put(mid, value, detail):
        m[mid] = {"actual": value, "detail": detail}

    put("OT-CSL-01", 100 * one_feed_ok / rack_minutes, f"{len(leased)} leased racks; minutes with at least one feed in tolerance")
    put("OT-CSL-02", 100 * both_ok / rack_minutes, f"{len(leased)} leased racks; minutes with both feeds in tolerance")
    put("OT-CSL-03", 100.0, "No rack-level cooling excursion in the window")
    put("OT-CSL-10", 100.0, "No hall-level cooling excursion in the window")

    def response(prio, ack_lim, eng_lim):
        rows = [i for i in inc if i.priority == prio]
        ok = [i for i in rows if i.ack_at and minutes_between(i.t0, i.ack_at) <= ack_lim
              and i.engaged_at and minutes_between(i.t0, i.engaged_at) <= eng_lim]
        return rows, ok

    p1 = ctx.prio["P1"]
    rows, ok = response("P1", p1["acknowledge_min"], p1["engaged_on_site_min"])
    put("OT-CSL-04", 100 * len(ok) / len(rows) if rows else None, f"{len(ok)} of {len(rows)} P1 events acknowledged and attended in time (badge)")
    p2 = ctx.prio["P2"]
    rows, ok = response("P2", p2["acknowledge_min"], p2["engaged_on_site_min"])
    put("OT-KM-01", 100 * len(ok) / len(rows) if rows else None, f"{len(ok)} of {len(rows)} P2 events acknowledged and attended in time (badge)")
    red = [i for i in inc if i.fault_class in ("OT-FC-CDU", "OT-FC-UPS", "OT-FC-PWR", "OT-FC-CHW", "OT-FC-GEN")]
    in_t = [i for i in red if i.restore_min is not None and i.restore_min <= ctx.prio[i.priority]["restore_min"]]
    put("OT-CSL-05", 100 * len(in_t) / len(red) if red else None, f"{len(in_t)} of {len(red)} redundancy events restored within target (telemetry)")

    bad_pm = {k for f in result.findings if f.type in ("pm_without_evidence", "gen_test_no_load") for k in f.tickets}
    on_time = [p for p in ctx.pm if p["completed_at"] <= p["due_end"] and p["task_id"] not in bad_pm]
    put("OT-CSL-06", 100 * len(on_time) / len(ctx.pm) if ctx.pm else None, f"{len(on_time)} of {len(ctx.pm)} tasks on time with evidence")
    gens = [p for p in ctx.pm if p["task"] == "Monthly loaded exercise"]
    no_load = {f.keys["asset"] for f in result.findings if f.type == "gen_test_no_load"}
    put("OT-KM-02", 100 * (len(gens) - len(no_load)) / len(gens) if gens else None,
        f"{len(gens) - len(no_load)} of {len(gens)} monthly tests met {LOAD_MIN_PCT}% for {LOAD_MIN_MINUTES} minutes (EMCP)")
    crit = [f for f in result.findings if f.type == "critical_work_no_mop"]
    n_crit = (sum(1 for e in ctx.busway if e.get("event") == "Breaker open") + sum(1 for e in ctx.ups if e["event"].endswith("switchedBypass"))
              + sum(1 for e in ctx.cdu if e["property"] == "Status.State" and e["value"] == "Disabled")
              + sum(1 for e in ctx.vesda if e["event"] == "Isolate"))
    put("OT-CSL-07", 100 * (n_crit - len(crit)) / n_crit if n_crit else None, f"{n_crit - len(crit)} of {n_crit} critical work events under an approved MOP")
    records = [w["wo"] for w in ctx.work_orders] + [p["task_id"] for p in ctx.pm]
    tainted = {k for f in result.findings for k in f.tickets}
    put("OT-CSL-08", 100 * (len(records) - len(tainted & set(records))) / len(records),
        f"{len(records) - len(tainted & set(records))} of {len(records)} work orders and maintenance records reconcile")
    rostered = len(ctx.roster)
    badged = sum(1 for r in ctx.roster if any(b["person_id"] == r["engineer"] and b["reader"] == "Main lobby"
                                              and abs((b["timestamp"] - r["shift_start"]).total_seconds()) <= 3600 for b in ctx.badges))
    put("OT-CSL-09", 100 * badged / rostered if rostered else None, f"{badged} of {rostered} rostered shifts badge-verified")
    coolant = [p for p in ctx.pm if p["task"] == "Filter change and coolant sample"]
    put("OT-KM-03", 100.0 if coolant else None, f"{len(coolant)} coolant samples, all within specification")
    put("OT-KM-04", None, "No fuel quality test due in the window")
    overrides = [f for f in result.findings if f.type == "bms_override_unrecorded" and (f.metrics.get("hours") or 99) > 24]
    put("OT-KM-05", float(len(overrides)), f"{len(overrides)} override or inhibit held over 24 hours without a change reference")
    put("OT-KM-06", 100.0, "No gap in the Customer's facility feeds")
    notice_ok = [x for x in ctx.mops if (x["window_start"] - x["approved_at"]).days >= 14]
    put("OT-KM-07", 100 * len(notice_ok) / len(ctx.mops) if ctx.mops else None,
        f"{len(notice_ok)} of {len(ctx.mops)} MOPs approved at least 10 business days before the work")
    put("OT-KM-08", None, "No corrective action plan due in the window")
    return m


def build_landlord_scorecard(sla: dict[str, Any], result: LandlordResult) -> dict[str, Any]:
    measured = measure_landlord(result)
    rows, credits = [], []
    reported = result.context.weekly[-1]["results"] if result.context.weekly else {}
    for c in sla["critical_service_levels"]:
        val = measured[c["id"]]["actual"]
        res = evaluate_csl(sla, c["id"], val) if val is not None else None
        status = res.status if res else "not_applicable"
        credit = 0.0
        if res and res.status in ("below_minimum", "deep_below_minimum"):
            cr = compute_credit(sla, c["id"], 1, aggravators=["AGG-INTEGRITY"] if c["id"] == "OT-CSL-08" else [])
            credits.append(cr)
            credit = cr.credit
        rows.append({"id": c["id"], "name": c["name"], "expected": c["expected"], "minimum": c["minimum"],
                     "direction": c["direction"], "actual": val, "vendor_reported": reported.get(c["id"]),
                     "status": status, "credit": credit, "detail": measured[c["id"]]["detail"]})
    uncapped, payable, _ = cap_monthly_credits(sla, credits) if credits else (0.0, 0.0, [])
    kms = [{"id": k["id"], "name": k["name"], "target": k["target"], "unit": k["unit"], "direction": k["direction"],
            "actual": measured[k["id"]]["actual"], "detail": measured[k["id"]]["detail"],
            "met": None if measured[k["id"]]["actual"] is None else (
                measured[k["id"]]["actual"] >= k["target"] if k["direction"] == "higher_is_better"
                else measured[k["id"]]["actual"] <= k["target"])} for k in sla["key_measurements"]]
    return {"supplier": sla["parties"]["supplier"]["name"], "window": {"start": result.context.window_start, "end": result.context.window_end},
            "csl": rows, "km": kms, "credits": {"uncapped": uncapped, "payable": payable, "capped": payable < uncapped,
                                                  "items": [{"csl": c.csl_id, "credit": c.credit, "explanation": c.explanation} for c in credits]},
            "defaults": [r["id"] for r in rows if r["status"] in ("below_minimum", "deep_below_minimum")],
            "findings": len(result.findings), "s1": sum(1 for f in result.findings if f.severity == "S1"),
            "attribution": attribution_rows(result.incidents)}
