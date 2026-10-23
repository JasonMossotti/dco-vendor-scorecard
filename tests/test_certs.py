"""Certification register and work gate (/training/): every person's credentials against every badge-verified shift and
every record that names who did the work, four planted record problems, the EHS lapse as found, KM-15, the staffing
service levels recalculated with the qualification rule, renewal notices, and the Training page."""

import filecmp
import json
import re
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from scorecard import certifications as C
from scorecard import ehs as E
from scorecard.change_calendar import parse
from scorecard.synthetic import certs as G

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "data" / "certs"
SEC = ROOT / "data" / "security"
EHS = ROOT / "data" / "ehs"
sys.path.insert(0, str(ROOT / "scripts"))

import render_certs  # noqa: E402


@pytest.fixture(scope="module")
def site():
    return C.load_site()


@pytest.fixture(scope="module")
def reg():
    return C.load()


@pytest.fixture(scope="module")
def r(site, reg):
    return C.analyse(site, reg)


@pytest.fixture(scope="module")
def f():
    return C.page_data()


@pytest.fixture(scope="module")
def key():
    return json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))


def test_committed_layer_is_current(tmp_path):
    seed = json.loads((ROOT / "data" / "sample" / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = G.CertsLayer(ROOT / "data" / "sample", seed, SEC, EHS)
    G.write_certs(layer, layer.run(), tmp_path, "data/sample, data/security, data/ehs")
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(p.name for p in LAYER.iterdir())
    for n in names:
        assert filecmp.cmp(tmp_path / n, LAYER / n, shallow=False), f"data/certs/{n} is stale: run python scripts/generate_certs.py"


def test_report_is_current(f):
    assert (ROOT / "reports" / "certifications.md").read_text(encoding="utf-8") == render_certs.markdown(f)


def test_every_person_and_every_role_credential_is_on_file(site, reg):
    cfg, ehs_cfg = C.config(), E.config()
    who = C.people(site)
    assert len(who) == 74
    assert {p for p, (pt, _) in who.items() if pt == "security"} == {g["guard_id"] for g in site.guards}
    planted = {(k["ref"], k["credential"]) for k in json.loads((LAYER / "answer_key.json").read_text()) if k["kind"] == "never_held"}
    for person, (partner, role) in who.items():
        for c in C.role_needs(cfg, ehs_cfg, partner, role):
            assert reg.last(person, c) or (person, c) in planted, (person, c)


def test_the_register_reads_ehs_training_and_never_copies_it(reg):
    ehs = E._csv(EHS / "training.csv")
    rows = [x for x in reg.rows if x["source"] == "ehs"]
    assert len(rows) == len(ehs)
    own = {x["credential"] for x in reg.rows if x["source"] == "register"}
    assert own <= set(C.config()["credentials"]) and not own & set(E.config()["courses"])


def test_no_natural_lapse_inside_the_month(site, reg, key):
    """Outside the planted cases, everything on file is current through the month (the notices fall after it)."""
    planted = {(k["ref"], k["credential"]) for k in key if k["kind"] in ("lapsed", "never_held")}
    for x in reg.rows:
        if (x["person"], x["credential"]) in planted:
            continue
        assert parse(x["completed"]) < site.m.start
        assert not x["expires"] or parse(x["expires"]) > site.m.end, x


def test_shifts_follow_the_staffing_rules_and_records_name_their_person(site, r):
    S = [x for x in r["work"] if x["source"] in C.SHIFT_SOURCES]
    W = [x for x in r["work"] if x["source"] not in C.SHIFT_SOURCES]
    assert {x["source"] for x in S} == {"it_shift", "ll_shift", "post_shift"}
    assert {x["source"] for x in W} >= {"incident", "work_order", "pm", "destruction"}
    by = {t["number"]: t for t in site.tickets}
    for x in W:
        if x["source"] == "incident":
            assert by[x["ref"]]["assigned_to"] == x["person"]
            assert "esd" in x["needs"] or "liquid" in x["needs"]
    assert all(site.m.start <= parse(x["at"]) < site.m.end for x in r["work"])


def test_planted_cases_found_and_nothing_else(r, key):
    sc = C.score(r["findings"], key)
    assert sc == {"planted": 5, "found": 5, "as_found": 1, "as_found_expected": 1, "false_positives": 0}
    kinds = sorted(f["kind"] for f in r["findings"])
    assert kinds == ["lapsed", "lapsed", "lapsed", "lapsed", "never_held", "report"]


def test_each_agreement_holds_or_is_explained(r):
    for c in r["agreements"]:
        assert c.checked > 0
        assert len(c.misses) == r["explained"].get(c.name, 0), c.name


def test_findings_are_records_not_judgments(r):
    for f in r["findings"]:
        assert f["id"].startswith("CRT-") and f["action"]
        for w in ("lied", "fraud", "falsif", "dishonest"):
            assert w not in f["text"].lower()


def test_the_ehs_lapse_is_corroborated_not_counted_twice(r):
    saf = {x["person"]: x["id"] for x in E.analyse(E.load_month(), E.load(), security_dir=SEC)["findings"] if x.get("person")}
    hits = [f for f in r["findings"] if f["person"] in saf and f["credential"] == "nfpa70e"]
    assert len(hits) == 1 and hits[0]["corroborates"] == saf[hits[0]["person"]]


def test_a_guards_finding_names_the_guard_file(r):
    g = [f for f in r["findings"] if f["partner"] == "security" and f["kind"] != "report"]
    assert g and all(x.get("guard_file") == "current" and "guard file" in x["text"] for x in g)
    assert all(x["credential"] in C.config()["roles"]["security"]["guard"] for x in g)


def test_the_it_report_leaves_out_what_the_register_shows(r, reg):
    rep = next(f for f in r["findings"] if f["kind"] == "report")
    assert rep["partner"] == "it" and rep["missing"] and not rep["extra"]
    said = next(x for x in reg.reported if x["partner"] == "it")["lapsed"].split(";")
    assert not set(rep["missing"]) & set(said)


def test_km15_is_the_it_partners_shifts_and_reaches_the_scorecard(site, reg, r):
    k = C.km15(site, reg, r["work"])
    shifts = [x for x in r["work"] if x["source"] == "it_shift"]
    bad = [x for x in shifts if x["missing"]]
    assert k["events"] == len(shifts) and k["misses"] == len(bad) and 0 < k["actual"] < 100
    sc = json.loads((ROOT / "reports" / "scorecard.json").read_text(encoding="utf-8"))
    row = next(x for x in sc["km"] if x["id"] == "KM-15")
    assert row["actual"] == k["actual"] and row["met"] is False
    assert C.km15_for(ROOT / "data" / "quarter" / "2026-07-06") is None      # only the month the register was built from


def test_published_staffing_equals_each_scorecard_and_headlines_hold(f):
    rep = {"CSL-10": "scorecard.json", "OT-CSL-09": "landlord_scorecard.json", "SEC-CSL-01": "security_scorecard.json"}
    for s in f["staffing"]:
        sc = json.loads((ROOT / "reports" / rep[s["csl"]]).read_text(encoding="utf-8"))
        row = next(x for x in sc["csl"] if x["id"] == s["csl"])
        assert abs(row["actual"] - s["published"]) < 1e-6, s["csl"]
        assert row["status"] == s["published_status"]
        assert s["adjusted"] <= s["published"] and s["people"]
    it = json.loads((ROOT / "reports" / "scorecard.json").read_text(encoding="utf-8"))
    assert it["credits"]["payable"] == 188700 and it["totals"]["defaults"] == 4
    sec = json.loads((ROOT / "reports" / "security_scorecard.json").read_text(encoding="utf-8"))
    assert sec["credits"]["payable"] == 12276 and sec["defaults"] == ["SEC-CSL-03", "SEC-CSL-06"]


def test_renewal_notices(f):
    N = C.config()["notices"]
    as_of = parse(f["as_of"])
    assert f["notices"] and all(0 <= n["days"] < N["horizon_days"] for n in f["notices"])
    for n in f["notices"]:
        assert [x["lead"] for x in n["notices"]] == N["lead_days"]
        exp = parse(n["expires"])
        due = [x["lead"] for x in n["notices"] if exp - timedelta(days=x["lead"]) <= as_of]
        assert n["stage"] == (min(due) if due else None)
        for addr in (n["to"], n["cc"]):   # reserved example domains only (RFC 2606)
            assert re.fullmatch(r"[\w.-]+@(?:[\w-]+\.)*example\.com", addr), addr


def test_bench_reads_the_forward_schedule(f):
    sched = json.loads((ROOT / "data" / "calendar" / "schedule.json").read_text(encoding="utf-8"))
    assert f["bench"] and {b["id"] for b in f["bench"]} <= {j["id"] for j in sched}
    assert all(b["holders"] >= 0 and b["names"] for b in f["bench"])


def test_people_are_ids_only(f):
    import csv
    names = {p["name"] for p in csv.DictReader((ROOT / "data" / "sample" / "vendor" / "personnel.csv").open(encoding="utf-8"))}
    text = json.dumps(f) + (ROOT / "reports" / "certifications.md").read_text(encoding="utf-8")
    assert not [n for n in names if n in text]


def test_security_sla_requires_level_three_armed_guards():
    from scorecard.sla_model import PARTNER_FILES, load_sla
    sla = load_sla(PARTNER_FILES["security"])
    q = " ".join(sla["posts"]["qualifications"])
    assert "Level III" in q and "SA (handgun)" in q and "STG (shotgun)" in q and "MMPI" in q
    assert "never enters a data hall" in sla["posts"]["armed_posts"]["rule"]
    doc = (ROOT / "docs" / "sla" / "SECURITY_SLA.md").read_text(encoding="utf-8")
    assert "**Armed posts:**" in doc


def test_robustness_small():
    assert render_certs.robustness(2) == 0


def test_training_page_builds_and_works(tmp_path):
    import render_training
    html = render_training.html_page()
    assert "__DATA__" not in html and 'data-tab="training" class="on"' in html
    out = tmp_path / "training.html"
    out.write_text(html, encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "training_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
