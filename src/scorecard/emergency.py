"""Emergency procedures, the decision tree, and the call lists.

The procedures (config/emergency.yaml) are the Customer's judgment. What the contracts and the site model set is read
from them here and filled into the text: the bridge, page, update, and review clocks from the agreements (through
scorecard.command), the first leadership notice from the runbook, the on-call rota from the routing file, and the
generator fuel from the site model. The sample's P1 records are tied to event types by the config's match rules and
grouped into events by their confirmed relations, so one event never opens two responses.

The response console (``responses``) gets each P1 event, and each P2 record a person may escalate, with the facts the
first minutes need, as the records stood when it started: the restore clocks from the SLAs, racks and GPUs from the
topology, who was on call, the redundancy groups reduced, the change work and permits open on the site that day (the
daily standup's own functions, so the two pages cannot disagree), spares below their minimum, the partners' pages, and,
where the bridge was recorded, the comms log to replay.

The Incident Commander runbook and the A07 replay (scorecard.command) are shown on the same page.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from scorecard import command, tickets

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "emergency.yaml"
NOTIFY = ROOT / "config" / "customer_notifications.yaml"
SITE = ROOT / "site" / "site.yaml"
IA = ROOT / "sla" / "interface_agreement.yaml"
TOPOLOGY = ROOT / "data" / "sample" / "site" / "topology.json"
COMMS = ROOT / "data" / "incident_comms"
PAGES = ROOT / "data" / "changes" / "notification_log.json"
SLA_FILES = {"IT Partner": ROOT / "sla" / "it_partner.yaml", "Landlord": ROOT / "sla" / "ot_partner.yaml",
             "Security Partner": ROOT / "sla" / "security_partner.yaml"}


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
        ends = [r["end"] for r in recs if r.get("end")]
        out.append({"id": g[0], "records": g, "start": recs[0]["start"], "end": max(ends) if len(ends) == len(recs) else "", "types": types,
                    "summary": recs[0]["summary"], "location": recs[0].get("location") or recs[0].get("device", ""),
                    "partners": sorted({data["types"][r["type"]]["partner"] for r in recs})})
    return out


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _z(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def clocks() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Each partner's clocks for a priority: engaged on site (a guard on scene for the Security Partner), then
    restore."""
    from scorecard.sla_model import load_sla
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for party, f in SLA_FILES.items():
        pr = yaml.safe_load(f.read_text(encoding="utf-8"))["priorities"] if party == "Security Partner" else load_sla(f)["priorities"]
        out[party] = {}
        for p in pr:
            c = []
            if p.get("engaged_on_site_min"):
                what = "Guard on scene" if party == "Security Partner" else "Engaged on site"
                c.append({"label": f"{what} ({party} SLA, {p['id']})", "min": p["engaged_on_site_min"]})
            if p.get("restore_min"):
                c.append({"label": f"Restore ({party} SLA, {p['id']})", "min": p["restore_min"]})
            out[party][p["id"]] = c
    return out


@lru_cache(maxsize=1)
def responses() -> dict[str, Any]:
    """Every P1 event, and every P2 record (for escalation), with what the console shows when it opens."""
    from scorecard import standup as SU
    cfg = load_config()
    data = tickets.build()
    rec = {r["id"]: r for r in data["records"]}
    su = SU.Standup()
    clk = clocks()
    racks = {r["rack"]: r for r in json.loads(TOPOLOGY.read_text(encoding="utf-8"))["racks"]}
    pages = json.loads(PAGES.read_text(encoding="utf-8"))
    pages = pages if isinstance(pages, list) else next(iter(pages.values()))
    comms = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in COMMS.glob("INC*.json")}
    groups = [(e["id"], e["records"], e["types"]) for e in events(cfg, data)]
    groups += [(r["id"], [r["id"]], classify(r, cfg["types"])) for r in data["records"] if r.get("priority") == "P2"]
    out, by_record = {}, {}
    for eid, ids, types in groups:
        rs = [rec[i] for i in ids]
        alarms = sorted((a for r in rs for a in r.get("alarms") or []), key=lambda a: a.get("raised") or "")
        start = min(_t(r["start"]) for r in rs)
        ends = [_t(r["end"]) for r in rs if r.get("end")]
        end = max(ends) if ends else None
        rack = next((r["rack"] for r in rs if r.get("rack")), "")
        rk = racks.get(rack)
        devices = sorted({r["device"] for r in rs if r.get("device")})
        hall = next((r["hall"] for r in rs if r.get("hall")), "")
        win_end = end or start + timedelta(hours=4)
        red = su.redundancy(start, start + timedelta(hours=1))
        work = [j for j in su.work(start) if _t(j["start"]) < start + timedelta(hours=24)]
        permits = [p for p in su.permits(start, start, win_end)["open"]]
        pg = [{"party": p["party"], "channel": p["channel"], "sent_at": p["sent_at"], "signal": p["signal"], "device": p["device"],
               "late_min": round((_t(p["sent_at"]) - _t(p["alarm_time"])).total_seconds() / 60, 1)}
              for p in pages if start - timedelta(minutes=10) <= _t(p["alarm_time"]) <= win_end
              and (p["device"] in devices or (rack and rack in p["device"]) or p["device"] in {a.get("device") for a in alarms})]
        log = next((comms[i] for i in ids if i in comms), None)
        prio = sorted({r["priority"] for r in rs})[0]
        out[eid] = {
            "id": eid, "records": [{k: r.get(k, "") for k in ("id", "type_label", "partner", "priority", "summary", "start", "end", "state")}
                                   for r in rs],
            "priority": prio, "types": types, "summary": rs[0]["summary"], "start": _z(start), "end": _z(end) if end else "",
            "location": rs[0].get("location") or rs[0].get("device", ""), "hall": hall, "rack": rack, "devices": devices,
            "gpus": len(rk["compute_trays"]) * 4 if rk else 0,
            "partners": sorted({r["partner"] for r in rs}),
            "clocks": [{"label": l, "min": m} for l, m in sorted({(c["label"], c["min"]) for r in rs
                                                                 for c in clk.get(r["partner"], {}).get(r["priority"], [])}, key=lambda x: x[1])],
            "alarms": [{"t": a.get("raised", ""), "device": a.get("device", ""), "signal": a.get("signal", ""), "partner": a.get("partner", "")}
                       for a in alarms[:6]],
            "on_call": SU.on_call(start, su.notify),
            "redundancy": [{"name": g["name"], "hall": g["hall"], "state": g["state"], "text": g["text"], "link": g["link"]} for g in red],
            "work": [{k: j[k] for k in ("id", "owner", "title", "start", "end", "hall", "status")} for j in work],
            "permits": [{k: p[k] for k in ("permit", "type", "job", "point", "partner", "issued", "closed", "title")} for p in permits],
            "spares": su.spares(start),
            "pages": pg,
            "related": sorted({x for r in rs for x in r.get("related") or []} - set(ids)),
            "replay": log or [],
        }
        for i in ids:
            by_record[i] = eid
    return {"events": out, "by_record": by_record}


def console() -> dict[str, Any]:
    """The console's clocks: the runbook's (page acknowledged, command declared, first leadership notice, leads on the
    bridge, leadership cadence, milestones) and the routing file's escalation of an unacknowledged critical notice."""
    n = yaml.safe_load(NOTIFY.read_text(encoding="utf-8"))
    rule = next(r for r in n["rules"] if r["event"] == "critical")
    return {"runbook": command.load_config()["clocks"], "offset_h": n["utc_offset_h"], "timezone": n["timezone"],
            "escalate": [{"after_min": e["after_min"], "to": n["groups"][e["to"]]["label"], "via": e["via"]} for e in rule["escalate"]]}


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
            "facts": f, "paging": command.paging_tree(), "command": command.build(), "responses": responses(),
            "console": console()}
