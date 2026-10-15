"""The storage and storage fabric telemetry: agreements with the records, and the findings where records do not reconcile.

Like the other telemetry sections, every check reads only what the layer publishes (``data/telemetry/storage/``), the
management layer it builds on (``data/telemetry/mgmt/``), and the records already written for the month
(``data/sample/``), never the generator's internals.

Agreements (the telemetry never contradicts itself or the records; each returns cases checked and disagreements):

1. drives: replaying the drive event log from the start inventory gives the end inventory, bay by bay, and every event
   fits its bay (a removal takes the drive that is there, an insertion goes into an empty bay, a rebuild completes on the
   drive that was inserted).
2. nodes: each node's hourly drive counts and minutes online equal the event log and the node log.
3. cluster: each cluster hour is the sum of its nodes, and its lowest protection in the hour is the erasure code's
   tolerance less the nodes that were out or held a failed, missing, or rebuilding drive.
4. rebuild: every rebuild moves the drive's share of its node's data at a rate inside the configured range.
5. ports: replaying the trap log gives every port's seconds up per hour and each row leaf's tray ports up.
6. traffic: each node's reads and writes equal the octets on its two ports; each hall's reads and writes cross the storage
   leaves' uplinks, the row leaves' uplinks, and the row leaves' tray ports, byte for byte.
7. trays: a compute tray's two storage ports are both down whenever the tray is (its host management port, management
   layer), and at least one is up whenever it is up.
8. stalls: every client I/O stall falls inside a flapping episode on an uplink of its row's leaves, on a node that was
   running a job; every flapping episode on a row leaf uplink stalls someone.

Findings (records that do not reconcile; config/telemetry_storage.yaml ``checks``):

* SP-STALL: a flapping uplink that stalled running jobs, with no ticket, or a ticket whose stated customer impact does
  not match the GPU-hours the clients lost.
* SP-CUSTODY: a pulled drive with no chain-of-custody handover to the Security Partner (Interface Agreement HO-5).
* SP-REBUILD: a drive ticket resolved before the replacement drive's rebuild completed.
* SP-BAY: a drive ticket naming a different bay from the one whose serial changed.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from scorecard import telemetry_mgmt as TGM
from scorecard.synthetic import telemetry_storage as TSG
from scorecard.telemetry import Check, _csv, _jsonl, parse

HOUR = 60
GPUS_PER_NODE = 4
OK, FAILED, ABSENT, REBUILDING = 0, 1, 2, 3
CONTRACT = {
    "fabric_stall": "Interface Agreement RACI: Leaf and spine switches (physical replacement); IT Partner SLA ticket records",
    "custody_gap": "Interface Agreement HO-5 (storage media under chain of custody); Security SLA media destruction",
    "closed_before_rebuild": "Interface Agreement RACI: Storage nodes and drives (physical); IT Partner SLA ticket records",
    "wrong_bay": "Interface Agreement RACI: Storage nodes and drives (physical); IT Partner SLA ticket records",
}


@dataclass
class StorageData:
    dir: Path
    sample: Path
    manifest: dict
    node_hourly: list[dict]
    cluster_hourly: list[dict]
    port_hourly: list[dict]
    leaf_hourly: list[dict]
    inventory: list[dict]
    drive_events: list[dict]
    node_events: list[dict]
    traps: list[dict]
    stalls: list[dict]
    tickets: list[dict]
    custody: list[dict]
    ledger: list[dict]
    counts: list[dict]
    sched: list[dict]
    topology: dict
    mgmt: Any

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def M(self) -> int:
        return int((parse(self.manifest["window"]["end"]) - self.start).total_seconds() // 60)

    @property
    def H(self) -> int:
        return self.M // HOUR

    def m_of(self, ts: str) -> int:
        return max(0, min(self.M, math.ceil((parse(ts) - self.start).total_seconds() / 60 - 1e-9)))

    def iso(self, m: int) -> str:
        return (self.start + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def devices(self, *families: str) -> list[str]:
        return sorted(d for d, x in self.manifest["devices"].items() if x["family"] in families)


def load(storage_dir: str | Path, sample_dir: str | Path, mgmt_dir: str | Path | None = None) -> StorageData:
    d, s = Path(storage_dir), Path(sample_dir)
    mgmt_dir = Path(mgmt_dir) if mgmt_dir else d.parent / "mgmt"
    return StorageData(dir=d, sample=s, manifest=json.loads((d / "manifest.json").read_text(encoding="utf-8")),
                       node_hourly=_csv(d / "nodes_hourly.csv"), cluster_hourly=_csv(d / "cluster_hourly.csv"),
                       port_hourly=_csv(d / "ports_hourly.csv"), leaf_hourly=_csv(d / "leaf_hourly.csv"),
                       inventory=_csv(d / "drive_inventory.csv"), drive_events=_jsonl(d / "drive_events.jsonl"),
                       node_events=_jsonl(d / "node_events.jsonl"), traps=_jsonl(d / "traps.jsonl"),
                       stalls=_jsonl(d / "client_stalls.jsonl"), tickets=json.loads((d / "tickets.json").read_text(encoding="utf-8")),
                       custody=_csv(d / "custody.csv"), ledger=_csv(d / "spares_ledger.csv"),
                       counts=_csv(d / "spares_cycle_counts.csv"), sched=_jsonl(s / "telemetry" / "scheduler_node_states.jsonl"),
                       topology=json.loads((s / "site" / "topology.json").read_text(encoding="utf-8")),
                       mgmt=TGM.load(mgmt_dir, s))


# ------------------------------------------------------------------------- the published logs, replayed
def spans(mask: np.ndarray) -> list[tuple[int, int]]:
    return TGM.spans(mask)


def replay_links(t: StorageData) -> dict[tuple[str, str], np.ndarray]:
    """Every port of every fabric switch per minute (1 up, 0 down): the manifest's ports down at the start, then traps."""
    out: dict[tuple[str, str], np.ndarray] = {}
    for sw, x in t.manifest["devices"].items():
        if x["family"] == "node":
            continue
        d0 = set(x["down_at_start"])
        for ifn in x["ports"]:
            out[(sw, ifn)] = np.zeros(t.M, dtype=np.int8) if ifn in d0 else np.ones(t.M, dtype=np.int8)
    for e in sorted(t.traps, key=lambda e: e["timestamp"]):
        k = (e["switch"], e["ifName"])
        if k in out:
            out[k][t.m_of(e["timestamp"]):] = 1 if e["trap"] == "linkUp" else 0
    return out


def node_online(t: StorageData) -> dict[str, np.ndarray]:
    out = {n: np.ones(t.M, dtype=bool) for n in t.devices("node")}
    for e in sorted(t.node_events, key=lambda e: e["timestamp"]):
        out[e["node"]][t.m_of(e["timestamp"]):] = e["event"] == "online"
    return out


def replay_bays(t: StorageData) -> tuple[dict[str, np.ndarray], dict[tuple[str, str], str | None], list[str]]:
    """Per node [bays x minutes] state, the serial in each bay at the end, and every event that does not fit its bay."""
    devs = t.manifest["devices"]
    cur: dict[tuple[str, str], str | None] = {(r["node"], r["bay"]): r["serial_start"] for r in t.inventory}
    st = {n: np.zeros((devs[n]["drives"], t.M), dtype=np.int8) for n in t.devices("node")}
    state: dict[tuple[str, str], int] = {k: OK for k in cur}
    bad: list[str] = []
    for e in sorted(t.drive_events, key=lambda e: e["timestamp"]):
        k = (e["node"], e["bay"])
        m = t.m_of(e["timestamp"])
        ev, ser = e["event"], e["serial"]
        if k not in cur:
            bad.append(f"{e['node']} {e['bay']}: no such bay")
            continue
        if ev in ("Failed", "PredictedFailure", "Warning", "Cleared", "Removed"):
            if cur[k] != ser:
                bad.append(f"{e['node']} {e['bay']} {ev} at {e['timestamp']}: serial {ser}, the bay holds {cur[k]}")
            if ev == "Failed":
                state[k] = FAILED
            elif ev == "Removed":
                cur[k], state[k] = None, ABSENT
        elif ev == "Inserted":
            if cur[k] is not None:
                bad.append(f"{e['node']} {e['bay']}: {ser} inserted into a bay holding {cur[k]}")
            cur[k], state[k] = ser, REBUILDING
        elif ev == "RebuildComplete":
            if cur[k] != ser or state[k] != REBUILDING:
                bad.append(f"{e['node']} {e['bay']}: rebuild complete on {ser}, not a drive being rebuilt")
            state[k] = OK
        st[e["node"]][int(e["bay"][3:]) - 1, m:] = state[k]
    return st, cur, bad


def host_up(t: StorageData) -> dict[str, np.ndarray]:
    """Each compute tray in the rack and powered: its host management port on <rack>-mgmt2 (management layer)."""
    import yaml
    rep = TGM.replay_ports(t.mgmt)
    hp = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "telemetry_mgmt.yaml").read_text(encoding="utf-8"))["ports"]["mgmt2"]["compute_host"]
    out = {}
    for sw, x in t.manifest["devices"].items():
        if x["family"] != "row_leaf":
            continue
        for ifn, (kind, peer, _, _) in x["ports"].items():
            if kind == "tray" and peer not in out and f"{peer[:3]}-mgmt2" in rep:
                out[peer] = rep[f"{peer[:3]}-mgmt2"]["ports"][hp + int(peer[-2:]) - 1].astype(bool)
    return out


def running(t: StorageData, hosts: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Per compute node: installed (Hall A from the start, Hall B from its validated handoff), not drained or down in the
    scheduler, and its tray up."""
    state = {r["rack"]: r["state"] for r in t.topology["racks"]}
    handoff: dict[str, int] = {}
    by: dict[str, list[dict]] = {}
    for s in t.sched:
        by.setdefault(s["node"], []).append(s)
        if s["reason"] == "validated handoff":
            r = s["node"][:3].upper()
            handoff[r] = min(handoff.get(r, t.M), t.m_of(s["timestamp"]))
    out = {}
    for host, up in hosts.items():
        rack = host[:3].upper()
        run = up.copy()
        run[:0 if state.get(rack) == "production" else handoff.get(rack, t.M)] = False
        down = None
        for s in sorted(by.get(host, []), key=lambda s: s["timestamp"]):
            m = t.m_of(s["timestamp"])
            if s["state"] in ("drain", "down"):
                down = m if down is None else down
            elif down is not None:
                run[down:m] = False
                down = None
        if down is not None:
            run[down:] = False
        out[host] = run
    return out


def flaps(t: StorageData, cfg: dict[str, Any], links: dict[tuple[str, str], np.ndarray] | None = None) -> list[dict]:
    """Flapping episodes on leaf uplinks: runs of linkDowns no more than five minutes apart, at least ``flap_downs`` of
    them within ``flap_window_min``. The episode runs from its first down to the link's last up."""
    ck = cfg["checks"]
    devs = t.manifest["devices"]
    downs: dict[tuple[str, str], list[int]] = {}
    for e in t.traps:
        x = devs.get(e["switch"])
        if e["trap"] == "linkDown" and x and x["family"] in ("row_leaf", "storage_leaf") and x["ports"][e["ifName"]][0] == "uplink":
            downs.setdefault((e["switch"], e["ifName"]), []).append(t.m_of(e["timestamp"]))
    links = links if links is not None else replay_links(t)
    out = []
    for (sw, ifn), ms in sorted(downs.items()):
        ms.sort()
        runs: list[list[int]] = [[ms[0]]]
        for m in ms[1:]:
            if m - runs[-1][-1] <= 5:
                runs[-1].append(m)
            else:
                runs.append([m])
        for r in runs:
            if not any(sum(1 for y in r if x <= y < x + ck["flap_window_min"]) >= ck["flap_downs"] for x in r):
                continue
            v = links[(sw, ifn)]
            b = r[-1] + 1
            while b < t.M and v[b] == 0:
                b += 1
            x = devs[sw]
            out.append({"switch": sw, "ifName": ifn, "hall": x["hall"], "row": x["row"], "role": x["family"], "a": r[0], "b": b,
                        "downs": len(r)})
    return out


def rack_row(t: StorageData) -> dict[str, tuple[str, int]]:
    """Each compute tray's (hall, row) from the row leaves' port maps."""
    out = {}
    for sw, x in t.manifest["devices"].items():
        if x["family"] == "row_leaf":
            for kind, peer, _, _ in x["ports"].values():
                if kind == "tray":
                    out[peer] = (x["hall"], x["row"])
    return out


# ------------------------------------------------------------------------- agreements
def agreements(t: StorageData, cfg: dict[str, Any]) -> list[Check]:
    devs = t.manifest["devices"]
    M, H = t.M, t.H
    hours = [t.iso(h * HOUR) for h in range(H)]
    links = replay_links(t)
    online = node_online(t)
    bst, end_inv, bad = replay_bays(t)
    out = []

    # 1. drives
    c = Check("drives", "The drive event log, replayed from the start inventory, gives the end inventory bay by bay")
    for r in t.inventory:
        c((end_inv[(r["node"], r["bay"])] or "") == r["serial_end"], f"{r['node']} {r['bay']}: replay gives {end_inv[(r['node'], r['bay'])]}, "
          f"the inventory {r['serial_end']}")
    for e in t.drive_events:
        c(True, "")
    for b in bad:
        c(False, b)
    out.append(c)

    # 2. nodes
    c = Check("nodes", "Each node's hourly drive counts and minutes online equal the drive and node logs")
    for r in t.node_hourly:
        h = hours.index(r["hour"]) if r["hour"] in hours else None
        if h is None:
            c(False, f"{r['node']} {r['hour']}: hour outside the month")
            continue
        n = r["node"]
        end = bst[n][:, (h + 1) * HOUR - 1]
        want = {"drives_ok": (end == OK).sum(), "drives_failed": (end == FAILED).sum(), "drives_absent": (end == ABSENT).sum(),
                "drives_rebuilding": (end == REBUILDING).sum(), "online_min": online[n][h * HOUR:(h + 1) * HOUR].sum()}
        diff = [f"{k} {r[k]} (log {int(v)})" for k, v in want.items() if int(r[k]) != int(v)]
        c(not diff, f"{n} {r['hour']}: {', '.join(diff)}")
    out.append(c)

    # 3. cluster
    c = Check("cluster", "Each cluster hour is the sum of its nodes, and its lowest protection matches the nodes out")
    by_node: dict[tuple[str, str], dict] = {(r["hour"], r["node"]): r for r in t.node_hourly}
    for r in t.cluster_hourly:
        cl = t.manifest["clusters"][r["cluster"]]
        h = hours.index(r["hour"])
        rows = [by_node[(r["hour"], n)] for n in cl["nodes"]]
        ok = True
        for k in ("read_gb", "write_gb", "used_tb"):
            if abs(sum(float(x[k]) for x in rows) - float(r[k])) > 0.001 * len(rows):
                ok = False
        sl = slice(h * HOUR, (h + 1) * HOUR)
        outn = np.zeros(HOUR, dtype=int)
        for n in cl["nodes"]:
            outn += ((~online[n][sl]) | (bst[n][:, sl] != OK).any(0)).astype(int)
        prot = int(cl["tolerates"] - outn.max())
        on_end = sum(int(online[n][(h + 1) * HOUR - 1]) for n in cl["nodes"])
        c(ok and prot == int(r["protection_min"]) and on_end == int(r["nodes_online"]),
          f"{r['cluster']} {r['hour']}: sums {'match' if ok else 'differ'}, protection {r['protection_min']} (nodes give {prot}), "
          f"online {r['nodes_online']} (log {on_end})")
    out.append(c)

    # 4. rebuild
    lo, hi = cfg["drive"]["rebuild_tb_per_h"]
    c = Check("rebuild", f"Every rebuild moves the drive's share of its node's data at {lo} to {hi} TB/h")
    done = {(e["node"], e["bay"], e["serial"]): t.m_of(e["timestamp"]) for e in t.drive_events if e["event"] == "RebuildComplete"}
    for e in t.drive_events:
        if e["event"] != "Inserted":
            continue
        a = t.m_of(e["timestamp"])
        b = done.get((e["node"], e["bay"], e["serial"]))
        if b is None:
            c(True, "")      # still rebuilding when the month ended
            continue
        h = min(a // HOUR, H - 1)
        used = float(by_node[(hours[h], e["node"])]["used_tb"]) / devs[e["node"]]["drives"]
        rate = used / max((b - a) / 60, 1e-9)
        c(lo - 0.15 <= rate <= hi + 0.15, f"{e['node']} {e['bay']} {e['serial']}: {used:.2f} TB in {b - a} min is {rate:.2f} TB/h")
    out.append(c)

    # 5. ports
    c = Check("ports", "Replaying the trap log gives every port's seconds up per hour and each row leaf's tray ports up")
    for r in t.port_hourly:
        h = hours.index(r["hour"])
        v = links.get((r["switch"], r["ifName"]))
        up = int(v[h * HOUR:(h + 1) * HOUR].sum()) * 60 if v is not None else -1
        c(up == int(r["up_s"]), f"{r['switch']} {r['ifName']} {r['hour']}: up_s {r['up_s']}, traps give {up}")
    for r in t.leaf_hourly:
        h = hours.index(r["hour"])
        ps = [i for i, p in devs[r["switch"]]["ports"].items() if p[0] == "tray"]
        mins = sum(int(links[(r["switch"], i)][h * HOUR:(h + 1) * HOUR].sum()) for i in ps)
        end = sum(int(links[(r["switch"], i)][(h + 1) * HOUR - 1]) for i in ps)
        c(mins == int(r["tray_port_min"]) and end == int(r["tray_ports_up"]) and len(ps) == int(r["tray_ports"]),
          f"{r['switch']} {r['hour']}: tray ports up {r['tray_ports_up']} ({end}), port-minutes {r['tray_port_min']} ({mins})")
    out.append(c)

    # 6. traffic
    c = Check("traffic", "Each node's reads and writes equal its ports' octets, and each hall's traffic crosses every tier byte for byte")
    ph: dict[tuple[str, str, str], dict] = {(r["hour"], r["switch"], r["ifName"]): r for r in t.port_hourly}
    lh: dict[tuple[str, str], dict] = {(r["hour"], r["switch"]): r for r in t.leaf_hourly}
    for r in t.node_hourly:
        ps = devs[r["node"]]["ports"]
        rin = sum(int(ph[(r["hour"], sw, i)]["in_octets"]) for sw, i in ps)
        wout = sum(int(ph[(r["hour"], sw, i)]["out_octets"]) for sw, i in ps)
        c(abs(rin / 1e9 - float(r["read_gb"])) <= 0.0006 and abs(wout / 1e9 - float(r["write_gb"])) <= 0.0006,
          f"{r['node']} {r['hour']}: read {r['read_gb']} GB, ports {rin / 1e9:.3f}; write {r['write_gb']} GB, ports {wout / 1e9:.3f}")
    for cl in t.manifest["clusters"].values():
        rows = [x for k in sorted(cl["row_leaves"], key=int) for x in cl["row_leaves"][k]]
        for hr in hours:
            node_r = sum(int(ph[(hr, sw, i)]["in_octets"]) for n in cl["nodes"] for sw, i in devs[n]["ports"])
            node_w = sum(int(ph[(hr, sw, i)]["out_octets"]) for n in cl["nodes"] for sw, i in devs[n]["ports"])
            def up_sum(sws: list[str], col: str) -> int:
                return sum(int(ph[(hr, sw, i)][col]) for sw in sws for i, p in devs[sw]["ports"].items() if p[0] == "uplink")
            st_out, st_in = up_sum(cl["storage_leaves"], "out_octets"), up_sum(cl["storage_leaves"], "in_octets")
            rw_in, rw_out = up_sum(rows, "in_octets"), up_sum(rows, "out_octets")
            tr_out = sum(int(lh[(hr, sw)]["out_octets"]) for sw in rows)
            tr_in = sum(int(lh[(hr, sw)]["in_octets"]) for sw in rows)
            dead = [f"{sw} {i}" for sw in cl["storage_leaves"] + rows for i, p in devs[sw]["ports"].items() if p[0] == "uplink"
                    and int(ph[(hr, sw, i)]["up_s"]) == 0 and (int(ph[(hr, sw, i)]["in_octets"]) or int(ph[(hr, sw, i)]["out_octets"]))]
            c(node_r == st_out == rw_in == tr_out and node_w == st_in == rw_out == tr_in and not dead,
              f"{cl['hall']} {hr}: reads nodes {node_r}, storage uplinks {st_out}, row uplinks {rw_in}, trays {tr_out}; "
              f"writes {node_w}, {st_in}, {rw_out}, {tr_in}{'; traffic on a port down all hour: ' + ', '.join(dead) if dead else ''}")
    out.append(c)

    # 7. trays
    c = Check("trays", "A tray's two storage ports are down whenever the tray is, and one is up whenever it is up")
    hosts = host_up(t)
    tray_ports: dict[str, list[tuple[str, str]]] = {}
    for sw, x in devs.items():
        if x["family"] == "row_leaf":
            for i, p in x["ports"].items():
                if p[0] == "tray":
                    tray_ports.setdefault(p[1], []).append((sw, i))
    for host, ps in sorted(tray_ports.items()):
        hu = hosts.get(host)
        if hu is None:
            continue
        both_down = (links[ps[0]] == 0) & (links[ps[1]] == 0)
        bad_down = (~hu) & ~both_down
        bad_up = hu & both_down
        for h in range(H):
            sl = slice(h * HOUR, (h + 1) * HOUR)
            c(not bad_down[sl].any() and not bad_up[sl].any(),
              f"{host} {hours[h]}: {int(bad_down[sl].sum())} minutes with the tray out and a storage port up, "
              f"{int(bad_up[sl].sum())} with the tray up and both ports down")
    out.append(c)

    # 8. stalls
    ck = cfg["checks"]
    c = Check("stalls", "Every client stall falls in a flapping episode on its row's leaf uplinks, on a node running a job")
    run = running(t, hosts)
    fl = [f for f in flaps(t, cfg, links) if f["role"] == "row_leaf"]
    rr = rack_row(t)
    g = ck["stall_grace_min"]
    hit = set()
    for s in t.stalls:
        a, b = t.m_of(s["from"]), t.m_of(s["to"])
        ep = [i for i, f in enumerate(fl) if (f["hall"], f["row"]) == rr.get(s["node"]) and f["a"] - g <= a and b <= f["b"] + g]
        r_ok = s["node"] in run and bool(run[s["node"]][a:b].all())
        hit.update(ep)
        c(bool(ep) and r_ok and b > a, f"{s['node']} stalled {s['from']} to {s['to']}: "
          f"{'no flapping uplink on its row' if not ep else 'the node was not running a job'}")
    for i, f in enumerate(fl):
        c(i in hit, f"{f['switch']} {f['ifName']} flapped {t.iso(f['a'])} to {t.iso(f['b'])} ({f['downs']} downs) and no client stalled")
    out.append(c)

    # 9. spares shelf
    c = Check("spares", "Every part a storage ticket used is issued from its hall's spares shelf against that ticket before the swap, "
                        "and every cycle count's system quantity equals the shelf ledger")
    issues: dict[tuple[str, str, str], list[str]] = {}
    for x in t.ledger:
        if x["transaction"] == "issue":
            issues.setdefault((x["ticket"], x["hall"], x["fru"]), []).append(x["timestamp"])
    label = {p["part"]: p["fru"] for p in shelf_classes()}
    for k in t.tickets:
        for p in k["parts_used"]:
            if p["part"] not in label:
                continue
            got = issues.get((k["number"], k["hall"], label[p["part"]]), [])
            sw = swap_time(k, p.get("removed_serial"))
            ok = [x for x in got if sw - timedelta(hours=4) <= parse(x) <= sw]
            if ok:
                got.remove(ok[0])
            c(bool(ok), f"{k['number']} used {p['part']} ({p.get('installed_serial')}) at {TSG.iso(sw)}; no issue from the {k['hall']} shelf "
                        "against it in the 4 hours before")
    for (tk, hall, fru), rest in sorted(issues.items()):
        for x in rest:
            c(False, f"{hall} shelf issued {fru} at {x} against {tk}, which used no such part")
    for cnt in t.counts:
        bal = [x for x in t.ledger if x["hall"] == cnt["hall"] and x["fru"] == cnt["fru"] and x["timestamp"] <= cnt["counted_at"]]
        want = int(bal[-1]["balance_after"]) if bal else opening(cnt["hall"], cnt["fru"])
        c(int(cnt["system_qty"]) == want, f"{cnt['hall']} {cnt['fru']} count {cnt['counted_at']}: system {cnt['system_qty']}, ledger {want}")
    out.append(c)
    return out


@lru_cache(maxsize=1)
def _shelf() -> tuple:
    from scorecard.sla_model import load_sla
    return tuple(TSG.shelf_classes(load_sla()))


def shelf_classes() -> list[dict[str, Any]]:
    return list(_shelf())


def opening(hall: str, fru: str) -> int:
    return next(int(round(p["minimum"] * 1.5)) for p in shelf_classes() if p["fru"] == fru)


def swap_time(ticket: dict, removed: str | None) -> datetime:
    return TSG.swap_time(ticket, removed)


def shelf(t: StorageData) -> dict[str, Any]:
    """The storage spares shelf against the IT Partner SLA: KM-06 (each class in each hall at or above its minimum at every weekly
    count) and KM-07 (the count equals the ledger), with each class's opening, issues, receipts, and lowest balance."""
    mins = {p["fru"]: p["minimum"] for p in shelf_classes()}
    rows = []
    for hall in sorted({x["hall"] for x in t.counts}):
        for fru in sorted(mins):
            xs = [x for x in t.ledger if x["hall"] == hall and x["fru"] == fru]
            cs = [c for c in t.counts if c["hall"] == hall and c["fru"] == fru]
            op = opening(hall, fru)
            rows.append({"hall": hall, "fru": fru, "minimum": mins[fru], "opening": op,
                         "issued": -sum(int(x["qty"]) for x in xs if x["transaction"] == "issue"),
                         "received": sum(int(x["qty"]) for x in xs if x["transaction"] in ("receive", "emergency_receive")),
                         "emergency": sum(int(x["qty"]) for x in xs if x["transaction"] == "emergency_receive"),
                         "lowest": min([op] + [int(x["balance_after"]) for x in xs]),
                         "counts": [[c["counted_at"], int(c["counted_qty"]), int(c["system_qty"])] for c in cs]})
    counts = [c for c in t.counts]
    below = [c for c in counts if int(c["counted_qty"]) < mins[c["fru"]]]
    return {"rows": rows, "km06": [len(counts) - len(below), len(counts)],
            "km07": [sum(1 for c in counts if c["counted_qty"] == c["system_qty"]), len(counts)],
            "below": [{"hall": c["hall"], "fru": c["fru"], "at": c["counted_at"], "counted": int(c["counted_qty"]), "minimum": mins[c["fru"]]}
                      for c in below]}


# ------------------------------------------------------------------------- findings
def _gpu_hours(text: str | None) -> float | None:
    """The GPU-hours a ticket's customer impact states: "None ..." is 0; "... 107.5 GPU-hours idle" is 107.5."""
    if not text:
        return None
    m = re.search(r"([\d,.]+) GPU-hours", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return 0.0 if text.strip().lower().startswith("none") else None


def stall_hours(t: StorageData, cfg: dict[str, Any]) -> list[dict]:
    """Each flapping episode on a row leaf uplink with the client stalls inside it and their GPU-hours."""
    g = cfg["checks"]["stall_grace_min"]
    rr = rack_row(t)
    out = []
    for f in flaps(t, cfg):
        if f["role"] != "row_leaf":
            continue
        ss = [s for s in t.stalls if rr.get(s["node"]) == (f["hall"], f["row"]) and f["a"] - g <= t.m_of(s["from"])
              and t.m_of(s["to"]) <= f["b"] + g]
        racks = sorted({s["rack"] for s in ss})
        out.append({**f, "stalls": ss, "racks": racks, "nodes": len({s["node"] for s in ss}),
                    "gpu_hours": round(sum(int(s["minutes"]) for s in ss) * GPUS_PER_NODE / 60, 1)})
    return out


def findings(t: StorageData, cfg: dict[str, Any]) -> list[dict]:
    """Records that do not reconcile. Each: id, kind, title, summary, owner, contract, lines (facts), refs, devices,
    and from / to where it has a span."""
    ck = cfg["checks"]
    out: list[dict] = []
    # SP-STALL
    for f in stall_hours(t, cfg):
        if not f["stalls"]:
            continue
        a, b = f["a"], f["b"]
        tks = [k for k in t.tickets if k["category"] == "fabric_optic" and k["configuration_item"] == f"{f['switch']} {f['ifName']}"
               and a - 60 <= t.m_of(k["opened_at"]) <= b + 120]
        stated = _gpu_hours(tks[0]["customer_impact"]) if tks else None
        if tks and stated is not None and abs(stated - f["gpu_hours"]) <= ck["impact_tolerance"] * f["gpu_hours"]:
            continue
        peer = t.manifest["devices"][f["switch"]]["ports"][f["ifName"]]
        lines = [f"{f['switch']} {f['ifName']} (uplink to {peer[1]} {peer[2]}) went down {f['downs']} times from {t.iso(a)} to {t.iso(b)}; "
                 "the other uplinks stayed up",
                 f"{f['nodes']} running compute nodes in racks {', '.join(f['racks'])} waited on storage I/O inside the episode: "
                 f"{f['gpu_hours']:.1f} GPU-hours idle (Customer job telemetry)",
                 "The scheduler kept every one of them in service, so neither scheduler availability nor CSL-01 counts the time"]
        if tks:
            lines.append(f"{tks[0]['number']} (optic replaced) records customer impact: \"{tks[0]['customer_impact']}\"")
        else:
            lines.append(f"No IT Partner ticket on {f['switch']} {f['ifName']} opened during the episode")
        out.append({"kind": "fabric_stall", "title": f"{f['switch']} uplink flap idled {f['gpu_hours']:.1f} GPU-hours",
                    "summary": f"A flapping uplink on {f['switch']} stalled the storage I/O of {f['nodes']} running nodes for up to "
                               f"{b - a} minutes. The GPUs were healthy and idle, so the time belongs to the storage fabric, not to the "
                               f"IT Partner's GPU repairs; the ticket for the optic {'says there was no customer impact' if tks else 'does not exist'}.",
                    "owner": "IT Partner", "contract": CONTRACT["fabric_stall"], "lines": lines,
                    "refs": [k["number"] for k in tks], "devices": [f["switch"]] + f["racks"],
                    "from": t.iso(a), "to": t.iso(b), "gpu_hours": f["gpu_hours"], "ifName": f["ifName"]})
    # SP-CUSTODY
    handed = {}
    for r in t.custody:
        handed.setdefault(r["drive_serial"], []).append(r["handed_over_at"])
    end = t.start + timedelta(minutes=t.M)
    tk_by_serial = {p["removed_serial"]: k for k in t.tickets for p in k.get("parts_used", []) if p.get("removed_serial")}
    for e in t.drive_events:
        if e["event"] != "Removed":
            continue
        rm = parse(e["timestamp"])
        if rm + timedelta(hours=ck["custody_h"]) > end:
            continue
        ok = any(rm <= parse(x) <= rm + timedelta(hours=ck["custody_h"]) for x in handed.get(e["serial"], []))
        if ok:
            continue
        tk = tk_by_serial.get(e["serial"])
        out.append({"kind": "custody_gap", "title": f"Drive {e['serial']} pulled with no custody handover",
                    "summary": f"The drive pulled from {e['node']} {e['bay']} has no chain-of-custody handover to the Security Partner "
                               f"within {ck['custody_h']} h, so storage media is unaccounted for between the rack and destruction.",
                    "owner": "IT Partner", "contract": CONTRACT["custody_gap"],
                    "lines": [f"Redfish: {e['node']} {e['bay']} serial {e['serial']} removed at {e['timestamp']}",
                              f"{tk['number']} records the swap (removed SN {e['serial']})" if tk else "No ticket records the swap",
                              f"Chain-of-custody log: no handover of {e['serial']} by {(rm + timedelta(hours=ck['custody_h'])).strftime('%Y-%m-%dT%H:%M:%SZ')}"],
                    "refs": [tk["number"]] if tk else [], "devices": [e["node"]], "serial": e["serial"], "from": e["timestamp"], "to": None})
    # SP-REBUILD and SP-BAY
    done = {e["serial"]: e["timestamp"] for e in t.drive_events if e["event"] == "RebuildComplete"}
    removed = {e["serial"]: e for e in t.drive_events if e["event"] == "Removed"}
    for k in t.tickets:
        if k["category"] != "storage_drive":
            continue
        for p in k.get("parts_used", []):
            node, _, tb = p["location"].partition(" ")
            if k.get("resolved_at"):
                fin = done.get(p["installed_serial"])
                if fin is None or parse(k["resolved_at"]) < parse(fin):
                    early = round((parse(fin) - parse(k["resolved_at"])).total_seconds() / 60) if fin else None
                    out.append({"kind": "closed_before_rebuild", "title": f"{k['number']} resolved before the rebuild finished",
                                "summary": f"The ticket for {p['location']} was resolved "
                                           f"{f'{early} minutes before' if early is not None else 'with no'} rebuild completion on the "
                                           "new drive, so the cluster was still short of full protection when the record says the work was done.",
                                "owner": "IT Partner", "contract": CONTRACT["closed_before_rebuild"],
                                "lines": [f"{k['number']} resolved at {k['resolved_at']}: \"{k['work_notes'][-1]['text']}\"",
                                          f"Redfish: {p['installed_serial']} in {p['location']} StatusIndicator Rebuild until "
                                          f"{fin or 'the end of the month'} (RebuildComplete)"],
                                "refs": [k["number"]], "devices": [node], "serial": p["installed_serial"],
                                "from": k["resolved_at"], "to": fin, "minutes_early": early})
            rm = removed.get(p["removed_serial"])
            if rm and (rm["node"], rm["bay"]) != (node, tb):
                out.append({"kind": "wrong_bay", "title": f"{k['number']} names {tb}; the serial changed in {rm['bay']}",
                            "summary": f"The ticket records the swap in {p['location']}, but Redfish shows the drive it names as removed "
                                       f"({p['removed_serial']}) leaving {rm['node']} {rm['bay']}, and {tb} still holding its drive. The record of "
                                       "which bay was worked does not match the hardware.",
                            "owner": "IT Partner", "contract": CONTRACT["wrong_bay"],
                            "lines": [f"{k['number']} parts used: {p['location']}, removed SN {p['removed_serial']}, installed SN {p['installed_serial']}",
                                      f"Redfish: {p['removed_serial']} removed from {rm['node']} {rm['bay']} at {rm['timestamp']}",
                                      f"Redfish: no drive change in {node} {tb}"],
                            "refs": [k["number"]], "devices": [rm["node"]], "ticket_bay": tb, "changed_bay": rm["bay"],
                            "from": rm["timestamp"], "to": None})
    order = {"fabric_stall": 0, "custody_gap": 1, "closed_before_rebuild": 2, "wrong_bay": 3}
    out.sort(key=lambda f: (f["from"] or "", order[f["kind"]]))
    for i, f in enumerate(out, 1):
        f["id"] = f"SP-{i}"
    return out


def score(fs: list[dict], key: dict[str, Any]) -> dict[str, int]:
    """Planted cases found, and findings that match none (false positives)."""
    def hit(f: dict, p: dict) -> bool:
        if f["kind"] != p["kind"]:
            return False
        if p["kind"] == "fabric_stall":
            return (p["switch"], p["ifName"]) == (f["devices"][0], f["ifName"])
        if p["kind"] == "custody_gap":
            return p["serial"] == f["serial"]
        if p["kind"] == "closed_before_rebuild":
            return p["ticket"] in f["refs"]
        if p["kind"] == "wrong_bay":
            return p["ticket"] in f["refs"] and p["changed_bay"] == f["changed_bay"]
        return False
    planted = key.get("planted", [])
    found = sum(1 for p in planted if any(hit(f, p) for f in fs))
    fp = sum(1 for f in fs if not any(hit(f, p) for p in planted))
    return {"planted": len(planted), "found": found, "false_positives": fp}


# ------------------------------------------------------------------------- what the page and report list
def events(t: StorageData, cfg: dict[str, Any], fs: list[dict]) -> list[dict]:
    """Every drive swap, warning, node reboot, uplink down, port blip, and flap, with what explains it."""
    by_ref = {r: f["id"] for f in fs for r in f["refs"]}
    by_serial = {f.get("serial"): f["id"] for f in fs if f.get("serial")}
    out: list[dict] = []
    tk_by_serial = {p["removed_serial"]: k for k in t.tickets for p in k.get("parts_used", []) if p.get("removed_serial")}
    tk_by_loc = {}
    for k in t.tickets:
        tk_by_loc.setdefault(k["configuration_item"], []).append(k)
    for e in sorted(t.drive_events, key=lambda e: e["timestamp"]):
        loc = f"{e['node']} {e['bay']}"
        if e["event"] in ("Failed", "PredictedFailure"):
            tk = next((k for k in t.tickets if k["category"] == "storage_drive" and any(p["removed_serial"] == e["serial"] for p in k["parts_used"])), None) \
                or next((k for k in tk_by_loc.get(loc, []) if parse(k["opened_at"]) >= parse(e["timestamp"])), None)
            what = "failed (StatusIndicator Fail)" if e["event"] == "Failed" else "predicted its own failure (FailurePredicted)"
            out.append({"t": e["timestamp"], "device": e["node"], "kind": "drive", "text": f"{e['bay']} {e['serial']} {what}",
                        "refs": [tk["number"]] if tk else [], "finding": by_ref.get(tk["number"]) if tk else None})
        elif e["event"] == "Removed":
            tk = tk_by_serial.get(e["serial"])
            out.append({"t": e["timestamp"], "device": e["node"], "kind": "swap", "text": f"{e['bay']} {e['serial']} pulled",
                        "refs": [tk["number"]] if tk else [], "finding": by_serial.get(e["serial"]) or (by_ref.get(tk["number"]) if tk else None)})
        elif e["event"] == "RebuildComplete":
            out.append({"t": e["timestamp"], "device": e["node"], "kind": "rebuild", "text": f"{e['bay']} {e['serial']} rebuild complete",
                        "refs": [], "finding": by_serial.get(e["serial"])})
        elif e["event"] == "Warning":
            out.append({"t": e["timestamp"], "device": e["node"], "kind": "warning", "text": f"{e['bay']} {e['serial']} warning (cleared on its own)",
                        "refs": [], "finding": None})
    for e in t.node_events:
        if e["event"] == "offline":
            back = next((x["timestamp"] for x in t.node_events if x["node"] == e["node"] and x["event"] == "online" and x["timestamp"] > e["timestamp"]), None)
            mins = t.m_of(back) - t.m_of(e["timestamp"]) if back else None
            out.append({"t": e["timestamp"], "device": e["node"], "kind": "node", "text": f"{e['reason']}: out {mins} min; the cluster kept serving",
                        "refs": [], "finding": None})
    links = replay_links(t)
    hosts = host_up(t)
    devs = t.manifest["devices"]
    flap_keys = {(f["switch"], f["ifName"], f["a"]) for f in flaps(t, cfg, links)}
    for f in stall_hours(t, cfg):
        tk = [k for k in tk_by_loc.get(f"{f['switch']} {f['ifName']}", []) if f["a"] - 60 <= t.m_of(k["opened_at"]) <= f["b"] + 120]
        out.append({"t": t.iso(f["a"]), "device": f["switch"], "kind": "flap",
                    "text": f"{f['ifName']} flapped ({f['downs']} downs, {f['b'] - f['a']} min); {f['gpu_hours']:.1f} GPU-hours of jobs waited on I/O",
                    "refs": [k["number"] for k in tk], "finding": next((x["id"] for x in fs if x["kind"] == "fabric_stall" and x["devices"][0] == f["switch"]
                                                                        and x["from"] == t.iso(f["a"])), None)})
    for (sw, ifn), v in sorted(links.items()):
        x = devs[sw]
        if x["family"] == "spine":
            continue
        kind = x["ports"][ifn][0]
        d0 = ifn in x["down_at_start"]
        for a, b in spans(v == 0):
            if (a == 0 and d0) or any((sw, ifn) == (fs_, fi) and fa <= a <= fa + 60 for fs_, fi, fa in flap_keys):
                continue
            if kind == "tray" and (x["ports"][ifn][1] not in hosts or not hosts[x["ports"][ifn][1]][a:b].all()):
                continue            # the tray itself out of the rack or unpowered: the management section lists it
            if kind == "node" and any(e["node"] == x["ports"][ifn][1] and abs(t.m_of(e["timestamp"]) - a) <= 1 for e in t.node_events):
                continue            # the node rebooting: listed above
            tk = [k for k in tk_by_loc.get(f"{sw} {ifn}", []) if a - 30 <= t.m_of(k["opened_at"]) <= b + 30]
            out.append({"t": t.iso(a), "device": sw, "kind": "uplink" if kind == "uplink" else "port",
                        "text": f"{ifn} down {b - a} min ({'to ' + x['ports'][ifn][1]}); {'the other uplinks carried it' if kind == 'uplink' else 'the other port carried it'}",
                        "refs": [k["number"] for k in tk], "finding": None})
    out.sort(key=lambda e: (e["t"], e["device"]))
    return out
