"""Synthetic CDU telemetry for Site AUS-1, in the published DMTF Redfish schema for cooling units.

Portfolio demo; all data fictional. Runs on a finished month after its GPU health layer, its energy meters,
and its GPU telemetry, with its own random stream, and writes beside them, never into them.

Every CDU is read once a minute over Redfish (the Customer's read-only account on the Landlord's CDUs):
the CoolingUnit, its primary (facility water) and secondary (rack loop) CoolantConnectors, two Pumps, the
secondary Filter, the Reservoir, two LeakDetectors, and EnvironmentMetrics. The series are shaped to agree
with every record already written for the month:

* the hourly secondary supply mean and max and flow mean and min (``gpu_health/cdu_hourly.csv``);
* every Redfish event in ``facility/cdu_redfish_events.jsonl`` (pump isolations, failures, tests,
  redundancy) at its minute: a failed pump was the duty pump, and flow dips while the standby ramps;
* the leaks the BMS and the leak detection controllers recorded, on the CDU's own detectors;
* the filter changes in the Landlord's PM records (filter differential pressure falls only then);
* the facility water supply temperature in ``energy/meters_hourly.csv`` on the primary side;
* the heat of the racks on each hall's shared secondary header, from the GPU telemetry minute by minute.

Published tiers (see ``write_cdu``): ``cdu_hourly.csv``, ``states.jsonl``, and ``windows/`` committed; the
one-minute series per CDU (``minutes/<cdu>.json``) built at publish time with checksums in the manifest.
Settings and every assumption: ``config/telemetry_cdu.yaml``.
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
                                           rack_input_w)

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "telemetry_cdu.yaml"
HOUR_MIN = 60

HOURLY_COLUMNS = ["hour", "cdu", "hall", "supply_c", "supply_max_c", "return_c", "flow_lpm", "flow_min_lpm", "dp_kpa",
                  "heat_kwh", "pri_supply_c", "pri_return_c", "pri_flow_lpm", "valve_pct", "pump1_pct", "pump2_pct",
                  "filter_dp_kpa", "reservoir_pct", "power_kwh", "leak_min", "redundancy_lost_min"]


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rng(seed: int, *parts: object) -> np.random.Generator:
    key = ":".join(str(p) for p in (seed, "telemetry", "cdu") + parts)
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def pin(base: np.ndarray, mean_u: int, ext_u: int, sign: int) -> np.ndarray:
    """Integers shaped like ``base`` whose sum is exactly 60 * mean_u and whose max (sign 1) or min (sign -1)
    is exactly ext_u: an hour of one-minute readings that reproduces the hourly record to the last digit."""
    n = len(base)
    s = base - base.mean()
    k = int(np.argmax(sign * s))
    v = np.full(n, float(mean_u))
    if sign * s[k] > 1e-9:
        v = mean_u + (ext_u - mean_u) / s[k] * s
    v = np.round(v).astype(np.int64)
    v[k] = ext_u
    v = np.minimum(v, ext_u) if sign > 0 else np.maximum(v, ext_u)
    v[k] = ext_u
    resid = n * mean_u - int(v.sum())
    order = [i for i in np.argsort(np.abs(s), kind="stable") if i != k]
    while resid:
        step = 1 if resid > 0 else -1
        moved = False
        for i in order:
            if not resid:
                break
            nv = v[i] + step
            if (sign > 0 and nv > ext_u) or (sign < 0 and nv < ext_u):
                continue
            v[i] = nv
            resid -= step
            moved = True
        if not moved:
            raise ValueError("cannot pin an hour to its record")
    return v


def _ar(rng: np.random.Generator, n: int, sd: float, rho: float) -> np.ndarray:
    """AR(1) noise with stationary sd (pandas ewm: the same numbers on every CPU)."""
    e = rng.normal(0, sd * math.sqrt(1 - rho * rho), n)
    return pd.Series(e).ewm(alpha=1 - rho, adjust=False).mean().to_numpy() / (1 - rho)


def delta(a: np.ndarray) -> list[int]:
    """An integer series as its first value and the steps after it (small numbers: a compact file)."""
    a = np.asarray(a, dtype=np.int64)
    return [int(a[0])] + np.diff(a).tolist() if len(a) else []


def undelta(d: list[int]) -> np.ndarray:
    return np.cumsum(np.asarray(d, dtype=np.int64))


class CduTelemetry:
    """One-minute Redfish readings for every CDU serving a hall with GPU telemetry."""

    def __init__(self, tel: GpuTelemetry, pub: Published, energy_dir: str | Path | None = None,
                 history_dir: str | Path | None = None, cfg: dict[str, Any] | None = None, site: dict | None = None):
        self.tel, self.pub = tel, pub
        self.cfg = cfg or load_config()
        self.site = site or S.load_site()
        self.seed, self.start, self.end, self.M = tel.seed, tel.start, tel.end, tel.M
        self.H = self.M // HOUR_MIN
        self.hc = tel.hcfg["cdu"]
        d = tel.dir
        self.halls = {r["cdu"]: r["hall"] for r in tel.layer.racks}
        self.cdus = sorted(self.halls)
        self.records = {(r["cdu"], r["hour"]): r for r in _csv_rows(tel.hdir / "cdu_hourly.csv")}
        self.events = sorted(tel.layer.cdu_events, key=lambda e: (e["timestamp"], e["resource"], e["property"]))
        self.bms_leaks = _jsonl(d / "telemetry" / "bms_cdu_events.jsonl")
        self.leak_events = _jsonl(d / "facility" / "leak_events.jsonl")
        pm = [r for r in _csv_rows(d / "landlord" / "pm_records.csv") if r.get("system") == "CDUs" and "Filter" in r.get("task", "")]
        hist = [r for r in _csv_rows(Path(history_dir) / "landlord" / "pm_records.csv")] if history_dir else []
        self.filter_done = {c: sorted(parse(r["completed_at"]) for r in pm if r["asset"] == c and r.get("completed_at")) for c in self.cdus}
        self.filter_due = {c: min((parse(r["due_start"]) for r in pm if r["asset"] == c and r.get("due_start")), default=None)
                           for c in self.cdus}
        self.filter_before = {c: max((parse(r["completed_at"]) for r in hist if r["asset"] == c and "Filter" in r["task"]
                                      and parse(r["completed_at"]) < self.start), default=None) for c in self.cdus}
        meters = _csv_rows(Path(energy_dir) / "meters_hourly.csv") if energy_dir else []
        self.fw = {r["hour"]: float(r["fw_supply_c"]) for r in meters}
        self.excursions = [x for x in tel.key.get("excursions", [])]
        self.conflicts: list[str] = []

    # ----------------------------------------------------------------- time helpers
    def m_of(self, t: datetime) -> int:
        return self.tel.m_of(t)

    def t_of(self, m: int) -> datetime:
        return self.tel.t_of(m)

    def hourly(self, vals: list[float]) -> np.ndarray:
        """Hourly values to minutes, interpolated between hour midpoints."""
        mids = np.arange(len(vals)) * HOUR_MIN + 30
        return np.interp(np.arange(self.M), mids, np.asarray(vals, dtype=float))

    # ----------------------------------------------------------------- heat on each hall's header
    def hall_heat_kw(self) -> dict[str, np.ndarray]:
        rr = self.cfg["rack_rest"]
        out: dict[str, np.ndarray] = {}
        for rack, x in sorted(self.pub.rack_load.items()):
            lf = S.product(self.site, x["product"])["liquid_fraction"]
            it_w = rack_input_w(x["n"], x["gpu_w"], rr)
            out[x["hall"]] = out.get(x["hall"], np.zeros(self.M)) + lf * it_w / 1000
        lag = self.cfg["heat_lag_min"]
        a = 1 - math.exp(-1 / lag)
        return {h: pd.Series(q).ewm(alpha=a, adjust=False).mean().to_numpy() for h, q in out.items()}

    # ----------------------------------------------------------------- records as minute spans
    def _cdu_events(self, cdu: str) -> list[dict]:
        return [dict(e, m=self.m_of(parse(e["timestamp"]))) for e in self.events if e["cdu"] == cdu]

    def pump_spans(self, cdu: str) -> dict[str, Any]:
        """Per pump: minutes it cannot run (failed, isolated) and minutes in test; failures; redundancy loss."""
        out = {"down": {1: np.zeros(self.M, bool), 2: np.zeros(self.M, bool)},
               "test": {1: np.zeros(self.M, bool), 2: np.zeros(self.M, bool)},
               "fail": [], "redundancy": np.zeros(self.M, bool)}
        open_: dict[tuple, int] = {}
        for e in self._cdu_events(cdu):
            res, prop, val, m = e["resource"], e["property"], e["value"], e["m"]
            if "/Pumps/" in res:
                p = int(res.rsplit("/", 1)[1])
                if prop == "Status.Health" and val == "Critical":
                    open_[("crit", p)] = m
                    out["fail"].append((p, m, parse(e["timestamp"])))
                elif prop == "Status.Health" and val == "OK":
                    for kind in ("crit", "test"):
                        if (kind, p) in open_:
                            a = open_.pop((kind, p))
                            (out["down"] if kind == "crit" else out["test"])[p][a:m] = True
                elif prop == "Status.State" and val == "Disabled":
                    open_[("dis", p)] = m
                elif prop == "Status.State" and val == "Enabled" and ("dis", p) in open_:
                    out["down"][p][open_.pop(("dis", p)):m] = True
                elif prop == "Status.State" and val == "InTest":
                    if ("crit", p) in open_:
                        out["down"][p][open_.pop(("crit", p)):m] = True
                    open_[("test", p)] = m
            elif prop == "PumpRedundancy.Status.Health":
                if val == "OK" and "red" in open_:
                    out["redundancy"][open_.pop("red"):m] = True
                elif val != "OK":
                    open_.setdefault("red", m)
        for (kind, p), a in open_.items():          # still open at the end of the month
            if kind == "red":
                out["redundancy"][a:] = True
            else:
                (out["test"] if kind == "test" else out["down"])[p][a:] = True
        return out

    def duty(self, cdu: str, sp: dict) -> np.ndarray:
        """The duty pump each minute: lead-lag rotation weekly, a failed pump was the one running (the records
        show a flow dip at every failure), and an isolated or failed pump hands over to the other."""
        rot = self.cfg["unit"]["rotation_hours"] * HOUR_MIN
        r = _rng(self.seed, cdu, "rotation")
        offset, phase = int(r.integers(0, rot)), int(r.integers(0, 2))
        forced = {}
        for p, m, _t in sp["fail"]:
            forced.setdefault((m + offset) // rot, p)
        pre = {max(0, m - 1): p for p, m, _t in sp["fail"]}
        duty = np.zeros(self.M, dtype=np.int8)
        cur, last_period = None, None
        down = sp["down"]
        for m in range(self.M):
            j = (m + offset) // rot
            if j != last_period:
                want = forced.get(j, 1 + (j + phase) % 2)
                if cur is None or not down[want][m]:
                    cur = want
                last_period = j
            if m in pre and not down[pre[m]][m]:
                cur = pre[m]                                   # a changeover ahead of the recorded failure
            if down[cur][m]:
                other = 3 - cur
                if not down[other][m]:
                    cur = other
            duty[m] = cur
        for p, m, t in sp["fail"]:
            if m > 0 and duty[m - 1] != p:
                self.conflicts.append(f"{cdu} pump {p} failed at {iso(t)} while it was not the duty pump")
        return duty

    def leak_spans(self, cdu: str) -> dict[int, list[tuple[int, int, str]]]:
        """Detector 1 (under the unit, its TTDM circuit) and 2 (the row leak rope) from the recorded leaks."""
        out: dict[int, list[tuple[int, int, str]]] = {1: [], 2: []}
        on: dict[tuple, int] = {}
        for e in sorted(self.bms_leaks, key=lambda e: e["timestamp"]):
            if e.get("cdu") != cdu or e.get("alarm") != "LeakDetected":
                continue
            k = (2, e.get("point", ""))
            if e["state"] == "active":
                on.setdefault(k, self.m_of(parse(e["timestamp"])))
            elif k in on:
                out[2].append((on.pop(k), self.m_of(parse(e["timestamp"])), e.get("point", "")))
        for e in sorted(self.leak_events, key=lambda e: e["timestamp"]):
            if e.get("label") != f"Under {cdu}":
                continue
            k = (1, e["label"])
            if e["event"] == "LEAK":
                on.setdefault(k, self.m_of(parse(e["timestamp"])))
            elif e["event"] == "NORMAL" and k in on:
                out[1].append((on.pop(k), self.m_of(parse(e["timestamp"])), e["label"]))
        for (det, label), a in on.items():
            out[det].append((a, self.M, label))
        return out

    # ----------------------------------------------------------------- one CDU
    def cdu(self, cdu: str, heat: np.ndarray, t_ret_hall: np.ndarray,
            supply_c: np.ndarray, flow: np.ndarray) -> dict[str, Any]:
        """Everything but the secondary supply and flow (shared with the hall and set first)."""
        cfg, M = self.cfg, self.M
        u, sec, pri = cfg["unit"], cfg["secondary"], cfg["primary"]
        co, wa = cfg["coolant"], cfg["water"]
        rng = _rng(self.seed, cdu, "readings")
        f = {}
        f["sec_supply_c"] = supply_c
        f["sec_flow_lpm"] = flow
        sup = supply_c / 100.0
        fl = flow / 10.0
        ret = t_ret_hall + rng.normal(0, sec["sensor_noise_c"], M)        # the shared header's return (no load: about the supply)
        f["sec_return_c"] = np.round(ret * 100).astype(np.int64)
        f["sec_dt_c"] = f["sec_return_c"] - f["sec_supply_c"]
        mdot = fl / 60.0 * co["density_kg_per_l"]
        heat_meter = mdot * co["cp_kj_per_kg_k"] * (f["sec_dt_c"] / 100.0)             # the CDU's own heat calculation
        f["heat_kw"] = np.round(heat_meter * 10).astype(np.int64)
        r = fl / self.hc["flow_lpm"]
        r2 = r * r
        sp_kpa = sec["supply_kpa_static"] + sec["pump_head_kpa"] * r2 + rng.normal(0, 0.4, M)
        dp = sec["loop_dp_kpa"] * r2 + rng.normal(0, 0.3, M)
        f["sec_supply_kpa"] = np.round(sp_kpa * 10).astype(np.int64)
        f["sec_return_kpa"] = np.round((sp_kpa - dp) * 10).astype(np.int64)
        f["sec_dp_kpa"] = f["sec_supply_kpa"] - f["sec_return_kpa"]
        f["setpoint_c"] = np.full(M, int(round(self.hc["setpoint_c"] * 100)), dtype=np.int64)

        # primary: facility water in at the metered temperature; the valve opens with the load
        fw = self.fw_minutes(rng)
        q_true = np.maximum(heat, 0)
        dtp = np.clip(t_ret_hall - pri["hot_end_approach_c"] - fw, 0.5, pri["max_dt_c"])
        pflow = np.maximum(pri["min_flow_lpm"], q_true / (wa["density_kg_per_l"] * wa["cp_kj_per_kg_k"] * dtp) * 60)
        pflow = np.minimum(pflow, u["rated_primary_flow_lpm"])
        pret = fw + q_true / (pflow / 60 * wa["density_kg_per_l"] * wa["cp_kj_per_kg_k"])
        f["pri_supply_c"] = np.round(fw * 100).astype(np.int64)
        f["pri_return_c"] = np.round(pret * 100).astype(np.int64)
        f["pri_flow_lpm"] = np.round(pflow * 10).astype(np.int64)
        pr = pflow / u["rated_primary_flow_lpm"]
        f["pri_dp_kpa"] = np.round((pri["dp_kpa_at_rated"] * pr * pr + rng.normal(0, 0.3, M)) * 10).astype(np.int64)
        f["valve_pct"] = np.round(np.clip(pr * 100 + rng.normal(0, 0.3, M), 0, 100) * 10).astype(np.int64)

        # pumps
        sp = self.pump_spans(cdu)
        duty = self.duty(cdu, sp)
        speed = {1: np.zeros(M), 2: np.zeros(M)}
        run = u["duty_speed_pct"] * r + rng.normal(0, 0.15, M)
        for p in (1, 2):
            speed[p] = np.where(duty == p, run, 0.0)
            speed[p] = np.where(sp["test"][p], 60.0 + rng.normal(0, 0.15, M), speed[p])
            speed[p] = np.where(sp["down"][p], 0.0, speed[p])
            f[f"pump{p}_pct"] = np.round(np.clip(speed[p], 0, 100) * 10).astype(np.int64)
        kw_rated, lpm_rated = u["pump_kw_at_1500_lpm"], 1500.0
        x = fl / lpm_rated
        pump_w = kw_rated * 1000 * x * x * x
        test_w = sum(np.where(sp["test"][p], kw_rated * 1000 * 0.216, 0) for p in (1, 2))      # 60% speed: 0.6 cubed
        f["power_w"] = np.round(pump_w + test_w + u["controls_w"] + rng.normal(0, 40, M)).astype(np.int64)

        # filter: loads up between changes, falls at each recorded change; pressure drop scales with flow squared
        fc = cfg["filter"]
        prior = self.filter_before[cdu]
        if prior is None:                     # no history: the last change one interval before this month's was due,
            fr = _rng(self.seed, cdu, "filter")  # or, with none due this month, recent enough not to fall due
            due = self.filter_due[cdu]
            days = fc["rated_service_days"]
            prior = (due - timedelta(days=days) + timedelta(hours=float(fr.uniform(-48, 48)))) if due else \
                self.start - timedelta(days=float(fr.uniform(5, days - (self.end - self.start).days - 3)))
        resets = [self.m_of(t) for t in self.filter_done[cdu]]
        age = (np.arange(M) / 1440.0) + (self.start - prior).total_seconds() / 86400
        for m in resets:
            age[m:] = (np.arange(M - m)) / 1440.0
        f["filter_dp_kpa"] = np.round(((fc["clean_kpa"] + fc["rise_kpa_per_day"] * age) * r2 + rng.normal(0, 0.1, M)) * 10).astype(np.int64)

        # reservoir: steady, falling only while a recorded leak is active, topped up 30 minutes after it clears
        rc = cfg["reservoir"]
        base = float(_rng(self.seed, cdu, "reservoir").uniform(*rc["level_pct"]))
        lvl = np.full(M, base)
        leaks = self.leak_spans(cdu)
        for det in (1, 2):
            for a, b, _l in leaks[det]:
                drop = np.minimum(np.arange(M - a), b - a) * rc["leak_loss_pct_per_hour"] / 60
                lvl[a:] -= drop
                lvl[min(M, b + 30):] += drop[min(M, b + 30) - a:] if b + 30 < M else 0
        f["reservoir_pct"] = np.round((lvl + rng.normal(0, 0.03, M)) * 10).astype(np.int64)

        # environment at the CDU (hourly with a daily cycle, interpolated): math functions per hour, not numpy's
        rm = cfg["room"]
        er = _rng(self.seed, cdu, "room")
        t0, rh0 = float(er.uniform(*rm["temp_c"])), float(er.uniform(*rm["rh_pct"]))
        th, hh, dh = [], [], []
        for h in range(self.H):
            local = (self.t_of(h * HOUR_MIN).hour - 5) % 24
            wave = round(math.sin(2 * math.pi * (local - 9) / 24), 9)
            tc = t0 + 0.6 * wave + float(er.normal(0, 0.1))
            rh = rh0 - 3.0 * wave + float(er.normal(0, 0.5))
            g = round(math.log(rh / 100), 9) + 17.62 * tc / (243.12 + tc)                    # Magnus formula
            th.append(tc), hh.append(rh), dh.append(243.12 * g / (17.62 - g))
        f["room_c"] = np.round(self.hourly(th) * 10).astype(np.int64)
        f["rh_pct"] = np.round(self.hourly(hh) * 10).astype(np.int64)
        f["dew_c"] = np.round(self.hourly(dh) * 10).astype(np.int64)

        hall = self.halls[cdu]
        sh = _rng(self.seed, cdu, "service")
        lo, hi = cfg["service_hours"].get(hall, [500, 5000])
        states = self.states(cdu, sp, leaks)
        return {"cdu": cdu, "hall": hall, "fields": f, "duty": duty, "pumps": sp, "leaks": leaks, "states": states,
                "service_hours_start": [round(float(sh.uniform(lo, hi)), 1), round(float(sh.uniform(lo, hi)), 1)],
                "filter_serviced": [iso(prior)] + [iso(t) for t in self.filter_done[cdu]]}

    def fw_minutes(self, rng: np.random.Generator) -> np.ndarray:
        """Facility water supply: smooth through the hours, each hour's mean the metered hourly value."""
        vals = []
        for h in range(self.H):
            k = iso(self.t_of(h * HOUR_MIN))
            vals.append(self.fw.get(k, self.cfg["primary"]["supply_c_if_unmetered"]))
        x = self.hourly(vals) + rng.normal(0, 0.02, self.M)
        sh = (self.H, HOUR_MIN)
        return (x.reshape(sh) - x.reshape(sh).mean(axis=1, keepdims=True) + np.asarray(vals)[:, None]).reshape(-1)

    def states(self, cdu: str, sp: dict, leaks: dict) -> list[dict]:
        """The state changes a Redfish client sees: the recorded events, a pump in test back to Enabled when its
        health returns to OK, and the leak detectors on the recorded leaks."""
        out = []
        intest: set[int] = set()
        for e in self._cdu_events(cdu):
            out.append({"m": e["m"], "time": e["timestamp"], "resource": e["resource"], "property": e["property"],
                        "value": e["value"], "record": "facility/cdu_redfish_events.jsonl"})
            if "/Pumps/" in e["resource"]:
                p = int(e["resource"].rsplit("/", 1)[1])
                if e["property"] == "Status.State" and e["value"] == "InTest":
                    intest.add(p)
                elif e["property"] == "Status.Health" and e["value"] == "OK" and p in intest:
                    intest.discard(p)
                    out.append({"m": e["m"], "time": e["timestamp"], "resource": e["resource"], "property": "Status.State",
                                "value": "Enabled", "record": "derived: test finished with the pump's health back to OK"})
        base = f"{self.cfg['collection']['base_uri']}/{cdu}/LeakDetection/LeakDetectors"
        for det, spans in leaks.items():
            for a, b, label in spans:
                src = "telemetry/bms_cdu_events.jsonl" if det == 2 else "facility/leak_events.jsonl"
                out.append({"m": a, "time": iso(self.t_of(a)), "resource": f"{base}/{det}", "property": "DetectorState",
                            "value": "Critical", "record": src, "note": label})
                if b < self.M:
                    out.append({"m": b, "time": iso(self.t_of(b)), "resource": f"{base}/{det}", "property": "DetectorState",
                                "value": "OK", "record": src, "note": label})
        return sorted(out, key=lambda s: (s["m"], s["resource"], s["property"]))

    # ----------------------------------------------------------------- the month
    def supply_and_flow(self, cdu: str) -> tuple[np.ndarray, np.ndarray]:
        """Secondary supply (hundredths) and flow (tenths), pinned hour by hour to cdu_hourly.csv."""
        M, sec = self.M, self.cfg["secondary"]
        rng = _rng(self.seed, cdu, "loop")
        s = self.tel.supply(cdu) + _ar(rng, M, sec["supply_noise_c"], 0.9)
        fl = self.hc["flow_lpm"] + _ar(rng, M, 6.0, 0.8)
        for x in self.excursions:
            if x["cdu"] != cdu:
                continue
            a, b = self.m_of(parse(x["start"])), self.m_of(parse(x["end"]))
            ramp = np.minimum(np.minimum(np.arange(b - a) + 1, b - a - np.arange(b - a)), 6) / 6.0
            s[a:b] += 5.0 * ramp
            fl[a:b] -= 700.0 * ramp
        for p, m, t in self.pump_spans(cdu)["fail"]:
            h_end = (int((t - self.start).total_seconds()) // 3600 + 1) * HOUR_MIN
            dm = min(m, h_end - 1)
            for i, k in enumerate((1.0, 0.35, 0.1)):
                if dm + i < M:
                    fl[dm + i] -= 220.0 * k
        supply = np.zeros(M, dtype=np.int64)
        flow = np.zeros(M, dtype=np.int64)
        for h in range(self.H):
            rec = self.records.get((cdu, iso(self.t_of(h * HOUR_MIN))))
            sl = slice(h * HOUR_MIN, (h + 1) * HOUR_MIN)
            if rec is None:
                self.conflicts.append(f"{cdu} has no cdu_hourly record for hour {h}")
                supply[sl] = np.round(s[sl] * 100)
                flow[sl] = np.round(fl[sl] * 10)
                continue
            supply[sl] = pin(s[sl] * 100, round(float(rec["supply_c"]) * 100), round(float(rec["supply_max_c"]) * 100), 1)
            flow[sl] = pin(fl[sl] * 10, int(rec["flow_lpm"]) * 10, int(rec["flow_min_lpm"]) * 10, -1)
        return supply, flow

    def run(self) -> dict[str, Any]:
        co = self.cfg["coolant"]
        heat = self.hall_heat_kw()
        loops = {c: self.supply_and_flow(c) for c in self.cdus}
        out: dict[str, Any] = {}
        for hall in sorted(set(self.halls.values())):
            cdus = [c for c in self.cdus if self.halls[c] == hall]
            q = heat.get(hall, np.zeros(self.M))
            mdot = {c: loops[c][1] / 10.0 / 60.0 * co["density_kg_per_l"] for c in cdus}
            tot = sum(mdot.values())
            mix = sum(mdot[c] * loops[c][0] / 100.0 for c in cdus) / tot
            t_ret = mix + q / (tot * co["cp_kj_per_kg_k"])
            for c in cdus:
                q_c = mdot[c] * co["cp_kj_per_kg_k"] * (t_ret - loops[c][0] / 100.0)
                out[c] = self.cdu(c, q_c, t_ret, loops[c][0], loops[c][1])
        self.hall_load = heat
        return out


# --------------------------------------------------------------------- publish
def _windows(cdu: dict, M: int, start: datetime, before: int, after: int, keys: list[str]) -> list[dict]:
    """One-minute windows around every state change and recorded flow dip (merged where they overlap)."""
    spans = []
    for s in cdu["states"]:
        spans.append((max(0, s["m"] - before), min(M, s["m"] + after)))
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        out.append({"cdu": cdu["cdu"], "hall": cdu["hall"], "from": iso(start + a * MIN), "minutes": b - a, "m0": a,
                    "fields": {k: cdu["fields"][k][a:b].tolist() for k in keys},
                    "states": [s for s in cdu["states"] if a <= s["m"] < b]})
    return out


def hourly_rows(cdus: dict[str, dict], start: datetime, M: int) -> list[dict]:
    rows = []
    H = M // HOUR_MIN
    for c, x in sorted(cdus.items()):
        f = x["fields"]
        sh = (H, HOUR_MIN)
        leak = np.zeros(M, bool)
        for spans in x["leaks"].values():
            for a, b, _l in spans:
                leak[a:b] = True
        red = x["pumps"]["redundancy"]
        for h in range(H):
            sl = slice(h * HOUR_MIN, (h + 1) * HOUR_MIN)

            def mean(k: str, scale: float, nd: int = 1, sl=sl) -> float:
                return round(float(f[k][sl].sum()) / HOUR_MIN / scale, nd)
            rows.append({"hour": iso(start + h * HOUR_MIN * MIN), "cdu": c, "hall": x["hall"],
                         "supply_c": mean("sec_supply_c", 100, 2), "supply_max_c": round(int(f["sec_supply_c"][sl].max()) / 100, 2),
                         "return_c": mean("sec_return_c", 100, 2), "flow_lpm": mean("sec_flow_lpm", 10, 0),
                         "flow_min_lpm": round(int(f["sec_flow_lpm"][sl].min()) / 10, 1), "dp_kpa": mean("sec_dp_kpa", 10),
                         "heat_kwh": mean("heat_kw", 10), "pri_supply_c": mean("pri_supply_c", 100, 2),
                         "pri_return_c": mean("pri_return_c", 100, 2), "pri_flow_lpm": mean("pri_flow_lpm", 10, 0),
                         "valve_pct": mean("valve_pct", 10), "pump1_pct": mean("pump1_pct", 10), "pump2_pct": mean("pump2_pct", 10),
                         "filter_dp_kpa": mean("filter_dp_kpa", 10), "reservoir_pct": mean("reservoir_pct", 10),
                         "power_kwh": mean("power_w", 1000, 2), "leak_min": int(leak[sl].sum()),
                         "redundancy_lost_min": int(red[sl].sum())})
    del sh
    return rows


def write_cdu(layer: CduTelemetry, cdus: dict[str, dict], dest: str | Path, source: str = "",
              minutes_dest: str | Path | None = None) -> dict[str, Any]:
    """Write the committed tiers to dest and the one-minute tier to minutes_dest (publish time) if given."""
    cfg = layer.cfg
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    win = dest / "windows"
    if win.exists():
        for p in win.glob("*.json"):
            p.unlink()
    win.mkdir(exist_ok=True)
    keys = [x["key"] for x in cfg["fields"]]
    rows = hourly_rows(cdus, layer.start, layer.M)
    (dest / "cdu_hourly.csv").write_text(_csv(rows, HOURLY_COLUMNS), encoding="utf-8", newline="\n")
    states = [dict(s, cdu=c) for c, x in sorted(cdus.items()) for s in x["states"]]
    (dest / "states.jsonl").write_text("".join(json.dumps(s, sort_keys=True) + "\n" for s in states), encoding="utf-8", newline="\n")
    index = []
    for c, x in sorted(cdus.items()):
        for w in _windows(x, layer.M, layer.start, cfg["tiers"]["window_before_min"], cfg["tiers"]["window_after_min"], keys):
            name = f"{c}_{w['from'][:16].replace('-', '').replace(':', '')}"
            (win / f"{name}.json").write_text(_dump(w), encoding="utf-8", newline="\n")
            index.append({"file": f"windows/{name}.json", "cdu": c, "from": w["from"], "minutes": w["minutes"]})
    minutes = {}
    for c, x in sorted(cdus.items()):
        minutes[c] = _dump({"cdu": c, "hall": x["hall"], "start": iso(layer.start), "minutes": layer.M,
                            "encoding": "first value then minute-to-minute steps; divide by the field's scale",
                            "fields": {k: delta(x["fields"][k]) for k in keys},
                            "service_hours_start": x["service_hours_start"], "filter_serviced": x["filter_serviced"]})
    if minutes_dest is not None:
        md = Path(minutes_dest)
        md.mkdir(parents=True, exist_ok=True)
        for c, text in minutes.items():
            (md / f"{c}.json").write_text(text, encoding="utf-8", newline="\n")
    man = {"disclaimer": "Synthetic CDU telemetry for a portfolio demonstration, in the published DMTF Redfish schema for "
                         "cooling units. All names and readings are fictional; no vendor's register map is implied.",
           "source": source, "window": {"start": iso(layer.start), "end": iso(layer.end)},
           "cdus": {c: {"hall": x["hall"], "uri": f"{cfg['collection']['base_uri']}/{c}"} for c, x in sorted(cdus.items())},
           "files": {"cdu_hourly.csv": len(rows), "states.jsonl": len(states), "windows": len(index)},
           "windows": index,
           "minutes": {f"{c}.json": {"sha256": hashlib.sha256(t.encode()).hexdigest(), "bytes": len(t.encode())}
                       for c, t in minutes.items()}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
