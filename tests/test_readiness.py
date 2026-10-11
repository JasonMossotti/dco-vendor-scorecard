"""Hall C readiness: the commissioning record, the Customer's readiness gates, the first-compute forecast, the
pilot spares, and the record checks that find what was planted and nothing else."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import deployments as D  # noqa: E402
from scorecard import readiness as R  # noqa: E402
from scorecard.synthetic import readiness as G  # noqa: E402

REC = ROOT / "data" / "readiness"


@pytest.fixture(scope="module")
def built():
    return R.build()


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    """The same program with nothing planted: every natural record must pass every check."""
    d = tmp_path_factory.mktemp("clean")
    w = json.loads((ROOT / "data" / "sample" / "manifest.json").read_text(encoding="utf-8"))["window"]
    G.write_readiness(G.ReadinessRecordLayer(w["end"], w["seed"], plant=False).run(), d)
    return R.build(d)


def test_standard_work_resolves():
    assert R.validate(R.load_config(), D.load_config()["roles"]) == []


@pytest.mark.parametrize("break_it, expect", [
    (lambda c: c["levels"]["L4"].update(by="nobody"), "unknown role nobody"),
    (lambda c: c["gates"][4]["items"][0]["after"].append("R9-99"), "unknown dependency R9-99"),
    (lambda c: c["systems"][0]["levels"].reverse(), "levels out of order"),
    (lambda c: c["gates"][1]["items"][1].pop("spares"), "exactly one item must claim the spares"),
])
def test_validation_catches_broken_references(break_it, expect):
    c = copy.deepcopy(R.load_config())
    break_it(c)
    assert any(expect in e for e in R.validate(c, D.load_config()["roles"]))


def test_systems_come_from_the_site_model(built):
    """Every Hall C system with a product names the site model's product; the hall's counts match it."""
    from scorecard import site_model as S
    site = S.load_site()
    hall = S.hall_by_id(site, "HALL-C")
    ids = [s["id"] for s in built["systems"]]
    assert sum(i.startswith("MVS-C") for i in ids) == hall["power"]["mvsst_count"]
    assert sum(i.startswith("CDU-C") for i in ids) == hall["cooling"]["cdu_count"]
    assert sum(i.startswith("CRAH-C") for i in ids) == hall["cooling"]["electrical_room_crah_count"]
    assert built["program"]["racks"] == 8 and hall["state"] == "planned"
    assert next(s for s in built["systems"] if s["id"] == "ESS-C")["model"] == "Per pilot submittal (generic)"


def test_committed_record_is_current(tmp_path):
    sample = sorted((ROOT / "data" / "sample").rglob("*"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sample if p.is_file()}
    import generate_readiness
    generate_readiness.generate(tmp_path)
    for p in sorted(tmp_path.rglob("*")):
        if p.is_file():
            rel = p.relative_to(tmp_path)
            assert p.read_bytes() == (REC / rel).read_bytes(), f"{rel} is stale: run python scripts/generate_readiness.py"
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sample if p.is_file()}, "data/sample was written"


def test_checks_find_every_planted_record_and_nothing_else(built):
    c = built["self_check"]
    assert (c["detected"], c["planted"], c["false_positives"]) == (4, 4, [])
    assert {f["kind"] for f in built["findings"]} == set(R.load_config()["checks"]) and len(built["findings"]) == 4


def test_a_clean_program_has_no_findings(clean):
    """Retests that pass, Category 2 issues open at a pass, and signatures the same day after the run are in the
    natural record; none is a finding."""
    assert clean["findings"] == [] and clean["self_check"]["planted"] == 0
    d = clean["self_check"]["decoys"]
    assert d["retested_then_passed"] > 0 and d["cat2_open_at_pass"] > 0


def test_findings_name_the_records_to_compare(built):
    by = {f["kind"]: f for f in built["findings"]}
    assert by["passed_open_cat1"]["refs"][1].startswith("CXI-C-") and "cannot pass" in by["passed_open_cat1"]["text"]
    assert "Customer witness signature" in by["signed_before_run"]["text"] and "hours before" in by["signed_before_run"]["text"]
    assert "the level below it" in by["out_of_sequence"]["text"]
    assert by["spares_short"]["ref"] == "R1-02" and by["spares_short"]["party"] == "IT Partner" and "of 24" in by["spares_short"]["text"]


def test_checks_never_read_the_answer_key():
    for fn in (R.checks, R.forecast, R.load_record):
        assert "answer_key" not in inspect.getsource(fn)


def test_planting_has_its_own_stream():
    src = inspect.getsource(G.ReadinessRecordLayer)
    assert ':readiness:planted"' in src and "self.prng" in inspect.getsource(G.ReadinessRecordLayer._plant)


def test_record_is_ordered_and_signed_in_order(clean):
    """In the natural record a level passes only after the level below it, signatures follow the passing run in
    the level's order, and a Category 1 is closed before its retest passes."""
    cfg = R.load_config()
    for sc in clean["scripts"]:
        if not sc["passed_at"]:
            assert not sc["signatures"]
            continue
        roles = [g["role"] for g in sc["signatures"]]
        assert roles == cfg["levels"][sc["level"]]["sign"]
        times = [g["signed_at"] for g in sc["signatures"] if g["signed_at"]]
        assert times == sorted(times) and all(t > sc["passed_at"] for t in times)


def test_first_compute_forecast_follows_the_slipped_energy_storage(built):
    fc = built["forecast"]
    assert fc["critical_path"][:4] == [f"CX-C-ESS-C-L{n}" for n in range(1, 5)]
    assert fc["critical_path"][4] == "CX-C-HALL-L5" and fc["critical_path"][-1] == "R4-03"
    ess = next(s for s in built["scripts"] if s["id"] == "CX-C-ESS-C-L1")
    assert ess["scheduled"] > built["program"]["as_of"][:10] > ess["planned"]
    assert fc["first_compute"] == fc["finish"]["R4-03"] and fc["slip_days"] == 1


def test_nobody_is_named_in_the_record():
    text = "".join(p.read_text(encoding="utf-8") for p in REC.iterdir())
    assert "assigned" not in text and "@" not in text
    roles = set(D.load_config()["roles"])
    for sc in json.loads((REC / "cx_scripts.json").read_text(encoding="utf-8")):
        assert all(g["role"] in roles for g in sc["signatures"])


def test_robustness_small(capsys):
    """Readiness checks across generated months, without building the full datasets."""
    from datetime import date, timedelta
    import tempfile
    for k in range(5):
        with tempfile.TemporaryDirectory() as tmp:
            as_of = (date(2025, 2, 3) + timedelta(weeks=4 * k)).isoformat() + "T00:00:00Z"
            G.write_readiness(G.ReadinessRecordLayer(as_of, 2000 + k).run(), Path(tmp))
            c = R.build(Path(tmp))["self_check"]
            assert (c["detected"], c["planted"], c["false_positives"]) == (4, 4, []), k
