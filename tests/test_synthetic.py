"""Tests for the synthetic data generator.

These tests prove two things the rest of the project depends on:
1. Every planted discrepancy leaves real, detectable evidence in the data.
2. Honest records are internally consistent (so detections are not noise).
"""

import csv
import filecmp
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from scorecard.sla_model import load_sla
from scorecard.synthetic import SiteGenerator, write_dataset

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_START = date(2026, 8, 31)


def P(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ds(tmp_path_factory, config):
    out = tmp_path_factory.mktemp("sample")
    write_dataset(SiteGenerator(load_sla(), config, start=SAMPLE_START).run(), out)
    d = {
        "dir": out,
        "tickets": {t["number"]: t for t in json.loads((out / "vendor/tickets.json").read_text())},
        "planted": json.loads((out / "ground_truth/planted_discrepancies.json").read_text()),
        "gt": {g["gt_id"]: g for g in json.loads((out / "ground_truth/incidents.json").read_text())},
        "xid": jsonl(out / "telemetry/dcgm_xid_events.jsonl"),
        "inv": jsonl(out / "telemetry/redfish_inventory_changes.jsonl"),
        "health": jsonl(out / "telemetry/health_checks.jsonl"),
        "ufm": jsonl(out / "telemetry/ufm_port_events.jsonl"),
        "badge": rows(out / "access/badge_events.csv"),
        "roster": rows(out / "vendor/roster.csv"),
        "counts": rows(out / "vendor/spares_cycle_counts.csv"),
        "cab": json.loads((out / "customer/cab_changes.json").read_text()),
    }
    return d


def planted(ds, kind):
    items = [p for p in ds["planted"] if p["type"] == kind]
    assert items, f"no planted {kind}"
    return items


# ------------------------------------------------------------- reproducibility
def test_committed_sample_is_current(ds):
    """data/sample must equal a fresh run (catches code changes without regenerating)."""
    sample = ROOT / "data" / "sample"
    for f in ds["dir"].rglob("*"):
        if f.is_file():
            rel = f.relative_to(ds["dir"])
            assert filecmp.cmp(f, sample / rel, shallow=False), f"{rel} is stale; run scripts/generate_data.py"


def test_different_seed_differs(config, tmp_path):
    a = SiteGenerator(load_sla(), config, start=SAMPLE_START, seed=1).run()
    b = SiteGenerator(load_sla(), config, start=SAMPLE_START, seed=2).run()
    assert a["streams"]["tickets"] != b["streams"]["tickets"]


def test_start_must_be_monday(config):
    with pytest.raises(ValueError):
        SiteGenerator(load_sla(), config, start=date(2026, 9, 1))


def test_all_configured_anomaly_types_planted(ds, config):
    want = {k for k, v in config["anomalies"].items() if v}
    assert want == {p["type"] for p in ds["planted"]}


# ----------------------------------------------------------- honest integrity
def test_every_ticket_tech_was_badged_in_hall(ds):
    by_person = {}
    for b in ds["badge"]:
        by_person.setdefault(b["person_id"], []).append(b)
    for t in ds["tickets"].values():
        door = f"HALL-{t['hall'][-1]}"
        entries = [P(b["timestamp"]) for b in by_person.get(t["assigned_to"], [])
                   if b["door"] == door and b["direction"] == "in"]
        assert any(P(t["opened_at"]) - timedelta(hours=3) <= e <= P(t["resolved_at"]) for e in entries), t["number"]


def test_cycle_count_variance_only_from_planted_drift(ds):
    variances = [c for c in ds["counts"] if c["system_qty"] != c["counted_qty"]]
    assert len(variances) == len(planted(ds, "spares_drift"))


def test_no_unplanned_repeat_failures(ds):
    hosts = {}
    for g in ds["gt"].values():
        if g["host"]:
            hosts.setdefault(g["host"], []).append(g)
    for h, gs in hosts.items():
        if len(gs) > 1:
            assert any(g["anomalies"] or g["parent_gt_id"] for g in gs), h


def test_vendor_self_report_hides_telemetry_breaches(ds):
    """The demo's premise: the vendor's own numbers look perfect where telemetry does not."""
    weekly = json.loads((ds["dir"] / "vendor/self_reported_weekly.json").read_text())
    assert all(w["first_time_fix_pct"] == 100.0 and w["staffing_fill_pct"] == 100.0 for w in weekly)
    assert len(planted(ds, "phantom_fix")) > 0 and len(planted(ds, "staffing_gap")) > 0


# ------------------------------------------------- planted discrepancy evidence
def test_unverified_swap_serial_never_in_inventory(ds):
    new_serials = {e["new_value"] for e in ds["inv"] if e["property"] == "SerialNumber"}
    for p in planted(ds, "unverified_swap"):
        part = ds["tickets"][p["ticket"]]["parts_used"][0]
        assert part["installed_serial"] not in new_serials


def test_skipped_validation_has_no_health_checks(ds):
    for p in planted(ds, "skipped_validation"):
        g = ds["gt"][p["gt_id"]]
        window = (P(g["t0"]), P(g["rts"]) + timedelta(hours=2))
        checks = [h for h in ds["health"] if h["target"] == g["host"] and window[0] <= P(h["started_at"]) <= window[1]]
        assert checks == []
        assert "Validation complete" in ds["tickets"][p["ticket"]]["work_notes"][-1]["text"]


def test_clock_shift_fault_precedes_ticket(ds):
    for p in planted(ds, "clock_shift"):
        g, t = ds["gt"][p["gt_id"]], ds["tickets"][p["ticket"]]
        first = min(P(x["timestamp"]) for x in ds["xid"] if x["host"] == g["host"] and P(x["timestamp"]) <= P(t["opened_at"]))
        assert P(t["opened_at"]) - first > timedelta(minutes=90)
        vendor_min = (P(t["resolved_at"]) - P(t["reported_outage_start"])).total_seconds() / 60
        assert vendor_min <= g["target_restore_min"] < g["true_restore_min"]


def test_ghost_engagement_badge_after_claim(ds):
    for p in planted(ds, "ghost_engagement"):
        t = ds["tickets"][p["ticket"]]
        claim = P(next(n["at"] for n in t["work_notes"] if n["text"].startswith("On site")))
        door = f"HALL-{t['hall'][-1]}"
        first_in = min(P(b["timestamp"]) for b in ds["badge"] if b["person_id"] == t["assigned_to"]
                       and b["door"] == door and b["direction"] == "in" and P(b["timestamp"]) >= P(t["opened_at"]) - timedelta(minutes=10))
        assert first_in - claim > timedelta(minutes=10)


def test_phantom_fix_same_family_recurs_after_stability_window(ds):
    """Recurrence lands after the 24 h stability window but within 7 days (TR-5)."""
    family = {79: "bus", 94: "ecc", 48: "ecc", 119: "gsp", 145: "nvlink", 149: "nvlink"}
    for p in planted(ds, "phantom_fix"):
        g, t = ds["gt"][p["gt_id"]], ds["tickets"][p["ticket"]]
        later = [x for x in ds["xid"] if x["host"] == g["host"] and P(x["timestamp"]) > P(g["rts"])]
        first = min(later, key=lambda x: x["timestamp"])
        gap = P(first["timestamp"]) - P(g["rts"])
        assert timedelta(hours=24) < gap <= timedelta(days=7)
        assert family[first["xid"]] == family[g["xid"]]
        assert t["close_code"] == "Cleaned/reseated"


def test_ticket_split_refault_within_early_failure_window(ds):
    """Each vendor ticket looks on time; measured from the first T0 it is a breach."""
    for p in planted(ds, "ticket_split"):
        g = ds["gt"][p["gt_id"]]
        t1, t2 = ds["tickets"][p["ticket"]], ds["tickets"][p["recurrence_ticket"]]
        refault = min(P(x["timestamp"]) for x in ds["xid"] if x["host"] == g["host"] and P(x["timestamp"]) > P(g["rts"]))
        assert refault - P(g["rts"]) <= timedelta(minutes=60)          # TR-1 window
        target = g["target_restore_min"]
        for t in (t1, t2):                                             # vendor view: both on time
            assert (P(t["resolved_at"]) - P(t["reported_outage_start"])).total_seconds() / 60 <= target
        child = ds["gt"][next(k for k, v in ds["gt"].items() if v["parent_gt_id"] == g["gt_id"])]
        assert (P(child["rts"]) - P(g["t0"])).total_seconds() / 60 > target   # truth: breach
        assert t1["configuration_item"] == t2["configuration_item"]


def test_wrong_end_optic_errors_continue(ds):
    for p in planted(ds, "wrong_end_optic"):
        g, t = ds["gt"][p["gt_id"]], ds["tickets"][p["ticket"]]
        after = [u for u in ds["ufm"] if u["switch"] == g["link"]["switch"] and u["port"] == g["link"]["port"]
                 and u["event"] == "symbol_errors" and P(u["timestamp"]) > P(t["resolved_at"])]
        assert after
        assert "(switch side)" in t["parts_used"][0]["location"]


def test_lemon_unit_three_failures_no_rma_escalation(ds):
    for p in planted(ds, "lemon_unit"):
        ts = [ds["tickets"][n] for n in p["tickets"]]
        assert len(ts) >= 3 and len({t["configuration_item"] for t in ts}) == 1
        span = P(ts[-1]["opened_at"]) - P(ts[0]["opened_at"])
        assert span <= timedelta(days=30)
        assert not any("RMA" in n["text"] for t in ts for n in t["work_notes"])


def test_staffing_gap_rostered_but_never_badged(ds):
    for p in planted(ds, "staffing_gap"):
        s, e = P(p["shift_start"]), P(p["shift_end"])
        for pid in p["missing_person_ids"]:
            assert any(r["person_id"] == pid and r["shift_start"] == p["shift_start"] for r in ds["roster"])
            assert not any(b["person_id"] == pid and s - timedelta(hours=1) <= P(b["timestamp"]) <= e for b in ds["badge"])


def test_unauthorized_change_has_no_cab_cover(ds):
    for p in planted(ds, "unauthorized_change"):
        fw = [e for e in ds["inv"] if e["rack"] == p["rack"] and e["property"] == "FirmwareVersion"]
        assert len(fw) >= 18
        covered = [c for c in ds["cab"] if c["rack"] == p["rack"]]
        assert covered == []
