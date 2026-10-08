"""Facts for the Weekly Operations Review: one pack per week for the joint review with both partners.

Everything here is computed from the dataset by the same engines as the monthly scorecards. The pack for a
week is prepared at that week's end and uses only what was knowable then:

* service levels are measured for the week and for the month to date (the contract settles credits
  monthly, so weekly results are early warnings, never credits);
* a finding is reported in the week its detector observed the discrepancy;
* the look-ahead lists only work that was approved or scheduled by the end of the week.

Judgment (decisions, asks, commentary) is written by people in ``weekly/notes/<week>.yaml``.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from scorecard.builder import _csl_rows, _vendor_value
from scorecard.connectors import FileConnector
from scorecard.engine import run_engine
from scorecard.engine.landlord import measure_landlord, run_landlord
from scorecard.kpi import build_incidents, measure_period
from scorecard.sla_model import PARTNER_FILES, evaluate_csl, load_sla

ROOT = Path(__file__).resolve().parents[2]
LOOKAHEAD = timedelta(days=7)
DEFAULT = ("below_minimum", "deep_below_minimum")
STATUS_TEXT = {"met_expected": "Met", "below_expected": "Below Expected", "below_minimum": "Below Minimum",
               "deep_below_minimum": "Below Minimum (severe)", "no_events": "No events"}


def _t(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hm(minutes: float) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def knowable_at(f) -> datetime | None:
    """When a finding is raised: the time its detector observed the discrepancy.

    Some detectors attach corroborating evidence that arrives later (an RMA shipment, later GPU telemetry). That
    evidence strengthens a finding but is not needed to raise it, so it never delays the week the finding is
    reported in. Only a finding with no observed time falls back to its latest dated evidence.
    """
    if f.observed_at:
        return f.observed_at
    times = [v if isinstance(v, datetime) else _t(str(v)) for e in f.evidence if (v := e.get("at"))]
    return max(times) if times else None


def week_id(start: datetime) -> str:
    y, w, _ = start.isocalendar()
    return f"{y}-W{w:02d}"


@dataclass
class WeeklyData:
    """Runs both engines once and keeps everything the weekly packs need."""

    data_dir: Path

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.it_sla, self.ll_sla = load_sla(), load_sla(PARTNER_FILES["landlord"])
        conn = FileConnector(self.data_dir)
        self.it = run_engine(self.it_sla, conn)
        self.it_incidents = build_incidents(self.it.context, self.it.findings)
        self.ll = run_landlord(self.ll_sla, conn)
        ctx = self.it.context
        self.window_start, self.window_end = ctx.window_start, ctx.window_end
        self.weeks = [(w["week_start"], w["week_end"]) for w in ctx.vendor_weekly]
        self.plan = self._csv("customer/deployment_plan.csv")
        self.milestones = self._csv("vendor/deployment_milestones.csv")
        self.it_target = {p["id"]: p["restore_min"] for p in self.it_sla["priorities"]}
        self.reviews = self._reviews()
        self.pattern_review = self._pattern_review()
        self.energy = self._energy()

    def _energy(self):
        """The energy meters (data/energy/, beside the sample), if they have been generated."""
        from scorecard import energy
        p = self.data_dir.parent / "energy"
        return energy.load(p) if (p / "meters_hourly.csv").exists() else None

    def _csv(self, rel: str) -> list[dict]:
        p = self.data_dir / rel
        return list(csv.DictReader(p.open(encoding="utf-8"))) if p.exists() else []

    def _reviews(self) -> list[dict]:
        """Completed post-incident reviews whose incident is in this dataset."""
        from scorecard.pir import Dataset, build_review
        out, ds = [], None
        refs = {t["number"] for t in self.it.context.tickets}
        for p in sorted((ROOT / "pir" / "reviews").glob("*.yaml")):
            r = yaml.safe_load(p.read_text(encoding="utf-8"))
            if r["ref"] not in refs:
                continue
            ds = ds or Dataset(self.data_dir)
            f = build_review(ds, r["ref"])
            out.append({"review": r, "facts": f, "refs": {f["ticket"], f["work_order"]} - {None}})
        return out


    def _pattern_review(self) -> dict | None:
        """The failure pattern review of the half-year that ends where this dataset begins, if there is one."""
        lp, mp = ROOT / "patterns" / "lessons.yaml", ROOT / "data" / "history" / "manifest.json"
        if not lp.exists() or not mp.exists():
            return None
        if _t(json.loads(mp.read_text(encoding="utf-8"))["window"]["end"]) != self.window_start:
            return None
        return yaml.safe_load(lp.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- service levels
def _status(rows: list[dict]) -> tuple[str, list[str]]:
    """One line per partner: below Minimum month to date, at risk, or on track."""
    mtd_bad = [r for r in rows if r["mtd_status"] in DEFAULT]
    if mtd_bad:
        return "Below Minimum (month to date)", [f"{r['id']} {r['name']}" for r in mtd_bad]
    risk = [r for r in rows if r["week_status"] in DEFAULT or r["mtd_status"] == "below_expected"]
    if risk:
        return "At risk", [f"{r['id']} {r['name']}" for r in risk]
    return "On track", []


def _it_levels(d: WeeklyData, ws: datetime, we: datetime, known: list) -> list[dict]:
    ctx = d.it.context
    weeks_to_date = [w for w in ctx.vendor_weekly if w["week_end"] <= we]
    this_week = [w for w in ctx.vendor_weekly if w["week_start"] == ws]
    week = _csl_rows(d.it_sla, measure_period(ctx, d.it_incidents, known, ws, we, d.it_sla), this_week)
    mtd = _csl_rows(d.it_sla, measure_period(ctx, d.it_incidents, known, d.window_start, we, d.it_sla), weeks_to_date)
    return [{"id": a["id"], "name": a["name"], "unit": a["unit"], "direction": a["direction"],
             "expected": a["expected"], "minimum": a["minimum"],
             "week": a["actual"], "week_status": a["status"], "week_detail": a["detail"],
             "reported": a["vendor_reported"], "mtd": b["actual"], "mtd_status": b["status"]}
            for a, b in zip(week, mtd)]


def _ll_levels(d: WeeklyData, ws: datetime, we: datetime, known: list) -> list[dict]:
    week = measure_landlord(d.ll, ws, we, known)
    mtd = measure_landlord(d.ll, d.window_start, we, known)
    reported = next((w["results"] for w in d.ll.context.weekly if w["week_start"] == ws), {})

    def status(cid, v):
        return "no_events" if v is None else evaluate_csl(d.ll_sla, cid, v).status
    rows = []
    for c in d.ll_sla["critical_service_levels"]:
        w, m = week[c["id"]]["actual"], mtd[c["id"]]["actual"]
        rows.append({"id": c["id"], "name": c["name"], "unit": c["unit"], "direction": c["direction"],
                     "expected": c["expected"], "minimum": c["minimum"],
                     "week": w, "week_status": status(c["id"], w), "week_detail": week[c["id"]]["detail"],
                     "reported": reported.get(c["id"]), "mtd": m, "mtd_status": status(c["id"], m)})
    return rows


def _gap(r: dict) -> float | None:
    """How far the partner's own report is more favorable than the measurement (positive = overstated)."""
    if r["reported"] is None or r["week"] is None:
        return None
    g = r["reported"] - r["week"]
    return round(g if r["direction"] == "higher_is_better" else -g, 3)


# --------------------------------------------------------------------------- incidents and findings
def _pir_for(d: WeeklyData, refs: set[str], we: datetime) -> dict | None:
    for rv in d.reviews:
        if rv["refs"] & refs:
            meeting = rv["review"].get("review_meeting")
            return {"id": rv["review"]["id"], "status": rv["review"]["status"] if meeting and meeting < _iso(we)[:10]
                    else f"Review meeting scheduled {meeting}"}
    return None


def _it_incidents(d: WeeklyData, ws: datetime, we: datetime) -> dict:
    rows = [i for i in d.it_incidents if ws <= i.t0 < we and i.priority in ("P1", "P2")]
    out = []
    for i in sorted(rows, key=lambda i: i.t0):
        open_ = i.rts >= we
        mins = i.measured_min
        target = d.it_target[i.priority]
        out.append({"priority": i.priority, "tickets": i.tickets, "fault_class": i.fault_class, "unit": i.unit,
                    "t0": _iso(i.t0), "rts": None if open_ else _iso(i.rts), "restore": None if open_ else _hm(mins),
                    "target": _hm(target), "met": None if open_ else mins <= target,
                    "facility_caused": i.fault_class == "FC-RACK",
                    "pir": _pir_for(d, set(i.tickets), we)})
    p1 = [r for r in out if r["priority"] == "P1"]
    p2 = [r for r in out if r["priority"] == "P2"]
    return {"p1": p1, "p2_count": len(p2), "p2_met": sum(1 for r in p2 if r["met"]),
            "p2_exceptions": [r for r in p2 if r["met"] is not True]}


def _ll_incidents(d: WeeklyData, ws: datetime, we: datetime) -> list[dict]:
    prio = d.ll.context.prio
    out = []
    for i in sorted((i for i in d.ll.incidents if ws <= i.t0 < we and i.priority in ("P1", "P2")), key=lambda i: i.t0):
        open_ = i.restored is None or i.restored >= we
        wo = (i.work_order or {}).get("wo")
        out.append({"priority": i.priority, "work_order": wo, "fault_class": i.fault_class, "unit": i.unit,
                    "description": i.description, "t0": _iso(i.t0), "restored": None if open_ else _iso(i.restored),
                    "restore": None if open_ else _hm(i.restore_min), "target": _hm(prio[i.priority]["restore_min"]),
                    "met": None if open_ else i.restore_min <= prio[i.priority]["restore_min"],
                    "owner": i.owner, "rule": i.rule, "rack_dark": i.capacity_lost,
                    "pir": _pir_for(d, {wo} if wo else set(), we)})
    return out


def _finding_row(f, partner: str) -> dict:
    return {"partner": partner, "id": f.id, "severity": f.severity, "title": f.title, "summary": f.summary,
            "refs": f.tickets, "sla_refs": f.sla_refs, "action": f.recommended_action, "known": _iso(knowable_at(f))}


# --------------------------------------------------------------------------- actions, look-ahead, resources, EHS
def _actions(d: WeeklyData, we: datetime) -> list[dict]:
    out = []
    for rv in d.reviews:
        r = rv["review"]
        if not r.get("review_meeting") or r["review_meeting"] >= _iso(we)[:10]:
            continue
        for a in r["actions"]:
            out.append({"source": r["id"], "id": a["id"], "action": a["action"], "owner": a["owner"],
                        "priority": a["priority"], "due": a["due"], "status": a["status"],
                        "status_as_of": r["status_as_of"],
                        "overdue": a["status"] != "Complete" and a["due"] < _iso(we)[:10]})
    return out


def _lookahead(d: WeeklyData, we: datetime) -> dict:
    nxt = we + LOOKAHEAD
    mops = [{"id": m["mop_id"], "title": m["title"], "window_start": _iso(m["window_start"]),
             "window_end": _iso(m["window_end"]), "approved_at": _iso(m["approved_at"]), "assets": m["assets"]}
            for m in sorted(d.ll.context.mops, key=lambda m: m["window_start"])
            if m["approved_at"] < we and we <= m["window_start"] < nxt]
    changes = [{"id": c["change_id"], "summary": c["summary"], "rack": c["rack"], "window_start": _iso(c["window_start"]),
                "window_end": _iso(c["window_end"])}
               for c in sorted(d.it.context.cab, key=lambda c: c["window_start"])
               if c["state"] == "Approved" and we <= c["window_start"] < nxt]
    pm = [{"id": p["task_id"], "asset": p["asset"], "task": p["task"], "due_start": _iso(p["due_start"]),
           "due_end": _iso(p["due_end"])}
          for p in sorted(d.ll.context.pm, key=lambda p: p["due_end"])
          if p["due_start"] < nxt and p["due_end"] > we and p["completed_at"] >= we]
    done = {}
    for m in d.milestones:
        if _t(m["reported_complete_at"]) < we:
            done[m["rack"]] = max(done.get(m["rack"], "M0"), m["milestone"])
    names = {m["milestone"]: m["name"] for m in d.milestones}
    deploy = [{"rack": p["rack"], "committed_handoff": p["committed_handoff"], "milestone": done.get(p["rack"], "M0"),
               "milestone_name": names.get(done.get(p["rack"], ""), "Not received")}
              for p in sorted(d.plan, key=lambda p: p["committed_handoff"])
              if we <= _t(p["committed_handoff"]) < nxt]
    late = [{"rack": p["rack"], "committed_handoff": p["committed_handoff"], "milestone": done.get(p["rack"], "M0"),
             "milestone_name": names.get(done.get(p["rack"], ""), "Not received")}
            for p in sorted(d.plan, key=lambda p: p["committed_handoff"])
            if _t(p["committed_handoff"]) < we and done.get(p["rack"]) != "M7"]
    receipts = [{"rack": p["rack"], "planned_receipt": p["planned_receipt"], "days_overdue": (we - _t(p["planned_receipt"])).days}
                for p in sorted(d.plan, key=lambda p: p["planned_receipt"])
                if _t(p["planned_receipt"]) < we and p["rack"] not in done]
    it_shifts = [r for r in d.it.context.roster if we <= r["shift_start"] < nxt]
    ll_shifts = [r for r in d.ll.context.roster if we <= r["shift_start"] < nxt]
    return {"from": _iso(we), "to": _iso(nxt), "beyond_data": nxt > d.window_end, "mops": mops, "changes": changes,
            "maintenance": pm, "handoffs_due": deploy, "handoffs_late": late, "receipts_overdue": receipts,
            "rostered_shifts": {"it": len(it_shifts), "landlord": len(ll_shifts)}}


def _resources(d: WeeklyData, ws: datetime, we: datetime, it_rows: list[dict], ll_rows: list[dict], known: list) -> dict:
    km = measure_period(d.it.context, d.it_incidents, known, ws, we, d.it_sla)
    kms = []
    for kid in ("KM-06", "KM-07", "KM-08"):
        k = next(x for x in d.it_sla["key_measurements"] if x["id"] == kid)
        v = km[kid]["actual"]
        kms.append({"id": kid, "name": k["name"], "target": k["target"], "actual": v, "detail": km[kid]["detail"],
                    "met": None if v is None else v >= k["target"]})
    open_rma = [r for r in d.it.context.rma if r["removed_at"] < we and (r["shipped_at"] is None or r["shipped_at"] >= we)]
    staffing = [next(r for r in it_rows if r["id"] == "CSL-10"), next(r for r in ll_rows if r["id"] == "OT-CSL-09")]
    return {"staffing": [{"id": r["id"], "name": r["name"], "week": r["week"], "minimum": r["minimum"],
                          "status": r["week_status"], "detail": r["week_detail"]} for r in staffing],
            "spares": kms,
            "rma_open": len(open_rma),
            "rma_oldest_days": max(((we - r["removed_at"]).days for r in open_rma), default=None)}


def _ehs(d: WeeklyData, ws: datetime, we: datetime, actions: list[dict]) -> dict:
    injuries, events, open_inv = 0, [], []
    for rv in d.reviews:
        f, r = rv["facts"], rv["review"]
        if ws <= _t(f["start"]) < we:
            injuries += r["ehs"]["injuries"]
            events.append({"pir": r["id"], "screening": r["ehs"]["screening"]})
        if r.get("review_meeting") and r["review_meeting"] < _iso(we)[:10]:
            for a in actions:
                if a["source"] == r["id"] and a["owner"] == "Customer EHS" and a["status"] != "Complete":
                    open_inv.append({"pir": r["id"], "action": a["id"], "due": a["due"], "overdue": a["overdue"],
                                     "referral": r["ehs"]["referral"]})
    return {"injuries": injuries, "events": events, "open_investigations": open_inv}


def _energy_line(d: WeeklyData, ws: datetime, we: datetime) -> dict | None:
    """PUE for the week and the month to date, from the same meters as the PUE report."""
    if d.energy is None:
        return None
    from scorecard import energy
    from scorecard.synthetic.energy import parse
    keep = ("pue", "ppue_cooling", "ppue_power", "facility_kwh", "it_kwh")

    def span(a: datetime, b: datetime) -> dict:
        t = energy.totals([r for r in d.energy.meters if a <= parse(r["hour"]) < b])
        return {k: round(t[k], 4) if k.startswith("p") else round(t[k], 1) for k in keep}
    return {"week": span(ws, we), "mtd": span(d.window_start, we)}


# --------------------------------------------------------------------------- the pack
def build_week(d: WeeklyData, ws: datetime) -> dict[str, Any]:
    we = next(e for s, e in d.weeks if s == ws)
    it_known = [f for f in d.it.findings if knowable_at(f) and knowable_at(f) < we]
    ll_known = [f for f in d.ll.findings if knowable_at(f) and knowable_at(f) < we]
    it_rows, ll_rows = _it_levels(d, ws, we, it_known), _ll_levels(d, ws, we, ll_known)
    for r in it_rows + ll_rows:
        r["gap"] = _gap(r)
    it_status, it_why = _status(it_rows)
    ll_status, ll_why = _status(ll_rows)
    new = ([_finding_row(f, "IT Partner") for f in it_known if knowable_at(f) >= ws]
           + [_finding_row(f, "Landlord") for f in ll_known if knowable_at(f) >= ws])
    sev = {"S1": 0, "S2": 1, "S3": 2, "S4": 3}
    new.sort(key=lambda r: (sev.get(r["severity"], 9), r["known"]))
    actions = _actions(d, we)
    pr = d.pattern_review
    pattern_actions = None
    if pr and pr["review_meeting"] < _iso(we)[:10]:
        acts = [a for p in pr["patterns"].values() for a in p["actions"]]
        pattern_actions = {"id": pr["id"], "meeting": pr["review_meeting"], "status_as_of": pr["status_as_of"],
                           "patterns": len(pr["patterns"]), "open": sum(a["status"] != "Complete" for a in acts),
                           "overdue": sum(a["status"] != "Complete" and a["due"] < _iso(we)[:10] for a in acts)}
    return {
        "id": week_id(ws), "start": _iso(ws), "end": _iso(we), "prepared": _iso(we),
        "number": [s for s, _ in d.weeks].index(ws) + 1, "of": len(d.weeks),
        "partners": [
            {"name": d.it_sla["parties"]["supplier"]["name"], "role": "IT Partner", "status": it_status,
             "reasons": it_why, "levels": it_rows},
            {"name": d.ll_sla["parties"]["supplier"]["name"], "role": "Landlord", "status": ll_status,
             "reasons": ll_why, "levels": ll_rows},
        ],
        "incidents": {"it": _it_incidents(d, ws, we), "landlord": _ll_incidents(d, ws, we)},
        "findings": {"new": new, "awaiting_monthly_review": len(it_known) + len(ll_known)},
        "actions": actions,
        "pattern_actions": pattern_actions,
        "lookahead": _lookahead(d, we),
        "resources": _resources(d, ws, we, it_rows, ll_rows, it_known),
        "ehs": _ehs(d, ws, we, actions),
        "energy": _energy_line(d, ws, we),
    }


def build_all(d: WeeklyData) -> list[dict[str, Any]]:
    return [build_week(d, s) for s, _ in d.weeks]
