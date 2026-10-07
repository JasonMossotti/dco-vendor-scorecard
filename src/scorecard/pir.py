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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
    mops = [m for m in ds.mops if any(e["busway"] in m["assets"] for e in bw_events) or (wo and wo["unit"] in m["assets"])]
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
        m("Landlord restoration (handoff)", power_lost, handoff, 240, "Landlord P1 restore target 4 h"),
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


def build_index(ds: Dataset) -> dict[str, Any]:
    """Every P1 or P2 ticket and work order with enough facts to auto-fill a review."""
    refs = [t["number"] for t in ds.tickets if t["priority"] in ("P1", "P2")]
    refs += [w["wo"] for w in ds.work_orders if w["priority"] in ("P1", "P2")]
    out = {}
    for r in refs:
        rv = build_review(ds, r)
        if rv:
            out[r] = rv
    return out
