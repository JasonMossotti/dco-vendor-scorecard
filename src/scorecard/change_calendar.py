"""Maintenance and change calendar: every booked job at the site on one calendar, checked for conflicts.

The calendar holds the Customer CAB's changes, the Landlord's MOPs, the change-approval queue, the Landlord's
preventive maintenance, the Hall B deployment milestones, and the Hall C commissioning scripts. The four data weeks
come from the records as they are; the forward look to Hall C first compute comes from the forward schedule
(``data/calendar/``, its own random stream). Each job's effect on redundancy follows from its title
(``config/calendar.yaml``, work_types) and is counted against the redundancy groups Site health uses:

1. **Overlap.** Two jobs in one redundancy group at the same time take out more units than the group's redundancy
   allows: the group is below N for the overlap.
2. **Both feeds.** Work on the A and the B feed of one rack at the same time.
3. **Surge day.** A job that takes a unit out of a Hall B or site-wide group on a day with two or more Hall B
   energizations (Interface Agreement HO-4 tap-offs and rack power-ons).
4. **Freeze.** A job that takes a unit out of a site-wide group, or Hall C work outside the commissioning plan, in
   the days before Hall C first compute.

For the data weeks the calendar also reconciles with the devices: every recorded action on a job's equipment that
starts inside the job's booked window ends inside it. A finding (CAL-#) means the bookings do not reconcile with each
other or with the devices; it starts a planning action, not a judgment of anyone.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "calendar.yaml"
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "calendar"
KINDS = {"overlap": "Two jobs in one redundancy group at once (below N)",
         "both_feeds": "Work on both feeds of one rack at once",
         "surge": "A unit out on a deployment surge day",
         "freeze": "Work inside the first-compute freeze",
         "overrun": "Work ran past its booked window"}
ACTIONS = {"overlap": "Move one of the jobs so the group keeps its redundant unit; the change board checks the group before approving.",
           "both_feeds": "Move one of the jobs; never book both feeds of a rack in the same window.",
           "surge": "Move the job off the surge day, or move an energization, so new load does not land on a group without its redundant unit.",
           "freeze": "Move the job out of the freeze or bring it to the change board as an exception with a rollback plan.",
           "overrun": "Record why the work ran long and extend the window through the change board before it closes; review the window length for this kind of work."}
AGREEMENTS = [
    ("records", "Every CAB change, MOP, queued change, and maintenance record is on the calendar once"),
    ("declared", "A change takes a unit out exactly when its impact declaration says redundancy is reduced"),
    ("windows", "Every device action on a job's equipment that starts in its booked window ends inside it"),
]
SOURCES = {"CAB": "Customer CAB change", "MOP": "Landlord MOP", "Queue": "Change-approval queue",
           "Maintenance": "Landlord maintenance record", "Forward": "Forward schedule"}


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def iso(t: datetime | None) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else ""


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def config(path: Path = CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Central time (US daylight saving rule)
def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def utc_offset(t: datetime) -> timedelta:
    """Central time: daylight time (UTC-5) from 2 a.m. on the second Sunday of March to 2 a.m. on the first Sunday of November."""
    y = t.year
    on = datetime.combine(_nth_sunday(y, 3, 2), datetime.min.time(), timezone.utc) + timedelta(hours=8)
    off = datetime.combine(_nth_sunday(y, 11, 1), datetime.min.time(), timezone.utc) + timedelta(hours=7)
    return timedelta(hours=-5) if on <= t < off else timedelta(hours=-6)


def local(t: datetime) -> datetime:
    return (t + utc_offset(t)).replace(tzinfo=None)


def local_day(t: datetime) -> str:
    return local(t).date().isoformat()


def day_bounds(d: str) -> tuple[datetime, datetime]:
    """The UTC start and end of a local (Central) date."""
    day = date.fromisoformat(d)
    s = datetime.combine(day, datetime.min.time(), timezone.utc)
    e = s + timedelta(days=1)
    return s - utc_offset(s + timedelta(hours=6)), e - utc_offset(e + timedelta(hours=6))


def at_local(d: str, hours: float) -> datetime:
    """The UTC time of ``hours`` after local midnight on date ``d``."""
    s, _ = day_bounds(d)
    t = s + timedelta(hours=hours)
    return t + (utc_offset(s) - utc_offset(t))


def hm_local(t: datetime) -> str:
    """A UTC time as the page shows it: Central, with the zone."""
    return f"{local(t):%H:%M} {'CDT' if utc_offset(t) == timedelta(hours=-5) else 'CST'}"


def what(j: dict[str, Any]) -> str:
    """What one job takes out of service, in words."""
    if j["takes"] == "pump":
        return f"a pump of {j['group'][6:]}"
    if j["takes"] == "feed":
        return f"feed {j['unit'][-1]} of rack {j['rack']}"
    return j["unit"] or "nothing"


def days(start: str, end: str) -> list[str]:
    d, e = date.fromisoformat(start), date.fromisoformat(end)
    return [(d + timedelta(days=k)).isoformat() for k in range((e - d).days + 1)]


# ---------------------------------------------------------------- redundancy groups (the same as Site health's)
def groups(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    """Site health's redundancy groups that work can take a unit out of, from the site model and the device lists.

    Each CDU's two pumps are their own group (Site health shows them as "N+1 in each CDU"); rack feeds are checked
    rack by rack (check 2), not as a group."""
    site = yaml.safe_load((root / "site" / "site.yaml").read_text(encoding="utf-8"))
    tele = root / "data" / "telemetry"
    power = _json(tele / "power" / "manifest.json")["devices"]
    mech = _json(tele / "mechanical" / "manifest.json")["devices"]
    cdus = _json(tele / "cdu" / "manifest.json")["cdus"]
    out: dict[str, dict[str, Any]] = {}

    def g(key: str, name: str, scheme: str, hall: str | None, units: list[str], need: int) -> None:
        out[key] = {"key": key, "name": name, "scheme": scheme, "hall": hall, "units": units, "need": need}

    buses = site["plants"]["mv_switchgear"]["buses"]
    g("utility", "Utility feeds", "2N", None, [f"MV:{b}" for b in buses], 1)
    gen = site["plants"]["generators"]
    g("generators", "Generators", f"N+{gen['redundancy']}", None, sorted(k for k, x in power.items() if x["family"] == "generator"),
      gen["count"] - gen["redundancy"])
    for hall in [h for h in site["halls"] if h["state"] != "planned"]:
        hid, P, C = hall["id"], hall["power"], hall["cooling"]
        ups = sorted(u for u, x in power.items() if x["family"] == "ups" and x["hall"] == hid and x["kind"] == "it")
        g(f"ups-{hid}", "IT UPSs", f"{P['ups_count']} make {P['ups_count'] - 1}", hid, ups, P["ups_count"] - 1)
        mups = sorted(u for u, x in power.items() if x["family"] == "ups" and x["hall"] == hid and x["kind"] == "mech")
        g(f"mups-{hid}", "Mechanical UPSs", "2N", hid, mups, 1)
        hc = sorted(c for c, x in cdus.items() if x["hall"] == hid)
        g(f"cdu-{hid}", "CDUs", f"N+{C['cdu_redundancy']}", hid, hc, len(hc) - C["cdu_redundancy"])
        for c in hc:
            g(f"pumps-{c}", f"{c} pumps", "N+1 in each CDU", hid, [f"PUMP:{c}:1", f"PUMP:{c}:2"], 1)
        walls = sorted(w for w, x in mech.items() if x["family"] == "wall" and x.get("hall") == hid)
        g(f"walls-{hid}", "Thermal walls", f"N+{C['thermal_wall_redundancy']}", hid, walls, len(walls) - C["thermal_wall_redundancy"])
        crahs = sorted(w for w, x in mech.items() if x["family"] == "crah" and x.get("hall") == hid)
        g(f"crah-{hid}", "Electrical-room CRAHs", f"N+{C['electrical_room_crah_redundancy']}", hid, crahs,
          len(crahs) - C["electrical_room_crah_redundancy"])
    hr = site["plants"]["heat_rejection"]
    ch = sorted(c for c, x in mech.items() if x["family"] == "chiller")
    g("chillers", "Chillers", f"N+{hr['chiller_redundancy']}", None, ch, len(ch) - hr["chiller_redundancy"])
    pumps = sorted(c for c, x in mech.items() if x["family"] == "pump")
    g("fwpumps", "Facility water pumps", f"N+{hr['pump_redundancy']}", None, pumps, len(pumps) - hr["pump_redundancy"])
    return out


def rack_halls(root: Path = ROOT, sample: Path = SAMPLE) -> dict[str, str]:
    return {r["rack"]: r["hall"] for r in _json(sample / "site" / "topology.json")["racks"]}


# ---------------------------------------------------------------- jobs
def classify(title: str, cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    for w in cfg["work_types"]:
        m = re.match(w["match"], title)
        if m:
            return w, m.groupdict()
    raise ValueError(f"no work type matches {title!r} (config/calendar.yaml work_types)")


def make_job(jid: str, source: str, owner: str, title: str, start: str, end: str, cfg: dict[str, Any], G: dict[str, dict],
             racks: dict[str, str], status: str = "booked", refs: list[str] | None = None, period: str = "past",
             note: str = "") -> dict[str, Any]:
    """One calendar job, with what it takes out of service and the group that counts it."""
    w, m = classify(title, cfg)
    unit = group = hall = device = None
    rack = m.get("rack")
    asset = m.get("asset")
    if w["takes"] == "pump":
        group, unit, device = f"pumps-{asset}", f"PUMP:{asset}:2", f"PUMP:{asset}"
    elif w["takes"] in ("ups", "chiller"):
        group = next(k for k, g in G.items() if asset in g["units"])
        unit = device = asset
    elif w["takes"] == "feed":
        unit, device = f"{rack}:{m['side']}", f"TO-{rack}-{m['side']}"
    elif w["type"] in ("tapoff_energize", "gen_exercise", "vesda_test"):
        device = asset
    if group:
        hall = G[group]["hall"]
    elif rack:
        hall = racks.get(rack)
    elif asset and re.match(r"(VESDA|TO)-([A-Z])", asset):
        hall = f"HALL-{re.match(r'(VESDA|TO)-([A-Z])', asset).group(2)}"
    elif asset and asset.startswith("Hall "):
        hall = f"HALL-{asset[5]}"
    return {"id": jid, "source": source, "owner": owner, "title": title, "type": w["type"], "takes": w["takes"],
            "unit": unit, "group": group, "rack": rack, "hall": hall, "device": device, "start": start, "end": end,
            "status": status, "refs": refs or [], "period": period, "note": note}


def past_jobs(cfg: dict[str, Any], G: dict[str, dict], racks: dict[str, str], sample: Path = SAMPLE,
              changes: Path = ROOT / "data" / "changes") -> list[dict[str, Any]]:
    """The data weeks' jobs, from the records as they are."""
    jobs: list[dict[str, Any]] = []
    cust = sample / "customer"
    for c in _json(cust / "cab_changes.json"):
        jobs.append(make_job(c["change_id"], "CAB", "IT Partner", c["summary"], c["window_start"], c["window_end"], cfg, G, racks,
                             status="approved", note=f"{c['state']} by the {c['approved_by']}"))
    pms = _csv(sample / "landlord" / "pm_records.csv")
    by_mop = {p["mop_ref"]: p for p in pms if p["mop_ref"]}
    for m in _json(cust / "landlord_mop_approvals.json"):
        pm = by_mop.get(m["mop_id"])
        jobs.append(make_job(m["mop_id"], "MOP", "Landlord", m["title"], m["window_start"], m["window_end"], cfg, G, racks,
                             status="approved", refs=[pm["task_id"]] if pm else [], note=f"Approved by the {m['approved_by']}"))
    status = {"approved_late": "approved late", "started_unapproved": "worked before final approval", "deferred": "deferred"}
    for q in _json(changes / "pending_approvals.json"):
        note = ""
        if q["work_started"]:
            note = f"Worked {q['work_started'][11:16]} to {q['work_ended'][11:16]} UTC"
        jobs.append(make_job(q["id"], "Queue", q["owner"], q["title"], q["window_start"], q["window_end"], cfg, G, racks,
                             status=status.get(q["outcome"], q["outcome"]), refs=[q["work_order"]] if q["work_order"] != q["id"] else [],
                             note=note))
    # Maintenance without a MOP: the window is what the device recorded, or the task's length before its completion
    bms = [x for x in _jsonl(sample / "facility" / "bms_events.jsonl") if x.get("point") == "Chiller enable"]
    emcp = _jsonl(sample / "facility" / "emcp_readings.jsonl")
    for p in pms:
        if p["mop_ref"]:
            continue
        title = f"{p['task']}: {p['asset']}"
        w, _ = classify(title, cfg)
        done = parse(p["completed_at"])
        start, note = done - timedelta(minutes=w["minutes"]), "Window: the task's length before its recorded completion"
        ref = [x for x in bms if x.get("change_ref") == p["task_id"]]
        if ref:
            start, done = parse(min(x["timestamp"] for x in ref)), parse(max(x["timestamp"] for x in ref))
            note = "Window: the chiller's lockout in the BMS"
        elif w["type"] == "gen_exercise":
            run = [x for x in emcp if x["generator"] == p["asset"] and done - timedelta(hours=3) <= parse(x["timestamp"]) <= done]
            if run:
                start = parse(min(x["timestamp"] for x in run))
                note = "Window: the engine's run in the EMCP record"
        jobs.append(make_job(p["task_id"], "Maintenance", "Landlord", title, iso(start), iso(done), cfg, G, racks, status="done", note=note))
    return sorted(jobs, key=lambda j: (j["start"], j["id"]))


def day_items(root: Path = ROOT) -> list[dict[str, Any]]:
    """Hall B rack milestones (both partners' Jira) and Hall C commissioning scripts, one item per day."""
    out: list[dict[str, Any]] = []
    for proj in ("RSS-DEP", "CCF-DEP"):
        for i in _json(root / "data" / "deployments" / "jira" / f"{proj}.json")["issues"]:
            F = i["fields"]
            step = F.get("customfield_10101") or ""
            if not re.match(r"R-(M\d|HO4)$", step):
                continue
            done = F["resolutiondate"]
            day = local_day(datetime.strptime(done[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)) if done else F["duedate"]
            out.append({"kind": "hallb", "id": i["key"], "date": day, "step": step, "rack": F.get("customfield_10102"),
                        "title": F["summary"], "state": "done" if done else F["status"]["name"].lower(),
                        "energization": step in ("R-HO4", "R-M4"), "owner": "Landlord" if proj == "CCF-DEP" else "IT Partner"})
    for s in _json(root / "data" / "readiness" / "cx_scripts.json"):
        res = s["runs"][-1]["result"] if s["runs"] else ""
        out.append({"kind": "hallc", "id": s["id"], "date": s["scheduled"], "step": s["level"], "rack": None,
                    "title": f"{s['level']} {s['system']} commissioning script", "state": res or "scheduled",
                    "energization": False, "owner": "Landlord"})
    return sorted(out, key=lambda x: (x["date"], x["kind"], x["id"]))


def surge_days(items: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, int]:
    n: dict[str, int] = {}
    for x in items:
        if x["energization"]:
            n[x["date"]] = n.get(x["date"], 0) + 1
    return {d: k for d, k in sorted(n.items()) if k >= cfg["surge_min_energizations"]}


def freeze_window(cfg: dict[str, Any]) -> tuple[str, str]:
    end = cfg["forward"]["end"]
    return (date.fromisoformat(end) - timedelta(days=cfg["freeze_days"])).isoformat(), end


# ---------------------------------------------------------------- the four checks
def _overlap(a: dict, b: dict) -> tuple[datetime, datetime] | None:
    s, e = max(parse(a["start"]), parse(b["start"])), min(parse(a["end"]), parse(b["end"]))
    return (s, e) if s < e else None


def _days_hit(j: dict, wanted: set[str]) -> list[str]:
    s, e = parse(j["start"]), parse(j["end"]) - timedelta(seconds=1)
    return sorted({local_day(s), local_day(e)} & wanted)


def conflicts(jobs: list[dict[str, Any]], G: dict[str, dict], surge: dict[str, int], freeze: tuple[str, str]) -> list[dict[str, Any]]:
    """Every conflict among the jobs (deferred jobs are off the calendar). Not numbered; ``analyse`` numbers them."""
    live = [j for j in jobs if j["status"] != "deferred" and j["takes"] != "none"]
    out: list[dict[str, Any]] = []
    by_group: dict[str, list[dict]] = {}
    for j in live:
        if j["group"]:
            by_group.setdefault(j["group"], []).append(j)
    for key, js in sorted(by_group.items()):
        g = G[key]
        spare = len(g["units"]) - g["need"]
        js = sorted(js, key=lambda j: (j["start"], j["id"]))
        for i, a in enumerate(js):
            for b in js[i + 1:]:
                ov = _overlap(a, b)
                if ov and spare < 2:
                    out.append({"kind": "overlap", "jobs": [a["id"], b["id"]], "at": iso(ov[0]), "until": iso(ov[1]),
                                "group": key, "hall": g["hall"],
                                "text": f"{a['id']} ({what(a)}) and {b['id']} ({what(b)}) overlap: "
                                        f"{g['name']}{' (' + g['hall'].replace('HALL-', 'Hall ') + ')' if g['hall'] else ''} "
                                        f"{g['scheme']} would have {len(g['units']) - 2} of {len(g['units'])} for the overlap, below N ({g['need']})."})
    feeds = sorted([j for j in live if j["takes"] == "feed"], key=lambda j: (j["start"], j["id"]))
    for i, a in enumerate(feeds):
        for b in feeds[i + 1:]:
            ov = _overlap(a, b)
            if ov and a["rack"] == b["rack"] and a["unit"] != b["unit"]:
                out.append({"kind": "both_feeds", "jobs": [a["id"], b["id"]], "at": iso(ov[0]), "until": iso(ov[1]),
                            "rack": a["rack"], "hall": a["hall"],
                            "text": f"{a['id']} (feed {a['unit'][-1]}) and {b['id']} (feed {b['unit'][-1]}) overlap: rack {a['rack']} "
                                    "would have neither feed for the overlap."})
    sd = set(surge)
    f0, f1 = freeze
    fz = set(days(f0, f1))
    for j in sorted(live, key=lambda j: (j["start"], j["id"])):
        site_wide = bool(j["group"]) and G[j["group"]]["hall"] is None
        if site_wide or j["hall"] == "HALL-B":
            for d in _days_hit(j, sd):
                where = f"site-wide {G[j['group']]['name'].lower()}" if site_wide else "Hall B"
                out.append({"kind": "surge", "jobs": [j["id"]], "at": j["start"], "until": j["end"], "day": d, "hall": j["hall"],
                            "group": j["group"],
                            "text": f"{j['id']} takes {what(j)} out of service ({where}) on {d}, a surge day with {surge[d]} Hall B "
                                    "energizations."})
        if site_wide or j["hall"] == "HALL-C":
            for d in _days_hit(j, fz)[:1]:
                out.append({"kind": "freeze", "jobs": [j["id"]], "at": j["start"], "until": j["end"], "day": d, "hall": j["hall"],
                            "group": j["group"],
                            "text": f"{j['id']} takes {what(j)} out of service ({'site-wide ' + G[j['group']]['name'].lower() if site_wide else 'Hall C'}) "
                                    f"on {d}, inside the first-compute freeze ({f0} to {f1})."})
    return out


# ---------------------------------------------------------------- the devices (data weeks)
def device_actions(sample: Path = SAMPLE) -> dict[str, list[tuple[datetime, datetime | None, str]]]:
    """What each device recorded as taken out of service and put back: (start, end, record)."""
    f = sample / "facility"
    out: dict[str, list] = {}
    opened: dict[str, tuple[datetime, str]] = {}

    def start(unit: str, t: str, rec: str) -> None:
        opened.setdefault(unit, (parse(t), rec))

    def end(unit: str, t: str) -> None:
        if unit in opened:
            s, rec = opened.pop(unit)
            out.setdefault(unit, []).append((s, parse(t), rec))

    rows: list[tuple[str, str, str, str]] = []           # (time, unit, start|end, record)
    for x in _jsonl(f / "ups_nmc_events.jsonl"):
        if x["event"].startswith("upsBasicOutputStatus "):
            rows.append((x["timestamp"], x["ups"], "start" if x["event"].endswith("switchedBypass") else "end", "UPS NMC: maintenance bypass"))
    for x in _jsonl(f / "cdu_redfish_events.jsonl"):
        if x["property"] == "Status.State" and "/Pumps/" in x["resource"]:
            rows.append((x["timestamp"], f"PUMP:{x['cdu']}", "end" if x["value"] == "Enabled" else "start", "CDU Redfish: pump isolated"))
    for x in _jsonl(f / "bms_events.jsonl"):
        if x.get("point") == "Chiller enable":
            rows.append((x["timestamp"], x["device"], "start" if x["value"] == "Off" else "end", "BMS: chiller enable held Off"))
    for x in _jsonl(f / "busway_cpm_events.jsonl"):
        if x.get("point") == "Tap-off breaker":
            rows.append((x["timestamp"], x["tapoff"], "start" if x["event"] == "Breaker open" else "end", "Busway CPM: tap-off breaker open"))
    for x in _jsonl(f / "emcp_readings.jsonl"):
        st = x["engine_operating_state"]
        if st in ("Starting", "Stopped"):
            rows.append((x["timestamp"], x["generator"], "start" if st == "Starting" else "end", "EMCP: engine run"))
    for x in _jsonl(f / "vesda_events.jsonl"):
        if x["event"] in ("Isolate", "Normal"):
            rows.append((x["timestamp"], x["detector"], "start" if x["event"] == "Isolate" else "end", "VESDA: detector isolated"))
    for t, unit, kind, rec in sorted(rows):
        if kind == "start":
            start(unit, t, rec)
        else:
            end(unit, t)
    for unit, (s, rec) in opened.items():
        out.setdefault(unit, []).append((s, None, rec))
    return out


# ---------------------------------------------------------------- analysis
@dataclass
class Check:
    name: str
    title: str
    checked: int = 0
    misses: list[str] = field(default_factory=list)


def forward_jobs(cfg: dict[str, Any], G: dict[str, dict], racks: dict[str, str], layer: Path = LAYER,
                 schedule: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = schedule if schedule is not None else _json(layer / "schedule.json")
    return [make_job(r["id"], "Forward", r["owner"], r["title"], r["window_start"], r["window_end"], cfg, G, racks,
                     period="forward", note=r.get("note", "")) for r in rows]


def analyse(cfg: dict[str, Any] | None = None, root: Path = ROOT, sample: Path = SAMPLE, layer: Path = LAYER,
            schedule: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cfg = cfg or config()
    G, racks = groups(root), rack_halls(root, sample)
    past = past_jobs(cfg, G, racks, sample, root / "data" / "changes")
    fwd = forward_jobs(cfg, G, racks, layer, schedule)
    items = day_items(root)
    surge = surge_days(items, cfg)
    freeze = freeze_window(cfg)
    found = conflicts(past, G, surge, freeze) + conflicts(fwd, G, surge, freeze)

    # Agreements (data weeks)
    checks = {k: Check(k, t) for k, t in AGREEMENTS}
    cust = sample / "customer"
    pms = _csv(sample / "landlord" / "pm_records.csv")
    n_records = {"CAB": len(_json(cust / "cab_changes.json")), "MOP": len(_json(cust / "landlord_mop_approvals.json")),
                 "Queue": len(_json(root / "data" / "changes" / "pending_approvals.json")), "Maintenance": sum(1 for p in pms if not p["mop_ref"])}
    ids = [j["id"] for j in past]
    c = checks["records"]
    for src, n in n_records.items():
        c.checked += n
        got = sum(1 for j in past if j["source"] == src)
        if got != n:
            c.misses.append(f"{src}: {got} on the calendar, {n} in the records")
    for p in pms:
        if p["mop_ref"]:
            c.checked += 1
            if not any(j["id"] == p["mop_ref"] and p["task_id"] in j["refs"] for j in past):
                c.misses.append(f"{p['task_id']}: its MOP {p['mop_ref']} is not on the calendar")
    if len(set(ids)) != len(ids):
        c.misses.append("a record is on the calendar twice")
    c = checks["declared"]
    for d in _json(root / "data" / "changes" / "impact_declarations.json"):
        j = next((j for j in past if j["id"] == d["change_id"]), None)
        c.checked += 1
        if j is None or (j["takes"] != "none") != d["redundancy_reduced"] or j["type"] != d["type"]:
            c.misses.append(f"{d['change_id']}: declared {d['type']}, redundancy reduced {d['redundancy_reduced']}")
    c = checks["windows"]
    acts = device_actions(sample)
    for j in past:
        if not j["device"] or j["status"] == "deferred":
            continue
        s, e = parse(j["start"]), parse(j["end"])
        for a0, a1, rec in acts.get(j["device"], []):
            if s <= a0 <= e:
                c.checked += 1
                if a1 is None or a1 > e:
                    late = int(((a1 or e) - e).total_seconds() // 60)
                    also = ""
                    ev = [{"label": f"{j['device']} ({rec.split(': ')[0]})", "start": iso(a0), "end": iso(a1)}]
                    if j["takes"] == "feed":
                        other = f"TO-{j['rack']}-{'B' if j['unit'].endswith('A') else 'A'}"
                        for b0, b1, _ in acts.get(other, []):
                            if b0 < (a1 or e) and s < (b1 or e):
                                also = (f" The other feed's tap-off breaker was open from {hm_local(b0)} to {hm_local(b1) if b1 else 'the end of the data'}, so "
                                        f"rack {j['rack']} had neither feed for that time.")
                                ev.append({"label": f"{other} ({rec.split(': ')[0]})", "start": iso(b0), "end": iso(b1)})
                    c.misses.append(f"{j['id']}: {rec} until {iso(a1)}, {late} min after the window closed")
                    found.append({"kind": "overrun", "jobs": [j["id"]], "at": j["end"], "until": iso(a1), "hall": j["hall"],
                                  "group": j["group"], "rack": j["rack"], "minutes": late, "record": rec, "evidence": ev,
                                  "text": f"{j['id']} ({j['title']}) was booked until {hm_local(e)}; {rec.split(': ')[0]} shows "
                                          f"{rec.split(': ')[1]} until {hm_local(a1) if a1 else 'the end of the data'}, "
                                          f"{late // 60} h {late % 60:02d} min later.{also}"})
    explained = {"windows": sum(1 for f in found if f["kind"] == "overrun")}

    # Number the findings in time order, data weeks first
    found.sort(key=lambda f: (f["at"] >= at_local(cfg["forward"]["start"], 0).strftime("%Y-%m-%dT%H:%M:%SZ"), f["at"], f["kind"], f["jobs"]))
    jobs = {j["id"]: j for j in past + fwd}
    for n, f in enumerate(found, 1):
        f["id"] = f"CAL-{n}"
        f["period"] = jobs[f["jobs"][0]]["period"]
        f["title"] = KINDS[f["kind"]]
        f["action"] = ACTIONS[f["kind"]]
        f["owners"] = sorted({jobs[x]["owner"] for x in f["jobs"]})
    return {"jobs": past + fwd, "items": items, "surge": surge, "freeze": list(freeze), "groups": G, "findings": found,
            "agreements": list(checks.values()), "explained": explained, "records": n_records,
            "forward": cfg["forward"], "first_compute": cfg["forward"]["end"]}


def score(findings: list[dict[str, Any]], key: list[dict[str, Any]]) -> dict[str, int]:
    fwd = [f for f in findings if f["period"] == "forward"]
    hit = [k for k in key if any(f["kind"] == k["kind"] and k["job"] in f["jobs"] for f in fwd)]
    fp = [f for f in fwd if not any(f["kind"] == k["kind"] and k["job"] in f["jobs"] for k in key)]
    return {"planted": len(key), "found": len(hit), "false_positives": len(fp)}


def page_data(r: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the Calendar view and the report show."""
    cfg = cfg or config()
    r = r or analyse(cfg)
    used = sorted({j["group"] for j in r["jobs"] if j["group"]})
    G = r["groups"]
    past_days = days("2026-08-31", (date.fromisoformat(cfg["forward"]["start"]) - timedelta(days=1)).isoformat())
    fwd_days = days(cfg["forward"]["start"], cfg["forward"]["end"])
    keep = ("id", "source", "owner", "title", "type", "takes", "unit", "group", "rack", "hall", "start", "end", "status", "refs",
            "period", "note")
    jobs = [{k: j[k] for k in keep} for j in r["jobs"]]
    for j in jobs:
        if j["takes"] == "pump":
            j["unit"] = None                    # the page names the pump from the group ("Pump 2 of CDU-B3")
        j["day"] = local_day(parse(j["start"]))
        j["findings"] = [f["id"] for f in r["findings"] if j["id"] in f["jobs"]]
    finds = [{k: f.get(k) for k in ("id", "kind", "title", "period", "jobs", "at", "until", "hall", "group", "rack", "day", "text",
                                    "action", "owners", "minutes", "evidence")} for f in r["findings"]]
    for f in finds:
        f["date"] = f["day"] or local_day(parse(f["at"]))
    count = lambda per, kind=None: sum(1 for f in finds if f["period"] == per and (kind is None or f["kind"] == kind))
    return {
        "days": past_days + fwd_days, "past_days": len(past_days), "as_of": cfg["forward"]["start"], "first_compute": cfg["forward"]["end"],
        "freeze": r["freeze"], "surge": r["surge"], "surge_min": cfg["surge_min_energizations"], "freeze_days": cfg["freeze_days"],
        "jobs": jobs, "items": r["items"], "findings": finds,
        "groups": {k: {"name": G[k]["name"], "scheme": G[k]["scheme"], "hall": G[k]["hall"], "units": len(G[k]["units"]),
                       "need": G[k]["need"]} for k in used},
        "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": c.misses,
                        "explained": r["explained"].get(c.name, 0)} for c in r["agreements"]],
        "records": r["records"], "kinds": KINDS, "sources": SOURCES,
        "work_types": [{"type": w["type"], "takes": w["takes"], "owner": w["owner"]} for w in cfg["work_types"]],
        "summary": {"past": {"jobs": sum(1 for j in jobs if j["period"] == "past"), "findings": count("past"),
                             "by_kind": {k: count("past", k) for k in KINDS}},
                    "forward": {"jobs": sum(1 for j in jobs if j["period"] == "forward"), "findings": count("forward"),
                                "by_kind": {k: count("forward", k) for k in KINDS}},
                    "reduce": sum(1 for j in jobs if j["takes"] != "none" and j["status"] != "deferred")},
    }
