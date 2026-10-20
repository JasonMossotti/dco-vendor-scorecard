"""Quality audit: the Customer's monthly audit of a random sample of closed records, end to end.

The contract (``sla/common.yaml``, measurement.audit) sets the rule: each month the Customer audits a random 5% of
closed tickets or work orders (minimum 10) against raw telemetry, badge, and inventory records, and inspects the
work in place against the workmanship checklist (``config/audit.yaml``). This module draws the sample, checks each
sampled record, and reconciles the walk-down (``data/audit/``) with the records:

- **Records check.** The engines read every record each month; the audit shows, for each sampled record, the
  evidence trail from the Customer's own systems and the engine findings that cite it (CSL-11 counts those).
- **Workmanship.** Each item on the checklist that applies to the record: the serial read at the location
  against the ticket and the BMC inventory, the failed part against the RMA ledger and the cage scan, the cable
  label against the ticket's tray, the maintenance tag against the PM record, a facility part's nameplate against
  the work order, and the inspector's observations.

A walk-down reading that disagrees with the records is a finding (QA-#), unless an engine finding already
explains it: then the audit corroborates that finding. A finding means the records and the work in place do not
reconcile; it starts a corrective action, not a judgment of anyone.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "audit.yaml"
COMMON = ROOT / "sla" / "common.yaml"
PARTNERS = {"it": "IT Partner", "landlord": "Landlord"}
TRACKED = {"Compute tray", "NVLink switch tray", "PSU (5.5 kW)", "Power shelf"}
WET = {"Compute tray", "NVLink switch tray", "Manifold hose and quick-disconnect kit"}
INSPECTOR = "Customer site lead"
WALK_COLS = ["record", "partner", "item", "result", "reading", "note", "inspected_at", "inspector"]
CAGE_COLS = ["serial", "scanned_at", "shelf"]
KIND_TITLE = {"custody": "Failed part in the RMA cage after the ledger shipped it",
              "label": "Cable label names a different tray",
              "pm_tag": "Maintenance tag older than its maintenance record",
              "nameplate": "Nameplate serial differs from the work order",
              "serial": "Serial at the location differs from the BMC inventory",
              "qd": "Quick-disconnects without witness marks",
              "dressing": "Cable dressing not to standard",
              "mop": "MOP not initialed",
              "site": "Work area not restored"}
AGREEMENTS = [
    ("sample", "The sample reproduces from the published seed (record by record)"),
    ("inventory", "Serial read at the location equals the BMC inventory's current serial there"),
    ("engine", "A ticket's installed serial is missing at its location exactly when the engine found an unverified swap"),
    ("custody", "Each failed part is either shipped in the RMA ledger or in the RMA cage, not both"),
    ("labels", "Cable label at a replaced optic names the ticket's link"),
    ("tags", "Maintenance tag date equals the maintenance record's completion date"),
    ("nameplates", "Nameplate serial equals the serial the work order records"),
]


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def iso(t: datetime | None) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else ""


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def config(path: Path = CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def rule(path: Path = COMMON) -> dict[str, Any]:
    """The contract's audit clause: sample_pct, min_records, workmanship_target_pct, and the rule's text."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))["measurement"]["audit"]


def business_days_after(t: datetime, n: int) -> datetime:
    d = t
    while n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


# --------------------------------------------------------------------------- #
# The month's records
# --------------------------------------------------------------------------- #
@dataclass
class Month:
    """The sample month's records the audit reads (never the answer key)."""

    window: dict[str, Any]
    tickets: list[dict[str, Any]]
    work_orders: list[dict[str, Any]]
    pms: list[dict[str, str]]
    inventory: list[dict[str, Any]]
    rma: list[dict[str, str]]
    badges: list[dict[str, str]]
    ll_badges: list[dict[str, str]]
    mop_approvals: list[dict[str, Any]]
    start: datetime = field(init=False)
    end: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.start, self.end = parse(self.window["start"]), parse(self.window["end"])


def load_month(sample_dir: str | Path) -> Month:
    d = Path(sample_dir)
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    return Month(window=man["window"], tickets=json.loads((d / "vendor" / "tickets.json").read_text(encoding="utf-8")),
                 work_orders=json.loads((d / "landlord" / "work_orders.json").read_text(encoding="utf-8")),
                 pms=_csv(d / "landlord" / "pm_records.csv"),
                 inventory=[e for e in _jsonl(d / "telemetry" / "redfish_inventory_changes.jsonl") if e["property"] == "SerialNumber"],
                 rma=_csv(d / "vendor" / "rma_shipments.csv"), badges=_csv(d / "access" / "badge_events.csv"),
                 ll_badges=_csv(d / "access" / "landlord_badge_events.csv"),
                 mop_approvals=json.loads((d / "customer" / "landlord_mop_approvals.json").read_text(encoding="utf-8")))


def pools(m: Month) -> dict[str, list[str]]:
    """Every record closed in the month, by partner: IT tickets; Landlord work orders and completed PM tasks."""
    it = sorted(t["number"] for t in m.tickets if t["state"] == "Closed" and m.start <= parse(t["resolved_at"]) < m.end)
    ll = sorted([w["wo"] for w in m.work_orders if w["closed"] and m.start <= parse(w["closed"]) < m.end]
                + [p["task_id"] for p in m.pms if p["completed_at"] and m.start <= parse(p["completed_at"]) < m.end])
    return {"it": it, "landlord": ll}


def sample_size(n: int, r: dict[str, Any]) -> int:
    return min(n, max(r["min_records"], math.ceil(n * r["sample_pct"] / 100)))


def draw(pool: list[str], seed: int, partner: str, r: dict[str, Any]) -> list[str]:
    """The sample: a seeded draw from the sorted pool, so anyone holding the published seed gets the same records."""
    return sorted(random.Random(f"{seed}:{partner}").sample(sorted(pool), sample_size(len(pool), r)))


def current_serial(serial: str, inventory: list[dict[str, Any]]) -> str:
    """The serial the BMC inventory shows now where ``serial`` was: follow each SerialNumber change from it."""
    nxt = {e["old_value"]: e["new_value"] for e in sorted(inventory, key=lambda e: e["observed_at"])}
    seen = set()
    while serial in nxt and serial not in seen:
        seen.add(serial)
        serial = nxt[serial]
    return serial


def history(serial: str, inventory: list[dict[str, Any]]) -> list[str]:
    """Every serial the inventory has shown at the location, starting from ``serial``."""
    nxt = {e["old_value"]: e["new_value"] for e in sorted(inventory, key=lambda e: e["observed_at"])}
    out = [serial]
    while out[-1] in nxt and nxt[out[-1]] not in out:
        out.append(nxt[out[-1]])
    return out


def still_installed(part: dict[str, Any], inventory: list[dict[str, Any]]) -> bool:
    """A tracked part the ticket says was removed while the inventory never showed its replacement."""
    return (part["part"] in TRACKED and bool(part["installed_serial"]) and bool(part["removed_serial"])
            and part["installed_serial"] not in history(part["removed_serial"], inventory))


def wo_serial(wo: dict[str, Any]) -> str:
    """The serial a Landlord work order records installed ("Pump assembly SN CHX-P24761 installed"), or ""."""
    words = (wo.get("parts") or "").split()
    return words[words.index("SN") + 1] if "SN" in words and words.index("SN") + 1 < len(words) else ""


def host_of(location: str) -> str:
    return location.split(" (")[0]


def link_label(ticket: dict[str, Any], location: str) -> str:
    """What the cable label at a replaced optic should read: the link's two ends as the ticket names them
    ("a23-ct07:mlx5_0 <-> leaf-a12-r0:swp7"), or the tray when the ticket names no link."""
    d = ticket.get("short_description", "")
    return d[5:] if d.startswith("Link ") and "<->" in d else host_of(location)


def items_for(partner: str, rec: dict[str, Any], kind: str, cfg: dict[str, Any]) -> list[str]:
    """The checklist items that apply to a record (config/audit.yaml, checklist)."""
    keys: list[str] = []
    if partner == "it":
        parts = rec["parts_used"]
        if any(p["part"] in TRACKED and p["installed_serial"] and p["removed_serial"] for p in parts):
            keys.append("serial")
        if any(p["removed_serial"] for p in parts):
            keys.append("custody")
        if any("optic" in p["part"] for p in parts):
            keys += ["label", "dressing"]
        if any(p["part"] in WET for p in parts):
            keys.append("qd")
    elif kind == "pm":
        keys.append("pm_tag")
    else:
        if wo_serial(rec):
            keys.append("nameplate")
        if rec.get("mop_ref"):
            keys.append("mop")
    keys.append("site")
    order = [c["key"] for c in cfg["checklist"][partner]]
    return sorted(set(keys), key=order.index)


def record_index(m: Month) -> dict[str, tuple[str, str, dict[str, Any]]]:
    """Record id -> (partner, kind, record): kind is ticket, wo, or pm."""
    out: dict[str, tuple[str, str, dict[str, Any]]] = {t["number"]: ("it", "ticket", t) for t in m.tickets}
    out.update({w["wo"]: ("landlord", "wo", w) for w in m.work_orders})
    out.update({p["task_id"]: ("landlord", "pm", p) for p in m.pms})
    return out


# --------------------------------------------------------------------------- #
# The audit layer
# --------------------------------------------------------------------------- #
@dataclass
class AuditData:
    month: Month
    manifest: dict[str, Any]
    sample: dict[str, Any]
    walkdown: list[dict[str, str]]
    cage: list[dict[str, str]]


def load(audit_dir: str | Path, sample_dir: str | Path) -> AuditData:
    a = Path(audit_dir)
    return AuditData(month=load_month(sample_dir), manifest=json.loads((a / "manifest.json").read_text(encoding="utf-8")),
                     sample=json.loads((a / "sample.json").read_text(encoding="utf-8")),
                     walkdown=_csv(a / "walkdown.csv"), cage=_csv(a / "rma_cage_scan.csv"))


@dataclass
class Check:
    name: str
    title: str
    checked: int = 0
    misses: list[str] = field(default_factory=list)


def _evidence(m: Month, partner: str, kind: str, rec: dict[str, Any]) -> list[dict[str, str]]:
    """The record's trail through the Customer's systems: when it opened and closed, who badged in, what the BMC saw."""
    ev: list[dict[str, str]] = []
    if partner == "it":
        t0, t1 = parse(rec["opened_at"]), parse(rec["resolved_at"])
        ev.append({"source": "Ticket", "at": rec["opened_at"], "text": f"{rec['priority']} opened: {rec['short_description']}"})
        b = [x for x in m.badges if x["person_id"] == rec["assigned_to"] and x["door"] != "OPS-MAIN" and x["direction"] == "in"
             and t0 - timedelta(hours=1) <= parse(x["timestamp"]) <= t1]
        ev.append({"source": "Access control", "at": b[0]["timestamp"] if b else "",
                   "text": f"{rec['assigned_to']} badged into {b[0]['door']}" if b else f"No hall badge-in for {rec['assigned_to']} while the ticket was open"})
        for p in rec["parts_used"]:
            if p["installed_serial"]:
                ch = [e for e in m.inventory if e["new_value"] == p["installed_serial"]]
                ev.append({"source": "BMC inventory", "at": ch[0]["observed_at"] if ch else "",
                           "text": (f"{ch[0]['old_value']} to {ch[0]['new_value']} at {ch[0]['resource'].split('/Chassis/')[-1]}" if ch
                                    else f"{p['part']}: the inventory does not track it" if p["part"] not in TRACKED
                                    else f"No inventory change to {p['installed_serial']}")})
            if p["removed_serial"]:
                r = next((x for x in m.rma if x["serial"] == p["removed_serial"]), None)
                ev.append({"source": "RMA ledger", "at": r["shipped_at"] if r else "",
                           "text": f"{p['removed_serial']} shipped to the OEM" if r else f"{p['removed_serial']} not shipped"})
        ev.append({"source": "Ticket", "at": rec["resolved_at"],
                   "text": f"Closed: {rec['close_code']}; validation {'attached' if rec['validation_attached'] else 'not attached'}"})
    elif kind == "wo":
        ev.append({"source": "Work order", "at": rec["opened"], "text": f"{rec['priority']} opened: {rec['notes'] or rec['unit']}"})
        day = rec["engaged_at"] or rec["opened"]
        b = [x for x in m.ll_badges if x["person_id"] == rec["engineer"] and parse(day) - timedelta(hours=12) <= parse(x["timestamp"]) <= parse(rec["closed"])]
        ev.append({"source": "Access control", "at": b[0]["timestamp"] if b else "",
                   "text": f"{rec['engineer']} badged in at the {b[0]['reader'].lower()}" if b else f"No badge-in for {rec['engineer']} while the work order was open"})
        if rec.get("mop_ref"):
            a = next((x for x in m.mop_approvals if x["mop_id"] == rec["mop_ref"]), None)
            ev.append({"source": "Change board", "at": a["approved_at"] if a else "",
                       "text": f"{rec['mop_ref']} approved" if a else f"{rec['mop_ref']}: no approval on record"})
        ev.append({"source": "Work order", "at": rec["closed"], "text": f"Closed{': ' + rec['parts'] if rec['parts'] else ''}"})
    else:
        ev.append({"source": "Maintenance record", "at": rec["completed_at"], "text": f"{rec['task']} on {rec['asset']}: {rec['result']}"})
        ev.append({"source": "Maintenance record", "at": "", "text": f"Evidence: {rec['evidence'] or 'none recorded'}"})
        b = [x for x in m.ll_badges if x["person_id"] == rec["engineer"] and abs((parse(x["timestamp"]) - parse(rec["completed_at"])).total_seconds()) <= 12 * 3600]
        ev.append({"source": "Access control", "at": b[0]["timestamp"] if b else "",
                   "text": f"{rec['engineer']} badged in at the {b[0]['reader'].lower()}" if b else f"No badge-in for {rec['engineer']} that day"})
    return ev


def analyse(t: AuditData, engine_findings: dict[str, list[dict[str, Any]]], cfg: dict[str, Any] | None = None,
            r: dict[str, Any] | None = None) -> dict[str, Any]:
    """Draw the sample, check every sampled record, reconcile the walk-down; the findings, agreements, and rows.

    ``engine_findings`` maps a record id to the engine findings that cite it ({"id", "type", "title"} each).
    """
    cfg, r = cfg or config(), r or rule()
    m = t.month
    idx = record_index(m)
    pool = pools(m)
    seed = t.sample["seed"]
    checks = {k: Check(k, title) for k, title in AGREEMENTS}
    drawn = {}
    for p in PARTNERS:
        drawn[p] = draw(pool[p], seed, p, r)
        checks["sample"].checked += len(drawn[p])
        checks["sample"].misses += [f"{p}: {x}" for x in sorted(set(drawn[p]) ^ set(t.sample["records"][p]))]
    walk: dict[str, dict[str, dict[str, str]]] = {}
    for w in t.walkdown:
        walk.setdefault(w["record"], {})[w["item"]] = w
    cage_at = min((parse(c["scanned_at"]) for c in t.cage), default=m.end)
    in_cage = {c["serial"] for c in t.cage}
    shipped = {x["serial"]: parse(x["shipped_at"]) for x in m.rma if x["shipped_at"]}

    findings: list[dict[str, Any]] = []
    explained: dict[str, int] = {}
    records = []
    for p in PARTNERS:
        for rid in drawn[p]:
            partner, kind, rec = idx[rid]
            eng = engine_findings.get(rid, [])
            items = []
            for key in items_for(partner, rec, kind, cfg):
                w = walk.get(rid, {}).get(key)
                item = {"key": key, "title": next(c["title"] for c in cfg["checklist"][partner] if c["key"] == key),
                        "reading": w["reading"] if w else "", "note": w["note"] if w else "", "at": w["inspected_at"] if w else "",
                        "expected": "", "result": "pass", "corroborates": ""}
                fail_kind = ""
                if w is None:
                    item["result"], item["note"] = "missing", "Not inspected"
                elif key == "serial":
                    parts = [x for x in rec["parts_used"] if x["part"] in TRACKED and x["installed_serial"] and x["removed_serial"]]
                    x = parts[0]
                    now = current_serial(x["removed_serial"], m.inventory)
                    item["expected"] = f"Ticket {x['installed_serial']}; BMC inventory now {now}"
                    checks["inventory"].checked += 1
                    if w["reading"] != now:
                        checks["inventory"].misses.append(f"{rid}: read {w['reading']}, inventory {now}")
                        fail_kind = "serial"
                    swapped = not still_installed(x, m.inventory)
                    swap_finding = next((f for f in eng if f["type"] == "unverified_swap"), None)
                    checks["engine"].checked += 1
                    if (not swapped) != bool(swap_finding):
                        checks["engine"].misses.append(f"{rid}: installed serial {'missing' if not swapped else 'present'}, "
                                                       f"engine {'found' if swap_finding else 'did not find'} an unverified swap")
                    if not swapped and not fail_kind:
                        item["result"] = "fail"
                        item["corroborates"] = swap_finding["id"] if swap_finding else ""
                        item["note"] = (f"The part in the slot is {w['reading']}, the one the ticket says was removed; "
                                        f"the ticket's {x['installed_serial']} is not installed.")
                elif key == "custody":
                    for x in [x for x in rec["parts_used"] if x["removed_serial"]]:
                        s = x["removed_serial"]
                        if still_installed(x, m.inventory):
                            item["expected"] = f"{s} still installed (see the serial check)"
                            continue
                        gone = s in shipped and shipped[s] <= cage_at
                        checks["custody"].checked += 1
                        item["expected"] = (f"{s} shipped {shipped[s].strftime('%b %d')}" if gone else f"{s} in the RMA cage")
                        if gone and s in in_cage:
                            checks["custody"].misses.append(f"{rid}: {s} shipped and in the cage")
                            fail_kind = "custody"
                            item["note"] = f"{s} is on the RMA cage shelf; the RMA ledger says it shipped to the OEM on {shipped[s].strftime('%b %d')}."
                        elif not gone and s not in in_cage:
                            checks["custody"].misses.append(f"{rid}: {s} neither shipped nor in the cage")
                            fail_kind = "custody"
                            item["note"] = f"{s} is not in the RMA cage and the RMA ledger has not shipped it."
                elif key == "label":
                    x = next(x for x in rec["parts_used"] if "optic" in x["part"])
                    item["expected"] = link_label(rec, x["location"])
                    checks["labels"].checked += 1
                    if w["reading"] != item["expected"]:
                        checks["labels"].misses.append(f"{rid}: label {w['reading']}, ticket {item['expected']}")
                        fail_kind = "label"
                elif key == "pm_tag":
                    item["expected"] = rec["completed_at"][:10]
                    checks["tags"].checked += 1
                    if w["reading"] != item["expected"]:
                        checks["tags"].misses.append(f"{rid}: tag {w['reading']}, record {item['expected']}")
                        fail_kind = "pm_tag"
                elif key == "nameplate":
                    item["expected"] = wo_serial(rec)
                    checks["nameplates"].checked += 1
                    if w["reading"] != item["expected"]:
                        checks["nameplates"].misses.append(f"{rid}: nameplate {w['reading']}, work order {item['expected']}")
                        fail_kind = "nameplate"
                elif w["result"] == "fail":
                    fail_kind = key
                if fail_kind:
                    item["result"] = "fail"
                    findings.append({"kind": fail_kind, "record": rid, "partner": partner, "item": key, "title": KIND_TITLE[fail_kind],
                                     "reading": w["reading"], "expected": item["expected"], "note": item["note"] or w["note"],
                                     "at": w["inspected_at"]})
                items.append(item)
            records.append({"id": rid, "partner": partner, "kind": kind, "what": _what(kind, rec), "closed": _closed(kind, rec),
                            "rack": rec.get("rack", "") if partner == "it" else "", "unit": rec.get("unit", rec.get("asset", "")),
                            "engine": eng, "items": items, "evidence": _evidence(m, partner, kind, rec),
                            "passed": all(i["result"] == "pass" for i in items)})

    findings.sort(key=lambda f: (f["at"], f["record"]))
    due_days = cfg["action_due_business_days"]
    for k, f in enumerate(findings, 1):
        f["id"] = f"QA-{k}"
        f["action"] = cfg["actions"][f["item"]]
        f["owner"] = PARTNERS[f["partner"]]
        f["due"] = iso(business_days_after(parse(f["at"]), due_days))[:10]
    by_check = {"custody": "custody", "label": "labels", "pm_tag": "tags", "nameplate": "nameplates", "serial": "inventory"}
    for f in findings:
        if f["kind"] in by_check:
            explained[by_check[f["kind"]]] = explained.get(by_check[f["kind"]], 0) + 1
    summary = {}
    for p in PARTNERS:
        rs = [x for x in records if x["partner"] == p]
        passed = sum(1 for x in rs if x["passed"])
        summary[p] = {"name": PARTNERS[p], "pool": len(pool[p]), "sampled": len(rs), "passed": passed,
                      "pass_pct": round(100 * passed / len(rs), 1) if rs else None,
                      "met": (100 * passed / len(rs) >= r["workmanship_target_pct"]) if rs else None,
                      "items": sum(len(x["items"]) for x in rs), "items_failed": sum(1 for x in rs for i in x["items"] if i["result"] != "pass"),
                      "engine": sum(1 for x in rs if x["engine"]), "findings": sum(1 for f in findings if f["partner"] == p),
                      "corroborated": sum(1 for x in rs for i in x["items"] if i["corroborates"])}
    return {"records": records, "findings": findings, "agreements": list(checks.values()), "explained": explained,
            "summary": summary, "seed": seed, "drawn_at": t.sample["drawn_at"], "cage_scanned_at": iso(cage_at),
            "rule": {"sample_pct": r["sample_pct"], "min_records": r["min_records"], "target_pct": r["workmanship_target_pct"],
                     "text": " ".join(r["rule"].split())}}


def _what(kind: str, rec: dict[str, Any]) -> str:
    if kind == "ticket":
        return rec["short_description"]
    if kind == "wo":
        return f"{rec['unit']}: {rec['notes']}" if rec["notes"] else rec["unit"]
    return f"{rec['task']}, {rec['asset']}"


def _closed(kind: str, rec: dict[str, Any]) -> str:
    return {"ticket": rec.get("resolved_at"), "wo": rec.get("closed"), "pm": rec.get("completed_at")}[kind] or ""


def engine_index(it_findings, ll_findings) -> dict[str, list[dict[str, Any]]]:
    """Record id -> the engine findings that cite it (IT Partner and Landlord engines)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for f in list(it_findings) + list(ll_findings):
        for n in f.tickets:
            out.setdefault(n, []).append({"id": f.id, "type": f.type, "title": f.title})
    return out


def run_engines(sample_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    from scorecard import app_support as A
    from scorecard.sla_model import PARTNER_FILES, load_sla
    it, _, _ = A.run_pipeline(load_sla(PARTNER_FILES["it"]), sample_dir)
    ll, _, _, _ = A.run_landlord_pipeline(sample_dir)
    return engine_index(it.findings, ll.findings)


def score(fs: list[dict[str, Any]], key: list[dict[str, Any]]) -> dict[str, int]:
    """Planted defects found, and findings that match none (false positives)."""
    def hit(f: dict, p: dict) -> bool:
        return f["kind"] == p["kind"] and f["record"] == p["record"]
    found = sum(1 for p in key if any(hit(f, p) for f in fs))
    fp = sum(1 for f in fs if not any(hit(f, p) for p in key))
    return {"planted": len(key), "found": found, "false_positives": fp}


QUALITY = ("CSL-06", "CSL-08", "KM-18")


def quality_rows(sample_dir: str | Path) -> list[dict[str, Any]]:
    """The engine's own quality measures for every repair this month (the audit looks at a sample in person)."""
    from scorecard import app_support as A
    from scorecard.sla_model import PARTNER_FILES, load_sla
    _, sc, _ = A.run_pipeline(load_sla(PARTNER_FILES["it"]), sample_dir)
    rows = [r for r in A.csl_rows(sc) if r["ID"] in QUALITY] + [r for r in A.km_rows(sc) if r["ID"] in QUALITY]
    return [{"id": r["ID"], "name": r.get("Service level") or r.get("Key measurement"), "measured": r.get("Measured") or r.get("Actual"),
             "target": r.get("Target") or r.get("Expected"), "basis": r.get("Basis", "")} for r in rows]


def page_data(t: AuditData, sample_dir: str | Path) -> dict[str, Any]:
    """Everything the report (scripts/render_audit.py) and the Scorecards page's Quality audit view show."""
    r = analyse(t, run_engines(sample_dir))
    return {"window": t.month.window, "seed": r["seed"], "drawn_at": r["drawn_at"], "cage_scanned_at": r["cage_scanned_at"],
            "rule": r["rule"], "summary": r["summary"], "records": r["records"], "findings": r["findings"],
            "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses),
                            "explained": r["explained"].get(c.name, 0)} for c in r["agreements"]],
            "checklist": config()["checklist"], "cage": t.cage, "quality": quality_rows(sample_dir)}
