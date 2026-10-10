"""Synthetic GPU telemetry for Site AUS-1, in the published format of NVIDIA's open-source DCGM exporter.

Portfolio demo; all data fictional. Runs on a finished month (the committed sample or a generated month)
after its GPU health layer, with its own random stream, and writes beside them, never into them.

Every GPU is sampled once a minute (the site's Prometheus scrape of the exporter). The series are shaped
to agree with every record already written for the month:

* the daily peak GPU and HBM temperatures of each rack (``gpu_health/rack_daily.csv``) and of each GPU
  with a counter row (``gpu_health/gpu_counters.csv``), published as whole degrees as the exporter does;
* every XID in ``telemetry/dcgm_xid_events.jsonl`` on the same GPU at the same minute;
* scheduler drains (the node idles until it returns to service) and rack power loss (no samples at all);
* every hardware thermal slowdown episode in ``gpu_health/thermal_episodes.jsonl`` (clock drop, thermal
  violation time, the GPU at or above the slowdown temperature only inside an episode);
* remapped rows, pending remaps, and corrected memory errors day by day;
* Hall B racks report from their power-on milestone and run burn-in until each node's validated handoff.

Published tiers (see ``write_telemetry``):

* ``rack_hourly.csv``: per rack per hour, committed.
* ``gaps.jsonl``: spans where a GPU or a whole tray reported nothing, committed.
* ``windows/<host>_<start>.json``: one-minute samples for the four GPUs of a tray around each event, committed.
* ``gpu_hourly/<rack>.json``: per GPU per hour, built at publish time (checksums in ``manifest.json``).

Settings and every assumption: ``config/telemetry.yaml``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from scorecard.synthetic.gpu_health import GpuHealthLayer, load_config as load_health_config

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "telemetry.yaml"
UTC = timezone.utc
MIN = timedelta(minutes=1)
PER_DAY = 1440
GPUS = 4

RACK_HOURLY_COLUMNS = ["hour", "rack", "hall", "gpus_reporting", "samples", "util_avg", "power_kwh", "gpu_temp_max_c",
                       "hbm_temp_max_c", "sm_clock_min_loaded_mhz", "thermal_violation_s", "power_violation_s", "xids",
                       "nodes_drained"]
# Per GPU per hour, built at publish time: mean utilization, mean power, peak temperature, lowest SM clock
# while loaded, samples in the hour, thermal and power violation seconds, corrected errors.
HOURLY_FIELDS = ["util", "power", "temp", "clock", "n", "thermal_s", "power_s", "sbe"]
# One-minute samples in a window: gauges and the cumulative counters.
WINDOW_FIELDS = ["util", "power", "temp", "clock", "fb", "tensor", "energy_mj", "sbe_total", "thermal_ns", "power_ns",
                 "remap_corr", "remap_unc", "pending", "xid"]


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def half_up(x: float) -> int:
    """The exporter publishes whole degrees; the GPU Health layer keeps tenths. Round half up."""
    return int(math.floor(x + 0.5 + 1e-9))


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _csv_rows(p: Path) -> list[dict]:
    return list(csv.DictReader(p.open(encoding="utf-8"))) if p.exists() else []


def gpu_uuid(serial: str, gpu: int) -> str:
    """A stable, obviously synthetic UUID per GPU: a new tray brings new GPUs and new series."""
    h = hashlib.sha256(f"{serial}:{gpu}".encode()).hexdigest()
    return f"GPU-{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def rack_input_w(n: Any, gpu_w: Any, rest: dict[str, float]) -> Any:
    """A rack's input power (W) at its tap-offs: its GPUs plus the rest of the rack, a fixed part per GPU
    reporting and a part that follows GPU power (``rack_rest`` in config/telemetry_cdu.yaml). The CDU heat
    balance, the energy meters, and the power telemetry all use this one model."""
    return n * rest["per_gpu_w"] + (1 + rest["per_gpu_watt"]) * gpu_w


def rack_input_kwh(row: dict[str, Any], rest: dict[str, float]) -> float:
    """The same for one row of rack_hourly.csv: ``samples`` GPU-minutes and ``power_kwh`` of GPU energy."""
    return int(row["samples"]) * rest["per_gpu_w"] / 60 / 1000 + (1 + rest["per_gpu_watt"]) * float(row["power_kwh"])


def _rng(seed: int, *parts: object) -> np.random.Generator:
    key = ":".join(str(p) for p in (seed, "telemetry", "gpu") + parts)
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


class GpuTelemetry:
    """Builds one-minute GPU series for a month, rack by rack."""

    def __init__(self, data_dir: str | Path, health_dir: str | Path, seed: int,
                 cfg: dict[str, Any] | None = None, health_cfg: dict[str, Any] | None = None):
        self.dir, self.hdir, self.seed = Path(data_dir), Path(health_dir), seed
        self.cfg = cfg or load_config()
        self.hcfg = health_cfg or load_health_config()
        self.layer = GpuHealthLayer(self.dir, seed, self.hcfg)     # topology, serials, reporting dates (no random draws)
        self.start, self.end = self.layer.start, self.layer.end
        self.M = int((self.end - self.start) / MIN)
        self.days = len(self.layer.days)
        self.trays = self.layer.trays()
        self.racks = sorted({t["rack"] for t in self.trays})
        h = self.hdir
        self.rack_daily = {(r["date"], r["rack"]): r for r in _csv_rows(h / "rack_daily.csv")}
        self.counters = _csv_rows(h / "gpu_counters.csv")
        self.episodes = _jsonl(h / "thermal_episodes.jsonl")
        self.watches = _jsonl(h / "watches.jsonl")
        self.key = json.loads((h / "answer_key.json").read_text(encoding="utf-8")) if (h / "answer_key.json").exists() else {}
        self.cdu = {}
        for r in _csv_rows(h / "cdu_hourly.csv"):
            self.cdu.setdefault(r["cdu"], {})[r["hour"]] = float(r["supply_c"])
        self.xids = self.layer.xids
        self.sched = self.layer.sched
        self.fac = json.loads((self.dir / "ground_truth" / "facility_incidents.json").read_text(encoding="utf-8")) \
            if (self.dir / "ground_truth" / "facility_incidents.json").exists() else []

    # ----------------------------------------------------------------- time helpers
    def m_of(self, t: datetime) -> int:
        """Index of the first sample at or after t."""
        return max(0, min(self.M, math.ceil((t - self.start).total_seconds() / 60 - 1e-9)))

    def t_of(self, m: int) -> datetime:
        return self.start + m * MIN

    def supply(self, cdu: str) -> np.ndarray:
        """CDU secondary supply per minute: the hourly means, interpolated between hour midpoints."""
        hours = [self.start + timedelta(hours=i) for i in range(self.M // 60)]
        vals = np.array([self.cdu[cdu].get(iso(h), self.hcfg["cdu"]["setpoint_c"]) for h in hours], dtype=float)
        mids = np.arange(len(hours)) * 60 + 30
        return np.interp(np.arange(self.M), mids, vals)

    # ----------------------------------------------------------------- what each node is doing
    def node_spans(self, host: str) -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str]]]:
        """(drains, dark): minute spans the node is out of the job, and spans with no samples at all."""
        drains, dark = [], []
        ev = [e for e in self.sched if e["node"] == host]
        for i, e in enumerate(ev):
            if e["state"] not in ("drain", "down"):
                continue
            t = parse(e["timestamp"])
            back = next((parse(x["timestamp"]) for x in ev[i + 1:] if x["state"] == "idle"), self.end)
            drains.append((self.m_of(t), self.m_of(back), e["reason"]))
            if e["state"] == "down":
                inc = next((f for f in self.fac if f.get("rack_capacity_lost") and f.get("unit") == f"Rack {host[:3].upper()}"
                            and abs((parse(f["t0"]) - t).total_seconds()) < 900), None)
                lost = parse(inc["t0"]) if inc else t - timedelta(seconds=15)
                r = _rng(self.seed, "boot", host, e["timestamp"])
                up = (parse(inc["restored_at"]) if inc else back - timedelta(minutes=20)) \
                    + timedelta(minutes=float(r.uniform(*self.cfg["boot_min"])))
                dark.append((self.m_of(lost), self.m_of(min(up, back)), "rack input power lost" if inc else e["reason"]))
        return drains, dark

    def handoff(self, host: str) -> datetime | None:
        return next((parse(e["timestamp"]) for e in self.sched if e["node"] == host and e["reason"] == "validated handoff"), None)

    # ----------------------------------------------------------------- the rack's job timeline
    def jobs(self, rack: str, begin: datetime, breaks: list[int], rng: random.Random) -> list[dict]:
        w = self.cfg["workload"]
        out, m, stop = [], self.m_of(begin), self.M
        breaks = sorted(set(b for b in breaks if b > self.m_of(begin)))
        while m < stop:
            hours = math.exp(rng.uniform(math.log(w["job_hours"][0]), math.log(w["job_hours"][1])))
            end = min(stop, m + int(hours * 60))
            nb = next((b for b in breaks if m < b < end), None)
            faulted = nb is not None
            if faulted:
                end = nb
            out.append({"start": m, "end": end, "util": rng.uniform(*w["utilization"]),
                        "every": rng.randint(*w["checkpoint_every_min"]), "ck": rng.randint(*w["checkpoint_min"]),
                        "ck_util": rng.uniform(*w["checkpoint_utilization"]), "phase": rng.randrange(0, 60),
                        "startup": rng.randint(*w["startup_min"]), "fb": rng.uniform(*w["fb_used_fraction"]),
                        "tensor": rng.uniform(*w["tensor_active_at_full"]), "demand": rng.random()})
            if faulted:
                m = end + rng.randint(*w["restart_after_fault_min"])
            elif rng.random() < w["long_gap_probability"]:
                m = end + int(rng.uniform(*w["long_gap_hours"]) * 60)
            else:
                m = end + rng.randint(*w["short_gap_min"])
        return out

    # ----------------------------------------------------------------- one rack, one minute at a time
    def rack(self, rack: str) -> dict[str, Any]:
        cfg, hc = self.cfg, self.hcfg
        trays = sorted([t for t in self.trays if t["rack"] == rack], key=lambda t: t["host"])
        hall, cdu, product = trays[0]["hall"], trays[0]["cdu"], trays[0]["product"]
        P = cfg["products"][product]
        G, M = len(trays) * GPUS, self.M
        rng = random.Random(f"{self.seed}:telemetry:gpu:{rack}")
        nrng = _rng(self.seed, rack)
        hosts = [t["host"] for t in trays]
        begin = trays[0]["from"]
        m0 = self.m_of(begin)

        avail = np.zeros((G, M), dtype=bool)
        avail[:, m0:] = True
        eligible = np.ones((G, M), dtype=bool)      # in the rack's production job when one runs
        burn = np.zeros((G, M), dtype=bool)
        gaps: list[dict] = []
        drains_by_host: dict[str, list] = {}
        breaks: list[int] = []
        for i, t in enumerate(trays):
            s = slice(i * GPUS, i * GPUS + GPUS)
            drains, dark = self.node_spans(t["host"])
            drains_by_host[t["host"]] = drains
            for a, b, _r in drains:
                eligible[s, a:b] = False
                breaks.append(a)
            for a, b, why in dark:
                avail[s, a:b] = False
                gaps.append({"host": t["host"], "gpu": None, "from": iso(self.t_of(a)), "to": iso(self.t_of(b)), "reason": why})
            if hall == "HALL-B":
                h = self.handoff(t["host"])
                hm = self.m_of(h) if h else M
                burn[s, m0:hm] = True
                eligible[s, :hm] = False
        # XIDs: the job fails; a GPU that falls off the bus stops answering until reset or replacement
        xid_by_gpu: dict[int, list[tuple[int, int, str]]] = {}
        for e in self.xids:
            if e["host"] not in hosts:
                continue
            g = hosts.index(e["host"]) * GPUS + int(e["gpu_index"])
            m = self.m_of(parse(e["timestamp"]))
            xid_by_gpu.setdefault(g, []).append((m, int(e["xid"]), e["tray_serial"]))
            breaks.append(m)
            if int(e["xid"]) in cfg["gone_xids"]:
                host = e["host"]
                back = next((b for a, b, _r in drains_by_host[host] if a <= m + 1 and b > m), M)
                b = min(M, max(m + 1, back - 10))
                avail[g, m + 1:b] = False
                gaps.append({"host": host, "gpu": int(e["gpu_index"]), "from": iso(self.t_of(m + 1)), "to": iso(self.t_of(b)),
                             "reason": f"XID {e['xid']}: GPU not answering"})
        rack_dark = [(self.m_of(parse(g["from"])), self.m_of(parse(g["to"]))) for g in gaps if g["gpu"] is None]
        breaks += [a for a, _b in rack_dark]

        # ---- utilization
        util = np.zeros((G, M), dtype=np.float32)
        fbf = np.zeros((G, M), dtype=np.float32)
        tens = np.zeros((G, M), dtype=np.float32)
        demand = np.zeros((G, M), dtype=np.float32)
        lo_d, hi_d = P["demand_w"]
        prod_from = begin if hall == "HALL-A" else (min((self.handoff(h) for h in hosts if self.handoff(h)), default=self.end))
        joblist = self.jobs(rack, prod_from, breaks, rng) if prod_from < self.end else []
        for j in joblist:
            a, b = j["start"], j["end"]
            if b <= a:
                continue
            idx = np.arange(a, b)
            u = np.full(b - a, j["util"], dtype=np.float32)
            u[((idx - a + j["phase"]) % j["every"]) < j["ck"]] = j["ck_util"]
            u[: j["startup"]] = np.linspace(30, 60, min(j["startup"], b - a), dtype=np.float32)[: b - a]
            el = eligible[:, a:b]
            util[:, a:b] = np.where(el, u, util[:, a:b])
            fbf[:, a:b] = np.where(el, j["fb"], fbf[:, a:b])
            tens[:, a:b] = np.where(el, j["tensor"] * u / 100.0, tens[:, a:b])
            demand[:, a:b] = np.where(el, lo_d + (hi_d - lo_d) * j["demand"], demand[:, a:b])
        bi = cfg["workload"]["burn_in"]
        cyc = (bi["stress_hours"] + bi["rest_hours"]) * 60
        on = ((np.arange(M) - m0) % cyc) < bi["stress_hours"] * 60
        bmask = burn & on[None, :]
        util[bmask] = bi["utilization"]
        fbf[bmask] = 0.5
        tens[bmask] = 0.8
        demand[bmask] = hi_d
        loaded = util > 0
        util = np.where(loaded, np.clip(util + nrng.normal(0, 1.2, (G, M)), 0, 100), 0).astype(np.float32)

        # ---- power, clocks, violations
        idle, limit = P["idle_w"], P["power_limit_w"]
        want = np.where(loaded, idle + (demand - idle) * _curve(util), idle) * (1 + nrng.normal(0, 0.012, (G, M)))
        power = np.minimum(want, limit).astype(np.float32)
        pviol = (want > limit) & loaded
        smax = P["sm_clock_max_mhz"]
        clock = np.where(util > 50, smax * (0.985 + nrng.normal(0, 0.004, (G, M))), cfg["idle_sm_clock_mhz"] + (smax - cfg["idle_sm_clock_mhz"]) * util / 50.0)
        clock = np.where(pviol, smax * np.sqrt(limit / np.maximum(want, 1)), clock).astype(np.float32)
        power_s = np.where(pviol, 60.0, 0.0).astype(np.float32)
        thermal_s = np.zeros((G, M), dtype=np.float32)

        # ---- thermal episodes from the GPU Health layer
        th, tc = hc["thermal"], cfg["thermal"]
        slow = th["slowdown_c"]
        ep_by_unit: dict[tuple[int, int], list[tuple[int, int, float]]] = {}
        spans_by_gpu: dict[int, list[tuple[datetime, datetime]]] = {}
        for e in self.episodes:
            if e["host"] not in hosts:
                continue
            g = hosts.index(e["host"]) * GPUS + int(e["gpu"])
            s_t, e_t = parse(e["start"]), parse(e["end"])
            a, b = self.m_of(s_t), int((e_t - self.start).total_seconds() // 60) + 1
            b = max(b, a + 1)
            ep_by_unit.setdefault((g, a // PER_DAY), []).append((a, b, float(e["gpu_temp_max_c"])))
            spans_by_gpu.setdefault(g, []).append((s_t, e_t))
            er = random.Random(f"{self.seed}:telemetry:ep:{e['host']}:{e['gpu']}:{e['start']}")
            cf, pf = er.uniform(*tc["slowdown_clock_fraction"]), er.uniform(*tc["slowdown_power_fraction"])
            clock[g, a:b] = smax * cf
            power[g, a:b] = np.minimum(power[g, a:b], limit) * pf
        for g, spans in spans_by_gpu.items():      # overlapping episodes count once, as the driver's counter does
            merged: list[list[datetime]] = []
            for s_t, e_t in sorted(spans):
                if merged and s_t <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], e_t)
                else:
                    merged.append([s_t, e_t])
            for s_t, e_t in merged:
                a, b = self.m_of(s_t), int((e_t - self.start).total_seconds() // 60) + 1
                for m in range(a, min(b + 1, M)):  # the sample at minute m reports the throttled time since the last one
                    ms, me = self.t_of(m - 1), self.t_of(m)
                    thermal_s[g, m] += max(0.0, (min(me, e_t) - max(ms, s_t)).total_seconds())

        # ---- temperature: CDU supply plus a rise that follows power
        sup = self.supply(cdu)
        over = th["gpu_over_supply_c"][product]
        heat = pd.DataFrame((power / limit).T).ewm(alpha=1 - math.exp(-1 / tc["tau_min"]), adjust=False).mean().to_numpy().T
        offs = nrng.normal(0, tc["gpu_offset_sd_c"], (G, 1))
        temp = sup[None, :] + over * heat + offs + nrng.normal(0, tc["sample_noise_c"], (G, M))
        hot = {h["host"]: h for h in self.key.get("hot_trays", [])}
        for i, t in enumerate(trays):
            if t["host"] in hot:
                k0 = self.m_of(parse(hot[t["host"]]["from"] + "T00:00:00Z"))
                rise = float(np.mean(hc["plants"]["hot_tray_rise_c"]))
                temp[i * GPUS:(i + 1) * GPUS, k0:] += rise * heat[i * GPUS:(i + 1) * GPUS, k0:]
        temp = np.where(avail, temp, np.nan)
        conflicts = self._pin(rack, trays, hosts, temp, sup, util, avail, ep_by_unit, product)

        # ---- memory counters, pending remaps, XID gauge
        serial_at = self._serials(trays, G)
        cnt = self._counters(hosts, trays, G, avail, serial_at)
        xid_g = np.zeros((G, M), dtype=np.int16)    # the last XID; a new tray brings new GPUs, which start at zero
        for g, lst in xid_by_gpu.items():
            for m, x, _s in sorted(lst):
                end = next((b for a, b, _s2 in serial_at[g]["spans"] if a <= m < b), M)
                xid_g[g, m:end] = x

        # ---- energy since boot, cumulative violation time
        e_step = np.where(avail, power * 60_000.0, 0.0)                      # mJ per minute
        energy = np.cumsum(e_step, axis=1)
        for g in range(G):
            boots = list(np.flatnonzero(avail[g, 1:] & ~avail[g, :-1]) + 1) + serial_at[g]["swaps"]
            for b in sorted(set(boots)):
                energy[g, b:] -= energy[g, b - 1]
        energy = energy + np.where(avail, 0.0, np.nan)
        return {"rack": rack, "hall": hall, "cdu": cdu, "product": product, "hosts": hosts, "trays": trays,
                "avail": avail, "util": util, "power": power, "temp": temp, "clock": clock, "fb": fbf * P["fb_total_mib"],
                "tensor": tens, "thermal_s": thermal_s, "power_s": power_s, "xid": xid_g, "energy": energy,
                "eligible": eligible, "burn": burn, "gaps": gaps, "serial_at": serial_at, "conflicts": conflicts,
                "xid_events": xid_by_gpu, "drains": drains_by_host, **cnt}

    # ----------------------------------------------------------------- pin the daily peaks
    def _pin(self, rack, trays, hosts, temp, sup, util, avail, ep_by_unit, product) -> list[str]:
        th, tc = self.hcfg["thermal"], self.cfg["thermal"]
        slow, below = th["slowdown_c"], tc["below_slowdown_c"]
        prng = random.Random(f"{self.seed}:telemetry:peaks:{rack}")
        G = temp.shape[0]
        fixed: dict[tuple[int, int], float] = {}
        for c in self.counters:
            if c["host"] in hosts:
                d = (parse(c["date"] + "T00:00:00Z") - self.start).days
                g = hosts.index(c["host"]) * GPUS + int(c["gpu"])
                if self._serial_on_day(trays[hosts.index(c["host"])], d) == c["tray_serial"]:
                    fixed[(g, d)] = float(c["gpu_temp_max_c"])
        conflicts = []
        for (g, d), eps in ep_by_unit.items():
            pk = max(p for _a, _b, p in eps)
            if (g, d) in fixed and abs(fixed[(g, d)] - pk) > 0.05:
                conflicts.append(f"{hosts[g // GPUS]} GPU {g % GPUS} {d}: counter {fixed[(g, d)]} vs episode {pk}")
            fixed[(g, d)] = pk
        over = th["gpu_over_supply_c"][product]
        hot = {h["host"]: h for h in self.key.get("hot_trays", [])}
        for d in range(self.days):
            date = (self.start + timedelta(days=d)).strftime("%Y-%m-%d")
            rd = self.rack_daily.get((date, rack))
            lo, hi = d * PER_DAY, (d + 1) * PER_DAY
            live = [g for g in range(G) if avail[g, lo:hi].any()]
            if not rd or not live:
                continue
            R = float(rd["gpu_temp_max_c"])
            target = {g: fixed[(g, d)] for g in live if (g, d) in fixed}
            if not any(abs(v - R) < 0.05 for v in target.values()):
                cand = [g for g in live if g not in target and (util[g, lo:hi] > 50).any()] or [g for g in live if g not in target]
                if cand:
                    target[prng.choice(cand)] = R
            smax = float(np.nanmax(sup[lo:hi]))
            for g in live:
                if g in target:
                    continue
                rise = 0.0
                h = hosts[g // GPUS]
                if h in hot and date >= hot[h]["from"]:
                    rise = float(np.mean(self.hcfg["plants"]["hot_tray_rise_c"]))
                v = smax + over + rise + prng.gauss(0, th["daily_sd_c"])
                target[g] = round(min(v, R - 0.1, slow - below), 1)
            for g, P in target.items():
                eps = ep_by_unit.get((g, d), [])
                normal = P if not eps else round(min(P, slow - below - prng.uniform(0.0, 1.5)), 1)
                self._scale(temp[g], sup, lo, hi, normal, util[g])
                seg = temp[g, lo:hi]
                np.minimum(seg, slow, out=seg, where=~np.isnan(seg))      # never at slowdown outside an episode
        # the recorded episodes last, so a later day's scaling never overwrites one that crossed midnight;
        # where episodes overlap on one GPU the higher reading wins
        M = temp.shape[1]
        for (g, _d), eps in sorted(ep_by_unit.items()):
            for a, b, pk in eps:
                b = min(b, M)
                n = b - a
                if n <= 0:
                    continue
                w = np.linspace(0.3, 1.0, (n + 1) // 2)
                shape = np.concatenate([w, w[::-1][n % 2:]])[:n] if n > 1 else np.array([1.0])
                vals = slow + (pk - slow) * shape
                vals[int(np.argmax(shape))] = pk
                cur = temp[g, a:b]
                inside = cur >= slow
                temp[g, a:b] = np.where(np.isnan(cur), np.nan, np.where(inside, np.maximum(cur, vals), vals))
                if a - 1 >= 0 and not np.isnan(temp[g, a - 1]) and temp[g, a - 1] < slow:
                    temp[g, a - 1] = min(slow - 0.05, max(temp[g, a - 1], slow - below - 0.3))
        return conflicts

    @staticmethod
    def _scale(row: np.ndarray, sup: np.ndarray, lo: int, hi: int, target: float, u: np.ndarray) -> None:
        seg = row[lo:hi]
        if np.all(np.isnan(seg)):
            return
        s = sup[lo:hi]
        rise = seg - s
        k = int(np.nanargmax(seg))
        if (u[lo:hi] > 50).any() and rise[k] > 1.0 and target - s[k] > 1.0:
            seg[:] = s + rise * (target - s[k]) / rise[k]
        else:
            seg[:] = seg + (target - seg[k])
        k = int(np.nanargmax(seg))
        np.minimum(seg, target, out=seg, where=~np.isnan(seg))
        seg[k] = target

    def _serial_on_day(self, tray: dict, d: int) -> str | None:
        mid = self.start + timedelta(days=d, hours=12)
        return next((s for a, b, s in tray["serials"] if a <= mid < b or b == self.end), None)

    def _serials(self, trays: list[dict], G: int) -> list[dict]:
        out = []
        for i, t in enumerate(trays):
            spans = [(self.m_of(a), self.m_of(b), s) for a, b, s in t["serials"]]
            for gpu in range(GPUS):
                out.append({"spans": spans, "swaps": [a for a, _b, _s in spans[1:]]})
        return out

    # ----------------------------------------------------------------- remapped rows, pending, corrected errors
    def _counters(self, hosts, trays, G, avail, serial_at) -> dict[str, np.ndarray]:
        M = self.M
        corr = np.zeros((G, M), dtype=np.int32)
        unc = np.zeros((G, M), dtype=np.int32)
        pend = np.zeros((G, M), dtype=np.int8)
        sbe = np.zeros((G, M), dtype=np.int32)     # corrected errors in the minute
        base_sbe = np.zeros(G, dtype=np.int64)
        rows: dict[tuple[int, str], list[dict]] = {}
        for c in self.counters:
            if c["host"] in hosts:
                g = hosts.index(c["host"]) * GPUS + int(c["gpu"])
                rows.setdefault((g, c["tray_serial"]), []).append(c)
        mem = set(self.hcfg["memory_xids"])
        for (g, serial), rs in rows.items():
            host = hosts[g // GPUS]
            span = next(((a, b) for a, b, s in serial_at[g]["spans"] if s == serial), (0, M))
            rr = random.Random(f"{self.seed}:telemetry:ctr:{host}:{g % GPUS}:{serial}")
            prev = None
            for c in sorted(rs, key=lambda r: r["date"]):
                d = (parse(c["date"] + "T00:00:00Z") - self.start).days
                lo, hi = max(d * PER_DAY, span[0]), min((d + 1) * PER_DAY, span[1])
                total, uce = int(c["remapped_rows"]), int(c["uce_day"])
                xm = sorted(min(self.m_of(parse(e["timestamp"])), span[1] - 1) for e in self.xids   # the XIDs dated today
                            if e["host"] == host and int(e["gpu_index"]) == g % GPUS and e["tray_serial"] == serial
                            and int(e["xid"]) in mem and e["timestamp"][:10] == c["date"])
                if prev is None:                    # rows remapped before the first row's day: earlier months, correctable
                    prev = max(0, total - uce)
                    corr[g, span[0]:span[1]] += prev
                corr_add = max(0, total - prev - uce)
                for m in xm[:uce]:
                    unc[g, m:span[1]] += 1
                for _ in range(corr_add):
                    m = rr.randrange(lo, hi) if hi > lo else lo
                    corr[g, m:span[1]] += 1
                n = int(c["sbe_day"])
                if n and hi > lo:
                    ok = np.flatnonzero(avail[g, lo:hi]) + lo
                    if len(ok):
                        picks = np.random.default_rng(rr.randrange(2**32)).choice(ok, size=n)
                        np.add.at(sbe[g], picks, 1)
                prev = total
        for w in self.watches:
            if w["system"] == "Memory" and w["xid"] is None and w["host"] in hosts:
                g = hosts.index(w["host"]) * GPUS + int(w["gpu"])
                a = self.m_of(parse(w["opened"]))
                b = self.m_of(parse(w["cleared"])) if w["cleared"] else M
                span = next(((x, y) for x, y, s in serial_at[g]["spans"] if s == w["tray_serial"]), (0, M))
                pend[g, a:min(b, span[1])] = 1
        for g in range(G):
            base_sbe[g] = random.Random(f"{self.seed}:telemetry:sbe:{hosts[g // GPUS]}:{g % GPUS}").randint(0, 400)
        sbe_total = np.cumsum(sbe, axis=1) + base_sbe[:, None]
        for g in range(G):
            for m in serial_at[g]["swaps"]:
                sbe_total[g, m:] -= sbe_total[g, m - 1] - base_sbe[g] // 3
        return {"remap_corr": corr, "remap_unc": unc, "pending": pend, "sbe": sbe, "sbe_total": sbe_total}


# ===================================================================== publishing
# Power follows utilization on a slight curve. numpy's power and exp take CPU-specific vector paths whose last bits
# differ between machines, which would change the published data from one computer to the next; a table built with
# the math module and read with np.interp gives the same numbers everywhere.
_CURVE_X = np.linspace(0.0, 1.0, 20001)
_CURVE_Y = np.array([round(math.pow(x, 1.15), 12) for x in _CURVE_X])


def _curve(util: np.ndarray) -> np.ndarray:
    """(util / 100) ** 1.15, identical on every CPU."""
    return np.interp(np.asarray(util, dtype=float) / 100.0, _CURVE_X, _CURVE_Y)


def _rle(a: np.ndarray) -> list[list]:
    """Run-length pairs [value, count]; NaN becomes null, whole numbers become integers."""
    out: list[list] = []
    for v in a.tolist():
        v = None if isinstance(v, float) and math.isnan(v) else (int(v) if isinstance(v, float) and v.is_integer() else v)
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def _ints(a: np.ndarray, avail: np.ndarray, nd: int = 0) -> list:
    if nd:
        return [round(float(v), nd) if ok else None for v, ok in zip(a.tolist(), avail.tolist())]
    return [int(round(float(v))) if ok else None for v, ok in zip(a.tolist(), avail.tolist())]


def _temps(t: np.ndarray) -> np.ndarray:
    """Whole degrees, rounded half up, as the exporter publishes them; NaN where there is no sample."""
    return np.floor(t + 0.5 + 1e-9)


def labels(cfg: dict, product: str, host: str, gpu: int, serial: str) -> dict[str, str]:
    """The exporter's labels for one GPU (synthetic values; label names as the exporter publishes them)."""
    return {"gpu": str(gpu), "UUID": gpu_uuid(serial, gpu), "pci_bus_id": f"{0x0008 + gpu:08X}:01:00.0",
            "device": f"nvidia{gpu}", "modelName": cfg["products"][product]["model_name"], "Hostname": host,
            "DCGM_FI_DRIVER_VERSION": cfg["collection"]["driver_version"]}


class Published:
    """Everything the month's telemetry publishes, built rack by rack."""

    def __init__(self, tel: GpuTelemetry):
        self.tel = tel
        self.rack_hourly: list[dict] = []
        self.gaps: list[dict] = []
        self.windows: dict[str, dict] = {}
        self.gpu_hourly: dict[str, dict] = {}
        self.conflicts: list[str] = []
        self.rack_load: dict[str, dict] = {}         # per rack per minute: GPU watts and GPUs reporting (the CDU layer's heat)

    def run(self, racks: list[str] | None = None) -> "Published":
        for r in racks or self.tel.racks:
            self.add(self.tel.rack(r))
        return self

    # ----------------------------------------------------------------- one rack
    def add(self, x: dict) -> None:
        tel, cfg = self.tel, self.tel.cfg
        G, M = x["avail"].shape
        H = M // 60
        av = x["avail"]
        sh = (G, H, 60)
        n = av.reshape(sh).sum(axis=2)
        with np.errstate(invalid="ignore", divide="ignore"):
            util_h = np.where(n > 0, np.where(av, x["util"], 0).reshape(sh).sum(axis=2) / np.maximum(n, 1), np.nan)
            pow_h = np.where(n > 0, np.where(av, x["power"], 0).reshape(sh).sum(axis=2) / np.maximum(n, 1), np.nan)
            tpub = _temps(x["temp"])
            temp_h = np.nanmax(np.where(av, tpub, -1e9).reshape(sh), axis=2)
            temp_h = np.where(n > 0, temp_h, np.nan)
            loaded = av & (x["util"] > 50)
            clk_h = np.min(np.where(loaded, x["clock"], 1e9).reshape(sh), axis=2)
            clk_h = np.where(clk_h < 1e9, clk_h, np.nan)
        th_h = np.where(av, x["thermal_s"], 0).reshape(sh).sum(axis=2)
        pw_h = np.where(av, x["power_s"], 0).reshape(sh).sum(axis=2)
        sbe_h = x["sbe"].reshape(sh).sum(axis=2)
        xid_h = np.zeros((G, H), dtype=int)
        for g, lst in x["xid_events"].items():
            for m, _x, _s in lst:
                xid_h[g, min(m // 60, H - 1)] += 1
        drained_h = np.zeros(H, dtype=int)
        for host, spans in x["drains"].items():
            hh = np.zeros(H, dtype=bool)
            for a, b, _r in spans:
                hh[a // 60: (b + 59) // 60] = True
            drained_h += hh
        rack = x["rack"]
        self.rack_load[rack] = {"hall": x["hall"], "cdu": x["cdu"], "product": x["product"],
                                "gpu_w": np.where(av, x["power"], 0).astype(np.float64).sum(axis=0), "n": av.sum(axis=0)}
        for h in range(H):
            ok = n[:, h] > 0
            samples = int(n[:, h].sum())
            row = {"hour": iso(tel.t_of(h * 60)), "rack": rack, "hall": x["hall"], "gpus_reporting": int(ok.sum()),
                   "samples": samples, "util_avg": "", "power_kwh": round(float(np.where(av[:, h * 60:(h + 1) * 60], x["power"][:, h * 60:(h + 1) * 60], 0).sum()) / 60 / 1000, 2),
                   "gpu_temp_max_c": "", "hbm_temp_max_c": "", "sm_clock_min_loaded_mhz": "",
                   "thermal_violation_s": int(round(float(th_h[:, h].sum()))), "power_violation_s": int(round(float(pw_h[:, h].sum()))),
                   "xids": int(xid_h[:, h].sum()), "nodes_drained": int(drained_h[h])}
            if samples:
                row["util_avg"] = round(float(np.where(av[:, h * 60:(h + 1) * 60], x["util"][:, h * 60:(h + 1) * 60], 0).sum()) / samples, 1)
                t = int(np.nanmax(temp_h[:, h]))
                row["gpu_temp_max_c"], row["hbm_temp_max_c"] = t, t + int(tel.cfg["thermal"]["hbm_over_gpu_c"])
                if not np.all(np.isnan(clk_h[:, h])):
                    row["sm_clock_min_loaded_mhz"] = int(round(float(np.nanmin(clk_h[:, h]))))
            self.rack_hourly.append(row)
        self.gaps += x["gaps"]
        self.conflicts += x["conflicts"]

        # ---- per GPU hourly, with the sparse records the page marks
        gpus = []
        for g in range(G):
            host, gi = x["hosts"][g // GPUS], g % GPUS
            spans = x["serial_at"][g]["spans"]
            lab = [{"from": iso(tel.t_of(a)), "to": iso(tel.t_of(b)), "serial": s,
                    **labels(cfg, x["product"], host, gi, s)} for a, b, s in spans]
            last = int(np.flatnonzero(av[g])[-1]) if av[g].any() else None
            gpus.append({"host": host, "gpu": gi, "labels": lab,
                         "util": _ints(util_h[g], n[g] > 0), "power": _ints(pow_h[g], n[g] > 0),
                         "temp": _ints(temp_h[g], n[g] > 0), "clock": _rle(np.round(clk_h[g], -1)),
                         "n": _rle(n[g].astype(float)), "thermal_s": _rle(np.round(th_h[g])),
                         "power_s": _rle(pw_h[g].astype(float)), "sbe": _rle(sbe_h[g].astype(float)),
                         "counters": self._changes(x, g),
                         "last": self._scrape_values(x, g, last) if last is not None else None})
        self.gpu_hourly[rack] = {"rack": rack, "hall": x["hall"], "cdu": x["cdu"], "product": x["product"],
                                 "start": iso(tel.start), "hours": H, "gpus": gpus}

        # ---- minute windows around events on each tray
        tc = cfg["tiers"]
        for i, host in enumerate(x["hosts"]):
            evs = []
            sl = slice(i * GPUS, (i + 1) * GPUS)
            for g in range(i * GPUS, (i + 1) * GPUS):
                for m, xv, _s in x["xid_events"].get(g, []):
                    evs.append((m, m + 1, f"XID {xv}"))
            for e in tel.episodes:
                if e["host"] == host:
                    evs.append((tel.m_of(parse(e["start"])), tel.m_of(parse(e["end"])) + 1, "thermal slowdown"))
            for gp in x["gaps"]:
                if gp["host"] == host and gp["gpu"] is None:
                    a, b = tel.m_of(parse(gp["from"])), tel.m_of(parse(gp["to"]))
                    evs += [(a, a + 1, "samples stop"), (b, b + 1, "samples resume")]
            spans = []
            for a, b, _w in sorted(evs):
                lo, hi = max(0, a - tc["window_before_min"]), min(M, b + tc["window_after_min"])
                if spans and lo <= spans[-1][1]:
                    spans[-1][1] = max(spans[-1][1], hi)
                else:
                    spans.append([lo, hi])
            for lo, hi in spans:
                name = f"{host}_{tel.t_of(lo).strftime('%Y%m%dT%H%M')}"
                self.windows[name] = self._window(x, host, sl, lo, hi)

    def _changes(self, x: dict, g: int) -> list[list]:
        """[time, correctable rows, uncorrectable rows, pending, last XID] whenever one of them changes."""
        cols = [x["remap_corr"][g], x["remap_unc"][g], x["pending"][g], x["xid"][g]]
        stack = np.vstack(cols)
        idx = [0] + list(np.flatnonzero((stack[:, 1:] != stack[:, :-1]).any(axis=0)) + 1)
        return [[iso(self.tel.t_of(int(m)))] + [int(c[m]) for c in cols] for m in idx]

    def _scrape_values(self, x: dict, g: int, m: int) -> dict[str, Any]:
        cfg = self.tel.cfg
        t = float(x["temp"][g, m])
        return {"at": iso(self.tel.t_of(m)),
                "DCGM_FI_DEV_GPU_TEMP": int(_temps(np.array(t))), "DCGM_FI_DEV_MEMORY_TEMP": int(_temps(np.array(t + cfg["thermal"]["hbm_over_gpu_c"]))),
                "DCGM_FI_DEV_POWER_USAGE": round(float(x["power"][g, m]), 3),
                "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION": int(x["energy"][g, m]),
                "DCGM_FI_DEV_GPU_UTIL": int(round(float(x["util"][g, m]))), "DCGM_FI_DEV_SM_CLOCK": int(round(float(x["clock"][g, m]))),
                "DCGM_FI_DEV_FB_USED": int(round(float(x["fb"][g, m]))), "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE": round(float(x["tensor"][g, m]), 6),
                "DCGM_FI_DEV_XID_ERRORS": int(x["xid"][g, m]),
                "DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS": int(x["remap_corr"][g, m]),
                "DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS": int(x["remap_unc"][g, m]),
                "DCGM_FI_DEV_ROW_REMAP_PENDING": int(x["pending"][g, m]),
                "DCGM_FI_DEV_ECC_SBE_AGG_TOTAL": int(x["sbe_total"][g, m]),
                "DCGM_FI_DEV_THERMAL_VIOLATION": int(round(float(np.where(x["avail"][g, :m + 1], x["thermal_s"][g, :m + 1], 0).sum()) * 1e9)),
                "DCGM_FI_DEV_POWER_VIOLATION": int(round(float(np.where(x["avail"][g, :m + 1], x["power_s"][g, :m + 1], 0).sum()) * 1e9))}

    def _window(self, x: dict, host: str, sl: slice, lo: int, hi: int) -> dict:
        tel = self.tel
        gp = []
        for g in range(sl.start, sl.stop):
            av = x["avail"][g, lo:hi]
            gp.append({"gpu": g % GPUS,
                       "util": _ints(x["util"][g, lo:hi], av), "power": _ints(x["power"][g, lo:hi], av),
                       "temp": _ints(_temps(np.where(av, x["temp"][g, lo:hi], 0)), av), "clock": _ints(x["clock"][g, lo:hi], av),
                       "fb": _rle(np.where(av, np.round(x["fb"][g, lo:hi].astype(float)), np.nan)),
                       "tensor": _rle(np.where(av, np.round(x["tensor"][g, lo:hi].astype(float), 4), np.nan)),
                       "thermal_s": _rle(np.where(av, np.round(x["thermal_s"][g, lo:hi]), np.nan)),
                       "power_s": _rle(np.where(av, x["power_s"][g, lo:hi], np.nan)),
                       "energy_mj": _ints(x["energy"][g, lo:hi], av),
                       "sbe_total": _rle(x["sbe_total"][g, lo:hi].astype(float)),
                       "remap_corr": _rle(x["remap_corr"][g, lo:hi].astype(float)), "remap_unc": _rle(x["remap_unc"][g, lo:hi].astype(float)),
                       "pending": _rle(x["pending"][g, lo:hi].astype(float)), "xid": _rle(x["xid"][g, lo:hi].astype(float)),
                       "thermal_ns_before": int(round(float(np.where(x["avail"][g, :lo], x["thermal_s"][g, :lo], 0).sum()) * 1e9)),
                       "power_ns_before": int(round(float(np.where(x["avail"][g, :lo], x["power_s"][g, :lo], 0).sum()) * 1e9)),
                       "labels": next((labels(tel.cfg, x["product"], host, g % GPUS, s) for a, b, s in x["serial_at"][g]["spans"]
                                       if a <= lo < b), labels(tel.cfg, x["product"], host, g % GPUS, x["serial_at"][g]["spans"][-1][2]))})
        return {"host": host, "rack": x["rack"], "from": iso(tel.t_of(lo)), "minutes": hi - lo, "gpus": gp}


# ===================================================================== files
def _csv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n"


def write_telemetry(pub: Published, dest: str | Path, source: str = "", hourly_dest: str | Path | None = None) -> dict[str, Any]:
    """Write the committed tiers to dest; the per-GPU hourly tier to hourly_dest (publish time) if given.

    The manifest always records each per-GPU hourly file's SHA-256, so a test can rebuild them and compare."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    win = dest / "windows"
    if win.exists():
        for p in win.glob("*.json"):
            p.unlink()
    win.mkdir(exist_ok=True)
    rows = sorted(pub.rack_hourly, key=lambda r: (r["hour"], r["rack"]))
    gaps = sorted(pub.gaps, key=lambda g: (g["from"], g["host"], -1 if g["gpu"] is None else g["gpu"]))
    files = {"rack_hourly.csv": _csv(rows, RACK_HOURLY_COLUMNS),
             "gaps.jsonl": "".join(json.dumps(g, sort_keys=True) + "\n" for g in gaps)}
    for name, text in files.items():
        (dest / name).write_text(text, encoding="utf-8", newline="\n")
    index = []
    for name in sorted(pub.windows):
        w = pub.windows[name]
        (win / f"{name}.json").write_text(_dump(w), encoding="utf-8", newline="\n")
        index.append({"file": f"windows/{name}.json", "host": w["host"], "rack": w["rack"], "from": w["from"], "minutes": w["minutes"]})
    hourly = {r: _dump(v) for r, v in sorted(pub.gpu_hourly.items())}
    if hourly_dest is not None:
        hd = Path(hourly_dest)
        hd.mkdir(parents=True, exist_ok=True)
        for r, text in hourly.items():
            (hd / f"{r}.json").write_text(text, encoding="utf-8", newline="\n")
    tel = pub.tel
    man = {"disclaimer": "Synthetic GPU telemetry for a portfolio demonstration, in the published format of NVIDIA's open-source "
                         "DCGM exporter. All names, serials, UUIDs, and readings are fictional.",
           "source": source, "window": {"start": iso(tel.start), "end": iso(tel.end)},
           "files": {"rack_hourly.csv": len(rows), "gaps.jsonl": len(gaps), "windows": len(index)},
           "windows": index,
           "gpu_hourly": {f"{r}.json": {"sha256": hashlib.sha256(t.encode()).hexdigest(), "bytes": len(t.encode())}
                          for r, t in hourly.items()},
           "racks": sorted(pub.gpu_hourly), "gpus": sum(len(v["gpus"]) for v in pub.gpu_hourly.values())}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
