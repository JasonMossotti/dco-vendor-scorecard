"""Tests for the SLA model and the generated SLA document.

Run with:  pytest -q
"""

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard.sla_model import (
    SLAValidationError,
    cap_monthly_credits,
    classify_event_breach,
    classify_period_breach,
    compute_credit,
    evaluate_csl,
    load_sla,
    validate_sla,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sla():
    return load_sla()


# ----------------------------------------------------------------- validation
def test_shipped_sla_is_valid(sla):
    assert validate_sla(sla) == []


def test_allocations_fit_pool(sla):
    total = sum(c["credit_allocation_pct"] for c in sla["critical_service_levels"])
    assert total <= sla["commercial"]["pool_pct"]


def test_validation_catches_inverted_thresholds(sla):
    bad = copy.deepcopy(sla)
    bad["critical_service_levels"][0]["expected"] = 90.0  # below its minimum of 99.0
    assert any("must be >= minimum" in e for e in validate_sla(bad))


def test_validation_catches_pool_overflow(sla):
    bad = copy.deepcopy(sla)
    bad["critical_service_levels"][0]["credit_allocation_pct"] = 400
    errors = validate_sla(bad)
    assert any("exceeds pool" in e for e in errors)
    assert any("exceeds per-CSL cap" in e for e in errors)


def test_validation_catches_unknown_data_source(sla):
    bad = copy.deepcopy(sla)
    bad["critical_service_levels"][0]["data_sources"].append("DS-NOPE")
    assert any("unknown data source" in e for e in validate_sla(bad))


def test_validation_catches_bad_measurement_spec(sla):
    bad = copy.deepcopy(sla)
    bad["measurement_spec"][0]["validation_class"] = ["Not a real checklist"]
    bad["measurement_spec"][1]["stability_window_hours"] = 0.5      # shorter than the early-failure window
    bad["measurement_spec"][2]["detection"]["source"] = "DS-NOPE"
    errors = validate_sla(bad)
    assert any("not in Return-to-Service Validation" in e for e in errors)
    assert any("longer than the early-failure window" in e for e in errors)
    assert any("unknown detection source" in e for e in errors)


def test_every_fault_class_has_a_validation_checklist(sla):
    rts = {c["component"] for c in sla["rts_validation"]["classes"]}
    for fc in sla["measurement_spec"]:
        assert set(fc["validation_class"]) <= rts


def test_load_refuses_invalid_file(tmp_path, sla):
    import yaml

    bad = copy.deepcopy(sla)
    bad["priorities"][0]["restore_min"] = 99999  # P1 slower than P4
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(bad))
    with pytest.raises(SLAValidationError):
        load_sla(path)


# ------------------------------------------------------------- CSL evaluation
@pytest.mark.parametrize(
    "csl, actual, expected_status",
    [
        ("CSL-01", 99.7, "met_expected"),
        ("CSL-01", 99.3, "below_expected"),
        ("CSL-01", 98.8, "below_minimum"),
        ("CSL-01", 98.2, "deep_below_minimum"),
        ("CSL-08", 2.0, "met_expected"),       # lower is better
        ("CSL-08", 4.0, "below_expected"),
        ("CSL-08", 6.0, "below_minimum"),
        ("CSL-08", 8.0, "deep_below_minimum"),
    ],
)
def test_evaluate_csl(sla, csl, actual, expected_status):
    assert evaluate_csl(sla, csl, actual).status == expected_status


def test_small_sample_rule_p1_engaged(sla):
    # 10 P1s, 1 missed = 90% (would look "deep below minimum"), but the
    # small-sample rule decides: 0 misses allowed -> plain Minimum default.
    r = evaluate_csl(sla, "CSL-02", 90.0, events=10, misses=1)
    assert r.status == "below_minimum"
    assert "Small-sample" in r.note


def test_small_sample_rule_allows_one_miss_for_p1_restore(sla):
    r = evaluate_csl(sla, "CSL-03", 87.5, events=8, misses=1)
    assert r.status == "below_expected"


# -------------------------------------------------------------------- credits
def test_single_credit(sla):
    r = compute_credit(sla, "CSL-03", 1)
    assert r.at_risk_amount == pytest.approx(222_000)
    assert r.credit == pytest.approx(66_600)
    assert r.earnback_eligible


def test_doubled_credit_after_three_consecutive(sla):
    r = compute_credit(sla, "CSL-03", 3)
    assert r.credit == pytest.approx(133_200)
    assert not r.earnback_eligible


def test_integrity_default_not_earnback_eligible(sla):
    assert not compute_credit(sla, "CSL-11", 1, aggravators=["AGG-INTEGRITY"]).earnback_eligible


def test_monthly_cap(sla):
    credits = [compute_credit(sla, c, 1) for c in ("CSL-01", "CSL-03", "CSL-06", "CSL-07", "CSL-11")]
    uncapped, payable, capped = cap_monthly_credits(sla, credits)
    assert uncapped == pytest.approx(288_600)
    assert payable == pytest.approx(222_000)
    assert capped


# ------------------------------------------------------------------- severity
def test_no_breach_within_target(sla):
    assert classify_event_breach(sla, 240, 200, 72).level is None


def test_small_overrun_small_unit_is_watch(sla):
    assert classify_event_breach(sla, 480, 520, 4).level == "S4"


def test_rack_four_hours_late_is_major(sla):
    r = classify_event_breach(sla, 240, 480, 72)
    assert r.level == "S2"
    assert r.metrics["gpu_hours_beyond_target"] == pytest.approx(288)


def test_impact_dimension_can_dominate(sla):
    # Only 25% late (S3 by overrun) but a whole CDU loop: 576 GPUs x 1 hr = 576 GPU-h -> S2
    assert classify_event_breach(sla, 240, 300, 576).level == "S2"


def test_repeat_bumps_one_level(sla):
    assert classify_event_breach(sla, 480, 720, 4, ["AGG-REPEAT"]).level == "S2"


def test_bump_never_exceeds_s1(sla):
    assert classify_event_breach(sla, 240, 1200, 576, ["AGG-REPEAT"]).level == "S1"


def test_integrity_floors_to_s1(sla):
    assert classify_event_breach(sla, 480, 500, 4, ["AGG-INTEGRITY"]).level == "S1"


def test_aggravator_never_creates_a_breach(sla):
    met = evaluate_csl(sla, "CSL-01", 99.9)
    assert classify_period_breach(sla, met, 0, ["AGG-INTEGRITY"]).level is None


def test_chronic_period_breach_is_s1(sla):
    r = evaluate_csl(sla, "CSL-10", 94.0)
    assert classify_period_breach(sla, r, consecutive_minimum_defaults=3).level == "S1"


def test_unknown_aggravator_raises(sla):
    with pytest.raises(KeyError):
        classify_event_breach(sla, 240, 480, 72, ["AGG-MADE-UP"])


# ------------------------------------------------------------------ document
def test_generated_document_is_current():
    """Fails if someone edited the YAML without regenerating docs/SLA.md."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "render_sla.py"), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_document_mentions_every_service_level(sla):
    text = (ROOT / "docs" / "SLA.md").read_text(encoding="utf-8")
    for item in sla["critical_service_levels"] + sla["key_measurements"] + sla["measurement_spec"]:
        assert item["id"] in text
    for rule in sla["ticket_handling"]["stability"]["rules"]:
        assert rule["id"] in text
