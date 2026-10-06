"""Equipment detail sheets: every part has a public source or a stated assumption, every part is drawn
with its tag inside its outline, alarms name the right part, and the pages and the app open the sheet."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import detail_drawings as DD  # noqa: E402
from scorecard import locations as L  # noqa: E402
from scorecard import site_model as S  # noqa: E402

DETAILS = DD.load_details()


@pytest.fixture(scope="module")
def drawn():
    marks: dict = {}
    return {num: (svg, marks[num]) for num, _, _, svg in DD.detail_sheets(marks)}


# ------------------------------------------------------------------ the data
@pytest.mark.parametrize("key", sorted(DETAILS["products"]))
def test_every_part_has_a_source_or_a_stated_assumption(key):
    spec = DETAILS["products"][key]
    assert key in S.load_site()["products"], f"{key} is not a product in site/site.yaml"
    assert spec["sources"] and all(s["url"].startswith("https://") and s["says"] for s in spec["sources"].values())
    for p in spec["parts"]:
        b = p["basis"]
        if isinstance(b, str):
            assert b.startswith("assumption: "), (key, p["id"])
        else:
            assert b and all(s in spec["sources"] for s in b), (key, p["id"], b)
        assert "position" not in p or p["position"].startswith("assumption: "), (key, p["id"])
    assert spec["order_note"] and spec["alarm_points"]


def test_sheet_numbers_follow_the_drawing_set():
    nums = [s["sheet"] for s in DETAILS["products"].values()]
    assert len(set(nums)) == len(nums)
    cat = {"compute_rack": "D-1", "cdu": "D-2", "thermal_wall": "D-2", "chiller": "D-2", "ups": "D-3", "busway": "D-3",
           "generator": "D-4", "smoke_detection": "D-5", "leak_detection": "D-5", "ib_switch": "D-6"}
    site = S.load_site()
    for k, s in DETAILS["products"].items():
        assert s["sheet"].startswith(cat[site["products"][k]["category"]]), k


def test_the_rack_has_what_the_sources_say():
    """18 compute trays, 9 NVLink switch trays, 8 power shelves of 6 PSUs (NVIDIA, Supermicro)."""
    ids = DD.parts(DETAILS["products"]["gb200_nvl72"])
    count = lambda pat: sum(bool(re.fullmatch(pat, i)) for i in ids)
    assert (count(r"ct\d+"), count(r"nvsw\d+"), count(r"ps\d+"), count(r"ps\d+-psu\d+")) == (18, 9, 8, 48)
    assert len(DD.parts(DETAILS["products"]["galaxy_vx_1500"]).keys() & {f"pm{i}" for i in range(1, 9)}) == 7


# ------------------------------------------------------------------ the drawings
def _texts(svg: str) -> list[tuple[float, float, str]]:
    return [(float(x), float(y), t) for x, y, t in re.findall(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]+)</text>', svg)]


@pytest.mark.parametrize("key", sorted(DETAILS["products"]))
def test_each_part_is_drawn_with_its_tag_inside_its_outline(drawn, key):
    spec = DETAILS["products"][key]
    svg, marks = drawn[spec["sheet"]]
    ps = DD.parts(spec)
    assert set(marks) == set(ps) | {"device"}, "every part is drawn, and every drawn box is a part"
    texts = _texts(svg)
    for pid, p in ps.items():
        boxes = marks[pid]
        inside = [t for x, y, t in texts if t == p["tag"]
                  and any(bx <= x <= bx + bw and by <= y <= by + bh for bx, by, bw, bh in boxes)]
        assert inside, f"{spec['sheet']} {pid}: no '{p['tag']}' inside its outline"


@pytest.mark.parametrize("key", sorted(DETAILS["products"]))
def test_sheets_say_they_are_representative(drawn, key):
    svg = drawn[DETAILS["products"][key]["sheet"]][0]
    words = " ".join(t for _, _, t in _texts(svg))
    assert "(representative)" in words and "not a manufacturer drawing" in words


def test_the_leaf_switch_numbers_ports_two_per_cage(drawn):
    """Port n is the n-th NDR port; cage c holds ports 2c-1 and 2c (stated as assumed on the sheet)."""
    marks = drawn["D-601"][1]
    assert len([k for k in marks if k.startswith("port")]) == 64
    p1, p2, p3 = marks["port1"][0], marks["port2"][0], marks["port3"][0]
    assert p1[0] == p2[0] and p2[1] > p1[1], "ports 1 and 2 share a cage"
    assert p3[0] == p1[0] and p3[1] > p2[1], "cage 2 sits below cage 1"


def test_site_sheets_point_to_the_details():
    site = S.load_site()
    docs = ROOT / "docs" / "site"
    hall_a = (docs / "A-201_hall_a_plan.svg").read_text(encoding="utf-8")
    assert "Typical details:" in hall_a and "rack D-101" in hall_a and "CDU D-201" in hall_a
    e001 = (docs / "E-001_one_line.svg").read_text(encoding="utf-8")
    assert "UPS line-up D-301" in e001 and "mechanical UPS D-302" in e001 and "generator D-401" in e001
    assert "leaf switch D-601" in hall_a and "leak detection D-502" in hall_a and "thermal wall D-202" in hall_a
    assert "rack D-102" in (docs / "A-202_hall_b_plan.svg").read_text(encoding="utf-8")
    assert "chiller D-203" in (docs / "M-001_cooling_flow.svg").read_text(encoding="utf-8")
    assert "D-101" not in (docs / "A-202_hall_b_plan.svg").read_text(encoding="utf-8"), "Hall B racks are GB300"
    md = (docs / "SITE.md").read_text(encoding="utf-8")
    for spec in DETAILS["products"].values():
        assert f"| {spec['sheet']} |" in md
    assert site


# ------------------------------------------------------------------ alarms to parts
@pytest.mark.parametrize("value,text,expected", [
    ("a23-ct18", "", ("A23", "ct18")),
    ("a22-ct07", "GPU error (XID)", ("A22", "ct7")),
    ("A06_PowerShelf_1", "PSU failed PSU 5 in A06 power shelf 1 reported failure", ("A06", "ps1-psu5")),
    ("A23_PowerShelf_7", "Power shelf failed A23 power shelf 7 reported failure", ("A23", "ps7")),
    ("PSU 5 in A06 power shelf 1", "", ("A06", "ps1-psu5")),
    ("a15-nvsw3", "NVLink switch tray failed", ("A15", "nvsw3")),
    ("Rack A06|Hall A, rack A06", "Rack leak detected Leak at A06 rack manifold: leak detector tripped", ("A06", "manifold")),
    ("CDU-A1|Hall A, rack A06", "Rack leak detected A06 leak rope: leak detected", ("A06", "drip")),
    ("Rack A07|Hall A, rack A07", "Rack input power lost (both feeds)", ("A07", "ac-in")),
    ("Rack A07|Hall A, rack A07", "Rack outage Rack A07: 18 nodes not responding", None),
    ("CDU-B3|Hall B", "Pump 2 fault", ("CDU-B3", "pump2")),
    ("CDU-B3 pump 2", "", ("CDU-B3", "pump2")),
    ("UPS-A2|Hall A electrical room", "Module 6 fault", ("UPS-A2", "pm6")),
    ("UPS-A1|Hall A electrical room", "UPS on battery", ("UPS-A1", "battery")),
    ("UPS-A1|Hall A electrical room", "UPS on maintenance bypass", ("UPS-A1", "mbb")),
    ("UPS-B4 output feeder to BW-B-R3-PG-B4-B|Hall B electrical room", "Breaker trip", ("UPS-B4", "out-brk")),
    ("BW-B-R1-PG-B1-B|Hall B", "Tap-off breaker open Tap-off TO-B29 open on BW-B-R1-PG-B1-B", ("TO-B29", "to-brk")),
    ("BW-B-R3-PG-B4-B|Hall B", "Busway undervoltage", ("BW-B-R3-PG-B4-B", "feed-cpm")),
    ("BW-B-R3-PG-B4-B|Hall B", "Tenant whip fault on rack B21; Landlord equipment healthy", ("BW-B-R3-PG-B4-B", "cord")),
    ("TO-A07-B", "", None),                                       # a tap-off with nothing said about it
    # a unit the site plans do not show: its sheet opens, never a part of the recorded location (rack A13)
    ("leaf-a07-r1 port 18|Hall A, rack A13", "Fabric link down leaf-a07-r1 port 18 to a13-ct18: link down",
     ("leaf-a07-r1", "port18")),
    ("TTDM-A|Hall A", "Leak circuit 8 at 13.2 m", ("TTDM-A", "c8")),
    ("B07", "PSU failed PSU 5 in B07 power shelf 1", ("B07", "ps1-psu5")),
    ("b03-ct09", "GPU error (XID)", ("B03", "ct9")),
    ("MUPS-A1|Hall A electrical room", "UPS on battery", ("MUPS-A1", "battery")),
    ("TW-A4|Hall A", "Fan 6 failure", ("TW-A4", "fan6")),
    ("TW-B2|Hall B", "Alarm inhibited: High supply air temperature alarm = Inhibited", ("TW-B2", "sat")),
    ("CH-08|Chiller yard", "Compressor trip (high condenser pressure)", ("CH-08", "compressor")),
    ("CH-05|Chiller yard", "Condenser fan fault", ("CH-05", "fans")),
    ("CH-06|Chiller yard", "Point override: Chiller enable = Off", ("CH-06", "controller")),
    ("VESDA-B2|Hall B electrical room", "Detector fault: airflow low", ("VESDA-B2", "inlets")),
    ("VESDA-B1|Hall B", "Smoke alarm VESDA-B1 smoke alarm Fire 1 (Smoke test)", ("VESDA-B1", "chamber")),
    ("VESDA-B1|Hall B", "Detector isolated VESDA-B1 isolated (Inspection)", ("VESDA-B1", "display")),
    ("MV switchgear|Central plant", "Utility power lost", None),   # no product sheet for the switchgear
])
def test_alarm_text_names_the_part(value, text, expected):
    assert L.resolve_field_part(L.load(), value, text) == expected


def test_every_sample_alarm_on_a_detailed_product_names_a_part():
    """60 generated months are checked by `python scripts/render_alarms.py --robustness 60`."""
    import render_alarms
    f = render_alarms.prepare()
    checked, missing = L.part_coverage(L.load(), f["alarms"])
    assert checked > 50 and not missing, missing
    tickets = [{"device": k["device"], "location": k["location"], "signal": "", "summary": k["summary"]} for k in f["tickets"]]
    checked, missing = L.part_coverage(L.load(), tickets)
    # a ticket's summary is the engineer's words; this one is about the whole chiller (a reset), not a part
    assert checked > 20 and missing == ["CH-05:  (Engineer attended and reset the unit)"], missing


def test_every_part_a_point_can_name_exists():
    """Each pattern's part template, filled with the numbers the telemetry uses, is a part on the sheet."""
    data = L.load()
    for pat, flags, product, part_t, inst_t in data["points"]:
        re.compile(pat)
        assert flags in ("", "i") and product in data["details"], pat
        if "{" not in part_t:
            assert part_t in data["details"][product]["parts"], pat


def test_cards_put_the_detail_sheet_first():
    data = L.load()
    title, views = L.card(data, "CDU-B3", ("CDU-B3", "pump2"))
    assert title == "CDU-B3 · Pump 2" and views[0][0]["s"] == "D-201" and views[0][1] == "CDU-B3 · Pump 2"
    assert [v["s"] for v, _ in views[1:]] == [v["s"] for v in data["entries"]["CDU-B3"]["views"] if v["s"] != "D-201"]
    title, views = L.card(data, "BW-B-R3-PG-B4-B", ("UPS-B4", "out-brk"))
    assert title == "Busway BW-B-R3-PG-B4-B · UPS-B4 output feeder breakers to the busways"
    assert views[0][0]["s"] == "D-301" and views[0][1] == "UPS-B4 · Output feeder breakers to the busways"
    assert views[-1][0]["s"] == "D-303", "the busway's own detail sheet stays, last"
    title, views = L.card(data, "A13", ("leaf-a07-r1", "port18"))
    assert title == "Rack A13 · leaf-a07-r1 port 18" and views[0][0]["s"] == "D-601" and views[1][0]["s"] == "A-201"
    _, views = L.card(data, "A07", None)
    assert views[-1][0]["s"] == "D-101" and views[0][0]["s"] == "A-201", "without a part, the site sheets lead"


# ------------------------------------------------------------------ the Scorecards app
def test_app_lookup_shows_the_part_on_its_detail_sheet(monkeypatch):
    import runpy
    from fake_streamlit import FakeStreamlit
    fake = FakeStreamlit(overrides={"View": "IT Partner (Ridgeline)", "Code or ID": "CDU-B3 pump 2"})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    runpy.run_path(str(ROOT / "app" / "streamlit_app.py"), run_name="__main__")
    md = " ".join(fake.texts("markdown"))
    assert "**CDU-B3 · Pump 2**" in md
    imgs = fake.texts("image")
    assert len(imgs) == 1 and "CHx2000 CDU" in imgs[0] and "CDU-B3 · Pump 2" in imgs[0]
