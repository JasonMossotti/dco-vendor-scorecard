"""PM coverage: every Landlord device that needs preventive maintenance, when it was last done, when it falls due, and
whether the next one is booked (page /ops/#pm; report reports/pm_coverage.md).

The program (``config/pm_program.yaml``) expands the Landlord SLA's maintenance schedule to every device it covers in
Halls A and B and the site-wide plant (Hall C joins at handover). Each device-task line takes its last completion
from the PM records (the Hall A history for the Hall A CDU filters, the July, August, and September Measurement
Periods for everything else) or, before the records begin, from the opening register (``data/pm_coverage/``, own
random stream). Its bookings come from the forward schedule (``data/calendar/schedule.json``). Walking forward from
the last completion, each due date must have a booking on or before its grace limit until the horizon:

1. **Overdue.** The grace limit is before the as-of day and nothing is recorded.
2. **Booked late.** The next booking falls after the grace limit.
3. **Due with nothing booked.** The grace limit falls before the horizon and nothing is booked.
4. **No baseline.** The device needs PM (a line the coverage clause added to the schedule) and has no record at all.

A finding (PMC-#) means the PM records and the bookings do not reconcile with the schedule; it starts the coverage
procedure in the Landlord SLA (maintenance.coverage), not a judgment of anyone. It changes no service level: OT-CSL-06
counts the tasks the Landlord opened, and these lines are shown beside it.
"""

from __future__ import annotations

import calendar
import csv
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from scorecard.change_calendar import local_day, parse

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "pm_program.yaml"
LAYER = ROOT / "data" / "pm_coverage"
SCHEDULE = ROOT / "data" / "calendar" / "schedule.json"
DEVICES = ROOT / "docs" / "site" / "devices.json"
ASSETS = ROOT / "data" / "assets" / "register_opening.csv"
SLA = ROOT / "sla" / "ot_partner.yaml"
ORDER = ["overdue", "booked_late", "not_booked", "no_baseline"]
STATUS = {"current": "Current", "booked": "Booked", "overdue": "Overdue", "booked_late": "Booked late",
          "not_booked": "Due, nothing booked", "no_baseline": "No baseline", "not_required": "Not required"}
ACTIONS = {"overdue": "The Landlord books it within 2 business days and the Customer's account lead is told; the device shows PM "
                      "overdue until the work is recorded, or a Customer-signed deferral sets a new date.",
           "booked_late": "The Landlord moves the booking inside the grace window through the change board, or asks for a "
                          "Customer-signed deferral with the reason, the risk, and a new date.",
           "not_booked": "The Customer sends the Landlord a booking request; the Landlord books it inside the due window "
                         "within 5 business days.",
           "no_baseline": "The Landlord books a baseline PM for each device within 30 days of the schedule change and records it."}
AGREEMENTS = [
    ("records", "Every PM record read names a device-task line in the program"),
    ("bookings", "Every PM booking in the forward schedule names a device-task line in the program"),
    ("assets", "Every device in the program of a kind the asset register holds is in it, installed and maintained by the Landlord"),
]


def config(path: Path = CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def d(s: str) -> date:
    return date.fromisoformat(s[:10])


# ---------------------------------------------------------------- due dates
def next_due(last: date, interval: str, cfg: dict[str, Any]) -> date:
    """The due date after a completion: monthly tasks by the end of the next calendar month, the rest by days."""
    if interval == "monthly":
        y, m = (last.year + 1, 1) if last.month == 12 else (last.year, last.month + 1)
        return date(y, m, calendar.monthrange(y, m)[1])
    return last + timedelta(days=cfg["interval_days"][interval])


def grace(interval: str, cfg: dict[str, Any]) -> int:
    return cfg["grace_days"][interval]


def walk(last: date, interval: str, bookings: list[date], cfg: dict[str, Any]) -> dict[str, Any]:
    """Each due date from ``last`` on must be booked on or before its grace limit until the horizon.

    Returns the status (current, booked, overdue, booked_late, not_booked), the first due date and its limit, the
    bookings used, and for a finding the due date, the limit, and the booking (if any) that the finding is about."""
    as_of, horizon = d(cfg["as_of"]), d(cfg["horizon"])
    t, used = last, []
    first = None
    while True:
        due = next_due(t, interval, cfg)
        limit = due + timedelta(days=grace(interval, cfg))
        first = first or (due, limit)
        if limit < as_of:
            nb = next((b for b in bookings if b > t), None)
            return {"status": "overdue", "due": due, "limit": limit, "booking": nb, "used": used, "first": first}
        nb = next((b for b in bookings if b > t), None)
        if nb is not None and nb <= limit:
            used.append(nb)
            t = nb
            continue
        if limit > horizon:
            return {"status": "booked" if used else "current", "due": due, "limit": limit, "booking": None, "used": used, "first": first}
        return {"status": "booked_late" if nb else "not_booked", "due": due, "limit": limit, "booking": nb, "used": used, "first": first}


# ---------------------------------------------------------------- the program
def devices(path: Path = DEVICES) -> dict[str, dict[str, Any]]:
    return _json(path)["devices"]


def program(cfg: dict[str, Any] | None = None, devs: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Every device-task line: Halls A and B and the site-wide plant (Hall C joins at handover)."""
    cfg = cfg or config()
    devs = devs if devs is not None else devices()
    lines = []
    for t in cfg["tasks"]:
        if t.get("units"):
            units = [(u, (devs.get(u, {}).get("hall") or ("Hall " + u[5] if u.startswith("Hall ") else ""))) for u in t["units"]]
        else:
            units = [(n, v.get("hall") or "") for n, v in devs.items() if v.get("kind") in t["kinds"]]
        for u, hall in sorted(units, key=lambda x: _natural(x[0])):
            if hall == "Hall C":
                continue
            lines.append({"key": f"{t['id']}|{u}", "task_id": t["id"], "task": t["task"], "system": t["system"], "unit": u,
                          "hall": hall or "Site-wide", "interval": t["interval"], "grace": grace(t["interval"], cfg),
                          "basis": t["basis"], "in_schedule": t.get("in_schedule", True), "only_if": t.get("only_if"),
                          "device": u in devs})
    return lines


def _natural(s: str) -> list[Any]:
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]


def _hall_a_cdu(r: dict[str, str]) -> bool:
    return r["system"] == "CDUs" and r["asset"].startswith("CDU-A")


def records(cfg: dict[str, Any] | None = None, root: Path = ROOT) -> list[dict[str, Any]]:
    """The PM records read, oldest first, with the source each came from and the first day that source covers."""
    cfg = cfg or config()
    out = []
    for s in cfg["records"]:
        for r in _csv(root / s["path"]):
            if s.get("only") == "hall_a_cdu" and not _hall_a_cdu(r):
                continue
            if s.get("skip") == "hall_a_cdu" and _hall_a_cdu(r):
                continue
            out.append({"id": r["task_id"], "unit": r["asset"], "task": r["task"], "system": r["system"],
                        "done": local_day(parse(r["completed_at"])), "result": r.get("result", ""), "evidence": r.get("evidence", ""),
                        "source": s["path"], "start": s["start"]})
    return sorted(out, key=lambda x: (x["done"], x["id"]))


def window_start(line: dict[str, Any], cfg: dict[str, Any]) -> str:
    """The first day the records cover for a line (before it, the opening register holds the last completion)."""
    hall_a_cdu = line["task_id"] == "cdu_filter" and line["unit"].startswith("CDU-A")
    starts = [s["start"] for s in cfg["records"]
              if not (s.get("only") == "hall_a_cdu" and not hall_a_cdu) and not (s.get("skip") == "hall_a_cdu" and hall_a_cdu)]
    return min(starts)


def bookings(cfg: dict[str, Any] | None = None, schedule: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The forward schedule's PM bookings: a title "<task>: <unit>" for a task in the program."""
    cfg = cfg or config()
    schedule = schedule if schedule is not None else _json(SCHEDULE)
    tasks = {t["task"] for t in cfg["tasks"]}
    out = []
    for j in schedule:
        task, sep, unit = j["title"].partition(": ")
        if sep and task in tasks:
            out.append({"id": j["id"], "task": task, "unit": unit, "day": local_day(parse(j["window_start"])), "start": j["window_start"]})
    return sorted(out, key=lambda x: (x["day"], x["id"]))


def exercise_loads(recs: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Each generator's recorded load in its monthly exercises (percent of nameplate)."""
    out: dict[str, list[int]] = {}
    for r in recs:
        m = re.search(r"(\d+)% load", r["result"]) if r["task"] == "Monthly loaded exercise" else None
        if m:
            out.setdefault(r["unit"], []).append(int(m.group(1)))
    return out


def asset_units(path: Path = ASSETS) -> dict[str, dict[str, str]]:
    return {r["location"]: r for r in _csv(path) if r["class"] == "Facility equipment"}


# ---------------------------------------------------------------- the register and the checks
def analyse(cfg: dict[str, Any] | None = None, root: Path = ROOT, layer: Path = LAYER,
            schedule: list[dict[str, Any]] | None = None, opening: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cfg = cfg or config()
    lines = program(cfg, devices(root / "docs" / "site" / "devices.json"))
    by_key = {ln["key"]: ln for ln in lines}
    by_task_unit = {(ln["task"], ln["unit"]): ln for ln in lines}
    recs = records(cfg, root)
    books = bookings(cfg, schedule)
    opening = opening if opening is not None else _csv(layer / "opening.csv")
    open_by = {o["line"]: o for o in opening}
    loads = exercise_loads(recs)
    checks = {k: {"key": k, "title": t, "checked": 0, "misses": [], "explained": 0} for k, t in AGREEMENTS}

    for r in recs:
        checks["records"]["checked"] += 1
        ln = by_task_unit.get((r["task"], r["unit"]))
        if ln:
            ln.setdefault("records", []).append(r)
        else:
            checks["records"]["misses"].append(f"{r['id']} {r['task']}: {r['unit']}")
    for b in books:
        checks["bookings"]["checked"] += 1
        ln = by_task_unit.get((b["task"], b["unit"]))
        if ln:
            ln.setdefault("bookings", []).append(b)
        else:
            checks["bookings"]["misses"].append(f"{b['id']} {b['task']}: {b['unit']}")
    assets = asset_units(root / "data" / "assets" / "register_opening.csv")
    scope = set(yaml.safe_load((root / "config" / "assets.yaml").read_text(encoding="utf-8"))["facility_kinds"])
    devs = devices(root / "docs" / "site" / "devices.json")
    in_scope = {ln["unit"] for ln in lines if ln["device"] and devs[ln["unit"]]["kind"] in scope}
    checks["assets"]["outside"] = sorted({ln["unit"] for ln in lines if ln["device"]} - in_scope, key=_natural)
    for u in sorted(in_scope, key=_natural):
        checks["assets"]["checked"] += 1
        a = assets.get(u)
        if not a or a["status"] != "installed" or a["maintainer"] != "Landlord":
            checks["assets"]["misses"].append(u)

    found = []
    for ln in lines:
        ln.setdefault("records", [])
        ln.setdefault("bookings", [])
        ln["window_start"] = window_start(ln, cfg)
        op = open_by.get(ln["key"])
        ln["opening"] = {"done": op["last_done"], "source": op["source"]} if op else None
        last = max([r["done"] for r in ln["records"]] + ([op["last_done"]] if op else []), default=None)
        ln["last"] = last
        ln.update(due=None, limit=None, booked=None, finding=None)
        if ln["only_if"] == "monthly_below_30":
            low = {u: v for u, v in loads.items() if u == ln["unit"] and min(v) < 30}
            if not low:
                ln["status"] = "not_required"
                ln["note"] = f"Not required: every monthly exercise recorded reached 30% ({min(loads.get(ln['unit'], [0]))}% lowest)."
                continue
        if last is None:
            ln["status"] = "no_baseline"
            continue
        w = walk(d(last), ln["interval"], [d(b["day"]) for b in ln["bookings"]], cfg)
        ln["status"] = w["status"]
        ln["due"], ln["limit"] = w["first"][0].isoformat(), w["first"][1].isoformat()
        ln["booked"] = [x.isoformat() for x in w["used"]]
        if w["status"] in ORDER:
            bk = next((b for b in ln["bookings"] if b["day"] == w["booking"].isoformat()), None) if w["booking"] else None
            found.append({"kind": w["status"], "lines": [ln["key"]], "units": [ln["unit"]], "task": ln["task"], "system": ln["system"],
                          "due": w["due"].isoformat(), "limit": w["limit"].isoformat(), "last": last,
                          "booking": bk["id"] if bk else None, "booking_day": bk["day"] if bk else None, "hall": ln["hall"]})
    for t in cfg["tasks"]:
        nb = [ln for ln in lines if ln["task_id"] == t["id"] and ln["status"] == "no_baseline"]
        if nb:
            found.append({"kind": "no_baseline", "lines": [x["key"] for x in nb], "units": [x["unit"] for x in nb], "task": t["task"],
                          "system": t["system"], "due": None, "limit": None, "last": None, "booking": None, "booking_day": None,
                          "hall": ", ".join(sorted({x["hall"] for x in nb}))})

    found.sort(key=lambda f: (ORDER.index(f["kind"]), f["limit"] or "9999", _natural(f["units"][0])))
    for i, f in enumerate(found, 1):
        f["id"] = f"PMC-{i}"
        f["title"] = cfg["kinds"][f["kind"]]
        f["text"] = finding_text(f, cfg)
        f["action"] = ACTIONS[f["kind"]]
        f["owner"] = "Landlord"
        for k in f["lines"]:
            by_key[k]["finding"] = f["id"]
    return {"lines": lines, "findings": found, "agreements": list(checks.values()), "records": recs, "bookings": books}


def _md(s: str) -> str:
    """Oct 31, with the year when it is not 2026 (Feb 21, 2029)."""
    x = d(s)
    return f"{calendar.month_abbr[x.month]} {x.day}" + (f", {x.year}" if x.year != 2026 else "")


def finding_text(f: dict[str, Any], cfg: dict[str, Any]) -> str:
    u = f["units"][0]
    last = f"last done {_md(f['last'])}" if f["last"] else ""
    if f["kind"] == "overdue":
        b = f" The next booking is {f['booking']} on {_md(f['booking_day'])}." if f["booking"] else " Nothing is booked."
        return f"{f['task']} on {u}: {last}, due {_md(f['due'])}, grace ended {_md(f['limit'])} before the as-of day {_md(cfg['as_of'])}.{b}"
    if f["kind"] == "booked_late":
        return f"{f['task']} on {u}: {last}, due {_md(f['due'])}, grace ends {_md(f['limit'])}; booked {f['booking']} on {_md(f['booking_day'])}."
    if f["kind"] == "not_booked":
        return f"{f['task']} on {u}: {last}, due {_md(f['due'])}, grace ends {_md(f['limit'])}; nothing booked before the horizon {_md(cfg['horizon'])}."
    return (f"{f['task']} ({f['system']}): {len(f['units'])} device{'s' if len(f['units']) != 1 else ''} with no PM record "
            f"({', '.join(f['units'])}); the coverage clause adds the task to the schedule.")


def score(r: dict[str, Any], key: dict[str, Any]) -> dict[str, int]:
    """Planted and as-found lines against the findings; a finding on any other line the opening register placed is a
    false positive. Lines with records and lines with no baseline are the records' own and are not scored."""
    found = {k: f["kind"] for f in r["findings"] for k in f["lines"]}
    rec = {ln["key"] for ln in r["lines"] if ln["records"] or ln["status"] in ("no_baseline", "not_required")}
    exp = {p["line"]: p["kind"] for p in key["planted"] + key["as_found"]}
    hit = sum(1 for p in key["planted"] if found.get(p["line"]) == p["kind"])
    af = sum(1 for p in key["as_found"] if found.get(p["line"]) == p["kind"])
    fp = sum(1 for k in found if k not in rec and k not in exp)
    wrong = sum(1 for k, v in exp.items() if k in found and found[k] != v)
    return {"planted": len(key["planted"]), "found": hit, "as_found": len(key["as_found"]), "as_found_hit": af,
            "false_positives": fp + wrong}


# ---------------------------------------------------------------- the page
def procedure(path: Path = SLA) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["maintenance"]["coverage"]


def page_data(r: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the PM coverage view, the device cards, and the report show."""
    cfg = cfg or config()
    r = r or analyse(cfg)
    keep = ("key", "task_id", "task", "system", "unit", "hall", "interval", "grace", "basis", "in_schedule", "device", "status",
            "last", "due", "limit", "booked", "finding", "window_start")
    lines = []
    for ln in r["lines"]:
        x = {k: ln.get(k) for k in keep}
        x["records"] = [{k: v for k, v in rec.items() if k in ("id", "done", "result", "evidence", "source")} for rec in ln["records"]]
        x["bookings"] = [{"id": b["id"], "day": b["day"]} for b in ln["bookings"]]
        x["opening"] = ln["opening"]
        x["note"] = ln.get("note", "")
        lines.append(x)
    count = {k: sum(1 for x in lines if x["status"] == k) for k in STATUS}
    tasks = []
    for t in cfg["tasks"]:
        ls = [x for x in lines if x["task_id"] == t["id"]]
        tasks.append({"id": t["id"], "task": t["task"], "system": t["system"], "interval": t["interval"], "lines": len(ls),
                      "in_schedule": t.get("in_schedule", True), "basis": t["basis"],
                      "status": {k: sum(1 for x in ls if x["status"] == k) for k in STATUS if any(x["status"] == k for x in ls)}})
    finds = [{k: f[k] for k in ("id", "kind", "title", "lines", "units", "task", "system", "due", "limit", "last", "booking",
                                "booking_day", "hall", "text", "action", "owner")} for f in r["findings"]]
    return {"as_of": cfg["as_of"], "horizon": cfg["horizon"], "lines": lines, "tasks": tasks, "findings": finds,
            "count": count, "status_names": STATUS, "kinds": cfg["kinds"], "agreements": r["agreements"],
            "devices": len({x["unit"] for x in lines}), "records": len(r["records"]), "bookings": len(r["bookings"]),
            "sources": [s["path"] for s in cfg["records"]], "procedure": procedure(), "grace_days": cfg["grace_days"],
            "interval_days": cfg["interval_days"]}


def device_notes(f: dict[str, Any] | None = None) -> dict[str, list[list[str]]]:
    """A line per PM task for each device card on the Devices tab: [sentence, register line key]."""
    f = f or page_data()
    out: dict[str, list[list[str]]] = {}
    for x in f["lines"]:
        if x["status"] == "not_required":
            s = f"{x['task']}: not required"
        elif x["status"] == "no_baseline":
            s = f"{x['task']}: no record, baseline needed ({x['finding']})"
        else:
            s = f"{x['task']}: last {_md(x['last'])}, due {_md(x['due'])}"
            late = next((b for b in x["bookings"] if x["status"] in ("booked_late", "overdue")), None)
            if x["booked"] or late:
                s += f", booked {_md(x['booked'][0] if x['booked'] else late['day'])}"
            s += f". {STATUS[x['status']]}" + (f" ({x['finding']})" if x["finding"] else "")
        out.setdefault(x["unit"], []).append([s, x["key"]])
    return out
