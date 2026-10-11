"""Synthetic mechanical telemetry for Site AUS-1: chillers, facility water pumps and loop, thermal walls, and CRAHs.

Portfolio demo; all data fictional. Runs on a finished month after its energy meters, its CDU telemetry, and its
power telemetry, with its own random stream, and writes beside them, never into them.

The energy meters already say, hour by hour, how much heat the plant rejects, the outdoor temperature, the facility
water temperature, and what the chiller yard, the pumps, the CRAHs, and each hall's mechanical UPS drew. This layer
splits those totals into each machine, one reading a minute, in the point names Vertiv publishes for its iCOM
controllers (config/telemetry_mechanical.yaml):

* **Chillers** (Liebert AFC, V1C points): the plant runs the number of chillers the energy model stages, picked by a
  lead/lag rotation and skipping any chiller tripped or held off by the BMS. Each running chiller takes an equal share
  of the heat; free cooling takes the part the outdoor air allows unless it is inhibited (``chiller_events``), and the
  compressors carry the rest. Each hour's summed draw is the chiller meter.
* **Pumps and loop**: two duty pumps at the speed the energy model uses; their draw is the pump meter. The loop's flow
  is the CDUs' primary flow (CDU telemetry) plus the thermal walls' and CRAHs' chilled water; the return header is the
  supply plus the plant's heat over that flow.
* **Thermal walls** (Liebert CWA, iCOM chilled-water points): each hall's air-side heat (its IT load less what the CDUs
  take out, plus the mechanical loads in the hall) shared by its walls. Fan speed follows load above a floor; EC fan
  power follows the cube of speed. A failed fan's share moves to the other five. ``wall_power`` is the one model the
  energy meters use for the walls' draw too.
* **CRAHs**: the electrical rooms' heat (UPS losses), at a fixed fan speed; their summed draw is the CRAH meter.

Every BMS record shows where it is: compressor trips (``bms_events`` alarms), chiller enable and condenser fan overrides
(written at BACnet priority 8), free-cooling lockouts, thermal-wall fan failures, and alarm inhibits
(``Event_Algorithm_Inhibit``). Published tiers (see ``write_mechanical``): hourly per device, the states, and one-minute
windows around every event, committed; each device's one-minute series built at publish time with checksums in the
manifest.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from scorecard import site_model as S
from scorecard.synthetic.telemetry import MIN, _csv, _csv_rows, _dump, _jsonl, iso, parse
from scorecard.synthetic.telemetry_power import _ar, pack, pin_sum

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "telemetry_mechanical.yaml"
HOUR_MIN = 60

CHILLER_HOURLY = ["hour", "chiller", "status", "run_min", "fc_min", "inhibit_min", "bms_off_min", "alarm_min", "kwh", "cap_kwh",
                  "fc_kwh", "mech_kwh", "inlet_c", "outlet_c", "ambient_c", "flow_m3h", "hp_max_bar", "fan_max_pct"]
PUMP_HOURLY = ["hour", "pump", "run_min", "speed_pct", "hz", "kwh", "flow_lps"]
LOOP_HOURLY = ["hour", "supply_c", "return_c", "flow_lps", "dp_kpa", "heat_kwh", "chillers_running", "chillers_needed"]
AIR_HOURLY = ["hour", "unit", "hall", "kind", "sup_c", "sup_max_c", "ret_c", "fan_pct", "fans_min", "valve_pct", "cw_in_c",
              "cw_out_c", "flow_lps", "load_kwh", "kwh", "alarm_min", "inhibit_min"]


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rng(seed: int, *parts: object) -> np.random.Generator:
    key = ":".join(str(p) for p in (seed, "telemetry", "mechanical") + parts)
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def pin_mean(x: np.ndarray, total: int) -> np.ndarray:
    """Integers shaped like x (which may be negative) whose sum is exactly total."""
    off = int(math.ceil(max(0.0, -float(np.min(x))))) + 1 if len(x) else 0
    return pin_sum(np.asarray(x, dtype=np.float64) + off, int(total) + off * len(x)) - off


def sat_bar_g(t_c: Any, a: float, b: float) -> Any:
    """Refrigerant saturation pressure (bar gauge) at t_c, from ln(P abs) = a - b / T."""
    return np.exp(a - b / (np.asarray(t_c, dtype=np.float64) + 273.15)) - 1.01325


def wall_power(heat_kw: Any, fans_ok: Any, cfg: dict[str, Any]) -> tuple[Any, Any]:
    """A thermal wall's fan speed (fraction) and electrical draw (kW) at a heat load (scalars or arrays). Speed holds a floor
    (the walls hold cold-aisle pressure) and rises with load; EC fan power follows the cube of speed. With fans_ok of six
    running, each running fan speeds up to keep the airflow, so the draw rises by (6 / fans_ok) squared."""
    a = cfg["air"]
    n = a["fans_per_wall"]
    load = np.maximum(0.0, np.asarray(heat_kw, dtype=np.float64)) / 400.0
    ok = np.maximum(1, np.asarray(fans_ok, dtype=np.float64))
    s = np.minimum(1.0, a["wall_speed_min"] + a["wall_speed_per_load"] * load)
    s_run = np.minimum(1.0, s * n / ok)
    kw = a["wall_fan_kw_max"] * (ok / n) * s_run ** 3 + a["wall_controls_kw"]
    return s_run, kw


class MechanicalTelemetry:
    """One-minute readings for every chiller, facility water pump, the loop header, every thermal wall, and every CRAH in
    a hall with telemetry."""

    def __init__(self, data_dir: str | Path, seed: int, energy_dir: str | Path, cdu_dir: str | Path,
                 cfg: dict[str, Any] | None = None, site: dict | None = None, energy_cfg: dict | None = None,
                 meters: list[dict] | None = None):
        from scorecard.synthetic.energy import Plant, load_config as energy_config
        self.dir = Path(data_dir)
        self.cfg = cfg or load_config()
        self.site = site or S.load_site()
        self.ecfg = energy_cfg or energy_config()
        self.plant = Plant(self.ecfg, self.site)
        self.seed = seed
        man = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        self.start, self.end = parse(man["window"]["start"]), parse(man["window"]["end"])
        self.M = int((self.end - self.start).total_seconds() // 60)
        self.H = self.M // HOUR_MIN
        rows = meters if meters is not None else _csv_rows(Path(energy_dir) / "meters_hourly.csv")
        by_hour = {r["hour"]: r for r in rows}
        self.meters = [by_hour.get(iso(self.start + timedelta(hours=k))) for k in range(self.H)]
        self.cdu_rows = _csv_rows(Path(cdu_dir) / "cdu_hourly.csv")
        self.bms = sorted(_jsonl(self.dir / "facility" / "bms_events.jsonl"), key=lambda e: (e["timestamp"], e["device"]))
        self.fc_events = sorted(_jsonl(Path(energy_dir) / "chiller_events.jsonl"), key=lambda e: (e["timestamp"], e["chiller"]))
        self.epms = sorted(_jsonl(self.dir / "facility" / "epms_events.jsonl"), key=lambda e: e["timestamp"])
        self.halls = [h for h in self.site["halls"] if h["state"] in ("production", "deployment")]
        hr = self.site["plants"]["heat_rejection"]
        self.chillers = [f"CH-{i:02d}" for i in range(1, hr["chiller_count"] + 1)]
        self.pumps = [f"FWP-{i}" for i in range(1, hr["pump_count"] + 1)]
        self.duty_pumps = hr["pump_count"] - hr["pump_redundancy"]
        self.chiller_kw = S.product(self.site, hr["chiller_product"])["capacity_kw"]
        self.walls = {h["id"]: [f"TW-{h['letter']}{i}" for i in range(1, h["cooling"].get("thermal_wall_count", 0) + 1)] for h in self.halls}
        self.crahs = {h["id"]: [f"CRAH-{h['letter']}{i}" for i in range(1, h["cooling"].get("electrical_room_crah_count", 0) + 1)]
                      for h in self.halls}
        self.mups_eff = {h["id"]: S.product(self.site, h["power"]["mech_ups_product"])["efficiency"] for h in self.halls}
        self.conflicts: list[str] = []

    # ----------------------------------------------------------------- time helpers
    def m_of(self, t: datetime) -> int:
        """Index of the first reading at or after t."""
        return max(0, min(self.M, math.ceil((t - self.start).total_seconds() / 60 - 1e-9)))

    def t_of(self, m: int) -> datetime:
        return self.start + m * MIN

    def hour_of(self, m: int) -> int:
        return min(self.H - 1, m // HOUR_MIN)

    def per_minute(self, hourly: np.ndarray) -> np.ndarray:
        return np.repeat(np.asarray(hourly, dtype=np.float64), HOUR_MIN)[: self.M]

    # ----------------------------------------------------------------- the records as spans (minutes)
    def _spans(self, pick, start_key: str = "set", end_key: str = "release") -> dict[str, list[tuple[int, int, dict, dict | None]]]:
        out: dict[str, list] = {}
        open_: dict[str, dict] = {}
        for e in self.bms:
            k = pick(e)
            if k is None:
                continue
            if k[1] == start_key:
                open_[k[0]] = e
            elif k[1] == end_key and k[0] in open_:
                s = open_.pop(k[0])
                out.setdefault(k[0], []).append((self.m_of(parse(s["timestamp"])), self.m_of(parse(e["timestamp"])), s, e))
        for d, s in open_.items():
            out.setdefault(d, []).append((self.m_of(parse(s["timestamp"])), self.M, s, None))
        return out

    def trips(self) -> dict[str, list]:
        """Compressor trips per chiller, active to cleared (BMS alarms)."""
        def pick(e):
            if e.get("kind") == "alarm" and e["device"].startswith("CH-") and e["alarm"].startswith("Compressor trip") \
                    and e["state"] in ("active", "cleared"):
                return (e["device"], "set" if e["state"] == "active" else "release")
            return None
        return self._spans(pick)

    def fan_failures(self) -> dict[str, list]:
        """Thermal-wall fan failures, active to cleared; the fan number is in the alarm text."""
        def pick(e):
            if e.get("kind") == "alarm" and e["device"].startswith("TW-") and e["alarm"].startswith("Fan ") \
                    and e["state"] in ("active", "cleared"):
                return (f"{e['device']}|{e['alarm']}", "set" if e["state"] == "active" else "release")
            return None
        out: dict[str, list] = {}
        for k, v in self._spans(pick).items():
            dev, alarm = k.split("|")
            fan = int(alarm.split()[1])
            out.setdefault(dev, []).extend((a, b, s, e, fan) for a, b, s, e in v)
        return out

    def overrides(self, point: str) -> dict[str, list]:
        """BMS overrides and inhibits on one point, set to release."""
        def pick(e):
            if e.get("kind") in ("override", "inhibit") and e.get("point") == point:
                return (e["device"], e["action"])
            return None
        return self._spans(pick)

    def lockouts(self) -> dict[str, list[tuple[int, int, dict, dict | None]]]:
        """Free cooling disabled to enabled, per chiller (energy/chiller_events.jsonl)."""
        out: dict[str, list] = {}
        open_: dict[str, dict] = {}
        for e in self.fc_events:
            if e["event"] == "Free cooling disabled":
                open_[e["chiller"]] = e
            elif e["event"] == "Free cooling enabled" and e["chiller"] in open_:
                s = open_.pop(e["chiller"])
                out.setdefault(e["chiller"], []).append((self.m_of(parse(s["timestamp"])), self.m_of(parse(e["timestamp"])), s, e))
        for c, s in open_.items():
            out.setdefault(c, []).append((self.m_of(parse(s["timestamp"])), self.M, s, None))
        return out

    def outage_minutes(self) -> list[int]:
        """The minute the utility mains opened (the plant's motors lose power until the generator bus is live)."""
        return [int((parse(e["timestamp"]) - self.start).total_seconds() // 60) for e in self.epms
                if e["device"] == "MV-A main breaker" and "utility undervoltage" in e["event"]
                and 0 <= (parse(e["timestamp"]) - self.start).total_seconds() < self.M * 60]

    def mask(self, spans: list) -> np.ndarray:
        out = np.zeros(self.M, dtype=bool)
        for x in spans:
            out[x[0]:x[1]] = True
        return out

    # ----------------------------------------------------------------- hourly inputs
    def meter(self, k: int, col: str) -> float:
        r = self.meters[k]
        return float(r[col]) if r is not None and r.get(col, "") != "" else 0.0

    def cdu_by_hall(self) -> dict[str, dict[str, np.ndarray]]:
        """Per hall per hour: the CDUs' heat removed, own draw, and primary (facility water) flow, from cdu_hourly.csv."""
        idx = {iso(self.start + timedelta(hours=k)): k for k in range(self.H)}
        out = {h["id"]: {"heat": np.zeros(self.H), "power": np.zeros(self.H), "flow_lpm": np.zeros(self.H)} for h in self.halls}
        for r in self.cdu_rows:
            k = idx.get(r["hour"])
            if k is None or r["hall"] not in out:
                continue
            x = out[r["hall"]]
            x["heat"][k] += float(r["heat_kwh"] or 0)
            x["power"][k] += float(r["power_kwh"] or 0)
            x["flow_lpm"][k] += float(r["pri_flow_lpm"] or 0)
        return out

    def plant_heat(self) -> np.ndarray:
        """The heat the plant rejects each hour, as the energy model counts it: every UPS input, the mechanical UPSs, and the CRAHs."""
        q = np.zeros(self.H)
        for k in range(self.H):
            q[k] = sum(self.meter(k, f"ups_in_{h['letter'].lower()}_kwh") + self.meter(k, f"mech_{h['letter'].lower()}_kwh")
                       for h in self.halls) + self.meter(k, "crah_kwh")
        return q

    # ----------------------------------------------------------------- thermal walls (shared with the energy meters)
    def wall_minutes(self, cdu: dict[str, dict[str, np.ndarray]] | None = None) -> dict[str, dict[str, np.ndarray]]:
        """Each wall's fan speed, fans running, and draw (kW) per minute, from its hall's air-side heat. The heat includes
        the walls' own fan power, so each hour is solved by fixed-point iteration. Needs only the IT meters and the CDU
        telemetry, so the energy meters can call it before their mechanical UPS column exists."""
        cdu = cdu or self.cdu_by_hall()
        fails = self.fan_failures()
        out: dict[str, dict[str, np.ndarray]] = {}
        for h in self.halls:
            ids = self.walls[h["id"]]
            if not ids:
                continue
            L = h["letter"].lower()
            it = np.array([self.meter(k, f"ups_out_{L}_kwh") for k in range(self.H)])
            c = cdu[h["id"]]
            rng = _rng(self.seed, "walls", h["id"])
            imb = 1 + rng.uniform(-0.04, 0.04, len(ids))
            imb = imb * len(ids) / imb.sum()
            fans = {w: np.full(self.M, self.cfg["air"]["fans_per_wall"], dtype=np.int64) for w in ids}
            for w in ids:
                for a, b, _, _, _fan in fails.get(w, []):
                    fans[w][a:b] -= 1
            noise = {w: 1 + _ar(_rng(self.seed, "wall-kw", w), self.M, 0.008, 0.97) for w in ids}
            speed = {w: np.zeros(self.M) for w in ids}
            kw = {w: np.zeros(self.M) for w in ids}
            heat = {w: np.zeros(self.M) for w in ids}
            for k in range(self.H):
                sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
                W = 0.0
                for _ in range(5):
                    air = max(0.0, it[k] - c["heat"][k] + c["power"][k] + W)
                    tot = 0.0
                    for j, w in enumerate(ids):
                        hw = air / len(ids) * imb[j]
                        s_, p_ = wall_power(hw, fans[w][sl], self.cfg)
                        kw[w][sl] = p_ * noise[w][sl]
                        speed[w][sl] = s_
                        heat[w][sl] = hw
                        tot += float(kw[w][sl].mean())
                    W = tot
            for w in ids:
                out[w] = {"hall": h["id"], "speed": speed[w], "kw": kw[w], "fans": fans[w], "heat_model": heat[w]}
        return out

    def hall_mech_kw(self, walls: dict[str, dict] | None = None, cdu: dict | None = None) -> dict[str, np.ndarray]:
        """Each hall's mechanical UPS output per hour (kW): its CDUs' draw plus its walls' (the energy meters' column)."""
        cdu = cdu or self.cdu_by_hall()
        walls = walls if walls is not None else self.wall_minutes(cdu)
        out = {}
        for h in self.halls:
            tot = cdu[h["id"]]["power"].copy()
            for w in self.walls[h["id"]]:
                tot += walls[w]["kw"].reshape(self.H, HOUR_MIN).mean(axis=1)
            out[h["id"]] = tot
        return out

    # ----------------------------------------------------------------- air side for display
    def air_units(self, walls: dict[str, dict], cdu: dict[str, dict[str, np.ndarray]], supply_c: np.ndarray) -> dict[str, dict]:
        a = self.cfg["air"]
        cp_air, rho = self.cfg["air_props"]["cp_kj_per_kg_k"], self.cfg["air_props"]["density_kg_per_m3"]
        cp_w = self.cfg["water"]["cp_kj_per_kg_k"] * self.cfg["water"]["density_kg_per_l"]
        out: dict[str, dict] = {}
        inhib = self.overrides("High supply air temperature alarm")
        fails = self.fan_failures()
        crah_kwh = np.array([self.meter(k, "crah_kwh") for k in range(self.H)])
        # CRAH draw: the meter split across the units, minute by minute
        crah_kw10: dict[str, np.ndarray] = {}
        ids_all = [c for h in self.halls for c in self.crahs[h["id"]]]
        if ids_all:
            base = {c: 1 + _ar(_rng(self.seed, "crah-kw", c), self.M, 0.01, 0.95) for c in ids_all}
            for c in ids_all:
                crah_kw10[c] = np.zeros(self.M, dtype=np.int64)
            for k in range(self.H):
                sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
                flat = np.concatenate([base[c][sl] for c in ids_all])
                got = pin_sum(flat, int(round(crah_kwh[k] * 600)))
                for j, c in enumerate(ids_all):
                    crah_kw10[c][sl] = got[j * HOUR_MIN:(j + 1) * HOUR_MIN]
        for h in self.halls:
            L = h["letter"].lower()
            eff = self.mups_eff[h["id"]]
            it = np.array([self.meter(k, f"ups_out_{L}_kwh") for k in range(self.H)])
            mech_in = np.array([self.meter(k, f"mech_{L}_kwh") for k in range(self.H)])
            ups_in = np.array([self.meter(k, f"ups_in_{L}_kwh") for k in range(self.H)])
            air_heat = np.maximum(0.0, it - cdu[h["id"]]["heat"] + mech_in * eff)
            ids = self.walls[h["id"]]
            for j, w in enumerate(ids):
                x = walls[w]
                rng = _rng(self.seed, "air", w)
                hall_model = sum(walls[v]["heat_model"] for v in ids)
                frac = np.where(hall_model > 0, x["heat_model"] / np.where(hall_model > 0, hall_model, 1), 1 / len(ids))
                heat = self.per_minute(air_heat) * frac * (1 + _ar(rng, self.M, 0.006, 0.9))
                fail_bump = np.zeros(self.M)
                fan_no = np.zeros(self.M, dtype=np.int64)
                for aa, bb, _, _, fan in fails.get(w, []):
                    fail_bump[aa:bb] = a["fan_failed_bump_c"]
                    fan_no[aa:bb] = fan
                sup = a["supply_setpoint_c"] + _ar(rng, self.M, a["supply_sd_c"], 0.9) + fail_bump
                design_flow = 400.0 / (rho * cp_air * a["wall_design_dt_air_k"])
                airflow = design_flow * np.minimum(1.0, x["speed"] * x["fans"] / a["fans_per_wall"])
                ret = sup + heat / (rho * cp_air * np.maximum(airflow, 0.1))
                flow = heat / (cp_w * a["water_dt_k"])
                cw_in = supply_c + 0.05 + _ar(rng, self.M, 0.02, 0.9)
                cw_out = cw_in + np.where(flow > 0, heat / (cp_w * np.maximum(flow, 1e-6)), 0.0)
                valve = np.clip(heat / 400.0 * 100 * 1.15, 5, 100)
                rh = rng.uniform(*a["return_rh_pct"]) + _ar(rng, self.M, 0.6, 0.98)
                inh = self.mask(inhib.get(w, []))
                out[w] = {"kind": "wall", "hall": h["id"], "sup": sup, "ret": ret, "setp": a["supply_setpoint_c"], "hi": a["high_supply_c"],
                          "fan": x["speed"] * 100, "fans": x["fans"], "fan_no": fan_no, "valve": valve, "cw_in": cw_in, "cw_out": cw_out,
                          "flow": flow, "load": heat, "kw": x["kw"], "rh": rh, "inhibit": inh, "fan_alarm": fan_no > 0,
                          "inhibit_spans": inhib.get(w, []), "fail_spans": fails.get(w, [])}
            room = np.maximum(0.0, (ups_in - it) + mech_in * (1 - eff))
            cids = self.crahs[h["id"]]
            for c in cids:
                rng = _rng(self.seed, "air", c)
                kwc = crah_kw10[c] / 10.0
                heat = self.per_minute(room) / len(cids) + kwc
                heat = heat * (1 + _ar(rng, self.M, 0.006, 0.9))
                sup = a["supply_setpoint_c"] + _ar(rng, self.M, a["supply_sd_c"], 0.9)
                design_flow = 100.0 / (rho * cp_air * a["crah_design_dt_air_k"])
                airflow = design_flow * a["crah_fan_pct"] / 100
                ret = sup + heat / (rho * cp_air * airflow)
                flow = heat / (cp_w * a["water_dt_k"])
                cw_in = supply_c + 0.05 + _ar(rng, self.M, 0.02, 0.9)
                cw_out = cw_in + np.where(flow > 0, heat / (cp_w * np.maximum(flow, 1e-6)), 0.0)
                rh = rng.uniform(*a["return_rh_pct"]) + _ar(rng, self.M, 0.6, 0.98)
                out[c] = {"kind": "crah", "hall": h["id"], "sup": sup, "ret": ret, "setp": a["supply_setpoint_c"], "hi": a["high_supply_c"],
                          "fan": np.full(self.M, a["crah_fan_pct"]), "fans": np.ones(self.M, dtype=np.int64), "fan_no": np.zeros(self.M, dtype=np.int64),
                          "valve": np.clip(heat / 100.0 * 100 * 1.15, 5, 100), "cw_in": cw_in, "cw_out": cw_out, "flow": flow, "load": heat,
                          "kw": kwc, "kw10": crah_kw10[c], "rh": rh, "inhibit": np.zeros(self.M, dtype=bool), "fan_alarm": np.zeros(self.M, dtype=bool),
                          "inhibit_spans": [], "fail_spans": []}
        return out

    # ----------------------------------------------------------------- the plant
    def rotation(self, week: int, items: list[str], step: int) -> list[str]:
        k = (week * step) % len(items)
        return items[k:] + items[:k]

    def supply_header(self) -> np.ndarray:
        """The facility water supply header, minute by minute: each hour's mean is the meter's facility water temperature."""
        fw = np.array([self.meter(k, "fw_supply_c") or self.ecfg["plant"]["supply_c"] for k in range(self.H)])
        raw = self.per_minute(fw) * 100 + _ar(_rng(self.seed, "supply"), self.M, 4.0, 0.95)
        # a utility outage stops the chillers until Quick Start: the water in the loop takes the heat and the header warms,
        # then recovers once the compressors are back (basis: assumption)
        qs, rise = self.cfg["chiller"]["quick_start_min"], self.cfg["chiller"]["outage_rise_c"] * 100
        for m in self.outage_minutes():
            up = np.linspace(rise / (qs + 1), rise, qs + 1)
            down = rise * np.exp(-np.arange(1, 16) / 4.0)
            bump = np.concatenate([up, down])[: max(0, self.M - m)]
            raw[m:m + len(bump)] += bump
        out = np.zeros(self.M)
        for k in range(self.H):
            sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
            out[sl] = pin_mean(raw[sl], int(round(fw[k] * 100 * HOUR_MIN))) / 100
        return out

    def plant_series(self, air: dict[str, dict], cdu: dict[str, dict[str, np.ndarray]], supply: np.ndarray) -> dict[str, Any]:
        cc, pc = self.cfg["chiller"], self.cfg["pump"]
        p = self.ecfg["plant"]
        cp_w = self.cfg["water"]["cp_kj_per_kg_k"] * self.cfg["water"]["density_kg_per_l"]
        M, H = self.M, self.H
        Q = self.plant_heat()
        outdoor = np.array([self.meter(k, "outdoor_c") for k in range(H)])
        need = np.array([self.plant.running(q) for q in Q])
        free = np.array([self.plant.free_fraction(t) for t in outdoor])
        cop = np.array([self.plant.cop(t) for t in outdoor])
        # loop: flow = CDUs' primary + walls + CRAHs; the return header carries the plant's heat over that flow
        rng = _rng(self.seed, "loop")
        cdu_flow = sum(self.per_minute(cdu[h["id"]]["flow_lpm"]) for h in self.halls) / 60.0
        flow = cdu_flow + sum(x["flow"] for x in air.values())
        heat_m = self.per_minute(Q)
        ret = supply + np.where(flow > 0, heat_m / (cp_w * np.maximum(flow, 1e-6)), 0.0)
        dp = pc["dp_setpoint_kpa"] + _ar(rng, M, 0.8, 0.9)
        # records
        trips, offs, fan_ovr, locks = self.trips(), self.overrides("Chiller enable"), self.overrides("Condenser fan speed"), self.lockouts()
        tripped = {c: self.mask(trips.get(c, [])) for c in self.chillers}
        off = {c: self.mask([x for x in offs.get(c, []) if x[2].get("value") == "Off"]) for c in self.chillers}
        fan100 = {c: self.mask(fan_ovr.get(c, [])) for c in self.chillers}
        locked = {c: self.mask(locks.get(c, [])) for c in self.chillers}
        pre = {c: np.zeros(M, dtype=bool) for c in self.chillers}
        ramp = {c: np.zeros(M, dtype=bool) for c in self.chillers}
        for c in self.chillers:
            for a, _b, _s, _e in trips.get(c, []):
                pre[c][max(0, a - 180):a] = True
                ramp[c][max(0, a - cc["trip_ramp_min"]):a] = True
        outage = self.outage_minutes()
        pf = np.zeros(M, dtype=bool)
        qs = np.zeros(M, dtype=bool)
        for m in outage:
            pf[m] = True
            qs[m + 1:m + 1 + cc["quick_start_min"]] = True
        # staging, minute by minute
        n_ch = len(self.chillers)
        running = np.zeros((n_ch, M), dtype=bool)
        idx = {c: i for i, c in enumerate(self.chillers)}
        for m in range(M):
            k = m // HOUR_MIN
            week = m // (cc["rotation_hours"] * HOUR_MIN)
            avail = [c for c in self.rotation(week, self.chillers, cc["rotation_step"]) if not (off[c][m] or tripped[c][m])]
            must = [c for c in avail if locked[c][m] or pre[c][m]]
            rest = [c for c in avail if c not in must]
            pick = (must + rest)[:max(int(need[k]), len(must))]
            if len(pick) < need[k]:
                self.conflicts.append(f"{iso(self.t_of(m))}: {len(pick)} chillers available, {int(need[k])} needed")
            for c in pick:
                running[idx[c], m] = True
        starting = np.zeros_like(running)
        for i in range(n_ch):
            r = running[i]
            on = np.flatnonzero(r[1:] & ~r[:-1]) + 1
            for m in on:
                starting[i, m:m + cc["start_delay_min"]] = r[m:m + cc["start_delay_min"]]
        loaded = running & ~starting
        nload = loaded.sum(axis=0)
        cap = np.where(loaded, heat_m / np.maximum(nload, 1), 0.0)
        # no capacity while the power is off, then back over Quick Start; the hour's heat is carried in its other minutes
        back = np.ones(M)
        for m in outage:
            back[m] = 0.0
            n = len(back[m + 1:m + 1 + cc["quick_start_min"]])
            back[m + 1:m + 1 + n] = np.linspace(0.3, 0.9, cc["quick_start_min"])[:n]
        cap = cap * back[None, :]
        fcf = np.zeros((n_ch, M))
        for c, i in idx.items():
            f = self.per_minute(free)
            f = np.where(locked[c], 0.0, f)
            f = np.where(ramp[c], np.minimum(f, 0.7), f)
            fcf[i] = np.where(running[i], f, 0.0)
        copm = self.per_minute(cop)
        kw_w = np.where(loaded, cap * (fcf * p["free_cooling_kw_per_kw"] + (1 - fcf) / copm), 0.0)
        kw_w = kw_w + np.where(starting, 8.0, 0.0) + 1.5                      # starting draw; controls and heaters on every unit
        kw_w = np.where(pf[None, :], kw_w * 0.3, np.where(qs[None, :], kw_w * 0.7, kw_w))
        rngk = _rng(self.seed, "chiller-kw")
        kw_w = kw_w * (1 + _ar(rngk, n_ch * M, 0.01, 0.9).reshape(n_ch, M))
        kw10 = np.zeros((n_ch, M), dtype=np.int64)
        cap10 = np.zeros((n_ch, M), dtype=np.int64)
        for k in range(H):
            sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
            kw10[:, sl] = pin_sum(kw_w[:, sl].reshape(-1), int(round(self.meter(k, "chillers_kwh") * 600))).reshape(n_ch, HOUR_MIN)
            cap10[:, sl] = pin_sum(cap[:, sl].reshape(-1), int(round(Q[k] * 600))).reshape(n_ch, HOUR_MIN)
        fc10 = np.round(cap10 * fcf).astype(np.int64)
        mech10 = cap10 - fc10
        # pressures, fans, compressors, status
        a_, b_ = cc["sat_a"], cc["sat_b"]
        amb_raw = self.per_minute(outdoor) * 10 + _ar(_rng(self.seed, "ambient"), M, 2.0, 0.97)
        amb = np.zeros(M)
        for k in range(H):
            sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
            amb[sl] = pin_mean(amb_raw[sl], int(round(outdoor[k] * 10 * HOUR_MIN))) / 10
        circ = self.chiller_kw / 2
        out_c: dict[str, dict] = {}
        stat = cc["unit_status"]
        code = {v: k for k, v in stat.items()}
        ccode = {v: k for k, v in cc["compressor_status"].items()}
        nflow = running.sum(axis=0)
        for c, i in idx.items():
            rng = _rng(self.seed, "chiller", c)
            mech_kw = mech10[i] / 10.0
            c1_on = loaded[i] & (mech_kw > 0) & ~pf & ~qs
            c2_on = c1_on & (mech_kw > circ * 0.5)
            load1 = np.clip(np.where(c2_on, mech_kw / 2, mech_kw) / circ, 0, 1)
            load2 = np.clip(np.where(c2_on, mech_kw / 2, 0.0) / circ, 0, 1)
            appr = cc["condensing_approach_k"]
            p_eq = sat_bar_g(amb, a_, b_)
            hp1 = np.where(c1_on, sat_bar_g(amb + appr[0] + (appr[1] - appr[0]) * load1, a_, b_), p_eq)
            hp2 = np.where(c2_on, sat_bar_g(amb + appr[0] + (appr[1] - appr[0]) * load2, a_, b_), p_eq)
            for a, b, _s, _e in trips.get(c, []):
                r0 = max(0, a - cc["trip_ramp_min"])
                if a > r0:
                    hp1[r0:a] = np.linspace(hp1[r0], cc["hp_alarm_bar"] + 0.3, a - r0 + 1)[1:]
                # after the trip the circuit equalizes toward the outdoor air
                tail = np.arange(0, max(0, b - a))
                hp1[a:b] = p_eq[a:b] + (cc["hp_alarm_bar"] + 0.3 - p_eq[a:b]) * np.exp(-tail / 5.0)
            hp1 = hp1 + _ar(rng, M, 0.05, 0.9)
            hp2 = hp2 + _ar(rng, M, 0.05, 0.9)
            out_t = supply + np.where(running[i], _ar(rng, M, cc["outlet_sd_c"], 0.9), 0.0)
            lp1 = np.where(c1_on, sat_bar_g(out_t - cc["evaporating_below_outlet_k"], a_, b_), sat_bar_g((amb + ret) / 2, a_, b_))
            fc_fan = np.interp(fcf[i], [0, 1], cc["fan_speed_fc_pct"])
            mech_fan = np.interp(np.maximum(load1, load2), [0, 1], cc["fan_speed_mech_pct"])
            fan = np.where(running[i], np.maximum(np.where(fcf[i] > 0, fc_fan, 0), np.where(c1_on, mech_fan, 0)), 0)
            fan = np.where(fan100[c] & running[i], 100.0, fan)
            fan = np.where(pf, 0.0, fan)
            st = np.full(M, code["Standby"], dtype=np.int64)
            st[running[i]] = code["Local On"]
            st[off[c]] = code["BMS Off"]
            st[tripped[c]] = code["Alarm Off"]
            st[pf & running[i]] = code["Power Failure"]
            cmp1 = np.where(c1_on, ccode["LOADED"], ccode["OFF"])
            cmp1 = np.where(starting[i] | (qs & running[i]), ccode["STARTING"], cmp1)
            cmp1 = np.where(tripped[c], ccode["ALARM"], cmp1)
            cmp2 = np.where(c2_on, ccode["LOADED"], ccode["OFF"])
            flow_i = np.where(running[i], flow / np.maximum(nflow, 1) * 3.6, 0.0)
            out_c[c] = {"status": st, "enable": (~off[c]).astype(np.int64), "setp": np.full(M, cc["setpoint_c"]),
                        "inlet": np.where(running[i], ret + _ar(rng, M, 0.03, 0.9), ret), "outlet": np.where(running[i], out_t, ret),
                        "ambient": amb, "fc": (fcf[i] > 0).astype(np.int64), "fc_inhibit": locked[c].astype(np.int64),
                        "fc_valve": fcf[i] * 100, "fan1": fan, "fan2": fan, "cmp1": cmp1, "cmp2": cmp2, "hp1": hp1, "lp1": lp1, "hp2": hp2,
                        "flow": flow_i, "kw10": kw10[i], "cap10": cap10[i], "fc10": fc10[i], "mech10": mech10[i],
                        "alarm": tripped[c].astype(np.int64), "hp1_alarm": tripped[c].astype(np.int64), "fan_override": fan100[c].astype(np.int64),
                        "running": running[i], "spans": {"trip": trips.get(c, []), "off": offs.get(c, []), "fan": fan_ovr.get(c, []),
                                                         "lock": locks.get(c, [])}}
        # pumps: two duty, the standby rotating weekly; their draw is the pump meter
        speed = np.array([max(p["pump_floor"], min(1.0, q / self.plant.design_heat)) for q in Q])
        pumps: dict[str, dict] = {}
        duty = np.zeros((len(self.pumps), M), dtype=bool)
        for m in range(0, M, HOUR_MIN):
            week = m // (pc["rotation_hours"] * HOUR_MIN)
            sb = week % len(self.pumps)
            for j in range(len(self.pumps)):
                if j != sb:
                    duty[j, m:m + HOUR_MIN] = True
        pw = np.where(duty, 1.0, 0.0) * (1 + _ar(_rng(self.seed, "pump-kw"), len(self.pumps) * M, 0.01, 0.9).reshape(len(self.pumps), M))
        pw = np.where(pf[None, :], pw * 0.8, pw)
        pkw10 = np.zeros((len(self.pumps), M), dtype=np.int64)
        for k in range(H):
            sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
            pkw10[:, sl] = pin_sum(pw[:, sl].reshape(-1), int(round(self.meter(k, "pumps_kwh") * 600))).reshape(len(self.pumps), HOUR_MIN)
        spm = self.per_minute(speed) * (1 + _ar(_rng(self.seed, "pump-speed"), M, 0.003, 0.9))
        ndut = duty.sum(axis=0)
        for j, pmp in enumerate(self.pumps):
            on = duty[j]
            pumps[pmp] = {"run": on.astype(np.int64), "speed": np.where(on, spm * 100, 0.0), "hz": np.where(on, spm * pc["motor_hz"], 0.0),
                          "kw10": pkw10[j], "flow": np.where(on, flow / np.maximum(ndut, 1), 0.0), "fault": np.zeros(M, dtype=np.int64)}
        loop = {"supply": supply, "return": ret, "flow": flow, "dp": dp, "heat": flow * cp_w * (ret - supply),
                "need": self.per_minute(need), "running": running.sum(axis=0)}
        return {"chillers": out_c, "pumps": pumps, "loop": loop, "Q": Q}

    # ----------------------------------------------------------------- the month
    def states(self, plant: dict[str, Any], air: dict[str, dict]) -> list[dict]:
        """The state changes a client sees, each with the record it comes from."""
        out: list[dict] = []

        def add(dev: str, fam: str, m: int, point: str, value: str, record: str, ts: str, **kw: Any) -> None:
            out.append({"device": dev, "family": fam, "m": int(m), "time": ts, "point": point, "value": value, "record": record, **kw})
        for c, x in plant["chillers"].items():
            for a, b, s, e in x["spans"]["trip"]:
                add(c, "chiller", a, "Circuit 1 - High Condensing Pressure (BV 35)", "active", "facility/bms_events.jsonl", s["timestamp"],
                    alarm=s["alarm"])
                if e is not None:
                    add(c, "chiller", b, "Circuit 1 - High Condensing Pressure (BV 35)", "cleared", "facility/bms_events.jsonl", e["timestamp"])
            for a, b, s, e in x["spans"]["off"]:
                add(c, "chiller", a, "Chiller enable", f"{s['value']} (priority 8)", "facility/bms_events.jsonl", s["timestamp"],
                    change_ref=s.get("change_ref", ""))
                if e is not None:
                    add(c, "chiller", b, "Chiller enable", "relinquished (Auto)", "facility/bms_events.jsonl", e["timestamp"],
                        change_ref=e.get("change_ref", ""))
            for a, b, s, e in x["spans"]["fan"]:
                add(c, "chiller", a, "Condenser fan speed override", f"{s['value']} (priority 8)", "facility/bms_events.jsonl", s["timestamp"],
                    change_ref=s.get("change_ref", ""))
                if e is not None:
                    add(c, "chiller", b, "Condenser fan speed override", "relinquished (Auto)", "facility/bms_events.jsonl", e["timestamp"])
            for a, b, s, e in x["spans"]["lock"]:
                add(c, "chiller", a, "Stop or Inhibit FC activation", "1 (free cooling inhibited)", "energy/chiller_events.jsonl", s["timestamp"],
                    note=s.get("note", ""))
                if e is not None:
                    add(c, "chiller", b, "Stop or Inhibit FC activation", "0 (free cooling allowed)", "energy/chiller_events.jsonl", e["timestamp"],
                        note=e.get("note", ""))
        for u, x in air.items():
            for a, b, s, e, fan in x["fail_spans"]:
                add(u, x["kind"], a, f"FanSts_OV[{fan}]", "Alarm", "facility/bms_events.jsonl", s["timestamp"], alarm=s["alarm"])
                if e is not None:
                    add(u, x["kind"], b, f"FanSts_OV[{fan}]", "On", "facility/bms_events.jsonl", e["timestamp"])
            for a, b, s, e in x["inhibit_spans"]:
                add(u, x["kind"], a, "High supply temperature: Event_Algorithm_Inhibit", "TRUE", "facility/bms_events.jsonl", s["timestamp"],
                    change_ref=s.get("change_ref", ""))
                if e is not None:
                    add(u, x["kind"], b, "High supply temperature: Event_Algorithm_Inhibit", "FALSE", "facility/bms_events.jsonl", e["timestamp"])
        for e in self.epms:
            if e["device"] == "MV-A main breaker" or e["device"] == "Generator paralleling bus":
                t = parse(e["timestamp"])
                if self.start <= t < self.end:
                    add("SITE", "site", int((t - self.start).total_seconds() // 60), e["device"], e["event"], "facility/epms_events.jsonl", e["timestamp"])
        return sorted(out, key=lambda s: (s["time"], s["device"], s["point"]))

    def run(self) -> dict[str, Any]:
        cdu = self.cdu_by_hall()
        walls = self.wall_minutes(cdu)
        supply = self.supply_header()
        air = self.air_units(walls, cdu, supply)
        plant = self.plant_series(air, cdu, supply)
        return {"walls": walls, "air": air, "plant": plant, "states": self.states(plant, air),
                "mech_kw": {h: v.tolist() for h, v in self.hall_mech_kw(walls, cdu).items()}}


# --------------------------------------------------------------------- publish
def device_fields(layer: MechanicalTelemetry, out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every device's one-minute integer series (value x the field's scale), keyed by device id."""
    i = lambda a, s: np.round(np.asarray(a, dtype=np.float64) * s).astype(np.int64)     # noqa: E731
    dev: dict[str, dict[str, Any]] = {}
    for c, x in out["plant"]["chillers"].items():
        dev[c] = {"family": "chiller", "fields": {
            "status": x["status"], "enable": x["enable"], "setp_c": i(x["setp"], 10), "inlet_c": i(x["inlet"], 100), "outlet_c": i(x["outlet"], 100),
            "ambient_c": i(x["ambient"], 10), "fc": x["fc"], "fc_inhibit": x["fc_inhibit"], "fc_valve_pct": i(x["fc_valve"], 10),
            "fan1_pct": i(x["fan1"], 1), "fan2_pct": i(x["fan2"], 1), "cmp1": x["cmp1"].astype(np.int64), "cmp2": x["cmp2"].astype(np.int64),
            "hp1_bar": i(x["hp1"], 10), "lp1_bar": i(x["lp1"], 10), "hp2_bar": i(x["hp2"], 10), "flow_m3h": i(x["flow"], 10),
            "kw": x["kw10"], "cap_kw": x["cap10"], "fc_kw": x["fc10"], "mech_kw": x["mech10"], "alarm": x["alarm"], "hp1_alarm": x["hp1_alarm"],
            "cond_fan_override": x["fan_override"]}}
    for p, x in out["plant"]["pumps"].items():
        dev[p] = {"family": "pump", "fields": {"run": x["run"], "speed_pct": i(x["speed"], 10), "hz": i(x["hz"], 10), "kw": x["kw10"],
                                               "flow_lps": i(x["flow"], 10), "fault": x["fault"]}}
    lp = out["plant"]["loop"]
    dev["FW-LOOP"] = {"family": "loop", "fields": {"supply_c": i(lp["supply"], 100), "return_c": i(lp["return"], 100), "flow_lps": i(lp["flow"], 10),
                                                   "dp_kpa": i(lp["dp"], 10), "heat_kw": i(lp["heat"], 10)}}
    for u, x in out["air"].items():
        kw_w = i(x["kw10"], 100) if "kw10" in x else i(x["kw"], 1000)
        status = np.where(x["fan_alarm"], 13, 11).astype(np.int64)
        dev[u] = {"family": x["kind"], "hall": x["hall"], "fields": {
            "status": status, "sup_c": i(x["sup"], 100), "ret_c": i(x["ret"], 100), "setp_c": i(np.full(layer.M, x["setp"]), 10),
            "hi_c": i(np.full(layer.M, x["hi"]), 10), "fan_pct": i(x["fan"], 1), "fans_ok": np.asarray(x["fans"], dtype=np.int64),
            "fan_failed": np.asarray(x["fan_no"], dtype=np.int64), "valve_pct": i(x["valve"], 10), "cw_in_c": i(x["cw_in"], 100),
            "cw_out_c": i(x["cw_out"], 100), "flow_lps": i(x["flow"], 100), "load_kw": i(x["load"], 10), "kw": kw_w,
            "rh_pct": i(x["rh"], 10), "hi_alarm": np.zeros(layer.M, dtype=np.int64), "hi_inhibit": x["inhibit"].astype(np.int64),
            "fan_alarm": x["fan_alarm"].astype(np.int64)}}
    return dev


def hourly_rows(layer: MechanicalTelemetry, dev: dict[str, dict], out: dict[str, Any]) -> dict[str, list[dict]]:
    H, sh = layer.H, (layer.H, HOUR_MIN)
    hours = [iso(layer.start + timedelta(hours=k)) for k in range(H)]
    stat = layer.cfg["chiller"]["unit_status"]
    ch_rows, p_rows, l_rows, a_rows = [], [], [], []
    for d, x in dev.items():
        f = x["fields"]
        if x["family"] == "chiller":
            run = (f["status"] == 0).reshape(sh) | (f["status"] == 8).reshape(sh)
            for k in range(H):
                sts = f["status"][k * HOUR_MIN:(k + 1) * HOUR_MIN]
                vals, cnt = np.unique(sts, return_counts=True)
                r = run[k]
                avg = lambda key, s: round(float(f[key].reshape(sh)[k][r].mean()) / s, 2) if r.any() else ""   # noqa: E731
                ch_rows.append({"hour": hours[k], "chiller": d, "status": stat[int(vals[np.argmax(cnt)])], "run_min": int(r.sum()),
                                "fc_min": int(f["fc"].reshape(sh)[k].sum()), "inhibit_min": int(f["fc_inhibit"].reshape(sh)[k].sum()),
                                "bms_off_min": int((f["enable"].reshape(sh)[k] == 0).sum()), "alarm_min": int(f["alarm"].reshape(sh)[k].sum()),
                                "kwh": round(int(f["kw"].reshape(sh)[k].sum()) / 600, 2), "cap_kwh": round(int(f["cap_kw"].reshape(sh)[k].sum()) / 600, 2),
                                "fc_kwh": round(int(f["fc_kw"].reshape(sh)[k].sum()) / 600, 2), "mech_kwh": round(int(f["mech_kw"].reshape(sh)[k].sum()) / 600, 2),
                                "inlet_c": avg("inlet_c", 100), "outlet_c": avg("outlet_c", 100),
                                "ambient_c": round(int(f["ambient_c"].reshape(sh)[k].sum()) / 600, 2),
                                "flow_m3h": round(int(f["flow_m3h"].reshape(sh)[k].sum()) / 600, 1),
                                "hp_max_bar": round(int(max(f["hp1_bar"].reshape(sh)[k].max(), f["hp2_bar"].reshape(sh)[k].max())) / 10, 1),
                                "fan_max_pct": int(max(f["fan1_pct"].reshape(sh)[k].max(), f["fan2_pct"].reshape(sh)[k].max()))})
        elif x["family"] == "pump":
            for k in range(H):
                p_rows.append({"hour": hours[k], "pump": d, "run_min": int(f["run"].reshape(sh)[k].sum()),
                               "speed_pct": round(int(f["speed_pct"].reshape(sh)[k].sum()) / 600, 1), "hz": round(int(f["hz"].reshape(sh)[k].sum()) / 600, 2),
                               "kwh": round(int(f["kw"].reshape(sh)[k].sum()) / 600, 2), "flow_lps": round(int(f["flow_lps"].reshape(sh)[k].sum()) / 600, 1)})
        elif x["family"] == "loop":
            run = out["plant"]["loop"]["running"].reshape(sh)
            need = out["plant"]["loop"]["need"].reshape(sh)
            for k in range(H):
                l_rows.append({"hour": hours[k], "supply_c": round(int(f["supply_c"].reshape(sh)[k].sum()) / 6000, 3),
                               "return_c": round(int(f["return_c"].reshape(sh)[k].sum()) / 6000, 3),
                               "flow_lps": round(int(f["flow_lps"].reshape(sh)[k].sum()) / 600, 2), "dp_kpa": round(int(f["dp_kpa"].reshape(sh)[k].sum()) / 600, 1),
                               "heat_kwh": round(int(f["heat_kw"].reshape(sh)[k].sum()) / 600, 1), "chillers_running": int(run[k].max()),
                               "chillers_needed": int(need[k].max())})
        else:
            for k in range(H):
                g = lambda key: f[key].reshape(sh)[k]      # noqa: E731
                a_rows.append({"hour": hours[k], "unit": d, "hall": x["hall"], "kind": x["family"],
                               "sup_c": round(int(g("sup_c").sum()) / 6000, 2), "sup_max_c": round(int(g("sup_c").max()) / 100, 2),
                               "ret_c": round(int(g("ret_c").sum()) / 6000, 2), "fan_pct": round(int(g("fan_pct").sum()) / 60, 1),
                               "fans_min": int(g("fans_ok").min()), "valve_pct": round(int(g("valve_pct").sum()) / 600, 1),
                               "cw_in_c": round(int(g("cw_in_c").sum()) / 6000, 2), "cw_out_c": round(int(g("cw_out_c").sum()) / 6000, 2),
                               "flow_lps": round(int(g("flow_lps").sum()) / 6000, 3), "load_kwh": round(int(g("load_kw").sum()) / 600, 2),
                               "kwh": round(int(g("kw").sum()) / 60000, 3),
                               "alarm_min": int(g("fan_alarm").sum()), "inhibit_min": int(g("hi_inhibit").sum())})
    return {"chiller_hourly.csv": ch_rows, "pump_hourly.csv": p_rows, "loop_hourly.csv": l_rows, "air_hourly.csv": a_rows}


def _windows(dev: dict[str, dict], states: list[dict], M: int, start: datetime, before: int, after: int) -> list[dict]:
    """One-minute windows around every state change, per device (merged where they overlap). The utility outage opens a
    window on every chiller and pump and the loop."""
    spans: dict[str, list[tuple[int, int]]] = {}
    for s in states:
        targets = [s["device"]]
        if s["device"] == "SITE":
            targets = [d for d, x in dev.items() if x["family"] in ("chiller", "pump", "loop")]
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
            if b - a > 24 * HOUR_MIN:
                continue                          # long spans (a lockout) are in the hourly tables; the window is its edges
            out.append({"device": d, "family": dev[d]["family"], "from": iso(start + a * MIN), "minutes": b - a, "m0": a,
                        "fields": {k: v[a:b].tolist() for k, v in dev[d]["fields"].items()},
                        "states": [s for s in states if a <= s["m"] < b and s["device"] in (d, "SITE")]})
    return out


def write_mechanical(layer: MechanicalTelemetry, out: dict[str, Any], dest: str | Path, source: str = "",
                     minutes_dest: str | Path | None = None) -> dict[str, Any]:
    """Write the committed tiers to dest and the publish-time tier (each device's minutes) to minutes_dest if given."""
    cfg = layer.cfg
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    win = dest / "windows"
    if win.exists():
        for p in win.glob("*.json"):
            p.unlink()
    win.mkdir(exist_ok=True)
    dev = device_fields(layer, out)
    tables = hourly_rows(layer, dev, out)
    cols = {"chiller_hourly.csv": CHILLER_HOURLY, "pump_hourly.csv": PUMP_HOURLY, "loop_hourly.csv": LOOP_HOURLY, "air_hourly.csv": AIR_HOURLY}
    for name, rows in tables.items():
        (dest / name).write_text(_csv(rows, cols[name]), encoding="utf-8", newline="\n")
    states = out["states"]
    (dest / "states.jsonl").write_text("".join(json.dumps(s, sort_keys=True) + "\n" for s in states), encoding="utf-8", newline="\n")
    index = []
    for w in _windows(dev, states, layer.M, layer.start, cfg["tiers"]["window_before_min"], cfg["tiers"]["window_after_min"]):
        name = f"{w['device']}_{w['from'][:16].replace('-', '').replace(':', '')}"
        (win / f"{name}.json").write_text(_dump(w), encoding="utf-8", newline="\n")
        index.append({"file": f"windows/{name}.json", "device": w["device"], "from": w["from"], "minutes": w["minutes"]})
    minutes = {}
    for d, x in sorted(dev.items()):
        meta = {k: v for k, v in x.items() if k != "fields"}
        minutes[f"{d}.json"] = _dump({"device": d, **meta, "start": iso(layer.start), "minutes": layer.M,
                                      "encoding": "first value, then minute-to-minute steps; [n] is n minutes unchanged; divide by the field's scale",
                                      "fields": {k: pack(v) for k, v in x["fields"].items()}})
    if minutes_dest is not None:
        md = Path(minutes_dest)
        md.mkdir(parents=True, exist_ok=True)
        for name, text in minutes.items():
            (md / name).write_text(text, encoding="utf-8", newline="\n")
    devices = {}
    for d, x in sorted(dev.items()):
        meta = {k: v for k, v in x.items() if k != "fields"}
        devices[d] = meta
    man = {"disclaimer": "Synthetic mechanical telemetry for a portfolio demonstration, using the point names Vertiv publishes for its "
                         "iCOM controllers and the ASHRAE 135 (BACnet) object model. All names and readings are fictional.",
           "source": source, "window": {"start": iso(layer.start), "end": iso(layer.end)}, "devices": devices,
           "files": {**{k: len(v) for k, v in tables.items()}, "states.jsonl": len(states), "windows": len(index)},
           "windows": index,
           "minutes": {name: {"sha256": hashlib.sha256(t.encode()).hexdigest(), "bytes": len(t.encode())} for name, t in minutes.items()}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
