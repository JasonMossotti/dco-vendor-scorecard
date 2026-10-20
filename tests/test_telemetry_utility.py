"""Utility mains metering and UPS ride-through: the 13.8 kV mains under PowerLogic ION labels, agreeing with the energy
meters, the EPMS breaker events, and the UPS telemetry; the ride-through gathered from the UPSs' published runtimes."""

import filecmp
import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from scorecard import telemetry_utility as TU
from scorecard.synthetic import telemetry_power as P
from scorecard.synthetic import telemetry_utility as U

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "data" / "telemetry" / "utility"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_telemetry  # noqa: E402
import render_telemetry  # noqa: E402


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    """One regeneration to a temp folder, the one-minute tiers to their usual place."""
    tmp = tmp_path_factory.mktemp("telemetry")
    watched = (ROOT / "data" / "sample", ROOT / "data" / "energy", ROOT / "data" / "telemetry" / "power")
    before = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    man = generate_telemetry.generate(tmp / "gpu", generate_telemetry.HOURLY)
    after = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    return tmp, man["utility"], before == after


@pytest.fixture(scope="module")
def data(regenerated):
    return render_telemetry.load_utility()


@pytest.fixture(scope="module")
def checks(data):
    return TU.agreements(data, U.load_config(), P.load_config())


def test_committed_tier_is_current(regenerated):
    out = regenerated[0] / "utility"
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file()), "a window was added or removed"
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_telemetry.py"


def test_power_layer_is_unchanged_by_the_utility_layer(regenerated):
    out = regenerated[0] / "power"
    for p in sorted((ROOT / "data" / "telemetry" / "power").rglob("*")):
        if p.is_file():
            assert filecmp.cmp(out / p.relative_to(ROOT / "data" / "telemetry" / "power"), p, shallow=False), p.name


def test_minute_tier_matches_the_manifest_checksums(regenerated):
    man = json.loads((LAYER / "manifest.json").read_text(encoding="utf-8"))
    folder = generate_telemetry.HOURLY.parent / "utility_minutes"
    assert sorted(man["minutes"]) == ["MV-A.json", "MV-B.json", "ride_through.json"]
    for name, meta in man["minutes"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == meta["sha256"], name


def test_reads_the_records_and_never_writes_them(regenerated):
    assert regenerated[2], "data/sample, data/energy and the power telemetry are read, never written"
    assert '"telemetry", "utility"' in inspect.getsource(U), "its own random stream"
    assert "scorecard.synthetic" not in inspect.getsource(TU), "the checks read only what is published"


def test_every_agreement_holds_on_the_sample(checks):
    assert [c.name for c in checks] == ["energy", "outage", "ohms_law", "quality", "buses", "ride_through", "runtime", "bridge"]
    for c in checks:
        assert c.checked > 0 and not c.misses, (c.name, c.misses[:5])


def test_mains_carry_the_metered_utility_energy(data):
    meters = data.power.meters
    total = sum(float(r["utility_kwh"]) for r in meters.values())
    assert sum(float(r["kwh"]) for r in data.mains_hourly) == pytest.approx(total, abs=1.0)


def test_the_outage_is_41_dead_minutes_on_each_main_and_a_12_second_bridge(data):
    for b in ("MV-A", "MV-B"):
        assert sum(int(r["dead_min"]) for r in data.mains_hourly if r["main"] == b) == 41
    (o,) = data.manifest["outages"]
    assert o["bridge_s"] == 12 and o["ride_it_s"] > 500 and o["ride_cooling_s"] > o["ride_it_s"]


def test_ride_through_headline(data):
    f = render_telemetry.prepare_utility(data.power, data)
    assert list(f["ride"])[:2] == ["SITE-IT", "SITE-COOLING"]
    assert f["ride"]["SITE-IT"]["min_s"] == 540 and f["ride"]["SITE-COOLING"]["min_s"] == 1230
    assert f["ride"]["SITE-IT"]["min_ups"].startswith("UPS-A") and f["ride"]["SITE-COOLING"]["min_ups"].startswith("MUPS-")
    assert TU.fmt_s(540) == "9:00" and TU.fmt_s(1230) == "20:30" and TU.fmt_s(-1) == "–"


def test_every_ups_sits_on_one_bus():
    cfg = U.load_config()
    assert U.bus_of("UPS-A1", cfg) == "MV-A" and U.bus_of("UPS-A2", cfg) == "MV-B" and U.bus_of("MUPS-B1", cfg) == "MV-A"


def test_utility_report_is_current(regenerated):
    f = render_telemetry.prepare()
    assert (ROOT / "reports" / "utility_telemetry.md").read_text(encoding="utf-8") == render_telemetry.utility_markdown(f["power"]["utility"])
