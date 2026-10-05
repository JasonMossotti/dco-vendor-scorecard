"""Landlord engine: detection, attribution, measurement, scorecard, and committed reports."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard.connectors import FileConnector
from scorecard.engine.evaluate import evaluate_landlord
from scorecard.engine.landlord import build_landlord_scorecard, measure_landlord, run_landlord
from scorecard.sla_model import PARTNER_FILES, cap_monthly_credits, load_sla

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def sla():
    return load_sla(PARTNER_FILES["landlord"])


@pytest.fixture(scope="module")
def result(sla):
    return run_landlord(sla, FileConnector(SAMPLE))


@pytest.fixture(scope="module")
def sc(sla, result):
    return build_landlord_scorecard(sla, result)


def test_every_planted_landlord_discrepancy_is_detected_with_no_false_positives(result):
    ev = evaluate_landlord(result.findings, SAMPLE)
    assert ev.detected == ev.planted == 8 and not ev.false_positives, (ev.missed, ev.false_positives)


def test_findings_do_not_depend_on_the_answer_key(sla, result, tmp_path):
    copy = tmp_path / "sample"
    shutil.copytree(SAMPLE, copy)
    shutil.rmtree(copy / "ground_truth")
    again = run_landlord(sla, FileConnector(copy))
    assert [(f.type, f.summary) for f in again.findings] == [(f.type, f.summary) for f in result.findings]


def test_every_finding_carries_evidence_and_sla_severity(result):
    for f in result.findings:
        assert f.severity in ("S1", "S2", "S3", "S4") and len(f.evidence) >= 2 and f.sla_refs and f.recommended_action


def test_facility_incidents_rebuilt_from_telemetry(result):
    classes = {i.fault_class for i in result.incidents}
    assert {"UTILITY", "OT-FC-CDU", "OT-FC-UPS", "OT-FC-PWR", "OT-FC-LEAK", "OT-FC-FIRE", "OT-FC-CHW", "OT-FC-AIR"} <= classes
    for i in result.incidents:
        assert i.restored is not None and i.restored > i.t0
        assert i.work_order is not None, f"every facility event has a Landlord work order ({i.unit})"


def test_attribution_follows_the_interface_agreement(result, sc):
    for i in result.incidents:
        if i.fault_class == "UTILITY":
            assert (i.owner, i.rule) == ("Utility", "FA-6")
        elif i.capacity_lost:
            continue
        else:
            assert (i.owner, i.rule) == ("Landlord", "FA-5"), "no rack capacity lost: a redundancy event"
    rack = [i for i in result.incidents if i.capacity_lost]
    assert rack and all((i.owner, i.rule) == ("Landlord", "FA-1") for i in rack)
    disagree = [r for r in sc["attribution"] if not r["agrees"]]
    assert len(disagree) == 1 and disagree[0]["claimed_owner"] == "IT Partner"


def test_measurement_reflects_the_telemetry(result):
    m = measure_landlord(result)
    assert m["OT-CSL-01"]["actual"] < 100.0, "the rack that lost both feeds counts against rack power availability"
    assert m["OT-CSL-02"]["actual"] < 100.0, "one busway feed was lost, so some racks ran on one feed"
    assert m["OT-KM-02"]["actual"] < 100.0, "the unloaded generator test does not count"
    assert m["OT-KM-05"]["actual"] == 1.0


def test_scorecard_contrasts_self_report_with_telemetry(sla, result, sc):
    assert all(r["vendor_reported"] >= r["expected"] for r in sc["csl"])
    assert sc["defaults"], "the telemetry shows Minimum defaults the Landlord did not report"
    assert sc["credits"]["payable"] <= sla["commercial"]["monthly_charges"] * sla["commercial"]["at_risk_pct"] / 100
    assert sc["credits"]["payable"] == pytest.approx(sum(i["credit"] for i in sc["credits"]["items"]))


def test_committed_landlord_reports_are_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_landlord.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_landlord_engine_on_unseen_months():
    sys.path.insert(0, str(ROOT / "scripts"))
    import run_landlord
    planted, detected, fps = run_landlord.robustness(3)
    assert detected == planted and fps == 0


# ------------------------------------------------------------------ cross-partner attribution (Interface Agreement FA-1, FA-3)
@pytest.fixture(scope="module")
def it_runs():
    from scorecard.builder import build_scorecard
    from scorecard.engine import run_engine
    it = load_sla()
    src = FileConnector(SAMPLE)
    on, off = run_engine(it, src), run_engine(it, src, attribution=False)
    return on, off, build_scorecard(it, on), build_scorecard(it, off)


def test_it_partner_clock_starts_at_the_landlords_handoff(it_runs, result):
    on, off, *_ = it_runs
    rack_event = next(i for i in result.incidents if i.capacity_lost)
    ticket = next(t for t in on.context.tickets if t["category"] == "rack_facility")
    assert on.context.telemetry_t0(ticket)[0] == rack_event.restored, "IT clock starts at the Landlord's handoff"
    assert off.context.telemetry_t0(ticket)[0] == rack_event.t0, "without attribution it would start at the power loss"


def test_attribution_keeps_the_landlords_outage_off_the_it_scorecard(it_runs):
    *_, with_attr, without = it_runs
    assert (with_attr["totals"]["defaults"], with_attr["credits"]["payable"]) == (4, 188700.0), \
        "the IT headline is unchanged by a Landlord-caused rack outage"
    assert without["totals"]["defaults"] > with_attr["totals"]["defaults"]
    assert without["credits"]["payable"] > with_attr["credits"]["payable"]
    rows = lambda sc: {c["id"]: c["actual"] for c in sc["csl"]}
    assert rows(without)["CSL-03"] < rows(with_attr)["CSL-03"]


def test_it_engine_is_unchanged_by_the_facility_event(it_runs):
    from scorecard.engine.evaluate import evaluate
    on, *_ = it_runs
    ev = evaluate(on.findings, SAMPLE)
    assert ev.detected == ev.planted and not ev.false_positives
    assert not any("rack_facility" == on.context.ticket_by_no[n]["category"] for f in on.findings for n in f.tickets)
