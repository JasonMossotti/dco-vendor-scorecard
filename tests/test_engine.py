"""Tests for the discrepancy engine.

The claims in the README ("caught every planted discrepancy, no false alarms")
are only worth something if they are tested, including on months the engine
has never seen.
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

from scorecard.connectors import SOURCES, FileConnector
from scorecard.engine import run_engine
from scorecard.engine.evaluate import evaluate
from scorecard.engine.report import to_json, to_markdown
from scorecard.sla_model import load_sla
from scorecard.synthetic import SiteGenerator, write_dataset
from scorecard.synthetic.generator import VALIDATION_PLANS

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
INTEGRITY_TYPES = {"clock_shift", "ticket_split", "ghost_engagement", "skipped_validation", "unverified_swap"}


@pytest.fixture(scope="module")
def sla():
    return load_sla()


@pytest.fixture(scope="module")
def result(sla):
    return run_engine(sla, FileConnector(SAMPLE))


# ------------------------------------------------------- answer-key isolation
def test_connector_cannot_reach_ground_truth():
    assert not any("ground_truth" in p for p in SOURCES.values())
    conn = FileConnector(SAMPLE)
    with pytest.raises(KeyError):
        conn.get("planted_discrepancies")
    with pytest.raises(PermissionError):
        conn.read_path("ground_truth/planted_discrepancies.json")


def test_engine_identical_without_ground_truth(sla, result, tmp_path):
    """Delete the answer key entirely: the findings must not change."""
    copy = tmp_path / "sample"
    shutil.copytree(SAMPLE, copy)
    shutil.rmtree(copy / "ground_truth")
    again = run_engine(sla, FileConnector(copy))
    assert [(f.id, f.type, f.tickets) for f in again.findings] == [(f.id, f.type, f.tickets) for f in result.findings]


# ------------------------------------------------------------------ accuracy
def test_sample_detects_everything_with_no_false_positives(result):
    e = evaluate(result.findings, SAMPLE)
    assert e.detected == e.planted
    assert e.false_positives == []


def test_robust_on_unseen_months(sla, tmp_path):
    """Fresh months the engine was not tuned on (seeds differ from the committed sample)."""
    cfg = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    for seed in (101, 202, 303, 404, 505, 606):
        out = tmp_path / f"seed{seed}"
        write_dataset(SiteGenerator(sla, cfg, start=date(2026, 8, 31), seed=seed).run(), out)
        e = evaluate(run_engine(sla, FileConnector(out)).findings, out)
        assert e.detected == e.planted, (seed, [p["type"] for p in e.missed])
        assert not e.false_positives, (seed, [f.summary for f in e.false_positives])


# ---------------------------------------------------------- severity policy
def test_record_integrity_findings_are_s1(result):
    for f in result.findings:
        if f.type in INTEGRITY_TYPES:
            assert f.severity == "S1", f.id


def test_repeat_findings_escalate_one_level(result):
    for f in result.findings:
        if f.type in ("phantom_fix", "wrong_end_optic"):
            assert f.severity == "S2"


def test_ticket_split_breaches_target(result):
    for f in result.findings:
        if f.type == "ticket_split":
            assert f.metrics["measured_restore_min"] > f.metrics["target_min"]


# ---------------------------------------------------------- evidence quality
def test_every_finding_is_actionable(result):
    for f in result.findings:
        assert len(f.evidence) >= 2, f.id
        assert all(e["source"] in SOURCES.values() for e in f.evidence), f.id
        assert f.recommended_action and f.sla_refs and f.severity, f.id


def test_ids_are_sequential_and_sorted_by_severity(result):
    assert [f.id for f in result.findings] == [f"F-{n:03d}" for n in range(1, len(result.findings) + 1)]
    ranks = [int(f.severity[1]) for f in result.findings]
    assert ranks == sorted(ranks)


# ------------------------------------------------- single source of truth
def test_generator_validation_names_match_sla_check_ids(sla):
    sla_ids = {c["component"]: c["check_ids"] for c in sla["rts_validation"]["classes"]}
    mapping = {"tray": "Compute tray", "switch_tray": "NVLink switch tray", "optic": "Optic, cable, or fiber",
               "psu": "Power shelf or PSU", "power_shelf": "Power shelf or PSU",
               "cdu": "CDU component (pump, filter, sensor)", "rack_manifold": "Rack manifold"}
    for plan, component in mapping.items():
        assert {c for c, _ in VALIDATION_PLANS[plan]} == set(sla_ids[component]), plan


# --------------------------------------------------------------- reports
def test_committed_reports_are_current(result):
    e = evaluate(result.findings, SAMPLE)
    js = json.dumps(to_json(result, e), indent=2, sort_keys=True) + "\n"
    assert (ROOT / "reports" / "findings.json").read_text(encoding="utf-8") == js, "run scripts/run_engine.py"
    assert (ROOT / "reports" / "discrepancy_report.md").read_text(encoding="utf-8") == to_markdown(result, e)


def test_cli_runs(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_engine.py"), "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = re.search(r"detected (\d+)/(\d+), 0 false positives", r.stdout)
    assert m and m.group(1) == m.group(2), r.stdout
