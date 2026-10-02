"""Logic behind the interactive app, kept free of Streamlit so it can be tested.

The app is a thin display layer over these functions:

* ``apply_overrides``: build a what-if copy of the SLA from slider values.
* ``run_pipeline``: engine -> scorecard -> self-check, cached per (dataset, SLA).
* ``generate_month``: make a brand-new synthetic month in a temporary folder.
* ``*_rows``: plain list-of-dict tables the app turns into DataFrames.
"""

from __future__ import annotations

import copy
import json
import tempfile
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from scorecard.builder import build_scorecard
from scorecard.connectors import FileConnector
from scorecard.engine import run_engine
from scorecard.engine.core import fmt_t
from scorecard.engine.evaluate import evaluate
from scorecard.sla_model import load_sla
from scorecard.synthetic import SiteGenerator, write_dataset

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #
def available_datasets(root: Path = ROOT) -> dict[str, Path]:
    """Label -> dataset folder for the datasets shipped with the app."""
    out = {}
    sample = root / "data" / "sample"
    if (sample / "manifest.json").exists():
        out["Committed sample (Aug 31 to Sep 27, 2026)"] = sample
    latest = root / "data" / "latest"
    if (latest / "manifest.json").exists():
        w = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))["window"]
        out[f"Latest 4 weeks ({w['start'][:10]} to {w['end'][:10]}, refreshed weekly)"] = latest
    return out


def generate_month(seed: int, root: Path = ROOT, start: date | None = None) -> Path:
    """Generate a fresh 4-week dataset for ``seed`` into a temporary folder."""
    cfg = yaml.safe_load((root / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    if start is None:
        today = date.today()
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=cfg["weeks"])
    out = Path(tempfile.mkdtemp(prefix=f"month_{seed}_"))
    write_dataset(SiteGenerator(load_sla(), cfg, start=start, seed=seed).run(), out)
    return out


# --------------------------------------------------------------------------- #
# What-if SLA
# --------------------------------------------------------------------------- #
def contract_defaults(sla: dict[str, Any]) -> dict[str, Any]:
    """Current contract values for every control the app exposes."""
    prio = {p["id"]: p for p in sla["priorities"]}
    fc = {f["id"]: f for f in sla["measurement_spec"]}
    return {
        "restore_hours": {p: prio[p]["restore_min"] / 60 for p in ("P1", "P2", "P3")},
        "early_failure_minutes": sla["ticket_handling"]["stability"]["early_failure_minutes"],
        "stability_hours": fc["FC-GPU"]["stability_window_hours"],
        "at_risk_pct": sla["commercial"]["at_risk_pct"],
        "thresholds": {c["id"]: (c["expected"], c["minimum"]) for c in sla["critical_service_levels"]},
    }


def apply_overrides(sla: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Return a modified deep copy of the SLA. Unknown or missing keys are ignored."""
    new = copy.deepcopy(sla)
    for p in new["priorities"]:
        if p["id"] in overrides.get("restore_hours", {}):
            p["restore_min"] = int(round(overrides["restore_hours"][p["id"]] * 60))
    if "early_failure_minutes" in overrides:
        new["ticket_handling"]["stability"]["early_failure_minutes"] = int(overrides["early_failure_minutes"])
    if "stability_hours" in overrides:
        for f in new["measurement_spec"]:
            if f["id"] in ("FC-GPU", "FC-LINK", "FC-SWITCH", "FC-PSU", "FC-SHELF"):
                f["stability_window_hours"] = overrides["stability_hours"]
    if "at_risk_pct" in overrides:
        new["commercial"]["at_risk_pct"] = overrides["at_risk_pct"]
    for c in new["critical_service_levels"]:
        if c["id"] in overrides.get("thresholds", {}):
            c["expected"], c["minimum"] = overrides["thresholds"][c["id"]]
    return new


def changed_from_contract(sla: dict[str, Any], overrides: dict[str, Any]) -> list[str]:
    """Human-readable list of what differs from the contract."""
    d = contract_defaults(sla)
    out = []
    for p, h in overrides.get("restore_hours", {}).items():
        if abs(h - d["restore_hours"][p]) > 1e-9:
            out.append(f"{p} restore target {d['restore_hours'][p]:g} -> {h:g} hrs")
    if overrides.get("early_failure_minutes", d["early_failure_minutes"]) != d["early_failure_minutes"]:
        out.append(f"Early-failure window {d['early_failure_minutes']} -> {overrides['early_failure_minutes']} min")
    if overrides.get("stability_hours", d["stability_hours"]) != d["stability_hours"]:
        out.append(f"Stability window {d['stability_hours']} -> {overrides['stability_hours']} hrs")
    if overrides.get("at_risk_pct", d["at_risk_pct"]) != d["at_risk_pct"]:
        out.append(f"At-risk amount {d['at_risk_pct']}% -> {overrides['at_risk_pct']}%")
    for cid, (e, m) in overrides.get("thresholds", {}).items():
        if (e, m) != d["thresholds"][cid]:
            out.append(f"{cid} Expected/Minimum {d['thresholds'][cid][0]:g}/{d['thresholds'][cid][1]:g} -> {e:g}/{m:g}")
    return out


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=12)
def _run_cached(data_dir: str, sla_json: str):
    sla = json.loads(sla_json)
    result = run_engine(sla, FileConnector(data_dir))
    sc = build_scorecard(sla, result)
    has_key = (Path(data_dir) / "ground_truth" / "planted_discrepancies.json").exists()
    ev = evaluate(result.findings, data_dir) if has_key else None   # read only after the engine has finished
    return result, sc, ev


def run_pipeline(sla: dict[str, Any], data_dir: str | Path):
    """(engine result, scorecard, evaluation or None) for a dataset and SLA."""
    return _run_cached(str(data_dir), json.dumps(sla, sort_keys=True, default=str))


# --------------------------------------------------------------------------- #
# Tables for display
# --------------------------------------------------------------------------- #
def _pct(v: float | None, d: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{d}f}%"


def headline(sc: dict[str, Any]) -> str:
    defaults = [r["id"] for r in sc["csl"] if r["status"] in ("below_minimum", "deep_below_minimum")]
    clean = sum(1 for w in sc["weeks"] if w["vendor_note"].startswith("All SLAs met"))
    cr = sc["credits"]
    s1 = sum(1 for e in sc["severity_log"] if e["level"] == "S1")
    return (f"The supplier's weekly reports claimed every SLA was met in {clean} of {len(sc['weeks'])} weeks. "
            f"Measured from telemetry: **{len(defaults)} Minimum defaults**"
            + (f" ({', '.join(defaults)})" if defaults else "")
            + f", **{s1} S1 items**, and **${cr['payable']:,.0f}** in credits"
            + (f" (capped from ${cr['uncapped']:,.0f})." if cr["capped"] else "."))


def vendor_vs_measured_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Service level": f"{r['id']} {r['name']}", "Vendor reported (%)": r["vendor_reported"],
             "Measured (%)": r["actual"],
             "Gap (pts)": None if r["actual"] is None else round(r["actual"] - r["vendor_reported"], 2)}
            for r in sc["csl"] if r["vendor_reported"] is not None]


def csl_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    sym = lambda r: "≥" if r["direction"] == "higher_is_better" else "≤"  # noqa: E731
    return [{"ID": r["id"], "Service level": r["name"],
             "Expected": f"{sym(r)} {r['expected']:g}%", "Minimum": f"{sym(r)} {r['minimum']:g}%",
             "Measured": _pct(r["actual"]), "Vendor reported": _pct(r["vendor_reported"]),
             "Status": r["status_text"], "Credit": f"${r['credit']:,.0f}" if r["credit"] else "",
             "Basis": r["detail"] + (f". {r['note']}" if r["note"] else "")} for r in sc["csl"]]


def km_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for k in sc["km"]:
        sym = "≥" if k["direction"] == "higher_is_better" else "≤"
        unit = k["unit"]
        val = "n/a" if k["actual"] is None else (_pct(k["actual"]) if unit == "%" else f"{k['actual']:g}{unit}")
        rows.append({"ID": k["id"], "Key measurement": k["name"], "Target": f"{sym} {k['target']:g}{unit}",
                     "Measured": val, "Result": "n/a" if k["met"] is None else ("Met" if k["met"] else "Missed"),
                     "Basis": k["detail"]})
    return rows


def weekly_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for w in sc["weeks"]:
        out.append({"Week": w["week_start"].strftime("%Y-%m-%d"),
                    "P2 restore, vendor": w["vendor"]["CSL-04"], "P2 restore, measured": w["measured"]["CSL-04"],
                    "First-time fix, vendor": w["vendor"]["CSL-06"], "First-time fix, measured": w["measured"]["CSL-06"],
                    "Staffing, vendor": w["vendor"]["CSL-10"], "Staffing, measured": w["measured"]["CSL-10"],
                    "Findings": w["findings"], "Vendor's note": w["vendor_note"]})
    return out


def incident_rows(sc: dict[str, Any], target_min: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for i in sc["incidents"]:
        tgt = target_min[i.priority]
        rows.append({"Ticket of Record": i.key, "Class": i.fault_class, "Priority": i.priority, "Unit": i.unit,
                     "Rack": i.rack, "T0": fmt_t(i.t0),
                     "Measured restore (hrs)": round(i.measured_min / 60, 2),
                     "Vendor restore (hrs)": round(sum(i.vendor_restore_min) / 60, 2),
                     "Target (hrs)": tgt / 60, "Within target": i.measured_min <= tgt,
                     "First-time fix": i.first_time_fix, "Validated": i.validated,
                     "Vendor tickets": ", ".join(i.tickets)})
    return rows


def cap_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"CAP": c["id"], "Severity": c["level"], "Tickets": ", ".join(c["tickets"]) or (c["unit"] or "-"),
             "Triggers": "; ".join(c["triggers"]), "Required actions": " ".join(c["actions"]),
             "Owner": c["owner"], "Due": c["due"].strftime("%Y-%m-%d"), "Status": c["status"]}
            for c in sc["corrective_actions"]]


def severity_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Severity": e["level"], "Kind": e["kind"], "Reference": e["ref"],
             "Tickets": ", ".join(e["tickets"]) or "-", "What happened": e["title"]} for e in sc["severity_log"]]


def evidence_rows(finding) -> list[dict[str, Any]]:
    return [{"Source": e["source"], "Time": fmt_t(e["at"]) if e["at"] else "-", "Evidence": e["detail"]}
            for e in finding.evidence]
