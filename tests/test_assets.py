"""The asset register: every asset by serial, reconciled every day with what the devices answer and with every record that
moves an asset, with three planted findings, the other checks' findings corroborated, and no false positives."""

import copy
import filecmp
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from scorecard import assets as A
from scorecard.synthetic import assets as G

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
SECURITY = ROOT / "data" / "security"
MGMT = ROOT / "data" / "telemetry" / "mgmt"
STORAGE = ROOT / "data" / "telemetry" / "storage"
LAYER = ROOT / "data" / "assets"
sys.path.insert(0, str(ROOT / "scripts"))

import render_assets  # noqa: E402

NAMES = ["installed", "stock", "tickets", "rma", "returns", "media", "disposals", "directory", "landlord"]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("assets")
    watched = [SAMPLE, SECURITY, MGMT, STORAGE]
    before = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = G.AssetLayer(SAMPLE, seed, SECURITY, MGMT, STORAGE)
    G.write_assets(layer, layer.run(), tmp, render_assets_source())
    after = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    return tmp, before == after


def render_assets_source() -> str:
    import generate_assets
    return generate_assets.SOURCE


@pytest.fixture(scope="module")
def t():
    return render_assets.load()


@pytest.fixture(scope="module")
def r(t):
    return A.analyse(t)


def test_committed_register_is_current(regenerated):
    out = regenerated[0]
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file())
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_assets.py"


def test_reads_the_records_and_writes_nothing_there(regenerated):
    assert regenerated[1], "generating the register changed a record it reads"


def test_every_received_device_is_registered(t, r):
    R = r["R"]
    st = R.state(t.end)[0]
    classes = {}
    for tag, (s, _) in st.items():
        classes.setdefault(R.asset[tag]["class"], 0)
        classes[R.asset[tag]["class"]] += 1
    for c in ("Compute tray", "NVLink switch tray", "Power shelf", "PSU (5.5 kW)", "Management switch", "InfiniBand leaf switch",
              "Ethernet switch", "Console server", "OOB aggregation switch", "Storage node", "NVMe SSD 30.72 TB (U.2)", "Facility equipment"):
        assert classes.get(c), f"no {c} in the register"
    # every shelf has its six PSUs, and Hall B racks enter only once received (M1)
    held = R.state(t.end)[1]
    assert all(len(held.get(f"A01_PowerShelf_{n} PSU {m}", [])) == 1 for n in range(1, 9) for m in range(1, 7))
    received = {x["rack"] for x in t.milestones if x["milestone"] == "M1" and x["reported_complete_at"]}
    assert "B14" in received and held.get("B14") and not held.get("B20")
    assert len({a["serial"] for a in R.asset.values()}) == len(R.asset), "one asset per serial"


def test_each_halls_storage_shelf_matches_its_ledger(t, r):
    """The register's units on each hall's storage spares shelf at month end equal the shelf ledger's closing balance."""
    R = r["R"]
    st = R.state(t.end)[0]
    last: dict[tuple[str, str], int] = {}
    for x in t.stg_ledger:
        last[(G.shelf_of(x["hall"]), x["fru"].replace(" (storage fabric)", ""))] = int(x["balance_after"])
    assert last
    for (loc, cls), n in last.items():
        held = sum(1 for tag, (s, l) in st.items() if s == "in_stock" and l == loc and R.asset[tag]["class"] == cls)
        assert held == n, (loc, cls)


def test_every_agreement_holds(r):
    cs = r["agreements"]
    assert [c.name for c in cs] == NAMES
    assert all(c.checked > 0 for c in cs)
    assert {c.name: c.misses for c in cs if c.misses} == {}


def test_three_planted_findings_and_no_false_positives(r):
    fs = r["findings"]
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert A.score(fs, key) == {"planted": 3, "found": 3, "false_positives": 0}
    assert sorted(f["kind"] for f in fs) == ["disposed_answering", "live_in_stock", "rma_not_received"]
    assert [f["id"] for f in fs] == ["AR-1", "AR-2", "AR-3"]
    for f in fs:
        assert f["owner"] == "IT Partner" and f["lines"] and f["contract"].startswith("Interface Agreement REG-")
        assert not re.search(r"\blied\b|\bfalsif|\bdishonest|\bstole", f["summary"] + " ".join(f["lines"]), re.I)


def test_other_checks_findings_are_corroborated_not_counted_again(r):
    """The register sees the IT engine's unverified swaps, the Security engine's drive shipped without destruction, and
    the storage checks' wrong bay and custody gap; each is listed once as corroboration, never as an AR finding."""
    got = {(c["finding"], c["type"]) for c in r["corroborations"]}
    assert got == {("F-007", "unverified_swap"), ("F-009", "unverified_swap"), ("S-002", "media_shipped_without_destruction"),
                   ("SP-1", "wrong_bay"), ("SP-3", "custody_gap")}


def test_without_the_other_findings_the_disagreements_show(t):
    """Corroboration is earned: with nothing known, the same disagreements become findings of their own."""
    t2 = copy.copy(t)
    t2.known = {}
    kinds = sorted({f["kind"] for f in A.analyse(t2)["findings"]})
    assert "serial_mismatch" in kinds and "media_unaccounted" in kinds


def test_a_receipt_clears_the_delivery(t):
    p = next(x for x in json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))["planted"] if x["kind"] == "rma_not_received")
    row = next(x for x in t.portal if x["rma"] == p["rma"])
    t2 = copy.copy(t)
    t2.tx = sorted(t.tx + [{"at": G.iso(G.parse(row["delivered_at"]) + timedelta(hours=2)), "tag": "AT-999999", "class": row["fru"],
                            "serial": row["replacement_serial"], "action": "receive", "location": G.CAGE, "ref": row["rma"],
                            "by": "IT Partner"}], key=lambda x: x["at"])
    assert "rma_not_received" not in {f["kind"] for f in A.analyse(t2)["findings"]}


def test_checks_catch_broken_records(t):
    # an install recorded at the wrong location
    t2 = copy.copy(t)
    t2.tx = copy.deepcopy(t.tx)
    x = next(x for x in t2.tx if x["action"] == "install" and x["ref"].startswith("INC") and x["class"] == "Compute tray")
    x["location"] = "a01-ct01"
    m = {c.name: c.misses for c in A.analyse(t2)["agreements"]}
    assert m["tickets"]
    # an RMA shipment the register never recorded
    t3 = copy.copy(t)
    t3.tx = [x for x in t.tx if x["action"] != "rma_ship" or x["serial"] != t.rma[0]["serial"]]
    assert {c.name: c.misses for c in A.analyse(t3)["agreements"]}["rma"]


def test_the_device_page_carries_the_register():
    import render_devices
    page = render_devices.html_page()
    data = json.loads(re.search(r'<script type="application/json" data-gl-skip id="dev-data">(.*?)</script>', page, re.S).group(1).replace("<\\/", "</"))
    a = data["assets"]
    assert a["total"] == len(a["assets"]) and [f["id"] for f in a["findings"]] == ["AR-1", "AR-2", "AR-3"]


def test_report_is_current():
    f = render_assets.prepare()
    assert render_assets.OUT.read_text(encoding="utf-8") == render_assets.markdown(f)
