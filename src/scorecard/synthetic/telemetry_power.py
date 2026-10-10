"""Synthetic power telemetry for Site AUS-1: UPSs, busway runs and tap-offs, and generators.

Portfolio demo; all data fictional. Runs on a finished month after its GPU telemetry and its energy meters,
with its own random stream, and writes beside them, never into them.

Built from the bottom up, one reading a minute per device:

* **Tap-offs** (Starline M70 plug-in meters): each rack's input power is the GPU telemetry's rack model
  (``rack_input_w``: the GPUs plus the rest of the rack), pinned hour by hour to the rack's energy in
  ``rack_hourly.csv``, split between its A and B tap-offs by power shelf. A tap-off whose breaker is open
  (``busway_cpm_events``) or whose run has lost its feed carries nothing, and the other side carries the rack.
* **Busway runs** (M70 end-feed meters): the sum of their tap-offs plus the conductor loss the energy
  meters use; voltage from the feeding UPS less the drop along the run; 0 V while the feed is lost.
* **IT UPSs** (Galaxy VX, SNMPv3: UPS-MIB and PowerNet-MIB): the sum of the runs they feed. Each hall's
  output equals the metered UPS output every hour. Modes, battery discharge and recharge, and power-module
  faults follow the NMC events (``ups_nmc_events``).
* **Mechanical UPSs** (Galaxy VL): the recorded load polls (``ups_status``) at the poll minute, and each hall's
  input equals the metered mechanical UPS energy every hour.
* **Generators** (EMCP 4.4, Modbus): every EMCP reading on record at its minute (the monthly tests), and in a
  utility outage (``epms_events``) the site's own load, shared across the running sets.

kW fields are one-minute averages (the collector derives them from each meter's energy counter); states and
breaker positions are read at the minute. Published tiers (see ``write_power``): hourly per UPS, run, tap-off,
and generator, the states, and one-minute windows around every event, committed; the one-minute series per
device built at publish time with checksums in the manifest. Settings: ``config/telemetry_power.yaml``.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from scorecard import site_model as S
from scorecard.synthetic.telemetry import (MIN, GpuTelemetry, Published, _csv, _csv_rows, _dump, _jsonl, iso, parse,
                                           rack_input_kwh, rack_input_w)
from scorecard.synthetic.telemetry_cdu import _ar as _ar_cdu

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "telemetry_power.yaml"
HOUR_MIN = 60
SQRT3 = math.sqrt(3)

UPS_HOURLY = ["hour", "ups", "hall", "kind", "out_kwh", "in_kwh", "load_avg_pct", "load_max_pct", "amps_max", "soc_min_pct",
              "bypass_min", "battery_s", "modules_min"]
RUN_HOURLY = ["hour", "run", "hall", "ups", "kwh", "amps_avg", "amps_max", "v_min", "v_max", "dead_min", "encl_max_c"]
TAP_HOURLY = ["hour", "tapoff", "rack", "kwh", "amps_max", "open_min"]
GEN_HOURLY = ["hour", "generator", "run_min", "kwh", "kw_max", "pct_max", "coolant_max_c", "fuel_pct", "hours"]


def _ar(rng: np.random.Generator, n: int, sd: float, rho: float) -> np.ndarray:
    """AR(1) noise with stationary sd from the first minute (the CDU helper starts its series at the first draw over
    1 - rho, a transient that at rho 0.995 begins 200 times the step: several percent on a voltage)."""
    if n == 0:
        return _ar_cdu(rng, n, sd, rho)
    e = rng.normal(0, sd * math.sqrt(1 - rho * rho), n)
    e[0] *= (1 - rho) / math.sqrt(1 - rho * rho)                 # the first value is then a stationary draw
    return pd.Series(e).ewm(alpha=1 - rho, adjust=False).mean().to_numpy() / (1 - rho)


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rng(seed: int, *parts: object) -> np.random.Generator:
    key = ":".join(str(p) for p in (seed, "telemetry", "power") + parts)
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def pin_sum(x: np.ndarray, total: int, fixed: dict[int, int] | None = None) -> np.ndarray:
    """Non-negative integers shaped like x whose sum is exactly total, with the indices in fixed set to their values."""
    n = len(x)
    out = np.zeros(n, dtype=np.int64)
    fixed = fixed or {}
    free = np.array([i for i in range(n) if i not in fixed], dtype=np.int64)
    for i, v in fixed.items():
        out[i] = v
    rest = total - sum(fixed.values())
    if not len(free):
        return out
    w = np.maximum(x[free].astype(np.float64), 0.0)
    if w.sum() <= 0:
        w = np.ones(len(free))
    want = w * (rest / w.sum())
    base = np.floor(want).astype(np.int64)
    short = int(rest - base.sum())
    frac = want - base
    if short > 0:
        order = np.argsort(-frac, kind="stable")[:short]
        base[order] += 1
    elif short < 0:
        order = np.argsort(frac, kind="stable")
        k = 0
        for i in order:
            if k == -short:
                break
            if base[i] > 0:
                base[i] -= 1
                k += 1
    out[free] = base
    return out


def pack(a: np.ndarray) -> list:
    """An integer series as its first value and the minute-to-minute steps, with each run of two or more unchanged
    minutes written as [n] (most power readings hold still at the resolution the device publishes)."""
    a = np.asarray(a, dtype=np.int64)
    if not len(a):
        return []
    d = [int(a[0])] + np.diff(a).tolist()
    out: list = [d[0]]
    i, n = 1, len(d)
    while i < n:
        if d[i] == 0:
            j = i
            while j < n and d[j] == 0:
                j += 1
            out.append([j - i] if j - i > 1 else 0)
            i = j
        else:
            out.append(d[i])
            i += 1
    return out


def unpack(p: list) -> np.ndarray:
    steps: list[int] = []
    for x in p:
        if isinstance(x, list):
            steps.extend([0] * x[0])
        else:
            steps.append(x)
    return np.cumsum(np.asarray(steps, dtype=np.int64))


def _spans(events: list[tuple[int, bool]], M: int, start_on: bool = False) -> np.ndarray:
    """A boolean minute series from (minute, on) changes."""
    out = np.zeros(M, dtype=bool)
    state, since = start_on, 0
    for m, on in sorted(events):
        if state:
            out[since:m] = True
        state, since = on, m
    if state:
        out[since:] = True
    return out


class PowerTelemetry:
    """One-minute readings for every UPS, busway run, tap-off, and generator in a hall with GPU telemetry."""

    def __init__(self, tel: GpuTelemetry, pub: Published, energy_dir: str | Path, cfg: dict[str, Any] | None = None,
                 site: dict | None = None, energy_cfg: dict | None = None, rack_rest: dict | None = None):
        from scorecard.synthetic.energy import load_config as energy_config
        from scorecard.synthetic.telemetry_cdu import load_config as cdu_config
        self.tel, self.pub = tel, pub
        self.cfg = cfg or load_config()
        self.site = site or S.load_site()
        self.ecfg = energy_cfg or energy_config()
        self.rest = rack_rest or cdu_config()["rack_rest"]
        self.seed, self.start, self.end, self.M = tel.seed, tel.start, tel.end, tel.M
        self.H = self.M // HOUR_MIN
        d = tel.dir
        self.meters = {r["hour"]: r for r in _csv_rows(Path(energy_dir) / "meters_hourly.csv")}
        self.nmc = sorted(_jsonl(d / "facility" / "ups_nmc_events.jsonl"), key=lambda e: (e["timestamp"], e["ups"]))
        self.polls = _jsonl(d / "facility" / "ups_status.jsonl")
        self.cpm = sorted(_jsonl(d / "facility" / "busway_cpm_events.jsonl"), key=lambda e: e["timestamp"])
        self.epms = sorted(_jsonl(d / "facility" / "epms_events.jsonl"), key=lambda e: e["timestamp"])
        self.emcp = sorted(_jsonl(d / "facility" / "emcp_readings.jsonl"), key=lambda e: (e["generator"], e["timestamp"]))
        self.halls = [h for h in self.site["halls"] if h["state"] in ("production", "deployment")]
        self.racks = {r["rack"]: r for h in self.halls for r in S.racks(self.site, h["id"])}
        self.runs: dict[str, dict] = {}
        for h in self.halls:
            for s in S.busway_segments(self.site, h["id"]):
                for side in ("A", "B"):
                    self.runs[f"{s['id']}-{side}"] = {"hall": h["id"], "segment": s["id"], "side": side,
                                                      "ups": s["feeds"][side], "racks": list(s["racks"])}
        self.run_of = {(rk, side): run for run, x in self.runs.items() for rk in x["racks"] for side in (x["side"],)}
        self.ups = {}
        for h in self.halls:
            vx = S.product(self.site, h["power"]["ups_product"])
            vl = S.product(self.site, h["power"]["mech_ups_product"])
            for i in range(1, h["power"]["ups_count"] + 1):
                self.ups[f"UPS-{h['letter']}{i}"] = {"hall": h["id"], "kind": "it", "rating_kw": vx["rating_kw"],
                                                      "eff": vx["efficiency"], "model": vx["model"], "modules": self.cfg["ups"]["modules_vx"]}
            for i in range(1, h["power"]["mech_ups_count"] + 1):
                self.ups[f"MUPS-{h['letter']}{i}"] = {"hall": h["id"], "kind": "mech", "rating_kw": vl["rating_kw"],
                                                       "eff": vl["efficiency"], "model": vl["model"], "modules": self.cfg["ups"]["modules_vl"]}
        g = self.site["plants"]["generators"]
        self.gens = [f"GEN-{i}" for i in range(1, g["count"] + 1)]
        self.conflicts: list[str] = []

    # ----------------------------------------------------------------- time helpers
    def m_of(self, t: datetime) -> int:
        return self.tel.m_of(t)

    def floor_m(self, t: datetime) -> int:
        return max(0, min(self.M - 1, int((t - self.start).total_seconds() // 60)))

    def t_of(self, m: int) -> datetime:
        return self.start + m * MIN

    def overlap(self, a: datetime, b: datetime) -> np.ndarray:
        """Seconds of each minute [t_m, t_m+1) inside [a, b)."""
        out = np.zeros(self.M)
        s0 = (a - self.start).total_seconds()
        s1 = (b - self.start).total_seconds()
        if s1 <= 0 or s0 >= self.M * 60:
            return out
        s0, s1 = max(0.0, s0), min(self.M * 60.0, s1)
        m0, m1 = int(s0 // 60), int(math.ceil(s1 / 60))
        for m in range(m0, m1):
            out[m] = max(0.0, min(s1, (m + 1) * 60.0) - max(s0, m * 60.0))
        return out

    # ----------------------------------------------------------------- records as spans
    def tapoff_breakers(self) -> dict[str, list[tuple[int, bool, dict]]]:
        """Breaker changes per tap-off (TO-<rack>-<side>). The plug-in meter reports its own tap-off; the side is the
        event's, or the run's suffix when the record names the tap-off without one."""
        out: dict[str, list] = {}
        for e in self.cpm:
            if e.get("point") != "Tap-off breaker":
                continue
            tap = e["tapoff"] if e["tapoff"][-2:] in ("-A", "-B") else f"{e['tapoff']}-{e['busway'][-1]}"
            out.setdefault(tap, []).append((self.m_of(parse(e["timestamp"])), e["event"] == "Breaker closed", e))
        return out

    def dead_runs(self) -> dict[str, list[tuple[int, int, dict, dict | None]]]:
        """Runs whose feed was lost (the CPM's own undervoltage reading, out of tolerance until back in tolerance)."""
        out: dict[str, list] = {}
        open_: dict[str, tuple[int, dict]] = {}
        for e in self.cpm:
            if e.get("point") != "Voltage L-L avg":
                continue
            m = self.m_of(parse(e["timestamp"]))
            if e["state"] == "out_of_tolerance":
                open_[e["busway"]] = (m, e)
            elif e["busway"] in open_:
                a, ea = open_.pop(e["busway"])
                out.setdefault(e["busway"], []).append((a, m, ea, e))
        for bw, (a, ea) in open_.items():
            out.setdefault(bw, []).append((a, self.M, ea, None))
        return out

    def ups_modes(self, ups: str) -> dict[str, Any]:
        """Bypass and battery spans (exact times) and power-module faults from the NMC events."""
        ev = [e for e in self.nmc if e["ups"] == ups]
        byp, bat, mod = [], [], []
        since: dict[str, tuple[datetime, dict]] = {}
        for e in ev:
            t, x = parse(e["timestamp"]), e["event"]
            if x.endswith("switchedBypass"):
                since["byp"] = (t, e)
            elif x.endswith("onBattery"):
                since["bat"] = (t, e)
            elif x.endswith("onLine"):
                for k, lst in (("byp", byp), ("bat", bat)):
                    if k in since:
                        lst.append((since.pop(k)[0], t))
            elif x.startswith("Power module") and x.endswith("fault"):
                since["mod"] = (t, e)
            elif x == "Power module redundancy restored" and "mod" in since:
                mod.append((since.pop("mod")[0], t))
        for k, lst in (("byp", byp), ("bat", bat), ("mod", mod)):
            if k in since:
                lst.append((since.pop(k)[0], self.end))
        return {"bypass": byp, "battery": bat, "module": mod, "events": ev}

    def outages(self) -> list[dict]:
        """Utility outages from the EPMS: trip, generator bus live, ties closed, retransfer, ties open."""
        out, cur = [], None
        for e in self.epms:
            t = parse(e["timestamp"])
            if e["device"] == "MV-A main breaker" and "utility undervoltage" in e["event"]:
                cur = {"trip": t, "events": [e]}
            elif cur is None:
                continue
            else:
                cur["events"].append(e)
                if e["device"] == "Generator paralleling bus":
                    cur["bus_live"] = t
                elif e["device"] == "Generator tie breakers" and e["event"].startswith("Closed"):
                    cur["ties_closed"] = t
                elif e["device"] == "MV-A main breaker" and "utility restored" in e["event"]:
                    cur["back"] = t
                elif e["device"] == "Generator tie breakers" and e["event"] == "Open":
                    cur["ties_open"] = t
                    out.append(cur)
                    cur = None
        for o in out:
            o.setdefault("bus_live", o["trip"] + timedelta(seconds=10))
            o.setdefault("ties_closed", o["bus_live"] + timedelta(seconds=2))
        return out

    # ----------------------------------------------------------------- racks and tap-offs
    def rack_watts(self) -> dict[str, np.ndarray]:
        """Each rack's input power, W per minute, pinned so every hour's energy equals rack_hourly.csv (W-minutes)."""
        rows = {(r["rack"], r["hour"]): r for r in self.pub.rack_hourly}
        out = {}
        for rack, x in sorted(self.pub.rack_load.items()):
            w = rack_input_w(x["n"].astype(np.float64), x["gpu_w"], self.rest)
            v = np.zeros(self.M, dtype=np.int64)
            for h in range(self.H):
                r = rows.get((rack, iso(self.t_of(h * HOUR_MIN))))
                sl = slice(h * HOUR_MIN, (h + 1) * HOUR_MIN)
                if r is None:
                    continue
                target = int(round(rack_input_kwh(r, self.rest) * 60000))
                v[sl] = pin_sum(np.where(x["n"][sl] > 0, w[sl], 0.0), target) if target else 0
            out[rack] = v
        return out

    def tapoffs(self, rack_w: dict[str, np.ndarray], dead: dict[str, list]) -> dict[str, dict]:
        el = self.cfg["electrical"]
        brk = self.tapoff_breakers()
        out = {}
        for rack, r in sorted(self.racks.items()):
            rng = _rng(self.seed, rack, "shelves")
            share = float(rng.uniform(*el["share_a"]))
            pf = float(rng.uniform(*el["rack_pf"]))
            imb = rng.normal(0, el["phase_imbalance_pct"] / 100, 3)
            imb = 1 + imb - imb.mean()
            live, closed = {}, {}
            for side in ("A", "B"):
                tap = f"TO-{rack}-{side}"
                changes = [(m, on) for m, on, _e in brk.get(tap, [])]
                closed[side] = ~_spans([(m, not on) for m, on in changes], self.M)
                run = self.run_of[(rack, side)]
                alive = np.ones(self.M, dtype=bool)
                for a, b, _x, _y in dead.get(run, []):
                    alive[a:b] = False
                live[side] = closed[side] & alive
            w = rack_w.get(rack, np.zeros(self.M, dtype=np.int64))
            both = live["A"] & live["B"]
            wa = np.where(both, np.round(w * share).astype(np.int64), np.where(live["A"], w, 0))
            wb = w - wa
            dark = (w > 0) & ~live["A"] & ~live["B"]
            if dark.any():
                m = int(np.argmax(dark))
                self.conflicts.append(f"rack {rack} draws power at {iso(self.t_of(m))} with neither tap-off live")
            for side, ws in (("A", wa), ("B", wb)):
                out[f"TO-{rack}-{side}"] = {"rack": rack, "side": side, "run": self.run_of[(rack, side)], "hall": r["hall"],
                                           "w": ws, "closed": closed[side], "live": live[side], "pf": round(pf, 3),
                                           "imbalance": [round(float(k), 4) for k in imb],
                                           "changes": brk.get(f"TO-{rack}-{side}", [])}
        return out

    # ----------------------------------------------------------------- UPS output voltage and frequency
    def ups_bus(self) -> dict[str, dict[str, np.ndarray]]:
        """Utility-side and output voltage and frequency per UPS (the hall's MV bus feeds its UPSs)."""
        el = self.cfg["electrical"]
        out = {}
        hz_rng = _rng(self.seed, "utility", "hz")
        hz = el["hz"] + _ar(hz_rng, self.M, 0.012, 0.9)
        for o in self.outages():
            on = self.overlap(o["ties_closed"], o["back"]) > 0
            hz = np.where(on, el["hz"] + _ar(_rng(self.seed, "gen", "hz"), self.M, 0.035, 0.7), hz)
        for h in self.halls:
            hv = el["ln_v"] * (1 + _ar(_rng(self.seed, h["id"], "utility_v"), self.M, el["utility_v_sd_pct"] / 100, 0.995))
            for u, x in self.ups.items():
                if x["hall"] != h["id"]:
                    continue
                r = _rng(self.seed, u, "bus")
                out[u] = {"in_v": hv * (1 + r.normal(0, 0.0004, self.M)), "byp_v": hv * (1 + r.normal(0, 0.0004, self.M)),
                          "out_v": el["ln_v"] * (1 + _ar(r, self.M, el["ups_out_v_sd_pct"] / 100, 0.6)),
                          "in_hz": hz + r.normal(0, 0.003, self.M)}
        return out

    # ----------------------------------------------------------------- busway runs
    def run_series(self, taps: dict[str, dict], bus: dict, dead: dict) -> dict[str, dict]:
        el = self.cfg["electrical"]
        loss = self.ecfg["busway_loss_fraction"]
        rating = S.product(self.site, "starline_1200t5")["rating_a"]
        out = {}
        for run, x in sorted(self.runs.items()):
            mine = [t for t in taps.values() if t["run"] == run]
            w = sum(t["w"] for t in mine) if mine else np.zeros(self.M, dtype=np.int64)
            kw10 = np.round(w * (1 + loss) / 100).astype(np.int64)            # tenths of kW
            alive = np.ones(self.M, dtype=bool)
            for a, b, _x, _y in dead.get(run, []):
                alive[a:b] = False
            u = bus[x["ups"]]
            v0 = u["out_v"] * SQRT3
            # line currents: each tap-off's share on each line at the run's voltage and the rack's power factor
            amps = np.zeros((3, self.M))
            vbase = np.where(v0 > 0, v0, 1.0)
            for t in mine:
                i = t["w"] / (SQRT3 * vbase * t["pf"])
                for k in range(3):
                    amps[k] += i * t["imbalance"][k]
            amps *= (1 + loss)
            iavg = amps.mean(axis=0)
            v = v0 * (1 - el["busway_drop_pct_at_rated"] / 100 * iavg / rating)
            r = _rng(self.seed, run, "cpm")
            v = np.where(alive, v + r.normal(0, 0.15, self.M), 0.0)
            for a, b, ea, eb in dead.get(run, []):
                if eb is not None and b < self.M:
                    v[b] = float(eb["value_v"])                    # the CPM's own reading when the feed came back
            a1, a2, a3 = (np.where(alive, amps[k], 0.0) for k in range(3))
            an = np.sqrt(np.maximum(a1 * a1 + a2 * a2 + a3 * a3 - a1 * a2 - a2 * a3 - a3 * a1, 0.0))
            room = float(r.uniform(*el["enclosure_c"]))
            frac = iavg / rating
            rise = el["enclosure_rise_c_at_rated"] * frac * frac
            encl = room + _smooth(rise, 20.0) + r.normal(0, 0.05, self.M)
            out[run] = {**x, "kw10": np.where(alive, kw10, 0), "v_ll": v, "a": (a1, a2, a3), "an": an,
                        "hz": u["in_hz"], "encl": encl, "alive": alive, "dead": dead.get(run, []),
                        "tapoffs": sorted(t for t, y in taps.items() if y["run"] == run)}
        return out

    # ----------------------------------------------------------------- UPS
    def ups_series(self, runs: dict[str, dict], bus: dict) -> dict[str, dict]:
        uc = self.cfg["ups"]
        out = {}
        mech = self.mech_output()
        for u, x in self.ups.items():
            M = self.M
            md = self.ups_modes(u)
            b = bus[u]
            if x["kind"] == "it":
                feeds = [r for r in runs.values() if r["ups"] == u]
                kw10 = sum(r["kw10"] for r in feeds)
                amps = [sum(r["a"][k] for r in feeds) for k in range(3)]
            else:
                kw10 = mech[u]
                i = kw10 * 100 / (3 * np.where(b["out_v"] > 0, b["out_v"], 1.0) * 0.99)
                amps = [i, i, i]
            out_kw = kw10 / 10.0
            byp = np.zeros(M)
            for a, z in md["bypass"]:
                byp += self.overlap(a, z)
            bat = np.zeros(M)
            for a, z in md["battery"]:
                bat += self.overlap(a, z)
            byp, bat = np.minimum(byp, 60) / 60, np.minimum(bat, 60) / 60
            conv = 1 - byp - bat
            in_kw = out_kw * (conv / x["eff"] + byp / uc["bypass_efficiency"])
            if x["kind"] == "it":
                in_kw = in_kw + x["rating_kw"] * self.ecfg["ups_no_load_fraction"] * (1 - bat)     # no-load loss, while on the input
            # battery: the input it did not draw while on battery, returned by recharge at a fixed rate afterwards
            bc = uc["battery"]
            cap_kwh = x["rating_kw"] * 5 / 60                           # 5 minutes at full rated load
            idle = x["rating_kw"] * self.ecfg["ups_no_load_fraction"] if x["kind"] == "it" else 0.0
            missed = (out_kw / x["eff"] + idle) * bat / 60               # kWh from the battery each minute (the inverter's own loss too)
            recharge = np.zeros(M)
            rate = bc["recharge_frac"] * x["rating_kw"] / 60             # kWh per minute
            owed = 0.0
            for m in range(M):
                if missed[m] > 0:
                    owed += missed[m]                                   # recharging starts the minute after
                elif owed > 1e-12:
                    take = min(owed, rate)
                    recharge[m] = take
                    owed -= take
            in_kw = in_kw + recharge * 60
            soc = 100 * (1 - (np.cumsum(missed) - np.cumsum(recharge)) / cap_kwh)
            r = _rng(self.seed, u, "battery")
            vbat = bc["float_v"] + r.normal(0, 0.15, M) - 6.0 * (missed > 0) + 3.0 * (recharge > 0)
            ibat = (recharge * 60 - missed * 60) * 1000 / vbat + r.normal(0, 0.1, M) + 0.3
            t0 = float(r.uniform(*bc["temp_c"]))
            bt = t0 + _ar(r, M, 0.15, 0.995) + 0.6 * recharge * 60 / max(1.0, rate * 60)
            load = np.maximum(out_kw, 1.0)
            runtime = np.minimum(cap_kwh * soc / 100 / load * 3600, bc["runtime_cap_min"] * 60)
            modules = np.full(M, x["modules"], dtype=np.int64)
            for a, z in md["module"]:
                modules[self.m_of(a):self.m_of(z)] = x["modules"] - 1
            src = np.full(M, uc["output_source"]["normal"], dtype=np.int64)
            for a, z in md["bypass"]:
                src[self.m_of(a):self.m_of(z)] = uc["output_source"]["bypass"]
            for a, z in md["battery"]:
                src[self.m_of(a):self.m_of(z)] = uc["output_source"]["battery"]
            pf_in = 0.99
            in_a = in_kw * 1000 / (3 * np.where(b["in_v"] > 0, b["in_v"], 1.0) * pf_in)
            out[u] = {**x, "source": src, "in_v": b["in_v"], "in_a": in_a, "in_hz": b["in_hz"], "in_kw": in_kw, "byp_v": b["byp_v"],
                      "out_v": b["out_v"], "out_a": amps, "out_kw10": kw10, "out_hz": b["in_hz"],
                      "soc": soc, "runtime": runtime, "batt_v": vbat, "batt_a": ibat, "batt_c": bt, "modules": modules,
                      "module_count": x["modules"],
                      "bypass_frac": byp, "battery_frac": bat, "modes": md}
        return out

    def mech_output(self) -> dict[str, np.ndarray]:
        """Mechanical UPS output, tenths of kW per minute: the recorded poll at its minute; each hall's input each hour the
        metered mechanical UPS energy."""
        polls: dict[str, list[tuple[int, float]]] = {}
        for p in self.polls:
            if p["ups"].startswith("MUPS-") and "load_pct" in p:
                polls.setdefault(p["ups"], []).append((self.m_of(parse(p["timestamp"])), float(p["load_pct"])))
        out = {}
        for h in self.halls:
            ids = [u for u, x in self.ups.items() if x["hall"] == h["id"] and x["kind"] == "mech"]
            base = {}
            for u in ids:
                pts = sorted(polls.get(u, []))
                if not pts:
                    base[u] = np.full(self.M, 35.0 * self.ups[u]["rating_kw"] / 100)
                    continue
                xs, ys = [m for m, _ in pts], [v * self.ups[u]["rating_kw"] / 100 for _, v in pts]
                base[u] = np.interp(np.arange(self.M), xs, ys) * (1 + _ar(_rng(self.seed, u, "mech"), self.M, 0.01, 0.95))
            series = {u: np.zeros(self.M, dtype=np.int64) for u in ids}
            col = f"mech_{h['letter'].lower()}_kwh"
            for k in range(self.H):
                sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
                row = self.meters.get(iso(self.t_of(k * HOUR_MIN)))
                fixed = {u: {m - k * HOUR_MIN: int(round(v * self.ups[u]["rating_kw"] / 100 * 10)) for m, v in polls.get(u, [])
                             if k * HOUR_MIN <= m < (k + 1) * HOUR_MIN} for u in ids}
                if row is None:
                    for u in ids:
                        series[u][sl] = np.round(base[u][sl] * 10)
                    continue
                eff = self.ups[ids[0]]["eff"]
                target = int(round(float(row[col]) * eff * 600))           # tenths of kW x minutes over the hall
                tot_base = sum(float(base[u][sl].sum()) for u in ids) or 1.0
                left = target
                for j, u in enumerate(ids):
                    t_u = left if j == len(ids) - 1 else int(round(target * float(base[u][sl].sum()) / tot_base))
                    left -= t_u
                    series[u][sl] = pin_sum(base[u][sl] * 10, t_u, fixed[u])
            out.update(series)
        return out

    # ----------------------------------------------------------------- generators
    def site_load_kw(self, ups: dict[str, dict]) -> np.ndarray:
        """The site's load each minute: the metered facility energy of the hour, with the UPS inputs' minute-to-minute
        swing around their hourly mean."""
        it = sum(x["in_kw"] for x in ups.values())
        out = np.zeros(self.M)
        for k in range(self.H):
            sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
            row = self.meters.get(iso(self.t_of(k * HOUR_MIN)))
            f = (float(row["utility_kwh"]) + float(row["generator_kwh"])) if row else 0.0
            out[sl] = f + it[sl] - it[sl].mean()
        return out

    def generator_series(self, site_kw: np.ndarray) -> dict[str, dict]:
        gc = self.cfg["generator"]
        el = self.cfg["electrical"]
        st = gc["states"]
        M = self.M
        rated = gc["rated_kw"]
        recs: dict[str, list[dict]] = {}
        for r in self.emcp:
            recs.setdefault(r["generator"], []).append(r)
        outs = self.outages()
        # the outage's readings, generated the way the EMCP records a run: Starting, then a reading a minute, Cooldown
        # for the last five minutes, Stopped; the load is the site's, shared across the sets
        share_rng = _rng(self.seed, "gens", "share")
        n = len(self.gens)
        shares = 1 + share_rng.normal(0, gc["load_share_sd_pct"] / 100, (n, M))
        shares = shares / shares.sum(axis=0)
        out = {}
        for gi, g in enumerate(self.gens):
            r = _rng(self.seed, g, "engine")
            state = np.full(M, st["Stopped"], dtype=np.int64)
            ecs = np.ones(M, dtype=np.int64)
            brk = np.zeros(M, dtype=np.int64)
            kw = np.zeros(M)
            pfv = np.zeros(M)
            loadbank = np.zeros(M, dtype=bool)
            readings: list[dict] = []
            for x in recs.get(g, []):
                readings.append({"m": self.floor_m(parse(x["timestamp"])), "time": x["timestamp"], "state": x["engine_operating_state"],
                                 "kw": float(x["gen_total_kw"]), "pct": float(x["gen_pct_rated_kw"]), "record": "facility/emcp_readings.jsonl",
                                 "test": True})
            for o in outs:
                # kW is the minute's average: the generators carry the site from the tie breakers closing until
                # the utility is back (the UPS batteries bridge the seconds before)
                carried = self.overlap(o["ties_closed"], o["back"]) / 60
                t = o["trip"] + timedelta(seconds=2)
                end = o["back"] + timedelta(minutes=5)
                tt, now = t, "Starting"
                while tt < end:
                    m = self.floor_m(tt)
                    k = site_kw[m] * shares[gi, m] * carried[m]
                    rec = ("derived: EPMS trip (facility/epms_events.jsonl)" if now == "Starting"
                           else "derived: site load while the generators carried the site")
                    readings.append({"m": m, "time": iso(tt), "state": now, "kw": round(k, 1), "pct": round(k / rated * 100, 1),
                                     "test": False, "record": rec})
                    tt += MIN
                    now = "Running" if tt < end - timedelta(minutes=5) else "Cooldown"
                readings.append({"m": self.floor_m(end), "time": iso(end), "state": "Stopped", "kw": 0.0, "pct": 0.0, "test": False,
                                 "record": "derived: EPMS retransfer plus the five-minute cooldown"})
            readings.sort(key=lambda x: x["time"])
            # fill the minutes between readings with the last state
            kw10 = np.zeros(M, dtype=np.int64)
            pct10 = np.zeros(M, dtype=np.int64)
            runs: list[list[int]] = []
            cur = None
            for x in readings:
                m = x["m"]
                state[m:] = st[x["state"]]
                kw10[m:] = int(round(x["kw"] * 10))
                pct10[m:] = int(round(x["pct"] * 10))
                if x["state"] == "Starting":
                    cur = [m, M, x["test"]]
                    runs.append(cur)
                elif x["state"] == "Stopped" and cur is not None:
                    cur[1] = m
                    cur = None
            for a, b, test in runs:
                if test:
                    ecs[a:b + 1] = 2                         # switched to Run for the monthly exercise, back to Auto after
            running = (state == st["Running"]) | (state == st["Cooldown"])
            loaded = kw10 > 0
            brk = np.where(loaded, 1, 0).astype(np.int64)
            for a, b, test in runs:
                if test:
                    loadbank[a:b] = True
            kw = kw10 / 10.0
            pf_g = float(r.uniform(*el["gen_pf"]))
            pfv = np.where(loaded, np.where(loadbank, 1.0, pf_g + r.normal(0, 0.001, M)), 0.0)
            pfv = np.minimum(pfv, 1.0)
            safe_pf = np.where(pfv > 0, pfv, 1.0)
            kvar = np.where(loaded, kw * np.sqrt(np.maximum(1 - safe_pf * safe_pf, 0.0)) / safe_pf, 0.0)
            on = running
            v = np.where(on, el["gen_v_ll"] * (1 + r.normal(0, 0.002, M)), 0.0)
            amps = np.where(loaded, kw * 1000 / (SQRT3 * np.where(v > 0, v, 1.0) * safe_pf), 0.0)
            hz = np.where(on, el["hz"] + r.normal(0, 0.02, M), 0.0)
            rpm = np.where(on, gc["rpm"] + r.normal(0, 1.5, M), np.where(state == st["Starting"], 160.0, 0.0))
            oil = np.where(on, r.uniform(*gc["oil_kpa_running"]) + r.normal(0, 2.0, M), 0.0)
            batt = np.where(on, float(r.uniform(*gc["battery_running_v"])), float(r.uniform(*gc["battery_float_v"]))) + r.normal(0, 0.02, M)
            batt = np.where(state == st["Starting"], 21.6 + r.normal(0, 0.1, M), batt)
            batt = np.round(batt / 0.05) * 0.05                              # the register's 0.05 V resolution
            frac = kw / rated
            # coolant and exhaust: first-order lags toward a target set by state and load (math.exp on scalars only)
            stand = float(r.uniform(*gc["standby_coolant_c"]))
            a_run = 1 - math.exp(-1 / gc["coolant_tau_min"])
            a_off = 1 - math.exp(-1 / 90.0)
            a_ex = 1 - math.exp(-1 / 3.0)
            tgt_c = np.where(on, stand + (gc["running_coolant_c"] - stand) * np.minimum(1.0, 0.55 + frac), stand)
            lo_ex, hi_ex = gc["exhaust_c"]
            tgt_e = np.where(on, lo_ex + (hi_ex - lo_ex) * frac, 35.0)
            cool = np.zeros(M)
            exh = np.zeros(M)
            c, e = stand, 35.0
            for m in range(M):
                c += (a_run if on[m] else a_off) * (tgt_c[m] - c)
                e += (a_ex if on[m] else a_off) * (tgt_e[m] - e)
                cool[m], exh[m] = c, e
            cool = cool + np.where(on, r.normal(0, 0.1, M), 0.0)
            # fuel and hours
            tank_l = gc["tank_hours_full_load"] * (gc["fuel_lph_idle"] + gc["fuel_lph_per_kw"] * rated)
            burn = np.where(on, (gc["fuel_lph_idle"] + gc["fuel_lph_per_kw"] * kw) / 60, 0.0)
            fuel = float(r.uniform(*gc["fuel_start_pct"])) - np.cumsum(burn) / tank_l * 100
            hours = float(r.uniform(*gc["hours_start"])) + np.cumsum(on.astype(np.float64)) / 60
            starts = int(r.integers(*gc["starts_start"])) + np.cumsum((state == st["Starting"]) & (np.r_[st["Stopped"], state[:-1]] != st["Starting"]))
            out[g] = {"state": state, "ecs": ecs, "brk": brk, "kw10": kw10, "pct10": pct10, "kvar": kvar, "pf": pfv, "v": v,
                      "amps": amps, "hz": hz, "rpm": rpm, "coolant": cool, "oil": oil, "batt": batt, "fuel": fuel, "hours": hours,
                      "exhaust": exh, "starts": starts, "readings": readings, "runs": runs, "loadbank": loadbank}
        return out

    # ----------------------------------------------------------------- states
    def states(self, taps: dict, runs: dict, ups: dict, gens: dict) -> list[dict]:
        """The state changes a client sees, each with the record it comes from."""
        out = []
        for u, x in ups.items():
            for e in x["modes"]["events"]:
                out.append({"device": u, "family": "ups", "time": e["timestamp"], "m": self.m_of(parse(e["timestamp"])),
                            "point": "upsBasicOutputStatus" if e["event"].startswith("upsBasic") else "Power module",
                            "value": e["event"].replace("upsBasicOutputStatus ", ""), "record": "facility/ups_nmc_events.jsonl"})
        for t, x in taps.items():
            for m, on, e in x["changes"]:
                note = "" if e["busway"] == x["run"] else f"the record names {e['busway']}; tap-off {t} is on {x['run']}"
                out.append({"device": t, "family": "tapoff", "time": e["timestamp"], "m": m, "point": "cpmAcBrkrCurrentStatus",
                            "value": "closed" if on else "open", "record": "facility/busway_cpm_events.jsonl", "note": note})
        for run, x in runs.items():
            for a, b, ea, eb in x["dead"]:
                out.append({"device": run, "family": "busway", "time": ea["timestamp"], "m": a, "point": "cpmAcInfLineToLineVoltAve",
                            "value": f"{ea['value_v']} V (out of tolerance)", "record": "facility/busway_cpm_events.jsonl"})
                if eb is not None:
                    out.append({"device": run, "family": "busway", "time": eb["timestamp"], "m": b, "point": "cpmAcInfLineToLineVoltAve",
                                "value": f"{eb['value_v']} V (in tolerance)", "record": "facility/busway_cpm_events.jsonl"})
            for e in self.epms:
                if e["device"].endswith(f"feeder to {run}"):
                    out.append({"device": run, "family": "busway", "time": e["timestamp"], "m": self.m_of(parse(e["timestamp"])),
                                "point": "Feeder breaker (EPMS)", "value": e["event"], "record": "facility/epms_events.jsonl"})
        for g, x in gens.items():
            prev = None
            for r in x["readings"]:
                if r["state"] != prev:
                    out.append({"device": g, "family": "generator", "time": r["time"], "m": r["m"], "point": "Automatic Start/Stop State",
                                "value": r["state"], "record": r["record"]})
                    prev = r["state"]
        for o in self.outages():
            for e in o["events"]:
                out.append({"device": "SITE", "family": "site", "time": e["timestamp"], "m": self.m_of(parse(e["timestamp"])),
                            "point": e["device"], "value": e["event"], "record": "facility/epms_events.jsonl"})
        return sorted(out, key=lambda s: (s["time"], s["device"], s["point"]))

    # ----------------------------------------------------------------- the month
    def run(self) -> dict[str, Any]:
        rack_w = self.rack_watts()
        dead = self.dead_runs()
        taps = self.tapoffs(rack_w, dead)
        bus = self.ups_bus()
        runs = self.run_series(taps, bus, dead)
        ups = self.ups_series(runs, bus)
        site_kw = self.site_load_kw(ups)
        gens = self.generator_series(site_kw)
        return {"tapoffs": taps, "runs": runs, "ups": ups, "gens": gens, "states": self.states(taps, runs, ups, gens),
                "outages": [{k: iso(v) if isinstance(v, datetime) else v for k, v in o.items() if k != "events"} for o in self.outages()]}


def _smooth(x: np.ndarray, tau: float) -> np.ndarray:
    """First-order lag (pandas ewm: the same numbers on every CPU)."""
    import pandas as pd
    return pd.Series(x).ewm(alpha=1 - math.exp(-1 / tau), adjust=False).mean().to_numpy()


# --------------------------------------------------------------------- publish
def device_fields(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every device's one-minute integer series (value x the field's scale), keyed by device id."""
    dev: dict[str, dict[str, Any]] = {}
    i = lambda a, s: np.round(np.asarray(a, dtype=np.float64) * s).astype(np.int64)     # noqa: E731
    for u, x in sorted(out["ups"].items()):
        kw = x["out_kw10"]
        dev[u] = {"family": "ups", "hall": x["hall"], "kind": x["kind"], "model": x["model"], "rating_kw": x["rating_kw"],
                  "eff": x["eff"], "modules": x["module_count"], "fields": {"source": x["source"], "in_v": i(x["in_v"], 1), "in_a": i(x["in_a"], 10), "in_hz": i(x["in_hz"], 10),
                             "in_kw": i(x["in_kw"], 10), "byp_v": i(x["byp_v"], 1), "out_v": i(x["out_v"], 1),
                             "out_a1": i(x["out_a"][0], 10), "out_a2": i(x["out_a"][1], 10), "out_a3": i(x["out_a"][2], 10),
                             "out_kw": kw,
                             "soc_pct": i(np.minimum(x["soc"], 100.0), 1), "runtime_s": i(x["runtime"] / 10, 1) * 10,
                             "batt_v": i(x["batt_v"], 10), "batt_a": i(x["batt_a"], 10), "batt_c": i(x["batt_c"], 1),
                             "modules_ok": x["modules"]}}
    for run, x in sorted(out["runs"].items()):
        a1, a2, a3 = x["a"]
        iavg = (a1 + a2 + a3) / 3
        v = x["v_ll"]
        s = SQRT3 * v * iavg / 1000
        pf = np.where(s > 0.5, np.minimum(x["kw10"] / 10 / np.where(s > 0, s, 1.0), 1.0), 0.0)
        dev[run] = {"family": "busway", "hall": x["hall"], "ups": x["ups"], "segment": x["segment"], "side": x["side"],
                    "racks": x["racks"], "tapoffs": x["tapoffs"],
                    "fields": {"v_ll": i(v, 10), "v_ln": i(v / SQRT3, 10), "a1": i(a1, 10), "a2": i(a2, 10), "a3": i(a3, 10),
                               "an": i(x["an"], 10), "kw": x["kw10"], "pf": i(pf, 1000), "hz": i(np.where(x["alive"], x["hz"], 0.0), 100),
                               "encl_c": i(x["encl"], 10)}}
    runs = out["runs"]
    for t, x in sorted(out["tapoffs"].items()):
        v = runs[x["run"]]["v_ll"]
        vb = np.where(v > 0, v, 1.0)
        base = x["w"] / (SQRT3 * vb * x["pf"])
        dev[t] = {"family": "tapoff", "hall": x["hall"], "rack": x["rack"], "side": x["side"], "run": x["run"],
                  "fields": {"kw": x["w"], "a1": i(base * x["imbalance"][0], 10), "a2": i(base * x["imbalance"][1], 10),
                             "a3": i(base * x["imbalance"][2], 10), "pf": np.where(x["w"] > 0, int(round(x["pf"] * 1000)), 0).astype(np.int64),
                             "brk": x["closed"].astype(np.int64)}}
    for g, x in sorted(out["gens"].items()):
        dev[g] = {"family": "generator", "fields": {
            "state": x["state"], "ecs": x["ecs"], "brk": x["brk"], "kw": x["kw10"], "pct_kw": x["pct10"], "kvar": i(x["kvar"], 10),
            "pf": i(x["pf"], 100), "v_ll": i(x["v"], 1), "amps": i(x["amps"], 1), "hz": i(x["hz"], 100), "rpm": i(x["rpm"], 1),
            "coolant_c": i(x["coolant"], 10), "oil_kpa": i(x["oil"], 1), "batt_v": i(x["batt"], 100), "fuel_pct": i(x["fuel"], 10),
            "hours": i(x["hours"], 100), "exhaust_c": i(x["exhaust"], 1), "starts": np.asarray(x["starts"], dtype=np.int64)}}
    return dev


def hourly_rows(dev: dict[str, dict], out: dict[str, Any], start: datetime, M: int) -> dict[str, list[dict]]:
    H = M // HOUR_MIN
    sh = (H, HOUR_MIN)
    hours = [iso(start + h * HOUR_MIN * MIN) for h in range(H)]
    ups_rows, run_rows, tap_rows, gen_rows = [], [], [], []
    for u, d in dev.items():
        f = d["fields"]
        if d["family"] == "ups":
            x = out["ups"][u]
            kw, ikw = f["out_kw"].reshape(sh), f["in_kw"].reshape(sh)
            load = np.round(f["out_kw"] * 100 / d["rating_kw"]).astype(np.int64).reshape(sh)
            amax = np.maximum(np.maximum(f["out_a1"], f["out_a2"]), f["out_a3"]).reshape(sh)
            soc, mods = f["soc_pct"].reshape(sh), f["modules_ok"].reshape(sh)
            byp = (x["bypass_frac"] > 0).reshape(sh)
            bat = (x["battery_frac"] * 60).reshape(sh)
            for h in range(H):
                ups_rows.append({"hour": hours[h], "ups": u, "hall": d["hall"], "kind": d["kind"],
                                 "out_kwh": round(int(kw[h].sum()) / 600, 2), "in_kwh": round(int(ikw[h].sum()) / 600, 2),
                                 "load_avg_pct": round(int(load[h].sum()) / 600, 1), "load_max_pct": round(int(load[h].max()) / 10, 1),
                                 "amps_max": round(int(amax[h].max()) / 10, 1), "soc_min_pct": int(soc[h].min()),
                                 "bypass_min": int(byp[h].sum()), "battery_s": int(round(float(bat[h].sum()))), "modules_min": int(mods[h].min())})
        elif d["family"] == "busway":
            kw = f["kw"].reshape(sh)
            iavg = ((f["a1"] + f["a2"] + f["a3"]) / 3).reshape(sh)
            amax = np.maximum(np.maximum(f["a1"], f["a2"]), f["a3"]).reshape(sh)
            v = f["v_ll"].reshape(sh)
            enc = f["encl_c"].reshape(sh)
            for h in range(H):
                run_rows.append({"hour": hours[h], "run": u, "hall": d["hall"], "ups": d["ups"], "kwh": round(int(kw[h].sum()) / 600, 2),
                                 "amps_avg": round(float(iavg[h].mean()) / 10, 1), "amps_max": round(int(amax[h].max()) / 10, 1),
                                 "v_min": round(int(v[h].min()) / 10, 1), "v_max": round(int(v[h].max()) / 10, 1),
                                 "dead_min": int((v[h] == 0).sum()), "encl_max_c": round(int(enc[h].max()) / 10, 1)})
        elif d["family"] == "tapoff":
            if not (f["kw"].any() or (f["brk"] == 0).any()):
                continue
            kw = f["kw"].reshape(sh)
            amax = np.maximum(np.maximum(f["a1"], f["a2"]), f["a3"]).reshape(sh)
            op = (f["brk"] == 0).reshape(sh)
            for h in range(H):
                tap_rows.append({"hour": hours[h], "tapoff": u, "rack": d["rack"], "kwh": round(int(kw[h].sum()) / 60000, 3),
                                 "amps_max": round(int(amax[h].max()) / 10, 1), "open_min": int(op[h].sum())})
        else:
            st = f["state"].reshape(sh)
            kw = f["kw"].reshape(sh)
            pct = f["pct_kw"].reshape(sh)
            cool = f["coolant_c"].reshape(sh)
            for h in range(H):
                gen_rows.append({"hour": hours[h], "generator": u, "run_min": int((st[h] >= 2).sum()),
                                 "kwh": round(int(kw[h].sum()) / 600, 2), "kw_max": round(int(kw[h].max()) / 10, 1),
                                 "pct_max": round(int(pct[h].max()) / 10, 1), "coolant_max_c": round(int(cool[h].max()) / 10, 1),
                                 "fuel_pct": round(int(f["fuel_pct"][(h + 1) * HOUR_MIN - 1]) / 10, 1),
                                 "hours": round(int(f["hours"][(h + 1) * HOUR_MIN - 1]) / 100, 2)})
    return {"ups_hourly.csv": ups_rows, "busway_hourly.csv": run_rows, "tapoff_hourly.csv": tap_rows, "generator_hourly.csv": gen_rows}


def _windows(dev: dict[str, dict], states: list[dict], M: int, start: datetime, before: int, after: int) -> list[dict]:
    """One-minute windows around every state change, per device (merged where they overlap). A site event (the utility
    outage) opens a window on every UPS and generator."""
    spans: dict[str, list[tuple[int, int]]] = {}
    for s in states:
        targets = [s["device"]]
        if s["device"] == "SITE":
            targets = [d for d, x in dev.items() if x["family"] in ("ups", "generator")]
        elif s["family"] == "tapoff":
            targets.append(dev[s["device"]]["run"])
        elif s["family"] == "busway":
            targets.append(dev[s["device"]]["ups"])
        for t in targets:
            spans.setdefault(t, []).append((max(0, s["m"] - before), min(M, s["m"] + after)))
    out = []
    for d in sorted(spans):
        merged: list[list[int]] = []
        for a, b in sorted(spans[d]):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        for a, b in merged:
            out.append({"device": d, "family": dev[d]["family"], "from": iso(start + a * MIN), "minutes": b - a, "m0": a,
                        "fields": {k: v[a:b].tolist() for k, v in dev[d]["fields"].items()},
                        "states": [s for s in states if a <= s["m"] < b and s["device"] in (d, "SITE")]})
    return out


def write_power(layer: PowerTelemetry, out: dict[str, Any], dest: str | Path, source: str = "",
                minutes_dest: str | Path | None = None) -> dict[str, Any]:
    """Write the committed tiers to dest and the publish-time tier to minutes_dest if given."""
    cfg = layer.cfg
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    win = dest / "windows"
    if win.exists():
        for p in win.glob("*.json"):
            p.unlink()
    win.mkdir(exist_ok=True)
    dev = device_fields(out)
    tables = hourly_rows(dev, out, layer.start, layer.M)
    cols = {"ups_hourly.csv": UPS_HOURLY, "busway_hourly.csv": RUN_HOURLY, "tapoff_hourly.csv": TAP_HOURLY,
            "generator_hourly.csv": GEN_HOURLY}
    taps = tables.pop("tapoff_hourly.csv")
    for name, rows in tables.items():
        (dest / name).write_text(_csv(rows, cols[name]), encoding="utf-8", newline="\n")
    states = out["states"]
    (dest / "states.jsonl").write_text("".join(json.dumps(s, sort_keys=True) + "\n" for s in states), encoding="utf-8", newline="\n")
    index = []
    for w in _windows(dev, states, layer.M, layer.start, cfg["tiers"]["window_before_min"], cfg["tiers"]["window_after_min"]):
        name = f"{w['device']}_{w['from'][:16].replace('-', '').replace(':', '')}"
        (win / f"{name}.json").write_text(_dump(w), encoding="utf-8", newline="\n")
        index.append({"file": f"windows/{name}.json", "device": w["device"], "from": w["from"], "minutes": w["minutes"]})
    # publish-time tier: every UPS and generator minute by minute, and every tap-off hour by hour (busway runs and
    # tap-offs keep minutes only in the windows around their events: raw for the events, rollups for the month)
    minutes = {}
    for d, x in sorted(dev.items()):
        if x["family"] not in ("ups", "generator"):
            continue
        meta = {k: v for k, v in x.items() if k != "fields"}
        minutes[f"{d}.json"] = _dump({"device": d, **meta, "start": iso(layer.start), "minutes": layer.M,
                                      "encoding": "first value, then minute-to-minute steps; [n] is n minutes unchanged; divide by the field's scale",
                                      "fields": {k: pack(v) for k, v in x["fields"].items()}})
    by_tap: dict[str, dict] = {}
    for r in taps:
        t = by_tap.setdefault(r["tapoff"], {"rack": r["rack"], "wh": [], "amps_max": [], "open_min": []})
        t["wh"].append(int(round(r["kwh"] * 1000)))
        t["amps_max"].append(r["amps_max"])
        t["open_min"].append(r["open_min"])
    for t, x in out["tapoffs"].items():
        if t in by_tap:
            by_tap[t].update(run=x["run"], side=x["side"], pf=x["pf"], imbalance=x["imbalance"])
    minutes["tapoff_hourly.json"] = _dump({"start": iso(layer.start), "hours": layer.M // HOUR_MIN,
                                           "note": "tap-offs that carried load or opened this month; Wh per hour",
                                           "tapoffs": by_tap})
    if minutes_dest is not None:
        md = Path(minutes_dest)
        md.mkdir(parents=True, exist_ok=True)
        for name, text in minutes.items():
            (md / name).write_text(text, encoding="utf-8", newline="\n")
    devices = {d: {k: v for k, v in x.items() if k not in ("fields",)} for d, x in sorted(dev.items())}
    man = {"disclaimer": "Synthetic power telemetry for a portfolio demonstration, using the manufacturers' published SNMP "
                         "and Modbus point maps. All names and readings are fictional.",
           "source": source, "window": {"start": iso(layer.start), "end": iso(layer.end)},
           "devices": devices, "outages": out["outages"],
           "files": {**{k: len(v) for k, v in tables.items()}, "states.jsonl": len(states), "windows": len(index)},
           "windows": index,
           "minutes": {name: {"sha256": hashlib.sha256(t.encode()).hexdigest(), "bytes": len(t.encode())}
                       for name, t in minutes.items()}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
