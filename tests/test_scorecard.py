"""Tests for the scorecard (service levels measured from telemetry)."""

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest

from scorecard.builder import build_scorecard
from scorecard.connectors import FileConnector
from scorecard.engine import run_engine
from scorecard.kpi import INTEGRITY_TYPES
from scorecard.scorecard_report import scorecard_json, scorecard_markdown
from scorecard.sla_model import load_sla

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def sla():
    return load_sla()


@pytest.fixture(scope="module")
def engine(sla):
    return run_engine(sla, FileConnector(SAMPLE))


@pytest.fixture(scope="module")
def sc(sla, engine):
    return build_scorecard(sla, engine)


def row(sc, cid):
    return next(r for r in sc["csl"] if r["id"] == cid)


# ------------------------------------------------------------- measurement
def test_every_csl_measured(sc):
    assert all(r["actual"] is not None for r in sc["csl"])


def test_vendor_overstates_where_telemetry_disagrees(sc):
    """The demo's premise, as numbers."""
    for cid in ("CSL-04", "CSL-06", "CSL-07"):
        r = row(sc, cid)
        assert r["vendor_reported"] == 100.0 and r["actual"] < 100.0, cid


def test_split_ticket_measured_as_one_late_restore(sc, engine):
    split = next(f for f in engine.findings if f.type == "ticket_split" and "Ticket of Record" in f.summary
                 and f.unit.startswith("a"))
    inc = next(i for i in sc["incidents"] if split.tickets[0] in i.tickets)
    assert set(split.tickets) <= set(inc.tickets)
    assert inc.measured_min > 480 and all(v <= 480 for v in inc.vendor_restore_min)


def test_record_integrity_counts_flagged_tickets(sc, engine):
    flagged = {n for f in engine.findings if f.type in INTEGRITY_TYPES for n in f.tickets}
    r = row(sc, "CSL-11")
    assert r["misses"] == len(flagged)


def test_engagement_is_badge_verified(sc):
    for i in sc["incidents"]:
        if i.engaged_at is not None:
            assert i.engaged_at >= i.t0 - timedelta(minutes=5)


def test_worst_rack_not_better_than_fleet(sc):
    assert row(sc, "CSL-12")["actual"] <= row(sc, "CSL-01")["actual"]


# ------------------------------------------------------------------ credits
def test_credits_match_defaults_and_cap(sc, sla):
    defaults = {r["id"] for r in sc["csl"] if r["status"] in ("below_minimum", "deep_below_minimum")}
    assert {c["csl"] for c in sc["credits"]["items"]} == defaults
    at_risk = sla["commercial"]["monthly_charges"] * sla["commercial"]["at_risk_pct"] / 100
    assert sc["credits"]["payable"] <= at_risk
    assert sc["credits"]["payable"] == min(sc["credits"]["uncapped"], at_risk)


def test_integrity_credit_not_earnback_eligible(sc):
    for c in sc["credits"]["items"]:
        if c["csl"] == "CSL-11":
            assert c["earnback_eligible"] is False


# -------------------------------------------------- corrective action plans
def test_every_s1_s2_item_has_a_cap(sc):
    covered = {t for c in sc["corrective_actions"] for t in c["triggers"]}
    for e in sc["severity_log"]:
        if e["level"] in ("S1", "S2"):
            assert f"{e['ref']} {e['title']}" in covered


def test_cap_due_dates_are_business_days(sc):
    for c in sc["corrective_actions"]:
        assert c["due"].weekday() < 5


# ------------------------------------------------------------------ what-if
def test_what_if_tighter_target_creates_more_breaches(sla, engine):
    """The browser app relies on this: change the SLA, rerun, and results change."""
    tight = copy.deepcopy(sla)
    next(p for p in tight["priorities"] if p["id"] == "P2")["restore_min"] = 240
    before = build_scorecard(sla, engine)
    after = build_scorecard(tight, engine)
    assert row(after, "CSL-04")["actual"] < row(before, "CSL-04")["actual"]
    assert after["credits"]["uncapped"] >= before["credits"]["uncapped"]


def test_what_if_looser_minimum_removes_a_default(sla, engine):
    loose = copy.deepcopy(sla)
    c = next(c for c in loose["critical_service_levels"] if c["id"] == "CSL-07")
    c["expected"], c["minimum"] = 97.0, 95.0
    after = build_scorecard(loose, engine)
    assert row(after, "CSL-07")["status"] == "met_expected"


# ------------------------------------------------------------------ weekly
def test_weekly_views(sc):
    assert len(sc["weeks"]) == 4
    for w in sc["weeks"]:
        assert w["measured"]["CSL-01"] is not None and w["vendor"]["CSL-01"] is not None


# ------------------------------------------------------------------ reports
def test_committed_scorecard_is_current(sc):
    js = json.dumps(scorecard_json(sc), indent=2, sort_keys=True) + "\n"
    assert (ROOT / "reports" / "scorecard.json").read_text(encoding="utf-8") == js, "run scripts/build_scorecard.py"
    assert (ROOT / "reports" / "scorecard.md").read_text(encoding="utf-8") == scorecard_markdown(sc)
