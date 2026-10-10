"""Facility (Landlord) synthetic data: realism, independence from the IT data, and planted evidence."""

import copy
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from scorecard import site_model as S
from scorecard.connectors import FileConnector
from scorecard.sla_model import PARTNER_FILES, load_sla
from scorecard.synthetic import SiteGenerator
from scorecard.synthetic.facility import GEN_KW, UPS_STATES, room_for

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = Path(os.environ.get("FACILITY_DATASET", ROOT / "data" / "sample"))   # set to sweep other months


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def src():
    return FileConnector(SAMPLE)


@pytest.fixture(scope="module")
def planted():
    return json.loads((SAMPLE / "ground_truth" / "facility_planted_discrepancies.json").read_text(encoding="utf-8"))


def by_type(planted, kind):
    return [p for p in planted if p["type"] == kind]


def badged(src, room, start, end, person=None):
    return [b for b in src.get("landlord_badges")
            if b["reader"] == room and start <= b["timestamp"] <= end and (person is None or b["person_id"] == person)]


# ------------------------------------------------------------------ independence
def test_facility_stream_only_adds_the_it_side_of_rack_outages(config):
    """Every IT record is unchanged; the only additions are the IT side of Landlord-caused rack outages."""
    start = date(2026, 8, 31)
    it_only = {k: v for k, v in config.items() if k != "facility"}
    a = SiteGenerator(load_sla(), it_only, start=start).run()
    b = SiteGenerator(load_sla(), config, start=start).run()
    assert a["facility"] is None and b["facility"] is not None and a["planted"] == b["planted"]
    racks = {o["rack"] for o in b["facility"]["rack_outages"]}
    assert racks
    for key, rows in a["streams"].items():
        before = [json.dumps(r, sort_keys=True, default=str) for r in rows]
        after = [json.dumps(r, sort_keys=True, default=str) for r in b["streams"][key]]
        extra = list(after)
        for r in before:
            extra.remove(r)               # raises if any original record changed or vanished
        for r in map(json.loads, extra):
            assert (r.get("rack") in racks or r.get("target") in racks or r.get("category") == "rack_facility"
                    or any(r.get("node", "").startswith(x.lower() + "-") for x in racks) or key == "badge"), (key, r)


def test_every_configured_landlord_discrepancy_is_planted(planted, config):
    want = {k: v for k, v in config["facility"]["planted"].items() if v}
    want["critical_work_no_mop"] = want.get("critical_work_no_mop", 0) + config["facility"].get("rack_power_outages", 0)
    got = {}
    for p in planted:
        got[p["type"]] = got.get(p["type"], 0) + 1
    assert got == want


def test_engine_cannot_read_the_facility_answer_key(src):
    with pytest.raises(PermissionError):
        src.read_path("ground_truth/facility_planted_discrepancies.json")


# ------------------------------------------------------------------ realism
def test_device_names_and_values_match_the_site_and_the_standards(src):
    site = S.load_site()
    names = {e["id"] for e in S.equipment(site)}
    for e in src.get("ups_status"):
        assert e["ups"] in names and e["upsBasicOutputStatus"] in UPS_STATES
    for e in src.get("ups_nmc_events"):
        assert e["ups"] in names
        if e["event"].startswith("upsBasicOutputStatus"):
            assert e["event"].split()[1] in UPS_STATES
    for e in src.get("cdu_events"):
        assert e["cdu"] in names and e["resource"].startswith(f"/redfish/v1/ThermalEquipment/CDUs/{e['cdu']}")
    for e in src.get("busway_events"):
        assert e["busway"] in names
    for e in src.get("vesda_events"):
        assert e["level"] in (None, "Alert", "Action", "Fire 1", "Fire 2")
    for wo in src.get("work_orders"):
        assert wo["unit"] in names or wo["unit"].startswith(("TTDM-", "VESDA-", "138 kV", "Rack "))


def test_generator_readings_are_consistent(src):
    for r in src.get("emcp_readings"):
        assert r["gen_pct_rated_kw"] == pytest.approx(r["gen_total_kw"] / GEN_KW * 100, abs=0.11)
        assert r["engine_operating_state"] in ("Starting", "Running", "Cooldown", "Stopped")


def test_utility_outage_is_carried_by_ups_then_generators(src):
    trips = [e for e in src.get("epms_events") if "utility undervoltage" in e["event"]]
    assert trips, "the sample month includes one utility outage"
    t0 = trips[0]["timestamp"]
    on_batt = [e for e in src.get("ups_nmc_events") if e["timestamp"] == t0 and e["event"].endswith("onBattery")]
    assert len(on_batt) == 12, "every UPS (8 IT and 4 mechanical) rode through on battery"
    for e in on_batt:
        back = next(x for x in src.get("ups_nmc_events") if x["ups"] == e["ups"] and x["timestamp"] > t0)
        assert back["event"].endswith("onLine") and (back["timestamp"] - t0).total_seconds() <= 15
    # The EMCP log holds the monthly test runs; the outage readings live in the power telemetry, which follows the racks.
    assert not [r for r in src.get("emcp_readings") if t0 - timedelta(minutes=5) < r["timestamp"] < t0 + timedelta(hours=2)]
    states = [json.loads(x) for x in (ROOT / "data" / "telemetry" / "power" / "states.jsonl").read_text(encoding="utf-8").splitlines() if x]
    running = {s["device"] for s in states if s["family"] == "generator" and s["value"] == "Running"
               and t0 < datetime.fromisoformat(s["time"].replace("Z", "+00:00")) < t0 + timedelta(minutes=10)}
    assert len(running) == 7


def test_honest_generator_tests_meet_nfpa_110(src, planted):
    bad = {p["generator"] for p in by_type(planted, "gen_test_no_load")}
    for pm in [p for p in src.get("pm_records") if p["task"] == "Monthly loaded exercise"]:
        rows = [r for r in src.get("emcp_readings") if r["generator"] == pm["asset"]
                and pm["completed_at"] - timedelta(hours=1) <= r["timestamp"] <= pm["completed_at"]
                and r["engine_operating_state"] == "Running"]
        loaded = [r for r in rows if r["gen_pct_rated_kw"] >= 30]
        if pm["asset"] in bad:
            assert not loaded
        else:
            assert len(loaded) >= 30, pm["asset"]


def test_honest_maintenance_has_badge_evidence(src, planted):
    """Evidence means the engineer badged into the equipment's own room shortly before completion."""
    skipped = {p["task"] for p in by_type(planted, "pm_without_evidence")}
    for pm in src.get("pm_records"):
        hits = badged(src, room_for(pm["asset"]), pm["completed_at"] - timedelta(hours=6), pm["completed_at"],
                      person=pm["engineer"])
        if pm["task_id"] in skipped:
            assert not hits, pm["task_id"]
        else:
            assert hits, pm["task_id"]


def test_critical_work_has_an_approved_mop_unless_planted(src, planted):
    bad = {p["busway"] for p in by_type(planted, "critical_work_no_mop")}
    mops = src.get("landlord_mops")
    for e in [x for x in src.get("busway_events") if x.get("event") == "Breaker open"]:
        covered = [m for m in mops if e["busway"] in m["assets"] and m["window_start"] <= e["timestamp"] <= m["window_end"]]
        assert (not covered) == (e["busway"] in bad), e


def test_overrides_carry_a_change_reference_unless_planted(src, planted):
    bad = {(p["device"], ts(p["set_at"])) for p in by_type(planted, "bms_override_unrecorded")}
    sets = [x for x in src.get("facility_bms") if x["kind"] in ("override", "inhibit") and x["action"] == "set"]
    assert {(e["device"], e["timestamp"]) for e in sets} >= bad
    for e in sets:
        assert bool(e["change_ref"]) == ((e["device"], e["timestamp"]) not in bad), e


def test_acknowledged_without_dispatch_has_no_badge(src, planted):
    for p in by_type(planted, "alarm_acked_no_dispatch"):
        wo = next(w for w in src.get("work_orders") if w["wo"] == p["wo"])
        assert wo["engaged_at"] is not None, "the work order claims attendance"
        assert not badged(src, wo["room"], ts(p["t0"]), wo["restored_at"])


def test_clock_shift_work_order_restores_before_telemetry(src, planted):
    for p in by_type(planted, "landlord_clock_shift"):
        assert ts(p["wo_restored"]) < ts(p["telemetry_restored"])
        ok = [e for e in src.get("cdu_events") if e["cdu"] == p["unit"] and e["value"] == "OK"
              and e["property"] == "PumpRedundancy.Status.Health"]
        assert any(e["timestamp"] == ts(p["telemetry_restored"]) for e in ok)


def test_contradicted_attribution_shows_feed_lost_at_the_busway(src, planted):
    for p in by_type(planted, "attribution_contradicted"):
        wo = next(w for w in src.get("work_orders") if w["wo"] == p["wo"])
        assert wo["attribution"] == "IT Partner"
        lost = [e for e in src.get("busway_events") if e["busway"] == p["unit"] and e.get("state") == "out_of_tolerance"]
        assert lost, "the Customer's busway data shows the feed lost upstream of the tap-off"


def test_landlord_self_report_claims_every_service_level_met(src):
    sla = load_sla(PARTNER_FILES["landlord"])
    for w in src.get("landlord_weekly"):
        for c in sla["critical_service_levels"]:
            assert w["results"][c["id"]] >= c["expected"]


def test_other_seeds_generate_cleanly(config, tmp_path):
    for seed in (3, 11, 42):
        out = SiteGenerator(load_sla(), config, start=date(2026, 3, 2), seed=seed).run()["facility"]
        assert len(out["planted"]) == sum(config["facility"]["planted"].values()) + config["facility"].get("rack_power_outages", 0)
        assert out["work_orders"] and out["emcp"]
