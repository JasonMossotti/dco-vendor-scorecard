"""Change-aware alarms: one feed for both partners, classified against declared change work, with the
notifications each partner owed under Interface Agreement section 10, and the alarm board page."""

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from scorecard import alarms as A
from scorecard import site_model as S
from scorecard.connectors import FileConnector
from scorecard.sla_model import load_interface_agreement
from scorecard.synthetic.changes import ChangeLayer, write_changes

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
CHANGES = ROOT / "data" / "changes"
sys.path.insert(0, str(ROOT / "scripts"))

import render_alarms  # noqa: E402


@pytest.fixture(scope="module")
def check():
    return A.run_check(SAMPLE, CHANGES)


@pytest.fixture(scope="module")
def by_id(check):
    return {a.id: a for a in check["alarms"]}


def _digest(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(d).as_posix().encode() + p.read_bytes())
    return h.hexdigest()


def test_committed_change_layer_is_current_and_leaves_the_sample_alone(tmp_path):
    before = _digest(SAMPLE)
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    out = ChangeLayer(SAMPLE, window["seed"]).run(plant=False)
    write_changes(out, tmp_path, window, window["seed"], "data/sample")
    assert _digest(SAMPLE) == before, "generating the change layer must not touch data/sample"
    for p in tmp_path.rglob("*"):
        if p.is_file():
            rel = p.relative_to(tmp_path)
            assert (CHANGES / rel).read_bytes() == p.read_bytes(), f"data/changes/{rel} is stale: run python scripts/generate_changes.py"


def test_change_layer_has_its_own_random_stream():
    src = (ROOT / "src" / "scorecard" / "synthetic" / "changes.py").read_text(encoding="utf-8")
    assert 'random.Random(f"{seed}:changes")' in src


def test_check_never_reads_the_answer_key(tmp_path):
    shutil.copytree(CHANGES, tmp_path / "changes")
    shutil.rmtree(tmp_path / "changes" / "ground_truth")
    r = A.run_check(SAMPLE, tmp_path / "changes")
    assert len(r["alarms"]) == len(A.run_check(SAMPLE, CHANGES)["alarms"])
    with pytest.raises(PermissionError):
        FileConnector(SAMPLE).read_path("ground_truth/facility_incidents.json")


def test_every_change_record_gets_a_declaration(check):
    src = FileConnector(SAMPLE)
    ids = {c["change_id"] for c in A.change_records(src)}
    assert {d["change_id"] for d in check["declarations"]} == ids and len(ids) == 12
    for d in check["declarations"]:
        assert d["expected"] and d["max_severity"] in ("minor", "major", "critical") and d["grace_min"] == 15
    with pytest.raises(ValueError):
        A.declare({"change_id": "X", "title": "Something nobody catalogued", "assets": ["UPS-A1"]}, A.load_config())


def test_feed_covers_both_partners_and_every_alarm_source(check):
    al = check["alarms"]
    sources = {a.source for a in al}
    for s in ("BMS", "UPS card", "Busway monitor", "EPMS", "CDU controller", "VESDA panel", "Customer check",
              "Redfish", "NVLink manager", "Fabric manager", "GPU telemetry", "Scheduler", "Rack leak rope"):
        assert s in sources, s
    assert {a.severity for a in al} <= {"critical", "major", "minor"}
    assert all(a.partner in ("Landlord", "IT Partner") and a.location and a.hall for a in al)
    assert len({a.id for a in al}) == len(al)


def test_device_events_merge_into_the_bms_alarm_of_record(check):
    pump = [a for a in check["alarms"] if a.source == "BMS" and a.signal.startswith("Pump ") and a.signal.endswith("fault")]
    assert pump and all(any("CDU controller" in e for e in a.evidence) for a in pump)
    # The facility leak is one row (the BMS), not two.
    leaks = [a for a in check["alarms"] if a.device == "TTDM-A"]
    assert len(leaks) == 1 and leaks[0].evidence


def test_rack_outage_is_one_critical_row_not_eighteen(check):
    rack = [a for a in check["alarms"] if a.signal == "Rack outage"]
    assert len(rack) == 1 and rack[0].tally == 18 and rack[0].severity == "critical" and rack[0].rack == "A07"
    assert not [a for a in check["alarms"] if a.signal == "Node not responding" and a.rack == "A07"]


def test_a07_reconciles_with_the_post_incident_review(check):
    pir = (ROOT / "docs" / "pir" / "PIR-2026-001.md").read_text(encoding="utf-8")
    f = render_alarms.a07_facts(check["alarms"], check["declarations"], check["owed"])
    assert f["change"] == "MOP-310" and f["declared"] == ["BW-A-R1-PG-A2-A"]
    assert f["first_flag"]["raised"] == "2026-09-15T15:42:11Z" and "15:42:11Z" in pir
    assert f["first_flag"]["device"] == "BW-A-R1-PG-A2-B" and f["first_flag"]["cls"] == A.OUT_OF_SCOPE
    assert f["expected_alarm"]["device"] == "BW-A-R1-PG-A2-A" and f["expected_alarm"]["cleared"] == "2026-09-15T19:22:05Z"
    assert "19:22:05Z" in pir and "2 h 06 min" in pir
    assert f["overrun"]["raised"] == "2026-09-15T17:31:03Z" and "2 h 06 min" in f["overrun"]["reason"]
    assert f["window_end"] == "2026-09-15T17:16:03Z" and "17:16:03Z" in pir
    assert {(a["device"], a["signal"]) for a in f["flags"]} == {
        ("BW-A-R1-PG-A2-B", "Tap-off breaker open"), ("Rack A07", "Rack input power lost (both feeds)"),
        ("Rack A07", "Rack outage"), ("BW-A-R1-PG-A2-A", "Change window overrun")}


def test_sample_flags_only_the_rack_outage_and_expects_the_planned_work(check):
    flagged = [a for a in check["alarms"] if a.cls in A.FLAGGED]
    assert {a.change for a in flagged} == {"MOP-310"} and len(flagged) == 4
    expected = {(a.change, a.signal) for a in check["alarms"] if a.cls == A.EXPECTED}
    assert ("MOP-305", "UPS on maintenance bypass") in expected and ("MOP-307", "Smoke alarm") in expected
    assert ("MOP-308", "Tap-off breaker open") in expected and ("MOP-303", "Pump isolated") in expected
    # The chiller alarm during the CDU-B4 filter change is not connected to it.
    ch = [a for a in check["alarms"] if a.device == "CH-06"]
    assert ch and all(a.cls == A.NOT_CHANGE for a in ch)
    s = A.score(check["alarms"], check["owed"], json.loads((CHANGES / "ground_truth" / "change_alarm_key.json").read_text()))
    assert s["found"] == s["cases"] == 4 and not s["other_flags"]


def test_connected_means_the_site_models_paths():
    sm = A.SiteMap(S.load_site(), json.loads((SAMPLE / "site" / "topology.json").read_text()))
    bw = sm.scope("BW-A-R1-PG-A2-A")
    assert {"BW-A-R1-PG-A2-B", "rack:A07", "rack:A08"} <= bw and "UPS-A3" not in bw
    cdu = sm.scope("CDU-B4")
    assert {"CDU-B1", "TTDM-B", "rack:B01"} <= cdu and not any(x.startswith("CH-") for x in cdu)
    assert sm.scope("rack:A05") == {"rack:A05"}


def test_classification_rules_on_small_cases():
    cfg = A.load_config()
    sm = A.SiteMap(S.load_site(), json.loads((SAMPLE / "site" / "topology.json").read_text()))
    d = A.declare({"change_id": "MOP-1", "owner": "Landlord", "title": "Filter change and coolant sample: CDU-A1",
                   "assets": ["CDU-A1"], "window_start": "2026-09-10T14:00:00Z", "window_end": "2026-09-10T16:00:00Z"}, cfg)
    t = A.parse
    mk = lambda dev, sig, at, dom=("cooling",), sev="major", clr=None: A.Alarm("x", "Landlord", dev, sig, sig, sev, list(dom), t(at), cleared=t(clr) if clr else None)
    cases = [
        (mk("CDU-A1", "Pump isolated", "2026-09-10T14:10:00Z", clr="2026-09-10T16:10:00Z"), A.EXPECTED),     # inside grace
        (mk("CDU-A1", "Pump isolated", "2026-09-10T13:30:00Z", clr="2026-09-10T13:40:00Z"), A.OUT_OF_WINDOW),  # started early
        (mk("CDU-A1", "Pump isolated", "2026-09-10T14:20:00Z", sev="critical", clr="2026-09-10T14:30:00Z"), A.OUT_OF_SCOPE),
        (mk("CDU-A2", "Pump isolated", "2026-09-10T14:20:00Z", clr="2026-09-10T14:30:00Z"), A.OUT_OF_SCOPE),  # sibling
        (mk("CH-03", "Compressor trip", "2026-09-10T14:20:00Z"), A.NOT_CHANGE),                                 # not connected
        (mk("a01-ct01", "GPU error (XID)", "2026-09-10T14:20:00Z", dom=("compute",)), A.NOT_CHANGE),            # other domain
        (mk("CDU-A2", "Pump isolated", "2026-09-10T17:00:00Z"), A.NOT_CHANGE),                                  # after the window
    ]
    cases[5][0].rack = "A01"
    alarms = [c[0] for c in cases]
    over = A.classify(alarms, [d], sm, cfg)
    assert [a.cls for a in alarms] == [c[1] for c in cases]
    assert not over, "cleared inside the grace: no overrun"
    late = mk("CDU-A1", "Pump isolated", "2026-09-10T14:10:00Z", clr="2026-09-10T17:00:00Z")
    over = A.classify([late], [d], sm, cfg)
    assert len(over) == 1 and over[0].raised == t("2026-09-10T16:15:00Z") and over[0].cls == A.OUT_OF_WINDOW


def test_notifications_owed_follow_section_10(check):
    ia = load_interface_agreement()
    rules = {n["id"]: n for n in ia["alarm_notification"]["notifications"]}
    assert rules["NT-1"]["within_min"] == 5 and rules["NT-1"]["page"] and rules["NT-2"]["within_min"] == 15
    owed = check["owed"]
    assert not [o for o in owed if o["cls"] == A.EXPECTED], "an expected alarm owes no notification"
    over = next(o for o in owed if o["signal"] == "Change window overrun")
    assert over["party"] == "Landlord" and over["rule"] == "NT-3" and over["status"] == "missing"
    rack = [o for o in owed if o["signal"] == "Rack outage"]
    assert {(o["party"], o["rule"], o["status"]) for o in rack} == {("Landlord", "NT-3", "missing"), ("IT Partner", "NT-1", "on_time")}
    p1 = next(o for o in owed if o["signal"] == "Rack input power lost (both feeds)")
    assert p1["status"] == "incomplete" and p1["delay_min"] <= 5, "paged on time, but the page does not name MOP-310"
    km = {k["id"]: k for k in check["key_measures"]}
    assert km["IA-KM-01"]["party"] == "Landlord" and km["IA-KM-02"]["party"] == "IT Partner"
    assert km["IA-KM-01"]["by_rule"]["NT-3"] == {"owed": 4, "on_time": 0}
    assert km["IA-KM-02"]["by_rule"]["NT-1"]["owed"] == km["IA-KM-02"]["by_rule"]["NT-1"]["on_time"]


def test_interface_agreement_section_10_is_rendered():
    doc = (ROOT / "docs" / "sla" / "INTERFACE_AGREEMENT.md").read_text(encoding="utf-8")
    assert "## 10. Change-Aware Alarm Notification" in doc and "IA-KM-01" in doc and "NT-3" in doc
    assert "not by itself a finding against anyone" in doc


def test_robustness_small_sample():
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    cfg = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    import tempfile
    for k in (3, 21):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = SiteGenerator(load_sla(), cfg, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run()
            write_dataset(data, d)
            out = ChangeLayer(d, 2000 + k).run(plant=True)
            write_changes(out, d / "changes", data["window"], 2000 + k, "generated")
            r = A.run_check(d, d / "changes")
            s = A.score(r["alarms"], r["owed"], out["key"])
            assert s["found"] == s["cases"] == 8 and s["decoys"] == 3 and s["decoys_flagged"] == 0, s["missed"]
            assert s["notify_found"] == s["notify"] == 2


def test_report_is_current():
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "render_alarms.py"), "--check"], capture_output=True).returncode == 0


def test_alarm_board_builds_and_works(tmp_path):
    out = tmp_path / "alarms.html"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "render_alarms.py"), "--html", str(out)], check=True, capture_output=True)
    html = out.read_text(encoding="utf-8")
    assert "__DATA__" not in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "alarms_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_trouble_tickets_cover_both_partners_without_planned_work():
    tk = A.trouble_tickets(FileConnector(SAMPLE))
    ids = {t["id"] for t in tk}
    assert "WO-41017" not in ids and "WO-41021" not in ids          # planned work orders (MOP-308, MOP-309) are change work
    assert "WO-41014" in ids                                          # Landlord work with no MOP is still a ticket
    wo = next(t for t in tk if t["id"] == "WO-41023")
    assert wo["keys"] == ["rack:A07"] and wo["domains"] == ["power", "compute"] and wo["closed"] == "2026-09-15T19:27:55Z"
    inc = next(t for t in tk if t["id"] == "INC3100629")
    assert inc["partner"] == "IT Partner" and inc["keys"] == ["rack:A05"] and inc["domains"] == ["compute"]
    utility = next(t for t in tk if t["id"] == "WO-41009")
    assert utility["domains"] == ["power"]


def test_planned_work_orders_attach_to_their_mop():
    pw = {w["id"]: w for w in A.planned_work(FileConnector(SAMPLE))}
    assert set(pw) == {"WO-41017", "WO-41021", "WO-41014"}                # the utility outage WO-41009 is not planned work
    assert pw["WO-41017"]["mop_ref"] == "MOP-308" and pw["WO-41021"]["mop_ref"] == "MOP-309"
    assert pw["WO-41014"]["mop_ref"] == ""                                 # planned work with no MOP on file


def test_customer_routing_config_is_complete_and_fictional():
    import re
    rc = yaml.safe_load((ROOT / "config" / "customer_notifications.yaml").read_text(encoding="utf-8"))
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hours = {}
    for s in rc["schedule"]:
        a, b = int(s["start"][:2]), int(s["end"][:2])
        assert s["primary"] in rc["people"] and s["secondary"] in rc["people"] and s["primary"] != s["secondary"]
        for d in s["days"]:
            span = range(a, b) if a < b else list(range(a, 24)) + [24 + h for h in range(0, b)]
            for h in span:
                k = ((days.index(d) * 24 + h) % 168)
                assert k not in hours, f"schedule overlap at {days[k // 24]} {k % 24:02d}:00"
                hours[k] = s["label"]
    assert len(hours) == 168                                   # every hour of the week, exactly once
    events = {r["event"] for r in rc["rules"]}
    assert events == {"out_of_scope", "out_of_window", "critical", "major", "minor", "expected", "p1_ticket", "nt_breach",
                      "upcoming_trouble", "change_conflict"}
    for r in rc["rules"]:
        assert set(r["business"]) | set(r["after_hours"]) <= {"email", "sms"}
        assert set(r["to"]) <= set(rc["groups"]) and all(x["to"] in rc["groups"] for x in r.get("escalate", []))
    contacts = [p["email"] for p in rc["people"].values()] + [p["sms"] for p in rc["people"].values()]
    contacts += [c for g in rc["groups"].values() for c in g.get("email", []) + g.get("sms", [])]
    assert all(c.endswith("@example.com") or re.fullmatch(r"\+1 512 555 01\d\d", c) for c in contacts)
