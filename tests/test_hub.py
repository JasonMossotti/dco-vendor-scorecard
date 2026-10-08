"""Unified Site Management: the overview at the site root and the tab bar on every page.

The overview's numbers come from the same code as the pages it links to; these tests
check they match the headline results, and that every page carries the same tab bar
with working links.
"""

import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pytest

from scorecard import sitenav

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

PAGES = {"": "overview", "app/": "scorecards", "alarms/": "alarms", "pir/": "pir", "weekly/": "weekly", "patterns/": "patterns", "energy/": "energy", "gpu/": "gpu",
         "agreements/": "agreements", "agreements/interface-agreement/": "agreements", "agreements/it-partner-sla/": "agreements",
         "agreements/landlord-sla/": "agreements", "glossary/": "glossary"}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    import build_site
    out = tmp_path_factory.mktemp("site")
    build_site.build(out)
    return out


@pytest.fixture(scope="module")
def facts():
    import render_hub
    return render_hub.facts()


def test_overview_matches_the_headline_results(facts):
    assert (facts["it"]["defaults"], facts["it"]["credits"]) == (4, 188700)
    assert (facts["ll"]["defaults"], facts["ll"]["credits"]) == (4, 106200)
    assert (facts["it"]["detected"], facts["it"]["planted"]) == (17, 17)
    assert (facts["ll"]["detected"], facts["ll"]["planted"]) == (8, 8)
    al = facts["alarms"]
    assert (al["total"], al["expected"], al["flagged"], al["flag_changes"]) == (120, 11, 4, ["MOP-310"])
    assert facts["patterns"]["found"] == 3 and facts["pir"]["id"] == "PIR-2026-001"
    assert facts["pir"]["reviews"] >= 2 and facts["pir"]["open"] < facts["pir"]["actions"]
    assert [w for w, _ in facts["weeks"]] == ["2026-W36", "2026-W37", "2026-W38", "2026-W39"]


def test_overview_agrees_with_the_app_table(facts):
    """The Overview and the app's 'Both partners, measured' table are one set of numbers."""
    from scorecard import app_support as A
    from scorecard.sla_model import load_sla
    _, sc, ev = A.run_pipeline(load_sla(ROOT / "sla" / "it_partner.yaml"), ROOT / "data" / "sample")
    _, ll_sc, ll_ev, _ = A.run_landlord_pipeline(ROOT / "data" / "sample")
    rows = {r["Measure"]: r for r in A.site_rows(sc, ll_sc, ev, ll_ev)}
    assert rows["Minimum defaults (measured)"]["IT Partner"] == str(facts["it"]["defaults"])
    assert rows["Credits payable"]["IT Partner"] == f"${facts['it']['credits']:,.0f}"
    assert rows["Credits payable"]["Landlord"].startswith(f"${facts['ll']['credits']:,.0f}")
    assert rows["Findings (S1)"]["IT Partner"].startswith(f"{facts['it']['findings']} (")
    assert rows["Findings (S1)"]["Landlord"].startswith(f"{facts['ll']['findings']} (")


def test_site_has_every_page(site):
    for path in PAGES:
        assert (site / path / "index.html").exists(), path
    assert (site / "app" / "app_bundle.zip").exists() and (site / "app" / "streamlit_app.py").exists()


def test_every_page_has_the_tab_bar_with_its_own_tab_marked(site):
    for path, key in PAGES.items():
        html = (site / path / "index.html").read_text(encoding="utf-8")
        assert "__SITENAV" not in html, path
        assert html.count('<nav class="usm"') == 1, path
        on = re.findall(r'data-tab="(\w+)" class="on" aria-current="page"', html)
        assert on == [key], (path, on)
        assert re.findall(r'data-tab="(\w+)"', html) == sitenav.KEYS, path


def _links(html):
    return re.findall(r'href="([^"]+)"', re.sub(r"<script\b.*?</script[^>]*>", "", html, flags=re.S | re.I))


def test_every_internal_link_resolves(site):
    """Tab bar and Overview links, followed from each page, land on a page the build produced."""
    base = "https://example.test/site/"
    for path in PAGES:
        html = (site / path / "index.html").read_text(encoding="utf-8")
        nav = re.search(r'<nav class="usm".*?</nav>', html, re.S).group(0)
        checked = _links(nav) + (_links(html) if path == "" or path.startswith(("agreements/", "glossary/")) else [])
        for href in checked:
            if href.startswith(("http://", "https://", "#")) and not href.startswith(base):
                continue
            target = urlparse(urljoin(base + path, href)).path
            assert target.startswith("/site/"), (path, href)
            rel = target[len("/site/"):]
            f = site / rel / "index.html" if rel == "" or rel.endswith("/") else site / rel
            assert f.exists(), (path, href, f)


def test_overview_deep_links_name_real_sub_views(site):
    """#live, #changes, #notify (alarm board), #blank (PIR), and week ids (weekly) are views those pages open."""
    html = (site / "index.html").read_text(encoding="utf-8")
    hashes = {h for h in re.findall(r'href="(\w+/)#([\w-]+)"', html)}
    assert {("alarms/", "live"), ("alarms/", "changes"), ("alarms/", "notify"), ("pir/", "blank"), ("pir/", "reviews"),
            ("weekly/", "2026-W38")} <= hashes
    alarms = (ROOT / "templates" / "alarms.html").read_text(encoding="utf-8")
    assert '["board", "changes", "notify", "about"].includes(h)' in alarms and 'h === "live"' in alarms
    pir = (ROOT / "templates" / "pir.html").read_text(encoding="utf-8")
    assert 'if (h === "reviews") setMode("list")' in pir and 'else if (h === "blank") setMode("blank")' in pir
    assert 'h.startsWith("new=")' in pir, "a record's Start review link opens the form filled from it"


def test_app_page_keeps_one_scroll_bar_and_the_light_theme(site):
    import build_site
    html = (site / "app" / "index.html").read_text(encoding="utf-8")
    assert "overflow: hidden" in html and "transform: translateZ(0)" in html, "the page never scrolls; the app scrolls inside"
    assert '"theme.base": "light"' in html
    local = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    for k, v in local["theme"].items():
        assert build_site.STREAMLIT_CONFIG[f"theme.{k}"] == v, k


def test_static_pages_use_the_light_toolbar():
    for name in ("alarms", "pir", "weekly", "patterns", "energy", "gpu_health"):
        tpl = (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
        assert "header.top { background:#fff;" in tpl, name
        assert "__SITENAV__" in tpl and "__SITENAV_CSS__" in tpl, name


def test_unknown_tab_is_rejected():
    with pytest.raises(ValueError):
        sitenav.nav_html("nope")
