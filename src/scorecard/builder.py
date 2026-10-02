"""Assemble the scorecard from engine results.

``build_scorecard(sla, result)`` is a pure function of the SLA and the data: the
browser app calls it again with a modified SLA (for example, a tighter restore
target) and every status, credit, severity, and corrective action updates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from scorecard.engine.core import Context, Finding, fmt_t
from scorecard.engine.run import EngineResult
from scorecard.kpi import INTEGRITY_TYPES, ScoredIncident, build_incidents, measure_period
from scorecard.sla_model import (
    cap_monthly_credits, classify_event_breach, classify_period_breach, compute_credit, evaluate_csl,
)

# Vendor weekly self-report fields that correspond to a CSL.
VENDOR_FIELDS = {
    "CSL-01": ("gpu_availability_pct", None),
    "CSL-03": ("restore_performance", "P1"),
    "CSL-04": ("restore_performance", "P2"),
    "CSL-05": ("restore_performance", "P3"),
    "CSL-06": ("first_time_fix_pct", None),
    "CSL-07": ("validated_rts_pct", None),
    "CSL-10": ("staffing_fill_pct", None),
}
SEV_RANK = {"S1": 4, "S2": 3, "S3": 2, "S4": 1, None: 0}
STATUS_TEXT = {"met_expected": "Met", "below_expected": "Below Expected", "below_minimum": "Minimum default",
               "deep_below_minimum": "Minimum default (severe)", "no_events": "No events"}


def _vendor_value(weeks: list[dict], csl: str) -> float | None:
    if csl not in VENDOR_FIELDS or not weeks:
        return None
    fld, prio = VENDOR_FIELDS[csl]
    if prio:
        rows = [w[fld][prio] for w in weeks if w[fld][prio]["count"]]
        n = sum(r["count"] for r in rows)
        return round(sum(r["within_target_pct"] * r["count"] for r in rows) / n, 3) if n else None
    return round(sum(w[fld] for w in weeks) / len(weeks), 3)


def _add_business_days(dt: datetime, n: int) -> datetime:
    d = dt
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _csl_rows(sla: dict, measured: dict, vendor_weeks: list[dict]) -> list[dict]:
    rows = []
    for c in sla["critical_service_levels"]:
        r = measured.get(c["id"], {"actual": None, "events": None, "misses": None, "detail": "Not measured"})
        if r["actual"] is None:
            status, res = "no_events", None
        else:
            res = evaluate_csl(sla, c["id"], r["actual"], r.get("events"), r.get("misses"))
            status = res.status
        rows.append({
            "id": c["id"], "name": c["name"], "unit": c["unit"], "direction": c["direction"],
            "expected": c["expected"], "minimum": c["minimum"], "allocation_pct": c["credit_allocation_pct"],
            "actual": r["actual"], "events": r.get("events"), "misses": r.get("misses"), "detail": r["detail"],
            "status": status, "status_text": STATUS_TEXT[status], "note": res.note if res else "",
            "vendor_reported": _vendor_value(vendor_weeks, c["id"]),
            "_result": res,
        })
    return rows


def _km_rows(sla: dict, measured: dict) -> list[dict]:
    rows = []
    for k in sla["key_measurements"]:
        r = measured.get(k["id"])
        if r is None or r["actual"] is None:
            rows.append({"id": k["id"], "name": k["name"], "target": k["target"], "unit": k["unit"],
                         "direction": k["direction"], "actual": None, "met": None,
                         "detail": r["detail"] if r else "Not measured in the demo data"})
            continue
        met = r["actual"] >= k["target"] if k["direction"] == "higher_is_better" else r["actual"] <= k["target"]
        rows.append({"id": k["id"], "name": k["name"], "target": k["target"], "unit": k["unit"],
                     "direction": k["direction"], "actual": r["actual"], "met": met, "detail": r["detail"]})
    return rows


def _severity_log(sla: dict, ctx: Context, incidents: list[ScoredIncident], findings: list[Finding],
                  csl_rows: list[dict]) -> list[dict]:
    target = {p["id"]: p["restore_min"] for p in sla["priorities"]}
    log = []
    for f in findings:
        log.append({"level": f.severity, "kind": "Discrepancy", "ref": f.id, "tickets": f.tickets,
                    "unit": f.unit, "at": f.observed_at, "title": f.title, "description": f.summary,
                    "action": f.recommended_action})
    for i in incidents:
        tgt = target[i.priority]
        if i.measured_min <= tgt:
            continue
        aggs = []
        if i.gpus >= sla["site"]["per_rack"]["gpus"]:
            aggs.append("AGG-RACKWIDE")
        if i.is_child or i.early_failures or i.reopens:
            aggs.append("AGG-REPEAT")
        if i.integrity_issue:
            aggs.append("AGG-INTEGRITY")
        sev = classify_event_breach(sla, tgt, i.measured_min, max(i.gpus, 1), aggs)
        log.append({"level": sev.level, "kind": "Restore breach", "ref": i.key, "tickets": i.tickets, "unit": i.unit,
                    "at": i.t0, "title": f"{i.priority} restore {i.measured_min / 60:.1f} hrs vs {tgt // 60}-hr target",
                    "description": "; ".join(sev.reasons),
                    "action": "RCA on the delay (dispatch, diagnosis, parts, or validation) with a corrective action for the cause."})
    for r in csl_rows:
        if r["_result"] is None or r["status"] == "met_expected":
            continue
        sev = classify_period_breach(sla, r["_result"], 1 if r["_result"].is_minimum_default else 0)
        log.append({"level": sev.level, "kind": "Service level", "ref": r["id"], "tickets": [], "unit": None,
                    "at": ctx.window_end, "title": f"{r['id']} {r['name']}: {r['status_text']}",
                    "description": f"{r['detail']}. " + "; ".join(sev.reasons),
                    "action": f"Supplier RCA and corrective action plan for {r['id']} (SLA Section 17)."})
    log.sort(key=lambda e: (-SEV_RANK[e["level"]], e["at"] or ctx.window_end))
    return log


def _corrective_actions(sla: dict, log: list[dict]) -> list[dict]:
    """Draft one CAP per affected ticket group (or service level) for every S1/S2 entry."""
    days = {"S1": 5, "S2": 10}
    groups: dict[tuple, dict] = {}
    for e in log:
        if e["level"] not in days:
            continue
        key = tuple(sorted(e["tickets"])) or (e["ref"],)
        # Merge with an existing group that shares any ticket.
        match = next((k for k in groups if e["tickets"] and set(k) & set(e["tickets"])), None)
        g = groups.get(match) if match else None
        due = _add_business_days(e["at"], days[e["level"]])
        if g is None:
            groups[key] = {"level": e["level"], "tickets": sorted(set(e["tickets"])), "unit": e["unit"],
                           "triggers": [f"{e['ref']} {e['title']}"], "actions": [e["action"]], "due": due}
        else:
            g["triggers"].append(f"{e['ref']} {e['title']}")
            if e["action"] not in g["actions"]:
                g["actions"].append(e["action"])
            if SEV_RANK[e["level"]] > SEV_RANK[g["level"]]:
                g["level"] = e["level"]
            g["due"] = min(g["due"], due)
    caps = sorted(groups.values(), key=lambda g: (-SEV_RANK[g["level"]], g["due"]))
    for n, g in enumerate(caps, start=1):
        g.update({"id": f"CAP-{n:03d}", "owner": "Supplier site manager", "reviewer": "Customer site lead",
                  "status": "Open"})
    return caps


def build_scorecard(sla: dict[str, Any], result: EngineResult) -> dict[str, Any]:
    ctx, findings = result.context, result.findings
    incidents = build_incidents(ctx, findings)
    measured = measure_period(ctx, incidents, findings, ctx.window_start, ctx.window_end, sla)
    csl = _csl_rows(sla, measured, ctx.vendor_weekly)
    kms = _km_rows(sla, measured)

    integrity_csls = {"CSL-11"}
    credits = [compute_credit(sla, r["id"], 1, aggravators=["AGG-INTEGRITY"] if r["id"] in integrity_csls else [])
               for r in csl if r["status"] in ("below_minimum", "deep_below_minimum")]
    uncapped, payable, capped = cap_monthly_credits(sla, credits)
    for r in csl:
        r["credit"] = next((c.credit for c in credits if c.csl_id == r["id"]), 0.0)

    weeks = []
    for w in ctx.vendor_weekly:
        ws, we = w["week_start"], w["week_end"]
        wm = measure_period(ctx, incidents, findings, ws, we, sla)
        weeks.append({"week_start": ws, "week_end": we,
                      "measured": {k: v["actual"] for k, v in wm.items()},
                      "vendor": {cid: _vendor_value([w], cid) for cid in VENDOR_FIELDS},
                      "vendor_note": w["notes"],
                      "findings": sum(1 for f in findings if f.observed_at and ws <= f.observed_at < we)})

    log = _severity_log(sla, ctx, incidents, findings, csl)
    caps = _corrective_actions(sla, log)
    lost = sum(i.lost_gpu_hours(ctx.window_start, ctx.window_end) for i in incidents)
    vendor_lost = sum(i.gpus * i.factor * sum(i.vendor_restore_min) / 60 for i in incidents)
    for r in csl:
        r.pop("_result")
    return {
        "window": {"start": ctx.window_start, "end": ctx.window_end},
        "site": sla["site"]["name"],
        "supplier": sla["parties"]["supplier"]["name"],
        "csl": csl,
        "km": kms,
        "credits": {"items": [{"csl": c.csl_id, "credit": c.credit, "explanation": c.explanation,
                               "earnback_eligible": c.earnback_eligible} for c in credits],
                    "at_risk": credits[0].at_risk_amount if credits else sla["commercial"]["monthly_charges"] * sla["commercial"]["at_risk_pct"] / 100,
                    "uncapped": uncapped, "payable": payable, "capped": capped},
        "weeks": weeks,
        "severity_log": log,
        "corrective_actions": caps,
        "incidents": incidents,
        "totals": {"incidents": len(incidents), "tickets": len(ctx.tickets), "findings": len(findings),
                   "gpu_hours_lost": lost, "vendor_gpu_hours_lost": vendor_lost,
                   "defaults": sum(1 for r in csl if r["status"] in ("below_minimum", "deep_below_minimum")),
                   "s1": sum(1 for e in log if e["level"] == "S1")},
    }
