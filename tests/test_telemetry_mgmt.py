"""Management network telemetry: every BMC's Redfish answers, the management switches' IF-MIB ports and traps, and the
console servers' session logs, agreeing with every record, with four planted findings and no false positives."""

import copy
import filecmp
import json
import re
import sys
from pathlib import Path

import pytest

from scorecard import site_health as SH
from scorecard import telemetry_mgmt as TG
from scorecard.synthetic import telemetry_mgmt as G

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "telemetry" / "mgmt"
sys.path.insert(0, str(ROOT / "scripts"))

import render_telemetry  # noqa: E402

NAMES = ["records", "power", "swaps", "nmx", "handover", "hourly", "ports", "rackwide"]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mgmt")
    before = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = G.MgmtTelemetry(SAMPLE, seed)
    G.write_mgmt(layer, layer.run(), tmp, "data/sample + site/site.yaml")
    after = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    return tmp, before == after


@pytest.fixture(scope="module")
def t():
    return TG.load(LAYER, SAMPLE)


@pytest.fixture(scope="module")
def cfg():
    return G.load_config()


def misses(t, cfg):
    return {c.name: c.misses for c in TG.agreements(t, cfg)}


def test_committed_tier_is_current(regenerated):
    out = regenerated[0]
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file()), "a window was added or removed"
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_telemetry.py"


def test_reads_the_records_and_writes_nothing_there(regenerated):
    assert regenerated[1], "generating the management layer changed a file in data/sample"


def test_devices_match_the_site_model(t):
    devs = t.manifest["devices"]
    fam = {}
    for x in devs.values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    assert fam == {"bmc": 2240, "rack": 128, "agg": 4, "console": 8}
    per = {}
    for x in devs.values():
        if x["family"] == "bmc":
            per.setdefault(x["rack"], {}).setdefault(x["kind"], 0)
            per[x["rack"]][x["kind"]] += 1
    assert all(k == {"compute": 18, "switch": 9, "shelf": 8} for k in per.values()) and len(per) == 64
    directory = json.loads((ROOT / "docs" / "site" / "devices.json").read_text(encoding="utf-8"))
    names = set(directory["devices"]) if isinstance(directory.get("devices"), dict) else {d["name"] for d in directory["devices"]}
    assert {s for s, x in devs.items() if x["family"] != "bmc"} <= names, "every management switch and console server is in the device directory"


def test_every_agreement_holds(t, cfg):
    cs = TG.agreements(t, cfg)
    assert [c.name for c in cs] == NAMES
    assert all(c.checked > 0 for c in cs)
    assert {c.name: c.misses[:3] for c in cs if c.misses} == {}


def test_four_planted_findings_and_no_false_positives(t, cfg):
    fs = TG.findings(t, cfg)
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert TG.score(fs, key) == {"planted": 4, "found": 4, "false_positives": 0}
    assert sorted(f["kind"] for f in fs) == ["console_swap", "late_bmc", "unticketed_outage", "validation_gap"]
    assert [f["id"] for f in fs] == ["MP-1", "MP-2", "MP-3", "MP-4"]
    for f in fs:
        assert f["owner"] == "IT Partner" and f["lines"] and f["contract"]
        assert not re.search(r"\blied\b|\bfalsif|\bdishonest", f["summary"] + " ".join(f["lines"]), re.I)


def test_the_decoys_raise_nothing(t, cfg):
    """Power losses, swaps, reseats, BMC resets and hangs, collector restarts, and uplink flaps all happen, and none is a finding."""
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    kinds = {d["kind"] for d in key["decoys"]}
    assert {"reset", "hang", "collector", "uplink"} <= kinds
    ev = TG.events(t, cfg, TG.findings(t, cfg))
    assert {"power", "swap", "reseat", "uplink", "collector"} <= {e["kind"] for e in ev}
    assert all(e["finding"] is None for e in ev if e["kind"] in ("power", "swap", "reseat", "uplink", "collector", "failed"))


def test_a_ticket_explains_the_outage(t, cfg):
    """With an IT Partner ticket on the rack during the switch outage, there is nothing to reconcile."""
    out = next(f for f in TG.findings(t, cfg) if f["kind"] == "unticketed_outage")
    t2 = copy.copy(t)
    t2.tickets = t.tickets + [{"rack": out["devices"][1], "opened_at": out["from"], "number": "INC0000000"}]
    assert not [f for f in TG.findings(t2, cfg) if f["kind"] == "unticketed_outage"]


def test_a_corrected_port_map_clears_the_console_finding(t, cfg):
    sw = next(f for f in TG.findings(t, cfg) if f["kind"] == "console_swap")
    con, (a, b) = sw["devices"][0], sw["ports"]
    t2 = copy.copy(t)
    t2.ports = copy.deepcopy(t.ports)
    t2.ports[con][str(a)], t2.ports[con][str(b)] = t.ports[con][str(b)], t.ports[con][str(a)]
    assert not [f for f in TG.findings(t2, cfg) if f["kind"] == "console_swap"]


def test_checks_catch_broken_logs(t, cfg):
    # a lost linkUp: the trap log no longer gives the hourly port counts
    i = next(i for i, e in enumerate(t.traps) if e["trap"] == "linkUp" and e["switch"].endswith("-mgmt1"))
    t2 = copy.copy(t)
    t2.traps = t.traps[:i] + t.traps[i + 1:]
    assert misses(t2, cfg)["ports"]
    # an hourly BMC row that does not add up
    t3 = copy.copy(t)
    t3.bmc_hourly = copy.deepcopy(t.bmc_hourly)
    row = next(r for r in t3.bmc_hourly if int(r["failed_polls"]) > 0)
    row["failed_polls"] = str(int(row["failed_polls"]) + 1)
    assert misses(t3, cfg)["hourly"]
    # a swap whose gap the log lost: the serial change falls in a minute the BMC answered... or no gap ends there
    swap_ep = next(e for e in t.inventory if "/PowerSubsystem/" not in e["resource"] and e["property"] == "SerialNumber" and t.endpoint_of(e["resource"]))
    n = t.endpoint_of(swap_ep["resource"])
    t4 = copy.copy(t)
    t4.gaps = [g for g in t.gaps if not (g["endpoint"] == n and g["to"] and t.m_of(g["to"]) == t.m_of(swap_ep["observed_at"]))]
    assert misses(t4, cfg)["swaps"]


def test_site_health_has_the_management_family(t):
    sh, d = SH.build()
    assert "mgmt" in [k for k, _, _ in SH.FAMILIES]
    groups = [g for g in d["groups"] if g["family"] == "mgmt"]
    assert [g["hall"] for g in groups] == ["HALL-A", "HALL-B"] and all(g["scheme"] == "N+1" for g in groups)
    out = next(f for f in TG.findings(t, G.load_config()) if f["kind"] == "unticketed_outage")
    h = t.m_of(out["from"]) // 60 + 1
    assert d["family_state"]["mgmt"][h] == SH.AMBER
    assert any(i["family"] == "mgmt" and i["text"].startswith(out["devices"][0] + " down") for i in d["issues"])
    assert next(c for c in SH.agreements(sh, d) if c.name == "mgmt_switches").misses == []


def test_report_is_current():
    f = render_telemetry.prepare_mgmt()
    assert render_telemetry.OUT_MGMT.read_text(encoding="utf-8") == render_telemetry.mgmt_markdown(f)
    assert len(f["racks"]) == 64 and len(f["findings"]) == 4
    assert all(r["answered_pct"] is None or r["answered_pct"] < 100 or r["failed"] == 0 for r in f["racks"])
