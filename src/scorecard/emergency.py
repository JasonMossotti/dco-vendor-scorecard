"""Emergency procedures, the decision tree, and the call lists.

The procedures (config/emergency.yaml) are the Customer's judgment. What the contracts and the site model set is read
from them here and filled into the text: the bridge, page, update, and review clocks from the agreements (through
scorecard.command), the first leadership notice from the runbook, the on-call rota from the routing file, and the
generator fuel from the site model. The sample's P1 records are tied to event types by the config's match rules and
grouped into events by their confirmed relations, so one event never opens two responses.

The Incident Commander runbook and the A07 replay (scorecard.command) are shown on the same page.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from scorecard import command, tickets

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "emergency.yaml"
NOTIFY = ROOT / "config" / "customer_notifications.yaml"
SITE = ROOT / "site" / "site.yaml"
IA = ROOT / "sla" / "interface_agreement.yaml"


def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def facts() -> dict[str, Any]:
    """The values the config's {placeholders} name, each read from its source."""
    cc = command.contract_clocks()
    site = yaml.safe_load(SITE.read_text(encoding="utf-8"))
    return {"bridge_min": cc["bridge_min"], "page_min": cc["page_min"], "lead_cadence_min": cc["lead_cadence_min"],
            "pir_business_days": cc["pir_business_days"],
            "first_notice_min": command.load_config()["clocks"]["first_leadership_min"],
            "fuel_hours": site["plants"]["generators"]["fuel_hours_at_full_load"]}


def _fill(o: Any, f: dict[str, Any]) -> Any:
    if isinstance(o, str):
        return o.format_map(f) if "{" in o else o
    if isinstance(o, list):
        return [_fill(x, f) for x in o]
    if isinstance(o, dict):
        return {k: _fill(v, f) for k, v in o.items()}
    return o


def raci() -> dict[str, dict[str, str]]:
    ia = yaml.safe_load(IA.read_text(encoding="utf-8"))
    return {r["component"]: r for r in ia["raci"]}


def classify(record: dict[str, Any], types: list[dict[str, Any]]) -> list[str]:
    """Every event type whose match rules fit the record (the sample's P1s fit exactly one; tested)."""
    out = []
    for t in types:
        for m in t["match"]:
            if m["type"] != record["type"]:
                continue
            if "category" in m and not re.search(m["category"], record.get("category") or ""):
                continue
            if "device" in m and not re.search(m["device"], record.get("device") or "", re.I):
                continue
            out.append(t["id"])
            break
    return out


def tree_paths(tree: dict[str, Any]) -> list[list[tuple[str, str]]]:
    """Every path from the start to a leaf, as (node, option label) steps; a leaf is the last option's target."""
    paths: list[list[tuple[str, str]]] = []

    def walk(node: str, path: list[tuple[str, str]], seen: frozenset[str]) -> None:
        if node in seen:
            raise ValueError(f"decision tree loops at {node}")
        for o in tree["nodes"][node]["options"]:
            step = path + [(node, o["label"])]
            if o["to"].startswith("type:"):
                paths.append(step + [("", o["to"])])
            else:
                walk(o["to"], step, seen | {node})

    walk(tree["start"], [], frozenset())
    return paths


def events(cfg: dict[str, Any], data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The sample's P1 records grouped into events (records joined by a relation are one event), with their type."""
    data = data or tickets.build()
    p1 = {r["id"]: r for r in data["records"] if r.get("priority") == "P1"}
    groups: list[list[str]] = []
    seen: set[str] = set()
    for rid in sorted(p1, key=lambda i: (p1[i]["start"], i)):
        if rid in seen:
            continue
        stack, members = [rid], []
        while stack:
            x = stack.pop()
            if x in seen or x not in p1:
                continue
            seen.add(x)
            members.append(x)
            stack += sorted(p1[x]["related"])
        groups.append(sorted(members, key=lambda i: (p1[i]["start"], i)))
    out = []
    for g in groups:
        recs = [p1[i] for i in g]
        types = sorted({t for r in recs for t in classify(r, cfg["types"])})
        out.append({"id": g[0], "records": g, "start": recs[0]["start"], "types": types,
                    "summary": recs[0]["summary"], "location": recs[0].get("location") or recs[0].get("device", ""),
                    "partners": sorted({data["types"][r["type"]]["partner"] for r in recs})})
    return out


def _age(verified: str, as_of: str) -> int:
    return (date.fromisoformat(as_of) - date.fromisoformat(verified)).days


def contacts(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    n = yaml.safe_load(NOTIFY.read_text(encoding="utf-8"))
    out = []
    for c in cfg["contacts"]:
        c = dict(c)
        if c.get("rota"):
            c["rota_shifts"] = [{"label": s["label"], "days": s["days"], "start": s["start"], "end": s["end"],
                                 "who": s[c["rota"]], "phone": n["people"][s[c["rota"]]]["sms"]} for s in n["schedule"]]
        c["age_days"] = _age(c["verified"], cfg["as_of"])
        c["stale"] = c["age_days"] > cfg["verify_within_days"]
        out.append(c)
    return out


def build() -> dict[str, Any]:
    cfg = load_config()
    f = facts()
    cfg = _fill(cfg, f)
    tiers = {t["id"]: t for t in cfg["tiers"]}
    cons = {c["id"]: c for c in contacts(cfg)}
    types = []
    for t in cfg["types"]:
        t = {k: v for k, v in t.items() if k != "match"}   # the match rules are for classifying, not for the page
        t["phases"] = t.get("phases") or cfg["phases"]
        t["notify"] = [{"tier": k, "name": tiers[k]["name"], "within_min": v, "why": tiers[k]["why"],
                        "contact": cons[tiers[k]["contact"]]["role"], "phone": cons[tiers[k]["contact"]].get("phone", "")}
                       for k, v in sorted(t["notify"].items(), key=lambda kv: (kv[1], list(tiers).index(kv[0])))]
        types.append(t)
    ev = events(cfg)   # classified with the config's types, which carry the match rules
    for t in types:
        t["samples"] = [e["id"] for e in ev if t["id"] in e["types"]]
    return {"intro": cfg["intro"], "sources": cfg["sources"], "always_first": cfg["always_first"], "site": cfg["site"],
            "bridge": cfg["bridge"], "verify_within_days": cfg["verify_within_days"], "as_of": cfg["as_of"],
            "contacts": list(cons.values()), "tiers": cfg["tiers"], "tree": cfg["tree"], "types": types, "events": ev,
            "facts": f, "paging": command.paging_tree(), "command": command.build()}
