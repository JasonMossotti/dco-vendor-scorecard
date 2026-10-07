"""GPU XID codes: the Glossary addendum from NVIDIA's public Xid catalog and the XID popups.

Every XID the site shows has a meaning, the names the synthetic data and the pattern review print are
NVIDIA's, and the critical XIDs the IT Partner SLA names are the ones the catalog marks critical.
"""

import json
import re
import sys
from pathlib import Path

from scorecard import glossary as G
from scorecard import patterns, xid
from scorecard.synthetic import generator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_catalog_is_complete_and_sourced():
    cat = xid.catalog()
    assert cat["source"]["url"].startswith("https://docs.nvidia.com/deploy/xid-errors/")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cat["source"]["retrieved"])
    nums = [c["xid"] for c in cat["codes"]]
    assert nums == sorted(set(nums)), "one entry per code, in number order"
    assert not set(nums) & set(cat["not_gb200"])
    for c in cat["codes"]:
        assert c["name"] and c["text"], c["xid"]
        for b in (c.get("now"), c.get("then")):
            assert not b or b in cat["buckets"], f"XID {c['xid']}: no meaning for bucket {b}"


def test_every_xid_in_the_data_has_an_entry():
    names = xid.names()
    for f in ("data/sample/telemetry/dcgm_xid_events.jsonl", "data/history/telemetry/dcgm_xid_events.jsonl"):
        for line in (ROOT / f).read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            assert ev["message"] == names[ev["xid"]], f"{f}: XID {ev['xid']} message is not NVIDIA's name"


def test_generator_and_patterns_use_nvidia_names():
    names = xid.names()
    assert generator.XID_MESSAGES == {x: names[x] for x in generator.XID_FAMILY}
    for x in generator.XID_FAMILY:
        assert patterns.SIGNATURES[f"xid_{x}"] == f"XID {x} ({names[x]})"


def test_critical_xids_match_the_it_partner_sla():
    text = (ROOT / "sla" / "it_partner.yaml").read_text(encoding="utf-8")
    m = re.search(r"Critical XID \(([\d, ]+)\)", text)
    assert m and sorted(int(n) for n in m.group(1).split(",")) == sorted(xid.critical())


def test_every_xid_on_the_site_opens_its_own_entry():
    import render_glossary
    gl = G.load()
    seen = set()
    for src, (_, _, text) in render_glossary.corpus().items():
        for m in G.XID_CODE.finditer(text):
            found = gl.lookup(m.group(), render_glossary.page_key(src))
            assert found and found[0].type == "xid", f"{m.group()} on {src}"
            seen.add(m.group())
    assert {f"XID {x}" for x in generator.XID_FAMILY} <= seen


def test_xid_popup_entry():
    e = G.load().lookup("XID 79")[0]
    assert e.key == "XID-79" and e.title == "GPU has fallen off the bus"
    assert "RESTART_BM" in e.senses[0].text and "critical XID" in e.senses[0].text
    assert e.source["href"] == xid.catalog()["source"]["url"]
    pat = re.compile(G.load().link_pattern("patterns"))
    assert pat.search("after XID 145 on a09").group() == "XID 145", "the code and its number underline together"


def test_glossary_lists_every_gb200_xid():
    import render_glossary
    html = render_glossary.html_page()
    for c in xid.catalog()["codes"]:
        assert f'id="XID-{c["xid"]}"' in html
    ids = re.findall(r'id="XID-(\d+)"', html)
    assert ids == sorted(ids, key=int), "XID codes sort by number"
    md = (ROOT / "docs" / "glossary" / "GLOSSARY.md").read_text(encoding="utf-8")
    assert "## GPU XID codes" in md and xid.catalog()["source"]["url"] in md


def test_app_lookup_explains_an_xid():
    from scorecard import app_support
    lines = app_support.lookup_lines("xid 79")
    assert lines[0] == "**XID 79** · GPU XID codes"
    assert "GPU has fallen off the bus" in lines[1]
    assert lines[-1] == f"*Source: [NVIDIA Xid catalog]({xid.catalog()['source']['url']}).*"
