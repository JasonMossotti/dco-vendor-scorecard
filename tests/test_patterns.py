"""Failure pattern review: the history is current and separate, the analysis finds what was planted and nothing else,
and the written judgment matches the facts."""

import filecmp
import inspect
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scorecard import patterns as P
from scorecard.synthetic.generator import FIRST_NAMES, LAST_NAMES
from scorecard.synthetic.history import write_history

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "history"
SAMPLE = ROOT / "data" / "sample"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_history  # noqa: E402
import render_patterns  # noqa: E402

NUMBER = re.compile(r"(?<![\w.\-])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w\-])")


@pytest.fixture(scope="module")
def review():
    return render_patterns.prepare()


@pytest.fixture(scope="module")
def lessons():
    return yaml.safe_load((ROOT / "patterns" / "lessons.yaml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- the history
def test_committed_history_is_current(tmp_path):
    write_history(generate_history.generate(), tmp_path)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            rel = f.relative_to(tmp_path)
            assert filecmp.cmp(f, HISTORY / rel, shallow=False), f"{rel} is stale; run scripts/generate_history.py"


def test_history_ends_where_the_sample_begins():
    hist = json.loads((HISTORY / "manifest.json").read_text(encoding="utf-8"))["window"]
    sample = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    assert hist["end"] == sample["start"]


def test_tray_serials_chain_into_the_sample():
    """The last tray installed in each slot during the history is the one the sample month starts with."""
    topo = json.loads((SAMPLE / "site" / "topology.json").read_text(encoding="utf-8"))
    now = {t["host"]: t["serial"] for r in topo["racks"] for t in r["compute_trays"]}
    tickets = json.loads((HISTORY / "vendor" / "tickets.json").read_text(encoding="utf-8"))
    last, first = {}, {}
    for t in sorted(tickets, key=lambda t: t["resolved_at"]):
        for part in t["parts_used"]:
            if part["part"] == "Compute tray":
                first.setdefault(part["location"], part["removed_serial"])
                last[part["location"]] = part["installed_serial"]
    assert last and all(now[h] == s for h, s in last.items())
    assert not set(first.values()) & set(now.values()), "a tray removed in the history is still installed in the sample"
    numbers = {t["number"] for t in tickets}
    sample = {t["number"] for t in json.loads((SAMPLE / "vendor" / "tickets.json").read_text(encoding="utf-8"))}
    assert not numbers & sample


def test_history_has_its_own_random_stream():
    """Changing the history seed changes the history, never the sample generator's state."""
    src = inspect.getsource(sys.modules["scorecard.synthetic.history"])
    assert 'random.Random(f"failure-history-' in src and "SiteGenerator" not in src


def test_analysis_never_reads_the_answer_key():
    assert "ground_truth" not in inspect.getsource(P.History) + inspect.getsource(P.build_review)


# --------------------------------------------------------------------------- the analysis
def test_statistics_helpers():
    assert P.binom_upper(0, 10, 0.3) == 1.0
    assert math.isclose(P.binom_upper(10, 10, 0.5), 0.5 ** 10)
    assert math.isclose(P.binom_upper(1, 5, 0.2), 1 - 0.8 ** 5)
    # Fisher one-sided, 3 of 3 against 0 of 3: 1 / C(6, 3)
    assert math.isclose(P.fisher_upper(3, 3, 0, 3), 1 / 20)


def test_committed_review_finds_the_planted_patterns_and_nothing_else(review):
    key = json.loads((HISTORY / "ground_truth" / "planted_patterns.json").read_text(encoding="utf-8"))
    s = P.score(review, key)
    assert s["found"] == s["planted"] == s["owner_ok"] == 3 and s["decoys_flagged"] == 0 and s["other_flags"] == []


def test_decoy_tops_the_ticket_league_but_is_not_a_pattern(review):
    key = json.loads((HISTORY / "ground_truth" / "planted_patterns.json").read_text(encoding="utf-8"))
    decoy = next(a for a in key if a["type"] == "decoy")["group"]
    assert review["league"][0]["rack"] == decoy and review["league"][0]["verdict"] != "pattern"


def test_cooling_pattern_is_the_landlords_and_stayed_under_the_alarm(review):
    p = next(p for p in review["patterns"] if p["evidence"]["kind"] == "cooling")
    e = p["evidence"]
    assert p["raci"]["accountable"] == "Landlord" and e["explained"] and e["below_alarm"]
    assert e["ended_by_filter_change"] and e["episode"]["from"] < e["ended_by_filter_change"] <= e["episode"]["to"]


def test_every_failure_has_its_repair_ticket(review):
    assert review["totals"]["failures"] == review["totals"]["matched"] == review["totals"]["tickets"]


def test_robustness_small_sample(tmp_path):
    """Five moved and resized histories: the lot and the CDU drift are always found, owners are right, decoys are not flagged."""
    for seed in range(1, 6):
        data = generate_history.generate(seed, vary=True)
        d = tmp_path / str(seed)
        write_history(data, d)
        r = P.build_review(P.History(d, render_patterns.TOPOLOGY, ROOT / "sla"))
        s = P.score(r, data["streams"]["ground_truth/planted_patterns.json"])
        assert not {"optic_lot", "cdu_drift"} & set(s["missed"]), (seed, s)
        assert s["owner_ok"] == s["found"] and s["decoys_flagged"] == 0, (seed, s)


# --------------------------------------------------------------------------- the judgment
def test_lessons_cover_every_pattern_and_watch_item(review, lessons):
    assert set(lessons["patterns"]) == {p["key"] for p in review["patterns"]}
    assert set(lessons["watch_rulings"]) == {w["key"] for w in review["watch"]}


NOT_FACTS = {"judgment", "facts_txt", "weekly", "cdu_weekly", "ruling", "first", "last"}   # text and series, not citable facts


def _numbers(obj) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in NOT_FACTS:
                out |= _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _numbers(v)
    elif isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        out |= {float(x) for x in re.findall(r"\d+(?:\.\d+)?", obj.replace(",", ""))}
    return out


def _unmatched(text: str, facts: set[float]) -> list[str]:
    bad = []
    for m in NUMBER.finditer(text):
        whole, frac = m.group(1).replace(",", ""), m.group(2) or ""
        places = len(frac) - 1 if frac else 0
        value = float(whole + frac)
        if not any(round(f, places) == value for f in facts):
            bad.append(m.group(0))
    return bad


def test_every_number_in_the_judgment_matches_a_fact(review, lessons):
    common = _numbers(review["window"]) | _numbers(review["method"]) | _numbers(review["totals"])
    every = common | _numbers(review["patterns"]) | _numbers(review["league"])
    for p in review["patterns"]:
        j = lessons["patterns"][p["key"]]
        facts = common | _numbers(p)
        for field in ("title", "root_cause", "cost", "lesson", "confidence"):
            assert not _unmatched(j[field], facts), (p["key"], field, _unmatched(j[field], facts))
    for w in review["watch"]:
        text = lessons["watch_rulings"][w["key"]]
        assert not _unmatched(text, common | _numbers(w)), (w["key"], _unmatched(text, common | _numbers(w)))
    for field in ("summary", "league_note"):
        assert not _unmatched(lessons[field], every), (field, _unmatched(lessons[field], every))


def test_standard_work_changes_cite_clauses_that_exist(lessons):
    for p in lessons["patterns"].values():
        for c in p["standard_changes"]:
            text = (ROOT / "sla" / f"{c['doc']}.yaml").read_text(encoding="utf-8")
            assert re.search(rf"id:\s*\"?{re.escape(c['ref'])}\"?\s*$", text, re.M), (c["doc"], c["ref"])


def test_no_individual_is_named(lessons):
    text = json.dumps(lessons)
    names = set(FIRST_NAMES) | set(LAST_NAMES)
    assert not [n for n in names if re.search(rf"\b{n}\b", text)]
    roles = set(lessons["authors"])
    assert all(a["owner"] in roles for p in lessons["patterns"].values() for a in p["actions"])


def test_action_statuses_are_dated_and_honest(review, lessons):
    as_of = lessons["status_as_of"]
    assert lessons["prepared"] <= lessons["review_meeting"] <= as_of
    assert lessons["prepared"] > review["window"]["end"][:10]
    for p in review["patterns"]:
        for a in lessons["patterns"][p["key"]]["actions"]:
            assert a["status"] in ("Not started", "In progress", "Complete"), a["id"]
            assert a["status"] == "Complete" or a["due"] > as_of, f"{a['id']} is overdue as of {as_of}"
        # A fix pattern's interim rule cannot be marked done while the next month's data shows the old fix in use.
        if p["followup"]:
            assert all(a["status"] != "Complete" for a in lessons["patterns"][p["key"]]["actions"])


# --------------------------------------------------------------------------- outputs
def test_report_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_patterns.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_weekly_pack_points_to_the_review_after_its_meeting():
    from scorecard.weekly import WeeklyData, build_all
    by = {w["id"]: w for w in build_all(WeeklyData(SAMPLE))}
    assert by["2026-W36"]["pattern_actions"] is None
    pa = by["2026-W37"]["pattern_actions"]
    assert pa["id"] == "FPR-2026-H1" and pa["open"] == 7 and pa["overdue"] == 0


def test_interactive_page_builds_and_works(tmp_path):
    out = tmp_path / "patterns.html"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "render_patterns.py"), "--html", str(out)], check=True, capture_output=True)
    html = out.read_text(encoding="utf-8")
    assert "__DATA__" not in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "patterns_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
