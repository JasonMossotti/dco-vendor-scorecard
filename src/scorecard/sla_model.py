"""SLA model: load the machine-readable SLA, validate it, and apply its rules.

Everything the scorecard needs to judge vendor performance comes from a
partner SLA file (sla/it_partner.yaml) merged onto the terms every partner
shares (sla/common.yaml). This module turns those files into answers:

* ``load_sla`` / ``validate_sla``: read and merge the files, refuse to run on a broken SLA.
* ``merge_terms``: add-only merge; a partner file can never override a common term.
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

SLA_DIR = Path(__file__).resolve().parents[2] / "sla"
DEFAULT_SLA_PATH = SLA_DIR / "it_partner.yaml"
PROVENANCE_KEYS = ("extends", "common_version")   # describe the files, not the contract

HIGHER = "higher_is_better"
LOWER = "lower_is_better"


class SLAValidationError(ValueError):
    """Raised when the SLA file is internally inconsistent."""


class SLAMergeError(SLAValidationError):
    """Raised when a partner file tries to set a term the common file already sets."""


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #
def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def merge_terms(common: dict[str, Any], partner: dict[str, Any], where: str = "") -> dict[str, Any]:
    """Add the partner's terms to the common terms.

    Dictionaries merge key by key. Any other value set in both files is an
    error: a partner contract may add terms but may never replace or weaken a
    site-wide one. Neither input is modified.
    """
    out = dict(common)
    for key, value in partner.items():
        path = f"{where}.{key}" if where else key
        if key not in out:
            out[key] = value
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = merge_terms(out[key], value, path)
        else:
            raise SLAMergeError(f"'{path}' is set in both the common terms and the partner SLA; "
                                "a partner SLA may add terms but not override common ones")
    return out


def sla_sources(path: str | Path = DEFAULT_SLA_PATH) -> dict[str, str]:
    """File names and versions behind a partner SLA, for the rendered document's footer."""
    path = Path(path)
    partner = _read_yaml(path)
    out = {"partner": path.name}
    if partner.get("extends"):
        common = _read_yaml(path.parent / partner["extends"])
        out.update(common=partner["extends"], common_version=str(common.get("common_version", "")))
    return out


def load_sla(path: str | Path = DEFAULT_SLA_PATH, validate: bool = True) -> dict[str, Any]:
    """Load a partner SLA merged onto the common terms. Validates by default and raises on any problem."""
    path = Path(path)
    sla = _read_yaml(path)
    if sla.get("extends"):
        common = _read_yaml(path.parent / sla["extends"])
        sla = merge_terms({k: v for k, v in common.items() if k not in PROVENANCE_KEYS},
                          {k: v for k, v in sla.items() if k not in PROVENANCE_KEYS})
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
    agg_ids = {a["id"] for a in sev.get("aggravators", [])}
    for ft in sev.get("finding_types", []):
        if ft["base_level"] not in level_ids:
            errors.append(f"Finding type {ft['id']}: unknown base level {ft['base_level']}")
        for a in ft["aggravators"]:
            if a not in agg_ids:
                errors.append(f"Finding type {ft['id']}: unknown aggravator {a}")
    for c in sla.get("rts_validation", {}).get("classes", []):
        if not c.get("check_ids"):
            errors.append(f"Validation class '{c['component']}' needs check_ids")
    for agg in sev.get("aggravators", []):
        if agg["effect"] == "floor" and agg.get("level") not in level_ids:
            errors.append(f"Aggravator {agg['id']}: unknown floor level")
        if agg["effect"] not in ("floor", "bump"):
            errors.append(f"Aggravator {agg['id']}: effect must be 'floor' or 'bump'")

    errors += _validate_ehs(sla)
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
# EHS credits (site-wide terms; outside the monthly cap, never earned back)
# --------------------------------------------------------------------------- #
def _validate_ehs(sla: dict[str, Any]) -> list[str]:
    ehs = sla.get("ehs")
    if ehs is None:
        return ["ehs: missing (every partner SLA must carry the site EHS terms)"]
    errors: list[str] = []
    standards = {x["id"] for x in ehs["standards"]}
    for rule in ehs["site_rules"]:
        for ref in rule["refs"]:
            if ref not in standards:
                errors.append(f"ehs.site_rules.{rule['id']}: unknown standard '{ref}'")
    classes = {c["id"]: c for c in ehs["violation_classes"]}
    for c in classes.values():
        if c["credit_pct_of_monthly_charges"] < 0:
            errors.append(f"ehs.{c['id']}: credit cannot be negative")
        if not c["examples"]:
            errors.append(f"ehs.{c['id']}: a class needs examples so investigators classify consistently")
    pcts = [c["credit_pct_of_monthly_charges"] for c in ehs["violation_classes"]]
    if pcts != sorted(pcts, reverse=True):
        errors.append("ehs.violation_classes: listed most to least severe, credits must not increase")
    cr = ehs["credits"]
    if cr["repeat"]["class"] not in classes:
        errors.append(f"ehs.credits.repeat: unknown class {cr['repeat']['class']}")
    if not 0 <= cr["self_reported_reduction_pct"] < 100:
        errors.append("ehs.credits.self_reported_reduction_pct must be at least 0 and below 100")
    if cr["earnback_eligible"]:
        errors.append("ehs.credits.earnback_eligible must be false: EHS credits are never earned back")
    if not cr["outside_monthly_cap"]:
        errors.append("ehs.credits.outside_monthly_cap must be true: a bad service month must not make a safety violation free")
    return errors


@dataclass
class EHSCredit:
    """One confirmed violation and the EHS Credit it carries."""

    violation_id: str
    violation_class: str
    confirmed: str                      # ISO date the investigation confirmed it
    base: float
    amount: float
    adjustments: list[str] = field(default_factory=list)
    record_integrity_finding: bool = False


def compute_ehs_credits(sla: dict[str, Any], violations: Iterable[dict[str, Any]],
                        monthly_charges: float | None = None) -> list[EHSCredit]:
    """EHS Credits for independently confirmed violations.

    Each violation: ``{"id", "class", "confirmed" (YYYY-MM-DD), "self_reported", "concealed"}``.
    Order of adjustments: repeat multiplier, then self-report reduction or
    concealment multiplier. Unconfirmed allegations never reach this function.
    These credits are never passed through ``cap_monthly_credits``.
    """
    from datetime import date

    ehs = sla["ehs"]
    cr = ehs["credits"]
    classes = {c["id"]: c for c in ehs["violation_classes"]}
    charges = sla["commercial"]["monthly_charges"] if monthly_charges is None else monthly_charges
    out: list[EHSCredit] = []
    history: list[date] = []
    for v in sorted(violations, key=lambda x: x["confirmed"]):
        if v.get("self_reported") and v.get("concealed"):
            raise ValueError(f"{v['id']}: a violation cannot be both self-reported and concealed")
        cls = classes[v["class"]]
        when = date.fromisoformat(v["confirmed"])
        base = charges * cls["credit_pct_of_monthly_charges"] / 100
        amount, notes = base, []
        rep = cr["repeat"]
        if v["class"] == rep["class"]:
            if any(0 <= (when - d).days <= rep["window_days"] for d in history):
                amount *= rep["multiplier"]
                notes.append(f"repeat within {rep['window_days']} days: x{rep['multiplier']}")
            history.append(when)
        if v.get("self_reported") and amount:
            amount *= 1 - cr["self_reported_reduction_pct"] / 100
            notes.append(f"self-reported and corrected: -{cr['self_reported_reduction_pct']}%")
        if v.get("concealed"):
            amount *= cr["concealment_multiplier"]
            notes.append(f"concealed: x{cr['concealment_multiplier']}")
        out.append(EHSCredit(v["id"], v["class"], v["confirmed"], base, amount, notes,
                             bool(v.get("concealed")) and cr["concealment_is_record_integrity_finding"]))
    return out


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


def finding_type(sla: dict[str, Any], type_id: str) -> dict[str, Any]:
    for ft in sla["breach_severity"]["finding_types"]:
        if ft["id"] == type_id:
            return ft
    raise KeyError(f"Unknown finding type {type_id}")


def classify_finding(
    sla: dict[str, Any],
    type_id: str,
    target_min: float | None = None,
    actual_min: float | None = None,
    gpus_affected: int = 0,
    extra_aggravators: Iterable[str] = (),
) -> SeverityResult:
    """Severity for a discrepancy finding.

    If the finding carries a time breach (actual beyond target), severity starts
    from the event-breach dimensions; otherwise from the type's base level. The
    type's aggravators (plus any extras) are then applied.
    """
    ft = finding_type(sla, type_id)
    aggs = list(dict.fromkeys(list(ft["aggravators"]) + list(extra_aggravators)))
    if target_min is not None and actual_min is not None and actual_min > target_min:
        res = classify_event_breach(sla, target_min, actual_min, gpus_affected)
        base = res.level if _rank(sla, res.level) >= _rank(sla, ft["base_level"]) else ft["base_level"]
        reasons = res.reasons + [f"Base level for {ft['name'].lower()}: {ft['base_level']}"]
        metrics = res.metrics
    else:
        base, reasons, metrics = ft["base_level"], [f"Base level for {ft['name'].lower()}: {ft['base_level']}"], {}
    level = _apply_aggravators(sla, base, aggs, reasons)
    return _result(sla, level, reasons, metrics)
