"""The device directory, the device cards in the code popups, and the Devices page.

Facts come from the data: every cable the directory lists is the cable the telemetry reports, every device
inside a rack is in the rack inventory, and every device a page names is in the directory.
"""

import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scorecard import devices as DV
from scorecard import glossary as G
from scorecard import locations as L
from scorecard import site_model as S
from scorecard.sla_model import load_sla

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def data():
    return DV.load()


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    import build_site
    out = tmp_path_factory.mktemp("site")
    build_site.build(out)
    return out


def _jsonl(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]


# ------------------------------------------------------------------ the directory against the data
def test_directory_is_current(data):
    built = DV.build(S.load_site(), load_sla(ROOT / "sla" / "it_partner.yaml")["site"], L.build(S.load_site())["entries"])
    assert built == data, "run: python scripts/render_site.py"


def test_every_cable_matches_the_telemetry(data):
    """UFM reports the tray NIC at the other end of every port event; the directory must list the same cable."""
    for path in (SAMPLE / "telemetry" / "ufm_port_events.jsonl", ROOT / "data" / "history" / "telemetry" / "ufm_port_events.jsonl"):
        n, bad = DV.cabling_mismatches(data, _jsonl(path))
        assert n > 100 and not bad, (path.name, bad[:5])


def test_racks_hold_what_the_inventory_lists(data):
    topo = json.loads((SAMPLE / "site" / "topology.json").read_text(encoding="utf-8"))
    inside = {"compute_tray", "switch_tray", "power_shelf"}
    listed = set()
    for r in topo["racks"]:
        assert data["devices"][r["rack"]]["kind"] == "rack"
        primary = next(c for c in data["devices"][r["rack"]]["conn"] if c[0] == "Primary CDU")
        assert primary[1] == r["cdu"], r["rack"]
        listed |= {t["host"] for t in r["compute_trays"]} | {t["name"] for t in r["switch_trays"]}
        listed |= {p["redfish"].rsplit("/", 1)[1] for p in r["power_shelves"]}
    assert listed == {n for n, e in data["devices"].items() if e["kind"] in inside}


def test_leaf_numbers_count_rack_pairs(data):
    """Jason's example: leaf-a07-r1 port 18 is tray 18 of rack A13 (not A07), NIC mlx5_1."""
    e = DV.lookup(data, "leaf-a07-r1 port 18")
    assert ["Cable to", "a13-ct18", "NIC mlx5_1, rack A13"] in e["conn"]
    assert DV.lookup(data, "leaf-a07-r1:swp18")["conn"] == e["conn"]
    assert "racks A13 and A14" in data["devices"]["leaf-a07-r1"]["text"]
    assert "uplink" in DV.lookup(data, "leaf-a07-r1 port 40")["text"]
    assert DV.lookup(data, "leaf-a07-r1 port 18")["loc"] == "leaf-a07-r1 port 18|A13"
    assert DV.lookup(data, "Rack A07") is data["devices"]["A07"]
    assert DV.lookup(data, "leaf-z07-r1") is None


def test_connections_are_names_in_the_directory_and_agree_both_ways(data):
    devs = data["devices"]
    for name, e in devs.items():
        for rel, target, _ in e["conn"]:
            assert not target or DV.lookup(data, target) is not None, (name, rel, target)
    for name, e in devs.items():   # power: what a busway or UPS says it feeds says it is fed from there
        for rel, target, _ in e["conn"]:
            if e["kind"] == "ups" and rel == "Feeds":
                assert ["Fed by", name, "output feeder breaker"] in devs[target]["conn"]
            if e["kind"] == "busway" and rel == "Tap-off":
                assert any(c[0] == "On busway" and c[1] == name for c in devs[target]["conn"])
            if e["kind"] == "compute_tray" and rel.startswith("Rail "):
                assert DV.ports(data)[target][0] == name
    groups = {k for _, _, kinds in DV.GROUPS for k in kinds}
    assert {e["kind"] for e in devs.values()} <= groups and set(data["kinds"]) >= groups


def test_every_device_a_page_names_is_in_the_directory(data):
    import render_glossary
    texts = [t for _, _, t in render_glossary.corpus().values()]
    n, missing = DV.name_coverage(data, texts)
    assert n > 400 and not missing, sorted(set(missing))


def test_device_names_are_underlined_like_codes():
    gl = G.load()
    for name in ("leaf-a07-r1 port 18", "leaf-a07-r1:swp18", "leaf-a07-r1", "a13-ct18", "a15-nvsw3", "A06_PowerShelf_1", "Rack A07", "rack A07"):
        assert [m.group() for m in G.DEVICE_NAME.finditer(f"on {name}.")] == [name], name
        assert [e.type for e in gl.lookup(name)] == ["equipment"], name
        assert re.search(gl.link_pattern(), f"({name})").group() == name, name
    assert not G.DEVICE_NAME.search("A07 and rack position A07B")   # a bare rack position stays plain


# ------------------------------------------------------------------ the pages
def test_pages_carry_the_devices_they_name_and_their_neighbours(site, data):
    for page in ("alarms", "pir", "weekly", "patterns"):
        html = (site / page / "index.html").read_text(encoding="utf-8")
        blob = json.loads(re.search(r'<script id="gl-data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
        assert 0 < len(blob["dev"]) < len(data["devices"]) / 2, page
        for name, e in blob["dev"].items():
            assert e == DV.lookup(data, name), (page, name)
    weekly = (site / "weekly" / "index.html").read_text(encoding="utf-8")
    assert '"leaf-a07-r1:swp18"' in weekly and '"a13-ct18"' in weekly


def test_devices_page_is_published(site):
    html = (site / "devices" / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="devices"' in html and 'id="dev-data"' in html and 'id="loc-data"' in html
    gl = json.loads(re.search(r'<script id="gl-data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
    assert len(gl["dev"]) < 20, "the page's own copy of the directory is not scanned for code popups"


def _node(script, *args):
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, script, *map(str, args)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


@pytest.mark.parametrize("path,device,conn,redraw", [
    ("weekly/", "leaf-a07-r1:swp18", "a13-ct18", '[data-week="2026-W36"]'),
    ("alarms/#a07", "BW-A-R1-PG-A2-A", "UPS-A3", None),
    ("pir/", "TO-A07-B", "A07", None),
])
def test_device_cards_in_a_browser(site, path, device, conn, redraw):
    _node("device_popups.cjs", site / path.split("#")[0] / "index.html", f"https://example.test/{path}", device, conn, *([redraw] if redraw else []))


def test_devices_page_in_a_browser(site, data):
    out = _node("devices_page.cjs", site / "devices" / "index.html")
    got = json.loads(next(ln for ln in out.splitlines() if ln.startswith("LOOKUP "))[7:])
    for name, hit in got.items():   # the page reads names exactly as devices.lookup does
        e = DV.lookup(data, name)
        assert hit is not None and [hit[1], hit[2]] == [e["text"], e["conn"]], name


# ------------------------------------------------------------------ the Scorecards app
def test_app_lookup_shows_the_device_and_its_connections(monkeypatch):
    import runpy
    from fake_streamlit import FakeStreamlit
    fake = FakeStreamlit(overrides={"View": "IT Partner (Ridgeline)", "Code or ID": "leaf-a07-r1 port 18"})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    runpy.run_path(str(ROOT / "app" / "streamlit_app.py"), run_name="__main__")
    md = " ".join(fake.texts("markdown"))
    assert "**This device** · Leaf switch port" in md and "- Cable to: **a13-ct18** NIC mlx5_1, rack A13" in md


def test_app_bundle_carries_what_the_lookup_reads(tmp_path):
    """The app's lookup panel draws the detail sheets and builds the directory from the bundle alone."""
    import build_site
    members = {p.relative_to(ROOT).as_posix() for p in build_site.bundle_members(ROOT)}
    assert {"site/site.yaml", "site/details.yaml", "sla/it_partner.yaml", "src/scorecard/devices.py"} <= members
    with zipfile.ZipFile(tmp_path / "b.zip", "w") as z:
        for m in members:
            z.write(ROOT / m, m)
    with zipfile.ZipFile(tmp_path / "b.zip") as z:
        z.extractall(tmp_path / "app")
    code = ("import sys; sys.path.insert(0, 'src'); from scorecard import app_support as A; "
            "assert A.location_view('CDU-B3 pump 2'); assert A.device_lines('a13-ct18')[0].startswith('**This device**')")
    proc = subprocess.run([sys.executable, "-c", code], cwd=tmp_path / "app", capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
