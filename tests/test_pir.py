"""Post-incident review: facts match the dataset exactly, and the written review agrees with the facts."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scorecard.pir import Dataset, build_index, build_review

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


@pytest.fixture(scope="module")
def ds():
    return Dataset(SAMPLE)


@pytest.fixture(scope="module")
def review():
    return yaml.safe_load((ROOT / "pir" / "reviews" / "PIR-2026-001.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def facts(ds, review):
    return build_review(ds, review["ref"])


def test_every_timeline_record_is_reproduced_exactly(facts):
    sources = {}
    for r in facts["timeline"]:
        if not r["record"]:
            continue
        path = SAMPLE / r["source"]
        if path not in sources:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".jsonl":
                sources[path] = [json.dumps(json.loads(x), sort_keys=True) for x in text.splitlines() if x.strip()]
            elif path.suffix == ".json":
                sources[path] = [json.dumps(x, sort_keys=True) for x in json.loads(text)]
            else:
                import csv
                sources[path] = [json.dumps(x, sort_keys=True) for x in csv.DictReader(path.open(encoding="utf-8"))]
        rec = json.loads(r["record"])
        assert any(rec.items() <= json.loads(line).items() for line in sources[path]), (r["source"], r["record"])


def test_facts_for_rack_a07(facts):
    assert (facts["ticket"], facts["work_order"], facts["mops"], facts["rack"]) == ("INC3900001", "WO-41023", ["MOP-310"], "A07")
    assert (facts["power_lost"], facts["handoff"], facts["rts"]) == ("2026-09-15T15:42:11Z", "2026-09-15T19:06:55Z", "2026-09-15T20:01:36Z")
    assert facts["attribution"]["owner"] == "Landlord" and facts["attribution"]["rules"] == ["FA-1", "FA-3"]
    assert facts["impact"]["gpus"] == 72 and facts["impact"]["duration"] == "4 h 19 min"
    assert facts["mop_overrun"]["overrun"] == "2 h 06 min"
    assert [f["id"] for f in facts["findings"]] == ["L-004"]


def test_work_order_and_ticket_resolve_to_the_same_incident(ds, facts):
    other = build_review(ds, "WO-41023")
    assert (other["ticket"], other["power_lost"], other["rts"]) == (facts["ticket"], facts["power_lost"], facts["rts"])


def test_written_review_agrees_with_the_facts(facts, review):
    """Every number a reader sees in the prose must match the data."""
    text = json.dumps(review)
    pl = review["plain_language"]["what_happened"]
    assert "4 hours 19 minutes" in pl and facts["impact"]["duration"] == "4 h 19 min"
    assert "10:42 a.m. Central" in pl and facts["timeline"][[r["t"] for r in facts["timeline"]].index(facts["power_lost"])]["local"].startswith("10:42")
    for t in (facts["power_lost"][11:19], facts["handoff"][11:19], facts["rts"][11:19], "19:22:05"):
        assert t + "Z" in review["summary_technical"], t
    assert facts["mop_overrun"]["overrun"] in text
    m = {x["measure"]: x for x in facts["metrics"]}
    assert m["Landlord acknowledge (P1 target 5 min)"]["elapsed"] == "3 min" and "acknowledged in 3 minutes" in text
    assert m["IT Partner acknowledge"]["elapsed"] == "2 min" and "acknowledged in 2 minutes" in text
    assert m["IT Partner validation, handoff to return to service (P1 target 4 h, FA-3)"]["elapsed"] == "55 min" and "55 minutes" in text
    assert facts["findings"][0]["id"] in review["severity"]["internal"]
    assert review["severity"]["osr_level"] == facts["osr_suggested"]["level"]


def test_review_is_blameless(review, facts):
    text = json.dumps(review)
    for person in (facts["people"]["landlord_engineer"], facts["people"]["it_technician"], "Lane Haddad"):
        assert person not in text, f"the review names {person}"
    for a in review["actions"]:
        assert all(a.get(k) for k in ("owner", "due", "priority", "success", "factor")), a["id"]
        assert a["factor"] in {f["id"] for f in review["factors"]}


def test_index_covers_every_p1_and_p2(ds):
    idx = build_index(ds)
    want = {t["number"] for t in ds.tickets if t["priority"] in ("P1", "P2")} | {w["wo"] for w in ds.work_orders if w["priority"] in ("P1", "P2")}
    assert set(idx) == want


def test_markdown_review_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_pir.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_interactive_page_builds_and_works(tmp_path):
    out = tmp_path / "pir.html"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "render_pir.py"), "--html", str(out)], check=True, capture_output=True)
    html = out.read_text(encoding="utf-8")
    assert "__DATA__" not in html and "INC3900001" in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "pir_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
