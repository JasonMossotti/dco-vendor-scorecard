"""The Emergency tab: procedures, the decision tree, and the call lists.

The procedures are judgment; these tests hold them to the facts: clocks read from the agreements and the runbook,
owners the RACI makes Responsible, every P1 record in the sample tied to exactly one procedure, a tree with no dead
end, and contacts that are fictional and checked on time."""

from __future__ import annotations

import re
from datetime import timedelta
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import command, emergency, tickets  # noqa: E402

def _fictional(host: str) -> bool:
    """A host in the reserved example.com domain (RFC 2606), matched as a whole name, never a substring."""
    return host == "example.com" or host.endswith(".example.com")


PHONE = re.compile(r"^(\+1 512 555 01\d\d|911|none: .+)$")


@pytest.fixture(scope="module")
def built():
    return emergency.build()


@pytest.fixture(scope="module")
def cfg():
    return emergency.load_config()


def _texts(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _texts(v)
    elif isinstance(o, list):
        for v in o:
            yield from _texts(v)


def test_markdown_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_emergency.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_clocks_are_read_from_their_sources(built, cfg):
    f = built["facts"]
    cc = command.contract_clocks()
    assert (f["bridge_min"], f["page_min"], f["lead_cadence_min"], f["pir_business_days"]) == (
        cc["bridge_min"], cc["page_min"], cc["lead_cadence_min"], cc["pir_business_days"])
    assert f["first_notice_min"] == command.load_config()["clocks"]["first_leadership_min"]
    site = yaml.safe_load((ROOT / "site" / "site.yaml").read_text(encoding="utf-8"))
    assert f["fuel_hours"] == site["plants"]["generators"]["fuel_hours_at_full_load"]
    # Every placeholder is filled, and the bridge rule says the contract's minutes.
    assert not [s for s in _texts({k: v for k, v in built.items() if k != "command"}) if re.search(r"\{[a-z_]+\}", s)]
    assert f"within {cc['bridge_min']} minutes" in built["bridge"]["rules"][0]
    assert any("{bridge_min}" in r for r in cfg["bridge"]["rules"]), "the bridge clock is read, not restated"


def test_every_tree_path_ends_at_a_procedure_and_every_procedure_is_reached(built):
    tree, ids = built["tree"], {t["id"] for t in built["types"]}
    paths = emergency.tree_paths(tree)
    leaves = [p[-1][1][5:] for p in paths]
    assert set(leaves) <= ids
    assert set(leaves) == ids, f"unreachable: {ids - set(leaves)}"
    assert len(paths) == 10
    seen = {n for p in paths for n, _ in p if n}
    assert seen == set(tree["nodes"]), "every question is on some path"
    # Life safety first: the first question is about people, and injury is one answer away.
    assert tree["start"] == "safety" and paths[0][-1][1] == "type:injury" and len(paths[0]) == 2


def test_every_p1_record_has_exactly_one_procedure(built, cfg):
    data = tickets.build()
    p1 = [r for r in data["records"] if r.get("priority") == "P1"]
    assert len(p1) == 9
    for r in p1:
        assert len(emergency.classify(r, cfg["types"])) == 1, (r["id"], emergency.classify(r, cfg["types"]))
    ev = built["events"]
    assert len(ev) == 8 and sum(len(e["records"]) for e in ev) == 9
    a07 = next(e for e in ev if "INC3900001" in e["records"])
    assert a07["records"] == ["WO-41023", "INC3900001"] and a07["types"] == ["power_rack"]
    assert a07["partners"] == ["IT Partner", "Landlord"]
    by_type = {t["id"]: t["samples"] for t in built["types"]}
    assert by_type["security"] == ["SIR-00004", "SIR-00021"] and by_type["power_utility"] == ["WO-41009"]
    assert by_type["fire"] == ["IMP-0006"] and by_type["injury"] == [] and by_type["weather"] == []


def test_owners_are_responsible_under_the_raci(built):
    raci = emergency.raci()
    for t in built["types"]:
        for a in t["actions"]:
            assert a["owner"] in ("Customer", "Landlord", "IT Partner", "Security Partner"), (t["id"], a)
            if "raci" in a:
                assert a["raci"] in raci, f"{t['id']}: no RACI row '{a['raci']}'"
                assert "R" in raci[a["raci"]][a["owner"]], f"{t['id']}: {a['owner']} is not Responsible for {a['raci']}"
            else:
                assert a["owner"] == "Customer", f"{t['id']}: a partner action must name its RACI row: {a['text']}"


def test_each_procedure_is_complete(built):
    roles = {r["role"] for r in built["bridge"]["roles"]}
    for t in built["types"]:
        assert {a["phase"] for a in t["actions"]} == {p["id"] for p in t["phases"]}, t["id"]
        assert len(t["questions"]) >= 5 and len(t["rts"]) >= 3 and t["partner_docs"], t["id"]
        assert set(t["leads"]) <= roles, t["id"]
        tiers = {n["tier"]: n["within_min"] for n in t["notify"]}
        assert tiers["site_leadership"] == built["facts"]["first_notice_min"], t["id"]
        assert tiers.get("regional") == 30, t["id"]
    life = {t["id"]: {n["tier"]: n["within_min"] for n in t["notify"]} for t in built["types"]}
    for k in ("injury", "fire"):
        assert life[k]["executive"] == 0 and life[k]["ehs"] == 0 and life[k]["comms"] == 0
    assert life["security"]["corp_security"] == 0


def test_injury_procedure_cites_the_reporting_rule(built):
    inj = next(t for t in built["types"] if t["id"] == "injury")
    text = " ".join(a["text"] for a in inj["actions"])
    assert "fatality within 8 hours" in text and "within 24 hours (29 CFR 1904.39)" in text
    assert any("osha.gov/report" in s for s in built["sources"])


def test_contacts_are_fictional_roles_and_checked_on_time(built, cfg):
    ids = {c["id"] for c in built["contacts"]}
    assert {t["contact"] for t in built["tiers"]} <= ids
    for c in built["contacts"]:
        if c.get("rota"):
            assert all(re.match(r"^\+1 512 555 01\d\d$", s["phone"]) for s in c["rota_shifts"])
        else:
            assert PHONE.match(c["phone"]), c
        assert not c.get("email") or _fictional(c["email"].rpartition("@")[2]), c
    b = built["bridge"]
    assert PHONE.match(b["dial_in"]) and _fictional(urlparse(b["video"]).hostname or "")
    stale = [c["id"] for c in built["contacts"] if c["stale"]]
    assert stale == ["utility"], "one contact is past its check date as of the sample month's end"
    assert all(c["age_days"] >= 0 for c in built["contacts"]), "no check is dated after the as-of date"
    # Roles only: nobody in the people or roster files is named anywhere in the config.
    text = (ROOT / "config" / "emergency.yaml").read_text(encoding="utf-8")
    import csv
    for f in ("data/sample/vendor/personnel.csv", "data/security/guards.csv"):
        with open(ROOT / f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = row.get("name") or row.get("full_name") or ""
                assert not name or name not in text, f"{name} is named in config/emergency.yaml"


def test_each_procedure_fits_a_one_page_card(built):
    """Chromium prints every card on one Letter page at this size (checked when written); this budget keeps it so."""
    for t in built["types"]:
        n = sum(len(a["text"]) for a in t["actions"]) + sum(map(len, t["questions"])) + sum(map(len, t["rts"])) \
            + sum(map(len, t["partner_docs"])) + len(t["priority"])
        assert n <= 2000 and len(t["notify"]) <= 7, (t["id"], n)


def test_page_builds_and_works(tmp_path):
    import render_emergency
    out = tmp_path / "emergency.html"
    out.write_text(render_emergency.html_page(), encoding="utf-8")
    html = out.read_text(encoding="utf-8")
    assert "__DATA__" not in html and 'href="../emergency/"' in html
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "emergency_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_console_works_and_feeds_the_review(tmp_path):
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    import render_emergency
    import render_pir
    em, pir = tmp_path / "emergency.html", tmp_path / "pir.html"
    em.write_text(render_emergency.html_page(), encoding="utf-8")
    pir.write_text(render_pir.html_page(), encoding="utf-8")
    proc = subprocess.run([node, "emergency_console.cjs", str(em), str(pir)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_responses_cover_every_p1_event_and_p2_record():
    r = emergency.responses()
    data = tickets.build()
    p1 = {x["id"] for x in data["records"] if x["priority"] == "P1"}
    p2 = {x["id"] for x in data["records"] if x["priority"] == "P2"}
    assert p1 | p2 == set(r["by_record"])
    assert r["by_record"]["INC3900001"] == r["by_record"]["WO-41023"] == "WO-41023"
    assert sum(e["priority"] == "P1" for e in r["events"].values()) == 8
    assert all(r["events"][r["by_record"][i]]["priority"] == "P2" for i in p2)


def test_response_facts_come_from_their_sources():
    """A07's console: the topology's GPUs, the SLAs' clocks, the Calendar's change work, the EHS permits, the partners'
    page log, and the bridge's comms log; the daily standup's open P1s all open a response."""
    import json
    from scorecard import standup as SU
    from scorecard.sla_model import load_sla
    e = emergency.responses()["events"]["WO-41023"]
    topo = json.loads(emergency.TOPOLOGY.read_text(encoding="utf-8"))
    assert e["gpus"] == 4 * len(next(r for r in topo["racks"] if r["rack"] == "A07")["compute_trays"]) == 72
    p1 = {k: next(p for p in load_sla(f)["priorities"] if p["id"] == "P1") for k, f in emergency.SLA_FILES.items() if k != "Security Partner"}
    assert {(c["label"], c["min"]) for c in e["clocks"]} == {(f"Restore ({k} SLA, P1)", p["restore_min"]) for k, p in p1.items()} \
        | {(f"Engaged on site ({k} SLA, P1)", p["engaged_on_site_min"]) for k, p in p1.items()}
    assert [j["id"] for j in e["work"]] == ["MOP-310", "PM-0005"]
    assert [p["permit"] for p in e["permits"]] == ["PTW-26020", "PTW-26021"]
    assert len(e["pages"]) == 5 and len(e["replay"]) == 27
    assert e["redundancy"] and e["redundancy"][0]["name"] == "Rack feeds"
    sec = emergency.responses()["events"]["SIR-00004"]
    assert [c["min"] for c in sec["clocks"]] == [3, 60]
    su = SU.Standup()
    by = emergency.responses()["by_record"]
    days = {i["refs"][0] for h in range(0, 28 * 24, 6) for i in su.open_incidents(su.start + timedelta(hours=h)) if i["priority"] == "P1" and i["refs"]}
    assert days and all(x in by for x in days)


def test_console_clocks_come_from_the_runbook_and_routing_file():
    c = emergency.console()
    n = yaml.safe_load(emergency.NOTIFY.read_text(encoding="utf-8"))
    rule = next(r for r in n["rules"] if r["event"] == "critical")
    assert [x["after_min"] for x in c["escalate"]] == [x["after_min"] for x in rule["escalate"]] == [15, 30]
    assert c["runbook"] == command.load_config()["clocks"]


def test_p1_buttons_on_the_portal_live_and_standup():
    assert "Open emergency response" in (ROOT / "templates" / "tickets.html").read_text(encoding="utf-8")
    assert "Escalate to emergency response" in (ROOT / "templates" / "tickets.html").read_text(encoding="utf-8")
    assert "../emergency/#respond/" in (ROOT / "templates" / "ops.html").read_text(encoding="utf-8")
    import render_live
    html = render_live.html_page()
    assert '"p1":' in html and "WO-41023" in html
