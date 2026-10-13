"""Security Partner: its SLA, the security layer on its own stream, the engine, and the scorecard."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard.engine.evaluate import evaluate_security
from scorecard.engine.security import build_security_scorecard, measure_security, run_security
from scorecard.sla_model import PARTNER_FILES, load_interface_agreement, load_sla
from scorecard.synthetic.security import KEY, PLANTED_TYPES, SecurityLayer, generate

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
SEC = ROOT / "data" / "security"
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def sla():
    return load_sla(PARTNER_FILES["security"])


@pytest.fixture(scope="module")
def result(sla):
    return run_security(sla, SAMPLE, SEC)


@pytest.fixture(scope="module")
def sc(sla, result):
    return build_security_scorecard(sla, result)


def test_security_layer_is_current(tmp_path):
    generate(SAMPLE, tmp_path, "data/sample")
    for p in sorted(x for x in tmp_path.rglob("*") if x.is_file()):
        rel = p.relative_to(tmp_path)
        assert p.read_bytes() == (SEC / rel).read_bytes(), f"{rel} is stale: run python scripts/generate_security.py"


def test_security_layer_reads_the_sample_and_never_writes_it():
    before = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    SecurityLayer(SAMPLE, 2026).run()
    assert before == {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}


def test_layer_has_its_own_stream():
    """A different seed moves the security records; the sample records it reads are the same."""
    a, b = SecurityLayer(SAMPLE, 1).run(), SecurityLayer(SAMPLE, 2).run()
    assert a["door_alarms.jsonl"] != b["door_alarms.jsonl"]
    assert [x["ticket"] for x in a["tray_drives.csv"]] == [x["ticket"] for x in b["tray_drives.csv"]]


def test_escorts_and_trays_come_from_the_existing_records():
    import csv
    ins = {(r["person_id"], r["door"]) for r in csv.DictReader((SAMPLE / "access" / "badge_events.csv").open(encoding="utf-8"))}
    ins |= {(r["person_id"], "HALL-" + r["reader"][-1]) for r in csv.DictReader((SAMPLE / "access" / "landlord_badge_events.csv").open(encoding="utf-8"))}
    visits = list(csv.DictReader((SEC / "visits.csv").open(encoding="utf-8")))
    assert visits and all((v["escort"], v["hall"]) in ins for v in visits)
    trays = {r["serial"] for r in csv.DictReader((SAMPLE / "vendor" / "rma_shipments.csv").open(encoding="utf-8")) if r["fru"] == "Compute tray"}
    drives = list(csv.DictReader((SEC / "tray_drives.csv").open(encoding="utf-8")))
    assert {d["tray_serial"] for d in drives} == trays and len(drives) == 8 * len(trays)


def test_engine_finds_every_planted_discrepancy(result):
    ev = evaluate_security(result.findings, SEC)
    assert (ev.detected, ev.planted, len(ev.false_positives)) == (4, 4, 0)
    assert sorted(ev.by_type) == sorted(PLANTED_TYPES)


def test_engine_never_reads_the_answer_key(sla, tmp_path):
    import shutil
    shutil.copytree(SEC, tmp_path / "security")
    (tmp_path / "security" / KEY).unlink()
    assert len(run_security(sla, SAMPLE, tmp_path / "security").findings) == 4


def test_headline(sc):
    assert sc["defaults"] == ["SEC-CSL-03", "SEC-CSL-06"] and sc["credits"]["payable"] == 12276
    assert sc["findings"] == 4 and sc["s1"] == 4
    reported = {r["id"]: r["vendor_reported"] for r in sc["csl"]}
    assert reported["SEC-CSL-03"] == reported["SEC-CSL-06"] == 100.0, "the self-report claims every level met"


def test_small_sample_rule_defaults_one_unescorted_visitor(sc):
    r = next(x for x in sc["csl"] if x["id"] == "SEC-CSL-03")
    assert r["status"] == "below_minimum" and "Small-sample rule" in r["note"]


def test_weeks_add_up_to_the_month(result):
    """Events count in the week they began: the weekly counts add up to the month's."""
    from datetime import timedelta
    ctx = result.context
    month = measure_security(result)
    for cid in ("SEC-CSL-02", "SEC-CSL-03", "SEC-CSL-06"):
        weeks = [measure_security(result, ctx.window_start + timedelta(days=7 * k), ctx.window_start + timedelta(days=7 * (k + 1)))
                 for k in range(4)]
        assert sum(w[cid]["events"] or 0 for w in weeks) == month[cid]["events"], cid
        assert sum(w[cid]["misses"] or 0 for w in weeks) == month[cid]["misses"], cid


def test_interface_agreement_adds_the_security_partner():
    ia = load_interface_agreement()
    assert ia["raci_parties"][-1] == "Security Partner" and "security_partner" in ia["parties"]
    rows = {r["component"]: r for r in ia["raci"]}
    mine = [c for c, r in rows.items() if r["Security Partner"] == "R"]
    assert len(mine) == 6 and all(rows[c]["Customer"] == "A" for c in mine), "the Customer owns the policy; the Security Partner runs it"
    assert {d["id"] for d in ia["demarcations"]} >= {"DM-SEC"} and "HO-5" in {h["id"] for h in ia["handoffs"]}


def test_media_rule_is_the_same_in_every_contract(sla):
    """The common terms already say media never leaves intact; the Security SLA names the standard and HO-5."""
    assert any("NIST SP 800-88" in x for x in [sla["media_destruction"]["standard"]])
    assert any("HO-5" in r for r in sla["media_destruction"]["rules"])


def test_reports_are_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_security.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_findings_name_no_one_but_ids():
    text = (ROOT / "reports" / "security_discrepancy_report.md").read_text(encoding="utf-8")
    names = {r.split(",")[1] for r in (SAMPLE / "vendor" / "personnel.csv").read_text(encoding="utf-8").splitlines()[1:]}
    assert not any(n in text for n in names)
    assert json.loads((ROOT / "reports" / "security_scorecard.json").read_text(encoding="utf-8"))["supplier"] == "Llano Gate Protective Services, LLC"
