"""Predictive maintenance: the condition history (its own random stream), the four detectors, the backtest scored from
the records, the planted wear-outs found from the answer key, the deployable command, and the generated report."""

import csv
import filecmp
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREDICT = ROOT / "data" / "predict"
HISTORY = ROOT / "data" / "history"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_predict  # noqa: E402
import render_predict  # noqa: E402
from scorecard.predict import detectors as D  # noqa: E402
from scorecard.predict import methods as M  # noqa: E402
from scorecard.predict import review as R  # noqa: E402
from scorecard.synthetic.predict import write_predict  # noqa: E402


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("predict")
    watched = [p for d in (HISTORY, ROOT / "data" / "sample", ROOT / "data" / "telemetry" / "cdu") for p in d.rglob("*") if p.is_file()]
    before = {p: p.stat().st_mtime_ns for p in watched}
    write_predict(generate_predict.generate(), tmp)
    return tmp, before == {p: p.stat().st_mtime_ns for p in watched}


@pytest.fixture(scope="module")
def bt():
    return R.backtest()


def test_committed_history_is_current_and_nothing_else_written(regenerated):
    out, untouched = regenerated
    assert untouched, "generating the condition history must not write the failure history, the sample, or the CDU telemetry"
    files = sorted(p.name for p in out.iterdir())
    assert files == sorted(p.name for p in PREDICT.iterdir())
    for f in files:
        assert filecmp.cmp(out / f, PREDICT / f, shallow=False), f"data/predict/{f} is stale: run python scripts/generate_predict.py"


def test_report_is_current():
    assert (ROOT / "reports" / "predictive_maintenance.md").read_text(encoding="utf-8") == render_predict.markdown(render_predict.prepare())


def test_detectors_never_read_the_answer_key(bt, tmp_path):
    for f in ("detectors.py", "methods.py"):
        assert "answer_key" not in (ROOT / "src" / "scorecard" / "predict" / f).read_text(encoding="utf-8")
    blind = tmp_path / "predict"
    shutil.copytree(PREDICT, blind)
    (blind / "answer_key.json").unlink()
    again = R.backtest(blind)
    assert again["requests"] == bt["requests"] and R.summary(again, R.config()) == R.summary(bt, R.config())


def test_backtest_headline(bt):
    s = R.summary(bt, R.config())
    assert (s["optics"]["failures"], s["optics"]["scored"], s["optics"]["too_early"], s["optics"]["warned"]) == (112, 108, 4, 69)
    assert s["optics"]["median_lead_days"] == 10.0
    assert (s["gpu_memory"]["failures"], s["gpu_memory"]["warned"], s["gpu_memory"]["after_the_fact"]) == (68, 36, 16)
    assert s["gpu_memory"]["median_lead_days"] == 4.6
    assert (s["cdu_filter"]["failures"], s["cdu_filter"]["warned"], s["cdu_filter"]["median_lead_days"]) == (1, 1, 29.5)
    assert (s["cdu_pump"]["failures"], s["cdu_pump"]["warned"], s["cdu_pump"]["median_lead_days"]) == (2, 1, 28.7)
    assert all(v["false_alarms"] == 0 for v in s.values())
    assert len(bt["requests"]) == 107
    assert [r["id"] for r in bt["requests"]] == [f"PDM-{i:04d}" for i in range(1, 108)]


def test_every_planted_wear_out_is_warned_and_no_decoy_flagged(bt):
    key = json.loads((PREDICT / "answer_key.json").read_text(encoding="utf-8"))
    s = R.score(bt, key, R.config())
    assert s["optics"] == {"planted": 69, "warned": 69, "far_end": 0, "missed": [], "sudden_warned": 0, "false_alarms": 0, "steps_flagged": 0}
    assert s["gpu_memory"] == {"planted": 36, "warned": 36, "too_early": 0, "false_alarms": 0}
    assert s["cdu_filter"] == {"planted": 1, "warned": 1, "false_alarms": 0}
    assert s["cdu_pump"] == {"planted": 1, "warned": 1, "sudden_warned": 0, "false_alarms": 0}


def test_work_requests_go_to_the_party_that_does_the_work(bt):
    owner = {r["detector"]: r["owner"]["responsible"] for r in bt["requests"]}
    assert owner == {"optics": "IT Partner", "gpu_memory": "IT Partner", "cdu_filter": "Landlord", "cdu_pump": "Landlord"}
    for r in bt["requests"]:
        assert r["evidence"] and r["due_by"] >= r["flagged"][:10] and r["outcome"]
        assert "lied" not in r["evidence"] + r["outcome"]


def test_command_on_the_exported_history_equals_the_backtest(bt, tmp_path):
    out = tmp_path / "out"
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "predict.py"), "--demo", "--out", str(out)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = list(csv.DictReader((out / "work_requests.csv").open(encoding="utf-8")))
    assert [(r["id"], r["detector"], r["device"], r["flagged"], r["due_by"]) for r in rows] == \
        [(r["id"], r["detector"], r["device"], r["flagged"], r["due_by"]) for r in bt["requests"]]
    assert {r["owner_party"] for r in rows} == {"IT Partner", "Landlord"}
    for f in ("optic_dom.csv", "gpu_memory.csv", "gpu_xids.csv", "cdu_readings.csv", "cdu_events.csv"):
        assert (out / "inputs" / f).exists(), f
    since = subprocess.run([sys.executable, str(ROOT / "scripts" / "predict.py"), "--source", str(out / "inputs"), "--out", str(tmp_path / "s"),
                            "--since", "2026-08-01"], capture_output=True, text=True)
    assert since.returncode == 0, since.stdout + since.stderr
    later = list(csv.DictReader((tmp_path / "s" / "work_requests.csv").open(encoding="utf-8")))
    assert later and len(later) < len(rows) and all(r["flagged"] >= "2026-08-01" for r in later)


def test_command_with_no_inputs_says_so(tmp_path):
    (tmp_path / "empty").mkdir()
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "predict.py"), "--source", str(tmp_path / "empty"), "--out", str(tmp_path / "o")],
                          capture_output=True, text=True)
    assert proc.returncode == 1 and "No input files" in proc.stdout


def test_sample_month_now():
    n = R.now()
    assert n["as_of"] == "2026-09-27"
    assert all(f["state"] == "healthy" for f in n["cdu_filter"]) and len(n["cdu_filter"]) == 8
    assert sorted(f["cdu"] for f in n["cdu_filter"] if f["overdue"]) == ["CDU-A1", "CDU-A2"]
    assert len(n["cdu_pump"]) == 16 and all(p["state"] == "healthy" for p in n["cdu_pump"])
    failed = sorted((p["cdu"], p["pump"]) for p in n["cdu_pump"] if p["failures"])
    assert failed == [("CDU-A2", 2), ("CDU-B3", 2)] and not any(p["warned"] for p in n["cdu_pump"] if p["failures"])
    assert [(g["host"], g["gpu"]) for g in n["gpu_memory"] if not g["xid_before"] and not g["xid_after"]] == [("a16-ct18", 2)]


def test_filter_history_meets_the_sample_month():
    """The condition history ends where the sample's CDU telemetry starts, at the same filter pressure drop."""
    h = list(csv.DictReader((PREDICT / "cdu_condition.csv").open(encoding="utf-8")))
    s = list(csv.DictReader((ROOT / "data" / "telemetry" / "cdu" / "cdu_hourly.csv").open(encoding="utf-8")))

    def level(r):
        return float(r["filter_dp_kpa"]) / (float(r["flow_lpm"]) / 1800) ** 2
    for cdu in sorted({r["cdu"] for r in h}):
        a = [r for r in h if r["cdu"] == cdu][-1]
        b = next(r for r in s if r["cdu"] == cdu)
        assert abs(level(a) - level(b)) < 0.5, cdu


def test_fleet_outlook():
    f = R.fleet()
    assert f["optics"]["fit"]["beta"] == 1.032 and f["optics"]["expected"] == 18.9 and tuple(f["optics"]["range"]) == (12, 26)
    assert f["gpu_memory"]["per_1000_gpu_months"] == 4.86 and f["gpu_memory"]["expected"] == 11.2


def test_weekly_line_agrees_with_now():
    w = R.week_line(R.now())
    assert w["filters"] == {"healthy": 8, "of": 8, "act": [], "watch": [], "due_by_calendar": ["CDU-A1", "CDU-A2"]}
    assert w["pumps"] == {"healthy": 16, "of": 16, "not_healthy": []} and w["gpu_watch"] == ["a16-ct18 GPU 2"]


def test_small_robustness():
    """Two generated histories, every planted wear-out moved: all warned in time, no false alarms."""
    from generate_history import generate as gen_history
    from scorecard.synthetic.history import write_history
    import tempfile
    cfg = R.config()
    for seed in (3, 8):
        with tempfile.TemporaryDirectory() as d:
            h, p = Path(d) / "history", Path(d) / "predict"
            write_history(gen_history(seed, vary=True), h)
            data = generate_predict.generate(h, seed, vary=True)
            write_predict(data, p)
            s = R.score(R.backtest(p, h, cfg), data["streams"]["answer_key.json"], cfg)
        for k, v in s.items():
            assert v["warned"] == v["planted"] and v["false_alarms"] == 0, (seed, k, v)


# --------------------------------------------------------------------------- methods
def test_theil_sen_ignores_one_outlier():
    xs = list(range(10))
    ys = [2.0 * x + 1 for x in xs]
    ys[4] = 100.0
    slope, icpt = M.theil_sen(xs, ys)
    assert slope == pytest.approx(2.0) and icpt == pytest.approx(1.0)


def test_days_to_level_only_toward_the_limit():
    assert M.days_to_level(10.0, 0.5, 12.0, bad=1) == pytest.approx(4.0)
    assert M.days_to_level(10.0, -0.5, 12.0, bad=1) is None
    assert M.days_to_level(-8.0, -0.2, -10.0, bad=-1) == pytest.approx(10.0)


def test_cusum_accumulates_only_excess():
    s = 0.0
    for r in [0.2, 0.3, 0.1]:
        s = M.cusum_step(s, r, 0.5)
    assert s == 0.0
    for r in [1.0, 1.0]:
        s = M.cusum_step(s, r, 0.5)
    assert s == pytest.approx(1.0)


def test_weibull_recovers_a_known_shape():
    import random
    rng = random.Random(1)
    times = [rng.weibullvariate(1000.0, 2.0) for _ in range(2000)]
    fit = M.weibull_fit(times, [True] * len(times))
    assert fit["beta"] == pytest.approx(2.0, rel=0.08) and fit["eta"] == pytest.approx(1000.0, rel=0.05)


def test_a_step_is_not_wear():
    """A reseat moves the level once; the optics detector needs a steady trend."""
    base = [-5.0] * 30
    step = base + [-7.5] * 10
    wear = base + [-5.0 - 0.35 * i for i in range(1, 11)]
    c = R.config()["detectors"]["optics"]
    mods = [{"serial": s, "location": s, "peer": "", "first_day": "2026-03-02", "bias_ma": [7.0] * 40, "tx_dbm": [-2.0] * 40, "rx_dbm": rx}
            for s, rx in (("STEP", step), ("WEAR", wear))]
    flags = {f["serial"]: f for f in D.optics(mods, c)}
    assert "STEP" not in flags or not flags["STEP"]["first_act"]
    assert flags["WEAR"]["first_watch"] or flags["WEAR"]["first_act"]
