"""The asset register: its daily reconciliation with what the devices report and with every record that moves an asset.

The register (``data/assets/``) is what the partners record; everything it is checked against is a record already
written for the month or the devices' own answers: the site topology, the Redfish inventory changes, the storage drive
log and drive tickets, the Hall B first answers and the management switches' hours up (``data/telemetry/mgmt``), the
spares ledger, RMA shipments, the OEM's RMA portal, custody handovers, destruction and disposal certificates, the
deployment milestones, and the Landlord's maintenance records and work orders. Interface Agreement section 11 (REG-1 to REG-6).

Agreements (every case reconciles, or is explained by a finding; each returns cases checked and disagreements):

1. installed: at every daily scan, every answering slot answers with a serial the register holds there (REG-4), allowing
   REG-2's 4 hours either way for the record to catch up with the hardware.
2. stock: at every daily cut, the register's spares in the cage equal the spares ledger's balance, class by class.
3. tickets: every part a ticket replaced is removed and installed in the register, at that location, citing the ticket,
   within 4 hours of the work (REG-2).
4. rma: every RMA shipment is in the register, and every register RMA shipment is a shipment.
5. returns: every replacement the OEM delivered (carrier proof of delivery) is received into the register within 24
   hours (REG-3).
6. media: every drive pulled from a shipped tray is in Security Partner custody and destroyed under its certificate
   before the tray ships; every drive pulled from a storage node is in custody within 24 hours (HO-5).
7. disposals: every disposal certificate names a disposed register asset, and every disposed asset has one (REG-5).
8. directory: every device in the directory is in the register at its location at month end, or on order.
9. landlord: every facility unit the Landlord's maintenance records and work orders name is registered, installed.

Findings (records that do not reconcile; new here, numbered AR-n):

* live_in_stock: a device answers with a serial the register lists in the spares cage.
* rma_not_received: an OEM replacement delivered more than 24 hours ago and never received.
* disposed_answering: a device answers with a serial the register lists as disposed under a certificate.
A disagreement another check already explains (IT engine unverified_swap and spares_drift, Security
media_shipped_without_destruction, storage custody_gap and wrong_bay) is listed as corroboration, not as a new finding.
Anything else that does not reconcile is a finding of its own kind (serial_mismatch, stock_mismatch, media_unaccounted,
unrecorded_work), which no planted case produces.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scorecard.synthetic.assets import (CAGE, STORAGE_SHELF, load_config, parse, iso, slot_of_part, slot_of_resource, work_time,
                                        _csv, _jsonl)
from scorecard.telemetry import Check

ON_SITE = ("installed", "received")
STATUS_OF = {"receive": None, "install": "installed", "remove": "removed", "rma_ship": "at_oem", "custody": "in_custody",
             "destroy": "destroyed", "dispose": "disposed"}
STATUS_NAME = {"installed": "installed", "received": "received, not yet installed", "in_stock": "in stock in the spares cage",
               "removed": "removed, in the failed-parts cage", "at_oem": "shipped to the OEM", "in_custody": "in Security Partner custody",
               "destroyed": "destroyed", "disposed": "disposed"}
CONTRACT = {
    "live_in_stock": "Interface Agreement REG-2 and REG-6 (every install recorded by serial; serial-level cycle counts)",
    "rma_not_received": "Interface Agreement REG-3 (a delivery received into the register and the spares ledger within 24 hours)",
    "disposed_answering": "Interface Agreement REG-5 (a disposed serial that answers on a network is an asset whose disposal is unconfirmed)",
    "serial_mismatch": "Interface Agreement REG-2 and REG-4",
    "stock_mismatch": "Interface Agreement REG-2; IT Partner SLA spares",
    "media_unaccounted": "Interface Agreement HO-5 and REG-2",
    "unrecorded_work": "Interface Agreement REG-2",
}
ORDER = ["live_in_stock", "rma_not_received", "disposed_answering", "serial_mismatch", "stock_mismatch", "media_unaccounted", "unrecorded_work"]


@dataclass
class AssetData:
    dir: Path
    sample: Path
    cfg: dict
    manifest: dict
    opening: list[dict]
    tx: list[dict]
    baseline: list[dict]
    portal: list[dict]
    disposals: list[dict]
    topology: dict
    inv: list[dict]
    drive_events: list[dict]
    stg_tickets: list[dict]
    stg_custody: list[dict]
    tickets: list[dict]
    ledger: list[dict]
    rma: list[dict]
    tray_drives: list[dict]
    custody: list[dict]
    certs: list[dict]
    milestones: list[dict]
    first_answer: dict
    switch_up: dict
    pm: list[dict]
    work_orders: list[dict]
    known: dict = field(default_factory=dict)

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def end(self) -> datetime:
        return parse(self.manifest["window"]["end"])


def load(assets_dir: str | Path, sample_dir: str | Path, sec_dir: str | Path, mgmt_dir: str | Path, storage_dir: str | Path,
         known: dict | None = None, cfg: dict | None = None) -> AssetData:
    a, s, sec, mg, st = (Path(x) for x in (assets_dir, sample_dir, sec_dir, mgmt_dir, storage_dir))
    up: dict[str, set[str]] = {}
    for r in _csv(mg / "switch_hourly.csv"):
        if int(r["up_min"]) > 0:
            up.setdefault(r["switch"], set()).add(r["hour"])
    return AssetData(
        dir=a, sample=s, cfg=cfg or load_config(), manifest=json.loads((a / "manifest.json").read_text(encoding="utf-8")),
        opening=_csv(a / "register_opening.csv"), tx=_csv(a / "register_transactions.csv"), baseline=_csv(a / "inventory_baseline.csv"),
        portal=_csv(a / "oem_rma.csv"), disposals=_csv(a / "disposals.csv"),
        topology=json.loads((s / "site" / "topology.json").read_text(encoding="utf-8")),
        inv=[e for e in _jsonl(s / "telemetry" / "redfish_inventory_changes.jsonl") if e["property"] == "SerialNumber"],
        drive_events=_jsonl(st / "drive_events.jsonl"), stg_tickets=json.loads((st / "tickets.json").read_text(encoding="utf-8")),
        stg_custody=_csv(st / "custody.csv"), tickets=json.loads((s / "vendor" / "tickets.json").read_text(encoding="utf-8")),
        ledger=_csv(s / "vendor" / "spares_ledger.csv"), rma=_csv(s / "vendor" / "rma_shipments.csv"),
        tray_drives=_csv(sec / "tray_drives.csv"), custody=_csv(sec / "chain_of_custody.csv"), certs=_csv(sec / "destruction_certificates.csv"),
        milestones=_csv(s / "vendor" / "deployment_milestones.csv"),
        first_answer=json.loads((mg / "first_answer.json").read_text(encoding="utf-8")) if (mg / "first_answer.json").exists() else {},
        switch_up=up, pm=_csv(s / "landlord" / "pm_records.csv"),
        work_orders=json.loads((s / "landlord" / "work_orders.json").read_text(encoding="utf-8")), known=known or {})


def known_findings(sample_dir: str | Path, sec_dir: str | Path, storage_dir: str | Path, mgmt_dir: str | Path) -> dict[str, list[dict]]:
    """What the other checks already found that touches the register: the IT engine, the Security engine, and the storage
    checks, each reduced to the fields the register's corroboration needs."""
    from scorecard import telemetry_storage as TS
    from scorecard.connectors import FileConnector
    from scorecard.engine import run_engine
    from scorecard.engine.security import run_security
    from scorecard.sla_model import PARTNER_FILES, load_sla
    from scorecard.synthetic.telemetry_storage import load_config as storage_cfg
    it = run_engine(load_sla(), FileConnector(str(sample_dir))).findings
    sec = run_security(load_sla(PARTNER_FILES["security"]), sample_dir, sec_dir).findings
    st = TS.findings(TS.load(storage_dir, sample_dir, mgmt_dir), storage_cfg())
    out = {"it": [], "security": [], "storage": []}
    for f in it:
        if f.type in ("unverified_swap", "spares_drift"):
            out["it"].append({"id": f.id, "type": f.type, "tickets": f.tickets, "unit": f.unit, "at": iso(f.observed_at) if f.observed_at else None,
                              "claimed": f.metrics.get("claimed_serial"), "removed": f.metrics.get("removed_serial")})
    for f in sec:
        if f.type == "media_shipped_without_destruction":
            out["security"].append({"id": f.id, "type": f.type, "tickets": f.tickets, "serial": f.keys.get("drive_serial")})
    for f in st:
        if f["kind"] in ("custody_gap", "wrong_bay"):
            out["storage"].append({"id": f["id"], "type": f["kind"], "tickets": f["refs"], "node": f["devices"][0],
                                   "serial": f.get("serial"), "bays": [f.get("ticket_bay"), f.get("changed_bay")]})
    return out


# ----------------------------------------------------------------------------- the register and the devices over time
class Register:
    """The register replayed: each asset's status and location at any time."""

    def __init__(self, t: AssetData):
        self.t = t
        self.asset: dict[str, dict] = {a["tag"]: dict(a) for a in t.opening}
        for x in t.tx:
            self.asset.setdefault(x["tag"], {"tag": x["tag"], "class": x["class"], "serial": x["serial"], "status": None,
                                             "location": "", "maintainer": x["by"], "since": x["at"], "ref": x["ref"]})
        self.by_serial = {a["serial"]: tag for tag, a in self.asset.items()}
        self.times = [parse(x["at"]) for x in t.tx]
        self._cache: dict[int, tuple[dict, dict]] = {}

    def state(self, at: datetime) -> tuple[dict[str, tuple[str, str]], dict[str, list[str]]]:
        """(tag -> (status, location), slot -> serials held there) after every transaction up to ``at``."""
        n = bisect_right(self.times, at)
        if n not in self._cache:
            st = {o["tag"]: (o["status"], o["location"]) for o in self.t.opening}
            for x in self.t.tx[:n]:
                s = STATUS_OF[x["action"]]
                if s is None:
                    s = "in_stock" if x["location"] in (CAGE, STORAGE_SHELF) else "received"
                st[x["tag"]] = (s, x["location"])
            held: dict[str, list[str]] = {}
            for tag, (s, loc) in st.items():
                if s in ON_SITE:
                    held.setdefault(loc, []).append(self.asset[tag]["serial"])
            self._cache[n] = (st, held)
        return self._cache[n]

    def status_of(self, serial: str, at: datetime) -> tuple[str, str] | None:
        tag = self.by_serial.get(serial)
        return self.state(at)[0].get(tag) if tag else None

    def history(self, tag: str) -> list[dict]:
        a = self.asset[tag]
        out = [{"at": a["since"], "action": "opening", "status": a["status"], "location": a["location"], "ref": a["ref"]}] if a["status"] else []
        for x in self.t.tx:
            if x["tag"] == tag:
                s = STATUS_OF[x["action"]] or ("in_stock" if x["location"] in (CAGE, STORAGE_SHELF) else "received")
                out.append({"at": x["at"], "action": x["action"], "status": s, "location": x["location"], "ref": x["ref"], "by": x["by"]})
        return out


class Devices:
    """What every slot answers with, and whether it answers, at any time."""

    def __init__(self, t: AssetData):
        self.t = t
        sw = {x["redfish"]: x["name"] for r in t.topology["racks"] for x in r["switch_trays"]}
        self.base = {r["slot"]: r["serial"] for r in t.baseline}
        self.source = {r["slot"]: r["source"] for r in t.baseline}
        self.changes: dict[str, list[tuple[datetime, str | None]]] = {}
        for e in sorted(t.inv, key=lambda e: e["observed_at"]):
            s = slot_of_resource(e["resource"], e["host"], sw)
            if s:
                self.changes.setdefault(s, []).append((parse(e["observed_at"]), e["new_value"]))
        for e in t.drive_events:
            if e["event"] in ("Removed", "Inserted"):
                self.changes.setdefault(f"{e['node']} {e['bay']}", []).append((parse(e["timestamp"]), e["serial"] if e["event"] == "Inserted" else None))
        for v in self.changes.values():
            v.sort(key=lambda x: x[0])
        self.first = {k: parse(v) for k, v in t.first_answer.items() if v}

    def serial(self, slot: str, at: datetime) -> str | None:
        s = self.base.get(slot)
        for when, v in self.changes.get(slot, []):
            if when > at:
                break
            s = v
        return s

    def answering(self, slot: str, at: datetime) -> bool:
        if re.match(r"[a-c]\d{2}-mgmt\d$", slot):
            return at.strftime("%Y-%m-%dT%H:00:00Z") in self.t.switch_up.get(slot, set())
        key = slot.split(" PSU ")[0]
        if key in self.t.first_answer:
            return key in self.first and self.first[key] <= at
        return True


def scans(t: AssetData, hour: int) -> list[datetime]:
    d = t.start.replace(hour=hour, minute=0, second=0)
    if d < t.start:
        d += timedelta(days=1)
    out = []
    while d < t.end:
        out.append(d)
        d += timedelta(days=1)
    return out


# ----------------------------------------------------------------------------- reconciliation
def reconcile(t: AssetData) -> dict[str, Any]:
    """Every case of every agreement, with the disagreements found (before any finding explains them)."""
    cfg, ck = t.cfg, t.cfg["checks"]
    g = timedelta(hours=ck["record_h"])
    R, D = Register(t), Devices(t)
    end = t.end
    clamp = lambda x: min(x, end)  # noqa: E731
    out: dict[str, Any] = {"R": R, "D": D, "cases": {}, "bad": {}}

    def case(name: str, ok: bool, what: Any) -> None:
        out["cases"][name] = out["cases"].get(name, 0) + 1
        if not ok:
            out["bad"].setdefault(name, []).append(what)
    # 1. installed
    for T in scans(t, cfg["scan"]["hour_utc"]):
        held, held_g = R.state(T)[1], R.state(clamp(T + g))[1]
        for slot in D.base:
            if not D.answering(slot, T):
                continue
            rep = D.serial(slot, T)
            if rep is None:
                continue
            ok = rep in held.get(slot, []) or rep in held_g.get(slot, []) or D.serial(slot, clamp(T + g)) in held.get(slot, [])
            case("installed", ok, {"at": T, "slot": slot, "reported": rep, "held": sorted(held.get(slot, []))})
    # 2. stock
    ser = cfg["spares"]["serialized"]
    led: dict[str, list[tuple[datetime, int]]] = {}
    opening: dict[str, int] = {}
    for r in t.ledger:
        opening.setdefault(r["fru"], int(r["balance_after"]) - int(r["qty"]))
        led.setdefault(r["fru"], []).append((parse(r["timestamp"]), int(r["balance_after"])))

    def bal(fru: str, at: datetime) -> int | None:
        b = opening.get(fru)
        for when, v in led.get(fru, []):
            if when > at:
                break
            b = v
        return b

    def count(fru: str, at: datetime) -> int:
        st = R.state(at)[0]
        return sum(1 for tag, (s, loc) in st.items() if s == "in_stock" and loc == CAGE and R.asset[tag]["class"] == fru)
    moves: dict[str, list[datetime]] = {}
    for x in t.tx:
        moves.setdefault(x["class"], []).append(parse(x["at"]))
    for T in scans(t, cfg["scan"]["cut_hour_utc"]):
        for fru in ser:
            lb = bal(fru, T)
            if lb is None:
                continue
            rc = count(fru, T)
            lb = max(lb, 0)                 # a ledger below zero issued parts it did not hold: the cage is empty
            # the ledger issues a part when it leaves the cage, the register when it is installed: either record may
            # trail the other by REG-2's 4 hours, so the cut agrees if the two meet anywhere inside that span
            near = [x for x in moves.get(fru, []) if T - g <= x <= T + g]
            ok = rc == lb or any(count(fru, x) == lb for x in near) or any(max(bal(fru, y), 0) == rc for y, _ in led.get(fru, []) if T - g <= y <= T + g)
            case("stock", ok, {"at": T, "fru": fru, "register": rc, "ledger": lb})
    # 3. tickets
    txs: dict[tuple[str, str], list[dict]] = {}
    for x in t.tx:
        txs.setdefault((x["serial"], x["action"]), []).append(x)
    for tk in t.tickets + t.stg_tickets:
        for p in tk.get("parts_used", []):
            at = work_time(tk, p.get("removed_serial"))
            slot = slot_of_part(p["part"], p["location"]) or p["location"]
            for action, s in (("remove", p.get("removed_serial")), ("install", p.get("installed_serial"))):
                if not s:
                    continue
                hit = [x for x in txs.get((s, action), []) if x["ref"] == tk["number"] and abs(parse(x["at"]) - at) <= g
                       and (action == "remove" or x["location"] == slot)]
                case("tickets", bool(hit), {"ticket": tk["number"], "serial": s, "action": action, "at": at})
    # 4. rma
    shipped = {(r["serial"], r["ticket"]): r for r in t.rma}
    for r in t.rma:
        hit = [x for x in txs.get((r["serial"], "rma_ship"), []) if x["ref"] == r["ticket"] and abs(parse(x["at"]) - parse(r["shipped_at"])) <= g]
        case("rma", bool(hit), {"serial": r["serial"], "ticket": r["ticket"], "what": "shipment not in the register"})
    for x in t.tx:
        if x["action"] == "rma_ship":
            case("rma", (x["serial"], x["ref"]) in shipped, {"serial": x["serial"], "ticket": x["ref"], "what": "register shipment with no RMA record"})
    # 5. returns
    rh = timedelta(hours=ck["receive_h"])
    for p in t.portal:
        if not p["delivered_at"] or parse(p["delivered_at"]) + rh > end:
            continue
        dl = parse(p["delivered_at"])
        hit = [x for x in txs.get((p["replacement_serial"], "receive"), []) if dl <= parse(x["at"]) <= dl + rh]
        case("returns", bool(hit), {"rma": p["rma"], "serial": p["replacement_serial"], "fru": p["fru"], "delivered": p["delivered_at"]})
    # 6. media
    ships = {r["ticket"]: parse(r["shipped_at"]) for r in t.rma}
    certs = {c["drive_serial"]: c for c in t.certs}
    for d in t.tray_drives:
        if d["ticket"] not in ships:
            continue
        sh = ships[d["ticket"]]
        cu = [x for x in txs.get((d["drive_serial"], "custody"), []) if parse(x["at"]) <= sh]
        de = [x for x in txs.get((d["drive_serial"], "destroy"), []) if parse(x["at"]) <= sh + g]
        c = certs.get(d["drive_serial"])
        ok = bool(cu and de and c and de[0]["ref"] == c["certificate"] and parse(c["destroyed_at"]) <= sh)
        case("media", ok, {"serial": d["drive_serial"], "ticket": d["ticket"], "tray": d["tray_serial"], "shipped": iso(sh)})
    ch = timedelta(hours=ck["custody_h"])
    for e in t.drive_events:
        if e["event"] != "Removed" or parse(e["timestamp"]) + ch > end:
            continue
        rm = parse(e["timestamp"])
        cu = [x for x in txs.get((e["serial"], "custody"), []) if rm <= parse(x["at"]) <= rm + ch + g]
        case("media", bool(cu), {"serial": e["serial"], "ticket": None, "node": e["node"], "bay": e["bay"], "removed": e["timestamp"]})
    # 7. disposals
    disp = {d["serial"]: d for d in t.disposals}
    st_end = R.state(end)[0]
    for d in t.disposals:
        tag = R.by_serial.get(d["serial"])
        ok = bool(tag) and R.asset[tag]["status"] == "disposed" and R.asset[tag]["ref"] == d["certificate"]
        case("disposals", ok, {"serial": d["serial"], "certificate": d["certificate"]})
    for tag, (s, _) in st_end.items():
        if s == "disposed":
            case("disposals", R.asset[tag]["serial"] in disp, {"serial": R.asset[tag]["serial"], "certificate": None})
    # 8. directory
    from scorecard import devices as DV
    dev = DV.load()["devices"]
    md = {r["rack"] for r in t.milestones if r["milestone"] == "M1" and r["reported_complete_at"] and parse(r["reported_complete_at"]) < end}
    prod = {r["rack"] for r in t.topology["racks"] if r["state"] == "production"}
    held_end = R.state(end)[1]
    scope = set(cfg["classes"]) | set(cfg["facility_kinds"])
    for name, x in sorted(dev.items()):
        if x["kind"] not in scope:
            continue
        rk = {"rack": name}.get(x["kind"]) or (name[:3].upper() if re.match(r"[a-c]\d{2}-", name) else
                                               name[:3] if re.match(r"[A-C]\d{2}_", name) else None)
        if x["kind"] == "rack":
            rk = name
        on_order = rk is not None and rk not in prod and rk not in md
        case("directory", on_order or len(held_end.get(name, [])) == 1, {"device": name, "held": held_end.get(name, [])})
    # 9. landlord
    for unit in sorted({r["asset"] for r in t.pm} | {w["unit"] for w in t.work_orders}):
        name = unit.split("/")[0]
        if name not in dev or dev[name]["kind"] not in cfg["facility_kinds"]:
            continue
        held = held_end.get(name, [])
        ok = len(held) == 1 and R.asset[R.by_serial[held[0]]]["maintainer"] == "Landlord"
        case("landlord", ok, {"unit": unit})
    return out


AGREEMENTS = [
    ("installed", "Every answering slot answers with the serial the register holds there, at every daily scan"),
    ("stock", "The register's spares in the cage equal the spares ledger, class by class, at every daily cut"),
    ("tickets", "Every part a ticket replaced is removed and installed in the register within 4 hours, citing the ticket"),
    ("rma", "Every RMA shipment is in the register, and every register shipment is an RMA shipment"),
    ("returns", "Every OEM replacement delivered is received into the register within 24 hours"),
    ("media", "Every pulled drive is in Security Partner custody, and a tray's drives are destroyed before it ships"),
    ("disposals", "Every disposal certificate names a disposed register asset, and every disposed asset has one"),
    ("directory", "Every device in the directory is in the register at its location, or on order"),
    ("landlord", "Every facility unit in the Landlord's maintenance records and work orders is registered and installed"),
]


def analyse(t: AssetData) -> dict[str, Any]:
    """Findings, corroborations, and the agreements with every disagreement either explained or listed."""
    rc = reconcile(t)
    R, D = rc["R"], rc["D"]
    known = t.known
    findings: list[dict] = []
    corro: list[dict] = []
    explained: dict[str, int] = {}
    misses: dict[str, list[str]] = {}

    def explain(name: str, n: int = 1) -> None:
        explained[name] = explained.get(name, 0) + n

    # ---- installed: group a slot's disagreements, then classify by what the register says of the answering serial
    groups: dict[tuple, list[dict]] = {}
    for b in rc["bad"].get("installed", []):
        groups.setdefault((b["slot"], b["reported"], tuple(b["held"])), []).append(b)
    for (slot, rep, held), bs in groups.items():
        a, z = bs[0]["at"], bs[-1]["at"]
        st = R.status_of(rep, a)
        kn = next((f for f in known.get("it", []) if f["type"] == "unverified_swap" and f["unit"] == slot and f["removed"] == rep), None)
        if kn is None and " Bay" in slot:
            node, bay = slot.split(" ")
            kn = next((f for f in known.get("storage", []) if f["type"] == "wrong_bay" and f["node"] == node and bay in f["bays"]), None)
        if kn:
            explain("installed", len(bs))
            corro.append({"source": "IT engine" if kn["type"] == "unverified_swap" else "Storage", "finding": kn["id"], "type": kn["type"],
                          "refs": kn["tickets"], "text": f"{slot} answers with {rep}; the register holds {', '.join(held) or 'nothing'} there "
                                                         f"({len(bs)} scan{'s' * (len(bs) > 1)} from {iso(a)})"})
            continue
        tag = R.by_serial.get(rep)
        hist = R.asset[tag] if tag else None
        reg_holder = ", ".join(held) or "no asset"
        src = D.source.get(slot, "Redfish")
        how = "Redfish SerialNumber" if src == "Redfish" else "SNMP entPhysicalSerialNum"
        base = [f"{how}: {slot} answered with {rep} at {len(bs)} daily scan{'s' * (len(bs) > 1)}, {iso(a)} to {iso(z)}",
                f"Register: {slot} holds {reg_holder}"]
        moved = [x for x in t.tx if x["serial"] in [rep] + list(held)]
        if st and st[0] in ("in_stock", "disposed"):
            explain("installed", len(bs))
        if st and st[0] == "in_stock":
            findings.append({"kind": "live_in_stock", "title": f"{rep} answers in {slot}; the register has it in the cage",
                             "summary": f"The register lists {rep} as a spare in the cage and {reg_holder} in {slot}, but the device answers with "
                                        f"{rep}. The cage's quantity count still matches the ledger, so the unit on the shelf in its place is likely "
                                        f"{reg_holder}, a removed part back in stock (inferred; a serial-level count of the cage settles it).",
                             "owner": "IT Partner", "contract": CONTRACT["live_in_stock"],
                             "lines": base + [f"Register: {rep} ({hist['tag']}) in stock in the {CAGE} since {hist['since']}",
                                              ] + (["No ticket or register transaction moves either unit this month"] if not moved else []),
                             "refs": [hist["tag"]], "devices": [slot], "serial": rep, "from": iso(a), "to": iso(z)})
        elif st and st[0] == "disposed":
            cert = next((d for d in t.disposals if d["serial"] == rep), None)
            findings.append({"kind": "disposed_answering", "title": f"{slot} answers with {rep}, disposed under {cert['certificate'] if cert else 'no certificate'}",
                             "summary": f"The register records {rep} as replaced at {slot} and disposed"
                                        f"{(' under ' + cert['certificate']) if cert else ''}, "
                                        f"and {reg_holder} installed in its place, but {slot} still answers with {rep}. The disposal certificate "
                                        "cannot cover this unit, and the replacement's whereabouts are unknown.",
                             "owner": "IT Partner", "contract": CONTRACT["disposed_answering"],
                             "lines": base + ([f"Disposal certificate {cert['certificate']}: {rep} {cert['method'].lower()} by {cert['recycler']}, "
                                               f"{cert['disposed_at']}, witnessed by the {cert['witness']}"] if cert else [])
                                      + ([f"Register: {held[0]} recorded installed at {slot} on {R.asset[R.by_serial[held[0]]]['since']}"] if held else []),
                             "refs": [cert["certificate"]] if cert else [], "devices": [slot], "serial": rep, "from": iso(a), "to": iso(z)})
        else:
            findings.append({"kind": "serial_mismatch", "title": f"{slot} answers with {rep}; the register holds {reg_holder}",
                             "summary": f"{slot} answers with a serial the register does not hold there "
                                        f"({STATUS_NAME.get(st[0], st[0]) if st else 'not in the register'}).",
                             "owner": "IT Partner", "contract": CONTRACT["serial_mismatch"], "lines": base,
                             "refs": [], "devices": [slot], "serial": rep, "from": iso(a), "to": iso(z)})
    # ---- stock
    for b in rc["bad"].get("stock", []):
        kn = next((f for f in known.get("it", []) if f["type"] == "spares_drift" and f["unit"] == b["fru"] and f["at"]
                   and parse(f["at"]) - timedelta(hours=24) <= b["at"]), None)
        if kn:
            explain("stock")
            corro.append({"source": "IT engine", "finding": kn["id"], "type": kn["type"], "refs": kn["tickets"],
                          "text": f"{b['fru']} at the {iso(b['at'])} cut: register {b['register']} in stock, ledger {b['ledger']}"})
        else:
            findings.append({"kind": "stock_mismatch", "title": f"{b['fru']}: register {b['register']}, ledger {b['ledger']}",
                             "summary": f"At the {iso(b['at'])} cut the register holds {b['register']} {b['fru']} spares and the ledger {b['ledger']}.",
                             "owner": "IT Partner", "contract": CONTRACT["stock_mismatch"], "lines": [], "refs": [], "devices": [],
                             "serial": None, "from": iso(b["at"]), "to": None, "fru": b["fru"]})
    # ---- returns
    for b in rc["bad"].get("returns", []):
        explain("returns")
        p = next(x for x in t.portal if x["rma"] == b["rma"])
        led = [r for r in t.ledger if r["transaction"] == "receive" and r["fru"] == p["fru"]
               and parse(p["delivered_at"]) <= parse(r["timestamp"]) <= parse(p["delivered_at"]) + timedelta(hours=t.cfg["checks"]["receive_h"])]
        findings.append({"kind": "rma_not_received", "title": f"{p['fru']} {p['replacement_serial']} delivered, never received",
                         "summary": f"The OEM's carrier delivered replacement {p['replacement_serial']} ({p['rma']}) to the dock at {p['delivered_at']}, "
                                    "but neither the register nor the spares ledger received it within 24 hours. A Customer-owned spare is "
                                    "between the dock and the cage on no record.",
                         "owner": "IT Partner", "contract": CONTRACT["rma_not_received"],
                         "lines": [f"OEM RMA portal {p['rma']}: {p['fru']}"
                                   + (f", failed unit {p['failed_serial']} received by the OEM {p['oem_received_at']}" if p["oem_received_at"] else "")
                                   + f"; replacement {p['replacement_serial']} shipped {p['replacement_shipped_at']}, delivered {p['delivered_at']} "
                                   f"(proof of delivery: {p['pod'].lower()})",
                                   f"Register: no receipt of {p['replacement_serial']}",
                                   f"Spares ledger: {len(led)} receipt{'s' * (len(led) != 1)} of {p['fru']} in the 24 hours after delivery"
                                   + (" (the weekly replenishment, whose serials are other units)" if led else "")],
                         "refs": [p["rma"]] + ([p["ticket"]] if p["ticket"] else []), "devices": [], "serial": p["replacement_serial"],
                         "rma": p["rma"], "from": p["delivered_at"], "to": None})
    # ---- media
    for b in rc["bad"].get("media", []):
        kn = next((f for f in known.get("security", []) if f["serial"] == b["serial"]), None) or \
            next((f for f in known.get("storage", []) if f["type"] == "custody_gap" and f["serial"] == b["serial"]), None)
        if kn:
            explain("media")
            corro.append({"source": "Security engine" if kn["type"] == "media_shipped_without_destruction" else "Storage", "finding": kn["id"],
                          "type": kn["type"], "refs": kn["tickets"],
                          "text": f"Drive {b['serial']}: no custody " + ("and destruction " if b.get("tray") else "") + "in the register "
                                  + ("before " if b.get("tray") else "within ")
                                  + (f"tray {b['tray']} shipped ({b['shipped']})" if b.get("tray") else f"24 hours of leaving {b['node']} {b['bay']}")})
        else:
            findings.append({"kind": "media_unaccounted", "title": f"Drive {b['serial']} not accounted for", "summary": "A pulled drive has no custody or destruction in the register.",
                             "owner": "IT Partner", "contract": CONTRACT["media_unaccounted"], "lines": [], "refs": [], "devices": [],
                             "serial": b["serial"], "from": None, "to": None})
    # ---- everything else must agree
    for name in ("tickets", "rma", "disposals", "directory", "landlord"):
        for b in rc["bad"].get(name, []):
            findings.append({"kind": "unrecorded_work", "title": f"{name}: {json.dumps(b, default=str)[:120]}", "summary": "Records do not reconcile.",
                             "owner": "IT Partner", "contract": CONTRACT["unrecorded_work"], "lines": [], "refs": [], "devices": [],
                             "serial": b.get("serial"), "from": None, "to": None})
    findings.sort(key=lambda f: (f["from"] or "", ORDER.index(f["kind"])))
    for i, f in enumerate(findings, 1):
        f["id"] = f"AR-{i}"
    checks = []
    for name, title in AGREEMENTS:
        c = Check(name, title)
        c.checked = rc["cases"].get(name, 0)
        n_bad = len(rc["bad"].get(name, []))
        if n_bad != explained.get(name, 0):
            c.misses.append(f"{n_bad - explained.get(name, 0)} disagreements not explained")
        checks.append(c)
    return {"findings": findings, "corroborations": corro, "agreements": checks, "R": R, "D": D, "rc": rc,
            "explained": {k: len(v) for k, v in rc["bad"].items()}}


def score(fs: list[dict], key: dict[str, Any]) -> dict[str, int]:
    """Planted cases found, and findings that match none (false positives)."""
    def hit(f: dict, p: dict) -> bool:
        if f["kind"] != p["kind"]:
            return False
        if p["kind"] == "rma_not_received":
            return f.get("rma") == p["rma"]
        return f.get("serial") == p["serial"] and f["devices"] == [p["slot"]]
    planted = key.get("planted", [])
    found = sum(1 for p in planted if any(hit(f, p) for f in fs))
    fp = sum(1 for f in fs if not any(hit(f, p) for p in planted))
    return {"planted": len(planted), "found": found, "false_positives": fp}
