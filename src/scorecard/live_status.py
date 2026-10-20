"""Live status: the whole site minute by minute, for the Live tab (/live/) and the live strip on each Telemetry page.

Reads only what is already published: Site health's conditions and redundancy groups (src/scorecard/site_health.py),
each held for the minutes it lasts; the utility mains, the ride-through, every UPS and generator minute by minute
(data/telemetry/utility, data/telemetry/power, and their one-minute tiers); the busway hourly rows; the Alarm Board's
alarms and trouble tickets; the fire panel's history; and the security post log, door alarms, and visits. Nothing is
generated and nothing is judged: there are no findings here.

Two products:

``index``: the month in one file (conditions as minute spans, each family's state and each group's units by minute,
run-length encoded; Site health's hourly readings and rack states; the alarms, tickets, fire panel spans, door alarms,
posts, and visits as records with their times). The page and every Telemetry family page read it.

``days``: one file per day of the minute series the Power panel draws (mains, ride-through, UPSs, generators), so the
page loads a day at a time.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from . import site_health as SH

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "live.yaml"
DAY = 1440
FAMILIES = [(k, n, link) for k, n, link in SH.FAMILIES]


def load_config(path: str | Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def pack(a: np.ndarray) -> list:
    """An integer series as its first value and the minute-to-minute steps, [n] for n unchanged minutes (the
    telemetry tiers' encoding; the pages' unpackSteps reads it)."""
    a = np.asarray(a, dtype=np.int64)
    if not len(a):
        return []
    d = [int(a[0])] + np.diff(a).tolist()
    out: list = [d[0]]
    i, n = 1, len(d)
    while i < n:
        if d[i] == 0:
            j = i
            while j < n and d[j] == 0:
                j += 1
            out.extend([[j - i]] if j - i > 1 else [0])
            i = j
        else:
            out.append(int(d[i]))
            i += 1
    return out


def rle_min(a: np.ndarray) -> list[list[int]]:
    """[[value, minutes], ...] for a minute series that changes a few times a month."""
    return SH.rle([int(x) for x in a])


def _csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------------------------- conditions and states
def conditions(sh: SH.SiteHealth) -> list[dict[str, Any]]:
    """Site health's conditions as minute spans [a, b): identical conditions in consecutive minutes merge."""
    by: dict[tuple, set[int]] = defaultdict(set)
    for h, fam, hall, s, text, link, mk in sh.minute_issues:
        mins = range(60) if mk is None else np.flatnonzero(mk).tolist()
        by[(fam, hall, s, text, link)].update(h * 60 + m for m in mins)
    out = []
    for (fam, hall, s, text, link), ms in by.items():
        ms_ = sorted(ms)
        a = prev = ms_[0]
        for m in ms_[1:] + [None]:
            if m is not None and m == prev + 1:
                prev = m
                continue
            out.append({"a": a, "b": prev + 1, "family": fam, "hall": hall, "state": s, "text": text, "link": link,
                        **({"dir": direction(text)} if fam == "network" else {})})
            if m is not None:
                a = prev = m
    return sorted(out, key=lambda x: (x["a"], -x["state"], x["family"], x["text"]))


def direction(text: str) -> str:
    """East-West (GPU to GPU: InfiniBand and NVLink) or North-South (the storage and in-band Ethernet fabric)."""
    return "ew" if ("InfiniBand" in text or "NVLink" in text) else "ns"


def minute_states(conds: list[dict], M: int, halls: list[str]) -> tuple[dict, dict, np.ndarray]:
    """Each family's state by minute, site-wide and per hall, and the site's (the worst family)."""
    fam = {f: np.zeros(M, dtype=int) for f, _, _ in FAMILIES}
    hall = {h: {f: np.zeros(M, dtype=int) for f, _, _ in FAMILIES} for h in halls}
    for c in conds:
        sl = slice(c["a"], c["b"])
        fam[c["family"]][sl] = np.maximum(fam[c["family"]][sl], c["state"])
        if c["hall"]:
            hall[c["hall"]][c["family"]][sl] = np.maximum(hall[c["hall"]][c["family"]][sl], c["state"])
    site = np.max(np.stack(list(fam.values())), axis=0)
    return fam, hall, site


# ---------------------------------------------------------------------------------------------- the month index
def index(sh: SH.SiteHealth, data: dict[str, Any], power, util, alarms: dict, fire: dict, cfg: dict | None = None,
          sec_dir: Path | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    M, H = sh.M, sh.H
    st = states(sh, data)
    page = SH.page_data(data)
    pdev = power.manifest["devices"]
    ups = {u: {k: pdev[u][k] for k in ("hall", "kind", "rating_kw", "model")} for u in power.devices("ups")}
    gens = power.devices("generator")
    # the busway by hour: the most loaded run and the warmest enclosure
    bw: dict[int, list] = {}
    for r in power.busway_hourly:
        h = int((_parse(r["hour"]) - sh.start).total_seconds() // 3600)
        cur = bw.setdefault(h, [None, -1.0, None, -1.0])
        if float(r["amps_max"]) > cur[1]:
            cur[0], cur[1] = r["run"], float(r["amps_max"])
        if r["encl_max_c"] and float(r["encl_max_c"]) > cur[3]:
            cur[2], cur[3] = r["run"], float(r["encl_max_c"])
    um = util.manifest
    (o,) = um["outages"] or [None]
    a07 = alarms["a07"]["first_flag"]["raised"]
    jumps = []
    for j in cfg["clock"]["jumps"]:
        at = o["trip"] if j["key"] == "trip" else a07
        m = int((_parse(at) - sh.start).total_seconds() // 60) - j["lead_min"]
        jumps.append({"key": j["key"], "label": j["label"], "m": max(0, m)})
    sec = security(sec_dir or ROOT / "data" / "security", cfg)
    return {
        "window": sh.window, "minutes": M, "hours": H, "days": M // DAY, "framing": cfg["framing"],
        "halls": page["halls"], "planned": page["planned"],
        "families": [{"key": k, "name": n, "link": link} for k, n, link in FAMILIES],
        **st,
        "readings": page["readings"], "racks": page["racks"], "thresholds": page["thresholds"],
        "power": {"ups": ups, "generators": gens, "mains": {b: {"ups": x["ups"], "breaker": x["breaker"]} for b, x in um["mains"].items()},
                  "scopes": um["scopes"], "outages": um["outages"], "design_take_load_s": _util_cfg()["ride_through"]["design_take_load_s"],
                  "runtime_cap_s": _power_cfg()["ups"]["battery"]["runtime_cap_min"] * 60,
                  "busway": {"rating_a": cfg["power"]["busway_rating_a"], "hours": [bw.get(h) for h in range(H)]}},
        "alarms": [{"id": a["id"], "t": a["raised"], "tc": a["cleared"], "severity": a["severity"], "device": a["device"],
                    "summary": a["summary"], "partner": a["partner"]} for a in alarms["alarms"]],
        "tickets": [{"id": k["id"], "t": k["opened"], "tc": k["closed"], "priority": k["priority"], "partner": k["partner"],
                     "device": k["device"], "summary": k["summary"]} for k in alarms["tickets"]],
        "fire": {"rule": cfg["fire"]["out_of_service"],
                 "out": [s for s in fire["spans"] if s["signal"] == "Disable" or (s["signal"] == "Supervisory" and s["device"].split("-")[0] in ("PAZ", "CAS"))]},
        "security": sec,
        "jumps": jumps, "speeds": cfg["clock"]["speeds"], "history_min": cfg["clock"]["history_min"],
    }


def states(sh: SH.SiteHealth, data: dict[str, Any]) -> dict[str, Any]:
    """The conditions as minute spans, each family's and the site's state by minute, and each group's units by minute."""
    conds = conditions(sh)
    fam, hall, site = minute_states(conds, sh.M, sh.hall_ids)
    groups = []
    for g in data["groups"]:
        am, sm = sh.group_minutes[g["key"]]
        groups.append({k: g[k] for k in ("key", "name", "scheme", "hall", "family", "link", "unit_word")}
                      | {"avail": rle_min(am), "total": rle_min(np.repeat(np.asarray(g["total"]), 60)), "state": rle_min(sm)})
    return {"conditions": conds, "family_state": {f: rle_min(v) for f, v in fam.items()},
            "hall_state": {h: {f: rle_min(v) for f, v in x.items()} for h, x in hall.items()}, "site_state": rle_min(site), "groups": groups}


def _util_cfg() -> dict:
    return yaml.safe_load((ROOT / "config" / "telemetry_utility.yaml").read_text(encoding="utf-8"))


def _power_cfg() -> dict:
    return yaml.safe_load((ROOT / "config" / "telemetry_power.yaml").read_text(encoding="utf-8"))


def security(d: Path, cfg: dict) -> dict[str, Any]:
    """Door alarms with their times, the posts by shift as the post log reports them, and visits signed in and out."""
    doors = [json.loads(x) for x in (d / "door_alarms.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    shift = timedelta(hours=cfg["security"]["shift_h"])
    posts = [{"from": r["shift_start"], "to": (_parse(r["shift_start"]) + shift).strftime("%Y-%m-%dT%H:%M:%SZ"), "shift": r["shift"],
              "post": r["post"], "reported": r["reported"]} for r in _csv(d / "post_log.csv")]
    visits = [{"id": r["visit_id"], "company": r["company"], "hall": r["hall"], "escort_party": r["escort_party"],
               "in": r["signed_in"], "out": r["signed_out"]} for r in _csv(d / "visits.csv")]
    return {"note": cfg["security"]["note"],
            "doors": [{k: a[k] for k in ("alarm_id", "door", "event", "priority", "timestamp", "cleared_at")} for a in doors],
            "posts": posts, "visits": visits}


# ---------------------------------------------------------------------------------------------- the day files
def days(power, util) -> list[dict[str, Any]]:
    """One file per day: each main's average line-to-line voltage, average phase current, kW, PF, frequency, and
    breaker; the ride-through for every scope and the UPS that sets it; each UPS's output, source, runtime, and charge;
    each generator's state, output, breaker, and fuel. Values keep each tier's integer scale."""
    M = util.M
    mains = {}
    for b in util.manifest["mains"]:
        x = util.minutes(b)
        mains[b] = {"v": np.rint((x["v_ab"] + x["v_bc"] + x["v_ca"]) / 3).astype(np.int64),
                    "a": np.rint((x["a_a"] + x["a_b"] + x["a_c"]) / 3).astype(np.int64),
                    "kw": x["kw"], "pf": x["pf"], "hz": x["hz"], "brk": x["brk"]}
    ride = util.ride()
    ups = {u: {"kw": power.minutes(u)["out_kw"], "src": power.minutes(u)["source"], "rt": power.minutes(u)["runtime_s"],
               "soc": power.minutes(u)["soc_pct"]} for u in power.devices("ups")}
    gens = {g: {"st": power.minutes(g)["state"], "kw": power.minutes(g)["kw"], "brk": power.minutes(g)["brk"],
                "fuel": power.minutes(g)["fuel_pct"]} for g in power.devices("generator")}
    out = []
    for d in range(M // DAY):
        sl = slice(d * DAY, (d + 1) * DAY)
        out.append({"day": d, "from": d * DAY, "minutes": DAY,
                    "encoding": "first value, then minute-to-minute steps; [n] is n minutes unchanged",
                    "scales": {"mains": {"v": 1, "a": 10, "kw": 10, "pf": 1000, "hz": 100, "brk": 1}, "ride": {"s": 1, "k": 1},
                               "ups": {"kw": 10, "src": 1, "rt": 1, "soc": 1}, "gen": {"st": 1, "kw": 10, "brk": 1, "fuel": 10}},
                    "mains": {b: {k: pack(v[sl]) for k, v in x.items()} for b, x in mains.items()},
                    "ride": {s: {"s": pack(x["s"][sl]), "k": pack(x["k"][sl])} for s, x in ride.items()},
                    "ups": {u: {k: pack(v[sl]) for k, v in x.items()} for u, x in ups.items()},
                    "gen": {g: {k: pack(v[sl]) for k, v in x.items()} for g, x in gens.items()}})
    return out


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True) + "\n"


def manifest(idx: dict[str, Any], day_files: list[dict[str, Any]], checks: list) -> dict[str, Any]:
    """What a build publishes, with checksums (the files themselves are built with the site), and the reconciliation."""
    files = {"index.json": hashlib.sha256(dumps(idx).encode()).hexdigest()}
    for d in day_files:
        files[f"day_{d['day']:02d}.json"] = hashlib.sha256(dumps(d).encode()).hexdigest()
    return {"window": idx["window"], "minutes": idx["minutes"], "conditions": len(idx["conditions"]),
            "files": files, "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks]}


# ---------------------------------------------------------------------------------------------- reconciliation
def agreements(sh: SH.SiteHealth, data: dict[str, Any], idx: dict[str, Any], day_files: list[dict], util) -> list:
    """The live page against what it was built from.

    1. families: the worst minute of every hour equals Site health's state for that hour, site-wide and per hall.
    2. groups: the worst minute of every hour equals each redundancy group's hourly state.
    3. units: a group counted unit by unit has, at its worst minute, the units Site health shows for the hour.
    4. mains: the day files carry the mains' minutes unchanged (kW summed over the day equals the published tier).
    5. ride_through: the day files carry the published ride-through for every scope and minute.
    """
    from .telemetry import Check
    H = sh.H
    unrle = lambda r: np.asarray(SH.unrle(r))
    c1 = Check("families", "The worst minute of every hour equals Site health's state for that hour, for every family, site-wide and per hall")
    for f, _, _ in FAMILIES:
        hm = unrle(idx["family_state"][f]).reshape(H, 60).max(1)
        for h in range(H):
            c1(int(hm[h]) == int(data["family_state"][f][h]), f"{f} hour {h}: live {hm[h]}, Site health {data['family_state'][f][h]}")
        for hl in sh.hall_ids:
            hm = unrle(idx["hall_state"][hl][f]).reshape(H, 60).max(1)
            for h in range(H):
                c1(int(hm[h]) == int(data["hall_state"][hl][f][h]), f"{hl} {f} hour {h}: live {hm[h]}, Site health {data['hall_state'][hl][f][h]}")
    hm = unrle(idx["site_state"]).reshape(H, 60).max(1)
    for h in range(H):
        c1(int(hm[h]) == int(data["site_state"][h]), f"site hour {h}")
    c2 = Check("groups", "The worst minute of every hour equals each redundancy group's state for that hour")
    c3 = Check("units", "Each group counted unit by unit has, at its worst minute of the hour, Site health's units for that hour")
    per_unit = {"utility", "generators", "chillers", "fwpumps"} | {g["key"] for g in data["groups"] if g["key"].split("-")[0] in ("ups", "mups", "cdu", "walls", "crah", "oob", "stg", "spine", "storage_leaf")}
    for g, lg in zip(data["groups"], idx["groups"]):
        st, av = unrle(lg["state"]).reshape(H, 60), unrle(lg["avail"]).reshape(H, 60)
        for h in range(H):
            c2(int(st[h].max()) == int(g["state"][h]), f"{g['key']} hour {h}: live {st[h].max()}, Site health {g['state'][h]}")
            if g["key"] in per_unit:
                c3(int(av[h].min()) == int(g["avail"][h]), f"{g['key']} hour {h}: live {av[h].min()}, Site health {g['avail'][h]}")
    from .telemetry_power import unpack
    c4 = Check("mains", "The day files carry each main's published minutes unchanged")
    c5 = Check("ride_through", "The day files carry the published ride-through for every scope and minute")
    ride = util.ride()
    for d in day_files:
        sl = slice(d["from"], d["from"] + d["minutes"])
        for b, x in d["mains"].items():
            pub = util.minutes(b)
            for k in ("kw", "pf", "hz", "brk"):
                c4(bool(np.array_equal(unpack(x[k]), pub[k][sl])), f"day {d['day']} {b} {k}")
        for s, x in d["ride"].items():
            c5(bool(np.array_equal(unpack(x["s"]), ride[s]["s"][sl]) and np.array_equal(unpack(x["k"]), ride[s]["k"][sl])), f"day {d['day']} {s}")
    return [c1, c2, c3, c4, c5]
