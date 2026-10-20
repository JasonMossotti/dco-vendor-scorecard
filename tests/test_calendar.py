"""Maintenance and change calendar (/ops/#calendar): every booked job on one calendar, four conflict checks on Site
health's redundancy groups, the data weeks as found, and a forward schedule with four planted conflicts."""

import filecmp
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard import change_calendar as CC
from scorecard.synthetic import change_calendar as G

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "data" / "calendar"
sys.path.insert(0, str(ROOT / "scripts"))

import render_calendar  # noqa: E402


@pytest.fixture(scope="module")
def r():
    return CC.analyse()


@pytest.fixture(scope="module")
def f(r):
    return CC.page_data(r)


def test_committed_layer_is_current(tmp_path):
    seed = json.loads((ROOT / "data" / "sample" / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    s = G.ForwardSchedule(seed)
    G.write_calendar(s, s.run(), tmp_path, seed)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(p.name for p in LAYER.iterdir())
    for n in names:
        assert filecmp.cmp(tmp_path / n, LAYER / n, shallow=False), f"data/calendar/{n} is stale: run python scripts/generate_calendar.py"


def test_report_is_current(f):
    assert (ROOT / "reports" / "change_calendar.md").read_text(encoding="utf-8") == render_calendar.markdown(f)


def test_groups_are_site_healths():
    """The calendar counts jobs against the same groups (units and N) as Site health's redundancy panel."""
    from scorecard import site_health as SH
    _, data = SH.build()
    sh = {g["key"]: g for g in data["groups"]}
    mine = CC.groups()
    for key, g in mine.items():
        if key.startswith("pumps-CDU"):
            hall = g["hall"]
            assert g["units"][0][5:-2] in sh[f"pumps-{hall}"]["units"] and g["need"] == 1
            continue
        assert g["units"] == sh[key]["units"] and g["need"] == sh[key]["need"][0] and g["scheme"] == sh[key]["scheme"], key


def test_every_record_is_on_the_calendar_and_agrees(r):
    assert r["records"] == {"CAB": 2, "MOP": 10, "Queue": 10, "Maintenance": 11}
    for c in r["agreements"]:
        assert c.checked > 0, c.name
        assert len(c.misses) == r["explained"].get(c.name, 0), (c.name, c.misses)
    assert [c.name for c in r["agreements"]] == ["records", "declared", "windows"]
    assert {c.name: c.checked for c in r["agreements"]} == {"records": 40, "declared": 12, "windows": 20}


def test_data_weeks_as_found(r):
    """No planted conflicts in the data weeks: four surge-day jobs and the MOP-310 overrun that led to the A07 outage."""
    past = [x for x in r["findings"] if x["period"] == "past"]
    assert [(x["kind"], x["jobs"]) for x in past] == [
        ("surge", ["MOP-303"]), ("surge", ["MOP-304"]), ("surge", ["PM-0014"]), ("surge", ["PM-0015"]), ("overrun", ["MOP-310"])]
    o = past[-1]
    assert o["minutes"] == 126 and "neither feed" in o["text"] and [e["label"][:8] for e in o["evidence"]] == ["TO-A07-A", "TO-A07-B"]
    pir = (ROOT / "docs" / "pir" / "PIR-2026-001.md").read_text(encoding="utf-8")
    assert "Rack A07 lost both power feeds during planned maintenance" in pir and "MOP-310" in pir


def test_forward_plants_found_no_false_positives(r):
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert CC.score(r["findings"], key) == {"planted": 4, "found": 4, "false_positives": 0}
    assert sorted(k["kind"] for k in key) == ["both_feeds", "freeze", "overlap", "surge"]
    assert [x["id"] for x in r["findings"]] == [f"CAL-{n}" for n in range(1, 10)]


def test_each_check_counts_what_its_rule_says(r):
    G_ = r["groups"]
    jobs = {j["id"]: j for j in r["jobs"]}
    f0, f1 = r["freeze"]
    for x in r["findings"]:
        js = [jobs[i] for i in x["jobs"]]
        assert all(j["takes"] != "none" and j["status"] != "deferred" for j in js)
        if x["kind"] == "overlap":
            a, b = js
            assert a["group"] == b["group"] and len(G_[a["group"]]["units"]) - 2 < G_[a["group"]]["need"]
            assert CC.parse(a["start"]) < CC.parse(b["end"]) and CC.parse(b["start"]) < CC.parse(a["end"])
        elif x["kind"] == "both_feeds":
            a, b = js
            assert a["rack"] == b["rack"] and {a["unit"][-1], b["unit"][-1]} == {"A", "B"}
        elif x["kind"] == "surge":
            j = js[0]
            assert r["surge"][x["day"]] >= 2 and (j["hall"] == "HALL-B" or G_[j["group"]]["hall"] is None)
        elif x["kind"] == "freeze":
            assert f0 <= x["day"] <= f1 and G_[js[0]["group"]]["hall"] is None
    assert (f0, f1) == ("2026-11-15", "2026-11-22")


def test_surge_days_come_from_both_partners_jira(r):
    n = {}
    for x in r["items"]:
        if x["step"] in ("R-HO4", "R-M4"):
            n[x["date"]] = n.get(x["date"], 0) + 1
    assert r["surge"] == {d: k for d, k in sorted(n.items()) if k >= 2}
    assert r["surge"]["2026-09-04"] == 3


def test_central_time_switches_on_november_1():
    assert CC.utc_offset(CC.parse("2026-11-01T06:59:00Z")).total_seconds() == -5 * 3600
    assert CC.utc_offset(CC.parse("2026-11-01T07:00:00Z")).total_seconds() == -6 * 3600
    assert CC.day_bounds("2026-11-01") == (CC.parse("2026-11-01T05:00:00Z"), CC.parse("2026-11-02T06:00:00Z"))
    assert CC.local_day(CC.parse("2026-09-05T03:00:00Z")) == "2026-09-04"


def test_robustness_small():
    assert render_calendar.robustness(3) == 0


def test_operations_page_builds_and_works(tmp_path):
    import render_ops
    html = render_ops.html_page()
    assert "__DATA__" not in html and 'data-tab="ops" class="on"' in html
    out = tmp_path / "ops.html"
    out.write_text(html, encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "ops_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
