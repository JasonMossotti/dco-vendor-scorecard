"""Certification register and work gate (page /training/, report reports/certifications.md).

Every credential each partner's people must hold (``config/certifications.yaml``), read beside the work records that
name the person who did the work. The register is the certification layer (``data/certs/``, own random stream) plus
the EHS training records (``data/ehs/training.csv``), which it reads and never copies.

The gate checks every piece of work at its own time:

* **Shifts.** Each badge-verified shift (the IT Partner's roster by the CSL-10 rule, the Landlord's by OT-CSL-09, each
  Security Partner post shift by SEC-CSL-01's post reader rule): the person holds every credential their role needs.
* **Work.** An IT Partner incident by its category and the rack's model (Hall A GB200, Hall B GB300); a Landlord work
  order by its fault class and a maintenance record by its system; a destruction certificate's operator.

Three kinds of finding, each meaning the records do not reconcile (never a judgment of anyone, never a credit):

1. **Never held.** Work that needs a credential the register has no record of for that person.
2. **Lapsed.** Work after the person's credential expired. A guard's finding also compares the guard file.
3. **Report.** A partner's monthly credential report disagrees with the register at the month end.

A person the EHS check already found (a permit named someone without current training) is shown as corroborated by
that SAF finding. KM-15 (Training and Certification Currency) is the share of the IT Partner's worked shifts on which
the person held every credential the role needs. The staffing service levels say only qualified hours count; the
register shows that recalculation beside each published value and changes none of them.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from scorecard import ehs as E
from scorecard.change_calendar import hm_local, iso, local_day, parse

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "certifications.yaml"
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "certs"
EHS_LAYER = ROOT / "data" / "ehs"
SEC = ROOT / "data" / "security"
PARTNERS = E.PARTNERS
KINDS = {"never_held": "Worked without a required credential on file",
         "lapsed": "Worked after a required credential lapsed",
         "report": "Monthly credential report disagrees with the register"}
ACTIONS = {"never_held": "The person stops this kind of work until the partner shows the credential; the Customer reviews the "
                         "records it touched and the partner's assignment check (who may be dispatched to which work).",
           "lapsed": "The person stops the work the credential covers until it is renewed; the partner shows the renewal or "
                     "explains the gap, and the Customer reviews the work done while it was lapsed.",
           "report": "The partner corrects its monthly report and shows how it tracks expiry; the Customer reads the register, "
                     "not the report, until two reports in a row agree with it."}
AGREEMENTS = [
    ("shifts", "Every badge-verified shift is worked by a person holding every credential the role needs"),
    ("work", "Every incident, work order, maintenance record, and destruction certificate is done by a person holding "
             "every credential that work needs"),
    ("reports", "Each partner's monthly credential report lists exactly the credentials the register shows lapsed"),
]
CRED_COLS = ["person", "partner", "role", "credential", "completed", "expires"]
REPORT_COLS = ["partner", "as_of", "people", "required", "current", "current_pct", "lapsed"]
SOURCE = {"it_shift": "IT Partner shift", "ll_shift": "Landlord shift", "post_shift": "Security post shift",
          "incident": "IT Partner incident", "work_order": "Landlord work order", "pm": "Landlord maintenance record",
          "destruction": "Destruction certificate"}
SHIFT_SOURCES = ("it_shift", "ll_shift", "post_shift")
SEC_SHIFT = timedelta(hours=12)
SEC_EARLY = timedelta(minutes=30)


def config(path: Path = CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the month's records
@dataclass
class Site:
    m: E.Month
    tickets: list[dict[str, Any]]
    it_roster: list[dict[str, str]]
    guards: list[dict[str, str]]
    post_log: list[dict[str, str]]
    guard_badges: list[dict[str, str]]
    destruction: list[dict[str, str]]
    post_readers: dict[str, str]
    security_dir: Path | None


def load_site(sample: str | Path = SAMPLE, security_dir: str | Path | None = SEC) -> Site:
    from scorecard.sla_model import PARTNER_FILES, load_sla
    d = Path(sample)
    s = Path(security_dir) if security_dir else None
    have = s is not None and (s / "guards.csv").exists()
    readers = {p["id"]: p["reader"] for p in load_sla(PARTNER_FILES["security"], validate=False)["posts"]["list"]}
    return Site(m=E.load_month(d), tickets=_json(d / "vendor" / "tickets.json"), it_roster=_csv(d / "vendor" / "roster.csv"),
                guards=_csv(s / "guards.csv") if have else [], post_log=_csv(s / "post_log.csv") if have else [],
                guard_badges=_csv(s / "guard_badges.csv") if have else [],
                destruction=_csv(s / "destruction_certificates.csv") if have else [], post_readers=readers,
                security_dir=s if have else None)


@dataclass
class Register:
    rows: list[dict[str, str]]                  # every credential and EHS course completion
    reported: list[dict[str, str]]
    manifest: dict[str, Any]
    _by: dict[tuple[str, str], list[dict[str, str]]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for r in self.rows:
            self._by.setdefault((r["person"], r["credential"]), []).append(r)

    def current(self, person: str, cred: str, t: datetime) -> dict[str, str] | None:
        for r in self._by.get((person, cred), []):
            if parse(r["completed"]) <= t and (not r["expires"] or t < parse(r["expires"])):
                return r
        return None

    def last(self, person: str, cred: str) -> dict[str, str] | None:
        rows = self._by.get((person, cred), [])
        return max(rows, key=lambda r: r["completed"]) if rows else None


def ehs_rows(ehs_layer: Path = EHS_LAYER) -> list[dict[str, str]]:
    """The EHS training records as register rows (credential = the course key)."""
    if not (Path(ehs_layer) / "training.csv").exists():
        return []
    return [{"person": t["person"], "partner": t["partner"], "role": t["role"], "credential": t["course"],
             "completed": t["completed"], "expires": t["expires"], "source": "ehs"} for t in _csv(Path(ehs_layer) / "training.csv")]


def load(layer: str | Path = LAYER, ehs_layer: str | Path = EHS_LAYER) -> Register:
    d = Path(layer)
    rows = [dict(r, source="register") for r in _csv(d / "credentials.csv")]
    return Register(rows=rows + ehs_rows(Path(ehs_layer)), reported=_csv(d / "reported.csv"), manifest=_json(d / "manifest.json"))


# ---------------------------------------------------------------- people and what they need
def people(site: Site) -> dict[str, tuple[str, str]]:
    """person -> (partner key, role): the IT Partner's personnel, the Landlord's rostered engineers, the guards."""
    out = E.roles(site.m)
    for g in site.guards:
        out[g["guard_id"]] = ("security", "guard")
    return out


def cred_name(cfg: dict[str, Any], ehs_cfg: dict[str, Any], key: str) -> str:
    if key in cfg["credentials"]:
        return cfg["credentials"][key]["name"]
    return ehs_cfg["courses"][key]["name"]


def role_needs(cfg: dict[str, Any], ehs_cfg: dict[str, Any], partner: str, role: str) -> list[str]:
    """The register's credentials for the role, then every EHS course the role holds (config/ehs.yaml `for`)."""
    out = list(cfg["roles"].get(partner, {}).get(role, []))
    for k, c in ehs_cfg["courses"].items():
        fors = c["for"]
        if fors == "all" or partner in fors or role in fors:
            out.append(k)
    return out


def _incident_at(t: dict[str, Any]) -> datetime:
    """When the technician was at the equipment: the "On site" work note, else the acknowledgement."""
    on = [n["at"] for n in t.get("work_notes") or [] if n["text"].startswith("On site")]
    return parse(min(on)) if on else parse(t.get("acknowledged_at") or t["opened_at"])


def work(site: Site, cfg: dict[str, Any] | None = None, ehs_cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every piece of work in the month that names its person, with what that person must hold at the time."""
    cfg, ehs_cfg = cfg or config(), ehs_cfg or E.config()
    m, W = site.m, cfg["work"]
    who = people(site)
    out: list[dict[str, Any]] = []

    def add(source, ref, person, at, needs, what, where="", extra=None):
        partner, role = who.get(person, ("", ""))
        out.append({"source": source, "ref": ref, "person": person, "partner": partner, "role": role, "at": iso(at),
                    "needs": list(dict.fromkeys(needs)), "what": what, "where": where, **(extra or {})})

    # IT Partner shifts: badged in at the main door between an hour before the shift and its end (the CSL-10 rule)
    ins: dict[str, list[datetime]] = {}
    for b in m.badges:
        if b["door"] == "OPS-MAIN" and b["direction"] == "in":
            ins.setdefault(b["person_id"], []).append(parse(b["timestamp"]))
    for r in site.it_roster:
        s, e = parse(r["shift_start"]), parse(r["shift_end"])
        if not (m.start <= s < m.end) or r["person_id"] not in who:
            continue
        if any(s - timedelta(hours=1) <= t <= e for t in ins.get(r["person_id"], [])):
            partner, role = who[r["person_id"]]
            add("it_shift", f"{r['shift_date']} {r['shift']} {r['crew']}", r["person_id"], s,
                role_needs(cfg, ehs_cfg, partner, role), f"{r['shift'].title()} shift, crew {r['crew']}", "OPS-MAIN")
    # Landlord shifts: badged at the main lobby within an hour of the shift start (the OT-CSL-09 rule)
    lobby: dict[str, list[datetime]] = {}
    for b in m.ll_badges:
        if b["reader"] == "Main lobby":
            lobby.setdefault(b["person_id"], []).append(parse(b["timestamp"]))
    for r in m.ll_roster:
        s = parse(r["shift_start"])
        if not (m.start <= s < m.end):
            continue
        if any(abs((t - s).total_seconds()) <= 3600 for t in lobby.get(r["engineer"], [])):
            add("ll_shift", f"{local_day(s)} {r['shift']}", r["engineer"], s,
                role_needs(cfg, ehs_cfg, "landlord", "engineer"), f"{r['shift'].title()} shift", "Main lobby")
    # Security Partner post shifts: the logged guard badged in at the post's reader for the shift (the SEC-CSL-01 rule)
    gb: dict[tuple[str, str], list[datetime]] = {}
    for b in site.guard_badges:
        if b["direction"] == "in":
            gb.setdefault((b["guard_id"], b["reader"]), []).append(parse(b["timestamp"]))
    for r in site.post_log:
        s = parse(r["shift_start"])
        if not (m.start <= s < m.end) or r["guard_id"] not in who:
            continue
        reader = site.post_readers[r["post"]]
        if any(s - SEC_EARLY <= t < s + SEC_SHIFT - SEC_EARLY for t in gb.get((r["guard_id"], reader), [])):
            needs = role_needs(cfg, ehs_cfg, "security", "guard") + W["guard_post"]
            if r["post"] in W["exterior_posts"]:
                needs += W["guard_post_exterior"]
            add("post_shift", f"{r['post']} {local_day(s)} {r['shift']}", r["guard_id"], s, needs,
                f"{r['shift'].title()} shift at {r['post']}", reader)
    # IT Partner incidents
    for t in site.tickets:
        at = _incident_at(t)
        spec = W["it_incident"].get(t.get("category"))
        if spec is None or not (m.start <= at < m.end) or not t.get("assigned_to"):
            continue
        needs = list(spec["needs"])
        hall = (t.get("rack") or " ")[0]
        if spec.get("model") and hall in W["rack_model"]:
            needs.append(W["rack_model"][hall])
        if needs:
            add("incident", t["number"], t["assigned_to"], at, needs, t.get("short_description", ""), t.get("rack") or "",
                {"category": t.get("category"), "priority": t.get("priority")})
    # Landlord work orders and maintenance records
    for o in m.wos:
        needs = W["landlord_work_order"].get(o.get("fault_class") or "", [])
        at = parse(o.get("engaged_at") or o["opened"])
        if needs and o.get("engineer") and m.start <= at < m.end:
            add("work_order", o["wo"], o["engineer"], at, needs, o.get("notes") or o["fault_class"], o.get("unit") or "",
                {"fault_class": o["fault_class"]})
    for p in m.pms:
        needs = W["landlord_pm"].get(p["system"], [])
        if not needs or not p["completed_at"] or not p["engineer"]:
            continue
        at = parse(p["completed_at"])
        if m.start <= at < m.end:
            add("pm", p["task_id"], p["engineer"], at, needs, f"{p['task']}: {p['asset']}", p["asset"])
    # Destruction certificates: the operator
    for c in site.destruction:
        at = parse(c["destroyed_at"])
        if c["operator"] in who and m.start <= at < m.end:
            add("destruction", c["certificate"], c["operator"], at, W["destruction"], f"Drive {c['drive_serial']} destroyed",
                "Media destruction")
    out.sort(key=lambda x: (x["at"], x["source"], x["ref"]))
    return out


# ---------------------------------------------------------------- the gate
@dataclass
class Check:
    name: str
    title: str
    checked: int = 0
    misses: list[str] = field(default_factory=list)


def lapsed_at(reg: Register, who: dict[str, tuple[str, str]], cfg: dict[str, Any], ehs_cfg: dict[str, Any],
              t: datetime) -> dict[str, list[str]]:
    """partner -> sorted "person:credential" pairs the register shows not current at t, over every role credential."""
    out: dict[str, list[str]] = {}
    for person, (partner, role) in sorted(who.items()):
        for c in role_needs(cfg, ehs_cfg, partner, role):
            if not reg.current(person, c, t):
                out.setdefault(partner, []).append(f"{person}:{c}")
    return {k: sorted(v) for k, v in out.items()}


def _ehs_findings(site: Site, ehs_layer: Path) -> list[dict[str, Any]]:
    if not (Path(ehs_layer) / "permits.csv").exists():
        return []
    return E.analyse(site.m, E.load(ehs_layer), security_dir=site.security_dir)["findings"]


def analyse(site: Site, reg: Register, cfg: dict[str, Any] | None = None, ehs_cfg: dict[str, Any] | None = None,
            ehs_layer: Path | None = EHS_LAYER) -> dict[str, Any]:
    cfg, ehs_cfg = cfg or config(), ehs_cfg or E.config()
    m = site.m
    who = people(site)
    items = work(site, cfg, ehs_cfg)
    checks = {k: Check(k, t) for k, t in AGREEMENTS}
    explained: dict[str, int] = {}
    gaps: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for it in items:
        name = "shifts" if it["source"] in SHIFT_SOURCES else "work"
        checks[name].checked += 1
        miss = [c for c in it["needs"] if not reg.current(it["person"], c, parse(it["at"]))]
        it["missing"] = miss
        for c in miss:
            gaps.setdefault((it["person"], c), []).append(it)
        if miss:
            checks[name].misses.append(f"{it['ref']}: {it['person']} without {', '.join(miss)}")
            explained[name] = explained.get(name, 0) + 1
    ehs_found = _ehs_findings(site, ehs_layer) if ehs_layer else []
    saf = {f["person"]: f["id"] for f in ehs_found if f.get("person")}
    guards = {g["guard_id"]: g for g in site.guards}
    found: list[dict[str, Any]] = []
    for (person, c), rows in sorted(gaps.items(), key=lambda kv: (min(r["at"] for r in kv[1]), kv[0])):
        partner, role = who.get(person, (rows[0]["partner"], rows[0]["role"]))
        last = reg.last(person, c)
        kind = "lapsed" if last else "never_held"
        name = cred_name(cfg, ehs_cfg, c)
        shifts = [r for r in rows if r["source"] in SHIFT_SOURCES]
        jobs = [r for r in rows if r["source"] not in SHIFT_SOURCES]
        first = min(parse(r["at"]) for r in rows)
        bits = []
        if jobs:
            bits.append(f"{len(jobs)} record{'s' if len(jobs) != 1 else ''} ({', '.join(r['ref'] for r in jobs[:6])}"
                        + (", ..." if len(jobs) > 6 else "") + ")")
        if shifts:
            bits.append(f"{len(shifts)} badge-verified shift{'s' if len(shifts) != 1 else ''}")
        state = f"expired {last['expires'][:10]}" if last else "no record on file"
        text = (f"{person} ({PARTNERS[partner]} {role.replace('_', ' ')}) worked {' and '.join(bits)} from "
                f"{local_day(first)} {hm_local(first)} needing {name} ({state}).")
        extra: dict[str, Any] = {}
        if partner == "security" and guards.get(person, {}).get("dps_registration") == "current":
            text += " The Security Partner's guard file lists the guard as current."
            extra["guard_file"] = "current"
        if person in saf:
            text += f" The EHS check found the same person on a permit ({saf[person]})."
            extra["corroborates"] = saf[person]
        found.append({"kind": kind, "title": KINDS[kind], "person": person, "credential": c, "credential_name": name,
                      "partner": partner, "owner": PARTNERS[partner], "role": role, "at": iso(first),
                      "refs": [person] + [r["ref"] for r in jobs], "records": [r["ref"] for r in jobs],
                      "shifts": len(shifts), "last": last, "text": text, "action": ACTIONS[kind], **extra})
    # Monthly reports against the register at the month end
    measured = lapsed_at(reg, who, cfg, ehs_cfg, m.end - timedelta(seconds=1))
    for rep in reg.reported:
        p = rep["partner"]
        checks["reports"].checked += 1
        said = sorted(x for x in rep["lapsed"].split(";") if x)
        real = measured.get(p, [])
        if said != real:
            missing, extra_ = sorted(set(real) - set(said)), sorted(set(said) - set(real))
            text = (f"The {PARTNERS[p]}'s credential report as of {rep['as_of'][:10]} says {rep['current_pct']}% current"
                    + (f" and lists {len(said)} lapsed" if said else " and lists none lapsed")
                    + f"; the register shows {len(real)} lapsed")
            text += (f" ({', '.join(x.replace(':', ' ') for x in missing)} not in the report)" if missing else "") + "."
            if extra_:
                text += f" The report lists {', '.join(x.replace(':', ' ') for x in extra_)}, which the register shows current."
            found.append({"kind": "report", "title": KINDS["report"], "person": "", "credential": "", "credential_name": "",
                          "partner": p, "owner": PARTNERS[p], "role": "", "at": rep["as_of"],
                          "refs": [f"report:{p}"] + sorted({x.split(':')[0] for x in missing + extra_}), "records": [],
                          "shifts": 0, "last": None, "text": text, "action": ACTIONS["report"],
                          "missing": missing, "extra": extra_})
            checks["reports"].misses.append(f"{p}: {text}")
            explained["reports"] = explained.get("reports", 0) + 1
    found.sort(key=lambda f: (f["at"], f["kind"], f["person"]))
    for i, f in enumerate(found, 1):
        f["id"] = f"CRT-{i}"
    return {"work": items, "findings": found, "agreements": list(checks.values()), "explained": explained,
            "measured_lapsed": measured, "people": who}


def score(fs: list[dict[str, Any]], key: list[dict[str, Any]]) -> dict[str, int]:
    """Planted cases found, cases the EHS layer already holds (as found), and findings neither explains."""
    hit = lambda k: any(f["kind"] == k["kind"] and k["ref"] in f["refs"] and (not k.get("credential") or k["credential"] == f["credential"])
                        for f in fs)
    planted = [k for k in key if k["source"] == "planted"]
    fp = [f for f in fs if not any(f["kind"] == k["kind"] and k["ref"] in f["refs"]
                                   and (not k.get("credential") or k["credential"] == f["credential"]) for k in key)]
    return {"planted": len(planted), "found": sum(hit(k) for k in planted),
            "as_found": sum(hit(k) for k in key if k["source"] != "planted"),
            "as_found_expected": sum(1 for k in key if k["source"] != "planted"), "false_positives": len(fp)}


# ---------------------------------------------------------------- KM-15 and the staffing rule
def km15(site: Site, reg: Register, items: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """KM-15 Training and Certification Currency: the IT Partner's badge-verified shifts on which the person held every
    credential the role needs, at the shift start."""
    items = items if items is not None else work(site)
    shifts = [x for x in items if x["source"] == "it_shift"]
    if not shifts:
        return None
    ok = sum(1 for x in shifts if all(reg.current(x["person"], c, parse(x["at"])) for c in x["needs"]))
    return {"actual": round(100 * ok / len(shifts), 3), "events": len(shifts), "misses": len(shifts) - ok,
            "detail": f"{ok} of {len(shifts)} badge-verified IT Partner shifts worked with every role credential current"}


def km15_for(data_dir: str | Path) -> dict[str, Any] | None:
    """KM-15 for a dataset directory, when the certification layer was generated from it (the sample month); else None."""
    try:
        d = Path(data_dir).resolve()
    except TypeError:
        return None
    if d != SAMPLE.resolve() or not (LAYER / "manifest.json").exists():
        return None
    site = load_site(d, SEC)
    if _json(LAYER / "manifest.json")["window"] != site.m.window:
        return None
    return km15(site, load(LAYER, EHS_LAYER))


def staffing(site: Site, reg: Register, cfg: dict[str, Any] | None = None, ehs_cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Each staffing service level as published, and recalculated with the contract's rule that only hours by people with
    current qualifications count. Reported beside the scorecards; it changes none of them."""
    from scorecard.sla_model import PARTNER_FILES, evaluate_csl, load_sla
    cfg, ehs_cfg = cfg or config(), ehs_cfg or E.config()
    m, who = site.m, people(site)

    def qualified(person: str, t: datetime, extra: list[str] = ()) -> bool:
        partner, role = who.get(person, ("", ""))
        return all(reg.current(person, c, t) for c in role_needs(cfg, ehs_cfg, partner, role) + list(extra))

    out = []
    # CSL-10: committed technician hours, badge-verified
    ins: dict[str, list[datetime]] = {}
    for b in m.badges:
        if b["door"] == "OPS-MAIN" and b["direction"] == "in":
            ins.setdefault(b["person_id"], []).append(parse(b["timestamp"]))
    committed = present = adj = 0.0
    lost: set[str] = set()
    for r in site.it_roster:
        if r["role"] != "technician":
            continue
        s, e = parse(r["shift_start"]), parse(r["shift_end"])
        lo, hi = max(s, m.start), min(e, m.end)
        if hi <= lo:
            continue
        hrs = (hi - lo).total_seconds() / 3600
        committed += hrs
        if any(s - timedelta(hours=1) <= t <= e for t in ins.get(r["person_id"], [])):
            present += hrs
            if qualified(r["person_id"], s):
                adj += hrs
            else:
                lost.add(r["person_id"])
    it_sla = load_sla()
    out.append(_staff_row(it_sla, "CSL-10", "IT Partner", round(100 * present / committed, 3) if committed else None,
                          round(100 * adj / committed, 3) if committed else None, round(present - adj, 1), "technician hours", sorted(lost),
                          evaluate_csl))
    # OT-CSL-09: rostered Landlord shifts badge-verified
    lobby: dict[str, list[datetime]] = {}
    for b in m.ll_badges:
        if b["reader"] == "Main lobby":
            lobby.setdefault(b["person_id"], []).append(parse(b["timestamp"]))
    rostered = badged = adj_n = 0
    lost = set()
    for r in m.ll_roster:
        s = parse(r["shift_start"])
        rostered += 1
        if any(abs((t - s).total_seconds()) <= 3600 for t in lobby.get(r["engineer"], [])):
            badged += 1
            if qualified(r["engineer"], s):
                adj_n += 1
            else:
                lost.add(r["engineer"])
    ll_sla = load_sla(PARTNER_FILES["landlord"])
    out.append(_staff_row(ll_sla, "OT-CSL-09", "Landlord", 100 * badged / rostered if rostered else None,
                          100 * adj_n / rostered if rostered else None, badged - adj_n, "shifts", sorted(lost), evaluate_csl))
    # SEC-CSL-01: post-minutes with a guard badged in at the post
    if site.security_dir:
        guards = {g["guard_id"] for g in site.guards}
        rows = [r for r in site.post_log if m.start <= parse(r["shift_start"]) < m.end]
        committed_min = 720 * len(rows)
        covered = adj_min = 0.0
        lost = set()
        for r in rows:
            t0, reader = parse(r["shift_start"]), site.post_readers[r["post"]]
            b = [parse(x["timestamp"]) for x in site.guard_badges if x["reader"] == reader and x["direction"] == "in"
                 and x["guard_id"] in guards and t0 - SEC_EARLY <= parse(x["timestamp"]) < t0 + SEC_SHIFT - SEC_EARLY]
            if not b:
                continue
            mins = (t0 + SEC_SHIFT - max(min(b), t0)).total_seconds() / 60
            covered += mins
            extra = cfg["work"]["guard_post"] + (cfg["work"]["guard_post_exterior"] if r["post"] in cfg["work"]["exterior_posts"] else [])
            if qualified(r["guard_id"], t0, extra):
                adj_min += mins
            else:
                lost.add(r["guard_id"])
        sec_sla = load_sla(PARTNER_FILES["security"])
        out.append(_staff_row(sec_sla, "SEC-CSL-01", "Security Partner", 100 * covered / committed_min if committed_min else None,
                              100 * adj_min / committed_min if committed_min else None, round((covered - adj_min) / 60, 1),
                              "post-hours", sorted(lost), evaluate_csl))
    return out


def _staff_row(sla, csl, partner, published, adjusted, lost, unit, people_, evaluate_csl) -> dict[str, Any]:
    c = next(x for x in sla["critical_service_levels"] if x["id"] == csl)
    st = lambda v: evaluate_csl(sla, csl, v).status if v is not None else "no_events"
    return {"csl": csl, "name": c["name"], "partner": partner, "expected": c["expected"], "minimum": c["minimum"],
            "published": published, "adjusted": adjusted, "published_status": st(published), "adjusted_status": st(adjusted),
            "lost": lost, "unit": unit, "people": people_}


# ---------------------------------------------------------------- renewal notices and bench
def notices(reg: Register, who: dict[str, tuple[str, str]], cfg: dict[str, Any], ehs_cfg: dict[str, Any],
            as_of: datetime) -> list[dict[str, Any]]:
    """Every required credential that lapses within the horizon, with the 90/60/30-day notice dates. Drafted, never sent."""
    N = cfg["notices"]
    horizon = as_of + timedelta(days=N["horizon_days"])
    out = []
    for person, (partner, role) in sorted(who.items()):
        for c in role_needs(cfg, ehs_cfg, partner, role):
            r = reg.current(person, c, as_of)
            if not r or not r["expires"]:
                continue
            exp = parse(r["expires"])
            if exp >= horizon:
                continue
            steps = [{"lead": d, "date": (exp - timedelta(days=d)).date().isoformat(),
                      "due": exp - timedelta(days=d) <= as_of} for d in N["lead_days"]]
            stage = min((x["lead"] for x in steps if x["due"]), default=None)   # the latest notice whose date has come
            out.append({"person": person, "partner": partner, "role": role, "credential": c,
                        "name": cred_name(cfg, ehs_cfg, c), "expires": r["expires"], "days": (exp - as_of).days,
                        "notices": steps, "stage": stage, "to": N["to"][partner], "cc": N["cc"],
                        "source": r.get("source", "register")})
    out.sort(key=lambda x: (x["expires"], x["partner"], x["person"], x["credential"]))
    return out


def bench(reg: Register, who: dict[str, tuple[str, str]], cfg: dict[str, Any], ehs_cfg: dict[str, Any],
          schedule: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each forward job: how many of the owner's people hold every credential the work type needs on the job's date."""
    from scorecard import change_calendar as CC
    ccfg = CC.config()
    owners = {"Landlord": "landlord", "IT Partner": "it"}
    out = []
    for j in schedule:
        w, g = CC.classify(j["title"], ccfg)
        needs = list(cfg["schedule_work"].get(w["type"], []))
        if w["type"] == "tray_firmware":
            needs = [cfg["work"]["rack_model"].get(g["rack"][0], "oem_gb200")]
        partner = owners.get(j["owner"])
        if not needs or not partner:
            continue
        t = parse(j["window_start"])
        holders = sorted(p for p, (pt, _) in who.items() if pt == partner and all(reg.current(p, c, t) for c in needs))
        out.append({"id": j["id"], "title": j["title"], "owner": j["owner"], "start": j["window_start"], "type": w["type"],
                    "needs": needs, "names": [cred_name(cfg, ehs_cfg, c) for c in needs], "holders": len(holders),
                    "short": len(holders) < cfg["notices"]["bench_min"]})
    return out


# ---------------------------------------------------------------- the page
def page_data(sample: Path = SAMPLE, layer: Path = LAYER, ehs_layer: Path = EHS_LAYER, security_dir: Path | None = SEC,
              cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg, ehs_cfg = cfg or config(), E.config()
    site, reg = load_site(sample, security_dir), load(layer, ehs_layer)
    r = analyse(site, reg, cfg, ehs_cfg, ehs_layer)
    m, who = site.m, r["people"]
    as_of = m.end - timedelta(seconds=1)
    by_person: dict[str, list[str]] = {}
    for f in r["findings"]:
        for ref in f["refs"]:
            by_person.setdefault(ref, []).append(f["id"])
    roster = []
    for person, (partner, role) in sorted(who.items(), key=lambda kv: (list(PARTNERS).index(kv[1][0]), kv[0])):
        creds = []
        for c in role_needs(cfg, ehs_cfg, partner, role) + ([x for x in ("oem_gb300",) if partner == "it"]):
            row = reg.current(person, c, as_of) or reg.last(person, c)
            creds.append({"key": c, "name": cred_name(cfg, ehs_cfg, c), "required": c in role_needs(cfg, ehs_cfg, partner, role),
                          "completed": row["completed"] if row else "", "expires": row["expires"] if row else "",
                          "source": row.get("source", "") if row else "",
                          "current": bool(reg.current(person, c, as_of))})
        mine = [x for x in r["work"] if x["person"] == person]
        roster.append({"person": person, "partner": partner, "role": role, "credentials": creds,
                       "shifts": sum(1 for x in mine if x["source"] in SHIFT_SOURCES),
                       "records": [{"ref": x["ref"], "source": x["source"], "at": x["at"], "what": x["what"],
                                    "needs": x["needs"], "missing": x["missing"]} for x in mine if x["source"] not in SHIFT_SOURCES],
                       "findings": sorted(set(by_person.get(person, []))),
                       "required_current": sum(1 for c in creds if c["required"] and c["current"]),
                       "required": sum(1 for c in creds if c["required"])})
    catalog = []
    for k, c in cfg["credentials"].items():
        rows = [x for x in roster for y in x["credentials"] if y["key"] == k]
        catalog.append({"key": k, "name": c["name"], "months": c["months"], "partner": c["partner"], "issuer": c["issuer"],
                        "basis": c["basis"], "holders": sum(1 for x in rows for y in x["credentials"] if y["key"] == k and y["completed"]),
                        "current": sum(1 for x in rows for y in x["credentials"] if y["key"] == k and y["current"]), "source": "register"})
    for k, c in ehs_cfg["courses"].items():
        held = {x["person"] for x in reg.rows if x["credential"] == k}
        catalog.append({"key": k, "name": c["name"], "months": c["months"], "partner": "ehs", "issuer": "EHS training (data/ehs)",
                        "basis": "Common terms, EHS partner qualification", "holders": len(held),
                        "current": sum(1 for p in held if reg.current(p, k, as_of)), "source": "ehs"})
    schedule_path = ROOT / "data" / "calendar" / "schedule.json"
    schedule = _json(schedule_path) if sample == SAMPLE and schedule_path.exists() else []
    k15 = km15(site, reg, r["work"])
    nts = notices(reg, who, cfg, ehs_cfg, as_of)
    for f in r["findings"]:
        f["date"] = local_day(parse(f["at"]))
    return {"window": m.window, "as_of": iso(as_of), "partners": PARTNERS, "kinds": KINDS, "sources": SOURCE,
            "roles": cfg["roles"], "work_rules": cfg["work"], "catalog": catalog, "people": roster,
            "findings": r["findings"], "notices": nts, "bench": bench(reg, who, cfg, ehs_cfg, schedule),
            "staffing": staffing(site, reg, cfg, ehs_cfg), "km15": k15, "reported": reg.reported,
            "measured_lapsed": r["measured_lapsed"], "notice_rules": cfg["notices"],
            "agreements": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": c.misses,
                            "explained": r["explained"].get(c.name, 0)} for c in r["agreements"]],
            "summary": {"people": len(who), "credentials": sum(1 for x in reg.rows if x["source"] == "register"),
                        "ehs_courses": sum(1 for x in reg.rows if x["source"] == "ehs"), "work": len(r["work"]),
                        "shifts": sum(1 for x in r["work"] if x["source"] in SHIFT_SOURCES),
                        "records": sum(1 for x in r["work"] if x["source"] not in SHIFT_SOURCES),
                        "findings": len(r["findings"]), "notices": len(nts),
                        "by_kind": {k: sum(1 for f in r["findings"] if f["kind"] == k) for k in KINDS}}}
