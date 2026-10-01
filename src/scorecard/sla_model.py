"""SLA model: load the machine-readable SLA, validate it, and apply its rules.

Everything the scorecard needs to judge vendor performance comes from
sla/vendor_sla.yaml. This module turns that file into answers:

* ``load_sla`` / ``validate_sla``: read the file and refuse to run on a broken SLA.
* ``evaluate_csl``: did a measured value meet Expected, Minimum, or neither?
* ``compute_credit`` / ``cap_monthly_credits``: contractual credit math.
* ``classify_event_breach`` / ``classify_period_breach``: internal severity (S1-S4).

Only standard library + PyYAML are used so the same code runs locally, on
GitHub Actions, on EC2, and in the browser (stlite / Pyodide).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

DEFAULT_SLA_PATH = Path(__file__).resolve().parents[2] / "sla" / "vendor_sla.yaml"

HIGHER = "higher_is_better"
LOWER = "lower_is_better"


class SLAValidationError(ValueError):
    """Raised when the SLA file is internally inconsistent."""


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #
def load_sla(path: str | Path = DEFAULT_SLA_PATH, validate: bool = True) -> dict[str, Any]:
    """Load the SLA YAML. Validates by default and raises on any problem."""
    with open(path, encoding="utf-8") as fh:
        sla = yaml.safe_load(fh)
    if validate:
        errors = validate_sla(sla)
        if errors:
            raise SLAValidationError("SLA failed validation:\n  - " + "\n  - ".join(errors))
    return sla


def validate_sla(sla: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems. An empty list means valid."""
    errors: list[str] = []
    commercial = sla.get("commercial", {})
    pool = commercial.get("pool_pct", 0)
    per_cap = commercial.get("max_allocation_per_csl_pct", 100)

    # Data source references must resolve.
    ds_ids = {d["id"] for d in sla.get("measurement", {}).get("data_sources", [])}
    category_ids = {c["id"] for c in sla.get("performance_categories", [])}

    csls = sla.get("critical_service_levels", [])
    kms = sla.get("key_measurements", [])

    # Unique IDs across CSLs and KMs.
    seen: set[str] = set()
    for item in csls + kms:
        if item["id"] in seen:
            errors.append(f"Duplicate service level id {item['id']}")
        seen.add(item["id"])

    total_alloc = 0.0
    for c in csls:
        cid = c["id"]
        alloc = c.get("credit_allocation_pct", 0)
        total_alloc += alloc
        if alloc > per_cap:
            errors.append(f"{cid}: allocation {alloc}% exceeds per-CSL cap {per_cap}%")
        if c.get("direction") not in (HIGHER, LOWER):
            errors.append(f"{cid}: direction must be '{HIGHER}' or '{LOWER}'")
            continue
        exp, mn = c.get("expected"), c.get("minimum")
        if exp is None or mn is None:
            errors.append(f"{cid}: expected and minimum are both required")
            continue
        # Expected must be at least as demanding as Minimum.
        if c["direction"] == HIGHER and exp < mn:
            errors.append(f"{cid}: expected ({exp}) must be >= minimum ({mn}) for higher_is_better")
        if c["direction"] == LOWER and exp > mn:
            errors.append(f"{cid}: expected ({exp}) must be <= minimum ({mn}) for lower_is_better")
        if c.get("category") not in category_ids:
            errors.append(f"{cid}: unknown category {c.get('category')}")
        for ds in c.get("data_sources", []):
            if ds not in ds_ids:
                errors.append(f"{cid}: unknown data source {ds}")

    if total_alloc > pool:
        errors.append(f"Total CSL allocation {total_alloc}% exceeds pool {pool}%")

    for k in kms:
        if k.get("direction") not in (HIGHER, LOWER):
            errors.append(f"{k['id']}: invalid direction")
        for ds in k.get("data_sources", []):
            if ds not in ds_ids:
                errors.append(f"{k['id']}: unknown data source {ds}")

    # Priorities: P1-P4 present, and stricter priorities have tighter targets.
    prios = {p["id"]: p for p in sla.get("priorities", [])}
    for pid in ("P1", "P2", "P3", "P4"):
        if pid not in prios:
            errors.append(f"Missing priority {pid}")
    if all(p in prios for p in ("P1", "P2", "P3", "P4")):
        restores = [prios[p]["restore_min"] for p in ("P1", "P2", "P3", "P4")]
        if restores != sorted(restores):
            errors.append("Restore targets must increase from P1 to P4")

    # Measurement Specification: every rule card must reference real things.
    rts_classes = {c["component"] for c in sla.get("rts_validation", {}).get("classes", [])}
    th = sla.get("ticket_handling", {})
    early_min = th.get("stability", {}).get("early_failure_minutes", 0)
    fc_ids: set[str] = set()
    for fc in sla.get("measurement_spec", []):
        fid = fc["id"]
        if fid in fc_ids:
            errors.append(f"Duplicate fault class {fid}")
        fc_ids.add(fid)
        if fc["detection"]["source"] not in ds_ids:
            errors.append(f"{fid}: unknown detection source {fc['detection']['source']}")
        if fc["default_priority"] not in prios:
            errors.append(f"{fid}: unknown default priority {fc['default_priority']}")
        for vc in fc["validation_class"]:
            if vc not in rts_classes:
                errors.append(f"{fid}: validation class '{vc}' not in Return-to-Service Validation")
        if fc["stability_window_hours"] * 60 <= early_min:
            errors.append(f"{fid}: stability window must be longer than the early-failure window")
        if fc["recurrence_window_days"] * 24 <= fc["stability_window_hours"]:
            errors.append(f"{fid}: recurrence window must be longer than the stability window")
        for st in fc["capacity_impact"]["states"]:
            if not 0 <= st["factor"] <= 1:
                errors.append(f"{fid}: capacity factor must be between 0 and 1")
    if sla.get("measurement_spec") and not th:
        errors.append("measurement_spec requires a ticket_handling section")
    allowed_pauses = {pc["code"] for pc in th.get("pause_codes", [])}
    if th and len(allowed_pauses) != len(sla["measurement"]["clock_rules"]["pause_allowed_only_for"]):
        errors.append("Pause codes must correspond one-to-one with the clock pause rules")
    for r in sla.get("capacity_accounting", {}).get("rollups", []):
        if r["metric"] not in seen:
            errors.append(f"Capacity rollup references unknown service level {r['metric']}")

    # Severity bands must be ascending, and end with an open (null) band.
    sev = sla.get("breach_severity", {})
    level_ids = {lvl["id"] for lvl in sev.get("levels", [])}
    for dim_name, dim in sev.get("event_dimensions", {}).items():
        maxes = [b["max"] for b in dim["bands"]]
        if maxes[-1] is not None:
            errors.append(f"Severity dimension {dim_name}: last band must have max: null")
        finite = [m for m in maxes if m is not None]
        if finite != sorted(finite):
            errors.append(f"Severity dimension {dim_name}: bands must be ascending")
        for b in dim["bands"]:
            if b["level"] not in level_ids:
                errors.append(f"Severity dimension {dim_name}: unknown level {b['level']}")
    for agg in sev.get("aggravators", []):
        if agg["effect"] == "floor" and agg.get("level") not in level_ids:
            errors.append(f"Aggravator {agg['id']}: unknown floor level")
        if agg["effect"] not in ("floor", "bump"):
            errors.append(f"Aggravator {agg['id']}: effect must be 'floor' or 'bump'")

    return errors


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def get_csl(sla: dict[str, Any], csl_id: str) -> dict[str, Any]:
    for c in sla["critical_service_levels"]:
        if c["id"] == csl_id:
            return c
    raise KeyError(f"Unknown CSL {csl_id}")


def get_priority(sla: dict[str, Any], priority_id: str) -> dict[str, Any]:
    for p in sla["priorities"]:
        if p["id"] == priority_id:
            return p
    raise KeyError(f"Unknown priority {priority_id}")


def at_risk_amount(sla: dict[str, Any], monthly_charges: float | None = None) -> float:
    c = sla["commercial"]
    charges = c["monthly_charges"] if monthly_charges is None else monthly_charges
    return charges * c["at_risk_pct"] / 100.0


# --------------------------------------------------------------------------- #
# Evaluating a measured value against a CSL
# --------------------------------------------------------------------------- #
@dataclass
class CSLResult:
    csl_id: str
    actual: float
    expected: float
    minimum: float
    status: str  # "met_expected" | "below_expected" | "below_minimum" | "deep_below_minimum"
    events: int | None = None
    misses: int | None = None
    note: str = ""

    @property
    def is_minimum_default(self) -> bool:
        return self.status in ("below_minimum", "deep_below_minimum")


def _meets(value: float, threshold: float, direction: str) -> bool:
    return value >= threshold if direction == HIGHER else value <= threshold


def evaluate_csl(
    sla: dict[str, Any],
    csl_id: str,
    actual: float,
    events: int | None = None,
    misses: int | None = None,
) -> CSLResult:
    """Classify a measured value for one CSL in one Measurement Period.

    ``events`` / ``misses`` enable the small-sample rule: with few incidents a
    single miss swings the percentage wildly, so the contract instead caps the
    number of allowed misses.
    """
    c = get_csl(sla, csl_id)
    exp, mn, d = c["expected"], c["minimum"], c["direction"]
    gap = abs(exp - mn)

    ssr = c.get("small_sample_rule")
    if ssr and events is not None and misses is not None and events < ssr["below_events"]:
        allowed = ssr["max_misses_before_minimum_default"]
        if misses == 0:
            status, note = "met_expected", f"Small-sample rule: {events} events, 0 misses."
        elif misses <= allowed:
            status, note = "below_expected", f"Small-sample rule: {misses} miss(es) within allowance of {allowed}."
        else:
            status, note = "below_minimum", f"Small-sample rule: {misses} misses exceeds allowance of {allowed}."
        return CSLResult(csl_id, actual, exp, mn, status, events, misses, note)

    if _meets(actual, exp, d):
        status = "met_expected"
    elif _meets(actual, mn, d):
        status = "below_expected"
    else:
        shortfall = (mn - actual) if d == HIGHER else (actual - mn)
        status = "deep_below_minimum" if shortfall > gap else "below_minimum"
    return CSLResult(csl_id, actual, exp, mn, status, events, misses)


# --------------------------------------------------------------------------- #
# Credits
# --------------------------------------------------------------------------- #
@dataclass
class CreditResult:
    csl_id: str
    at_risk_amount: float
    allocation_pct: float
    base_credit: float
    multiplier: int
    credit: float
    earnback_eligible: bool
    explanation: str


def compute_credit(
    sla: dict[str, Any],
    csl_id: str,
    consecutive_minimum_defaults: int = 1,
    monthly_charges: float | None = None,
    aggravators: Iterable[str] = (),
) -> CreditResult:
    """Service Level Credit for one Minimum Service Level Default.

    Credit = At-Risk Amount x CSL allocation %; doubled when the same CSL has
    defaulted for the configured number of consecutive periods.
    """
    c = get_csl(sla, csl_id)
    com = sla["commercial"]
    charges = com["monthly_charges"] if monthly_charges is None else monthly_charges
    ara = at_risk_amount(sla, charges)
    alloc = c["credit_allocation_pct"]
    base = ara * alloc / 100.0

    doubling = com["doubling"]
    mult = doubling["multiplier"] if consecutive_minimum_defaults >= doubling["consecutive_minimum_defaults"] else 1
    credit = base * mult

    ineligible_aggs = {"AGG-INTEGRITY", "AGG-EHS", "AGG-SECURITY"}
    earnback_ok = com["earnback"]["enabled"] and mult == 1 and not (set(aggravators) & ineligible_aggs)

    explanation = (
        f"At-Risk Amount ${ara:,.0f} ({com['at_risk_pct']}% of ${charges:,.0f}) "
        f"× {alloc}% allocation = ${base:,.0f}"
        + (f"; ×{mult} for {consecutive_minimum_defaults} consecutive defaults" if mult > 1 else "")
    )
    return CreditResult(csl_id, ara, alloc, base, mult, credit, earnback_ok, explanation)


def cap_monthly_credits(sla: dict[str, Any], credits: Iterable[CreditResult],
                        monthly_charges: float | None = None) -> tuple[float, float, bool]:
    """Apply the monthly cap. Returns (uncapped_total, payable_total, was_capped)."""
    total = sum(cr.credit for cr in credits)
    cap = at_risk_amount(sla, monthly_charges)
    return total, min(total, cap), total > cap


# --------------------------------------------------------------------------- #
# Internal breach severity
# --------------------------------------------------------------------------- #
@dataclass
class SeverityResult:
    level: str | None
    name: str | None
    escalation: str | None
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


def _levels(sla: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {lvl["id"]: lvl for lvl in sla["breach_severity"]["levels"]}


def _rank(sla: dict[str, Any], level: str | None) -> int:
    return 0 if level is None else _levels(sla)[level]["rank"]


def _level_for_rank(sla: dict[str, Any], rank: int) -> str | None:
    if rank <= 0:
        return None
    rank = min(rank, max(lvl["rank"] for lvl in _levels(sla).values()))
    for lid, lvl in _levels(sla).items():
        if lvl["rank"] == rank:
            return lid
    return None


def _band_level(bands: list[dict[str, Any]], value: float) -> str:
    for band in bands:
        if band["max"] is None or value <= band["max"]:
            return band["level"]
    return bands[-1]["level"]


def _apply_aggravators(sla: dict[str, Any], level: str | None, aggravators: Iterable[str],
                       reasons: list[str]) -> str | None:
    defs = {a["id"]: a for a in sla["breach_severity"]["aggravators"]}
    rank = _rank(sla, level)
    for agg_id in aggravators:
        agg = defs.get(agg_id)
        if agg is None:
            raise KeyError(f"Unknown aggravator {agg_id}")
        if agg["effect"] == "bump" and rank > 0:
            rank += agg["amount"]
            reasons.append(f"{agg_id}: +{agg['amount']} level ({agg['description'].rstrip('.')})")
        elif agg["effect"] == "floor":
            floor_rank = _rank(sla, agg["level"])
            if floor_rank > rank:
                rank = floor_rank
                reasons.append(f"{agg_id}: raised to at least {agg['level']} ({agg['description'].rstrip('.')})")
            else:
                reasons.append(f"{agg_id}: present; already at or above {agg['level']}")
    return _level_for_rank(sla, rank)


def _result(sla: dict[str, Any], level: str | None, reasons: list[str],
            metrics: dict[str, float]) -> SeverityResult:
    if level is None:
        return SeverityResult(None, None, None, reasons, metrics)
    lvl = _levels(sla)[level]
    return SeverityResult(level, lvl["name"], lvl["escalation"], reasons, metrics)


def classify_event_breach(
    sla: dict[str, Any],
    target_min: float,
    actual_min: float,
    gpus_affected: int,
    aggravators: Iterable[str] = (),
) -> SeverityResult:
    """Severity for a single time-based breach (e.g., one P1 restore that ran late).

    Severity = worst of (overrun %, GPU-hours lost beyond target), then aggravators.
    """
    aggravators = list(aggravators)
    if actual_min <= target_min:
        return _result(sla, None, ["Within target; no breach."], {"overrun_pct": 0.0, "gpu_hours_beyond_target": 0.0})

    dims = sla["breach_severity"]["event_dimensions"]
    overrun_pct = (actual_min - target_min) / target_min * 100.0
    gpu_hours = gpus_affected * (actual_min - target_min) / 60.0

    lvl_overrun = _band_level(dims["overrun_pct"]["bands"], overrun_pct)
    lvl_impact = _band_level(dims["gpu_hours_beyond_target"]["bands"], gpu_hours)
    reasons = [
        f"Overrun {overrun_pct:.0f}% past target → {lvl_overrun}",
        f"{gpu_hours:,.0f} GPU-hours lost beyond target ({gpus_affected} GPUs) → {lvl_impact}",
    ]
    level = lvl_overrun if _rank(sla, lvl_overrun) >= _rank(sla, lvl_impact) else lvl_impact
    level = _apply_aggravators(sla, level, aggravators, reasons)
    return _result(sla, level, reasons, {"overrun_pct": overrun_pct, "gpu_hours_beyond_target": gpu_hours})


def classify_period_breach(
    sla: dict[str, Any],
    csl_result: CSLResult,
    consecutive_minimum_defaults: int = 0,
    aggravators: Iterable[str] = (),
) -> SeverityResult:
    """Severity for a CSL measured over a period (weekly or monthly).

    ``consecutive_minimum_defaults`` includes the current period when it is a
    Minimum default (e.g., 3 means this is the third month in a row).
    """
    aggravators = list(aggravators)
    rules = {r["condition"]: r for r in sla["breach_severity"]["period_rules"]}
    status = csl_result.status
    chronic_n = sla["commercial"]["doubling"]["consecutive_minimum_defaults"]

    if csl_result.is_minimum_default and consecutive_minimum_defaults >= chronic_n:
        condition = "chronic"
    else:
        condition = status
    rule = rules[condition]
    reasons = [f"{csl_result.csl_id} actual {csl_result.actual:g} vs expected {csl_result.expected:g} / "
               f"minimum {csl_result.minimum:g}: {rule['description']}"]
    if csl_result.note:
        reasons.append(csl_result.note)
    # Aggravators only adjust an actual breach; they never create one.
    level = _apply_aggravators(sla, rule["level"], aggravators, reasons) if rule["level"] else None
    return _result(sla, level, reasons, {"actual": csl_result.actual})
