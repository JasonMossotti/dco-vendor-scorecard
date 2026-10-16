"""Fire protection impairments: the fire panel's history, the Landlord's impairment log, and the Customer's notices,
reconciled under Interface Agreement section 12, with two planted findings and no false positives."""

import filecmp
import json
import re
import sys
from pathlib import Path

import pytest

from scorecard import fire as F
from scorecard.sla_model import load_interface_agreement
from scorecard.synthetic import fire as G

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "fire"
sys.path.insert(0, str(ROOT / "scripts"))

import render_fire  # noqa: E402

NAMES = ["vesda", "maintenance", "notice", "restored", "restore_notice", "window", "watch", "logged"]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fire")
    before = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    seed = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]["seed"]
    layer = G.FireLayer(SAMPLE, seed)
    G.write_fire(layer, layer.run(), tmp, "data/sample")
    after = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    return tmp, before == after


@pytest.fixture(scope="module")
def r():
    return F.analyse(render_fire.load())


def test_committed_layer_is_current_and_sample_untouched(regenerated):
    out, untouched = regenerated
    assert untouched, "generating the fire layer must not write data/sample"
    files = sorted(p.name for p in out.iterdir())
    assert files == sorted(p.name for p in LAYER.iterdir())
    for f in files:
        assert filecmp.cmp(out / f, LAYER / f, shallow=False), f"data/fire/{f} is stale: run python scripts/generate_fire.py"


def test_report_is_current():
    assert (ROOT / "reports" / "fire_protection.md").read_text(encoding="utf-8") == render_fire.markdown(render_fire.prepare())


def test_every_agreement_holds_and_both_plants_are_found(r):
    assert [c.name for c in r["agreements"]] == NAMES
    for c in r["agreements"]:
        assert c.checked > 0 and not c.misses, (c.name, c.misses)
    key = json.loads((LAYER / "answer_key.json").read_text(encoding="utf-8"))
    assert F.score(r["findings"], key) == {"planted": 2, "found": 2, "false_positives": 0}
    assert [f["kind"] for f in r["findings"]] == ["restored_late", "unlogged"]
    assert [f["id"] for f in r["findings"]] == ["FLS-1", "FLS-2"]


def test_findings_quote_the_records(r):
    late, unlogged = r["findings"]
    imp = next(x for x in r["rc"]["imps"] if x["row"]["imp_id"] == late["imp"])
    assert imp["panel_end"] > imp["window_end"] and imp["restored"] <= imp["window_end"]
    assert f"{imp['panel_end']:%Y-%m-%d %H:%M}" in late["summary"]
    assert not [m for m in imp["notices"] if m["kind"] == "extension"]
    assert "lied" not in late["summary"] + unlogged["summary"]
    s = next(s for s in r["rc"]["oos"] if s["device"] == unlogged["devices"][0] and F.iso(s["start"]) == unlogged["from"])
    assert not any(s in x["spans"] for x in r["rc"]["imps"])


def test_every_vesda_event_and_fire_maintenance_record_is_covered():
    t = render_fire.load()
    assert len(t.vesda) == 5 and len(t.pm) == 1
    imp = next(i for i in t.imps if i["pm_ref"] == t.pm[0]["task_id"])
    assert imp["mop_ref"] == t.pm[0]["mop_ref"] and imp["devices"] == t.pm[0]["asset"]


def test_decoys_are_present():
    t = render_fire.load()
    assert any(n["kind"] == "extension" for n in t.notices), "a planned impairment extended in time"
    assert any(i["type"] == "unplanned" for i in t.imps)
    sp = F.spans(t.panel, t.end)
    assert any(s["signal"] == "Trouble" for s in sp), "troubles are not impairments"
    assert any(F.out_of_service(s) and (s["end"] - s["start"]).total_seconds() < 1800 and not s["device"].startswith("VESDA") for s in sp)


def test_thresholds_match_the_interface_agreement():
    rules = {r["id"]: r["rule"] for r in load_interface_agreement()["fire_impairments"]["rules"]}
    assert f"{F.NOTICE_LEAD_H} hours before" in rules["FPI-1"]
    assert f"within {F.UNPLANNED_NOTICE_MIN} minutes" in rules["FPI-2"]
    assert f"more than {F.WATCH_AFTER_H} hours" in rules["FPI-3"]
    assert f"within {F.RECORD_MIN} minutes" in rules["FPI-5"] and f"within {F.RESTORE_NOTICE_MIN} minutes" in rules["FPI-5"]
    assert f"more than {F.LOG_AFTER_MIN} minutes" in rules["FPI-6"]


def test_core_services_are_customer_owned_in_the_matrix():
    raci = {r["component"]: r for r in load_interface_agreement()["raci"]}
    for name in ("Core network services: DNS, DHCP, and NTP and PTP time", "Firewalls and network segmentation, including the monitoring network"):
        assert raci[name]["Customer"] == "A/R"
        assert all("A" not in str(v) and "R" not in str(v) for k, v in raci[name].items() if k not in ("component", "Customer"))


def test_fire_devices_are_in_the_directory():
    devs = json.loads((ROOT / "docs" / "site" / "devices.json").read_text(encoding="utf-8"))["devices"]
    names = {n for n, e in devs.items() if e["kind"] in ("facp", "paz", "cas")}
    assert names == {"FACP-1", "PAZ-A1", "PAZ-A2", "PAZ-B1", "PAZ-B2", "PAZ-C1", "CAS-A1", "CAS-B1", "CAS-C1"}
    monitored = {c[1] for c in devs["FACP-1"]["conn"] if c[0] == "Monitors"}
    assert monitored == {n for n, e in devs.items() if e["kind"] in ("vesda", "paz", "cas")}
    t = render_fire.load()
    for e in t.panel:
        assert e["device"] in devs, e["device"]


def test_impairments_are_portal_records():
    from scorecard import tickets as T
    assert re.fullmatch(T.ID_PATTERN, "IMP-0001")
    ids = T.ids()
    t = render_fire.load()
    assert {i["imp_id"] for i in t.imps} <= set(ids)
