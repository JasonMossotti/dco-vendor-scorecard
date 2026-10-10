"""Energy meters and the PUE report: the numbers reconcile, the planted cases are found, the page works."""

import filecmp
import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard import energy as N
from scorecard.synthetic import energy as E

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
ENERGY = ROOT / "data" / "energy"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_energy  # noqa: E402
import render_energy  # noqa: E402


@pytest.fixture(scope="module")
def data():
    return N.load(ENERGY)


@pytest.fixture(scope="module")
def res(data):
    return N.analyse(data)


def test_committed_energy_data_is_current(tmp_path):
    generate_energy.generate(tmp_path)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            rel = f.relative_to(tmp_path)
            assert filecmp.cmp(f, ENERGY / rel, shallow=False), f"{rel} is stale; run scripts/generate_energy.py"


def test_report_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_energy.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_energy_layer_reads_the_sample_and_never_writes_it(tmp_path):
    """Own random stream: generating twice gives the same meters, and data/sample is not touched."""
    before = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    a = E.EnergyLayer(SAMPLE, window["seed"]).run("none")
    b = E.EnergyLayer(SAMPLE, window["seed"]).run("none")
    assert a["meters"] == b["meters"]
    assert before == {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    src = inspect.getsource(E.EnergyLayer.__init__)
    assert ':energy"' in src, "the meters draw from their own random stream"


def test_meters_balance(data):
    """Every hour: UPS output at most input, and the submeters sum to just under the revenue meters."""
    for r in data.meters:
        for h in ("a", "b"):
            assert r[f"ups_out_{h}_kwh"] < r[f"ups_in_{h}_kwh"], r["hour"]
        sub = sum(r[f"ups_in_{h}_kwh"] for h in "ab") + r["chillers_kwh"] + r["pumps_kwh"] + r["crah_kwh"] \
            + r["mech_a_kwh"] + r["mech_b_kwh"] + r["house_kwh"]
        site = r["utility_kwh"] + r["generator_kwh"]
        assert 0.0 < (site - sub) / site < 0.02, r["hour"]
    assert len(data.meters) == 28 * 24


def test_it_energy_follows_the_racks(data):
    """IT energy is the UPS output: each hall's racks' input power from the GPU telemetry, plus busway losses."""
    el = E.EnergyLayer(SAMPLE, 0, rack_hourly=ROOT / "data" / "telemetry" / "gpu" / "rack_hourly.csv")
    racks = el.rack_it_kwh()
    for r in data.meters:
        for h in "ab":
            rack = racks.get(r["hour"], {}).get(h.upper(), 0.0)
            out = r[f"ups_out_{h}_kwh"]
            assert rack <= out + 0.1 and out <= rack * 1.01 + 0.1, (r["hour"], h, rack, out)
    it_mw = sum(r["ups_out_a_kwh"] + r["ups_out_b_kwh"] for r in data.meters) / len(data.meters) / 1000
    assert 2.0 < it_mw < 6.0, "Hall A full, Hall B still deploying"


def test_generator_energy_only_during_the_outage(data):
    gen = [r for r in data.meters if r["generator_kwh"] > 0]
    assert 0 < len(gen) <= 3, "the A07 outage, an hour or two"
    assert all(r["hour"].startswith("2026-09-24") for r in gen)


def test_weeks_reconcile_with_the_month(res):
    for k in ("facility_kwh", "it_kwh", "cooling_kwh", "power_loss_kwh", "other_kwh"):
        assert sum(w[k] for w in res.weeks) == pytest.approx(res.month[k], rel=1e-12), k
    assert sum(d["it_kwh"] for d in res.days) == pytest.approx(res.month["it_kwh"], rel=1e-12)
    assert len(res.weeks) == 4 and len(res.days) == 28
    m = res.month
    assert m["pue"] == pytest.approx(m["ppue_cooling"] + m["ppue_power"] + m["other_per_it"] - 1)


def test_weekly_pack_energy_line_matches_the_report(res):
    """The weekly packs' week and month-to-date PUE are the PUE report's numbers."""
    from scorecard.weekly import WeeklyData, build_all
    packs = build_all(WeeklyData(SAMPLE))
    assert [p["energy"]["week"]["pue"] for p in packs] == [round(w["pue"], 4) for w in res.weeks]
    assert packs[-1]["energy"]["mtd"]["pue"] == round(res.month["pue"], 4)
    assert packs[-1]["energy"]["mtd"]["facility_kwh"] == round(res.month["facility_kwh"], 1)
    assert packs[0]["energy"]["mtd"] == packs[0]["energy"]["week"]


def test_52_weeks_and_the_kpi(res):
    assert len(res.periods) == 13 and res.periods[-1]["month"] and not any(p["month"] for p in res.periods[:-1])
    assert res.year["days"] == 364
    assert sum(p["it_kwh"] for p in res.periods) == pytest.approx(res.year["it_kwh"], rel=1e-9)
    assert res.kpi["id"] == "OT-EN-02" and res.kpi["actual"] == res.year["pue"]
    assert not res.kpi["met"], "fixed overhead over a half-built IT load: the 52-week PUE misses 1.35"
    winter = min(res.periods, key=lambda p: p["outdoor_c"])
    summer = max(res.periods, key=lambda p: p["outdoor_c"])
    assert winter["ppue_cooling"] < summer["ppue_cooling"], "free cooling in winter"


def test_sample_findings(res):
    ids = {f.id: f for f in res.findings}
    assert sorted(ids) == ["EN-F1", "EN-F2"]
    f1, f2 = ids["EN-F1"], ids["EN-F2"]
    assert f1.type == "report_mismatch" and f1.detail["cause"] == "ups_input_as_it" and f1.refs == ["OT-EN-01", "OT-EN-02"]
    assert f1.detail["reported_pue"] < f1.detail["metered_pue"], "the report flatters the site"
    assert f2.type == "free_cooling_lockout" and f2.detail["chiller"] == "CH-03" and f2.refs == ["OT-EN-03"]
    assert f2.extra_kwh > 0


def test_short_maintenance_lockouts_are_not_findings(res):
    short = [s for s in res.lockouts if (E.parse(s["end"]) - E.parse(s["start"])).total_seconds() < 24 * 3600]
    assert len(short) >= 2
    flagged = {f.detail["chiller"] for f in res.findings if f.type == "free_cooling_lockout"}
    assert not ({s["chiller"] for s in short} & flagged)


def test_the_checks_never_read_the_answer_key():
    for fn in (N.analyse, N.check_report, N.check_lockouts, N.check_unmetered, N.lockouts, N.lockout_cost):
        assert ".key" not in inspect.getsource(fn), fn.__name__


def test_sample_self_check(res, data):
    ev = N.evaluate(res, data.key)
    assert (ev.planted, ev.detected, ev.false_positives, ev.cause_named) == (2, 2, [], 1)


def test_landlord_credits_unchanged_by_the_energy_terms():
    """PUE is a Key Measurement with no credits: the Landlord's credits stay $106,200."""
    from scorecard.sla_model import PARTNER_FILES, load_sla
    sla = load_sla(PARTNER_FILES["landlord"])
    terms = N.energy_terms(sla)
    assert sorted(terms) == ["OT-EN-01", "OT-EN-02", "OT-EN-03"]
    assert all(not t.get("credits") for t in terms.values())
    assert terms["OT-EN-02"]["target"] == 1.35
    import render_hub
    assert render_hub.facts()["ll"]["credits"] == 106200


def test_dst_offset_is_computed():
    from datetime import datetime, timezone
    assert E.utc_offset_h(datetime(2026, 1, 15, tzinfo=timezone.utc)) == -6
    assert E.utc_offset_h(datetime(2026, 7, 15, tzinfo=timezone.utc)) == -5
    assert E.utc_offset_h(datetime(2026, 3, 8, 7, 59, tzinfo=timezone.utc)) == -6
    assert E.utc_offset_h(datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc)) == -5
    assert E.utc_offset_h(datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)) == -6


def test_robustness_small_sample(capsys):
    assert render_energy.robustness(1) == 0, capsys.readouterr().out


def test_interactive_page_builds_and_works(tmp_path):
    out = tmp_path / "energy.html"
    html = render_energy.html_page()
    assert "__DATA__" not in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    out.write_text(html, encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "energy_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
