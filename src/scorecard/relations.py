"""Related records: suggesting that one record in the Incident Portal may be related to another.

Every portal record (incident, change, work order, MOP, preventive maintenance task) already carries the
links its own records make: a MOP number written on a work order, a finding that names both, tickets merged
into one Ticket of Record, a ticket opened on a rack under change. Those are facts and are labeled as such.

This module adds the leads nobody wrote down, scored from the records themselves: the devices the two
records name and how those devices are connected in the device directory (``scorecard.devices``), how the
two windows sit in time, the evidence the Customer already holds (the same alarm, the same finding, a MOP
covering the device and the time), and weaker ties such as the same part or XID. The weights are in
``config/relations.yaml`` and are shown to the reader with every suggestion.

A suggestion is a lead, not a finding: it needs a person to confirm or deny it, and nothing in the
engines, the scorecards, or the reports reads an unconfirmed suggestion. The person who is assigned to a
record is deliberately not a signal: it would read as blaming a person and says little about the fault.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "relations.yaml"
WORD = re.compile(r"[a-z][a-z-]{2,}")


@lru_cache(maxsize=2)
def config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _window(r: dict[str, Any]) -> tuple[datetime, datetime]:
    start = _t(r["start"])
    return start, _t(r["end"]) if r["end"] else start


def _words(text: str, stop: set[str]) -> set[str]:
    return {w for w in WORD.findall((text or "").lower()) if w not in stop}


def _fault_keys(r: dict[str, Any]) -> set[str]:
    """What makes two records the same kind of failure: the XID code, the part numbers, the fault class."""
    keys = {f"xid:{m}" for m in re.findall(r"XID (\d+)", r["summary"] or "")}
    keys |= {f"part:{p.get('part') or ''}".strip().lower() for p in r["parts"] if p.get("part")}
    if r["category"]:
        keys.add(f"class:{r['category'].lower()}")
    return {k for k in keys if k and not k.endswith(":")}


def prepare(records: list[dict[str, Any]], devices: dict[str, Any] | None = None,
            cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """What scoring needs for each record, read once: its window, the devices it names, those devices'
    direct connections, the power and cooling above them, its alarms, findings, and summary words."""
    from scorecard import devices as D
    cfg = cfg or config()
    devices = devices or D.load()
    stop = set(cfg["stop_words"])
    adj = D.adjacency(devices)
    out: dict[str, dict[str, Any]] = {}
    for r in records:
        names = D.names_in(devices, r["device"], f"Rack {r['rack']}" if r["rack"] else "", r["summary"])
        near = set().union(*(adj.get(n, set()) for n in names)) if names else set()
        upstream = _upstream(devices, names)
        start, end = _window(r)
        out[r["id"]] = {"record": r, "start": start, "end": end, "devices": set(names), "near": near - set(names),
                        "upstream": upstream, "rack": r["rack"] or "", "alarms": {a["id"] for a in r["alarms"]},
                        "findings": {f["id"] for f in r["findings"]}, "words": _words(r["summary"], stop),
                        "faults": _fault_keys(r), "mops": {x for x in r["related"] if x.startswith("MOP-")},
                        "type": r["type"]}
    return {"by_id": out, "cfg": cfg, "devices": devices, "adj": adj}


# What "shared power or cooling" means: the power group, the busway and tap-offs that feed a rack, and the
# CDU of its row. The hall's UPS line-ups and the shared cooling header serve too much to mean anything:
# every rack in Hall A shares the header, and a UPS feeds three power groups.
UPSTREAM = {"Power group", "A feed", "B feed", "Busway", "Tap-off", "Primary CDU", "Fed by", "In rack", "Where"}
UPSTREAM_KINDS = {"group", "busway", "tapoff", "cdu", "rack"}

# A connection only means something when both ends are close to the fault. A UPS line-up feeds three power
# groups and a CDU serves a row, so "connected to the same UPS" would make half of Hall A a suggestion;
# those devices count through shared power or cooling instead, which is worth less.
NARROW_KINDS = {"compute_tray", "switch_tray", "power_shelf", "rack", "tapoff", "busway", "leaf", "group", "pump"}


def _upstream(devices: dict[str, Any], names: list[str]) -> set[str]:
    devs = devices["devices"]
    out: set[str] = set()
    for n in names:
        for rel, other, _note in devs[n].get("conn", []):
            if rel in UPSTREAM and other in devs and devs[other]["kind"] in UPSTREAM_KINDS:
                out.add(other)
                for rel2, up, _n2 in devs[other].get("conn", []):   # a tap-off's busway, a busway's power group
                    if rel2 in ("Power group", "Fed by", "On busway", "Busway") and up in devs and devs[up]["kind"] in ("group", "busway"):
                        out.add(up)
    return out - set(names)


def score(prep: dict[str, Any], a: str, b: str) -> dict[str, Any]:
    """Score one pair and say why, in the order a reader would weigh it: place, time, evidence, then the
    weak ties. Returns the score, the reasons, and which groups fired (the ``require`` rule uses them)."""
    cfg, P = prep["cfg"], prep["by_id"]
    x, y = P[a], P[b]
    sig = cfg["signals"]
    hits: list[tuple[str, int, str]] = []

    def hit(name: str, text: str) -> None:
        hits.append((name, sig[name]["points"], text))

    shared = x["devices"] & y["devices"]
    if shared:
        hit("same_device", f"both name {', '.join(sorted(shared))}")
    else:
        adj = prep["adj"]
        devs = prep["devices"]["devices"]
        narrow = lambda n: devs[n]["kind"] in NARROW_KINDS
        pairs = sorted((n, o) for n in x["devices"] for o in y["devices"]
                       if o in adj.get(n, set()) and narrow(n) and narrow(o))
        if pairs:
            hit("connected_device", " and ".join(f"{n} is connected to {o}" for n, o in pairs[:2]))
    if x["rack"] and x["rack"] == y["rack"] and not shared:
        hit("same_rack", f"same rack {x['rack']}")
    up = x["upstream"] & y["upstream"]
    if up and not shared:
        hit("shared_upstream", f"both served by {', '.join(sorted(up)[:2])}")

    gap = max((x["start"] - y["end"]).total_seconds(), (y["start"] - x["end"]).total_seconds()) / 60
    if gap <= 0:
        overlap = min(x["end"], y["end"]) - max(x["start"], y["start"])
        hit("overlapping", f"windows overlap by {_span(overlap)}" if overlap else "windows touch")
    elif gap < 120:
        hit("within_2h", f"{round(gap)} min apart")
    elif gap < 24 * 60:
        hit("within_24h", f"{round(gap / 60, 1)} hours apart")

    if x["alarms"] & y["alarms"]:
        hit("same_alarm", f"alarm {', '.join(sorted(x['alarms'] & y['alarms']))} is tied to both")
    if x["findings"] & y["findings"]:
        hit("same_finding", f"finding {', '.join(sorted(x['findings'] & y['findings']))} names both")
    for one, two in ((x, y), (y, x)):
        if one["type"] == "mop" and one["devices"] & (two["devices"] | two["near"]) and one["start"] <= two["end"] and two["start"] <= one["end"]:
            hit("covering_mop", f"{one['record']['id']} covers {', '.join(sorted(one['devices'] & (two['devices'] | two['near']))[:2])} over this time")
            break
    same = sorted(x["faults"] & y["faults"])
    if same:
        label = {"xid": "XID", "part": "part", "class": "category"}
        hit("same_fault", "same " + ", ".join(f"{label[k.split(':', 1)[0]]} {k.split(':', 1)[1]}" for k in same[:2]))
    words = x["words"] & y["words"]
    if words:
        pts = min(len(words) * 4, sig["shared_words"]["max"])
        hits.append(("shared_words", pts, "summaries share " + ", ".join(sorted(words)[:3])))

    groups = {sig[n]["group"] for n, _, _ in hits}
    total = sum(p for _, p, _ in hits)
    ok = ("place" in groups and "time" in groups) or "evidence" in groups
    return {"score": total if ok else 0, "raw": total, "reasons": [{"signal": n, "points": p, "text": t} for n, p, t in hits],
            "groups": sorted(groups), "qualifies": ok}


def _span(d: timedelta) -> str:
    m = round(d.total_seconds() / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def suggest(records: list[dict[str, Any]], devices: dict[str, Any] | None = None,
            cfg: dict[str, Any] | None = None, curated: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Every record's suggestions, best first: at most ``per_record``, never a pair the records already
    link, and never one a curated relation (``tickets/relations.yaml``) already settles."""
    prep = prepare(records, devices, cfg)
    cfg = prep["cfg"]
    linked = {frozenset((r["id"], x)) for r in records for x in r["related"]}
    settled = {frozenset((c["records"][0], c["records"][1])) for c in (curated or {}).get("relations", [])}
    ids = [r["id"] for r in records]
    out: dict[str, list[dict[str, Any]]] = {i: [] for i in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            pair = frozenset((a, b))
            if pair in linked or pair in settled:
                continue
            s = score(prep, a, b)
            if s["score"] < cfg["threshold"]:
                continue
            for one, two in ((a, b), (b, a)):
                out[one].append({"id": two, "score": s["score"], "reasons": s["reasons"]})
    for i in ids:
        out[i] = sorted(out[i], key=lambda s: (-s["score"], s["id"]))[:cfg["per_record"]]
    return out


# --------------------------------------------------------------------------- #
# Curated relations: the calls people have made, kept in the repository
# --------------------------------------------------------------------------- #

CURATED = ROOT / "tickets" / "relations.yaml"


def load_curated(path: Path = CURATED) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"relations": []}


def check_curated(curated: dict[str, Any], records: list[dict[str, Any]], cfg: dict[str, Any] | None = None) -> list[str]:
    """Every curated relation must name two records that exist, a type the configuration offers, a person's
    role and a date, and a reason; and the pair must not already be linked in the records."""
    cfg = cfg or config()
    by_id = {r["id"]: r for r in records}
    types = {t["id"] for t in cfg["types"]}
    bad = []
    for c in curated.get("relations", []):
        a, b = (c.get("records") or ["", ""])[:2] if len(c.get("records") or []) == 2 else ("", "")
        if a not in by_id or b not in by_id or a == b:
            bad.append(f"{c.get('records')}: not two records of this month")
            continue
        if c.get("type") not in types:
            bad.append(f"{a} and {b}: type {c.get('type')!r} is not one of {sorted(types)}")
        if not (c.get("confirmed_by") and c.get("confirmed_on") and (c.get("reason") or "").strip()):
            bad.append(f"{a} and {b}: needs confirmed_by, confirmed_on, and a reason")
        if b in by_id[a]["related"]:
            bad.append(f"{a} and {b}: already linked in the records, so a person's call adds nothing")
    return bad


def apply_curated(records: list[dict[str, Any]], curated: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Curated relations by record, both ways, for the portal to show beside the links in the records."""
    out: dict[str, list[dict[str, Any]]] = {r["id"]: [] for r in records}
    for c in curated.get("relations", []):
        a, b = c["records"]
        for one, two in ((a, b), (b, a)):
            if one in out:
                out[one].append({"id": two, "type": c["type"], "reason": c["reason"],
                                 "confirmed_by": c["confirmed_by"], "confirmed_on": c["confirmed_on"]})
    return out


# --------------------------------------------------------------------------- #
# Measurement: does the scoring find the links the records already make, and does it stay quiet on decoys?
# --------------------------------------------------------------------------- #

def evaluate(records: list[dict[str, Any]], devices: dict[str, Any] | None = None,
             cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recall against the links the records themselves make (a MOP written on a work order, a finding that
    names both records, tickets merged into one Ticket of Record), and false positives against decoys:
    pairs a person would reject. The scoring never reads either set.

    Decoys, each one a shape that must not reach the threshold on its own:

    * same rack but more than 7 days apart (a place with no time),
    * overlapping in time in different halls, with no device in common and none connected (a time with no place),
    * the same fault family far apart in both place and time (a family resemblance only).
    """
    prep = prepare(records, devices, cfg)
    cfg = prep["cfg"]
    P, ids = prep["by_id"], [r["id"] for r in records]
    thr = cfg["threshold"]
    links, misses = set(), []
    for r in records:
        for x in r["related"]:
            if x in P:
                links.add(frozenset((r["id"], x)))
    for pair in sorted(map(sorted, links)):
        s = score(prep, *pair)
        if s["score"] < thr:
            misses.append({"pair": pair, "score": s["score"], "raw": s["raw"], "reasons": s["reasons"]})
    decoys: dict[str, list[list[str]]] = {"same_place_far_apart": [], "same_time_other_hall": [], "same_fault_only": []}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if frozenset((a, b)) in links:
                continue
            x, y = P[a], P[b]
            gap = max((x["start"] - y["end"]).total_seconds(), (y["start"] - x["end"]).total_seconds()) / 60
            connected = bool(x["devices"] & y["devices"]) or bool(
                [1 for n in x["devices"] for o in y["devices"] if o in prep["adj"].get(n, set())])
            hall = lambda r: (r["record"]["hall"] or "")[-1:]
            if x["rack"] and x["rack"] == y["rack"] and gap > 7 * 24 * 60:
                decoys["same_place_far_apart"].append([a, b])
            elif gap <= 0 and hall(x) and hall(y) and hall(x) != hall(y) and not connected and not (x["upstream"] & y["upstream"]):
                decoys["same_time_other_hall"].append([a, b])
            elif x["faults"] & y["faults"] and gap > 7 * 24 * 60 and not connected and x["rack"] != y["rack"]:
                decoys["same_fault_only"].append([a, b])
    bad = {k: [{"pair": p, "score": score(prep, *p)["score"]} for p in v if score(prep, *p)["score"] >= thr]
           for k, v in decoys.items()}
    sug = suggest(records, devices, cfg)
    return {"links": len(links), "found": len(links) - len(misses), "missed": misses,
            "decoys": {k: len(v) for k, v in decoys.items()}, "false": {k: v for k, v in bad.items() if v},
            "suggested_pairs": sum(len(v) for v in sug.values()) // 2,
            "records_with_suggestions": sum(1 for v in sug.values() if v),
            "top": sorted(({"pair": sorted((i, s["id"])), "score": s["score"],
                            "reasons": [r["text"] for r in s["reasons"]]} for i, v in sug.items() for s in v),
                          key=lambda s: -s["score"])[:6]}
