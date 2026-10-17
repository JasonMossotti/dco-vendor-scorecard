"""The Scorecards tab as a static page: every partner's scorecard, computed at build time.

The same engines and the same table helpers as the Python app (``scorecard.app_support``), run once per
shipped dataset when the site is built, so the page opens without starting Python in the browser. The app
itself stays at ``/app/lab/`` for generating a new random month.

``build()`` returns plain JSON: the datasets (each with the IT Partner, Landlord, Security Partner, and site
views) and the commercial terms of each contract, which the Service credits view explains and its calculator
applies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scorecard import app_support as A
from scorecard.sla_model import PARTNER_FILES, get_csl, load_sla

ROOT = A.ROOT
NAMES = {"it": "IT Partner", "landlord": "Landlord", "security": "Security Partner"}


def _plain(md: str) -> str:
    """App markdown to the page's light markup: **bold** stays (the page turns it into <b>), escapes go."""
    return md.replace("\\$", "$")


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _finding(f, it: bool) -> dict[str, Any]:
    return {"id": f.id, "severity": f.severity, "severity_name": f.severity_name, "title": f.title,
            "tickets": list(f.tickets), "unit": f.unit or "", "summary": f.summary,
            "evidence": A.evidence_rows(f), "reasons": list(f.severity_reasons) if it else [],
            "action": f.recommended_action, "refs": list(f.sla_refs)}


def _ev(ev) -> dict[str, int] | None:
    return None if ev is None else {"planted": ev.planted, "detected": ev.detected, "false_positives": len(ev.false_positives)}


def _credit_items(sc: dict[str, Any], sla: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in sc["credits"]["items"]:
        csl = get_csl(sla, c["csl"])
        out.append({"csl": c["csl"], "name": csl["name"], "allocation_pct": csl["credit_allocation_pct"], "credit": c["credit"],
                    "earnback": c.get("earnback_eligible")})
    return out


def _status(r: dict[str, Any]) -> str:
    return {"below_minimum": "default", "deep_below_minimum": "default", "below_expected": "rca",
            "met_expected": "met", "met": "met"}.get(r["status"], "na")


def _csl(sc: dict[str, Any], rows: list[dict[str, Any]], sla: dict[str, Any]) -> list[dict[str, Any]]:
    """The app's CSL table rows, each with its status class and allocation (for the flags and the credits view)."""
    by_id = {r["id"]: r for r in sc["csl"]}
    out = []
    for row in rows:
        r = by_id[row["ID"]]
        out.append({"row": row, "status": _status(r), "allocation_pct": get_csl(sla, r["id"])["credit_allocation_pct"],
                    "actual": r["actual"], "reported": r["vendor_reported"]})
    return out


def it_view(data_dir: Path) -> dict[str, Any]:
    sla = load_sla(PARTNER_FILES["it"])
    result, sc, ev = A.run_pipeline(sla, data_dir)
    targets = {p["id"]: p["restore_min"] for p in sla["priorities"]}
    t = sc["totals"]
    return {"supplier": sc["supplier"], "headline": _plain(A.headline(sc)),
            "tiles": {"defaults": t["defaults"], "payable": sc["credits"]["payable"], "uncapped": sc["credits"]["uncapped"],
                      "capped": sc["credits"]["capped"], "s1": t["s1"], "caps": len(sc["corrective_actions"]), "findings": t["findings"],
                      "incidents": t["incidents"], "gpu_hours_lost": round(t["gpu_hours_lost"], 1),
                      "vendor_gpu_hours_lost": round(t["vendor_gpu_hours_lost"], 1)},
            "reported": A.vendor_vs_measured_rows(sc), "csl": _csl(sc, A.csl_rows(sc), sla), "km": A.km_rows(sc),
            "weeks": A.weekly_rows(sc), "gaps": A.weekly_gap_rows(sc),
            "credits": {"items": _credit_items(sc, sla), "uncapped": sc["credits"]["uncapped"], "payable": sc["credits"]["payable"],
                        "capped": sc["credits"]["capped"]},
            "findings": [_finding(f, True) for f in result.findings], "caps": A.cap_rows(sc), "severity": A.severity_rows(sc),
            "incidents": A.incident_rows(sc, targets), "ev": _ev(ev)}


def landlord_view(data_dir: Path) -> dict[str, Any]:
    sla = load_sla(PARTNER_FILES["landlord"])
    result, sc, ev, _ = A.run_landlord_pipeline(data_dir)
    return {"supplier": sc["supplier"], "headline": _plain(A.landlord_headline(sc)),
            "tiles": {"defaults": len(sc["defaults"]), "payable": sc["credits"]["payable"], "capped": sc["credits"]["capped"],
                      "s1": sc["s1"], "findings": sc["findings"],
                      "events": len(sc["attribution"]), "disagree": sum(1 for r in sc["attribution"] if not r["agrees"])},
            "reported": A.landlord_vs_reported_rows(sc), "csl": _csl(sc, A.landlord_csl_rows(sc), sla), "km": A.landlord_km_rows(sc),
            "credits": {"items": _credit_items(sc, sla), "uncapped": sc["credits"]["uncapped"], "payable": sc["credits"]["payable"],
                        "capped": sc["credits"]["capped"]},
            "findings": [_finding(f, False) for f in result.findings], "events": A.attribution_display_rows(sc), "ev": _ev(ev)}


def security_view(data_dir: Path) -> dict[str, Any] | None:
    got = A.run_security_pipeline(data_dir)
    if got is None:
        return None
    result, sc, ev = got
    sla = load_sla(PARTNER_FILES["security"])
    return {"supplier": sc["supplier"], "headline": _plain(A.security_headline(sc)),
            "tiles": {"defaults": len(sc["defaults"]), "payable": sc["credits"]["payable"], "capped": sc["credits"]["capped"],
                      "s1": sc["s1"], "findings": sc["findings"]},
            "reported": A.security_vs_reported_rows(sc), "csl": _csl(sc, A.security_csl_rows(sc), sla), "km": A.landlord_km_rows(sc),
            "credits": {"items": _credit_items(sc, sla), "uncapped": sc["credits"]["uncapped"], "payable": sc["credits"]["payable"],
                        "capped": sc["credits"]["capped"]},
            "findings": [_finding(f, False) for f in result.findings], "ev": _ev(ev)}


def dataset(label: str, key: str, data_dir: Path) -> dict[str, Any]:
    result, sc, ev = A.run_pipeline(load_sla(PARTNER_FILES["it"]), data_dir)
    out: dict[str, Any] = {"key": key, "label": label, "start": _iso(sc["window"]["start"]), "end": _iso(sc["window"]["end"]),
                           "it": it_view(data_dir), "landlord": None, "security": None, "site": None}
    if A.has_facility(data_dir):
        _, ll_sc, ll_ev, it_plain = A.run_landlord_pipeline(data_dir)
        out["landlord"] = landlord_view(data_dir)
        out["security"] = security_view(data_dir)
        sec = A.run_security_pipeline(data_dir)
        out["site"] = {"rows": A.site_rows(sc, ll_sc, ev, ll_ev, *(sec[1:] if sec else (None, None))),
                       "crossing": [_plain(x) for x in A.crossing_outages(ll_sc, result)],
                       "attribution": A.attribution_change_rows(sc, it_plain)}
    return out


def terms() -> dict[str, Any]:
    """Each contract's commercial terms and credit-bearing service levels, straight from the SLA YAML."""
    out = {}
    for k in NAMES:
        sla = load_sla(PARTNER_FILES[k])
        c = sla["commercial"]
        out[k] = {"name": NAMES[k], "monthly_charges": c["monthly_charges"], "at_risk_pct": c["at_risk_pct"], "pool_pct": c["pool_pct"],
                  "max_allocation_pct": c["max_allocation_per_csl_pct"], "application": c["credit_application"],
                  "doubling_after": c["doubling"]["consecutive_minimum_defaults"], "multiplier": c["doubling"]["multiplier"],
                  "earnback_periods": c["earnback"]["following_periods_required"],
                  "earnback_ineligible": list(c["earnback"]["ineligible_when"]),
                  "csl": [{"id": x["id"], "name": x["name"], "allocation_pct": x["credit_allocation_pct"]} for x in sla["critical_service_levels"]]}
    ehs = load_sla(PARTNER_FILES["it"])["ehs"]
    out["ehs"] = {"classes": [{"id": x["id"], "name": x["name"], "pct": x["credit_pct_of_monthly_charges"]} for x in ehs["violation_classes"]],
                  "self_reported_reduction_pct": ehs["credits"]["self_reported_reduction_pct"],
                  "concealment_multiplier": ehs["credits"]["concealment_multiplier"]}
    return out


def build(root: Path = ROOT) -> dict[str, Any]:
    sets = []
    for label, d in A.available_datasets(root).items():
        key = "sample" if Path(d).name == "sample" else "latest"
        sets.append(dataset(label, key, Path(d)))
    return {"datasets": sets, "terms": terms()}

