"""Synthetic readiness record for Hall C, the 800 VDC pilot (data/readiness/): the commissioning agent's scripts
with their runs and signatures, the issues log, the Customer's readiness items, and the pilot spares receipts.

Own random stream (``{seed}:readiness``); nothing else is read but the as-of date, so every existing record and
report stays byte-identical. Every day is placed relative to the as-of date, so each generated month holds a
program at the same stage. What is planted uses its own stream (``{seed}:readiness:planted``) and never moves the
rest. No person is named: signatures carry a role.
"""

from __future__ import annotations

import csv
import io
import json
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from .. import readiness as R

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "readiness_data.yaml"
UTC = timezone.utc


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class ReadinessRecordLayer:
    def __init__(self, as_of: str, seed: int, cfg: dict[str, Any] | None = None, program: dict[str, Any] | None = None,
                 plant: bool = True):
        self.cfg = cfg or load_config()
        self.program = program or R.load_config()
        self.rng = random.Random(f"{seed}:readiness")             # independent of every other stream
        self.prng = random.Random(f"{seed}:readiness:planted")    # what is planted never moves the rest
        self.plant = plant
        self.as_of = _ts(as_of)
        self.day0 = self.as_of.date()
        syn = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
        self.offset = timedelta(hours=syn["site_utc_offset_hours"])

    # ---------------------------------------------------------------- time helpers
    def _day(self, d: float) -> date:
        return self.day0 + timedelta(days=round(d))

    def _work(self, day: date) -> datetime:
        """A local working-hour time on ``day``, as UTC, to the minute."""
        lo, hi = self.cfg["work_hours_local"]
        mins = self.rng.randrange(lo * 60, hi * 60)
        return datetime.combine(day, time(0), tzinfo=UTC) + timedelta(minutes=mins) - self.offset

    def _next_day(self, t: datetime, gap: int) -> date:
        return (t + self.offset).date() + timedelta(days=gap)

    # ---------------------------------------------------------------- the record
    def run(self) -> dict[str, Any]:
        c, p = self.cfg, self.program
        levels = list(p["levels"])
        scripts: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        self._issues = issues
        base = {L: self.rng.uniform(*c["level_start_days"][L]) for L in levels}
        # Each system's baseline: the level's window, with a little spread per system.
        for s in p["systems"]:
            prev_pass: datetime | None = None
            prev: tuple[date, date] | None = None         # the level below: (planned, scheduled)
            slipped = s["id"] == c["slipped_system"]
            to = self._day(self.rng.uniform(*c["slipped_to_days"])) if slipped else None
            for L in s["levels"]:
                planned = self._day(base[L] + self.rng.uniform(-4, 4))
                sched = to if slipped and L == s["levels"][0] else planned
                if prev:
                    gap = timedelta(days=p["duration_days"][L] + 1)
                    planned, sched = max(planned, prev[0] + gap), max(sched, prev[1] + gap)
                prev = (planned, sched)
                sc = self._script(s, L, planned, sched, prev_pass, issues)
                scripts.append(sc)
                prev_pass = _ts(sc["passed_at"]) if sc.get("passed_at") else None
        # The hall-wide integrated test.
        # Its schedule stays at the baseline: the forecast, not the record, carries the slip into it.
        l5_plan = self._day(base["L5"])
        sched = l5_plan
        hall = {"id": "HALL-C", "domain": "hall"}
        scripts.append(self._script(hall, "L5", l5_plan, sched, None, issues, after_all=True))
        for sc in scripts:
            sc.pop("passed_at", None)
        committed = self._day(c["first_compute_days"])
        items, receipts = self._items(committed)
        key: dict[str, Any] = {"planted": [], "decoys": {}}
        if self.plant:
            self._plant(scripts, issues, items, receipts, key)
        key["decoys"] = self._decoys(scripts, issues, items, receipts)
        issues.sort(key=lambda i: (i["opened"], i["system"]))
        for n, i in enumerate(issues, 1):
            i["id"] = f"CXI-C-{n:03d}"
        receipts.sort(key=lambda r: (r["received_at"], r["fru"]))
        return {"program": {"as_of": iso(self.as_of), "committed_first_compute": committed.isoformat(),
                            "baseline_issued": (self.day0 + timedelta(days=-95)).isoformat()},
                "scripts": scripts, "issues": issues, "items": items, "receipts": receipts, "answer_key": key}

    def _script(self, s: dict[str, Any], L: str, planned: date, sched: date, prev_pass: datetime | None,
                issues: list[dict[str, Any]], after_all: bool = False) -> dict[str, Any]:
        c, p = self.cfg, self.program
        sid = f"CX-C-{s['id']}-{L}" if not after_all else "CX-C-HALL-L5"
        sc: dict[str, Any] = {"id": sid, "system": s["id"], "level": L, "planned": planned.isoformat(),
                              "scheduled": sched.isoformat(), "runs": [], "signatures": []}
        start = sched
        if prev_pass is not None:
            start = max(start, self._next_day(prev_pass, c["level_gap_days"]))
        domain = s["domain"]
        at = self._work(start)
        if prev_pass is not None and at <= prev_pass:
            return sc
        if not after_all and prev_pass is None and L != s["levels"][0]:
            return sc                                   # the level below has not passed
        while at + timedelta(days=p["duration_days"][L]) < self.as_of:
            fail = self.rng.random() < c["fail_probability"]
            sc["runs"].append({"at": iso(at), "result": "fail" if fail else "pass"})
            if fail:
                retest = at + timedelta(days=self.rng.randint(*c["retest_days"]))
                retest = self._work(self._next_day(retest, 0))
                # The failure is a Category 1, opened at the run and closed before the retest.
                close = at + (retest - at) * self.rng.uniform(0.3, 0.97)
                issues.append(self._issue(s, L, sid, 1, at + timedelta(minutes=self.rng.randint(20, 180)), close))
                if self.rng.random() < 0.5:
                    # A Category 2 raised with the failure, still open when the retest passes: allowed.
                    issues.append(self._issue(s, L, sid, 2, at + timedelta(minutes=self.rng.randint(30, 200)),
                                              retest + timedelta(days=self.rng.randint(*c["issue_close_days"]))))
                at = retest
                continue
            sc["passed_at"] = iso(at)
            t = at
            for role in p["levels"][L]["sign"]:
                t = t + timedelta(hours=self.rng.uniform(*c["signature_hours"]))
                if t >= self.as_of:
                    sc["signatures"].append({"role": role, "signed_at": None})
                else:
                    sc["signatures"].append({"role": role, "signed_at": iso(t)})
            for _ in range(self.rng.randint(*c["issues_per_run"])):
                cat = self.rng.choices(list(c["issue_category_weights"]), weights=list(c["issue_category_weights"].values()))[0]
                opened = at + timedelta(minutes=self.rng.randint(10, 300))
                closed = (None if self.rng.random() < c["issue_open_probability"]
                          else opened + timedelta(days=self.rng.uniform(*c["issue_close_days"])))
                issues.append(self._issue(s, L, sid, int(cat), opened, closed))
            break
        return sc

    def _issue(self, s: dict[str, Any], L: str, sid: str, cat: int, opened: datetime, closed: datetime | None) -> dict[str, Any]:
        if closed is not None and closed >= self.as_of:
            closed = None
        used = {i["text"] for i in self._issues if i["script"] == sid}
        texts = [t for t in self.cfg["issue_texts"][s["domain"]][cat] if t not in used] or self.cfg["issue_texts"][s["domain"]][cat]
        text = self.rng.choice(texts)
        return {"system": s["id"], "level": L, "script": sid, "category": cat, "opened": iso(opened),
                "closed": iso(closed) if closed else "", "text": text}

    def _items(self, committed: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        c, p = self.cfg, self.program
        items: list[dict[str, Any]] = []
        finish: dict[str, datetime | None] = {}
        receipts: list[dict[str, Any]] = []
        for g in p["gates"]:
            for it in g["items"]:
                if it.get("from_cx"):
                    continue
                if it.get("spares"):
                    end = self._work(self._day(self.rng.uniform(*c["spares_item_done_days"])))
                else:
                    plan = committed - timedelta(days=it["due"])
                    end = self._work(plan + timedelta(days=round(self.rng.uniform(*c["item_jitter_days"]))))
                deps = [finish.get(a) for a in it.get("after", [])]
                if any(d is None for d in deps):
                    # A dependency not finished (or computed from the commissioning record): not started.
                    items.append({"item": it["id"], "state": "not started", "started": "", "done": "", "evidence": ""})
                    finish[it["id"]] = None
                    continue
                start = end - timedelta(days=it["days"])
                for d in deps:
                    if d is not None and start <= d:
                        start = d + timedelta(hours=self.rng.uniform(4, 30))
                        end = max(end, start + timedelta(days=it["days"]))
                if end < self.as_of:
                    state, done = "done", iso(end)
                    finish[it["id"]] = end
                elif start < self.as_of:
                    state, done = "in progress", ""
                    finish[it["id"]] = None
                else:
                    state, done = "not started", ""
                    finish[it["id"]] = None
                items.append({"item": it["id"], "state": state, "started": iso(start) if start < self.as_of else "",
                              "done": done, "evidence": f"RDY-C-{it['id']}" if state == "done" else ""})
                if it.get("spares") and state == "done":
                    receipts += self._receipts(end)
        return items, receipts

    def _receipts(self, claim: datetime) -> list[dict[str, Any]]:
        c, out, n = self.cfg, [], 0
        for s in self.program["spares"]:
            k = self.rng.randint(*c["spares_shipments"])
            k = min(k, s["minimum"])
            cuts = sorted(self.rng.sample(range(1, s["minimum"]), k - 1)) if k > 1 else []
            qtys = [b - a for a, b in zip([0] + cuts, cuts + [s["minimum"]])]
            days = sorted((self.rng.uniform(*c["spares_lead_days"]) for _ in qtys), reverse=True)
            for q, d in zip(qtys, days):
                n += 1
                t = self._work(self._next_day(claim - timedelta(days=d), 0))
                if t >= claim:
                    t = claim - timedelta(hours=self.rng.uniform(1, 20))
                out.append({"received_at": iso(t), "fru": s["fru"], "qty": q, "po": f"PO-C-{4100 + n}"})
        return out

    # ---------------------------------------------------------------- planted records
    def _plant(self, scripts, issues, items, receipts, key) -> None:
        r = self.prng
        clean = [s for s in scripts if len(s["runs"]) == 1 and s["runs"][0]["result"] == "pass"]
        # 1. A level passed with a Category 1 open on it.
        s1 = r.choice(clean)
        at = _ts(s1["runs"][0]["at"])
        sys_ = next((x for x in self.program["systems"] if x["id"] == s1["system"]), {"id": s1["system"], "domain": "hall"})
        issue = {"system": s1["system"], "level": s1["level"], "script": s1["id"], "category": 1,
                 "opened": iso(at - timedelta(hours=r.uniform(20, 70))),
                 "closed": iso(at + timedelta(days=r.uniform(1, 6))), "text": r.choice(self.cfg["issue_texts"][sys_["domain"]][1])}
        if _ts(issue["closed"]) >= self.as_of:
            issue["closed"] = ""
        issues.append(issue)
        key["planted"].append({"kind": "passed_open_cat1", "ref": s1["id"]})
        # 2. A signature dated before the run it accepts.
        rest = [s for s in clean if s is not s1 and sum(1 for g in s["signatures"] if g["signed_at"]) >= 2]
        s2 = r.choice(rest)
        g = r.choice([g for g in s2["signatures"][1:] if g["signed_at"]] or s2["signatures"][:1])
        g["signed_at"] = iso(_ts(s2["runs"][0]["at"]) - timedelta(hours=r.uniform(5, 40)))
        key["planted"].append({"kind": "signed_before_run", "ref": s2["id"]})
        # 3. A level passed before the level below it: the upper script's whole record moves earlier.
        by = {(s["system"], s["level"]): s for s in scripts}
        pairs = []
        for s in clean:
            if s in (s1, s2) or s["level"] in ("L1", "L5"):
                continue
            sys_levels = next(x["levels"] for x in self.program["systems"] if x["id"] == s["system"])
            i = sys_levels.index(s["level"])
            if i == 0:
                continue
            below = by[(s["system"], sys_levels[i - 1])]
            nxt = by.get((s["system"], sys_levels[i + 1])) if i + 1 < len(sys_levels) else None
            if below["runs"] and below["runs"][-1]["result"] == "pass" and below not in (s1, s2):
                pairs.append((s, below))
        s3, below = r.choice(pairs)
        delta = _ts(s3["runs"][0]["at"]) - (_ts(below["runs"][-1]["at"]) - timedelta(hours=r.uniform(6, 50)))
        s3["runs"][0]["at"] = iso(_ts(s3["runs"][0]["at"]) - delta)
        for g in s3["signatures"]:
            if g["signed_at"]:
                g["signed_at"] = iso(_ts(g["signed_at"]) - delta)
        for i in issues:
            if i["script"] == s3["id"]:
                i["opened"] = iso(_ts(i["opened"]) - delta)
                if i["closed"]:
                    i["closed"] = iso(_ts(i["closed"]) - delta)
        key["planted"].append({"kind": "out_of_sequence", "ref": s3["id"]})
        # 4. The spares claim made before the last shipment of one class arrived.
        claim = next(i for i in items if i["item"] == next(it["id"] for g in self.program["gates"] for it in g["items"] if it.get("spares")))
        if claim["state"] == "done":
            fru = r.choice(self.program["spares"])["fru"]
            last = max((x for x in receipts if x["fru"] == fru), key=lambda x: x["received_at"])
            t = _ts(claim["done"]) + timedelta(days=r.uniform(2, 9))
            last["received_at"] = iso(min(t, self.as_of - timedelta(hours=3)))
            key["planted"].append({"kind": "spares_short", "ref": claim["item"]})

    def _decoys(self, scripts, issues, items, receipts) -> dict[str, int]:
        """Natural records the checks must leave alone, counted for the self-check."""
        retested = sum(1 for s in scripts if len(s["runs"]) > 1 and s["runs"][-1]["result"] == "pass")
        cat2 = 0
        for s in scripts:
            if s["runs"] and s["runs"][-1]["result"] == "pass":
                at = s["runs"][-1]["at"]
                cat2 += any(i["script"] == s["id"] and i["category"] == 2 and i["opened"] < at and (not i["closed"] or i["closed"] > at)
                            for i in issues)
        same_day = sum(1 for s in scripts if s["runs"] and s["signatures"] and s["signatures"][0]["signed_at"]
                       and s["signatures"][0]["signed_at"][:10] == s["runs"][-1]["at"][:10]
                       and s["signatures"][0]["signed_at"] > s["runs"][-1]["at"])
        return {"retested_then_passed": retested, "cat2_open_at_pass": cat2, "signed_same_day_after_run": same_day}


def write_readiness(out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, int]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    counts: dict[str, int] = {}
    for name, rows in (("cx_scripts.json", out["scripts"]), ("readiness_items.json", out["items"]),
                       ("program.json", out["program"]), ("answer_key.json", out["answer_key"])):
        files[name] = json.dumps(rows, indent=1, sort_keys=True) + "\n"
        counts[name] = len(rows["planted"]) if name == "answer_key.json" else (len(rows) if isinstance(rows, list) else 1)
    for name, rows, cols in (("cx_issues.csv", out["issues"], ["id", "system", "level", "script", "category", "opened", "closed", "text"]),
                             ("spares_receipts.csv", out["receipts"], ["received_at", "fru", "qty", "po"])):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        files[name] = buf.getvalue()
        counts[name] = len(rows)
    files["manifest.json"] = json.dumps({
        "disclaimer": "Synthetic readiness record for Hall C (the 800 VDC pilot) in a portfolio demonstration: the "
                      "commissioning agent's scripts, runs, and signatures by role, the issues log, the Customer's "
                      "readiness items, and the pilot spares receipts. Fictional parties and numbers; no person is named. "
                      "answer_key.json lists the planted records that do not reconcile, for the checks' self-test only; "
                      "the checks never read it.",
        "source": source, "as_of": out["program"]["as_of"], "files": counts}, indent=2, sort_keys=True) + "\n"
    for name, text in files.items():
        (dest / name).write_text(text, encoding="utf-8", newline="\n")
    return counts
