"""The Incident Portal and the links to it.

Facts come from the data: every record the portal shows is a record in the partners' files, its measurement is
the scorecards' measurement, every finding and alarm that names a record is on it, and no person is named.
Every ticket, change, and work order number on every page and in the app opens that record on the portal.
"""

import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard import app_support as A
from scorecard import sitenav
from scorecard import tickets as T
from scorecard.pir import Dataset, build_review
from scorecard.sla_model import load_sla

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
REPORTS = ROOT / "reports"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(scope="module")
def portal():
    return T.build()


@pytest.fixture(scope="module")
def by_id(portal):
    return {r["id"]: r for r in portal["records"]}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    import build_site
    out = tmp_path_factory.mktemp("site")
    build_site.build(out)
    return out


def _js(f):
    return json.loads((SAMPLE / f).read_text(encoding="utf-8"))


def _names():
    return [r["name"] for r in csv.DictReader((SAMPLE / "vendor" / "personnel.csv").open(encoding="utf-8"))]


# ------------------------------------------------------------------ the records
def test_every_partner_record_is_in_the_portal_once(portal):
    want = {"inc": [t["number"] for t in _js("vendor/tickets.json")], "chg": [c["change_id"] for c in _js("customer/cab_changes.json")],
            "wo": [w["wo"] for w in _js("landlord/work_orders.json")], "mop": [m["mop_id"] for m in _js("customer/landlord_mop_approvals.json")],
            "pm": [p["task_id"] for p in csv.DictReader((SAMPLE / "landlord" / "pm_records.csv").open(encoding="utf-8"))]}
    got = [r["id"] for r in portal["records"]]
    assert len(got) == len(set(got)) == sum(len(v) for v in want.values())
    for t, refs in want.items():
        assert sorted(r["id"] for r in portal["records"] if r["type"] == t) == sorted(refs), t
        assert portal["counts"][t] == len(refs)
    assert set(got) == set(T.ids())
    assert all(T.ID_RE.fullmatch(x) for x in got), "every number matches the pattern the pages link"


def test_as_recorded_is_the_stored_record(by_id):
    """The partner's own fields, unchanged except that a person's name is shown as their person ID."""
    names = dict((r["name"], r["person_id"]) for r in csv.DictReader((SAMPLE / "vendor" / "personnel.csv").open(encoding="utf-8")))
    for k in _js("vendor/tickets.json"):
        stored = json.dumps(k, sort_keys=True)
        for n, pid in names.items():
            stored = stored.replace(n, pid)
        assert json.dumps(by_id[k["number"]]["native"], sort_keys=True) == stored
    for w in _js("landlord/work_orders.json"):
        assert by_id[w["wo"]]["native"] == w


def test_no_person_is_named(portal):
    blob = json.dumps(portal, default=list)
    assert not [n for n in _names() if n in blob]


def test_measurement_is_the_scorecards(by_id):
    sc = json.loads((REPORTS / "scorecard.json").read_text(encoding="utf-8"))
    targets = {p["id"]: p["restore_min"] for p in load_sla()["priorities"]}
    for i in sc["incidents"]:
        for ref in i["tickets"]:
            m = by_id[ref]["measured"]
            assert m["measured_min"] == i["measured_min"] and m["t0"] == i["t0"] and m["rts"] == i["rts"]
            assert m["within_target"] == (i["measured_min"] <= targets[i["priority"]])
            assert m["ticket_of_record"] == i["key"] and set(m["merged"]) == set(i["tickets"]) - {ref}
    ll = json.loads((REPORTS / "landlord_scorecard.json").read_text(encoding="utf-8"))
    for a in ll["attribution"]:
        if a.get("work_order"):
            m = by_id[a["work_order"]]["measured"]
            assert (m["owner"], m["agrees"], m["t0"], m["restored"]) == (a["owner"], a["agrees"], a["t0"], a["restored"])
    # Every IT ticket the engine scored carries its measurement; a reported time only where one ticket is the whole clock.
    measured = {r for i in sc["incidents"] for r in i["tickets"]}
    assert {r for r, x in by_id.items() if x["type"] == "inc" and x["measured"]} == measured


def test_findings_and_alarms_are_on_their_records(by_id):
    it = json.loads((REPORTS / "findings.json").read_text(encoding="utf-8"))["findings"]
    ll = json.loads((REPORTS / "landlord_findings.json").read_text(encoding="utf-8"))
    for f in it + ll:
        for ref in f["tickets"]:
            assert f["id"] in [x["id"] for x in by_id[ref]["findings"]], (f["id"], ref)
    n = sum(len(r["findings"]) for r in by_id.values())
    assert n == sum(len(f["tickets"]) for f in it + ll)
    from scorecard import alarms as AL
    for a in AL.run_check(SAMPLE, ROOT / "data" / "changes")["alarms"]:
        for ref in {(a.ticket or {}).get("id"), a.change} - {None, ""}:
            assert a.id in [x["id"] for x in by_id[ref]["alarms"]], (a.id, ref)


def test_related_records_link_both_ways(by_id):
    for r in by_id.values():
        for x in r["related"]:
            assert r["id"] in by_id[x]["related"], (r["id"], x)
    assert "WO-41023" in by_id["INC3900001"]["related"], "the A07 ticket names the Landlord work order"
    assert "MOP-303" in by_id["PM-0010"]["related"]


def test_incident_timeline_is_the_post_incident_reviews(by_id):
    """Tickets and work orders use the review's own timeline (same events, same source records)."""
    ds = Dataset(SAMPLE, REPORTS)
    rv = build_review(ds, "INC3900001")
    mine = [x for x in by_id["INC3900001"]["timeline"] if x["source"] not in ("Customer alarm board", "reports/scorecard.json")]
    assert [(x["t"], x["source"]) for x in mine] == [(x["t"], x["source"]) for x in rv["timeline"]]
    for r in by_id.values():
        ts = [x["t"] for x in r["timeline"]]
        assert ts == sorted(ts) and r["timeline"], r["id"]


# ------------------------------------------------------------------ the agreement
def test_records_access_term_is_in_both_slas():
    sla = load_sla()
    ra = sla["measurement"]["records_access"]["terms"]
    assert [t["id"] for t in ra] == [f"RA-{i}" for i in range(1, 7)]
    fresh = next(t for t in ra if t["id"] == "RA-4")["text"]
    assert f"{sla['measurement']['record_integrity_tolerance_min']} minutes" in fresh, "freshness is the record integrity tolerance"
    for doc in ("IT_PARTNER_SLA.md", "LANDLORD_SLA.md"):
        text = (ROOT / "docs" / "sla" / doc).read_text(encoding="utf-8")
        assert "Records access" in text and all(f"| RA-{i} |" in text for i in range(1, 7)), doc
        assert "read-only API service account" in text


# ------------------------------------------------------------------ the page and the links
def test_tab_and_page_are_published(site):
    assert "tickets" in sitenav.KEYS
    html = (site / "tickets" / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="tickets"' in html and 'id="data"' in html and "Incident Portal" in html
    for page in ("index.html", "alarms/index.html", "pir/index.html", "weekly/index.html", "devices/index.html"):
        assert 'data-tab="tickets"' in (site / page).read_text(encoding="utf-8"), page


def test_every_page_links_the_numbers_it_shows(site):
    ids = set(T.ids())
    for page in sorted(site.rglob("index.html")):
        html = page.read_text(encoding="utf-8")
        m = re.search(r'<script id="gl-data" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            continue
        gl = json.loads(m.group(1).replace("<\\/", "</"))
        text = html[:m.start()] + html[m.end():]
        assert set(gl["tk"]) == set(T.ID_RE.findall(text)) & ids, page
        assert gl["tk_re"] == T.ID_PATTERN


def _node(script, *args):
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, script, *map(str, args)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


@pytest.mark.parametrize("path,redraw,must", [
    ("", None, ["MOP-310"]),
    ("alarms/#a07", None, ["INC3900001", "WO-41023", "MOP-310"]),
    ("pir/", None, ["INC3900001", "WO-41023", "MOP-310"]),
    ("weekly/", '[data-week="2026-W38"]', []),
    ("patterns/", "#tabs button:nth-child(4)", ["INC3100816"]),
    ("glossary/", None, ["INC3100816", "WO-41023", "MOP-310", "CHG2040031"]),
    ("tickets/#INC3100068", None, ["INC3100068", "INC3100085"]),
])
def test_numbers_link_to_the_portal_in_a_browser(site, path, redraw, must):
    out = _node("ticket_links.cjs", site / path.split("#")[0] / "index.html", f"https://example.test/{path}", *([redraw] if redraw else []))
    links = json.loads(next(ln for ln in out.splitlines() if ln.startswith("LINKS "))[6:])
    assert set(must) <= set(links), set(must) - set(links)


def test_portal_in_a_browser(site, by_id):
    out = _node("tickets_page.cjs", site / "tickets" / "index.html", json.dumps(_names()))
    got = json.loads(next(ln for ln in out.splitlines() if ln.startswith("RESULT "))[7:])
    recs = list(by_id.values())
    assert got["all"] == len(recs)
    for t in ("inc", "chg", "wo", "mop", "pm"):
        assert sorted(got["types"][t]) == sorted(r["id"] for r in recs if r["type"] == t), t
    s = got["search"]
    assert s["parts:PU5DX43MCA"] == ["INC3100017"], "a removed serial finds its ticket"
    assert set(s["person:RSS-024"]) == {r["id"] for r in recs if r["assigned"] == "RSS-024" or any(n["by"] == "RSS-024" for n in r["notes"])}
    assert s["id:WO-41023"] == ["WO-41023"]
    assert set(s["device:CDU-B3"]) == {r["id"] for r in recs if "cdu-b3" in r["device"].lower()} and s["device:CDU-B3"]
    assert set(s["finding:CSL-11"]) == {r["id"] for r in recs if any("CSL-11" in f["sla_refs"] for f in r["findings"])}
    assert "INC3100068" in s["alarm:ALM-0005"] and "INC3100068" in s["all:a31-ct11"]
    assert set(s["related:MOP-310"]) == {r["id"] for r in recs if "MOP-310" in r["related"]}
    assert s["notes:reseat"] and all(any("reseat" in n["text"].lower() for n in by_id[x]["notes"]) for x in s["notes:reseat"])
    assert set(s["location:Chiller yard"]) == {r["id"] for r in recs if r["location"] == "Chiller yard"}
    assert set(got["p1"]) == {r["id"] for r in recs if r["priority"] == "P1"}
    assert set(got["with_finding"]) == {r["id"] for r in recs if r["findings"]}
    assert set(got["hall_b"]) == {r["id"] for r in recs if r["hall"] == "HALL-B"}
    assert "INC3900001" in got["sep15"] and "MOP-310" in got["sep15"]


# ------------------------------------------------------------------ the app
def _run_app(monkeypatch, **kw):
    import runpy
    from fake_streamlit import FakeStreamlit
    fake = FakeStreamlit(**kw)
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    runpy.run_path(str(ROOT / "app" / "streamlit_app.py"), run_name="__main__")
    return fake


def test_app_links_numbers_to_the_portal(monkeypatch):
    fake = _run_app(monkeypatch, overrides={"View": "IT Partner (Ridgeline)"})
    md = " ".join(fake.texts("markdown") + fake.texts("caption"))
    assert f"[INC3100068]({A.PORTAL}#INC3100068)" in md, "finding summaries link their tickets"
    assert "Open in the Incident Portal:" in md
    cols = dict(fake.link_columns)
    assert len(cols["Ticket of Record"]) == len(json.loads((REPORTS / "scorecard.json").read_text(encoding="utf-8"))["incidents"])
    fake = _run_app(monkeypatch, overrides={"View": "Landlord (Caprock)"})
    assert "WO-41023" in " ".join(dict(fake.link_columns)["Work order"]) and "PM-0018" in " ".join(fake.texts("markdown"))
    fake = _run_app(monkeypatch, overrides={"Code or ID": "WO-41023"})
    assert f"[Open WO-41023 in the Incident Portal]({A.PORTAL}#WO-41023)" in fake.texts("markdown")


def test_app_does_not_link_a_generated_month(tmp_path):
    """A generated month reuses the same numbers for different records, so nothing links."""
    assert A.portal_ids(tmp_path) == frozenset()
    assert A.link_tickets("INC3100068", tmp_path) == "INC3100068" and A.portal_line(["INC3100068"], tmp_path) == ""
    assert A.link_tickets("INC3100068 and INC9999999", SAMPLE) == f"[INC3100068]({A.PORTAL}#INC3100068) and INC9999999"
