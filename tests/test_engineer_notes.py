"""Engineer notes on every Incident Portal record: current, complete, and every fact the record's own.

Facts come from the data: every time, number, serial, device, person ID, and record number in a note must be on the
record it sits on (or a record it links to), hours must equal their span, and no person is named. Notes follow the
partner's own record and add no finding.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from scorecard import engineer_notes as E
from scorecard import tickets as T

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_engineer_notes as G  # noqa: E402


@pytest.fixture(scope="module")
def built():
    d, bad = G.build()
    return d, bad


@pytest.fixture(scope="module")
def records():
    return T.build()["records"]


def _field(note, key):
    return next(f for f in note["fields"] if f["key"] == key)


def test_notes_are_current_and_reconcile(built):
    d, bad = built
    assert bad == []
    assert (ROOT / "data" / "engineer_notes" / "notes.json").read_text(encoding="utf-8") == G.text(d), \
        "Run: python scripts/generate_engineer_notes.py"


def test_every_record_has_its_systems_fields(built, records):
    notes = built[0]["notes"]
    cfg = E.config()
    assert set(notes) == {r["id"] for r in records}
    for r in records:
        n = notes[r["id"]]
        keys = [f["key"] for f in n["fields"]]
        want = [f["key"] for f in cfg["types"][r["type"]]["fields"]]
        assert keys == [k for k in want if k in keys], r["id"]
        assert len(keys) >= len(want) - 1, (r["id"], set(want) - set(keys))
        assert n["title"] == cfg["types"][r["type"]]["title"]


def test_incident_work_notes_are_the_tickets_own(built, records):
    notes = built[0]["notes"]
    for r in records:
        if r["type"] == "inc":
            assert _field(notes[r["id"]], "work_notes")["entries"] == [{"at": x["at"], "by": x["by"], "text": x["text"]} for x in r["notes"]]


def test_hand_written_notes_are_marked(built):
    d = built[0]
    hand = E.hand_written()
    assert d["hand_written"] == sorted(hand) and len(hand) == 12
    for ref in hand:
        assert d["notes"][ref]["source"] == "hand-written"


@pytest.mark.parametrize("mutate,expect", [
    (lambda n: _field(n, "work_log")["entries"][0].update(at="2026-09-15T15:50:00Z"), "time 2026-09-15T15:50:00Z"),
    (lambda n: _field(n, "work_log")["entries"][1].update(text="Arrived at 10:51 CDT."), "clock time 10:51"),
    (lambda n: _field(n, "long_description").update(text="Replaced SN ZZ12345678 on rack A07."), "'ZZ12345678'"),
    (lambda n: _field(n, "work_log")["entries"][0].update(by="CCF-E99"), "person CCF-E99"),
    (lambda n: _field(n, "labor")["entries"][0].update(hours=2.0), "hours 2.0"),
    (lambda n: _field(n, "long_description").update(text="Rack A07 lost 913 feeds."), "'913'"),
])
def test_the_check_catches_a_fact_that_is_not_on_the_record(built, records, mutate, expect):
    notes = copy.deepcopy(built[0]["notes"])
    mutate(notes["WO-41023"])
    bad = E.check(records, notes)
    assert any(b.startswith("WO-41023") and expect in b for b in bad), bad


def test_the_check_catches_a_name(built, records):
    names = list(T.Redactor(T.SAMPLE).ids)
    notes = copy.deepcopy(built[0]["notes"])
    _field(notes["INC3100068"], "close_notes")["text"] += " " + names[0]
    assert any("names a person" in b for b in E.check(records, notes, names=names))


def test_notes_follow_the_record_and_add_no_finding(built, records):
    """Where telemetry and a record do not reconcile, the note agrees with its record; the finding stays."""
    notes = built[0]["notes"]
    by_id = {r["id"]: r for r in records}
    # L-002: the work order attributes the fault to the IT Partner; so does the engineer's note
    assert "Attributed to the IT Partner" in json.dumps(notes["WO-41043"])
    # L-003: the generator test record says 40% load; the readings say the same
    assert ["Load on the load bank", "40%"] in _field(notes["PM-0004"], "readings")["rows"]
    # L-006: the work log's restore time is the work order's, not the Redfish recovery
    restored = [e for e in _field(notes["WO-41024"], "work_log")["entries"] if e["at"] == by_id["WO-41024"]["native"]["restored_at"]]
    assert restored
    # FLS-1: the impairment tag comes off when the log says restored
    assert _field(notes["IMP-0005"], "tag")["entries"][-1]["at"] == by_id["IMP-0005"]["native"]["restored_at"]
    # No note mentions a finding code or the Customer's measurement
    for ref, n in notes.items():
        s = json.dumps(n["fields"])
        assert not any(f["id"] in s.split('"') for f in by_id[ref]["findings"]), ref
        assert "Measured" not in s and "Telemetry of Record" not in s, ref


def test_notes_claim_nothing_the_quality_audit_found_missing(built):
    notes = built[0]["notes"]
    plants = E.audit_plants()
    assert plants, "the audit's answer key is present"
    for ref, kinds in plants.items():
        s = " ".join(E._strings([{k: v for k, v in f.items() if k not in ("key", "label")} for f in notes[ref]["fields"]])).lower()
        if "pm_tag" in kinds:
            assert "maintenance tag" not in s, ref
        if "label" in kinds:
            assert "label" not in s, ref
        if "qd" in kinds:
            assert "witness" not in s, ref


def test_time_worked_is_the_span_of_the_records_own_times(built):
    for ref, n in built[0]["notes"].items():
        for f in n["fields"]:
            for e in f.get("entries", []):
                if "hours" in e:
                    assert e["hours"] == E.hours(e["from"], e["to"]) and e["hours"] >= 0, ref


def test_existing_records_are_untouched():
    """The notes are their own layer: the sample's ticket files carry no new fields."""
    tickets = json.loads((ROOT / "data" / "sample" / "vendor" / "tickets.json").read_text(encoding="utf-8"))
    assert all("engineer_notes" not in t and "close_notes" not in t for t in tickets)
