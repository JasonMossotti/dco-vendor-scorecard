"""Forward schedule: the jobs booked from the end of the data weeks to Hall C first compute (data/calendar/).
Own random stream ("<seed>:calendar").

Reads, never writes, the site model, the device lists, the Hall B Jira milestones, and the Hall C commissioning
plan. ``config/calendar.yaml`` sets how many of each job a month, the working hours, and the planted conflicts.

Jobs are placed the way a careful planner would: one job at a time in each redundancy group, never both feeds of a
rack, no job that takes a unit out of a Hall B or site-wide group on a surge day, none that takes a site-wide unit out
in the freeze. The planner keeps its own book of what each group and rack has out, by the rules in the config; it does
not ask the checks (``scorecard.change_calendar.conflicts``), so the robustness run tests the checks against an
independent plan. Hall B HO-4 tap-off energizations follow the Landlord's Jira R-HO4 due dates. Then one job per
planted kind is added that breaks exactly that rule, against exactly one booked job; the answer key names them.
"""

from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path
from typing import Any

from scorecard import change_calendar as CC

FRAMING = "Synthetic forward maintenance and change schedule for a portfolio demonstration. All records are fictional."
COLS = ["id", "owner", "title", "window_start", "window_end", "note"]


class ForwardSchedule:
    def __init__(self, seed: int, root: Path = CC.ROOT, sample: Path = CC.SAMPLE, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or CC.config()
        self.root, self.sample = root, sample
        self.rng = random.Random(f"{seed}:calendar")
        self.G = CC.groups(root)
        self.racks = CC.rack_halls(root, sample)
        self.items = CC.day_items(root)
        self.surge = CC.surge_days(self.items, self.cfg)
        self.freeze = CC.freeze_window(self.cfg)
        self.wt = {w["type"]: w for w in self.cfg["work_types"]}
        self.rows: list[dict[str, Any]] = []
        self.n = {"MOP": 500, "CHG": 2050000, "PM": 1000}

    # ------------------------------------------------------------ helpers
    def _job(self, row: dict[str, Any]) -> dict[str, Any]:
        return CC.make_job(row["id"], "Forward", row["owner"], row["title"], row["window_start"], row["window_end"], self.cfg,
                           self.G, self.racks, period="forward")

    def _clash(self, row: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> list[tuple[str, str]]:
        """The planner's rules broken if ``row`` were booked beside ``rows``: (rule, the other job's title or the day)."""
        j = self._job(row)
        if j["takes"] == "none":
            return []
        s, e = CC.parse(row["window_start"]), CC.parse(row["window_end"])
        out: list[tuple[str, str]] = []
        for r in self.rows if rows is None else rows:
            o = self._job(r)
            if o["takes"] == "none" or not (CC.parse(r["window_start"]) < e and s < CC.parse(r["window_end"])):
                continue
            if j["group"] and o["group"] == j["group"]:
                out.append(("overlap", r["title"]))
            if j["takes"] == "feed" and o["takes"] == "feed" and o["rack"] == j["rack"]:
                out.append(("both_feeds" if o["unit"] != j["unit"] else "overlap", r["title"]))
        on = {CC.local_day(s), CC.local_day(e - timedelta(seconds=1))}
        site_wide = bool(j["group"]) and self.G[j["group"]]["hall"] is None
        if (site_wide or j["hall"] == "HALL-B") and on & set(self.surge):
            out.append(("surge", min(on & set(self.surge))))
        if site_wide and on & set(CC.days(*self.freeze)):
            out.append(("freeze", min(on & set(CC.days(*self.freeze)))))
        return out

    def _row(self, kind: str, title: str, day: str) -> dict[str, Any]:
        w = self.wt[kind]
        lo, hi = w.get("hours", self.cfg["schedule"]["local_hours"])
        t = CC.at_local(day, round(self.rng.uniform(lo, hi) * 4) / 4)
        if w["mop"]:
            m0, m1 = self.cfg["schedule"]["mop_margin_min"]
            s, e = t - timedelta(minutes=m0), t + timedelta(minutes=w["minutes"] + m1)
        else:
            s, e = t, t + timedelta(minutes=w["minutes"])
        prefix = "CHG" if w["owner"] == "IT Partner" else "MOP" if w["mop"] else "PM"
        return {"id": prefix, "owner": w["owner"], "title": title, "window_start": CC.iso(s), "window_end": CC.iso(e), "note": ""}

    def _place(self, kind: str, title: str, month_days: list[str], tries: int = 400) -> dict[str, Any] | None:
        """Book the job on a day of the month where it conflicts with nothing already booked."""
        for _ in range(tries):
            row = self._row(kind, title, self.rng.choice(month_days))
            if not self._clash(row):
                self.rows.append(row)
                return row
        return None

    def _months(self) -> list[list[str]]:
        f = self.cfg["forward"]
        out: dict[str, list[str]] = {}
        for d in CC.days(f["start"], f["end"]):
            out.setdefault(d[:7], []).append(d)
        return [v for v in out.values() if len(v) >= 14]            # a month with two weeks or more gets its program

    # ------------------------------------------------------------ the schedule
    def run(self) -> dict[str, Any]:
        rng, cfg = self.rng, self.cfg
        hall_cdus = [u for k, g in self.G.items() if k.startswith("cdu-") for u in g["units"]]
        ups = [u for k, g in self.G.items() if k.startswith("ups-") for u in g["units"]]
        chillers = self.G["chillers"]["units"]
        gens = self.G["generators"]["units"]
        vesda = [f"VESDA-{h}{n}" for h in "AB" for n in (1, 2)]
        hall_a = sorted(r for r, h in self.racks.items() if h == "HALL-A")
        cdu_turn = sorted(hall_cdus, key=lambda c: (c not in ("CDU-A1", "CDU-A2", "CDU-A4", "CDU-B1"), c))
        for mdays in self._months():
            share = len(mdays) / 30
            n = {k: max(1, round(v * min(1.0, share))) for k, v in cfg["schedule"]["per_month"].items()}
            for g in gens[:n["gen_exercise"]]:
                self._place("gen_exercise", f"Monthly loaded exercise: {g}", mdays)
            done = {self._job(r)["unit"] for r in self.rows}
            for u in rng.sample([u for u in ups if u not in done], n["ups_pm"]):
                self._place("ups_pm", f"Preventive maintenance and battery health check: {u}", mdays)
            for _ in range(n["cdu_filter"]):
                c = cdu_turn.pop(0)
                cdu_turn.append(c)
                self._place("cdu_filter", f"Filter change and coolant sample: {c}", mdays)
            for c in rng.sample([c for c in chillers if c not in done], n["chiller_pm"]):
                self._place("chiller_pm", f"Preventive maintenance: {c}", mdays)
            for v in rng.sample(vesda, n["vesda_test"]):
                self._place("vesda_test", f"VESDA inspection and smoke test: {v}", mdays)
            for h in rng.sample(["A", "B"], n["thermography"]):
                self._place("thermography", f"Infrared thermography under load: Hall {h} electrical room", mdays)
            for r in rng.sample(hall_a, n["tapoff_work"] + n["tray_firmware"])[:n["tapoff_work"]]:
                self._place("tapoff_work", f"Retorque {rng.choice('AB')}-side tap-off for rack {r}", mdays)
            for r in rng.sample(hall_a, n["tray_firmware"]):
                self._place("tray_firmware", f"Compute tray firmware 1.3.7 -> 1.3.8 on rack {r}", mdays)
        for x in self.items:
            if x["kind"] == "hallb" and x["step"] == "R-HO4" and x["state"] != "done" and x["date"] >= cfg["forward"]["start"]:
                self._place("tapoff_energize", f"Energize tap-off TO-{x['rack']} for a new rack (HO-4)", [x["date"]])
        key = self._plant(hall_cdus)
        self._number(key)
        return {"schedule": self.rows, "key": sorted(key, key=lambda k: (k["kind"], k["job"]))}

    def _plant(self, hall_cdus: list[str]) -> list[dict[str, Any]]:
        rng = self.rng
        key: list[dict[str, Any]] = []
        jobs = {id(r): self._job(r) for r in self.rows}
        f0, f1 = self.freeze
        fz = CC.days(f0, f1)

        def try_add(kind: str, make) -> None:
            for _ in range(400):
                row = make()
                if row is None:
                    continue
                got = self._clash(row)
                if len(got) == 1 and got[0][0] == kind:
                    self.rows.append(row)
                    key.append({"kind": kind, "row": row})
                    return

        def overlap_with(other: dict[str, Any], title: str, kind: str) -> dict[str, Any]:
            row = self._row(kind, title, CC.local_day(CC.parse(other["window_start"])))
            s = CC.parse(other["window_start"]) + timedelta(minutes=rng.choice([15, 30, 45, 60]))
            dur = CC.parse(row["window_end"]) - CC.parse(row["window_start"])
            row["window_start"], row["window_end"] = CC.iso(s), CC.iso(s + dur)
            return row

        if self.cfg["planted"].get("overlap"):
            def mk():
                cands = [r for r in self.rows if jobs.get(id(r), {}).get("type") in ("ups_pm", "chiller_pm")]
                if not cands:
                    return None
                o = rng.choice(cands)
                g = self.G[jobs[id(o)]["group"]]
                u = rng.choice([x for x in g["units"] if x != jobs[id(o)]["unit"]])
                t = jobs[id(o)]["type"]
                title = f"Preventive maintenance and battery health check: {u}" if t == "ups_pm" else f"Preventive maintenance: {u}"
                return overlap_with(o, title, t)
            try_add("overlap", mk)
        if self.cfg["planted"].get("both_feeds"):
            def mk():
                cands = [r for r in self.rows if jobs.get(id(r), {}).get("type") == "tapoff_work"]
                if not cands:
                    return None
                o = rng.choice(cands)
                j = jobs[id(o)]
                side = "B" if j["unit"].endswith("A") else "A"
                return overlap_with(o, f"Retorque {side}-side tap-off for rack {j['rack']}", "tapoff_work")
            try_add("both_feeds", mk)
        if self.cfg["planted"].get("surge"):
            def mk():
                d = rng.choice(sorted(d for d in self.surge if d >= self.cfg["forward"]["start"]))
                c = rng.choice([c for c in hall_cdus if c.startswith("CDU-B")])
                return self._row("cdu_filter", f"Filter change and coolant sample: {c}", d)
            try_add("surge", mk)
        if self.cfg["planted"].get("freeze"):
            def mk():
                booked = {self._job(r)["unit"] for r in self.rows}
                free = [c for c in self.G["chillers"]["units"] if c not in booked] or self.G["chillers"]["units"]
                return self._row("chiller_pm", f"Preventive maintenance: {rng.choice(free)}", rng.choice(fz))
            try_add("freeze", mk)
        return key

    def _number(self, key: list[dict[str, Any]]) -> None:
        """IDs in booking order (window start), so a planted job reads like any other."""
        self.rows.sort(key=lambda r: (r["window_start"], r["title"]))
        for r in self.rows:
            p = r["id"]
            self.n[p] += 1
            r["id"] = f"{p}-{self.n[p]}" if p != "CHG" else f"CHG{self.n[p]}"
        for k in key:
            k["job"] = k.pop("row")["id"]


def write_calendar(sched: ForwardSchedule, out: dict[str, Any], dest: str | Path, seed: int) -> dict[str, Any]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    rows = [{c: r[c] for c in COLS} for r in out["schedule"]]
    (dest / "schedule.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8", newline="\n")
    (dest / "answer_key.json").write_text(json.dumps(out["key"], indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    man = {"disclaimer": FRAMING, "seed": seed, "forward": sched.cfg["forward"], "files": {"schedule.json": len(rows)},
           "note": "Own random stream; answer_key.json is the answer key and the checks never read it."}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
