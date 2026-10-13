"""Incident Commander runbook and the A07 replay: clocks from the agreements, a comms log that reconciles with the
records and the review, and notes that agree with the facts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import command  # noqa: E402
from scorecard.pir import Dataset, build_review  # noqa: E402
from scorecard.sla_model import load_sla  # noqa: E402

COMMS = ROOT / "data" / "incident_comms"


@pytest.fixture(scope="module")
def built():
    return command.build()


@pytest.fixture(scope="module")
def a07(built):
    return next(r for r in built["replays"] if r["ref"] == "INC3900001")


def test_comms_log_is_current(tmp_path):
    import generate_incident_comms
    generate_incident_comms.generate(tmp_path)
    for p in sorted(tmp_path.iterdir()):
        assert p.read_bytes() == (COMMS / p.name).read_bytes(), f"{p.name} is stale: run python scripts/generate_incident_comms.py"


def test_comms_log_keeps_the_scenario_minutes_and_its_own_stream():
    """The generator only adds seconds; a different seed moves seconds, never a minute or the order."""
    from scorecard.synthetic.incident_comms import build
    cfg = yaml.safe_load((ROOT / "config" / "incident_comms.yaml").read_text(encoding="utf-8"))
    a, b = build(1), build(2)
    for ref, inc in cfg["incidents"].items():
        assert [e["t"][11:16] for e in a[ref]] == [e["at"] for e in inc["events"]] == [e["t"][11:16] for e in b[ref]]
        assert [e["t"] for e in a[ref]] == sorted(e["t"] for e in a[ref])
        assert [e["t"] for e in a[ref]] != [e["t"] for e in b[ref]]


def test_comms_log_reconciles_with_the_pir_timeline(a07):
    f = build_review(Dataset(ROOT / "data" / "sample"), "INC3900001")
    log = a07["log"]
    first = lambda k: next(e["t"] for e in log if e["kind"] == k)
    assert all(e["t"] >= f["start"] for e in log), "nothing on the bridge before the alarm"
    assert first("restoration_declared") >= f["handoff"], "restoration declared only after the busway shows the feed closed"
    assert first("rts_declared") >= f["end"], "return to service declared only after the scheduler shows the nodes back"
    assert first("bridge_closed") >= first("rts_declared")
    joined = {e["party"]: e["t"] for e in log if e["kind"] == "lead_joined"}
    assert all(e["t"] >= joined[e["party"]] for e in log if e["kind"] == "lead_update"), "no lead updates before joining"
    assert {e["role"] for e in log} == {"On-call primary", "Incident Commander", "Landlord lead", "IT Partner lead"}, "roles only"


def test_leadership_updates_match_the_reviews_communications_log(a07):
    review = yaml.safe_load((ROOT / "pir" / "reviews" / f"{a07['review']}.yaml").read_text(encoding="utf-8"))
    logged = [(e["local"][:5], e["to"], e["text"]) for e in a07["log"] if e["kind"] == "leadership_update"]
    written = [(c["local"].split()[0], c["to"], c["message"]) for c in review["communications"]]
    assert logged == written


def test_contract_clocks_are_read_from_the_agreements(built):
    cc = built["runbook"]["clocks"]
    ia = yaml.safe_load((ROOT / "sla" / "interface_agreement.yaml").read_text(encoding="utf-8"))
    assert f"within {cc['bridge_min']} minutes" in ia["incident_command"]["bridge"] and cc["bridge_min"] == 15
    assert f"within {cc['pir_business_days']} business days" in ia["incident_command"]["post_incident"]
    p1 = [next(p for p in load_sla(v)["priorities"] if p["id"] == "P1")["update_cadence_min"] for v in command.SLAS.values()]
    assert cc["lead_cadence_min"] == min(p1) == 30
    assert cc["page_min"] == next(n for n in ia["alarm_notification"]["notifications"] if n["id"] == "NT-1")["within_min"]


def test_runbook_covers_every_priority_and_step(built):
    rb = built["runbook"]
    assert [p["id"] for p in rb["severity"]["priorities"]] == ["P1", "P2", "P3", "P4"]
    assert all(p["command"] for p in rb["severity"]["priorities"])
    assert [x["id"] for x in rb["severity"]["internal"]][:2] == ["S1", "S2"]
    assert {s["phase"] for s in rb["steps"]} == {p["id"] for p in rb["phases"]}
    assert all(s["due"] for s in rb["steps"])
    assert {t["id"] for t in rb["templates"]} == {"leadership", "landlord", "it_partner"}
    tree = rb["paging"]["levels"]
    assert [x["min"] for x in tree] == sorted(x["min"] for x in tree) and tree[-1]["who"] == "Site leadership"


def test_a07_replay(a07):
    assert a07["summary"] == {"steps": 14, "met": 9, "missed": 5}
    missed = {s["id"] for s in a07["steps"] if s["met"] is False}
    assert missed == {"bridge", "lead_cadence", "leadership_cadence", "change_windows", "restoration_confirmed"}
    step = {s["id"]: s for s in a07["steps"]}
    assert step["bridge"]["checks"][0]["elapsed"] == "19 min"
    assert [c["elapsed"] for c in step["leadership_cadence"]["checks"] if not c["met"]] == ["2 h 37 min"]
    assert step["restoration_confirmed"]["checks"][0]["detail"] == "TO-A07-A still open at confirmation (closed 19:22:05Z)"
    assert step["pir"]["checks"][0]["elapsed"] == "3 business days"


def test_replay_notes_agree_with_the_facts(a07):
    """A note for every missed step and none for a met one; every time and factor a note gives is in the facts."""
    review = yaml.safe_load((ROOT / "pir" / "reviews" / f"{a07['review']}.yaml").read_text(encoding="utf-8"))
    factors = {x["id"] for x in review["factors"]}
    log_times = {e["t"][11:16] for e in a07["log"]}
    for s in a07["steps"]:
        assert bool(s["note"]) == (s["met"] is False), s["id"]
        if not s["note"]:
            continue
        facts = log_times | {x[11:16] for c in s["checks"] for x in (c["from"], c["at"]) if x and len(x) > 10}
        facts |= set(re.findall(r"(\d\d:\d\d)", " ".join(c["detail"] for c in s["checks"])))
        for hhmm in re.findall(r"(\d\d:\d\d)Z", s["note"]):
            assert hhmm in facts, f"{s['id']}: {hhmm}Z is not in the facts"
        for fid in re.findall(r"factor (F\d+)", s["note"]):
            assert fid in factors, f"{s['id']}: {fid} is not a factor of {review['id']}"
        assert not re.search(r"\b(?:Lane|Haddad)\b", s["note"]), "no individual is named"


def test_markdown_runbook_is_current():
    import render_pir
    md = render_pir.outputs()[ROOT / "docs" / "pir" / "incident-command.md"]
    assert md == (ROOT / "docs" / "pir" / "incident-command.md").read_text(encoding="utf-8")
    assert "9 of 14 steps met, 5 missed" in md


def test_manifest_counts(a07):
    m = json.loads((COMMS / "manifest.json").read_text(encoding="utf-8"))
    assert m["files"]["INC3900001.json"] == len(a07["log"])
