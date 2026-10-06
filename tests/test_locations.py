"""Location pins: every drawn item has a location, each box really surrounds its label, fields resolve
the way the popup script resolves them, and pins appear only on marked fields."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import locations as L  # noqa: E402
from scorecard import site_model as S  # noqa: E402
from scorecard.site_drawings import sheets  # noqa: E402

from test_glossary import _node  # noqa: E402


@pytest.fixture(scope="module")
def site_model():
    return S.load_site()


@pytest.fixture(scope="module")
def data(site_model):
    return L.build(site_model)


@pytest.fixture(scope="module")
def drawn(site_model):
    return {num: svg for num, _, _, svg in sheets(site_model)}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    import build_site
    out = tmp_path_factory.mktemp("site")
    build_site.build(out)
    return out


# ------------------------------------------------------------------ the generated data
def test_generated_file_matches_the_site(data):
    assert L.load() == json.loads(json.dumps(data)), "docs/site/locations.json is stale: run scripts/render_site.py"


def test_every_rack_and_named_piece_of_equipment_has_a_location(site_model, data):
    names = {r["rack"] for r in S.racks(site_model)} | {e["id"] for e in S.equipment(site_model)}
    missing = sorted(n for n in names if n not in data["entries"])
    assert not missing, f"drawn but not locatable: {missing}"
    for name, e in data["entries"].items():
        assert e["views"], name
        assert any(b[4] for v in e["views"] for b in v["b"]), f"{name} has nothing to outline"
        assert e["text"].endswith(".") and e["title"], name


def test_boxes_stay_on_their_sheet(data):
    for name, e in data["entries"].items():
        for v in e["views"]:
            s = data["sheets"][v["s"]]
            for x, y, w, h, _ in v["b"]:
                assert 0 <= x and 0 <= y and x + w <= s["w"] and y + h <= s["h"] and w > 0 and h > 0, (name, v["s"])


def _labels(svg: str) -> dict[str, list[tuple[float, float]]]:
    out: dict[str, list[tuple[float, float]]] = {}
    for x, y, t in re.findall(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]+)</text>', svg):
        out.setdefault(t, []).append((float(x), float(y)))
    return out


def _inside(pt, box, slack=2.0):
    x, y = pt
    bx, by, bw, bh = box[:4]
    return bx - slack <= x <= bx + bw + slack and by - slack <= y <= by + bh + slack


@pytest.mark.parametrize("prefix,label", [
    (r"[A-C]\d\d$", lambda n: n),                      # racks
    (r"CDU-[A-C]\d$", lambda n: n[4:]),                # hall plans label a CDU by its number
    (r"TW-[A-C]\d$", lambda n: n),
    (r"UPS-[A-C]\d$", lambda n: n), (r"MUPS-[A-C]\d$", lambda n: n), (r"MVSST-[A-C]\d$", lambda n: n),
    (r"CH-\d\d$", lambda n: n), (r"GEN-\d$", lambda n: n), (r"CRAH-[A-C]\d$", lambda n: n),
])
def test_each_outline_surrounds_its_own_label(data, drawn, prefix, label):
    """The outline is where the drawing writes the name: proof the box was recorded at the right place."""
    checked = 0
    for name, e in data["entries"].items():
        if not re.match(prefix, name):
            continue
        for v in e["views"]:
            if v["s"] == "A-101" or (v["s"] == "E-001" and name.startswith("GEN")):
                continue   # the building plan does not label single racks; the one-line labels generators above the symbol
            pts = _labels(drawn[v["s"]]).get(label(name), [])
            prim = [b for b in v["b"] if b[4]]
            if not pts:
                continue
            assert any(_inside(p, b) for p in pts for b in prim), f"{name} on {v['s']}: outline misses its label"
            checked += 1
    assert checked > 0


def test_power_paths_match_the_site_model(site_model, data):
    """A rack's one-line view outlines its power group and its two feeds, from the model, never typed."""
    for r in S.racks(site_model):
        e_view = next(v for v in data["entries"][r["rack"]]["views"] if v["s"] == "E-001")
        boxes = {tuple(b[:4]) for b in e_view["b"]}
        marks: dict = {}
        sheets(site_model, marks=marks)
        for side in "AB":
            assert tuple(marks["E-001"][r["feeds"][side]][0]) in boxes, (r["rack"], side)
        assert r["group"] is None or tuple(marks["E-001"][r["group"]][0]) in boxes


# ------------------------------------------------------------------ reading fields
@pytest.mark.parametrize("value,expected", [
    ("Hall A, rack A07", ("A07", "")),
    ("CDU-B3|Hall B", ("CDU-B3", "")),
    ("a23-ct18", ("A23", "Compute tray 18 in this rack")),
    ("A06_PowerShelf_1", ("A06", "Power shelf 1 in this rack")),
    ("PSU 5 in A06 power shelf 1", ("A06", "PSU 5 in power shelf 1 of this rack")),
    ("NVLink switch tray a15-nvsw3", ("A15", "NVLink switch tray 3 in this rack")),
    ("TO-A07-B", ("TO-A07-B", "")), ("TO-B29", ("TO-B29", "")),
    ("BW-A-R1-PG-A2-A", ("BW-A-R1-PG-A2-A", "")),
    ("Hall B electrical room", ("ER-B", "")),
    ("Hall C (800 VDC pilot)", ("HALL-C", "")),
    ("MV-A main breaker|Central plant", ("MV-A main breaker", "")),
    ("leaf-a07-r1 port 18|Hall A, rack A13",
     ("A13", "The drawings do not show leaf-a07-r1 port 18; shown at its recorded location")),
    ("leaf-a07-r1:swp18", None), ("TTDM-A/C8", None), ("MOP-310", None), ("138 kV utility service", None),
])
def test_fields_resolve_to_the_most_specific_location(data, value, expected):
    assert L.resolve_field(data, value) == expected


def test_alarm_board_fields_resolve_except_what_the_drawings_do_not_show():
    """Only fabric switch ports, leak controllers, and the central plant (fallbacks only) go unresolved, so a
    new kind of device or room with no location fails here instead of silently losing its pin."""
    import render_alarms
    f = render_alarms.prepare()
    data = L.load()
    values = [a["device"] + "|" + a["location"] for a in f["alarms"]] + [k["device"] + "|" + k["location"] for k in f["tickets"]]
    values += [w["unit"] for w in f["planned_work"]] + [o["device"] for o in f["owed"]]
    unresolved = {v for v in values if L.resolve_field(data, v) is None}
    assert all(re.match(r"(leaf-|TTDM-|MV switchgear\b|$)", v) or "Central plant" in v for v in unresolved), sorted(unresolved)
    assert len(values) - len(unresolved) > 100


# ------------------------------------------------------------------ the pages
def test_pages_with_fields_carry_only_the_locations_they_name(site):
    for page in ("alarms", "pir", "weekly", "patterns"):
        html = (site / page / "index.html").read_text(encoding="utf-8")
        assert 'id="loc-data"' in html, page
        blob = json.loads(re.search(r'<script id="loc-data" type="application/json">(.*?)</script>', html, re.S).group(1))
        assert 0 < len(blob["entries"]) < len(L.load()["entries"]), page
    for page in ("", "agreements/it-partner-sla", "glossary"):
        assert 'id="loc-data"' not in (site / page / "index.html").read_text(encoding="utf-8"), f"{page or 'overview'} has no fields"
    assert sorted(p.name for p in (site / "site").glob("*.svg")) == sorted(p.name for p in (ROOT / "docs" / "site").glob("*.svg"))


@pytest.mark.parametrize("page,expected,redraw", [
    ("alarms/", "A07", None),
    ("pir/", "A07", None),
    ("weekly/", "A07", '[data-week="2026-W36"]'),
    ("patterns/", "A11", '#tabs button:nth-child(2)'),
])
def test_pins_in_a_browser(site, page, expected, redraw):
    out = _node("location_popups.cjs", site, page, expected, *([redraw] if redraw else []))
    fields = json.loads(next(line for line in out.splitlines() if line.startswith("FIELDS "))[7:])
    data = L.load()
    for value, got in fields.items():   # the script reads every field exactly as locations.resolve_field does
        exp = L.resolve_field(data, value)
        assert (list(exp) if exp else None) == got, value


# ------------------------------------------------------------------ the Scorecards app
@pytest.mark.parametrize("query,title,sheet", [("a07", "Rack A07", "E-001 Electrical one-line"),
                                               ("CDU-B3", "CDU-B3", "A-202 Hall B floor plan")])
def test_app_lookup_shows_the_location_on_a_drawing(monkeypatch, query, title, sheet):
    import runpy
    from fake_streamlit import FakeStreamlit
    fake = FakeStreamlit(overrides={"View": "IT Partner (Ridgeline)", "Code or ID": query, "Drawing": sheet})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    runpy.run_path(str(ROOT / "app" / "streamlit_app.py"), run_name="__main__")
    md = " ".join(fake.texts("markdown"))
    assert f"**{title}**" in md and "No code or ID matches" not in md
    imgs = fake.texts("image")
    assert len(imgs) == 1 and 'class="loc-hl"' in imgs[0] and 'stroke="#d62728"' in imgs[0]
