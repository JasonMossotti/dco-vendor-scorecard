"""Security engine: hold the Security Partner to its SLA with the Customer's own security systems.

Mirrors the Landlord engine:

* ``SecurityContext`` reads the Customer's access control, video, and identity records and the Security Partner's
  post log, tours, dispatch log, visitor log, and chain-of-custody log (never the answer key), plus the IT Partner's
  and the Landlord's hall badge-ins (the escorts) and the RMA shipments (the trays that left the Site).
* One detector per finding type, with severity and corrective action taken from the Security Partner SLA.
* ``measure_security`` measures every SEC-CSL and SEC-KM; ``build_security_scorecard`` turns that into credits beside
  the Security Partner's own weekly report.

The access control system is the evidence: a post is staffed when a guard badges in at the post reader, a door alarm
is answered when a guard badges the alarmed door, and an escort is present when the escort badges into the hall. A
log entry is a claim. A finding means the records do not reconcile, not that someone lied.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from scorecard.engine.core import Finding, ev, fmt_t
from scorecard.engine.run import SEVERITY_ORDER
from scorecard.sla_model import cap_monthly_credits, classify_finding, compute_credit, evaluate_csl, finding_type
from scorecard.synthetic.security import parse

SHIFT = timedelta(hours=12)
EARLY = timedelta(minutes=30)       # a guard badging in up to 30 minutes before the shift counts for that shift
ESCORT_S = 120                      # the escort badges into the hall within 2 minutes of the visitor (SEC-CSL-03)
LATE_SCAN = timedelta(minutes=15)   # a tour scan more than 15 minutes late is missed (posts.tours)


def _csv(p: Path) -> list[dict]:
    return list(csv.DictReader(p.open(encoding="utf-8", newline="")))


def _json(p: Path) -> Any:
    if p.suffix == ".jsonl":
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return json.loads(p.read_text(encoding="utf-8"))


class SecurityContext:
    def __init__(self, sla: dict[str, Any], data_dir: str | Path, sec_dir: str | Path):
        d, s = Path(data_dir), Path(sec_dir)
        self.sla = sla
        w = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["window"]
        self.window_start, self.window_end = parse(w["start"]), parse(w["end"])
        self.prio = {p["id"]: p for p in sla["priorities"]}
        self.posts = {p["id"]: p for p in sla["posts"]["list"]}
        self.guards = {g["guard_id"] for g in _csv(s / "guards.csv")}
        self.post_log = [dict(r, shift_start=parse(r["shift_start"])) for r in _csv(s / "post_log.csv")]
        self.guard_badges = [dict(r, timestamp=parse(r["timestamp"])) for r in _csv(s / "guard_badges.csv")]
        self.tours = [dict(r, due=parse(r["due"]), scanned_at=parse(r["scanned_at"]) if r["scanned_at"] else None)
                      for r in _csv(s / "tour_scans.csv")]
        self.alarms = [dict(a, timestamp=parse(a["timestamp"]), console_ack_at=parse(a["console_ack_at"]) if a["console_ack_at"] else None)
                       for a in _json(s / "door_alarms.jsonl")]
        self.dispatch = {x["alarm_id"]: x for x in _json(s / "dispatch_log.json")}
        self.visits = {v["visit_id"]: v for v in _csv(s / "visits.csv")}
        visit_of = {v["visitor_badge"]: v["visit_id"] for v in self.visits.values()}
        self.visitor_entries = [dict(b, timestamp=parse(b["timestamp"]), visit_id=visit_of.get(b["badge_id"]))
                                for b in _csv(s / "visitor_badges.csv") if b["direction"] == "in"]
        self.cameras = _json(s / "cameras.json")
        self.camera_events = [dict(e, timestamp=parse(e["timestamp"])) for e in _json(s / "camera_events.jsonl")]
        self.retention = [dict(r, oldest_recording_days=int(r["oldest_recording_days"])) for r in _csv(s / "retention_audit.csv")]
        self.leavers = [dict(r, separated_at=parse(r["separated_at"]), deactivated_at=parse(r["deactivated_at"]) if r["deactivated_at"] else None)
                        for r in _csv(s / "leavers.csv")]
        self.reviews = [dict(r, due=parse(r["due"]), completed_at=parse(r["completed_at"]) if r["completed_at"] else None)
                        for r in _csv(s / "access_reviews.csv")]
        self.tray_drives = _csv(s / "tray_drives.csv")
        self.custody = {r["drive_serial"]: r for r in _csv(s / "chain_of_custody.csv")}
        self.certs = {r["drive_serial"]: dict(r, destroyed_at=parse(r["destroyed_at"])) for r in _csv(s / "destruction_certificates.csv")}
        self.weekly = _json(s / "self_reported_weekly.json")
        self.shipments = {r["ticket"]: dict(r, shipped_at=parse(r["shipped_at"]))
                          for r in _csv(d / "vendor" / "rma_shipments.csv") if r["fru"] == "Compute tray"}
        # Hall badge-ins of people who can escort: IT Partner (HALL-A, HALL-B) and Landlord (Hall A, Hall B).
        self.hall_ins = [{"t": parse(b["timestamp"]), "person": b["person_id"], "hall": b["door"]}
                         for b in _csv(d / "access" / "badge_events.csv") if b["door"].startswith("HALL-") and b["direction"] == "in"]
        self.hall_ins += [{"t": parse(b["timestamp"]), "person": b["person_id"], "hall": "HALL-" + b["reader"][-1]}
                          for b in _csv(d / "access" / "landlord_badge_events.csv")
                          if b["reader"] in ("Hall A", "Hall B") and b["direction"] == "in"]

    def post_badge_in(self, row: dict) -> datetime | None:
        """First badge-in by a rostered guard at the post's reader for the shift. A badge-in in the last 30 minutes of a
        shift belongs to the next one (the relief arriving early)."""
        reader, t0 = self.posts[row["post"]]["reader"], row["shift_start"]
        ins = [b["timestamp"] for b in self.guard_badges if b["reader"] == reader and b["direction"] == "in"
               and b["guard_id"] in self.guards and t0 - EARLY <= b["timestamp"] < t0 + SHIFT - EARLY]
        return min(ins) if ins else None

    def guard_at_door(self, alarm: dict, until: datetime) -> dict | None:
        rows = [b for b in self.guard_badges if b["reader"] == alarm["door"] and b["guard_id"] in self.guards
                and alarm["timestamp"] <= b["timestamp"] <= until]
        return min(rows, key=lambda b: b["timestamp"]) if rows else None

    def escort_in(self, entry: dict) -> dict | None:
        v = self.visits.get(entry["visit_id"] or "")
        if not v:
            return None
        rows = [h for h in self.hall_ins if h["person"] == v["escort"] and h["hall"] == entry["reader"]
                and abs((h["t"] - entry["timestamp"]).total_seconds()) <= ESCORT_S]
        return min(rows, key=lambda h: abs((h["t"] - entry["timestamp"]).total_seconds())) if rows else None

    def shipped_drives(self) -> list[dict]:
        return [dict(d, shipped_at=self.shipments[d["ticket"]]["shipped_at"]) for d in self.tray_drives if d["ticket"] in self.shipments]


@dataclass
class SecurityResult:
    context: SecurityContext
    findings: list[Finding]


DETECTORS: list[Callable[[SecurityContext], list[Finding]]] = []


def detector(fn):
    DETECTORS.append(fn)
    return fn


def new_finding(ctx: SecurityContext, type_id: str, summary: str, refs: list[str], unit: str | None,
                at: datetime | None, evidence: list[dict], **kw) -> Finding:
    ft = finding_type(ctx.sla, type_id)
    return Finding(type=type_id, title=ft["name"], summary=summary, tickets=refs, unit=unit, observed_at=at,
                   evidence=evidence, sla_refs=list(ft["sla_refs"]), recommended_action=ft["action"], **kw)


def post_key(row: dict) -> str:
    return f"{row['post']} {fmt_t(row['shift_start'])}"


@detector
def detect_post_reported_unstaffed(ctx):
    out = []
    for r in ctx.post_log:
        if r["reported"] != "Staffed" or ctx.post_badge_in(r):
            continue
        p = ctx.posts[r["post"]]
        out.append(new_finding(
            ctx, "post_reported_unstaffed",
            f"The post log reports {p['name']} staffed by {r['guard_id']} for the {r['shift']} shift starting {fmt_t(r['shift_start'])}, "
            f"but no guard badged in at the post reader during the shift.",
            [post_key(r)], p["name"], r["shift_start"],
            [ev("security/post_log.csv", r["shift_start"], f"{r['post']} {r['shift']} shift: {r['reported']} ({r['guard_id']})"),
             ev("security/guard_badges.csv", None, f"No badge-in at '{p['reader']}' from {fmt_t(r['shift_start'] - EARLY)} "
                                                  f"to {fmt_t(r['shift_start'] + SHIFT - EARLY)}")],
            keys={"post": r["post"], "shift_start": r["shift_start"]}, metrics={"minutes": 720}))
    return out


@detector
def detect_door_alarm_closed_no_response(ctx):
    out = []
    for a in ctx.alarms:
        d = ctx.dispatch.get(a["alarm_id"])
        if not d or not d["closed"]:
            continue
        closed = parse(d["closed"])
        if ctx.guard_at_door(a, closed):
            continue
        out.append(new_finding(
            ctx, "door_alarm_closed_no_response",
            f"{a['event']} at {a['door']} ({a['priority']}) at {fmt_t(a['timestamp'])}. The dispatch log closed {d['sir']} at "
            f"{fmt_t(closed)} as '{d['disposition']}', but no guard badged the door's reader between the alarm and the close.",
            [d["sir"], a["alarm_id"]], a["door"], a["timestamp"],
            [ev("security/door_alarms.jsonl", a["timestamp"], f"{a['alarm_id']} {a['event']} at {a['door']}; console acknowledged "
                                                             f"{fmt_t(a['console_ack_at'])}"),
             ev("security/dispatch_log.json", closed, f"{d['sir']} closed: {d['disposition']} (dispatched {d['dispatched']})"),
             ev("security/guard_badges.csv", None, f"No guard badge at {a['door']} from {fmt_t(a['timestamp'])} to {fmt_t(closed)}")],
            keys={"alarm_id": a["alarm_id"]}))
    return out


@detector
def detect_visitor_without_escort(ctx):
    out = []
    for e in ctx.visitor_entries:
        v = ctx.visits.get(e["visit_id"] or "")
        if not v or ctx.escort_in(e):
            continue
        near = [h for h in ctx.hall_ins if h["person"] == v["escort"] and h["hall"] == e["reader"]]
        nearest = min(near, key=lambda h: abs((h["t"] - e["timestamp"]).total_seconds()), default=None)
        gap = f"; the escort's nearest badge-in to {e['reader']} was {fmt_t(nearest['t'])}" if nearest else "; the escort did not badge into that hall"
        out.append(new_finding(
            ctx, "visitor_without_escort",
            f"Visitor {v['visitor_badge']} ({v['company']}, {v['visit_id']}) badged into {e['reader']} at {fmt_t(e['timestamp'])} "
            f"with {v['escort']} ({v['escort_party']}) named as escort, but the escort did not badge in within 2 minutes{gap}.",
            [v["visit_id"]], e["reader"], e["timestamp"],
            [ev("security/visits.csv", parse(v["signed_in"]), f"{v['visit_id']} signed in under {v['request']}; escort {v['escort']}"),
             ev("security/visitor_badges.csv", e["timestamp"], f"{v['visitor_badge']} in at {e['reader']}"),
             ev("access/badge_events.csv" if v["escort_party"] == "IT Partner" else "access/landlord_badge_events.csv",
                nearest["t"] if nearest else None, f"{v['escort']} nearest hall badge-in" if nearest else f"{v['escort']}: no hall badge-in")],
            keys={"visit_id": v["visit_id"]}))
    return out


@detector
def detect_media_shipped_without_destruction(ctx):
    out = []
    for d in ctx.shipped_drives():
        c = ctx.certs.get(d["drive_serial"])
        if c and c["destroyed_at"] <= d["shipped_at"]:
            continue
        cust = ctx.custody.get(d["drive_serial"])
        why = (f"its certificate {c['certificate']} is dated {fmt_t(c['destroyed_at'])}, after the shipment" if c
               else "there is no destruction certificate" + ("" if cust else " and no chain-of-custody handover"))
        out.append(new_finding(
            ctx, "media_shipped_without_destruction",
            f"Compute tray {d['tray_serial']} ({d['ticket']}) shipped at {fmt_t(d['shipped_at'])}. Its Redfish inventory lists drive "
            f"{d['drive_serial']} in bay {d['bay']}, but {why}.",
            [d["ticket"], d["drive_serial"]], f"Tray {d['tray_serial']}", d["shipped_at"],
            [ev("security/tray_drives.csv", None, f"{d['tray_serial']} bay {d['bay']}: {d['drive_serial']} ({d['model']})"),
             ev("vendor/rma_shipments.csv", d["shipped_at"], f"{d['ticket']} compute tray {d['tray_serial']} shipped"),
             ev("security/chain_of_custody.csv", parse(cust["handed_over_at"]) if cust else None,
                f"Handed to the Security Partner" if cust else f"No handover recorded for {d['drive_serial']}"),
             ev("security/destruction_certificates.csv", c["destroyed_at"] if c else None,
                f"{c['certificate']}" if c else f"No certificate for {d['drive_serial']}")],
            keys={"drive_serial": d["drive_serial"], "ticket": d["ticket"]}))
    return out


def run_security(sla: dict[str, Any], data_dir: str | Path, sec_dir: str | Path) -> SecurityResult:
    ctx = SecurityContext(sla, data_dir, sec_dir)
    findings: list[Finding] = []
    for d in DETECTORS:
        findings.extend(d(ctx))
    for f in findings:
        r = classify_finding(sla, f.type, None, None, 0)
        f.severity, f.severity_name, f.escalation, f.severity_reasons = r.level, r.name, r.escalation, r.reasons
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.observed_at or ctx.window_start, f.type))
    for n, f in enumerate(findings, 1):
        f.id = f"S-{n:03d}"
    return SecurityResult(ctx, findings)


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #
def _outage_minutes(events: list[dict], start: datetime, end: datetime) -> float:
    total, open_at = 0.0, {}
    for e in sorted(events, key=lambda e: e["timestamp"]):
        if e["event"] == "Recording stopped":
            open_at[e["camera"]] = e["timestamp"]
        elif e["camera"] in open_at:
            a = max(open_at.pop(e["camera"]), start)
            b = min(e["timestamp"], end)
            total += max((b - a).total_seconds() / 60, 0)
    for a in open_at.values():
        total += max((end - max(a, start)).total_seconds() / 60, 0)
    return total


def measure_security(result: SecurityResult, start: datetime | None = None, end: datetime | None = None,
                     findings: list[Finding] | None = None) -> dict[str, dict[str, Any]]:
    """Measure every SEC-CSL and SEC-KM for the window, or for [start, end) when a period is given (the weekly review).
    Events count in the period they began."""
    ctx = result.context
    start, end = start or ctx.window_start, end or ctx.window_end
    found = result.findings if findings is None else findings
    inside = lambda t: start <= t < end
    m: dict[str, dict[str, Any]] = {}

    def put(mid, value, detail, events=None, misses=None):
        m[mid] = {"actual": value, "detail": detail, "events": events, "misses": misses}

    posts = [r for r in ctx.post_log if inside(r["shift_start"])]
    committed = 720 * len(posts)
    covered = 0.0
    for r in posts:
        b = ctx.post_badge_in(r)
        if b:
            covered += (r["shift_start"] + SHIFT - max(b, r["shift_start"])).total_seconds() / 60
    put("SEC-CSL-01", 100 * covered / committed if committed else None,
        f"{len(posts)} post-shifts; {committed - covered:,.0f} of {committed:,} post-minutes with no guard badged in at the post")

    alarms = [a for a in ctx.alarms if inside(a["timestamp"])]
    ok = [a for a in alarms if ctx.guard_at_door(a, a["timestamp"] + timedelta(minutes=ctx.prio[a["priority"]]["engaged_on_site_min"]))]
    put("SEC-CSL-02", 100 * len(ok) / len(alarms) if alarms else None,
        f"{len(ok)} of {len(alarms)} door alarms with a guard badged at the door in time (3 min P1, 5 min P2)", len(alarms), len(alarms) - len(ok))

    entries = [e for e in ctx.visitor_entries if inside(e["timestamp"])]
    esc = [e for e in entries if ctx.escort_in(e)]
    put("SEC-CSL-03", 100 * len(esc) / len(entries) if entries else None,
        f"{len(esc)} of {len(entries)} visitor hall entries with the escort badged in within 2 minutes", len(entries), len(entries) - len(esc))

    cam_min = len(ctx.cameras) * (end - start).total_seconds() / 60
    down = _outage_minutes(ctx.camera_events, start, end)
    put("SEC-CSL-04", 100 * (cam_min - down) / cam_min if cam_min else None,
        f"{len(ctx.cameras)} cameras; {down:,.0f} camera-minutes not recording")

    leavers = [x for x in ctx.leavers if inside(x["separated_at"])]
    in_time = [x for x in leavers if x["deactivated_at"] and x["deactivated_at"] - x["separated_at"] <= timedelta(hours=24)]
    put("SEC-CSL-05", 100 * len(in_time) / len(leavers) if leavers else None,
        f"{len(in_time)} of {len(leavers)} leavers' badges deactivated within 24 hours", len(leavers), len(leavers) - len(in_time))

    drives = [d for d in ctx.shipped_drives() if inside(d["shipped_at"])]
    cert = [d for d in drives if d["drive_serial"] in ctx.certs and ctx.certs[d["drive_serial"]]["destroyed_at"] <= d["shipped_at"]]
    trays = len({d["ticket"] for d in drives})
    put("SEC-CSL-06", 100 * len(cert) / len(drives) if drives else None,
        f"{len(cert)} of {len(drives)} drive serials in {trays} shipped compute trays certified destroyed before shipment", len(drives), len(drives) - len(cert))

    records = ([post_key(r) for r in posts] + [ctx.dispatch[a["alarm_id"]]["sir"] for a in alarms if a["alarm_id"] in ctx.dispatch]
               + sorted({e["visit_id"] for e in entries if e["visit_id"]}) + [d["drive_serial"] for d in drives])
    tainted = {k for f in found for k in f.tickets} & set(records)
    put("SEC-CSL-07", 100 * (len(records) - len(tainted)) / len(records) if records else None,
        f"{len(records) - len(tainted)} of {len(records)} post log, dispatch, visitor, and media records reconcile")

    audits = [r for r in ctx.retention if inside(parse(r["audited_at"]))]
    keep = [r for r in audits if r["oldest_recording_days"] >= ctx.sla["video"]["retention_days"]]
    put("SEC-KM-01", 100 * len(keep) / len(audits) if audits else None,
        f"{len(keep)} of {len(audits)} daily recorder audits held at least {ctx.sla['video']['retention_days']} days")
    acked = [a for a in alarms if a["console_ack_at"]
             and (a["console_ack_at"] - a["timestamp"]).total_seconds() <= 60 * ctx.prio[a["priority"]]["acknowledge_min"]]
    put("SEC-KM-02", 100 * len(acked) / len(alarms) if alarms else None, f"{len(acked)} of {len(alarms)} door alarms acknowledged at the console in time")
    scans = [t for t in ctx.tours if inside(t["due"])]
    on_time = [t for t in scans if t["scanned_at"] and t["scanned_at"] <= t["due"] + LATE_SCAN]
    put("SEC-KM-03", 100 * len(on_time) / len(scans) if scans else None, f"{len(on_time)} of {len(scans)} tour checkpoints scanned on time")
    due = [r for r in ctx.reviews if inside(r["due"])]
    done = [r for r in due if r["completed_at"] and r["completed_at"] <= r["due"]]
    put("SEC-KM-04", 100 * len(done) / len(due) if due else None,
        f"{len(done)} of {len(due)} quarterly access reviews completed by the due date" if due else "No quarterly access review due in the window")
    return m


def build_security_scorecard(sla: dict[str, Any], result: SecurityResult) -> dict[str, Any]:
    measured = measure_security(result)
    rows, credits = [], []
    reported = result.context.weekly[-1]["results"] if result.context.weekly else {}
    for c in sla["critical_service_levels"]:
        x = measured[c["id"]]
        res = evaluate_csl(sla, c["id"], x["actual"], x["events"], x["misses"]) if x["actual"] is not None else None
        status = res.status if res else "not_applicable"
        credit = 0.0
        if res and res.status in ("below_minimum", "deep_below_minimum"):
            cr = compute_credit(sla, c["id"], 1, aggravators=["AGG-INTEGRITY"] if c["id"] == "SEC-CSL-07" else [])
            credits.append(cr)
            credit = cr.credit
        rows.append({"id": c["id"], "name": c["name"], "expected": c["expected"], "minimum": c["minimum"],
                     "direction": c["direction"], "actual": x["actual"], "vendor_reported": reported.get(c["id"]),
                     "status": status, "credit": credit, "detail": x["detail"],
                     "note": res.note if res else ""})
    uncapped, payable, _ = cap_monthly_credits(sla, credits) if credits else (0.0, 0.0, [])
    kms = [{"id": k["id"], "name": k["name"], "target": k["target"], "unit": k["unit"], "direction": k["direction"],
            "actual": measured[k["id"]]["actual"], "detail": measured[k["id"]]["detail"],
            "met": None if measured[k["id"]]["actual"] is None else measured[k["id"]]["actual"] >= k["target"]}
           for k in sla["key_measurements"]]
    return {"supplier": sla["parties"]["supplier"]["name"], "window": {"start": result.context.window_start, "end": result.context.window_end},
            "csl": rows, "km": kms, "credits": {"uncapped": uncapped, "payable": payable, "capped": payable < uncapped,
                                                  "items": [{"csl": c.csl_id, "credit": c.credit, "explanation": c.explanation} for c in credits]},
            "defaults": [r["id"] for r in rows if r["status"] in ("below_minimum", "deep_below_minimum")],
            "findings": len(result.findings), "s1": sum(1 for f in result.findings if f.severity == "S1")}
