"""Site health: the whole site at any hour of the month, from the committed telemetry (the Telemetry tab's landing page).

Reads only what the six telemetry sections already publish (data/telemetry/: the hourly tiers and each section's
recorded state changes), the scheduler's node states (when a Hall B rack was handed over), and the topology in
site/site.yaml. Nothing new is generated and nothing is judged: there are no findings here.

Three things per hour, each hour showing its worst minute:

1. Redundancy, the headline. Units in service against the units the design needs (N+1, 2N, 4 make 3), for the
   utility feeds, generators, UPSs, rack feeds, CDUs and their pumps, chillers, facility water pumps, thermal walls
   and their fans, and the electrical-room CRAHs. A unit is out for any minute a recorded state change says so.
2. Each device family's main readings with a green, amber, or red state from thresholds in config/site_health.yaml,
   and the conditions behind any state that is not green.
3. Every rack's state for the hall map.

``agreements`` checks the dashboard's state against the published hourly figures it was not built from: the minutes
of bypass, feeder trips, chiller alarms and BMS holds, fan failures, and dark racks each section reports by the hour.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .telemetry import Check

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "site_health.yaml"

OFF, GREEN, AMBER, RED = -1, 0, 1, 2
STATE_NAME = {OFF: "not in service", GREEN: "normal", AMBER: "degraded", RED: "lost"}
FAMILIES = [("gpu", "GPUs", "gpus"), ("cdu", "CDUs", "cdus"), ("power", "Power", "power"), ("network", "Network", "network"),
            ("mechanical", "Mechanical", "mechanical"), ("mgmt", "Management network", "management"), ("storage", "Storage", "storage")]
GPUS_PER_RACK = 72


def load_config(path: str | Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def rle(v: list) -> list[list]:
    """[[value, count], ...]: the page's compact form of an hourly series."""
    out: list[list] = []
    for x in v:
        if out and out[-1][0] == x:
            out[-1][1] += 1
        else:
            out.append([x, 1])
    return out


def unrle(r: list[list]) -> list:
    return [v for v, n in r for _ in range(n)]


@dataclass
class Dirs:
    gpu: Path
    cdu: Path
    power: Path
    network: Path
    mechanical: Path
    sample: Path
    mgmt: Path | None = None
    storage: Path | None = None

    @classmethod
    def committed(cls, root: Path = ROOT) -> "Dirs":
        t = root / "data" / "telemetry"
        return cls(t / "gpu", t / "cdu", t / "power", t / "network", t / "mechanical", root / "data" / "sample", t / "mgmt", t / "storage")


class SiteHealth:
    """Every hour's redundancy, family readings and states, and rack states. ``build()`` returns the page's data."""

    def __init__(self, dirs: Dirs, site: dict[str, Any], cfg: dict[str, Any] | None = None):
        self.d, self.site, self.cfg = dirs, site, cfg or load_config()
        man = json.loads((dirs.gpu / "manifest.json").read_text(encoding="utf-8"))
        self.window = man["window"]
        self.start = _parse(self.window["start"])
        self.H = int((_parse(self.window["end"]) - self.start).total_seconds() // 3600)
        self.M = self.H * 60
        self.halls = [h for h in site["halls"] if h["state"] != "planned"]
        self.hall_ids = [h["id"] for h in self.halls]
        self.planned = [h for h in site["halls"] if h["state"] == "planned"]
        self.power_dev = json.loads((dirs.power / "manifest.json").read_text(encoding="utf-8"))["devices"]
        self.mech_dev = json.loads((dirs.mechanical / "manifest.json").read_text(encoding="utf-8"))["devices"]
        self.cdu_dev = json.loads((dirs.cdu / "manifest.json").read_text(encoding="utf-8"))["cdus"]
        self.rack_rows = _csv(dirs.gpu / "rack_hourly.csv")
        self._load_states()
        self._load_mgmt()
        self._load_storage()
        self._racks()

    # ------------------------------------------------------------------ helpers
    def hour_of(self, iso: str) -> int:
        return int((_parse(iso) - self.start).total_seconds() // 3600)

    def hourly(self, rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
        """Rows by device, in hour order, one per hour of the window."""
        out: dict[str, list] = defaultdict(lambda: [None] * self.H)
        for r in rows:
            h = self.hour_of(r["hour"])
            if 0 <= h < self.H:
                out[r[key]][h] = r
        return dict(out)

    def _spans(self, changes: list[tuple[int, Any, float]], is_out, seconds: bool = False) -> np.ndarray:
        """Minute mask: out from each change whose value is_out until the next change that is not. Each change is
        (minute, value, seconds from the window start). By default a change takes effect at the minute its own tier
        records (the first reading at or after it); with seconds, a minute counts if any second of it is out, as the
        UPS hourly rows count bypass minutes."""
        mask = np.zeros(self.M, dtype=bool)
        since = None
        for m, v, t in sorted(changes, key=lambda x: x[2]):
            a, b = (math.floor(t / 60), math.ceil(t / 60)) if seconds else (m, m)
            if is_out(v) and since is None:
                since = a
            elif not is_out(v) and since is not None:
                mask[max(0, since):max(0, min(self.M, b))] = True
                since = None
        if since is not None:
            mask[max(0, since):] = True
        return mask

    def sec(self, iso: str) -> float:
        return (_parse(iso) - self.start).total_seconds()

    def hour_any(self, mask: np.ndarray) -> np.ndarray:
        return mask.reshape(self.H, 60).any(axis=1)

    def hour_max(self, minute_counts: np.ndarray) -> np.ndarray:
        return minute_counts.reshape(self.H, 60).max(axis=1)

    # ------------------------------------------------------------------ recorded state changes -> units out
    def _load_states(self) -> None:
        """Minute masks of every unit out of service, from each section's recorded state changes."""
        out: dict[str, np.ndarray] = {}
        why: dict[str, list[tuple[np.ndarray, str]]] = defaultdict(list)
        by: dict[tuple, list] = defaultdict(list)
        for e in _jsonl(self.d.power / "states.jsonl"):
            by[("power", e["device"], e["point"])].append((e["m"], e["value"], self.sec(e["time"])))
        for e in _jsonl(self.d.mechanical / "states.jsonl"):
            by[("mech", e["device"], e["point"])].append((e["m"], e["value"], self.sec(e["time"])))
        for e in _jsonl(self.d.cdu / "states.jsonl"):
            by[("cdu", e["resource"], e["property"])].append((e["m"], e["value"], self.sec(e["time"])))

        def add(unit: str, mask: np.ndarray, text: str) -> None:
            if mask.any():
                out[unit] = out[unit] | mask if unit in out else mask
                why[unit].append((mask, text))

        # utility: each MV main breaker
        for bus in self.site["plants"]["mv_switchgear"]["buses"]:
            ch = by.get(("power", "SITE", f"{bus} main breaker"), [])
            add(f"MV:{bus}", self._spans(ch, lambda v: str(v).startswith("Trip")), "main breaker tripped")
        # UPSs: static bypass
        for u, x in self.power_dev.items():
            if x["family"] == "ups":
                ch = by.get(("power", u, "upsBasicOutputStatus"), [])
                add(u, self._spans(ch, lambda v: v == "switchedBypass", seconds=True), "on static bypass")
        # rack feeds: the tap-off breaker, or the busway's feeder breaker
        self.run_trip: dict[str, np.ndarray] = {}
        for run, x in self.power_dev.items():
            if x["family"] == "busway":
                # dead from the feeder breaker's trip until the busway's own meter reads voltage in tolerance again
                ch = by.get(("power", run, "Feeder breaker (EPMS)"), [])
                volts = by.get(("power", run, "cpmAcInfLineToLineVoltAve"), [])
                self.run_trip[run] = (self._spans(ch, lambda v: str(v).startswith("Breaker trip"))
                                      | self._spans(volts, lambda v: "out of tolerance" in str(v)))
        for to, x in self.power_dev.items():
            if x["family"] == "tapoff":
                ch = by.get(("power", to, "cpmAcBrkrCurrentStatus"), [])
                add(f"FEED:{x['rack']}:{x['side']}", self._spans(ch, lambda v: v == "open"), f"tap-off {to} open")
                add(f"FEED:{x['rack']}:{x['side']}", self.run_trip[x["run"]], f"busway {x['run']} without voltage (feeder breaker tripped)")
        # CDU pumps
        n_pumps = 2
        for cdu, x in self.cdu_dev.items():
            for p in range(1, n_pumps + 1):
                res = f"{x['uri']}/Pumps/{p}"
                state = by.get(("cdu", res, "Status.State"), [])
                hl = self._spans(by.get(("cdu", res, "Status.Health"), []), lambda v: v == "Critical")
                add(f"PUMP:{cdu}:{p}", hl, f"pump {p} failed")
                add(f"PUMP:{cdu}:{p}", self._spans(state, lambda v: v == "Disabled") & ~hl, f"pump {p} isolated for planned work")
                add(f"PUMP:{cdu}:{p}", self._spans(state, lambda v: v == "InTest") & ~hl, f"pump {p} in test after repair")
        # chillers: held off by the BMS, or a compressor trip
        for ch_id, x in self.mech_dev.items():
            if x["family"] != "chiller":
                continue
            hold = self._spans(by.get(("mech", ch_id, "Chiller enable"), []), lambda v: str(v).startswith("Off"))
            trip = np.zeros(self.M, dtype=bool)
            for (src, dev, pt), chg in by.items():
                if src == "mech" and dev == ch_id and pt != "Chiller enable" and any(v in ("active", "cleared") for _, v, _ in chg):
                    trip |= self._spans(chg, lambda v: v == "active")
            add(ch_id, hold, "held off by the BMS (planned maintenance)")
            add(ch_id, trip, "compressor trip")
        # thermal-wall fans
        for (src, dev, pt), chg in by.items():
            m = re.fullmatch(r"FanSts_OV\[(\d+)\]", pt)
            if src == "mech" and m:
                add(f"FAN:{dev}:{m.group(1)}", self._spans(chg, lambda v: v == "Alarm"), f"fan {m.group(1)} failed")
        # leaks (a reading, not a unit out)
        self.leak: dict[str, list[tuple[np.ndarray, str]]] = defaultdict(list)
        for (src, res, prop), chg in by.items():
            if src == "cdu" and prop == "DetectorState":
                cdu = res.split("/CDUs/")[1].split("/")[0]
                note = next((e.get("note") for e in _jsonl(self.d.cdu / "states.jsonl") if e["resource"] == res and e.get("note")), "")
                self.leak[cdu].append((self._spans(chg, lambda v: v == "Critical"), note))
        self.out, self.out_why = out, why

    def _load_mgmt(self) -> None:
        """The management network, replayed from its trap log (src/scorecard/telemetry_mgmt.py): each switch's minutes up
        and ports, the rack power losses, and the collector's own restarts. An aggregation switch is out while it is down."""
        self.mg = None
        if not self.d.mgmt or not (self.d.mgmt / "manifest.json").exists():
            return
        from . import telemetry_mgmt as TG
        self.mg = TG.load(self.d.mgmt, self.d.sample)
        self.mg_rep = TG.replay_ports(self.mg)
        self.mg_loss = TG.power_losses(self.mg)
        self.mg_unpolled = TG.unpolled(self.mg)
        for s, o in self.mg_rep.items():
            if self.mg.manifest["devices"][s]["family"] == "agg":
                down = o["up"] == 0
                if down.any():
                    self.out[s] = down
                    self.out_why[s].append((down, "down (no SNMP answer, its rack-switch ports dark)"))

    def _load_storage(self) -> None:
        """The storage clusters and their fabric (src/scorecard/telemetry_storage.py): each node's minutes online and drive
        bays, replayed from its event logs, and every fabric port from the trap log."""
        self.sg = None
        if not self.d.storage or not (self.d.storage / "manifest.json").exists() or self.mg is None:
            return
        from . import telemetry_storage as TS
        self.sg = TS.load(self.d.storage, self.d.sample, self.d.mgmt)
        self.sg_online = TS.node_online(self.sg)
        self.sg_bays, _, _ = TS.replay_bays(self.sg)
        self.sg_links = TS.replay_links(self.sg)
        self.sg_flaps = TS.flaps(self.sg, yaml.safe_load((ROOT / "config" / "telemetry_storage.yaml").read_text(encoding="utf-8")), self.sg_links)
        for n, on in self.sg_online.items():
            off = ~on
            if off.any():
                self.out[n] = off
                self.out_why[n].append((off, "offline"))

    def sg_degraded(self, node: str) -> np.ndarray:
        """A storage node counts against its cluster's protection while it is offline or holds a drive that is failed,
        pulled, or rebuilding."""
        return ~self.sg_online[node] | (self.sg_bays[node] != 0).any(0)

    def why(self, unit: str, h: int) -> str:
        """Why a unit is out during hour h (each recorded reason that overlaps the hour)."""
        return " then ".join(dict.fromkeys(t for m, t in self.out_why.get(unit, []) if m[h * 60:(h + 1) * 60].any()))

    def unit_out(self, unit: str) -> np.ndarray:
        return self.out.get(unit, np.zeros(self.M, dtype=bool))

    # ------------------------------------------------------------------ racks
    def _racks(self) -> None:
        """Each rack's place on the hall map, its CDU and feeds, and from when it is in service."""
        self.rack_hourly = self.hourly(self.rack_rows, "rack")
        handoff: dict[str, int] = {}
        for s in _jsonl(self.d.sample / "telemetry" / "scheduler_node_states.jsonl"):
            if s["reason"] == "validated handoff":
                r = s["node"][:3].upper()
                handoff[r] = min(handoff.get(r, 10 ** 9), max(0, self.hour_of(s["timestamp"])))
        self.racks: dict[str, dict] = {}
        for hall in self.halls:
            letter, per = hall["letter"], hall["racks_per_row"]
            for i in range(hall["rows"] * per):
                rid = f"{letter}{i + 1:02d}"
                rows = self.rack_hourly.get(rid, [None] * self.H)
                first = next((h for h, r in enumerate(rows) if r and int(r["gpus_reporting"]) > 0), None)
                prod = hall["state"] == "production"
                self.racks[rid] = {"rack": rid, "hall": hall["id"], "row": i // per + 1, "pos": i % per + 1,
                                   "cdu": f"CDU-{letter}{i // per + 1}", "first": first,
                                   "handoff": 0 if prod else handoff.get(rid)}

    def rack_state(self, rid: str, feeds_out: np.ndarray, nv: dict[str, list]) -> tuple[list[int], list[list[str]]]:
        """Per hour: the rack's state and the conditions behind it."""
        x, rows = self.racks[rid], self.rack_hourly.get(rid, [None] * self.H)
        thr = self.cfg["thresholds"]["gpu"]
        st, why = [OFF] * self.H, [[] for _ in range(self.H)]
        for h in range(self.H):
            r = rows[h]
            if x["first"] is None or h < x["first"] or r is None:
                continue
            s, w = GREEN, why[h]
            g = int(r["gpus_reporting"])
            if g == 0:
                s, _ = RED, w.append("no GPUs reporting")
            elif g < GPUS_PER_RACK:
                s, _ = max(s, AMBER), w.append(f"{GPUS_PER_RACK - g} GPU{'s' if GPUS_PER_RACK - g > 1 else ''} not reporting all hour")
            if int(r["nodes_drained"]):
                s, _ = max(s, AMBER), w.append(f"{r['nodes_drained']} node{'s' if int(r['nodes_drained']) > 1 else ''} drained")
            if int(r["thermal_violation_s"]):
                s, _ = max(s, AMBER), w.append("hardware thermal slowdown")
            elif r["gpu_temp_max_c"] and int(r["gpu_temp_max_c"]) >= thr["temp_amber_c"]:
                s, _ = max(s, AMBER), w.append(f"GPU at {r['gpu_temp_max_c']} C")
            fo = feeds_out[h]
            if fo >= 2:
                s, _ = RED, w.append("both power feeds lost")
            elif fo == 1:
                s, _ = max(s, AMBER), w.append("one power feed lost (no redundancy)")
            t = nv.get(rid, [None] * self.H)[h]
            if g > 0 and t is not None and int(t["trays_reporting"]) < 9:
                s, _ = max(s, AMBER), w.append(f"{9 - int(t['trays_reporting'])} NVLink tray{'s' if 9 - int(t['trays_reporting']) > 1 else ''} not reporting")
            if x["handoff"] is None or h < x["handoff"]:
                w.insert(0, "commissioning (not yet handed over)")
            st[h] = s
        return st, why

    # ------------------------------------------------------------------ build
    def build(self) -> dict[str, Any]:
        H, thr = self.H, self.cfg["thresholds"]
        issues: list[tuple[int, str, str | None, int, str, str]] = []      # (hour, family, hall, state, text, link)

        def issue(h: int, fam: str, hall: str | None, s: int, text: str, link: str) -> None:
            issues.append((h, fam, hall, s, text, link))

        # ---- rack feeds and rack states
        nv = self.hourly(_csv(self.d.network / "nvlink_hourly.csv"), "rack")
        feeds_out: dict[str, np.ndarray] = {}
        for rid in self.racks:
            cnt = self.unit_out(f"FEED:{rid}:A").astype(int) + self.unit_out(f"FEED:{rid}:B").astype(int)
            feeds_out[rid] = self.hour_max(cnt)
        racks = {}
        for rid, x in self.racks.items():
            st, why = self.rack_state(rid, feeds_out[rid], nv)
            racks[rid] = {**x, "state": st, "why": why}
            for h in range(H):
                for w in why[h]:
                    if w.startswith("commissioning"):
                        continue
                    fam = "power" if "feed" in w else "network" if "NVLink" in w else "gpu"
                    s = RED if w in ("no GPUs reporting", "both power feeds lost") else AMBER
                    issue(h, fam, x["hall"], s, f"{rid}: {w}", rid if fam != "power" else rid)

        def in_service(h: int, hall: str | None = None) -> list[str]:
            return [r for r, x in racks.items() if x["state"][h] != OFF and (hall is None or x["hall"] == hall)]

        # ---- redundancy groups
        groups: list[dict] = []

        def group(key: str, name: str, scheme: str, hall: str | None, family: str, units: list[str], need: int, link: str) -> None:
            cnt = np.zeros(self.M, dtype=int)
            for u in units:
                cnt += self.unit_out(u)
            avail = [len(units) - int(v) for v in self.hour_max(cnt)]
            tot, need_l, unit_word = [len(units)] * H, [need] * H, ""
            state = [OFF if t == 0 else RED if a < n else AMBER if a < t else GREEN for a, t, n in zip(avail, tot, need_l)]
            groups.append({"key": key, "name": name, "scheme": scheme, "hall": hall, "family": family, "link": link,
                           "units": units, "unit_word": unit_word, "need": need_l, "avail": avail, "total": tot, "state": state})
            for h in range(H):
                if state[h] in (AMBER, RED):
                    downs = [u for u in units if self.unit_out(u)[h * 60:(h + 1) * 60].any()]
                    detail = "; ".join(f"{self.label(u)} {self.why(u, h)}" for u in downs) if downs else ""
                    txt = f"{name}{' (' + self.hall_name(hall) + ')' if hall else ''}: {avail[h]} of {tot[h]}{' ' + unit_word if unit_word else ''}, {('site on generators' if key == 'utility' else 'below N') if state[h] == RED else 'no redundant unit'}"
                    issue(h, family, hall, state[h], txt + (f" ({detail})" if detail else ""), downs[0] if downs and not downs[0].startswith("MV:") else link)

        buses = self.site["plants"]["mv_switchgear"]["buses"]
        group("utility", "Utility feeds", "2N", None, "power", [f"MV:{b}" for b in buses], 1, "power")
        gen = self.site["plants"]["generators"]
        group("generators", "Generators", f"N+{gen['redundancy']}", None, "power",
              [g for g, x in self.power_dev.items() if x["family"] == "generator"], gen["count"] - gen["redundancy"], "power")
        for hall in self.halls:
            hid, P = hall["id"], hall["power"]
            ups = sorted(u for u, x in self.power_dev.items() if x["family"] == "ups" and x["hall"] == hid and x["kind"] == "it")
            group(f"ups-{hid}", "IT UPSs", f"{P['ups_count']} make {P['ups_count'] - 1}", hid, "power", ups, P["ups_count"] - 1, ups[0])
            mups = sorted(u for u, x in self.power_dev.items() if x["family"] == "ups" and x["hall"] == hid and x["kind"] == "mech")
            group(f"mups-{hid}", "Mechanical UPSs", "2N", hid, "power", mups, 1, mups[0])
            # rack feeds: racks in service with both feeds
            rk = [r for r, x in racks.items() if x["hall"] == hid]
            tot = [len(in_service(h, hid)) for h in range(H)]
            both = [sum(1 for r in in_service(h, hid) if feeds_out[r][h] == 0) for h in range(H)]
            # a rack with one feed is at N (amber); with none, below N (red)
            st = [OFF if t == 0 else RED if any(feeds_out[r][h] >= 2 for r in in_service(h, hid)) else AMBER if b < t else GREEN
                  for h, (b, t) in enumerate(zip(both, tot))]
            groups.append({"key": f"feeds-{hid}", "name": "Rack feeds", "scheme": "2N", "hall": hid, "family": "power",
                           "link": "power", "units": rk, "unit_word": "racks with both feeds", "need": tot, "avail": both,
                           "total": tot, "state": st})
            # CDUs (unit level) and their pumps
            C = hall["cooling"]
            cdus = sorted(c for c, x in self.cdu_dev.items() if x["hall"] == hid)
            group(f"cdu-{hid}", "CDUs", f"N+{C['cdu_redundancy']}", hid, "cdu", cdus, len(cdus) - C["cdu_redundancy"], "cdus")
            spare = [sum(1 for c in cdus if not any(self.unit_out(f"PUMP:{c}:{p}")[h * 60:(h + 1) * 60].any() for p in (1, 2))) for h in range(H)]
            pumps_out = {c: self.hour_max(self.unit_out(f"PUMP:{c}:1").astype(int) + self.unit_out(f"PUMP:{c}:2").astype(int)) for c in cdus}
            st = [RED if any(pumps_out[c][h] >= 2 for c in cdus) else AMBER if s < len(cdus) else GREEN for h, s in enumerate(spare)]
            groups.append({"key": f"pumps-{hid}", "name": "CDU pumps", "scheme": "N+1 in each CDU", "hall": hid, "family": "cdu",
                           "link": "cdus", "units": cdus, "unit_word": "CDUs with a spare pump", "need": [len(cdus)] * H,
                           "avail": spare, "total": [len(cdus)] * H, "state": st})
            for h in range(H):
                for c in cdus:
                    downs = [p for p in (1, 2) if self.unit_out(f"PUMP:{c}:{p}")[h * 60:(h + 1) * 60].any()]
                    if downs:
                        issue(h, "cdu", hid, RED if len(downs) == 2 else AMBER,
                              f"{c}: {'; '.join(self.why(f'PUMP:{c}:{p}', h) for p in downs)}, no spare pump", c)
            walls = sorted(w for w, x in self.mech_dev.items() if x["family"] == "wall" and x.get("hall") == hid)
            if walls:
                group(f"walls-{hid}", "Thermal walls", f"N+{C['thermal_wall_redundancy']}", hid, "mechanical", walls,
                      len(walls) - C["thermal_wall_redundancy"], walls[0])
            crahs = sorted(w for w, x in self.mech_dev.items() if x["family"] == "crah" and x.get("hall") == hid)
            if crahs:
                group(f"crah-{hid}", "Electrical-room CRAHs", f"N+{C['electrical_room_crah_redundancy']}", hid, "mechanical", crahs,
                      len(crahs) - C["electrical_room_crah_redundancy"], crahs[0])
            fans = self.mech_cfg_fans()
            full = [sum(1 for w in walls if not any(self.unit_out(f"FAN:{w}:{f}")[h * 60:(h + 1) * 60].any() for f in range(1, fans + 1))) for h in range(H)]
            groups.append({"key": f"fans-{hid}", "name": "Thermal-wall fans", "scheme": f"N+1 in each wall ({fans} fans)", "hall": hid,
                           "family": "mechanical", "link": walls[0] if walls else "mechanical", "units": walls,
                           "unit_word": "walls with every fan", "need": [len(walls)] * H, "avail": full, "total": [len(walls)] * H,
                           "state": [AMBER if a < len(walls) else GREEN for a in full]})
            for h in range(H):
                for w in walls:
                    downs = [f for f in range(1, fans + 1) if self.unit_out(f"FAN:{w}:{f}")[h * 60:(h + 1) * 60].any()]
                    if downs:
                        issue(h, "mechanical", hid, AMBER, f"{w}: {'; '.join(self.why(f'FAN:{w}:{f}', h) for f in downs)}, {fans - len(downs)} of {fans} fans", w)
        hr = self.site["plants"]["heat_rejection"]
        chillers = sorted(c for c, x in self.mech_dev.items() if x["family"] == "chiller")
        group("chillers", "Chillers", f"N+{hr['chiller_redundancy']}", None, "mechanical", chillers, len(chillers) - hr["chiller_redundancy"], "mechanical")
        pumps = sorted(c for c, x in self.mech_dev.items() if x["family"] == "pump")
        group("fwpumps", "Facility water pumps", f"N+{hr['pump_redundancy']}", None, "mechanical", pumps, len(pumps) - hr["pump_redundancy"], "mechanical")

        # ---- family readings, by hour
        R: dict[str, Any] = {"gpu": {}, "cdu": {}, "power": {}, "network": {}, "mechanical": {}, "mgmt": {}, "storage": {}}
        for hall in self.halls:
            hid = hall["id"]
            rk = [r for r, x in racks.items() if x["hall"] == hid]
            g = {k: [] for k in ("racks", "gpus", "util", "kw", "temp", "slow", "drained", "dark")}
            for h in range(H):
                rows = [self.rack_hourly[r][h] for r in rk if r in self.rack_hourly and racks[r]["state"][h] != OFF]
                gp = sum(int(x["gpus_reporting"]) for x in rows)
                g["racks"].append(len(rows))
                g["gpus"].append(gp)
                g["util"].append(round(sum(float(x["util_avg"]) * int(x["gpus_reporting"]) for x in rows if x["util_avg"]) / gp, 1) if gp else None)
                g["kw"].append(round(sum(float(x["power_kwh"]) for x in rows)))
                g["temp"].append(max((int(x["gpu_temp_max_c"]) for x in rows if x["gpu_temp_max_c"]), default=None))
                g["slow"].append(sum(1 for x in rows if int(x["thermal_violation_s"])))
                g["drained"].append(sum(int(x["nodes_drained"]) for x in rows))
                g["dark"].append(sum(1 for x in rows if int(x["gpus_reporting"]) == 0))
            R["gpu"][hid] = g
        cdu_h = self.hourly(_csv(self.d.cdu / "cdu_hourly.csv"), "cdu")
        for hall in self.halls:
            hid = hall["id"]
            cdus = sorted(c for c, x in self.cdu_dev.items() if x["hall"] == hid)
            c = {k: [] for k in ("supply", "flow", "heat_kw", "leaks")}
            for h in range(H):
                rows = [cdu_h[x][h] for x in cdus]
                sup = max(float(r["supply_max_c"]) for r in rows)
                c["supply"].append(round(sup, 1))
                c["flow"].append(round(sum(float(r["flow_lpm"]) for r in rows)))
                c["heat_kw"].append(round(sum(float(r["heat_kwh"]) for r in rows)))
                lk = [(cd, note) for cd in cdus for m, note in self.leak.get(cd, []) if m[h * 60:(h + 1) * 60].any()]
                c["leaks"].append(len(lk))
                for cd, note in lk:
                    issue(h, "cdu", hid, RED, f"{cd}: leak detected{' (' + note + ')' if note else ''}", cd)
                hot = [(x, float(cdu_h[x][h]["supply_max_c"])) for x in cdus]
                for x, v in hot:
                    if v >= thr["cdu"]["supply_amber_c"]:
                        issue(h, "cdu", hid, RED if v >= thr["cdu"]["supply_red_c"] else AMBER, f"{x}: coolant supply {v:.1f} C", x)
            R["cdu"][hid] = c
        ups_h = self.hourly(_csv(self.d.power / "ups_hourly.csv"), "ups")
        gen_h = self.hourly(_csv(self.d.power / "generator_hourly.csv"), "generator")
        gens = sorted(gen_h)
        R["power"]["site"] = {"gens_running": [sum(1 for x in gens if int(gen_h[x][h]["run_min"]) > 0) for h in range(H)],
                              "fuel_min": [min(float(gen_h[x][h]["fuel_pct"]) for x in gens) for h in range(H)]}
        for h in range(H):
            low = [x for x in gens if float(gen_h[x][h]["fuel_pct"]) < thr["generator"]["fuel_amber_pct"]]
            for x in low:
                issue(h, "power", None, AMBER, f"{x}: fuel {float(gen_h[x][h]['fuel_pct']):.0f}%", x)
        for hall in self.halls:
            hid = hall["id"]
            it = sorted(u for u, x in self.power_dev.items() if x["family"] == "ups" and x["hall"] == hid and x["kind"] == "it")
            allu = sorted(u for u, x in self.power_dev.items() if x["family"] == "ups" and x["hall"] == hid)
            p = {k: [] for k in ("it_kw", "load_max", "battery", "soc_min")}
            for h in range(H):
                p["it_kw"].append(round(sum(float(ups_h[u][h]["out_kwh"]) for u in it)))
                p["load_max"].append(max(float(ups_h[u][h]["load_max_pct"]) for u in it))
                p["battery"].append(sum(1 for u in allu if int(ups_h[u][h]["battery_s"]) > 0))
                p["soc_min"].append(min(int(float(ups_h[u][h]["soc_min_pct"])) for u in allu))
                for u in allu:
                    r = ups_h[u][h]
                    if int(r["battery_s"]):
                        issue(h, "power", hid, AMBER, f"{u}: on battery {int(r['battery_s'])} s", u)
                    if int(r["modules_min"]) < self.power_dev[u]["modules"]:
                        issue(h, "power", hid, AMBER, f"{u}: power module out, {r['modules_min']} of {self.power_dev[u]['modules']} (no module redundancy)", u)
                    if u in it and float(r["load_max_pct"]) >= thr["ups"]["load_amber_pct"]:
                        issue(h, "power", hid, RED if float(r["load_max_pct"]) >= thr["ups"]["load_red_pct"] else AMBER,
                              f"{u}: load {float(r['load_max_pct']):.0f}% (above {thr['ups']['load_amber_pct']:.0f}%, three cannot carry a fourth's load)", u)
            R["power"][hid] = p
        fab = _csv(self.d.network / "fabric_hourly.csv")
        for hall in self.halls:
            hid = hall["id"]
            n = {k: [0] * H for k in ("cabled", "up", "downs")}
            util: list[list[float]] = [[] for _ in range(H)]
            for r in fab:
                if r["hall"] != hid:
                    continue
                h = self.hour_of(r["hour"])
                n["cabled"][h] += int(r["links_cabled"])
                n["up"][h] += int(r["links_up"])
                n["downs"][h] += int(r["link_downs"])
                if int(r["links_cabled"]) and r["util_avg_pct"] != "":            # empty while no cabled link is up
                    util[h].append(float(r["util_avg_pct"]))
            n["util"] = [round(sum(u) / len(u), 1) if u else None for u in util]
            trays = [sum(int(nv[r][h]["trays_reporting"]) for r in nv if nv[r][h] and racks.get(r, {}).get("hall") == hid
                         and racks[r]["state"][h] != OFF) for h in range(H)]
            n["trays"] = trays
            n["trays_total"] = [9 * len(in_service(h, hid)) for h in range(H)]
            for h in range(H):
                if n["downs"][h] > 0:
                    issue(h, "network", hid, AMBER, f"{self.hall_name(hid)}: InfiniBand link drops (a dropped link takes one GPU off its rail)", "network")
            R["network"][hid] = n
        loop = _csv(self.d.mechanical / "loop_hourly.csv")
        air = self.hourly(_csv(self.d.mechanical / "air_hourly.csv"), "unit")
        pmp = self.hourly(_csv(self.d.mechanical / "pump_hourly.csv"), "pump")
        chg = next(g for g in groups if g["key"] == "chillers")
        m = {"supply": [], "ret": [], "running": [], "needed": [], "available": chg["avail"], "pumps": []}
        for h, r in enumerate(loop[:H]):
            m["supply"].append(float(r["supply_c"]))
            m["ret"].append(float(r["return_c"]))
            m["running"].append(int(r["chillers_running"]))
            m["needed"].append(int(r["chillers_needed"]))
            m["pumps"].append(sum(1 for x in pmp if int(pmp[x][h]["run_min"]) > 0))
            v = float(r["supply_c"])
            if v >= thr["loop"]["supply_amber_c"]:
                issue(h, "mechanical", None, RED if v >= thr["loop"]["supply_red_c"] else AMBER, f"Facility water supply {v:.1f} C", "FW-LOOP")
            if chg["avail"][h] < int(r["chillers_needed"]):
                issue(h, "mechanical", None, RED, f"Chillers: {chg['avail'][h]} available, {r['chillers_needed']} needed for the load", "mechanical")
        R["mechanical"]["site"] = m
        for hall in self.halls:
            hid = hall["id"]
            walls = sorted(w for w, x in self.mech_dev.items() if x.get("hall") == hid and x["family"] in ("wall", "crah"))
            a = {"air_max": [max(float(air[w][h]["sup_max_c"]) for w in walls) for h in range(H)]}
            for h in range(H):
                for w in walls:
                    v = float(air[w][h]["sup_max_c"])
                    if v >= thr["air"]["supply_amber_c"]:
                        issue(h, "mechanical", hid, RED if v >= thr["air"]["supply_red_c"] else AMBER, f"{w}: supply air {v:.1f} C", w)
            R["mechanical"][hid] = a

        # ---- management network: the aggregation pair, rack switches, uplinks, the collector, BMC gaps
        if self.mg is not None:
            self._mgmt(groups, R, issue)

        # ---- storage: each cluster's protection (Storage); the storage fabric's spine and storage leaf pairs and its
        #      flapping and down uplinks (Network, North-South)
        if self.sg is not None:
            self._storage(groups, R, issue)

        # ---- family states by hour, and the issue spans
        fam_state = {f: [GREEN] * H for f, _, _ in FAMILIES}
        hall_state = {hid: {f: [GREEN] * H for f, _, _ in FAMILIES} for hid in self.hall_ids}
        for h, fam, hall, s, _, _ in issues:
            fam_state[fam][h] = max(fam_state[fam][h], s)
            if hall:
                hall_state[hall][fam][h] = max(hall_state[hall][fam][h], s)
        spans = self._issue_spans(issues)
        site_state = [max(fam_state[f][h] for f, _, _ in FAMILIES) for h in range(H)]
        return {"window": self.window, "hours": H, "framing": self.cfg["framing"], "unit_out": self.cfg["unit_out"],
                "thresholds": thr, "sources": self.cfg["sources"],
                "halls": [{"id": h["id"], "name": h["name"], "rows": h["rows"], "per_row": h["racks_per_row"], "state": h["state"],
                           "cdus": sorted(c for c, x in self.cdu_dev.items() if x["hall"] == h["id"]),
                           "ups": sorted(u for u, x in self.power_dev.items() if x["family"] == "ups" and x["hall"] == h["id"])}
                          for h in self.halls],
                "planned": [{"name": h["name"], "state": h["state"]} for h in self.planned],
                "families": [{"key": k, "name": n, "link": l} for k, n, l in FAMILIES],
                "groups": groups, "racks": racks, "readings": R, "family_state": fam_state, "hall_state": hall_state,
                "site_state": site_state, "issues": spans}

    def _mgmt(self, groups: list[dict], R: dict[str, Any], issue) -> None:
        mg, rep, H = self.mg, self.mg_rep, self.H
        devs = mg.manifest["devices"]
        cfg = yaml.safe_load((ROOT / "config" / "telemetry_mgmt.yaml").read_text(encoding="utf-8"))
        R["mgmt"] = {}
        bmc = self.hourly(mg.bmc_hourly, "rack")
        for hall in self.halls:
            hid = hall["id"]
            aggs = sorted(s for s, x in devs.items() if x["family"] == "agg" and x["hall"] == hid)
            if not aggs:
                continue
            cnt = np.zeros(self.M, dtype=int)
            for a in aggs:
                cnt += self.unit_out(a)
            avail = [len(aggs) - int(v) for v in self.hour_max(cnt)]
            state = [RED if a < 1 else AMBER if a < len(aggs) else GREEN for a in avail]
            groups.append({"key": f"oob-{hid}", "name": "Management aggregation", "scheme": f"N+{len(aggs) - 1}", "hall": hid, "family": "mgmt",
                           "link": "management", "units": aggs, "unit_word": "", "need": [1] * H, "avail": avail, "total": [len(aggs)] * H, "state": state})
            for h in range(H):
                if state[h] > GREEN:
                    downs = [a for a in aggs if self.unit_out(a)[h * 60:(h + 1) * 60].any()]
                    issue(h, "mgmt", hid, state[h], f"Management aggregation ({self.hall_name(hid)}): {avail[h]} of {len(aggs)}, "
                          f"{'below N' if state[h] == RED else 'no redundant unit'} ({'; '.join(f'{a} {self.why(a, h)}' for a in downs)})", downs[0] if downs else "management")
            racks = sorted({x["rack"] for x in devs.values() if x["family"] == "bmc" and x["hall"] == hid})
            sws = sorted(s for s, x in devs.items() if x["family"] == "rack" and x["hall"] == hid)
            r = {k: [0] * H for k in ("bmcs", "answering", "failed", "switches", "switches_down")}
            for rid in racks:
                for h, row in enumerate(bmc.get(rid, [None] * H)):
                    if row and int(row["endpoints"]):
                        r["bmcs"][h] += int(row["endpoints"])
                        r["answering"][h] += int(row["answering_min"]) if row["answering_min"] != "" else 0
                        r["failed"][h] += int(row["failed_polls"])
            for s in sws:
                o, rid = rep[s], devs[s]["rack"]
                booted = np.maximum.accumulate(o["up"]).astype(bool) if devs[s]["down_at_start"] is None else np.ones(self.M, dtype=bool)
                ins, dn = self.hour_any(booted), self.hour_any(o["dark"] & booted)
                lost = np.zeros(self.M, dtype=bool)
                if rid in self.mg_loss:
                    a, b = self.mg_loss[rid]
                    lost[a:b + 15] = True
                own = self.hour_any(o["dark"] & ~lost)
                for h in range(H):
                    r["switches"][h] += int(ins[h])
                    r["switches_down"][h] += int(dn[h])
                    if own[h]:
                        n = sum(1 for x in devs.values() if x["family"] == "bmc" and x["rack"] == rid)
                        what = f"its {n} BMCs unreachable" if devs[s]["role"] == "oob" else "in-band management (NVLink tray eth0, host ports) unreachable"
                        issue(h, "mgmt", hid, AMBER, f"{s} down: rack {rid}, {what}", s)
                for p in (49, 50):
                    if p in o["ports"]:
                        flap = self.hour_any((o["ports"][p] == 0) & (o["up"] == 1) & booted)
                        for h in np.flatnonzero(flap).tolist():
                            issue(h, "mgmt", hid, AMBER, f"{s}: uplink swp{p} down (no redundant uplink)", s)
            for g in mg.gaps:
                n = g["endpoint"]
                if devs[n]["hall"] != hid or (g["minutes"] or 0) <= cfg["checks"]["gap_min"]:
                    continue
                a = mg.m_of(g["from"])
                b = mg.m_of(g["to"]) if g["to"] else self.M
                sw, rid = devs[n]["switch"], devs[n]["rack"]
                if rep[sw]["dark"][a:b].any() or (rid in self.mg_loss and self.mg_loss[rid][0] - 2 <= a <= self.mg_loss[rid][1]):
                    continue
                for h in range(a // 60, min(H, (b - 1) // 60 + 1)):
                    issue(h, "mgmt", hid, AMBER, f"{n}: BMC not answering", f"mgmt-{rid}")
            R["mgmt"][hid] = r
        for h in np.flatnonzero(self.hour_any(self.mg_unpolled)).tolist():
            issue(h, "mgmt", None, AMBER, "Telemetry of Record poller restarted: no BMC polled", "management")

    def _storage(self, groups: list[dict], R: dict[str, Any], issue) -> None:
        t, H = self.sg, self.H
        devs = t.manifest["devices"]
        node_rows = self.hourly(t.node_hourly, "node")
        for cname, cl in sorted(t.manifest["clusters"].items()):
            hid, tol, nodes = cl["hall"], int(cl["tolerates"]), cl["nodes"]
            if hid not in self.hall_ids:
                continue
            deg = {n: self.sg_degraded(n) for n in nodes}
            worst = self.hour_max(sum(d.astype(int) for d in deg.values()))
            avail = [tol - int(v) for v in worst]
            state = [RED if a < 0 else AMBER if a < tol else GREEN for a in avail]
            ec = cl["erasure_coding"]
            groups.append({"key": f"stg-{hid}", "name": "Storage cluster", "cluster": cname, "scheme": f"erasure coding {ec[0]}+{ec[1]}", "hall": hid,
                           "family": "storage", "link": "storage", "units": nodes, "unit_word": "more nodes it could lose",
                           "need": [0] * H, "avail": avail, "total": [tol] * H, "state": state})
            for h in range(H):
                if state[h] > GREEN:
                    sl = slice(h * 60, (h + 1) * 60)
                    why = []
                    for n in nodes:
                        if not deg[n][sl].any():
                            continue
                        if not self.sg_online[n][sl].all():
                            why.append(f"{n} offline")
                        for b in np.flatnonzero((self.sg_bays[n][:, sl] != 0).any(1)).tolist():
                            st = int(self.sg_bays[n][b, sl].max())
                            why.append(f"{n} Bay{b + 1:02d} {({1: 'failed', 2: 'pulled', 3: 'rebuilding'}).get(st, 'not OK')}")
                    issue(h, "storage", hid, state[h], f"{cname}: protection {avail[h]} of {tol} ({'; '.join(why)})", "storage")
            for role, word in (("spine", "Storage fabric spines"), ("storage_leaf", "Storage leaves")):
                sws = sorted(s for s, x in devs.items() if x["family"] == role and x["hall"] == hid)
                dark = {s: np.logical_and.reduce([self.sg_links[(s, i)] == 0 for i in devs[s]["ports"]]) for s in sws}
                cnt = self.hour_max(sum(d.astype(int) for d in dark.values()))
                av = [len(sws) - int(v) for v in cnt]
                groups.append({"key": f"{role}-{hid}", "name": word, "scheme": f"N+{len(sws) - 1}", "hall": hid, "family": "network",
                               "link": sws[0], "units": sws, "unit_word": "", "need": [1] * H, "avail": av, "total": [len(sws)] * H,
                               "state": [RED if a < 1 else AMBER if a < len(sws) else GREEN for a in av]})
            r = {k: [0] * H for k in ("nodes", "online", "drives_out", "read_gbps")}
            for n in nodes:
                for h, row in enumerate(node_rows[n]):
                    r["nodes"][h] += 1
                    r["online"][h] += int(int(row["online_min"]) == 60)
                    r["drives_out"][h] += int(row["drives_failed"]) + int(row["drives_absent"]) + int(row["drives_rebuilding"])
                    r["read_gbps"][h] += float(row["read_gb"]) / 3600
            r["read_gbps"] = [round(v, 1) for v in r["read_gbps"]]
            r["protection"] = avail
            r["tolerates"] = [tol] * H
            R["storage"][hid] = r
        flap_at = set()
        for f in self.sg_flaps:
            x = devs[f["switch"]]
            for h in range(f["a"] // 60, min(H, (f["b"] - 1) // 60 + 1)):
                flap_at.add((f["switch"], f["ifName"], h))
                issue(h, "network", x["hall"], AMBER, f"{f['switch']} {f['ifName']} flapping: storage clients behind it stall", f["switch"])
        for (sw, ifn), v in self.sg_links.items():
            x = devs[sw]
            if x["family"] == "spine" or x["ports"][ifn][0] != "uplink" or v.all():
                continue
            for h in np.flatnonzero(self.hour_any(v == 0)).tolist():
                if (sw, ifn, h) not in flap_at:
                    issue(h, "network", x["hall"], AMBER, f"{sw}: uplink {ifn} down ({len([p for p in x['ports'].values() if p[0] == 'uplink']) - 1} others carry it)", sw)

    def _issue_spans(self, issues: list[tuple]) -> list[dict]:
        """Identical conditions in consecutive hours merge into one span (the page filters by hour)."""
        by: dict[tuple, list[int]] = defaultdict(list)
        for h, fam, hall, s, text, link in issues:
            by[(fam, hall, s, text, link)].append(h)
        out = []
        for (fam, hall, s, text, link), hs in by.items():
            hs = sorted(set(hs))
            a = prev = hs[0]
            for h in hs[1:] + [None]:
                if h is not None and h == prev + 1:
                    prev = h
                    continue
                out.append({"from": a, "to": prev, "family": fam, "hall": hall, "state": s, "text": text, "link": link})
                if h is not None:
                    a = prev = h
        return sorted(out, key=lambda x: (x["from"], -x["state"], x["family"], x["text"]))

    # ------------------------------------------------------------------ labels
    def mech_cfg_fans(self) -> int:
        cfg = yaml.safe_load((ROOT / "config" / "telemetry_mechanical.yaml").read_text(encoding="utf-8"))
        return int(_find(cfg, "fans_per_wall"))

    def hall_name(self, hid: str | None) -> str:
        return next((h["name"] for h in self.site["halls"] if h["id"] == hid), "Site")

    @staticmethod
    def label(unit: str) -> str:
        if unit.startswith("MV:"):
            return unit[3:]
        if unit.startswith(("PUMP:", "FAN:")):
            return unit.split(":")[1]
        if unit.startswith("FEED:"):
            _, r, s = unit.split(":")
            return f"{r} feed {s}"
        return unit


def _find(d: Any, key: str) -> Any:
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = _find(v, key)
            if r is not None:
                return r
    return None


# --------------------------------------------------------------------------- agreements
def agreements(sh: SiteHealth, data: dict[str, Any]) -> list[Check]:
    """The dashboard's state, built from the recorded state changes, against the hourly figures each section publishes."""
    H = sh.H
    checks = []

    c = Check("bypass", "A UPS counts as out in exactly the hours its hourly row reports minutes on bypass")
    for u, rows in sh.hourly(_csv(sh.d.power / "ups_hourly.csv"), "ups").items():
        out = sh.hour_any(sh.unit_out(u))
        for h in range(H):
            c(bool(out[h]) == (int(rows[h]["bypass_min"]) > 0), f"{u} hour {h}: dashboard {'out' if out[h] else 'in service'}, bypass minutes {rows[h]['bypass_min']}")
    checks.append(c)

    c = Check("feeders", "A busway's racks lose that feed in exactly the hours its hourly row reports minutes without voltage")
    for run, rows in sh.hourly(_csv(sh.d.power / "busway_hourly.csv"), "run").items():
        out = sh.hour_any(sh.run_trip.get(run, np.zeros(sh.M, dtype=bool)))
        for h in range(H):
            c(bool(out[h]) == (int(rows[h]["dead_min"]) > 0), f"{run} hour {h}: dashboard {'tripped' if out[h] else 'live'}, dead minutes {rows[h]['dead_min']}")
    checks.append(c)

    c = Check("chillers", "A chiller counts as out in exactly the hours its hourly row reports alarm or BMS-off minutes")
    for ch, rows in sh.hourly(_csv(sh.d.mechanical / "chiller_hourly.csv"), "chiller").items():
        out = sh.hour_any(sh.unit_out(ch))
        for h in range(H):
            rep = int(rows[h]["alarm_min"]) + int(rows[h]["bms_off_min"]) > 0
            c(bool(out[h]) == rep, f"{ch} hour {h}: dashboard {'out' if out[h] else 'available'}, alarm {rows[h]['alarm_min']} and BMS-off {rows[h]['bms_off_min']} minutes")
    checks.append(c)

    c = Check("fans", "A thermal wall loses a fan in exactly the hours its hourly row reports fewer fans running")
    fans = sh.mech_cfg_fans()
    for w, rows in sh.hourly(_csv(sh.d.mechanical / "air_hourly.csv"), "unit").items():
        if sh.mech_dev[w]["family"] != "wall":
            continue
        out = sh.hour_any(np.logical_or.reduce([sh.unit_out(f"FAN:{w}:{f}") for f in range(1, fans + 1)]))
        for h in range(H):
            c(bool(out[h]) == (int(rows[h]["fans_min"]) < fans), f"{w} hour {h}: dashboard {'fan out' if out[h] else 'all fans'}, fans_min {rows[h]['fans_min']}")
    checks.append(c)

    c = Check("pumps", "Every hour a CDU reports pump redundancy lost, the dashboard has a pump out")
    for cdu, rows in sh.hourly(_csv(sh.d.cdu / "cdu_hourly.csv"), "cdu").items():
        out = sh.hour_any(sh.unit_out(f"PUMP:{cdu}:1") | sh.unit_out(f"PUMP:{cdu}:2"))
        for h in range(H):
            if int(rows[h]["redundancy_lost_min"]) > 0:
                c(bool(out[h]), f"{cdu} hour {h}: pump redundancy lost {rows[h]['redundancy_lost_min']} min, no pump out on the dashboard")
    checks.append(c)

    c = Check("dark_racks", "A rack shows no GPUs reporting only in hours it lost both feeds, and in every hour it had none all hour")
    for rid, x in data["racks"].items():
        both = sh.unit_out(f"FEED:{rid}:A") & sh.unit_out(f"FEED:{rid}:B")
        any_h, all_h = sh.hour_any(both), both.reshape(H, 60).all(axis=1)
        for h in range(H):
            if x["state"][h] == OFF:
                continue
            dark = "no GPUs reporting" in x["why"][h]
            c((not dark or any_h[h]) and (dark or not all_h[h]), f"{rid} hour {h}: {'dark' if dark else 'reporting'}, both feeds lost {'all hour' if all_h[h] else 'part of the hour' if any_h[h] else 'never'}")
    checks.append(c)

    c = Check("generators", "Every hour the utility feeds are lost, every generator runs")
    gen = sh.hourly(_csv(sh.d.power / "generator_hourly.csv"), "generator")
    util = next(g for g in data["groups"] if g["key"] == "utility")
    for h in range(H):
        if util["avail"][h] < util["total"][h]:
            c(all(int(gen[g][h]["run_min"]) > 0 for g in gen), f"hour {h}: utility lost, generators running {[g for g in gen if int(gen[g][h]['run_min']) > 0]}")
    checks.append(c)

    if sh.mg is not None:
        c = Check("mgmt_switches", "A management switch counts as down in exactly the hours its hourly row reports fewer than 60 minutes up")
        for s, rows in sh.hourly(sh.mg.switch_hourly, "switch").items():
            if s not in sh.mg_rep:
                continue
            down = sh.hour_any(sh.mg_rep[s]["up"] == 0)
            for h in range(H):
                c(bool(down[h]) == (int(rows[h]["up_min"]) < 60), f"{s} hour {h}: dashboard {'down' if down[h] else 'up'}, up {rows[h]['up_min']} min")
        checks.append(c)

    if sh.sg is not None:
        c = Check("storage_protection", "A storage cluster's protection on the dashboard equals the lowest its hourly row reports")
        rows = sh.hourly(sh.sg.cluster_hourly, "cluster")
        for g in data["groups"]:
            if g["key"].startswith("stg-"):
                cname = g["cluster"]
                for h in range(H):
                    c(g["avail"][h] == int(rows[cname][h]["protection_min"]), f"{cname} hour {h}: dashboard {g['avail'][h]}, hourly row {rows[cname][h]['protection_min']}")
        checks.append(c)

    c = Check("readings", "Each hall's GPU power and UPS output add up from the hourly rows")
    for hid in sh.hall_ids:
        g, p = data["readings"]["gpu"][hid], data["readings"]["power"][hid]
        for h in range(H):
            c(g["kw"][h] <= p["it_kw"][h] + 1, f"{hid} hour {h}: GPU power {g['kw'][h]} kW above the UPS output {p['it_kw'][h]} kW")
    checks.append(c)
    return checks


def page_data(data: dict[str, Any]) -> dict[str, Any]:
    """The page's copy: hourly series run-length encoded (they change a few times a month)."""
    out = {k: v for k, v in data.items() if k not in ("racks", "groups", "family_state", "hall_state", "site_state", "readings")}
    out["racks"] = {r: {**{k: v for k, v in x.items() if k not in ("state", "why")}, "state": rle(x["state"]),
                        "why": rle(["; ".join(w) for w in x["why"]])} for r, x in data["racks"].items()}
    out["groups"] = [{**{k: v for k, v in g.items() if k not in ("avail", "total", "need", "state")},
                      **{k: rle(g[k]) for k in ("avail", "total", "need", "state")}} for g in data["groups"]]
    out["family_state"] = {f: rle(v) for f, v in data["family_state"].items()}
    out["hall_state"] = {h: {f: rle(v) for f, v in x.items()} for h, x in data["hall_state"].items()}
    out["site_state"] = rle(data["site_state"])
    out["readings"] = {f: {s: {k: rle(v) for k, v in x.items()} for s, x in d.items()} for f, d in data["readings"].items()}
    return out


def build(dirs: Dirs | None = None, site: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None) -> tuple[SiteHealth, dict[str, Any]]:
    from .site_model import load_site
    sh = SiteHealth(dirs or Dirs.committed(), site or load_site(), cfg)
    return sh, sh.build()
