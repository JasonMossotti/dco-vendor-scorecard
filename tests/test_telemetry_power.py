"""Power telemetry: UPS, busway, tap-off, and generator readings in the manufacturers' published SNMP and Modbus
point maps, agreeing with the racks, the energy meters, and every power record."""

import filecmp
import hashlib
import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from scorecard import telemetry_power as TP
from scorecard.synthetic import energy as E
from scorecard.synthetic import telemetry_cdu as C
from scorecard.synthetic import telemetry_power as P

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "telemetry" / "power"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_telemetry  # noqa: E402
import render_telemetry  # noqa: E402


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    """One regeneration to a temp folder (GPU, energy, CDU, power), the one-minute tiers to their usual place."""
    tmp = tmp_path_factory.mktemp("telemetry")
    watched = (SAMPLE, ROOT / "data" / "gpu_health", ROOT / "data" / "energy", ROOT / "data" / "history")
    before = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    man = generate_telemetry.generate(tmp / "gpu", generate_telemetry.HOURLY)
    after = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    return tmp, man["power"], before == after


@pytest.fixture(scope="module")
def data(regenerated):
    return render_telemetry.load_power()


@pytest.fixture(scope="module")
def checks(data):
    return TP.agreements(data, P.load_config(), C.load_config()["rack_rest"], E.load_config())


def test_committed_tier_is_current(regenerated):
    out = regenerated[0] / "power"
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file()), "a window was added or removed"
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_telemetry.py"


def test_energy_meters_rebuilt_from_the_racks_are_the_committed_ones(regenerated):
    out = regenerated[0] / "energy"
    for p in sorted(out.rglob("*")):
        if p.is_file():
            assert filecmp.cmp(p, ROOT / "data" / "energy" / p.relative_to(out), shallow=False), f"{p.name} is stale"


def test_minute_tier_matches_the_manifest_checksums(regenerated):
    man = json.loads((LAYER / "manifest.json").read_text(encoding="utf-8"))
    folder = generate_telemetry.HOURLY.parent / "power_minutes"
    for name, meta in man["minutes"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == meta["sha256"], name
    fam: dict[str, int] = {}
    for x in man["devices"].values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    assert fam == {"ups": 12, "busway": 36, "tapoff": 128, "generator": 7}


def test_reads_the_records_and_never_writes_them(regenerated):
    assert regenerated[2], "data/sample, data/gpu_health, data/energy and data/history are read, never written"
    assert '"telemetry", "power"' in inspect.getsource(P), "its own random streams"


def test_every_agreement_holds_on_the_sample(checks):
    assert [c.name for c in checks] == ["racks", "breakers", "feed_loss", "tree", "modes", "battery", "mech", "generators", "quality"]
    for c in checks:
        assert c.checked > 0 and not c.misses, (c.name, c.misses[:5])


def test_the_checks_read_only_what_is_published():
    from scorecard.synthetic import telemetry as T
    assert TP.rack_input_kwh({"samples": 4320, "power_kwh": 60.0}, C.load_config()["rack_rest"]) \
        == T.rack_input_kwh({"samples": 4320, "power_kwh": 60.0}, C.load_config()["rack_rest"]), "the same rack model"
    src = inspect.getsource(TP)
    assert "scorecard.synthetic" not in src.split('"""', 2)[2] and "answer_key" not in src


def test_point_maps_are_the_published_ones():
    """UPS-MIB (RFC 1628, mib-2 33), APC PowerNet-MIB (enterprise 318), Starline (35774), and EMCP registers."""
    f = P.load_config()["fields"]
    for x in (x for x in f["ups"] if x["oid"]):
        assert x["oid"].startswith(("1.3.6.1.2.1.33.", "1.3.6.1.4.1.318.")), x["key"]
    for x in f["busway"] + f["tapoff"]:
        assert x["oid"].startswith("1.3.6.1.4.1.35774."), x["key"]
    for x in f["generator"]:
        assert isinstance(x["reg"], int) and isinstance(x["res"], (int, float)) and isinstance(x["offset"], (int, float)), x["key"]


def test_pack_round_trips():
    rng = np.random.default_rng(1)
    for a in (np.zeros(500, dtype=np.int64), np.cumsum(rng.integers(-3, 4, 2000)), np.repeat(rng.integers(0, 9, 40), 50)):
        assert np.array_equal(TP.unpack(P.pack(a)), a)
    assert len(json.dumps(P.pack(np.zeros(40320, dtype=np.int64)))) < 20, "a month of zeros is a few bytes"


def test_the_utility_outage_rides_on_battery_then_all_seven_generators(data):
    o = data.manifest["outages"]
    assert len(o) == 1
    o = o[0]
    gens = data.devices("generator")
    m = data.m_of(TP.parse(o["ties_closed"])) + 2
    assert all(int(data.minutes(g)["kw"][m]) > 0 for g in gens) and len(gens) == 7
    for u in data.devices("ups"):
        assert int(data.minutes(u)["soc_pct"][m - 3:m + 2].min()) <= 100
    assert all(int(data.minutes(g)["kw"][data.m_of(TP.parse(o["back"])) + 10]) == 0 for g in gens), "cooldown is unloaded"


def test_hall_ups_output_is_the_racks_plus_busway_loss(data):
    """Each hall's UPS output (the meter's ups_out) is its racks' tap-off energy plus the busway loss."""
    loss = E.load_config()["busway_loss_fraction"]
    rows = [r for r in data.ups_hourly if r["kind"] == "it"]
    out = sum(float(r["out_kwh"]) for r in rows)
    taps = sum(sum(v["wh"]) for v in data.tapoff_hourly["tapoffs"].values()) / 1000
    assert out == pytest.approx(taps * (1 + loss), rel=2e-3)


def test_power_report_is_current(regenerated):
    f = render_telemetry.prepare()
    assert (ROOT / "reports" / "power_telemetry.md").read_text(encoding="utf-8") == render_telemetry.power_markdown(f["power"])


def test_events_carry_their_records(regenerated):
    f = render_telemetry.prepare()["power"]
    gen4 = [e for e in f["events"] if e["device"] == "GEN-4"]
    assert gen4 and any("L-003" in json.dumps(e) for e in gen4), "GEN-4's short loaded test is the Landlord finding"
    a07 = [e for e in f["events"] if e["device"].startswith("TO-A07")]
    assert a07 and any("went dark" in e["text"] for e in a07), "rack A07 lost both feeds"
