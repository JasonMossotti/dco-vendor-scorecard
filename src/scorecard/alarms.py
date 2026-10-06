"""Change-aware alarms: one alarm feed for both partners, checked against declared change work.

Portfolio demo; all data fictional. Three steps, all pure functions of the dataset:

* ``normalize`` turns every alarm-bearing source (the Landlord's BMS, UPS cards,
  busway monitors, EPMS, CDU controllers, leak and VESDA panels; the IT side's
  Redfish, NVLink, fabric, GPU, and scheduler feeds) into one list of alarms with
  four severities, a domain, a location, a repeat count, acknowledgment, and the
  partner ticket or work order raised for it.
* ``classify`` checks each alarm against the impact declarations of the change
  records active at that moment (Interface Agreement section 10): expected,
  out of scope (undeclared alarm, too severe, or connected equipment), out of
  window (started early, or left in maintenance after the window), or not change
  work. "Connected" comes from the site model's power and cooling paths.
* ``measure_notifications`` lists the notifications each party owed (NT-1 to
  NT-3) and compares them with the party's delivery log (IA-KM-01, IA-KM-02).

A flag means the alarm does not reconcile with the approved change; it is not a
finding against anyone. The engine never reads ground_truth/.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from scorecard import site_model as S
from scorecard.connectors import FileConnector
from scorecard.synthetic.facility import room_for

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "change_alarms.yaml"
UTC = timezone.utc

EXPECTED, OUT_OF_SCOPE, OUT_OF_WINDOW, NOT_CHANGE = "expected", "out_of_scope", "out_of_window", "not_change_work"
CLASS_TEXT = {EXPECTED: "Expected", OUT_OF_SCOPE: "Out of scope", OUT_OF_WINDOW: "Out of window",
              NOT_CHANGE: "Not change work"}
FLAGGED = (OUT_OF_SCOPE, OUT_OF_WINDOW)
_ASSET = re.compile(r"BW-[A-Z]-R\d+-PG-[A-Z]\d+-[AB]|(?:UPS|MUPS|CDU|TW|CRAH|VESDA|USS)-[A-Z]\d+|CH-\d+|TTDM-[A-Z]|GEN-\d+")


def parse(ts: str | datetime | None) -> datetime | None:
    if isinstance(ts, datetime) or not ts:
        return ts or None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@dataclass
class Alarm:
    source: str
    partner: str
    device: str
    signal: str
    summary: str
    severity: str
    domains: list[str]
    raised: datetime
    cleared: datetime | None = None
    last: datetime | None = None
    tally: int = 1
    rack: str | None = None
    ack_at: datetime | None = None
    ack_by: str | None = None
    evidence: list[str] = field(default_factory=list)
    change_ref: str = ""
    id: str = ""
    hall: str = ""
    location: str = ""
    ticket: dict | None = None
    cls: str = NOT_CHANGE
    change: str = ""
    reason: str = ""

    @property
    def keys(self) -> set[str]:
        k = set(_ASSET.findall(self.device))
        if self.rack:
            k.add(f"rack:{self.rack}")
        return k


# --------------------------------------------------------------------------- #
# Site relationships
# --------------------------------------------------------------------------- #
class SiteMap:
    """Which equipment a change on one asset could plausibly affect, from the site model."""

    def __init__(self, site: dict, topology: dict):
        self.site = site
        self.host_rack = {t["host"]: r["rack"] for r in topology["racks"] for t in r["compute_trays"]}
        self.segments: dict[str, dict] = {}
        self.halls: dict[str, dict] = {}
        for h in site["halls"]:
            if h["state"] == "planned":
                continue
            L = h["letter"]
            segs = S.busway_segments(site, h["id"])
            self.halls[L] = {"ups": S.ups_ids(h), "cdus": [f"CDU-{L}{i}" for i in range(1, h["cooling"]["cdu_count"] + 1)],
                             "vesda": [f"VESDA-{L}{i}" for i in range(1, h["fire_life_safety"]["vesda_detectors"] + 1)],
                             "racks": [r["rack"] for r in S.racks(site, h["id"])]}
            for s in segs:
                for side in ("A", "B"):
                    other = "B" if side == "A" else "A"
                    self.segments[f"{s['id']}-{side}"] = {"racks": s["racks"], "sibling": f"{s['id']}-{other}",
                                                          "ups": s["feeds"][side]}

    @staticmethod
    def hall_of(device: str, rack: str | None = None) -> str:
        if rack:
            return rack[0]
        m = _ASSET.search(device)
        tok = m.group(0) if m else device
        if tok.startswith(("BW-", "TTDM-")):
            return tok.split("-")[1][0]
        if re.match(r"(UPS|MUPS|CDU|TW|CRAH|VESDA|USS)-[A-Z]", tok):
            return tok.split("-")[1][0]
        return "Plant"

    def scope(self, asset: str) -> set[str]:
        """The asset itself plus what its work could disturb: redundant partners and the load it serves."""
        out = {asset}
        if asset.startswith("rack:"):
            return out
        if asset in self.segments:
            seg = self.segments[asset]
            out.add(seg["sibling"])
            out |= {f"rack:{r}" for r in seg["racks"]}
            return out
        L = self.hall_of(asset)
        hall = self.halls.get(L)
        if not hall:
            return out
        if asset.startswith("UPS-"):
            out |= set(hall["ups"])
            for bw, seg in self.segments.items():
                if seg["ups"] == asset:
                    out.add(bw)
                    out |= {f"rack:{r}" for r in seg["racks"]}
        elif asset.startswith("CDU-"):
            out |= set(hall["cdus"]) | {f"TTDM-{L}"} | {f"rack:{r}" for r in hall["racks"]}
        elif asset.startswith("VESDA-"):
            out |= set(hall["vesda"])
        return out


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
class _Episodes:
    """Raise/clear events per (source, device, signal) key, merged into rows with a tally."""

    def __init__(self, merge_min: float):
        self.merge = timedelta(minutes=merge_min)
        self.rows: list[Alarm] = []
        self.by_key: dict[tuple, Alarm] = {}

    def raise_(self, key: tuple, t: datetime, make) -> Alarm:
        a = self.by_key.get(key)
        if a and (a.cleared is None or t - a.cleared <= self.merge):
            a.tally += 1
            a.last = t
            a.cleared = None
            return a
        a = make()
        a.last = t
        self.rows.append(a)
        self.by_key[key] = a
        return a

    def clear(self, key: tuple, t: datetime) -> None:
        a = self.by_key.get(key)
        if a and a.cleared is None:
            a.cleared = t

    def instant(self, key: tuple, t: datetime, make) -> Alarm:
        a = self.raise_(key, t, make)
        a.cleared = t
        return a


def _bms_domain(cfg: dict, device: str) -> list[str]:
    for prefix, dom in cfg["alarm_map"]["bms_domain"].items():
        if device.startswith(prefix):
            return list(dom)
    return ["maintenance"]


def normalize(src: FileConnector, cfg: dict | None = None) -> list[Alarm]:
    cfg = cfg or load_config()
    am = cfg["alarm_map"]
    landlord = _Episodes(cfg["repeat_merge_min"])
    it = _Episodes(cfg["repeat_merge_min"])
    L, IT = "Landlord", "IT Partner"

    # ---- Landlord: the BMS is the alarm of record
    for e in src.get("facility_bms"):
        t, dev = parse(e["timestamp"]), e["device"]
        if e["kind"] == "alarm":
            key = ("bms", dev, e["alarm"])
            rack = dev[5:] if dev.startswith("Rack ") else None
            if e["state"] == "active":
                landlord.raise_(key, t, lambda: Alarm("BMS", L, dev, e["alarm"], e["alarm"],
                                                      am["bms_priority"][e["priority"]], _bms_domain(cfg, dev), t, rack=rack))
            elif e["state"] == "acknowledged":
                a = landlord.by_key.get(key)
                if a and a.ack_at is None:
                    a.ack_at, a.ack_by = t, e.get("user")
            elif e["state"] == "cleared":
                landlord.clear(key, t)
        else:   # override or inhibit
            key = ("bms-ovr", dev, e["point"])
            word = "Alarm inhibited" if e["kind"] == "inhibit" else "Point override"
            if e["action"] == "set":
                a = landlord.raise_(key, t, lambda: Alarm("BMS", L, dev, word, f"{word}: {e['point']} = {e['value']}",
                                                          am["bms_override"]["severity"], ["maintenance"], t))
                a.change_ref = e.get("change_ref") or ""
            else:
                landlord.clear(key, t)
    bms_rows = list(landlord.rows)

    dev_rows = _Episodes(cfg["repeat_merge_min"])
    for e in src.get("ups_nmc_events"):
        t, u, ev = parse(e["timestamp"]), e["ups"], e["event"]
        if ev.startswith("upsBasicOutputStatus "):
            state = ev.split()[1]
            for k in am["ups_status"]:
                if k != state:
                    dev_rows.clear(("ups", u, k), t)
            m = am["ups_status"].get(state)
            if m:
                dev_rows.raise_(("ups", u, state), t, lambda: Alarm("UPS card", L, u, m["signal"], f"{u}: {m['signal']}",
                                                                   m["severity"], ["power"], t))
        elif ev.startswith("Power module") and ev.endswith("fault"):
            m = am["ups_module_fault"]
            dev_rows.raise_(("ups-mod", u), t, lambda: Alarm("UPS card", L, u, m["signal"], f"{u}: {ev}", m["severity"], ["power"], t))
        elif ev == "Power module redundancy restored":
            dev_rows.clear(("ups-mod", u), t)
    for e in src.get("busway_events"):
        t, bw = parse(e["timestamp"]), e["busway"]
        if e.get("point") == "Tap-off breaker":
            key = ("tap", bw, e["tapoff"])
            if e["event"] == "Breaker open":
                m = am["busway"]["breaker_open"]
                rack = e.get("rack")
                dev_rows.raise_(key, t, lambda: Alarm("Busway monitor", L, bw, m["signal"], f"Tap-off {e['tapoff']} open on {bw}",
                                                      m["severity"], ["power"], t, rack=rack))
            else:
                dev_rows.clear(key, t)
        elif e.get("state") == "out_of_tolerance":
            m = am["busway"]["undervoltage"]
            dev_rows.raise_(("bwv", bw), t, lambda: Alarm("Busway monitor", L, bw, m["signal"], f"{bw}: {m['signal']}",
                                                          m["severity"], ["power"], t))
        elif e.get("state") == "in_tolerance":
            dev_rows.clear(("bwv", bw), t)
    for e in src.get("epms_events"):
        t, dev, ev = parse(e["timestamp"]), e["device"], e["event"]
        if "Trip" in ev or "trip" in ev:
            m = am["epms_trip"]
            dev_rows.raise_(("epms", dev), t, lambda: Alarm("EPMS", L, dev, m["signal"], f"{dev}: {ev}", m["severity"], ["power"], t))
        elif ev.startswith(("Closed", "Breaker closed")):
            dev_rows.clear(("epms", dev), t)
    for e in src.get("cdu_events"):
        t, cdu, res, prop, val = parse(e["timestamp"]), e["cdu"], e["resource"], e["property"], e["value"]
        pump = res.rsplit("/", 1)[-1] if "/Pumps/" in res else None
        cm = am["cdu"]
        if prop == "Status.State" and pump:
            key = ("cdu-iso", cdu, pump)
            if val == "Disabled":
                dev_rows.raise_(key, t, lambda: Alarm("CDU controller", L, cdu, cm["pump_disabled"]["signal"],
                                                      f"{cdu} pump {pump} isolated", cm["pump_disabled"]["severity"], ["cooling"], t))
            elif val == "Enabled":
                dev_rows.clear(key, t)
        elif prop == "Status.Health" and pump:
            key = ("cdu-fail", cdu, pump)
            if val == "Critical":
                dev_rows.raise_(key, t, lambda: Alarm("CDU controller", L, cdu, cm["pump_critical"]["signal"],
                                                      f"{cdu} pump {pump} failed", cm["pump_critical"]["severity"], ["cooling"], t))
            elif val == "OK":
                dev_rows.clear(key, t)
        elif prop == "PumpRedundancy.Status.Health":
            key = ("cdu-red", cdu)
            if val != "OK":
                dev_rows.raise_(key, t, lambda: Alarm("CDU controller", L, cdu, cm["redundancy_warning"]["signal"],
                                                      f"{cdu}: pump redundancy lost", cm["redundancy_warning"]["severity"], ["cooling"], t))
            else:
                dev_rows.clear(key, t)
    for e in src.get("leak_events"):
        t, dev = parse(e["timestamp"]), f"{e['controller']}"
        key = ("leak", dev, e["circuit"])
        if e["event"] == "LEAK":
            m = am["leak"]
            dev_rows.raise_(key, t, lambda: Alarm("Leak panel", L, dev, m["signal"],
                                                  f"Leak on {dev} circuit {e['circuit']} at {e['distance_m']} m ({e['label']})",
                                                  m["severity"], ["cooling"], t))
        else:
            dev_rows.clear(key, t)
    vm = am["vesda"]
    for e in src.get("vesda_events"):
        t, det, ev = parse(e["timestamp"]), e["detector"], e["event"]
        if ev == "Isolate":
            dev_rows.raise_(("vesda-iso", det), t, lambda: Alarm("VESDA panel", L, det, vm["isolate"]["signal"],
                                                                 f"{det} isolated ({e['detail']})", vm["isolate"]["severity"], ["fire"], t))
        elif ev == "Alarm":
            sev = vm["alarm_levels"].get(e["level"], "critical")
            dev_rows.raise_(("vesda-alm", det), t, lambda: Alarm("VESDA panel", L, det, "Smoke alarm",
                                                                 f"{det} smoke alarm {e['level']} ({e['detail']})", sev, ["fire"], t))
        elif ev == "Fault":
            dev_rows.raise_(("vesda-flt", det), t, lambda: Alarm("VESDA panel", L, det, vm["fault"]["signal"],
                                                                 f"{det} fault: {e['detail']}", vm["fault"]["severity"], ["fire"], t))
        elif ev == "Normal":
            for k in ("vesda-iso", "vesda-alm", "vesda-flt"):
                dev_rows.clear((k, det), t)

    # A device event within seconds of a BMS alarm on the same device is that alarm's evidence.
    merge = timedelta(seconds=cfg["bms_merge_s"])
    facility = list(bms_rows)
    for a in dev_rows.rows:
        host = next((b for b in bms_rows if b.device == a.device and abs(b.raised - a.raised) <= merge), None)
        if host:
            host.evidence.append(f"{a.source}: {a.summary}")
            if a.rack and not host.rack:
                host.rack = a.rack
        else:
            facility.append(a)

    # ---- IT partner telemetry
    imap = am["it"]
    topo = src.get("topology")
    host_rack = {t["host"]: r["rack"] for r in topo["racks"] for t in r["compute_trays"]}

    def mk(key, kind, t, device, rack, summary, sev=None, signal=None, source=""):
        m = imap[kind]
        return lambda: Alarm(source, IT, device, signal or m["signal"], summary, sev or m["severity"], list(m["domain"]), t, rack=rack)

    for e in src.get("bms_events"):   # rack leak ropes on the CDU manifolds (IT side)
        t, key = parse(e["timestamp"]), ("rleak", e["point"])
        rack = e["point"].split()[0]
        if e["state"] == "active":
            it.raise_(key, t, mk(key, "rack_leak", t, e["cdu"], rack, f"{e['point']}: leak detected", source="Rack leak rope"))
        else:
            it.clear(key, t)
    for e in src.get("redfish_events"):
        t, res, et = parse(e["timestamp"]), e["resource"], e["event_type"]
        rack = e.get("rack")
        if et == "PowerSupplyFailed":
            it.raise_(("psu", res), t, mk(None, "psu_failed", t, res.split("/")[4], rack, e["message"], source="Redfish"))
        elif et == "PowerShelfFailed":
            it.raise_(("shelf", res), t, mk(None, "shelf_failed", t, res.split("/")[4], rack, e["message"], source="Redfish"))
        elif et == "PowerRedundancyRestored":
            it.clear(("psu", res), t)
            for k in [k for k in it.by_key if k[0] == "shelf" and k[1].startswith(res.rsplit("/PowerSubsystem", 1)[0])]:
                it.clear(k, t)
        elif et == "LeakDetected":
            it.raise_(("rf-leak", rack), t, mk(None, "rack_leak", t, f"Rack {rack}", rack, e["message"], source="Redfish"))
        elif et == "LeakIsolated":
            it.clear(("rf-leak", rack), t)
    for e in src.get("nmx_events"):
        t, unit = parse(e["timestamp"]), e["unit"]
        if e["state"] == "failed":
            it.raise_(("nmx", unit), t, mk(None, "nvlink_failed", t, unit.split()[-1], e["rack"], e["message"], source="NVLink manager"))
        else:
            it.clear(("nmx", unit), t)
    for e in src.get("ufm_events"):
        t, ev = parse(e["timestamp"]), e["event"]
        dev = f"{e['switch']} port {e['port']}"
        rack = host_rack.get(e["peer_host"])
        key = ("ufm", dev)
        if ev == "link_down":
            it.raise_(key, t, mk(None, "link_down", t, dev, rack, f"{dev} to {e['peer_host']}: link down", source="Fabric manager"))
        elif ev == "link_up":
            it.clear(key, t)
        elif ev == "symbol_error_threshold":
            it.instant(("ufm-sym", dev), t, mk(None, "symbol_threshold", t, dev, rack,
                                               f"{dev} to {e['peer_host']}: symbol errors over threshold", source="Fabric manager"))
    for e in src.get("xid_events"):
        t, host, xid = parse(e["timestamp"]), e["host"], e["xid"]
        sev = "major" if xid in imap["xid_major"] else "minor"
        it.instant(("xid", host, xid), t, lambda: Alarm("GPU telemetry", IT, host, imap["xid_signal"],
                                                         f"{host} GPU {e['gpu_index']}: XID {xid} {e['message']}", sev, ["compute"], t,
                                                         rack=host_rack.get(host)))
    # Scheduler: nodes not responding; half a rack or more within 10 minutes is one rack outage.
    states = sorted(src.get("scheduler_states"), key=lambda e: e["timestamp"])
    downs: list[tuple[datetime, str]] = [(parse(e["timestamp"]), e["node"]) for e in states if e["state"] == "down"]
    nxt_idle: dict[tuple[str, datetime], datetime | None] = {}
    for t, node in downs:
        nxt_idle[(node, t)] = next((parse(e["timestamp"]) for e in states
                                    if e["node"] == node and e["state"] == "idle" and parse(e["timestamp"]) > t), None)
    used: set[tuple[str, datetime]] = set()
    by_rack: dict[str, list[tuple[datetime, str]]] = {}
    for t, node in downs:
        by_rack.setdefault(host_rack.get(node, "?"), []).append((t, node))
    need = imap["rack_outage_nodes"]
    for rack, lst in by_rack.items():
        i = 0
        while i < len(lst):
            t0 = lst[i][0]
            group = [x for x in lst[i:] if x[0] - t0 <= timedelta(minutes=10)]
            if len({n for _, n in group}) >= need:
                clear = [nxt_idle[(n, t)] for t, n in group]
                a = Alarm("Scheduler", IT, f"Rack {rack}", imap["rack_outage"]["signal"],
                          f"Rack {rack}: {len(group)} nodes not responding", imap["rack_outage"]["severity"],
                          list(imap["rack_outage"]["domain"]), t0, rack=rack)
                a.cleared = None if any(c is None for c in clear) else max(clear)
                a.last, a.tally = group[-1][0], len(group)
                it.rows.append(a)
                used |= {(n, t) for t, n in group}
                i += len(group)
            else:
                i += 1
    for t, node in downs:
        if (node, t) in used:
            continue
        a = it.raise_(("node", node), t, mk(None, "node_down", t, node, host_rack.get(node), f"{node} not responding", source="Scheduler"))
        a.cleared = nxt_idle[(node, t)]

    rows = facility + it.rows
    rows.sort(key=lambda a: (a.raised, a.partner, a.device, a.signal))
    for n, a in enumerate(rows, 1):
        a.id = f"ALM-{n:04d}"
        a.hall = SiteMap.hall_of(a.device, a.rack)
        if a.rack:
            a.location = f"Hall {a.rack[0]}, rack {a.rack}"
        elif a.partner == "Landlord":
            m = _ASSET.search(a.device)
            a.location = room_for(m.group(0)) if m else "Central plant"
        else:
            a.location = f"Hall {a.hall}"
    _link_tickets(rows, src)
    return rows


def _link_tickets(rows: list[Alarm], src: FileConnector) -> None:
    """The partner ticket or work order raised for each alarm (same equipment, opened around the alarm)."""
    wos = src.get("work_orders")
    tickets = src.get("tickets")
    for a in rows:
        if a.partner == "Landlord":
            c = [w for w in wos if (w["unit"] == a.device or w["unit"].startswith(a.device + "/")
                                    or (a.rack and w["unit"] == f"Rack {a.rack}") or w["unit"] in a.keys)
                 and timedelta(minutes=-60) <= parse(w["opened"]) - a.raised <= timedelta(minutes=10)]
            if c:
                w = min(c, key=lambda w: abs(parse(w["opened"]) - a.raised))
                a.ticket = {"id": w["wo"], "opened": w["opened"], "resolved": w["restored_at"] or w["closed"],
                            "closed": w["closed"], "ack": w["acknowledged_at"], "by": w["engineer"], "priority": w["priority"]}
        elif a.rack:
            c = [k for k in tickets if k.get("rack") == a.rack
                 and timedelta(minutes=-10) <= parse(k["opened_at"]) - a.raised <= timedelta(minutes=60)]
            if c:
                k = min(c, key=lambda k: (a.device not in k["configuration_item"], abs(parse(k["opened_at"]) - a.raised)))
                a.ticket = {"id": k["number"], "opened": k["opened_at"], "resolved": k["resolved_at"], "closed": k["resolved_at"],
                            "ack": k["acknowledged_at"], "by": k["assigned_to"], "priority": k["priority"]}
        if a.ticket and a.ack_at is None and a.ticket["ack"]:
            a.ack_at, a.ack_by = parse(a.ticket["ack"]), a.ticket["by"]


def trouble_tickets(src: FileConnector, cfg: dict | None = None) -> list[dict]:
    """Every trouble ticket from both partners, with the equipment and domain it is about.

    Landlord work orders that carry a MOP are planned change work, not trouble, and are left out.
    """
    cfg = cfg or load_config()
    am = cfg["alarm_map"]
    out = []
    for w in src.get("work_orders"):
        if w.get("mop_ref"):
            continue
        unit = w["unit"]
        keys = set(_ASSET.findall(unit))
        if unit.startswith("Rack "):
            keys.add(f"rack:{unit[5:]}")
        out.append({"id": w["wo"], "partner": "Landlord", "priority": w["priority"], "device": unit, "location": w["room"],
                    "summary": w["notes"], "opened": iso(parse(w["opened"])), "closed": iso(parse(w["closed"])),
                    "keys": sorted(keys), "domains": [d for d in _bms_domain(cfg, unit) if d != "maintenance"] or ["power"]})
    for k in src.get("tickets"):
        out.append({"id": k["number"], "partner": "IT Partner", "priority": k["priority"], "device": k["configuration_item"],
                    "location": f"Hall {k['rack'][0]}, rack {k['rack']}", "summary": k["short_description"],
                    "opened": iso(parse(k["opened_at"])), "closed": iso(parse(k["resolved_at"])),
                    "keys": [f"rack:{k['rack']}"], "domains": am["it_ticket_domain"].get(k["category"], ["compute"])})
    return sorted(out, key=lambda t: (t["opened"], t["id"]))


# --------------------------------------------------------------------------- #
# Change records and declarations
# --------------------------------------------------------------------------- #
def change_records(src: FileConnector) -> list[dict]:
    """Every approved change from both partners, in one shape."""
    out = [{"change_id": m["mop_id"], "owner": "Landlord", "title": m["title"], "assets": list(m["assets"]),
            "window_start": iso(parse(m["window_start"])), "window_end": iso(parse(m["window_end"]))} for m in src.get("landlord_mops")]
    out += [{"change_id": c["change_id"], "owner": "IT Partner", "title": c["summary"], "assets": [f"rack:{c['rack']}"],
             "window_start": iso(parse(c["window_start"])), "window_end": iso(parse(c["window_end"]))} for c in src.get("cab_changes")]
    return sorted(out, key=lambda c: (c["window_start"], c["change_id"]))


def declare(change: dict, cfg: dict) -> dict:
    """The structured impact declaration for one change record, from the change-type catalog."""
    for ct in cfg["change_types"]:
        if re.match(ct["match"], change["title"]):
            return {**change, "type": ct["id"], "domains": ct["domains"], "max_severity": ct["max_severity"],
                    "redundancy_reduced": ct["redundancy_reduced"], "grace_min": cfg["grace_min"],
                    "expected": [{"asset": a, "alarms": list(ct["expected"])} for a in change["assets"]]}
    raise ValueError(f"No change type matches {change['change_id']}: {change['title']!r}")


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify(alarms: list[Alarm], declarations: list[dict], sitemap: SiteMap, cfg: dict | None = None) -> list[Alarm]:
    """Classify every alarm in place and return the added out-of-window overrun alarms."""
    cfg = cfg or load_config()
    rank = cfg["severity_rank"]
    lookback = timedelta(hours=cfg["early_lookback_h"])
    decl = []
    for d in declarations:
        ws, we, g = parse(d["window_start"]), parse(d["window_end"]), timedelta(minutes=d["grace_min"])
        declared = {e["asset"]: set(e["alarms"]) for e in d["expected"]}
        scope = set().union(*(sitemap.scope(a) for a in declared))
        decl.append((d, ws, we, g, declared, scope))

    for a in alarms:
        best = None
        for d, ws, we, g, declared, scope in decl:
            hit = a.keys & set(declared)
            in_win = ws - g <= a.raised <= we + g
            if hit and a.signal in set().union(*(declared[h] for h in hit)):
                if in_win:
                    if rank[a.severity] > rank[d["max_severity"]]:
                        res = (OUT_OF_SCOPE, f"{a.signal} at {a.severity} exceeds the declared worst severity ({d['max_severity']})")
                    else:
                        res = (EXPECTED, f"Declared by {d['change_id']}")
                elif ws - lookback <= a.raised < ws - g:
                    res = (OUT_OF_WINDOW, f"Declared work signal {_mins(ws - a.raised)} before the window opened")
                elif we + g < a.raised <= we + lookback:
                    res = (OUT_OF_WINDOW, f"Declared work signal {_mins(a.raised - we)} after the window closed")
                else:
                    continue
            elif hit and in_win and set(a.domains) & set(d["domains"]):
                res = (OUT_OF_SCOPE, f"{a.signal} on a declared asset was not declared")
            elif in_win and (a.keys & scope) and set(a.domains) & set(d["domains"]):
                res = (OUT_OF_SCOPE, f"Connected to {', '.join(sorted(declared))} ({'/'.join(d['domains'])}), not declared")
            else:
                continue
            order = {EXPECTED: 0, OUT_OF_SCOPE: 1, OUT_OF_WINDOW: 2}     # an alarm another approved change declared is accounted for
            if best is None or order[res[0]] < order[best[0]]:
                best = (res[0], res[1], d)
        if best:
            a.cls, a.reason, a.change = best[0], best[1], best[2]["change_id"]

    # Overruns: a declared asset still in its maintenance state after the window plus grace.
    added = []
    for d, ws, we, g, declared, scope in decl:
        for a in alarms:
            if a.change != d["change_id"] or a.cls != EXPECTED:
                continue
            if a.cleared is None or a.cleared > we + g:
                o = Alarm("Customer check", d["owner"], a.device, "Change window overrun",
                          f"{d['change_id']} window has closed with this still in effect: {a.summary}",
                          "major", list(a.domains), we + g, cleared=a.cleared, rack=a.rack)
                o.last, o.cls, o.change = we + g, OUT_OF_WINDOW, d["change_id"]
                o.reason = (f"Still in its maintenance state {_mins(o.cleared - we)} after the window closed"
                            if o.cleared else "Still in its maintenance state when the data ends")
                o.hall, o.location, o.ticket = a.hall, a.location, a.ticket
                o.evidence = [f"{a.id}: {a.summary}"]
                added.append(o)
    return added


def change_conflicts(declarations: list[dict], sitemap: SiteMap) -> list[dict]:
    """Two approved changes that reduce redundancy on connected equipment at the same time.

    Each change's alarms are accounted for by its own declaration, so the check cannot flag them; the overlap
    itself is the risk (two pumps out on one header is less margin than either change declared).
    """
    out = []
    for i, a in enumerate(declarations):
        for b in declarations[i + 1:]:
            if not (a["redundancy_reduced"] and b["redundancy_reduced"]) or not set(a["domains"]) & set(b["domains"]):
                continue
            g = timedelta(minutes=a["grace_min"])
            if not (parse(a["window_start"]) - g < parse(b["window_end"]) + g and parse(b["window_start"]) - g < parse(a["window_end"]) + g):
                continue
            sa = set().union(*(sitemap.scope(x) for x in a["assets"]))
            if sa & set(b["assets"]):
                out.append({"changes": [a["change_id"], b["change_id"]], "assets": a["assets"] + b["assets"],
                            "overlap_start": max(a["window_start"], b["window_start"]),
                            "overlap_end": min(a["window_end"], b["window_end"]),
                            "text": f"{a['change_id']} and {b['change_id']} both reduce {'/'.join(sorted(set(a['domains']) & set(b['domains'])))} "
                                    f"redundancy on connected equipment ({', '.join(a['assets'] + b['assets'])}) in overlapping windows"})
    return out


def _mins(td: timedelta) -> str:
    m = round(td.total_seconds() / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


# --------------------------------------------------------------------------- #
# Notifications (Interface Agreement section 10)
# --------------------------------------------------------------------------- #
def owed_notifications(alarms: list[Alarm], declarations: list[dict], ia: dict) -> list[dict]:
    rules = {n["id"]: n for n in ia["alarm_notification"]["notifications"]}
    owner = {d["change_id"]: d["owner"] for d in declarations}
    out = []
    for a in alarms:
        need: dict[str, dict] = {}
        if a.cls in FLAGGED:
            r = rules["NT-3"]
            need[owner[a.change]] = {"rule": "NT-3", "within_min": r["within_min"], "channels_min": r["channels_min"],
                                     "page": a.severity == "critical"}
        if a.cls != EXPECTED and a.severity in ("critical", "major") and a.source != "Customer check":
            r = rules["NT-1" if a.severity == "critical" else "NT-2"]
            cur = need.get(a.partner)
            new = {"rule": r["id"], "within_min": r["within_min"], "channels_min": r["channels_min"], "page": r["page"]}
            if cur is None:
                need[a.partner] = new
            else:   # one notification, strictest terms
                cur["within_min"] = min(cur["within_min"], new["within_min"])
                cur["page"] = cur["page"] or new["page"]
                cur["rule"] = f"{cur['rule']}+{new['rule']}"
        for party, n in need.items():
            out.append({"alarm": a.id, "party": party, "device": a.device, "signal": a.signal, "severity": a.severity,
                        "raised": iso(a.raised), "cls": a.cls, "change": a.change if "NT-3" in n["rule"] else "", **n})
    return out


def measure_notifications(owed: list[dict], log: list[dict]) -> list[dict]:
    """Match each owed notification to the party's delivery log (same party, device, and alarm time)."""
    for o in owed:
        t = parse(o["raised"])
        sent = [x for x in log if x["party"] == o["party"] and x["device"] == o["device"] and x["signal"] == o["signal"]
                and abs(parse(x["alarm_time"]) - t) <= timedelta(seconds=120)]
        if not sent:
            o["status"], o["sent"], o["channels"] = "missing", None, []
            continue
        first = min(parse(x["sent_at"]) for x in sent)
        chans = sorted({x["channel"] for x in sent if parse(x["sent_at"]) - t <= timedelta(minutes=o["within_min"])})
        o["sent"] = iso(first)
        o["channels"] = sorted({x["channel"] for x in sent})
        o["delay_min"] = round((first - t).total_seconds() / 60, 1)
        auto = [c for c in chans if c != "phone"]
        if first - t > timedelta(minutes=o["within_min"]):
            o["status"] = "late"
        elif len(auto) < o["channels_min"] or (o["page"] and "page" not in auto):
            o["status"] = "incomplete"
        elif o["change"] and not any(x.get("change_ref") == o["change"] for x in sent):
            o["status"] = "incomplete"          # NT-3: the notification must name the change it falls outside
        else:
            o["status"] = "on_time"
    return owed


def key_measures(owed: list[dict], ia: dict) -> list[dict]:
    out = []
    for km in ia["alarm_notification"]["key_measures"]:
        mine = [o for o in owed if o["party"] == km["party"]]
        ok = [o for o in mine if o["status"] == "on_time"]
        by_rule = {}
        for rule in ("NT-1", "NT-2", "NT-3"):
            r = [o for o in mine if rule in o["rule"]]
            by_rule[rule] = {"owed": len(r), "on_time": sum(o["status"] == "on_time" for o in r)}
        out.append({"id": km["id"], "party": km["party"], "target": km["target"], "owed": len(mine), "on_time": len(ok),
                    "actual": round(100 * len(ok) / len(mine), 1) if mine else None,
                    "missing": sum(o["status"] == "missing" for o in mine), "late": sum(o["status"] == "late" for o in mine),
                    "incomplete": sum(o["status"] == "incomplete" for o in mine), "by_rule": by_rule})
    return out


# --------------------------------------------------------------------------- #
# Whole check
# --------------------------------------------------------------------------- #
def run_check(data_dir: str | Path, changes_dir: str | Path, cfg: dict | None = None) -> dict[str, Any]:
    from scorecard.sla_model import load_interface_agreement
    cfg = cfg or load_config()
    src = FileConnector(data_dir)
    changes_dir = Path(changes_dir)
    declarations = json.loads((changes_dir / "impact_declarations.json").read_text(encoding="utf-8"))
    log = json.loads((changes_dir / "notification_log.json").read_text(encoding="utf-8"))
    sitemap = SiteMap(S.load_site(), src.get("topology"))
    alarms = normalize(src, cfg)
    overruns = classify(alarms, declarations, sitemap, cfg)
    n = len(alarms)
    for k, o in enumerate(sorted(overruns, key=lambda o: o.raised), 1):
        o.id = f"ALM-{n + k:04d}"
    alarms = sorted(alarms + overruns, key=lambda a: (a.raised, a.id))
    ia = load_interface_agreement()
    conflicts = change_conflicts(declarations, sitemap)
    owed = measure_notifications(owed_notifications(alarms, declarations, ia), log)
    manifest = json.loads((Path(data_dir) / "manifest.json").read_text(encoding="utf-8"))
    return {"window": manifest["window"], "alarms": alarms, "declarations": declarations, "owed": owed,
            "key_measures": key_measures(owed, ia), "log": log, "conflicts": conflicts}


def alarm_dict(a: Alarm) -> dict:
    d = asdict(a)
    for k in ("raised", "cleared", "last", "ack_at"):
        d[k] = iso(d[k])
    return d


def score(alarms: list[Alarm], owed: list[dict], key: list[dict]) -> dict:
    """Compare the check with the generator's answer key (natural and planted cases)."""
    flagged = [a for a in alarms if a.cls in FLAGGED]
    matched: set[str] = set()
    res = {"cases": 0, "found": 0, "decoys": 0, "decoys_flagged": 0, "notify": 0, "notify_found": 0,
           "missed": [], "other_flags": [], "by_type": {}}

    def find(k: dict) -> Alarm | None:
        t = parse(k["at"])
        for a in alarms:
            if (k["device"] in a.keys or k["device"] == a.device) and abs(a.raised - t) <= timedelta(minutes=5) \
                    and (k.get("signal") is None or a.signal == k["signal"]):
                return a
        return None

    for k in key:
        if k["kind"] == "notification":
            res["notify"] += 1
            o = next((o for o in owed if o["device"] == k["device"] and abs(parse(o["raised"]) - parse(k["at"])) <= timedelta(seconds=120)
                      and o["status"] == k["expect"]), None)
            res["notify_found"] += bool(o)
            if not o:
                res["missed"].append(f"{k['type']} {k['device']} {k['at']}")
            res["by_type"].setdefault(k["type"], [0, 0])
            res["by_type"][k["type"]][0] += bool(o)
            res["by_type"][k["type"]][1] += 1
            continue
        a = find(k)
        if k["expect"] in FLAGGED:
            res["cases"] += 1
            ok = bool(a and a.cls == k["expect"])
            res["found"] += ok
            if a:
                matched.add(a.id)
            if not ok:
                res["missed"].append(f"{k['type']} {k['device']} {k['at']} (got {a.cls if a else 'no alarm'})")
        else:
            res["decoys"] += 1
            bad = bool(a and a.cls in FLAGGED)
            res["decoys_flagged"] += bad
            if a:
                matched.add(a.id)
            if bad:
                res["missed"].append(f"decoy {k['type']} {k['device']} flagged {a.cls}")
            ok = not bad
        res["by_type"].setdefault(k["type"], [0, 0])
        res["by_type"][k["type"]][0] += ok
        res["by_type"][k["type"]][1] += 1
    res["other_flags"] = [f"{a.id} {a.device} {a.signal} {a.cls} ({a.change}): {a.reason}" for a in flagged if a.id not in matched]
    return res
