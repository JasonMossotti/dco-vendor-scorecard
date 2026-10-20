#!/usr/bin/env python3
"""Generate the telemetry layers for the committed sample: data/telemetry/gpu/, cdu/, power/, and network/.

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

The mechanical layer comes last: every chiller, facility water pump, the loop header, every thermal wall and CRAH, in
the point names Vertiv publishes for its iCOM controllers over BACnet, splitting the energy meters into each machine and
shaped to agree with every mechanical record. Committed tiers go to data/telemetry/mechanical/, the one-minute files to
build/telemetry/mechanical_minutes/. The energy meters' mechanical UPS columns follow the same thermal-wall model and the
CDUs' own draw, so the meters are built in two passes around the CDU telemetry (energy.follow_devices).

The network layer follows the power layer: every back-end InfiniBand leaf port under the UFM Telemetry and IBTA
counter names, the leaf chassis, and the NVLink switch trays under NMX-T names, shaped to agree with every fabric
event, optic ticket, the device directory, and the GPU telemetry. Committed tiers go to data/telemetry/network/,
the per-port and per-tray hourly files to build/telemetry/network_hourly/.

The management network layer reads only the sample: every BMC's answers to the Telemetry of Record's Redfish polls, the
management switches' IF-MIB counters and SNMP traps, and the console servers' session logs, shaped to agree with every
Redfish event, inventory change, NMX event, rack power loss, and Hall B handover. All of it is committed, in
data/telemetry/mgmt/ (own random stream).

The storage layer follows the management layer: every storage node's drive bays under the Redfish Drive names, the
storage and in-band Ethernet fabric's IF-MIB counters and traps, the clients' I/O stalls, and the IT Partner's drive and
optic tickets and custody handovers. A compute tray's storage ports follow the tray's host management port. All of it
is committed, in data/telemetry/storage/ (own random stream).

Usage:
    python scripts/generate_telemetry.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.synthetic.telemetry import GpuTelemetry, Published, write_telemetry  # noqa: E402
from scorecard.synthetic.energy import EnergyLayer, follow_devices, history, write_energy  # noqa: E402
from scorecard.synthetic.telemetry_cdu import CduTelemetry, write_cdu  # noqa: E402
from scorecard.synthetic.telemetry_power import PowerTelemetry, write_power  # noqa: E402
from scorecard.synthetic.telemetry_utility import UtilityTelemetry, write_utility  # noqa: E402
from scorecard.synthetic.telemetry_network import NetworkTelemetry, write_network  # noqa: E402
from scorecard.synthetic.telemetry_mechanical import MechanicalTelemetry, write_mechanical  # noqa: E402
from scorecard.synthetic.telemetry_mgmt import MgmtTelemetry, write_mgmt  # noqa: E402
from scorecard.synthetic.telemetry_storage import StorageTelemetry, write_storage  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
HEALTH = ROOT / "data" / "gpu_health"
OUT = ROOT / "data" / "telemetry" / "gpu"
HOURLY = ROOT / "build" / "telemetry" / "gpu_hourly"
OUT_CDU = ROOT / "data" / "telemetry" / "cdu"
MINUTES_CDU = ROOT / "build" / "telemetry" / "cdu_minutes"
OUT_POWER = ROOT / "data" / "telemetry" / "power"
MINUTES_POWER = ROOT / "build" / "telemetry" / "power_minutes"
OUT_UTIL = ROOT / "data" / "telemetry" / "utility"
MINUTES_UTIL = ROOT / "build" / "telemetry" / "utility_minutes"
OUT_NET = ROOT / "data" / "telemetry" / "network"
MINUTES_NET = ROOT / "build" / "telemetry" / "network_hourly"
OUT_MECH = ROOT / "data" / "telemetry" / "mechanical"
MINUTES_MECH = ROOT / "build" / "telemetry" / "mechanical_minutes"
OUT_MGMT = ROOT / "data" / "telemetry" / "mgmt"
OUT_STORAGE = ROOT / "data" / "telemetry" / "storage"
ENERGY = ROOT / "data" / "energy"
HISTORY = ROOT / "data" / "history"


def generate(dest: Path = OUT, hourly: Path | None = HOURLY) -> dict:
    """GPU telemetry to dest, the energy meters (to data/energy, or beside dest when dest is elsewhere), then CDU,
    power, and network telemetry to the sibling cdu/, power/, and network/ folders (and their publish-time files
    beside the hourly ones).
    Returns the GPU manifest, with the CDU, power, and network manifests under "cdu", "power", and "network"."""
    window = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))["window"]
    pub = Published(GpuTelemetry(SAMPLE, HEALTH, window["seed"])).run()
    if pub.conflicts:
        raise SystemExit("records disagree with each other: " + "; ".join(pub.conflicts))
    man = write_telemetry(pub, dest, "data/sample + data/gpu_health", hourly)
    energy = ENERGY if Path(dest) == OUT else Path(dest).parent / "energy"
    el = EnergyLayer(SAMPLE, window["seed"], rack_hourly=Path(dest) / "rack_hourly.csv")
    build = Path(hourly).parent if hourly is not None else None

    def cdu_build(edir: Path) -> SimpleNamespace:
        layer = CduTelemetry(pub.tel, pub, edir, HISTORY)
        cdus = layer.run()
        if layer.conflicts:
            raise SystemExit("CDU records disagree with each other: " + "; ".join(layer.conflicts))
        cman = write_cdu(layer, cdus, Path(dest).parent / "cdu", "data/sample + data/gpu_health + data/energy + GPU telemetry",
                         build / "cdu_minutes" if build else None)
        return SimpleNamespace(dir=Path(dest).parent / "cdu", manifest=cman)

    eout, cdu = follow_devices(el, el.cfg["plants"]["sample_report_error"], energy, cdu_build)
    write_energy(eout, energy, history(eout["meters"], el.start, window["seed"]), "data/sample")
    man["cdu"] = cdu.manifest
    power = PowerTelemetry(pub.tel, pub, energy)
    pout = power.run()
    if power.conflicts:
        raise SystemExit("power records disagree with each other: " + "; ".join(power.conflicts))
    man["power"] = write_power(power, pout, Path(dest).parent / "power",
                               "data/sample + data/energy + GPU telemetry", build / "power_minutes" if build else None)
    util = UtilityTelemetry(power, pout)
    man["utility"] = write_utility(util, util.run(), Path(dest).parent / "utility", "data/sample + data/energy + power telemetry",
                                   build / "utility_minutes" if build else None)
    net = NetworkTelemetry(pub.tel, pub)
    nout = net.run()
    if net.conflicts:
        raise SystemExit("network records disagree with each other: " + "; ".join(net.conflicts))
    man["network"] = write_network(net, nout, Path(dest).parent / "network", "data/sample + GPU telemetry",
                                   build / "network_hourly" if build else None)
    mech = MechanicalTelemetry(SAMPLE, window["seed"], energy, Path(dest).parent / "cdu")
    mout = mech.run()
    if mech.conflicts:
        raise SystemExit("mechanical records disagree with each other: " + "; ".join(mech.conflicts[:5]))
    man["mechanical"] = write_mechanical(mech, mout, Path(dest).parent / "mechanical", "data/sample + data/energy + CDU telemetry",
                                         build / "mechanical_minutes" if build else None)
    mg = MgmtTelemetry(SAMPLE, window["seed"])
    man["mgmt"] = write_mgmt(mg, mg.run(), Path(dest).parent / "mgmt", "data/sample + site/site.yaml")
    sg = StorageTelemetry(SAMPLE, window["seed"], Path(dest).parent / "mgmt")
    man["storage"] = write_storage(sg, sg.run(), Path(dest).parent / "storage", "data/sample + data/telemetry/mgmt + site/site.yaml")
    return man


def hourly_current(dest: Path = OUT, hourly: Path = HOURLY) -> bool:
    """True when every per-GPU hourly file in hourly/ matches the committed manifest."""
    import hashlib
    pairs = [(dest / "manifest.json", "gpu_hourly", hourly),
             (dest.parent / "cdu" / "manifest.json", "minutes", hourly.parent / "cdu_minutes"),
             (dest.parent / "power" / "manifest.json", "minutes", hourly.parent / "power_minutes"),
             (dest.parent / "utility" / "manifest.json", "minutes", hourly.parent / "utility_minutes"),
             (dest.parent / "network" / "manifest.json", "minutes", hourly.parent / "network_hourly"),
             (dest.parent / "mechanical" / "manifest.json", "minutes", hourly.parent / "mechanical_minutes")]
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
        committed_util = json.loads((OUT_UTIL / "manifest.json").read_text(encoding="utf-8"))
        committed_net = json.loads((OUT_NET / "manifest.json").read_text(encoding="utf-8"))
        committed_mech = json.loads((OUT_MECH / "manifest.json").read_text(encoding="utf-8"))
        if (man["gpu_hourly"] != committed["gpu_hourly"] or man["cdu"]["minutes"] != committed_cdu["minutes"]
                or man["power"]["minutes"] != committed_power["minutes"] or man["utility"]["minutes"] != committed_util["minutes"] or man["network"]["minutes"] != committed_net["minutes"]
                or man["mechanical"]["minutes"] != committed_mech["minutes"]):
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
    u = man["utility"]
    print(f"Utility mains and ride-through -> {OUT_UTIL.relative_to(ROOT)}: {len(u['mains'])} mains, {len(u['scopes'])} ride-through scopes")
    for rel, k in u["files"].items():
        print(f"  {rel:<28} {k:>6}")
    print(f"  one-minute readings (not committed) -> {MINUTES_UTIL.relative_to(ROOT)}: "
          f"{sum(m['bytes'] for m in u['minutes'].values()) / 1e6:.1f} MB")
    n = man["network"]
    fam = {}
    for x in n["devices"].values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    print(f"Network telemetry -> {OUT_NET.relative_to(ROOT)}: {fam.get('leaf', 0)} leaf switches, {fam.get('port', 0):,} links, "
          f"{fam.get('nvlink', 0)} NVLink switch trays")
    for rel, k in n["files"].items():
        print(f"  {rel:<28} {k:>6}")
    print(f"  hourly per port and tray (not committed) -> {MINUTES_NET.relative_to(ROOT)}: "
          f"{sum(m['bytes'] for m in n['minutes'].values()) / 1e6:.1f} MB")
    mm = man["mechanical"]
    fam = {}
    for x in mm["devices"].values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    print(f"Mechanical telemetry -> {OUT_MECH.relative_to(ROOT)}: {fam.get('chiller', 0)} chillers, {fam.get('pump', 0)} pumps, the loop, "
          f"{fam.get('wall', 0)} thermal walls, {fam.get('crah', 0)} CRAHs")
    for rel, k in mm["files"].items():
        print(f"  {rel:<28} {k:>6}")
    print(f"  one-minute readings (not committed) -> {MINUTES_MECH.relative_to(ROOT)}: "
          f"{sum(m['bytes'] for m in mm['minutes'].values()) / 1e6:.1f} MB")
    mg = man["mgmt"]
    fam = {}
    for x in mg["devices"].values():
        fam[x["family"]] = fam.get(x["family"], 0) + 1
    print(f"Management network telemetry -> {OUT_MGMT.relative_to(ROOT)}: {fam.get('bmc', 0):,} BMCs, {fam.get('rack', 0)} rack switches, "
          f"{fam.get('agg', 0)} aggregation switches, {fam.get('console', 0)} console servers")
    for rel, k in mg["files"].items():
        print(f"  {rel:<28} {k:>6}")
    print(f"  minute windows: {len(mg['windows'])}")
    st = man["storage"]
    print(f"Storage telemetry -> {OUT_STORAGE.relative_to(ROOT)}: {st['nodes']} storage nodes, {st['drives']} drives, {st['switches']} fabric "
          f"switches, {st['drive_events']} drive events, {st['tickets']} tickets, {st['stalls']} client stalls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
