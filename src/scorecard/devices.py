"""The device directory: every named device in the site, what it is, and what it connects to.

One entry per name the pages use (leaf-a07-r1, a13-ct18, CDU-B3, BW-A-R1-PG-A2-A, UPS-B4, A07, ...),
built from the same sources as the data, never typed by hand:

* the site model (``site/site.yaml`` through ``site_model``) for racks, busways, tap-offs, UPSs,
  unit substations, the MV switchgear, generators, CDUs, thermal walls, chillers, and leak and smoke
  detection, with the descriptions the location popups already use (``locations``);
* the IT Partner SLA's site section (the generator's own input) for what is inside each rack:
  18 compute trays, 9 NVLink switch trays, 8 power shelves;
* the generator's cabling rule (``SiteGenerator.link_for``, imported, not retyped) for which leaf
  switch port each tray's four InfiniBand NICs land on.

``scripts/render_site.py`` writes the result to ``docs/site/devices.json``. The code popups show an
entry's description and connections under the code's meaning (``glossary.popup_data``), and the
Devices page (``scripts/render_devices.py``) lists them all with the drawing.

Each entry: ``kind``, ``title``, ``text`` (one or two sentences), ``conn`` (rows of [relation, name,
note]; a name another entry holds is a link), ``loc`` (what to show on the drawings, in the location
popups' ``data-loc`` form). ``title`` and ``loc`` are left out when they are the name itself. ``lookup``
turns "leaf-a07-r1 port 18" into its own entry, from the trays' rail links.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import site_model as S
from .synthetic.generator import SiteGenerator as Generator

ROOT = Path(__file__).resolve().parents[2]
DEVICES_JSON = ROOT / "docs" / "site" / "devices.json"
RAILS = 4                       # InfiniBand NICs per compute tray, one per rail (mlx5_0 to mlx5_3)

KIND_LABEL = {
    "rack": "Rack", "compute_tray": "Compute tray", "switch_tray": "NVLink switch tray", "power_shelf": "Power shelf",
    "leaf": "InfiniBand leaf switch", "leaf_port": "Leaf switch port", "busway": "Busway", "tapoff": "Tap-off",
    "group": "Power group", "ups": "UPS", "uss": "Unit substation", "mups": "Mechanical UPS", "mvsst": "Solid-state transformer",
    "mv": "Medium-voltage switchgear", "tx": "Utility transformer", "gen": "Generator", "chiller": "Chiller",
    "pump": "Facility water pump", "cdu": "Coolant distribution unit", "tw": "Thermal wall", "crah": "Air handler",
    "vesda": "Smoke detector", "leak": "Leak detection module",
}
# Sections of the Devices page, in order, and the kinds in each
GROUPS = [
    ("racks", "Racks and what is inside them", ["rack", "compute_tray", "switch_tray", "power_shelf"]),
    ("fabric", "InfiniBand fabric", ["leaf"]),
    ("power", "Power", ["tx", "mv", "gen", "uss", "ups", "mups", "mvsst", "group", "busway", "tapoff"]),
    ("cooling", "Cooling", ["cdu", "tw", "crah", "chiller", "pump"]),
    ("safety", "Smoke and leak detection", ["vesda", "leak"]),
]
GROUP_OF = {k: g for g, _, kinds in GROUPS for k in kinds}

# A leaf switch port as the alarms write it ("leaf-a07-r1 port 18"; the UFM form "leaf-a07-r1:swp18" too)
PORT_RE = re.compile(r"(leaf-[a-c]\d{2}-r\d)(?: port |:swp)(\d{1,3})")


def _span(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{names[0]} to {names[-1]}"


def build(site: dict[str, Any], it_site: dict[str, Any], loc_entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every device entry. ``it_site`` is the IT Partner SLA's ``site`` section (racks per hall and what is in
    each rack); ``loc_entries`` the location entries (``locations.build(site)["entries"]``) for descriptions."""
    dev: dict[str, dict[str, Any]] = {}

    def add(name: str, kind: str, text: str, conn: list[list[str]], loc: str = "", title: str = "", **extra: Any) -> None:
        if name in dev:
            raise ValueError(f"duplicate device {name}")
        e = {"kind": kind, "text": text, "conn": [[r, n, t] for r, n, t in conn], **extra}
        if title and title != name:
            e["title"] = title
        if loc and loc != name:
            e["loc"] = loc
        dev[name] = e

    def desc(name: str) -> str:
        return loc_entries[name]["text"]

    per = it_site["per_rack"]
    it_halls = {h["id"]: h for h in it_site["halls"]}
    pl = site["plants"]
    mv = {1: "MV-A", 2: "MV-B"}

    for h in site["halls"]:
        before = set(dev)
        L, hid, short = h["letter"], h["id"], h["name"].split(" (")[0]
        p, c = h["power"], h["cooling"]
        rp = S.product(site, h["rack_product"])
        fabric = re.sub(r" switch$", "", S.product(site, h["fabric"])["model"]) if h.get("fabric") else ""
        racks = S.racks(site, hid)
        cdus = [f"CDU-{L}{i}" for i in range(1, c["cdu_count"] + 1)]
        segs = S.busway_segments(site, hid)
        seg_of = {r: s for s in segs for r in s["racks"]}
        ups = S.ups_ids(h)
        mups = [f"MUPS-{L}{i}" for i in range(1, p.get("mech_ups_count", 0) + 1)]
        tws = [f"TW-{L}{i}" for i in range(1, c.get("thermal_wall_count", 0) + 1)]
        it = it_halls.get(hid)
        rows = h["rows"]
        leaves: dict[str, dict[str, Any]] = {}

        # ---- racks, and inside them (where the IT Partner SLA lists the hall's racks)
        for r in racks:
            rid, i = r["rack"], r["index"]
            conn = [["Where", "", f"{short}, row {r['row']}, position {r['position']}"]]
            if r["group"]:
                s = seg_of[rid]
                for side in "AB":
                    conn.append([f"{side} feed", f"TO-{rid}-{side}", f"on {s['id']}-{side}, from {r['feeds'][side]}"])
                conn.append(["Power group", r["group"], f"A from {r['feeds']['A']}, B from {r['feeds']['B']}"])
            else:
                conn += [["A feed", r["feeds"]["A"], "800 VDC"], ["B feed", r["feeds"]["B"], "800 VDC"]]
            conn.append(["Primary CDU", r["cdu"], f"row {r['row']}, on the shared {short} header with "
                         f"{', '.join(x for x in cdus if x != r['cdu'])}"])
            if it and i <= it["racks"]:
                host = f"{rid.lower()}-ct"
                for rail in range(RAILS):
                    first, last = Generator.link_for({"rack": rid, "index": i}, 1, rail), \
                        Generator.link_for({"rack": rid, "index": i}, per["compute_trays"], rail)
                    conn.append([f"Rail {rail}", first["switch"], f"ports {first['port']} to {last['port']}: trays 1 to "
                                 f"{per['compute_trays']}, NIC {first['hca']}"])
                conn += [["Contains", f"{host}01", f"to {host}{per['compute_trays']:02d}: {per['compute_trays']} compute trays"],
                         ["Contains", f"{rid.lower()}-nvsw1", f"to {rid.lower()}-nvsw{per['nvlink_switch_trays']}: "
                          f"{per['nvlink_switch_trays']} NVLink switch trays"],
                         ["Contains", f"{rid}_PowerShelf_1", f"to {rid}_PowerShelf_{per['power_shelves']}: "
                          f"{per['power_shelves']} power shelves"]]
            if it:
                conn.append(["Leak detection", f"TTDM-{L}", f"circuit C{r['row']} along the row {r['row']} manifold"])
            add(rid, "rack", desc(rid), conn, title=f"Rack {rid}")
            if not (it and i <= it["racks"]):
                continue
            shelves = [f"{rid}_PowerShelf_{n}" for n in range(1, per["power_shelves"] + 1)]
            nvsw = [f"{rid.lower()}-nvsw{n}" for n in range(1, per["nvlink_switch_trays"] + 1)]
            trays = [f"{rid.lower()}-ct{n:02d}" for n in range(1, per["compute_trays"] + 1)]
            half = per["power_shelves"] // 2
            for n in range(1, per["compute_trays"] + 1):
                links = [Generator.link_for({"rack": rid, "index": i}, n, rail) for rail in range(RAILS)]
                conn = [["In rack", rid, f"compute tray {n} of {per['compute_trays']}"]]
                for rail, lk in enumerate(links):
                    conn.append([f"Rail {rail}", f"{lk['switch']} port {lk['port']}", f"from NIC {lk['hca']}"])
                    leaves.setdefault(lk["switch"], {"rail": rail, "ports": {}})["ports"][lk["port"]] = [lk["host"], lk["hca"]]
                conn += [["NVLink", nvsw[0], f"to {nvsw[-1]}: all {len(nvsw)} switch trays, through the rack's NVLink spine"],
                         ["Power", shelves[0], f"to {shelves[-1]}, through the rack busbar"]]
                add(trays[n - 1], "compute_tray",
                    f"Compute tray {n} in rack {rid} ({rp['model']}): {per['gpus_per_compute_tray']} GPUs. One InfiniBand "
                    f"NIC per rail to the leaf switches, and NVLink to every switch tray in the rack.",
                    conn, loc=trays[n - 1], title=trays[n - 1])
            for n, name in enumerate(nvsw, 1):
                add(name, "switch_tray", f"NVLink switch tray {n} of {len(nvsw)} in rack {rid}: joins the rack's "
                    f"{per['compute_trays']} compute trays into one NVLink domain of {per['gpus']} GPUs.",
                    [["In rack", rid, f"switch tray {n}"], ["NVLink", trays[0], f"to {trays[-1]}: every compute tray"],
                     ["Power", shelves[0], f"to {shelves[-1]}, through the rack busbar"]], loc=name)
            for n, name in enumerate(shelves, 1):
                side = "A" if n <= half else "B"
                feed = [["Fed by", f"TO-{rid}-{side}", f"the rack's {side} feed (shelves {1 if side == 'A' else half + 1} to "
                         f"{half if side == 'A' else per['power_shelves']}; assumed, as on the detail sheet)"]] if r["group"] else []
                add(name, "power_shelf", f"Power shelf {n} of {per['power_shelves']} in rack {rid}: converts the rack's AC "
                    "feed to the DC busbar that powers the trays.",
                    [["In rack", rid, f"power shelf {n}"]] + feed +
                    [["Feeds", trays[0], f"to {trays[-1]} and the switch trays, through the busbar"]], loc=name)

        # ---- leaf switches: two racks per leaf and rail, ports 1 to 36 down, the rest up
        for name in sorted(leaves):
            lf = leaves[name]
            ports = dict(sorted(lf["ports"].items()))
            conn = []
            for rack_id in sorted({h_[0][:3].upper() for h_ in ports.values()}):
                ps = [pt for pt, h_ in ports.items() if h_[0].startswith(rack_id.lower())]
                conn.append([f"Ports {ps[0]} to {ps[-1]}", ports[ps[0]][0],
                             f"to {ports[ps[-1]][0]}: rack {rack_id} trays 1 to {len(ps)}, NIC {ports[ps[0]][1]}"])
            conn.append([f"Ports above {max(ports)}", "", f"uplinks to the spine plane for rail {lf['rail']} "
                         "(the spine switches are not in the sample data)"])
            served = sorted({h_[0][:3].upper() for h_ in ports.values()})
            add(name, "leaf", f"{fabric} leaf switch in {short} on rail {lf['rail']}, serving racks {' and '.join(served)}. "
                f"Leaf numbers count rack pairs: leaf {int(name.split('-')[1][1:])} serves racks {' and '.join(served)}.",
                conn, loc=f"{name}|{served[0]}")

        # ---- power distribution
        for s in segs:
            for side in "AB":
                bw = f"{s['id']}-{side}"
                add(bw, "busway", desc(bw), [["Fed by", s["feeds"][side], "output feeder breaker"],
                                             ["Power group", s["group"], ""]] +
                    [["Tap-off", f"TO-{x}-{side}", f"feeds rack {x}"] for x in s["racks"]])
            for rid in s["racks"]:
                add(f"TO-{rid}", "tapoff", desc(f"TO-{rid}"),
                    [[f"{side} side", f"TO-{rid}-{side}", f"on {s['id']}-{side}"] for side in "AB"] + [["Feeds", rid, "both feeds"]])
                for side in "AB":
                    lo, hi = (1, 4) if side == "A" else (5, 8)
                    conn = [["On busway", f"{s['id']}-{side}", f"from {s['feeds'][side]}"], ["Feeds", rid, f"{side} feed"]]
                    if it and int(rid[1:]) <= it["racks"]:
                        conn.append(["Feeds", f"{rid}_PowerShelf_{lo}", f"to {rid}_PowerShelf_{hi} (assumed)"])
                    add(f"TO-{rid}-{side}", "tapoff", desc(f"TO-{rid}-{side}"), conn)
        for g in p.get("groups", []):
            gr = [r["rack"] for r in racks if r["group"] == g["id"]]
            a, b = f"UPS-{L}{g['feeds'][0]}", f"UPS-{L}{g['feeds'][1]}"
            add(g["id"], "group", desc(g["id"]),
                [["A side", a, ""], ["B side", b, ""]] +
                [["Busway", f"{s['id']}-{side}", f"racks {_span(s['racks'])}"] for s in segs if s["group"] == g["id"] for side in "AB"] +
                [["Racks", gr[0], f"to {gr[-1]} ({len(gr)} racks)"]], title=f"Power group {g['id']}")
        for i, u in enumerate(ups, 1):
            add(u, "ups", desc(u), [["Fed by", f"USS-{L}{i}", f"from {S.mv_bus_for(i)}"]] +
                [["Feeds", f"{s['id']}-{side}", f"power group {s['group']}, racks {_span(s['racks'])}"]
                 for s in segs for side in "AB" if s["feeds"][side] == u])
            add(f"USS-{L}{i}", "uss", desc(f"USS-{L}{i}"), [["Fed by", S.mv_bus_for(i), "13.8 kV"], ["Feeds", u, "480 V"]])
        for i, m in enumerate(mups, 1):
            add(m, "mups", desc(m), [["Fed by", S.mv_bus_for(i), ""]] +
                [["Feeds", x, "pumps (2N)"] for x in cdus] +
                [["Feeds", t, "fans"] for k, t in enumerate(tws, 1) if (k - 1) % 2 + 1 == i])
        for i in range(1, p.get("mvsst_count", 0) + 1):
            name = f"MVSST-{L}{i}"
            add(name, "mvsst", desc(name), [["Fed by", S.mv_bus_for(i), "13.8 kV"],
                                            ["Feeds", racks[0]["rack"], f"to {racks[-1]['rack']}, 800 VDC ({'A' if i == 1 else 'B'} feed)"]])

        # ---- cooling and detection
        for i, cdu in enumerate(cdus, 1):
            row_racks = [r["rack"] for r in racks if r["cdu"] == cdu]
            conn = [["Primary for", row_racks[0], f"to {row_racks[-1]} (row {min(i, rows)})"] if row_racks else None,
                    ["Shared header", racks[0]["rack"], f"to {racks[-1]['rack']}: every rack in {short} draws from the header"]]
            conn = [x for x in conn if x] + [["Peer", x, "same header"] for x in cdus if x != cdu]
            conn += [["Powered by", m, "pumps"] for m in mups] or [["Powered by", f"MVSST-{L}1", "assumed"]]
            conn.append(["Facility water", "FWP-1", f"from the chiller plant (FWP-1 to FWP-{pl['heat_rejection']['pump_count']})"])
            if it and i + rows <= h["fire_life_safety"]["leak_circuits"]:
                conn.append(["Leak detection", f"TTDM-{L}", f"circuit C{rows + i} under this CDU"])
            add(cdu, "cdu", desc(cdu), conn)
        for i, t in enumerate(tws, 1):
            m = f"MUPS-{L}{(i - 1) % 2 + 1}"
            add(t, "tw", desc(t), [["Powered by", m, "fans"], ["Chilled water", "FWP-1", "facility water loop"],
                                   ["Cools", "", f"the air side of the racks in {short}"]])
        for i in range(1, c.get("electrical_room_crah_count", 0) + 1):
            add(f"CRAH-{L}{i}", "crah", desc(f"CRAH-{L}{i}"), [["Where", "", f"{short} electrical room"],
                                                               ["Chilled water", "FWP-1", "facility water loop"]])
        for n in range(1, h["fire_life_safety"]["vesda_detectors"] + 1):
            name = f"VESDA-{L}{n}"
            add(name, "vesda", desc(name), [["Samples", "", f"air from every cold aisle in {short}" if n == 1
                                             else f"the {short} electrical room's air"]])
        circuits = h["fire_life_safety"].get("leak_circuits", 0)
        if circuits and hid in it_halls:
            conn = []
            for k in range(1, circuits + 1):
                if k <= rows:
                    rr = [r["rack"] for r in racks if r["row"] == k]
                    conn.append([f"C{k}", rr[0], f"along the row {k} manifold, racks {_span(rr)}"])
                elif k - rows <= len(cdus):
                    conn.append([f"C{k}", cdus[k - rows - 1], "under this CDU"])
            add(f"TTDM-{L}", "leak", f"TraceTek {S.product(site, 'tracetek_ttdm128')['model']} for {short}: {circuits} sensing "
                "cable circuits. An alarm names the circuit and the distance along the cable.", conn, loc=f"TTDM-{L}|{hid}")

        for n in set(dev) - before:          # the Devices page lists them by hall
            dev[n]["hall"] = short

    # ---- site plants
    for i in range(1, pl["utility"]["transformer_count"] + 1):
        add(f"TX-{i}", "tx", desc(f"TX-{i}"), [["Feeds", mv[i], "13.8 kV"]])
    for i, bus in mv.items():
        other = mv[3 - i]
        add(bus, "mv", desc(bus), [["Fed by", f"TX-{i}", "through the main breaker"], ["Main breaker", f"{bus} main breaker", ""],
                                   ["Standby", "GEN-1", f"the paralleling bus (GEN-1 to GEN-{pl['generators']['count']})"],
                                   ["Tie", other, "main-tie-main"]] +
            [["Feeds", x, ""] for x in sorted(e["id"] for e in S.equipment(site) if e["fed_from"] == bus)],
            title=loc_entries[bus]["title"])
        add(f"{bus} main breaker", "mv", desc(f"{bus} main breaker"), [["On", bus, ""], ["From", f"TX-{i}", "utility"]])
    add("MV switchgear", "mv", desc("MV switchgear"), [["Bus", "MV-A", ""], ["Bus", "MV-B", ""]])
    for i in range(1, pl["generators"]["count"] + 1):
        add(f"GEN-{i}", "gen", desc(f"GEN-{i}"), [["Feeds", "MV-A", "through the paralleling bus"], ["Feeds", "MV-B", "through the paralleling bus"]])
    hr, subs = pl["heat_rejection"], pl["mechanical_power"]["chiller_unit_subs"]
    chillers = [f"CH-{i:02d}" for i in range(1, hr["chiller_count"] + 1)]
    pumps = [f"FWP-{i}" for i in range(1, hr["pump_count"] + 1)]
    for i, ch in enumerate(chillers, 1):
        add(ch, "chiller", desc(ch), [["Powered by", f"USS-CH{(i - 1) % subs + 1}", ""],
                                      ["Facility water", pumps[0], f"to {pumps[-1]}: the pumps that circulate the loop"]])
    eq = {e["id"]: e for e in S.equipment(site)}
    cdus_all = [f"CDU-{h['letter']}{i}" for h in site["halls"] for i in range(1, h["cooling"]["cdu_count"] + 1)]
    for p_ in pumps:
        add(p_, "pump", desc(p_), [["Powered by", eq[p_]["fed_from"], ""], ["From", chillers[0], f"to {chillers[-1]}"],
                                   ["To", cdus_all[0], f"and the other {len(cdus_all) - 1} CDUs, the thermal walls and the CRAHs"]])
    for i in range(1, subs + 1):
        name = f"USS-CH{i}"
        add(name, "uss", desc(name), [["Fed by", S.mv_bus_for(i), ""]] +
            [["Feeds", x, ""] for x in chillers + pumps if eq[x]["fed_from"] == name])
    return {"kinds": KIND_LABEL, "groups": [[g, label, kinds] for g, label, kinds in GROUPS], "devices": dev}


# --------------------------------------------------------------------------- #
# Reading names
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """The generated directory (``docs/site/devices.json``, written by ``scripts/render_site.py``)."""
    return json.loads(DEVICES_JSON.read_text(encoding="utf-8"))


_PORTS: dict[int, dict[str, list[str]]] = {}


def ports(data: dict[str, Any]) -> dict[str, list[str]]:
    """Every cabled leaf port, "leaf-a07-r1 port 18" -> [tray, NIC], read back from the trays' rail links."""
    key = id(data["devices"])
    if key not in _PORTS:
        _PORTS[key] = {n: [name, note.split()[-1]] for name, e in data["devices"].items() if e["kind"] == "compute_tray"
                       for rel, n, note in e["conn"] if rel.startswith("Rail ")}
    return _PORTS[key]


def lookup(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    """The entry for a name as the pages write it: a device, "Rack A07" (the rack), or a leaf port."""
    devs = data["devices"]
    m = re.fullmatch(r"[Rr]ack ([A-C]\d{2})", name)
    if m:
        name = m.group(1)
    if name in devs:
        return devs[name]
    m = PORT_RE.fullmatch(name)
    if not m or m.group(1) not in devs:
        return None
    sw, port = m.group(1), int(m.group(2))
    to = ports(data).get(f"{sw} port {port}")
    conn = [["Switch", sw, f"rail {sw[-1]}"]]
    if to:
        rack = to[0][:3].upper()
        conn += [["Cable to", to[0], f"NIC {to[1]}, rack {rack}"], ["Rack", rack, ""]]
        text = f"Port {port} of {sw}: cabled to compute tray {int(to[0][-2:])} in rack {rack} ({to[0]}, NIC {to[1]})."
    else:
        rack = devs[sw].get("loc", "").split("|")[-1]
        text = f"Port {port} of {sw}: not cabled to a tray; ports above 36 are uplinks to the spine plane (the spine switches are not in the sample data)."
    return {"kind": "leaf_port", "title": f"{sw} port {port}", "text": text, "conn": conn, "loc": f"{sw} port {port}|{rack}"}


def subset(data: dict[str, Any], names: set[str]) -> dict[str, dict[str, Any]]:
    """The entries a page needs: each name it shows, and every device those entries link to (one step), so a
    card's connections open their own cards."""
    out: dict[str, dict[str, Any]] = {}
    for n in sorted(names):
        e = lookup(data, n)
        if e is None:
            continue
        out[n] = e
        for _, target, _ in e["conn"]:
            if target and target not in out:
                t = lookup(data, target)
                if t is not None:
                    out[target] = t
    return out


# --------------------------------------------------------------------------- #
# Reconciling the directory with the data
# --------------------------------------------------------------------------- #
NOT_DEVICES = {"AUS-1", "HALL-A", "HALL-B", "HALL-C", "OPS-MAIN"}   # the site, halls, and the NOC: places, not devices


def name_coverage(data: dict[str, Any], texts: list[str]) -> tuple[int, list[str]]:
    """Every equipment name in ``texts`` (the glossary's equipment entries, plus the device names it finds in lower
    case) must be in the directory: (names checked, names missing). A leak circuit (C8) belongs to its module."""
    from . import glossary
    gl = glossary.load()
    checked, missing = 0, []
    for text in texts:
        for tok in glossary.tokens(text):
            es = gl.lookup(tok)
            if tok in NOT_DEVICES or not any(e.type == "equipment" and e.key != "EQ-LEAK" for e in es):
                continue
            checked += 1
            if lookup(data, tok) is None:
                missing.append(tok)
    return checked, missing


def cabling_mismatches(data: dict[str, Any], port_events: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """Every UFM port event names the tray NIC on the other end (``peer_host``, ``peer_hca``); the directory must
    say the same cable: (events checked, mismatches). Events without a peer (optic module alarms) are skipped."""
    bad = []
    port_events = [ev for ev in port_events if "peer_host" in ev]
    for ev in port_events:
        key = f"{ev['switch']} port {ev['port']}"
        to = ports(data).get(key)
        if to != [ev["peer_host"], ev["peer_hca"]]:
            bad.append(f"{key}: data says {ev['peer_host']} {ev['peer_hca']}, directory says {to}")
    return len(port_events), bad


# --------------------------------------------------------------------------- #
# Device names in a record, and what they connect to (PIR search, related-record suggestions)
# --------------------------------------------------------------------------- #

_RANGE = re.compile(r"^(?:racks )?(?:to )?([A-Za-z0-9_-]*?)(\d+)$")
_SHELF = re.compile(r"\b([A-C]\d{2}) power shelf (\d)\b")
_TRAYWORD = re.compile(r"\b([a-c]\d{2}-(?:ct|nvsw)\d{1,2})\b")
_RACKS = re.compile(r"racks ([A-C])(\d{2}) to [A-C](\d{2})")
_ADJ: dict[int, dict[str, set[str]]] = {}
BROAD = {"Shared header"}   # "every rack in Hall A draws from the header": true, but it would make every rack a neighbor


def _span_names(first: str, note: str, devs: dict[str, Any]) -> list[str]:
    """"A09" with note "to A16 (row 2)" -> A09..A16; "a07-ct01" with "to a07-ct18: ..." -> every tray."""
    m = re.match(r"to (\S+?)[:,( ]|to (\S+)$", note)
    last = (m.group(1) or m.group(2)) if m else None
    a, b = re.fullmatch(r"(.*?)(\d+)", first), re.fullmatch(r"(.*?)(\d+)", last or "")
    if not (a and b and a.group(1) == b.group(1)):
        return [first]
    w = len(a.group(2))
    out = [f"{a.group(1)}{i:0{w}d}" for i in range(int(a.group(2)), int(b.group(2)) + 1)]
    return [n for n in out if n in devs] or [first]


def adjacency(data: dict[str, Any]) -> dict[str, set[str]]:
    """Every device and the devices it connects to, both ways, read from the directory's "Connected to" rows. Ranges
    ("A09 to A16", "a07-ct01 to a07-ct18") are expanded; a leaf port counts as its switch. The shared Hall A header
    is left out (see ``BROAD``)."""
    key = id(data["devices"])
    if key in _ADJ:
        return _ADJ[key]
    devs = data["devices"]
    adj: dict[str, set[str]] = {n: set() for n in devs}
    for name, e in devs.items():
        for rel, other, note in e.get("conn", []):
            if rel in BROAD:
                continue
            m = PORT_RE.fullmatch(other or "")
            targets = [m.group(1)] if m else _span_names(other, note or "", devs) if other else []
            m2 = _RACKS.search(note or "")
            if m2:
                targets += [f"{m2.group(1)}{i:02d}" for i in range(int(m2.group(2)), int(m2.group(3)) + 1)]
            for t in targets:
                if t in devs and t != name:
                    adj[name].add(t)
                    adj[t].add(name)
    _ADJ[key] = adj
    return adj


def names_in(data: dict[str, Any], *texts: str) -> list[str]:
    """The directory names a record's free text points at: "PSU 5 in A17 power shelf 4" -> A17, A17_PowerShelf_4;
    "Rack A07" -> A07; "NVLink switch tray a15-nvsw3" -> a15-nvsw3, A15; a leaf port -> its switch."""
    from . import glossary
    devs = data["devices"]
    out: list[str] = []
    for text in texts:
        if not text:
            continue
        found = [f"{m.group(1)}_PowerShelf_{m.group(2)}" for m in _SHELF.finditer(text)]
        found += _TRAYWORD.findall(text)
        found += [t for t in glossary.tokens(text)]
        found += re.findall(r"\b[A-C]\d{2}\b", text)
        for n in found:
            m = PORT_RE.fullmatch(n)
            n = m.group(1) if m else n
            if n in devs and n not in NOT_DEVICES and n not in out:
                out.append(n)
    for n in list(out):   # a tray, shelf, or switch tray belongs to its rack
        e = devs[n]
        if e["kind"] in ("compute_tray", "switch_tray", "power_shelf"):
            r = next((o for rel, o, _ in e["conn"] if rel == "In rack" or o[:3].upper() == o[:3] and re.fullmatch(r"[A-C]\d{2}", o)), None)
            if r and r not in out:
                out.append(r)
    return out


def neighbors(data: dict[str, Any], names: list[str]) -> list[str]:
    """Devices one connection away from any of ``names``, not counting the names themselves."""
    adj = adjacency(data)
    near = set().union(*(adj.get(n, set()) for n in names)) if names else set()
    return sorted(near - set(names))
