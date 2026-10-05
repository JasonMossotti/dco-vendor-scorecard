"""Engine core: data context, ticket/telemetry linking, and Tickets of Record.

The ``Context`` loads every source through a connector, parses it once, and
builds the indexes detectors need. It also derives outages from telemetry
alone and turns them into Tickets of Record with the SLA's measurement rules,
so vendor ticket boundaries never decide how restoration is measured.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from scorecard.connectors import SiteDataSource
from scorecard.measurement import Outage, TicketOfRecord, build_tickets_of_record

# Ticket category (as written by the vendor ITSM) -> SLA fault class.
CATEGORY_TO_CLASS = {
    "tray_gpu": "FC-GPU",
    "optic_link": "FC-LINK",
    "psu": "FC-PSU",
    "power_shelf": "FC-SHELF",
    "switch_tray": "FC-SWITCH",
    "cdu_pump": "FC-CDU",
    "rack_facility": "FC-RACK",
    "leak": "FC-LEAK",
}
XID_FAMILY = {79: "bus", 94: "ecc", 48: "ecc", 119: "gsp", 145: "nvlink", 149: "nvlink"}

_LINK_RE = re.compile(r"Link (?P<host>\S+):(?P<hca>mlx5_\d+) <-> (?P<switch>\S+):swp(?P<port>\d+)")
_PSU_RE = re.compile(r"PSU (?P<psu>\d+) in (?P<rack>[A-Z]\d+) power shelf (?P<shelf>\d+)")
_SHELF_RE = re.compile(r"^(?P<rack>[A-Z]\d+) power shelf (?P<shelf>\d+)$")
_CDU_RE = re.compile(r"(CDU-[A-Z]\d+)")
_HOST_RE = re.compile(r"^[a-z]\d+-ct\d+$")


@dataclass
class Finding:
    """One discrepancy, with the evidence that proves it."""

    type: str
    title: str
    summary: str
    tickets: list[str]
    unit: str | None
    observed_at: datetime | None
    evidence: list[dict[str, Any]]
    sla_refs: list[str]
    recommended_action: str
    severity: str | None = None
    severity_name: str | None = None
    escalation: str | None = None
    severity_reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    keys: dict[str, Any] = field(default_factory=dict)   # stable identifiers (shift, rack) for matching
    id: str = ""


def ev(source: str, at: datetime | None, detail: str) -> dict[str, Any]:
    """Evidence item: which system said what, and when."""
    return {"source": source, "at": at, "detail": detail}


def fmt_t(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "n/a"


def minutes_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60.0


class Context:
    """All site data, parsed and indexed, plus telemetry-derived Tickets of Record."""

    def __init__(self, sla: dict[str, Any], source: SiteDataSource, attribution: bool = True):
        self.sla = sla
        self.src = source
        self.attribution = attribution   # Interface Agreement FA-3: start the IT clock at the Landlord's handoff
        g = source.get
        manifest = g("manifest")
        self.window_start: datetime = manifest["window"]["start"]
        self.window_end: datetime = manifest["window"]["end"]
        self.tolerance = timedelta(minutes=sla["measurement"]["record_integrity_tolerance_min"])

        # Raw sources
        self.tickets: list[dict] = sorted(g("tickets"), key=lambda t: t["opened_at"])
        self.xid = g("xid_events")
        self.redfish = g("redfish_events")
        self.inventory = g("inventory_changes")
        self.nmx = g("nmx_events")
        self.ufm = g("ufm_events")
        self.bms = g("bms_events")
        self.health = g("health_checks")
        self.sched = g("scheduler_states")
        self.badges = g("badge_events")
        self.cab = g("cab_changes")
        self.roster = g("roster")
        self.personnel = {p["person_id"]: p for p in g("personnel")}
        self.ledger = g("spares_ledger")
        self.cycle_counts = g("cycle_counts")
        self.rma = g("rma_shipments")
        self.vendor_weekly = g("vendor_weekly")

        # Lookups from the SLA
        self.fault_classes = {fc["id"]: fc for fc in sla["measurement_spec"]}
        self.check_ids = {c["component"]: set(c["check_ids"]) for c in sla["rts_validation"]["classes"]}
        self.restore_target = {p["id"]: p["restore_min"] for p in sla["priorities"]}
        self.engaged_target = {p["id"]: p["engaged_on_site_min"] for p in sla["priorities"]}

        self.rack_power_loss = self._rack_power_loss(source)
        self._index()
        self.tors: dict[str, list[TicketOfRecord]] = {
            "FC-GPU": self._gpu_tickets_of_record(),
            "FC-LINK": self._link_tickets_of_record(),
        }

    # ----------------------------------------------------------- indexes
    def _index(self) -> None:
        self.ticket_by_no = {t["number"]: t for t in self.tickets}
        self.tickets_by_unit: dict[str, list[dict]] = defaultdict(list)
        for t in self.tickets:
            t["_class"] = CATEGORY_TO_CLASS[t["category"]]
            t["_unit"] = self.unit_key(t)
            self.tickets_by_unit[t["_unit"]].append(t)

        self.xid_by_host: dict[str, list[dict]] = defaultdict(list)
        for e in self.xid:
            self.xid_by_host[e["host"]].append(e)
        self.ufm_by_link: dict[str, list[dict]] = defaultdict(list)
        for e in self.ufm:
            self.ufm_by_link[f"{e['switch']}:swp{e['port']}"].append(e)
        self.health_by_target: dict[str, list[dict]] = defaultdict(list)
        for h in self.health:
            self.health_by_target[h["target"]].append(h)
        self.sched_by_node: dict[str, list[dict]] = defaultdict(list)
        for s in self.sched:
            self.sched_by_node[s["node"]].append(s)
        self.badges_by_person: dict[str, list[dict]] = defaultdict(list)
        for b in self.badges:
            self.badges_by_person[b["person_id"]].append(b)
        self.inventory_new_values = {e["new_value"] for e in self.inventory if e["property"] == "SerialNumber"}

    # ------------------------------------------------- ticket -> unit/target
    @staticmethod
    def parse_link(ticket: dict) -> dict | None:
        m = _LINK_RE.search(ticket["short_description"])
        return m.groupdict() if m else None

    def unit_key(self, t: dict) -> str:
        """Service Unit Key for a ticket, per the Measurement Specification."""
        cat = t["category"]
        if cat == "optic_link":
            link = self.parse_link(t)
            return f"{link['switch']}:swp{link['port']}" if link else t["configuration_item"]
        if cat in ("switch_tray", "rack_facility"):
            return t["rack"]
        return t["configuration_item"]

    def validation_target(self, t: dict) -> tuple[str | None, str | None]:
        """(health-check target, validation class) for a ticket."""
        cat, ci = t["category"], t["configuration_item"]
        if cat == "tray_gpu":
            return ci, "Compute tray"
        if cat == "leak":
            return (ci, "Compute tray") if _HOST_RE.match(ci) else (t["rack"], "Rack manifold")
        if cat == "switch_tray":
            return t["rack"], "NVLink switch tray"
        if cat == "rack_facility":
            return t["rack"], "Rack return to service"
        if cat == "optic_link":
            return t["_unit"], "Optic, cable, or fiber"
        if cat == "psu":
            m = _PSU_RE.search(ci)
            return (f"/redfish/v1/Chassis/{m['rack']}_PowerShelf_{m['shelf']}/PowerSubsystem/PowerSupplies/{m['psu']}"
                    if m else None), "Power shelf or PSU"
        if cat == "power_shelf":
            m = _SHELF_RE.search(ci)
            return (f"/redfish/v1/Chassis/{m['rack']}_PowerShelf_{m['shelf']}" if m else None), "Power shelf or PSU"
        if cat == "cdu_pump":
            m = _CDU_RE.search(ci)
            return (m.group(1) if m else None), "CDU component (pump, filter, sensor)"
        return None, None

    def previous_resolution(self, t: dict) -> datetime | None:
        prev = [x["resolved_at"] for x in self.tickets_by_unit[t["_unit"]]
                if x["opened_at"] < t["opened_at"] and x["number"] != t["number"]]
        return max(prev) if prev else None

    def telemetry_t0(self, t: dict) -> tuple[datetime | None, str | None, str | None]:
        """Earliest telemetry fault signal for a ticket, per its fault class T0 rule.

        Searches from the unit's previous resolution (or 12 hours back) to just
        after the ticket opened. Returns (t0, source file, description).
        """
        lower = max(t["opened_at"] - timedelta(hours=12), self.previous_resolution(t) or datetime.min.replace(tzinfo=t["opened_at"].tzinfo))
        upper = t["opened_at"] + timedelta(minutes=5)
        cat, ci, rack = t["category"], t["configuration_item"], t["rack"]
        if cat == "rack_facility":
            loss = next((x for x in self.rack_power_loss if x["rack"] == rack
                         and abs((x["t0"] - t["opened_at"]).total_seconds()) <= 3600), None)
            if loss is None:
                return None, None, None
            if self.attribution:
                return loss["handoff"], "facility/busway_cpm_events.jsonl", f"Landlord handoff: feed restored at the {rack} tap-off (FA-3)"
            return loss["t0"], "facility/busway_cpm_events.jsonl", f"Both {rack} tap-offs open: rack power lost"
        cands: list[tuple[datetime, str, str]] = []
        if cat == "tray_gpu":
            cands = [(e["timestamp"], "telemetry/dcgm_xid_events.jsonl", f"XID {e['xid']} ({e['message']}) on {e['host']}")
                     for e in self.xid_by_host.get(ci, [])]
        elif cat == "optic_link":
            cands = [(e["timestamp"], "telemetry/ufm_port_events.jsonl", f"{e['event']} on {t['_unit']}")
                     for e in self.ufm_by_link.get(t["_unit"], []) if e["event"] in ("link_down", "symbol_error_threshold")]
        elif cat == "leak":
            # Match the exact leak location (Service Unit Key): the tray's chassis, or the rack manifold.
            loc = (f"/redfish/v1/Chassis/{rack}_ComputeTray_{ci.split('-ct')[1]}/" if _HOST_RE.match(ci)
                   else f"/redfish/v1/Chassis/{rack}_RackManifold/")
            cands = [(e["timestamp"], "telemetry/redfish_events.jsonl", e["message"]) for e in self.redfish
                     if e["event_type"] == "LeakDetected" and e["resource"].startswith(loc)]
            cands += [(e["timestamp"], "telemetry/bms_cdu_events.jsonl", f"BMS {e['alarm']} at {e['point']}") for e in self.bms
                      if e["alarm"] == "LeakDetected" and e["state"] == "active" and e["point"].startswith(rack)]
        elif cat == "switch_tray":
            cands = [(e["timestamp"], "telemetry/nmx_events.jsonl", e["message"]) for e in self.nmx
                     if e["rack"] == rack and e["state"] == "failed"]
        elif cat in ("psu", "power_shelf"):
            # Match the exact PSU or shelf slot (Service Unit Key), never just the rack.
            etype = "PowerSupplyFailed" if cat == "psu" else "PowerShelfFailed"
            target, _ = self.validation_target(t)
            cands = [(e["timestamp"], "telemetry/redfish_events.jsonl", e["message"]) for e in self.redfish
                     if e["event_type"] == etype and e["resource"] == target]
        elif cat == "cdu_pump":
            target, _ = self.validation_target(t)
            cands = [(e["timestamp"], "telemetry/bms_cdu_events.jsonl", f"BMS {e['alarm']} on {e['cdu']}") for e in self.bms
                     if e["alarm"] == "PumpRedundancyLost" and e["state"] == "active" and e["cdu"] == target]
        cands = [c for c in cands if lower <= c[0] <= upper]
        return min(cands) if cands else (None, None, None)

    @staticmethod
    def _rack_power_loss(source: SiteDataSource) -> list[dict]:
        """Racks that lost both feeds at the tap-offs (Landlord side of the demarcation), from the busway monitors."""
        try:
            events = source.get("busway_events")
        except FileNotFoundError:
            return []
        open_: dict[str, dict[str, datetime]] = {}
        out = []
        for e in events:
            if "rack" not in e:
                continue
            side = e["busway"][-1]
            feeds = open_.setdefault(e["rack"], {})
            if e["event"] == "Breaker open":
                feeds[side] = e["timestamp"]
                if len(feeds) == 2:
                    out.append({"rack": e["rack"], "t0": e["timestamp"], "handoff": None})
            elif e["event"] == "Breaker closed":
                if len(feeds) == 2 and out and out[-1]["rack"] == e["rack"] and out[-1]["handoff"] is None:
                    out[-1]["handoff"] = e["timestamp"]
                feeds.pop(side, None)
        return [x for x in out if x["handoff"] is not None]

    # ------------------------------------------- telemetry-derived outages
    def _tickets_for(self, unit: str, category: str, start: datetime, end: datetime) -> tuple[str, ...]:
        return tuple(t["number"] for t in self.tickets_by_unit.get(unit, [])
                     if t["category"] == category and start - timedelta(minutes=10) <= t["opened_at"] <= end)

    def _gpu_tickets_of_record(self) -> list[TicketOfRecord]:
        """GPU outages: scheduler drain for an XID reason -> next return to service.
        T0 is the earliest of the drain and the XID that caused it (FC-GPU T0 rule)."""
        outages = []
        for node, states in self.sched_by_node.items():
            drain = None
            for s in states:
                if s["state"] == "drain" and s["reason"].startswith("XID"):
                    drain = s["timestamp"]
                elif s["state"] == "idle" and drain is not None:
                    xids = [e["timestamp"] for e in self.xid_by_host.get(node, [])
                            if drain - timedelta(minutes=10) <= e["timestamp"] <= drain]
                    t0 = min(xids + [drain])
                    outages.append(Outage(node, t0, s["timestamp"],
                                          self._tickets_for(node, "tray_gpu", t0, s["timestamp"])))
                    drain = None
        return build_tickets_of_record(self.sla, "FC-GPU", outages, as_of=self.window_end)

    def _link_tickets_of_record(self) -> list[TicketOfRecord]:
        """Link outages from fabric events. A fault starts on link-down or a symbol-error
        threshold; after a repair, ANY errors inside the stability window count (FC-LINK
        recurrence signal). An outage ends when the next 30-minute soak completes."""
        fc = self.fault_classes["FC-LINK"]
        stability = timedelta(hours=fc["stability_window_hours"])
        outages = []
        for link, events in self.ufm_by_link.items():
            soaks = sorted(h["completed_at"] for h in self.health_by_target.get(link, []) if h["check"] == "link_soak_30m")
            busy_until: datetime | None = None
            last_rts: datetime | None = None
            for e in events:
                if busy_until and e["timestamp"] < busy_until:
                    continue
                fault = e["event"] in ("link_down", "symbol_error_threshold")
                recur = (last_rts is not None and e["timestamp"] - last_rts <= stability
                         and e["event"] in ("link_down", "symbol_errors", "symbol_error_threshold"))
                if not (fault or recur):
                    continue
                i = bisect_left(soaks, e["timestamp"])
                end = soaks[i] if i < len(soaks) else None
                outages.append(Outage(link, e["timestamp"], end,
                                      self._tickets_for(link, "optic_link", e["timestamp"], end or self.window_end)))
                busy_until = end or self.window_end
                last_rts = end
        return build_tickets_of_record(self.sla, "FC-LINK", outages, as_of=self.window_end)
