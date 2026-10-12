"""Incident Commander runbook and its replay against a past incident.

The runbook (config/incident_command.yaml) is the Customer's judgment. The clocks the contracts set are read from them
here: the joint bridge's minutes and the review's business days from the Interface Agreement, the leads' update
cadence from the stricter of the two SLAs' P1 terms, the partners' page from NT-1, and the paging tree from
config/customer_notifications.yaml. The replay measures each step from records only: the alarms, the busway, the
scheduler, the partners' page delivery log (data/changes/), and the bridge's comms log (data/incident_comms/).

A missed step is a process finding for the post-incident review, never an SLA default.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from scorecard.pir import Dataset, _hm, _iso, _t, build_review
from scorecard.sla_model import load_interface_agreement, load_sla

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "incident_command.yaml"
NOTIFY = ROOT / "config" / "customer_notifications.yaml"
COMMS = ROOT / "data" / "incident_comms"
PAGES = ROOT / "data" / "changes" / "notification_log.json"
REVIEWS = ROOT / "pir" / "reviews"
SLAS = {"IT Partner": ROOT / "sla" / "it_partner.yaml", "Landlord": ROOT / "sla" / "ot_partner.yaml"}
COMMON = ROOT / "sla" / "common.yaml"
CHANNEL = {"sms": "SMS", "email": "email"}


def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _number(text: str, unit: str) -> int:
    """The number before a unit in a contract sentence ("within 15 minutes" gives 15)."""
    m = re.search(rf"(\d+) {unit}", text)
    if not m:
        raise ValueError(f"no '{unit}' clock in: {text}")
    return int(m.group(1))


def contract_clocks(ia: dict | None = None, slas: dict | None = None) -> dict[str, Any]:
    ia = ia or load_interface_agreement()
    slas = slas or {k: load_sla(v) for k, v in SLAS.items()}
    p1 = {k: next(p for p in s["priorities"] if p["id"] == "P1") for k, s in slas.items()}
    nt1 = next(n for n in ia["alarm_notification"]["notifications"] if n["id"] == "NT-1")
    return {
        "bridge_min": _number(ia["incident_command"]["bridge"], "minutes"),
        "pir_business_days": _number(ia["incident_command"]["post_incident"], "business days"),
        "lead_cadence_min": min(p["update_cadence_min"] for p in p1.values()),
        "lead_cadence_from": {k: p["update_cadence_min"] for k, p in p1.items()},
        "page_min": nt1["within_min"],
    }


def severity_matrix(cfg: dict, slas: dict | None = None) -> dict[str, Any]:
    """The SLAs' priorities side by side, with the stricter clock and how the Customer commands at each, then the
    Customer's internal severity levels."""
    slas = slas or {k: load_sla(v) for k, v in SLAS.items()}
    rows = []
    for pid in ("P1", "P2", "P3", "P4"):
        p = {k: next(x for x in s["priorities"] if x["id"] == pid) for k, s in slas.items()}
        clock = lambda key: min((x[key] for x in p.values() if x[key] is not None), default=None)
        rows.append({"id": pid, "names": {k: x["name"] for k, x in p.items()},
                     "criteria": {k: x["criteria"] for k, x in p.items()},
                     "acknowledge_min": clock("acknowledge_min"), "engaged_on_site_min": clock("engaged_on_site_min"),
                     "restore_min": clock("restore_min"), "update_cadence_min": clock("update_cadence_min"),
                     "command": cfg["command"][pid]})
    common = yaml.safe_load(COMMON.read_text(encoding="utf-8"))
    internal = [{"id": x["id"], "name": x["name"], "escalation": x["escalation"]} for x in common["breach_severity"]["levels"]]
    return {"priorities": rows, "internal": internal}


def paging_tree(ia: dict | None = None) -> dict[str, Any]:
    """Who is paged for a critical alarm and who is told next if nobody acknowledges."""
    ia = ia or load_interface_agreement()
    n = yaml.safe_load(NOTIFY.read_text(encoding="utf-8"))
    nt1 = next(x for x in ia["alarm_notification"]["notifications"] if x["id"] == "NT-1")
    rule = next(r for r in n["rules"] if r["event"] == "critical")
    g = n["groups"]
    via = lambda chans: " and ".join(CHANNEL[c] for c in chans)
    levels = [{"min": 0, "who": "The party that owns the equipment", "via": f"{nt1['channels']}, within {nt1['within_min']} minutes (NT-1)"},
              {"min": 0, "who": " and ".join(g[t]["label"] for t in rule["to"]), "via": f"{via(rule['business'])} from the Customer alarm board, at any hour"}]
    levels += [{"min": e["after_min"], "who": g[e["to"]]["label"], "via": f"{via(e['via'])} if nobody has acknowledged"} for e in rule["escalate"]]
    shifts = [{"label": s["label"], "days": s["days"], "start": s["start"], "end": s["end"], "primary": s["primary"], "secondary": s["secondary"]}
              for s in n["schedule"]]
    return {"levels": levels, "shifts": shifts, "timezone": n["timezone"]}


def runbook(cfg: dict | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    ia = load_interface_agreement()
    slas = {k: load_sla(v) for k, v in SLAS.items()}
    cc = contract_clocks(ia, slas)
    clocks = cfg["clocks"]
    due = {"pages": f"{cc['page_min']} min from the alarm (NT-1)", "page_ack": f"{clocks['page_ack_min']} min from the page",
           "declare": f"{clocks['declare_min']} min from detection", "first_leadership": f"{clocks['first_leadership_min']} min from detection",
           "bridge": f"{cc['bridge_min']} min from detection (Interface Agreement)", "leads_join": f"{clocks['lead_join_min']} min from the bridge opening",
           "lead_cadence": f"every {cc['lead_cadence_min']} min (the stricter P1 cadence)",
           "leadership_cadence": f"every {clocks['leadership_cadence_min']} min", "change_windows": "before the window closes",
           "restoration_declared": f"{clocks['restoration_declare_min']} min from the feed closing",
           "restoration_confirmed": "before the IT Partner powers on", "milestone_updates": f"{clocks['milestone_update_min']} min from each milestone",
           "bridge_close": "after return to service and change work closed", "pir": f"{cc['pir_business_days']} business days (Interface Agreement)"}
    steps = [{**s, "due": due[s["id"]]} for s in cfg["steps"]]
    return {"intro": cfg["intro"], "commander": ia["incident_command"]["commander"], "roles": ia["incident_command"]["roles"],
            "bridge_rule": ia["incident_command"]["bridge"], "post_incident": ia["incident_command"]["post_incident"],
            "handoff": next(h for h in ia["handoffs"] if h["id"] == "HO-1"),
            "clocks": cc, "phases": cfg["phases"], "steps": steps, "severity": severity_matrix(cfg, slas),
            "paging": paging_tree(ia), "templates": cfg["templates"]}


def _business_days(a: date, b: date) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def _check(label: str, start: datetime | None, at: datetime | None, target: float | None, detail: str = "", met: bool | None = None) -> dict[str, Any]:
    mins = (at - start).total_seconds() / 60 if (start and at) else None
    if met is None:
        met = at is not None and mins is not None and (target is None or mins <= target)
    return {"label": label, "from": _iso(start) if start else None, "at": _iso(at) if at else None,
            "elapsed": _hm(mins) if mins is not None else None, "minutes": round(mins, 1) if mins is not None else None,
            "target": target, "met": met, "detail": detail}


def _gaps(label: str, start: datetime, times: list[datetime], end: datetime, every: int) -> list[dict[str, Any]]:
    """One check per interval between updates: from joining (or the last update) to the next, until the part ends."""
    out, prev = [], start
    for t in [x for x in times if x <= end]:
        out.append(_check(label, prev, t, every))
        prev = t
    if (end - prev).total_seconds() / 60 > every:      # silence before the part ended
        out.append(_check(label, prev, None, every, f"no update before {_iso(end)[11:16]}Z", met=False))
    return out


def replay(ref: str, ds: Dataset | None = None, cfg: dict | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    ds = ds or Dataset(ROOT / "data" / "sample")
    rb = runbook(cfg)
    clocks, cc = cfg["clocks"], rb["clocks"]
    f = build_review(ds, ref)
    log = json.loads((COMMS / f"{ref}.json").read_text(encoding="utf-8"))
    offset = timedelta(hours=yaml.safe_load(NOTIFY.read_text(encoding="utf-8"))["utc_offset_h"])
    log = [{**e, "local": (_t(e["t"]) + offset).strftime("%H:%M:%S")} for e in log]
    review = yaml.safe_load((REVIEWS / f"{cfg['replays'][ref]['review']}.yaml").read_text(encoding="utf-8"))
    t0, handoff, rts = _t(f["start"]), _t(f["handoff"]), _t(f["end"])
    rack = f["rack"]
    kind = lambda k, party=None: [e for e in log if e["kind"] == k and (party is None or e["party"] == party)]
    at = lambda e: _t(e["t"]) if e else None
    first = lambda k, party=None: next(iter(kind(k, party)), None)

    pages = [p for p in json.loads(PAGES.read_text(encoding="utf-8"))
             if p["channel"] == "page" and p["device"] == f["unit"] and t0 <= _t(p["alarm_time"]) <= rts]
    checks: dict[str, list[dict]] = {}
    checks["pages"] = [_check(f"{p['party']} page to the {p['recipient']}", _t(p["alarm_time"]), _t(p["sent_at"]), cc["page_min"],
                              f"'{p['signal']}'") for p in pages]
    first_page = min((_t(p["sent_at"]) for p in pages), default=None)
    checks["page_ack"] = [_check("On-call primary acknowledges", first_page, at(first("page_ack")), clocks["page_ack_min"])]
    checks["declare"] = [_check("Incident Commander takes command", t0, at(first("ic_declared")), clocks["declare_min"])]
    lead_updates = kind("leadership_update")
    checks["first_leadership"] = [_check("First leadership notice", t0, at(lead_updates[0]) if lead_updates else None, clocks["first_leadership_min"])]
    bridge = at(first("bridge_open"))
    checks["bridge"] = [_check("Joint bridge open", t0, bridge, cc["bridge_min"])]
    joins = {e["party"]: at(e) for e in kind("lead_joined")}
    checks["leads_join"] = [_check(f"{p} lead joins", bridge, joins.get(p), clocks["lead_join_min"]) for p in ("Landlord", "IT Partner")]

    declared, rts_said, closed = at(first("restoration_declared")), at(first("rts_declared")), at(first("bridge_closed"))
    ends = {"Landlord": declared or rts, "IT Partner": rts_said or rts}
    checks["lead_cadence"] = []
    for p in ("Landlord", "IT Partner"):
        times = [at(e) for e in log if e["party"] == p and e["kind"] in ("lead_update", "restoration_declared", "rts_declared")]
        checks["lead_cadence"] += _gaps(f"{p} lead update", joins[p], times, ends[p], cc["lead_cadence_min"])
    checks["leadership_cadence"] = _gaps("Leadership update", at(lead_updates[0]), [at(e) for e in lead_updates[1:]],
                                         closed or rts, clocks["leadership_cadence_min"])

    decisions = kind("window_decision")
    checks["change_windows"] = []
    for mp in ds.mops:
        if mp["mop_id"] in f["mops"] and t0 <= _t(mp["window_end"]) <= rts:
            d = next((at(e) for e in decisions if mp["mop_id"] in e["text"] and at(e) <= _t(mp["window_end"])), None)
            checks["change_windows"].append(_check(f"Decision on {mp['mop_id']} before its window closed", t0, d, None,
                                                   f"window closed {mp['window_end'][11:16]}Z; " + ("decided" if d else "no decision in the comms log"),
                                                   met=d is not None))

    checks["restoration_declared"] = [_check("Landlord declares restoration on the bridge", handoff, declared, clocks["restoration_declare_min"],
                                             f"busway shows the feed closed at {f['handoff'][11:19]}Z")]
    confirmed = at(first("restoration_confirmed"))
    feeds = {}
    for e in sorted((e for e in ds.busway if e.get("rack") == rack and "tapoff" in e), key=lambda e: e["timestamp"]):
        if confirmed and _t(e["timestamp"]) <= confirmed:
            feeds[e["tapoff"]] = e["event"].lower()
    open_feeds = sorted(k for k, v in feeds.items() if "open" in v)
    reclosed = {e["tapoff"]: e["timestamp"] for e in sorted(ds.busway, key=lambda e: e["timestamp"], reverse=True)
                if e.get("tapoff") in open_feeds and "closed" in e["event"].lower() and confirmed and _t(e["timestamp"]) > confirmed}
    checks["restoration_confirmed"] = [_check("Customer confirms restoration from telemetry", declared, confirmed, None,
                                              ("every feed closed" if not open_feeds else "; ".join(
                                                  f"{k} still open at confirmation" + (f" (closed {reclosed[k][11:19]}Z)" if k in reclosed else "") for k in open_feeds)),
                                              met=confirmed is not None and not open_feeds)]
    checks["milestone_updates"] = []
    for name, t in (("restoration", handoff), ("return to service", rts)):
        nxt = next((at(e) for e in lead_updates if at(e) >= t), None)
        checks["milestone_updates"].append(_check(f"Leadership told of {name}", t, nxt, clocks["milestone_update_min"]))
    work_closed = max((_t(e["timestamp"]) for e in ds.busway if e.get("rack") == rack and "tapoff" in e and "closed" in e["event"].lower()
                       and _t(e["timestamp"]) <= rts + timedelta(hours=6)), default=None)
    checks["bridge_close"] = [_check("Bridge closed after return to service and change work closed", rts, closed, None,
                                     f"last tap-off closed {_iso(work_closed)[11:19]}Z" if work_closed else "",
                                     met=bool(closed and rts_said and closed >= rts_said and (work_closed is None or work_closed <= closed)))]
    held = date.fromisoformat(review["review_meeting"])
    bd = _business_days(t0.date(), held)
    checks["pir"] = [{"label": "Joint post-incident review held", "from": f["date"], "at": review["review_meeting"],
                      "elapsed": f"{bd} business days", "minutes": None, "target": cc["pir_business_days"],
                      "met": bd <= cc["pir_business_days"], "detail": review["id"]}]

    steps = []
    for s in rb["steps"]:
        rows = checks[s["id"]]
        steps.append({"id": s["id"], "phase": s["phase"], "text": s["text"], "due": s["due"], "checks": rows,
                      "met": all(r["met"] for r in rows) if rows else None,
                      "note": cfg["replays"][ref]["notes"].get(s["id"])})
    met = [s for s in steps if s["met"] is True]
    missed = [s for s in steps if s["met"] is False]
    return {"ref": ref, "review": review["id"], "title": review["title"], "unit": f["unit"], "start": f["start"],
            "handoff": f["handoff"], "end": f["end"], "steps": steps, "log": log,
            "summary": {"steps": len([s for s in steps if s["met"] is not None]), "met": len(met), "missed": len(missed)}}


def build() -> dict[str, Any]:
    cfg = load_config()
    ds = Dataset(ROOT / "data" / "sample")
    return {"runbook": runbook(cfg), "replays": [replay(ref, ds, cfg) for ref in cfg["replays"]]}
