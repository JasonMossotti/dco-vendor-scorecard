#!/usr/bin/env python3
"""Generate the telemetry layers for the committed sample: data/telemetry/gpu/ and data/telemetry/cdu/.

One-minute GPU samples in the published format of NVIDIA's open-source DCGM exporter, shaped to agree with
every record already in data/sample and data/gpu_health. Own random stream; those folders are read, never
written. The committed tiers (rack hourly, gaps, minute windows around events, manifest) go to
data/telemetry/gpu/; the per-GPU hourly tier (about 36 MB) goes to build/telemetry/gpu_hourly/, which is not
committed: scripts/build_site.py publishes it, and the manifest holds each file's SHA-256.

The CDU layer follows in the same pass (it takes each rack's minute-by-minute heat from the GPU telemetry):
one-minute DMTF Redfish readings for every CDU, shaped to agree with every CDU record and the energy meters.
Its committed tiers go to data/telemetry/cdu/ and its one-minute files to build/telemetry/cdu_minutes/.

The energy meters are rebuilt between the two (data/energy/: each hall's UPS output is its racks' power from the
GPU telemetry), and the power layer comes last: one-minute UPS, busway, tap-off, and generator readings in the
manufacturers' published SNMP and Modbus point maps, shaped to agree with the racks, the meters, and every
power record. Committed tiers go to data/telemetry/power/, the one-minute files to build/telemetry/power_minutes/.

Usage:
    python scripts/generate_telemetry.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.telemetry import GpuTelemetry, Published, write_telemetry  # noqa: E402
from scorecard.synthetic.energy import EnergyLayer, history, write_energy  # noqa: E402
from scorecard.synthetic.telemetry_cdu import CduTelemetry, write_cdu  # noqa: E402
from scorecard.synthetic.telemetry_power import PowerTelemetry, write_power  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
HEALTH = ROOT / "data" / "gpu_health"
OUT = ROOT / "data" / "telemetry" / "gpu"
HOURLY = ROOT / "build" / "telemetry" / "gpu_hourly"
OUT_CDU = ROOT / "data" / "telemetry" / "cdu"
MINUTES_CDU = ROOT / "build" / "telemetry" / "cdu_minutes"
OUT_POWER = ROOT / "data" / "telemetry" / "power"
MINUTES_POWER = ROOT / "build" / "telemetry" / "power_minutes"
ENERGY = ROOT / "data" / "energy"
HISTORY = ROOT / "data" / "history"


def generate(dest: Path = OUT, hourly: Path | None = HOURLY) -> dict:
    """GPU telemetry to dest, the energy meters (to data/energy, or beside dest when dest is elsewhere), then CDU
    and power telemetry to the sibling cdu/ and power/ folders (and their one-minute files beside the hourly ones).
    Returns the GPU manifest, with the CDU and power manifests under "cdu" and "power"."""
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    pub = Published(GpuTelemetry(SAMPLE, HEALTH, window["seed"])).run()
    if pub.conflicts:
        raise SystemExit("records disagree with each other: " + "; ".join(pub.conflicts))
    man = write_telemetry(pub, dest, "data/sample + data/gpu_health", hourly)
    energy = ENERGY if Path(dest) == OUT else Path(dest).parent / "energy"
    el = EnergyLayer(SAMPLE, window["seed"], rack_hourly=Path(dest) / "rack_hourly.csv")
    eout = el.run(report_error=el.cfg["plants"]["sample_report_error"])
    write_energy(eout, energy, history(eout["meters"], el.start, window["seed"]), "data/sample")
    layer = CduTelemetry(pub.tel, pub, energy, HISTORY)
    cdus = layer.run()
    if layer.conflicts:
        raise SystemExit("CDU records disagree with each other: " + "; ".join(layer.conflicts))
    build = Path(hourly).parent if hourly is not None else None
    man["cdu"] = write_cdu(layer, cdus, Path(dest).parent / "cdu", "data/sample + data/gpu_health + data/energy + GPU telemetry",
                           build / "cdu_minutes" if build else None)
    power = PowerTelemetry(pub.tel, pub, energy)
    pout = power.run()
    if power.conflicts:
        raise SystemExit("power records disagree with each other: " + "; ".join(power.conflicts))
    man["power"] = write_power(power, pout, Path(dest).parent / "power",
                               "data/sample + data/energy + GPU telemetry", build / "power_minutes" if build else None)
    return man


def hourly_current(dest: Path = OUT, hourly: Path = HOURLY) -> bool:
    """True when every per-GPU hourly file in hourly/ matches the committed manifest."""
    import hashlib
    pairs = [(dest / "manifest.json", "gpu_hourly", hourly),
             (dest.parent / "cdu" / "manifest.json", "minutes", hourly.parent / "cdu_minutes"),
             (dest.parent / "power" / "manifest.json", "minutes", hourly.parent / "power_minutes")]
    for mpath, key, folder in pairs:
        man = json.loads(mpath.read_text(encoding="utf-8"))
        for name, meta in man[key].items():
            p = folder / name
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != meta["sha256"]:
                return False
    return True


def ensure_hourly(hourly: Path = HOURLY) -> Path:
    """Build the per-GPU hourly tier if it is missing or stale; refuse if the rebuild disagrees with the manifest."""
    if not hourly_current(OUT, hourly):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            man = generate(Path(tmp) / "gpu", hourly)
        committed = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
        committed_cdu = json.loads((OUT_CDU / "manifest.json").read_text(encoding="utf-8"))
        committed_power = json.loads((OUT_POWER / "manifest.json").read_text(encoding="utf-8"))
        if (man["gpu_hourly"] != committed["gpu_hourly"] or man["cdu"]["minutes"] != committed_cdu["minutes"]
                or man["power"]["minutes"] != committed_power["minutes"]):
            raise SystemExit("data/telemetry is out of date. Run: python scripts/generate_telemetry.py")
    return hourly


def main() -> int:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    t = time.time()
    man = generate()
    print(f"GPU telemetry for {window['start']} to {window['end']} -> {OUT.relative_to(ROOT)} ({time.time() - t:.0f} s)")
    print(f"  {man['gpus']:,} GPUs in {len(man['racks'])} racks")
    for rel, n in man["files"].items():
        print(f"  {rel:<28} {n:>6}")
    print(f"  per-GPU hourly (not committed) -> {HOURLY.relative_to(ROOT)}: "
          f"{sum(m['bytes'] for m in man['gpu_hourly'].values()) / 1e6:.1f} MB")
    c = man["cdu"]
    print(f"CDU telemetry -> {OUT_CDU.relative_to(ROOT)}: {len(c['cdus'])} CDUs")
    for rel, n in c["files"].items():
        print(f"  {rel:<28} {n:>6}")
    print(f"  one-minute readings (not committed) -> {MINUTES_CDU.relative_to(ROOT)}: "
          f"{sum(m['bytes'] for m in c['minutes'].values()) / 1e6:.1f} MB")
    print(f"Energy meters rebuilt from rack power -> {ENERGY.relative_to(ROOT)}")
    p = man["power"]
    fam: dict[str, int] = {}
    for x in p["devices"].values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    print(f"Power telemetry -> {OUT_POWER.relative_to(ROOT)}: " + ", ".join(f"{n} {k}" for k, n in sorted(fam.items())))
    for rel, n in p["files"].items():
        print(f"  {rel:<28} {n:>6}")
    print(f"  one-minute readings (not committed) -> {MINUTES_POWER.relative_to(ROOT)}: "
          f"{sum(m['bytes'] for m in p['minutes'].values()) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
