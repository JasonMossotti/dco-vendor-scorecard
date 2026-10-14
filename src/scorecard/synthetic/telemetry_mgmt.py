"""Synthetic management network telemetry for Site AUS-1: every BMC's Redfish answer, every management switch's ports.

Portfolio demo; all data fictional. Runs on a finished month (data/sample) with its own random stream
("<seed>:telemetry:mgmt") and writes beside the other telemetry, never into the records it reads.

What the Telemetry of Record sees, once a minute:

* **BMC polls.** Every compute tray BMC, NVLink switch tray BMC, and power shelf controller (35 per rack) answers a
  Redfish service-root poll over its rack's out-of-band switch (``<rack>-mgmt1``), or does not. An endpoint stops
  answering only for a reason the records give or this layer plants:
    - its rack lost power (the facility record), until the switch and the BMC have booted again;
    - the tray or shelf was out of the rack: before each replacement's first serial in BMC inventory, a failed NVLink
      switch tray from NMX's "unreachable" until its replacement answers, and a few minutes at each recorded reseat;
    - a BMC self-reset of a few minutes, or a longer hang with no partner action inside (decoys: no finding);
    - the planted cases below.
  The new serial of every replacement is observed at the first answer after the swap, as the inventory record says.
* **Switches.** Each rack switch's ports follow the devices on them (a removed tray's port is down; a hung BMC's is
  up), its uplinks to the hall's aggregation pair, its ASIC temperature, and its traffic (the polls themselves).
  Traps: linkDown and linkUp for each port change, coldStart when a switch boots (then a linkUp for each port that
  comes up with it). A trap is sent in the seconds before the minute whose poll first shows the change.
* **Hall B.** A rack's switches and BMCs first come up between its leak test (M3) and its reported power-on (M4).
* **The collector itself** restarts once or twice a month: every endpoint unpolled for a few minutes (its own log).
* **Console sessions.** The IT Partner's sessions on the console servers: initial setup of each new Hall B switch, a
  weekly configuration backup round in Hall A, and whatever the planted cases need.

Planted (one each a month; ``answer_key.json``), each a case where records do not reconcile:
  1. ``unticketed_outage``: a Hall A rack's out-of-band switch down for hours with the rack powered and running, no
     ticket, and an IT Partner console session on it just before it came back.
  2. ``validation_gap``: a power shelf controller stops answering in the middle of a passing ``psu_redundancy``
     validation check (a Redfish check) and stays down after it.
  3. ``late_bmc``: a few BMCs in one Hall B rack first answer hours after M4 (whose checklist confirms "BMC reachable
     on the out-of-band network") was reported complete.
  4. ``console_swap``: two adjacent console ports labelled the wrong way round in the console server's port map; a
     session on one of them prints the other switch's name.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "telemetry_mgmt.yaml"
MIN = timedelta(minutes=1)
HOUR_MIN = 60

# minute states of an endpoint in a window file
ANSWER, NO_ANSWER, LINK_DOWN, UNPOLLED, OFF = 0, 1, 2, 3, -1


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _rng(seed: int, *parts: object) -> random.Random:
    key = ":".join(str(p) for p in (seed, "telemetry", "mgmt") + parts)
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def chassis_of(resource: str) -> str | None:
    """'/redfish/v1/Chassis/A06_PowerShelf_1/PowerSubsystem/...' -> 'A06_PowerShelf_1'."""
    m = re.match(r"/redfish/v1/Chassis/([A-C]\d{2}_[A-Za-z]+_\d+)", resource or "")
    return m.group(1) if m else None


def endpoint_name(chassis: str) -> str:
    """The directory's name for a Redfish chassis: A07_ComputeTray_03 -> a07-ct03, A07_SwitchTray_3 -> a07-nvsw3,
    A07_PowerShelf_3 stays."""
    rack, kind, n = chassis.split("_")
    if kind == "ComputeTray":
        return f"{rack.lower()}-ct{int(n):02d}"
    if kind == "SwitchTray":
        return f"{rack.lower()}-nvsw{int(n)}"
    return chassis


def console_map(devices: dict[str, Any]) -> dict[str, tuple[str, int]]:
    """Every console line in the directory: device -> (console server, port)."""
    out = {}
    for name, e in devices["devices"].items():
        for rel, other, note in e.get("conn", []):
            if rel == "Console" and other.startswith("con-"):
                out[name] = (other, int(note.split()[-1]))
    return out


class MgmtTelemetry:
    """One month of management network readings, built from the records and this layer's own random stream."""

    def __init__(self, data_dir: str | Path, seed: int, cfg: dict[str, Any] | None = None, devices: dict[str, Any] | None = None):
        from scorecard import devices as DV
        from scorecard import site_model as S
        self.d, self.seed = Path(data_dir), seed
        self.cfg = cfg or load_config()
        man = json.loads((self.d / "manifest.json").read_text(encoding="utf-8"))
        w = man["window"]
        self.window = {"start": w["start"] if "T" in w["start"] else w["start"] + "T00:00:00Z",
                       "end": w["end"] if "T" in w["end"] else w["end"] + "T00:00:00Z", "seed": seed}
        self.start, self.end = parse(self.window["start"]), parse(self.window["end"])
        self.M = int((self.end - self.start).total_seconds() // 60)
        self.H = self.M // HOUR_MIN
        self.dev = devices or DV.load()
        self.site = S.load_site()
        self.ports = self.cfg["ports"]
        # Records the BMC cannot have answered for: in a few generated months a tray is swapped or reseated while its rack has
        # no power (the base records place the inventory change inside the outage). Kept here; the checks leave them out.
        self.in_power_loss: list[str] = []
        topo = json.loads((self.d / "site" / "topology.json").read_text(encoding="utf-8"))
        self.racks = {r["rack"]: r for r in topo["racks"] if r["state"] in ("production", "deployment")}
        tel = self.d / "telemetry"
        self.events = _jsonl(tel / "redfish_events.jsonl")
        self.inventory = _jsonl(tel / "redfish_inventory_changes.jsonl")
        self.checks = _jsonl(tel / "health_checks.jsonl")
        self.nmx = _jsonl(tel / "nmx_events.jsonl")
        self.sched = _jsonl(tel / "scheduler_node_states.jsonl")
        self.tickets = json.loads((self.d / "vendor" / "tickets.json").read_text(encoding="utf-8"))
        gt = self.d / "ground_truth" / "facility_incidents.json"
        self.fac = json.loads(gt.read_text(encoding="utf-8")) if gt.exists() else []
        self.milestones: dict[str, dict[str, datetime]] = {}
        mp = self.d / "vendor" / "deployment_milestones.csv"
        if mp.exists():
            for r in csv.DictReader(mp.open(encoding="utf-8")):
                if r["reported_complete_at"]:
                    self.milestones.setdefault(r["rack"], {})[r["milestone"]] = parse(r["reported_complete_at"])
        self.cons = console_map(self.dev)
        self._endpoints()

    # ----------------------------------------------------------------- time helpers
    def m_of(self, t: datetime) -> int:
        """Index of the first minute at or after t (the minute a record lands in)."""
        return max(0, min(self.M, math.ceil((t - self.start).total_seconds() / 60 - 1e-9)))

    def t_of(self, m: int) -> datetime:
        return self.start + m * MIN

    # ----------------------------------------------------------------- what exists
    def _endpoints(self) -> None:
        P = self.ports
        self.ep: dict[str, dict] = {}            # endpoint name -> rack, port on mgmt1, Redfish resource, kind, mgmt2 port
        self.switches: dict[str, dict] = {}      # every management switch, aggregation switch, and console server
        halls = {h["id"]: h for h in self.site["halls"] if h.get("management")}
        for rid, r in sorted(self.racks.items()):
            if r["hall"] not in halls:
                continue
            lo = rid.lower()
            for t in r["compute_trays"]:
                self.ep[t["host"]] = {"rack": rid, "hall": r["hall"], "kind": "compute", "port": P["mgmt1"]["compute_bmc"] + t["slot"] - 1,
                                      "inband": P["mgmt2"]["compute_host"] + t["slot"] - 1, "resource": t["redfish"]}
            for t in r["switch_trays"]:
                self.ep[t["name"]] = {"rack": rid, "hall": r["hall"], "kind": "switch", "port": P["mgmt1"]["switch_bmc"] + t["slot"] - 1,
                                      "inband": P["mgmt2"]["switch_eth0"] + t["slot"] - 1, "resource": t["redfish"]}
            for t in r["power_shelves"]:
                self.ep[t["redfish"].rsplit("/", 1)[-1]] = {"rack": rid, "hall": r["hall"], "kind": "shelf",
                                                            "port": P["mgmt1"]["power_shelf"] + t["slot"] - 1, "inband": None, "resource": t["redfish"]}
            leaves = [n for n, e in self.dev["devices"].items() if e["kind"] == "leaf"
                      and any(rel == "Management" and o == f"{lo}-mgmt1" for rel, o, _ in e["conn"])]
            for k in (1, 2):
                name = f"{lo}-mgmt{k}"
                self.switches[name] = {"family": "rack", "rack": rid, "hall": r["hall"], "role": "oob" if k == 1 else "inband",
                                       "leaves": sorted(leaves) if k == 1 else [], "console": self.cons.get(name)}
        for hid, h in halls.items():
            L = h["letter"].lower()
            for k in range(1, h["management"]["aggregation_count"] + 1):
                self.switches[f"oob-agg-{L}{k}"] = {"family": "agg", "rack": None, "hall": hid, "role": "agg", "leaves": [],
                                                    "console": self.cons.get(f"oob-agg-{L}{k}")}
            for row in range(1, h["rows"] + 1):
                self.switches[f"con-{L}{row}"] = {"family": "console", "rack": None, "hall": hid, "role": "console", "leaves": [], "console": None}
        self.by_rack: dict[str, list[str]] = {}
        for n, e in self.ep.items():
            self.by_rack.setdefault(e["rack"], []).append(n)
        self.res_ep = {e["resource"].rsplit("/", 1)[-1]: n for n, e in self.ep.items()}   # chassis -> endpoint

    def endpoint_of(self, resource: str) -> str | None:
        ch = chassis_of(resource)
        return self.res_ep.get(ch) if ch else None

    # ----------------------------------------------------------------- what the records pin down
    def pinned(self) -> dict[str, list[int]]:
        """Minutes each endpoint must answer: every TOR-observed record (Redfish events, inventory changes)."""
        out: dict[str, list[int]] = {}
        for e in self.events:
            n = self.endpoint_of(e["resource"])
            if n:
                out.setdefault(n, []).append(self.m_of(parse(e["timestamp"])))
        for e in self.inventory:
            n = self.endpoint_of(e["resource"])
            if n:
                out.setdefault(n, []).append(self.m_of(parse(e["observed_at"])))
        return out

    def claims(self) -> dict[str, list[tuple[int, int]]]:
        """Partner checks run through an endpoint's Redfish (health checks with a Redfish target): [start, end] minutes."""
        out: dict[str, list[tuple[int, int]]] = {}
        for c in self.checks:
            n = self.endpoint_of(c["target"]) if str(c["target"]).startswith("/redfish/") else None
            if n:
                out.setdefault(n, []).append((self.m_of(parse(c["started_at"])), self.m_of(parse(c["completed_at"]))))
        return out

    # ----------------------------------------------------------------- the month
    def run(self) -> dict[str, Any]:
        cfg, B = self.cfg, self.cfg["behaviour"]
        M = self.M
        pinned, claims = self.pinned(), self.claims()
        busy: dict[str, list[tuple[int, int]]] = {}          # spans already used on each endpoint
        gaps: list[dict] = []                                  # {endpoint, a, b, reason, link}
        sw_down: list[dict] = []                               # {switch, a, b, reason}
        uplink_down: list[dict] = []                           # {switch, uplink, a, b}
        sessions: list[dict] = []
        key: dict[str, Any] = {"planted": [], "decoys": []}
        first: dict[str, int] = {}                             # endpoint -> first minute in service (Hall A: 0)
        sw_first: dict[str, int] = {s: 0 for s in self.switches}

        def free(n: str, a: int, b: int, pad: int = 0) -> bool:
            if a < first.get(n, 0) or b > M or a >= b:
                return False
            if any(a - pad <= m < b + pad for m in pinned.get(n, [])):
                return False
            if any(x < b + pad and a - pad < y for x, y in busy.get(n, [])):
                return False
            return True

        def put(n: str, a: int, b: int, reason: str, link: bool, **extra: Any) -> None:
            busy.setdefault(n, []).append((a, b))
            gaps.append({"endpoint": n, "a": a, "b": b, "reason": reason, "link": link, **extra})

        # ---- Hall B: switches and BMCs come up between M3 and M4
        rng = _rng(self.seed, "hallb")
        hallb_late: dict[str, int] = {}
        for rid in sorted(self.racks):
            r = self.racks[rid]
            if r["hall"] == "HALL-A" or rid.lower() + "-mgmt1" not in self.switches:
                continue
            ms = self.milestones.get(rid, {})
            if "M4" not in ms:
                for n in self.by_rack.get(rid, []):
                    first[n] = M
                for k in (1, 2):
                    sw_first[f"{rid.lower()}-mgmt{k}"] = M
                continue
            m4 = ms["M4"]
            on = m4 - timedelta(hours=rng.uniform(*B["hallb_first_before_m4_h"]))
            if "M3" in ms:
                on = max(on, ms["M3"] + timedelta(minutes=rng.uniform(30, 90)))
            on = min(on, m4 - timedelta(minutes=20))
            a = self.m_of(on)
            for k in (1, 2):
                sw_first[f"{rid.lower()}-mgmt{k}"] = a
            for n in self.by_rack.get(rid, []):
                first[n] = min(M, a + rng.randint(*B["bmc_boot_min"]))
        for n, e in self.ep.items():
            first.setdefault(n, 0)

        # ---- rack power losses (facility record): switches and every endpoint down, then boot
        rng = _rng(self.seed, "power")
        power_spans: dict[str, tuple[int, int]] = {}
        for f in self.fac:
            if not f.get("rack_capacity_lost"):
                continue
            rid = f["unit"].replace("Rack ", "")
            if rid not in self.by_rack:
                continue
            a, back = self.m_of(parse(f["t0"])), self.m_of(parse(f["restored_at"]))
            sboot = rng.randint(*B["switch_boot_min"])
            for k in (1, 2):
                sw_down.append({"switch": f"{rid.lower()}-mgmt{k}", "a": a, "b": min(M, back + sboot), "reason": "power"})
            for n in sorted(self.by_rack[rid]):
                b = min(M, back + sboot + rng.randint(1, 2))
                if any(a <= m < b for m in pinned.get(n, [])):
                    self.in_power_loss.append(f"{n}: a Redfish record during the rack's power loss")
                put(n, a, b, "power", False)
            power_spans[rid] = (a, back)

        # ---- replacements: each tray or shelf out of the rack until its new serial answers
        rng = _rng(self.seed, "swaps")
        nmx_fail = {}
        for e in sorted(self.nmx, key=lambda x: x["timestamp"]):
            m = re.search(r"([a-c]\d{2}-nvsw\d)", e.get("unit", ""))
            if m and e["state"] == "failed":
                nmx_fail.setdefault(m.group(1), []).append(self.m_of(parse(e["timestamp"])))
        for inv in sorted(self.inventory, key=lambda x: x["observed_at"]):
            n = self.endpoint_of(inv["resource"])
            if not n or "/PowerSubsystem/" in inv["resource"] or inv["property"] != "SerialNumber":
                continue
            b = self.m_of(parse(inv["observed_at"]))
            fails = [m for m in nmx_fail.get(n, []) if m < b]
            if fails:
                a, why = fails[-1], "failed"
            else:
                a, why = b - rng.randint(*B["swap_out_min"]), "swap"
            prior = [m for m in pinned.get(n, []) if m < b]
            a = max(a, (max(prior) + 1) if prior else a, first.get(n, 0))
            if a >= b:
                continue
            if not free(n, a, b):
                continue
            put(n, a, b, why, False, serial=inv["new_value"])
        for t in self.tickets:
            if t.get("close_code") != "Cleaned/reseated":
                continue
            host = t["configuration_item"]
            if host not in self.ep:
                continue
            note = next((w for w in t["work_notes"] if "Reseated" in w["text"]), None)
            if not note:
                continue
            m = self.m_of(parse(note["at"]))
            b = m - rng.randint(0, 1)
            a = b - rng.randint(*B["reseat_out_min"])
            if free(host, a, b):
                put(host, a, b, "reseat", False, ticket=t["number"])

        # ---- planted 1: an out-of-band switch down, no ticket, a console session just before it returns
        rng = _rng(self.seed, "planted", "outage")
        ticket_racks = {t["rack"] for t in self.tickets}
        cand = [rid for rid in sorted(self.by_rack) if self.racks[rid]["hall"] == "HALL-A" and rid not in power_spans
                and rid not in ticket_racks]
        if not cand:
            cand = [rid for rid in sorted(self.by_rack) if self.racks[rid]["hall"] == "HALL-A" and rid not in power_spans]
        rng.shuffle(cand)
        placed = None
        for rid in cand:
            dur = int(rng.uniform(*cfg["planted"]["unticketed_outage_h"]) * 60)
            for _ in range(40):
                a = rng.randint(6 * 60, M - dur - 6 * 60)
                b = a + dur
                near = [t for t in self.tickets if t["rack"] == rid and abs((parse(t["opened_at"]) - self.t_of(a)).total_seconds()) < 86400 * 2]
                if near or not all(free(n, a, b + 10, pad=30) for n in self.by_rack[rid]):
                    continue
                if any(x < b + 60 and a - 60 < y for x, y in sum((claims.get(n, []) for n in self.by_rack[rid]), [])):
                    continue
                placed = (rid, a, b)
                break
            if placed:
                break
        if placed:
            rid, a, b = placed
            sw = f"{rid.lower()}-mgmt1"
            boot = rng.randint(*B["switch_boot_min"])
            sw_down.append({"switch": sw, "a": a, "b": b + boot, "reason": "outage"})
            for n in sorted(self.by_rack[rid]):
                put(n, a, b + boot + rng.randint(1, 2), "switch", True)
            con, port = self.cons[sw]
            s0 = b - rng.randint(6, 25)
            sessions.append({"console": con, "port": port, "a": s0, "b": b + rng.randint(3, 12), "host": sw, "why": "outage"})
            key["planted"].append({"kind": "unticketed_outage", "switch": sw, "rack": rid, "from": iso(self.t_of(a)),
                                   "to": iso(self.t_of(b + boot)), "endpoints": len(self.by_rack[rid])})

        # ---- planted 2: a power shelf controller stops answering in the middle of a passing Redfish check
        rng = _rng(self.seed, "planted", "validation")
        cands = []
        for c in self.checks:
            if c["check"] != "psu_redundancy" or c.get("result") != "pass" or not str(c["target"]).startswith("/redfish/"):
                continue
            n = self.endpoint_of(c["target"])
            if not n:
                continue
            s, e = self.m_of(parse(c["started_at"])), self.m_of(parse(c["completed_at"]))
            if e - s >= 2:
                cands.append((c, n, s, e))
        rng.shuffle(cands)
        for c, n, s, e in cands:
            a = rng.randint(s + 1, e - 1)
            nxt = [m for m in pinned.get(n, []) if m > e]
            b = e + rng.randint(*cfg["planted"]["validation_gap_after_min"])
            if nxt:
                b = min(b, min(nxt) - 1)
            if b - e < 10 or not free(n, a, b):
                continue
            put(n, a, b, "hang", True)
            key["planted"].append({"kind": "validation_gap", "endpoint": n, "check": c["check"], "target": c["target"],
                                   "started_at": c["started_at"], "completed_at": c["completed_at"],
                                   "from": iso(self.t_of(a)), "to": iso(self.t_of(b))})
            break

        # ---- planted 3: Hall B BMCs first answering after M4 was reported complete
        rng = _rng(self.seed, "planted", "late")
        late_racks = [rid for rid in sorted(self.by_rack) if self.racks[rid]["hall"] != "HALL-A"
                      and "M4" in self.milestones.get(rid, {}) and self.m_of(self.milestones[rid]["M4"]) < M - 48 * 60
                      and self.milestones[rid]["M4"] > self.start]
        rng.shuffle(late_racks)
        for rid in late_racks:
            m4 = self.m_of(self.milestones[rid]["M4"])
            trays = sorted(n for n in self.by_rack[rid] if self.ep[n]["kind"] == "compute")
            k = rng.randint(*cfg["planted"]["late_bmc"]["trays"])
            pick = sorted(rng.sample(trays, k))
            late = min(M - 1, m4 + int(rng.uniform(*cfg["planted"]["late_bmc"]["after_m4_h"]) * 60))
            if any(m < late + 5 for n in pick for m in pinned.get(n, [])) or any(x < late for n in pick for x, _ in claims.get(n, [])):
                continue
            for n in pick:
                hallb_late[n] = late + rng.randint(0, 3)
                first[n] = hallb_late[n]
            key["planted"].append({"kind": "late_bmc", "rack": rid, "endpoints": pick, "m4": iso(self.milestones[rid]["M4"]),
                                   "first_answer": {n: iso(self.t_of(hallb_late[n])) for n in pick}})
            break

        # ---- decoys: BMC self-resets, longer hangs with nothing claimed inside, collector restarts, uplink flaps
        rng = _rng(self.seed, "decoys")
        names = sorted(n for n in self.ep if first[n] < M)
        for kind, count, dur in (("reset", B["short_resets"], B["short_reset_min"]), ("hang", B["long_hangs"], B["long_hang_min"])):
            for _ in range(rng.randint(*count)):
                for _try in range(60):
                    n = rng.choice(names)
                    d = rng.randint(*dur)
                    a = rng.randint(first[n] + 30, max(first[n] + 31, M - d - 30))
                    if not free(n, a, a + d, pad=10):
                        continue
                    if any(x <= a + d + 5 and a - 5 <= y for x, y in claims.get(n, [])):
                        continue
                    put(n, a, a + d, kind, True)
                    key["decoys"].append({"kind": kind, "endpoint": n, "from": iso(self.t_of(a)), "minutes": d})
                    break
        collector: list[tuple[int, int]] = []
        all_pinned = sorted(m for ms in pinned.values() for m in ms)
        all_claims = [x for cs in claims.values() for x in cs]
        for _ in range(rng.randint(*B["collector_restarts"])):
            for _try in range(60):
                d = rng.randint(*B["collector_restart_min"])
                a = rng.randint(60, M - 60)
                if any(a - 2 <= m < a + d + 2 for m in all_pinned) or any(x <= a + d and a <= y for x, y in all_claims):
                    continue
                if any(x < a + d + 60 and a - 60 < y for x, y in collector):
                    continue
                collector.append((a, a + d))
                key["decoys"].append({"kind": "collector", "from": iso(self.t_of(a)), "minutes": d})
                break
        rack_sw = sorted(s for s, x in self.switches.items() if x["family"] == "rack" and sw_first[s] < M)
        for _ in range(rng.randint(*B["uplink_flaps"])):
            s = rng.choice(rack_sw)
            u = rng.choice(self.ports["uplinks"])
            d = rng.randint(*B["uplink_flap_min"])
            a = rng.randint(sw_first[s] + 60, max(sw_first[s] + 61, M - d - 60))
            uplink_down.append({"switch": s, "uplink": u, "a": a, "b": a + d})
            key["decoys"].append({"kind": "uplink", "switch": s, "uplink": f"swp{u}", "from": iso(self.t_of(a)), "minutes": d})

        # ---- console sessions: Hall B setup, Hall A weekly backups
        rng = _rng(self.seed, "console")
        for s, x in sorted(self.switches.items()):
            if x["family"] == "rack" and x["hall"] != "HALL-A" and 0 < sw_first[s] < M and x["console"]:
                a = sw_first[s] + rng.randint(4, 40)
                sessions.append({"console": x["console"][0], "port": x["console"][1], "a": a, "b": a + rng.randint(8, 35), "host": s, "why": "setup"})
        hall_a = [s for s, x in self.switches.items() if x["family"] in ("rack", "agg") and x["hall"] == "HALL-A" and x["console"]]
        for _ in range(rng.randint(*B["console_audits"])):
            s = rng.choice(sorted(hall_a))
            if placed and s == f"{placed[0].lower()}-mgmt1":
                continue
            a = rng.randint(60, M - 120)
            sessions.append({"console": self.switches[s]["console"][0], "port": self.switches[s]["console"][1], "a": a,
                             "b": a + rng.randint(3, 15), "host": s, "why": "backup"})
        # ---- planted 4: two adjacent console ports labelled the wrong way round (a session shows it)
        labels = {}
        for s, x in self.switches.items():
            if x["console"]:
                labels.setdefault(x["console"][0], {})[x["console"][1]] = s
        for n, (con, port) in self.cons.items():
            if n.startswith("leaf-"):
                labels.setdefault(con, {})[port] = n
        rng = _rng(self.seed, "planted", "console")
        if cfg["planted"].get("console_swap"):
            opts = sorted({(s["console"], s["port"]) for s in sessions if s["why"] in ("setup", "backup")})
            rng.shuffle(opts)
            for con, port in opts:
                other = port + 1 if port % 2 else port - 1
                if other not in labels.get(con, {}):
                    continue
                labels[con][port], labels[con][other] = labels[con][other], labels[con][port]
                key["planted"].append({"kind": "console_swap", "console": con, "ports": sorted([port, other]),
                                       "labelled": {str(port): labels[con][port], str(other): labels[con][other]}})
                break
        self.first, self.sw_first = first, sw_first
        self._gaps_by = {}
        for g in gaps:
            self._gaps_by.setdefault(g["endpoint"], []).append(g)
        return {"gaps": sorted(gaps, key=lambda g: (g["a"], g["endpoint"])), "switch_down": sw_down, "uplink_down": uplink_down,
                "collector": sorted(collector), "sessions": sorted(sessions, key=lambda s: (s["a"], s["console"], s["port"])),
                "labels": labels, "answer_key": key, "power": power_spans}

    # ----------------------------------------------------------------- per-minute views, built from the spans
    def endpoint_state(self, out: dict, n: str) -> np.ndarray:
        """Per minute: ANSWER, NO_ANSWER (link up), LINK_DOWN, UNPOLLED (collector), or OFF (not in service yet)."""
        st = np.full(self.M, ANSWER, dtype=np.int8)
        for g in self._gaps_by.get(n, []):
            st[g["a"]:g["b"]] = NO_ANSWER if g["link"] else LINK_DOWN
        for a, b in out["collector"]:
            seg = st[a:b]
            seg[seg == ANSWER] = UNPOLLED
            seg[seg == NO_ANSWER] = UNPOLLED
        st[:min(self.first[n], self.M)] = OFF
        return st

    def presence(self, n: str) -> np.ndarray:
        """Per minute: 1 while the device is in the rack and powered (its in-band port can be up)."""
        pr = np.ones(self.M, dtype=np.int8)
        for g in self._gaps_by.get(n, []):
            if not g["link"] and g["reason"] != "switch":
                pr[g["a"]:g["b"]] = 0
        return pr


def _rle(v: list) -> list[list]:
    out: list[list] = []
    for x in v:
        if out and out[-1][0] == x:
            out[-1][1] += 1
        else:
            out.append([x, 1])
    return out


def _csv(rows: list[dict], cols: list[str]) -> str:
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue()


BMC_HOURLY = ["hour", "rack", "endpoints", "polled_min", "answering_min", "answering_max", "failed_polls"]
SWITCH_HOURLY = ["hour", "switch", "up_min", "ports", "ports_up_min", "ports_up_max", "uplinks_up_min", "temp_c", "kbps"]


def write_mgmt(layer: MgmtTelemetry, out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, Any]:
    """Write the management telemetry's committed tiers to dest (all small: hourly tables, the logs, windows)."""
    cfg, M, H = layer.cfg, layer.M, layer.H
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    win = dest / "windows"
    if win.exists():
        for p in win.glob("*.json"):
            p.unlink()
    win.mkdir(exist_ok=True)
    hours = [iso(layer.t_of(h * HOUR_MIN)) for h in range(H)]
    states = {n: layer.endpoint_state(out, n) for n in sorted(layer.ep)}
    polled = np.ones(M, dtype=bool)
    for a, b in out["collector"]:
        polled[a:b] = False
    hp = polled.reshape(H, HOUR_MIN)
    # ---- BMC answers by rack and hour (an unpolled minute counts nothing)
    bmc_rows = []
    for rid in sorted(layer.by_rack):
        st = np.stack([states[n] for n in sorted(layer.by_rack[rid])])
        insvc = (st != OFF).sum(0).reshape(H, HOUR_MIN)
        cnt = (st == ANSWER).sum(0).reshape(H, HOUR_MIN)
        fail = ((st == NO_ANSWER) | (st == LINK_DOWN)).sum(0).reshape(H, HOUR_MIN)
        for h in range(H):
            svc = int(insvc[h].max())
            sel = hp[h] & (insvc[h] > 0)
            ans = cnt[h][sel]
            bmc_rows.append({"hour": hours[h], "rack": rid, "hall": layer.racks[rid]["hall"], "endpoints": svc, "polled_min": int(hp[h].sum()),
                             "answering_min": int(ans.min()) if svc and ans.size else "", "answering_max": int(ans.max()) if svc and ans.size else "",
                             "failed_polls": int(fail[h].sum())})
    # ---- switches: ports, uplinks, temperature, traffic
    down: dict[str, list[tuple[int, int]]] = {}
    for d in out["switch_down"]:
        down.setdefault(d["switch"], []).append((d["a"], d["b"]))
    upl: dict[str, list[tuple[int, int, int]]] = {}
    for u in out["uplink_down"]:
        upl.setdefault(u["switch"], []).append((u["uplink"], u["a"], u["b"]))
    P = cfg["ports"]

    def sw_up(s: str) -> np.ndarray:
        up = np.ones(M, dtype=np.int8)
        up[:min(layer.sw_first.get(s, 0), M)] = 0
        for a, b in down.get(s, []):
            up[a:b] = 0
        return up

    UP = {s: sw_up(s) for s in layer.switches}
    swrows, port_state = [], {}
    traps: list[dict] = []
    down0: dict[str, list[int] | None] = {}
    for s, x in sorted(layer.switches.items()):
        rng = _rng(layer.seed, "switch", s)
        up = UP[s]
        ports: dict[int, np.ndarray] = {}
        if x["family"] == "rack":
            rid = x["rack"]
            for n in layer.by_rack[rid]:
                e = layer.ep[n]
                if x["role"] == "oob":
                    ports[e["port"]] = ((states[n] != LINK_DOWN) & (states[n] != OFF)).astype(np.int8)
                elif e["inband"]:
                    ports[e["inband"]] = layer.presence(n)
            for i, lf in enumerate(x["leaves"]):
                ports[P["mgmt1"]["leaf_mgmt"] + i] = np.ones(M, dtype=np.int8)
            for u in P["uplinks"]:
                st = np.ones(M, dtype=np.int8)
                for uu, a, b in upl.get(s, []):
                    if uu == u:
                        st[a:b] = 0
                ports[u] = st
            for p_ in ports:
                ports[p_] = ports[p_] & up
        elif x["family"] == "agg":
            k = int(s[-1])
            for rs, rx in layer.switches.items():
                if rx["family"] == "rack" and rx["hall"] == x["hall"]:
                    st = UP[rs].copy()
                    for uu, a, b in upl.get(rs, []):
                        if uu == P["uplinks"][k - 1]:
                            st[a:b] = 0
                    ports[_agg_port(layer, rs)] = st & up
        else:
            for p_ in out["labels"].get(s, {}):
                ports[p_] = up.copy()
        port_state[s] = ports
        # traps: linkDown/linkUp on each change while the switch is up, coldStart when it boots
        if x["family"] != "console":
            both = (up[1:] == 1) & (up[:-1] == 1)
            boots = (np.flatnonzero((up[1:] == 1) & (up[:-1] == 0)) + 1).tolist()
            for m in boots:
                traps.append({"switch": s, "m": m, "trap": "coldStart", "ifName": ""})
            for p_, st in sorted(ports.items()):
                for m in (np.flatnonzero((st[1:] != st[:-1]) & both) + 1).tolist():
                    traps.append({"switch": s, "m": m, "trap": "linkUp" if st[m] else "linkDown", "ifName": f"swp{p_}"})
                for m in boots:                       # each port that comes up with the switch reports it
                    if st[m]:
                        traps.append({"switch": s, "m": m, "trap": "linkUp", "ifName": f"swp{p_}"})
            down0[s] = sorted(p_ for p_, st in ports.items() if not st[0]) if up[0] else None
        # hourly
        lo, hi = cfg["switch"]["temp_c"]
        upl_ports = [u for u in P["uplinks"] if u in ports] if x["family"] == "rack" else []
        dn = [p_ for p_ in ports if p_ not in upl_ports]
        pu = (np.stack([ports[p_] for p_ in dn]).sum(0) if dn else np.zeros(M, dtype=np.int64)).reshape(H, HOUR_MIN)
        uu = (np.stack([ports[u] for u in upl_ports]).sum(0) if upl_ports else np.zeros(M, dtype=np.int64)).reshape(H, HOUR_MIN)
        uph = up.reshape(H, HOUR_MIN)
        polls = None
        if x["family"] == "rack" and x["role"] == "oob":
            polls = np.stack([states[n] == ANSWER for n in layer.by_rack[x["rack"]]]).sum(0).reshape(H, HOUR_MIN).sum(1)
        for h in range(H):
            upm = int(uph[h].sum())
            day = (h % 24 + 18) % 24
            base = lo + (hi - lo) * (0.5 - 0.5 * math.cos(2 * math.pi * day / 24))
            temp = round(base + rng.gauss(0, cfg["switch"]["temp_noise_c"]), 1) if upm else ""
            if x["family"] == "rack" and upm:
                n_polls = int(polls[h]) if polls is not None else 0
                kb = (n_polls * cfg["switch"]["poll_bytes"] + upm * cfg["switch"]["snmp_bytes"]) * 8 / 1000 / 3600
                kbps = round(kb, 2)
            else:
                kbps = ""
            on = uph[h] == 1
            swrows.append({"hour": hours[h], "switch": s, "family": x["family"], "rack": x["rack"] or "", "hall": x["hall"], "up_min": upm,
                           "ports": len(dn), "ports_up_min": int(pu[h][on].min()) if upm else 0, "ports_up_max": int(pu[h][on].max()) if upm else 0,
                           "uplinks_up_min": (int(uu[h][on].min()) if upm else 0) if upl_ports else "",
                           "temp_c": temp, "kbps": kbps})
    # agg sees its rack-switch ports drop: those traps come from the agg (already above)
    order = {"coldStart": 0, "linkDown": 1, "linkUp": 2}
    traps.sort(key=lambda t: (t["m"], t["switch"], order[t["trap"]], t["ifName"]))
    # ---- the logs
    gaps_out = []
    for n in sorted(states):
        bad = ((states[n] == NO_ANSWER) | (states[n] == LINK_DOWN)).astype(np.int8)
        edges = np.flatnonzero(np.diff(np.concatenate(([0], bad, [0]))))
        e = layer.ep[n]
        for a, m in zip(edges[::2].tolist(), edges[1::2].tolist()):
            gaps_out.append({"endpoint": n, "rack": e["rack"], "resource": e["resource"], "from": iso(layer.t_of(a)),
                             "to": iso(layer.t_of(m)) if m < M else None, "minutes": m - a})
    gaps_out.sort(key=lambda g: (g["from"], g["endpoint"]))
    first_out = {n: iso(layer.t_of(layer.first[n])) if layer.first[n] < M else None for n in sorted(layer.ep) if layer.first[n] > 0}
    collector_log = []
    for a, b in out["collector"]:
        collector_log += [{"timestamp": iso(layer.t_of(a)), "event": "poller stopped", "detail": "Redfish poller restarted (process exit)"},
                          {"timestamp": iso(layer.t_of(b)), "event": "poller started", "detail": "polling resumed"}]
    sess_out = []
    for s in out["sessions"]:
        rng = _rng(layer.seed, "session", s["console"], s["port"], s["a"])
        sess_out.append({"console": s["console"], "port": s["port"], "opened_at": iso(layer.t_of(s["a"]) + timedelta(seconds=rng.randint(0, 59))),
                         "closed_at": iso(layer.t_of(s["b"]) + timedelta(seconds=rng.randint(0, 59))), "user": "it-partner",
                         "label": out["labels"].get(s["console"], {}).get(s["port"], ""), "prompt": f"{s['host']} login:"})
    # a coldStart precedes the linkUps it brings within its minute (45 to 55 s before the minute; the rest 1 to 40 s)
    traps_out = [{"timestamp": iso(layer.t_of(t["m"]) - timedelta(seconds=_rng(layer.seed, "trap", t["switch"], t["m"], t["ifName"]).randint(
                      *((45, 55) if t["trap"] == "coldStart" else (1, 40))))),
                  "switch": t["switch"], "trap": t["trap"], "ifName": t["ifName"]} for t in traps]
    ports_out = {con: {str(p_): n for p_, n in sorted(lbl.items())} for con, lbl in sorted(out["labels"].items())}
    # ---- windows: minute detail around every gap longer than a few minutes and every switch outage
    windows = []
    seen = set()
    events = [(g["endpoint"], g["a"], g["b"], g["reason"]) for g in out["gaps"] if g["b"] - g["a"] >= 3]
    for n, a, b, why in sorted(events, key=lambda x: (x[1], x[0])):
        rid = layer.ep[n]["rack"]
        lo_, hi_ = max(0, a - 20), min(M, b + 20)
        if hi_ - lo_ > 26 * 60:
            hi_ = lo_ + 26 * 60
        k = (rid, lo_ // 60) if why in ("power", "switch") else (n, lo_)
        if k in seen:
            continue
        seen.add(k)
        scope = sorted(layer.by_rack[rid]) if why in ("power", "switch") else [n]
        fn = f"{rid if why in ('power', 'switch') else n}_{layer.t_of(lo_).strftime('%Y%m%dT%H%M')}.json"
        sws = [f"{rid.lower()}-mgmt1", f"{rid.lower()}-mgmt2"]
        body = {"device": rid if why in ("power", "switch") else n, "rack": rid, "from": iso(layer.t_of(lo_)), "minutes": hi_ - lo_,
                "endpoints": {e: _rle(states[e][lo_:hi_].tolist()) for e in scope},
                "ports": {sw: {str(e_port): _rle(v[lo_:hi_].tolist()) for e_port, v in sorted(port_state[sw].items())} for sw in sws},
                "switch_up": {sw: _rle(UP[sw][lo_:hi_].tolist()) for sw in sws}}
        (win / fn).write_text(json.dumps(body, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        windows.append({"file": f"mgmt/windows/{fn}", "device": body["device"], "rack": rid, "from": body["from"], "minutes": body["minutes"], "reason": why})
    files = {"bmc_hourly.csv": _csv(bmc_rows, BMC_HOURLY), "switch_hourly.csv": _csv(swrows, SWITCH_HOURLY),
             "poll_gaps.jsonl": "".join(json.dumps(g, sort_keys=True) + "\n" for g in gaps_out),
             "traps.jsonl": "".join(json.dumps(t, sort_keys=True) + "\n" for t in traps_out),
             "collector.jsonl": "".join(json.dumps(c, sort_keys=True) + "\n" for c in collector_log),
             "console_sessions.jsonl": "".join(json.dumps(s, sort_keys=True) + "\n" for s in sess_out),
             "console_ports.json": json.dumps(ports_out, indent=1, sort_keys=True) + "\n",
             "first_answer.json": json.dumps(first_out, indent=1, sort_keys=True) + "\n",
             "answer_key.json": json.dumps(out["answer_key"], indent=1, sort_keys=True) + "\n"}
    for name, text in files.items():
        (dest / name).write_text(text, encoding="utf-8", newline="\n")
    devices = {}
    for n, e in sorted(layer.ep.items()):
        devices[n] = {"family": "bmc", "kind": e["kind"], "rack": e["rack"], "hall": e["hall"], "switch": f"{e['rack'].lower()}-mgmt1",
                      "port": e["port"], "inband": e["inband"], "resource": e["resource"]}
    for s, x in sorted(layer.switches.items()):
        devices[s] = {"family": x["family"], "role": x["role"], "rack": x["rack"], "hall": x["hall"], "leaves": x["leaves"],
                      "console": list(x["console"]) if x["console"] else None, "ports": sorted(port_state[s]),
                      "down_at_start": down0.get(s)}
    man = {"disclaimer": "Synthetic management network telemetry for a portfolio demonstration. All names and readings are fictional.",
           "source": source, "window": layer.window, "devices": devices,
           "files": {k: v.count("\n") - (1 if k.endswith(".csv") else 0) if not k.endswith(".json") else 1 for k, v in files.items()},
           "windows": windows}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man


def _agg_port(layer: MgmtTelemetry, rack_switch: str) -> int:
    """The aggregation switch's port for a rack switch: two per rack, in rack order (swp1 a01-mgmt1, swp2 a01-mgmt2, ...)."""
    rid = layer.switches[rack_switch]["rack"]
    hall = layer.racks[rid]["hall"]
    order = sorted(r for r in layer.by_rack if layer.racks[r]["hall"] == hall)
    return 2 * order.index(rid) + int(rack_switch[-1])
