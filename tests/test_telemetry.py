"""GPU telemetry: in the exporter's published format, never contradicting the month's records, the page works."""

import filecmp
import hashlib
import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scorecard import telemetry as TM
from scorecard.synthetic import gpu_health as G
from scorecard.synthetic import telemetry as T

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
HEALTH = ROOT / "data" / "gpu_health"
LAYER = ROOT / "data" / "telemetry" / "gpu"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_telemetry  # noqa: E402
import render_telemetry  # noqa: E402


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    """One regeneration for the module: the committed tiers to a temp folder, the hourly tier to its usual place."""
    tmp = tmp_path_factory.mktemp("telemetry")
    before = {p: p.stat().st_mtime_ns for d in (SAMPLE, HEALTH) for p in d.rglob("*") if p.is_file()}
    man = generate_telemetry.generate(tmp / "gpu", generate_telemetry.HOURLY)
    after = {p: p.stat().st_mtime_ns for d in (SAMPLE, HEALTH) for p in d.rglob("*") if p.is_file()}
    return tmp / "gpu", man, before == after


@pytest.fixture(scope="module")
def tel(regenerated):
    return TM.load(LAYER, generate_telemetry.HOURLY, HEALTH, SAMPLE)


@pytest.fixture(scope="module")
def checks(tel):
    return TM.agreements(tel, T.load_config(), G.load_config())


def test_committed_tiers_are_current(regenerated):
    out, _man, _ = regenerated
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(LAYER) for p in LAYER.rglob("*") if p.is_file()), "a window was added or removed"
    for rel in files:
        assert filecmp.cmp(out / rel, LAYER / rel, shallow=False), f"{rel} is stale; run scripts/generate_telemetry.py"


def test_hourly_tier_matches_the_manifest_checksums(regenerated):
    man = json.loads((LAYER / "manifest.json").read_text(encoding="utf-8"))
    assert len(man["gpu_hourly"]) == len(man["racks"]) == 46
    for name, meta in man["gpu_hourly"].items():
        assert hashlib.sha256((generate_telemetry.HOURLY / name).read_bytes()).hexdigest() == meta["sha256"], name


def test_reads_the_records_and_never_writes_them(regenerated):
    assert regenerated[2], "data/sample and data/gpu_health are read, never written"
    src = inspect.getsource(T)
    assert '"telemetry", "gpu"' in src and ':telemetry:gpu:' in src, "its own random streams"


def test_report_is_current(regenerated):
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_telemetry.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_every_agreement_holds_on_the_sample(checks):
    assert [c.name for c in checks] == ["rack_peaks", "gpu_peaks", "memory", "xids", "drains", "dark", "thermal", "hall_b", "energy"]
    for c in checks:
        assert c.checked > 0 and not c.misses, (c.name, c.misses[:5])
    by = {c.name: c.checked for c in checks}
    assert by["rack_peaks"] == 1103 and by["xids"] == 41 and by["hall_b"] == 14


def test_the_checks_read_only_what_is_published():
    src = inspect.getsource(TM)
    assert "synthetic" not in src.split('"""', 2)[2] and "answer_key" not in src


def test_exporter_format(tel):
    cfg = T.load_config()
    assert all(f["name"].startswith(("DCGM_FI_DEV_", "DCGM_FI_PROF_")) and f["type"] in ("gauge", "counter") for f in cfg["fields"])
    assert set(cfg["collection"]["enabled_beyond_default"]) <= {f["name"] for f in cfg["fields"]}
    g = tel.gpu("a31-ct11", 0)
    lab = g["labels"][0]
    assert set(lab) - {"from", "to", "serial"} == {"gpu", "UUID", "pci_bus_id", "device", "modelName", "Hostname", "DCGM_FI_DRIVER_VERSION"}
    assert lab["modelName"] == "NVIDIA GB200" and lab["device"] == "nvidia0" and lab["UUID"].startswith("GPU-")
    assert len(g["labels"]) == 2 and g["labels"][0]["UUID"] != g["labels"][1]["UUID"], "a new tray brings new GPUs and new series"
    assert tel.gpu("b03-ct01", 0)["labels"][0]["modelName"] == "NVIDIA GB300"
    assert all(isinstance(v, int) for v in g["temp"] if v is not None), "whole degrees, as the exporter publishes"
    last = g["last"]
    assert set(last) - {"at"} == {f["name"] for f in cfg["fields"]}


def test_the_rack_power_loss_is_a_gap_not_zeros(tel):
    dark = [x for x in tel.gaps if x["reason"] == "rack input power lost"]
    assert len(dark) == 18 and {x["host"][:3] for x in dark} == {"a07"}
    g = tel.gpu("a07-ct06", 0)
    n = TM.unrle(g["n"])
    h = int((T.parse("2026-09-15T17:00:00Z") - tel.start).total_seconds() // 3600)
    assert n[h] == 0 and g["util"][h] is None and g["power"][h] is None


def test_hall_b_runs_burn_in_then_production_under_its_power_cap(tel):
    halls = render_telemetry.summarize(tel, T.load_config())
    assert halls["HALL-A"]["at_cap_pct"] == 0 and halls["HALL-B"]["at_cap_pct"] > 30
    assert halls["HALL-B"]["power_limit_w"] < halls["HALL-B"]["power_max_w"]


def test_robustness_one_month(capsys):
    assert render_telemetry.robustness(1) == 0, capsys.readouterr().out


def test_interactive_page_builds_and_works(tmp_path, regenerated):
    out = tmp_path / "telemetry"
    render_telemetry.write_site(out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "__DATA__" not in html and "</script" not in html.split('id="data"')[1].split("</script>")[0]
    assert (out / "data" / "racks.json").exists() and len(list((out / "data" / "gpu").glob("*.json"))) == 46
    node = shutil.which("node")
    if not node or subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, cwd=ROOT / "tests" / "js").returncode:
        pytest.skip("node and jsdom not installed (CI runs this check)")
    proc = subprocess.run([node, "telemetry_page.cjs", str(out / "index.html"), str(out)], capture_output=True, text=True,
                          cwd=ROOT / "tests" / "js")
    assert proc.returncode == 0, proc.stdout + proc.stderr
