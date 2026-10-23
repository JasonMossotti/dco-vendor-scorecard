"""The AUS-1 training portal: equipment courses, alarm job guides, preventive maintenance guides, and quizzes
(the Training tab's Courses, Job guides, PM guides, and Quizzes views).

The content lives in config/training/ (courses.yaml, guides.yaml, pm.yaml, quizzes.yaml). The prose there is general
knowledge written from public references; everything site-specific on the page is computed here from the site data,
so a test can check every number and name:

* the site model (site/site.yaml products), the device directory (docs/site/devices.json), and the drawings
  (docs/site/locations.json sheets);
* the Interface Agreement RACI, the certification register's credentials and work rules (config/certifications.yaml),
  the EHS permits and courses (config/ehs.yaml), the calendar's work types and forward schedule
  (config/calendar.yaml, data/calendar/schedule.json), and the emergency procedures (config/emergency.yaml);
* the sample month's alarm board and Incident Portal records, as examples of how the equipment fails here.

``validate()`` returns every place the content and the data disagree; the tests require it to be empty. Quizzes are
scored in the browser only: nothing is recorded, and a quiz is not a credential.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from scorecard import alarms as A
from scorecard import tickets as T
from scorecard.sla_model import load_interface_agreement

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "training"
SITE = ROOT / "site" / "site.yaml"
DEVICES = ROOT / "docs" / "site" / "devices.json"
LOCATIONS = ROOT / "docs" / "site" / "locations.json"
SAMPLE = ROOT / "data" / "sample"
CHANGES = ROOT / "data" / "changes"
SCHEDULE = ROOT / "data" / "calendar" / "schedule.json"
SECURITY = ROOT / "config" / "security.yaml"
PARTNERS = {"it": "IT Partner", "landlord": "Landlord", "security": "Security Partner", "all": "Everyone"}
QUIZ_KEYS = ("orientation", "it", "landlord", "security")
PROSE = {"courses": ("what", "failures", "safety"), "guides": ("means", "first15", "safety", "steps", "rts"),
         "pm": ("frequency", "why", "steps", "acceptance", "record")}
EXAMPLES = 6                    # records shown as examples on a course or guide


def _yaml(p: Path) -> Any:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _natural(s: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


@lru_cache(maxsize=1)
def content() -> dict[str, Any]:
    """The four content files, each with its own references."""
    out: dict[str, Any] = {}
    for name in ("courses", "guides", "pm", "quizzes"):
        out[name] = _yaml(CFG / f"{name}.yaml")
    return out


def references(c: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Every reference across the four files, by id (an id is unique across the files)."""
    c = c or content()
    out: dict[str, dict[str, Any]] = {}
    for name in ("courses", "guides", "pm", "quizzes"):
        for r in c[name].get("references") or []:
            out[r["id"]] = {**r, "file": name}
    return out


@lru_cache(maxsize=1)
def sources() -> dict[str, Any]:
    """The site data the portal reads."""
    site = _yaml(SITE)
    dev = _json(DEVICES)
    loc = _json(LOCATIONS)
    ia = load_interface_agreement()
    certs = _yaml(ROOT / "config" / "certifications.yaml")
    ehs = _yaml(ROOT / "config" / "ehs.yaml")
    cal = _yaml(ROOT / "config" / "calendar.yaml")
    em = _yaml(ROOT / "config" / "emergency.yaml")
    check = A.run_check(SAMPLE, CHANGES)
    alarms = [A.alarm_dict(a) for a in check["alarms"]]
    recs = T.build()["records"]
    recs = list(recs.values()) if isinstance(recs, dict) else recs
    return {"site": site, "devices": dev["devices"], "kinds": dev["kinds"], "sheets": loc["sheets"],
            "raci": {r["component"]: r for r in ia["raci"]}, "certs": certs, "ehs": ehs, "calendar": cal,
            "work_types": {w["type"]: w for w in cal["work_types"]}, "schedule": _json(SCHEDULE),
            "procedures": {t["id"]: t for t in em["types"]}, "alarms": alarms, "records": recs,
            "security": _yaml(SECURITY), "window": check["window"]}


def configured_signals(s: dict[str, Any] | None = None) -> list[str]:
    """Every fixed signal name the alarm map can raise (config/change_alarms.yaml), beside the BMS free texts the
    sample carries. A job guide must match each one."""
    m = A.load_config()["alarm_map"]
    out: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("signal"), str):
                out.add(o["signal"])
            for v in o.values():
                walk(v)
    walk(m)
    out.add(m["it"]["xid_signal"])
    out.update({"Smoke alarm", "Change window overrun", "Condenser fan fault"})
    return sorted(out)


# ------------------------------------------------------------------ matching
def _hall(h: str | None) -> str | None:
    """A record's HALL-A and a device's Hall A are the same hall."""
    m = re.fullmatch(r"(?i)hall[- ]([a-z])", h or "")
    return f"Hall {m.group(1).upper()}" if m else None


def _hall_ok(c: dict[str, Any], hall: str | None) -> bool:
    return not c.get("hall") or c["hall"] == _hall(hall)


def course_for_device(name: str, s: dict[str, Any] | None = None) -> str | None:
    """The one course that covers a device in the directory, by its kind and hall."""
    s = s or sources()
    d = s["devices"].get(name)
    if not d:
        return None
    hits = [c["id"] for c in content()["courses"]["courses"] if d["kind"] in c["kinds"] and _hall_ok(c, d.get("hall"))]
    return hits[0] if len(hits) == 1 else None


def courses_for_kind(kind: str, hall: str | None) -> list[str]:
    return [c["id"] for c in content()["courses"]["courses"] if kind in c["kinds"] and _hall_ok(c, hall)]


def courses_for_category(category: str, hall: str | None) -> list[str]:
    return [c["id"] for c in content()["courses"]["courses"] if category in c["categories"] and _hall_ok(c, hall)]


def guides_for_signal(signal: str) -> list[str]:
    return [g["id"] for g in content()["guides"]["guides"] if any(re.search(p, signal) for p in g["signals"])]


def guides_for_category(category: str) -> list[str]:
    return [g["id"] for g in content()["guides"]["guides"] if category in g["categories"]]


def _pm_pattern(p: dict[str, Any], s: dict[str, Any]) -> str | None:
    if p.get("match"):
        return p["match"]
    w = s["work_types"].get(p["id"])
    return w["match"] if w else None


def pm_for_title(title: str, s: dict[str, Any] | None = None) -> list[str]:
    s = s or sources()
    return [p["id"] for p in content()["pm"]["pm"] if (pat := _pm_pattern(p, s)) and re.search(pat, title)]


def record_links(r: dict[str, Any], s: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """The training a record points at: the job guides of its alarms (or its category), the PM guide its title
    names, and the course of its category or device."""
    s = s or sources()
    guides = sorted({g for a in r.get("alarms") or [] for g in guides_for_signal(a["signal"])} | set(guides_for_category(r.get("category") or "")))
    pm = pm_for_title(r.get("summary") or "", s)
    courses = courses_for_category(r.get("category") or "", r.get("hall") or None)
    for name in (r.get("device"), r.get("location")):
        if not courses and name:
            c = course_for_device(name, s)
            courses = [c] if c else []
    if not courses:
        courses = sorted({content_by_id("guides")[g]["course"] for g in guides} | {content_by_id("pm")[p]["course"] for p in pm})
    return {"guides": guides, "pm": pm, "courses": courses}


def record_training(records: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, dict[str, list[list[str]]]]:
    """Each Incident Portal record's training links as [id, title] pairs (the portal's record panel)."""
    rs = list(records.values()) if isinstance(records, dict) else records
    t = {n: {x["id"]: x["title"] for x in content_by_id(n).values()} for n in ("courses", "guides", "pm")}
    out = {}
    for r in rs:
        k = record_links(r)
        out[r["id"]] = {"guides": [[g, t["guides"][g]] for g in k["guides"]], "pm": [[p, t["pm"][p]] for p in k["pm"]],
                        "courses": [[c, t["courses"][c]] for c in k["courses"]]}
    return out


def content_by_id(name: str) -> dict[str, dict[str, Any]]:
    key = {"courses": "courses", "guides": "guides", "pm": "pm"}[name]
    return {x["id"]: x for x in content()[name][key]}


def kind_courses() -> dict[str, dict[str, str]]:
    """kind -> {hall or "": course id}, for the device directory's links (a course without a hall covers every hall)."""
    out: dict[str, dict[str, str]] = {}
    for c in content()["courses"]["courses"]:
        for k in c["kinds"]:
            out.setdefault(k, {})[c.get("hall") or ""] = c["id"]
    return out


def sheet_courses() -> dict[str, str]:
    """Detail sheet -> course, for the drawing card's link."""
    return {sh: c["id"] for c in content()["courses"]["courses"] for sh in c["sheets"] if sh.startswith("D-")}


def signal_guides(s: dict[str, Any] | None = None) -> dict[str, str]:
    """Each signal on the board -> its one job guide (the alarm board's links)."""
    s = s or sources()
    out = {}
    for sig in sorted({a["signal"] for a in s["alarms"]} | set(configured_signals(s))):
        g = guides_for_signal(sig)
        if len(g) == 1:
            out[sig] = g[0]
    return out


# ------------------------------------------------------------------ views
def _cred(s: dict[str, Any], key: str) -> dict[str, Any]:
    c = s["certs"]["credentials"].get(key)
    if c:
        return {"id": key, "name": c["name"], "months": c["months"], "issuer": c["issuer"], "partner": PARTNERS[c["partner"]]}
    e = s["ehs"]["courses"][key]
    return {"id": key, "name": e["name"], "months": e["months"], "issuer": "EHS training (config/ehs.yaml)", "partner": "EHS"}


def _raci(s: dict[str, Any], row: str) -> dict[str, Any]:
    r = s["raci"][row]
    return {"component": row, **{k: v for k, v in r.items() if k != "component"}}


def _owner(s: dict[str, Any], row: str) -> str:
    r = s["raci"][row]
    resp = [p for p, v in r.items() if p != "component" and "R" in str(v)]
    return ", ".join(resp)


def _rec(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "summary": r["summary"], "start": r["start"], "partner": r["partner"], "device": r.get("device") or ""}


def _records_for_course(c: dict[str, Any], s: dict[str, Any]) -> list[dict[str, Any]]:
    out = [r for r in s["records"] if c["id"] in record_links(r, s)["courses"]]
    return sorted(out, key=lambda r: r["start"])


def course_view(c: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    prods = [{"key": k, "manufacturer": s["site"]["products"][k]["manufacturer"], "model": s["site"]["products"][k]["model"],
              "interfaces": s["site"]["products"][k].get("interfaces", []), "sources": s["site"]["products"][k].get("sources", [])}
             for k in c["products"]]
    devs = []
    for k in c["kinds"]:
        names = sorted((n for n, d in s["devices"].items() if d["kind"] == k and _hall_ok(c, d.get("hall"))), key=_natural)
        devs.append({"kind": k, "label": s["kinds"][k], "count": len(names), "names": names if len(names) <= 16 else names[:8],
                     "more": max(0, len(names) - 16) and len(names) - 8})
    recs = _records_for_course(c, s)
    guides = [g["id"] for g in content()["guides"]["guides"] if g["course"] == c["id"]]
    pms = [p["id"] for p in content()["pm"]["pm"] if p["course"] == c["id"]]
    return {"id": c["id"], "title": c["title"], "partner": PARTNERS[c["partner"]], "hall": c.get("hall") or "",
            "products": prods, "devices": devs,
            "sheets": [{"num": sh, "title": s["sheets"][sh]["title"], "file": s["sheets"][sh]["file"]} for sh in c["sheets"]],
            "raci": [_raci(s, r) for r in c["raci"]], "credentials": [_cred(s, k) for k in c["credentials"]],
            "records": [_rec(r) for r in recs[:EXAMPLES]], "record_count": len(recs),
            "guides": guides, "pm": pms, "what": c["what"], "failures": c["failures"], "safety": c["safety"], "refs": c["refs"]}


def _work_needs(g: dict[str, Any], s: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Credentials and permits the guide's work needs, from the register's and the EHS work rules."""
    creds: list[str] = []
    permits: list[str] = []
    w = s["certs"]["work"]
    recs = [r for r in s["records"] if g["id"] in record_links(r, s)["guides"]]
    for r in recs:
        cat = r.get("category") or ""
        if cat in w["it_incident"]:
            creds += w["it_incident"][cat]["needs"]
            if w["it_incident"][cat].get("model") and r.get("hall"):
                creds.append(w["rack_model"].get(r["hall"][-1], ""))
        if cat in w["landlord_work_order"]:
            creds += w["landlord_work_order"][cat]
        for rule in s["ehs"]["jobs"]["work_orders"]:
            if rule.get("fault_class") == cat:
                permits += rule["permits"]
                if rule.get("electrical"):
                    creds.append("nfpa70e")
        if r["type"] == "sir":
            creds += w["guard_post"]
    creds = [c for c in dict.fromkeys(creds) if c]
    return creds, list(dict.fromkeys(permits))


def guide_view(g: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    al = [a for a in s["alarms"] if g["id"] in guides_for_signal(a["signal"])]
    recs = sorted((r for r in s["records"] if g["id"] in record_links(r, s)["guides"]), key=lambda r: r["start"])
    creds, permits = _work_needs(g, s)
    proc = s["procedures"].get(g["procedure"]) if g.get("procedure") else None
    sev = Counter(a["severity"] for a in al)
    return {"id": g["id"], "title": g["title"], "course": g["course"], "owner": g.get("owner") or _owner(s, g["raci"]),
            "raci": _raci(s, g["raci"]) if g["raci"] else None,
            "alarm_count": len(al), "severity": dict(sev), "devices": sorted({a["device"] for a in al}, key=_natural)[:8],
            "alarms": [{"id": a["id"], "device": a["device"], "summary": a["summary"], "raised": a["raised"], "severity": a["severity"]}
                       for a in sorted(al, key=lambda a: a["raised"])[:EXAMPLES]],
            "records": [_rec(r) for r in recs[:EXAMPLES]], "record_count": len(recs),
            "credentials": [_cred(s, k) for k in creds],
            "permits": [{"id": p, **s["ehs"]["permit_types"][p]} for p in permits],
            "procedure": {"id": proc["id"], "name": proc["name"]} if proc else None,
            "means": g["means"], "first15": g["first15"], "safety": g["safety"], "steps": g["steps"], "rts": g["rts"], "refs": g["refs"]}


def pm_view(p: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    w = s["work_types"].get(p["id"])
    pat = _pm_pattern(p, s)
    recs = sorted((r for r in s["records"] if re.search(pat, r.get("summary") or "")), key=lambda r: r["start"]) if pat else []
    fwd = sorted((j for j in s["schedule"] if pat and re.search(pat, j["title"])), key=lambda j: j["window_start"])
    ehs_job = s["ehs"]["jobs"]["work_types"].get(p["id"], {})
    permits = [{"id": k, **s["ehs"]["permit_types"][k]} for k in ehs_job.get("permits", [])]
    creds = list(s["certs"]["schedule_work"].get(p["id"], []))
    if ehs_job.get("electrical") and "nfpa70e" not in creds:
        creds.append("nfpa70e")
    if p["id"] == "fiber_clean":
        creds = s["certs"]["work"]["it_incident"]["optic_link"]["needs"]
    return {"id": p["id"], "title": p["title"], "course": p["course"], "partner": PARTNERS[p["partner"]],
            "work_type": bool(w), "minutes": w["minutes"] if w else None, "mop": w["mop"] if w else None,
            "takes": w["takes"] if w else None, "per_month": s["calendar"]["schedule"]["per_month"].get(p["id"]),
            "permits": permits, "credentials": [_cred(s, k) for k in creds], "lock": ehs_job.get("lock"),
            "records": [_rec(r) for r in recs[:EXAMPLES]], "record_count": len(recs),
            "forward": [{"id": j["id"], "title": j["title"], "start": j["window_start"]} for j in fwd[:EXAMPLES]], "forward_count": len(fwd),
            "frequency": p["frequency"], "why": p["why"], "steps": p["steps"], "acceptance": p["acceptance"], "record": p["record"], "refs": p["refs"]}


# ------------------------------------------------------------------ quizzes
def _q(qid: str, q: str, answer: str, wrong: list[str], why: str, rng: random.Random, source: str) -> dict[str, Any]:
    opts = [answer] + [w for w in dict.fromkeys(wrong) if w != answer][:3]
    rng.shuffle(opts)
    return {"id": qid, "q": q, "options": opts, "answer": opts.index(answer), "why": why, "source": source}


def _num_wrong(n: int) -> list[str]:
    return [str(x) for x in (n + 1, n - 1 if n > 1 else n + 3, n * 2, n + 2) if x != n]


def computed_questions(s: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Site questions with answers read from the data. Deterministic (a fixed seed shuffles the options)."""
    s = s or sources()
    rng = random.Random(2026)
    site, dev, sec = s["site"], s["devices"], s["site"]["security"]
    count = Counter((d["kind"], d.get("hall")) for d in dev.values())
    kinds = Counter(d["kind"] for d in dev.values())
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in QUIZ_KEYS}
    parties = site["parties"]
    names = [parties[k]["name"] for k in ("landlord", "it_partner", "security_partner")]

    o = out["orientation"]
    o.append(_q("o-landlord", "Who owns the building, power, cooling, and CDUs at AUS-1?", parties["landlord"]["name"],
                names + ["The Customer"], "The Landlord runs the building and its plant under the Landlord SLA.", rng, "site/site.yaml parties"))
    o.append(_q("o-security", "Who guards the whole property, inside and outside the fence?", parties["security_partner"]["name"],
                names + ["The Landlord's own staff"], "The Security Partner's scope covers the whole property (Security SLA, SEC-POST).", rng,
                "site/site.yaml parties; sla/security_partner.yaml"))
    zones = sec["zones"]
    gh = next(z for z in zones if "Guard house" in z["where"] or "guard house" in z["where"].lower()) if any(
        "guard house" in z["where"].lower() for z in zones) else zones[1]
    o.append(_q("o-zones", "How many security zones does the site plan define (Z0 and up)?", str(len(zones)), _num_wrong(len(zones)),
                "Zones Z0 to Z2 are on sheet A-002, Z3 and up on sheet A-102.", rng, "site/site.yaml security.zones"))
    z_hall = next(z for z in zones if z["id"] == "Z5")
    o.append(_q("o-z5", "Which zone is the data hall floor?", z_hall["id"] + ": " + z_hall["name"],
                [z["id"] + ": " + z["name"] for z in zones if z["id"] != "Z5"][:5], "Zone names come from the security site plan.", rng,
                "site/site.yaml security.zones"))
    o.append(_q("o-gh-zone", "Where does an exterior tour start and end?", "The guard house",
                ["The security lobby", "The loading dock", "The NOC"], f"The exterior tour runs every {sec['exterior_tour']['every_h']} hours from the guard house.",
                rng, "site/site.yaml security.exterior_tour"))
    o.append(_q("o-tour", "How often does the exterior tour run?", f"Every {sec['exterior_tour']['every_h']} hours",
                [f"Every {h} hours" for h in (2, 6, 8, 12) if h != sec["exterior_tour"]["every_h"]], "From the post orders.", rng,
                "site/site.yaml security.exterior_tour"))
    halls = [h for h in site["halls"]] if isinstance(site["halls"], list) else list(site["halls"])
    o.append(_q("o-halls", "How many data halls does the site model have?", str(len(halls)), _num_wrong(len(halls)),
                "Halls A and B are in production; Hall C is the 800 VDC pilot.", rng, "site/site.yaml halls"))
    gens = kinds["gen"]
    o.append(_q("o-gens", "How many generators carry the site when the utility is lost?", str(gens), _num_wrong(gens),
                "N+1 on the paralleling bus.", rng, "docs/site/devices.json"))
    for k in ("loto", "eewp", "height", "hot"):
        pt = s["ehs"]["permit_types"][k]
        o.append(_q(f"o-permit-{k}", f"Which site rule requires the {pt['name'].lower()} permit?", pt["rule"],
                    [x["rule"] for kk, x in s["ehs"]["permit_types"].items() if kk != k], "From the EHS permit types.", rng, "config/ehs.yaml permit_types"))
    o.append(_q("o-orientation-months", "How long does site orientation stay current?", f"{s['ehs']['courses']['orientation']['months']} months",
                ["6 months", "24 months", "36 months"], "Everyone renews site orientation on this cycle.", rng, "config/ehs.yaml courses"))

    it = out["it"]
    for hall, model in (("Hall A", "GB200 NVL72"), ("Hall B", "GB300 NVL72")):
        n = count[("rack", hall)]
        it.append(_q(f"it-racks-{hall[-1]}", f"How many {model} racks are in {hall}?", str(n), _num_wrong(n), "From the device directory.", rng,
                     "docs/site/devices.json"))
    a01 = dev["A01"]
    ct = sum(1 for n, d in dev.items() if d["kind"] == "compute_tray" and n.startswith("a01-"))
    sw = sum(1 for n, d in dev.items() if d["kind"] == "switch_tray" and n.startswith("a01-"))
    ps = sum(1 for n, d in dev.items() if d["kind"] == "power_shelf" and n.startswith("A01_"))
    it.append(_q("it-trays", "How many compute trays are in one NVL72 rack?", str(ct), _num_wrong(ct), "Rack A01 in the device directory.", rng, "docs/site/devices.json"))
    it.append(_q("it-nvsw", "How many NVLink switch trays are in one NVL72 rack?", str(sw), _num_wrong(sw), "Rack A01 in the device directory.", rng, "docs/site/devices.json"))
    it.append(_q("it-shelves", "How many power shelves feed one NVL72 rack at AUS-1?", str(ps), _num_wrong(ps), "Rack A01 in the device directory.", rng, "docs/site/devices.json"))
    cdu = next(c[1] for c in a01["conn"] if c[0] == "Primary CDU")
    it.append(_q("it-a01-cdu", "Which CDU is primary for rack A01?", cdu, ["CDU-A2", "CDU-A3", "CDU-B1", "CDU-A4"],
                 "Racks draw from the shared hall header; the row's CDU is primary.", rng, "docs/site/devices.json"))
    feed = next(c[1] for c in a01["conn"] if c[0] == "A feed")
    it.append(_q("it-a01-feed", "Which tap-off is rack A01's A feed?", feed, ["TO-A01-B", "TO-A02-A", "TO-B01-A"], "From the device directory.", rng,
                 "docs/site/devices.json"))
    w = s["certs"]["work"]["it_incident"]
    it.append(_q("it-optic-needs", "Besides ESD control, which credential must you hold to work an optic or link ticket?",
                 _cred(s, "fiber")["name"], [_cred(s, k)["name"] for k in ("liquid", "custody", "ncp_aii")],
                 "The work gate checks it at the ticket time.", rng, "config/certifications.yaml work.it_incident"))
    it.append(_q("it-hallb-tray", "Which manufacturer-authorized credential does tray work in Hall B need?", _cred(s, "oem_gb300")["name"],
                 [_cred(s, "oem_gb200")["name"], _cred(s, "ncp_aii")["name"], _cred(s, "liquid")["name"]],
                 "Hall B racks are GB300; the work gate checks the rack model.", rng, "config/certifications.yaml work.rack_model"))
    lead = s["certs"]["roles"]["it"]["shift_lead"]
    tech = s["certs"]["roles"]["it"]["technician"]
    extra = [k for k in lead if k not in tech][0]
    it.append(_q("it-lead", "Which credential does a shift lead hold that a technician does not need?", _cred(s, extra)["name"],
                 [_cred(s, k)["name"] for k in tech[:3]], "The IT SLA's key personnel rule.", rng, "config/certifications.yaml roles"))
    raci = s["raci"]["Rack manifold, isolation valves, quick-disconnects"]
    it.append(_q("it-qd-raci", "Who is Responsible for the rack manifold, isolation valves, and quick disconnects?", "IT Partner",
                 ["Landlord", "Customer", "OEM"], f"RACI: Landlord {raci['Landlord']}, IT Partner {raci['IT Partner']}.", rng, "sla/interface_agreement.yaml raci"))
    raci = s["raci"]["CDUs and the hall secondary header"]
    it.append(_q("it-cdu-raci", "Who is Accountable and Responsible for the CDUs and the hall secondary header?", "Landlord",
                 ["IT Partner", "Customer", "OEM"], f"RACI: IT Partner {raci['IT Partner']}.", rng, "sla/interface_agreement.yaml raci"))

    ll = out["landlord"]
    for k, label in (("ups", "IT UPS modules"), ("chiller", "chillers"), ("cdu", "CDUs"), ("tw", "thermal walls")):
        n = kinds[k]
        ll.append(_q(f"ll-count-{k}", f"How many {label} are on site?", str(n), _num_wrong(n), "From the device directory.", rng, "docs/site/devices.json"))
    for wt in ("ups_pm", "thermography", "tapoff_energize"):
        j = s["ehs"]["jobs"]["work_types"][wt]
        ans = ", ".join(s["ehs"]["permit_types"][p]["name"] for p in j["permits"]) or "No permit"
        wrongs = ["No permit", "Hot work", "Confined space", "Lockout/tagout", "Energized electrical work, Working at height",
                  "Working at height"]
        title = content_by_id("pm")[wt]["title"]
        ll.append(_q(f"ll-permit-{wt}", f"Which permits does this job need? {title}.", ans, wrongs, "From the EHS job rules.", rng, "config/ehs.yaml jobs"))
    for wt in ("chiller_pm", "ups_pm"):
        ans = ", ".join(_cred(s, k)["name"] for k in s["certs"]["schedule_work"][wt])
        alt = [", ".join(_cred(s, k)["name"] for k in s["certs"]["schedule_work"][o]) for o in ("cdu_filter", "tapoff_work", "gen_exercise", "vesda_test") if o != wt]
        ll.append(_q(f"ll-creds-{wt}", f"What must the engineer hold for this job? {content_by_id('pm')[wt]['title']}.", ans, alt,
                     "The register's bench check uses the same list.", rng, "config/certifications.yaml schedule_work"))
    ups = dev["UPS-A1"]
    uss = next(c[1] for c in ups["conn"] if c[0] == "Fed by")
    ll.append(_q("ll-ups-fed", "Which unit substation feeds UPS-A1?", uss, ["USS-A2", "USS-B1", "USS-CH1"], "From the one-line and device directory.", rng,
                 "docs/site/devices.json"))
    ll.append(_q("ll-fuel", "How many hours of generator fuel does the site hold at full load?", str(site["plants"]["generators"]["fuel_hours_at_full_load"]),
                 _num_wrong(site["plants"]["generators"]["fuel_hours_at_full_load"]), "A site model assumption.", rng, "site/site.yaml plants"))
    epa = s["certs"]["credentials"]["epa608"]
    ll.append(_q("ll-epa", "How long does EPA Section 608 certification stay current?", "It does not expire", ["12 months", "36 months", "60 months"],
                 epa["basis"], rng, "config/certifications.yaml credentials"))

    se = out["security"]
    gates = sec["gates"]
    se.append(_q("se-gates", "How many property gates are on the security site plan?", str(len(gates)), _num_wrong(len(gates)), "Sheet A-002.", rng,
                 "site/site.yaml security.gates"))
    xc = sec["exterior_tour"]["checkpoints"]
    se.append(_q("se-xc", "How many checkpoints does the exterior tour scan?", str(len(xc)), _num_wrong(len(xc)), "Sheet A-002.", rng,
                 "site/site.yaml security.exterior_tour"))
    xcam = [c for c in sec["exterior_cameras"]]
    se.append(_q("se-xcam", "Which recorder holds the exterior cameras?", sec["exterior_recorder"], ["NVR-1", "NVR-2", "NVR-3", "NVR-4"], "Sheet A-002.", rng,
                 "site/site.yaml security"))
    se.append(_q("se-xcam-n", "How many exterior cameras are on the property?", str(len(xcam)), _num_wrong(len(xcam)), "Sheet A-002.", rng,
                 "site/site.yaml security.exterior_cameras"))
    main = next(g for g in gates if g["id"] == "GATE-MAIN")
    se.append(_q("se-main-cam", "Which camera watches the main gate?", main["camera"], [c["id"] for c in xcam if c["id"] != main["camera"]][:3],
                 "Every gate has an exterior camera on it.", rng, "site/site.yaml security.gates"))
    cam = dev["CAM-B-04"]
    nvr = next(c[1] for c in cam["conn"] if c[0] == "Records to")
    se.append(_q("se-cam-b04", "Which recorder does CAM-B-04 record to?", nvr, [f"NVR-{i}" for i in range(1, 6) if f"NVR-{i}" != nvr],
                 "From the device directory.", rng, "docs/site/devices.json"))
    posts = s["site"]["security"]["posts"]
    se.append(_q("se-posts", "How many guard posts are staffed?", str(len(posts)), _num_wrong(len(posts)), "From the post list.", rng,
                 "site/site.yaml security.posts"))
    ext = s["certs"]["work"]["exterior_posts"]
    se.append(_q("se-stg-posts", "Which posts draw a shotgun from the guard house rack?", " and ".join(ext),
                 ["POST-HA and POST-HB", "POST-SOC and POST-HA", "POST-SOC only"], "A shotgun never enters a data hall.", rng,
                 "config/certifications.yaml work.exterior_posts"))
    for k in ("firearm_sa", "dps_commission"):
        c = s["certs"]["credentials"][k]
        se.append(_q(f"se-{k}", f"How long does this stay current: {c['name']}?", f"{c['months']} months",
                     [f"{m} months" for m in (6, 12, 24, 36, 60) if m != c["months"]], c["basis"], rng, "config/certifications.yaml credentials"))
    raci = s["raci"]["Property perimeter, gates, and patrols"]
    se.append(_q("se-perimeter", "Who maintains the fences, gates, and readers (as opposed to guarding them)?", "Landlord",
                 ["Security Partner", "IT Partner", "Customer"], f"RACI: Landlord {raci['Landlord']}, Security Partner {raci['Security Partner']}.", rng,
                 "sla/interface_agreement.yaml raci; sla/security_partner.yaml out_of_scope"))
    return out


def quiz_view(key: str, s: dict[str, Any]) -> dict[str, Any]:
    q = content()["quizzes"]["quizzes"][key]
    written = [{"id": f"{key}-w{i + 1}", **w, "source": "written"} for i, w in enumerate(q["written"] or [])]
    comp = computed_questions(s)[key]
    return {"id": key, "title": q["title"], "for": q["for"], "questions": comp + written, "computed": len(comp), "written": len(written)}


# ------------------------------------------------------------------ the page and the checks
def page_data() -> dict[str, Any]:
    """The portal's views. References (titles, publishers, web addresses, and each item's list of them) are split off
    into ``refs``: the page carries them in their own script block, outside the codes the Glossary explains, since
    document titles and web addresses are not site codes."""
    s = sources()
    c = content()
    out = {"courses": [course_view(x, s) for x in c["courses"]["courses"]],
           "guides": [guide_view(x, s) for x in c["guides"]["guides"]],
           "pm": [pm_view(x, s) for x in c["pm"]["pm"]],
           "quizzes": [quiz_view(k, s) for k in QUIZ_KEYS],
           "partners": PARTNERS}
    refs: dict[str, Any] = {"list": {k: {f: v[f] for f in ("title", "url", "publisher", "checked") if f in v} | {"login": bool(v.get("login"))}
                                     for k, v in sorted(references(c).items())}, "items": {}, "sources": {}}
    for kind in ("courses", "guides", "pm"):
        for x in out[kind]:
            refs["items"][f"{kind}:{x['id']}"] = x.pop("refs")
    for x in out["courses"]:
        refs["sources"][x["id"]] = [u for p in x["products"] for u in p.pop("sources")]
    for q in out["quizzes"]:
        for x in q["questions"]:
            if x.get("ref"):
                refs["items"][f"quiz:{x['id']}"] = [x.pop("ref")]
    out["refs"] = refs
    return out


def validate() -> list[str]:
    """Every place the content and the data disagree (empty when they reconcile)."""
    s = sources()
    c = content()
    refs = references(c)
    errs: list[str] = []
    seen_ids: set[str] = set()
    for name in ("courses", "guides", "pm"):
        key = name
        for x in c[name][key]:
            if x["id"] in seen_ids and name == "courses":
                errs.append(f"duplicate id {x['id']}")
            for f in PROSE[name]:
                v = x.get(f)
                if v in (None, "", "TODO", []) or (isinstance(v, list) and any(not str(i).strip() or i == "TODO" for i in v)):
                    errs.append(f"{name} {x['id']}: {f} not written")
            for r in x.get("refs") or []:
                if r not in refs:
                    errs.append(f"{name} {x['id']}: unknown reference {r}")
            if not x.get("refs"):
                errs.append(f"{name} {x['id']}: no references")
    ids = [x["id"] for x in c["courses"]["courses"]]
    if len(set(ids)) != len(ids):
        errs.append("duplicate course id")
    allr = [r["id"] for n in ("courses", "guides", "pm", "quizzes") for r in c[n].get("references") or []]
    for k, n in Counter(allr).items():
        if n > 1:
            errs.append(f"reference id {k} defined {n} times")
    for r in refs.values():
        if not str(r.get("url", "")).startswith("https://"):
            errs.append(f"reference {r['id']}: not an https URL")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("checked", ""))):
            errs.append(f"reference {r['id']}: no checked date")
        for f in ("title", "publisher"):
            if not r.get(f):
                errs.append(f"reference {r['id']}: no {f}")
    courses = {x["id"]: x for x in c["courses"]["courses"]}
    for x in c["courses"]["courses"]:
        for p in x["products"]:
            if p not in s["site"]["products"]:
                errs.append(f"course {x['id']}: unknown product {p}")
        for k in x["kinds"]:
            if k not in s["kinds"]:
                errs.append(f"course {x['id']}: unknown kind {k}")
        for sh in x["sheets"]:
            if sh not in s["sheets"]:
                errs.append(f"course {x['id']}: unknown sheet {sh}")
        for r in x["raci"]:
            if r not in s["raci"]:
                errs.append(f"course {x['id']}: unknown RACI row {r}")
        for k in x["credentials"]:
            if k not in s["certs"]["credentials"] and k not in s["ehs"]["courses"]:
                errs.append(f"course {x['id']}: unknown credential {k}")
        if x["partner"] not in PARTNERS:
            errs.append(f"course {x['id']}: unknown partner {x['partner']}")
    # every device belongs to exactly one course; every detail sheet and every product to one
    for n, d in s["devices"].items():
        hits = courses_for_kind(d["kind"], d.get("hall"))
        if len(hits) != 1:
            errs.append(f"device {n} ({d['kind']}, {d.get('hall')}): {len(hits)} courses")
    for sh in s["sheets"]:
        if sh.startswith("D-"):
            hits = [x["id"] for x in courses.values() if sh in x["sheets"]]
            if len(hits) != 1:
                errs.append(f"detail sheet {sh}: {len(hits)} courses")
    for p in s["site"]["products"]:
        hits = [x["id"] for x in courses.values() if p in x["products"]]
        if len(hits) != 1:
            errs.append(f"product {p}: {len(hits)} courses")
    # guides
    for g in c["guides"]["guides"]:
        if g["course"] not in courses:
            errs.append(f"guide {g['id']}: unknown course {g['course']}")
        if g["raci"] not in s["raci"] and not (g["raci"] is None and g.get("owner")):
            errs.append(f"guide {g['id']}: unknown RACI row {g['raci']}")
        if g.get("procedure") and g["procedure"] not in s["procedures"]:
            errs.append(f"guide {g['id']}: unknown procedure {g['procedure']}")
        for p in g["signals"]:
            try:
                re.compile(p)
            except re.error as e:
                errs.append(f"guide {g['id']}: bad pattern {p}: {e}")
    for sig in sorted({a["signal"] for a in s["alarms"]} | set(configured_signals(s))):
        hits = guides_for_signal(sig)
        if len(hits) != 1:
            errs.append(f"signal {sig!r}: {len(hits)} job guides")
    for r in s["records"]:
        cat = r.get("category") or ""
        if not record_links(r, s)["courses"]:
            errs.append(f"record {r['id']}: no course")
        if r["type"] == "sir" and len(guides_for_category(cat)) != 1:
            errs.append(f"record {r['id']}: security category {cat!r} has {len(guides_for_category(cat))} job guides")
        if r["type"] in ("pm", "mop") and len(pm_for_title(r["summary"], s)) != 1:
            errs.append(f"record {r['id']}: {r['summary']!r} matches {len(pm_for_title(r['summary'], s))} PM guides")
    for cat in {r.get("category") for r in s["records"]}:
        if not cat:
            continue
        for hall in {r.get("hall") or None for r in s["records"] if r.get("category") == cat}:
            if len(courses_for_category(cat, hall)) > 1:
                errs.append(f"category {cat!r} in {hall}: more than one course")
    # PM guides
    for p in c["pm"]["pm"]:
        if p["course"] not in courses:
            errs.append(f"pm {p['id']}: unknown course {p['course']}")
        if p["id"] not in s["work_types"] and not p.get("match") and p["id"] not in ("fiber_clean", "spares_count"):
            errs.append(f"pm {p['id']}: not a calendar work type and no match")
    for wt in s["work_types"]:
        if wt not in {p["id"] for p in c["pm"]["pm"]}:
            errs.append(f"calendar work type {wt}: no PM guide")
    for j in s["schedule"]:
        if len(pm_for_title(j["title"], s)) != 1:
            errs.append(f"forward job {j['id']}: matches {len(pm_for_title(j['title'], s))} PM guides")
    # quizzes
    for k in QUIZ_KEYS:
        v = quiz_view(k, s)
        n = len(v["questions"])
        if not 20 <= n <= 30:
            errs.append(f"quiz {k}: {n} questions (20 to 30)")
        for q in v["questions"]:
            if not 3 <= len(q["options"]) <= 4 or len(set(q["options"])) != len(q["options"]):
                errs.append(f"quiz {k} {q['id']}: options must be 3 or 4 distinct")
            if not 0 <= q["answer"] < len(q["options"]):
                errs.append(f"quiz {k} {q['id']}: answer out of range")
            if q["source"] == "written" and q.get("ref") not in refs:
                errs.append(f"quiz {k} {q['id']}: unknown reference {q.get('ref')}")
            if not str(q.get("why", "")).strip():
                errs.append(f"quiz {k} {q['id']}: no why")
    return errs
