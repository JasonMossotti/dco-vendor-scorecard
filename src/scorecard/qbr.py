"""Quarterly business review (Scorecards tab, /app/#qbr): one pack per partner for the quarter's three months.

The contract's quarterly forum (sla/common.yaml, governance) takes trend analysis, SLA change proposals, the roadmap
and capacity plan, and program-wide lessons. Every number here comes from the three months' own scorecards, run by
the same engines the Scorecards tab uses (``scorecard.app_support``); nothing is measured twice. The quarter adds what
a single month cannot show:

1. **Service levels by month**, each with a trend mark; each month's column is that month's published scorecard.
2. **Credits by month** and for the quarter, against the at-risk cap.
3. **The multi-month rules** across the quarter: repeat-default doubling, earnback, and the chronic-failure triggers.
   A doubling is an adjustment line beside the published month, which stays as published.
4. **Self-report against measurement** by month, and **findings by type** by month (a type seen in two months or
   more is a repeat: the same kind of record keeps failing to reconcile).
5. **Corrective actions**, **staffing fill**, **SLA change proposals** by a stated rule (config/qbr.yaml), and the
   **roadmap and capacity** (Hall B racks, Hall C first compute).

The record starts with the quarter's first month: a default before it is not known here, so a doubling needs three
consecutive defaults inside the quarter, and an earnback can only be on track or lost (it needs the three months
after the default).
"""

from __future__ import annotations

import csv
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from scorecard import app_support as A
from scorecard.sla_model import PARTNER_FILES, cap_monthly_credits, compute_credit, get_csl, load_sla

ROOT = A.ROOT
CFG = ROOT / "config" / "qbr.yaml"
NOTES = ROOT / "qbr" / "notes"
SAMPLE = ROOT / "data" / "sample"
QUARTER = ROOT / "data" / "quarter"

PARTNERS = ("it", "landlord", "security")
NAMES = {"it": "IT Partner", "landlord": "Landlord", "security": "Security Partner"}
STAFFING = {"it": "CSL-10", "landlord": "OT-CSL-09", "security": "SEC-CSL-01"}
# Earnback is lost when the default involved a record integrity finding or a security (chain-of-custody) failure
# (each contract's commercial.earnback.ineligible_when). The monthly engines mark the integrity ones the same way.
AGGRAVATORS = {"CSL-11": "AGG-INTEGRITY", "OT-CSL-08": "AGG-INTEGRITY", "SEC-CSL-07": "AGG-INTEGRITY",
               "SEC-CSL-06": "AGG-SECURITY"}
AGG_TEXT = {"AGG-INTEGRITY": "record integrity finding", "AGG-SECURITY": "chain-of-custody failure"}
DEFAULT = ("below_minimum", "deep_below_minimum")
PIR_OWNERS = {"IT Partner Site Manager": "it", "Landlord Chief Engineer": "landlord", "Security Partner Site Manager": "security"}


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def label(start: str, end: str) -> str:
    """Jul 6 to Aug 2 (no strftime padding flags: they differ on Windows)."""
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return f"{MON[a.month - 1]} {a.day} to {MON[b.month - 1]} {b.day}"


def load_config(path: Path = CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def month_dirs(cfg: dict[str, Any], root: Path = ROOT) -> list[tuple[dict[str, Any], Path]]:
    """Each month of the quarter and its dataset: the generated months under data/quarter/, then the sample."""
    out = []
    for m in cfg["months"]:
        d = root / "data" / "sample" if m.get("sample") else root / "data" / "quarter" / str(m["start"])
        out.append((m, d))
    return out


# --------------------------------------------------------------------------- one month, as published
def _month(meta: dict[str, Any], d: Path) -> dict[str, Any]:
    """The three partners' published scorecards for one month, reduced to what the quarter rolls up."""
    it_r, it_sc, _ = A.run_pipeline(load_sla(PARTNER_FILES["it"]), d)
    ll_r, ll_sc, _, _ = A.run_landlord_pipeline(d)
    sec = A.run_security_pipeline(d)
    sec_r, sec_sc = (sec[0], sec[1]) if sec else (None, None)
    w = it_sc["window"]
    rows = {"it": A.csl_rows(it_sc), "landlord": A.landlord_csl_rows(ll_sc),
            "security": A.security_csl_rows(sec_sc) if sec_sc else []}
    out = {"id": str(meta["id"]), "start": w["start"].strftime("%Y-%m-%d"),
           "end": (w["end"] - timedelta(seconds=1)).strftime("%Y-%m-%d"), "sample": bool(meta.get("sample")), "partners": {}}
    out["label"] = label(out["start"], out["end"])
    for k, sc, res in (("it", it_sc, it_r), ("landlord", ll_sc, ll_r), ("security", sec_sc, sec_r)):
        if sc is None:
            continue
        shown = {r["ID"]: r for r in rows[k]}
        out["partners"][k] = {
            "csl": [{"id": r["id"], "actual": r["actual"], "reported": r["vendor_reported"], "status": r["status"],
                     "credit": r["credit"], "detail": r["detail"], "measured": shown[r["id"]]["Measured"]} for r in sc["csl"]],
            "credits": {"uncapped": sc["credits"]["uncapped"], "payable": sc["credits"]["payable"],
                        "capped": bool(sc["credits"]["capped"]), "items": [c["csl"] for c in sc["credits"]["items"]]},
            "findings": [{"type": f.type, "title": f.title, "id": f.id} for f in res.findings],
            "caps": (len(sc["corrective_actions"]) if k == "it" else sc["s1"]),
            "caps_due": ([str(c["due"])[:10] for c in sc["corrective_actions"]] if k == "it" else []),
        }
    return out


# --------------------------------------------------------------------------- the quarter, by partner
def _better(direction: str, a: float, b: float) -> bool:
    return a > b if direction == "higher_is_better" else a < b


def _meets(direction: str, v: float | None, target: float) -> bool | None:
    if v is None:
        return None
    return v >= target if direction == "higher_is_better" else v <= target


def _trend(direction: str, vals: list[float | None]) -> str:
    v = [x for x in vals if x is not None]
    if len(v) < 2:
        return "n/a"
    if round(v[0], 3) == round(v[-1], 3):
        return "same"
    return "better" if _better(direction, v[-1], v[0]) else "worse"


def _run(statuses: list[str], i: int) -> int:
    """Consecutive Minimum defaults ending at month i (the record starts with the quarter)."""
    n = 0
    while i >= 0 and statuses[i] in DEFAULT:
        n, i = n + 1, i - 1
    return n


def partner_pack(k: str, months: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    sla = load_sla(PARTNER_FILES[k])
    com = sla["commercial"]
    at_risk = com["monthly_charges"] * com["at_risk_pct"] / 100
    P = [m["partners"][k] for m in months]
    n = len(months)
    ids = [r["id"] for r in P[-1]["csl"]]
    by = [{r["id"]: r for r in p["csl"]} for p in P]

    levels = []
    for cid in ids:
        c = get_csl(sla, cid)
        vals = [b[cid]["actual"] for b in by]
        levels.append({"id": cid, "name": c["name"], "unit": c["unit"], "direction": c["direction"],
                       "expected": c["expected"], "minimum": c["minimum"], "allocation_pct": c["credit_allocation_pct"],
                       "months": [{"measured": b[cid]["measured"], "actual": b[cid]["actual"], "status": b[cid]["status"],
                                   "credit": b[cid]["credit"], "reported": b[cid]["reported"]} for b in by],
                       "trend": _trend(c["direction"], vals),
                       "defaults": sum(1 for b in by if b[cid]["status"] in DEFAULT)})

    # Credits as published, then the doubling adjustment.
    credits = {"at_risk": at_risk, "months": [dict(p["credits"]) for p in P],
               "quarter_payable": sum(p["credits"]["payable"] for p in P), "quarter_at_risk": at_risk * n}
    adjust = []
    for i in range(n):
        crs, doubled = [], []
        for cid in ids:
            st = [b[cid]["status"] for b in by]
            if st[i] not in DEFAULT:
                continue
            run = _run(st, i)
            agg = [AGGRAVATORS[cid]] if cid in AGGRAVATORS else []
            cr = compute_credit(sla, cid, run, aggravators=agg)
            crs.append(cr)
            if cr.credit > by[i][cid]["credit"] + 1e-9:
                doubled.append({"csl": cid, "run": run, "published": by[i][cid]["credit"], "doubled": cr.credit})
        if doubled:
            unc, pay, capped = cap_monthly_credits(sla, crs)
            adjust.append({"month": months[i]["id"], "csls": doubled, "uncapped": unc, "payable": pay, "capped": bool(capped),
                           "published": P[i]["credits"]["payable"], "adjustment": pay - P[i]["credits"]["payable"]})
    credits["adjustments"] = adjust
    credits["quarter_adjusted"] = credits["quarter_payable"] + sum(a["adjustment"] for a in adjust)

    # Earnback on every default credit.
    need = com["earnback"]["following_periods_required"]
    earnback = []
    for i in range(n):
        for cid in ids:
            st = [b[cid]["status"] for b in by]
            if st[i] not in DEFAULT:
                continue
            run = _run(st, i)
            after = st[i + 1:i + 1 + need]
            met = sum(1 for s in after if s == "met_expected")
            if run >= com["doubling"]["consecutive_minimum_defaults"]:
                state, why = "ineligible", "doubled"
            elif cid in AGGRAVATORS:
                state, why = "ineligible", AGG_TEXT[AGGRAVATORS[cid]]
            elif any(s in ("below_expected",) + DEFAULT for s in after):
                state, why = "lost", f"missed Expected in {months[i + 1 + next(j for j, s in enumerate(after) if s in ('below_expected',) + DEFAULT)]['label']}"
            elif not after:
                state, why = "pending", f"the {need} months after fall in the next quarter"
            elif met >= need:
                state, why = "earned", f"met Expected in the {need} months after"
            else:
                state, why = "on track", f"met Expected in {met} of the {need} months after so far"
            earnback.append({"month": months[i]["id"], "csl": cid, "credit": by[i][cid]["credit"], "state": state, "why": why})

    # Chronic failure (each contract's chronic_failure triggers).
    cf_run = com["doubling"]["consecutive_minimum_defaults"]
    chronic = {"cf1": [], "cf2": [], "cf3": None}
    for lv in levels:
        st = [m["status"] for m in lv["months"]]
        hit = next((months[i]["id"] for i in range(n) if _run(st, i) >= 3), None)
        if hit:
            chronic["cf1"].append({"csl": lv["id"], "month": hit})
        if lv["defaults"]:
            chronic["cf2"].append({"csl": lv["id"], "defaults": lv["defaults"], "more": max(0, 4 - lv["defaults"])})
    six = at_risk * 6 * 0.5
    chronic["cf3"] = {"credits": credits["quarter_payable"], "threshold": six, "share": credits["quarter_payable"] / six}

    # Self-report against measurement: the partner's own report meets Expected while the measurement does not.
    self_report = []
    for lv in levels:
        cells = []
        for m in lv["months"]:
            rep, act = m["reported"], m["actual"]
            over = bool(rep is not None and act is not None and _meets(lv["direction"], rep, lv["expected"])
                        and not _meets(lv["direction"], act, lv["expected"]))
            cells.append({"reported": rep, "actual": act, "overstated": over,
                          "gap": None if rep is None or act is None else round(abs(rep - act), 3)})
        self_report.append({"id": lv["id"], "months": cells, "overstated": sum(c["overstated"] for c in cells)})
    overstated_by_month = [sum(1 for s in self_report if s["months"][i]["overstated"]) for i in range(n)]

    # Findings by type.
    types: dict[str, dict[str, Any]] = {}
    for i, p in enumerate(P):
        for f in p["findings"]:
            t = types.setdefault(f["type"], {"type": f["type"], "title": f["title"], "months": [0] * n})
            t["months"][i] += 1
    findings = sorted(types.values(), key=lambda t: (-sum(t["months"]), t["type"]))
    for t in findings:
        t["total"] = sum(t["months"])
        t["repeat"] = sum(1 for x in t["months"] if x) >= 2

    # Staffing fill.
    st_id = STAFFING[k]
    staffing = next(dict(lv, detail=[b[st_id]["detail"] for b in by]) for lv in levels if lv["id"] == st_id)

    # SLA change proposals, by rule.
    rule = cfg["proposals"]
    proposals = []
    for lv in levels:
        st = [m["status"] for m in lv["months"]]
        acts = [m["actual"] for m in lv["months"]]
        if lv["defaults"] >= rule["cap_min_defaults"]:
            proposals.append({"csl": lv["id"], "rule": "corrective_action_plan",
                              "fact": f"below Minimum in {lv['defaults']} of {n} months"})
        sr = next(s for s in self_report if s["id"] == lv["id"])
        if sr["overstated"] == n:
            proposals.append({"csl": lv["id"], "rule": "review_measure",
                              "fact": f"reported meeting Expected while measured below it in all {n} months"})
        if all(s == "met_expected" for s in st) and all(a is not None for a in acts):
            gap = abs(lv["expected"] - lv["minimum"])
            worst = min(acts) if lv["direction"] == "higher_is_better" else max(acts)
            margin = (worst - lv["expected"]) if lv["direction"] == "higher_is_better" else (lv["expected"] - worst)
            if gap and margin >= rule["tighten_margin_share"] * gap:
                proposals.append({"csl": lv["id"], "rule": "tighten",
                                  "fact": f"met Expected in all {n} months; worst month {A._pct(worst, 3)} against Expected {lv['expected']:g}"})

    return {"key": k, "name": NAMES[k], "supplier": sla["parties"]["supplier"]["name"], "levels": levels, "credits": credits,
            "earnback": earnback, "chronic": chronic, "self_report": self_report, "overstated_by_month": overstated_by_month,
            "findings": findings, "staffing": staffing, "proposals": proposals,
            "caps": [{"month": m["id"], "opened": p["caps"],
                      "due_in_quarter": sum(1 for x in p["caps_due"] if x <= months[-1]["end"])} for m, p in zip(months, P)],
            "terms": {"monthly_charges": com["monthly_charges"], "at_risk_pct": com["at_risk_pct"],
                      "doubling_after": com["doubling"]["consecutive_minimum_defaults"], "multiplier": com["doubling"]["multiplier"],
                      "earnback_periods": need}}


# --------------------------------------------------------------------------- September's programs
def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def program_actions(root: Path = ROOT, sample: Path = SAMPLE) -> dict[str, dict[str, Any]]:
    """Corrective actions that September's programs raised, by partner: post-incident reviews, the quality audit, and
    EHS. On-time closure is computed only where the record carries a close date (EHS actions)."""
    from scorecard import audit as AU
    out = {k: {"pir": [], "audit": [], "ehs": []} for k in PARTNERS}
    for f in sorted((root / "pir" / "reviews").glob("*.yaml")):
        rv = yaml.safe_load(f.read_text(encoding="utf-8"))
        for a in rv.get("actions", []):
            k = PIR_OWNERS.get(a["owner"])
            if k:
                out[k]["pir"].append({"ref": f"{f.stem} {a['id']}", "due": a["due"], "status": a["status"], "priority": a["priority"]})
    if (root / "data" / "audit" / "manifest.json").exists():
        page = AU.page_data(AU.load(root / "data" / "audit", sample), sample)
        for x in page["findings"]:
            out[x["partner"]]["audit"].append({"ref": x["id"], "due": x["due"], "status": "Open", "record": x["record"]})
    ev = root / "data" / "ehs" / "events.csv"
    if ev.exists():
        with ev.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r["action_due"] and r["partner"] in out:
                    closed = r["action_closed"] or None
                    out[r["partner"]]["ehs"].append({"ref": r["event"], "opened": r["at"][:10], "due": r["action_due"][:10],
                                                     "closed": closed[:10] if closed else None,
                                                     "on_time": bool(closed) and closed <= r["action_due"],
                                                     "days": (_day(closed) - _day(r["at"])).days if closed else None})
    for k, v in out.items():
        e = v["ehs"]
        days = [x["days"] for x in e if x["days"] is not None]
        v["summary"] = {"pir": len(v["pir"]), "pir_complete": sum(1 for x in v["pir"] if x["status"] == "Complete"),
                        "audit": len(v["audit"]), "ehs": len(e), "ehs_closed": sum(1 for x in e if x["closed"]),
                        "ehs_on_time": sum(1 for x in e if x["on_time"]),
                        "ehs_median_days": statistics.median(days) if days else None}
    return out


def roadmap(root: Path = ROOT) -> dict[str, Any]:
    """Hall B racks against their committed handoff dates, and Hall C first compute against its commitment."""
    from scorecard import deployments as D
    from scorecard import readiness as R
    racks = D.build()["racks"]
    rs = racks["racks"]
    asof = racks["as_of"]
    due = [r for r in rs if r["committed_handoff"] < asof]
    on_time = [r for r in due if r.get("measured_handoff") and r["measured_handoff"] <= r["committed_handoff"]]
    handed = [r for r in rs if r.get("measured_handoff")]
    rb = R.build()
    fc = rb["forecast"]
    first = re.sub(r"^CX-C-|-L\d$", "", fc["critical_path"][0])
    names = {x["id"]: x["name"].split(" (")[0] for x in rb["systems"]}
    return {"hall_b": {"racks": len(rs), "as_of": asof[:10], "handed_off": len(handed), "due": len(due), "on_time": len(on_time),
                       "last_committed": max(r["committed_handoff"] for r in rs)[:10]},
            "hall_c": {"committed": fc["committed"], "forecast": fc["first_compute"], "slip_days": fc["slip_days"],
                       "critical_path": names.get(first, first)}}   # a system's name: its ID is explained on the Deployments page


# --------------------------------------------------------------------------- the whole pack
def build_quarter(month_list: list[tuple[dict[str, Any], Path]], cfg: dict[str, Any]) -> dict[str, Any]:
    months = [_month(m, d) for m, d in month_list]
    packs = {k: partner_pack(k, months, cfg) for k in PARTNERS if all(k in m["partners"] for m in months)}
    return {"quarter": cfg["quarter"], "months": [{k: m[k] for k in ("id", "label", "start", "end", "sample")} for m in months],
            "packs": packs, "rule": cfg["proposals"]}


def load_notes(quarter: str, root: Path = ROOT) -> dict[str, Any] | None:
    p = root / "qbr" / "notes" / f"{quarter}.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None


def page_data(root: Path = ROOT) -> dict[str, Any]:
    cfg = load_config(root / "config" / "qbr.yaml")
    q = build_quarter(month_dirs(cfg, root), cfg)
    acts = program_actions(root)
    for k, p in q["packs"].items():
        p["actions"] = acts[k]
    q["roadmap"] = roadmap(root)
    q["notes"] = load_notes(cfg["quarter"], root)
    return q


def check(q: dict[str, Any]) -> list[str]:
    """The pack's own arithmetic: quarter totals equal the sum of the months, and the rules hold."""
    bad = []
    for k, p in q["packs"].items():
        c = p["credits"]
        if abs(c["quarter_payable"] - sum(m["payable"] for m in c["months"])) > 0.005:
            bad.append(f"{k}: quarter credits are not the sum of the months")
        for m in c["months"]:
            if m["payable"] > c["at_risk"] + 0.005:
                bad.append(f"{k}: a month's credits exceed the at-risk cap")
        for a in c["adjustments"]:
            if a["payable"] > c["at_risk"] + 0.005 or a["adjustment"] < 0:
                bad.append(f"{k} {a['month']}: the doubled month breaks the cap or lowers the credit")
            for x in a["csls"]:
                if x["run"] < p["terms"]["doubling_after"] or abs(x["doubled"] - x["published"] * p["terms"]["multiplier"]) > 0.005:
                    bad.append(f"{k} {a['month']} {x['csl']}: doubled without {p['terms']['doubling_after']} consecutive defaults")
        for lv in p["levels"]:
            st = [m["status"] for m in lv["months"]]
            runs = [_run(st, i) for i in range(len(st))]
            if (max(runs) >= 3) != any(x["csl"] == lv["id"] for x in p["chronic"]["cf1"]):
                bad.append(f"{k} {lv['id']}: chronic trigger CF-1 does not follow the months")
            if (max(runs) >= p["terms"]["doubling_after"]) != any(x["csl"] == lv["id"] for a in c["adjustments"] for x in a["csls"]):
                bad.append(f"{k} {lv['id']}: doubling does not follow the months")
        for e in p["earnback"]:
            if e["state"] == "earned":
                bad.append(f"{k} {e['csl']}: earnback earned inside one quarter")
    return bad


CODE = re.compile(r"\b(?:OT-|SEC-)?CSL-\d{2}\b")
