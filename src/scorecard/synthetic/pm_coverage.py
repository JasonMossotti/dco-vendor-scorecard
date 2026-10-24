"""Opening PM register: each device-task line's last completion before the PM records begin (data/pm_coverage/).
Own random stream ("<seed>:pm").

Reads, never writes, the PM program (``config/pm_program.yaml``), the PM records, the forward schedule, and the asset
register (each device's in-service date: nothing was done before it). A line with records gets an opening date one
interval before its first record. A line with no records gets a date the way a careful maintenance planner's book
would leave it: its next due date is booked inside the grace window, or falls after the horizon. The generator keeps
its own rule for that and does not ask the checks (``scorecard.pm_coverage.walk``), so the robustness run tests the
checks against an independent book. Where no such date exists (a quarterly task with no record in the twelve weeks
and nothing booked in time) the latest date is used and the line is listed in the answer key as found. Then one line
per planted kind gets a date that breaks exactly that rule.
"""

from __future__ import annotations

import csv
import io
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from scorecard import pm_coverage as PC

FRAMING = "Synthetic opening PM register for a portfolio demonstration. All records are fictional."
COLS = ["line", "unit", "task", "last_done", "source"]


class OpeningRegister:
    def __init__(self, seed: int, root: Path = PC.ROOT, cfg: dict[str, Any] | None = None,
                 schedule: list[dict[str, Any]] | None = None):
        self.cfg = cfg or PC.config()
        self.rng = random.Random(f"{seed}:pm")
        self.lines = [ln for ln in PC.program(self.cfg, PC.devices(root / "docs" / "site" / "devices.json")) if ln["in_schedule"]]
        recs = PC.records(self.cfg, root)
        self.first = {}
        for r in recs:
            self.first.setdefault((r["task"], r["unit"]), r["done"])
        books = PC.bookings(self.cfg, schedule)
        self.b0 = {}
        for b in books:
            self.b0.setdefault((b["task"], b["unit"]), PC.d(b["day"]))
        assets = PC.asset_units(root / "data" / "assets" / "register_opening.csv")
        self.site_start = min(PC.d(a["since"]) for a in assets.values())
        self.svc = {u: PC.d(a["since"]) for u, a in assets.items()}
        self.as_of, self.horizon = PC.d(self.cfg["as_of"]), PC.d(self.cfg["horizon"])

    # ------------------------------------------------------------ the planner's rule
    def _limit(self, ln: dict[str, Any], last: date) -> date:
        return PC.next_due(last, ln["interval"], self.cfg) + timedelta(days=ln["grace"])

    def _kind(self, ln: dict[str, Any], last: date) -> str:
        """clean, overdue, booked_late, or not_booked for an opening date on a line with no records."""
        lim, b0 = self._limit(ln, last), self.b0.get((ln["task"], ln["unit"]))
        if lim < self.as_of:
            return "overdue"
        if lim > self.horizon or (b0 is not None and b0 <= lim):
            return "clean"
        return "booked_late" if b0 is not None else "not_booked"

    def _range(self, ln: dict[str, Any]) -> list[date]:
        lo = self.svc.get(ln["unit"], self.site_start)
        hi = PC.d(PC.window_start(ln, self.cfg)) - timedelta(days=1)
        return [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]

    def run(self) -> dict[str, Any]:
        rows, free, as_found = {}, [], []
        for ln in self.lines:
            first = self.first.get((ln["task"], ln["unit"]))
            days = self._range(ln)
            if first:
                step = 30 if ln["interval"] == "monthly" else self.cfg["interval_days"][ln["interval"]]
                want = PC.d(first) - timedelta(days=step + self.rng.randint(-5, 5))
                last = min(max(want, days[0]), days[-1])
            else:
                ok = [x for x in days if self._kind(ln, x) == "clean"]
                if ok:
                    last = self.rng.choice(ok)
                    free.append(ln)
                else:
                    last = days[-1]
                    as_found.append({"line": ln["key"], "kind": self._kind(ln, last)})
            rows[ln["key"]] = last
        planted = []
        for kind in ("overdue", "booked_late", "not_booked"):
            for _ in range(self.cfg["planted"][kind]):
                cands = [(ln, [x for x in self._range(ln) if self._kind(ln, x) == kind]) for ln in free
                         if ln["key"] not in {p["line"] for p in planted}]
                cands = [c for c in cands if c[1]]
                if not cands:
                    continue
                ln, days = self.rng.choice(cands)
                rows[ln["key"]] = self.rng.choice(days)
                planted.append({"line": ln["key"], "kind": kind})
        opening = []
        for ln in self.lines:
            last = rows[ln["key"]]
            src = "Acceptance test at commissioning" if last == self.svc.get(ln["unit"], self.site_start) else "Maintenance system export"
            opening.append({"line": ln["key"], "unit": ln["unit"], "task": ln["task"], "last_done": last.isoformat(), "source": src})
        return {"opening": opening, "key": {"planted": planted, "as_found": as_found}}


def write_opening(out: dict[str, Any], dest: str | Path, seed: int) -> dict[str, Any]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, lineterminator="\n")
    w.writeheader()
    w.writerows(out["opening"])
    (dest / "opening.csv").write_text(buf.getvalue(), encoding="utf-8", newline="\n")
    (dest / "answer_key.json").write_text(json.dumps(out["key"], indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    man = {"disclaimer": FRAMING, "seed": seed, "files": {"opening.csv": len(out["opening"])},
           "note": "Own random stream; answer_key.json is the answer key and the checks never read it. Reads the PM records, "
                   "data/calendar/schedule.json, and data/assets/register_opening.csv."}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
