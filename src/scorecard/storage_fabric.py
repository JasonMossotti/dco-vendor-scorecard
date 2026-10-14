"""The storage clusters and the storage and in-band Ethernet fabric of Site AUS-1, as one map every reader shares.

Portfolio demo; all data fictional. Built from ``site/site.yaml`` (``halls[].storage``) and the port maps in
``config/telemetry_storage.yaml`` (basis: assumption). The device directory, the synthetic telemetry, and the checks all
read this map, so a port is named the same way everywhere:

* row leaves ``eth-a1-1`` and ``eth-a1-2`` (one pair per row): compute tray ``n`` of the ``k``-th rack in the row on
  lane ``(k-1)*18 + n``, an 800 GbE port split four ways (``swp1s0`` is lane 1);
* storage leaves ``eth-a-st1`` and ``eth-a-st2``: storage node ``i`` on lane ``i``, split two ways;
* spines ``eth-a-sp1`` and ``eth-a-sp2``: leaf ``j`` of the hall (row leaves first, then the storage pair) on
  ``swp(2j-1)`` and ``swp(2j)``; each leaf's uplinks are swp61 and swp62 to the first spine, swp63 and swp64 to the second.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "telemetry_storage.yaml"


def lane(n: int, split: int) -> str:
    """Lane 1 -> swp1s0; lane 5 with split 4 -> swp2s0."""
    return f"swp{(n - 1) // split + 1}s{(n - 1) % split}"


@lru_cache(maxsize=1)
def _ports() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["ports"]


def build(site: dict[str, Any], trays_per_rack: int) -> dict[str, Any]:
    """Every storage rack, node, and fabric switch with its ports, and each compute tray's two storage ports.

    Returns ``{"halls": {hall: {...}}, "switches": {name: {...}}, "nodes": {name: {...}}, "trays": {host: [...]}}``.
    A switch's ``ports`` map an ifName to ``{"peer": device, "peer_port": ifName or "", "kind": "tray" | "node" |
    "uplink" | "downlink", "gbps": speed}``."""
    P = _ports()
    halls: dict[str, Any] = {}
    switches: dict[str, dict[str, Any]] = {}
    nodes: dict[str, dict[str, Any]] = {}
    trays: dict[str, list[tuple[str, str]]] = {}
    for h in site["halls"]:
        st = h.get("storage")
        if not st:
            continue
        L, hid, per_row = h["letter"].lower(), h["id"], h["racks_per_row"]
        spines = [f"eth-{L}-sp{k}" for k in range(1, st["spines"] + 1)]
        row_leaves = {row: [f"eth-{L}{row}-{k}" for k in (1, 2)] for row in range(1, h["rows"] + 1)}
        st_leaves = [f"eth-{L}-st{k}" for k in range(1, st["storage_leaves"] + 1)]
        leaves = [x for row in sorted(row_leaves) for x in row_leaves[row]] + st_leaves
        racks = [f"STG-{L.upper()}{k}" for k in range(1, st["racks"] + 1)]
        hall_nodes = []
        for sw in spines:
            switches[sw] = {"hall": hid, "role": "spine", "row": None, "ports": {}}
        for row, pair in row_leaves.items():
            for sw in pair:
                switches[sw] = {"hall": hid, "role": "row_leaf", "row": row, "ports": {}, "pair": pair}
        for sw in st_leaves:
            switches[sw] = {"hall": hid, "role": "storage_leaf", "row": None, "ports": {}, "pair": st_leaves}
        # uplinks: each leaf's swp61..64 to the spines, landing on the spine's swp(2j-1), swp(2j)
        for j, leaf in enumerate(leaves, 1):
            up = P["row_leaf" if switches[leaf]["role"] == "row_leaf" else "storage_leaf"]["uplinks"]
            for s_i, sp in enumerate(spines):
                for q, port in enumerate(up[f"sp{s_i + 1}"]):
                    sp_port = f"swp{2 * j - 1 + q}"
                    switches[leaf]["ports"][f"swp{port}"] = {"peer": sp, "peer_port": sp_port, "kind": "uplink", "gbps": 800}
                    switches[sp]["ports"][sp_port] = {"peer": leaf, "peer_port": f"swp{port}", "kind": "downlink", "gbps": 800}
        # storage nodes, one port to each storage leaf
        i = 0
        for rk in racks:
            for n in range(1, st["nodes_per_rack"] + 1):
                i += 1
                name = f"stg-{rk[4:].lower()}-n{n:02d}"
                ifn = lane(i, P["storage_leaf"]["split"])
                nodes[name] = {"hall": hid, "rack": rk, "index": i, "ports": [[sw, ifn] for sw in st_leaves],
                               "drives": st["drives_per_node"]}
                for k, sw in enumerate(st_leaves):
                    switches[sw]["ports"][ifn] = {"peer": name, "peer_port": f"p{k}", "kind": "node", "gbps": 400}
                hall_nodes.append(name)
        # compute trays: one 200 GbE port to each leaf of the row's pair
        for idx in range(1, h["rows"] * per_row + 1):
            row, pos = (idx - 1) // per_row + 1, (idx - 1) % per_row + 1
            rid = f"{L}{idx:02d}"
            for slot in range(1, trays_per_rack + 1):
                ifn = lane((pos - 1) * trays_per_rack + slot, P["row_leaf"]["split"])
                host = f"{rid}-ct{slot:02d}"
                trays[host] = [(sw, ifn) for sw in row_leaves[row]]
                for k, sw in enumerate(row_leaves[row]):
                    switches[sw]["ports"][ifn] = {"peer": host, "peer_port": f"p{k}", "kind": "tray", "gbps": 200}
        ec = st["erasure_coding"]
        halls[hid] = {"letter": L, "spines": spines, "row_leaves": row_leaves, "storage_leaves": st_leaves, "racks": racks,
                      "nodes": hall_nodes, "erasure_coding": ec, "tolerates": ec[1], "drives_per_node": st["drives_per_node"],
                      "cluster": f"PFS-{L.upper()}"}
    return {"halls": halls, "switches": switches, "nodes": nodes, "trays": trays}


def sort_key(ifname: str) -> tuple[int, int]:
    """swp12s3 -> (12, 3); swp61 -> (61, -1)."""
    a, _, b = ifname[3:].partition("s")
    return int(a), int(b) if b else -1
