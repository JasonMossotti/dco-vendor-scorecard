"""Weekly Operations Review: the weeks reconcile with the month, nothing is known early, and the notes match the facts."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scorecard.builder import build_scorecard
from scorecard.engine.landlord import build_landlord_scorecard
from scorecard.weekly import WeeklyData, build_all, knowable_at

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def data():
    return WeeklyData(SAMPLE)


@pytest.fixture(scope="module")
def weeks(data):
    return build_all(data)


@pytest.fixture(scope="module")
def notes():
    return {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "weekly" / "notes").glob("*.yaml"))}


def test_weeks_cover_the_window_without_gaps(data, weeks):
    assert weeks[0]["start"].startswith(data.window_start.strftime("%Y-%m-%d"))
    assert weeks[-1]["end"].startswith(data.window_end.strftime("%Y-%m-%d"))
    for a, b in zip(weeks, weeks[1:]):
        assert a["end"] == b["start"]
    assert [w["id"] for w in weeks] == ["2026-W36", "2026-W37", "2026-W38", "2026-W39"]


def test_every_finding_is_raised_exactly_once_in_the_week_it_was_observed(data, weeks):
    raised = [f["id"] for w in weeks for f in w["findings"]["new"]]
    every = {f.id: f for f in data.it.findings + data.ll.findings}
    assert sorted(raised) == sorted(every)
    for w in weeks:
        for f in w["findings"]["new"]:
            assert w["start"] <= f["known"] < w["end"], f["id"]
            assert knowable_at(every[f["id"]]) == every[f["id"]].observed_at
    assert weeks[-1]["findings"]["awaiting_monthly_review"] == len(every)


def test_corroborating_evidence_never_delays_a_finding(data):
    """F-007 carries later corroboration (GPU telemetry or an RMA shipment); it is still raised when observed."""
    f = next(f for f in data.it.findings if f.id == "F-007")
    later = [e["at"] for e in f.evidence if e.get("at") and e["at"] > f.observed_at]
    assert later and knowable_at(f) == f.observed_at


def test_month_to_date_at_the_last_week_matches_the_monthly_scorecards(data, weeks):
    it_month = {r["id"]: r for r in build_scorecard(data.it_sla, data.it)["csl"]}
    ll_month = {r["id"]: r for r in build_landlord_scorecard(data.ll_sla, data.ll)["csl"]}
    it_last, ll_last = weeks[-1]["partners"]
    for r in it_last["levels"]:
        assert r["mtd_status"] == it_month[r["id"]]["status"], r["id"]
        assert r["mtd"] == pytest.approx(it_month[r["id"]]["actual"]), r["id"]
    for r in ll_last["levels"]:
        want = ll_month[r["id"]]["status"]
        assert r["mtd_status"] == ("no_events" if want == "not_applicable" else want), r["id"]
        if ll_month[r["id"]]["actual"] is not None:
            assert r["mtd"] == pytest.approx(ll_month[r["id"]]["actual"]), r["id"]


def test_weekly_power_availability_averages_to_the_month(data, weeks):
    """Equal-length weeks of rack-minutes: the weekly figures must average exactly to the monthly one."""
    month = next(r for r in build_landlord_scorecard(data.ll_sla, data.ll)["csl"] if r["id"] == "OT-CSL-01")["actual"]
    weekly = [next(r for r in w["partners"][1]["levels"] if r["id"] == "OT-CSL-01")["week"] for w in weeks]
    assert sum(weekly) / len(weekly) == pytest.approx(month, abs=1e-9)


def test_incidents_add_up_to_the_month(data, weeks):
    p1 = sorted(k for w in weeks for r in w["incidents"]["it"]["p1"] for k in r["tickets"])
    assert p1 == sorted(k for i in data.it_incidents if i.priority == "P1" for k in i.tickets)
    assert sum(w["incidents"]["it"]["p2_count"] for w in weeks) == sum(1 for i in data.it_incidents if i.priority == "P2")
    ll = sum(len(w["incidents"]["landlord"]) for w in weeks)
    assert ll == sum(1 for i in data.ll.incidents if i.priority in ("P1", "P2"))


def test_the_rack_a07_outage_links_to_its_review(weeks):
    w = next(w for w in weeks if w["id"] == "2026-W38")
    it = next(r for r in w["incidents"]["it"]["p1"] if "INC3900001" in r["tickets"])
    ll = next(r for r in w["incidents"]["landlord"] if r["work_order"] == "WO-41023")
    assert it["pir"]["id"] == ll["pir"]["id"] == "PIR-2026-001"
    assert it["facility_caused"] and ll["owner"] == "Landlord"


def test_lookahead_only_shows_what_was_known_by_the_end_of_the_week(data, weeks):
    mops = {m["mop_id"]: m for m in data.ll.context.mops}
    for w in weeks:
        la = w["lookahead"]
        for m in la["mops"]:
            src = mops[m["id"]]
            assert m["approved_at"] < w["end"] <= m["window_start"] < la["to"], m["id"]
            assert src["title"] == m["title"]
        hidden = [x for x in data.ll.context.mops if x["approved_at"].strftime("%Y-%m-%dT%H:%M:%SZ") >= w["end"]]
        assert not {x["mop_id"] for x in hidden} & {m["id"] for m in la["mops"]}
        for p in la["maintenance"]:
            assert p["due_start"] < la["to"] and p["due_end"] > w["end"]


def test_actions_appear_only_after_the_review_meeting(weeks):
    by = {w["id"]: w for w in weeks}
    assert by["2026-W37"]["actions"] == [] and len(by["2026-W38"]["actions"]) == 7
    assert not any(a["overdue"] for w in weeks for a in w["actions"])


def test_notes_only_reference_what_the_week_contains(weeks, notes):
    by = {w["id"]: w for w in weeks}
    for wid, n in notes.items():
        assert n["week"] == wid and wid in by
        w = by[wid]
        facts = repr(w)
        text = yaml.safe_dump(n)
        for ref in set(re.findall(r"\b(?:F|L)-\d{3}\b|\bA\d\b|\bMOP-\d{3}\b|\bWO-\d{5}\b|\bPIR-\d{4}-\d{3}\b|\b[AB]\d{2}\b|\bPM-\d{4}\b", text)):
            assert ref in facts, f"{wid} notes mention {ref}, which is not in that week's facts"
        for role, comment in n["commentary"].items():
            partner = next(p for p in w["partners"] if p["role"] == role)
            for csl in re.findall(r"\b(?:OT-)?CSL-\d{2}\b", comment):
                assert any(r.startswith(csl + " ") for r in partner["reasons"]), f"{csl} is not below Minimum or at risk for {role}"
        for p in n["priorities"]:                   # a priority's service level must be one flagged for that partner
            partner = next(x for x in w["partners"] if x["role"] == p["to"])
            for csl in re.findall(r"\b(?:OT-)?CSL-\d{2}\b", p["text"]):
                assert any(r.startswith(csl + " ") for r in partner["reasons"]), f"{csl} is not flagged for {p['to']}"
        for a in n["asks"]:
            assert a["due"] >= n["meeting"]
        assert n["meeting"] >= w["end"][:10], "the meeting is held after the week it reviews"


def test_notes_are_blameless(notes):
    for n in notes.values():
        assert not re.search(r"\b(RSS|CCF)-[A-Z]?\d+", yaml.safe_dump(n)), "notes name an individual"


def test_markdown_packs_are_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_weekly.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_weekly_page_builds_and_works(tmp_path):
    import render_weekly
    out = tmp_path / "weekly.html"
    out.write_text(render_weekly.html_page(), encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "weekly_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
