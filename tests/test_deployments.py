"""The deployment program: standard work that resolves, calculations that match the site model, rack status that
reconciles with CSL-09, the authority profile switch, the generated plan, and the Deployments page."""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import render_deployments  # noqa: E402
from scorecard import deployments as D  # noqa: E402
from scorecard import site_model as S  # noqa: E402
from scorecard import sitenav  # noqa: E402
from scorecard.sla_model import load_sla  # noqa: E402


@pytest.fixture(scope="module")
def built():
    return D.build()


@pytest.fixture(scope="module")
def cfg():
    return D.load_config()


def calc(b, group, check):
    return next(r for r in b["calc"] if r["group"] == group and r["check"] == check)


def test_standard_work_resolves(cfg):
    assert D.validate(cfg, load_sla()) == []


@pytest.mark.parametrize("break_it, expect", [
    (lambda c: c["gates"][0]["steps"][1]["signoff"].append("nobody"), "unknown role nobody"),
    (lambda c: c["gates"][0]["steps"][0].setdefault("after", []).append("G0-02"), "which comes later"),
    (lambda c: c["gates"][2]["steps"][0].update(milestone="M9"), "M9 is not in the IT Partner SLA"),
    (lambda c: c["gates"][1]["steps"][0]["doc"].update(id="DEP-B-OPR-01"), "used 2 times"),
    (lambda c: c["program"].update(jurisdiction="mars"), "no authority profile"),
    (lambda c: c["gates"][0]["steps"][0].update(records=[]), "no records"),
])
def test_validation_catches_broken_references(cfg, break_it, expect):
    bad = copy.deepcopy(cfg)
    break_it(bad)
    assert any(expect in e for e in D.validate(bad, load_sla()))
    with pytest.raises(D.DeploymentConfigError):
        D.build(cfg=bad)


def test_rack_milestones_come_from_the_sla(built):
    ms = load_sla()["deployment"]["milestones"]
    rack_steps = [s for s in built["steps"] if s["per_rack"]]
    assert [s["milestone"] for s in rack_steps if s.get("milestone")] == [m["id"] for m in ms]
    for s in rack_steps:
        if s.get("milestone"):
            m = next(m for m in ms if m["id"] == s["milestone"])
            assert s["name"] == m["name"] and s["acceptance"] == [m["exit_criteria"]]
    # The Landlord's energization sits between the leak test and power-on (Interface Agreement HO-4).
    ids = [s["id"] for s in rack_steps]
    assert ids.index("R-M3") < ids.index("R-HO4") < ids.index("R-M4")
    assert next(s for s in rack_steps if s["id"] == "R-HO4")["owner"] == "ll-ops"


def test_every_step_follows_something_but_the_first(built):
    assert built["steps"][0]["after"] == []
    assert all(s["after"] for s in built["steps"][1:])
    g3 = next(s for s in built["steps"] if s["id"] == "G3-01")
    assert g3["after"] == ["R-M7"]


def test_no_person_is_named(cfg):
    # Sign-offs are by role and organization. Role names say what the role is, never who.
    for r in cfg["roles"].values():
        assert r["org"] in {"Customer", "Landlord", "IT Partner", "Third party", "Authority"}


def test_design_checks_are_the_site_models(built):
    site = S.load_site()
    hall = S.hall_by_id(site, "HALL-B")
    mine = [(r["check"], r["load"], r["capacity"]) for r in built["calc"] if r["group"] == "Hall at design"]
    theirs = [(c.system, round(c.load, 1), round(c.capacity, 1)) for c in S.capacity_checks(site) if c.scope == hall["name"]]
    assert mine == theirs and all(r["passed"] for r in built["calc"] if r["group"] == "Hall at design")


def test_peak_checks_name_the_control(built):
    bus = calc(built, "Hall at reported peak", "Busway, one feed lost (largest segment)")
    assert bus["load"] == pytest.approx(6 * 155_000 / (math.sqrt(3) * 480 * 0.99), abs=0.1)
    assert not bus["passed"] and "132 kW" in bus["control"]
    lost = calc(built, "Hall at reported peak", "UPS, one module lost (4 make 3)")
    assert lost["load"] == pytest.approx(1452 * 155 / 132, abs=0.1) and lost["control"]
    sub = calc(built, "Hall at reported peak", "Unit substation (worst UPS input)")
    assert sub["passed"] and not sub["control"]


def test_tap_off_breaker_at_125_percent(built):
    design = calc(built, "Per rack", "Tap-off breaker, one feed carries the rack (design)")
    peak = calc(built, "Per rack", "Tap-off breaker, one feed carries the rack (reported peak)")
    a = 132_000 / (math.sqrt(3) * 480 * 0.99)
    assert round(a, 1) == 160.4 and a * 1.25 > 200
    assert design["load"] == 225 and design["passed"]
    assert peak["load"] == 250 and not peak["passed"] and peak["control"]
    assert D.next_standard(200.0, [100, 200, 225]) == 200 and D.next_standard(200.5, [100, 200, 225]) == 225


def test_per_rack_cooling_and_floor(built):
    assert calc(built, "Per rack", "Liquid heat to the CDU header")["load"] == pytest.approx(118.8)
    assert calc(built, "Per rack", "Coolant flow")["load"] == pytest.approx(142.6)
    dt = 118.8 / (142.56 / 60 * 1.02 * 3.85)
    assert calc(built, "Per rack", "Coolant temperature rise across the rack")["load"] == pytest.approx(round(dt, 1))
    floor = calc(built, "Per rack", "Floor load under the rack footprint")
    assert floor["load"] == pytest.approx(1360 * 9.80665 / 0.72 / 1000, abs=0.05) and floor["passed"]


def test_cabling_counts_from_the_device_directory(built):
    c = built["cabling"]
    assert (c["racks"], c["compute_trays"], c["rails"], c["leaf_switches"]) == (32, 576, 4, 64)
    assert c["backend_links"] == 2304 and c["links_per_rack"] == 72


def test_rack_status_reconciles_with_csl09(built):
    racks = built["racks"]["racks"]
    assert len(racks) == 32 and all(r["rack"].startswith("B") for r in racks)
    due = [r for r in racks if r["committed_handoff"] and r["committed_handoff"] < built["racks"]["as_of"]]
    on_time = sum(1 for r in due if r["state"] == "handed off")
    line = next(x for x in (ROOT / "reports" / "scorecard.md").read_text(encoding="utf-8").splitlines() if x.startswith("| CSL-09 |"))
    m = re.search(r"(\d+) of (\d+) racks due this period", line)
    assert (on_time, len(due)) == (int(m.group(1)), int(m.group(2))) == (10, 13)
    assert built["racks"]["counts"] == {"handed off": 10, "handed off late": 3, "in progress": 1, "not received": 18}


def test_measured_handoff_is_never_before_the_burn_in(built):
    for r in built["racks"]["racks"]:
        if r["measured_handoff"]:
            assert r["measured_burn_in"] and r["measured_burn_in"] <= r["measured_handoff"]


def test_large_load_threshold_from_the_site_model(built):
    sb6 = next(d for d in built["statewide"] if d["id"] == "TX-SB6")
    assert f"{S.site_peak_kw(S.load_site()) / 1000:,.1f} MW is below the 75 MW" in sb6["result"]


def test_authority_profile_is_one_switch(cfg):
    county = D.build()
    city_cfg = copy.deepcopy(cfg)
    city_cfg["program"]["jurisdiction"] = "city"
    city = D.build(cfg=city_cfg)
    who = lambda b: {i["by"] for s in b["steps"] for i in s["inspections"] if i["kind"] == "ahj"}
    assert "ahj-fm" in who(county) and "ahj-city" not in who(county)
    assert "ahj-city" in who(city) and "ahj-fm" not in who(city)
    assert [p["id"] for p in city["authority"]["permits"]][-1] == "AHJ-CITY-CO"


def test_plan_document_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_deployments.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_deployments_tab_in_the_bar():
    assert ("deployments", "Deployments", "deployments/") in sitenav.TABS
    assert 'data-tab="deployments" class="on"' in sitenav.nav_html("deployments")


def test_interactive_page_builds_and_works(tmp_path):
    out = tmp_path / "deployments.html"
    html = render_deployments.html_page()
    assert "__DATA__" not in html and "__SITENAV__" not in html
    out.write_text(html, encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "deployments_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ------------------------------------------------------------------------------------------ the record
from scorecard import jira_import as J  # noqa: E402
from scorecard.synthetic import deployments as SD  # noqa: E402

REC = ROOT / "data" / "deployments"


KEY = json.loads((REC / "answer_key.json").read_text(encoding="utf-8"))
PLANTED = {(k["step"], k["rack"]): k["kind"] for k in KEY["planted"]}


@pytest.fixture(scope="module")
def issues():
    return J.load_dir(REC / "jira")


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    """The same program with nothing planted: every natural record must pass every check."""
    d = tmp_path_factory.mktemp("clean")
    window = json.loads((ROOT / "data" / "sample" / "manifest.json").read_text(encoding="utf-8"))["window"]
    SD.write_deployments(SD.DeploymentRecordLayer(ROOT / "data" / "sample", window["seed"], plant=False).run(), d)
    return D.build(rec_dir=d)


def test_committed_record_is_current(tmp_path):
    import hashlib
    sample = sorted((ROOT / "data" / "sample").rglob("*"))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sample if p.is_file()}
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_deployments
    generate_deployments.generate(tmp_path)
    for p in sorted(tmp_path.rglob("*")):
        if p.is_file():
            rel = p.relative_to(tmp_path)
            assert p.read_bytes() == (REC / rel).read_bytes(), f"{rel} is stale: run python scripts/generate_deployments.py"
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sample if p.is_file()}, "data/sample was written"


def test_jira_rack_milestones_are_the_it_partners_report(issues):
    import csv
    with (ROOT / "data" / "sample" / "vendor" / "deployment_milestones.csv").open(encoding="utf-8") as f:
        reported = {(r["rack"], "R-" + r["milestone"]): r["reported_complete_at"] for r in csv.DictReader(f)}
    jira = {(i["rack"], i["step"]): i["resolved"] for i in issues
            if i["project"] == "RSS-DEP" and i["type"] == "Sub-task" and i["resolved"]}
    assert jira == reported and len(jira) == 97


def test_landlord_energizes_between_leak_test_and_power_on(issues):
    done = {(i["rack"], i["step"]): i["resolved"] for i in issues if i["rack"] and i["resolved"]}
    ho4 = [(r, t) for (r, s), t in done.items() if s == "R-HO4"]
    assert len(ho4) == 14
    for rack, t in ho4:
        if PLANTED.get(("R-HO4", rack)) == "out_of_order":
            assert t < done[(rack, "R-M3")], "the planted case energizes before the leak test"
        else:
            assert done[(rack, "R-M3")] < t < done[(rack, "R-M4")]
    assert all(i["project"] == "CCF-DEP" for i in issues if i["step"] == "R-HO4")


def test_nobody_is_named_in_the_record():
    for p in (REC / "jira").glob("*.json"):
        for i in json.loads(p.read_text(encoding="utf-8"))["issues"]:
            assert i["fields"]["assignee"] is None
    roles = D.load_config()["roles"]
    for line in (REC / "signoffs.jsonl").read_text(encoding="utf-8").splitlines():
        x = json.loads(line)
        assert set(x) == {"step", "rack", "role", "org", "signed_at", "decision"} and x["role"] in roles


def test_csv_export_reads_the_same(issues):
    again = J.from_csv(J.to_csv(issues))
    assert again == issues


def test_importer_refuses_what_it_cannot_map(issues):
    fmap = J.load_field_map()
    bad = [dict(issues[0], status="Parked")]
    with pytest.raises(J.JiraImportError, match="no status category"):
        J.from_csv(J.to_csv(bad))
    with pytest.raises(J.JiraImportError, match="not in the field map"):
        J.from_json({"issues": [{"key": "XYZ-1", "fields": {}}]}, fmap)
    with pytest.raises(J.JiraImportError, match="not a Jira search response"):
        J.from_json({"values": []}, fmap)


def test_importer_reads_pages_and_rejects_duplicates(tmp_path):
    export = json.loads((REC / "jira" / "CCF-DEP.json").read_text(encoding="utf-8"))
    half = len(export["issues"]) // 2
    pages = [{"issues": export["issues"][:half], "isLast": False, "nextPageToken": "x"}, {"issues": export["issues"][half:], "isLast": True}]
    assert J.from_json(pages) == J.from_json(export)
    (tmp_path / "a.json").write_text(json.dumps(export), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(export), encoding="utf-8")
    with pytest.raises(J.JiraImportError, match="exported twice"):
        J.load_dir(tmp_path)


def test_one_work_order_per_unit_of_work(built):
    wos = built["record"]["work_orders"]
    program = [s for s in built["steps"] if not s["per_rack"]]
    rack_steps = [s for s in built["steps"] if s["per_rack"]]
    assert len(wos) == len(program) + 32 * len(rack_steps) == 275
    assert len({w["id"] for w in wos}) == len(wos) and len({(w["step"], w["rack"]) for w in wos}) == len(wos)
    assert {w["source"].split()[0] for w in wos} == {"Jira", "Customer"}
    assert {w["step"] for w in wos if w["partner"] == "Customer"} == {"G0-01", "G0-05", "G3-04"}


def test_complete_needs_done_signed_and_inspected(built):
    for w in built["record"]["work_orders"]:
        signed = all(x["signed_at"] for x in w["signoffs"])
        inspected = all(i["result"] == "pass" for i in w["inspections_required"])
        assert w["complete"] == (w["state"] == "done" and signed and inspected)
    pending = {(w["step"], w["rack"]) for w in built["record"]["work_orders"] if w["state"] == "done" and not w["complete"]}
    planted = {k for k, kind in PLANTED.items() if kind in ("unsigned", "uninspected")}
    assert pending == {("R-M6", "B14")} | planted, "B14's burn-in awaits sign-off inside the window; the rest are planted"


def test_gate_status(built, clean):
    gs = {g["gate"]: g for g in built["gate_status"]}
    assert not gs["G0"]["closed"] and gs["G1"]["closed"], "G0-04's plan review record is the planted gap"
    assert (gs["G0"]["complete"], gs["G0"]["total"]) == (6, 7)
    assert (gs["G2"]["complete"], gs["G2"]["total"], gs["G2"]["closed"]) == (109, 256, False)
    assert (gs["G3"]["complete"], gs["G3"]["total"]) == (0, 4)
    cg = {g["gate"]: g for g in clean["gate_status"]}
    assert cg["G0"]["closed"] and cg["G1"]["closed"] and cg["G2"]["complete"] == 110


def test_hall_ready_before_the_first_rack(built):
    wos = {(w["step"], w["rack"]): w for w in built["record"]["work_orders"]}
    first = min(r["planned_receipt"] for r in built["racks"]["racks"])
    assert wos[("G1-08", None)]["done"] < first
    for w in built["record"]["work_orders"]:
        for a in next(s for s in built["steps"] if s["id"] == w["step"])["after"]:
            pred = wos.get((a, w["rack"])) or wos.get((a, None))
            if w["done"] and pred and PLANTED.get((w["step"], w["rack"])) != "out_of_order":
                assert pred["done"] and pred["done"] <= w["done"], (w["id"], a)


def test_signoffs_in_order_after_the_work(built):
    for w in built["record"]["work_orders"]:
        if (w["step"], w["rack"]) in PLANTED:
            continue
        times = [x["signed_at"] for x in w["signoffs"] if x["signed_at"]]
        assert times == sorted(times) and all(w["done"] and t >= w["done"] for t in times)
        assert [x["signed_at"] is not None for x in w["signoffs"]] == sorted((x["signed_at"] is not None for x in w["signoffs"]), reverse=True)


def test_permits_and_inspections_agree(built):
    rec = built["record"]
    ins = {i["id"]: i for i in rec["inspections"]}
    finals = [p for p in rec["permits"] if p["status"] == "finaled"]
    assert {p["permit"] for p in finals} == {"AHJ-FM-CON", "AHJ-FM-FA"}
    for p in finals:
        i = ins[p["inspection"]]
        assert i["result"] == "pass" and i["by"] == p["by"] and i["at"] == p["finaled"] and p["applied"] < p["issued"] < p["finaled"]
    coc = next(p for p in rec["permits"] if p["permit"] == "AHJ-FM-COC")
    assert coc["issued"] > max(p["finaled"] for p in finals)
    fails = [i for i in rec["inspections"] if i["result"] == "fail"]
    assert {(i["step"], i["by"]) for i in fails} == {("G1-02", "neta"), ("G1-05", "ahj-fm")}
    for f in fails:
        assert any(i["step"] == f["step"] and i["by"] == f["by"] and i["result"] == "pass" and i["at"] > f["at"] for i in rec["inspections"])


def test_nec_edition_by_design_date(built):
    nec = next(d for d in built["record"]["determinations"] if d["id"] == "TX-NEC")
    sealed = next(w for w in built["record"]["work_orders"] if w["step"] == "G0-03")["done"]
    assert sealed < "2026-09-01" and nec["result"].startswith("2023 NEC")


# ------------------------------------------------------------------------------------------ record checks
def test_checks_find_every_planted_record_and_nothing_else(built):
    c = built["self_check"]
    assert (c["detected"], c["planted"], c["false_positives"]) == (4, 4, [])
    assert {f["kind"] for f in built["findings"]} == set(D.CHECKS) and len(built["findings"]) == 4
    assert c["decoys"] == {"signatures_pending_in_window": 1, "inspections_failed_then_passed": 2, "handoff_minutes_after_leak_test": 1}


def test_a_clean_program_has_no_findings(clean):
    """Signatures inside the window, failed-then-passed inspections, and a tap-off energized minutes after the leak
    test are all in the natural record; none is a finding."""
    assert clean["findings"] == [] and clean["self_check"]["planted"] == 0


def test_findings_name_the_records_to_compare(built):
    by = {f["kind"]: f for f in built["findings"]}
    ho4 = by["out_of_order"]
    assert ho4["step"] == "R-HO4" and ho4["partner"] == "Landlord" and "Interface Agreement" in ho4["text"]
    assert len(ho4["refs"]) == 2 and ho4["refs"][0].startswith("CCF-DEP-") and ho4["refs"][1].startswith("RSS-DEP-")
    assert "Fire Marshal" in by["uninspected"]["text"] and "no inspection record" in by["uninspected"]["text"]
    assert "days later" in by["unsigned"]["text"] and "hours before" in by["signed_early"]["text"]
    assert all(f["known_at"] for f in built["findings"])


def test_checks_never_read_the_answer_key():
    import inspect
    for fn in (D.checks, D.records, D.gate_status):
        assert "answer_key" not in inspect.getsource(fn)


def test_planting_has_its_own_stream():
    import inspect
    src = inspect.getsource(SD.DeploymentRecordLayer)
    assert ':deployments:planted"' in src and "self.prng" in inspect.getsource(SD.DeploymentRecordLayer._plant_records)


def test_robustness_small(capsys):
    assert render_deployments.robustness(3) == 0, capsys.readouterr().out


def test_weekly_pack_reconciles_with_the_tab(built):
    import render_weekly
    weeks = render_weekly.packs()
    last = weeks[-1]["deploy"]
    assert last["to_date"] == sum(w["complete"] for w in built["record"]["work_orders"])
    assert last["findings"] == len(built["findings"])
    assert sum(w["deploy"]["week"] for w in weeks) == last["to_date"] - weeks[0]["deploy"]["to_date"] + weeks[0]["deploy"]["week"]


def test_overview_tile():
    import render_hub
    f = render_hub.facts()["deploy"]
    assert (f["handed"], f["racks"], f["findings"]) == (13, 32, 4)
    assert 'data-tile="deployments"' in render_hub.body(render_hub.facts())
