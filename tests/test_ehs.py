"""EHS (safety, /ops/#ehs): the monthly EHS report by partner, permits and training against the job, badge, and device
records, four planted record problems, the A07 wrong tap-off as found, and the weekly pack's EHS line."""

import filecmp
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from scorecard import ehs as E
from scorecard.change_calendar import parse
from scorecard.synthetic import ehs as G

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "data" / "ehs"
SEC = ROOT / "data" / "security"
sys.path.insert(0, str(ROOT / "scripts"))

import render_ehs  # noqa: E402


@pytest.fixture(scope="module")
def m():
    return E.load_month()


@pytest.fixture(scope="module")
def e():
    return E.load()


@pytest.fixture(scope="module")
def r(m, e):
    return E.analyse(m, e, security_dir=SEC)


@pytest.fixture(scope="module")
def f():
    return E.page_data()


def test_committed_layer_is_current(tmp_path):
    seed = json.loads((ROOT / "data" / "sample" / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = G.EhsLayer(ROOT / "data" / "sample", seed, security_dir=SEC)
    G.write_ehs(layer, layer.run(), tmp_path, "data/sample, data/security")
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(p.name for p in LAYER.iterdir())
    for n in names:
        assert filecmp.cmp(tmp_path / n, LAYER / n, shallow=False), f"data/ehs/{n} is stale: run python scripts/generate_ehs.py"


def test_report_is_current(f):
    assert (ROOT / "reports" / "ehs.md").read_text(encoding="utf-8") == render_ehs.markdown(f)


def test_every_job_that_needs_a_permit_comes_from_the_records(m):
    J = E.jobs(m)
    by = {}
    for j in J:
        by[j["source"]] = by.get(j["source"], 0) + 1
    assert by == {"MOP": 9, "Maintenance": 4, "Work order": 6, "Milestone": 14}  # the VESDA test MOP needs no permit
    assert {j["id"]: j["permits"] for j in J if j["id"] in ("MOP-308", "MOP-310", "WO-41014", "PM-0018")} == {
        "MOP-308": ["eewp", "height"], "MOP-310": ["loto"], "WO-41014": ["loto"], "PM-0018": []}
    a07 = next(j for j in J if j["id"] == "MOP-310")
    assert a07["point"] == "TO-A07-A" and a07["device"] == ["2026-09-15T15:16:03Z", "2026-09-15T19:22:05Z"]


def test_findings_planted_and_as_found(r):
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert E.score(r["findings"], key) == {"planted": 4, "found": 4, "as_found": 1, "as_found_expected": 1, "false_positives": 0}
    assert sorted(k["kind"] for k in key if k["source"] == "planted") == ["closed_early", "lock_power", "no_permit", "untrained"]
    assert [x["id"] for x in r["findings"]] == [f"SAF-{n}" for n in range(1, 6)]


def test_the_a07_wrong_tapoff_is_found_from_the_records(r):
    """The B-side tap-off opened before any job on it existed: no permit can cover it. The dataset's own ground truth
    names the same breaker operation (critical work with no MOP) and PIR-2026-001 refers it to Customer EHS."""
    x = next(f for f in r["findings"] if "TO-A07-B" in f["refs"])
    assert x["kind"] == "no_permit" and x["at"] == "2026-09-15T15:42:11Z" and "WO-41023" in x["text"]
    gt = json.loads((ROOT / "data" / "sample" / "ground_truth" / "facility_planted_discrepancies.json").read_text(encoding="utf-8"))
    assert any(g["type"] == "critical_work_no_mop" and g["at"] == x["at"] for g in gt)
    pir = next(p for p in E.pir_screenings() if p["pir"] == "PIR-2026-001")
    assert pir["referred"] and "EHS-R2" in pir["screening"]


def test_each_check_says_what_its_rule_says(m, e, r):
    J = {j["id"]: j for j in r["jobs"]}
    P = {p["permit"]: p for p in e.permits}
    for x in r["findings"]:
        if x["kind"] == "lock_power":
            p = P[x["permit"]]
            s, en = (parse(t) for t in J[p["job"]]["device"])
            assert parse(p["lock_on"]) < s or parse(p["lock_off"]) > en
        elif x["kind"] == "closed_early":
            assert parse(P[x["permit"]]["closed"]) < E.work_end(J[x["job"]])
        elif x["kind"] == "untrained":
            assert any(not E.current(e.training, x["person"], "nfpa70e", parse(J[P[ref]["job"]]["start"]))
                       for ref in x["refs"][1:] if ref in P)
        elif x["kind"] == "no_permit" and x["job"]:
            assert not [p for p in e.permits if p["job"] == x["job"] and p["type"] == x["permit_type"]]
    for p in e.permits:                                      # every other lockout sits inside its device's isolation
        if p["type"] == "loto" and p["lock_on"] and J.get(p["job"], {}).get("device") \
                and not any(p["permit"] in x["refs"] for x in r["findings"]):
            s, en = (parse(t) for t in J[p["job"]]["device"])
            assert s <= parse(p["lock_on"]) < parse(p["lock_off"]) <= en


def test_agreements_hold_or_are_explained(r):
    assert [c.name for c in r["agreements"]] == ["permits", "lockout", "qualified", "closed"]
    for c in r["agreements"]:
        assert c.checked > 0 and len(c.misses) == r["explained"].get(c.name, 0), (c.name, c.misses)
    assert {c.name: c.checked for c in r["agreements"]} == {"permits": 39, "lockout": 13, "qualified": 50, "closed": 33}


def test_reported_events_are_never_findings(r, e):
    assert e.events and not any(x["event"] in f["refs"] for f in r["findings"] for x in e.events)
    assert {f["kind"] for f in r["findings"]} <= set(E.KINDS)


def test_monthly_report_by_partner(r, m):
    rep = r["report"]
    assert set(rep) == {"it", "landlord", "security"}
    assert rep["landlord"]["hours"] == 2016.0                 # 168 rostered 12-hour shifts, each with a badge-in
    for k, x in rep.items():
        assert x["trir"] == round(x["recordables"] * 200000 / x["hours"], 2)
    assert sum(x["permits"] for x in rep.values()) == len(E.load().permits)


def test_weekly_pack_sums_to_the_month(f, e):
    """Section 8's permits and reported events, week by week, add up to the month on the Safety view."""
    weeks = f["weeks"]
    assert len(weeks) == 4
    rep = f["report"]
    assert sum(w["permits"] for w in weeks) == sum(x["permits"] for x in rep.values())
    for k in ("near_miss", "stop_work", "first_aid"):
        assert sum(w[k] for w in weeks) == sum(x[k] for x in rep.values())
    for w in weeks:
        md = (ROOT / "docs" / "weekly").glob("*.md")
        assert any(f"**Permits issued:** {w['permits']}" in p.read_text(encoding="utf-8") for p in md)


def test_training_never_names_anyone(e):
    names = {p["name"] for p in E._csv(ROOT / "data" / "sample" / "vendor" / "personnel.csv")}
    text = (LAYER / "training.csv").read_text(encoding="utf-8") + (LAYER / "permits.csv").read_text(encoding="utf-8")
    assert not any(n in text for n in names)


def test_robustness_small():
    assert render_ehs.robustness(2) == 0
