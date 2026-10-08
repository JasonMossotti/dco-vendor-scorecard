"""Post-incident review: facts match the dataset exactly, and the written review agrees with the facts."""

import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scorecard.pir import OSR, Dataset, build_index, build_review

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def ds():
    return Dataset(SAMPLE)


@pytest.fixture(scope="module")
def review():
    return yaml.safe_load((ROOT / "pir" / "reviews" / "PIR-2026-001.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def facts(ds, review):
    return build_review(ds, review["ref"])


def test_every_timeline_record_is_reproduced_exactly(facts):
    sources = {}
    for r in facts["timeline"]:
        if not r["record"]:
            continue
        path = SAMPLE / r["source"]
        if path not in sources:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".jsonl":
                sources[path] = [json.dumps(json.loads(x), sort_keys=True) for x in text.splitlines() if x.strip()]
            elif path.suffix == ".json":
                sources[path] = [json.dumps(x, sort_keys=True) for x in json.loads(text)]
            else:
                import csv
                sources[path] = [json.dumps(x, sort_keys=True) for x in csv.DictReader(path.open(encoding="utf-8"))]
        rec = json.loads(r["record"])
        assert any(rec.items() <= json.loads(line).items() for line in sources[path]), (r["source"], r["record"])


def test_facts_for_rack_a07(facts):
    assert (facts["ticket"], facts["work_order"], facts["mops"], facts["rack"]) == ("INC3900001", "WO-41023", ["MOP-310"], "A07")
    assert (facts["power_lost"], facts["handoff"], facts["rts"]) == ("2026-09-15T15:42:11Z", "2026-09-15T19:06:55Z", "2026-09-15T20:01:36Z")
    assert facts["attribution"]["owner"] == "Landlord" and facts["attribution"]["rules"] == ["FA-1", "FA-3"]
    assert facts["impact"]["gpus"] == 72 and facts["impact"]["duration"] == "4 h 19 min"
    assert facts["mop_overrun"]["overrun"] == "2 h 06 min"
    assert [f["id"] for f in facts["findings"]] == ["L-004"]


def test_work_order_and_ticket_resolve_to_the_same_incident(ds, facts):
    other = build_review(ds, "WO-41023")
    assert (other["ticket"], other["power_lost"], other["rts"]) == (facts["ticket"], facts["power_lost"], facts["rts"])


def test_written_review_agrees_with_the_facts(facts, review):
    """Every number a reader sees in the prose must match the data."""
    text = json.dumps(review)
    pl = review["plain_language"]["what_happened"]
    assert "4 hours 19 minutes" in pl and facts["impact"]["duration"] == "4 h 19 min"
    assert "10:42 a.m. Central" in pl and facts["timeline"][[r["t"] for r in facts["timeline"]].index(facts["power_lost"])]["local"].startswith("10:42")
    for t in (facts["power_lost"][11:19], facts["handoff"][11:19], facts["rts"][11:19], "19:22:05"):
        assert t + "Z" in review["summary_technical"], t
    assert facts["mop_overrun"]["overrun"] in text
    m = {x["measure"]: x for x in facts["metrics"]}
    assert m["Landlord acknowledge (P1 target 5 min)"]["elapsed"] == "3 min" and "acknowledged in 3 minutes" in text
    assert m["IT Partner acknowledge"]["elapsed"] == "2 min" and "acknowledged in 2 minutes" in text
    assert m["IT Partner validation, handoff to return to service (P1 target 4 h, FA-3)"]["elapsed"] == "55 min" and "55 minutes" in text
    assert facts["findings"][0]["id"] in review["severity"]["internal"]
    assert review["severity"]["osr_level"] == facts["osr_suggested"]["level"]


def test_review_is_blameless(review, facts):
    text = json.dumps(review)
    for person in (facts["people"]["landlord_engineer"], facts["people"]["it_technician"], "Lane Haddad"):
        assert person not in text, f"the review names {person}"
    for a in review["actions"]:
        assert all(a.get(k) for k in ("owner", "due", "priority", "success", "factor")), a["id"]
        assert a["factor"] in {f["id"] for f in review["factors"]}


def test_index_covers_every_record_in_the_portal(ds):
    """A review can be started from any record, so the index holds every one the Incident Portal holds."""
    from scorecard.tickets import ids
    idx = build_index(ds)
    assert set(idx) == set(ids())
    for ref, f in idx.items():
        assert f["title"] and f["date"] and f["metrics"], ref
        assert f["kind"] in ("rack_power", "event", "chg", "mop", "pm")
        assert f["impact"]["gpus"] >= 0 and f["osr_suggested"]["level"] in OSR


def test_facts_for_every_record_type(ds):
    """Each type is measured on what its own records say: windows for changes and MOPs, response for incidents."""
    idx = build_index(ds)
    cdu = idx["WO-41024"]            # a CDU work order: no rack lost power, so no handoff
    m = {x["measure"].split(" (")[0]: x for x in cdu["metrics"]}
    assert cdu["kind"] == "event" and cdu["handoff"] is None and cdu["attribution"]["rules"] == ["FA-5"]
    assert m["Restored, as recorded in the work order"]["elapsed"] == "44 min"
    assert m["Restored, as measured from telemetry"]["elapsed"] == "3 h 44 min"   # finding L-006: 180 min apart
    assert "3 h 00 min earlier than the telemetry" in m["Restored, as measured from telemetry"]["note"]
    assert [f["id"] for f in cdu["findings"]] == ["L-006"]
    mop = idx["MOP-310"]             # the MOP behind the A07 outage: its window was overrun
    assert mop["kind"] == "mop" and mop["mop_overrun"]["overrun"] == "2 h 06 min"
    chg = idx["CHG2040031"]          # a firmware change: the work recorded sits inside its window
    assert chg["kind"] == "chg" and "Inside the approved window." in [x["note"] for x in chg["metrics"]]
    pm = idx["PM-0018"]              # the thermography task with a records finding
    assert pm["kind"] == "pm" and [f["id"] for f in pm["findings"]] == ["L-001"]
    util = idx["WO-41009"]           # the utility outage: attributed to the utility, FA-6
    assert util["attribution"]["owner"] == "Utility" and util["attribution"]["rules"] == ["FA-6"]


def test_the_a07_review_is_unchanged_by_the_index(ds, facts):
    """Starting a review from any record must not change the facts of the review we already publish."""
    entry = build_index(ds)["INC3900001"]
    for k, v in facts.items():
        assert entry[k] == v, k


def test_every_record_names_devices_the_directory_knows(ds):
    """PIR search matches on device names, so each record's devices must be real entries in the directory."""
    from scorecard import devices as D
    data = D.load()
    idx = build_index(ds)
    named = [ref for ref, f in idx.items() if f["devices"]]
    assert len(named) >= len(idx) - 6        # the utility service and the leak-detection module are not devices
    for ref, f in idx.items():
        for n in f["devices"]:
            assert D.lookup(data, n), f"{ref} names {n}, which is not in the device directory"
        assert not (set(f["devices"]) & set(f["near"])), ref


def test_markdown_review_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_pir.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_interactive_page_builds_and_works(tmp_path):
    out = tmp_path / "pir.html"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "render_pir.py"), "--html", str(out)], check=True, capture_output=True)
    html = out.read_text(encoding="utf-8")
    assert "__DATA__" not in html and "INC3900001" in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "pir_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_every_repeat_event_is_ruled(facts, review):
    """The review says each repeat event is ruled in or out, so every one must be."""
    rulings = review.get("repeat_rulings", {})
    assert set(rulings) == {r["ref"] for r in facts["repeats"]}
    for ref, rl in rulings.items():
        assert isinstance(rl["related"], bool) and rl["reason"].strip(), ref


def test_action_statuses_are_dated(review):
    """Statuses are a snapshot. Nothing may be shown open past its due date as of that snapshot."""
    as_of = review["status_as_of"]
    assert as_of >= review["review_meeting"]
    for a in review["actions"]:
        assert a["status"] in ("Not started", "In progress", "Complete"), a["id"]
        assert a["status"] == "Complete" or a["due"] > as_of, f"{a['id']} is overdue as of {as_of}"


def test_one_feed_power_on_matches_the_data(review):
    """F6: the rack was powered on after the handoff but before the A-side tap-off closed."""
    checks = [json.loads(x) for x in (SAMPLE / "telemetry" / "health_checks.jsonl").read_text().splitlines() if x.strip()]
    power_on = next(c for c in checks if c["target"] == "A07" and c["check"] == "rack_power_on")["started_at"]
    events = [json.loads(x) for x in (SAMPLE / "facility" / "busway_cpm_events.jsonl").read_text().splitlines() if x.strip()]
    a_close = next(e for e in events if e.get("tapoff") == "TO-A07-A" and e["event"] == "Breaker closed")["timestamp"]
    b_close = next(e for e in events if e.get("tapoff") == "TO-A07-B" and e["event"] == "Breaker closed")["timestamp"]
    assert b_close < power_on < a_close
    f6 = next(f for f in review["factors"] if f["id"] == "F6")["text"]
    assert power_on[11:19] + "Z" in f6 and b_close[11:19] + "Z" in f6
    assert power_on[11:19] + "Z" in review["summary_technical"]


def test_outage_technician_badges_out_after_return_to_service(facts):
    """IT readers record exits, so the outage's badge-in must be followed by a badge-out once the rack is back."""
    import csv
    tech = facts["people"]["it_technician"]
    rows = sorted((r for r in csv.DictReader((SAMPLE / "access" / "badge_events.csv").open(encoding="utf-8"))
                   if r["person_id"] == tech), key=lambda r: r["timestamp"])
    i = next(i for i, r in enumerate(rows) if r["timestamp"] > facts["handoff"] and r["direction"] == "in")
    nxt = rows[i + 1]
    assert nxt["direction"] == "out" and nxt["door"] == rows[i]["door"] and nxt["timestamp"] > facts["rts"]


def test_repeat_rulings_name_findings_on_the_same_ticket(review):
    """A reader of the scorecard should not find a finding on a repeat ticket that the review never mentions."""
    from scorecard.connectors import FileConnector
    from scorecard.engine import run_engine
    from scorecard.sla_model import load_sla
    findings = run_engine(load_sla(), FileConnector(SAMPLE)).findings
    for ref, rl in review["repeat_rulings"].items():
        for f in findings:
            if ref in f.tickets:
                assert f.id in rl["reason"], f"{ref} has {f.id}, which the ruling does not mention"

# --------------------------------------------------------------------------- every completed review
@pytest.fixture(scope="module")
def reviews():
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "pir" / "reviews").glob("*.yaml"))]


def _ids(reviews):
    return [r["id"] for r in reviews]


def test_every_review_is_of_a_record_in_the_dataset(ds, reviews):
    idx = build_index(ds)
    assert len(reviews) >= 2, "the PIR search needs more than one review to be worth searching"
    assert _ids(reviews) == sorted(_ids(reviews)) and len(set(_ids(reviews))) == len(reviews)
    for r in reviews:
        assert r["ref"] in idx, r["id"]
        assert r["id"] == f"PIR-{r['review_meeting'][:4]}-{r['id'][-3:]}"


def test_every_number_in_the_prose_comes_from_the_facts(ds, reviews):
    """A reader acts on these numbers: every clock time and every duration in a review must be in its facts."""
    idx = build_index(ds)
    for r in reviews:
        f = idx[r["ref"]]
        text = json.dumps(r)
        pool = " ".join([json.dumps(f["metrics"]), json.dumps(f["timeline"]), json.dumps(f["impact"]),
                         f["start"], str(f["end"]), json.dumps(f["mop_overrun"])])
        for t in set(re.findall(r"\d{2}:\d{2}:\d{2}Z", text)):
            assert t in pool, f"{r['id']} quotes {t}, which is not in the facts"
        for d in set(re.findall(r"\b\d+ h \d{2} min\b|\b\d+ min\b", text)):
            assert d in pool, f"{r['id']} quotes {d}, which is not in the facts"


def test_every_review_is_complete_and_blameless(ds, reviews):
    idx = build_index(ds)
    people = {r["person_id"] for r in csv.DictReader((SAMPLE / "vendor" / "personnel.csv").open(encoding="utf-8"))}
    names = {r["name"] for r in csv.DictReader((SAMPLE / "vendor" / "personnel.csv").open(encoding="utf-8"))}
    for r in reviews:
        f, text = idx[r["ref"]], json.dumps(r)
        assert r["severity"]["osr_level"] == f["osr_suggested"]["level"], r["id"]
        assert r["status_as_of"] >= r["review_meeting"] and r["signoff"], r["id"]
        for k in ("plain_language", "summary_technical", "trigger", "detection", "resolution", "factors", "lessons", "ehs", "actions"):
            assert r[k], f"{r['id']} has no {k}"
        for q in ("what_happened", "who_was_affected", "why", "what_we_are_doing"):
            assert r["plain_language"][q].strip(), f"{r['id']} {q}"
        for k in ("went_well", "went_poorly", "lucky"):
            assert r["lessons"][k], f"{r['id']} {k}"
        factors = {x["id"] for x in r["factors"]}
        for a in r["actions"]:
            assert all(a.get(k) for k in ("action", "owner", "due", "priority", "success", "factor")), f"{r['id']} {a['id']}"
            assert a["factor"] in factors and a["status"] in ("Not started", "In progress", "Complete"), f"{r['id']} {a['id']}"
            assert a["status"] == "Complete" or a["due"] > r["status_as_of"], f"{r['id']} {a['id']} is overdue as of {r['status_as_of']}"
        assert set(r.get("repeat_rulings", {})) == {x["ref"] for x in f["repeats"]}, r["id"]
        for ref, rl in r.get("repeat_rulings", {}).items():
            assert isinstance(rl["related"], bool) and rl["reason"].strip(), f"{r['id']} {ref}"
        for person in people | names:
            assert person not in text, f"{r['id']} names {person}"
        for x in f["findings"]:
            assert x["id"] in text, f"{r['id']} does not mention finding {x['id']} on its own record"


def test_the_portal_marks_a_record_reviewed_only_through_its_own_incident(reviews):
    """A MOP or PM task is not reviewed because an incident that names it was; the review covers the incident."""
    import render_tickets
    from scorecard import tickets as T
    reviewed = render_tickets.reviewed(T.build()["records"])
    assert set(reviewed.values()) == set(_ids(reviews))
    assert reviewed["INC3900001"] == reviewed["WO-41023"] == "PIR-2026-001"
    assert not [k for k in reviewed if k.startswith(("MOP-", "PM-"))]
