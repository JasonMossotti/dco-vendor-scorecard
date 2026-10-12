"""Ownership trainer: one scenario per row of the ownership matrix, every answer read from the agreement."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard import tickets as T
from scorecard import trainer as TR
from scorecard.sla_model import load_interface_agreement

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def records():
    return T.build()["records"]


@pytest.fixture(scope="module")
def data(records):
    return TR.build(records)


def test_one_scenario_per_row_in_order(data):
    ia = load_interface_agreement()
    assert [s["component"] for s in data["scenarios"]] == [r["component"] for r in ia["raci"]]
    assert sorted(r["component"] for r in TR.load_config()["rows"]) == sorted(r["component"] for r in ia["raci"])


def test_answers_come_from_the_raci(data):
    ia = load_interface_agreement()
    for s, row in zip(data["scenarios"], ia["raci"]):
        assert s["raci"] == {p: row[p] for p in ia["raci_parties"]}
        assert s["A"] in [p for p in ia["raci_parties"] if "A" in row[p].split("/")]
        assert sorted(s["R"]) == sorted(p for p in ia["raci_parties"] if "R" in row[p].split("/"))
    for key in ("R", "A", "C", "I", "notifier", "minutes"):
        assert not any(key in r for r in TR.load_config()["rows"] if key != "notifier"), "answers are never configured"


def test_priority_criteria_are_quoted_from_the_contracts(data):
    for s in data["scenarios"]:
        if s["priority"]:
            assert s["criterion_source"], f"{s['component']}: criterion not found in the owning party's SLA"
            assert s["criterion_source"].endswith(s["priority"]) or s["criterion_source"].startswith("Interface Agreement")


def test_notification_follows_the_alarm_terms(data):
    by = {s["component"].split(" ")[0]: s for s in data["scenarios"]}
    for s in data["scenarios"]:
        if s["priority"] == "P1" and s["notifier"]:
            assert (s["rule"], s["minutes"]) == ("NT-1", 5)
        elif s["priority"] == "P2" and s["notifier"]:
            assert (s["rule"], s["minutes"]) == ("NT-2", 15)
        else:
            assert s["rule"] is None
    leak = next(s for s in data["scenarios"] if s["component"].startswith("Rack manifold"))
    assert (leak["R"], leak["A"], leak["notifier"]) == (["IT Partner"], "Customer", "IT Partner")
    assert by["138"]["A"] == "Utility" and by["138"]["notifier"] == "Landlord" and by["138"]["notifier_why"]


def test_scenarios_do_not_give_away_the_owner(data):
    for s in data["scenarios"]:
        assert not any(p in s["scenario"] for p in ("IT Partner", "Landlord", "OEM")), s["scenario"]


def test_every_sample_record_belongs_to_a_row(data, records):
    hit = {r["id"] for s in data["scenarios"] for r in s["records"]}
    assert {r["id"] for r in records} <= hit
    whip = next(s for s in data["scenarios"] if s["component"].startswith("Rack power shelves"))
    assert "WO-41043" in [r["id"] for r in whip["records"]] and [r["id"] for r in whip["rules"]] == ["FA-4"]


def test_trainer_page_builds_and_works(tmp_path):
    import render_agreements
    paths = render_agreements.write(tmp_path)
    page = tmp_path / "ownership-trainer" / "index.html"
    assert page in paths
    assert 'href="ownership-trainer/"' in (tmp_path / "index.html").read_text(encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "trainer_page.cjs", str(page)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
