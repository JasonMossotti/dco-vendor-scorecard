"""Synthetic program record for the Hall B GB300 rollout: what the partners' Jira projects, the Customer's own
records, the sign-offs, the inspections, and the permits would hold (data/deployments/).

Own random stream (``{seed}:deployments``); ``data/sample`` is read, never written, so every existing record and
report stays byte-identical. The rack milestones in the IT Partner's project are the IT Partner's own self-report,
the same times as ``data/sample/vendor/deployment_milestones.csv``; the Landlord's energization of each rack (HO-4)
falls between its leak test and its power-on. The Jira files have the shape a Jira Cloud search returns
(``/rest/api/3/search/jql``), so a real export reads through the same importer (``scorecard.jira_import``).

No person is named anywhere: Jira assignees are left empty and sign-offs carry a role and an organization.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from .. import deployments as D
from ..sla_model import load_sla

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "deployments_data.yaml"
UTC = timezone.utc
STATUS = {"done": ("Done", "done"), "doing": ("In Progress", "indeterminate"), "todo": ("To Do", "new")}
FIELD = {"start": "customfield_10015", "step": "customfield_10101", "rack": "customfield_10102", "doc": "customfield_10103"}


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def jira_time(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def from_jira(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f%z")


class DeploymentRecordLayer:
    def __init__(self, data_dir: str | Path, seed: int, cfg: dict[str, Any] | None = None,
                 program: dict[str, Any] | None = None, plant: bool = True):
        self.data_dir = Path(data_dir)
        self.cfg = cfg or load_config()
        self.program = program or D.load_config()
        self.sla = load_sla()
        self.rng = random.Random(f"{seed}:deployments")       # independent of every other stream
        self.prng = random.Random(f"{seed}:deployments:planted")  # what is planted never moves the rest
        self.plant = plant
        manifest = json.loads((self.data_dir / "manifest.json").read_text(encoding="utf-8"))
        self.window = manifest["window"]
        self.as_of = _ts(self.window["end"])
        syn = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
        self.offset = timedelta(hours=syn["site_utc_offset_hours"])
        self.profile = self.program["program"]["jurisdiction"]
        self.steps = D.steps(self.program, self.sla)
        for s in self.steps:
            s["inspections"] = [i for i in s["inspections"] if D.applies(i, self.profile)]
        hall = self.program["program"]["hall"]
        first = min(_ts(r["planned_receipt"]) for r in self._csv("customer/deployment_plan.csv") if r["hall"] == hall)
        self.program_day = self._local_day(first) - timedelta(days=self.cfg["program_lead_days"])

    # ---------------------------------------------------------------- time helpers
    def _work(self, day: date, hour: float) -> datetime:
        """A local working-day time on ``day`` as UTC."""
        return datetime.combine(day, time(0), tzinfo=UTC) + timedelta(hours=hour) - self.offset

    def _local_day(self, t: datetime) -> date:
        return (t + self.offset).date()

    # ---------------------------------------------------------------- schedule
    def schedule(self) -> dict[str, dict[str, Any]]:
        """Start and end of every program step (not per rack). Done when it ended before the window end."""
        c, out = self.cfg, {}
        start0 = self._work(self.program_day, c["workday_start_hour"])
        rack_plan = self._csv("customer/deployment_plan.csv")
        hall_racks = [r for r in rack_plan if r["hall"] == self.program["program"]["hall"]]
        last_handoff = max(_ts(r["committed_handoff"]) for r in hall_racks)
        first_receipt = min(_ts(r["planned_receipt"]) for r in hall_racks)
        for s in self.steps:
            if s["per_rack"]:
                continue
            # A step after the rack work waits for the last rack's committed handoff.
            preds = [out[a]["end"] if a in out else last_handoff for a in s["after"]]
            begin = max(preds) if preds else start0
            day = self._local_day(begin) + timedelta(days=1 if preds else 0)
            start = self._work(day, c["workday_start_hour"] + self.rng.uniform(0, 2))
            days = c["days"][s["id"]] * (1 + self.rng.uniform(-c["jitter"], c["jitter"]))
            end_day = self._local_day(start + timedelta(days=days))
            end = self._work(end_day, c["workday_start_hour"] + self.rng.uniform(1, 8))
            out[s["id"]] = {"start": start, "end": end}
        g1_end = out["G1-08"]["end"]
        if g1_end >= first_receipt:
            raise ValueError(f"hall readiness ends {iso(g1_end)}, after the first rack arrives {iso(first_receipt)}")
        return out

    def _csv(self, rel: str) -> list[dict[str, str]]:
        with (self.data_dir / rel).open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    # ---------------------------------------------------------------- run
    def run(self) -> dict[str, Any]:
        c = self.cfg
        sched = self.schedule()
        roles = self.program["roles"]
        hall = self.program["program"]["hall"]
        plan = [r for r in self._csv("customer/deployment_plan.csv") if r["hall"] == hall]
        reported: dict[str, dict[str, str]] = {}
        for r in self._csv("vendor/deployment_milestones.csv"):
            reported.setdefault(r["rack"], {})[r["milestone"]] = r["reported_complete_at"]
        rack_steps = [s for s in self.steps if s["per_rack"]]

        # Every unit of work: (step, rack or None, tracker, state, planned start, due, done time).
        units: list[dict[str, Any]] = []
        for s in self.steps:
            if s["per_rack"]:
                continue
            t = sched[s["id"]]
            state = "done" if t["end"] <= self.as_of else "doing" if t["start"] <= self.as_of else "todo"
            units.append({"step": s, "rack": None, "start": t["start"], "due": t["end"],
                          "done": t["end"] if state == "done" else None, "state": state})
        for p in plan:
            rack, rep = p["rack"], reported.get(p["rack"], {})
            receipt = _ts(p["planned_receipt"])
            times: dict[str, datetime] = {s["milestone"]: _ts(rep[s["milestone"]]) for s in rack_steps
                                          if s.get("milestone") in rep}
            if "M3" in times and "M4" in times:
                gap = (times["M4"] - times["M3"]).total_seconds()
                times["HO4"] = times["M3"] + timedelta(seconds=gap * self.rng.uniform(0.2, 0.5))
            started = False
            for s in rack_steps:
                k = s.get("milestone") or "HO4"
                target = s.get("target_days")
                due = receipt + timedelta(days=target if target is not None else 3.5)
                done = times.get(k)
                if done:
                    state = "done"
                elif not started and times:
                    state, started = "doing", True
                else:
                    state = "todo"
                units.append({"step": s, "rack": rack, "start": receipt, "due": due, "done": done, "state": state})

        key: dict[str, Any] = {"planted": [], "decoys": {}}
        if self.plant:
            self._plant_order(units, key)

        issues: dict[str, list[dict[str, Any]]] = {"landlord": [], "it_partner": []}
        epics: dict[tuple[str, str], str] = {}
        stories: dict[tuple[str, str], str] = {}
        counter = {k: 0 for k in issues}
        customer: list[dict[str, Any]] = []

        def tracker(s: dict[str, Any]) -> str:
            return c["tracking"][roles[s["owner"]]["org"]]

        def new_issue(proj: str, kind: str, summary: str, created: datetime, **f: Any) -> dict[str, Any]:
            counter[proj] += 1
            jc = c["jira"][proj]
            key = f"{jc['key']}-{counter[proj]}"
            fields = {"summary": summary, "issuetype": {"name": kind}, "created": jira_time(created),
                      "assignee": None, "labels": ["hall-b", "gb300"]}
            fields.update(f)
            issue = {"id": str(jc["id_base"] + counter[proj]), "key": key, "fields": fields}
            issues[proj].append(issue)
            return issue

        def status(fields: dict[str, Any], state: str, done: datetime | None, created: datetime) -> None:
            name, cat = STATUS[state]
            fields["status"] = {"name": name, "statusCategory": {"key": cat}}
            fields["resolutiondate"] = jira_time(done) if done else None
            fields["updated"] = jira_time(done if done else min(self.as_of, max(created, self.as_of - timedelta(hours=6))))

        program_start = self._work(self.program_day, c["workday_start_hour"])
        gates = {g["id"]: g for g in self.program["gates"]}
        units.sort(key=lambda u: (u["start"], u["rack"] or "", [s["id"] for s in self.steps].index(u["step"]["id"])))
        for u in units:
            s, proj = u["step"], tracker(u["step"])
            created = max(program_start, u["start"] - timedelta(days=c["created_before_days"]))
            if proj == "customer":
                customer.append({"id": f"CUST-{s['id']}", "step": s["id"], "rack": u["rack"], "state": u["state"],
                                 "planned_start": iso(u["start"]), "due": iso(u["due"]),
                                 "done": iso(u["done"]) if u["done"] else None})
                continue
            if (proj, s["gate"]) not in epics:
                e = new_issue(proj, "Epic", f"{s['gate']} {gates[s['gate']]['name']}", program_start,
                              **{FIELD["step"]: s["gate"]})
                status(e["fields"], "doing", None, program_start)
                epics[(proj, s["gate"])] = e["key"]
            parent = epics[(proj, s["gate"])]
            kind = "Task"
            if u["rack"] and proj == "it_partner":
                if (proj, u["rack"]) not in stories:
                    st = new_issue(proj, "Story", f"Rack {u['rack']}: receive, integrate, and hand off", created,
                                   parent={"key": parent}, **{FIELD["rack"]: u["rack"], FIELD["step"]: "G2"})
                    stories[(proj, u["rack"])] = st
                parent, kind = stories[(proj, u["rack"])]["key"], "Sub-task"
            name = s["name"] if not u["rack"] else f"{u['rack']}: {s['name']}"
            it = new_issue(proj, kind, f"{s['id']} {name}", created, parent={"key": parent},
                           duedate=self._local_day(u["due"]).isoformat(),
                           **{FIELD["start"]: self._local_day(u["start"]).isoformat(), FIELD["step"]: s["id"],
                              FIELD["rack"]: u["rack"], FIELD["doc"]: s["doc"]["id"]})
            status(it["fields"], u["state"], u["done"], created)
        for (proj, rack), st in stories.items():
            subs = [i for i in issues[proj] if i["fields"].get("parent", {}).get("key") == st["key"]]
            states = {i["fields"]["status"]["statusCategory"]["key"] for i in subs}
            state = "done" if states == {"done"} else "todo" if states == {"new"} else "doing"
            last = max((from_jira(i["fields"]["resolutiondate"]) for i in subs if i["fields"]["resolutiondate"]), default=None)
            status(st["fields"], state, last if state == "done" else None, from_jira(st["fields"]["created"]))

        signoffs, inspections = self._signoffs(units), self._inspections(units)
        if self.plant:
            signoffs, inspections = self._plant_records(units, signoffs, inspections, key)
        permits, determinations = self._permits(sched, inspections), self._determinations(sched)
        return {"window": self.window, "jira": {k: self._export(v) for k, v in issues.items()},
                "customer": customer, "signoffs": signoffs, "inspections": inspections,
                "permits": permits, "determinations": determinations, "answer_key": key}

    # ---------------------------------------------------------------- planted cases (own stream)
    def _plant_order(self, units: list[dict[str, Any]], key: dict[str, Any]) -> None:
        """The Landlord energizes one rack's tap-off (HO-4) before the rack's leak test (M3) is done; a second rack's
        HO-4 comes only minutes after M3 (a decoy: tight, but in order)."""
        r, c = self.prng, self.cfg
        by = {(u["step"]["id"], u["rack"]): u for u in units if u["rack"]}
        racks = sorted({rk for (sid, rk), u in by.items() if sid == "R-HO4" and u["done"]
                        and by[("R-M2", rk)]["done"] and (by[("R-M3", rk)]["done"] - by[("R-M2", rk)]["done"]) > timedelta(hours=12)})
        if len(racks) < 2:
            return
        for _ in range(c["planted"].get("out_of_order", 0)):
            rk = racks.pop(r.randrange(len(racks)))
            by[("R-HO4", rk)]["done"] = by[("R-M3", rk)]["done"] - timedelta(hours=r.uniform(2, 8))
            key["planted"].append({"kind": "out_of_order", "step": "R-HO4", "rack": rk})
        if racks:
            rk = racks.pop(r.randrange(len(racks)))
            lo, hi = c["decoys"]["handoff_after_leak_test_minutes"]
            by[("R-HO4", rk)]["done"] = by[("R-M3", rk)]["done"] + timedelta(minutes=r.uniform(lo, hi))
            key["decoys"]["handoff_minutes_after_leak_test"] = 1

    def _plant_records(self, units: list[dict[str, Any]], signoffs: list[dict[str, Any]], inspections: list[dict[str, Any]],
                       key: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Remove one sign-off, remove one required inspection's passing record, and date one sign-off before the
        work it accepts. Each on a different unit of work that is Done."""
        r, c = self.prng, self.cfg
        window = timedelta(days=c["signoff_window_days"])
        used = {(k["step"], k["rack"]) for k in key["planted"]}
        done = [u for u in units if u["done"] and (u["step"]["id"], u["rack"]) not in used]

        def pick(pool: list[dict[str, Any]]) -> dict[str, Any] | None:
            pool = [u for u in pool if (u["step"]["id"], u["rack"]) not in used]
            if not pool:
                return None
            u = pool[r.randrange(len(pool))]
            used.add((u["step"]["id"], u["rack"]))
            return u

        def mine(rows: list[dict[str, Any]], u: dict[str, Any]) -> list[dict[str, Any]]:
            return [x for x in rows if x["step"] == u["step"]["id"] and x["rack"] == u["rack"]]

        for _ in range(c["planted"].get("unsigned", 0)):
            u = pick([u for u in done if self.as_of - u["done"] > window + timedelta(days=1)
                      and len(mine(signoffs, u)) == len(u["step"]["signoff"]) > 1])
            if u:
                drop = r.choice(mine(signoffs, u)[1:])
                signoffs = [x for x in signoffs if x is not drop]
                key["planted"].append({"kind": "unsigned", "step": u["step"]["id"], "rack": u["rack"], "role": drop["role"]})
        for _ in range(c["planted"].get("uninspected", 0)):
            u = pick([u for u in done if u["step"]["inspections"]])
            if u:
                by = r.choice(sorted({i["by"] for i in u["step"]["inspections"]}))
                gone = [x for x in mine(inspections, u) if x["by"] == by and x["result"] == "pass"]
                inspections = [x for x in inspections if not any(x is g for g in gone)]
                key["planted"].append({"kind": "uninspected", "step": u["step"]["id"], "rack": u["rack"], "by": by})
        for _ in range(c["planted"].get("signed_early", 0)):
            u = pick([u for u in done if len(mine(signoffs, u)) == len(u["step"]["signoff"]) > 1])
            if u:
                x = r.choice(mine(signoffs, u)[1:])
                x["signed_at"] = iso(u["done"] - timedelta(hours=r.uniform(6, 72)))
                key["planted"].append({"kind": "signed_early", "step": u["step"]["id"], "rack": u["rack"], "role": x["role"]})
        signoffs.sort(key=lambda x: (x["signed_at"], x["step"], x["rack"] or ""))
        for n, x in enumerate(inspections, 1):
            x["id"] = f"INSP-B-{n:03d}"

        # Decoys the checks must leave alone: signatures still inside the window, and failures that were retested.
        pending = sum(1 for u in units if u["done"] and self.as_of - u["done"] <= window
                      and len(mine(signoffs, u)) < len(u["step"]["signoff"]))
        retests = sum(1 for u in units if u["done"] and {"fail", "pass"} <= {x["result"] for x in mine(inspections, u)})
        key["decoys"].update(signatures_pending_in_window=pending, inspections_failed_then_passed=retests)
        return signoffs, inspections

    def _export(self, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """The shape of a Jira Cloud search response (/rest/api/3/search/jql), last page."""
        return {"issues": issues, "isLast": True}

    def _signoffs(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lo, hi = self.cfg["signoff_lag_hours"]
        out = []
        for u in units:
            if not u["done"]:
                continue
            t = u["done"]
            for n, r in enumerate(u["step"]["signoff"]):
                t = t + timedelta(hours=self.rng.uniform(lo, hi) if n else self.rng.uniform(0.1, lo))
                if t > self.as_of:
                    break
                out.append({"step": u["step"]["id"], "rack": u["rack"], "role": r,
                            "org": self.program["roles"][r]["org"], "signed_at": iso(t), "decision": "accepted"})
        return sorted(out, key=lambda x: (x["signed_at"], x["step"], x["rack"] or ""))

    def _inspections(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fails = {(f["step"], f["by"]): f for f in self.cfg["first_time_failures"]}
        out = []
        for u in units:
            if not u["done"]:
                continue
            for i in u["step"]["inspections"]:
                at = u["done"] - timedelta(hours=self.rng.uniform(1, 6))
                base = {"step": u["step"]["id"], "rack": u["rack"], "by": i["by"], "kind": i["kind"], "what": i["what"]}
                f = fails.get((u["step"]["id"], i["by"]))
                if f:
                    out.append(dict(base, at=iso(at - timedelta(days=f["retest_days"])), result="fail", note=f["note"]))
                out.append(dict(base, at=iso(at), result="pass", note="Retest passed." if f else ""))
        out.sort(key=lambda x: (x["at"], x["step"]))
        for n, x in enumerate(out, 1):
            x["id"] = f"INSP-B-{n:03d}"
        return out

    def _permits(self, sched: dict[str, dict[str, Any]], inspections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        prof = self.program["authorities"][self.profile]
        out, finaled = [], None
        for n, p in enumerate(prof["permits"], 1):
            rule = self.cfg["permits"].get(p["id"], {})
            row = {"permit": p["id"], "name": p["name"], "by": p["by"], "number": f"{p['id']}-26-{self.rng.randint(1000, 9999)}"}
            if "not_required" in rule:
                out.append(dict(row, number=None, status="not required", reason=rule["not_required"]))
                continue
            if "applied_step" in rule:
                a = sched[rule["applied_step"]]
                applied = a["start"] + timedelta(days=self.rng.uniform(1, 3))
                issued = a["end"] - timedelta(hours=self.rng.uniform(0.5, 4))
                passes = [x for x in inspections if x["step"] == rule["final_step"] and x["by"] == p["by"] and x["result"] == "pass"]
                final = _ts(passes[-1]["at"]) if passes else None
                finaled = max(finaled, final) if finaled and final else final or finaled
                out.append(dict(row, applied=iso(applied), issued=iso(issued), finaled=iso(final) if final else None,
                                status="finaled" if final else "issued", inspection=passes[-1]["id"] if passes else None))
            elif "after_final_days" in rule and finaled:
                out.append(dict(row, issued=iso(finaled + timedelta(days=rule["after_final_days"])), status="issued"))
        return out

    def _determinations(self, sched: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        sealed = sched["G0-03"]["end"]
        nec_change = datetime(2026, 9, 1, tzinfo=UTC) - self.offset
        out.append({"id": "TX-NEC", "recorded": iso(sealed), "step": "G0-03",
                    "result": ("2023 NEC: construction documents sealed before the 2026 NEC took effect in Texas on 2026-09-01."
                               if sealed < nec_change else "2026 NEC: construction documents sealed on or after 2026-09-01.")})
        for k, v in self.cfg["determinations"].items():
            out.append({"id": k, "recorded": iso(sched[v["step"]]["end"]), "step": v["step"], "result": v["result"]})
        return out


def write_deployments(out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, int]:
    dest = Path(dest)
    (dest / "jira").mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    files: dict[str, str] = {}
    counts: dict[str, int] = {}
    for proj, export in out["jira"].items():
        name = f"jira/{cfg['jira'][proj]['key']}.json"
        files[name] = json.dumps(export, indent=1, sort_keys=True) + "\n"
        counts[name] = len(export["issues"])
    for name, rows in (("customer_steps.json", out["customer"]), ("permits.json", out["permits"]),
                       ("determinations.json", out["determinations"]), ("answer_key.json", out["answer_key"])):
        files[name] = json.dumps(rows, indent=1, sort_keys=True) + "\n"
        counts[name] = len(rows["planted"]) if isinstance(rows, dict) else len(rows)
    for name, rows in (("signoffs.jsonl", out["signoffs"]), ("inspections.jsonl", out["inspections"])):
        files[name] = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        counts[name] = len(rows)
    files["manifest.json"] = json.dumps({
        "disclaimer": "Synthetic deployment program records for a portfolio demonstration: the partners' Jira projects "
                      "(Jira Cloud search export shape), the Customer's step records, sign-offs by role, inspections, and "
                      "permits. Fictional parties and numbers; no person is named. answer_key.json lists the planted "
                      "records that do not reconcile, for the checks' self-test only; the checks never read it.",
        "source": source, "window": out["window"], "files": counts}, indent=2, sort_keys=True) + "\n"
    for name, text in files.items():
        (dest / name).write_text(text, encoding="utf-8", newline="\n")
    return counts
