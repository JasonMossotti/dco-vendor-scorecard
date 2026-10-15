"""Storage and storage fabric telemetry: every storage node's drive bays, the storage and in-band Ethernet fabric's ports and
traps, and the clients' I/O stalls, agreeing with every record, with four planted findings and no false positives."""

import copy
import filecmp
import json
import re
import sys
from pathlib import Path

import pytest

from scorecard import availability as AV
from scorecard import site_health as SH
from scorecard import storage_fabric as SF
from scorecard import telemetry_storage as TS
from scorecard.site_model import load_site
from scorecard.synthetic import telemetry_storage as G

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "telemetry" / "storage"
MGMT = ROOT / "data" / "telemetry" / "mgmt"
sys.path.insert(0, str(ROOT / "scripts"))

import render_telemetry  # noqa: E402

NAMES = ["drives", "nodes", "cluster", "rebuild", "ports", "traffic", "trays", "stalls", "spares"]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("storage")
    before = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = G.StorageTelemetry(SAMPLE, seed, MGMT)
    G.write_storage(layer, layer.run(), tmp, "data/sample + data/telemetry/mgmt + site/site.yaml")
    after = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    return tmp, before == after


@pytest.fixture(scope="module")
def t():
    return TS.load(LAYER, SAMPLE, MGMT)


@pytest.fixture(scope="module")
def cfg():
    return G.load_config()


def misses(t, cfg):
    return {c.name: c.misses for c in TS.agreements(t, cfg)}


def test_committed_tier_is_current(regenerated):
    out = regenerated[0]
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file())
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_telemetry.py"


def test_reads_the_records_and_writes_nothing_there(regenerated):
    assert regenerated[1], "generating the storage layer changed a file in data/sample"


def test_devices_match_the_site_model(t):
    devs = t.manifest["devices"]
    fam = {}
    for x in devs.values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    assert fam == {"node": 32, "row_leaf": 16, "storage_leaf": 4, "spine": 4}
    assert sum(x["drives"] for x in devs.values() if x["family"] == "node") == 768
    fab = SF.build(load_site(), 18)
    assert len(fab["trays"]) == 64 * 18 and all(len(p) == 2 for p in fab["trays"].values())
    assert set(fab["switches"]) == {s for s, x in devs.items() if x["family"] != "node"}
    # every leaf has two uplinks to each spine, and each lands on its own spine port
    for sw, x in fab["switches"].items():
        if x["role"] == "spine":
            assert len(x["ports"]) == 2 * 10 and all(p["kind"] == "downlink" for p in x["ports"].values())
        else:
            ups = [p for p in x["ports"].values() if p["kind"] == "uplink"]
            assert len(ups) == 4 and all(fab["switches"][p["peer"]]["ports"][p["peer_port"]]["peer"] == sw for p in ups)
    directory = json.loads((ROOT / "docs" / "site" / "devices.json").read_text(encoding="utf-8"))
    names = set(directory["devices"]) if isinstance(directory.get("devices"), dict) else {d["name"] for d in directory["devices"]}
    assert set(devs) <= names, "every storage node and fabric switch is in the device directory"


def test_every_agreement_holds(t, cfg):
    cs = TS.agreements(t, cfg)
    assert [c.name for c in cs] == NAMES
    assert all(c.checked > 0 for c in cs)
    assert {c.name: c.misses[:3] for c in cs if c.misses} == {}


def test_four_planted_findings_and_no_false_positives(t, cfg):
    fs = TS.findings(t, cfg)
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert TS.score(fs, key) == {"planted": 4, "found": 4, "false_positives": 0}
    assert sorted(f["kind"] for f in fs) == ["closed_before_rebuild", "custody_gap", "fabric_stall", "wrong_bay"]
    assert [f["id"] for f in fs] == ["SP-1", "SP-2", "SP-3", "SP-4"]
    for f in fs:
        assert f["owner"] == "IT Partner" and f["lines"] and f["contract"]
        assert not re.search(r"\blied\b|\bfalsif|\bdishonest", f["summary"] + " ".join(f["lines"]), re.I)


def test_the_decoys_raise_nothing(t, cfg):
    """Node reboots, swaps on time, predictive swaps, warnings, port blips, a clean uplink down, and a flap whose ticket
    states its impact all happen, and none is a finding."""
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert {"node_reboot", "transient_warning", "predicted_swap", "port_blip", "uplink_down"} <= {d["kind"] for d in key["decoys"]}
    ev = TS.events(t, cfg, TS.findings(t, cfg))
    assert {"drive", "swap", "rebuild", "warning", "node", "port", "uplink", "flap"} <= {e["kind"] for e in ev}
    assert all(e["finding"] is None for e in ev if e["kind"] in ("node", "warning", "port", "uplink"))


def test_a_ticket_that_states_the_impact_clears_the_stall(t, cfg):
    stall = next(f for f in TS.findings(t, cfg) if f["kind"] == "fabric_stall")
    t2 = copy.copy(t)
    t2.tickets = copy.deepcopy(t.tickets)
    tk = next(k for k in t2.tickets if k["number"] == stall["refs"][0])
    gh = next(x["gpu_hours"] for x in TS.stall_hours(t, cfg) if x["switch"] == stall["devices"][0])
    tk["customer_impact"] = f"I/O stalls on four racks; {gh} GPU-hours idle"
    assert not [f for f in TS.findings(t2, cfg) if f["kind"] == "fabric_stall"]


def test_a_custody_handover_clears_the_gap(t, cfg):
    gap = next(f for f in TS.findings(t, cfg) if f["kind"] == "custody_gap")
    key = next(p for p in json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))["planted"] if p["kind"] == "custody_gap")
    t2 = copy.copy(t)
    t2.custody = t.custody + [{"drive_serial": key["serial"], "node": key["node"], "bay": key["bay"], "ticket": key["ticket"],
                               "from": "IT Partner", "to": "Security Partner", "handed_over_at": key["removed_at"].replace(":00Z", ":30Z")}]
    assert gap and not [f for f in TS.findings(t2, cfg) if f["kind"] == "custody_gap"]


def test_checks_catch_broken_logs(t, cfg):
    # a lost linkUp: the trap log no longer gives the hourly seconds up
    i = next(i for i, e in enumerate(t.traps) if e["trap"] == "linkUp")
    t2 = copy.copy(t)
    t2.traps = t.traps[:i] + t.traps[i + 1:]
    assert misses(t2, cfg)["ports"]
    # a lost RebuildComplete: the bay never returns to OK, so the node's hourly counts disagree
    j = next(j for j, e in enumerate(t.drive_events) if e["event"] == "RebuildComplete")
    t3 = copy.copy(t)
    t3.drive_events = t.drive_events[:j] + t.drive_events[j + 1:]
    m = misses(t3, cfg)
    assert m["drives"] or m["nodes"]
    # a node's reads that its ports did not carry
    t4 = copy.copy(t)
    t4.node_hourly = copy.deepcopy(t.node_hourly)
    row = next(r for r in t4.node_hourly if float(r["read_gb"]) > 100)
    row["read_gb"] = f"{float(row['read_gb']) * 1.05:.3f}"
    assert misses(t4, cfg)["traffic"]


def test_storage_spares_shelf_against_the_sla(t, cfg):
    """Each hall's storage shelf: the SLA's minimums, an issue for every part a storage ticket used, the weekly counts, and
    KM-06 and KM-07 measured from them. The sample month's first week took four drives from Hall A's shelf."""
    from scorecard.sla_model import load_sla
    mins = {f.get("label") or f["fru"]: f["minimum"] for f in load_sla()["spares"]["storage_shelf"]["minimum_stock_per_hall"]}
    assert mins == {"NVMe SSD 30.72 TB (U.2)": 4, "800G OSFP optic (storage fabric)": 4}
    sh = TS.shelf(t)
    assert len(sh["rows"]) == 4 and sh["km06"] == [15, 16] and sh["km07"] == [16, 16]
    assert sh["below"] == [{"hall": "HALL-A", "fru": "NVMe SSD 30.72 TB (U.2)", "at": "2026-09-06T23:00:00Z", "counted": 2, "minimum": 4}]
    used = sum(1 for k in t.tickets for p in k["parts_used"] if p["part"] in {"NVMe SSD 30.72 TB (U.2)", "800G OSFP optic"})
    assert sum(r["issued"] for r in sh["rows"]) == used
    # an issue the shelf never recorded, and a count that does not match the ledger
    t2 = copy.copy(t)
    i = next(i for i, x in enumerate(t.ledger) if x["transaction"] == "issue")
    t2.ledger = t.ledger[:i] + t.ledger[i + 1:]
    assert misses(t2, cfg)["spares"]
    t3 = copy.copy(t)
    t3.counts = copy.deepcopy(t.counts)
    t3.counts[0]["system_qty"] = str(int(t3.counts[0]["system_qty"]) + 1)
    assert misses(t3, cfg)["spares"]


def test_site_health_has_the_storage_family(t, cfg):
    sh, d = SH.build()
    assert "storage" in [k for k, _, _ in SH.FAMILIES]
    assert sorted(g["key"] for g in d["groups"] if g["family"] == "storage") == ["stg-HALL-A", "stg-HALL-B"]
    assert sorted(g["key"] for g in d["groups"] if g["key"].startswith(("spine-", "storage_leaf-"))) == \
        sorted(f"{k}-{h}" for k in ("spine", "storage_leaf") for h in ("HALL-A", "HALL-B"))
    assert all(g["family"] == "network" for g in d["groups"] if g["key"].startswith(("spine-", "storage_leaf-"))), "the fabric is North-South network"
    stall = next(f for f in TS.findings(t, cfg) if f["kind"] == "fabric_stall")
    h = t.m_of(stall["from"]) // 60
    assert d["family_state"]["network"][h] == SH.AMBER
    assert any(i["family"] == "network" and "flapping" in i["text"] and i["from"] <= h <= i["to"] for i in d["issues"])
    assert next(c for c in SH.agreements(sh, d) if c.name == "storage_protection").misses == []


def test_availability_shows_storage_idle_beside_the_bridge(t, cfg):
    si = AV.storage_idle()
    assert si["gpu_hours"] == round(sum(x["gpu_hours"] for x in TS.stall_hours(t, cfg)), 1) > 0
    assert AV.storage_idle(ROOT / "no-such-dir") is None


def test_report_is_current():
    f = render_telemetry.prepare_storage()
    assert render_telemetry.OUT_STORAGE.read_text(encoding="utf-8") == render_telemetry.storage_markdown(f)
    assert len(f["nodes"]) == 32 and len(f["findings"]) == 4
    assert [e["from"] for e in f["episodes"]] == sorted(e["from"] for e in f["episodes"])
