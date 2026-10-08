"""Post-incident review (PIR) facts, built from the dataset for any ticket or work order number.

Everything factual in a review (header, response metrics, impact, the alarm
timeline with each source record reproduced exactly, attribution, contract
consequences, and repeat events) comes from here, so the blank form can
auto-fill from a reference number and the completed review can be checked
against the data. Judgment (narratives, factors, lessons, actions) is written
by people: for a completed review it lives in ``pir/reviews/*.yaml``.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
LOCAL = timezone(timedelta(hours=-5), "CDT")      # Central Texas in September (daylight time)
GPUS_PER_RACK = 72

OSR = {  # Uptime Institute Outage Severity Rating
    1: ("Negligible", "Recorded and reported, little or no obvious impact on business services, no service disruptions."),
    2: ("Minimal", "Some IT services disrupted or degraded, with minimal effect on users, customers, or reputation."),
    3: ("Significant", "Observable customer or user service disruption, mainly of limited scope, duration, or effect."),
    4: ("Serious", "Disruption of service and/or operations."),
    5: ("Severe", "Mission-critical outage with major, damaging disruption of services and/or operations."),
}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hm(minutes: float) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


class Dataset:
    def __init__(self, data_dir: str | Path, reports_dir: str | Path | None = None):
        d = Path(data_dir)
        self.dir = d
        jl = lambda f: [json.loads(x) for x in (d / f).read_text(encoding="utf-8").splitlines() if x.strip()]
        js = lambda f: json.loads((d / f).read_text(encoding="utf-8"))
        rows = lambda f: list(csv.DictReader((d / f).open(encoding="utf-8")))
        self.tickets = js("vendor/tickets.json")
        self.work_orders = js("landlord/work_orders.json")
        self.mops = js("customer/landlord_mop_approvals.json")
        self.busway = jl("facility/busway_cpm_events.jsonl")
        self.bms = jl("facility/bms_events.jsonl")
        self.epms = jl("facility/epms_events.jsonl")
        self.cdu = jl("facility/cdu_redfish_events.jsonl")
        self.scheduler = jl("telemetry/scheduler_node_states.jsonl")
        self.health = jl("telemetry/health_checks.jsonl")
        self.it_badges = rows("access/badge_events.csv")
        self.ll_badges = rows("access/landlord_badge_events.csv")
        rep = Path(reports_dir) if reports_dir else d.parents[1] / "reports"
        self.reports = rep
        self.ll_findings = json.loads((rep / "landlord_findings.json").read_text(encoding="utf-8")) if (rep / "landlord_findings.json").exists() else []
        self.ll_scorecard = json.loads((rep / "landlord_scorecard.json").read_text(encoding="utf-8")) if (rep / "landlord_scorecard.json").exists() else {}


def _row(t: str, party: str, source: str, event: str, record: dict | None) -> dict[str, Any]:
    local = _t(t).astimezone(LOCAL)
    return {"t": t, "local": local.strftime("%H:%M:%S %Z"), "party": party, "source": source, "event": event,
            "record": json.dumps(record, sort_keys=True) if record is not None else ""}


def build_review(ds: Dataset, ref: str) -> dict[str, Any] | None:
    """All facts for one incident, keyed from a ticket (INC...) or work order (WO-...) number."""
    ticket = next((t for t in ds.tickets if t["number"] == ref), None)
    wo = next((w for w in ds.work_orders if w["wo"] == ref), None)
    if ticket and "Landlord WO-" in ticket["short_description"]:
        wo_ref = ticket["short_description"].split("Landlord ")[1].rstrip(")")
        wo = next((w for w in ds.work_orders if w["wo"] == wo_ref), None)
    if wo and ticket is None:
        ticket = next((t for t in ds.tickets if wo["wo"] in t["short_description"]), None)
    if ticket is None and wo is None:
        return None
    rack = (ticket or {}).get("rack") or (wo["unit"].split()[-1] if wo and wo["unit"].startswith("Rack ") else None)
    unit = wo["unit"] if wo else ticket["configuration_item"]
    starts = [_t(x) for x in ((wo or {}).get("opened"), (ticket or {}).get("opened_at")) if x]
    ends = [_t(x) for x in ((wo or {}).get("closed"), (ticket or {}).get("resolved_at")) if x]
    lo, hi = min(starts) - timedelta(hours=1), max(ends) + timedelta(hours=1)
    within = lambda s: lo <= _t(s) <= hi
    tl: list[dict[str, Any]] = []

    # Facility side
    bw_events = [e for e in ds.busway if within(e["timestamp"]) and (e.get("rack") == rack or e["busway"] == unit)]
    for e in bw_events:
        what = (f"Tap-off {e['tapoff']} ({e['busway'][-1]}-side feed" + (f" to rack {e['rack']}" if e.get("rack") else "") + f"): {e['event'].lower()}" if "tapoff" in e
                else f"{e['busway']}: {e['point']} {e.get('value_v')} V, {e.get('state')}")
        tl.append(_row(e["timestamp"], "Landlord", "facility/busway_cpm_events.jsonl", what, e))
    for e in [x for x in ds.bms if within(x["timestamp"]) and x["device"] == unit]:
        what = f"BMS alarm '{e['alarm']}' {e['state']}" + (f" by {e['user']}" if e.get("user") else "") + (f" ({e['priority']})" if e.get("priority") else "")
        tl.append(_row(e["timestamp"], "Landlord", "facility/bms_events.jsonl", what, e))
    if wo:
        for k, label in (("opened", "opened"), ("acknowledged_at", "acknowledged"), ("engaged_at", "engineer engaged (as recorded)"),
                         ("restored_at", "restored (as recorded)"), ("closed", "closed")):
            if wo.get(k):
                tl.append(_row(wo[k], "Landlord", "landlord/work_orders.json", f"Work order {wo['wo']} {label}",
                               wo if k == "opened" else None))
        for b in ds.ll_badges:
            if b["person_id"] == wo["engineer"] and within(b["timestamp"]) and b["reader"] == wo["room"]:
                tl.append(_row(b["timestamp"], "Landlord", "access/landlord_badge_events.csv",
                               f"{b['person_id']} badged {b['direction']} at {b['reader']}", b))
    mops = [m for m in ds.mops if (any(e["busway"] in m["assets"] for e in bw_events) or (wo and wo["unit"] in m["assets"]))
            and _t(m["window_start"]) <= hi and _t(m["window_end"]) >= lo]
    for m in mops:
        tl.append(_row(m["window_start"], "Customer", "customer/landlord_mop_approvals.json",
                       f"{m['mop_id']} window opens: {m['title']} (assets {', '.join(m['assets'])})", m))
        tl.append(_row(m["window_end"], "Customer", "customer/landlord_mop_approvals.json", f"{m['mop_id']} window closes", None))

    # IT side
    nodes_down = []
    if rack:
        prefix = rack.lower() + "-"
        down = [s for s in ds.scheduler if s["node"].startswith(prefix) and s["state"] == "down" and within(s["timestamp"])]
        up = [s for s in ds.scheduler if s["node"].startswith(prefix) and s["state"] == "idle" and down
              and _t(s["timestamp"]) > min(_t(x["timestamp"]) for x in down) and within(s["timestamp"])]
        nodes_down = down
        if down:
            first, last = min(down, key=lambda s: s["timestamp"]), max(down, key=lambda s: s["timestamp"])
            tl.append(_row(first["timestamp"], "IT Partner", "telemetry/scheduler_node_states.jsonl",
                           f"{len(down)} of 18 nodes in rack {rack} go down (first {first['node']}, last {last['node']} at "
                           f"{_t(last['timestamp']).strftime('%H:%M:%S')}Z): '{first['reason']}'", first))
        if up:
            lastup = max(up, key=lambda s: s["timestamp"])
            tl.append(_row(lastup["timestamp"], "IT Partner", "telemetry/scheduler_node_states.jsonl",
                           f"{len(up)} of 18 nodes back in service (last {lastup['node']}): '{lastup['reason']}'", lastup))
        for h in [x for x in ds.health if x.get("target") == rack and within(x["completed_at"])]:
            tl.append(_row(h["completed_at"], "IT Partner", "telemetry/health_checks.jsonl",
                           f"Return-to-service check {h['check']}: {h['result']}", h))
    if ticket:
        tl.append(_row(ticket["opened_at"], "IT Partner", "vendor/tickets.json", f"Ticket {ticket['number']} opened ({ticket['priority']})",
                       {k: ticket[k] for k in ("number", "priority", "short_description", "opened_at")}))
        for n in ticket["work_notes"]:
            tl.append(_row(n["at"], "IT Partner", "vendor/tickets.json", f"Work note ({n['author']}): {n['text']}", None))
        for b in ds.it_badges:
            if b["person_id"] == ticket["assigned_to"] and within(b["timestamp"]) and b["door"] == ticket["hall"]:
                tl.append(_row(b["timestamp"], "IT Partner", "access/badge_events.csv",
                               f"{b['person_id']} badged {b['direction']} at {b['door']}", b))
    tl.sort(key=lambda r: (r["t"], r["party"], r["event"]))

    # Phases and metrics
    opens = sorted(_t(e["timestamp"]) for e in bw_events if e.get("event") == "Breaker open")
    closes = sorted(_t(e["timestamp"]) for e in bw_events if e.get("event") == "Breaker closed")
    if not (rack and opens):   # anything but a rack losing power at its tap-offs
        return _event_review(ds, ref, ticket, wo, rack, unit, within, tl, mops, nodes_down)
    power_lost = opens[1] if len(opens) >= 2 else (_t(wo["opened"]) if wo else _t(ticket["opened_at"]))
    handoff = closes[0] if closes else (_t(wo["restored_at"]) if wo and wo.get("restored_at") else None)
    rts = _t(ticket["resolved_at"]) if ticket else handoff
    alarm = next((e for e in ds.bms if e["device"] == unit and e["state"] == "active" and within(e["timestamp"])), None)
    ack = next((e for e in ds.bms if e["device"] == unit and e["state"] == "acknowledged" and within(e["timestamp"])), None)
    ll_on_site = next((b for b in ds.ll_badges if wo and b["person_id"] == wo["engineer"] and b["reader"] == wo["room"]
                       and _t(b["timestamp"]) >= power_lost), None)
    it_on_site = next((b for b in ds.it_badges if ticket and b["person_id"] == ticket["assigned_to"] and b["door"] == ticket["hall"]
                       and b["direction"] == "in" and _t(b["timestamp"]) >= power_lost), None)

    def m(label, start, end, target=None, note=""):
        if not (start and end):
            return None
        mins = (end - start).total_seconds() / 60
        return {"measure": label, "from": _iso(start), "to": _iso(end), "minutes": round(mins, 1), "elapsed": _hm(mins),
                "target": target, "met": None if target is None else mins <= target, "note": note}

    metrics = [x for x in (
        m("Detect: power loss to BMS alarm", power_lost, _t(alarm["timestamp"]) if alarm else None),
        m("Landlord acknowledge (P1 target 5 min)", power_lost, _t(ack["timestamp"]) if ack else None, 5),
        m("Landlord engineer at equipment (P1 target 15 min)", power_lost, _t(ll_on_site["timestamp"]) if ll_on_site else None, 15),
        m("IT Partner acknowledge", _t(ticket["opened_at"]) if ticket else None, _t(ticket["acknowledged_at"]) if ticket else None),
        m("Landlord restoration, handoff (Landlord P1 restore target 4 h)", power_lost, handoff, 240),
        m("IT Partner technician on site after handoff (HO-1)", handoff, _t(it_on_site["timestamp"]) if it_on_site else None),
        m("IT Partner validation, handoff to return to service (P1 target 4 h, FA-3)", handoff, rts, 240),
        m("Total: power loss to return to service", power_lost, rts),
    ) if x]

    lost_h = ((rts - power_lost).total_seconds() / 3600) if (rts and rack) else 0.0
    ll_h = ((handoff - power_lost).total_seconds() / 3600) if (handoff and rack) else 0.0
    gpus = GPUS_PER_RACK if rack and nodes_down else 0
    finding = [f for f in ds.ll_findings if rack and (f"TO-{rack}" in f["summary"] or rack in (f.get("unit") or ""))]
    csl01 = next((c for c in ds.ll_scorecard.get("csl", []) if c["id"] == "OT-CSL-01"), None)
    mop_overrun = None
    for mp in mops:
        a_close = next((_t(e["timestamp"]) for e in bw_events if e.get("event") == "Breaker closed" and e["busway"] in mp["assets"]), None)
        if a_close and a_close > _t(mp["window_end"]):
            mop_overrun = {"mop": mp["mop_id"], "window_end": mp["window_end"], "closed": _iso(a_close),
                           "overrun": _hm((a_close - _t(mp["window_end"])).total_seconds() / 60)}
    repeats = [{"ref": t["number"], "opened": t["opened_at"], "what": t["short_description"]} for t in ds.tickets
               if rack and t.get("rack") == rack and t is not ticket]
    repeats += [{"ref": w["wo"], "opened": w["opened"], "what": w["notes"]} for w in ds.work_orders
                if w is not wo and any(e["busway"] in w["unit"] for e in bw_events)]
    osr = 1 if gpus == 0 else 2 if gpus <= GPUS_PER_RACK else 3
    return {
        "kind": "rack_power", "start": _iso(power_lost), "end": _iso(rts) if rts else None,
        "labels": {"duration": "Power loss to back in service", "gpus": "One rack offline", "split": "GPU-hours: Landlord / IT validation",
                   "offline": "GPUs offline"},
        "phases": [["Landlord", _iso(power_lost), _iso(handoff), "Landlord-attributed (FA-1)"],
                   ["IT Partner", _iso(handoff), _iso(rts), "IT validation (FA-3)"]] if handoff and rts else [],
        "marks": [[_iso(x), lbl] for x, lbl in ((power_lost, "Power lost"), (handoff, "Handoff"), (rts, "Back in service")) if x],
        "ref": ref, "ticket": ticket["number"] if ticket else None, "work_order": wo["wo"] if wo else None,
        "mops": [mp["mop_id"] for mp in mops], "unit": unit, "rack": rack,
        "title": (ticket or {}).get("short_description") or (wo or {}).get("notes"),
        "date": _iso(power_lost)[:10], "power_lost": _iso(power_lost),
        "handoff": _iso(handoff) if handoff else None, "rts": _iso(rts) if rts else None,
        "attribution": {"owner": wo["attribution"] if wo else "IT Partner", "rules": ["FA-1", "FA-3"] if wo and rack else ["FA-2"],
                        "evidence": f"Both of rack {rack}'s tap-offs open from {_iso(power_lost)} to {_iso(handoff)} (busway monitors)"
                        if wo and rack and handoff else ""},
        "impact": {"gpus": gpus, "duration": _hm(lost_h * 60), "gpu_hours_total": round(gpus * lost_h, 1),
                   "gpu_hours_landlord": round(gpus * ll_h, 1), "gpu_hours_it": round(gpus * (lost_h - ll_h), 1),
                   "injuries": 0},
        "osr_suggested": {"level": osr, "name": OSR[osr][0], "definition": OSR[osr][1]},
        "metrics": metrics, "timeline": tl, "findings": finding,
        "csl": {"OT-CSL-01": csl01} if csl01 else {}, "credits_landlord": ds.ll_scorecard.get("credits", {}).get("payable"),
        "mop_overrun": mop_overrun, "repeats": repeats,
        "people": {"landlord_engineer": wo["engineer"] if wo else None, "it_technician": ticket["assigned_to"] if ticket else None},
    }


def _measures(ds: Dataset) -> tuple[dict, dict, list]:
    """The Customer's own measurement of each ticket and work order, and every finding (IT Partner and Landlord)."""
    if not hasattr(ds, "_meas"):
        rep = ds.reports
        if (rep / "scorecard.json").exists() and (rep / "landlord_scorecard.json").exists():
            from scorecard.tickets import _measures as m
            by_ticket, by_wo, findings, _ = m(rep)
        else:
            by_ticket, by_wo, findings = {}, {}, []
        ds._meas = (by_ticket, by_wo, findings)
    return ds._meas


@lru_cache(maxsize=2)
def _priorities(partner: str) -> tuple[dict[str, Any], ...]:
    from scorecard.sla_model import load_sla
    path = ROOT / "sla" / ("ot_partner.yaml" if partner == "Landlord" else "it_partner.yaml")
    return tuple(load_sla(path, validate=False)["priorities"])


def _targets(partner: str, priority: str) -> dict[str, Any]:
    return next((p for p in _priorities(partner) if p["id"] == priority), {})


def _span(mins: int | None) -> str:
    return "" if mins is None else f"{mins} min" if mins < 60 else f"{mins // 60} h" if mins % 60 == 0 else _hm(mins)


def _metric(label: str, start: datetime | None, end: datetime | None, target: int | None = None, note: str = "") -> dict | None:
    if not (start and end):
        return None
    mins = (end - start).total_seconds() / 60
    return {"measure": label, "from": _iso(start), "to": _iso(end), "minutes": round(mins, 1), "elapsed": _hm(mins),
            "target": target, "met": None if target is None else mins <= target, "note": note}


def _event_review(ds: Dataset, ref: str, ticket: dict | None, wo: dict | None, rack: str | None, unit: str,
                  within, tl: list[dict], mops: list[dict], nodes_down: list[dict]) -> dict[str, Any]:
    """Facts for any incident or work order that is not a rack losing power at its tap-offs: the clock starts at
    the Customer's measured start of the event (first fault evidence in the Telemetry of Record), and each
    response is measured against the partner's target for the record's priority."""
    by_ticket, by_wo, all_findings = _measures(ds)
    mi = by_ticket.get(ticket["number"]) if ticket else None
    ml = by_wo.get(wo["wo"]) if wo else None
    partner = "Landlord" if wo else "IT Partner"
    prio = (wo or ticket)["priority"]
    tg = _targets(partner, prio)
    alarm = next((e for e in ds.bms if e["device"] == unit and e["state"] == "active" and within(e["timestamp"])), None)
    ack = next((e for e in ds.bms if e["device"] == unit and e["state"] == "acknowledged" and within(e["timestamp"])), None)
    opened = _t(wo["opened"]) if wo else _t(ticket["opened_at"])
    start = min(_t(x) for x in ((ml or {}).get("t0"), (mi or {}).get("t0"), (alarm or {}).get("timestamp"), _iso(opened)) if x)
    ack_min, site_min, rest_min = tg.get("acknowledge_min"), tg.get("engaged_on_site_min"), tg.get("restore_min")
    rows: list[dict | None] = []
    if wo:
        restored_rec = _t(wo["restored_at"]) if wo.get("restored_at") else None
        restored = _t(ml["restored"]) if ml and ml.get("restored") else restored_rec
        on_site = next((b for b in ds.ll_badges if b["person_id"] == wo["engineer"] and b["reader"] == wo["room"]
                        and _t(b["timestamp"]) >= start and within(b["timestamp"])), None)
        ack_t = _t(ack["timestamp"]) if ack else (_t(wo["acknowledged_at"]) if wo.get("acknowledged_at") else None)
        gap = (restored - restored_rec).total_seconds() / 60 if restored and restored_rec else 0
        rows += [
            _metric("Detect: event start to BMS alarm", start, _t(alarm["timestamp"]) if alarm else None),
            _metric("Detect: event start to work order opened", start, opened),
            _metric(f"Landlord acknowledge ({prio} target {_span(ack_min)})", start, ack_t, ack_min),
            _metric(f"Landlord engineer at the equipment ({prio} target {_span(site_min)})", start,
                    _t(on_site["timestamp"]) if on_site else None, site_min),
            _metric("Restored, as recorded in the work order", start, restored_rec),
            _metric(f"Restored, as measured from telemetry ({prio} target {_span(rest_min)})", start, restored, rest_min,
                    f"The work order records restoration {_hm(abs(gap))} {'earlier' if gap > 0 else 'later'} than the telemetry shows."
                    if abs(gap) >= 1 else ""),
        ]
        end = restored
    if ticket:
        rts = _t(mi["rts"]) if mi and mi.get("rts") else _t(ticket["resolved_at"])
        engaged = _t(mi["engaged_at"]) if mi and mi.get("engaged_at") else None
        reported = ticket.get("reported_outage_start")
        it_start = _t(mi["t0"]) if mi else start
        rows += [
            _metric("Detect: first fault evidence to ticket opened", it_start, _t(ticket["opened_at"])),
            _metric(f"IT Partner acknowledge ({ticket['priority']} target {_span(ack_min if not wo else None)})" if not wo else "IT Partner acknowledge",
                    _t(ticket["opened_at"]), _t(ticket["acknowledged_at"]) if ticket.get("acknowledged_at") else None, None if wo else ack_min),
            _metric(f"IT Partner technician on site ({ticket['priority']} target {_span(site_min)})" if not wo else "IT Partner technician on site",
                    it_start, engaged, None if wo else site_min),
            _metric("Back in service, as the ticket reports", _t(reported) if reported else None, _t(ticket["resolved_at"])),
            _metric(f"Back in service, as measured ({ticket['priority']} target {_span(rest_min)})" if not wo else "Back in service, as measured",
                    it_start, rts, None if wo else rest_min),
        ]
        end = rts if not wo else max(x for x in (end, rts) if x) if (end or rts) else None
    rows.append(_metric("Total: event start to " + ("back in service" if ticket else "restoration (measured)"), start, end))

    # The scheduler's own view for an IT event: the trays taken out of service and when they came back. A rack-wide
    # fault (an NVLink switch tray) drains every tray in the rack; a single-tray fault drains only its own.
    if ticket and rack:
        tray = next((t for t in re.findall(r"[a-c]\d{2}-(?:ct|nvsw)\d{1,2}", ticket["configuration_item"].lower())), None)
        wide = bool(mi and mi.get("gpus", 0) > 4)
        hit = [x for x in ds.scheduler if within(x["timestamp"]) and x["state"] in ("drain", "down")
               and (x["node"].startswith(rack.lower() + "-") if wide else x["node"] == tray)]
        if hit:
            first, last = min(hit, key=lambda x: x["timestamp"]), max(hit, key=lambda x: x["timestamp"])
            tl.append(_row(first["timestamp"], "IT Partner", "telemetry/scheduler_node_states.jsonl",
                           (f"{len({x['node'] for x in hit})} of 18 nodes in rack {rack} go to {first['state']} (first {first['node']}"
                            + (f", last {last['node']} at {_t(last['timestamp']).strftime('%H:%M:%S')}Z" if last is not first else "")
                            + f"): '{first['reason']}'"), first))
            back = [x for x in ds.scheduler if within(x["timestamp"]) and x["state"] == "idle"
                    and x["node"] in {y["node"] for y in hit} and _t(x["timestamp"]) > _t(first["timestamp"])]
            if back:
                lastup = max(back, key=lambda x: x["timestamp"])
                tl.append(_row(lastup["timestamp"], "IT Partner", "telemetry/scheduler_node_states.jsonl",
                               f"{len({x['node'] for x in back})} of 18 nodes back in service (last {lastup['node']}): '{lastup['reason']}'", lastup))

    # Facility telemetry for the event (CDU Redfish, electrical power monitoring), from just before the start to
    # just after the measured end, so the timeline shows the evidence behind the measured times.
    if wo:
        lo2, hi2 = start - timedelta(minutes=10), (end or start) + timedelta(minutes=10)
        near = lambda x: lo2 <= _t(x) <= hi2
        for e in ds.cdu:
            if e["cdu"] == unit and near(e["timestamp"]):
                tl.append(_row(e["timestamp"], "Landlord", "facility/cdu_redfish_events.jsonl",
                               f"CDU Redfish: {e['resource'].rsplit('/CDUs/', 1)[-1]} {e['property']} = {e['value']}", e))
        for e in ds.epms:
            if near(e["timestamp"]) and (unit in e["device"] or (ml or {}).get("rule") == "FA-6"):
                tl.append(_row(e["timestamp"], "Landlord", "facility/epms_events.jsonl", f"EPMS: {e['device']}: {e['event']}", e))
    tl.sort(key=lambda r: (r["t"], r["party"], r["event"]))
    metrics = [x for x in rows if x]

    gpus = (mi or {}).get("gpus") or (GPUS_PER_RACK if rack and nodes_down else 0)
    hours = (mi["measured_min"] / 60) if mi else ((end - start).total_seconds() / 3600 if (gpus and end) else 0.0)
    if ml:
        owner, rules = ml["owner"], [ml["rule"]]
        evidence = (f"Telemetry: {ml['event']} from {ml['t0']}. The work order names {ml['claimed_owner']} as the cause"
                    + (", which agrees." if ml["agrees"] else ", so the work order and the telemetry do not reconcile."))
    elif wo:
        owner, rules, evidence = wo["attribution"], [], ""
    else:
        owner, rules = "IT Partner", ["FA-2"]
        evidence = (f"Fault class {mi['fault_class']} on {mi['unit']}; the Landlord side was healthy at T0." if mi else "")
    refs = {x for x in ((ticket or {}).get("number"), (wo or {}).get("wo")) if x}
    findings, seen = [], set()
    for f in all_findings:
        if refs & set(f["refs"]) and f["id"] not in seen:
            seen.add(f["id"])
            findings.append({"id": f["id"], "severity": f["severity"], "summary": f["summary"]})
    for f in ds.ll_findings:
        if rack and (f"TO-{rack}" in f["summary"] or rack in (f.get("unit") or "")) and f["id"] not in seen:
            seen.add(f["id"])
            findings.append({"id": f["id"], "severity": f["severity"], "summary": f["summary"]})
    repeats = [{"ref": t["number"], "opened": t["opened_at"], "what": t["short_description"]} for t in ds.tickets
               if rack and t.get("rack") == rack and t is not ticket]
    repeats += [{"ref": w["wo"], "opened": w["opened"], "what": w["notes"]} for w in ds.work_orders
                if w is not wo and wo and w["unit"] == wo["unit"]]
    osr = 1 if gpus == 0 else 2 if gpus <= GPUS_PER_RACK else 3
    lane = "Landlord" if wo else "IT Partner"
    phases = [[lane, _iso(start), _iso(end), ("Event, as measured" if wo else "Out of service, as measured")]] if end else []
    marks = [[_iso(start), "Event start"]] + ([[_iso(end), "Restored" if wo and not ticket else "Back in service"]] if end else [])
    if wo and wo.get("restored_at") and end and abs((_t(wo["restored_at"]) - end).total_seconds()) >= 60:
        marks.append([wo["restored_at"], "Restored (work order)"])
    return {
        "kind": "event", "start": _iso(start), "end": _iso(end) if end else None,
        "labels": {"duration": "Event start to " + ("back in service" if ticket else "restored"), "gpus": "GPUs out of service",
                   "split": "GPU-hours: Landlord / IT Partner", "offline": "GPUs out of service"},
        "phases": phases, "marks": marks,
        "ref": ref, "ticket": ticket["number"] if ticket else None, "work_order": wo["wo"] if wo else None,
        "mops": [mp["mop_id"] for mp in mops], "unit": unit, "rack": rack,
        "title": (ticket or {}).get("short_description") or (wo or {}).get("notes"),
        "date": _iso(start)[:10], "power_lost": None, "handoff": None, "rts": _iso(end) if end else None,
        "attribution": {"owner": owner, "rules": rules, "evidence": evidence},
        "impact": {"gpus": gpus, "duration": _hm((end - start).total_seconds() / 60) if end else "",
                   "gpu_hours_total": round(gpus * hours, 1),
                   "gpu_hours_landlord": round(gpus * hours, 1) if owner == "Landlord" else 0.0,
                   "gpu_hours_it": round(gpus * hours, 1) if owner != "Landlord" else 0.0, "injuries": 0},
        "osr_suggested": {"level": osr, "name": OSR[osr][0], "definition": OSR[osr][1]},
        "metrics": metrics, "timeline": tl, "findings": findings, "csl": {},
        "credits_landlord": ds.ll_scorecard.get("credits", {}).get("payable"),
        "mop_overrun": None, "repeats": repeats,
        "people": {"landlord_engineer": wo["engineer"] if wo else None, "it_technician": ticket["assigned_to"] if ticket else None},
    }


def _record_review(ds: Dataset, r: dict[str, Any]) -> dict[str, Any]:
    """Facts for a change, a MOP, or a PM task, from its Incident Portal record (``scorecard.tickets.build``): the
    approved or due window, when the work actually happened, the alarms and findings, and its timeline."""
    n, t = r["native"], r["type"]
    ws, we = _t(r["start"]), _t(r["end"]) if r["end"] else None
    rows: list[dict | None] = []
    overrun, work_lo, work_hi = None, None, None
    if t == "mop":
        rows.append(_metric("Approved window", ws, we))
        wos = [w for w in ds.work_orders if w.get("mop_ref") == r["id"]]
        if wos:
            work_lo, work_hi = min(_t(w["opened"]) for w in wos), max(_t(w["closed"]) for w in wos if w.get("closed"))
        lo, hi = ws - timedelta(hours=1), (we or ws) + timedelta(hours=12)
        closes = [e for e in ds.busway if e.get("event") == "Breaker closed" and e["busway"] in n["assets"] and lo <= _t(e["timestamp"]) <= hi]
        if closes and we:
            last = max(_t(e["timestamp"]) for e in closes)
            if last > we:
                overrun = {"mop": r["id"], "window_end": _iso(we), "closed": _iso(last), "overrun": _hm((last - we).total_seconds() / 60)}
            rows.append(_metric("Window opens to equipment back to normal (last breaker closed)", ws, last, None,
                                f"{overrun['overrun']} past the approved window." if overrun else "Inside the approved window."))
    elif t == "chg":
        rows.append(_metric("Approved window", ws, we))
        inv = [x for x in r["timeline"] if x["source"].endswith("redfish_inventory_changes.jsonl")]
        if inv:
            work_lo, work_hi = _t(inv[0]["t"]), _t(inv[-1]["t"])
    else:   # PM task
        rows.append(_metric("Due window", ws, _t(n["due_end"])))
        if n.get("completed_at"):
            done = _t(n["completed_at"])
            m = _metric("Due window opens to task closed", ws, done, None,
                        "Closed inside the due window." if done <= _t(n["due_end"]) else "Closed after the due window.")
            rows.append(m)
    if work_lo and work_hi:
        inside = work_lo >= ws and (we is None or work_hi <= we)
        rows.append(_metric("Work recorded: first to last", work_lo, work_hi, None,
                            "Inside the approved window." if inside else "Outside the approved window."))
    nodes = set()
    if r["rack"] and we:
        prefix = r["rack"].lower() + "-"
        nodes = {x["node"] for x in ds.scheduler if x["node"].startswith(prefix) and x["state"] == "down" and ws <= _t(x["timestamp"]) <= we}
    gpus = 4 * len(nodes)
    hours = ((we - ws).total_seconds() / 3600) if (gpus and we) else 0.0
    osr = 1 if gpus == 0 else 2 if gpus <= GPUS_PER_RACK else 3
    lane = "Landlord" if r["partner"] == "Landlord" else "Customer" if t in ("chg", "mop") else "IT Partner"
    return {
        "kind": t, "start": r["start"], "end": r["end"],
        "labels": {"duration": "Due window" if t == "pm" else "Approved window", "gpus": "GPUs out of service",
                   "split": "GPU-hours: Landlord / IT Partner", "offline": "GPUs out of service"},
        "phases": [[lane, r["start"], r["end"], "Due window" if t == "pm" else "Approved window"]] if r["end"] else [],
        "marks": [[r["start"], "Opens"]] + ([[r["end"], "Closes"]] if r["end"] else []) + ([[overrun["closed"], "Equipment closed"]] if overrun else []),
        "ref": r["id"], "ticket": None, "work_order": None,
        "mops": [r["id"]] if t == "mop" else sorted(x for x in r["related"] if x.startswith("MOP-")),
        "unit": r["device"], "rack": r["rack"] or None, "title": r["summary"], "date": r["start"][:10],
        "power_lost": None, "handoff": None, "rts": None,
        "attribution": {"owner": r["partner"] if t != "chg" else "IT Partner", "rules": [], "evidence": ""},
        "impact": {"gpus": gpus, "duration": _hm((we - ws).total_seconds() / 60) if we else "", "gpu_hours_total": round(gpus * hours, 1),
                   "gpu_hours_landlord": 0.0, "gpu_hours_it": 0.0, "injuries": 0},
        "osr_suggested": {"level": osr, "name": OSR[osr][0], "definition": OSR[osr][1]},
        "metrics": [x for x in rows if x], "timeline": r["timeline"],
        "findings": [{"id": f["id"], "severity": f["severity"], "summary": f["summary"]} for f in r["findings"]],
        "csl": {}, "credits_landlord": ds.ll_scorecard.get("credits", {}).get("payable"),
        "mop_overrun": overrun, "repeats": [],
        "people": {"landlord_engineer": None, "it_technician": None},
    }


def build_index(ds: Dataset, records: list[dict[str, Any]] | None = None, devices: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every record in the Incident Portal (incidents, changes, work orders, MOPs, PM tasks) with the facts to
    start a review from it, plus what the PIR search matches on: related record numbers, the devices the record
    names, and the devices one connection away from them (``scorecard.devices``)."""
    from scorecard import devices as D
    if records is None:
        from scorecard.tickets import build
        records = build(ds.dir, reports=ds.reports)["records"]
    devices = devices or D.load()
    out = {}
    for r in records:
        f = build_review(ds, r["id"]) if r["type"] in ("inc", "wo") else _record_review(ds, r)
        if not f:
            continue
        names = D.names_in(devices, r["device"], r["rack"] and f"Rack {r['rack']}", r["summary"], f["unit"] or "")
        f |= {"type": r["type"], "type_label": r["type_label"], "partner": r["partner"], "priority": r["priority"],
              "related": r["related"], "devices": names, "near": D.neighbors(devices, names)}
        out[r["id"]] = f
    return out
