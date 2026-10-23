"""The AUS-1 training portal (config/training/, src/scorecard/training_portal.py): every course, job guide, PM guide,
and quiz reconciles with the site data; site questions' answers are checked against a second source; the links from
the alarm board, the Incident Portal, the device directory, and the drawing cards point at the right training."""

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import training_portal as TP  # noqa: E402


@pytest.fixture(scope="module")
def s():
    return TP.sources()


@pytest.fixture(scope="module")
def page():
    return TP.page_data()


def test_content_reconciles_with_the_data():
    assert TP.validate() == []


def test_sizes(page):
    assert len(page["courses"]) == 25 and len(page["guides"]) == 29 and len(page["pm"]) == 13
    assert [q["id"] for q in page["quizzes"]] == ["orientation", "it", "landlord", "security"]
    assert all(20 <= len(q["questions"]) <= 30 for q in page["quizzes"])


def test_every_alarm_on_the_board_has_one_job_guide(s):
    sigs = {a["signal"] for a in s["alarms"]}
    assert len(sigs) >= 25
    for sig in sigs | set(TP.configured_signals()):
        assert len(TP.guides_for_signal(sig)) == 1, sig
    gmap = TP.signal_guides()
    assert all(a["signal"] in gmap for a in s["alarms"])


def test_every_device_and_detail_sheet_has_one_course(s, page):
    covered = Counter()
    for c in page["courses"]:
        for d in c["devices"]:
            covered[d["kind"]] += d["count"]
    assert covered == Counter(d["kind"] for d in s["devices"].values())
    assert sum(covered.values()) == len(s["devices"])
    assert set(TP.sheet_courses()) == {k for k in s["sheets"] if k.startswith("D-")}
    assert TP.course_for_device("a01-ct01") == "gb200" and TP.course_for_device("b01-ct01") == "gb300"
    assert TP.course_for_device("A01") == "gb200" and TP.course_for_device("C01") == "hall-c"


def test_every_record_points_at_training(s):
    links = TP.record_training(s["records"])
    assert len(links) == len(s["records"]) and all(v["courses"] for v in links.values())
    by = {r["id"]: r for r in s["records"]}
    a07 = next(r for r in s["records"] if r["summary"].startswith("Retorque A-side tap-off for rack A07"))
    assert links[a07["id"]]["pm"] == [["tapoff_work", "Tap-off retorque"]]
    sir = next(r for r in s["records"] if r["type"] == "sir" and r["category"] == "Door forced")
    assert [g for g, _ in links[sir["id"]]["guides"]] == ["door-forced"]
    for rid, v in links.items():
        for g, _ in v["guides"]:
            r = by[rid]
            assert any(TP.guides_for_signal(a["signal"]) == [g] for a in r["alarms"]) or TP.guides_for_category(r["category"]) == [g]


def test_course_facts_come_from_the_data(s, page):
    """Device counts, products, credentials, and RACI letters on each course equal their sources."""
    site = yaml.safe_load((ROOT / "site" / "site.yaml").read_text(encoding="utf-8"))
    certs = yaml.safe_load((ROOT / "config" / "certifications.yaml").read_text(encoding="utf-8"))
    for c in page["courses"]:
        for p in c["products"]:
            assert p["model"] == site["products"][p["key"]]["model"]
        for cr in c["credentials"]:
            if cr["id"] in certs["credentials"]:
                assert cr["name"] == certs["credentials"][cr["id"]]["name"] and cr["months"] == certs["credentials"][cr["id"]]["months"]
        for r in c["raci"]:
            assert {k: v for k, v in r.items() if k != "component"} == {k: v for k, v in s["raci"][r["component"]].items() if k != "component"}
    ups = next(c for c in page["courses"] if c["id"] == "ups")
    assert ups["devices"][0]["count"] == sum(1 for d in s["devices"].values() if d["kind"] == "ups")
    gb300 = next(c for c in page["courses"] if c["id"] == "gb300")
    assert next(d for d in gb300["devices"] if d["kind"] == "rack")["count"] == sum(
        1 for n, d in s["devices"].items() if d["kind"] == "rack" and d.get("hall") == "Hall B")


def test_guide_facts_come_from_the_board(s, page):
    for g in page["guides"]:
        n = sum(1 for a in s["alarms"] if TP.guides_for_signal(a["signal"]) == [g["id"]])
        assert g["alarm_count"] == n, g["id"]
        assert sum(g["severity"].values()) == n
    sm = {g["id"]: g for g in page["guides"]}
    assert sm["gpu-xid"]["alarm_count"] == 41 and sm["ups-on-battery"]["alarm_count"] == 12
    assert sm["door-forced"]["record_count"] == 2 and sm["door-held"]["record_count"] == 25
    assert sm["ups-on-battery"]["owner"] == "Landlord" and sm["rack-leak"]["owner"] == "IT Partner"
    assert sm["door-forced"]["owner"] == "Security Partner"


def test_pm_facts_come_from_the_calendar_and_ehs(page):
    cal = {w["type"]: w for w in yaml.safe_load((ROOT / "config" / "calendar.yaml").read_text(encoding="utf-8"))["work_types"]}
    ehs = yaml.safe_load((ROOT / "config" / "ehs.yaml").read_text(encoding="utf-8"))["jobs"]["work_types"]
    sched = json.loads((ROOT / "data" / "calendar" / "schedule.json").read_text(encoding="utf-8"))
    pm = {p["id"]: p for p in page["pm"]}
    for wt, w in cal.items():
        assert pm[wt]["minutes"] == w["minutes"] and pm[wt]["mop"] == w["mop"] and pm[wt]["takes"] == w["takes"]
        assert [x["id"] for x in pm[wt]["permits"]] == ehs.get(wt, {}).get("permits", [])
        assert pm[wt]["forward_count"] == sum(1 for j in sched if re.search(w["match"], j["title"]))
    assert sum(p["forward_count"] for p in pm.values()) == len(sched)
    assert pm["gen_exercise"]["record_count"] == 7 and pm["ups_pm"]["record_count"] == 4     # PM and MOP records


def test_site_questions_against_a_second_source():
    """Each computed answer re-read from a source the quiz code does not use for it."""
    q = {x["id"]: x for qs in TP.computed_questions().values() for x in qs}
    ans = lambda k: q[k]["options"][q[k]["answer"]]  # noqa: E731
    with (ROOT / "data" / "security" / "cameras.json").open(encoding="utf-8") as f:
        cams = {c["camera"]: c for c in json.load(f)}
    assert ans("se-cam-b04") == cams["CAM-B-04"]["recorder"]
    site = yaml.safe_load((ROOT / "site" / "site.yaml").read_text(encoding="utf-8"))
    halls = {h["letter"]: h for h in site["halls"]}
    assert int(ans("o-halls")) == len(halls)
    for h in ("A", "B"):
        assert int(ans(f"it-racks-{h}")) == halls[h]["rows"] * halls[h]["racks_per_row"]
    sla = yaml.safe_load((ROOT / "sla" / "security_partner.yaml").read_text(encoding="utf-8"))
    assert int(ans("se-posts")) == len(sla["posts"]["list"])
    assert ans("o-landlord") == site["parties"]["landlord"]["name"]
    ehs = yaml.safe_load((ROOT / "config" / "ehs.yaml").read_text(encoding="utf-8"))
    assert ans("o-permit-loto") == ehs["permit_types"]["loto"]["rule"]
    assert ans("ll-permit-thermography") == "No permit"
    for qs in TP.computed_questions().values():
        for x in qs:
            assert len(set(x["options"])) == len(x["options"]) and 3 <= len(x["options"]) <= 4, x["id"]


def test_quizzes_are_deterministic():
    assert TP.computed_questions() == TP.computed_questions()


def test_prose_is_plain_and_names_only_real_devices(s):
    """No em dashes; every device-like code in the prose is a device, a drawing, or a code the site uses."""
    devs = set(s["devices"]) | set(s["sheets"])
    c = TP.content()
    for name, key in (("courses", "courses"), ("guides", "guides"), ("pm", "pm")):
        for x in c[name][key]:
            for f in TP.PROSE[name]:
                v = x[f]
                for line in (v if isinstance(v, list) else [v]):
                    assert "—" not in line and "–" not in line, (x["id"], f)
                    for tok in re.findall(r"\b(?:UPS|CDU|CH|TW|GEN|USS|MV|VESDA|TTDM|PAZ|CAS|NVR|CAM|POST|GATE|BW)-[A-Z0-9-]*\d\b", line):
                        assert tok in devs, (x["id"], f, tok)
    for q in c["quizzes"]["quizzes"].values():
        for w in q["written"]:
            assert "—" not in w["q"] + w["why"] + "".join(w["options"])


def test_references_are_public_and_dated():
    refs = TP.references()
    assert len(refs) >= 40
    for k, r in refs.items():
        assert r["url"].startswith("https://") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r["checked"])), k
        assert not re.search(r"(?i)example\.(com|org)|localhost", r["url"]), k
    assert len({r["url"] for r in refs.values()}) >= 0.8 * len(refs)


def test_links_from_other_pages():
    import render_alarms
    import render_devices
    import render_tickets
    html = render_alarms.html_page()
    d = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert d["guides"]["UPS on battery"][0] == "ups-on-battery" and "training/#guide/" in html
    html = render_tickets.html_page()
    d = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert len(d["training"]) == len(d["records"]) and "function trainingLine" in html
    html = render_devices.html_page()
    d = json.loads(re.search(r'<script type="application/json" data-gl-skip id="dev-data">(.*?)</script>', html, re.S).group(1))
    assert d["training"]["kinds"]["ups"][""] == "ups" and d["training"]["kinds"]["rack"]["Hall B"] == "gb300"
    loc = re.search(r'<script id="loc-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(loc)["courses"]["D-301"][0] == "ups" and "loc-course" in html


def _node():
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    return node


def test_portal_views_work(tmp_path):
    import render_training
    out = tmp_path / "training.html"
    out.write_text(render_training.html_page(), encoding="utf-8")
    proc = subprocess.run([_node(), "training_portal.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
