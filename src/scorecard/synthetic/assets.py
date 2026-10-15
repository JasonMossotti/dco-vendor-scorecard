"""Synthetic asset register for Site AUS-1: every asset by serial, from receipt to install, RMA, and disposal.

Portfolio demo; all data fictional. Runs on a finished month (data/sample, the Security layer, and the management and
storage layers already written for it) with its own random stream ("<seed>:assets") and writes beside them, never into
the records it reads.

The register is what the partners record (Interface Agreement section 11): the IT Partner records its equipment and the
spares cage, the Landlord its facility equipment, the Security Partner the media in its custody. Each transaction
mirrors a record that already exists for the month: a ticket's parts (the work note that names the serials), an RMA
shipment, a spares ledger receipt, a custody handover, a destruction certificate, a Hall B rack's receipt (milestone M1)
and power-on (M4). What the devices answer with comes from the sample where it says (the site topology, the Redfish
inventory changes, the storage drive log, the Hall B first answers); this layer writes the rest of the first scan
(PSU serials, switch and storage node serials) in ``inventory_baseline.csv``.

Also written here: the OEM's RMA portal (each failed part received, its replacement shipped and delivered with a
carrier proof of delivery) and the e-waste disposal certificates.

Planted (one each a month; ``answer_key.json``), each a case where records do not reconcile:
  1. ``live_in_stock``: a PSU answers in a shelf, but the register lists it in the spares cage and lists the unit it
     replaced in the slot. Quantity counts still match.
  2. ``rma_not_received``: the OEM's carrier delivered a replacement (proof of delivery) that neither the register nor
     the spares ledger received.
  3. ``disposed_answering``: a switch the register says was replaced and disposed before the month is still the one
     answering at its location.
Decoys: transactions recorded late but inside REG-2's 4 hours, replacements in transit at month end, a delivery inside
REG-3's 24 hours at month end, past disposals that never answer, and past switch replacements done right.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "assets.yaml"
CAGE, FAILED_CAGE, OEM, SECURITY = "Spares cage", "Failed-parts cage", "OEM", "Security Partner"
STORAGE_SHELF = "Storage spares shelf"


def shelf_of(hall: str) -> str:
    """The storage spares shelf in a hall's storage row (HALL-A gives "Storage spares shelf, Hall A")."""
    return f"{STORAGE_SHELF}, Hall {hall.rsplit('-', 1)[-1]}"


def in_stock_at(location: str) -> bool:
    return location == CAGE or location.startswith(STORAGE_SHELF)
SWITCH_KINDS = ("mgmt", "leaf", "eth_leaf", "eth_spine", "console", "agg")


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _csv(p: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8")))) if p.exists() else []


def _rng(seed: int, *parts: object) -> random.Random:
    key = ":".join(str(p) for p in (seed, "assets") + parts)
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def shelf_name(rack: str, n: int | str) -> str:
    return f"{rack}_PowerShelf_{n}"


def psu_slot(shelf: str, m: int | str) -> str:
    return f"{shelf} PSU {m}"


def slot_of_resource(resource: str, host: str | None, switch_names: dict[str, str]) -> str | None:
    """The register location of a Redfish inventory resource."""
    m = re.match(r"/redfish/v1/Chassis/([A-C]\d{2}_PowerShelf_\d+)/PowerSubsystem/PowerSupplies/(\d+)$", resource)
    if m:
        return psu_slot(m.group(1), m.group(2))
    m = re.match(r"/redfish/v1/Chassis/([A-C]\d{2}_PowerShelf_\d+)$", resource)
    if m:
        return m.group(1)
    if "_SwitchTray_" in resource:
        return switch_names.get(resource)
    if "_ComputeTray_" in resource:
        return host
    return None


def slot_of_part(part: str, location: str) -> str | None:
    """The register location a ticket's part line names (None for a part the register does not hold by location)."""
    m = re.match(r"PSU (\d+) in ([A-C]\d{2}) power shelf (\d+)$", location)
    if m:
        return psu_slot(shelf_name(m.group(2), m.group(3)), m.group(1))
    m = re.match(r"([A-C]\d{2}) power shelf (\d+)$", location)
    if m:
        return shelf_name(m.group(1), m.group(2))
    m = re.match(r"NVLink switch tray ([a-c]\d{2}-nvsw\d)$", location)
    if m:
        return m.group(1)
    if re.match(r"[a-c]\d{2}-ct\d{2}$", location) or re.match(r"stg-[ab]\d-n\d{2} Bay\d{2}$", location):
        return location
    return None


def work_time(ticket: dict, removed: str | None) -> datetime:
    """When the part was swapped: the work note that names the removed serial, else the resolution."""
    for n in ticket.get("work_notes", []):
        if removed and removed in n["text"]:
            return parse(n["at"])
    return parse(ticket["resolved_at"])


class AssetLayer:
    """One month of the register, the first inventory scan, the OEM's RMA portal, and the disposal certificates."""

    def __init__(self, data_dir: str | Path, seed: int, sec_dir: str | Path, mgmt_dir: str | Path, storage_dir: str | Path,
                 cfg: dict[str, Any] | None = None):
        from scorecard import devices as DV
        self.d, self.seed = Path(data_dir), seed
        self.sec, self.mgmt, self.stg = Path(sec_dir), Path(mgmt_dir), Path(storage_dir)
        self.cfg = cfg or load_config()
        w = json.loads((self.d / "manifest.json").read_text(encoding="utf-8"))["window"]
        self.window = {"start": w["start"] if "T" in w["start"] else w["start"] + "T00:00:00Z",
                       "end": w["end"] if "T" in w["end"] else w["end"] + "T00:00:00Z", "seed": seed}
        self.start, self.end = parse(self.window["start"]), parse(self.window["end"])
        self.topology = json.loads((self.d / "site" / "topology.json").read_text(encoding="utf-8"))
        self.directory = DV.load()["devices"]
        self.tickets = json.loads((self.d / "vendor" / "tickets.json").read_text(encoding="utf-8"))
        self.stg_tickets = json.loads((self.stg / "tickets.json").read_text(encoding="utf-8"))
        self.ledger = _csv(self.d / "vendor" / "spares_ledger.csv")
        self.counts = _csv(self.d / "vendor" / "spares_cycle_counts.csv")
        self.rma = _csv(self.d / "vendor" / "rma_shipments.csv")
        self.inv = [e for e in _jsonl(self.d / "telemetry" / "redfish_inventory_changes.jsonl") if e["property"] == "SerialNumber"]
        self.milestones = _csv(self.d / "vendor" / "deployment_milestones.csv")
        self.tray_drives = _csv(self.sec / "tray_drives.csv")
        self.custody = _csv(self.sec / "chain_of_custody.csv")
        self.certs = _csv(self.sec / "destruction_certificates.csv")
        self.drive_inv = _csv(self.stg / "drive_inventory.csv")
        self.stg_custody = _csv(self.stg / "custody.csv")
        self.stg_ledger = _csv(self.stg / "spares_ledger.csv")
        self.stg_counts = _csv(self.stg / "spares_cycle_counts.csv")
        self.switch_names = {x["redfish"]: x["name"] for r in self.topology["racks"] for x in r["switch_trays"]}
        self.used: set[str] = set()
        for r in self.topology["racks"]:
            for k in ("compute_trays", "switch_trays", "power_shelves"):
                self.used |= {x["serial"] for x in r[k]}
        self.used |= {e["old_value"] for e in self.inv} | {e["new_value"] for e in self.inv}
        for t in self.tickets + self.stg_tickets:
            for p in t.get("parts_used", []):
                self.used |= {p.get("installed_serial") or "", p.get("removed_serial") or ""}
        self.used |= {r["serial"] for r in self.rma} | {r["drive_serial"] for r in self.tray_drives}
        self.used |= {r["serial_start"] for r in self.drive_inv} | {r["serial_end"] for r in self.drive_inv}

    # ------------------------------------------------------------------ helpers
    def serial(self, cls: str, rng: random.Random) -> str:
        f = self.cfg["serials"][cls]
        while True:
            s = f["prefix"] + "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(f["length"] - len(f["prefix"])))
            if s not in self.used:
                self.used.add(s)
                return s

    def m_dates(self) -> dict[str, dict[str, datetime]]:
        out: dict[str, dict[str, datetime]] = {}
        for r in self.milestones:
            if r["reported_complete_at"]:
                out.setdefault(r["rack"], {})[r["milestone"]] = parse(r["reported_complete_at"])
        return out

    def ledger_opening(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.ledger:
            out.setdefault(r["fru"], int(r["balance_after"]) - int(r["qty"]))
        for c in sorted(self.counts, key=lambda c: c["counted_at"]):
            out.setdefault(c["fru"], int(c["system_qty"]))
        return out

    # ------------------------------------------------------------------ the month
    def run(self) -> dict[str, Any]:
        cfg, B = self.cfg, self.cfg["behaviour"]
        cls_of = cfg["classes"]
        assets: list[dict] = []           # the opening register
        tx: list[dict] = []               # transactions in the month
        baseline: dict[str, tuple[str, str]] = {}   # slot -> (source, serial) at the first scan it answers
        by_serial: dict[str, dict] = {}
        seq = [0]

        def new(cls: str, serial: str, status: str, location: str, maintainer: str, since: datetime, ref: str = "", opening: bool = True) -> dict:
            seq[0] += 1
            a = {"tag": f"AT-{seq[0]:06d}", "class": cls, "serial": serial, "status": status, "location": location,
                 "maintainer": maintainer, "since": iso(since), "ref": ref}
            if opening:
                assets.append(a)
            by_serial[serial] = a
            self.used.add(serial)
            return a

        rng = _rng(self.seed, "serials")
        before = self.start - timedelta(days=200)
        # ---- first-scan serials of the Redfish slots: the first change's old value, else the topology's serial
        first_old: dict[str, str] = {}
        for e in sorted(self.inv, key=lambda e: e["observed_at"]):
            s = slot_of_resource(e["resource"], e["host"], self.switch_names)
            if s:
                first_old.setdefault(s, e["old_value"])
        md = self.m_dates()
        racks_in: list[tuple[dict, str, datetime | None]] = []     # rack, status at opening or "receive", receipt
        for r in sorted(self.topology["racks"], key=lambda r: r["rack"]):
            if r["state"] == "production":
                racks_in.append((r, "installed", None))
            elif "M1" in md.get(r["rack"], {}) and md[r["rack"]]["M1"] < self.end:
                m1, m4 = md[r["rack"]]["M1"], md[r["rack"]].get("M4")
                if m1 < self.start:
                    racks_in.append((r, "installed" if m4 and m4 < self.start else "received", m1))
                else:
                    racks_in.append((r, "receive", m1))
        rack_items: dict[str, list[tuple[str, str, str, str | None]]] = {}   # rack -> (kind, slot, serial, source)
        for r, _, _ in racks_in:
            rk, items = r["rack"], []
            items.append(("rack", rk, self.serial("Rack", rng), None))
            for x in r["compute_trays"]:
                items.append(("compute_tray", x["host"], first_old.get(x["host"], x["serial"]), "Redfish"))
            for x in r["switch_trays"]:
                items.append(("switch_tray", x["name"], first_old.get(x["name"], x["serial"]), "Redfish"))
            for x in r["power_shelves"]:
                sh = shelf_name(rk, x["slot"])
                items.append(("power_shelf", sh, first_old.get(sh, x["serial"]), "Redfish"))
                for m in range(1, cfg["scan"]["psus_per_shelf"] + 1):
                    ps = psu_slot(sh, m)
                    items.append(("psu", ps, first_old.get(ps) or self.serial("PSU (5.5 kW)", rng), "Redfish"))
            for i in (1, 2):
                items.append(("mgmt", f"{rk.lower()}-mgmt{i}", self.serial("Management switch", rng), "SNMP"))
            rack_items[rk] = items
        for r, status, m1 in racks_in:
            for kind, slot, serial, src in rack_items[r["rack"]]:
                if src:
                    baseline[slot] = (src, serial)
                if status != "receive":
                    new(cls_of[kind]["class"], serial, status, slot, cls_of[kind]["maintainer"], m1 or before)
        # ---- the halls' network, storage, and facility equipment, all in place before the month
        dev = self.directory
        for name in sorted(dev):
            kind = dev[name]["kind"]
            if kind in ("leaf", "eth_leaf", "eth_spine", "console", "agg", "stg_rack", "stg_node"):
                c = cls_of[kind]
                s = self.serial(c["class"], rng)
                new(c["class"], s, "installed", name, c["maintainer"], before)
                if c["reported"]:
                    baseline[name] = (c["reported"], s)
            elif kind in cfg["facility_kinds"] and not (dev[name].get("hall") == "Hall C" and kind == "rack"):
                new(cls_of["facility"]["class"], self.serial("Facility equipment", rng), "installed", name, "Landlord", before)
        for r in sorted(self.drive_inv, key=lambda r: (r["node"], r["bay"])):
            slot = f"{r['node']} {r['bay']}"
            new(cls_of["drive"]["class"], r["serial_start"], "installed", slot, "IT Partner", before)
            baseline[slot] = ("Redfish", r["serial_start"])
        # ---- the spares cage: the ledger's opening balance per serialized class; installs this month come from it, or
        #      from a receipt before them once the opening stock is spoken for
        opening = self.ledger_opening()
        installs: dict[str, list[tuple[datetime, str]]] = {}
        parts: list[tuple[datetime, dict, dict]] = []
        for t in self.tickets + self.stg_tickets:
            for p in t.get("parts_used", []):
                if p.get("installed_serial") or p.get("removed_serial"):
                    parts.append((work_time(t, p.get("removed_serial")), t, p))
        parts.sort(key=lambda x: (x[0], x[1]["number"]))
        stg_numbers = {t["number"] for t in self.stg_tickets}
        stg_installs: dict[str, list[str]] = {}
        for at, t, p in parts:
            if p.get("installed_serial"):
                if t["number"] in stg_numbers:
                    stg_installs.setdefault(p["part"], []).append(p["installed_serial"])
                else:
                    installs.setdefault(p["part"], []).append((at, p["installed_serial"]))
        receipts: dict[str, list[dict]] = {}
        for r in self.ledger:
            if r["transaction"] == "receive" and r["fru"] in cfg["spares"]["serialized"]:
                receipts.setdefault(r["fru"], []).append({"at": parse(r["timestamp"]), "qty": int(r["qty"]), "serials": [], "direct": 0})
        direct: list[tuple[str, datetime, str]] = []
        stock_open: dict[str, list[str]] = {}
        for cls in cfg["spares"]["serialized"]:
            n_open = opening.get(cls, 0)
            pool: list[str] = []
            for at, s in installs.get(cls, []):
                if len(pool) < n_open:
                    pool.append(s)
                    continue
                rc = [r for r in receipts.get(cls, []) if r["at"] <= at and len(r["serials"]) + r["direct"] < r["qty"]]
                if rc:
                    rc[-1]["serials"].append(s)
                    continue
                # the cage is empty (the ledger's balance is below zero): the OEM shipped the unit straight to the job,
                # and the ledger posts it with the next weekly receipt
                nxt = [r for r in receipts.get(cls, []) if r["at"] > at and len(r["serials"]) + r["direct"] < r["qty"]]
                if nxt:
                    nxt[0]["direct"] += 1
                direct.append((cls, at - timedelta(hours=_rng(self.seed, "direct", s).uniform(1, 4)), s))
            while len(pool) < n_open:
                pool.append(self.serial(cls, rng))
            stock_open[cls] = pool
            for s in pool:
                new(cls, s, "in_stock", CAGE, "IT Partner", before)
        # the storage spares shelf in each hall (drives and fabric optics): its own ledger (IT Partner SLA, storage spares
        # shelf). Each unit the shelf holds is a place in its stock, from the opening balance or a receipt; a storage
        # ticket's installed serial takes the oldest place in stock in its hall when the shelf issues it.
        from scorecard.sla_model import load_sla
        from scorecard.synthetic.telemetry_storage import shelf_classes
        part_of = {c["fru"]: c["part"] for c in shelf_classes(load_sla())}
        stg_parts: dict[tuple[str, str, str], list[str]] = {}
        for t in self.stg_tickets:
            for p in t.get("parts_used", []):
                if p.get("installed_serial"):
                    stg_parts.setdefault((t["number"], t["hall"], p["part"]), []).append(p["installed_serial"])
        shelf_places: dict[tuple[str, str], list[dict]] = {}
        shelf_receipts: list[dict] = []
        for c in self.stg_counts:
            k = (c["hall"], part_of[c["fru"]])
            if k not in shelf_places:
                first = [x for x in self.stg_ledger if (x["hall"], x["fru"]) == (c["hall"], c["fru"])]
                n0 = int(first[0]["balance_after"]) - int(first[0]["qty"]) if first else int(c["system_qty"])
                shelf_places[k] = [{"at": None, "serial": None} for _ in range(n0)]
        for x in self.stg_ledger:
            k = (x["hall"], part_of[x["fru"]])
            pl = shelf_places[k]
            if x["transaction"] in ("receive", "emergency_receive"):
                for _ in range(int(x["qty"])):
                    pl.append({"at": parse(x["timestamp"]), "serial": None, "emergency": x["transaction"] == "emergency_receive"})
                    shelf_receipts.append(pl[-1] | {"class": k[1], "hall": k[0]})
                    shelf_receipts[-1]["place"] = pl[-1]
            elif x["transaction"] == "issue":
                serials = stg_parts.get((x["ticket"], k[0], k[1]), [])
                free = next(q for q in pl if q["serial"] is None and (q["at"] is None or q["at"] <= parse(x["timestamp"])))
                free["serial"] = serials.pop(0) if serials else self.serial(k[1], _rng(self.seed, "shelf", x["timestamp"], k[0], k[1]))
        srng = _rng(self.seed, "stock")
        for (hall, cls), pl in sorted(shelf_places.items()):
            for q in pl:
                if q["serial"] is None:
                    q["serial"] = self.serial(cls, srng)
                if q["at"] is None:
                    new(cls, q["serial"], "in_stock", shelf_of(hall), "IT Partner", before)
        for cls, rs in receipts.items():
            for r in rs:
                while len(r["serials"]) + r["direct"] < r["qty"]:
                    r["serials"].append(self.serial(cls, rng))
        # ---- planted 1: a PSU answering in a shelf that the register lists in the cage; the slot lists the old unit
        prng = _rng(self.seed, "planted")
        touched = set(first_old) | {slot_of_part(p["part"], p["location"]) for _, _, p in parts}
        psu_slots = sorted(s for s, (src, _) in baseline.items() if " PSU " in s and s not in touched and s[0] == "A"
                           and s.rsplit(" PSU ", 1)[0] not in touched)
        used_later = {s for v in installs.values() for _, s in v} | {s for v in stg_installs.values() for s in v}
        planted: list[dict] = []
        if cfg["planted"]["live_in_stock"]:
            slot = prng.choice(psu_slots)
            spare = prng.choice(sorted(s for s in stock_open["PSU (5.5 kW)"] if s not in used_later))
            old = baseline[slot][1]
            baseline[slot] = ("Redfish", spare)
            planted.append({"kind": "live_in_stock", "serial": spare, "slot": slot, "registered": old})
        # ---- past disposals (decoys) and past switch replacements, one of them never done (planted 3)
        drng = _rng(self.seed, "disposals")
        disposals: list[dict] = []
        cert_n = [drng.randint(300, 600)]

        def dispose(cls: str, serial: str, at: datetime, why: str) -> None:
            cert_n[0] += 1
            c = f"EW-{cert_n[0]:05d}"
            disposals.append({"certificate": c, "serial": serial, "class": cls, "disposed_at": iso(at), "reason": why,
                              "method": "Shredded and recycled", "recycler": B["recycler"], "witness": "Security Partner"})
            new(cls, serial, "disposed", B["recycler"], "IT Partner", at, c)
        for _ in range(drng.randint(*B["past_disposals"])):
            cls = drng.choice(["PSU (5.5 kW)", "800G OSFP optic", "Management switch", "Compute tray"])
            dispose(cls, self.serial(cls, drng), self.start - timedelta(days=drng.uniform(10, 120)), "Beyond economical repair")
        switches = sorted(n for n in dev if dev[n]["kind"] in SWITCH_KINDS and n in baseline and n[0] in "aelco"
                          and not re.match(r"b\d{2}-mgmt", n))
        picks = drng.sample(switches, drng.randint(*B["past_replacements"]) + (1 if cfg["planted"]["disposed_answering"] else 0))
        for i, name in enumerate(picks):
            reg = by_serial[baseline[name][1]]
            old = self.serial(reg["class"], drng)
            at = self.start - timedelta(days=drng.uniform(5, 60))
            reg["since"] = iso(at)
            dispose(reg["class"], old, at + timedelta(hours=drng.uniform(24, 72)), f"Replaced at {name} (failed fan tray)")
            reg["ref"] = disposals[-1]["certificate"]
            if i == 0 and cfg["planted"]["disposed_answering"]:
                baseline[name] = (baseline[name][0], old)
                planted.append({"kind": "disposed_answering", "serial": old, "slot": name, "certificate": disposals[-1]["certificate"]})
        # ---- the month's transactions
        trng = _rng(self.seed, "records")

        def rec(at: datetime) -> datetime:
            return at + timedelta(minutes=trng.uniform(*B["record_after_min"]))

        def add(at: datetime, a: dict, action: str, location: str, ref: str, by: str = "IT Partner") -> None:
            tx.append({"at": iso(at), "tag": a["tag"], "class": a["class"], "serial": a["serial"], "action": action,
                       "location": location, "ref": ref, "by": by})

        def tag(cls: str, serial: str, location: str, at: datetime, maintainer: str = "IT Partner") -> dict:
            return by_serial.get(serial) or new(cls, serial, "installed", location, maintainer, at, opening=False)
        # rack receipts (M1) and power-on (M4) in Hall B
        for r, status, m1 in racks_in:
            rk = r["rack"]
            m4 = md.get(rk, {}).get("M4")
            for kind, slot, serial, _ in rack_items[rk]:
                c = cls_of[kind]
                if status == "receive":
                    a = new(c["class"], serial, "received", slot, c["maintainer"], m1, opening=False)
                    add(rec(m1), a, "receive", slot, f"{rk} M1")
                if status in ("receive", "received") and m4 and self.start <= m4 < self.end:
                    add(rec(m4), by_serial[serial], "install", slot, f"{rk} M4")
        # spares received this month (their receipt is recorded below, with the OEM's delivery)
        for cls in sorted(receipts):
            for r in receipts[cls]:
                for sr in r["serials"]:
                    new(cls, sr, "in_stock", CAGE, "IT Partner", r["at"], opening=False)
        for cls, at, sr in direct:
            new(cls, sr, "in_stock", CAGE, "IT Partner", at, opening=False)
        for q in shelf_receipts:
            a = new(q["class"], q["place"]["serial"], "in_stock", shelf_of(q["hall"]), "IT Partner", q["at"], opening=False)
            add(rec(q["at"]), a, "receive", shelf_of(q["hall"]), "Storage shelf emergency receipt" if q["emergency"] else "Storage shelf replenishment")
        # ticket parts
        for at, t, p in parts:
            slot = slot_of_part(p["part"], p["location"]) or p["location"]
            if p.get("removed_serial"):
                a = tag(p["part"], p["removed_serial"], slot, at)
                add(rec(at), a, "remove", FAILED_CAGE, t["number"])
            if p.get("installed_serial"):
                add(rec(at), by_serial[p["installed_serial"]], "install", slot, t["number"])
        # RMA shipments, and the drives pulled from each tray before it ships (HO-5)
        removed_at = {r["serial"]: parse(r["removed_at"]) for r in self.rma}
        cust = {r["drive_serial"]: r for r in self.custody}
        cert = {r["drive_serial"]: r for r in self.certs}
        for d in self.tray_drives:
            if d["drive_serial"] not in cust and d["drive_serial"] not in cert:
                continue                      # never recorded as pulled
            t0 = removed_at.get(d["tray_serial"], self.start)
            a = new("E1.S drive", d["drive_serial"], "installed", f"Tray {d['tray_serial']} bay {d['bay']}", "IT Partner", t0, opening=False)
            add(rec(t0), a, "remove", FAILED_CAGE, d["ticket"])
            if d["drive_serial"] in cust:
                c = cust[d["drive_serial"]]
                add(rec(parse(c["handed_over_at"])), a, "custody", SECURITY, d["ticket"], "Security Partner")
            if d["drive_serial"] in cert:
                c = cert[d["drive_serial"]]
                add(rec(parse(c["destroyed_at"])), a, "destroy", SECURITY, c["certificate"], "Security Partner")
        for r in self.rma:
            a = tag(r["fru"], r["serial"], "", parse(r["removed_at"]))
            add(rec(parse(r["shipped_at"])), a, "rma_ship", OEM, r["ticket"])
        for c in self.stg_custody:
            add(rec(parse(c["handed_over_at"])), by_serial[c["drive_serial"]], "custody", SECURITY, c["ticket"], "Security Partner")
        # ledger receipts, each unit a replacement the OEM delivered; the OEM's portal
        orng = _rng(self.seed, "oem")
        portal: list[dict] = []
        rma_n = [orng.randint(70000, 80000)]
        open_rma: dict[str, list[dict]] = {}
        for r in sorted(self.rma, key=lambda r: (r["shipped_at"], r["serial"])):
            rma_n[0] += 1
            got = parse(r["shipped_at"]) + timedelta(days=orng.uniform(*B["oem_receipt_d"]))
            row = {"rma": f"RMA-{rma_n[0]}", "fru": r["fru"], "failed_serial": r["serial"], "ticket": r["ticket"],
                   "shipped_to_oem_at": r["shipped_at"], "oem_received_at": iso(got) if got < self.end else "",
                   "replacement_serial": "", "replacement_shipped_at": "", "delivered_at": "", "pod": ""}
            portal.append(row)
            if row["oem_received_at"]:
                open_rma.setdefault(r["fru"], []).append(row)

        def pre_window(fru: str) -> dict:
            rma_n[0] += 1
            sh = self.start - timedelta(days=orng.uniform(8, 30))
            row = {"rma": f"RMA-{rma_n[0]}", "fru": fru, "failed_serial": self.serial(fru, orng), "ticket": "",
                   "shipped_to_oem_at": iso(sh), "oem_received_at": iso(sh + timedelta(days=orng.uniform(*B["oem_receipt_d"]))),
                   "replacement_serial": "", "replacement_shipped_at": "", "delivered_at": "", "pod": ""}
            portal.append(row)
            return row

        def deliver(row: dict, serial: str, at: datetime) -> None:
            row.update(replacement_serial=serial, replacement_shipped_at=iso(at - timedelta(days=orng.uniform(1, 3))),
                       delivered_at=iso(at), pod="Signed at the AUS-1 dock")

        for cls in sorted(receipts):
            for r in receipts[cls]:
                for s in r["serials"]:
                    dl = r["at"] - timedelta(hours=orng.uniform(*B["dock_to_cage_h"]))
                    cands = [x for x in open_rma.get(cls, []) if not x["replacement_serial"] and parse(x["oem_received_at"]) <= dl - timedelta(days=1)]
                    deliver(cands[0] if cands else pre_window(cls), s, dl)
                    add(rec(r["at"]), by_serial[s], "receive", CAGE, cands[0]["rma"] if cands else portal[-1]["rma"])
        for cls, at, s in direct:
            dl = at - timedelta(hours=orng.uniform(0.2, 1.0))
            cands = [x for x in open_rma.get(cls, []) if not x["replacement_serial"] and parse(x["oem_received_at"]) <= dl - timedelta(days=1)]
            deliver(cands[0] if cands else pre_window(cls), s, dl)
            add(rec(at), by_serial[s], "receive", CAGE, cands[0]["rma"] if cands else portal[-1]["rma"])
        # decoys: in transit at month end, and one delivered inside the 24 hours
        spare_rma = [x for c in sorted(open_rma) for x in open_rma[c] if not x["replacement_serial"]]
        orng.shuffle(spare_rma)
        decoys: list[dict] = []
        for x in spare_rma[:orng.randint(*B["in_transit"])]:
            x.update(replacement_serial=self.serial(x["fru"], orng), replacement_shipped_at=iso(self.end - timedelta(hours=orng.uniform(6, 40))))
            decoys.append({"kind": "in_transit", "rma": x["rma"]})
        late = pre_window(orng.choice(sorted(cfg["spares"]["serialized"][:4])))
        deliver(late, self.serial(late["fru"], orng), self.end - timedelta(hours=orng.uniform(*B["late_delivery_h"])))
        decoys.append({"kind": "late_delivery", "rma": late["rma"]})
        if cfg["planted"]["rma_not_received"]:
            fru = orng.choice(["Compute tray", "PSU (5.5 kW)", "800G OSFP optic", "Power shelf"])
            cands = [x for x in open_rma.get(fru, []) if not x["replacement_serial"]
                     and parse(x["oem_received_at"]) < self.end - timedelta(days=4)]
            row = cands[0] if cands else pre_window(fru)
            lo = max(self.start, parse(row["oem_received_at"])) + timedelta(days=1)
            at = lo + timedelta(hours=orng.uniform(0, max(1.0, (self.end - timedelta(days=2) - lo).total_seconds() / 3600)))
            deliver(row, self.serial(fru, orng), at)
            planted.append({"kind": "rma_not_received", "rma": row["rma"], "serial": row["replacement_serial"]})
        # some transactions recorded late, inside REG-2's 4 hours (decoy)
        late_ok = [i for i, x in enumerate(tx) if x["action"] in ("install", "remove") and x["ref"].startswith("INC")]
        for i in sorted(trng.sample(late_ok, min(len(late_ok), trng.randint(*B["late_records"])))):
            x = tx[i]
            x["at"] = iso(parse(x["at"]) + timedelta(hours=trng.uniform(*B["late_record_h"])) - timedelta(minutes=B["record_after_min"][1]))
            decoys.append({"kind": "late_record", "tag": x["tag"], "action": x["action"], "ref": x["ref"]})
        tx.sort(key=lambda x: (x["at"], x["tag"], x["action"]))
        portal.sort(key=lambda x: x["rma"])
        base = [{"slot": s, "source": v[0], "serial": v[1]} for s, v in sorted(baseline.items())]
        return {"assets": assets, "tx": tx, "baseline": base, "portal": portal, "disposals": sorted(disposals, key=lambda x: x["certificate"]),
                "key": {"planted": planted, "decoys": decoys}}


def _dump(path: Path, rows: list[dict], cols: list[str]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


def write_assets(layer: AssetLayer, out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, Any]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    files = {
        "register_opening.csv": (out["assets"], ["tag", "class", "serial", "status", "location", "maintainer", "since", "ref"]),
        "register_transactions.csv": (out["tx"], ["at", "tag", "class", "serial", "action", "location", "ref", "by"]),
        "inventory_baseline.csv": (out["baseline"], ["slot", "source", "serial"]),
        "oem_rma.csv": (out["portal"], ["rma", "fru", "failed_serial", "ticket", "shipped_to_oem_at", "oem_received_at",
                                        "replacement_serial", "replacement_shipped_at", "delivered_at", "pod"]),
        "disposals.csv": (out["disposals"], ["certificate", "serial", "class", "disposed_at", "reason", "method", "recycler", "witness"]),
    }
    for name, (rows, cols) in files.items():
        _dump(dest / name, rows, cols)
    (dest / "answer_key.json").write_text(json.dumps(out["key"], indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    man = {"disclaimer": layer.cfg["framing"], "source": source, "window": layer.window,
           "files": {n: len(r) for n, (r, _) in files.items()}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
