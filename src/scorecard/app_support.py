"""Logic behind the interactive app, kept free of Streamlit so it can be tested.

The app is a thin display layer over these functions:

* ``run_pipeline``: engine -> scorecard -> self-check, cached per dataset.
* ``generate_month``: make a brand-new synthetic month in a temporary folder.
* ``*_rows``: plain list-of-dict tables the app turns into DataFrames.
"""

from __future__ import annotations

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


def _round(v: float | None, d: int) -> float | None:
    return None if v is None else round(v, d)


def _threshold(direction: str, v: float) -> str:
    if direction == "higher_is_better" and v == 100:
        return "100%"
    return f"{'≥' if direction == 'higher_is_better' else '≤'} {v:g}%"


def headline(sc: dict[str, Any]) -> str:
    defaults = [r["id"] for r in sc["csl"] if r["status"] in ("below_minimum", "deep_below_minimum")]
    clean = sum(1 for w in sc["weeks"] if w["vendor_note"].startswith("All SLAs met"))
    cr = sc["credits"]
    s1 = sum(1 for e in sc["severity_log"] if e["level"] == "S1")
    return (f"The supplier's weekly reports claimed every SLA was met in {clean} of {len(sc['weeks'])} weeks. "
            f"Measured from telemetry: **{len(defaults)} Minimum defaults**"
            + (f" ({', '.join(defaults)})" if defaults else "")
            + f", **{s1} S1 items**, and **\\${cr['payable']:,.0f}** in credits"
            + (f" (capped from \\${cr['uncapped']:,.0f})." if cr["capped"] else "."))


def vendor_vs_measured_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Service level": f"{r['id']} {r['name']}", "Vendor reported (%)": _round(r["vendor_reported"], 2),
             "Measured (%)": _round(r["actual"], 2),
             "Gap (pts)": None if r["actual"] is None else round(r["actual"] - r["vendor_reported"], 2)}
            for r in sc["csl"] if r["vendor_reported"] is not None]


def csl_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"ID": r["id"], "Service level": r["name"],
             "Expected": _threshold(r["direction"], r["expected"]), "Minimum": _threshold(r["direction"], r["minimum"]),
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
        v, m = w["vendor"], w["measured"]
        out.append({"Week": w["week_start"].strftime("%Y-%m-%d"),
                    "P2 restore, vendor": _round(v["CSL-04"], 1), "P2 restore, measured": _round(m["CSL-04"], 1),
                    "First-time fix, vendor": _round(v["CSL-06"], 1), "First-time fix, measured": _round(m["CSL-06"], 1),
                    "Staffing, vendor": _round(v["CSL-10"], 1), "Staffing, measured": _round(m["CSL-10"], 1),
                    "Findings": w["findings"], "Vendor's note": w["vendor_note"]})
    return out


GAP_SERIES = {"P2 restore": "CSL-04", "First-time fix": "CSL-06", "Validated return to service": "CSL-07",
              "Staffing fill": "CSL-10"}


def weekly_gap_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    """Measured minus vendor-reported, in points, per week. 0 means the vendor's report was accurate;
    below 0 means the vendor overstated performance."""
    out = []
    for w in sc["weeks"]:
        row: dict[str, Any] = {"Week": w["week_start"].strftime("%Y-%m-%d")}
        for label, cid in GAP_SERIES.items():
            v, m = w["vendor"].get(cid), w["measured"].get(cid)
            row[label] = None if v is None or m is None else round(m - v, 1)
        out.append(row)
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
             "Owner": c["owner"], "Raised": c["raised"].strftime("%Y-%m-%d"), "Due": c["due"].strftime("%Y-%m-%d"),
             "Status": c["status"]}
            for c in sc["corrective_actions"]]


def severity_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Severity": e["level"], "Kind": e["kind"], "Reference": e["ref"],
             "Tickets": ", ".join(e["tickets"]) or "-", "What happened": e["title"]} for e in sc["severity_log"]]


def evidence_rows(finding) -> list[dict[str, Any]]:
    return [{"Source": e["source"], "Time": fmt_t(e["at"]) if e["at"] else "-", "Evidence": e["detail"]}
            for e in finding.evidence]
