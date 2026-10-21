"""EHS layer: the month's work permits, training records, and reported safety events (data/ehs/).
Own random stream ("<seed>:ehs").

Reads, never writes, the month's dataset: the Landlord's MOPs, maintenance records, work orders, and roster, the IT
Partner's deployment milestones, personnel, and roster, the badge records, and what the devices recorded (the tap-off
breakers, the UPS bypass, the CDU pumps, the chiller lockouts). ``config/ehs.yaml`` says which jobs need which permit
and what each person must be trained in.

What the month holds:

- A permit of each type every job needs (``scorecard.ehs.jobs``), issued shortly before the work starts (a corrective
  work order's permit after the work order opens), with the lockout inside the device's isolation and the close after
  the work ends. The named people are the record's engineer, else whoever badged into the room just before, else who
  was on shift; an energized work permit names a second person outside the boundary.
- Every worker's training: one current completion of each course their role holds.
- Reported near misses, stop-work uses, first aid cases, and recordables, at rates per hour worked, with corrective
  actions. These are never findings.
- Planted (the answer key): a job with its permit missing; a lockout recorded before the device isolated the circuit;
  a named person whose NFPA 70E qualification had lapsed; a permit closed before the work ended.
- Also in the answer key, as found: any tap-off breaker the dataset shows operated before any job on it existed (the
  dataset's own ground truth names it), which no permit can cover.
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scorecard import ehs as E
from scorecard.ehs import EVENT_COLS, PERMIT_COLS, TRAINING_COLS, iso, parse

FRAMING = "Synthetic work permits, training records, and safety events for a portfolio demonstration. All records are fictional."

WHERE = {"it": ["Hall A cold aisle", "Hall B cold aisle", "Hall B receiving dock", "Spares cage", "Hall B overhead tray"],
         "landlord": ["Hall A electrical room", "Hall B electrical room", "Chiller yard", "Generator yard", "Pump room", "Hall B"],
         "security": ["Receiving dock", "Hall A entrance", "Perimeter patrol", "Security console"]}
WHAT = {
    "near_miss": {"it": ["Rack lift pallet jack wheel caught on a floor grommet; load steadied, no contact.",
                         "Ladder footing slipped on packaging film during overhead tray work; spotter held it.",
                         "Unlabelled coolant drip found at a manifold during a tray swap; area coned off."],
                  "landlord": ["Door to the battery room found propped open with no one inside.",
                               "Hose left across the chiller yard walkway after a coolant top-up.",
                               "Panel cover left off after a reading; closed before anyone was near it."],
                  "security": ["Dock leveller lip raised as a guard walked past; no contact.",
                               "Wet floor at the Hall A entrance after rain; guard set out a sign."]},
    "stop_work": {"it": ["Stopped a rack move: route survey not on hand.", "Stopped tray work: ESD strap tester failed."],
                  "landlord": ["Stopped a filter change: spill kit missing at the CDU.", "Stopped yard work: heat index reached 90 F, rest break taken."],
                  "security": ["Stopped a delivery: forklift operating without a spotter."]},
    "first_aid": {"it": ["Minor cut on a cage nut; cleaned and bandaged on Site."],
                  "landlord": ["Heat cramps in the generator yard; rest, water, returned to work."],
                  "security": ["Blister from patrol boots; dressed on Site."]},
    "recordable": {"it": ["Strained back lifting a power shelf without a lift assist; restricted duty."],
                   "landlord": ["Wrist sprain on the chiller yard stairs; treated by a clinic, days away from work."],
                   "security": ["Knee injury on the dock stairs; treated by a clinic, restricted duty."]},
}
ACTION = {"near_miss": "Hazard corrected and shared at the next shift briefing.",
          "stop_work": "Condition corrected before work resumed.",
          "first_aid": "Task reviewed with the crew; control added to the job hazard analysis.",
          "recordable": "Incident investigation and corrective action plan under the common terms."}


def _dump(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: (";".join(r[c]) if isinstance(r.get(c), list) else r.get(c, "")) for c in cols})


def _poisson(rng: random.Random, lam: float) -> int:
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


class EhsLayer:
    def __init__(self, sample_dir: str | Path, seed: int, cfg: dict[str, Any] | None = None, security_dir: Path | None = None):
        self.dir = Path(sample_dir)
        self.cfg = cfg or E.config()
        self.m = E.load_month(self.dir)
        self.window = self.m.window
        self.security_dir = security_dir
        self.rng = random.Random(f"{seed}:ehs")
        self.it_roster = E._csv(self.dir / "vendor" / "roster.csv")
        gt = self.dir / "ground_truth" / "facility_planted_discrepancies.json"
        self.gt = [x for x in (json.loads(gt.read_text(encoding="utf-8")) if gt.exists() else []) if x["type"] == "critical_work_no_mop"]

    # ------------------------------------------------------------------ people
    def _on_duty(self, t: datetime) -> list[str]:
        return sorted({who for s, e, who in E.ll_shifts(self.m, self.cfg["generate"]["shift_hours"]) if s <= t < e})

    def _landlord_worker(self, j: dict[str, Any], t: datetime) -> str:
        if j["people"]:
            return j["people"][0]
        near = [b for b in self.m.ll_badges if b["reader"] == j["room"] and t - timedelta(minutes=90) <= parse(b["timestamp"]) <= t]
        if near:
            return max(near, key=lambda b: b["timestamp"])["person_id"]
        duty = self._on_duty(t)
        return self.rng.choice(duty) if duty else sorted({e for _, _, e in E.ll_shifts(self.m)})[0]

    def _it_workers(self, s: datetime, e: datetime, n: int = 2) -> list[str]:
        on = sorted({r["person_id"] for r in self.it_roster if r["role"] == "technician"
                     and parse(r["shift_start"]) <= e and parse(r["shift_end"]) > e})
        return sorted(self.rng.sample(on, min(n, len(on))))

    # ------------------------------------------------------------------ permits
    def _permit(self, j: dict[str, Any], t: str, worker: str | None) -> dict[str, Any]:
        g, rng = self.cfg["generate"], self.rng
        start, end = parse(j["start"]), E.work_end(j)
        if j["source"] == "Work order":
            opened = parse(next(o["opened"] for o in self.m.wos if o["wo"] == j["id"]))
            # after the work order opens, before the work starts (an engineer engaged before the record exists issues it on the spot)
            issued = opened + (start - opened) * rng.uniform(0.2, 0.8) if start - opened > timedelta(minutes=2) else start - timedelta(seconds=30)
        else:
            issued = start - timedelta(minutes=rng.uniform(*g["issued_before_min"]))
        p = {"type": t, "job": j["id"], "partner": j["partner"], "point": j["point"] or "", "issued": iso(issued),
             "approved": "", "lock_on": "", "lock_off": "", "closed": iso(end + timedelta(minutes=rng.uniform(*g["closed_after_min"]))),
             "workers": [], "attendant": "", "issuer": f"{E.PARTNERS[j['partner']]} EHS coordinator"}
        if t == "eewp":
            p["approved"] = iso(issued - timedelta(days=rng.uniform(*g["eewp_approved_days_before"])))
            p["issuer"] = "Customer EHS"
        if t == "loto":
            s, e = (parse(j["device"][0]), parse(j["device"][1])) if j["device"] else (start, end)
            s = max(s, issued)
            room = (e - s).total_seconds() / 60 / 3
            lo, hi = min(g["lock_after_min"][0], room / 2), min(g["lock_after_min"][1], room)
            p["lock_on"], p["lock_off"] = iso(s + timedelta(minutes=rng.uniform(lo, hi))), iso(e - timedelta(minutes=rng.uniform(lo, hi)))
        if j["partner"] == "it":
            p["workers"] = self._it_workers(start, end)
        else:
            p["workers"] = [worker]
            if t == "eewp":
                others = [x for x in self._on_duty(start) if x != worker] or \
                         [x for x in sorted({e for _, _, e in E.ll_shifts(self.m)}) if x != worker]
                p["attendant"] = rng.choice(others)
        return p

    # ------------------------------------------------------------------ training
    def _training(self, people: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
        g, rng = self.cfg["generate"], self.rng
        m_start, m_end = self.m.start, self.m.end
        rows = []
        for who, (partner, role) in sorted(people.items()):
            for key, c in self.cfg["courses"].items():
                fors = c["for"]
                if fors != "all" and partner not in fors and role not in fors:
                    continue
                lo = E.add_months(m_end + timedelta(days=g["training_margin_days"]), -c["months"])
                hi = m_start - timedelta(days=7)
                done = (lo + (hi - lo) * rng.random()).replace(hour=14, minute=0, second=0)
                rows.append({"person": who, "partner": partner, "role": role, "course": key, "completed": iso(done),
                             "expires": iso(E.add_months(done, c["months"]))})
        return rows

    # ------------------------------------------------------------------ safety events
    def _events(self, hours: dict[str, float]) -> list[dict[str, Any]]:
        g, rng, m = self.cfg["generate"], self.rng, self.m
        out = []
        for partner in sorted(hours):
            for kind, rate in g["events_per_10k_hours"].items():
                for _ in range(_poisson(rng, hours[partner] * rate / 10000)):
                    day = m.start + timedelta(days=rng.randrange((m.end - m.start).days))
                    at = day + timedelta(hours=rng.uniform(13, 23))
                    due = at + timedelta(days=rng.randint(*g["action_days"]))
                    closed = at + (due - at) * rng.uniform(0.3, 1.0) if rng.random() < g["action_closed_share"] else None
                    out.append({"kind": kind, "partner": partner, "at": iso(at), "where": rng.choice(WHERE[partner]),
                                "what": rng.choice(WHAT[kind][partner]), "action": ACTION[kind], "action_due": iso(due),
                                "action_closed": iso(closed) if closed else ""})
        out.sort(key=lambda x: (x["at"], x["partner"]))
        for i, x in enumerate(out, 1):
            x["event"] = f"SE-{i}"
        return out

    # ------------------------------------------------------------------ the month
    def run(self) -> dict[str, Any]:
        m, cfg, rng = self.m, self.cfg, self.rng
        J = E.jobs(m, cfg)
        permits: list[dict[str, Any]] = []
        for j in J:
            worker = self._landlord_worker(j, parse(j["start"])) if j["partner"] == "landlord" else None
            for t in j["permits"]:
                permits.append(self._permit(j, t, worker))
        people = E.roles(m)
        if self.security_dir and (self.security_dir / "guards.csv").exists():
            for r in E._csv(self.security_dir / "guards.csv"):
                people[r["guard_id"]] = ("security", "guard")
        training = self._training(people)
        hours = E.hours_worked(m, self.security_dir, cfg["generate"]["shift_hours"])
        events = self._events(hours)

        # As found: breaker operations no generated permit covers. The dataset's ground truth must name each one.
        key: list[dict[str, Any]] = []
        for b in m.breakers:
            t = parse(b["timestamp"])
            if b["event"] != "Breaker open" or not m.start <= t < m.end:
                continue
            if not any(p["point"] == b["tapoff"] and parse(p["issued"]) <= t <= parse(p["closed"]) for p in permits):
                gt = next((x for x in self.gt if x["busway"] == b["busway"] and x["at"] == b["timestamp"]), None)
                if not gt:
                    raise RuntimeError(f"tap-off {b['tapoff']} opened at {b['timestamp']} with no job and no ground truth")
                key.append({"kind": "no_permit", "ref": b["tapoff"], "source": "dataset", "ground_truth": gt["anomaly_id"],
                            "wo": gt.get("wo", ""), "at": b["timestamp"]})
        story = {k["wo"] for k in key}
        used: set[str] = set()

        def pick(cands):
            cands = [c for c in cands if c["job"] not in used and c["job"] not in story]
            c = rng.choice(cands)
            used.add(c["job"])
            return c

        jobs_by_id = {j["id"]: j for j in J}
        P = cfg["planted"]
        for _ in range(P.get("no_permit", 0)):
            c = pick([p for p in permits if p["type"] == "loto" and p["partner"] == "landlord"])
            permits = [p for p in permits if not (p["job"] == c["job"] and p["type"] == "loto")]
            key.append({"kind": "no_permit", "ref": c["job"], "source": "planted", "permit_type": "loto"})
        for _ in range(P.get("lock_power", 0)):
            c = pick([p for p in permits if p["type"] == "loto" and jobs_by_id[p["job"]]["device"]])
            dev_s = parse(jobs_by_id[c["job"]]["device"][0])
            on = dev_s - timedelta(minutes=rng.uniform(10, 40))
            c["lock_on"] = iso(on)
            c["issued"] = iso(min(parse(c["issued"]), on - timedelta(minutes=rng.uniform(5, 15))))
            key.append({"kind": "lock_power", "ref": None, "job": c["job"], "source": "planted",
                        "minutes": round((dev_s - on).total_seconds() / 60)})
        for _ in range(P.get("untrained", 0)):
            cands = [p for p in permits if p["partner"] == "landlord" and p["type"] in ("loto", "eewp")
                     and jobs_by_id[p["job"]]["electrical"]]
            c = pick(cands)
            who = c["workers"][0]
            first = min(parse(jobs_by_id[p["job"]]["start"]) for p in permits if who in p["workers"]
                        and p["type"] in ("loto", "eewp") and jobs_by_id[p["job"]]["electrical"])
            first = min([first] + [parse(j["start"]) for j in J if who in j["people"] and j["electrical"] and not j["permits"]])
            exp = first - timedelta(days=rng.uniform(5, 60))
            row = next(r for r in training if r["person"] == who and r["course"] == "nfpa70e")
            row["expires"] = iso(exp.replace(hour=14, minute=0, second=0))
            row["completed"] = iso(E.add_months(parse(row["expires"]), -cfg["courses"]["nfpa70e"]["months"]))
            key.append({"kind": "untrained", "ref": who, "source": "planted", "course": "nfpa70e", "expired": row["expires"]})
        for _ in range(P.get("closed_early", 0)):
            c = pick([p for p in permits if (E.work_end(jobs_by_id[p["job"]]) - parse(p["issued"])) > timedelta(minutes=50)])
            end = E.work_end(jobs_by_id[c["job"]])
            c["closed"] = iso(max(parse(c["issued"]) + timedelta(minutes=10), end - timedelta(minutes=rng.uniform(20, 45))))
            key.append({"kind": "closed_early", "ref": None, "job": c["job"], "source": "planted"})

        permits.sort(key=lambda p: (p["issued"], p["job"], p["type"]))
        for i, p in enumerate(permits, 1):
            p["permit"] = f"PTW-{26000 + i}"
        for k in key:
            if k["ref"] is None:                         # planted on a permit: the key names the permit
                k["ref"] = next(p["permit"] for p in permits if p["job"] == k["job"]
                                and (p["type"] == "loto" if k["kind"] == "lock_power" else True)
                                and (k["kind"] != "closed_early" or parse(p["closed"]) < E.work_end(jobs_by_id[p["job"]])))
        return {"permits": permits, "training": training, "events": events, "key": key, "hours": hours}


def write_ehs(layer: EhsLayer, out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, Any]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _dump(dest / "permits.csv", out["permits"], PERMIT_COLS)
    _dump(dest / "training.csv", out["training"], TRAINING_COLS)
    _dump(dest / "events.csv", out["events"], EVENT_COLS)
    (dest / "answer_key.json").write_text(json.dumps(out["key"], indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    man = {"disclaimer": FRAMING, "source": source, "window": layer.window,
           "files": {"permits.csv": len(out["permits"]), "training.csv": len(out["training"]), "events.csv": len(out["events"])}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
