"""PM coverage (/ops/#pm): every Landlord device that needs PM, its last and next PM against the forward schedule,
findings PMC-# for gaps, and the coverage procedure in the Landlord SLA (section 11.1)."""

import filecmp
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from scorecard import pm_coverage as PC
from scorecard.synthetic import pm_coverage as G

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "data" / "pm_coverage"
sys.path.insert(0, str(ROOT / "scripts"))

import render_pm  # noqa: E402


@pytest.fixture(scope="module")
def r():
    return PC.analyse()


@pytest.fixture(scope="module")
def f(r):
    return PC.page_data(r)


def test_committed_layer_is_current(tmp_path):
    seed = json.loads((ROOT / "data" / "sample" / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    G.write_opening(G.OpeningRegister(seed).run(), tmp_path, seed)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(p.name for p in LAYER.iterdir())
    for n in names:
        assert filecmp.cmp(tmp_path / n, LAYER / n, shallow=False), f"data/pm_coverage/{n} is stale: run python scripts/generate_pm.py"


def test_report_is_current(f):
    assert (ROOT / "reports" / "pm_coverage.md").read_text(encoding="utf-8") == render_pm.markdown(f)


def test_every_device_the_schedule_covers_has_a_line(r):
    """Every Hall A, Hall B, and site-wide device of a covered kind has each of its kind's tasks; Hall C has none."""
    cfg, devs = PC.config(), PC.devices()
    keys = {ln["key"] for ln in r["lines"]}
    for t in cfg["tasks"]:
        for n, v in devs.items():
            if v.get("kind") in t.get("kinds", []):
                assert (f"{t['id']}|{n}" in keys) == (v.get("hall") != "Hall C"), (t["id"], n)
    assert len(r["lines"]) == 90 and len({ln["unit"] for ln in r["lines"]}) == 69


def test_every_schedule_line_is_in_the_program():
    sla = PC.yaml.safe_load(PC.SLA.read_text(encoding="utf-8"))["maintenance"]
    prog = {(t["system"], t["task"]) for t in PC.config()["tasks"]}
    for s in sla["schedule"]:
        if s["system"] == "Fire protection":
            assert any(sy == "Fire protection" for sy, _ in prog)
        else:
            assert (s["system"], s["task"]) in prog, s["task"]
    assert [s["id"] for s in sla["coverage"]["steps"]] == [f"PMC-S{i}" for i in range(1, 7)]


def test_agreements_hold(r):
    assert all(not a["misses"] for a in r["agreements"]), [a["misses"] for a in r["agreements"]]
    assert [a["checked"] for a in r["agreements"]] == [58, 34, 60]


def test_due_dates():
    cfg = PC.config()
    assert PC.next_due(date(2026, 9, 1), "monthly", cfg) == date(2026, 10, 31)
    assert PC.next_due(date(2026, 12, 15), "monthly", cfg) == date(2027, 1, 31)
    assert PC.next_due(date(2026, 6, 8), "quarterly", cfg) == date(2026, 9, 7)
    w = PC.walk(date(2026, 6, 22), "quarterly", [date(2026, 10, 26)], cfg)
    assert w["status"] == "booked_late" and w["limit"] == date(2026, 10, 5)
    assert PC.walk(date(2026, 9, 4), "monthly", [date(2026, 10, 14), date(2026, 11, 3)], cfg)["status"] == "booked"
    assert PC.walk(date(2026, 9, 4), "monthly", [], cfg)["status"] == "not_booked"
    assert PC.walk(date(2026, 9, 4), "monthly", [date(2026, 11, 20)], cfg)["status"] == "booked_late"


def test_findings_as_found_and_planted(r):
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert PC.score(r, key) == {"planted": 3, "found": 3, "as_found": 3, "as_found_hit": 3, "false_positives": 0}
    k = {ln: f["kind"] for f in r["findings"] for ln in f["lines"]}
    # From the records as they are: the Hall A CDU filters Jason kept as an observation, chillers with no booking in time
    assert k["cdu_filter|CDU-A1"] == "overdue" and k["cdu_filter|CDU-A2"] == "booked_late"
    assert k["chiller_pm|CH-04"] == k["chiller_pm|CH-11"] == "not_booked"
    assert sorted(f["task"] for f in r["findings"] if f["kind"] == "no_baseline") == sorted(
        t["task"] for t in PC.config()["tasks"] if t.get("in_schedule") is False)
    assert [f["id"] for f in r["findings"]] == [f"PMC-{i}" for i in range(1, 15)]


def test_load_bank_is_not_required(r):
    assert all(ln["status"] == "not_required" for ln in r["lines"] if ln["task_id"] == "gen_loadbank")


def test_records_and_bookings_are_read_never_written():
    """The coverage check reads the PM records and the schedule; data/pm_coverage is its only own layer."""
    man = json.loads((LAYER / "manifest.json").read_text(encoding="utf-8"))
    assert man["files"] == {"opening.csv": 72} and "answer key" in man["note"]


def test_device_cards(f):
    n = PC.device_notes(f)
    assert n["CDU-A1"][0][0].endswith("Overdue (PMC-2)") and n["CDU-A1"][0][1] == "cdu_filter|CDU-A1"
    assert len(n["GEN-1"]) == 4 and "TW-A1" in n and "CDU-C1" not in n


def test_robustness_small():
    assert render_pm.robustness(3) == 0
