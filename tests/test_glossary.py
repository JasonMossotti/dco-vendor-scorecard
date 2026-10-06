"""The glossary, the code popups, the Agreements tab, and the Glossary tab.

Facts come from the contracts: a contract code's meaning is quoted from the SLA YAML, and its
"defined in" link lands on the clause. Every code the site shows is explained or left plain on
purpose, and every hand-written entry is still used somewhere.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard import agreements as AG
from scorecard import glossary as G
from scorecard import sitenav
from scorecard.sla_model import load_sla

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def gl():
    return G.load()


@pytest.fixture(scope="module")
def scanned(gl):
    import render_glossary
    return render_glossary.scan(gl)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    import build_site
    out = tmp_path_factory.mktemp("site")
    build_site.build(out)
    return out


# ------------------------------------------------------------------ coverage
def test_every_code_on_the_site_is_explained(scanned):
    assert not scanned["unexplained"], f"add these to config/glossary.yaml: {sorted(scanned['unexplained'])}"


def test_every_hand_written_entry_is_used(scanned):
    cfg = G.config()
    hand = [t["term"] for t in cfg["terms"]] + [f["key"] for f in cfg["families"]]
    unused = [k for k in hand if k not in scanned["used"]]
    assert not unused, f"no page uses these any more; remove them from config/glossary.yaml: {unused}"


def test_keys_are_unique_and_contracts_are_not_retyped(gl):
    keys = [e.key for e in gl.entries()]
    assert len(keys) == len(set(keys))
    contract = set(G.contract_entries())
    assert not contract & {t["term"] for t in G.config()["terms"]}


def test_every_example_is_its_own_family(gl):
    for f in gl.families:
        assert f.example and re.fullmatch(f.pattern, f.example), f.key
        assert gl.lookup(f.example, (f.on or [None])[0])[0] is f, f.key


def test_page_specific_meanings(gl):
    assert [e.key for e in gl.lookup("D1", "weekly")] == ["WK-D"]
    assert [e.key for e in gl.lookup("D1", "scorecards")] == ["CREW"]
    assert gl.lookup("D1", "alarms") == []
    assert [e.key for e in gl.lookup("P2", "patterns")] == ["FP-P", "P2"], "the pattern number and the priority"
    assert [e.key for e in gl.lookup("P2", "weekly")] == ["P2"]
    assert gl.lookup("A07") == [] and gl.ignored("A07"), "rack positions stay plain"
    assert [e.key for e in gl.lookup("CDUs")] == ["CDU"], "plurals resolve to the singular"


# ------------------------------------------------------------- facts from the contracts
def test_contract_meanings_quote_the_yaml(gl):
    it = load_sla(ROOT / "sla" / "it_partner.yaml")
    ot = load_sla(ROOT / "sla" / "ot_partner.yaml")
    csl07 = next(c for c in it["critical_service_levels"] if c["id"] == "CSL-07")
    s = gl.exact["CSL-07"].senses
    assert len(s) == 1 and s[0].title == csl07["name"] and s[0].text.startswith(csl07["description"]) and s[0].docs == ["it"]
    tr1 = {x["id"]: x["rule"] for x in it["ticket_handling"]["stability"]["rules"]}["TR-1"]
    tr1_ll = {x["id"]: x["rule"] for x in ot["ticket_handling"]["stability"]["rules"]}["TR-1"]
    assert [x.text for x in gl.exact["TR-1"].senses] == [tr1, tr1_ll], "each partner SLA's own wording"
    assert gl.exact["S1"].senses[0].docs == ["it", "landlord"], "identical terms merge"
    assert gl.exact["T0"].senses[0].title == "Fault Detection Time", "abbreviations come from the definitions"


def test_every_contract_meaning_links_to_its_clause(gl, scanned):
    for e in gl.entries():
        if e.key not in scanned["used"]:
            continue
        for s, d in zip(e.senses, G.entry_data(e)["senses"]):
            if s.docs:
                assert d["where"], f"{e.term}: no clause found in {s.docs}"


def test_definition_finder():
    md = AG.read("it")
    d = AG.definitions(md)
    assert d["CSL-07"].section == "10. Critical Service Levels"
    assert md.split("\n")[d["CSL-07"].line].startswith("### CSL-07:"), "the full clause, not the summary table row"
    assert d["T0"].section == "3. Definitions", "the defined term, not a 'T0 rule' row"
    assert md.split("\n")[d["IN_PROGRESS"].line].startswith("| `IN_PROGRESS`")


# ------------------------------------------------------------------ the Agreements tab
def test_agreement_pages_keep_every_line_and_anchor(site, gl):
    for key, slug, title, path in AG.DOCUMENTS:
        html = (site / "agreements" / slug / "index.html").read_text(encoding="utf-8")
        md = (ROOT / path).read_text(encoding="utf-8")
        ids = set(re.findall(r'\sid="([^"]+)"', html))
        for href in re.findall(r'href="#([^"]+)"', html):
            assert href in ids, (slug, href)
        for code in G.anchors()[key]:
            assert code in ids, (slug, code)
        rows = len([ln for ln in md.split("\n") if ln.startswith("|") and not re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", ln.strip())])
        assert html.count("<tr") == rows, slug
        text = re.sub(r"<[^>]+>", "", re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S))
        for heading in re.findall(r"^#{1,4} (.+)$", md, re.M):
            assert AG._plain(heading).replace("&", "&amp;") in text, (slug, heading)
        assert f"<title>{title} · Agreements" in html


def test_markdown_renderer():
    html = AG.to_html("## 2. A & B\n\nText with **bold**, *it*, `CODE_1`, [link](#x), and a<br>break.\n\n"
                      "| A | B |\n|---|---|\n| **TR-1** | rule |\n\n- one\n  - nested\n- [ ] box\n\n1. first\n\n> quote\n\n---",
                      {6: "TR-1"})
    assert '<h2 id="2-a--b">2. A &amp; B</h2>' in html
    assert "<strong>bold</strong>" in html and "<em>it</em>" in html and "<code>CODE_1</code>" in html
    assert '<a href="#x">link</a>' in html and "a<br>break" in html
    assert '<tr id="TR-1" data-gl-def="TR-1"><td><strong>TR-1</strong></td><td>rule</td></tr>' in html
    assert "<ul><li>one<ul><li>nested</li></ul></li><li>☐ box</li></ul>" in html
    assert "<ol><li>first</li></ol>" in html and "<blockquote>" in html and "<hr>" in html
    assert "<script" not in AG.to_html("<script>alert(1)</script>")


# ------------------------------------------------------------------ popups on every page
def test_every_static_page_has_popups_with_just_its_codes(site):
    pages = ["", "alarms/", "pir/", "weekly/", "patterns/", "agreements/", "agreements/it-partner-sla/", "glossary/"]
    for path in pages:
        html = (site / path / "index.html").read_text(encoding="utf-8")
        assert html.count('<script id="gl-data"') == 1, path
        assert "GLOSSARY_POPUPS" not in html, path
    app = (site / "app" / "index.html").read_text(encoding="utf-8")
    assert "gl-data" not in app, "Streamlit owns the app's markup; the app has its own lookup"
    import json
    hub = (site / "index.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script id="gl-data" type="application/json">(.*?)</script>', hub, re.S).group(1).replace("<\\/", "</"))
    keys = {e["key"] for e in data["entries"]}
    assert "MOP-N" in keys and "CSL-07" not in keys, "a page carries only the entries its own codes need"


def test_popup_links_land_on_real_anchors(site):
    import json
    for path, prefix in (("weekly/", "../"), ("agreements/landlord-sla/", "../../")):
        html = (site / path / "index.html").read_text(encoding="utf-8")
        data = json.loads(re.search(r'<script id="gl-data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
        assert data["root"] == prefix
        for e in data["entries"]:
            for s in e["senses"]:
                for w in s["where"]:
                    page, anchor = w["href"].split("#")
                    target = (site / page / "index.html").read_text(encoding="utf-8")
                    assert f'id="{anchor}"' in target, (path, w)
            if e.get("see"):
                assert (site / e["see"].split("#")[0] / "index.html").exists(), e["see"]


def test_python_and_browser_patterns_agree(gl):
    pat = re.compile(gl.link_pattern("weekly"))
    for t, e in gl.exact.items():
        if e.link and not e.code_only:
            assert pat.fullmatch(t), t
    for f in gl.families:
        m = re.compile(gl.link_pattern(f.on[0] if f.on else "weekly")).search(f"see {f.example}.")
        assert m and m.group() == f.example, f.key
    assert not pat.search("Crew N1"), "a meaning for one page is not underlined on another"
    assert not pat.search("IT and UTC and GPU"), "everyday acronyms are listed, not underlined"
    assert pat.search("rack CDUs here").group() == "CDU"


def test_glossary_document_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_glossary.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_tab_bar_has_reference_tabs_on_the_right():
    nav = sitenav.nav_html("glossary")
    main, ref = re.findall(r'<div class="usm-tabs[^"]*">(.*?)</div>', nav)
    assert re.findall(r'data-tab="(\w+)"', ref) == ["agreements", "glossary"]
    assert "agreements" not in main


# ------------------------------------------------------------------ the Scorecards app
def test_app_lookup_and_findings_explain_codes(monkeypatch):
    import runpy
    from fake_streamlit import FakeStreamlit
    fake = FakeStreamlit(overrides={"View": "IT Partner (Ridgeline)", "Code or ID": "csl-07"})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    runpy.run_path(str(ROOT / "app" / "streamlit_app.py"), run_name="__main__")
    assert "Look up a code" in fake.texts("popover")
    md = " ".join(fake.texts("markdown"))
    assert "**CSL-07** · Service levels" in md and "Defined in IT Partner SLA, 10. Critical Service Levels" in md
    assert re.search(r"\*\*SLA references:\*\* CSL-\d\d \([A-Z]", md), "finding references carry their meaning"


# ------------------------------------------------------------------ browser checks (jsdom)
def _node(script, *args):
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, script, *map(str, args)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


@pytest.mark.parametrize("path,code,redraw", [
    ("patterns/", "CDU-A3", '#tabs button:nth-child(2)'),
    ("pir/", "MOP-310", None),
    ("weekly/", "CSL-07", '[data-week="2026-W36"]'),
    ("alarms/", "MOP-310", None),
    ("agreements/it-partner-sla/", "TR-1", None),
    ("agreements/interface-agreement/", "NT-1", None),
    ("", "MOP-310", None),
])
def test_popups_in_a_browser(site, path, code, redraw):
    args = [site / path / "index.html", f"https://example.test/{path}", code] + ([redraw] if redraw else [])
    _node("glossary_popups.cjs", *args)


def test_glossary_page_in_a_browser(site):
    _node("glossary_page.cjs", site / "glossary" / "index.html")
