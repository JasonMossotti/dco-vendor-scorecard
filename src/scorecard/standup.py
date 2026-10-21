"""Daily operations standup: one page per day of the month, the Operations tab's opening view (/ops/).

The contract's daily forum (sla/common.yaml, governance) takes open P1 and P2 incidents, today's deployment plan,
blockers, and spares alerts. Each day's page is computed from the records as they stood at the standup (07:30 site
time), with the same engines and layers as the weekly pack:

* overnight: records opened, redundancy reduced, and reported safety events since the night shift handover;
* open P1 and P2 incidents with their restore clocks, and whether each is at risk;
* redundancy reduced at the standup (Site health's groups);
* today's work windows from the change calendar, with the conflicts the calendar flags;
* deployment steps due today or overdue (the Deployments tab's work orders) and Hall C scripts scheduled;
* permits open or issued today (the Safety view's permits);
* spares below their contract minimum (the IT Partner's spares ledger and each hall's storage spares shelf);
* staffing: each shift's roster against the badge records, by the same rules as CSL-10, OT-CSL-09, and SEC posts;
* who is on call: the Customer's rota (config/customer_notifications.yaml), the partners' shift leads, and duty managers.

"Top three today" follows a stated rule (config/standup.yaml), never a person's pick. The day close (19:00) counts
what happened in the operations day, and seven days add up to the weekly pack: incidents opened, findings raised,
permits issued, and technician hours. Nothing here is a finding; the standup only shows what other views found.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from scorecard.change_calendar import hm_local, iso, local_day, parse
from scorecard.weekly import WeeklyData, knowable_at, week_id

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "standup.yaml"
NOTIFY = ROOT / "config" / "customer_notifications.yaml"
PARTNERS = {"it": "IT Partner", "landlord": "Landlord", "security": "Security Partner"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def config(path: Path = CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _hm(minutes: float) -> str:
    h, m = divmod(round(minutes), 60)
    return (f"{h} h {m:02d} min" if m else f"{h} h") if h else f"{m} min"


def _hall(h: str | None) -> str:
    return f"Hall {h[-1]}" if h else "Site"


# ---------------------------------------------------------------- the day's times
def times(start: datetime, cfg: dict[str, Any]) -> dict[str, datetime]:
    """The operations day that starts at a night shift handover: overnight ends at the day shift handover twelve hours
    later, the standup follows it, and the day closes at the next night shift handover. The handovers are the
    rosters' own shift starts, the boundary the weekly packs' weeks use."""
    ov = start + timedelta(hours=cfg["shift_hours"])
    return {"start": start, "overnight_end": ov, "standup": ov + timedelta(minutes=cfg["standup_after_handover_min"]),
            "end": start + timedelta(days=1)}


# ---------------------------------------------------------------- on call
def _on_shift(s: dict[str, Any], t: datetime) -> bool:
    """Whether a rota line (site days and times; one ending before it starts runs past midnight) covers t."""
    d = date.fromisoformat(local_day(t))
    hm = hm_local(t)
    a, b = s["start"], s["end"]
    wd = WEEKDAYS[d.weekday()]
    yd = WEEKDAYS[(d.weekday() - 1) % 7]
    if a < b:
        return wd in s["days"] and a <= hm < b
    return (wd in s["days"] and hm >= a) or (yd in s["days"] and hm < b)


def on_call(t: datetime, n: dict[str, Any]) -> dict[str, str] | None:
    s = next((s for s in n["schedule"] if _on_shift(s, t)), None)
    return {"label": s["label"], "primary": s["primary"], "secondary": s["secondary"]} if s else None


# ---------------------------------------------------------------- the standup
class Standup:
    """Every day's standup page from one run of the engines and layers."""

    def __init__(self, data_dir: Path = ROOT / "data" / "sample", cfg: dict[str, Any] | None = None,
                 weekly: WeeklyData | None = None, layers: bool = True) -> None:
        self.cfg = cfg or config()
        self.data_dir = Path(data_dir)
        self.d = weekly or WeeklyData(self.data_dir)
        self.notify = yaml.safe_load(NOTIFY.read_text(encoding="utf-8"))
        d = self.d
        self.start, self.end = d.window_start, d.window_end
        self.day_start = {local_day(times(t, self.cfg)["standup"]): t
                          for t in (self.start + timedelta(days=i) for i in range((self.end - self.start).days))}
        self.days = list(self.day_start)
        self.findings = ([("IT Partner", f) for f in d.it.findings] + [("Landlord", f) for f in d.ll.findings]
                         + ([("Security Partner", f) for f in d.sec.findings] if d.sec else []))
        self.sev = {"S1": 0, "S2": 1, "S3": 2, "S4": 3}
        self.cal = self.ehs = self.health = None
        self.wos: list[dict] = []
        self.racks: dict[str, dict] = {}
        self.hallc: list[dict] = []
        self.storage_ledger: list[dict] = []
        if layers:
            self._layers()

    def _layers(self) -> None:
        from scorecard import change_calendar as CC
        from scorecard import ehs as E
        from scorecard import site_health as SH
        self.cal = CC.analyse()
        self.cal_ids = {f["id"]: f for f in self.cal["findings"]}
        e = self.data_dir.parent / "ehs"
        self.ehs = E.load(e) if (e / "manifest.json").exists() else None
        self.ehs_jobs = {j["id"]: j for j in E.jobs(E.load_month(self.data_dir))} if self.ehs else {}
        _, self.health = SH.build()
        if self.d.deploy:
            self.wos = [w for w in self.d.deploy["record"]["work_orders"] if w["partner"] in ("IT Partner", "Landlord")]
            self.racks = {r["rack"]: r for r in self.d.deploy["racks"]["racks"]}
        self.hallc = [x for x in self.cal["items"] if x["kind"] == "hallc"]
        p = self.data_dir.parent / "telemetry" / "storage" / "spares_ledger.csv"
        if p.exists():
            self.storage_ledger = _csv(p)

    # ------------------------------------------------------------ incidents and their clocks
    def open_incidents(self, S: datetime) -> list[dict[str, Any]]:
        d, share = self.d, self.cfg["top3"]["at_risk_share"]
        out = []

        def row(partner, prio, refs, what, unit, t0, target, owner=None):
            used = (S - t0).total_seconds() / 60
            out.append({"partner": partner, "priority": prio, "refs": refs, "what": what, "unit": unit, "t0": iso(t0),
                        "target_min": target, "used_min": round(used), "due": iso(t0 + timedelta(minutes=target)),
                        "left_min": round(target - used), "at_risk": used >= share * target, "missed": used > target,
                        "owner": owner or partner})
        for i in d.it_incidents:
            if i.priority in ("P1", "P2") and i.t0 <= S < i.rts:
                row("IT Partner", i.priority, list(i.tickets), f"{i.fault_class}: {i.unit}", i.unit, i.t0, d.it_target[i.priority])
        prio = d.ll.context.prio
        for i in d.ll.incidents:
            if i.priority in ("P1", "P2") and i.t0 <= S and (i.restored is None or S < i.restored):
                wo = (i.work_order or {}).get("wo")
                row("Landlord", i.priority, [wo] if wo else [], i.description, i.unit, i.t0, prio[i.priority]["restore_min"], i.owner)
        return sorted(out, key=lambda r: (r["left_min"], r["t0"]))

    # ------------------------------------------------------------ overnight
    def records_opened(self, a: datetime, b: datetime) -> list[dict[str, Any]]:
        d = self.d
        out = []
        for t in d.it.context.tickets:
            if a <= t["opened_at"] < b:
                out.append({"at": iso(t["opened_at"]), "partner": "IT Partner", "ref": t["number"], "priority": t["priority"],
                            "what": t["short_description"], "where": t.get("rack") or ""})
        for w in d.ll.context.work_orders:
            if a <= w["opened"] < b:
                out.append({"at": iso(w["opened"]), "partner": "Landlord", "ref": w["wo"], "priority": w["priority"],
                            "what": w["notes"], "where": w["unit"]})
        if d.sec:
            for x in d.sec.context.dispatch.values():
                t = parse(x["opened"])
                if a <= t < b:
                    out.append({"at": x["opened"], "partner": "Security Partner", "ref": x["sir"], "priority": x["priority"],
                                "what": f"{x['type']}: {x['disposition']}", "where": x["door"]})
        return sorted(out, key=lambda r: (r["at"], r["ref"]))

    def _hours(self, a: datetime, b: datetime) -> range:
        h0 = int((a - self.start).total_seconds() // 3600)
        h1 = int(-(-(b - self.start).total_seconds() // 3600))
        return range(max(h0, 0), min(h1, self.health["hours"] if self.health else 0))

    def redundancy(self, a: datetime, b: datetime) -> list[dict[str, Any]]:
        """Each redundancy group reduced in any hour of [a, b), its worst state, and what the Site health page says."""
        if not self.health:
            return []
        hrs = self._hours(a, b)
        out = []
        for g in self.health["groups"]:
            bad = [h for h in hrs if g["state"][h] > 0]
            if not bad:
                continue
            worst = max(g["state"][h] for h in bad)
            pre = f"{g['name']}{' (' + _hall(g['hall']) + ')' if g['hall'] else ''}:"
            others = tuple(f"{x['name']}" for x in self.health["groups"] if x["key"] != g["key"] and x["name"] != g["name"])
            why = []
            for i in self.health["issues"]:
                if (i["family"] == g["family"] and i["hall"] == g["hall"] and i["state"] > 0 and any(i["from"] <= h <= i["to"] for h in bad)
                        and not i["text"].startswith(others) and i["text"] not in why):
                    why.append(i["text"])
            mine = [w for w in why if w.startswith(pre)]
            h = bad[-1]
            out.append({"group": g["key"], "name": g["name"], "hall": g["hall"], "scheme": g["scheme"], "state": worst,
                        "avail": g["avail"][h], "total": g["total"][h], "need": g["need"][h],
                        "from": iso(self.start + timedelta(hours=bad[0])), "to": iso(self.start + timedelta(hours=bad[-1] + 1)),
                        "text": "; ".join(mine or why) or f"{pre} {g['avail'][h]} of {g['total'][h]}, {'below N' if worst == 2 else 'no redundant unit'}",
                        "link": g["link"]})
        return sorted(out, key=lambda r: (-r["state"], r["from"], r["group"]))

    def safety_events(self, a: datetime, b: datetime) -> list[dict[str, Any]]:
        if not self.ehs:
            return []
        return [{"at": x["at"], "ref": x["event"], "kind": x["kind"], "partner": PARTNERS[x["partner"]], "what": x["what"],
                 "where": x["where"]} for x in self.ehs.events if a <= parse(x["at"]) < b]

    # ------------------------------------------------------------ today's work
    def work(self, S: datetime) -> list[dict[str, Any]]:
        if not self.cal:
            return []
        nxt = S + timedelta(days=1)
        out = []
        for j in self.cal["jobs"]:
            if j["period"] != "past" or not (parse(j["start"]) < nxt and S < parse(j["end"])):
                continue
            fs = [f for f in self.cal["findings"] if j["id"] in f["jobs"]]
            out.append({k: j[k] for k in ("id", "source", "owner", "title", "takes", "unit", "group", "rack", "hall", "start", "end",
                                           "status")}
                       | {"unit": None if j["takes"] == "pump" else j["unit"],     # the page names the pump from the group
                          "conflicts": [f["id"] for f in fs if f["kind"] != "overrun"],     # known when the job was booked
                          "overrun": [f["id"] for f in fs if f["kind"] == "overrun"]})      # known when the work ran over
        return sorted(out, key=lambda j: (j["start"], j["id"]))

    def conflicts(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ids = sorted({c for j in jobs for c in j["conflicts"]}, key=lambda x: int(x.split("-")[1]))
        return [{"id": i, "kind": self.cal_ids[i]["kind"], "title": self.cal_ids[i]["title"], "jobs": self.cal_ids[i]["jobs"],
                 "text": self.cal_ids[i]["text"]} for i in ids]

    # ------------------------------------------------------------ deployment steps
    def steps(self, day: str, S: datetime, end: datetime) -> list[dict[str, Any]]:
        look = timedelta(days=self.cfg["top3"]["handoff_lookahead_days"])
        out = []
        for w in self.wos:
            done = parse(w["done"]) if w["done"] else None
            open_at_standup = done is None or done > S
            if not (w["due"] == day or (w["due"] < day and open_at_standup)):
                continue
            r = self.racks.get(w["rack"] or "", {})
            ho = r.get("committed_handoff")
            handed = bool(r.get("measured_handoff")) and parse(r["measured_handoff"]) <= S
            critical = (w["due"] < day and open_at_standup and bool(ho) and not handed and parse(ho) <= S + look)
            out.append({"id": w["id"], "key": w["key"], "partner": w["partner"], "step": w["step"], "rack": w["rack"],
                        "summary": w["summary"], "due": w["due"], "overdue": w["due"] < day and open_at_standup,
                        "done_before": not open_at_standup, "done_today": bool(done) and S < done <= end,
                        "committed_handoff": ho, "critical": critical})
        return sorted(out, key=lambda x: (not x["critical"], not x["overdue"], x["due"], x["id"]))

    # ------------------------------------------------------------ permits
    def permits(self, S: datetime, a: datetime, b: datetime) -> dict[str, Any]:
        if not self.ehs:
            return {"open": [], "issued": 0}
        jobs = self.ehs_jobs
        rows = []
        for p in self.ehs.permits:
            iss, cl = parse(p["issued"]), parse(p["closed"]) if p["closed"] else None
            if (iss <= S and (cl is None or cl > S)) or S < iss < b:
                rows.append({"permit": p["permit"], "type": p["type"], "job": p["job"], "point": p["point"], "partner": PARTNERS[p["partner"]],
                             "issued": p["issued"], "closed": p["closed"], "open_at_standup": iss <= S,
                             "title": jobs.get(p["job"], {}).get("title", "")})
        return {"open": sorted(rows, key=lambda r: r["issued"]),
                "issued": sum(1 for p in self.ehs.permits if a <= parse(p["issued"]) < b)}

    # ------------------------------------------------------------ spares
    def spares(self, S: datetime) -> list[dict[str, Any]]:
        out = []
        mins = {s["fru"]: s["minimum"] for s in self.d.it_sla["spares"]["minimum_stock_per_hall"]}
        led = self.d.it.context.src.get("spares_ledger") if hasattr(self.d.it.context.src, "get") else None
        rows = _csv(self.data_dir / "vendor" / "spares_ledger.csv") if led is None else led
        for fru, m in mins.items():
            xs = [r for r in rows if r["fru"] == fru]
            if not xs:
                continue
            before = [r for r in xs if parse(str(r["timestamp"]).replace(" ", "T").replace("+00:00", "Z")) <= S]
            bal = int(before[-1]["balance_after"]) if before else int(xs[0]["balance_after"]) - int(xs[0]["qty"])
            if bal < m:
                out.append({"where": "Spares cage", "fru": fru, "balance": bal, "minimum": m, "source": "IT Partner spares ledger"})
        if self.storage_ledger:
            from scorecard import telemetry_storage as TS
            for c in TS.shelf_classes():
                for hall in sorted({r["hall"] for r in self.storage_ledger}):
                    xs = [r for r in self.storage_ledger if r["hall"] == hall and r["fru"] == c["fru"] and parse(r["timestamp"]) <= S]
                    bal = int(xs[-1]["balance_after"]) if xs else TS.opening(hall, c["fru"])
                    if bal < c["minimum"]:
                        out.append({"where": f"Storage spares shelf, {_hall(hall)}", "fru": c["fru"], "balance": bal,
                                    "minimum": c["minimum"], "source": "Storage spares shelf ledger"})
        return out

    # ------------------------------------------------------------ staffing
    def shift(self, s: datetime, S: datetime, name: str) -> dict[str, Any]:
        """One shift: rostered against badged in, by each contract's rule. A shift that started before the standup
        counts badges up to the standup; one that ended counts them all."""
        d = self.d
        cut = min(S, s + timedelta(hours=12))
        it = [r for r in d.it.context.roster if r["shift_start"] == s]
        bp = d.it.context.badges_by_person

        def it_in(r):
            return any(b["door"] == "OPS-MAIN" and b["direction"] == "in" and r["shift_start"] - timedelta(hours=1) <= b["timestamp"] <= min(r["shift_end"], cut)
                       for b in bp.get(r["person_id"], []))
        lead = next((r["person_id"] for r in it if r["role"] == "shift_lead"), None)
        tech = [r for r in it if r["role"] == "technician"]
        ll = [r for r in d.ll.context.roster if r["shift_start"] == s]
        ll_in = [r["engineer"] for r in ll if any(b["person_id"] == r["engineer"] and b["reader"] == "Main lobby" and b["timestamp"] <= cut
                                                   and abs((b["timestamp"] - r["shift_start"]).total_seconds()) <= 3600 for b in d.ll.context.badges)]
        out = {"start": iso(s), "shift": name,
               "complete": s + timedelta(hours=12) <= S,
               "it": {"lead": lead, "rostered": len(tech), "badged": sum(1 for r in tech if it_in(r)),
                      "missing": [r["person_id"] for r in tech if not it_in(r)]},
               "landlord": {"rostered": len(ll), "badged": len(ll_in), "engineers": [r["engineer"] for r in ll],
                            "missing": [r["engineer"] for r in ll if r["engineer"] not in ll_in]}}
        if d.sec:
            posts = [r for r in d.sec.context.post_log if r["shift_start"] == s]

            def at_post(r):
                t = d.sec.context.post_badge_in(r)
                return bool(t) and t <= cut
            out["security"] = {"rostered": len(posts), "reported": sum(1 for r in posts if r["reported"] == "Staffed"),
                               "badged": sum(1 for r in posts if at_post(r)),
                               "missing": [r["post"] for r in posts if r["reported"] == "Staffed" and not at_post(r)]}
        return out

    def technician_hours(self, a: datetime, b: datetime) -> tuple[float, float]:
        """Committed and badge-verified technician hours in [a, b), as CSL-10 counts them."""
        committed = present = 0.0
        ctx = self.d.it.context
        for r in ctx.roster:
            if r["role"] != "technician":
                continue
            lo, hi = max(r["shift_start"], a), min(r["shift_end"], b)
            if hi <= lo:
                continue
            hrs = (hi - lo).total_seconds() / 3600
            committed += hrs
            if any(x["door"] == "OPS-MAIN" and x["direction"] == "in" and r["shift_start"] - timedelta(hours=1) <= x["timestamp"] <= r["shift_end"]
                   for x in ctx.badges_by_person.get(r["person_id"], [])):
                present += hrs
        return committed, present

    # ------------------------------------------------------------ top three
    def top3(self, inc: list[dict], red: list[dict], steps: list[dict]) -> list[dict[str, Any]]:
        items = []
        for i in inc:
            if i["at_risk"]:
                clock = (f"{_hm(-i['left_min'])} past its {_hm(i['target_min'])} restore target" if i["missed"]
                         else f"{_hm(i['used_min'])} of {_hm(i['target_min'])} used, restore by {hm_local(parse(i['due']))}")
                items.append({"rule": 1, "kind": "incident", "refs": i["refs"], "owner": i["owner"],
                              "text": f"{i['priority']} {i['what']}: {clock}."})
        for r in red:
            items.append({"rule": 2, "kind": "redundancy", "refs": [], "group": r["group"], "link": r["link"],
                          "owner": "Landlord" if r["link"] in ("power", "cdus", "mechanical") else "IT Partner",
                          "text": f"{r['text']}."})
        racks = set()
        for s in steps:                                 # one item per rack: its earliest open step
            if s["critical"] and s["rack"] not in racks:
                racks.add(s["rack"])
                items.append({"rule": 3, "kind": "deployment", "refs": [s["key"]], "owner": s["partner"],
                              "text": f"{s['summary']}: due {s['due']}, rack {s['rack']} committed for handoff "
                                      f"{s['committed_handoff'][:10]}."})
        return items[:3]

    # ------------------------------------------------------------ one day
    def day(self, day: str) -> dict[str, Any]:
        T = times(self.day_start[day], self.cfg)
        a, ov, S, b = T["start"], T["overnight_end"], T["standup"], T["end"]
        d = self.d
        inc = self.open_incidents(S)
        red_now = self.redundancy(S - timedelta(hours=1), S)          # the hour before the standup
        steps = self.steps(day, S, b) if self.wos else []
        work = self.work(S)
        idx = self.days.index(day)
        ws = self.start + timedelta(weeks=idx // 7)
        wk = week_id(ws)
        dm = self.cfg["duty_managers"]
        n = idx // 7
        it_p12 = [i for i in d.it_incidents if a <= i.t0 < b and i.priority in ("P1", "P2")]
        ll_p12 = [i for i in d.ll.incidents if a <= i.t0 < b and i.priority in ("P1", "P2")]
        raised = [(p, f) for p, f in self.findings if knowable_at(f) and a <= knowable_at(f) < b]
        committed, present = self.technician_hours(a, b)
        permits = self.permits(S, a, b)
        cal_jobs = [j for j in (self.cal["jobs"] if self.cal else []) if j["period"] == "past" and a <= parse(j["start"]) < b]
        return {
            "date": day, "weekday": WEEKDAYS[date.fromisoformat(day).weekday()], "week": wk, "week_day": idx % 7 + 1,
            "start": iso(a), "overnight_end": iso(ov), "standup": iso(S), "end": iso(b),
            "overnight": {"records": self.records_opened(a, ov), "redundancy": self.redundancy(a, ov),
                          "safety": self.safety_events(a, ov)},
            "incidents": inc,
            "redundancy": red_now,
            "work": work, "conflicts": self.conflicts(work) if self.cal else [],
            "steps": steps,
            "hallc": [{"id": x["id"], "title": x["title"], "state": x["state"]} for x in self.hallc if x["date"] == day],
            "permits": permits["open"],
            "spares": self.spares(S),
            "staffing": [self.shift(a, S, "night"), self.shift(a + timedelta(hours=12), S, "day")],
            "on_call": {"now": on_call(S, self.notify), "tonight": on_call(b, self.notify),
                        "duty_managers": {k: v[n % len(v)] for k, v in dm.items()}},
            "top3": self.top3(inc, red_now, steps),
            "close": {
                "incidents": {"it": len(it_p12), "landlord": len(ll_p12),
                              "refs": sorted({t for i in it_p12 for t in i.tickets} | {(i.work_order or {}).get("wo") for i in ll_p12} - {None})},
                "findings": {"total": len(raised), "by_partner": {p: sum(1 for q, _ in raised if q == p) for p in PARTNERS.values()},
                             "list": [{"partner": p, "id": f.id, "severity": f.severity, "title": f.title, "refs": f.tickets,
                                       "known": iso(knowable_at(f))}
                                      for p, f in sorted(raised, key=lambda x: (self.sev.get(x[1].severity, 9), knowable_at(x[1])))]},
                "changes": {"worked": sum(1 for j in cal_jobs if j["status"] != "deferred"),
                            "deferred": sum(1 for j in cal_jobs if j["status"] == "deferred"),
                            "overrun": sorted({f["id"] for j in work for f in self.cal["findings"] if f["kind"] == "overrun"
                                               and j["id"] in f["jobs"] and a <= parse(f["at"]) < b}) if self.cal else []},
                "permits": permits["issued"],
                "steps_done": sum(1 for s in steps if s["done_today"]) + sum(
                    1 for w in self.wos if w["done"] and w["due"] > day and a <= parse(w["done"]) < b),
                "technician_hours": {"committed": round(committed, 1), "present": round(present, 1)},
                "safety": len(self.safety_events(a, b)),
            },
        }

    def build(self) -> dict[str, Any]:
        days = [self.day(x) for x in self.days]
        return {"window": {"start": iso(self.start), "end": iso(self.end)}, "days": days, "today": days[-1]["date"],
                "rule": self.cfg["top3"], "times": {k: hm_local(v) for k, v in times(self.start, self.cfg).items() if k != "start"} | {"handover_night": hm_local(self.start)},
                "partners": list(PARTNERS.values())}


# ---------------------------------------------------------------- reconciliation with the weekly pack
def week_totals(days: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each week's day-close counts, summed the way the weekly pack counts them."""
    out: dict[str, dict[str, Any]] = {}
    for x in days:
        w = out.setdefault(x["week"], {"days": 0, "it_p12": 0, "landlord_p12": 0, "findings": 0, "permits": 0, "changes": 0,
                                       "committed": 0.0, "present": 0.0})
        c = x["close"]
        w["days"] += 1
        w["it_p12"] += c["incidents"]["it"]
        w["landlord_p12"] += c["incidents"]["landlord"]
        w["findings"] += c["findings"]["total"]
        w["permits"] += c["permits"]
        w["changes"] += c["changes"]["worked"]
        w["committed"] += c["technician_hours"]["committed"]
        w["present"] += c["technician_hours"]["present"]
    return out


def reconcile(days: list[dict[str, Any]], packs: list[dict[str, Any]]) -> list[str]:
    """Where the seven days of a week do not add up to that week's pack (empty when every week reconciles)."""
    tot = week_totals(days)
    misses = []
    for p in packs:
        w = tot.get(p["id"])
        if not w:
            misses.append(f"{p['id']}: no standup days")
            continue
        it = p["incidents"]["it"]
        want = {"it_p12": len(it["p1"]) + it["p2_count"], "landlord_p12": len(p["incidents"]["landlord"]),
                "findings": len(p["findings"]["new"])}
        if p["ehs"].get("work"):
            want["permits"] = p["ehs"]["work"]["permits"]
        for k, v in want.items():
            if w[k] != v:
                misses.append(f"{p['id']} {k}: days {w[k]}, pack {v}")
        csl10 = next(r for r in p["partners"][0]["levels"] if r["id"] == "CSL-10")
        if csl10["week"] is not None and w["committed"] and round(100 * w["present"] / w["committed"], 1) != round(csl10["week"], 1):
            misses.append(f"{p['id']} technician hours: days {100 * w['present'] / w['committed']:.3f}%, pack CSL-10 {csl10['week']}%")
    return misses


def page_data(s: Standup | None = None) -> dict[str, Any]:
    s = s or Standup()
    out = s.build()
    from scorecard.weekly import build_all
    packs = build_all(s.d)
    out["weeks"] = {p["id"]: {"start": p["start"], "end": p["end"],
                              "pack": {"it_p12": len(p["incidents"]["it"]["p1"]) + p["incidents"]["it"]["p2_count"],
                                       "landlord_p12": len(p["incidents"]["landlord"]), "findings": len(p["findings"]["new"]),
                                       "permits": (p["ehs"].get("work") or {}).get("permits")},
                              "days": t} for p, t in zip(packs, [week_totals(out["days"])[p["id"]] for p in packs])}
    out["reconcile"] = reconcile(out["days"], packs)
    if s.cal:
        out["calendar_jobs"] = sum(1 for j in s.cal["jobs"] if j["period"] == "past" and j["status"] != "deferred")
    return out
