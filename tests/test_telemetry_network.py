"""Network telemetry: the back-end InfiniBand fabric (UFM Telemetry, node_exporter, SNMP or gNMI) and the NVLink
switch trays (NMX-T), under the published counter names, agreeing with every fabric event, ticket, and record."""

import filecmp
import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from scorecard import devices as D
from scorecard import fabric
from scorecard import telemetry_network as TN
from scorecard.synthetic import telemetry_network as N

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "telemetry" / "network"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_telemetry  # noqa: E402
import render_telemetry  # noqa: E402


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    """One regeneration to a temp folder, the publish-time tiers to their usual place."""
    tmp = tmp_path_factory.mktemp("telemetry")
    watched = (SAMPLE, ROOT / "data" / "gpu_health", ROOT / "data" / "energy", ROOT / "data" / "history")
    before = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    man = generate_telemetry.generate(tmp / "gpu", generate_telemetry.HOURLY)
    after = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    return tmp, man["network"], before == after


@pytest.fixture(scope="module")
def data(regenerated):
    return render_telemetry.load_network()


@pytest.fixture(scope="module")
def checks(data):
    return TN.agreements(data, N.load_config(), D.load())


@pytest.fixture(scope="module")
def page(regenerated):
    return render_telemetry.prepare_network()


def test_committed_tier_is_current(regenerated):
    out = regenerated[0] / "network"
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file()), "a window was added or removed"
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_telemetry.py"


def test_hourly_tier_matches_the_manifest_checksums(regenerated):
    man = json.loads((LAYER / "manifest.json").read_text(encoding="utf-8"))
    folder = generate_telemetry.HOURLY.parent / "network_hourly"
    for name, meta in man["minutes"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == meta["sha256"], name
    fam: dict[str, int] = {}
    for x in man["devices"].values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    assert fam == {"leaf": 92, "port": 3312, "nvlink": 414}, "one link per GPU, one leaf per rack pair and rail, nine trays per rack"


def test_reads_the_records_and_never_writes_them(regenerated):
    assert regenerated[2], "data/sample, data/gpu_health, data/energy and data/history are read, never written"
    assert '"telemetry", "network"' in inspect.getsource(N), "its own random streams"


def test_every_agreement_holds_on_the_sample(checks):
    assert [c.name for c in checks] == ["symbol_errors", "link_state", "cabling", "traffic", "hall_b", "optics", "uplinks", "nvlink", "ranges"]
    for c in checks:
        assert c.checked > 0 and not c.misses, (c.name, c.misses[:5])


def test_the_checks_read_only_what_is_published():
    src = inspect.getsource(TN)
    assert "scorecard.synthetic" not in src.split('"""', 2)[2] and "ground_truth" not in src and "answer_key" not in src


def test_names_are_the_published_ones():
    cfg = N.load_config()
    ufm = [f["ufm"] for f in cfg["fields"]["port"]]
    for name in ("PortXmitDataExtended", "PortRcvDataExtended", "SymbolErrorCounterExtended", "LinkDownedCounterExtended",
                 "LinkErrorRecoveryCounterExtended", "PortXmitWaitExtended", "Total_Raw_BER", "Module_Temperature"):
        assert name in ufm
    assert all(f["host"].startswith("node_infiniband_") for f in cfg["fields"]["port"] if f.get("host"))
    assert {e["id"] for e in cfg["ufm_events"].values()} == {110, 328, 329}
    assert N.port_name(cfg["products"]["quantum2_qm9700"], 18) == "IB1/9/2" and N.port_name(cfg["products"]["quantum2_qm9700"], 1) == "IB1/1/1"
    assert N.port_name(cfg["products"]["quantum_x800_q3400"], 36) == "sw18p2"


def test_rack_power_loss_is_one_event_not_72_faults(data):
    """A07's outage logs Link is Down on its 72 links; the engine and alarm board fold them under the rack outage."""
    sched = TN._jsonl(SAMPLE / "telemetry" / "scheduler_node_states.jsonl")
    ufm = TN._jsonl(SAMPLE / "telemetry" / "ufm_port_events.jsonl")
    spans = fabric.power_loss_links(ufm, sched)
    lost = [e for e in ufm if fabric.peer_power_lost(e, spans)]
    assert len(lost) == 144 and {e["peer_host"][:3] for e in lost} == {"a07"}
    assert {e["event"] for e in lost} == {"link_down", "link_up"}
    findings = json.loads((ROOT / "reports" / "findings.json").read_text(encoding="utf-8"))["findings"]
    assert not any("a07-ct" in json.dumps(f["evidence"]) and "ufm" in json.dumps(f["evidence"]) for f in findings)


def test_hall_b_links_come_up_as_each_rack_is_cabled(page):
    cabled = [e for e in page["events"] if e["kind"] == "cabled"]
    assert len(cabled) == page["halls"]["HALL-B"]["racks"] == 14 and all(e["links"] == 72 and e["deploy"] for e in cabled)
    assert page["halls"]["HALL-B"]["cabled_start"] == 0 and page["halls"]["HALL-B"]["cabled_end"] == 1008


def test_events_carry_their_records(page):
    pd15 = [e for e in page["events"] if e["device"] == "leaf-a07-r1:swp18"]
    assert len(pd15) == 1
    e = pd15[0]
    assert e["refs"] == ["INC3100136", "INC3100170"] and "switch end replaced (INC3100136), errors continued" in e["text"]
    assert "host end replaced (INC3100170), errors stopped" in e["text"] and "F-011" in [f["id"] for f in e["findings"]]
    a07 = [e for e in page["events"] if e["kind"] == "power"]
    assert len(a07) == 1 and a07[0]["links"] == 72 and set(a07[0]["refs"]) == {"INC3900001", "WO-41023"}
    nv = [e for e in page["events"] if e["kind"] == "nvlink"]
    assert len(nv) == 1 and nv[0]["refs"] == ["INC3101173"]
    optic = [x for x in json.loads((SAMPLE / "vendor" / "tickets.json").read_text(encoding="utf-8")) if x["category"] == "optic_link"]
    shown = {r for e in page["events"] for r in e["refs"]}
    assert all(x["number"] in shown for x in optic if x["opened_at"] < page["window"]["end"]), "every optic ticket in the month has its event"


def test_network_report_is_current(regenerated):
    f = render_telemetry.prepare()
    assert (ROOT / "reports" / "network_telemetry.md").read_text(encoding="utf-8") == render_telemetry.network_markdown(f["network"])


def test_device_cards_link_to_telemetry():
    sys.path.insert(0, str(ROOT / "scripts"))
    import render_devices
    links = render_devices.telemetry_links()
    assert links["leaf-a07-r1 port 18"] == "#leaf-a07-r1:swp18" and links["a15-nvsw3"] == "#a15-nvsw3" and links["A07"] == "#A07"
    assert "B30" not in links, "a rack not yet in service has no telemetry"
    names = set(D.load()["devices"]) | set(D.ports(D.load()))
    assert all(k in names for k in links), [k for k in links if k not in names][:5]
