"""Related records: the suggestions are scored from the data, and a person's call is checked against it."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scorecard import relations as RL
from scorecard import tickets as T

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def records():
    return T.build()["records"]


@pytest.fixture(scope="module")
def curated():
    return RL.load_curated()


@pytest.fixture(scope="module")
def result(records):
    return RL.evaluate(records)


def test_every_link_the_records_make_would_be_suggested(result):
    """The truth set is the links the records themselves make. Scoring must find all of them."""
    assert result["links"] == 18 and result["found"] == 18, result["missed"]


def test_decoys_are_not_suggested(result):
    """A place with no time, a time with no place, and a family resemblance must all stay below the line."""
    assert sum(result["decoys"].values()) > 500 and result["false"] == {}, result["false"]
    assert set(result["decoys"]) == {"same_place_far_apart", "same_time_other_hall", "same_fault_only"}


def test_a_suggestion_needs_a_place_and_a_time_or_shared_evidence(records):
    """No signal group can carry a suggestion alone: that is the rule the weights are set around."""
    cfg = RL.config()
    prep = RL.prepare(records)
    place = {k for k, v in cfg["signals"].items() if v["group"] == "place"}
    time = {k for k, v in cfg["signals"].items() if v["group"] == "time"}
    assert max(cfg["signals"][k]["points"] for k in place) < cfg["threshold"]
    assert max(cfg["signals"][k]["points"] for k in time) < cfg["threshold"]
    for a, b in (("INC3100017", "INC3101258"), ("WO-41035", "INC3100068")):
        s = RL.score(prep, a, b)
        if not s["qualifies"]:
            assert s["score"] == 0, (a, b, s["reasons"])


def test_the_person_assigned_is_never_a_signal(records):
    """Suggesting a relation because the same technician worked both would read as blaming a person."""
    cfg = RL.config()
    text = json.dumps(cfg) + (ROOT / "src" / "scorecard" / "relations.py").read_text(encoding="utf-8")
    for word in ("assigned", "engineer", "person_id", "technician"):
        assert f'"{word}"' not in text and f"['{word}']" not in text and f'["{word}"]' not in text, word
    prep = RL.prepare(records)
    for r in records:
        assert r["assigned"] not in json.dumps(sorted(prep["by_id"][r["id"]]["words"])) or not r["assigned"]


def test_every_suggestion_shows_its_reasons_and_is_capped(records):
    cfg = RL.config()
    sug = RL.suggest(records, curated=RL.load_curated())
    by_id = {r["id"]: r for r in records}
    for ref, items in sug.items():
        assert len(items) <= cfg["per_record"]
        for s in items:
            assert s["id"] in by_id and s["id"] != ref
            assert s["score"] >= cfg["threshold"] and s["reasons"]
            assert sum(r["points"] for r in s["reasons"]) == s["score"]
            assert s["id"] not in by_id[ref]["related"], "a link the records already make is not a suggestion"
            for r in s["reasons"]:
                assert r["signal"] in cfg["signals"] and r["text"].strip()


def test_curated_relations_are_complete_and_agree_with_the_data(records, curated):
    import json as _json
    all_findings = (_json.loads((ROOT / "reports" / "findings.json").read_text(encoding="utf-8"))["findings"]
                    + _json.loads((ROOT / "reports" / "landlord_findings.json").read_text(encoding="utf-8")))
    assert curated["relations"], "the repository holds at least one relation a person confirmed"
    assert RL.check_curated(curated, records) == []
    by_id = {r["id"]: r for r in records}
    people = {r["assigned"] for r in records if r["assigned"]}
    for c in curated["relations"]:
        a, b = c["records"]
        text = c["reason"]
        assert c["confirmed_on"] >= min(by_id[a]["start"], by_id[b]["start"])[:10], c["records"]
        assert c["confirmed_by"] in {"Customer Site Lead", "IT Partner Site Manager", "Landlord Chief Engineer", "Customer EHS"}
        for p in people:
            assert p not in text, f"{c['records']} names {p}"
        for ref in (a, b):
            assert ref in by_id
        for word in ("F-0", "L-0"):          # a finding named in a reason is a real finding about these records
            for fid in {x.strip(".,;)(") for x in text.split() if x.startswith(word)}:
                found = next((f for f in all_findings if f["id"] == fid), None)
                assert found, f"{c['records']} cites {fid}, which is not a finding"
                refs = {f["id"] for ref in (a, b) for f in by_id[ref]["findings"]}
                named = set(found.get("tickets") or []) & {a, b}
                units = {by_id[ref].get("device") for ref in (a, b)} | {by_id[ref].get("unit") for ref in (a, b)}
                assert fid in refs or named or found.get("unit") in text or found.get("unit") in units, \
                    f"{c['records']} cites {fid}, which names neither record nor anything in the reason"


def test_curated_relations_are_checked(records, curated):
    """The check catches a relation that names a record that is not here, has no reason, or is already linked."""
    assert RL.check_curated({"relations": [{"records": ["INC0000000", "WO-41023"], "type": "related",
                                            "confirmed_by": "x", "confirmed_on": "2026-09-01", "reason": "y"}]}, records)
    assert RL.check_curated({"relations": [{"records": ["INC3900001", "WO-41023"], "type": "related",
                                            "confirmed_by": "x", "confirmed_on": "2026-09-01", "reason": "y"}]}, records)
    assert RL.check_curated({"relations": [{"records": ["MOP-310", "PM-0012"], "type": "nonsense",
                                            "confirmed_by": "x", "confirmed_on": "2026-09-01", "reason": "y"}]}, records)
    assert RL.check_curated({"relations": [{"records": ["MOP-310", "PM-0012"], "type": "related",
                                            "confirmed_by": "", "confirmed_on": "", "reason": " "}]}, records)


def test_the_outage_and_its_mop_are_the_strongest_suggestion(records):
    """MOP-310 and the rack A07 outage are related through the work; neither system wrote the reference."""
    prep = RL.prepare(records)
    s = RL.score(prep, "MOP-310", "WO-41023")
    kinds = {r["signal"] for r in s["reasons"]}
    assert s["score"] > 100 and {"same_device", "overlapping", "same_alarm", "covering_mop"} <= kinds
    assert "WO-41023" not in {x["id"] for x in RL.suggest(records, curated=RL.load_curated())["MOP-310"]}, \
        "once a person has confirmed it, it is no longer suggested"


def test_the_page_carries_the_relations(tmp_path):
    import render_tickets
    out = tmp_path / "tickets.html"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "render_tickets.py"), "--html", str(out)], check=True, capture_output=True)
    html = out.read_text(encoding="utf-8")
    assert "__RELATIONS__" not in html and "Suggested by the data" in html
    rel = json.loads(html.split('id="rel-data" type="application/json">')[1].split("</script>")[0].replace("<\\/", "</"))
    assert rel["threshold"] == RL.config()["threshold"] and {t["id"] for t in rel["types"]} == {"related", "duplicate", "follow_up"}
    assert rel["curated"] and rel["suggestions"]
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "relations.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_weights_are_published_with_their_reasons():
    """A reader can see why every point is awarded; nothing is learned or hidden."""
    cfg = yaml.safe_load((ROOT / "config" / "relations.yaml").read_text(encoding="utf-8"))
    assert cfg["threshold"] == 50 and cfg["per_record"] == 5
    for name, sig in cfg["signals"].items():
        assert sig["points"] > 0 and sig["group"] in ("place", "time", "evidence", "weak") and sig["why"].strip()
    for t in cfg["types"]:
        assert t["label"] and t["text"].strip()
