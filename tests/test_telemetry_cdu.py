"""CDU telemetry: DMTF Redfish readings that agree with every CDU record, the GPU telemetry, and the meters."""

import filecmp
import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from scorecard import telemetry_cdu as TC
from scorecard.synthetic import gpu_health as G
from scorecard.synthetic import telemetry_cdu as C

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
HEALTH = ROOT / "data" / "gpu_health"
LAYER = ROOT / "data" / "telemetry" / "cdu"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_telemetry  # noqa: E402
import render_telemetry  # noqa: E402


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    """One regeneration: GPU then CDU telemetry to a temp folder, the one-minute tiers to their usual place."""
    tmp = tmp_path_factory.mktemp("telemetry")
    watched = (SAMPLE, HEALTH, ROOT / "data" / "energy", ROOT / "data" / "history")
    before = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    man = generate_telemetry.generate(tmp / "gpu", generate_telemetry.HOURLY)
    after = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    return tmp / "cdu", man["cdu"], before == after


@pytest.fixture(scope="module")
def data(regenerated):
    return render_telemetry.load_cdu()


@pytest.fixture(scope="module")
def checks(data):
    return TC.agreements(data, C.load_config(), G.load_config())


def test_committed_tier_is_current(regenerated):
    out, _man, _ = regenerated
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file()), "a window was added or removed"
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_telemetry.py"


def test_minute_tier_matches_the_manifest_checksums(regenerated):
    man = json.loads((LAYER / "manifest.json").read_text(encoding="utf-8"))
    assert len(man["minutes"]) == len(man["cdus"]) == 8
    folder = generate_telemetry.HOURLY.parent / "cdu_minutes"
    for name, meta in man["minutes"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == meta["sha256"], name


def test_reads_the_records_and_never_writes_them(regenerated):
    assert regenerated[2], "data/sample, data/gpu_health, data/energy and data/history are read, never written"
    assert '"telemetry", "cdu"' in inspect.getsource(C), "its own random streams"


def test_every_agreement_holds_on_the_sample(checks):
    assert [c.name for c in checks] == ["supply", "flow", "pumps", "leaks", "heat", "formula", "facility_water", "filter", "pump_power"]
    for c in checks:
        assert c.checked > 0 and not c.misses, (c.name, c.misses[:5])
    by = {c.name: c.checked for c in checks}
    assert by["supply"] == by["flow"] == 8 * 672 and by["heat"] == 2 * 672 and by["filter"] == 12


def test_the_checks_read_only_what_is_published():
    src = inspect.getsource(TC)
    assert "synthetic" not in src.split('"""', 2)[2] and "answer_key" not in src


def test_redfish_names_and_resources():
    cfg = C.load_config()
    resources = {"SecondaryCoolantConnectors/1", "PrimaryCoolantConnectors/1", "Pumps/1", "Pumps/2", "Reservoirs/1",
                 "EnvironmentMetrics", "Sensors/PrimaryValve", "Sensors/FilterDP"}
    assert {f["resource"] for f in cfg["fields"]} == resources
    connector = {"SupplyTemperatureCelsius", "ReturnTemperatureCelsius", "DeltaTemperatureCelsius", "FlowLitersPerMinute",
                 "SupplyPressurekPa", "ReturnPressurekPa", "DeltaPressurekPa", "HeatRemovedkW", "SupplyTemperatureControlCelsius"}
    assert {f["property"] for f in cfg["fields"] if "Connectors" in f["resource"]} <= connector
    assert cfg["collection"]["base_uri"] == "/redfish/v1/ThermalEquipment/CDUs"


def test_events_are_the_records(data):
    """The pump failures, isolations, and tests are exactly the Redfish events; leaks are the BMS and TTDM records."""
    recorded = {(e["cdu"], e["resource"], e["property"], e["value"]) for e in data.events}
    shown = {(s["cdu"], s["resource"], s["property"], s["value"]) for s in data.states if s["record"].endswith("cdu_redfish_events.jsonl")}
    assert shown == recorded
    leaks = {(s["cdu"], s["resource"].rsplit("/", 1)[1]) for s in data.states if s["property"] == "DetectorState" and s["value"] == "Critical"}
    assert leaks == {("CDU-A1", "2"), ("CDU-A4", "1")}


def test_a_failed_pump_was_running_and_flow_dipped(data):
    x = data.minutes("CDU-B3")
    m = data.m_of("2026-09-06T02:51:39Z")
    assert x["pump2_pct"][m - 1] > 0 and x["pump2_pct"][m] == 0 and x["pump1_pct"][m] > 0
    assert x["sec_flow_lpm"][m - 1] - x["sec_flow_lpm"][m] > 1000          # tenths: more than 100 L/min
    assert x["sec_flow_lpm"][m] >= 15000, "the dip stays inside the 1,500 L/min band"


def test_hall_heat_follows_the_racks(data):
    """Rack A07's power loss: Hall A's heat falls by about one rack while it is dark."""
    sums = sum(data.minutes(c)["heat_kw"] for c in ("CDU-A1", "CDU-A2", "CDU-A3", "CDU-A4")) / 10
    m0, m1 = data.m_of("2026-09-15T15:30:00Z"), data.m_of("2026-09-15T16:30:00Z")
    drop = float(sums[m0 - 30:m0].mean() - sums[m1:m1 + 30].mean())
    assert 40 < drop < 130, drop


def test_cdu_report_is_current(regenerated):
    f = render_telemetry.prepare()
    assert (ROOT / "reports" / "cdu_telemetry.md").read_text(encoding="utf-8") == render_telemetry.cdu_markdown(f["cdu"])


def test_pin_reproduces_an_hour_exactly():
    import numpy as np
    base = np.linspace(0, 1, 60) ** 2 * 50 + 2500
    v = C.pin(base, 2512, 2530, 1)
    assert int(v.sum()) == 2512 * 60 and int(v.max()) == 2530
    v = C.pin(base, 18000, 17800, -1)
    assert int(v.sum()) == 18000 * 60 and int(v.min()) == 17800
