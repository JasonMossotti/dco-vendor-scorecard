"""Agreements between the GPU telemetry and every record already written for the month.

The telemetry is synthetic, so its value rests on one property: it never contradicts the records the other
pages show. Each check below reads only what the telemetry publishes (``data/telemetry/gpu/`` and the per-GPU
hourly files built at publish time) and the existing records, never the generator's internals, and returns
how many cases it checked and which ones disagree.

1. rack_peaks: each rack's daily peak GPU and HBM temperature and trays reporting equal ``rack_daily.csv``
   (the exporter publishes whole degrees: the GPU Health layer's tenths, rounded half up).
2. gpu_peaks: each GPU with a counter row peaks at that row's temperature that day.
3. xids: every XID shows on the same GPU at the first sample at or after it.
4. drains: a drained node runs nothing (utilization 0) in every whole hour of the drain.
5. dark: a span with no samples has none, and a rack power loss starts at the first sample after the
   Landlord's recorded loss and ends within the boot time after the recorded restoration.
6. thermal: the GPU is at or above the slowdown temperature only inside a recorded episode, its SM clock is
   lower there, and the thermal violation time adds up to the episode's length.
7. memory: remapped rows and pending remaps at the end of each day, and corrected errors per day, equal
   ``gpu_counters.csv``.
8. hall_b: a Hall B rack has no samples before its power-on milestone.
9. energy: the GPUs never draw more than the UPS output in any hour (sample month only).
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

UTC = timezone.utc
MIN = timedelta(minutes=1)


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def half_up(x: float) -> int:
    return int(math.floor(x + 0.5 + 1e-9))


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _csv(p: Path) -> list[dict]:
    return list(csv.DictReader(p.open(encoding="utf-8"))) if p.exists() else []


def unrle(pairs: list[list]) -> list:
    out: list = []
    for v, n in pairs:
        out += [v] * n
    return out


@dataclass
class Check:
    name: str
    title: str
    checked: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.misses

    def __call__(self, good: bool, what: str) -> None:
        self.checked += 1
        if not good:
            self.misses.append(what)


@dataclass
class Telemetry:
    dir: Path
    hourly_dir: Path
    health: Path
    sample: Path
    manifest: dict
    rack_hourly: list[dict]
    gaps: list[dict]
    hourly: dict[str, dict]

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def end(self) -> datetime:
        return parse(self.manifest["window"]["end"])

    def window(self, name: str) -> dict:
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    def windows_for(self, host: str, t: datetime) -> Iterator[tuple[dict, int]]:
        """The window holding the sample at or after t on this host, and that sample's index."""
        for w in self.manifest["windows"]:
            if w["host"] != host:
                continue
            a = parse(w["from"])
            i = math.ceil((t - a).total_seconds() / 60 - 1e-9)
            if 0 <= i < w["minutes"]:
                yield self.window(w["file"]), i

    def gpu(self, host: str, gpu: int) -> dict | None:
        rack = host[:3].upper()
        for g in self.hourly.get(rack, {}).get("gpus", []):
            if g["host"] == host and g["gpu"] == gpu:
                return g
        return None


def load(tel_dir: str | Path, hourly_dir: str | Path, health_dir: str | Path, sample_dir: str | Path) -> Telemetry:
    d, hd = Path(tel_dir), Path(hourly_dir)
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    hourly = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(hd.glob("*.json"))}
    return Telemetry(d, hd, Path(health_dir), Path(sample_dir), man, _csv(d / "rack_hourly.csv"), _jsonl(d / "gaps.jsonl"), hourly)


def agreements(t: Telemetry, cfg: dict, health_cfg: dict) -> list[Check]:
    start = t.start
    hour_i = lambda ts: int((parse(ts) - start).total_seconds() // 3600)          # noqa: E731
    out: list[Check] = []
    slow = health_cfg["thermal"]["slowdown_c"]

    # ---- 1. rack peaks and trays reporting
    c = Check("rack_peaks", "Rack daily peak temperatures and trays reporting equal the GPU Health layer")
    by_day: dict[tuple[str, str], list[dict]] = {}
    for r in t.rack_hourly:
        by_day.setdefault((r["hour"][:10], r["rack"]), []).append(r)
    for rd in _csv(t.health / "rack_daily.csv"):
        rows = [r for r in by_day.get((rd["date"], rd["rack"]), []) if r["gpu_temp_max_c"] != ""]
        got = max((int(r["gpu_temp_max_c"]) for r in rows), default=None)
        hbm = max((int(r["hbm_temp_max_c"]) for r in rows), default=None)
        d0 = hour_i(rd["date"] + "T00:00:00Z")
        trays = {g["host"] for g in t.hourly.get(rd["rack"], {}).get("gpus", []) if any(unrle(g["n"])[d0:d0 + 24])}
        c(got == half_up(float(rd["gpu_temp_max_c"])) and hbm == half_up(float(rd["hbm_temp_max_c"]))
          and len(trays) == int(rd["trays_reporting"]),
          f"{rd['rack']} {rd['date']}: telemetry {got} °C / {hbm} °C, {len(trays)} trays; record {rd['gpu_temp_max_c']} / "
          f"{rd['hbm_temp_max_c']}, {rd['trays_reporting']} trays")
    out.append(c)

    # ---- 2. per-GPU peaks on counter days, 7. memory counters
    c2 = Check("gpu_peaks", "Each GPU with a counter row peaks at that row's temperature that day")
    c7 = Check("memory", "Remapped rows, pending remaps, and corrected errors equal the daily counters")
    for row in _csv(t.health / "gpu_counters.csv"):
        g = t.gpu(row["host"], int(row["gpu"]))
        if g is None:
            c2(False, f"{row['host']} GPU {row['gpu']}: no telemetry")
            continue
        d0 = hour_i(row["date"] + "T00:00:00Z")
        day_start, day_end = start + timedelta(hours=d0), start + timedelta(hours=d0 + 24)
        whole = [lab for lab in g["labels"] if parse(lab["from"]) <= day_start and parse(lab["to"]) >= day_end]
        if whole and whole[0]["serial"] == row["tray_serial"]:
            temps = [v for v in g["temp"][d0:d0 + 24] if v is not None]
            c2(max(temps, default=None) == half_up(float(row["gpu_temp_max_c"])),
               f"{row['host']} GPU {row['gpu']} {row['date']}: telemetry peak {max(temps, default=None)}, counter {row['gpu_temp_max_c']}")
            sbe = sum(unrle(g["sbe"])[d0:d0 + 24])
        else:
            sbe = None                      # the tray was swapped that day: the hourly slot holds two GPUs
        last = None
        # the day's state as the first sample at or after midnight sees it (the counter row is taken at 23:59:59)
        eod = day_end if day_end < t.end else t.end - MIN
        if not whole:
            sbe = None
        for ch in g["counters"]:
            if parse(ch[0]) <= eod:
                last = ch
        at_eod = next((lab["serial"] for lab in g["labels"] if parse(lab["from"]) <= eod < parse(lab["to"])), None)
        if last is not None and at_eod == row["tray_serial"]:
            c7(last[1] + last[2] == int(row["remapped_rows"]) and last[3] == int(row["remap_pending"])
               and (sbe is None or sbe == int(row["sbe_day"])),
               f"{row['host']} GPU {row['gpu']} {row['date']}: telemetry rows {last[1]}+{last[2]}, pending {last[3]}, "
               f"errors {sbe}; counter {row['remapped_rows']}, {row['remap_pending']}, {row['sbe_day']}")
    out += [c2, c7]

    # ---- 3. XIDs
    c = Check("xids", "Every XID shows on the same GPU at the first sample after it")
    for e in _jsonl(t.sample / "telemetry" / "dcgm_xid_events.jsonl"):
        ts = parse(e["timestamp"])
        hit = None
        for w, i in t.windows_for(e["host"], ts):
            gp = next(x for x in w["gpus"] if x["gpu"] == int(e["gpu_index"]))
            hit = unrle(gp["xid"])[i]
        c(hit == int(e["xid"]), f"{e['host']} GPU {e['gpu_index']} XID {e['xid']} at {e['timestamp']}: telemetry shows {hit}")
    out.append(c)

    # ---- 4. drains, 5. dark spans
    c4 = Check("drains", "A drained node runs nothing in each whole hour of the drain")
    c5 = Check("dark", "No samples while a GPU or tray is dark; rack power loss matches the Landlord's record")
    sched = _jsonl(t.sample / "telemetry" / "scheduler_node_states.jsonl")
    for i, e in enumerate(sched):
        if e["state"] not in ("drain", "down"):
            continue
        back = next((parse(x["timestamp"]) for x in sched[i + 1:] if x["node"] == e["node"] and x["state"] == "idle"), t.end)
        a = math.ceil((parse(e["timestamp"]) - start).total_seconds() / 3600)
        b = int((back - start).total_seconds() // 3600)
        for gi in range(4):
            g = t.gpu(e["node"], gi)
            if g is None:
                continue
            n = unrle(g["n"])
            bad = [h for h in range(a, b) if n[h] and g["util"][h] != 0]
            c4(not bad, f"{e['node']} GPU {gi}: utilization during the drain from {e['timestamp']} in {len(bad)} hours")
    fac = json.loads((t.sample / "ground_truth" / "facility_incidents.json").read_text(encoding="utf-8")) \
        if (t.sample / "ground_truth" / "facility_incidents.json").exists() else []
    lo_b, hi_b = cfg["boot_min"]
    for gp in t.gaps:
        a, b = parse(gp["from"]), parse(gp["to"])
        ha, hb = math.ceil((a - start).total_seconds() / 3600), int((b - start).total_seconds() // 3600)
        gpus = [gp["gpu"]] if gp["gpu"] is not None else range(4)
        for gi in gpus:
            g = t.gpu(gp["host"], gi)
            n = unrle(g["n"]) if g else []
            c5(bool(g) and not any(n[h] for h in range(ha, hb)), f"{gp['host']} GPU {gi}: samples inside the gap {gp['from']} to {gp['to']}")
        if gp["reason"] == "rack input power lost":
            inc = next((f for f in fac if f.get("rack_capacity_lost") and f["unit"] == f"Rack {gp['host'][:3].upper()}"
                        and abs((parse(f["t0"]) - a).total_seconds()) < 120), None)
            ok = inc is not None and 0 <= (a - parse(inc["t0"])).total_seconds() < 60 \
                and lo_b * 60 - 60 <= (b - parse(inc["restored_at"])).total_seconds() <= hi_b * 60 + 60
            c5(ok, f"{gp['host']}: dark {gp['from']} to {gp['to']} vs the Landlord's loss and restoration")
    out += [c4, c5]

    # ---- 6. thermal episodes, inside the minute windows
    c = Check("thermal", "Slowdown temperature only inside recorded episodes, with a lower clock and matching violation time")
    eps = _jsonl(t.health / "thermal_episodes.jsonl")
    by_gpu: dict[tuple[str, int], list[tuple[datetime, datetime]]] = {}
    for e in sorted(eps, key=lambda e: e["start"]):     # overlapping episodes on one GPU are one throttled span
        spans = by_gpu.setdefault((e["host"], int(e["gpu"])), [])
        s, f = parse(e["start"]), parse(e["end"])
        if spans and s <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], f))
        else:
            spans.append((s, f))
    for w in t.manifest["windows"]:
        win = t.window(w["file"])
        a = parse(win["from"])
        for gp in win["gpus"]:
            spans = by_gpu.get((win["host"], gp["gpu"]), [])
            th = unrle(gp["thermal_s"])
            for i, v in enumerate(gp["temp"]):
                if v is None:
                    continue
                ts = a + i * MIN
                inside = any(s <= ts <= e for s, e in spans)
                # whole degrees: inside an episode at least the slowdown temperature, outside never above it
                c(v >= half_up(slow) if inside else v <= half_up(slow), f"{win['host']} GPU {gp['gpu']} {ts:%Y-%m-%dT%H:%MZ}: {v} °C, "
                  f"{'inside' if inside else 'outside'} an episode")
            # episodes whose samples share a minute are compared together: a sample reports the throttled
            # time since the previous one, which can hold the end of one episode and the start of the next
            clusters: list[list[tuple[datetime, datetime]]] = []
            for s, e in spans:
                i0 = math.ceil((s - a).total_seconds() / 60 - 1e-9)
                if clusters and i0 <= math.ceil((clusters[-1][-1][1] - a).total_seconds() / 60 - 1e-9):
                    clusters[-1].append((s, e))
                else:
                    clusters.append([(s, e)])
            for cl in clusters:
                s, e = cl[0][0], cl[-1][1]
                if a <= s and e + MIN <= a + win["minutes"] * MIN:
                    i0 = math.ceil((s - a).total_seconds() / 60 - 1e-9)
                    i1 = math.ceil((e - a).total_seconds() / 60 - 1e-9)
                    secs = sum(x or 0 for x in th[i0:i1 + 1])
                    dur = sum((f - b).total_seconds() for b, f in cl)
                    clocks = [x for x in gp["clock"][i0:i1] if x is not None]
                    before = [x for k, (x, u) in enumerate(zip(gp["clock"], gp["util"])) if max(0, i0 - 30) <= k < i0 and x and u and u > 50
                              and not any(s2 <= a + k * MIN <= e2 + MIN for s2, e2 in spans)]
                    lower = not clocks or not before or max(clocks) < min(before)
                    c(abs(secs - dur) <= 1 and lower,
                      f"{win['host']} GPU {gp['gpu']} episode {s:%Y-%m-%dT%H:%M:%SZ}: {secs} s of violation for "
                      f"{dur:.0f} s, clock lower: {lower}")
    out.append(c)

    # ---- 8. Hall B reports from power-on
    c = Check("hall_b", "A Hall B rack has no samples before its power-on milestone")
    for m in _csv(t.sample / "vendor" / "deployment_milestones.csv"):
        if m["milestone"] != "M4" or m["rack"] not in t.hourly:
            continue
        on = parse(m["reported_complete_at"]) if m["reported_complete_at"] else t.end
        h = int((on - start).total_seconds() // 3600)
        early = [g["host"] for g in t.hourly[m["rack"]]["gpus"] if any(unrle(g["n"])[:max(0, h)])]
        c(not early, f"{m['rack']}: samples before power-on at {m['reported_complete_at']} on {len(early)} GPUs")
    out.append(c)

    # ---- 9. GPU energy within the metered UPS output (the sample month has meters)
    meters = t.sample.parent / "energy" / "meters_hourly.csv"
    if meters.exists() and t.sample.name == "sample":
        c = Check("energy", "GPU energy never exceeds the UPS output in any hour")
        gpu_kwh: dict[str, float] = {}
        for r in t.rack_hourly:
            gpu_kwh[r["hour"]] = gpu_kwh.get(r["hour"], 0.0) + float(r["power_kwh"])
        shares = []
        for r in _csv(meters):
            if r["hour"] in gpu_kwh:
                ups = float(r["ups_out_a_kwh"]) + float(r["ups_out_b_kwh"])
                shares.append(gpu_kwh[r["hour"]] / ups)
                c(gpu_kwh[r["hour"]] < ups, f"{r['hour']}: GPUs {gpu_kwh[r['hour']]:.0f} kWh, UPS output {ups:.0f} kWh")
        c.title += f" (GPU share of UPS output {min(shares):.0%} to {max(shares):.0%})" if shares else ""
        out.append(c)
    return out


def summary(checks: list[Check]) -> dict[str, Any]:
    return {c.name: {"title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks}
