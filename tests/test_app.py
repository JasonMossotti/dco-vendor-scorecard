"""Run the interactive app end to end against a Streamlit stand-in.

The real UI is exercised in the browser; these tests make sure the app's logic
runs without errors for each dataset option.
"""

import runpy
import sys
from pathlib import Path

import pytest

from scorecard import app_support as A
from scorecard.sla_model import load_sla

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_streamlit import FakeStreamlit, StopApp  # noqa: E402


def run_app(monkeypatch, **kw) -> FakeStreamlit:
    fake = FakeStreamlit(**kw)
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    runpy.run_path(str(APP), run_name="__main__")
    return fake


def test_app_opens_on_the_site_summary(monkeypatch):
    fake = run_app(monkeypatch)
    assert any("two partners" in t for t in fake.texts("title"))
    subs = " ".join(fake.texts("subheader"))
    assert "Both partners, measured" in subs and "What attribution changed" in subs
    md = " ".join(fake.texts("markdown"))
    assert "went dark" in md and "FA-3" in md, "the cross-partner outage is explained"


def test_landlord_view(monkeypatch):
    fake = run_app(monkeypatch, overrides={"View": "Landlord (Caprock)"})
    assert any("Landlord SLA Scorecard" in t for t in fake.texts("title"))
    assert len(fake.texts("dataframe")) >= 4
    md = " ".join(fake.texts("markdown"))
    assert "credits against rent" in md and "8 of 8" in md
    assert "$" not in md.replace("\\$", ""), "every dollar sign is escaped (a pair renders as math)"


def test_app_renders_with_committed_sample(monkeypatch):
    fake = run_app(monkeypatch, overrides={"View": "IT Partner (Ridgeline)"})
    assert any("Vendor SLA Scorecard" in t for t in fake.texts("title"))
    assert len(fake.texts("dataframe")) >= 6
    md = " ".join(fake.texts("markdown"))
    assert "Minimum defaults" in md and "Engine self-check" in " ".join(fake.texts("subheader"))


def test_app_has_no_what_if_controls(monkeypatch):
    """The SLA terms are the signed contract; the app reports against them and offers no sliders."""
    fake = run_app(monkeypatch)
    assert not [k for k, _ in fake.drawn if k == "slider"]
    headers = " ".join(fake.texts("header"))
    assert "What if" not in headers


def test_app_navigation_is_on_the_page_not_in_a_sidebar(monkeypatch):
    """Views are a segmented control at the top; the site's tab bar carries the links to the other pages."""
    fake = run_app(monkeypatch)
    assert fake.sidebar_used == [], f"nothing is drawn in the sidebar: {fake.sidebar_used}"
    seg = [p for k, p in fake.drawn if k == "segmented_control"]
    assert seg == [("View", ["Site summary", "IT Partner (Ridgeline)", "Landlord (Caprock)"])]


def test_view_survives_being_clicked_off(monkeypatch):
    """Clicking the selected segment returns None in real Streamlit; the app keeps the last view."""
    fake = run_app(monkeypatch, overrides={"View": None}, session_state={"last_view": "Landlord (Caprock)"})
    assert any("Landlord SLA Scorecard" in t for t in fake.texts("title")), "a None view falls back to the last view"


def test_app_generate_flow(monkeypatch):
    with pytest.raises(StopApp):           # before pressing Generate the app asks for a seed
        run_app(monkeypatch, overrides={"Dataset": "Generate a new random month"})
    fake = run_app(monkeypatch, overrides={"Dataset": "Generate a new random month", "Seed": 11},
                   buttons={"Generate"})
    assert any("seed 11" in t for t in fake.texts("caption"))


def test_built_site_runs_in_browser_layout(monkeypatch, tmp_path):
    """Recreate what stlite does (unzip the bundle next to the entrypoint) and run the app there."""
    import zipfile
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site
    site = tmp_path / "site"
    build_site.build(site)
    site = site / "app"                              # the app is served at /app/, under the site tab bar
    html = (site / "index.html").read_text(encoding="utf-8")
    assert f"@stlite/browser@{build_site.STLITE_VERSION}/build/stlite.js" in html
    assert 'entrypoint: "streamlit_app.py"' in html and "app_bundle.zip" in html

    home = tmp_path / "pyodide_home"                 # the browser's virtual home directory
    home.mkdir()
    with zipfile.ZipFile(site / "app_bundle.zip") as z:
        names = z.namelist()
        assert {"sla/common.yaml", "sla/it_partner.yaml", "sla/ot_partner.yaml", "site/site.yaml"} <= set(names)
        assert not any("/live/" in n for n in names), "the live collector is not shipped to the browser" and "src/scorecard/app_support.py" in names
        assert not any(n.startswith(("tests/", "reports/", "docs/")) for n in names)
        z.extractall(home)
    (home / "streamlit_app.py").write_bytes((site / "streamlit_app.py").read_bytes())

    monkeypatch.chdir(home)
    for mod in [m for m in sys.modules if m == "scorecard" or m.startswith("scorecard.")]:
        monkeypatch.delitem(sys.modules, mod)          # import the bundled copy, not the repo's
    monkeypatch.setattr(sys, "path", [str(home / "src")] + [p for p in sys.path if "dco-vendor-scorecard/src" not in p])
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    runpy.run_path(str(home / "streamlit_app.py"), run_name="__main__")
    assert any("two partners" in t for t in fake.texts("title"))
    import scorecard
    assert str(home) in scorecard.__file__


def test_display_tables_are_tidy():
    _, sc, _ = A.run_pipeline(load_sla(), ROOT / "data" / "sample")
    for r in A.csl_rows(sc):
        assert "≥ 100%" not in (r["Expected"], r["Minimum"])
    for row in A.weekly_rows(sc):
        for k, v in row.items():
            if isinstance(v, float):
                assert round(v, 1) == v, (k, v)
    gaps = A.weekly_gap_rows(sc)
    assert all(v <= 0 for row in gaps for k, v in row.items() if k != "Week" and v is not None), \
        "the vendor never under-reports in this dataset"
