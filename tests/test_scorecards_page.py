"""The Scorecards tab as a static page (/app/): the engines run at build time, so the page opens without Python.

It scores nothing new: every number must equal the reports and the Python app, which still runs at /app/lab/.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import app_support as A  # noqa: E402
from scorecard import scorecards_page as SP  # noqa: E402
from scorecard.sla_model import PARTNER_FILES, load_sla  # noqa: E402

SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def b():
    return SP.build()


@pytest.fixture(scope="module")
def ds(b):
    return next(d for d in b["datasets"] if d["key"] == "sample")


def test_headline_numbers(ds):
    assert ds["it"]["tiles"]["defaults"] == 4 and ds["it"]["credits"]["payable"] == 188700
    assert ds["landlord"]["tiles"]["defaults"] == 4 and ds["landlord"]["credits"]["payable"] == 106200
    assert ds["security"]["tiles"]["defaults"] == 2 and ds["security"]["credits"]["payable"] == 12276
    assert ds["it"]["ev"] == {"planted": 17, "detected": 17, "false_positives": 0}
    assert ds["landlord"]["ev"] == {"planted": 8, "detected": 8, "false_positives": 0}
    assert ds["security"]["ev"] == {"planted": 4, "detected": 4, "false_positives": 0}


def test_numbers_equal_the_reports(ds):
    it = (ROOT / "reports" / "scorecard.md").read_text(encoding="utf-8")
    ll = (ROOT / "reports" / "landlord_scorecard.md").read_text(encoding="utf-8")
    sec = (ROOT / "reports" / "security_scorecard.md").read_text(encoding="utf-8")
    for text, p in ((it, ds["it"]), (ll, ds["landlord"]), (sec, ds["security"])):
        assert f"${p['credits']['payable']:,.0f}" in text
        for c in p["credits"]["items"]:
            assert c["csl"] in text


def test_tables_are_the_apps(ds):
    """The page shows the Python app's own tables, row for row."""
    _, sc, _ = A.run_pipeline(load_sla(PARTNER_FILES["it"]), SAMPLE)
    assert [c["row"] for c in ds["it"]["csl"]] == A.csl_rows(sc)
    assert ds["it"]["km"] == A.km_rows(sc) and ds["it"]["caps"] == A.cap_rows(sc)
    assert len(ds["it"]["incidents"]) == sc["totals"]["incidents"] == 72
    assert len(ds["it"]["findings"]) == sc["totals"]["findings"] == 18
    assert [c["status"] for c in ds["it"]["csl"]].count("default") == 4


def test_credits_follow_the_contract(b, ds):
    """Each credit is the at-risk amount times the service level's weight, both from the SLA YAML."""
    for k, part in (("it", "it"), ("landlord", "landlord"), ("security", "security")):
        com = load_sla(PARTNER_FILES[part])["commercial"]
        t = b["terms"][k]
        assert (t["monthly_charges"], t["at_risk_pct"], t["pool_pct"]) == (com["monthly_charges"], com["at_risk_pct"], com["pool_pct"])
        assert sum(c["allocation_pct"] for c in t["csl"]) <= t["pool_pct"]
        ar = t["monthly_charges"] * t["at_risk_pct"] / 100
        items = ds[k]["credits"]["items"]
        assert all(abs(c["credit"] - ar * c["allocation_pct"] / 100) < 0.01 for c in items)
        assert ds[k]["credits"]["payable"] == min(sum(c["credit"] for c in items), ar)
    assert b["terms"]["it"]["monthly_charges"] * 12 / 100 == 222000


def test_a_generated_month_builds(tmp_path):
    """The weekly deploy adds the latest four weeks; any month the generator makes must render."""
    d = A.generate_month(11, ROOT)
    try:
        got = SP.dataset("Generated", "latest", d)
        json.dumps(got)
        assert got["it"]["csl"] and got["landlord"] and got["security"] and got["site"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_no_python_runtime_on_the_page():
    import render_scorecards
    html = render_scorecards.html_page()
    assert "stlite" not in html and 'href="lab/"' in html


def test_interactive_page_builds_and_works(tmp_path):
    import render_scorecards
    out = tmp_path / "scorecards.html"
    html = render_scorecards.html_page()
    assert "__DATA__" not in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    assert re.search(r'<script id="gl-data"', html), "the code popups, like every other page"
    out.write_text(html, encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "scorecards_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
