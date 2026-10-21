"""EHS (safety): the contract's monthly EHS report by partner and four record checks (page /ops/#ehs).

The month's records say which jobs need a permit: a Landlord MOP or maintenance record by its work type, a corrective
work order by its fault class, an IT Partner deployment step by its milestone (``config/ehs.yaml``). The EHS layer
(``data/ehs/``, own random stream) holds the permits, the training records, and the safety events. The checks compare
them with the records and the devices:

1. **No permit.** A job that needs a permit has none of that type, or a tap-off breaker was operated with no permit
   open on it.
2. **Locked out while the device shows power.** A lockout recorded on a circuit before the device isolated it, or
   after the device restored it (the contract names "power present on a circuit recorded as locked out" as evidence).
3. **Named without current training.** A person named on a permit, or the engineer of an electrical task, without a
   current completion of every course the work requires; their badge-ins that day are the evidence.
4. **Closed before the work ended.** A permit closed while the device still showed the work open, or before the job
   record ended.

Reported injuries, near misses, first aid cases, and stop-work uses are counted in the monthly report and are never
findings. A finding means the records do not reconcile; it opens an investigation by Customer EHS, which decides any
violation class (``sla/common.yaml``, ehs).
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from scorecard import change_calendar as CC
from scorecard.change_calendar import parse, iso, local_day

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "ehs.yaml"
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "ehs"
PARTNERS = {"it": "IT Partner", "landlord": "Landlord", "security": "Security Partner"}
KINDS = {"no_permit": "Work with no permit",
         "lock_power": "Locked out while the device showed power",
         "untrained": "Named on a permit without current training",
         "closed_early": "Permit closed before the work ended"}
ACTIONS = {"no_permit": "Customer EHS investigates under the common terms (EHS-R2 or EHS-R3); the partner shows the permit or "
                        "explains the work, and the permit procedure is briefed before the next job of this kind.",
           "lock_power": "Customer EHS investigates: the lockout record and the device disagree on when the circuit was dead. "
                         "The partner shows the test-before-touch record; the lockout procedure is re-verified on the next job.",
           "untrained": "The person stops permit work until the course is current; the partner shows the training record "
                        "on Site (EHS-C2 if the work went ahead without it, EHS-C3 if only the record was missing).",
           "closed_early": "Customer EHS investigates why the permit was closed while the work was still open; the partner "
                           "re-briefs permit close-out (the job is closed only after the equipment is restored)."}
AGREEMENTS = [
    ("permits", "Every job that needs a permit has one of each type, open when the work starts, and every tap-off breaker "
                "operation happens under a permit on that tap-off"),
    ("lockout", "Every lockout on a circuit a device records sits inside the device's isolation"),
    ("qualified", "Every person named on a permit, and every electrical task's engineer, holds current training for the work"),
    ("closed", "Every permit closes after its work ends"),
]
SOURCE = {"MOP": "Landlord MOP", "Maintenance": "Landlord maintenance record", "Work order": "Landlord work order",
          "Milestone": "IT Partner deployment step"}
PERMIT_COLS = ["permit", "type", "job", "partner", "point", "issued", "approved", "lock_on", "lock_off", "closed",
               "workers", "attendant", "issuer"]
TRAINING_COLS = ["person", "partner", "role", "course", "completed", "expires"]
EVENT_COLS = ["event", "kind", "partner", "at", "where", "what", "action", "action_due", "action_closed"]


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def config(path: Path = CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def add_months(t: datetime, n: int) -> datetime:
    y, m = divmod(t.month - 1 + n, 12)
    return t.replace(year=t.year + y, month=m + 1, day=min(t.day, 28))


# ---------------------------------------------------------------- the month's records
@dataclass
class Month:
    dir: Path
    window: dict[str, Any]
    mops: list[dict[str, Any]]
    pms: list[dict[str, str]]
    wos: list[dict[str, Any]]
    milestones: list[dict[str, str]]
    personnel: list[dict[str, str]]
    ll_roster: list[dict[str, str]]
    badges: list[dict[str, str]]
    ll_badges: list[dict[str, str]]
    devices: dict[str, list[tuple[datetime, datetime | None, str]]]
    breakers: list[dict[str, Any]]

    @property
    def start(self) -> datetime:
        return parse(self.window["start"])

    @property
    def end(self) -> datetime:
        return parse(self.window["end"])


def load_month(sample_dir: str | Path = SAMPLE) -> Month:
    d = Path(sample_dir)
    return Month(dir=d, window=_json(d / "manifest.json")["window"],
                 mops=_json(d / "customer" / "landlord_mop_approvals.json"), pms=_csv(d / "landlord" / "pm_records.csv"),
                 wos=_json(d / "landlord" / "work_orders.json"), milestones=_csv(d / "vendor" / "deployment_milestones.csv"),
                 personnel=_csv(d / "vendor" / "personnel.csv"), ll_roster=_csv(d / "landlord" / "roster.csv"),
                 badges=_csv(d / "access" / "badge_events.csv"), ll_badges=_csv(d / "access" / "landlord_badge_events.csv"),
                 devices=CC.device_actions(d),
                 breakers=[x for x in CC._jsonl(d / "facility" / "busway_cpm_events.jsonl") if x.get("point") == "Tap-off breaker"])


@dataclass
class EhsData:
    permits: list[dict[str, Any]]
    training: list[dict[str, str]]
    events: list[dict[str, str]]
    manifest: dict[str, Any]


def load(layer: str | Path = LAYER) -> EhsData:
    d = Path(layer)
    permits = []
    for p in _csv(d / "permits.csv"):
        p = dict(p)
        p["workers"] = [w for w in p["workers"].split(";") if w]
        permits.append(p)
    return EhsData(permits=permits, training=_csv(d / "training.csv"), events=_csv(d / "events.csv"),
                   manifest=_json(d / "manifest.json"))


# ---------------------------------------------------------------- jobs that need a permit
def device_key(point: str) -> str:
    """The device record's name for a lock point ("CDU-B3 pump" is the CDU's pump record)."""
    return f"PUMP:{point[:-5]}" if point.endswith(" pump") else point


def _device_iv(m: Month, key: str | None, lo: datetime, hi: datetime) -> tuple[datetime, datetime] | None:
    """The device's isolation that overlaps [lo, hi] (the earliest one), with an open end closed at the month end."""
    if not key:
        return None
    for s, e, _ in sorted(m.devices.get(device_key(key), []), key=lambda x: x[0]):
        e = e or m.end
        if s < hi and e > lo:
            return s, e
    return None


def _lock_key(lock: str, g: dict[str, str]) -> str | None:
    asset = g.get("asset")
    if lock == "tapoff":
        return f"TO-{g['rack']}-{g['side']}" if g.get("rack") else asset
    if lock == "pump":
        return f"{asset} pump"
    if lock in ("ups", "chiller"):
        return asset
    return None


def jobs(m: Month, cfg: dict[str, Any] | None = None, ccfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every job in the month that needs a permit or is electrical work, from the records as they are.

    ``start`` and ``end`` are the work: what the device recorded where one records it (the tap-off breaker, the UPS
    bypass, the CDU pump, the chiller lockout), else the job record (a work order's engagement to its close, the
    window before a maintenance record's completion, the hours before a deployment step's completion). ``device`` is
    the isolation the device recorded on the job's lock point.
    """
    cfg, ccfg = cfg or config(), ccfg or CC.config()
    J = cfg["jobs"]
    out: list[dict[str, Any]] = []

    def add(jid, source, partner, title, spec, start, end, point=None, device=None, people=(), refs=(), room=None):
        out.append({"id": jid, "source": source, "partner": partner, "title": title, "permits": list(spec["permits"]),
                    "lock": spec["lock"], "electrical": bool(spec["electrical"]), "point": point,
                    "start": iso(start), "end": iso(end), "device": [iso(device[0]), iso(device[1])] if device else None,
                    "people": list(people), "refs": list(refs), "room": room})

    pm_by_mop = {p["mop_ref"]: p for p in m.pms if p["mop_ref"]}
    for x in m.mops:
        w, g = CC.classify(x["title"], ccfg)
        spec = J["work_types"].get(w["type"])
        if not spec:
            continue
        ws, we = parse(x["window_start"]), parse(x["window_end"])
        key = _lock_key("tapoff" if w["type"] == "tapoff_energize" else spec["lock"], g)
        dev = _device_iv(m, key, ws - timedelta(hours=2), we + timedelta(hours=2))
        s, e = dev or (ws, we)
        pm = pm_by_mop.get(x["mop_id"])
        add(x["mop_id"], "MOP", "landlord", x["title"], spec, s, e, key, dev if spec["lock"] != "none" or dev else None,
            [pm["engineer"]] if pm else [], [pm["task_id"]] if pm else [], _room(x["assets"][0] if x["assets"] else key))
    for p in m.pms:
        if p["mop_ref"] or not p["completed_at"]:
            continue
        title = f"{p['task']}: {p['asset']}"
        w, g = CC.classify(title, ccfg)
        spec = J["work_types"].get(w["type"])
        if not spec:
            continue
        done = parse(p["completed_at"])
        key = _lock_key(spec["lock"], g)
        dev = _device_iv(m, key, done - timedelta(hours=12), done + timedelta(minutes=1))
        s, e = dev or (done - timedelta(minutes=w["minutes"]), done)
        add(p["task_id"], "Maintenance", "landlord", title, spec, s, e, key, dev, [p["engineer"]], [], _room(p["asset"]))
    for o in m.wos:
        spec = next((w for w in J["work_orders"] if (w.get("fault_class") and w["fault_class"] == o["fault_class"])
                     or (w.get("match") and re.match(w["match"], o.get("notes") or ""))), None)
        if not spec or not o.get("engaged_at") or not o.get("closed"):
            continue
        s, e = parse(o["engaged_at"]), parse(o["closed"])
        found = re.search(r"\bTO-[A-Z]\d+(?:-[AB])?\b", o.get("notes", ""))
        key = found.group(0) if spec["lock"] == "tapoff" and found else (o["unit"] if spec["lock"] == "ups" else None)
        dev = _device_iv(m, key, s - timedelta(hours=1), e)
        add(o["wo"], "Work order", "landlord", o.get("notes") or f"{o['fault_class']} {o['unit']}", spec, s, e, key, dev,
            [o["engineer"]] if o.get("engineer") else [], [o["mop_ref"]] if o.get("mop_ref") else [], o.get("room"))
    for x in m.milestones:
        spec = J["milestones"].get(x["milestone"])
        if not spec or not x["reported_complete_at"]:
            continue
        e = parse(x["reported_complete_at"])
        s = e - timedelta(hours=spec["hours"][1])
        add(f"{x['rack']} {x['milestone']}", "Milestone", "it", f"{x['name']}: rack {x['rack']}", spec, s, e,
            None, None, [], [], f"Hall {x['rack'][0]}")
    keep = [j for j in out if m.start <= parse(j["start"]) < m.end]
    return sorted(keep, key=lambda j: (j["start"], j["id"]))


def _room(unit: str | None) -> str | None:
    from scorecard.synthetic.facility import room_for
    if not unit:
        return None
    if unit.startswith(("BW-", "TO-")):
        return f"Hall {unit.split('-')[1][0]}"
    return room_for(unit)


def work_end(j: dict[str, Any]) -> datetime:
    """When the job's work ended: the later of the device's restoration and the job record's end."""
    end = parse(j["end"])
    return max(end, parse(j["device"][1])) if j["device"] else end


def ll_shifts(m: Month, hours: int = 12) -> list[tuple[datetime, datetime, str]]:
    return [(parse(r["shift_start"]), parse(r["shift_start"]) + timedelta(hours=hours), r["engineer"]) for r in m.ll_roster]


def roles(m: Month) -> dict[str, tuple[str, str]]:
    """person -> (partner key, role)."""
    out = {p["person_id"]: ("it", p["role"]) for p in m.personnel}
    for _, _, e in ll_shifts(m):
        out.setdefault(e, ("landlord", "engineer"))
    return out


# ---------------------------------------------------------------- hours worked (facts from badges)
def hours_worked(m: Month, security_dir: Path | None = None, shift_hours: int = 12) -> dict[str, float]:
    """IT Partner: OPS-MAIN in to out. Landlord: each rostered shift the engineer badged in during (the Landlord's
    readers record entry only). Security Partner: each post shift the guard badged in at the post for."""
    out: dict[str, float] = {}

    def pairs(rows, who, door_ok):
        tot, opened = 0.0, {}
        for r in sorted(rows, key=lambda r: r["timestamp"]):
            if not door_ok(r):
                continue
            t = parse(r["timestamp"])
            if r["direction"] == "in":
                opened.setdefault(r[who], t)
            elif r[who] in opened:
                s = opened.pop(r[who])
                tot += (min(t, m.end) - max(s, m.start)).total_seconds() / 3600 if t > m.start and s < m.end else 0
        return tot

    out["it"] = pairs(m.badges, "person_id", lambda r: r["door"] == "OPS-MAIN")
    ins = {}
    for b in m.ll_badges:
        ins.setdefault(b["person_id"], []).append(parse(b["timestamp"]))
    tot = 0.0
    early = timedelta(minutes=30)                                      # a badge just before the shift starts counts
    for s, e, who in ll_shifts(m, shift_hours):
        if any(s - early <= t < e for t in ins.get(who, [])):
            tot += (min(e, m.end) - max(s, m.start)).total_seconds() / 3600 if e > m.start and s < m.end else 0
    out["landlord"] = tot
    if security_dir and (security_dir / "post_log.csv").exists():
        gins: dict[str, list[datetime]] = {}
        for b in _csv(security_dir / "guard_badges.csv"):
            if b["reader"].startswith("Post: "):
                gins.setdefault(b["guard_id"], []).append(parse(b["timestamp"]))
        tot = 0.0
        for r in _csv(security_dir / "post_log.csv"):
            s = parse(r["shift_start"])
            e = s + timedelta(hours=shift_hours)
            if any(s - early <= t < e for t in gins.get(r["guard_id"], [])) and e > m.start and s < m.end:
                tot += (min(e, m.end) - max(s, m.start)).total_seconds() / 3600
        out["security"] = tot
    return {k: round(v, 1) for k, v in out.items()}


# ---------------------------------------------------------------- the checks
@dataclass
class Check:
    name: str
    title: str
    checked: int = 0
    misses: list[str] = field(default_factory=list)


def current(training: list[dict[str, str]], person: str, course: str, t: datetime) -> dict[str, str] | None:
    for r in training:
        if r["person"] == person and r["course"] == course and parse(r["completed"]) <= t < parse(r["expires"]):
            return r
    return None


def last(training: list[dict[str, str]], person: str, course: str) -> dict[str, str] | None:
    rows = [r for r in training if r["person"] == person and r["course"] == course]
    return max(rows, key=lambda r: r["completed"]) if rows else None


def _badges_that_day(m: Month, person: str, t: datetime) -> list[dict[str, str]]:
    day = local_day(t)
    out = [{"at": b["timestamp"], "where": b["reader"]} for b in m.ll_badges
           if b["person_id"] == person and local_day(parse(b["timestamp"])) == day]
    out += [{"at": b["timestamp"], "where": b["door"]} for b in m.badges
            if b["person_id"] == person and b["direction"] == "in" and local_day(parse(b["timestamp"])) == day]
    return sorted(out, key=lambda x: x["at"])


def _mins(a: datetime, b: datetime) -> int:
    return round((b - a).total_seconds() / 60)


def named_tasks(permits: list[dict[str, Any]], J: list[dict[str, Any]], req: dict[str, list[str]]) -> list[tuple[str, list[str], datetime, str, str]]:
    """What each named person must hold, and when: (person, courses, work start, permit or job, partner). Every person
    named on a permit holds the permit type's courses (and NFPA 70E for a lockout or energized permit on electrical
    work); an energized permit's second person holds contact release; an electrical task with no permit (testing under
    load) needs its engineer qualified."""
    jobs_by_id = {j["id"]: j for j in J}
    tasks = []
    for p in permits:
        j = jobs_by_id.get(p["job"])
        at = parse(j["start"]) if j else parse(p["issued"])
        need = list(req["all"]) + list(req.get(p["type"], []))
        if j and j["electrical"] and p["type"] in ("loto", "eewp"):
            need += [c for c in req["electrical"] if c not in need]
        for w in p["workers"]:
            tasks.append((w, need, at, p["permit"], p["partner"]))
        if p["attendant"]:
            tasks.append((p["attendant"], list(req["all"]) + list(req["eewp_attendant"]), at, p["permit"], p["partner"]))
    permitted = {p["job"] for p in permits}
    for j in J:
        if j["electrical"] and not j["permits"] and j["id"] not in permitted:
            for w in j["people"]:
                tasks.append((w, list(req["all"]) + list(req["electrical"]), parse(j["start"]), j["id"], j["partner"]))
    return tasks


def analyse(m: Month, e: EhsData, cfg: dict[str, Any] | None = None, security_dir: Path | None = None) -> dict[str, Any]:
    cfg = cfg or config()
    req = cfg["required"]
    J = jobs(m, cfg)
    by_job: dict[str, list[dict[str, Any]]] = {}
    for p in e.permits:
        by_job.setdefault(p["job"], []).append(p)
    checks = {k: Check(k, t) for k, t in AGREEMENTS}
    found: list[dict[str, Any]] = []
    explained: dict[str, int] = {}

    def finding(kind, refs, at, text, partner, evidence, check, extra=None):
        found.append({"kind": kind, "title": KINDS[kind], "refs": refs, "at": at, "text": text, "partner": partner,
                      "owner": PARTNERS[partner], "evidence": evidence, "action": ACTIONS[kind], **(extra or {})})
        checks[check].misses.append(f"{refs[0]}: {text}")
        explained[check] = explained.get(check, 0) + 1

    # 1. permits: each job's permits, then each tap-off breaker operation
    flagged_points: list[tuple[str, datetime, datetime]] = []
    for j in J:
        for t in j["permits"]:
            checks["permits"].checked += 1
            ps = [p for p in by_job.get(j["id"], []) if p["type"] == t]
            if not ps:
                ev = [{"label": f"{j['point']} ({'device'})", "start": j["device"][0], "end": j["device"][1], "kind": "device"}] if j["device"] else []
                finding("no_permit", [j["id"]], j["start"],
                        f"{j['id']} ({j['title']}) needs a {cfg['permit_types'][t]['name'].lower()} permit "
                        f"({cfg['permit_types'][t]['rule']}); none is on file. The work ran "
                        f"{CC.hm_local(parse(j['start']))} to {CC.hm_local(parse(j['end']))} on {local_day(parse(j['start']))}.",
                        j["partner"], ev, "permits", {"job": j["id"], "permit_type": t})
                if j["device"] and j["point"]:
                    flagged_points.append((j["point"], parse(j["device"][0]), parse(j["device"][1])))
            elif parse(ps[0]["issued"]) > parse(j["start"]):
                checks["permits"].misses.append(f"{j['id']}: permit {ps[0]['permit']} issued after the work started")
    for b in m.breakers:
        if b["event"] != "Breaker open":
            continue
        t = parse(b["timestamp"])
        if not m.start <= t < m.end:
            continue
        checks["permits"].checked += 1
        if any(pt == b["tapoff"] and s <= t <= en for pt, s, en in flagged_points):
            continue
        cover = [p for p in e.permits if p["point"] == b["tapoff"] and parse(p["issued"]) <= t <= parse(p["closed"])]
        if not cover:
            later = [p for p in e.permits if p["point"] == b["tapoff"] and parse(p["issued"]) > t]
            close = next((parse(x["timestamp"]) for x in m.breakers if x["tapoff"] == b["tapoff"] and x["event"] == "Breaker closed"
                          and parse(x["timestamp"]) > t), m.end)
            ev = [{"label": f"{b['tapoff']} breaker open (busway CPM)", "start": iso(t), "end": iso(close), "kind": "device"}]
            if later:
                p0 = min(later, key=lambda p: p["issued"])
                ev.append({"label": f"{p0['permit']} ({cfg['permit_types'][p0['type']]['name'].lower()}, {p0['job']})",
                           "start": p0["issued"], "end": p0["closed"], "kind": "permit"})
            finding("no_permit", [b["tapoff"], b["busway"]], iso(t),
                    f"Tap-off {b['tapoff']} ({b['busway']}) was opened at {CC.hm_local(t)} on {local_day(t)} with no permit "
                    "open on it" + (f"; the first permit on it, {later[0]['permit']} for {later[0]['job']}, was issued "
                                    f"{_mins(t, parse(min(later, key=lambda p: p['issued'])['issued']))} minutes later." if later else "."),
                    "landlord", ev, "permits", {"job": None})
    jobs_by_id = {j["id"]: j for j in J}

    # 2. lockout against the device
    for p in e.permits:
        j = jobs_by_id.get(p["job"])
        if p["type"] != "loto" or not j or not p["lock_on"] or not p["point"]:
            continue
        on, off = parse(p["lock_on"]), parse(p["lock_off"])
        dev = _device_iv(m, p["point"], on, off)
        if not dev:
            continue
        checks["lockout"].checked += 1
        s, en = dev
        if on < s or off > en:
            gap = (_mins(on, s) if on < s else 0) + (_mins(en, off) if off > en else 0)
            what = []
            if on < s:
                what.append(f"locked out at {CC.hm_local(on)}, {_mins(on, s)} minutes before the device isolated it ({CC.hm_local(s)})")
            if off > en:
                what.append(f"lock removed at {CC.hm_local(off)}, {_mins(en, off)} minutes after the device restored it ({CC.hm_local(en)})")
            rec = next((r for a, b_, r in m.devices.get(device_key(p["point"]), []) if a == s), "device")
            finding("lock_power", [p["permit"], p["job"]], iso(min(on, s)),
                    f"{p['permit']} ({p['job']}) records {p['point']} {' and '.join(what)}: the record shows the circuit locked out "
                    f"while the device shows it energized for {gap} minutes.",
                    p["partner"],
                    [{"label": f"{p['permit']} lockout", "start": p["lock_on"], "end": p["lock_off"], "kind": "lock"},
                     {"label": f"{p['point']} isolated ({rec.split(':')[0]})", "start": iso(s), "end": iso(en), "kind": "device"}],
                    "lockout", {"job": p["job"], "permit": p["permit"], "minutes": gap})

    # 3. training
    gaps: dict[str, list[tuple[dict, str, datetime]]] = {}
    tasks = named_tasks(e.permits, J, req)
    for who, need, at, ref, partner in tasks:
        checks["qualified"].checked += 1
        miss = [c for c in need if not current(e.training, who, c, at)]
        if miss:
            for c in miss:
                gaps.setdefault(who, []).append(({"ref": ref, "partner": partner}, c, at))
    for who, rows in sorted(gaps.items()):
        courses = sorted({c for _, c, _ in rows})
        refs = sorted({r["ref"] for r, _, _ in rows})
        at = min(t for _, _, t in rows)
        lasts = {c: last(e.training, who, c) for c in courses}
        why = "; ".join(f"{cfg['courses'][c]['name']} " + (f"expired {lasts[c]['expires'][:10]}" if lasts[c] else "never recorded")
                        for c in courses)
        badges = _badges_that_day(m, who, at)
        text = (f"{who} is named on {', '.join(refs)} without current training ({why})."
                + (f" Badged in that day: {', '.join(CC.hm_local(parse(b['at'])) + ' ' + b['where'] for b in badges[:4])}." if badges else ""))
        partner = rows[0][0]["partner"]
        ev = [{"label": f"{cfg['courses'][c]['name']} (last completion)", "start": lasts[c]["completed"], "end": lasts[c]["expires"],
               "kind": "training"} for c in courses if lasts[c]]
        found.append({"kind": "untrained", "title": KINDS["untrained"], "refs": [who] + refs, "at": iso(at), "text": text,
                      "partner": partner, "owner": PARTNERS[partner], "evidence": ev, "badges": badges,
                      "action": ACTIONS["untrained"], "person": who})
        n = sum(1 for t in tasks if t[0] == who and any(not current(e.training, who, c, t[2]) for c in t[1]))
        checks["qualified"].misses += [f"{who}: {why}"] * n
        explained["qualified"] = explained.get("qualified", 0) + n

    # 4. closed after the work ended
    for p in e.permits:
        j = jobs_by_id.get(p["job"])
        if not j:
            continue
        checks["closed"].checked += 1
        end = work_end(j)
        if parse(p["closed"]) < end:
            ev = [{"label": f"{p['permit']} open", "start": p["issued"], "end": p["closed"], "kind": "permit"}]
            if j["device"]:
                ev.append({"label": f"{j['point']} isolated (device)", "start": j["device"][0], "end": j["device"][1], "kind": "device"})
            ev.append({"label": f"{j['id']} work ({SOURCE[j['source']].lower()})", "start": j["start"], "end": j["end"], "kind": "job"})
            finding("closed_early", [p["permit"], p["job"]], p["closed"],
                    f"{p['permit']} ({p['job']}) was closed at {CC.hm_local(parse(p['closed']))}, {_mins(parse(p['closed']), end)} minutes "
                    f"before the work ended ({CC.hm_local(end)}" + (", when the device restored the equipment)." if j["device"] else ", the job record's end)."),
                    p["partner"], ev, "closed", {"job": p["job"], "permit": p["permit"], "minutes": _mins(parse(p["closed"]), end)})

    found.sort(key=lambda f: (f["at"], f["kind"]))
    for i, f in enumerate(found, 1):
        f["id"] = f"SAF-{i}"
    return {"jobs": J, "findings": found, "agreements": list(checks.values()), "explained": explained,
            "report": report(m, e, cfg, security_dir)}


# ---------------------------------------------------------------- the monthly EHS report (contract's list)
def report(m: Month, e: EhsData, cfg: dict[str, Any], security_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    hours = hours_worked(m, security_dir, cfg["generate"]["shift_hours"])
    out = {}
    for k in PARTNERS:
        if k not in hours:
            continue
        ev = [x for x in e.events if x["partner"] == k and m.start <= parse(x["at"]) < m.end]
        rec = sum(1 for x in ev if x["kind"] == "recordable")
        dart = sum(1 for x in ev if x["kind"] == "recordable" and "days away" in x["what"].lower())
        out[k] = {"hours": hours[k], "recordables": rec, "dart": dart,
                  "trir": round(rec * 200000 / hours[k], 2) if hours[k] else 0.0,
                  "dart_rate": round(dart * 200000 / hours[k], 2) if hours[k] else 0.0,
                  "near_miss": sum(1 for x in ev if x["kind"] == "near_miss"),
                  "stop_work": sum(1 for x in ev if x["kind"] == "stop_work"),
                  "first_aid": sum(1 for x in ev if x["kind"] == "first_aid"),
                  "permits": sum(1 for p in e.permits if p["partner"] == k and m.start <= parse(p["issued"]) < m.end),
                  "open_actions": sum(1 for x in e.events if x["partner"] == k and x["action"] and parse(x["at"]) < m.end
                                      and (not x["action_closed"] or parse(x["action_closed"]) >= m.end))}
    return out


def score(fs: list[dict[str, Any]], key: list[dict[str, Any]]) -> dict[str, int]:
    """Planted cases found, cases the dataset already holds (as found), and findings neither explains."""
    hit = lambda k: any(f["kind"] == k["kind"] and k["ref"] in f["refs"] for f in fs)
    planted = [k for k in key if k["source"] == "planted"]
    fp = [f for f in fs if not any(f["kind"] == k["kind"] and k["ref"] in f["refs"] for k in key)]
    return {"planted": len(planted), "found": sum(hit(k) for k in planted),
            "as_found": sum(hit(k) for k in key if k["source"] != "planted"),
            "as_found_expected": sum(1 for k in key if k["source"] != "planted"), "false_positives": len(fp)}


def week_counts(e: EhsData, ws: datetime, we: datetime) -> dict[str, Any]:
    """The weekly pack's EHS lines: permits issued and reported events in [ws, we)."""
    ps = [p for p in e.permits if ws <= parse(p["issued"]) < we]
    ev = [x for x in e.events if ws <= parse(x["at"]) < we]
    return {"permits": len(ps), "by_type": {t: sum(1 for p in ps if p["type"] == t) for t in sorted({p["type"] for p in ps})},
            "near_miss": sum(1 for x in ev if x["kind"] == "near_miss"),
            "stop_work": sum(1 for x in ev if x["kind"] == "stop_work"),
            "first_aid": sum(1 for x in ev if x["kind"] == "first_aid"),
            "recordable": sum(1 for x in ev if x["kind"] == "recordable")}


# ---------------------------------------------------------------- the page
def pir_screenings(root: Path = ROOT) -> list[dict[str, Any]]:
    """Each post-incident review's EHS screening (pir/reviews/): injuries, the screening, and any referral."""
    out = []
    for f in sorted((root / "pir" / "reviews").glob("PIR-*.yaml")):
        r = yaml.safe_load(f.read_text(encoding="utf-8"))
        x = r.get("ehs") or {}
        out.append({"pir": r["id"], "title": r["title"], "injuries": x.get("injuries", 0), "screening": x.get("screening", ""),
                    "referral": x.get("referral", ""), "referred": "Referred to Customer EHS" in (x.get("referral") or "")})
    return out


def page_data(sample: Path = SAMPLE, layer: Path = LAYER, security_dir: Path | None = ROOT / "data" / "security",
              cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or config()
    m, e = load_month(sample), load(layer)
    r = analyse(m, e, cfg, security_dir)
    jobs_by_id = {j["id"]: j for j in r["jobs"]}
    flag: dict[str, list[str]] = {}
    for f in r["findings"]:
        for ref in f["refs"]:
            flag.setdefault(ref, []).append(f["id"])
    held: dict[str, list[dict[str, Any]]] = {}
    for who, need, at, ref, _ in named_tasks(e.permits, r["jobs"], cfg["required"]):
        for c in need:
            row = current(e.training, who, c, at) or last(e.training, who, c)
            held.setdefault(ref, []).append({"person": who, "course": c, "name": cfg["courses"][c]["name"],
                                             "expires": row["expires"] if row else "", "current": bool(current(e.training, who, c, at))})
    permits = []
    for p in e.permits:
        j = jobs_by_id.get(p["job"], {})
        permits.append({**p, "title": j.get("title", ""), "source": j.get("source", ""), "start": j.get("start", ""),
                        "end": iso(work_end(j)) if j else "", "device": j.get("device"), "room": j.get("room"),
                        "training": held.get(p["permit"], []),
                        "findings": sorted(set(flag.get(p["permit"], []) + flag.get(p["job"], [])))})
    for j in r["jobs"]:
        j["findings"] = sorted(set(flag.get(j["id"], [])))
        j["training"] = held.get(j["id"], [])
    people = roles(m)
    if security_dir and (security_dir / "guards.csv").exists():
        for g in _csv(security_dir / "guards.csv"):
            people[g["guard_id"]] = ("security", "guard")
    soon = m.end + timedelta(days=60)
    courses = []
    for key, c in cfg["courses"].items():
        rows = [t for t in e.training if t["course"] == key]
        holders = {t["person"] for t in rows}
        cur = {t["person"] for t in rows if parse(t["completed"]) <= m.end < parse(t["expires"])}
        courses.append({"key": key, "name": c["name"], "months": c["months"], "holders": len(holders), "current": len(cur),
                        "lapsed": sorted(holders - cur),
                        "expiring": sorted({t["person"] for t in rows if m.end <= parse(t["expires"]) < soon})})
    weeks = []
    for i in range(int(m.window["weeks"])):
        ws = m.start + timedelta(weeks=i)
        weeks.append({"start": iso(ws), **week_counts(e, ws, ws + timedelta(weeks=1))})
    for f in r["findings"]:
        f["date"] = local_day(parse(f["at"]))
    return {"window": m.window, "report": r["report"], "partners": PARTNERS, "permit_types": cfg["permit_types"],
            "courses": courses, "people": {k: list(v) for k, v in people.items()},
            "permits": permits, "jobs": r["jobs"], "findings": r["findings"], "events": e.events, "weeks": weeks,
            "pir": pir_screenings(),
            "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": c.misses,
                            "explained": r["explained"].get(c.name, 0)} for c in r["agreements"]],
            "kinds": KINDS, "sources": SOURCE,
            "summary": {"jobs": len(r["jobs"]), "permits": len(e.permits), "findings": len(r["findings"]),
                        "by_kind": {k: sum(1 for f in r["findings"] if f["kind"] == k) for k in KINDS},
                        "people": len(people), "training": len(e.training)}}
