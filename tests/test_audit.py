"""Quality audit: the Customer's monthly random sample of closed records (sla/common.yaml, measurement.audit), each
followed through the Customer's systems and walked down in person, with four planted workmanship defects and no
false positives."""

import filecmp
import json
import math
import re
import sys
from pathlib import Path

import pytest

from scorecard import audit as AU
from scorecard.synthetic import audit as G

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "audit"
sys.path.insert(0, str(ROOT / "scripts"))

import render_audit  # noqa: E402

NAMES = ["sample", "inventory", "engine", "custody", "labels", "tags", "nameplates"]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("audit")
    before = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = G.AuditLayer(SAMPLE, seed)
    G.write_audit(layer, layer.run(), tmp, "data/sample")
    after = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    return tmp, before == after


@pytest.fixture(scope="module")
def f():
    return render_audit.prepare()


@pytest.fixture(scope="module")
def r():
    return AU.analyse(render_audit.load(), AU.run_engines(SAMPLE))


def test_committed_layer_is_current_and_sample_untouched(regenerated):
    out, untouched = regenerated
    assert untouched, "generating the audit layer must not write data/sample"
    files = sorted(p.name for p in out.iterdir())
    assert files == sorted(p.name for p in LAYER.iterdir())
    for name in files:
        assert filecmp.cmp(out / name, LAYER / name, shallow=False), f"data/audit/{name} is stale: run python scripts/generate_audit.py"


def test_report_is_current(f):
    assert (ROOT / "reports" / "quality_audit.md").read_text(encoding="utf-8") == render_audit.markdown(f)


def test_sample_follows_the_contract(r):
    """5% of each partner's closed records, at least 10, reproducible from the published seed and drawn after the close."""
    rule = AU.rule()
    assert (rule["sample_pct"], rule["min_records"], rule["workmanship_target_pct"]) == (5, 10, 95)
    text = " ".join(rule["rule"].split())
    assert "random 5%" in text and "(minimum 10)" in text and "target of 95%" in text and "no service credit" in text
    m = AU.load_month(SAMPLE)
    pools = AU.pools(m)
    assert {k: len(v) for k, v in pools.items()} == {"it": 75, "landlord": 32}
    sample = json.loads((LAYER / "sample.json").read_text(encoding="utf-8"))
    for p, pool in pools.items():
        n = max(10, math.ceil(len(pool) * 0.05))
        assert sample["records"][p] == AU.draw(pool, sample["seed"], p, rule) and len(sample["records"][p]) == n
        assert set(sample["records"][p]) <= set(pool)
    assert AU.parse(sample["drawn_at"]) >= m.end, "the sample is drawn after the month closes"
    assert r["summary"]["it"]["sampled"] == r["summary"]["landlord"]["sampled"] == 10


def test_every_agreement_holds_and_every_plant_is_found(r):
    assert [c.name for c in r["agreements"]] == NAMES
    for c in r["agreements"]:
        assert c.checked > 0, c.name
        assert len(c.misses) == r["explained"].get(c.name, 0), (c.name, c.misses)
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert AU.score(r["findings"], key) == {"planted": 4, "found": 4, "false_positives": 0}
    assert sorted(f["kind"] for f in r["findings"]) == ["custody", "label", "pm_tag", "qd"]
    assert [f["id"] for f in r["findings"]] == ["QA-1", "QA-2", "QA-3", "QA-4"]


def test_headline(r):
    s = r["summary"]
    assert (s["it"]["passed"], s["it"]["sampled"], s["it"]["met"]) == (7, 10, False)
    assert (s["landlord"]["passed"], s["landlord"]["sampled"], s["landlord"]["met"]) == (9, 10, False)
    assert (s["it"]["engine"], s["landlord"]["engine"]) == (1, 2)


def test_findings_quote_the_records(r):
    m = AU.load_month(SAMPLE)
    idx = AU.record_index(m)
    rma = {x["serial"]: x for x in m.rma}
    cage = {c["serial"] for c in render_audit.load().cage}
    for x in r["findings"]:
        rec = idx[x["record"]][2]
        if x["kind"] == "custody":
            assert x["reading"] in cage and AU.parse(rma[x["reading"]]["shipped_at"]) <= AU.parse(r["cage_scanned_at"])
        elif x["kind"] == "label":
            assert x["reading"] != x["expected"] and x["expected"] == rec["short_description"][5:]
        elif x["kind"] == "pm_tag":
            assert x["expected"] == rec["completed_at"][:10] and x["reading"] < x["expected"]
        elif x["kind"] == "qd":
            assert any(p["part"] in AU.WET for p in rec["parts_used"])
        assert x["owner"] in ("IT Partner", "Landlord") and x["action"] and x["due"] > x["at"][:10]
        # Facts, not people: no technician or engineer is named in a finding
        names = {n["author"] for t in m.tickets for n in t["work_notes"]}
        assert not any(n in x["note"] + x["action"] for n in names)
        assert "lied" not in x["note"] and "fault of" not in x["note"]


def test_records_check_shows_the_engines_findings(r):
    """A sampled record's engine findings are the engines' own, record for record (they already count toward CSL-11)."""
    eng = AU.run_engines(SAMPLE)
    for x in r["records"]:
        assert x["engine"] == eng.get(x["id"], [])
    assert {e["id"] for x in r["records"] for e in x["engine"]} == {"F-014", "L-001", "L-003"}


def test_walkdown_reads_what_is_physically_there(r):
    """A tracked part's serial reads what the BMC inventory shows now at its location; the cage holds what the ledger had not shipped."""
    m = AU.load_month(SAMPLE)
    t = render_audit.load()
    for w in t.walkdown:
        if w["item"] == "serial":
            rec = AU.record_index(m)[w["record"]][2]
            part = next(p for p in rec["parts_used"] if p["part"] in AU.TRACKED and p["installed_serial"])
            assert w["reading"] == AU.current_serial(part["removed_serial"], m.inventory)
    assert all(w["inspector"] == "Customer site lead" for w in t.walkdown)
    assert all(AU.parse(w["inspected_at"]) > AU.parse(r["cage_scanned_at"]) for w in t.walkdown)


def test_an_unverified_swap_is_corroborated_not_double_counted():
    """When a sampled ticket's swap never reached the inventory, the walk-down reads the old part and points to the engine's finding."""
    m = AU.load_month(SAMPLE)
    eng = AU.run_engines(SAMPLE)
    swap = next(n for n, fs in eng.items() if any(x["type"] == "unverified_swap" for x in fs))
    t = render_audit.load()
    t.sample = dict(t.sample, records={"it": [swap], "landlord": []})
    rule = dict(AU.rule(), min_records=1, sample_pct=0)
    seed = next(s for s in range(10000) if AU.draw(AU.pools(m)["it"], s, "it", rule) == [swap])
    t.sample["seed"] = seed
    rec = AU.record_index(m)[swap][2]
    part = next(p for p in rec["parts_used"] if p["part"] in AU.TRACKED)
    t.walkdown = [{"record": swap, "partner": "it", "item": "serial", "result": "", "reading": part["removed_serial"], "note": "",
                   "inspected_at": "2026-09-29T15:00:00Z", "inspector": "Customer site lead"}]
    got = AU.analyse(t, eng, r=rule)
    item = next(i for x in got["records"] for i in x["items"] if i["key"] == "serial")
    assert item["result"] == "fail" and item["corroborates"] == next(x["id"] for x in eng[swap] if x["type"] == "unverified_swap")
    assert not [f for f in got["findings"] if f["kind"] == "serial"]
    assert not next(c for c in got["agreements"] if c.name == "engine").misses


def test_page_data(f):
    assert f["seed"] == json.loads((LAYER / "sample.json").read_text(encoding="utf-8"))["seed"]
    assert [q["id"] for q in f["quality"]] == ["CSL-06", "CSL-08", "KM-18"]
    assert len(f["records"]) == 20 and all(x["evidence"] for x in f["records"])
    assert set(f["checklist"]) == {"it", "landlord"}
    assert re.search(r"--sample \d+", render_audit.markdown(f))
