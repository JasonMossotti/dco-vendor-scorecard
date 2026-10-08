"""GPU health layer and review: consistent with the month's records, the planted cases are found, the page works."""

import filecmp
import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard import gpu_health as H
from scorecard.synthetic import gpu_health as G

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
LAYER = ROOT / "data" / "gpu_health"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_gpu_health  # noqa: E402
import render_gpu_health  # noqa: E402


@pytest.fixture(scope="module")
def data():
    return H.load(LAYER, SAMPLE)


@pytest.fixture(scope="module")
def res(data):
    return H.analyse(data)


def _jsonl(rel):
    return [json.loads(x) for x in (SAMPLE / rel).read_text(encoding="utf-8").splitlines() if x.strip()]


def test_committed_layer_is_current(tmp_path):
    generate_gpu_health.generate(tmp_path)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            rel = f.relative_to(tmp_path)
            assert filecmp.cmp(f, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_gpu_health.py"


def test_report_is_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_gpu_health.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_layer_reads_the_sample_and_never_writes_it():
    before = {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    a = G.GpuHealthLayer(SAMPLE, window["seed"]).run(excursion=False)
    b = G.GpuHealthLayer(SAMPLE, window["seed"]).run(excursion=False)
    assert a == b
    assert before == {p: p.stat().st_mtime_ns for p in SAMPLE.rglob("*") if p.is_file()}
    assert ':gpu-health"' in inspect.getsource(G.GpuHealthLayer.__init__), "its own random stream"


def test_every_xid_appears_as_a_watch_on_the_same_gpu(data):
    """Nothing contradicts the records already shown: each DCGM XID is a watch at the same time, GPU, and tray."""
    cfg = G.load_config()
    watches = {(w["opened"], w["host"], w["gpu"], w["tray_serial"], w["xid"]): w for w in data.watches if w["xid"]}
    xids = _jsonl("telemetry/dcgm_xid_events.jsonl")
    assert len(watches) == len(xids)
    for e in xids:
        w = watches[(e["timestamp"], e["host"], e["gpu_index"], e["tray_serial"], e["xid"])]
        assert [w["system"], w["result"]] == cfg["xid_watch"][e["xid"]]
        assert w["cleared"] is None or w["cleared"] > w["opened"]


def test_watches_clear_at_return_to_service_or_tray_swap(data):
    rts = {(e["node"], e["timestamp"]) for e in _jsonl("telemetry/scheduler_node_states.jsonl")
           if e["reason"] == "returned to service"}
    swaps = {(i["host"], i["observed_at"]) for i in _jsonl("telemetry/redfish_inventory_changes.jsonl") if i["property"] == "SerialNumber"}
    for w in data.watches:
        if w["xid"] and w["cleared"]:
            assert (w["host"], w["cleared"]) in rts | swaps, w


def test_counters_follow_the_installed_tray(data):
    """A replaced tray's counters stop at the swap; the new tray's start from it."""
    topo = json.loads((SAMPLE / "site" / "topology.json").read_text(encoding="utf-8"))
    initial = {c["host"]: c["serial"] for r in topo["racks"] for c in r["compute_trays"]}
    installed = {}
    for i in _jsonl("telemetry/redfish_inventory_changes.jsonl"):
        if i["property"] == "SerialNumber" and i["host"]:
            installed.setdefault(i["host"], {initial[i["host"]]}).add(i["new_value"])
    for r in data.counters:
        assert r["tray_serial"] in installed.get(r["host"], {initial[r["host"]]}), r


def test_hall_b_reports_from_power_on(data):
    first = {}
    for r in data.racks:
        first.setdefault(r["rack"], r["date"])
    assert first["A01"] == "2026-08-31"
    assert first["B01"] == "2026-09-05", "B01 powered on 2026-09-05 (M4)"
    assert "B20" not in first, "racks not yet powered on do not report"


def test_cdu_stayed_in_band_all_month(data):
    """OT-CSL-03 is 100% on the sample: no hour leaves the rack band, pump trips included."""
    cfg = G.load_config()
    assert not [r for r in data.cdu if H._out_of_band(cfg, r)]
    trips = [r for r in data.cdu if r["flow_lpm"] - r["flow_min_lpm"] > 150]
    assert {r["cdu"] for r in trips} == {"CDU-B3", "CDU-A2"}, "a dip at each pump trip"


def test_sample_findings(res):
    kinds = [f.type for f in res.findings]
    assert kinds == ["watch_list", "rts_pending", "rts_pending", "hot_tray"]
    assert all(f.party == "IT Partner" for f in res.findings)
    pend = {p["host"]: p for p in res.pending}
    assert pend["a31-ct11"]["ticket"] == "INC3100085" and pend["a31-ct11"]["cleared"] is None
    assert pend["a22-ct07"]["ticket"] == "INC3100204", "the phantom fix: no reset, so the remap stayed pending"
    assert pend["a22-ct07"]["cleared"] == "2026-09-07T03:40:05Z", "until the tray was replaced"
    assert res.thermal["landlord"] == []
    assert all(c["in_band"] and c["slowdown_gpus"] == 0 for c in res.thermal["cooling_events"])


def test_early_warning_comes_a_day_ahead(res):
    lead = G.load_config()["checks"]["lead_hours"]
    warned = [m for m in res.memory if m["warned"]]
    assert len(res.memory) == 10 and len(warned) == 3
    assert all(m["lead_h"] >= lead for m in warned)


def test_the_checks_never_read_the_answer_key():
    for fn in (H.analyse, H.early_warning, H.memory_xids, H.rts_pending, H.thermal, H.cooling_events, H.grid):
        assert ".key" not in inspect.getsource(fn), fn.__name__


def test_sample_self_check(res, data):
    ev = H.evaluate(res, data.key)
    assert (ev.planted, ev.detected, ev.false_positives) == (7, 7, [])


def test_headline_results_unchanged():
    import render_hub
    f = render_hub.facts()
    assert (f["it"]["defaults"], f["it"]["credits"], f["ll"]["credits"]) == (4, 188700, 106200)


def test_robustness_small_sample(capsys):
    assert render_gpu_health.robustness(3) == 0, capsys.readouterr().out


def test_interactive_page_builds_and_works(tmp_path):
    out = tmp_path / "gpu.html"
    html = render_gpu_health.html_page()
    assert "__DATA__" not in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    out.write_text(html, encoding="utf-8")
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "gpu_health_page.cjs", str(out)], capture_output=True, text=True, cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
