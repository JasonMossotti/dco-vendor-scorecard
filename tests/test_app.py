"""Run the interactive app end to end against a Streamlit stand-in.

The real UI is exercised in the browser; these tests make sure the app's logic
runs without errors for each dataset option and for what-if changes.
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


def test_app_renders_with_committed_sample(monkeypatch):
    fake = run_app(monkeypatch)
    assert any("Vendor SLA Scorecard" in t for t in fake.texts("title"))
    assert len(fake.texts("dataframe")) >= 6
    assert not fake.texts("warning"), "no what-if banner at contract values"
    md = " ".join(fake.texts("markdown"))
    assert "Minimum defaults" in md and "Engine self-check" in " ".join(fake.texts("subheader"))


def test_app_what_if_shows_banner_and_more_defaults(monkeypatch):
    base = run_app(monkeypatch)
    tight = run_app(monkeypatch, overrides={"P2 restore target (hours)": 4.0})
    assert any("What-if" in t for t in tight.texts("warning"))
    d = lambda f: next(v for k, v in f.drawn if k == "metric" and v[0] == "Minimum defaults")[1]  # noqa: E731
    assert d(tight) > d(base)


def test_app_generate_flow(monkeypatch):
    with pytest.raises(StopApp):           # before pressing Generate the app asks for a seed
        run_app(monkeypatch, overrides={"Dataset": "Generate a new random month"})
    fake = run_app(monkeypatch, overrides={"Dataset": "Generate a new random month", "Seed": 11},
                   buttons={"Generate"})
    assert any("seed 11" in t for t in fake.texts("caption"))


def test_reset_moves_widgets_back_to_contract(monkeypatch):
    """Regression: Reset must restore the widget values themselves, not only the results."""
    moved = {"wf_restore_P2": 11.0, "wf_early": 120, "wf_atrisk": 15.0}
    still_moved = run_app(monkeypatch, session_state=moved)
    assert any("What-if" in t for t in still_moved.texts("warning"))
    reset = run_app(monkeypatch, session_state=moved, buttons={"Reset to contract values"})
    sla = load_sla()
    assert reset.session_state["wf_restore_P2"] == next(p for p in sla["priorities"] if p["id"] == "P2")["restore_min"] / 60
    assert reset.session_state["wf_early"] == sla["ticket_handling"]["stability"]["early_failure_minutes"]
    assert not reset.texts("warning"), "no what-if banner after reset"


def test_invalid_threshold_is_rejected(monkeypatch):
    fake = run_app(monkeypatch, overrides={"Expected (%)": 90.0, "Minimum (%)": 99.0})
    assert any("Expected must be" in t for t in fake.texts("error"))


def test_overrides_round_trip():
    sla = load_sla()
    d = A.contract_defaults(sla)
    assert A.changed_from_contract(sla, d) == []
    new = A.apply_overrides(sla, {"restore_hours": {"P1": 2.0}, "at_risk_pct": 15})
    assert next(p for p in new["priorities"] if p["id"] == "P1")["restore_min"] == 120
    assert new["commercial"]["at_risk_pct"] == 15
    assert next(p for p in sla["priorities"] if p["id"] == "P1")["restore_min"] == 240   # original untouched


def test_built_site_runs_in_browser_layout(monkeypatch, tmp_path):
    """Recreate what stlite does (unzip the bundle next to the entrypoint) and run the app there."""
    import zipfile
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site
    site = tmp_path / "site"
    build_site.build(site)
    html = (site / "index.html").read_text(encoding="utf-8")
    assert f"@stlite/browser@{build_site.STLITE_VERSION}/build/stlite.js" in html
    assert 'entrypoint: "streamlit_app.py"' in html and "app_bundle.zip" in html

    home = tmp_path / "pyodide_home"                 # the browser's virtual home directory
    home.mkdir()
    with zipfile.ZipFile(site / "app_bundle.zip") as z:
        names = z.namelist()
        assert "sla/vendor_sla.yaml" in names and "src/scorecard/app_support.py" in names
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
    assert any("Vendor SLA Scorecard" in t for t in fake.texts("title"))
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
