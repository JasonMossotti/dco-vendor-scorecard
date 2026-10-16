"""Fire protection impairments: the Landlord's impairment log reconciled with the fire panel's history and the
Customer's record of notices (data/fire/), under Interface Agreement section 12 (FPI-1 to FPI-6).

The panel is the record of when protection was out (FPI-5). Its history pairs each signal's Active with its Cleared;
a disabled point, or a supervisory signal on a suppression device, is protection out of service. A trouble (a detector
fault, a ground fault) is not: adjacent detection keeps coverage.

Agreements (each case is one record checked):

1. vesda: every VESDA event in the month's facility data reaches the panel within 2 minutes, as the matching signal.
2. maintenance: every fire protection maintenance record has its impairment on the log, with the same MOP.
3. notice: every impairment was notified in time: a planned one at least 24 hours before it began (FPI-1), an unplanned
   one within 15 minutes (FPI-2).
4. restored: the logged restoration matches the panel's within 15 minutes (FPI-5).
5. restore_notice: a restoration notice within 30 minutes of the logged restoration (FPI-5).
6. window: a planned impairment, as the panel shows it, ends inside its window or inside an extension notified before
   the window closed (FPI-4).
7. watch: an impairment that lasted more than 4 hours, as the panel shows it, had a fire watch from no later than the
   fourth hour to restoration (FPI-3).
8. logged: every span of protection out of service longer than 30 minutes falls inside a logged impairment on that
   device (FPI-6).

Findings (records that do not reconcile; numbered FLS-n):

* restored_late: an impairment logged restored while the panel shows its point out of service for longer, past its
  window with no extension.
* unlogged: protection out of service for more than 30 minutes with no impairment on the log.
Every disagreement must be one of these; anything else becomes a finding of kind records_disagree, which no planted
case produces.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scorecard.synthetic.fire import parse, iso
from scorecard.telemetry import Check

# Interface Agreement section 12 (tests/test_fire.py checks each number against the agreement's text)
NOTICE_LEAD_H = 24          # FPI-1
UNPLANNED_NOTICE_MIN = 15   # FPI-2
WATCH_AFTER_H = 4           # FPI-3
RECORD_MIN = 15             # FPI-5: the log records the panel's restoration within 15 minutes
RESTORE_NOTICE_MIN = 30     # FPI-5
LOG_AFTER_MIN = 30          # FPI-6
PANEL_LAG_S = 120           # a VESDA event reaches the panel within 2 minutes

AGREEMENTS = [
    ("vesda", "Every VESDA event reaches the fire panel within 2 minutes"),
    ("maintenance", "Every fire protection maintenance record has its impairment on the log, with the same MOP"),
    ("notice", "Every impairment notified in time (24 hours ahead when planned, 15 minutes when not)"),
    ("restored", "Every logged restoration matches the panel within 15 minutes"),
    ("restore_notice", "Every restoration notified within 30 minutes of the logged time"),
    ("window", "Every planned impairment ends inside its window or a timely extension"),
    ("watch", "Every impairment over 4 hours has a fire watch from the fourth hour to restoration"),
    ("logged", "Every span of protection out of service over 30 minutes is on the impairment log"),
]
CONTRACT = {
    "restored_late": "Interface Agreement FPI-4 and FPI-5 (restore within the window or extend with notice; restoration is what the panel shows)",
    "unlogged": "Interface Agreement FPI-6 (log every impairment), FPI-1 and FPI-2 (notice)",
    "records_disagree": "Interface Agreement section 12",
}
ORDER = ["restored_late", "unlogged", "records_disagree"]
# What a VESDA event looks like on the panel: (signal, state)
VESDA_SIGNAL = {"Isolate": ("Disable", "Active"), "Fault": ("Trouble", "Active")}


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def dur(a: datetime, b: datetime) -> str:
    m = round((b - a).total_seconds() / 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def hm(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M UTC")


@dataclass
class FireData:
    dir: Path
    manifest: dict
    panel: list[dict]
    imps: list[dict]
    notices: list[dict]
    vesda: list[dict]
    pm: list[dict]

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def end(self) -> datetime:
        return parse(self.manifest["window"]["end"])


def load(fire_dir: str | Path, sample_dir: str | Path) -> FireData:
    f, s = Path(fire_dir), Path(sample_dir)
    return FireData(dir=f, manifest=json.loads((f / "manifest.json").read_text(encoding="utf-8")),
                    panel=_jsonl(f / "facp_history.jsonl"), imps=_csv(f / "impairments.csv"), notices=_csv(f / "impairment_notices.csv"),
                    vesda=_jsonl(s / "facility" / "vesda_events.jsonl"),
                    pm=[r for r in _csv(s / "landlord" / "pm_records.csv") if r["system"] == "Fire protection"])


def spans(panel: list[dict], month_end: datetime) -> list[dict]:
    """Each signal's Active paired with its Cleared, per device and point. A signal still active at month end runs to it."""
    open_: dict[tuple, dict] = {}
    out = []
    for e in sorted(panel, key=lambda e: e["timestamp"]):
        k = (e["device"], e["point"], e["signal"])
        if e["state"] == "Active":
            open_[k] = e
        elif e["state"] == "Cleared" and k in open_:
            a = open_.pop(k)
            out.append({"device": e["device"], "point": e["point"], "signal": e["signal"], "start": parse(a["timestamp"]),
                        "end": parse(e["timestamp"]), "text": a["text"], "clear_text": e["text"]})
    for k, a in open_.items():
        out.append({"device": k[0], "point": k[1], "signal": k[2], "start": parse(a["timestamp"]), "end": month_end, "text": a["text"],
                    "clear_text": "still active at month end"})
    return sorted(out, key=lambda s: (s["start"], s["device"]))


def out_of_service(s: dict) -> bool:
    """Protection out of service: a disabled point, or a supervisory signal on a suppression device."""
    return s["signal"] == "Disable" or (s["signal"] == "Supervisory" and s["device"].startswith(("PAZ-", "CAS-")))


def reconcile(t: FireData) -> dict[str, Any]:
    cases: dict[str, int] = {}
    bad: dict[str, list[dict]] = {}
    sp = spans(t.panel, t.end)
    oos = [s for s in sp if out_of_service(s)]
    notes: dict[str, list[dict]] = {}
    for n in t.notices:
        notes.setdefault(n["imp_id"], []).append(n)

    def case(name: str, ok: bool, **b: Any) -> None:
        cases[name] = cases.get(name, 0) + 1
        if not ok:
            bad.setdefault(name, []).append(b)

    # ---- 1. every VESDA event on the panel
    for e in t.vesda:
        at = parse(e["timestamp"])
        if e["event"] in VESDA_SIGNAL:
            want = [VESDA_SIGNAL[e["event"]]]
        elif e["event"] == "Normal":
            want = [("Disable", "Cleared"), ("Trouble", "Cleared")]
        else:
            want = [("Alarm", "Test"), ("Alarm", "Active")]
        hit = any(p["device"] == e["detector"] and (p["signal"], p["state"]) in want
                  and timedelta(0) <= parse(p["timestamp"]) - at <= timedelta(seconds=PANEL_LAG_S) for p in t.panel)
        case("vesda", hit, detector=e["detector"], event=e["event"], at=at)

    # ---- each logged impairment
    imps = []
    for r in t.imps:
        devs = r["devices"].split(";")
        a, rest = parse(r["start"]), parse(r["restored_at"])
        mine = [s for s in oos if s["device"] in devs and a - timedelta(minutes=RECORD_MIN) <= s["start"] <= rest + timedelta(minutes=RECORD_MIN)]
        panel_end = max((s["end"] for s in mine), default=None)
        n = notes.get(r["imp_id"], [])
        x = {"row": r, "devices": devs, "start": a, "restored": rest, "spans": mine, "panel_end": panel_end, "notices": n,
             "window_end": parse(r["window_end"]) if r["window_end"] else None}
        imps.append(x)
        # 3. notice
        st = [parse(m["received_at"]) for m in n if m["kind"] == "start"]
        if r["type"] == "planned":
            case("notice", any(a - q >= timedelta(hours=NOTICE_LEAD_H) for q in st), imp=r["imp_id"])
        else:
            case("notice", any(timedelta(0) <= q - a <= timedelta(minutes=UNPLANNED_NOTICE_MIN) for q in st), imp=r["imp_id"])
        # 4. restored
        case("restored", panel_end is not None and abs((panel_end - rest).total_seconds()) <= RECORD_MIN * 60,
             imp=r["imp_id"], logged=rest, panel=panel_end)
        # 5. restoration notice
        rn = [parse(m["received_at"]) for m in n if m["kind"] == "restored"]
        case("restore_notice", any(timedelta(0) <= q - rest <= timedelta(minutes=RESTORE_NOTICE_MIN) for q in rn), imp=r["imp_id"])
        true_end = max(rest, panel_end or rest)
        # 6. window
        if r["type"] == "planned":
            ext = [parse(m["new_end"]) for m in n if m["kind"] == "extension" and m["new_end"] and parse(m["received_at"]) < x["window_end"]]
            limit = max([x["window_end"]] + ext)
            case("window", true_end <= limit + timedelta(minutes=RECORD_MIN), imp=r["imp_id"], end=true_end, limit=limit)
        # 7. fire watch
        if true_end - a > timedelta(hours=WATCH_AFTER_H):
            fs, fe = (parse(r["fire_watch_start"]) if r["fire_watch_start"] else None), (parse(r["fire_watch_end"]) if r["fire_watch_end"] else None)
            ok = fs is not None and fe is not None and fs <= a + timedelta(hours=WATCH_AFTER_H) and fe >= true_end - timedelta(minutes=RECORD_MIN)
            case("watch", ok, imp=r["imp_id"], end=true_end)

    # ---- 2. maintenance records
    for p in t.pm:
        hit = any(p["asset"] in x["devices"] and x["row"]["mop_ref"] == p["mop_ref"] and x["row"]["pm_ref"] == p["task_id"] for x in imps)
        case("maintenance", hit, pm=p["task_id"], asset=p["asset"])

    # ---- 8. every span out of service over 30 minutes is logged
    for s in oos:
        if s["end"] - s["start"] <= timedelta(minutes=LOG_AFTER_MIN):
            continue
        hit = any(s in x["spans"] for x in imps)
        case("logged", hit, span=s)
    return {"cases": cases, "bad": bad, "imps": imps, "spans": sp, "oos": oos}


def analyse(t: FireData) -> dict[str, Any]:
    rc = reconcile(t)
    findings: list[dict] = []
    explained: dict[str, int] = {}

    def explain(name: str, n: int = 1) -> None:
        explained[name] = explained.get(name, 0) + n

    by_imp = {x["row"]["imp_id"]: x for x in rc["imps"]}
    late = {b["imp"] for b in rc["bad"].get("restored", []) if b["panel"] and b["panel"] > b["logged"]}
    for imp in sorted(late):
        x = by_imp[imp]
        r, pe = x["row"], x["panel_end"]
        win = [b for b in rc["bad"].get("window", []) if b["imp"] == imp]
        if not win:                     # restored late but inside the window: not this kind
            continue
        explain("restored")
        explain("window")
        watch = [b for b in rc["bad"].get("watch", []) if b["imp"] == imp]
        explain("watch", len(watch))
        s = max(x["spans"], key=lambda s: s["end"])
        n = x["notices"]
        ext = [m for m in n if m["kind"] == "extension"]
        lines = [f"Impairment log {imp}: {r['system'].lower()}, {', '.join(x['devices'])}, {r['reason'].lower()}; start {hm(x['start'])}, "
                 f"window to {hm(x['window_end'])}, restored {hm(x['restored'])}" + (f" (logged by {r['engineer']})" if r["engineer"] else "")]
        lines += [f"Notice {m['notice_id']}, received {hm(parse(m['received_at']))}: {m['text']}" for m in n]
        lines.append(f"Fire panel {s['device']} {s['point']}: {s['text'].lower()} at {hm(s['start'])}; {s['clear_text'].lower()} at {hm(s['end'])}")
        lines.append("Extension notices: " + (", ".join(m["notice_id"] for m in ext) if ext else "none"))
        lines.append("Fire watch: " + (f"{r['fire_watch_start']} to {r['fire_watch_end']}" if r["fire_watch_start"] else "none logged"))
        findings.append({
            "kind": "restored_late", "title": f"{imp} logged restored at {x['restored']:%H:%M}; the panel shows {s['device']} out until {pe:%H:%M} the next day"
            if pe.date() > x["restored"].date() else f"{imp} logged restored at {x['restored']:%H:%M}; the panel shows {s['device']} out until {pe:%H:%M}",
            "summary": f"The Landlord's impairment log records {imp} ({r['reason'].lower()} on {', '.join(x['devices'])}) restored at "
                       f"{hm(x['restored'])}, inside its window, and a restoration notice reached the Customer. The fire panel shows "
                       f"{s['device']} with its {s['text'].lower()} until {hm(pe)}: {dur(x['window_end'], pe)} after the window closed, "
                       "with no extension notice" + (" and no fire watch, although it was out for more than 4 hours" if watch else "")
                       + ". For those hours the zone was impaired on no record. The panel is the record of restoration (FPI-5); the "
                         "log and the panel do not reconcile.",
            "owner": "Landlord", "severity": "S2", "contract": CONTRACT["restored_late"] + ("; FPI-3 (fire watch)" if watch else ""),
            "sla_refs": ["FPI-4", "FPI-5"] + (["FPI-3"] if watch else []),
            "lines": lines, "refs": [imp] + [m["notice_id"] for m in n], "devices": x["devices"], "imp": imp,
            "from": iso(x["window_end"]), "to": iso(pe)})
    for b in rc["bad"].get("logged", []):
        s = b["span"]
        explain("logged")
        near = [x for x in rc["imps"] if s["device"] in x["devices"]]
        lines = [f"Fire panel {s['device']} {s['point']} ({s['signal'].lower()}): {s['text'].lower()} at {hm(s['start'])}; "
                 f"{s['clear_text'].lower()} at {hm(s['end'])}",
                 f"Impairment log: nothing on {s['device']} between {hm(s['start'])} and {hm(s['end'])}"
                 + (f" (its other impairments this month: {', '.join(x['row']['imp_id'] for x in near)})" if near else ""),
                 "Notices: none received for this span"]
        valve = s["point"] == "valve tamper"
        findings.append({
            "kind": "unlogged", "title": f"{s['device']}: {s['text'].lower()} for {dur(s['start'], s['end'])}, no impairment logged",
            "summary": f"The fire panel shows {s['device']} with its {s['text'].lower()} from {hm(s['start'])} to {hm(s['end'])} "
                       f"({dur(s['start'], s['end'])}). No impairment on the log covers it and the Customer received no notice."
                       + (" A closed control valve means the zone cannot deliver water." if valve else "")
                       + " Whatever the work was, the log and the panel do not reconcile.",
            "owner": "Landlord", "severity": "S2", "contract": CONTRACT["unlogged"], "sla_refs": ["FPI-6", "FPI-1", "FPI-2"], "lines": lines, "refs": [], "devices": [s["device"]],
            "imp": None, "from": iso(s["start"]), "to": iso(s["end"])})
    for name in ("vesda", "maintenance", "notice", "restore_notice", "restored", "window", "watch"):
        left = len(rc["bad"].get(name, [])) - explained.get(name, 0)
        if left > 0:
            for b in rc["bad"][name][-left:]:
                findings.append({"kind": "records_disagree", "title": f"{name}: {json.dumps(b, default=str)[:140]}",
                                 "summary": "Records do not reconcile.", "owner": "Landlord", "severity": "S3", "contract": CONTRACT["records_disagree"], "sla_refs": [],
                                 "lines": [], "refs": [], "devices": [], "imp": b.get("imp"), "from": None, "to": None})
    findings.sort(key=lambda f: (f["from"] or "", ORDER.index(f["kind"])))
    for i, f in enumerate(findings, 1):
        f["id"] = f"FLS-{i}"
    checks = []
    for name, title in AGREEMENTS:
        c = Check(name, title)
        c.checked = rc["cases"].get(name, 0)
        n_bad = len(rc["bad"].get(name, []))
        if n_bad != explained.get(name, 0):
            c.misses.append(f"{n_bad - explained.get(name, 0)} disagreements not explained")
        checks.append(c)
    return {"findings": findings, "agreements": checks, "rc": rc,
            "explained": {k: len(v) for k, v in rc["bad"].items()}}


def score(fs: list[dict], key: list[dict]) -> dict[str, int]:
    """Planted cases found, and findings that match none (false positives)."""
    def hit(f: dict, p: dict) -> bool:
        if f["kind"] != p["kind"]:
            return False
        if p["kind"] == "restored_late":
            return f["imp"] == p.get("imp_id")
        return f["devices"] == [p["device"]] and f["from"][:16] == p["start"][:16]
    found = sum(1 for p in key if any(hit(f, p) for f in fs))
    fp = sum(1 for f in fs if not any(hit(f, p) for p in key))
    return {"planted": len(key), "found": found, "false_positives": fp}
