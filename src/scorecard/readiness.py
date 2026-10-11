"""New-hall readiness: Hall C, the 800 VDC pilot, from commissioning (L1 to L5) to first compute.

Reads the standard work (config/readiness.yaml), the site model (site/site.yaml), the sign-off roles
(config/deployments.yaml), and the record (data/readiness/). Builds the commissioning matrix, the Customer's
readiness gates, the first-compute forecast with its critical path, the spares position, and the record checks.

The checks read the record alone, never the answer key. A finding means the records do not reconcile, not that
the work was not done.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from . import site_model as S

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "readiness.yaml"
RECORDS = ROOT / "data" / "readiness"
UTC = timezone.utc


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def validate(cfg: dict[str, Any], roles: dict[str, Any]) -> list[str]:
    errs = []
    levels = list(cfg["levels"])
    for L, v in cfg["levels"].items():
        errs += [f"level {L}: unknown role {r}" for r in [v["by"], *v["sign"]] if r not in roles]
        if L not in cfg["duration_days"]:
            errs.append(f"level {L}: no duration")
    ids = set()
    for s in cfg["systems"]:
        if s["id"] in ids:
            errs.append(f"duplicate system {s['id']}")
        ids.add(s["id"])
        if [L for L in levels if L in s["levels"]] != s["levels"] or "L5" in s["levels"]:
            errs.append(f"system {s['id']}: levels out of order or L5 listed")
    items = {}
    for g in cfg["gates"]:
        for it in g["items"]:
            if it["id"] in items:
                errs.append(f"duplicate item {it['id']}")
            items[it["id"]] = it
            if it["owner"] not in roles:
                errs.append(f"item {it['id']}: unknown role {it['owner']}")
    for it in items.values():
        errs += [f"item {it['id']}: unknown dependency {a}" for a in it.get("after", []) if a not in items]
    if sum(1 for it in items.values() if it.get("spares")) != 1:
        errs.append("exactly one item must claim the spares")
    return errs


def load_record(rec_dir: Path = RECORDS) -> dict[str, Any]:
    def csv_rows(name: str) -> list[dict[str, str]]:
        with open(rec_dir / name, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    issues = csv_rows("cx_issues.csv")
    for i in issues:
        i["category"] = int(i["category"])
    receipts = csv_rows("spares_receipts.csv")
    for r in receipts:
        r["qty"] = int(r["qty"])
    return {"program": json.loads((rec_dir / "program.json").read_text(encoding="utf-8")),
            "scripts": json.loads((rec_dir / "cx_scripts.json").read_text(encoding="utf-8")),
            "items": json.loads((rec_dir / "readiness_items.json").read_text(encoding="utf-8")),
            "issues": issues, "receipts": receipts}


# ------------------------------------------------------------------------------------------- state
def passed_at(sc: dict[str, Any]) -> str | None:
    """The time of the passing run, if the latest run passed."""
    return sc["runs"][-1]["at"] if sc["runs"] and sc["runs"][-1]["result"] == "pass" else None


def script_state(sc: dict[str, Any], as_of: str, duration_days: int) -> str:
    """Passed, failed (a retest follows), in progress (started on schedule, not finished), overdue, or scheduled."""
    if passed_at(sc):
        return "passed"
    if sc["runs"]:
        return "failed, retest scheduled"
    if sc["scheduled"] > as_of[:10]:
        return "scheduled"
    end = _day(sc["scheduled"]) + timedelta(days=duration_days)
    return "in progress" if end >= _day(as_of) else "overdue"


def forecast(cfg: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    """Finish date of every script and item: the record where it has finished, otherwise the later of its schedule
    (or plan) and its dependencies, plus its duration. Returns finishes, each one's binding dependency, and the
    critical path back from first compute."""
    as_of = _day(rec["program"]["as_of"])
    committed = _day(rec["program"]["committed_first_compute"])
    fin: dict[str, date] = {}
    why: dict[str, str | None] = {}
    by_sys: dict[str, list[dict[str, Any]]] = {}
    for sc in rec["scripts"]:
        by_sys.setdefault(sc["system"], []).append(sc)
    order = list(cfg["levels"])
    for sys_id, scs in by_sys.items():
        scs.sort(key=lambda s: order.index(s["level"]))
    l4 = []
    for sys_id, scs in by_sys.items():
        if sys_id == "HALL-C":
            continue
        prev, passed_prev = None, False
        for sc in scs:
            k = sc["id"]
            if p := passed_at(sc):
                fin[k], why[k] = _day(p), None
                passed_prev = True
            else:
                dur = timedelta(days=cfg["duration_days"][sc["level"]])
                if prev and not passed_prev:
                    # The level below has not passed: this one follows its forecast, whatever its schedule says.
                    start, why[k] = max(fin[prev] + timedelta(days=1), as_of), prev
                else:
                    start, why[k] = max(_day(sc["scheduled"]), as_of), None
                    if prev and fin[prev] + timedelta(days=1) > start:
                        start, why[k] = fin[prev] + timedelta(days=1), prev
                fin[k] = start + dur
            passed_prev = bool(passed_at(sc))
            prev = k
        l4.append(prev)
    hall = by_sys["HALL-C"][0]
    k = hall["id"]
    if p := passed_at(hall):
        fin[k], why[k] = _day(p), None
    else:
        top = max(l4, key=lambda x: fin[x])
        start, why[k] = max(_day(hall["scheduled"]), as_of), None
        if fin[top] + timedelta(days=1) > start:
            start, why[k] = fin[top] + timedelta(days=1), top
        fin[k] = start + timedelta(days=cfg["duration_days"]["L5"])
    items = {i["item"]: i for i in rec["items"]}
    for g in cfg["gates"]:
        for it in g["items"]:
            i = it["id"]
            if it.get("from_cx"):
                fin[i], why[i] = fin[k] + timedelta(days=cfg["cx_report_days"]), k
                continue
            r = items[i]
            if r["state"] == "done":
                fin[i], why[i] = _day(r["done"]), None
                continue
            plan = committed - timedelta(days=it["due"])
            fin[i], why[i] = max(plan, as_of + timedelta(days=it["days"] if r["state"] == "not started" else 1)), None
            for a in it.get("after", []):
                if fin[a] + timedelta(days=it["days"]) > fin[i]:
                    fin[i], why[i] = fin[a] + timedelta(days=it["days"]), a
    last = cfg["gates"][-1]["items"][-1]["id"]
    path, x = [], last
    while x:
        path.append(x)
        x = why.get(x)
    return {"finish": {a: b.isoformat() for a, b in fin.items()}, "binding": why, "critical_path": path[::-1],
            "first_compute": fin[last].isoformat(), "committed": committed.isoformat(),
            "slip_days": (fin[last] - committed).days}


# ------------------------------------------------------------------------------------------ checks
def checks(cfg: dict[str, Any], rec: dict[str, Any], roles: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Records that do not reconcile, from the record alone (never the answer key).

    * ``passed_open_cat1``: a passing run while a Category 1 issue on the same system and level was open.
    * ``signed_before_run``: a signature dated before the passing run it accepts.
    * ``out_of_sequence``: a level passed before the level below it on the same system passed.
    * ``spares_short``: the initial-spares item done while some pilot FRU class had not reached its minimum."""
    names = cfg["checks"]
    out: list[dict[str, Any]] = []
    by = {(s["system"], s["level"]): s for s in rec["scripts"]}
    levels = {s["id"]: s["levels"] for s in cfg["systems"]}

    def add(kind: str, ref: str, known: str, text: str, refs: list[str], party: str) -> None:
        out.append({"kind": kind, "check": names[kind], "ref": ref, "known_at": known, "text": text, "refs": refs, "party": party})

    for sc in rec["scripts"]:
        at = passed_at(sc)
        if not at:
            continue
        what = f"{sc['level']} on {sc['system']}" if sc["system"] != "HALL-C" else "the Hall C integrated systems test (L5)"
        for i in rec["issues"]:
            if (i["system"], i["level"], i["category"]) == (sc["system"], sc["level"], 1) and i["opened"] < at \
                    and (not i["closed"] or i["closed"] > at):
                still = f"closed {i['closed'][:16].replace('T', ' ')} UTC" if i["closed"] else "is still open"
                add("passed_open_cat1", sc["id"], at, f"{sc['id']} records {what} passed at {at[:16].replace('T', ' ')} UTC, "
                    f"but Category 1 issue {i['id']} ({i['text'].lower()}) was opened {i['opened'][:16].replace('T', ' ')} UTC "
                    f"and {still}. A level cannot pass with a Category 1 open.", [sc["id"], i["id"]], "Commissioning agent")
        for g in sc["signatures"]:
            if g["signed_at"] and g["signed_at"] < at:
                hrs = (_ts(at) - _ts(g["signed_at"])).total_seconds() / 3600
                who = (roles or {}).get(g["role"], {}).get("name", g["role"])
                add("signed_before_run", sc["id"], at, f"{sc['id']} carries the {who} signature at "
                    f"{g['signed_at'][:16].replace('T', ' ')} UTC, {hrs:.0f} hours before the passing run it accepts.",
                    [sc["id"]], "Commissioning agent")
        if sc["system"] in levels:
            lv = levels[sc["system"]]
            n = lv.index(sc["level"])
            if n:
                below = by.get((sc["system"], lv[n - 1]))
                b = passed_at(below) if below else None
                if not b or b > at:
                    when = f"passed {b[:16].replace('T', ' ')} UTC" if b else "has not passed"
                    add("out_of_sequence", sc["id"], at, f"{sc['id']} records {what} passed at {at[:16].replace('T', ' ')} UTC, "
                        f"but the level below it, {lv[n - 1]} ({below['id'] if below else 'no script'}), {when}.",
                        [sc["id"]] + ([below["id"]] if below else []), "Commissioning agent")
    spares_item = next(it for g in cfg["gates"] for it in g["items"] if it.get("spares"))
    claim = next((i for i in rec["items"] if i["item"] == spares_item["id"]), None)
    if claim and claim["state"] == "done":
        t = claim["done"]
        short = []
        for s in cfg["spares"]:
            got = sum(r["qty"] for r in rec["receipts"] if r["fru"] == s["fru"] and r["received_at"] <= t)
            if got < s["minimum"]:
                short.append(f"{s['fru']} {got} of {s['minimum']}")
        if short:
            add("spares_short", spares_item["id"], t, f"{spares_item['id']} ({spares_item['name'].lower()}) is recorded done at "
                f"{t[:16].replace('T', ' ')} UTC, but the receipts by then show {'; '.join(short)}.",
                [claim["evidence"]] if claim["evidence"] else [], "IT Partner")
    order = {k: n for n, k in enumerate(names)}
    return sorted(out, key=lambda f: (order[f["kind"]], f["ref"]))


def evaluate(findings: list[dict[str, Any]], key: dict[str, Any]) -> dict[str, Any]:
    planted = {(k["kind"], k["ref"]) for k in key.get("planted", [])}
    found = {(f["kind"], f["ref"]) for f in findings}
    by_kind: dict[str, list[int]] = {}
    for k in planted:
        t = by_kind.setdefault(k[0], [0, 0])
        t[0] += k in found
        t[1] += 1
    return {"planted": len(planted), "detected": len(planted & found), "missed": sorted(planted - found),
            "false_positives": sorted(found - planted), "by_kind": by_kind, "decoys": key.get("decoys", {})}


# ------------------------------------------------------------------------------------------- build
def build(rec_dir: Path = RECORDS, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    from . import deployments as D
    cfg = cfg or load_config()
    roles = D.load_config()["roles"]
    if errs := validate(cfg, roles):
        raise ValueError("; ".join(errs))
    site = S.load_site()
    hall = S.hall_by_id(site, cfg["program"]["hall"])
    rec = load_record(rec_dir)
    as_of = rec["program"]["as_of"]
    fc = forecast(cfg, rec)
    found = checks(cfg, rec, roles)
    key_path = rec_dir / "answer_key.json"
    self_check = evaluate(found, json.loads(key_path.read_text(encoding="utf-8"))) if key_path.exists() else None
    scripts = []
    for sc in rec["scripts"]:
        iss = [i for i in rec["issues"] if i["script"] == sc["id"]]
        scripts.append(dict(sc, state=script_state(sc, as_of, cfg["duration_days"][sc["level"]]), passed_at=passed_at(sc), forecast=fc["finish"][sc["id"]],
                            issues=[i["id"] for i in iss],
                            open_issues=sum(1 for i in iss if not i["closed"])))
    systems = []
    for s in cfg["systems"]:
        prod = S.product(site, s["product"]) if s.get("product") else None
        systems.append(dict(s, model=f"{prod['manufacturer']} {prod['model']}" if prod else "Per pilot submittal (generic)"))
    open_by_cat = {c: sum(1 for i in rec["issues"] if i["category"] == c and not i["closed"]) for c in (1, 2, 3)}
    items = {i["item"]: i for i in rec["items"]}
    gates = []
    for g in cfg["gates"]:
        rows = []
        for it in g["items"]:
            if it.get("from_cx"):
                hall_sc = next(s for s in scripts if s["system"] == "HALL-C")
                if it["from_cx"] == "l5_report":
                    state = "done" if hall_sc["passed_at"] else "not started"
                    note = (f"L5 {hall_sc['state']}; report {cfg['cx_report_days']} days after it passes")
                else:
                    state = "open" if open_by_cat[1] else "met"
                    note = f"{open_by_cat[1]} Category 1 open now; final at the L5 report"
                rows.append(dict(it, state=state, done="", started="", evidence="", evidence_kind="", note=note, forecast=fc["finish"][it["id"]]))
            else:
                r = items[it["id"]]
                rows.append(dict(it, state=r["state"], done=r["done"], started=r["started"], evidence=r["evidence"],
                                 evidence_kind=it.get("evidence", ""), note="",
                                 forecast=fc["finish"][it["id"]]))
        gates.append({"id": g["id"], "name": g["name"], "items": rows,
                      "done": sum(1 for x in rows if x["state"] == "done"), "total": len(rows)})
    spares = []
    for s in cfg["spares"]:
        rs = sorted((r for r in rec["receipts"] if r["fru"] == s["fru"]), key=lambda r: r["received_at"])
        spares.append(dict(s, received=sum(r["qty"] for r in rs), receipts=rs))
    lv = list(cfg["levels"])
    matrix = {}
    for sc in scripts:
        matrix.setdefault(sc["system"], {})[sc["level"]] = sc["id"]
    level_counts = {L: {"passed": sum(1 for s in scripts if s["level"] == L and s["passed_at"]),
                        "total": sum(1 for s in scripts if s["level"] == L)} for L in lv}
    return {"meta": cfg["meta"], "program": dict(cfg["program"], hall_name=hall["name"], racks=hall["rows"] * hall["racks_per_row"],
                                                 rack_model=S.product(site, hall["rack_product"])["model"],
                                                 as_of=as_of, baseline_issued=rec["program"]["baseline_issued"]),
            "levels": cfg["levels"], "level_counts": level_counts, "systems": systems, "scripts": scripts, "matrix": matrix,
            "issues": sorted(rec["issues"], key=lambda i: i["id"]), "open_by_category": open_by_cat,
            "issue_categories": cfg["issue_categories"], "gates": gates, "spares": spares,
            "spares_item": next(it["id"] for g in cfg["gates"] for it in g["items"] if it.get("spares")),
            "forecast": fc, "findings": found, "check_names": cfg["checks"], "check_help": cfg["check_help"],
            "self_check": self_check, "duration_days": cfg["duration_days"]}
