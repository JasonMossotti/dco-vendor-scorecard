"""Synthetic data generator for a partner-operated GB200 NVL72 site.

The generator simulates one fictional site for a number of weeks and writes two
independent views of the same reality:

* **Telemetry of Record** (what the hardware and Customer systems report):
  GPU XID events, BMC (Redfish-style) alarms and inventory changes, NVLink and
  InfiniBand fabric events, CDU alarms, scheduler node states, validation
  health checks, and badge access.
* **Vendor records** (what the Supplier reports): tickets with work notes and
  parts used, staffing roster, spares ledger, RMA shipments, deployment
  milestones, and the vendor's self-reported weekly summary.

It then plants realistic discrepancies between the two views and writes an
answer key to ``ground_truth/`` so the discrepancy engine's detection rate can
be measured. The engine must never read ``ground_truth/``.

Everything is driven by a seeded RNG: the same seed and dates always produce
byte-identical output. Standard library + PyYAML only, so it also runs in the
browser via Pyodide.
"""

from __future__ import annotations

import csv
import json
import random
import string
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

# --------------------------------------------------------------------------- #
# Static reference data
# --------------------------------------------------------------------------- #
XID_MESSAGES = {
    79: "GPU has fallen off the bus",
    94: "Contained ECC error",
    48: "Double Bit ECC Error",
    119: "Timeout waiting for GSP RPC response",
    145: "NVLink error",
    149: "NVLink error",
}
XID_FAMILY = {79: "bus", 94: "ecc", 48: "ecc", 119: "gsp", 145: "nvlink", 149: "nvlink"}

# Post-repair validation plans: (check name, minutes). Run sequentially.
VALIDATION_PLANS = {
    "tray": [("leak_hold_30m", 30), ("dcgm_diag_r3", 30), ("nvlink_domain", 5),
             ("nccl_allreduce_rack", 10), ("burn_in_1h", 60)],
    "switch_tray": [("leak_hold_30m", 30), ("nmx_tray_health", 10),
                    ("rack_nvlink_acceptance", 20), ("nccl_allreduce_rack", 15)],
    "optic": [("fiber_inspection", 5), ("link_soak_30m", 30)],
    "psu": [("psu_redundancy", 5)],
    "power_shelf": [("psu_redundancy", 10)],
    "cdu": [("cdu_flow_baseline", 20), ("pump_failover_test", 25)],
    "rack_manifold": [("leak_hold_30m", 30), ("rack_nvlink_acceptance", 20),
                      ("nccl_allreduce_rack", 15)],
}

PART_NAMES = {
    "tray": "Compute tray",
    "switch_tray": "NVLink switch tray",
    "optic": "800G OSFP optic",
    "psu": "PSU (5.5 kW)",
    "power_shelf": "Power shelf",
    "cdu": "CDU pump assembly",
    "qd_kit": "Manifold hose and quick-disconnect kit",
}

FIRST_NAMES = ["Alex", "Jordan", "Sam", "Taylor", "Casey", "Morgan", "Riley", "Jamie",
               "Drew", "Avery", "Cameron", "Quinn", "Reese", "Logan", "Hayden", "Parker",
               "Rowan", "Skyler", "Emerson", "Finley", "Dakota", "Kendall", "Marlowe",
               "Sasha", "Blake", "Elliot", "Harper", "Jesse", "Kai", "Lane", "Noel", "Shay"]
LAST_NAMES = ["Rivera", "Chen", "Patel", "Okafor", "Nguyen", "Garcia", "Kowalski", "Haddad",
              "Silva", "Brennan", "Ito", "Mensah", "Larsen", "Duarte", "Novak", "Reyes",
              "Abbott", "Fischer", "Moreau", "Kim", "Osei", "Vargas", "Lindqvist", "Hale",
              "Petrov", "Santos", "Mbeki", "Walsh", "Yamada", "Cruz", "Doyle", "Sato"]


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def minutes(n: float) -> timedelta:
    return timedelta(minutes=n)


# --------------------------------------------------------------------------- #
# Incident model
# --------------------------------------------------------------------------- #
@dataclass
class Incident:
    """One fault and its full lifecycle. Holds the truth and the vendor's view."""

    gt_id: str
    kind: str                     # tray_gpu | optic_link | psu | power_shelf | switch_tray | cdu_pump | leak
    priority: str
    hall: str
    rack: str
    t0: datetime                  # Fault Detection Time (truth)
    host: str | None = None       # Compute tray host, if any
    unit_label: str = ""          # Human-readable affected unit
    gpus_affected: int = 0
    nodes_affected: list[str] = field(default_factory=list)
    xid: int | None = None
    link: dict[str, Any] | None = None
    psu_path: str | None = None
    cdu: str | None = None
    leak_scope: str | None = None  # tray | rack

    # Repair decisions
    swap: bool = False            # A part was physically replaced
    part_key: str | None = None   # Key into PART_NAMES
    optic_side: str | None = None  # switch | host
    extra_parts: list[str] = field(default_factory=list)

    # True timeline
    ticket_opened: datetime | None = None
    acknowledged: datetime | None = None
    engaged: datetime | None = None
    contained: datetime | None = None
    swap_time: datetime | None = None
    repair_done: datetime | None = None
    rts: datetime | None = None
    resolved: datetime | None = None
    validation_plan: str | None = None

    # Vendor-view overrides (used by planted discrepancies)
    engaged_claimed: datetime | None = None
    vendor_claims_swap: bool | None = None
    emit_inventory_change: bool = True
    emit_validation: bool = True
    log_spares_issue: bool = True
    rma_escalation_note: bool = False
    continue_errors_until: datetime | None = None

    # Assignment and identity
    tech_id: str | None = None
    ticket_number: str | None = None
    removed_serial: str | None = None
    installed_serial: str | None = None
    parent_gt_id: str | None = None
    anomalies: list[str] = field(default_factory=list)

    def target_restore_min(self, sla: dict) -> int:
        return next(p for p in sla["priorities"] if p["id"] == self.priority)["restore_min"]


# --------------------------------------------------------------------------- #
# Generator
# --------------------------------------------------------------------------- #
class SiteGenerator:
    def __init__(self, sla: dict, config: dict, start: date, weeks: int | None = None,
                 seed: int | None = None):
        self.sla = sla
        self.cfg = config
        self.seed = config["seed"] if seed is None else seed
        self.weeks = config["weeks"] if weeks is None else weeks
        self.rng = random.Random(self.seed)
        if start.weekday() != 0:
            raise ValueError("start must be a Monday (ISO week start)")
        self.start = datetime.combine(start, time(0, 0), tzinfo=UTC)
        self.end = self.start + timedelta(weeks=self.weeks)
        self.utc_offset = timedelta(hours=config.get("site_utc_offset_hours", 0))
        self._serials: set[str] = set()
        self._gt_counter = 0
        self.incidents: list[Incident] = []
        self.planted: list[dict] = []
        self._used_hosts: set[str] = set()

    # ----------------------------------------------------------------- utils
    def _serial(self, prefix: str) -> str:
        while True:
            s = prefix + "".join(self.rng.choices(string.ascii_uppercase + string.digits, k=8))
            if s not in self._serials:
                self._serials.add(s)
                return s

    def _next_gt(self) -> str:
        self._gt_counter += 1
        return f"GT-{self._gt_counter:04d}"

    def _u(self, lo: float, hi: float) -> float:
        return self.rng.uniform(lo, hi)

    def _poisson(self, lam: float) -> int:
        # Knuth's algorithm; fine for the small rates used here.
        limit, k, p = pow(2.718281828459045, -lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= limit:
                return k
            k += 1

    def _restore_target(self, priority: str) -> int:
        return next(p for p in self.sla["priorities"] if p["id"] == priority)["restore_min"]

    def _engaged_target(self, priority: str) -> int | None:
        return next(p for p in self.sla["priorities"] if p["id"] == priority)["engaged_on_site_min"]

    # -------------------------------------------------------------- topology
    def build_topology(self) -> None:
        site = self.sla["site"]
        per = site["per_rack"]
        racks_per_cdu = site["cooling"]["racks_per_cdu"]
        self.racks: list[dict] = []
        self.tray_serial: dict[str, str] = {}      # host -> current true serial
        self.tray_firmware: dict[str, str] = {}
        for hall in site["halls"]:
            letter = hall["id"][-1]
            for i in range(1, hall["racks"] + 1):
                rid = f"{letter}{i:02d}"
                rack = {
                    "rack": rid,
                    "hall": hall["id"],
                    "index": i,
                    "state": hall["state"],
                    "cdu": f"CDU-{letter}{(i - 1) // racks_per_cdu + 1}",
                    "compute_trays": [],
                    "switch_trays": [],
                    "power_shelves": [],
                }
                for s in range(1, per["compute_trays"] + 1):
                    host = f"{rid.lower()}-ct{s:02d}"
                    serial = self._serial("CT")
                    rack["compute_trays"].append({
                        "slot": s, "host": host, "serial": serial, "firmware": "1.3.6",
                        "redfish": f"/redfish/v1/Chassis/{rid}_ComputeTray_{s:02d}",
                    })
                    self.tray_serial[host] = serial
                    self.tray_firmware[host] = "1.3.6"
                for s in range(1, per["nvlink_switch_trays"] + 1):
                    rack["switch_trays"].append({
                        "slot": s, "name": f"{rid.lower()}-nvsw{s}", "serial": self._serial("NS"),
                        "redfish": f"/redfish/v1/Chassis/{rid}_SwitchTray_{s}",
                    })
                for s in range(1, per["power_shelves"] + 1):
                    rack["power_shelves"].append({
                        "slot": s, "serial": self._serial("PS"),
                        "redfish": f"/redfish/v1/Chassis/{rid}_PowerShelf_{s}",
                    })
                self.racks.append(rack)
        self.rack_by_id = {r["rack"]: r for r in self.racks}
        self.prod_racks = [r for r in self.racks if r["state"] == "production"]

    @staticmethod
    def link_for(rack: dict, slot: int, rail: int) -> dict:
        """Deterministic rail-optimized cabling: host NIC <-> leaf switch port."""
        letter = rack["rack"][0].lower()
        leaf_group = (rack["index"] - 1) // 2 + 1
        return {
            "host": f"{rack['rack'].lower()}-ct{slot:02d}",
            "hca": f"mlx5_{rail}",
            "switch": f"leaf-{letter}{leaf_group:02d}-r{rail}",
            "port": ((rack["index"] - 1) % 2) * 18 + slot,
        }

    # -------------------------------------------------------------- staffing
    def _local(self, dt: datetime) -> datetime:
        return dt + self.utc_offset

    def _shift_of(self, dt: datetime) -> tuple[date, str]:
        local = self._local(dt)
        if 7 <= local.hour < 19:
            return local.date(), "day"
        if local.hour >= 19:
            return local.date(), "night"
        return local.date() - timedelta(days=1), "night"

    def _shift_bounds(self, shift_date: date, shift: str) -> tuple[datetime, datetime]:
        start_local = datetime.combine(shift_date, time(7 if shift == "day" else 19), tzinfo=UTC)
        start = start_local - self.utc_offset
        return start, start + timedelta(hours=12)

    def _crew_for(self, shift_date: date, shift: str) -> str:
        day_index = (shift_date - self._local(self.start).date()).days
        rot = (day_index // 4) % 2  # 4 on / 4 off
        return f"{'D' if shift == 'day' else 'N'}{rot + 1}"

    def build_staffing(self) -> None:
        names = [(f, l) for f in FIRST_NAMES for l in LAST_NAMES]
        self.rng.shuffle(names)
        committed = {s["shift"].split()[0].lower(): s for s in self.sla["staffing"]["committed_per_shift"]}
        self.personnel: list[dict] = []
        pid = 0
        for crew in ("D1", "D2", "N1", "N2"):
            spec = committed["day" if crew[0] == "D" else "night"]
            roles = ["shift_lead"] * spec["shift_leads"] + ["technician"] * spec["technicians"]
            for role in roles:
                pid += 1
                first, last = names[pid]
                self.personnel.append({
                    "person_id": f"RSS-{pid:03d}",
                    "name": f"{first} {last}",
                    "role": role,
                    "crew": crew,
                    "badge_id": f"B{40000 + pid * 7}",
                    "company": self.sla["parties"]["supplier"]["name"],
                })
        self.by_crew: dict[str, list[dict]] = {}
        for p in self.personnel:
            self.by_crew.setdefault(p["crew"], []).append(p)

        # Shifts overlapping the window.
        self.shifts: list[tuple[date, str]] = []
        d = self._local(self.start).date() - timedelta(days=1)
        last = self._local(self.end).date()
        while d <= last:
            for shift in ("day", "night"):
                s, e = self._shift_bounds(d, shift)
                if e > self.start and s < self.end:
                    self.shifts.append((d, shift))
            d += timedelta(days=1)

        # Planted: staffing gaps (2 rostered techs never badge in).
        self.absent: set[tuple[date, str, str]] = set()
        n_gaps = self.cfg["anomalies"].get("staffing_gap", 0)
        candidates = [s for s in self.shifts if self._shift_bounds(*s)[0] >= self.start
                      and self._shift_bounds(*s)[1] <= self.end]
        for shift_date, shift in self.rng.sample(candidates, k=min(n_gaps, len(candidates))):
            crew = self._crew_for(shift_date, shift)
            techs = [p for p in self.by_crew[crew] if p["role"] == "technician"]
            missing = self.rng.sample(techs, 2)
            for p in missing:
                self.absent.add((shift_date, shift, p["person_id"]))
            s, e = self._shift_bounds(shift_date, shift)
            self.planted.append({
                "type": "staffing_gap",
                "shift_date": shift_date.isoformat(), "shift": shift, "crew": crew,
                "shift_start": iso(s), "shift_end": iso(e),
                "missing_person_ids": sorted(p["person_id"] for p in missing),
                "evidence": "Vendor roster lists these technicians as on shift; access control has no badge-in for them.",
                "detect_with": ["vendor/roster.csv", "access/badge_events.csv"],
                "sla_refs": ["CSL-10"],
            })

    def on_duty_techs(self, dt: datetime) -> list[dict]:
        shift_date, shift = self._shift_of(dt)
        crew = self._crew_for(shift_date, shift)
        return [p for p in self.by_crew[crew] if p["role"] == "technician"
                and (shift_date, shift, p["person_id"]) not in self.absent]

    # ------------------------------------------------------------ incidents
    def _random_tray(self, racks: list[dict] | None = None) -> tuple[dict, dict]:
        """Pick a tray not yet used by another incident, so every repeat failure in
        the dataset is deliberate (planted) and the answer key stays unambiguous."""
        for _ in range(100):
            rack = self.rng.choice(racks or self.prod_racks)
            tray = self.rng.choice(rack["compute_trays"])
            if tray["host"] not in self._used_hosts:
                break
        self._used_hosts.add(tray["host"])
        return rack, tray

    def _random_t0(self, earliest: datetime | None = None, latest_margin_h: float = 36) -> datetime:
        lo = (earliest or self.start + timedelta(hours=2)).timestamp()
        hi = (self.end - timedelta(hours=latest_margin_h)).timestamp()
        return datetime.fromtimestamp(self.rng.uniform(lo, hi), tz=UTC).replace(microsecond=0)

    def make_incident(self, kind: str, t0: datetime | None = None, rack: dict | None = None,
                      tray: dict | None = None, **overrides: Any) -> Incident:
        t0 = t0 or self._random_t0()
        vb = self.cfg["vendor_behavior"]
        if kind in ("tray_gpu", "optic_link") or (kind == "leak"):
            if tray is None:
                rack, tray = self._random_tray([rack] if rack else None)
        rack = rack or self.rng.choice(self.prod_racks)
        inc = Incident(gt_id=self._next_gt(), kind=kind, priority="P2", hall=rack["hall"],
                       rack=rack["rack"], t0=t0)

        if kind == "tray_gpu":
            xids, weights = zip(*self.cfg["xid_mix"].items())
            inc.xid = int(self.rng.choices(xids, weights=weights)[0])
            inc.host = tray["host"]
            inc.unit_label = f"Compute tray {tray['host']}"
            inc.gpus_affected = self.sla["site"]["per_rack"]["gpus_per_compute_tray"]
            inc.nodes_affected = [tray["host"]]
            inc.swap = self.rng.random() < vb["tray_swap_probability"]
            inc.part_key = "tray" if inc.swap else None
            inc.validation_plan = "tray"
        elif kind == "optic_link":
            rail = self.rng.randrange(4)
            inc.link = self.link_for(rack, tray["slot"], rail)
            inc.host = tray["host"]
            inc.priority = "P2" if self.rng.random() < 0.7 else "P3"
            inc.unit_label = f"Link {inc.link['host']}:{inc.link['hca']} <-> {inc.link['switch']}:swp{inc.link['port']}"
            if inc.priority == "P2":
                inc.gpus_affected = 4
                inc.nodes_affected = [tray["host"]]
            inc.swap = self.rng.random() < vb["optic_replace_probability"]
            inc.part_key = "optic" if inc.swap else None
            inc.optic_side = self.rng.choice(["switch", "host"]) if inc.swap else None
            inc.validation_plan = "optic"
        elif kind == "psu":
            shelf = self.rng.choice(rack["power_shelves"])
            psu = self.rng.randint(1, 6)
            inc.priority = "P3"
            inc.psu_path = f"{shelf['redfish']}/PowerSubsystem/PowerSupplies/{psu}"
            inc.unit_label = f"PSU {psu} in {rack['rack']} power shelf {shelf['slot']}"
            inc.swap, inc.part_key, inc.validation_plan = True, "psu", "psu"
        elif kind == "power_shelf":
            shelf = self.rng.choice(rack["power_shelves"])
            inc.priority = "P2"
            inc.psu_path = shelf["redfish"]
            inc.unit_label = f"{rack['rack']} power shelf {shelf['slot']}"
            inc.swap, inc.part_key, inc.validation_plan = True, "power_shelf", "power_shelf"
        elif kind == "switch_tray":
            st = self.rng.choice(rack["switch_trays"])
            inc.priority = "P1"
            inc.unit_label = f"NVLink switch tray {st['name']}"
            inc.psu_path = st["redfish"]
            inc.gpus_affected = self.sla["site"]["per_rack"]["gpus"]
            inc.nodes_affected = [t["host"] for t in rack["compute_trays"]]
            inc.swap, inc.part_key, inc.validation_plan = True, "switch_tray", "switch_tray"
        elif kind == "cdu_pump":
            inc.priority = "P2"
            inc.cdu = rack["cdu"]
            inc.unit_label = f"{rack['cdu']} pump {self.rng.choice([1, 2])}"
            inc.swap, inc.part_key, inc.validation_plan = True, "cdu", "cdu"
        elif kind == "leak":
            inc.priority = "P1"
            inc.cdu = rack["cdu"]
            inc.leak_scope = "tray" if self.rng.random() < 0.8 else "rack"
            if inc.leak_scope == "tray":
                inc.host = tray["host"]
                inc.unit_label = f"Leak at compute tray {tray['host']}"
                inc.gpus_affected = 4
                inc.nodes_affected = [tray["host"]]
                inc.swap = self.rng.random() < 0.5
                inc.part_key = "tray" if inc.swap else None
                inc.extra_parts = ["qd_kit"]
                inc.validation_plan = "tray"
            else:
                inc.unit_label = f"Leak at {rack['rack']} rack manifold"
                inc.gpus_affected = self.sla["site"]["per_rack"]["gpus"]
                inc.nodes_affected = [t["host"] for t in rack["compute_trays"]]
                inc.extra_parts = ["qd_kit"]
                inc.validation_plan = "rack_manifold"
        else:
            raise ValueError(kind)

        for k, v in overrides.items():
            setattr(inc, k, v)
        self.schedule(inc)
        self.incidents.append(inc)
        return inc

    def _repair_minutes(self, inc: Incident) -> float:
        k = inc.kind
        if k == "tray_gpu":
            return self._u(50, 110) if inc.swap else self._u(25, 50)
        if k == "optic_link":
            return self._u(15, 45)
        if k == "psu":
            return self._u(10, 25)
        if k == "power_shelf":
            return self._u(25, 50)
        if k == "switch_tray":
            return self._u(80, 130)
        if k == "cdu_pump":
            return self._u(90, 200)
        if k == "leak":
            return self._u(60, 110) if inc.leak_scope == "tray" else self._u(90, 150)
        raise ValueError(k)

    def _validation_minutes(self, inc: Incident) -> int:
        return sum(m for _, m in VALIDATION_PLANS[inc.validation_plan])

    def schedule(self, inc: Incident, engaged_delay: float | None = None,
                 ticket_delay: float | None = None, extra_delay: float | None = None) -> None:
        """Compute an honest timeline for the incident (anomalies may adjust it later)."""
        vb = self.cfg["vendor_behavior"]
        inc.ticket_opened = inc.t0 + minutes(ticket_delay if ticket_delay is not None else self._u(1, 6))
        ack_rng = {"P1": (1, 4), "P2": (3, 12), "P3": (10, 50), "P4": (30, 200)}[inc.priority]
        inc.acknowledged = inc.ticket_opened + minutes(self._u(*ack_rng))
        if engaged_delay is None:
            late = self.rng.random() < vb["late_engagement_probability"]
            normal, slow = {"P1": ((5, 13), (17, 32)), "P2": ((10, 27), (33, 60)),
                            "P3": ((30, 180), (250, 400))}[inc.priority]
            engaged_delay = self._u(*(slow if late else normal))
        inc.engaged = max(inc.t0 + minutes(engaged_delay), inc.acknowledged + minutes(1))
        if inc.priority == "P1" and inc.kind == "leak":
            inc.contained = inc.engaged + minutes(self._u(10, 35))
        repair = self._repair_minutes(inc)
        if extra_delay is not None:
            repair += extra_delay
        elif self.rng.random() < vb["hard_fault_probability"]:
            repair += self._u(30, 120) if inc.priority == "P1" else self._u(120, 420)
        inc.repair_done = inc.engaged + minutes(repair)
        inc.swap_time = inc.engaged + minutes(repair * 0.6) if inc.swap else None
        inc.rts = inc.repair_done + minutes(self._validation_minutes(inc))
        inc.resolved = inc.rts + minutes(self._u(0, 8))
        inc.engaged_claimed = inc.engaged

    def generate_base_incidents(self) -> None:
        for kind, rate in self.cfg["incident_rates_per_week"].items():
            for _ in range(self._poisson(rate * self.weeks)):
                self.make_incident(kind)

    # ------------------------------------------------------------- anomalies
    def _pick(self, pred, earliest: datetime | None = None, latest: datetime | None = None) -> Incident | None:
        pool = [i for i in self.incidents if not i.anomalies and i.parent_gt_id is None and pred(i)
                and (earliest is None or i.t0 >= earliest) and (latest is None or i.t0 <= latest)]
        return self.rng.choice(pool) if pool else None

    def _plant(self, inc: Incident | None, kind: str, evidence: str, detect_with: list[str],
               sla_refs: list[str], **extra: Any) -> None:
        record = {"type": kind, "evidence": evidence, "detect_with": detect_with, "sla_refs": sla_refs, **extra}
        if inc is not None:
            inc.anomalies.append(kind)
            record.update({"gt_id": inc.gt_id, "unit": inc.unit_label})
        self.planted.append(record)

    def plant_anomalies(self) -> None:
        a = self.cfg["anomalies"]
        late_cut = self.end - timedelta(days=6)
        is_tray = lambda i: i.kind == "tray_gpu"  # noqa: E731

        # Lemon unit: one tray fails 3 times within ~3 weeks; reseated each time; no RMA escalation.
        for _ in range(a.get("lemon_unit", 0) if self.weeks >= 3 else 0):
            rack, tray = self._random_tray()
            t = self.start + timedelta(hours=self._u(10, 60))
            chain = []
            for xid in self.rng.sample(sorted({79, 119, 94, 145}), 3):
                inc = self.make_incident("tray_gpu", t0=t, rack=rack, tray=tray,
                                         xid=xid, swap=False, part_key=None)
                self.schedule(inc)
                chain.append(inc)
                t = inc.rts + timedelta(days=self._u(4, 8))
                if t > self.end - timedelta(hours=40):
                    break
            for inc in chain:
                inc.anomalies.append("lemon_unit")
                inc.parent_gt_id = chain[0].gt_id if inc is not chain[0] else None
            self.planted.append({
                "type": "lemon_unit", "unit": f"Compute tray {tray['host']}",
                "gt_ids": [i.gt_id for i in chain],
                "evidence": f"{len(chain)} repair events on one tray within 30 days; every ticket closed as reseated with no RMA escalation.",
                "detect_with": ["telemetry/dcgm_xid_events.jsonl", "vendor/tickets.json"],
                "sla_refs": ["KM-09", "CSL-08"],
            })

        # Phantom fix: tray reseated; the same fault family recurs after the stability
        # window but within the recurrence window (TR-5 linked recurrence).
        gpu_fc = next(f for f in self.sla["measurement_spec"] if f["id"] == "FC-GPU")
        stab_h = gpu_fc["stability_window_hours"]
        for _ in range(a.get("phantom_fix", 0)):
            inc = self._pick(is_tray, latest=self.end - timedelta(days=8))
            if not inc:
                break
            inc.swap, inc.part_key = False, None
            self.schedule(inc)
            gap_h = self._u(stab_h + 6, stab_h + 76)
            family = XID_FAMILY[inc.xid]
            same_family = [x for x, f in XID_FAMILY.items() if f == family]
            rack = self.rack_by_id[inc.rack]
            tray = next(t for t in rack["compute_trays"] if t["host"] == inc.host)
            child = self.make_incident("tray_gpu", t0=inc.rts + timedelta(hours=gap_h), rack=rack,
                                       tray=tray, xid=self.rng.choice(same_family), swap=True, part_key="tray")
            self.schedule(child)
            child.parent_gt_id = inc.gt_id
            self._plant(inc, "phantom_fix",
                        f"Ticket closed as resolved (reseat); same {family} fault recurred on {inc.host} "
                        f"{gap_h:.0f} hours after return to service, inside the {gpu_fc['recurrence_window_days']}-day "
                        "recurrence window (TR-5): a First-Time Fix failure.",
                        ["telemetry/dcgm_xid_events.jsonl", "vendor/tickets.json"], ["CSL-06", "CSL-08"],
                        recurrence_gt_id=child.gt_id)

        # Unverified swap: ticket claims new serial; BMC inventory never changes.
        for _ in range(a.get("unverified_swap", 0)):
            inc = self._pick(lambda i: is_tray(i) and i.swap)
            if not inc:
                break
            inc.emit_inventory_change = False
            self._plant(inc, "unverified_swap",
                        "Ticket parts record claims a tray replacement with a new serial number; "
                        "BMC inventory shows no serial change for that slot.",
                        ["vendor/tickets.json", "telemetry/redfish_inventory_changes.jsonl"], ["CSL-11"])

        # Skipped validation: returned to service minutes after repair, no validation records.
        for _ in range(a.get("skipped_validation", 0)):
            inc = self._pick(lambda i: is_tray(i))
            if not inc:
                break
            inc.emit_validation = False
            inc.rts = inc.repair_done + minutes(self._u(4, 12))
            inc.resolved = inc.rts + minutes(self._u(0, 5))
            self._plant(inc, "skipped_validation",
                        "Node returned to the scheduler with no validation health checks recorded; "
                        "ticket notes still claim validation passed.",
                        ["telemetry/health_checks.jsonl", "telemetry/scheduler_node_states.jsonl",
                         "vendor/tickets.json"], ["CSL-07", "CSL-11"])

        # Clock shift: ticket opened ~2 hours late, hiding a restore breach.
        for _ in range(a.get("clock_shift", 0)):
            inc = self._pick(lambda i: is_tray(i) and i.priority == "P2", latest=late_cut)
            if not inc:
                break
            target = inc.target_restore_min(self.sla)
            open_delay = self._u(100, 140)
            # Late by T0, but on time when measured from the (late) ticket open.
            true_total = target + self._u(40, open_delay - 15)
            self.schedule(inc, ticket_delay=open_delay, engaged_delay=open_delay + self._u(12, 20), extra_delay=0)
            filler = true_total - (inc.rts - inc.t0).total_seconds() / 60
            inc.repair_done += minutes(filler)
            if inc.swap_time:
                inc.swap_time += minutes(filler * 0.6)
            inc.rts += minutes(filler)
            inc.resolved = inc.rts + minutes(self._u(0, 5))
            self._plant(inc, "clock_shift",
                        f"GPU telemetry shows the fault {open_delay:.0f} minutes before the ticket was opened. "
                        f"Measured from ticket open the repair met the {target // 60}-hour target; "
                        f"measured from T0 it took {true_total / 60:.1f} hours.",
                        ["telemetry/dcgm_xid_events.jsonl", "telemetry/scheduler_node_states.jsonl",
                         "vendor/tickets.json"], ["CSL-04", "CSL-11"])

        # Ticket split: tray refaults minutes after RTS; vendor opens a new ticket so the
        # clock restarts. Each ticket looks on time; under TR-1 the restore is continuous.
        early = self.sla["ticket_handling"]["stability"]["early_failure_minutes"]
        for _ in range(a.get("ticket_split", 0)):
            inc = self._pick(lambda i: is_tray(i) and i.priority == "P2", latest=late_cut)
            if not inc:
                break
            target = inc.target_restore_min(self.sla)
            self.schedule(inc, extra_delay=0)
            filler = (target - self._u(40, 100)) - (inc.rts - inc.t0).total_seconds() / 60
            inc.repair_done += minutes(filler)
            if inc.swap_time:
                inc.swap_time += minutes(filler * 0.6)
            inc.rts += minutes(filler)
            inc.resolved = inc.rts + minutes(self._u(0, 5))
            gap = self._u(8, early - 15)
            rack = self.rack_by_id[inc.rack]
            tray = next(t for t in rack["compute_trays"] if t["host"] == inc.host)
            child = self.make_incident("tray_gpu", t0=inc.rts + minutes(gap), rack=rack, tray=tray,
                                       xid=inc.xid, swap=False, part_key=None)
            self.schedule(child, extra_delay=0)
            child.parent_gt_id = inc.gt_id
            first_h = (inc.rts - inc.t0).total_seconds() / 3600
            second_h = (child.rts - child.t0).total_seconds() / 3600
            combined_h = (child.rts - inc.t0).total_seconds() / 3600
            self._plant(inc, "ticket_split",
                        f"Tray faulted again {gap:.0f} minutes after return to service and the vendor opened a new "
                        f"ticket, restarting the clock. Separately the tickets look on time ({first_h:.1f} and "
                        f"{second_h:.1f} hours); under TR-1 the restore is continuous: {combined_h:.1f} hours "
                        f"against the {target // 60}-hour target.",
                        ["telemetry/dcgm_xid_events.jsonl", "telemetry/scheduler_node_states.jsonl",
                         "vendor/tickets.json"], ["TR-1", "TR-6", "CSL-04", "CSL-11"],
                        recurrence_gt_id=child.gt_id)

        # Ghost engagement: "on site" note before the tech actually badged into the hall.
        for _ in range(a.get("ghost_engagement", 0)):
            inc = self._pick(lambda i: i.priority in ("P1", "P2") and i.kind in ("tray_gpu", "optic_link"))
            if not inc:
                break
            target = self._engaged_target(inc.priority)
            claimed = inc.t0 + minutes(target - self._u(1, 5))
            # Badge-in lands at least 20 minutes after the claim: beyond the SLA's
            # 15-minute record-integrity tolerance, so it is a real discrepancy.
            self.schedule(inc, engaged_delay=target + self._u(22, 45))
            inc.engaged_claimed = max(claimed, inc.acknowledged + minutes(1))
            self._plant(inc, "ghost_engagement",
                        f"Ticket work note claims technician on site within the {target}-minute target; "
                        "the assigned technician's first badge-in to the hall came later.",
                        ["vendor/tickets.json", "access/badge_events.csv"], ["CSL-02" if inc.priority == "P1" else "KM-01", "CSL-11"])

        # Wrong-end optic: switch-side optic replaced, errors continue; host side replaced later.
        for _ in range(a.get("wrong_end_optic", 0)):
            inc = self._pick(lambda i: i.kind == "optic_link", latest=late_cut)
            if not inc:
                break
            inc.swap, inc.part_key, inc.optic_side = True, "optic", "switch"
            self.schedule(inc)
            gap_h = self._u(4, 30)
            rack = self.rack_by_id[inc.rack]
            tray = next(t for t in rack["compute_trays"] if t["host"] == inc.host)
            child = self.make_incident("optic_link", t0=inc.rts + timedelta(hours=gap_h), rack=rack, tray=tray,
                                       link=inc.link, unit_label=inc.unit_label, priority="P3",
                                       swap=True, part_key="optic", optic_side="host",
                                       gpus_affected=0, nodes_affected=[])
            self.schedule(child)
            child.parent_gt_id = inc.gt_id
            inc.continue_errors_until = child.repair_done
            self._plant(inc, "wrong_end_optic",
                        "Switch-side optic replaced and ticket closed; symbol errors on the same link continued "
                        f"until the host-side optic was replaced {gap_h:.0f}+ hours later ({child.gt_id}).",
                        ["telemetry/ufm_port_events.jsonl", "vendor/tickets.json"], ["CSL-06", "CSL-08"],
                        recurrence_gt_id=child.gt_id)

        # Spares drift: a tray swap never issued from the spares ledger.
        for _ in range(a.get("spares_drift", 0)):
            inc = self._pick(lambda i: is_tray(i) and i.swap)
            if not inc:
                break
            inc.log_spares_issue = False
            self._plant(inc, "spares_drift",
                        "Tray replaced (ticket and BMC inventory agree) but no matching issue in the spares "
                        "ledger; the next cycle count is one tray short of the ledger balance.",
                        ["vendor/tickets.json", "vendor/spares_ledger.csv", "vendor/spares_cycle_counts.csv"],
                        ["KM-06", "KM-07", "CSL-11"])

    # ------------------------------------------------------------ deployment
    def build_deployment(self) -> None:
        dcfg = self.cfg["deployment"]
        hall_b = [r for r in self.racks if r["state"] == "deployment"]
        ms = self.sla["deployment"]["milestones"]
        cycle = self.sla["deployment"]["rack_cycle_target_days"]
        self.deploy_plan, self.deploy_events = [], []
        first = self._local(self.start).date() + timedelta(days=1)
        for i, rack in enumerate(hall_b):
            receipt_local = datetime.combine(first + timedelta(days=int(i * 1.4)), time(8), tzinfo=UTC)
            receipt = receipt_local - self.utc_offset
            committed = receipt + timedelta(days=cycle)
            self.deploy_plan.append({"rack": rack["rack"], "hall": rack["hall"],
                                     "planned_receipt": iso(receipt), "committed_handoff": iso(committed)})
            if i >= dcfg["racks_received_in_window"]:
                continue
            late = self.rng.random() < dcfg["late_probability"]
            slip = timedelta(days=self._u(*dcfg["late_days"])) if late else timedelta(0)
            for m in ms:
                when = receipt + timedelta(days=m["target_days_from_receipt"]) - timedelta(hours=self._u(2, 20))
                if m["id"] in ("M5", "M6", "M7"):
                    when += slip
                if m["id"] == "M1":
                    when = receipt + timedelta(hours=self._u(2, 8))
                rack.setdefault("milestones", {})[m["id"]] = when
                self.deploy_events.append({"rack": rack["rack"], "milestone": m["id"], "name": m["name"],
                                           "completed_at": when})

    # --------------------------------------------------------------- assign
    def finalize(self) -> None:
        self.incidents.sort(key=lambda i: i.t0)
        for n, inc in enumerate(self.incidents, start=1):
            inc.ticket_number = f"INC{3_100_000 + n * 17:07d}"
        # Assign technicians. Planted ghost engagements go last, to a technician with
        # no other job within 3 hours, so no unrelated hall badge-in blurs the evidence.
        ordered = [i for i in self.incidents if "ghost_engagement" not in i.anomalies] + \
                  [i for i in self.incidents if "ghost_engagement" in i.anomalies]
        busy: dict[str, list[datetime]] = {}
        for inc in ordered:
            techs = self.on_duty_techs(inc.engaged)
            if "ghost_engagement" in inc.anomalies:
                free = [p for p in techs if all(abs((inc.engaged - t).total_seconds()) > 3 * 3600
                                                for t in busy.get(p["person_id"], []))]
                techs = free or techs
            inc.tech_id = self.rng.choice(techs)["person_id"]
            busy.setdefault(inc.tech_id, []).append(inc.engaged)

    # ================================================================ emit
    def emit(self) -> dict[str, list]:
        out: dict[str, list] = {k: [] for k in (
            "xid", "redfish_events", "inventory", "nmx", "ufm", "bms", "health", "scheduler",
            "badge", "tickets", "spares_ledger", "cycle_counts", "rma", "cab", "gt_incidents")}
        person = {p["person_id"]: p for p in self.personnel}

        def sched(node: str, at: datetime, state: str, reason: str) -> None:
            out["scheduler"].append({"timestamp": iso(at), "node": node, "state": state, "reason": reason})

        def health(target: str, plan: str, start: datetime) -> None:
            t = start
            for check, dur in VALIDATION_PLANS[plan]:
                out["health"].append({"started_at": iso(t), "completed_at": iso(t + minutes(dur)),
                                      "target": target, "check": check, "result": "pass"})
                t += minutes(dur)

        for inc in self.incidents:
            rack = self.rack_by_id[inc.rack]
            tech = person[inc.tech_id]
            hall_door = f"HALL-{inc.hall[-1]}"
            claims_swap = inc.swap if inc.vendor_claims_swap is None else inc.vendor_claims_swap
            # ---------------- telemetry: fault signal at T0
            if inc.kind == "tray_gpu":
                gpu = self.rng.randrange(4)
                out["xid"].append({"timestamp": iso(inc.t0), "host": inc.host, "gpu_index": gpu,
                                   "tray_serial": self.tray_serial[inc.host], "xid": inc.xid,
                                   "message": XID_MESSAGES[inc.xid]})
            elif inc.kind == "optic_link":
                L = inc.link
                if inc.priority == "P3":
                    for k in range(4, 0, -1):
                        out["ufm"].append({"timestamp": iso(inc.t0 - timedelta(hours=k * 1.5)),
                                           "switch": L["switch"], "port": L["port"], "peer_host": L["host"],
                                           "peer_hca": L["hca"], "event": "symbol_errors",
                                           "count": int(self._u(50, 400) * (5 - k))})
                    out["ufm"].append({"timestamp": iso(inc.t0), "switch": L["switch"], "port": L["port"],
                                       "peer_host": L["host"], "peer_hca": L["hca"],
                                       "event": "symbol_error_threshold", "count": int(self._u(2000, 6000))})
                else:
                    t = inc.t0
                    for _ in range(self.rng.randint(2, 4)):
                        out["ufm"].append({"timestamp": iso(t), "switch": L["switch"], "port": L["port"],
                                           "peer_host": L["host"], "peer_hca": L["hca"], "event": "link_down", "count": 1})
                        t += minutes(self._u(0.5, 3))
                        out["ufm"].append({"timestamp": iso(t), "switch": L["switch"], "port": L["port"],
                                           "peer_host": L["host"], "peer_hca": L["hca"], "event": "link_up", "count": 1})
                        t += minutes(self._u(2, 8))
                if inc.continue_errors_until:
                    t = inc.rts + minutes(self._u(20, 90))
                    while t < inc.continue_errors_until:
                        out["ufm"].append({"timestamp": iso(t), "switch": L["switch"], "port": L["port"],
                                           "peer_host": L["host"], "peer_hca": L["hca"], "event": "symbol_errors",
                                           "count": int(self._u(80, 900))})
                        t += timedelta(hours=self._u(1, 3))
            elif inc.kind in ("psu", "power_shelf"):
                out["redfish_events"].append({"timestamp": iso(inc.t0), "resource": inc.psu_path, "rack": inc.rack,
                                              "event_type": "PowerSupplyFailed" if inc.kind == "psu" else "PowerShelfFailed",
                                              "severity": "Warning" if inc.kind == "psu" else "Critical",
                                              "message": f"{inc.unit_label} reported failure"})
                out["redfish_events"].append({"timestamp": iso(inc.repair_done), "resource": inc.psu_path, "rack": inc.rack,
                                              "event_type": "PowerRedundancyRestored", "severity": "OK",
                                              "message": "Redundancy restored"})
            elif inc.kind == "switch_tray":
                out["nmx"].append({"timestamp": iso(inc.t0), "rack": inc.rack, "unit": inc.unit_label,
                                   "state": "failed", "message": "NVLink switch tray unreachable; NVLink domain degraded"})
                out["nmx"].append({"timestamp": iso(inc.repair_done + minutes(30)), "rack": inc.rack,
                                   "unit": inc.unit_label, "state": "healthy", "message": "NVLink domain healthy"})
            elif inc.kind == "cdu_pump":
                out["bms"].append({"timestamp": iso(inc.t0), "cdu": inc.cdu, "point": inc.unit_label,
                                   "alarm": "PumpRedundancyLost", "state": "active"})
                out["bms"].append({"timestamp": iso(inc.repair_done), "cdu": inc.cdu, "point": inc.unit_label,
                                   "alarm": "PumpRedundancyLost", "state": "cleared"})
            elif inc.kind == "leak":
                resource = (next(t for t in rack["compute_trays"] if t["host"] == inc.host)["redfish"]
                            if inc.leak_scope == "tray" else f"/redfish/v1/Chassis/{inc.rack}_RackManifold")
                out["redfish_events"].append({"timestamp": iso(inc.t0), "resource": resource + "/ThermalSubsystem/LeakDetection",
                                              "rack": inc.rack, "event_type": "LeakDetected", "severity": "Critical",
                                              "message": f"{inc.unit_label}: leak detector tripped"})
                out["redfish_events"].append({"timestamp": iso(inc.contained), "resource": resource + "/ThermalSubsystem/LeakDetection",
                                              "rack": inc.rack, "event_type": "LeakIsolated", "severity": "Warning",
                                              "message": "Loop isolated; no further fluid detected"})
                out["bms"].append({"timestamp": iso(inc.t0 + minutes(1)), "cdu": inc.cdu, "point": f"{inc.rack} leak rope",
                                   "alarm": "LeakDetected", "state": "active"})
                out["bms"].append({"timestamp": iso(inc.repair_done), "cdu": inc.cdu, "point": f"{inc.rack} leak rope",
                                   "alarm": "LeakDetected", "state": "cleared"})

            # ---------------- scheduler drain/return
            for node in inc.nodes_affected:
                reason = {"tray_gpu": f"XID {inc.xid}", "optic_link": "IB link down", "switch_tray": "NVLink domain degraded",
                          "leak": "Leak detected"}.get(inc.kind, inc.kind)
                sched(node, inc.t0 + minutes(1), "drain", reason)
                sched(node, inc.rts + minutes(1), "idle", "returned to service")

            # ---------------- inventory change (true physical swap)
            if inc.swap and inc.part_key == "tray":
                old = self.tray_serial[inc.host]
                new = self._serial("CT")
                inc.removed_serial, inc.installed_serial = old, new
                tray = next(t for t in rack["compute_trays"] if t["host"] == inc.host)
                if inc.emit_inventory_change:
                    out["inventory"].append({"observed_at": iso(inc.swap_time + minutes(self._u(3, 9))),
                                             "resource": tray["redfish"], "rack": inc.rack, "host": inc.host,
                                             "property": "SerialNumber", "old_value": old, "new_value": new})
                    self.tray_serial[inc.host] = new
                # If the inventory change was not observed, the tray was not really swapped: serial stays old.
            elif inc.swap:
                inc.removed_serial = self._serial({"switch_tray": "NS", "optic": "OP", "psu": "PU",
                                                   "power_shelf": "PS", "cdu": "CP"}[inc.part_key])
                inc.installed_serial = self._serial({"switch_tray": "NS", "optic": "OP", "psu": "PU",
                                                     "power_shelf": "PS", "cdu": "CP"}[inc.part_key])
                if inc.part_key in ("switch_tray", "psu", "power_shelf"):
                    out["inventory"].append({"observed_at": iso(inc.swap_time + minutes(self._u(3, 9))),
                                             "resource": inc.psu_path, "rack": inc.rack, "host": None,
                                             "property": "SerialNumber", "old_value": inc.removed_serial,
                                             "new_value": inc.installed_serial})

            # ---------------- validation health checks
            if inc.emit_validation:
                target = inc.rack if inc.validation_plan in ("switch_tray", "rack_manifold") else (
                    inc.cdu if inc.validation_plan == "cdu" else (
                        f"{inc.link['switch']}:swp{inc.link['port']}" if inc.validation_plan == "optic" else (
                            inc.psu_path if inc.validation_plan in ("psu", "power_shelf") else inc.host)))
                health(target, inc.validation_plan, inc.repair_done)

            # ---------------- badge: tech enters the hall for the job
            out["badge"].append({"timestamp": iso(inc.engaged - minutes(self._u(1, 3))), "badge_id": tech["badge_id"],
                                 "person_id": tech["person_id"], "door": hall_door, "direction": "in"})
            out["badge"].append({"timestamp": iso(inc.repair_done + minutes(self._u(2, 10))), "badge_id": tech["badge_id"],
                                 "person_id": tech["person_id"], "door": hall_door, "direction": "out"})

            # ---------------- vendor ticket
            out["tickets"].append(self._ticket(inc, tech, claims_swap))

            # ---------------- ground truth record
            gt = {k: (iso(v) if isinstance(v, datetime) else v) for k, v in asdict(inc).items()}
            gt["target_restore_min"] = inc.target_restore_min(self.sla)
            gt["true_restore_min"] = round((inc.rts - inc.t0).total_seconds() / 60, 1)
            out["gt_incidents"].append(gt)

        self._emit_shift_badges(out)
        self._emit_spares(out)
        self._emit_changes(out)
        self._emit_deployment_telemetry(out)
        for key in ("xid", "redfish_events", "inventory", "nmx", "ufm", "bms", "scheduler", "badge"):
            out[key].sort(key=lambda r: (r.get("timestamp") or r.get("observed_at"), json.dumps(r, sort_keys=True)))
        out["health"].sort(key=lambda r: (r["started_at"], r["target"], r["check"]))
        return out

    def _ticket(self, inc: Incident, tech: dict, claims_swap: bool) -> dict:
        notes = [
            {"at": iso(inc.acknowledged), "author": tech["name"], "text": f"Acknowledged. Assigned to {tech['name']}."},
            {"at": iso(inc.engaged_claimed), "author": tech["name"], "text": f"On site at rack {inc.rack} ({inc.hall})."},
        ]
        if inc.contained:
            notes.append({"at": iso(inc.contained), "author": tech["name"],
                          "text": "Leak contained: affected loop isolated, fluid cleaned, area secured."})
        parts = []
        if claims_swap and inc.part_key:
            # For an unverified swap this serial never appears in BMC inventory.
            installed = inc.installed_serial
            side = f" ({inc.optic_side} side)" if inc.optic_side else ""
            parts.append({"part": PART_NAMES[inc.part_key], "removed_serial": inc.removed_serial,
                          "installed_serial": installed, "location": (inc.host or inc.unit_label) + side})
            notes.append({"at": iso(inc.repair_done), "author": tech["name"],
                          "text": f"Replaced {PART_NAMES[inc.part_key].lower()}{side}. Removed SN {inc.removed_serial}, "
                                  f"installed SN {installed}. Failed part tagged for RMA."})
        elif inc.kind == "tray_gpu":
            notes.append({"at": iso(inc.repair_done), "author": tech["name"],
                          "text": "Reseated compute tray and verified quick-disconnects. No part replaced."})
        elif inc.kind == "optic_link":
            notes.append({"at": iso(inc.repair_done), "author": tech["name"],
                          "text": "Inspected and cleaned fiber on both ends. No part replaced."})
        for extra in inc.extra_parts:
            parts.append({"part": PART_NAMES[extra], "removed_serial": None, "installed_serial": None,
                          "location": inc.unit_label})
        if inc.rma_escalation_note:
            notes.append({"at": iso(inc.resolved), "author": tech["name"], "text": "Escalated to OEM for RMA review."})
        notes.append({"at": iso(inc.resolved), "author": tech["name"],
                      "text": "Validation complete; all return-to-service checks passed. Returned to production."})

        close_code = ("Hardware replaced" if parts and claims_swap else
                      "Cleaned/reseated" if inc.kind in ("tray_gpu", "optic_link") else "Resolved")
        return {
            "number": inc.ticket_number,
            "priority": inc.priority,
            "state": "Closed",
            "category": inc.kind,
            "short_description": inc.unit_label + (f": XID {inc.xid}" if inc.xid else ""),
            "configuration_item": inc.host or inc.unit_label,
            "rack": inc.rack,
            "hall": inc.hall,
            "opened_at": iso(inc.ticket_opened),
            "acknowledged_at": iso(inc.acknowledged),
            "assigned_to": tech["person_id"],
            "reported_outage_start": iso(inc.ticket_opened),
            "resolved_at": iso(inc.resolved),
            "close_code": close_code,
            "parts_used": parts,
            "validation_attached": True,
            "work_notes": notes,
        }

    def _emit_shift_badges(self, out: dict) -> None:
        roster = []
        for shift_date, shift in self.shifts:
            s, e = self._shift_bounds(shift_date, shift)
            crew = self._crew_for(shift_date, shift)
            for p in self.by_crew[crew]:
                roster.append({"shift_date": shift_date.isoformat(), "shift": shift, "crew": crew,
                               "shift_start": iso(s), "shift_end": iso(e), "person_id": p["person_id"],
                               "name": p["name"], "role": p["role"], "status": "scheduled"})
                if (shift_date, shift, p["person_id"]) in self.absent:
                    continue
                t_in = s - minutes(self._u(2, 15))
                t_out = e + minutes(self._u(0, 20))
                if t_in < self.end and t_out > self.start:
                    out["badge"].append({"timestamp": iso(t_in), "badge_id": p["badge_id"], "person_id": p["person_id"],
                                         "door": "OPS-MAIN", "direction": "in"})
                    out["badge"].append({"timestamp": iso(t_out), "badge_id": p["badge_id"], "person_id": p["person_id"],
                                         "door": "OPS-MAIN", "direction": "out"})
        self.roster = roster

    def _emit_spares(self, out: dict) -> None:
        minimums = {s["fru"]: s["minimum"] for s in self.sla["spares"]["minimum_stock_per_hall"]}
        ledger = {fru: int(round(m * 1.5)) for fru, m in minimums.items()}
        physical = dict(ledger)
        events: list[tuple[datetime, str, dict]] = []
        for inc in self.incidents:
            for key in ([inc.part_key] if inc.part_key and inc.swap else []) + inc.extra_parts:
                fru = PART_NAMES[key]
                when = (inc.swap_time or inc.repair_done) - minutes(self._u(10, 25))
                events.append((when, "issue", {"fru": fru, "ticket": inc.ticket_number,
                                               "log": inc.log_spares_issue or key != inc.part_key}))
                if key == inc.part_key and inc.removed_serial:
                    lo, hi = self.cfg["vendor_behavior"]["rma_ship_days"]
                    out["rma"].append({"ticket": inc.ticket_number, "fru": fru, "serial": inc.removed_serial,
                                       "removed_at": iso(inc.repair_done),
                                       "shipped_at": iso(inc.repair_done + timedelta(days=self._u(lo, hi)))})
        # Weekly replenishment (Monday 10:00 local) and cycle count (Sunday 18:00 local).
        for w in range(self.weeks):
            monday = self.start + timedelta(weeks=w) + timedelta(hours=10) - self.utc_offset
            sunday = self.start + timedelta(weeks=w, days=6) + timedelta(hours=18) - self.utc_offset
            events.append((monday, "replenish", {}))
            events.append((sunday, "cycle_count", {}))
        events.sort(key=lambda e: e[0])
        start_levels = dict(ledger)
        for when, kind, d in events:
            if kind == "issue":
                physical[d["fru"]] -= 1
                if d["log"]:
                    ledger[d["fru"]] -= 1
                    out["spares_ledger"].append({"timestamp": iso(when), "transaction": "issue", "fru": d["fru"],
                                                 "qty": -1, "ticket": d["ticket"], "balance_after": ledger[d["fru"]]})
            elif kind == "replenish":
                for fru, level in start_levels.items():
                    need = level - ledger[fru]
                    if need > 0:
                        ledger[fru] += need
                        physical[fru] += need
                        out["spares_ledger"].append({"timestamp": iso(when), "transaction": "receive", "fru": fru,
                                                     "qty": need, "ticket": None, "balance_after": ledger[fru]})
            else:
                for fru in sorted(ledger):
                    out["cycle_counts"].append({"counted_at": iso(when), "fru": fru,
                                                "system_qty": ledger[fru], "counted_qty": physical[fru]})
                # A count resets the ledger to physical (the variance is recorded, then adjusted).
                for fru in ledger:
                    if ledger[fru] != physical[fru]:
                        out["spares_ledger"].append({"timestamp": iso(when + minutes(5)), "transaction": "count_adjustment",
                                                     "fru": fru, "qty": physical[fru] - ledger[fru], "ticket": None,
                                                     "balance_after": physical[fru]})
                        ledger[fru] = physical[fru]

    def _emit_changes(self, out: dict) -> None:
        """Approved firmware changes (with CAB records) plus planted unauthorized ones."""
        racks = self.rng.sample(self.prod_racks, 2 + self.cfg["anomalies"].get("unauthorized_change", 0))
        approved, rogue = racks[:2], racks[2:]
        for n, rack in enumerate(approved, start=1):
            day = self.start + timedelta(days=self.rng.randint(3, max(3, self.weeks * 7 - 4)))
            # Maintenance window 01:00-05:00 site local time.
            win_start = datetime.combine(self._local(day).date(), time(1), tzinfo=UTC) - self.utc_offset
            win_end = win_start + timedelta(hours=4)
            chg = f"CHG{2_040_000 + n * 31:07d}"
            out["cab"].append({"change_id": chg, "summary": f"Compute tray firmware 1.3.6 -> 1.3.7 on rack {rack['rack']}",
                               "rack": rack["rack"], "approved_by": "Customer CAB", "window_start": iso(win_start),
                               "window_end": iso(win_end), "state": "Approved"})
            self._fw_events(out, rack, win_start + minutes(20))
        for rack in rogue:
            when = self._random_t0(latest_margin_h=24).replace(hour=8, minute=self.rng.randint(0, 59))  # ~03:00 local
            self._fw_events(out, rack, when)
            self.planted.append({
                "type": "unauthorized_change", "unit": f"Rack {rack['rack']} compute trays",
                "evidence": f"Firmware changed on all {len(rack['compute_trays'])} trays of rack {rack['rack']} with no "
                            "approved change record covering that rack and time.",
                "detect_with": ["telemetry/redfish_inventory_changes.jsonl", "customer/cab_changes.json"],
                "sla_refs": ["KM-10"], "rack": rack["rack"], "observed_from": iso(when),
            })

    def _fw_events(self, out: dict, rack: dict, start: datetime) -> None:
        for k, tray in enumerate(rack["compute_trays"]):
            out["inventory"].append({"observed_at": iso(start + minutes(k * 6)), "resource": tray["redfish"],
                                     "rack": rack["rack"], "host": tray["host"], "property": "FirmwareVersion",
                                     "old_value": self.tray_firmware[tray["host"]], "new_value": "1.3.7"})
            self.tray_firmware[tray["host"]] = "1.3.7"

    def _emit_deployment_telemetry(self, out: dict) -> None:
        self.milestone_rows = []
        for ev in self.deploy_events:
            if ev["completed_at"] > self.end:
                continue
            self.milestone_rows.append({"rack": ev["rack"], "milestone": ev["milestone"], "name": ev["name"],
                                        "reported_complete_at": iso(ev["completed_at"])})
            rack = self.rack_by_id[ev["rack"]]
            if ev["milestone"] == "M6":
                out["health"].append({"started_at": iso(ev["completed_at"] - timedelta(hours=24)),
                                      "completed_at": iso(ev["completed_at"]), "target": rack["rack"],
                                      "check": "rack_burn_in_24h", "result": "pass"})
            if ev["milestone"] == "M7":
                for t in rack["compute_trays"]:
                    out["scheduler"].append({"timestamp": iso(ev["completed_at"] + minutes(5)), "node": t["host"],
                                             "state": "idle", "reason": "validated handoff"})

    # ============================================================ summary
    def vendor_self_report(self) -> list[dict]:
        """What the vendor tells the Customer each week, computed from its own tickets."""
        gpus = sum(len(r["compute_trays"]) for r in self.prod_racks) * self.sla["site"]["per_rack"]["gpus_per_compute_tray"]
        weeks = []
        for w in range(self.weeks):
            ws, we = self.start + timedelta(weeks=w), self.start + timedelta(weeks=w + 1)
            incs = [i for i in self.incidents if ws <= i.ticket_opened < we]
            lost = sum(i.gpus_affected * (i.resolved - i.ticket_opened).total_seconds() / 3600 for i in incs)
            by_p = {}
            for p in ("P1", "P2", "P3"):
                ps = [i for i in incs if i.priority == p]
                met = [i for i in ps if (i.resolved - i.ticket_opened).total_seconds() / 60 <= self._restore_target(p)]
                by_p[p] = {"count": len(ps), "within_target_pct": round(100 * len(met) / len(ps), 1) if ps else 100.0}
            weeks.append({
                "week_start": iso(ws), "week_end": iso(we),
                "tickets_closed": len(incs),
                "gpu_availability_pct": round(100 * (1 - lost / (gpus * 168)), 3),
                "restore_performance": by_p,
                "first_time_fix_pct": 100.0,
                "validated_rts_pct": 100.0,
                "staffing_fill_pct": 100.0,
                "notes": ("All SLAs met. No open escalations." if all(v["within_target_pct"] == 100.0 for v in by_p.values())
                          else "Minor restore-time exceptions under review. No open escalations."),
            })
        return weeks

    # ============================================================== run
    def _facility_rack_effects(self, outages: list[dict], streams: dict[str, list]) -> None:
        """The IT side of a Landlord-caused rack outage: nodes down, the IT Partner validates after the handoff (HO-1).

        Uses its own random stream, so every IT incident generated above is unchanged.
        """
        rng = random.Random(f"{self.seed}:rackfx")
        for k, o in enumerate(outages, 1):
            rack = next(r for r in self.racks if r["rack"] == o["rack"])
            t0, handoff = o["t0"], o["handoff"]
            tech = rng.choice(self.on_duty_techs(handoff))
            badge_id = next(b["badge_id"] for b in streams["badge"] if b["person_id"] == tech["person_id"])
            arrive = handoff + minutes(rng.uniform(4, 9))
            streams["badge"].append({"timestamp": iso(arrive), "badge_id": badge_id, "person_id": tech["person_id"],
                                     "door": f"HALL-{rack['hall'][-1]}", "direction": "in"})
            t, checks = handoff + minutes(rng.uniform(8, 14)), []
            for check, dur in (("rack_power_on", rng.uniform(8, 15)), ("rack_nvlink_acceptance", rng.uniform(10, 18)),
                               ("nccl_allreduce_rack", rng.uniform(10, 15))):
                checks.append({"check": check, "started_at": iso(t), "completed_at": iso(t + minutes(dur)),
                               "result": "pass", "target": rack["rack"]})
                t += minutes(dur)
            rts = t + minutes(rng.uniform(3, 8))
            # The technician leaves the hall after return to service. IT readers record exits, so the
            # outage's badge-in needs a matching badge-out. Drawn from its own stream (no other value moves)
            # and kept before the technician's next badge event.
            leave = rts + minutes(random.Random(f"{self.seed}:rackfx:out:{k}").uniform(4, 12))
            later = [datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00")) for b in streams["badge"]
                     if b["person_id"] == tech["person_id"] and b["timestamp"] > iso(arrive)]
            if later and min(later) <= leave:
                leave = min(later) - minutes(1)
            if leave > rts:
                streams["badge"].append({"timestamp": iso(leave), "badge_id": badge_id, "person_id": tech["person_id"],
                                         "door": f"HALL-{rack['hall'][-1]}", "direction": "out"})
            streams["health"] += checks
            for tray in rack["compute_trays"]:
                streams["scheduler"] += [
                    {"node": tray["host"], "reason": "NotResponding (rack input power lost)", "state": "down",
                     "timestamp": iso(t0 + timedelta(seconds=rng.randint(15, 40)))},
                    {"node": tray["host"], "reason": "returned to service", "state": "idle", "timestamp": iso(rts)}]
            opened = t0 + minutes(rng.uniform(2, 4))
            name = tech["name"]
            streams["tickets"].append({
                "number": f"INC39{k:05d}", "category": "rack_facility", "priority": "P1", "state": "Closed",
                "hall": rack["hall"], "rack": rack["rack"], "configuration_item": f"Rack {rack['rack']}",
                "short_description": f"Rack {rack['rack']} down: input power lost on both feeds (Landlord {o['wo']})",
                "opened_at": iso(opened), "acknowledged_at": iso(opened + minutes(2)), "assigned_to": tech["person_id"],
                "reported_outage_start": iso(handoff), "resolved_at": iso(rts), "close_code": "Facility restored; validated",
                "parts_used": [], "validation_attached": True,
                "work_notes": [
                    {"at": iso(opened + minutes(2)), "author": name, "text": f"Acknowledged. Rack dark; Landlord working {o['wo']}. Standing by for handoff (HO-1)."},
                    {"at": iso(arrive + minutes(1)), "author": name, "text": f"On site at rack {rack['rack']} ({rack['hall']})."},
                    {"at": iso(handoff + minutes(10)), "author": name, "text": "Landlord handoff received; feed restored. Powering on and validating."},
                    {"at": iso(rts), "author": name, "text": "Validation complete; all return-to-service checks passed. Returned to production."}]})
        for key in ("badge", "health", "scheduler", "tickets"):
            field_ = {"badge": "timestamp", "health": "started_at", "scheduler": "timestamp", "tickets": "opened_at"}[key]
            streams[key].sort(key=lambda r: r[field_])      # stable: existing records keep their order

    def run(self) -> dict[str, Any]:
        self.build_topology()
        self.build_staffing()
        self.generate_base_incidents()
        self.plant_anomalies()
        self.build_deployment()
        self.finalize()
        streams = self.emit()
        topology = {
            "site": {k: self.sla["site"][k] for k in ("id", "name", "platform", "cooling")},
            "racks": [{k: v for k, v in r.items() if k != "milestones"} for r in self.racks],
        }
        # Topology is the baseline inventory at window start (before any swaps).
        planted = []
        for n, p in enumerate(self.planted, start=1):
            p = dict(p)
            p["anomaly_id"] = f"PD-{n:03d}"
            if "gt_id" in p:
                inc = next(i for i in self.incidents if i.gt_id == p["gt_id"])
                p["ticket"] = inc.ticket_number
            if "recurrence_gt_id" in p:
                p["recurrence_ticket"] = next(i.ticket_number for i in self.incidents if i.gt_id == p["recurrence_gt_id"])
            if "gt_ids" in p:
                p["tickets"] = [i.ticket_number for i in self.incidents if i.gt_id in p["gt_ids"]]
            planted.append(p)
        facility = None
        if "facility" in self.cfg:
            # Separate random stream: the facility data never changes the IT data above.
            from scorecard import site_model
            from scorecard.sla_model import PARTNER_FILES, load_sla
            from .facility import FacilityGenerator
            facility = FacilityGenerator(site_model.load_site(), load_sla(PARTNER_FILES["landlord"]), self.cfg,
                                         self.start, self.end, self.seed, self.utc_offset).run()
            self._facility_rack_effects(facility["rack_outages"], streams)
        return {
            "facility": facility,
            "window": {"start": iso(self.start), "end": iso(self.end), "weeks": self.weeks, "seed": self.seed},
            "topology": topology,
            "personnel": self.personnel,
            "roster": self.roster,
            "deployment_plan": self.deploy_plan,
            "deployment_milestones": self.milestone_rows,
            "vendor_weekly": self.vendor_self_report(),
            "streams": streams,
            "planted": planted,
        }


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8", newline="\n")
        return
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_dataset(data: dict[str, Any], out_dir: str | Path) -> dict[str, int]:
    """Write the dataset to disk. Returns {relative_path: record_count}."""
    out = Path(out_dir)
    s = data["streams"]
    files: dict[str, tuple[str, Any]] = {
        "site/topology.json": ("json", data["topology"]),
        "telemetry/dcgm_xid_events.jsonl": ("jsonl", s["xid"]),
        "telemetry/redfish_events.jsonl": ("jsonl", s["redfish_events"]),
        "telemetry/redfish_inventory_changes.jsonl": ("jsonl", s["inventory"]),
        "telemetry/nmx_events.jsonl": ("jsonl", s["nmx"]),
        "telemetry/ufm_port_events.jsonl": ("jsonl", s["ufm"]),
        "telemetry/bms_cdu_events.jsonl": ("jsonl", s["bms"]),
        "telemetry/health_checks.jsonl": ("jsonl", s["health"]),
        "telemetry/scheduler_node_states.jsonl": ("jsonl", s["scheduler"]),
        "access/badge_events.csv": ("csv", s["badge"]),
        "customer/cab_changes.json": ("json", s["cab"]),
        "customer/deployment_plan.csv": ("csv", data["deployment_plan"]),
        "vendor/tickets.json": ("json", s["tickets"]),
        "vendor/personnel.csv": ("csv", data["personnel"]),
        "vendor/roster.csv": ("csv", data["roster"]),
        "vendor/spares_ledger.csv": ("csv", s["spares_ledger"]),
        "vendor/spares_cycle_counts.csv": ("csv", s["cycle_counts"]),
        "vendor/rma_shipments.csv": ("csv", s["rma"]),
        "vendor/deployment_milestones.csv": ("csv", data["deployment_milestones"]),
        "vendor/self_reported_weekly.json": ("json", data["vendor_weekly"]),
        "ground_truth/incidents.json": ("json", s["gt_incidents"]),
        "ground_truth/planted_discrepancies.json": ("json", data["planted"]),
    }
    if data.get("facility"):
        from .facility import FACILITY_FILES
        for rel, key in FACILITY_FILES.items():
            kind = "jsonl" if rel.endswith(".jsonl") else "csv" if rel.endswith(".csv") else "json"
            files[rel] = (kind, data["facility"][key])
    counts: dict[str, int] = {}
    for rel, (kind, obj) in files.items():
        path = out / rel
        if kind == "jsonl":
            _write_jsonl(path, obj)
        elif kind == "csv":
            _write_csv(path, obj)
        else:
            _write_json(path, obj)
        counts[rel] = len(obj) if isinstance(obj, list) else 1
    manifest = {
        "generator": "scorecard.synthetic",
        "disclaimer": "Synthetic data for a portfolio demonstration. All sites, people, serials, and events are fictional.",
        "window": data["window"],
        "files": counts,
        "note": "ground_truth/ is the answer key for measuring detection. The discrepancy engine must not read it.",
    }
    _write_json(out / "manifest.json", manifest)
    return counts
