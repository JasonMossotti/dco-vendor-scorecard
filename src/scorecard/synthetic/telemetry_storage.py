"""Synthetic storage and storage fabric telemetry for Site AUS-1: every drive bay, every fabric port, every client stall.

Portfolio demo; all data fictional. Runs on a finished month (data/sample, and the management layer already written for
it) with its own random stream ("<seed>:telemetry:storage") and writes beside the other telemetry, never into the records
it reads.

What the Telemetry of Record sees:

* **Drives** (Redfish Drive, once a minute per bay): health, state, the bay's indicator, the serial. A month brings a few
  drive failures and a few drives that predict their own failure; each gets an IT Partner ticket, a swap (the pulled
  drive handed to the Security Partner under chain of custody, Interface Agreement HO-5), and a rebuild into the new drive
  at the rebuild rate. A few drives raise a warning that clears on its own.
* **Nodes**: a storage node rebooted for firmware is out for some minutes; the cluster keeps serving (erasure coding).
* **The fabric** (IF-MIB, traps): a compute tray's two storage ports follow the tray itself, which the management layer
  already records as its host management port on ``<rack>-mgmt2`` (out of the rack, unpowered, or not yet built). Leaf
  uplinks go down cleanly now and then (an optic replaced under a ticket; ECMP carries the traffic), and single ports
  blip. Hourly octets follow the cluster's reads and writes through every port they cross.
* **Clients** (the Customer's job telemetry): the minutes each compute node's job waited on storage. Only a flapping
  uplink stalls clients: each flap re-hashes the flows through it and their I/O times out.

Planted (one each a month; ``answer_key.json``), each a case where records do not reconcile:
  1. ``fabric_stall``: a Hall A row leaf uplink flaps; the clients hashed to it stall; the optic ticket says "Customer
     impact: none".
  2. ``custody_gap``: a pulled drive with no custody handover.
  3. ``closed_before_rebuild``: a drive ticket resolved before the replacement's rebuild completed.
  4. ``wrong_bay``: a drive ticket names the bay next to the one whose serial changed.
Decoys: a flap whose ticket states the impact it had (half the months), clean uplink downs with tickets, node reboots,
port blips, predictive swaps, warnings that clear.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from scorecard import storage_fabric as SF

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "telemetry_storage.yaml"
MIN = timedelta(minutes=1)
HOUR_MIN = 60
GPUS_PER_NODE = 4
# bay states in the replay
OK, FAILED, ABSENT, REBUILDING = 0, 1, 2, 3


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _rng(seed: int, *parts: object) -> random.Random:
    key = ":".join(str(p) for p in (seed, "telemetry", "storage") + parts)
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def bay(n: int) -> str:
    return f"Bay{n:02d}"


def split(total: int, weights: list[float]) -> list[int]:
    """Integer shares of ``total`` in proportion to ``weights`` that add up exactly (largest remainder)."""
    s = sum(weights)
    if total == 0 or s <= 0:
        return [0] * len(weights)
    raw = [total * w / s for w in weights]
    out = [int(math.floor(x)) for x in raw]
    rest = total - sum(out)
    for i in sorted(range(len(raw)), key=lambda i: (out[i] - raw[i], i))[:rest]:
        out[i] += 1
    return out


class StorageTelemetry:
    """One month of storage and fabric readings, built from the records, the management layer, and its own stream."""

    def __init__(self, data_dir: str | Path, seed: int, mgmt_dir: str | Path, cfg: dict[str, Any] | None = None):
        from scorecard import site_model as S
        from scorecard import telemetry_mgmt as TGM
        self.d, self.seed = Path(data_dir), seed
        self.cfg = cfg or load_config()
        man = json.loads((self.d / "manifest.json").read_text(encoding="utf-8"))
        w = man["window"]
        self.window = {"start": w["start"] if "T" in w["start"] else w["start"] + "T00:00:00Z",
                       "end": w["end"] if "T" in w["end"] else w["end"] + "T00:00:00Z", "seed": seed}
        self.start, self.end = parse(self.window["start"]), parse(self.window["end"])
        self.M = int((self.end - self.start).total_seconds() // 60)
        self.H = self.M // HOUR_MIN
        self.site = S.load_site()
        topo = json.loads((self.d / "site" / "topology.json").read_text(encoding="utf-8"))
        self.racks = {r["rack"]: r for r in topo["racks"] if r["state"] in ("production", "deployment")}
        self.trays_per_rack = max(len(r["compute_trays"]) for r in self.racks.values())
        self.fab = SF.build(self.site, self.trays_per_rack)
        tel = self.d / "telemetry"
        self.sched = _jsonl(tel / "scheduler_node_states.jsonl")
        self.tickets = json.loads((self.d / "vendor" / "tickets.json").read_text(encoding="utf-8"))
        # the management layer: a tray's host management port on <rack>-mgmt2 is the tray itself, in the rack and powered
        self.mgmt = TGM.load(mgmt_dir, self.d)
        rep = TGM.replay_ports(self.mgmt)
        hp = yaml.safe_load((ROOT / "config" / "telemetry_mgmt.yaml").read_text(encoding="utf-8"))["ports"]["mgmt2"]["compute_host"]
        self.host_up: dict[str, np.ndarray] = {}
        for host in self.fab["trays"]:
            sw = f"{host[:3]}-mgmt2"
            if sw in rep:
                self.host_up[host] = rep[sw]["ports"][hp + int(host[-2:]) - 1].astype(bool)
        self.running = self._running()
        self.people = sorted({t["assigned_to"] for t in self.tickets if t.get("assigned_to")}) or ["RSS-001"]

    # ----------------------------------------------------------------- time helpers
    def m_of(self, t: datetime) -> int:
        return max(0, min(self.M, math.ceil((t - self.start).total_seconds() / 60 - 1e-9)))

    def t_of(self, m: int) -> datetime:
        return self.start + m * MIN

    def at(self, m: float, rng: random.Random, lo: int = 1, hi: int = 40) -> str:
        """A record timestamped in the seconds before minute m (the poll at m is the first to show it)."""
        return iso(self.start + timedelta(minutes=m) - timedelta(seconds=rng.randint(lo, hi)))

    # ----------------------------------------------------------------- which compute nodes run jobs
    def _running(self) -> dict[str, np.ndarray]:
        """Per compute node per minute: installed (Hall A from the start, Hall B from its validated handoff), not drained or
        down in the scheduler, and its tray in the rack and powered (the host port)."""
        handoff: dict[str, int] = {}
        by: dict[str, list[dict]] = {}
        for s in self.sched:
            by.setdefault(s["node"], []).append(s)
            if s["reason"] == "validated handoff":
                r = s["node"][:3].upper()
                handoff[r] = min(handoff.get(r, self.M), self.m_of(parse(s["timestamp"])))
        out = {}
        for host, up in self.host_up.items():
            rack = host[:3].upper()
            r = self.racks.get(rack)
            if r is None:
                continue
            run = up.copy()
            begin = 0 if r["state"] == "production" else handoff.get(rack, self.M)
            run[:begin] = False
            down = None
            for s in sorted(by.get(host, []), key=lambda s: s["timestamp"]):
                m = self.m_of(parse(s["timestamp"]))
                if s["state"] in ("drain", "down"):
                    down = m if down is None else down
                elif down is not None:
                    run[down:m] = False
                    down = None
            if down is not None:
                run[down:] = False
            out[host] = run
        return out

    # ----------------------------------------------------------------- the month
    def run(self) -> dict[str, Any]:
        cfg, B = self.cfg, self.cfg["behaviour"]
        M, fab = self.M, self.fab
        key: dict[str, Any] = {"planted": [], "decoys": []}
        tickets: list[dict] = []
        custody: list[dict] = []
        n_ticket = [0]

        def ticket_no() -> str:
            n_ticket[0] += 1
            return f"INC35{n_ticket[0]:05d}"

        # ---- ports: minute state of every fabric link we model (1 up, 0 down)
        links: dict[tuple[str, str], np.ndarray] = {}
        for sw, e in fab["switches"].items():
            if e["role"] == "spine":
                continue
            for ifn, p in e["ports"].items():
                if p["kind"] == "tray":
                    up = self.host_up.get(p["peer"])
                    links[(sw, ifn)] = up.astype(np.int8).copy() if up is not None else np.zeros(M, dtype=np.int8)
                else:
                    links[(sw, ifn)] = np.ones(M, dtype=np.int8)
        node_on = {n: np.ones(M, dtype=bool) for n in fab["nodes"]}
        node_events: list[dict] = []
        flaps: list[dict] = []
        stalls: list[dict] = []
        busy_up: dict[tuple[str, str], list[tuple[int, int]]] = {}

        def up_free(k: tuple[str, str], a: int, b: int, pad: int = 30) -> bool:
            return 0 <= a < b <= M and not any(x < b + pad and a - pad < y for x, y in busy_up.get(k, []))

        # ---- node reboots (decoy): both node ports down while it is out; at most one node per hall at a time
        rng = _rng(self.seed, "reboots")
        reboots: list[tuple[str, int, int]] = []
        for _ in range(rng.randint(*B["node_reboots"])):
            for _try in range(50):
                n = rng.choice(sorted(fab["nodes"]))
                a = rng.randint(120, M - 120)
                b = a + rng.randint(*B["node_reboot_min"])
                hall = fab["nodes"][n]["hall"]
                if any(fab["nodes"][x]["hall"] == hall and x2 < b + 60 and a - 60 < y2 for x, x2, y2 in reboots):
                    continue
                reboots.append((n, a, b))
                node_on[n][a:b] = False
                for sw, ifn in fab["nodes"][n]["ports"]:
                    links[(sw, ifn)][a:b] = 0
                node_events += [{"timestamp": self.at(a, rng), "node": n, "event": "offline", "reason": "Reboot for firmware update"},
                                {"timestamp": self.at(b, rng), "node": n, "event": "online", "reason": "Rejoined the cluster"}]
                key["decoys"].append({"kind": "node_reboot", "node": n, "from": iso(self.t_of(a)), "minutes": b - a})
                break

        # ---- drives: the start inventory, then failures, predictions, warnings
        rng = _rng(self.seed, "inventory")
        alphabet = string.ascii_uppercase + string.digits

        def serial(r: random.Random) -> str:
            return "NV" + "".join(r.choice(alphabet) for _ in range(10))

        inv0 = {n: {bay(b): serial(rng) for b in range(1, fab["nodes"][n]["drives"] + 1)} for n in sorted(fab["nodes"])}
        used0 = {n: round(rng.uniform(*cfg["drive"]["used_fraction"]) * cfg["drive"]["capacity_tb"] * fab["nodes"][n]["drives"], 3)
                 for n in sorted(fab["nodes"])}
        grow = {n: rng.uniform(0.002, 0.006) for n in sorted(fab["nodes"])}   # TB per hour, net of deletes

        def used_at(n: str, h: int) -> float:
            return round(used0[n] + grow[n] * (h + 1), 3)

        drive_events: list[dict] = []
        degraded: dict[str, list[tuple[int, int]]] = {h: [] for h in fab["halls"]}   # per hall: node-minutes out of protection
        for n, a, b in reboots:
            degraded[fab["nodes"][n]["hall"]].append((a, b))
        bay_busy: dict[tuple[str, str], list[tuple[int, int]]] = {}
        swaps: list[dict] = []

        def protection_ok(hall: str, a: int, b: int) -> bool:
            """Adding [a, b) leaves at least one node of protection everywhere: at most tolerates - 2 others out at once."""
            tol = fab["halls"][hall]["tolerates"]
            cuts = sorted({a} | {x for x, y in degraded[hall] if a < x < b})
            return all(sum(1 for x, y in degraded[hall] if x <= p < y) <= tol - 2 for p in cuts)

        rng = _rng(self.seed, "drives")
        rb_lo, rb_hi = cfg["drive"]["rebuild_tb_per_h"]
        n_fail, n_pred = rng.randint(*B["drive_failures"]), rng.randint(*B["predictive_swaps"])
        k = 0
        while k < n_fail + n_pred or (sum(1 for s in swaps if s["done"] + 90 < M and s["swap"] + 26 * 60 < M) < 3 and k < n_fail + n_pred + 10):
            kind = "failed" if k < n_fail or k >= n_fail + n_pred else "predicted"
            k += 1
            for _try in range(200):
                n = rng.choice(sorted(fab["nodes"]))
                hall = fab["nodes"][n]["hall"]
                b_ = bay(rng.randint(1, fab["nodes"][n]["drives"]))
                t0 = rng.randint(60, M - 8 * 60)
                tk = t0 + rng.randint(*B["ticket_after_min"])
                sw_ = tk + int(rng.uniform(*B["swap_after_h"]) * 60)
                ins = sw_ + rng.randint(2, 6)
                rate = rng.uniform(rb_lo + 0.1, rb_hi - 0.1)
                h_ins = min(ins // HOUR_MIN, self.H - 1)
                dur = max(1, round(used_at(n, h_ins) / fab["nodes"][n]["drives"] / rate * 60))
                done = ins + dur
                end_out = min(done, M) if ins < M else M
                if any(x < end_out + 60 and t0 - 60 < y for x, y in bay_busy.get((n, b_), [])):
                    continue
                if any(n == x for x, xa, xb in reboots if xa < end_out and t0 < xb):
                    continue
                if not protection_ok(hall, t0 if kind == "failed" else sw_, end_out):
                    continue
                break
            else:
                continue
            bay_busy.setdefault((n, b_), []).append((t0, end_out))
            degraded[hall].append((t0 if kind == "failed" else sw_, end_out))
            swaps.append({"kind": kind, "node": n, "hall": hall, "bay": b_, "t0": t0, "ticket": tk, "swap": sw_, "insert": ins,
                          "done": done, "rate": rate, "dur": dur})
        rng = _rng(self.seed, "warnings")
        for _ in range(rng.randint(*B["transient_warnings"])):
            for _try in range(100):
                n = rng.choice(sorted(fab["nodes"]))
                b_ = bay(rng.randint(1, fab["nodes"][n]["drives"]))
                a = rng.randint(60, M - 120)
                b = a + rng.randint(3, 40)
                if any(x < b + 60 and a - 60 < y for x, y in bay_busy.get((n, b_), [])):
                    continue
                bay_busy.setdefault((n, b_), []).append((a, b))
                ser = inv0[n][b_]
                drive_events += [{"timestamp": self.at(a, rng), "node": n, "bay": b_, "serial": ser, "event": "Warning", "health": "Warning",
                                  "state": "Enabled", "indicator": "OK", "percent": None},
                                 {"timestamp": self.at(b, rng), "node": n, "bay": b_, "serial": ser, "event": "Cleared", "health": "OK",
                                  "state": "Enabled", "indicator": "OK", "percent": None}]
                key["decoys"].append({"kind": "transient_warning", "node": n, "bay": b_})
                break

        # ---- plants among the swaps that finish inside the month
        rng = _rng(self.seed, "plants")
        done_swaps = [s for s in swaps if s["done"] + 90 < M and s["swap"] + 26 * 60 < M]
        pick = rng.sample(done_swaps, min(3, len(done_swaps)))
        roles = ["custody_gap", "closed_before_rebuild", "wrong_bay"]
        for s, role in zip(pick, roles):
            s["plant"] = role

        rng = _rng(self.seed, "drive_flow")
        cur = {n: dict(v) for n, v in inv0.items()}
        late_custody = rng.random() < 0.5
        for s in sorted(swaps, key=lambda s: s["t0"]):
            n, b_ = s["node"], s["bay"]
            old = cur[n][b_]
            new = serial(rng)
            if s["kind"] == "failed":
                drive_events.append({"timestamp": self.at(s["t0"], rng), "node": n, "bay": b_, "serial": old, "event": "Failed",
                                     "health": "Critical", "state": "Disabled", "indicator": "Fail", "percent": None})
            else:
                drive_events.append({"timestamp": self.at(s["t0"], rng), "node": n, "bay": b_, "serial": old, "event": "PredictedFailure",
                                     "health": "Warning", "state": "Enabled", "indicator": "PredictiveFailureAnalysis", "percent": None})
            if s["swap"] < M:
                drive_events.append({"timestamp": self.at(s["swap"], rng), "node": n, "bay": b_, "serial": old, "event": "Removed",
                                     "health": None, "state": "Absent", "indicator": None, "percent": None})
            if s["insert"] < M:
                drive_events.append({"timestamp": self.at(s["insert"], rng), "node": n, "bay": b_, "serial": new, "event": "Inserted",
                                     "health": "OK", "state": "Enabled", "indicator": "Rebuild", "percent": 0})
                cur[n][b_] = new
            elif s["swap"] < M:
                cur[n][b_] = None
            if s["done"] < M:
                drive_events.append({"timestamp": self.at(s["done"], rng), "node": n, "bay": b_, "serial": new, "event": "RebuildComplete",
                                     "health": "OK", "state": "Enabled", "indicator": "OK", "percent": 100})
            # the ticket
            no = ticket_no()
            person = rng.choice(self.people)
            opened = self.t_of(s["ticket"]) - timedelta(seconds=rng.randint(0, 50))
            ack = opened + timedelta(minutes=rng.uniform(3, 15))
            loc = f"{n} {b_}"
            shown = b_
            if s.get("plant") == "wrong_bay":
                k = int(b_[3:])
                shown = bay(k + 1 if k < fab["nodes"][n]["drives"] else k - 1)
                loc = f"{n} {shown}"
            what = "failed" if s["kind"] == "failed" else "predicted to fail (FailurePredicted)"
            t = {"number": no, "category": "storage_drive", "hall": s["hall"], "rack": fab["nodes"][n]["rack"], "configuration_item": loc,
                 "short_description": f"NVMe drive {what}: {loc}", "priority": "P4", "assigned_to": person,
                 "opened_at": iso(opened), "acknowledged_at": iso(ack), "resolved_at": None, "state": "In Progress",
                 "close_code": None, "parts_used": [],
                 "customer_impact": f"None: {fab['halls'][s['hall']]['cluster']} kept serving (erasure coding "
                                    f"{fab['halls'][s['hall']]['erasure_coding'][0]}+{fab['halls'][s['hall']]['erasure_coding'][1]})",
                 "work_notes": [{"at": iso(ack), "author": person, "text": f"Acknowledged. Assigned to {person}."}]}
            if s["swap"] < M:
                on_site = self.t_of(s["swap"]) - timedelta(minutes=rng.uniform(10, 40))
                t["work_notes"].append({"at": iso(max(on_site, ack + timedelta(minutes=1))), "author": person,
                                        "text": f"On site at {fab['nodes'][n]['rack']}."})
            if s["insert"] < M:
                t["parts_used"] = [{"part": cfg["drive"]["model"], "location": loc, "removed_serial": old, "installed_serial": new}]
                t["work_notes"].append({"at": iso(self.t_of(s["insert"]) + timedelta(seconds=rng.randint(20, 50))), "author": person,
                                        "text": f"Replaced the drive in {loc}. Removed SN {old}, installed SN {new}. Rebuild started."})
            if s["done"] < M:
                if s.get("plant") == "closed_before_rebuild":
                    early = rng.randint(*cfg["planted"]["closed_before_rebuild_min"])
                    early = min(early, s["dur"] - 3)
                    res = self.t_of(s["done"] - early) - timedelta(seconds=rng.randint(0, 50))
                    key["planted"].append({"kind": "closed_before_rebuild", "ticket": no, "node": n, "bay": b_, "serial": new,
                                           "resolved_at": iso(res), "rebuild_complete": iso(self.t_of(s["done"])), "minutes_early": early})
                else:
                    res = self.t_of(s["done"]) + timedelta(minutes=rng.uniform(*B["close_after_rebuild_min"]))
                if res < self.end:
                    t.update({"resolved_at": iso(res), "state": "Closed", "close_code": "Hardware replaced"})
                    t["work_notes"].append({"at": iso(res), "author": person, "text": "Rebuild complete; drive Status OK. Resolved."})
            if s.get("plant") == "wrong_bay":
                key["planted"].append({"kind": "wrong_bay", "ticket": no, "node": n, "ticket_bay": shown, "changed_bay": b_})
            tickets.append(t)
            # chain of custody for the pulled drive
            if s["swap"] < M:
                if s.get("plant") == "custody_gap":
                    key["planted"].append({"kind": "custody_gap", "serial": old, "node": n, "bay": b_, "ticket": no,
                                           "removed_at": iso(self.t_of(s["swap"]))})
                else:
                    h = rng.uniform(*B["custody_after_h"])
                    if late_custody and s["kind"] == "failed":
                        h, late_custody = rng.uniform(10, 20), False
                        key["decoys"].append({"kind": "late_custody", "serial": old, "hours": round(h, 1)})
                    ho = self.t_of(s["swap"]) + timedelta(hours=h)
                    if ho < self.end:
                        custody.append({"drive_serial": old, "node": n, "bay": b_, "ticket": no, "from": "IT Partner",
                                        "to": "Security Partner", "handed_over_at": iso(ho)})
            s["number"], s["old"], s["new"] = no, old, new
        for s in swaps:
            if not s.get("plant"):
                key["decoys"].append({"kind": f"{s['kind']}_swap", "node": s["node"], "bay": s["bay"], "ticket": s["number"]})

        # ---- fabric: clean uplink downs (decoy, with a ticket), single-port blips, the flaps
        def uplinks(hall: str, role: str) -> list[tuple[str, str]]:
            return [(sw, ifn) for sw, e in fab["switches"].items() if e["hall"] == hall and e["role"] == role
                    for ifn, p in e["ports"].items() if p["kind"] == "uplink"]

        def optic_ticket(sw: str, ifn: str, a: int, b: int, impact: str, r: random.Random) -> dict:
            no = ticket_no()
            person = r.choice(self.people)
            opened = self.t_of(a + r.randint(3, 8)) - timedelta(seconds=r.randint(0, 50))
            ack = opened + timedelta(minutes=r.uniform(2, 8))
            res = self.t_of(b) + timedelta(minutes=r.uniform(10, 40))
            old, new = "OS" + "".join(r.choice(alphabet) for _ in range(10)), "OS" + "".join(r.choice(alphabet) for _ in range(10))
            peer = fab["switches"][sw]["ports"][ifn]
            return {"number": no, "category": "fabric_optic", "hall": fab["switches"][sw]["hall"], "rack": None,
                    "configuration_item": f"{sw} {ifn}", "short_description": f"Uplink errors and link down: {sw} {ifn} to {peer['peer']} {peer['peer_port']}",
                    "priority": "P3", "assigned_to": person, "opened_at": iso(opened), "acknowledged_at": iso(ack),
                    "resolved_at": iso(res), "state": "Closed", "close_code": "Hardware replaced",
                    "parts_used": [{"part": "800G OSFP optic", "location": f"{sw} {ifn}", "removed_serial": old, "installed_serial": new}],
                    "customer_impact": impact,
                    "work_notes": [{"at": iso(ack), "author": person, "text": f"Acknowledged. Assigned to {person}."},
                                   {"at": iso(self.t_of(b - 1)), "author": person, "text": f"Replaced the optic in {sw} {ifn}. Removed SN {old}, installed SN {new}."},
                                   {"at": iso(res), "author": person, "text": f"Link stable, errors cleared. Customer impact: {impact}. Resolved."}]}

        rng = _rng(self.seed, "uplinks")
        for _ in range(rng.randint(*B["uplink_downs"])):
            hall = rng.choice(sorted(fab["halls"]))
            k = rng.choice(uplinks(hall, rng.choice(["row_leaf", "storage_leaf"])))
            a = rng.randint(120, M - 300)
            b = a + rng.randint(*B["uplink_down_min"])
            if not up_free(k, a, b):
                continue
            busy_up.setdefault(k, []).append((a, b))
            links[k][a:b] = 0
            tickets.append(optic_ticket(k[0], k[1], a, b, "None (redundant uplinks)", rng))
            key["decoys"].append({"kind": "uplink_down", "switch": k[0], "ifName": k[1], "from": iso(self.t_of(a)), "minutes": b - a})
        rng = _rng(self.seed, "blips")
        for _ in range(rng.randint(*B["port_blips"])):
            sw = rng.choice(sorted(s for s, e in fab["switches"].items() if e["role"] != "spine"))
            ports = sorted(i for i, p in fab["switches"][sw]["ports"].items() if p["kind"] in ("tray", "node"))
            for _try in range(30):
                ifn = rng.choice(ports)
                a = rng.randint(60, M - 60)
                b = a + rng.randint(*B["port_blip_min"])
                v = links[(sw, ifn)]
                other = [(x, i) for x, i in (fab["trays"].get(fab["switches"][sw]["ports"][ifn]["peer"]) or
                                              [tuple(p) for p in fab["nodes"].get(fab["switches"][sw]["ports"][ifn]["peer"], {}).get("ports", [])])
                         if (x, i) != (sw, ifn)]
                if v[a - 5:b + 5].min() == 0 or any(links[o][a - 5:b + 5].min() == 0 for o in other):
                    continue
                v[a:b] = 0
                key["decoys"].append({"kind": "port_blip", "switch": sw, "ifName": ifn, "from": iso(self.t_of(a)), "minutes": b - a})
                break

        def flap(hall: str, row: int, r: random.Random, plant: bool) -> dict | None:
            F = cfg["flap"]
            leaf = r.choice(fab["halls"][hall]["row_leaves"][row])
            ifn = r.choice(sorted(i for i, p in fab["switches"][leaf]["ports"].items() if p["kind"] == "uplink"))
            racks = sorted({h[:3].upper() for h, x in fab["trays"].items() if x[0][0] in fab["halls"][hall]["row_leaves"][row]})
            for _try in range(200):
                dur = r.randint(*F["minutes"])
                a = r.randint(180, M - dur - 240)
                b = a + dur
                if not up_free((leaf, ifn), a, b, pad=120):
                    continue
                if any(f["hall"] == hall and f["a"] - 240 < b and a < f["b"] + 240 for f in flaps):
                    continue
                live = [rk for rk in racks if sum(self.running.get(f"{rk.lower()}-ct{s:02d}", np.zeros(M, bool))[a:b].all()
                                                for s in range(1, self.trays_per_rack + 1)) >= self.trays_per_rack - 2]
                lo, hi = F["racks_hashed"]
                if len(live) < lo:
                    continue
                hashed = sorted(r.sample(live, min(len(live), r.randint(lo, hi))))
                # the flap: down a minute, up one or two, until the window closes; at least flap_downs within any 15 minutes
                v = links[(leaf, ifn)]
                m, downs = a, 0
                while m < b - 1:
                    v[m] = 0
                    downs += 1
                    m += 1 + r.randint(1, 2)
                v[b - 1] = 0      # the last down: the optic pulled and replaced
                downs += 1
                if downs < F["downs"][0]:
                    v[a:b] = 1
                    continue
                busy_up.setdefault((leaf, ifn), []).append((a, b))
                fl = {"hall": hall, "row": row, "switch": leaf, "ifName": ifn, "a": a, "b": b, "racks": hashed, "downs": downs}
                # the stalls: every running node of the hashed racks waits on I/O from about the first down to the last up
                gh = 0.0
                for rk in hashed:
                    for s in range(1, self.trays_per_rack + 1):
                        host = f"{rk.lower()}-ct{s:02d}"
                        sa, sb = a + r.randint(0, 1), b + r.randint(0, 2)
                        run = self.running.get(host)
                        if run is None:
                            continue
                        mask = run[sa:sb]
                        e = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
                        for x, y in zip(e[::2].tolist(), e[1::2].tolist()):
                            stalls.append({"node": host, "rack": rk, "from": iso(self.t_of(sa + x)), "to": iso(self.t_of(sa + y)),
                                           "minutes": y - x, "cause": "I/O wait"})
                            gh += (y - x) * GPUS_PER_NODE / 60
                fl["gpu_hours"] = round(gh, 1)
                flaps.append(fl)
                return fl
            return None

        rng = _rng(self.seed, "flap")
        hall_a = sorted(fab["halls"])[0]
        fl = flap(hall_a, rng.randint(1, len(fab["halls"][hall_a]["row_leaves"])), rng, True)
        if fl:
            tickets.append(optic_ticket(fl["switch"], fl["ifName"], fl["a"], fl["b"], "None (redundant uplinks)", rng))
            key["planted"].append({"kind": "fabric_stall", "switch": fl["switch"], "ifName": fl["ifName"], "ticket": tickets[-1]["number"],
                                   "from": iso(self.t_of(fl["a"])), "to": iso(self.t_of(fl["b"])), "racks": fl["racks"], "gpu_hours": fl["gpu_hours"]})
        if rng.random() < B["reported_flap"]:
            hall = rng.choice(sorted(fab["halls"]))
            fl2 = flap(hall, rng.randint(1, len(fab["halls"][hall]["row_leaves"])), rng, False)
            if fl2 and fl2["gpu_hours"] > 0:
                imp = (f"I/O stalls on racks {', '.join(fl2['racks'])} for {fl2['b'] - fl2['a']} min; "
                       f"{fl2['gpu_hours']:.1f} GPU-hours idle")
                tickets.append(optic_ticket(fl2["switch"], fl2["ifName"], fl2["a"], fl2["b"], imp, rng))
                key["decoys"].append({"kind": "reported_flap", "switch": fl2["switch"], "ifName": fl2["ifName"], "ticket": tickets[-1]["number"],
                                      "gpu_hours": fl2["gpu_hours"]})

        # number the tickets in the order they were opened, as the ticketing system would
        tickets.sort(key=lambda t: t["opened_at"])
        renum = {t["number"]: f"INC35{i:05d}" for i, t in enumerate(tickets, 1)}
        for t in tickets:
            t["number"] = renum[t["number"]]
        for x in key["planted"] + key["decoys"] + custody + swaps:
            if x.get("ticket") in renum:
                x["ticket"] = renum[x["ticket"]]
        for s_ in swaps:
            s_["number"] = renum.get(s_.get("number"), s_.get("number"))
        drive_events.sort(key=lambda e: (e["timestamp"], e["node"], e["bay"]))
        node_events.sort(key=lambda e: e["timestamp"])
        stalls.sort(key=lambda s: (s["from"], s["node"]))
        custody.sort(key=lambda c: c["handed_over_at"])
        return {"links": links, "node_on": node_on, "inv0": inv0, "used_at": used_at, "drive_events": drive_events,
                "node_events": node_events, "swaps": swaps, "tickets": tickets, "custody": custody, "flaps": flaps,
                "stalls": stalls, "key": key}


# --------------------------------------------------------------------------- writing
def _csv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue()


def _jl(rows: list[dict]) -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)


NODE_HOURLY = ["hour", "node", "cluster", "online_min", "drives_ok", "drives_failed", "drives_absent", "drives_rebuilding",
               "read_gb", "write_gb", "used_tb"]
CLUSTER_HOURLY = ["hour", "cluster", "hall", "nodes_online", "read_gb", "write_gb", "used_tb", "protection_min"]
PORT_HOURLY = ["hour", "switch", "ifName", "up_s", "in_octets", "out_octets", "in_errors"]
LEAF_HOURLY = ["hour", "switch", "tray_ports", "tray_ports_up", "tray_port_min", "in_octets", "out_octets"]


def bay_states(layer: StorageTelemetry, out: dict[str, Any]) -> dict[str, np.ndarray]:
    """Per node: [bays x minutes] state (OK, FAILED, ABSENT, REBUILDING) from the drive event log."""
    M = layer.M
    st = {n: np.zeros((len(v), M), dtype=np.int8) for n, v in out["inv0"].items()}
    for e in out["drive_events"]:
        m = layer.m_of(parse(e["timestamp"]))
        row = int(e["bay"][3:]) - 1
        s = {"Failed": FAILED, "Removed": ABSENT, "Inserted": REBUILDING, "RebuildComplete": OK}.get(e["event"])
        if s is not None:
            st[e["node"]][row, m:] = s
    return st


def write_storage(layer: StorageTelemetry, out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, Any]:
    """Write the storage telemetry's committed tier to dest (hourly tables and the logs)."""
    cfg, M, H, fab = layer.cfg, layer.M, layer.H, layer.fab
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    hours = [iso(layer.t_of(h * HOUR_MIN)) for h in range(H)]
    links = out["links"]
    # ---- traps from every port's minute state (both ends of an uplink), and the ports down at the start
    traps: list[dict] = []
    down0: dict[str, list[str]] = {s: [] for s in fab["switches"]}
    rng = _rng(layer.seed, "traps")
    for (sw, ifn), v in sorted(links.items()):
        ends = [(sw, ifn)]
        p = fab["switches"][sw]["ports"][ifn]
        if p["kind"] == "uplink":
            ends.append((p["peer"], p["peer_port"]))
        for s_, i_ in ends:
            if v[0] == 0:
                down0[s_].append(i_)
        ch = np.flatnonzero(np.diff(v.astype(np.int8))) + 1
        for m in ch.tolist():
            trap = "linkUp" if v[m] == 1 else "linkDown"
            for s_, i_ in ends:
                traps.append({"timestamp": layer.at(m, rng), "switch": s_, "ifName": i_, "trap": trap})
    traps.sort(key=lambda e: (e["timestamp"], e["switch"], e["ifName"]))
    # ---- drives and nodes
    bst = bay_states(layer, out)
    node_rows, cluster_rows = [], []
    rng = _rng(layer.seed, "load")
    L = cfg["load"]
    rk_read = {r: rng.uniform(*L["read_per_rack"]) for r in sorted(layer.racks)}
    rk_write = {r: rng.uniform(*L["write_per_rack"]) for r in sorted(layer.racks)}
    stalled = {h: np.zeros(M, dtype=bool) for h in layer.running}
    for s in out["stalls"]:
        stalled[s["node"]][layer.m_of(parse(s["from"])):layer.m_of(parse(s["to"]))] = True
    port_rows, leaf_rows = [], []
    reads: dict[str, list[int]] = {}
    writes: dict[str, list[int]] = {}
    for hid, fh in sorted(fab["halls"].items()):
        tol = fh["tolerates"]
        nodes = fh["nodes"]
        out_mask = np.zeros((len(nodes), M), dtype=bool)
        for i, n in enumerate(nodes):
            out_mask[i] = (~out["node_on"][n]) | (bst[n] != OK).any(0)
        prot = tol - out_mask.sum(0)
        # the cluster's traffic per hour: clients that are running and not stalled, plus the floor
        hosts = [h for h in layer.running if layer.racks[h[:3].upper()]["hall"] == hid]
        active = {h: (layer.running[h] & ~stalled[h]) for h in hosts}
        rd_h, wr_h = np.zeros(H), np.zeros(H)
        for h in hosts:
            per = active[h].reshape(H, HOUR_MIN).mean(1) / layer.trays_per_rack
            rd_h += per * rk_read[h[:3].upper()]
            wr_h += per * rk_write[h[:3].upper()]
        diurnal = np.array([1 + 0.12 * math.sin(2 * math.pi * ((h + 6) % 24) / 24) for h in range(H)])
        noise_r = np.array([rng.uniform(0.95, 1.05) for _ in range(H)])
        noise_w = np.array([rng.uniform(0.92, 1.08) for _ in range(H)])
        read_b = ((rd_h * diurnal * noise_r + L["idle_floor"]) * 3600 * 1e9).astype(np.int64)
        write_b = ((wr_h * diurnal * noise_w + L["idle_floor"] * 0.2) * 3600 * 1e9).astype(np.int64)
        on = np.stack([out["node_on"][n].reshape(H, HOUR_MIN).sum(1) for n in nodes])
        wts = [[rng.uniform(0.9, 1.1) for _ in range(H)] for _ in nodes]
        for h in range(H):
            rs = split(int(read_b[h]), [on[i, h] * wts[i][h] for i in range(len(nodes))])
            ws = split(int(write_b[h]), [on[i, h] * wts[i][h] for i in range(len(nodes))])
            for i, n in enumerate(nodes):
                reads.setdefault(n, []).append(rs[i])
                writes.setdefault(n, []).append(ws[i])
        for h in range(H):
            sl = slice(h * HOUR_MIN, (h + 1) * HOUR_MIN)
            tot_r = tot_w = 0
            used = 0.0
            for i, n in enumerate(nodes):
                end = bst[n][:, (h + 1) * HOUR_MIN - 1]
                u = out["used_at"](n, h)
                used += u
                tot_r += reads[n][h]
                tot_w += writes[n][h]
                node_rows.append({"hour": hours[h], "node": n, "cluster": fh["cluster"], "online_min": int(on[i, h]),
                                  "drives_ok": int((end == OK).sum()), "drives_failed": int((end == FAILED).sum()),
                                  "drives_absent": int((end == ABSENT).sum()), "drives_rebuilding": int((end == REBUILDING).sum()),
                                  "read_gb": f"{reads[n][h] / 1e9:.3f}", "write_gb": f"{writes[n][h] / 1e9:.3f}", "used_tb": f"{u:.3f}"})
            cluster_rows.append({"hour": hours[h], "cluster": fh["cluster"], "hall": hid,
                                 "nodes_online": int(sum(out["node_on"][n][(h + 1) * HOUR_MIN - 1] for n in nodes)),
                                 "read_gb": f"{tot_r / 1e9:.3f}", "write_gb": f"{tot_w / 1e9:.3f}", "used_tb": f"{used:.3f}",
                                 "protection_min": int(prot[sl].min())})
        # ---- node ports (on the storage leaves): each node's bytes over its ports by seconds up
        st_up: dict[str, list[list[int]]] = {sw: [[0, 0] for _ in range(H)] for sw in fh["storage_leaves"]}  # [out, in] towards spines
        for n in nodes:
            ps = [tuple(p) for p in fab["nodes"][n]["ports"]]
            ups = [links[p].reshape(H, HOUR_MIN).sum(1) for p in ps]
            for h in range(H):
                ro = split(reads[n][h], [float(u[h]) for u in ups])
                wi = split(writes[n][h], [float(u[h]) for u in ups])
                for k, (sw, ifn) in enumerate(ps):
                    port_rows.append({"hour": hours[h], "switch": sw, "ifName": ifn, "up_s": int(ups[k][h]) * 60,
                                      "in_octets": ro[k], "out_octets": wi[k], "in_errors": 0})
                    st_up[sw][h][0] += ro[k]
                    st_up[sw][h][1] += wi[k]
        # node ports: in_octets = from the node (its reads), out_octets = to the node (writes)
        # ---- uplinks: the storage leaves send the reads up and take the writes down; the row leaves the reverse
        row_leaves = [x for row in sorted(fh["row_leaves"]) for x in fh["row_leaves"][row]]
        tray_up = {}
        for sw in row_leaves:
            ps = [i for i, p in fab["switches"][sw]["ports"].items() if p["kind"] == "tray"]
            mins = sum(links[(sw, i)].reshape(H, HOUR_MIN).sum(1) for i in ps)
            act = np.zeros(H)
            for i in ps:
                host = fab["switches"][sw]["ports"][i]["peer"]
                if host in active:
                    act += (active[host] & links[(sw, i)].astype(bool)).reshape(H, HOUR_MIN).sum(1)
            tray_up[sw] = (ps, mins, act)
        flaps_by = {(f["switch"], f["ifName"]) for f in out["flaps"]}
        for h in range(H):
            hall_r = sum(st_up[sw][h][0] for sw in fh["storage_leaves"])
            hall_w = sum(st_up[sw][h][1] for sw in fh["storage_leaves"])
            # storage leaves: reads out of the uplinks, writes in
            for sw in fh["storage_leaves"]:
                ups = sorted(i for i, p in fab["switches"][sw]["ports"].items() if p["kind"] == "uplink")
                w = [float(links[(sw, i)][h * HOUR_MIN:(h + 1) * HOUR_MIN].sum()) for i in ups]
                ro, wi = split(st_up[sw][h][0], w), split(st_up[sw][h][1], w)
                for k, i in enumerate(ups):
                    port_rows.append({"hour": hours[h], "switch": sw, "ifName": i, "up_s": int(w[k]) * 60,
                                      "in_octets": wi[k], "out_octets": ro[k], "in_errors": 0})
            # row leaves: reads in from the uplinks and out to the trays, writes the reverse
            wl = [float(tray_up[sw][2][h]) or 0.0 for sw in row_leaves]
            if sum(wl) == 0:
                wl = [1.0] * len(row_leaves)
            rl, wlv = split(hall_r, wl), split(hall_w, wl)
            for j, sw in enumerate(row_leaves):
                ups = sorted(i for i, p in fab["switches"][sw]["ports"].items() if p["kind"] == "uplink")
                w = [float(links[(sw, i)][h * HOUR_MIN:(h + 1) * HOUR_MIN].sum()) for i in ups]
                ri, wo = split(rl[j], w), split(wlv[j], w)
                for k, i in enumerate(ups):
                    err = 0
                    if (sw, i) in flaps_by:
                        downs = int((np.diff(links[(sw, i)][max(0, h * HOUR_MIN - 1):(h + 1) * HOUR_MIN].astype(np.int8)) == -1).sum())
                        err = downs * rng.randint(4000, 30000)
                    port_rows.append({"hour": hours[h], "switch": sw, "ifName": i, "up_s": int(w[k]) * 60,
                                      "in_octets": ri[k], "out_octets": wo[k], "in_errors": err})
                ps, mins, _ = tray_up[sw]
                end = sum(int(links[(sw, i)][(h + 1) * HOUR_MIN - 1]) for i in ps)
                leaf_rows.append({"hour": hours[h], "switch": sw, "tray_ports": len(ps), "tray_ports_up": end,
                                  "tray_port_min": int(mins[h]), "in_octets": wlv[j], "out_octets": rl[j]})
    port_rows.sort(key=lambda r: (r["hour"], r["switch"], SF.sort_key(r["ifName"])))
    leaf_rows.sort(key=lambda r: (r["hour"], r["switch"]))
    node_rows.sort(key=lambda r: (r["hour"], r["node"]))
    # ---- inventory at the start and the end (Redfish Drive SerialNumber per bay)
    end_inv = {n: dict(v) for n, v in out["inv0"].items()}
    for e in out["drive_events"]:
        if e["event"] == "Removed":
            end_inv[e["node"]][e["bay"]] = None
        elif e["event"] == "Inserted":
            end_inv[e["node"]][e["bay"]] = e["serial"]
    inv_rows = [{"node": n, "bay": b, "serial_start": out["inv0"][n][b], "serial_end": end_inv[n][b] or ""}
                for n in sorted(out["inv0"]) for b in sorted(out["inv0"][n])]
    devices = {}
    for n, e in fab["nodes"].items():
        devices[n] = {"family": "node", "hall": e["hall"], "rack": e["rack"], "cluster": fab["halls"][e["hall"]]["cluster"],
                      "ports": [list(p) for p in e["ports"]], "drives": e["drives"]}
    for sw, e in fab["switches"].items():
        devices[sw] = {"family": e["role"], "hall": e["hall"], "row": e["row"], "pair": e.get("pair"),
                       "ports": {i: [p["kind"], p["peer"], p["peer_port"], p["gbps"]] for i, p in sorted(e["ports"].items(), key=lambda kv: SF.sort_key(kv[0]))},
                       "down_at_start": sorted(down0[sw], key=SF.sort_key)}
    clusters = {fh["cluster"]: {"hall": hid, "nodes": fh["nodes"], "erasure_coding": fh["erasure_coding"], "tolerates": fh["tolerates"],
                                "racks": fh["racks"], "spines": fh["spines"], "storage_leaves": fh["storage_leaves"],
                                "row_leaves": {str(k): v for k, v in fh["row_leaves"].items()}}
                for hid, fh in sorted(fab["halls"].items())}
    files = {
        "nodes_hourly.csv": _csv(node_rows, NODE_HOURLY),
        "cluster_hourly.csv": _csv(cluster_rows, CLUSTER_HOURLY),
        "ports_hourly.csv": _csv(port_rows, PORT_HOURLY),
        "leaf_hourly.csv": _csv(leaf_rows, LEAF_HOURLY),
        "drive_inventory.csv": _csv(inv_rows, ["node", "bay", "serial_start", "serial_end"]),
        "drive_events.jsonl": _jl(out["drive_events"]),
        "node_events.jsonl": _jl(out["node_events"]),
        "traps.jsonl": _jl(traps),
        "client_stalls.jsonl": _jl(out["stalls"]),
        "tickets.json": json.dumps(out["tickets"], indent=1, sort_keys=True) + "\n",
        "custody.csv": _csv(out["custody"], ["drive_serial", "node", "bay", "ticket", "from", "to", "handed_over_at"]),
        "answer_key.json": json.dumps(out["key"], indent=1, sort_keys=True) + "\n",
    }
    for name, text in files.items():
        (dest / name).write_text(text, encoding="utf-8", newline="\n")
    man = {"disclaimer": "Synthetic storage and fabric telemetry for a fictional site; portfolio demo.",
           "window": layer.window, "source": source, "devices": devices, "clusters": clusters,
           "drive": {"capacity_tb": cfg["drive"]["capacity_tb"], "model": cfg["drive"]["model"]},
           "files": sorted(files)}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {"nodes": len(fab["nodes"]), "drives": sum(e["drives"] for e in fab["nodes"].values()), "switches": len(fab["switches"]),
            "drive_events": len(out["drive_events"]), "tickets": len(out["tickets"]), "stalls": len(out["stalls"]),
            "planted": len(out["key"]["planted"])}
