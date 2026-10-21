"""Quarterly business review (/app/#qbr): one pack per partner for the quarter's three months, each month's column the
published scorecard, the multi-month rules applied as an adjustment line, and the review's notes tested against the facts."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scorecard import qbr as Q
from scorecard import scorecards_page as SP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_qbr  # noqa: E402

NUM = re.compile(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w-])")


@pytest.fixture(scope="module")
def q():
    return Q.page_data()


def test_report_is_current(q):
    assert (ROOT / "reports" / "qbr.md").read_text(encoding="utf-8") == render_qbr.markdown(q)


def test_earlier_months_are_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_quarter.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_three_four_week_months_ending_with_the_sample(q):
    assert [m["start"] for m in q["months"]] == ["2026-07-06", "2026-08-03", "2026-08-31"]
    assert [m["end"] for m in q["months"]] == ["2026-08-02", "2026-08-30", "2026-09-27"]
    assert [m["sample"] for m in q["months"]] == [False, False, True]
    assert list(q["packs"]) == ["it", "landlord", "security"]


def test_september_column_is_the_published_scorecard(q):
    views = {"it": SP.it_view(Q.SAMPLE), "landlord": SP.landlord_view(Q.SAMPLE), "security": SP.security_view(Q.SAMPLE)}
    for k, p in q["packs"].items():
        pub = {r["row"]["ID"]: r for r in views[k]["csl"]}
        assert [lv["id"] for lv in p["levels"]] == list(pub)
        for lv in p["levels"]:
            m = lv["months"][-1]
            assert m["measured"] == pub[lv["id"]]["row"]["Measured"] and m["actual"] == pub[lv["id"]]["actual"]
        assert p["credits"]["months"][-1]["payable"] == views[k]["credits"]["payable"]


def test_headline_and_the_rules(q):
    assert Q.check(q) == []
    it, ll, sec = (q["packs"][k] for k in ("it", "landlord", "security"))
    assert [m["payable"] for m in it["credits"]["months"]] == [144300, 144300, 188700]        # September stays $188,700
    assert (it["credits"]["quarter_payable"], it["credits"]["quarter_adjusted"]) == (477300, 510600)
    assert (ll["credits"]["quarter_payable"], ll["credits"]["quarter_adjusted"]) == (224200, 236000)
    assert (sec["credits"]["quarter_payable"], sec["credits"]["quarter_adjusted"]) == (31248, 37944)
    assert [x["csl"] for x in it["chronic"]["cf1"]] == ["CSL-07", "CSL-08", "CSL-11"]
    assert [x["csl"] for x in ll["chronic"]["cf1"]] == ["OT-CSL-06"] and [x["csl"] for x in sec["chronic"]["cf1"]] == ["SEC-CSL-06"]
    a = it["credits"]["adjustments"][0]
    assert a["month"] == "2026-09" and a["capped"] and a["payable"] == it["credits"]["at_risk"] == 222000 and a["adjustment"] == 33300
    states = {(e["month"], e["csl"]): e["state"] for e in it["earnback"]}
    assert states[("2026-07", "CSL-07")] == "lost" and states[("2026-07", "CSL-11")] == "ineligible"
    assert states[("2026-09", "CSL-07")] == "ineligible" and states[("2026-09", "CSL-09")] == "pending"
    assert q["roadmap"]["hall_b"]["on_time"] == 10 and q["roadmap"]["hall_c"]["forecast"] == "2026-11-23"


def test_earlier_months_have_no_hall_b_racks_due(q):
    for m in q["packs"]["it"]["levels"]:
        if m["id"] == "CSL-09":
            assert [x["actual"] for x in m["months"][:2]] == [None, None]


def test_proposals_follow_the_rule(q):
    rule = q["rule"]
    for p in q["packs"].values():
        got = {(x["csl"], x["rule"]) for x in p["proposals"]}
        for lv in p["levels"]:
            st = [m["status"] for m in lv["months"]]
            assert ((lv["id"], "corrective_action_plan") in got) == (sum(s in Q.DEFAULT for s in st) >= rule["cap_min_defaults"])
            sr = next(s for s in p["self_report"] if s["id"] == lv["id"])
            assert ((lv["id"], "review_measure") in got) == all(c["overstated"] for c in sr["months"])
            if (lv["id"], "tighten") in got:
                assert all(s == "met_expected" for s in st)


def test_notes_match_the_facts(q):
    notes = q["notes"]
    assert notes["quarter"] == q["quarter"] and notes["meeting"] > q["months"][-1]["end"], "the review is held after the quarter"
    facts = repr(q) + render_qbr.markdown(q)
    known = {n.replace(",", "") for n in NUM.findall(facts)}
    said = [(n["partner"], n["csl"], n["rule"]) for n in notes["proposals"]]
    assert len(said) == len(set(said))
    assert set(said) == {(k, x["csl"], x["rule"]) for k, p in q["packs"].items() for x in p["proposals"]}, "one note per proposal"
    texts = [(k, t) for k, t in notes["summary"].items()] + [(n["partner"], n["text"]) for n in notes["proposals"]] + [(None, t) for t in notes["lessons"]]
    for k, text in texts:
        for csl in Q.CODE.findall(text):
            assert any(lv["id"] == csl for lv in q["packs"][k]["levels"]), f"{csl} is not one of {k}'s service levels"
        for num in NUM.findall(text):
            assert num.replace(",", "") in known, f"{num} is not in the quarter's facts"
    for k, text in notes["summary"].items():                  # a service level named below Minimum was below Minimum
        p = q["packs"][k]
        for csl in Q.CODE.findall(text):
            assert next(lv for lv in p["levels"] if lv["id"] == csl)["defaults"] >= 1


def test_notes_are_blameless():
    for f in (ROOT / "qbr" / "notes").glob("*.yaml"):
        assert not re.search(r"\b(RSS|CCF|LGP)-[A-Z]?\d+", f.read_text(encoding="utf-8")), "notes name an individual"
        yaml.safe_load(f.read_text(encoding="utf-8"))


def test_robustness_small():
    assert render_qbr.robustness(1) == 0
