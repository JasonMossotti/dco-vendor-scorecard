"""Mechanical telemetry: chillers, facility water pumps, the loop, thermal walls, and CRAHs, read over BACnet/IP with
Vertiv's published iCOM point names, agreeing with the energy meters, the CDU and power telemetry, and every
mechanical record."""

import copy
import filecmp
import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from scorecard import site_model as S
from scorecard import telemetry_mechanical as TM
from scorecard.synthetic import energy as E
from scorecard.synthetic import telemetry_mechanical as M

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "telemetry" / "mechanical"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_telemetry  # noqa: E402
import render_telemetry  # noqa: E402

NAMES = ["meters", "walls", "heat", "water", "staging", "trips", "overrides", "air_events", "quiet"]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    """One regeneration to a temp folder (GPU, energy, CDU, power, network, mechanical), the one-minute tiers to their usual place."""
    tmp = tmp_path_factory.mktemp("telemetry")
    watched = (SAMPLE, ROOT / "data" / "gpu_health", ROOT / "data" / "energy", ROOT / "data" / "history")
    before = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    man = generate_telemetry.generate(tmp / "gpu", generate_telemetry.HOURLY)
    after = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    return tmp, man["mechanical"], before == after


@pytest.fixture(scope="module")
def data(regenerated):
    return render_telemetry.load_mech()


def agree(t):
    return TM.agreements(t, M.load_config(), E.load_config(), S.load_site())


def test_committed_tier_is_current(regenerated):
    out = regenerated[0] / "mechanical"
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file()), "a window was added or removed"
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_telemetry.py"


def test_minute_tier_matches_the_manifest_checksums(regenerated):
    man = json.loads((LAYER / "manifest.json").read_text(encoding="utf-8"))
    folder = generate_telemetry.HOURLY.parent / "mechanical_minutes"
    for name, meta in man["minutes"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == meta["sha256"], name
    fam: dict[str, int] = {}
    for x in man["devices"].values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    assert fam == {"chiller": 11, "pump": 3, "loop": 1, "wall": 8, "crah": 6}


def test_reads_the_records_and_never_writes_them(regenerated):
    assert regenerated[2], "data/sample, data/gpu_health, data/energy and data/history are read, never written"
    assert '"telemetry", "mechanical"' in inspect.getsource(M), "its own random streams"
    src = inspect.getsource(TM)
    assert "scorecard.synthetic" not in src.split('"""', 2)[2] and "answer_key" not in src and "ground_truth" not in src


def test_every_agreement_holds_on_the_sample(data):
    checks = agree(data)
    assert [c.name for c in checks] == NAMES
    for c in checks:
        assert c.checked > 0 and not c.misses, (c.name, c.misses[:5])


def test_the_agreements_catch_a_disagreement(data):
    """Each kind of fault the checks exist for is caught when planted in a copy."""
    def broken(edit):
        t = copy.copy(data)
        t._minutes = {k: {f: a.copy() for f, a in v.items()} for k, v in data._minutes.items()}
        t.chiller_hourly = [dict(r) for r in data.chiller_hourly]
        edit(t)
        return {c.name: len(c.misses) for c in agree(t)}
    for d in data.devices("chiller") + data.devices("wall") + data.devices("crah"):
        data.minutes(d)

    def meter(t):
        t.chiller_hourly[5]["kwh"] = str(float(t.chiller_hourly[5]["kwh"]) + 5)
    assert broken(meter)["meters"] == 1

    trip = next(e for e in data.states if e["device"] == "CH-08" and e["value"] == "active")

    def unalarmed(t):
        t._minutes["CH-08"]["hp1_alarm"][trip["m"]] = 0
    assert broken(unalarmed)["trips"] >= 1

    def hidden(t):
        t._minutes["TW-B2"]["sup_c"][28000] = 3150
    assert broken(hidden)["quiet"] == 1, "supply air over the limit during the inhibit would be a hidden excursion"

    def running_off(t):
        hold = next(e for e in data.states if e["device"] == "CH-06" and e["point"] == "Chiller enable")
        t._minutes["CH-06"]["status"][hold["m"] + 10] = 0
    assert broken(running_off)["staging"] == 1


def test_the_plant_follows_its_records(data):
    cfg = M.load_config()
    stat = {v: k for k, v in cfg["chiller"]["unit_status"].items()}
    spans = TM.record_spans(data)
    a, b, _ = spans["CH-05"]["trip"][0]
    x = data.minutes("CH-05")
    assert int(x["hp1_bar"][a - 1]) >= cfg["chiller"]["hp_alarm_bar"] * 10 and (x["status"][a:b] == stat["Alarm Off"]).all()
    a, b, _ = spans["CH-03"]["lock"][0]
    assert (b - a) / 60 > 24 and not data.minutes("CH-03")["fc"][a:b].any(), "the 6-day lockout: no free cooling on CH-03"
    a, b, _ = spans["TW-B2"]["inhibit"][0]
    assert int(data.minutes("TW-B2")["sup_c"][a:b].max()) < cfg["air"]["high_supply_c"] * 100, "the inhibit hid no excursion"
    a, b, fan = spans["TW-A4"]["fan"][0]
    w = data.minutes("TW-A4")
    assert fan == 6 and (w["fans_ok"][a:b] == 5).all() and (w["fan_failed"][a:b] == 6).all()


def test_mechanical_ups_load_is_the_walls_plus_the_cdus(data):
    """Follow devices: each hall's mechanical meter is its thermal walls' and CDUs' draw over the UPS efficiency."""
    site = S.load_site()
    walls = {}
    for r in data.air_hourly:
        if r["kind"] == "wall":
            walls[(r["hall"], r["hour"])] = walls.get((r["hall"], r["hour"]), 0.0) + float(r["kwh"])
    cdu = {}
    for r in data.cdu_hourly:
        cdu[(r["hall"], r["hour"])] = cdu.get((r["hall"], r["hour"]), 0.0) + float(r["power_kwh"])
    for h in (h for h in site["halls"] if h["state"] != "planned"):
        eff = S.product(site, h["power"]["mech_ups_product"])["efficiency"]
        k = h["letter"].lower()
        load = sum(walls.get((h["id"], hr), 0) + cdu.get((h["id"], hr), 0) for hr in data.meters)
        meter = sum(float(m[f"mech_{k}_kwh"]) for m in data.meters.values())
        assert meter * eff == pytest.approx(load, rel=0.01), h["id"]


def test_object_names_are_the_published_ones():
    cfg = M.load_config()
    units = {"", "degrees-celsius", "kilowatts", "percent", "liters-per-second", "cubic-meters-per-hour", "bars", "kilopascals",
             "hertz", "no-units", "watts"}
    for fam, objs in cfg["objects"].items():
        own = [o for o in objs if "property" not in o]          # a property row reads another property of an object listed
        assert len({(o["type"], o["instance"]) for o in own}) == len(own), f"{fam}: an object instance is used twice"
        assert all((o["type"], o["instance"]) in {(x["type"], x["instance"]) for x in own} for o in objs if "property" in o), fam
        assert all(o["units"] in units for o in objs), fam
    ch = {o["key"]: o for o in cfg["objects"]["chiller"]}
    assert ch["hp1_alarm"]["published"] and (ch["hp1_alarm"]["type"], ch["hp1_alarm"]["instance"]) == ("binary-value", 35)
    assert ch["status"]["modbus"] == "IR 49201" and ch["fc_inhibit"]["modbus"] == "HR 45152"
    assert cfg["chiller"]["unit_status"][14] == "BMS Off" and cfg["chiller"]["compressor_status"][4] == "ALARM"


def test_mechanical_report_is_current(regenerated):
    f = render_telemetry.prepare()
    assert (ROOT / "reports" / "mechanical_telemetry.md").read_text(encoding="utf-8") == render_telemetry.mechanical_markdown(f["mechanical"])


def test_events_carry_their_records(regenerated):
    ev = render_telemetry.prepare_mechanical()["events"]
    by = lambda dev, kind: [e for e in ev if e["device"] == dev and e["kind"] == kind]   # noqa: E731
    assert "WO-41035" in by("CH-08", "trip")[0]["refs"]
    assert by("CH-05", "trip")[0]["finding"]["id"] == "L-008"
    assert by("CH-03", "lockout")[0]["finding"]["id"].startswith("EN-F") and "PM-0015" in by("CH-03", "lockout")[0]["refs"]
    assert by("TW-B2", "inhibit")[0]["finding"]["id"] == "L-005" and "hid no excursion" in by("TW-B2", "inhibit")[0]["text"]
    assert {e["refs"][0] for e in ev if e["kind"] == "hold"} == {"PM-0014", "PM-0015", "PM-0016"}
    assert by("SITE", "outage") and by("TW-A4", "fan")
