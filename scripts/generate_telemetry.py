#!/usr/bin/env python3
"""Generate the GPU telemetry layer for the committed sample: data/telemetry/gpu/.

One-minute GPU samples in the published format of NVIDIA's open-source DCGM exporter, shaped to agree with
every record already in data/sample and data/gpu_health. Own random stream; those folders are read, never
written. The committed tiers (rack hourly, gaps, minute windows around events, manifest) go to
data/telemetry/gpu/; the per-GPU hourly tier (about 36 MB) goes to build/telemetry/gpu_hourly/, which is not
committed: scripts/build_site.py publishes it, and the manifest holds each file's SHA-256.

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

SAMPLE = ROOT / "data" / "sample"
HEALTH = ROOT / "data" / "gpu_health"
OUT = ROOT / "data" / "telemetry" / "gpu"
HOURLY = ROOT / "build" / "telemetry" / "gpu_hourly"


def generate(dest: Path = OUT, hourly: Path | None = HOURLY) -> dict:
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    pub = Published(GpuTelemetry(SAMPLE, HEALTH, window["seed"])).run()
    if pub.conflicts:
        raise SystemExit("records disagree with each other: " + "; ".join(pub.conflicts))
    return write_telemetry(pub, dest, "data/sample + data/gpu_health", hourly)


def hourly_current(dest: Path = OUT, hourly: Path = HOURLY) -> bool:
    """True when every per-GPU hourly file in hourly/ matches the committed manifest."""
    import hashlib
    man = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    for name, meta in man["gpu_hourly"].items():
        p = hourly / name
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
        if man["gpu_hourly"] != committed["gpu_hourly"]:
            raise SystemExit("data/telemetry/gpu is out of date. Run: python scripts/generate_telemetry.py")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
