"""Break-fix ownership trainer: scenarios built from the Interface Agreement's ownership matrix.

Each row of the matrix (``raci`` in sla/interface_agreement.yaml) becomes one scenario. config/ownership_trainer.yaml
gives only what a technician would see, the priority with the criterion it comes from, and which sample records the
row applied to. Every answer is read from the agreement: Responsible, Accountable, Consulted, and Informed from the
RACI row; who notifies the Customer from the equipment's owner; how fast from the alarm notification rules (NT-1 for a
P1, NT-2 for a P2). So the trainer can never disagree with the contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scorecard import tickets as T
from scorecard.sla_model import load_interface_agreement, load_sla

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "ownership_trainer.yaml"
PARTY = {"customer": "Customer", "landlord": "Landlord", "it_partner": "IT Partner", "security_partner": "Security Partner",
         "oem": "OEM", "utility": "Utility"}
SLA_FILES = {"IT Partner": ROOT / "sla" / "it_partner.yaml", "Landlord": ROOT / "sla" / "ot_partner.yaml",
             "Security Partner": ROOT / "sla" / "security_partner.yaml"}
SLA_NAME = {"IT Partner": "IT Partner SLA", "Landlord": "Landlord SLA", "Security Partner": "Security SLA"}


def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def roles(row: dict[str, str], parties: list[str]) -> dict[str, list[str]]:
    """The parties holding each RACI letter in a row ("A/R" counts for both A and R)."""
    out: dict[str, list[str]] = {"R": [], "A": [], "C": [], "I": []}
    for p in parties:
        for letter in row[p].split("/"):
            if letter in out:
                out[letter].append(p)
    return out


def owner(r: dict[str, list[str]]) -> str:
    """The party that owns the equipment under the alarm terms: the Accountable party, or the party doing the work
    when the Customer is Accountable for equipment someone else maintains."""
    a = r["A"][0]
    if a != "Customer":
        return a
    return next((p for p in r["R"] if p != "Customer"), "Customer")


def criterion_source(crit: str, party: str, ia: dict, slas: dict[str, dict]) -> str | None:
    """Where the priority criterion is written: the owning party's SLA priority list, or the Interface Agreement."""
    sla = slas.get(party)
    if sla:
        for p in sla["priorities"]:
            if crit in p["criteria"]:
                return f"{SLA_NAME[party]}, {p['id']}"
    if crit in yaml.safe_dump(ia, width=10_000, allow_unicode=True):
        return "Interface Agreement, section 9"
    return None


def matches(rec: dict, m: dict) -> bool:
    return (rec.get("category") in m.get("categories", []) or rec["id"] in m.get("ids", [])
            or any(str(rec.get("device") or "").startswith(d) for d in m.get("devices", [])))


def build(records: list[dict] | None = None) -> dict[str, Any]:
    ia = load_interface_agreement()
    cfg = load_config()
    slas = {k: load_sla(v) for k, v in SLA_FILES.items()}
    records = T.build()["records"] if records is None else records
    parties = ia["raci_parties"]
    demarc = {d["id"]: d for d in ia["demarcations"]}
    rule_text = {r["id"]: r["rule"] for r in ia["fault_attribution"]["rules"]}
    rule_text.update({h["id"]: f"{h['name']}: {h['rule']}" for h in ia["handoffs"]})
    nts = {n["id"]: n for n in ia["alarm_notification"]["notifications"]}
    by_component = {r["component"]: r for r in cfg["rows"]}
    scenarios = []
    for i, row in enumerate(ia["raci"], 1):
        c = by_component[row["component"]]
        r = roles(row, parties)
        notifier = c["notifier"]["party"] if c.get("notifier") else owner(r)
        pri = c["priority"]
        note = cfg["notification"].get(pri) if pri else None
        if notifier == "Customer":
            note = None
        nt = nts[note["rule"]] if note else None
        dm = demarc.get(c.get("demarcation") or "")
        recs = [x for x in records if matches(x, c.get("match") or {})]
        recs.sort(key=lambda x: x.get("start") or "")
        scenarios.append({
            "n": i, "component": row["component"], "scenario": c["scenario"],
            "raci": {p: row[p] for p in parties}, "R": r["R"], "A": r["A"][0], "C": r["C"], "I": r["I"],
            "priority": pri, "criterion": c.get("criterion"),
            "criterion_source": criterion_source(c["criterion"], notifier, ia, slas) if pri else None,
            "notifier": notifier if nt else None, "notifier_why": (c.get("notifier") or {}).get("why"),
            "minutes": note["minutes"] if nt else None, "rule": nt["id"] if nt else None,
            "rule_text": f"{nt['trigger']}: within {nt['within_min']} minutes, {nt['channels']}; owed by {nt['owed_by'].lower()}." if nt else None,
            "demarcation": {"id": dm["id"], "system": dm["system"], "boundary": dm["boundary"],
                            "upstream": PARTY[dm["upstream"]], "downstream": PARTY[dm["downstream"]]} if dm else None,
            "rules": [{"id": k, "text": rule_text[k]} for k in c.get("rules", [])],
            "records": [{"id": x["id"], "type": x["type_label"], "partner": x["partner"], "priority": x.get("priority"),
                         "start": x.get("start"), "summary": x["summary"]} for x in recs],
        })
    return {"intro": cfg["intro"], "parties": parties, "no_notice": cfg["notification"]["none"],
            "legend": ia["raci_legend"], "scenarios": scenarios}
