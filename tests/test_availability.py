"""Availability and repair turnaround: the rollup behind the Availability tab.

It scores nothing new, so every number must reconcile with a result the project already has: the
IT Partner's GPU-hours with CSL-01, the Landlord's with the post-incident review, the weeks with the
weekly packs, and the spares measures with the scorecard.
"""

import csv
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import availability as AV  # noqa: E402

SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def b():
    return AV.build()


def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_report_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_availability.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_headline_numbers(b):
    assert (b["sched"]["pct"], b["sched"]["lost"], b["sched"]["outages"]) == (99.918, 1440.2, 107)
    assert b["csl01"]["actual"] == 99.927 and b["contract_lost"] == 1524.9
    assert {o["owner"]: o["hours"] for o in b["owners"]} == {"IT Partner": 1279.2, "Landlord": 245.7, "OEM": 0.0, "Customer": 0.0, "Planned work": 0.0}


def test_it_partner_hours_are_the_scorecards_csl01(b):
    sc = json.loads((ROOT / "reports" / "scorecard.json").read_text(encoding="utf-8"))
    csl = next(c for c in sc["csl"] if c["id"] == "CSL-01")
    lost = float(re.search(r"([\d,]+) capacity", csl["detail"])[1].replace(",", ""))
    it = next(o["hours"] for o in b["owners"] if o["owner"] == "IT Partner")
    assert round(it) == lost and b["csl01"]["actual"] == csl["actual"]
    installed = float(re.search(r"of ([\d,]+) installed", csl["detail"])[1].replace(",", ""))
    assert round(b["installed"]) == installed


def test_landlord_hours_match_the_post_incident_review(b):
    from scorecard.pir import Dataset, build_review
    f = build_review(Dataset(SAMPLE), "INC3900001")
    ll = next(o["hours"] for o in b["owners"] if o["owner"] == "Landlord")
    assert ll == f["impact"]["gpu_hours_landlord"] == 245.7
    assert [e["rack"] for e in b["landlord_events"]] == ["A07"] and b["landlord_events"][0]["t0"] == f["power_lost"]


def test_scheduler_hours_recomputed_from_the_raw_records(b):
    """Every drain or down until the node is idle again, 4 GPUs a node, read straight from the JSON lines."""
    states = defaultdict(list)
    for line in (SAMPLE / "telemetry" / "scheduler_node_states.jsonl").read_text(encoding="utf-8").splitlines():
        s = json.loads(line)
        states[s["node"]].append(s)
    total = 0.0
    for xs in states.values():
        down = None
        for s in sorted(xs, key=lambda s: s["timestamp"]):
            if s["state"] in ("drain", "down"):
                down = down or s
            elif down:
                total += (_t(s["timestamp"]) - _t(down["timestamp"])).total_seconds() / 3600 * 4
                down = None
    assert round(total, 1) == b["sched"]["lost"]
    assert round(sum(r["hours"] for r in b["sched"]["by_reason"]), 1) == b["sched"]["lost"]


def test_bridge_walks_the_scheduler_to_the_contracts(b):
    rows = {r["key"]: r["hours"] for r in b["bridge"]["rows"]}
    assert b["bridge"]["closes"]
    assert rows == {"sched": 1440.2, "after_rts": -10.5, "before_drain": 6.4, "not_held": 42.4, "degraded": 46.4, "contract": 1524.9}
    assert "unmatched" not in rows, "every scheduler outage belongs to an incident or a Landlord event"


def test_causes_add_up_to_the_owners(b):
    own = {o["owner"]: o["hours"] for o in b["owners"]}
    assert abs(sum(c["it"] for c in b["causes"]) - own["IT Partner"]) < 0.2   # each row rounded to 0.1
    assert abs(sum(c["landlord"] for c in b["causes"]) - own["Landlord"]) < 0.2
    assert b["causes"][0]["cause"] == "Compute tray (GPU)" and next(c for c in b["causes"] if c["category"] == "switch_tray")["worst_rack"] == "A15"


def test_days_and_weeks_add_up_to_the_month(b):
    it = sum(sum(d["it_by_cause"].values()) for d in b["days"])
    assert abs(it - 1279.2) < 0.1 and abs(sum(d["landlord"] for d in b["days"]) - 245.7) < 0.1
    assert abs(sum(d["sched_lost"] for d in b["days"]) - b["sched"]["lost"]) < 0.2
    assert abs(sum(w["it_lost"] for w in b["weeks"]) - 1279.2) < 0.2 and len(b["days"]) == 28


def test_weeks_match_the_weekly_packs(b):
    import render_weekly
    packs = render_weekly.packs()
    for w, p in zip(b["weeks"], packs):
        row = next(r for part in p["partners"] if part["role"] == "IT Partner" for r in part["levels"] if r["id"] == "CSL-01")
        assert row["week"] == w["csl01"], p["id"]
        assert p["availability"]["week"] == {"sched_pct": w["sched_pct"], "it": w["it_lost"], "landlord": w["landlord_lost"], "installed": w["installed"]}
    mtd = packs[-1]["availability"]["mtd"]
    assert (mtd["sched_pct"], mtd["it"], mtd["landlord"]) == (b["sched"]["pct"], 1279.2, 245.7)


def test_reported_weekly_availability_is_the_self_report(b):
    rep = json.loads((SAMPLE / "vendor" / "self_reported_weekly.json").read_text(encoding="utf-8"))
    assert [w["reported"] for w in b["weeks"]] == [r["gpu_availability_pct"] for r in rep]


def test_ticket_stages_add_up_and_never_guess(b):
    assert len(b["tickets"]) == 75
    for t in b["tickets"]:
        if not t["missing"]:
            assert abs(sum(v for v in t["stages"].values()) - t["measured_min"]) < 0.5, t["ticket"]
        assert all(v is None or v >= 0 for v in t["stages"].values()), t["ticket"]
    by = {t["ticket"]: t for t in b["tickets"]}
    for n, f in (("INC3100748", "F-008"), ("INC3100510", "F-006")):
        assert by[n]["missing"] == ["validation record"] and by[n]["stages"]["validate"] is None and f in by[n]["findings"]
    assert by["INC3100357"]["measured_min"] - by["INC3100357"]["reported_min"] > 100 and "F-005" in by["INC3100357"]["findings"]
    assert by["INC3900001"]["fa3"] and by["INC3900001"]["stages"]["detect"] == 0
    assert by["INC3100085"]["tor"] == "INC3100068"


def test_restoration_per_ticket_of_record_matches_the_engine(b):
    from scorecard.kpi import build_incidents
    R = AV.Rollup()
    inc = [i for i in build_incidents(R.ctx, R.findings) if R.start <= i.t0 < R.end]
    assert sum(r["tors"] for r in b["restoration"]) == len(inc)
    tray = next(r for r in b["restoration"] if r["cause"] == "Compute tray (GPU)")
    assert tray["merged"] == 2 and tray["measured"]["max"] == 623.2, "the split ticket F-001 measures 10.4 hours as one outage"


def test_spares_and_rma_match_the_scorecard(b):
    sc = json.loads((ROOT / "reports" / "scorecard.json").read_text(encoding="utf-8"))
    km = {k["id"]: k["actual"] for k in sc["km"]}
    assert {k["id"]: k["actual"] for k in b["spares"]["kms"]} == {k: km[k] for k in ("KM-06", "KM-07", "KM-08")}
    tray = next(r for r in b["spares"]["rows"] if r["fru"] == "Compute tray")
    assert (tray["minimum"], tray["opening"], tray["low"], tray["days_below"]) == (6, 9, 1, 16)
    assert b["spares"]["removed"] == len(b["spares"]["rma"]) == 53 and b["spares"]["no_rma"] == []
    ledger = list(csv.DictReader((SAMPLE / "vendor" / "spares_ledger.csv").open(encoding="utf-8")))
    for r in b["spares"]["rows"]:
        xs = [x for x in ledger if x["fru"] == r["fru"]]
        if xs:
            assert r["closing"] == int(xs[-1]["balance_after"]), r["fru"]


def test_page_names_no_technician(tmp_path):
    import render_availability
    html = render_availability.html_page()
    names = [r["name"] for r in csv.DictReader((SAMPLE / "vendor" / "personnel.csv").open(encoding="utf-8"))]
    assert names and not [n for n in names if n in html]


def test_robustness_one_month(capsys):
    import render_availability
    assert render_availability.robustness(1) == 0, capsys.readouterr().out


def test_interactive_page_builds_and_works(tmp_path):
    import render_availability
    out = tmp_path / "availability.html"
    html = render_availability.html_page()
    assert "__DATA__" not in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    out.write_text(html, encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "availability_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
