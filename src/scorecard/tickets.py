"""The Incident Portal: every partner ticket, change, work order, MOP, and PM task, read the way the
Customer's read-only records access would deliver them (common terms, measurement: Records access).

Portfolio demo; all data fictional. Five record types from three systems:

* ``INC``  IT Partner incidents, from the IT Partner's ticketing system (a ServiceNow-style record).
* ``CHG``  IT Partner changes approved by the Customer CAB, from the Customer's change management system.
* ``WO``   Landlord work orders, from the Landlord's maintenance management system (a Maximo-style record).
* ``MOP``  Landlord methods of procedure approved by the Customer change board.
* ``PM``   Landlord preventive maintenance tasks, from the same maintenance management system.

Each record carries the partner's own fields exactly as stored ("as recorded"), a timeline built the way
the post-incident review builds one (``scorecard.pir.build_review``), the alarms the alarm board ties to it,
the Customer's own measurement (``reports/scorecard.json`` and ``reports/landlord_scorecard.json``), and the
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
REPORTS = ROOT / "reports"
UTC = timezone.utc
LOCAL = timezone(timedelta(hours=-5), "CDT")

# The record numbers the portal opens; every page links them to tickets/#<number>.
ID_PATTERN = r"INC\d{7}|CHG\d{7}|WO-\d{5}|MOP-\d{3}|PM-\d{4}"
ID_RE = re.compile(rf"\b(?:{ID_PATTERN})\b")

TYPES = {   # key: (label, plural, partner, system of record)
    "inc": ("Incident", "Incidents", "IT Partner", "IT Partner ticketing system (ServiceNow-style incident record)"),
    "chg": ("Change", "Changes", "IT Partner", "Customer change management system (CAB record)"),
    "wo": ("Work order", "Work orders", "Landlord", "Landlord maintenance management system (Maximo-style work order)"),
    "mop": ("Method of procedure", "Methods of procedure (Landlord changes)", "Landlord", "Customer change management system (Landlord MOP approval)"),
    "pm": ("Maintenance task", "Preventive maintenance tasks", "Landlord", "Landlord maintenance management system (preventive maintenance record)"),
}
SOURCE = {"inc": "vendor/tickets.json", "chg": "customer/cab_changes.json", "wo": "landlord/work_orders.json",
          "mop": "customer/landlord_mop_approvals.json", "pm": "landlord/pm_records.csv"}


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


def _read(data_dir: Path) -> dict[str, Any]:
    js = lambda f: json.loads((data_dir / f).read_text(encoding="utf-8"))
    return {"inc": js(SOURCE["inc"]), "chg": js(SOURCE["chg"]), "wo": js(SOURCE["wo"]), "mop": js(SOURCE["mop"]),
            "pm": list(csv.DictReader((data_dir / SOURCE["pm"]).open(encoding="utf-8")))}


def ids(data_dir: Path = SAMPLE) -> list[str]:
    """Every record number the portal holds (the pages link only these)."""
    return sorted(_ids(str(data_dir)))


@lru_cache(maxsize=4)
def _ids(data_dir: str) -> frozenset[str]:
    r = _read(Path(data_dir))
    return frozenset([x["number"] for x in r["inc"]] + [x["change_id"] for x in r["chg"]] + [x["wo"] for x in r["wo"]]
                     + [x["mop_id"] for x in r["mop"]] + [x["task_id"] for x in r["pm"]])


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
                      {"partner": "Customer", "system": "Change management (CAB)", "access": "Customer system",
                       "types": ["chg", "mop"], "records": counts["chg"] + counts["mop"]}]}


def _hall(where: str) -> str:
    m = re.search(r"Hall ([A-Z])\b|\b([A-Z])\d{2}\b|-([A-Z])\d", where or "")
    return f"HALL-{next(g for g in m.groups() if g)}" if m else ""
