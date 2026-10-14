"""Site health: redundancy, family states, and rack states from the committed telemetry, agreeing with each section."""

import inspect
import json
import sys
from pathlib import Path

import pytest

from scorecard import site_health as SH

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_telemetry  # noqa: E402


@pytest.fixture(scope="module")
def built():
    return SH.build()


def group(data, key):
    return next(g for g in data["groups"] if g["key"] == key)


def hours(state, s):
    return sum(1 for x in state if x == s)


def test_every_agreement_holds(built):
    sh, data = built
    checks = SH.agreements(sh, data)
    assert len(checks) == 10
    assert all(c.checked for c in checks), [c.name for c in checks if not c.checked]
    assert [m for c in checks for m in c.misses] == []


def test_reads_only_the_published_telemetry_and_the_topology():
    src = inspect.getsource(SH)
    assert "synthetic" not in src and "random" not in src
    assert "ground_truth" not in src and "answer_key" not in src


def test_redundancy_headline(built):
    _, d = built
    util = group(d, "utility")
    assert hours(util["state"], SH.RED) == 1 and min(util["avail"]) == 0          # the Sep 24 utility outage
    assert set(group(d, "generators")["avail"]) == {7}
    assert hours(group(d, "ups-HALL-A")["state"], SH.AMBER) == 4                    # UPS-A1 on bypass
    assert hours(group(d, "ups-HALL-B")["state"], SH.AMBER) == 3                    # UPS-B3 on bypass
    assert hours(group(d, "feeds-HALL-A")["state"], SH.RED) == 5                    # A07, both feeds lost
    assert hours(group(d, "chillers")["state"], SH.AMBER) == 22                     # 3 PMs and 2 compressor trips
    assert hours(group(d, "pumps-HALL-B")["state"], SH.AMBER) == 12
    assert hours(group(d, "fans-HALL-A")["state"], SH.AMBER) == 4                   # TW-A4 fan 6
    for k in ("cdu-HALL-A", "cdu-HALL-B", "walls-HALL-A", "fwpumps", "mups-HALL-A"):
        assert set(group(d, k)["state"]) == {SH.GREEN}, k


def test_a_unit_out_for_planned_work_counts(built):
    """CDU-B4's pump 2 was isolated for a filter change (PM-0011): the design is at N while it is out, even though the
    CDU's own redundancy status only reports failures."""
    sh, d = built
    h = sh.hour_of("2026-09-08T13:30:30Z")
    assert group(d, "pumps-HALL-B")["state"][h] == SH.AMBER
    assert any("CDU-B4: pump 2 isolated for planned work" in i["text"] for i in d["issues"] if i["from"] <= h <= i["to"])


def test_the_rack_power_loss(built):
    sh, d = built
    a07 = d["racks"]["A07"]
    lost = [h for h, s in enumerate(a07["state"]) if s == SH.RED]
    assert lost == list(range(sh.hour_of("2026-09-15T15:00:00Z"), sh.hour_of("2026-09-15T20:00:00Z")))
    assert all("both power feeds lost" in "; ".join(a07["why"][h]) for h in lost)
    assert sum("no GPUs reporting" in a07["why"][h] for h in lost) == 3


def test_hall_b_racks_are_off_until_installed_and_commissioning_until_handoff(built):
    _, d = built
    b01 = d["racks"]["B01"]
    assert all(s == SH.OFF for s in b01["state"][:b01["first"]])
    assert b01["first"] < b01["handoff"]
    assert all("commissioning" in "; ".join(w) for w in b01["why"][b01["first"]:b01["handoff"]])
    assert all(s == SH.OFF for s in d["racks"]["B32"]["state"])


def test_no_composite_score_and_states_from_thresholds(built):
    _, d = built
    assert not any(k for k in d if "score" in k)
    cfg = SH.load_config()
    assert cfg["thresholds"]["ups"]["load_amber_pct"] == 75.0                     # 4 make 3
    assert d["site_state"] == [max(d["family_state"][f][h] for f, _, _ in SH.FAMILIES) for h in range(d["hours"])]


def test_issue_spans_cover_exactly_the_hours(built):
    _, d = built
    for i in d["issues"]:
        assert 0 <= i["from"] <= i["to"] < d["hours"]
        fam = d["family_state"][i["family"]]
        assert all(fam[h] >= i["state"] for h in range(i["from"], i["to"] + 1))


def test_page_data_round_trips(built):
    _, d = built
    p = SH.page_data(d)
    assert SH.unrle(p["groups"][0]["avail"]) == d["groups"][0]["avail"]
    assert SH.unrle(p["racks"]["A07"]["state"]) == d["racks"]["A07"]["state"]
    assert len(json.dumps(p, separators=(",", ":"))) < 260_000


def test_report_is_current():
    f = render_telemetry.prepare_site()
    assert render_telemetry.OUT_SITE.read_text(encoding="utf-8") == render_telemetry.site_markdown(f)
