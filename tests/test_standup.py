"""Daily operations standup (/ops/, the Operations tab's opening view): one page per day, computed from the records at
the standup, with a stated top-three rule, and seven days that add up to each week's pack."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

from scorecard import standup as SU
from scorecard.change_calendar import hm_local, parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_standup  # noqa: E402


@pytest.fixture(scope="module")
def s():
    return SU.Standup()


@pytest.fixture(scope="module")
def f(s):
    return SU.page_data(s)


def test_report_is_current(f):
    assert (ROOT / "reports" / "standup.md").read_text(encoding="utf-8") == render_standup.markdown(f)


def test_one_page_per_day_on_the_shift_handovers(f):
    days = f["days"]
    assert len(days) == 28 and days[0]["date"] == "2026-08-31" and days[-1]["date"] == "2026-09-27" and f["today"] == "2026-09-27"
    for a, b in zip(days, days[1:]):
        assert a["end"] == b["start"]                                   # the operations days tile the month
    d = days[0]
    assert d["start"] == f["window"]["start"] and days[-1]["end"] == f["window"]["end"]
    assert [hm_local(parse(d[k])) for k in ("start", "overnight_end", "standup", "end")] == ["19:00 CDT", "07:00 CDT", "07:30 CDT", "19:00 CDT"]


def test_every_week_adds_up_to_its_pack(f):
    """Incidents opened, findings raised, permits issued, and CSL-10 technician hours: seven days equal the week's pack."""
    assert f["reconcile"] == []
    assert list(f["weeks"]) == ["2026-W36", "2026-W37", "2026-W38", "2026-W39"]
    for w in f["weeks"].values():
        d, p = w["days"], w["pack"]
        assert d["days"] == 7 and (d["it_p12"], d["landlord_p12"], d["findings"], d["permits"]) == (p["it_p12"], p["landlord_p12"], p["findings"], p["permits"])
    assert sum(w["days"]["changes"] for w in f["weeks"].values()) == f["calendar_jobs"] == 30   # the Calendar's 33, less 3 deferred


def test_open_incidents_and_their_clocks(s, f):
    """An open P1 or P2 at the standup started before it and was restored after it; at risk means half its time used."""
    share = f["rule"]["at_risk_share"]
    seen = 0
    for d in f["days"]:
        S = parse(d["standup"])
        for i in d["incidents"]:
            seen += 1
            assert parse(i["t0"]) <= S
            assert i["used_min"] == round((S - parse(i["t0"])).total_seconds() / 60)
            assert i["at_risk"] == (i["used_min"] >= share * i["target_min"] - 0.5)
    assert seen > 0
    d = next(x for x in f["days"] if x["date"] == "2026-09-14")       # the A06 leak: P1, four hours to restore
    assert d["top3"][0]["rule"] == 1 and "FC-LEAK" in d["top3"][0]["text"] and "of 4 h used" in d["top3"][0]["text"]


def test_top_three_follows_the_rule(f):
    for d in f["days"]:
        r = [t["rule"] for t in d["top3"]]
        assert r == sorted(r) and len(r) <= 3
        risk = [i for i in d["incidents"] if i["at_risk"]]
        assert len([t for t in d["top3"] if t["rule"] == 1]) == min(3, len(risk))
        racks = [t["refs"] for t in d["top3"] if t["rule"] == 3]
        assert len(racks) == len({tuple(x) for x in racks})
        if len(r) < 3:                                                   # nothing that meets the rule was left out
            assert len(r) == len(risk) + len(d["redundancy"]) + len({x["rack"] for x in d["steps"] if x["critical"]})


def test_redundancy_matches_site_health(s, f):
    """A group reduced at the standup is reduced on Site health in the hour before it."""
    H = s.health
    for d in f["days"]:
        h = int((parse(d["standup"]) - parse(f["window"]["start"])).total_seconds() // 3600) - 1
        reduced = {g["key"] for g in H["groups"] if g["state"][h] > 0}
        assert {r["group"] for r in d["redundancy"]} == reduced
    sep16 = next(x for x in f["days"] if x["date"] == "2026-09-16")
    assert any("CH-05" in r["text"] for r in sep16["redundancy"])


def test_work_permits_spares_and_staffing(f):
    d = next(x for x in f["days"] if x["date"] == "2026-09-04")
    assert [j["id"] for j in d["work"]] == ["PM-0002", "MOP-308", "MOP-303"] and [c["id"] for c in d["conflicts"]] == ["CAL-1"]
    assert [p["permit"] for p in d["permits"]] == ["PTW-26001", "PTW-26002", "PTW-26003", "PTW-26004"]
    low = next(x for x in f["days"] if x["date"] == "2026-09-07")["spares"]
    assert {(x["where"], x["fru"]) for x in low} >= {("Storage spares shelf, Hall A", "NVMe SSD 30.72 TB (U.2)")}
    for d in f["days"]:
        night, day = d["staffing"]
        assert night["complete"] and not day["complete"] and night["shift"] == "night" and day["shift"] == "day"
        assert night["it"]["badged"] + len(night["it"]["missing"]) == night["it"]["rostered"]
        assert d["on_call"]["now"] and d["on_call"]["tonight"]


def test_on_call_follows_the_rota(f):
    by = {d["date"]: d["on_call"] for d in f["days"]}
    assert by["2026-09-01"]["now"]["primary"] == "Ops engineer 1" and by["2026-09-01"]["tonight"]["primary"] == "Ops engineer 3"
    assert by["2026-09-05"]["now"]["label"] == "Weekend on call" and by["2026-09-04"]["tonight"]["label"] == "Weekend on call"


def test_nothing_is_known_before_the_standup_that_happened_after(f):
    for d in f["days"]:
        S = parse(d["standup"])
        assert all(parse(r["at"]) < parse(d["overnight_end"]) for r in d["overnight"]["records"])
        for s in d["steps"]:
            assert not (s["done_before"] and s["done_today"])
        assert all(parse(x["known"]) < parse(d["end"]) for x in d["close"]["findings"]["list"])
        assert parse(d["standup"]) - parse(d["start"]) == timedelta(hours=12, minutes=30) and S


def test_robustness_small():
    assert render_standup.robustness(2) == 0
