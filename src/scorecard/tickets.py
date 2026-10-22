"""The Incident Portal: every partner ticket, change, work order, MOP, and PM task, read the way the
Customer's read-only records access would deliver them (common terms, measurement: Records access).

Portfolio demo; all data fictional. Six record types from four systems:

* ``INC``  IT Partner incidents, from the IT Partner's ticketing system (a ServiceNow-style record).
* ``CHG``  IT Partner changes approved by the Customer CAB, from the Customer's change management system.
* ``WO``   Landlord work orders, from the Landlord's maintenance management system (a Maximo-style record).
* ``MOP``  Landlord methods of procedure approved by the Customer change board.
* ``PM``   Landlord preventive maintenance tasks, from the same maintenance management system.
* ``SIR``  Security Partner incident reports for door alarms, from its dispatch log, beside the Customer's access
           control system (the alarm, the console acknowledgement, and the guard's badge at the door).

Each record carries the partner's own fields exactly as stored ("as recorded"), a timeline built the way
the post-incident review builds one (``scorecard.pir.build_review``), the alarms the alarm board ties to it,
the Customer's own measurement (``reports/scorecard.json``, ``reports/landlord_scorecard.json``, and
``reports/security_findings.json``), and the
findings that name it. People are shown by their person ID, never by name. The portal only reads.
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
SAMPLE = ROOT / "data" / "sample"
CHANGES = ROOT / "data" / "changes"
SECURITY = ROOT / "data" / "security"
FIRE = ROOT / "data" / "fire"
REPORTS = ROOT / "reports"
UTC = timezone.utc
LOCAL = timezone(timedelta(hours=-5), "CDT")

# The record numbers the portal opens; every page links them to tickets/#<number>.
ID_PATTERN = r"INC\d{7}|CHG\d{7}|WO-\d{5}|MOP-\d{3}|PM-\d{4}|SIR-\d{5}|IMP-\d{4}"
ID_RE = re.compile(rf"\b(?:{ID_PATTERN})\b")

TYPES = {   # key: (label, plural, partner, system of record)
    "inc": ("Incident", "Incidents", "IT Partner", "IT Partner ticketing system (ServiceNow-style incident record)"),
    "chg": ("Change", "Changes", "IT Partner", "Customer change management system (CAB record)"),
    "wo": ("Work order", "Work orders", "Landlord", "Landlord maintenance management system (Maximo-style work order)"),
    "mop": ("Method of procedure", "Methods of procedure (Landlord changes)", "Landlord", "Customer change management system (Landlord MOP approval)"),
    "pm": ("Maintenance task", "Preventive maintenance tasks", "Landlord", "Landlord maintenance management system (preventive maintenance record)"),
    "sir": ("Security incident", "Security incidents (door alarms)", "Security Partner", "Security Partner dispatch log (door alarm response record)"),
    "imp": ("Impairment", "Fire protection impairments", "Landlord", "Landlord impairment log (fire protection)"),
}
SOURCE = {"inc": "vendor/tickets.json", "chg": "customer/cab_changes.json", "wo": "landlord/work_orders.json",
          "mop": "customer/landlord_mop_approvals.json", "pm": "landlord/pm_records.csv", "sir": "security/dispatch_log.json",
          "imp": "fire/impairments.csv"}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _local(s: str) -> str:
    return _t(s).astimezone(LOCAL).strftime("%H:%M:%S %Z")


def _row(t: str, party: str, source: str, event: str, record: dict | None = None) -> dict[str, Any]:
    return {"t": t, "local": _local(t), "party": party, "source": source, "event": event,
            "record": json.dumps(record, sort_keys=True) if record is not None else ""}


def _hm(minutes: float) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


class Redactor:
    """People are shown by person ID: the IT Partner's records carry technician names, the Landlord's carry IDs."""

    def __init__(self, data_dir: Path):
        rows = list(csv.DictReader((data_dir / "vendor" / "personnel.csv").open(encoding="utf-8")))
        self.ids = {r["name"]: r["person_id"] for r in rows}
        self.re = re.compile("|".join(re.escape(n) for n in sorted(self.ids, key=len, reverse=True))) if self.ids else None

    def text(self, s: str) -> str:
        return self.re.sub(lambda m: self.ids[m.group(0)], s) if self.re and s else s

    def deep(self, v: Any) -> Any:
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, list):
            return [self.deep(x) for x in v]
        if isinstance(v, dict):
            return {k: self.deep(x) for k, x in v.items()}
        return v


def security_dir(data_dir: Path) -> Path | None:
    """The security layer beside a dataset: data/security for the sample, <month>/security for a generated month."""
    data_dir = Path(data_dir)
    for d in (data_dir / "security", SECURITY if data_dir.resolve() == SAMPLE.resolve() else None):
        if d and (d / "dispatch_log.json").exists():
            return d
    return None


def fire_dir(data_dir: Path) -> Path | None:
    """The fire protection layer beside a dataset: data/fire for the sample, <month>/fire for a generated month."""
    data_dir = Path(data_dir)
    for d in (data_dir / "fire", FIRE if data_dir.resolve() == SAMPLE.resolve() else None):
        if d and (d / "impairments.csv").exists():
            return d
    return None


def _read(data_dir: Path) -> dict[str, Any]:
    js = lambda f: json.loads((data_dir / f).read_text(encoding="utf-8"))
    sec = security_dir(data_dir)
    return {"inc": js(SOURCE["inc"]), "chg": js(SOURCE["chg"]), "wo": js(SOURCE["wo"]), "mop": js(SOURCE["mop"]),
            "pm": list(csv.DictReader((data_dir / SOURCE["pm"]).open(encoding="utf-8"))),
            "sir": json.loads((sec / "dispatch_log.json").read_text(encoding="utf-8")) if sec else [], "sec": sec,
            "imp": list(csv.DictReader((fire_dir(data_dir) / "impairments.csv").open(encoding="utf-8"))) if fire_dir(data_dir) else [],
            "fire": fire_dir(data_dir)}


def ids(data_dir: Path = SAMPLE) -> list[str]:
    """Every record number the portal holds (the pages link only these)."""
    return sorted(_ids(str(data_dir)))


@lru_cache(maxsize=4)
def _ids(data_dir: str) -> frozenset[str]:
    r = _read(Path(data_dir))
    return frozenset([x["number"] for x in r["inc"]] + [x["change_id"] for x in r["chg"]] + [x["wo"] for x in r["wo"]]
                     + [x["mop_id"] for x in r["mop"]] + [x["task_id"] for x in r["pm"]] + [x["sir"] for x in r["sir"]]
                     + [x["imp_id"] for x in r["imp"]])


def _measures(reports: Path) -> tuple[dict, dict, list, dict]:
    if not (reports / "scorecard.json").exists():
        # A generated month has no engine reports, so the records carry only what the partners wrote.
        return {}, {}, [], {}
    sc = json.loads((reports / "scorecard.json").read_text(encoding="utf-8"))
    ll = json.loads((reports / "landlord_scorecard.json").read_text(encoding="utf-8"))
    it_find = json.loads((reports / "findings.json").read_text(encoding="utf-8"))["findings"]
    ll_find = json.loads((reports / "landlord_findings.json").read_text(encoding="utf-8"))
    by_ticket = {k: i for i in sc["incidents"] for k in i["tickets"]}
    by_wo = {a["work_order"]: a for a in ll["attribution"] if a.get("work_order")}
    findings = [{"id": f["id"], "partner": "IT Partner", "severity": f["severity"], "title": f["title"], "summary": f["summary"],
                 "refs": f["tickets"], "sla_refs": f["sla_refs"]} for f in it_find]
    findings += [{"id": f["id"], "partner": "Landlord", "severity": f["severity"], "title": f["title"], "summary": f["summary"],
                  "refs": f["tickets"], "sla_refs": f["sla_refs"]} for f in ll_find]
    if (reports / "security_findings.json").exists():
        sec_find = json.loads((reports / "security_findings.json").read_text(encoding="utf-8"))
        findings += [{"id": f["id"], "partner": "Security Partner", "severity": f["severity"], "title": f["title"], "summary": f["summary"],
                      "refs": f["tickets"], "sla_refs": f["sla_refs"]} for f in sec_find]
    return by_ticket, by_wo, findings, sc


def build(data_dir: Path = SAMPLE, changes_dir: Path = CHANGES, reports: Path = REPORTS) -> dict[str, Any]:
    """Every record with its fields, timeline, links, measurement, and findings, newest first."""
    from scorecard import alarms as A
    from scorecard.pir import Dataset, build_review
    from scorecard.sla_model import load_sla

    raw = _read(data_dir)
    red = Redactor(data_dir)
    ds = Dataset(data_dir, reports)
    check = A.run_check(data_dir, changes_dir)
    alarms = [A.alarm_dict(a) for a in check["alarms"]]
    by_ticket, by_wo, findings, sc = _measures(reports)
    targets = {p["id"]: p["restore_min"] for p in load_sla()["priorities"]}
    inventory = [json.loads(x) for x in (data_dir / "telemetry" / "redfish_inventory_changes.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    ll_badges = ds.ll_badges
    records: dict[str, dict[str, Any]] = {}

    def base(ref, t, start, end, *, state, priority="", summary, device="", location="", hall="", rack="", assigned="", category=""):
        label, _, partner, system = TYPES[t]
        records[ref] = {"id": ref, "type": t, "type_label": label, "partner": partner, "system": system, "source": SOURCE[t],
                        "state": state, "priority": priority, "start": start, "end": end, "summary": red.text(summary),
                        "device": device, "location": location, "hall": hall, "rack": rack or "", "assigned": assigned,
                        "category": category, "related": set(), "alarms": [], "findings": [], "measured": None,
                        "native": None, "timeline": [], "markers": [], "notes": [], "parts": []}
        return records[ref]

    for k in raw["inc"]:
        r = base(k["number"], "inc", k["opened_at"], k["resolved_at"], state=k["state"], priority=k["priority"],
                 summary=k["short_description"], device=k["configuration_item"], location=f"Hall {k['rack'][0]}, rack {k['rack']}",
                 hall=k["hall"], rack=k["rack"], assigned=k["assigned_to"], category=k["category"])
        r["native"] = red.deep(k)
        r["notes"] = [{"at": n["at"], "by": red.text(n["author"]), "text": red.text(n["text"])} for n in k["work_notes"]]
        r["parts"] = [dict(p) for p in k.get("parts_used", [])]
        r["close_code"] = k.get("close_code", "")
        m = re.search(r"Landlord (WO-\d{5})", k["short_description"])
        if m:
            r["related"].add(m.group(1))
    for w in raw["wo"]:
        r = base(w["wo"], "wo", w["opened"], w["closed"], state="Closed" if w.get("closed") else "In progress", priority=w["priority"],
                 summary=w["notes"], device=w["unit"], location=w["room"], hall=_hall(w["room"]), rack=w["unit"][5:] if w["unit"].startswith("Rack ") else "",
                 assigned=w["engineer"], category=w.get("fault_class") or ("Planned (MOP)" if w.get("mop_ref") else ""))
        r["native"] = red.deep(w)
        r["work_type"] = "Planned under a MOP" if w.get("mop_ref") else "Corrective"
        if w.get("parts"):
            r["parts"] = [{"part": w["parts"]}]
        if w.get("mop_ref"):
            r["related"].add(w["mop_ref"])
    for c in raw["chg"]:
        r = base(c["change_id"], "chg", c["window_start"], c["window_end"], state=c["state"], summary=c["summary"],
                 device=f"Rack {c['rack']}", location=f"Hall {c['rack'][0]}, rack {c['rack']}", hall=f"HALL-{c['rack'][0]}", rack=c["rack"],
                 category="Firmware" if "firmware" in c["summary"].lower() else "Change")
        r["native"] = dict(c)
    for mp in raw["mop"]:
        r = base(mp["mop_id"], "mop", mp["window_start"], mp["window_end"], state="Approved", summary=mp["title"],
                 device=", ".join(mp["assets"]), location=", ".join(mp["assets"]), category="Landlord change")
        r["native"] = dict(mp)
    sec = _security(raw["sec"]) if raw["sec"] else None
    for x in raw["sir"]:
        a = sec["alarms"][x["alarm_id"]]
        door = sec["doors"].get(x["door"], {})
        r = base(x["sir"], "sir", a["timestamp"], x["closed"] or None, state="Closed" if x["closed"] else "Open", priority=x["priority"],
                 summary=f"{a['event']} at {door.get('name', x['door'])}: {x['disposition']}", device=x["door"],
                 location=door.get("name", x["door"]), hall=f"HALL-{door['hall']}" if door else "", assigned=x["dispatched"], category=x["type"])
        r["native"] = dict(x)
    fire = _fire(raw["fire"], data_dir) if raw["fire"] else None
    for x in raw["imp"]:
        devs = x["devices"].split(";")
        r = base(x["imp_id"], "imp", x["start"], x["restored_at"] or None, state="Restored" if x["restored_at"] else "Open",
                 priority="P1" if x["type"] == "unplanned" else "", summary=f"{x['reason']}: {', '.join(devs)}", device=devs[0],
                 location=", ".join(devs), hall=_hall(devs[0]), assigned=x["engineer"], category=x["system"])
        r["native"] = dict(x)
        r["work_type"] = "Planned impairment" if x["type"] == "planned" else "Unplanned impairment"
        r["related"].update(v for v in (x["mop_ref"], x["pm_ref"]) if v)
    if fire:
        findings += fire["findings"]
    findings += _credential_findings(data_dir)
    for p in raw["pm"]:
        r = base(p["task_id"], "pm", p["due_start"], p["completed_at"] or p["due_end"], state="Complete" if p["completed_at"] else "Open",
                 summary=f"{p['task']}: {p['asset']}", device=p["asset"], location=p["asset"], hall=_hall(p["asset"]),
                 assigned=p["engineer"], category=p["system"])
        r["native"] = dict(p)
        if p.get("mop_ref"):
            r["related"].add(p["mop_ref"])

    # Links both ways, alarms, findings, measurement.
    for ref, r in list(records.items()):
        for x in list(r["related"]):
            if x in records:
                records[x]["related"].add(ref)
    for a in alarms:
        for ref in {(a.get("ticket") or {}).get("id"), a.get("change")} - {None, ""}:
            if ref in records:
                records[ref]["alarms"].append({k: a[k] for k in ("id", "partner", "device", "signal", "summary", "severity", "raised",
                                                                  "cleared", "cls", "change", "location", "rack")})
    for f in findings:
        for ref in f["refs"]:
            if ref in records:
                records[ref]["findings"].append({k: red.deep(v) for k, v in f.items() if k != "refs"} | {"refs": f["refs"]})
                if f.get("severity") != "Credential":   # one person's lapsed credential does not relate the work it touched
                    records[ref]["related"].update(x for x in f["refs"] if x != ref and x in records)
    for ref, r in records.items():
        if r["type"] == "inc" and ref in by_ticket:
            i = by_ticket[ref]
            reported = (_t(r["native"]["resolved_at"]) - _t(r["native"]["reported_outage_start"])).total_seconds() / 60
            r["measured"] = {"kind": "IT", "ticket_of_record": i["key"], "merged": [x for x in i["tickets"] if x != ref],
                             "t0": i["t0"], "rts": i["rts"], "measured_min": i["measured_min"], "measured": _hm(i["measured_min"]),
                             "reported_min": round(reported, 1), "reported": _hm(reported), "target_min": targets[i["priority"]],
                             "within_target": i["measured_min"] <= targets[i["priority"]], "validated": i["validated"],
                             "fault_class": i["fault_class"], "engaged_min": i["engaged_min"],
                             "gap_min": round(i["measured_min"] - reported, 1) if not [x for x in i["tickets"] if x != ref] else None}
            r["related"].update(x for x in i["tickets"] if x != ref)
        if r["type"] == "wo" and ref in by_wo:
            a = by_wo[ref]
            mins = (_t(a["restored"]) - _t(a["t0"])).total_seconds() / 60 if a.get("restored") else None
            r["measured"] = {"kind": "Landlord", "t0": a["t0"], "restored": a["restored"], "measured_min": round(mins, 1) if mins is not None else None,
                             "measured": _hm(mins) if mins is not None else "", "owner": a["owner"], "claimed_owner": a["claimed_owner"],
                             "agrees": a["agrees"], "rule": a["rule"], "event": a["event"], "capacity_lost": a["capacity_lost"]}

    # Timelines.
    for ref, r in records.items():
        t = r["type"]
        if t in ("inc", "wo"):
            rv = build_review(ds, ref)
            tl = [dict(x, event=red.text(x["event"]), record=red.text(x["record"])) for x in (rv["timeline"] if rv else [])]
        elif t == "chg":
            n = r["native"]
            tl = [_row(n["window_start"], "Customer", SOURCE[t], f"{ref} window opens: {n['summary']} ({n['approved_by']}, {n['state']})", n),
                  _row(n["window_end"], "Customer", SOURCE[t], f"{ref} window closes")]
            lo, hi = _t(n["window_start"]) - timedelta(hours=1), _t(n["window_end"]) + timedelta(hours=1)
            for e in inventory:
                if e["rack"] == n["rack"] and lo <= _t(e["observed_at"]) <= hi:
                    tl.append(_row(e["observed_at"], "IT Partner", "telemetry/redfish_inventory_changes.jsonl",
                                   f"Redfish: {e['host'] or e['resource'].rsplit('/', 1)[-1]} {e['property']} {e['old_value']} → {e['new_value']}", e))
            for k in raw["inc"]:
                if k["rack"] == n["rack"] and lo <= _t(k["opened_at"]) <= hi:
                    tl.append(_row(k["opened_at"], "IT Partner", SOURCE["inc"], f"Ticket {k['number']} opened on the same rack ({k['priority']}): {red.text(k['short_description'])}"))
                    r["related"].add(k["number"]); records[k["number"]]["related"].add(ref)
        elif t == "mop":
            n = r["native"]
            tl = [_row(n["approved_at"], "Customer", SOURCE[t], f"{ref} approved by {n['approved_by']}: {n['title']}", n),
                  _row(n["window_start"], "Customer", SOURCE[t], f"{ref} window opens (assets {', '.join(n['assets'])})"),
                  _row(n["window_end"], "Customer", SOURCE[t], f"{ref} window closes")]
            for w in raw["wo"]:
                if w.get("mop_ref") == ref:
                    tl += [_row(w["opened"], "Landlord", SOURCE["wo"], f"Work order {w['wo']} opened under {ref}: {w['notes']}", w),
                           _row(w["closed"], "Landlord", SOURCE["wo"], f"Work order {w['wo']} closed")]
            for p in raw["pm"]:
                if p.get("mop_ref") == ref and p["completed_at"]:
                    tl.append(_row(p["completed_at"], "Landlord", SOURCE["pm"], f"{p['task_id']} completed by {p['engineer']}: {p['result']}", p))
        elif t == "sir":
            n = r["native"]
            a = sec["alarms"][n["alarm_id"]]
            tl = [_row(a["timestamp"], "Customer", "security/door_alarms.jsonl", f"Access control alarm {a['alarm_id']}: {a['event']} at {n['door']} ({a['priority']})", a)]
            if a["console_ack_at"]:
                tl.append(_row(a["console_ack_at"], "Security Partner", "security/door_alarms.jsonl", f"Alarm acknowledged at the security console"))
            tl.append(_row(n["opened"], "Security Partner", SOURCE[t], f"{ref} opened; {n['dispatched']} dispatched to {n['door']}"))
            if n["on_scene"]:
                tl.append(_row(n["on_scene"], "Security Partner", SOURCE[t], f"{ref}: guard on scene (dispatch log)"))
            if a["cleared_at"]:
                tl.append(_row(a["cleared_at"], "Customer", "security/door_alarms.jsonl", f"Door {n['door']} closed; alarm cleared"))
            lo, hi = _t(a["timestamp"]), _t(n["closed"]) if n["closed"] else _t(a["timestamp"]) + timedelta(hours=1)
            badges = [b for b in sec["badges"] if b["reader"] == n["door"] and lo <= _t(b["timestamp"]) <= hi]
            for b in badges:
                tl.append(_row(b["timestamp"], "Security Partner", "security/guard_badges.csv", f"{b['guard_id']} badged {b['direction']} at {n['door']}", b))
            if not badges:
                tl.append(_row(n["closed"] or a["timestamp"], "Customer", "security/guard_badges.csv", f"No guard badge at {n['door']} between the alarm and the close"))
            if n["closed"]:
                tl.append(_row(n["closed"], "Security Partner", SOURCE[t], f"{ref} closed: {n['disposition']}"))
            target = sec["on_site"][a["priority"]]
            first = min((_t(b["timestamp"]) for b in badges), default=None)
            mins = (first - lo).total_seconds() / 60 if first else None
            r["measured"] = {"kind": "Security", "t0": a["timestamp"], "arrived": _iso(first) if first else None,
                             "measured_min": round(mins, 1) if mins is not None else None, "measured": _hm(mins) if mins is not None else "",
                             "target_min": target, "within_target": mins is not None and mins <= target}
        elif t == "imp":
            tl, r["measured"] = _imp_timeline(ref, r["native"], fire)
        else:   # PM
            n = r["native"]
            tl = [_row(n["due_start"], "Landlord", SOURCE[t], f"{ref} due window opens: {n['task']} ({n['asset']})", n),
                  _row(n["due_end"], "Landlord", SOURCE[t], f"{ref} due window closes")]
            if n["completed_at"]:
                done = _t(n["completed_at"])
                tl.append(_row(n["completed_at"], "Landlord", SOURCE[t], f"{ref} closed by {n['engineer']}: {n['result']}. Evidence: {n['evidence']}"))
                for b in ll_badges:
                    if b["person_id"] == n["engineer"] and done - timedelta(hours=6) <= _t(b["timestamp"]) <= done:
                        tl.append(_row(b["timestamp"], "Landlord", "access/landlord_badge_events.csv",
                                       f"{b['person_id']} badged {b['direction']} at {b['reader']}", b))
        for a in r["alarms"]:
            tl.append(_row(a["raised"], "Customer", "Customer alarm board",
                           f"Alarm {a['id']} on the board: {a['device']}, {a['summary']} ({a['severity']}; {A.CLASS_TEXT[a['cls']].lower()})"))
            if a["cleared"]:
                tl.append(_row(a["cleared"], "Customer", "Customer alarm board", f"Alarm {a['id']} cleared"))
        m = r["measured"]
        if m and m["kind"] == "IT":
            tl.append(_row(m["t0"], "Customer", "reports/scorecard.json", f"Measured T0 (first telemetry evidence of the fault), ticket of record {m['ticket_of_record']}"))
            tl.append(_row(m["rts"], "Customer", "reports/scorecard.json", f"Measured validated return to service: {m['measured']} after T0"))
            r["markers"] = [[m["t0"], "Measured T0"], [m["rts"], "Measured RTS"]]
        elif m and m["kind"] == "Security":
            r["markers"] = [[m["t0"], "Alarm"]] + ([[m["arrived"], "Guard at the door"]] if m["arrived"] else [])
        elif m and m["kind"] == "Fire":
            r["markers"] = ([[m["window_end"], "Window ends"]] if m["window_end"] else []) + [[m["logged"], "Log: restored"]] + \
                ([[m["panel_end"], "Panel: restored"]] if m["panel_end"] and not m["agrees"] else [])
        elif m and m["kind"] == "Landlord":
            tl.append(_row(m["t0"], "Customer", "reports/landlord_scorecard.json", f"Measured start of the facility event: {m['event']}"))
            if m["restored"]:
                tl.append(_row(m["restored"], "Customer", "reports/landlord_scorecard.json", f"Measured restoration ({m['measured']}); owner by telemetry: {m['owner']} ({m['rule']})"))
            r["markers"] = [[m["t0"], "Measured start"]] + ([[m["restored"], "Measured restore"]] if m["restored"] else [])
        else:
            r["markers"] = [[r["start"], "Window opens" if t in ("chg", "mop") else "Due" if t == "pm" else "Opened"]] + \
                ([[r["end"], "Window closes" if t in ("chg", "mop") else "Completed" if t == "pm" else "Closed"]] if r["end"] else [])
        seen = set()
        r["timeline"] = [x for x in sorted(tl, key=lambda x: (x["t"], x["party"], x["event"]))
                         if not ((x["t"], x["event"]) in seen or seen.add((x["t"], x["event"])))]
    out = []
    for r in records.values():
        r["related"] = sorted(r["related"] - {r["id"]})
        out.append(r)
    out.sort(key=lambda r: (r["start"], r["id"]), reverse=True)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    counts = {t: sum(1 for r in out if r["type"] == t) for t in TYPES}
    return {"records": out, "types": {k: {"label": v[0], "plural": v[1], "partner": v[2], "system": v[3]} for k, v in TYPES.items()},
            "counts": counts, "window": manifest["window"],
            "feeds": [{"partner": "IT Partner", "system": "Ticketing system (ServiceNow-style)", "access": "Read-only API account",
                       "types": ["inc"], "records": counts["inc"]},
                      {"partner": "Landlord", "system": "Maintenance management system (Maximo-style)", "access": "Read-only API account",
                       "types": ["wo", "pm"], "records": counts["wo"] + counts["pm"]},
                      {"partner": "Landlord", "system": "Fire protection impairment log", "access": "Read-only API account",
                       "types": ["imp"], "records": counts["imp"]},
                      {"partner": "Security Partner", "system": "Dispatch log", "access": "Read-only API account",
                       "types": ["sir"], "records": counts["sir"]},
                      {"partner": "Customer", "system": "Change management (CAB)", "access": "Customer system",
                       "types": ["chg", "mop"], "records": counts["chg"] + counts["mop"]}]}


def _security(sec: Path) -> dict[str, Any]:
    """The Customer's access control records for the door alarms, and the doors and on-site targets they are held to."""
    import yaml

    from scorecard.sla_model import PARTNER_FILES, load_sla
    alarms = {a["alarm_id"]: a for a in (json.loads(x) for x in (sec / "door_alarms.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())}
    badges = list(csv.DictReader((sec / "guard_badges.csv").open(encoding="utf-8")))
    cfg = yaml.safe_load((ROOT / "config" / "security.yaml").read_text(encoding="utf-8"))
    prio = {p["id"]: p["engaged_on_site_min"] for p in load_sla(PARTNER_FILES["security"])["priorities"]}
    return {"alarms": alarms, "badges": badges, "doors": {d["id"]: d for d in cfg["doors"]}, "on_site": prio}


def _credential_findings(data_dir: Path) -> list[dict[str, Any]]:
    """The certification register's findings that name a record (scorecard.certifications), for the sample month only."""
    from scorecard import certifications as C
    if Path(data_dir).resolve() != C.SAMPLE.resolve() or not (C.LAYER / "manifest.json").exists():
        return []
    r = C.analyse(C.load_site(data_dir, C.SEC), C.load(C.LAYER, C.EHS_LAYER))
    return [{"id": f["id"], "partner": f["owner"], "severity": "Credential", "title": f["title"], "summary": f["text"],
             "refs": f["records"], "sla_refs": ["KM-15"] if f["partner"] == "it" else [], "source": "Certification register"}
            for f in r["findings"] if f["records"]]


def _fire(fire: Path, data_dir: Path) -> dict[str, Any]:
    """The fire panel's history, the notices, and the fire protection findings (the checks in scorecard.fire)."""
    from scorecard import fire as F
    t = F.load(fire, data_dir)
    r = F.analyse(t)
    by_imp = {x["row"]["imp_id"]: x for x in r["rc"]["imps"]}
    findings = [{"id": f["id"], "partner": "Landlord", "severity": f["severity"], "title": f["title"], "summary": f["summary"],
                 "refs": [f["imp"]] if f["imp"] else [], "sla_refs": f["sla_refs"]} for f in r["findings"]]
    return {"t": t, "by_imp": by_imp, "findings": findings}


def _imp_timeline(ref: str, n: dict, fire: dict | None) -> tuple[list[dict], dict | None]:
    """An impairment's log entries, its notices, and what the fire panel shows on its devices."""
    tl = [_row(n["start"], "Landlord", SOURCE["imp"], f"{ref} {n['type']} impairment begins: {n['reason']} ({n['devices'].replace(';', ', ')})", n)]
    if n["window_end"]:
        tl.append(_row(n["window_end"], "Landlord", SOURCE["imp"], f"{ref} window ends"))
    if n["fire_watch_start"]:
        tl.append(_row(n["fire_watch_start"], "Landlord", SOURCE["imp"], "Fire watch begins"))
        tl.append(_row(n["fire_watch_end"], "Landlord", SOURCE["imp"], "Fire watch ends"))
    if n["restored_at"]:
        tl.append(_row(n["restored_at"], "Landlord", SOURCE["imp"], f"{ref} logged restored by {n['engineer']}"))
    if not fire or ref not in fire["by_imp"]:
        return tl, None
    x, t = fire["by_imp"][ref], fire["t"]
    for m in x["notices"]:
        what = {"start": "Impairment notice", "extension": f"Extension notice (new end {m['new_end'][:16].replace('T', ' ')} UTC)",
                "restored": "Restoration notice"}[m["kind"]]
        tl.append(_row(m["received_at"], "Customer", "fire/impairment_notices.csv", f"{what} {m['notice_id']} received: {m['text']}", m))
    lo, hi = x["start"] - timedelta(hours=1), max(x["restored"], x["panel_end"] or x["restored"]) + timedelta(hours=1)
    for e in t.panel:
        if e["device"] in x["devices"] and lo <= _t(e["timestamp"]) <= hi:
            tl.append(_row(e["timestamp"], "Customer", "fire/facp_history.jsonl",
                           f"Fire panel {e['device']} {e['point']}: {e['signal'].lower()} {e['state'].lower()} ({e['text']})", e))
    pe = x["panel_end"]
    mins = (pe - x["start"]).total_seconds() / 60 if pe else None
    logged = (x["restored"] - x["start"]).total_seconds() / 60
    return tl, {"kind": "Fire", "t0": n["start"], "restored": _iso(pe) if pe else None, "panel_end": _iso(pe) if pe else None,
                "logged": n["restored_at"], "window_end": n["window_end"] or None, "measured_min": round(mins, 1) if mins is not None else None,
                "measured": _hm(mins) if mins is not None else "", "logged_text": _hm(logged),
                "agrees": pe is not None and abs((pe - x["restored"]).total_seconds()) <= 15 * 60,
                "fire_watch": f"{n['fire_watch_start'][11:16]} to {n['fire_watch_end'][11:16]} UTC" if n["fire_watch_start"] else ""}


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hall(where: str) -> str:
    m = re.search(r"Hall ([A-Z])\b|\b([A-Z])\d{2}\b|-([A-Z])\d", where or "")
    return f"HALL-{next(g for g in m.groups() if g)}" if m else ""
