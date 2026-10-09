"""Agreements between the CDU telemetry and every record already written for the month.

Like the GPU set (``scorecard.telemetry``), each check reads only what the CDU telemetry publishes
(``data/telemetry/cdu/`` and the one-minute files built at publish time) and the existing records, never the
generator's internals, and returns how many cases it checked and which ones disagree.

1. supply: each CDU's secondary supply, hour by hour, has the mean and max in ``cdu_hourly.csv``.
2. flow: each CDU's secondary flow, hour by hour, has the mean and min in ``cdu_hourly.csv``.
3. pumps: a pump the records show failed or isolated is stopped; otherwise exactly one pump runs (two only
   while one is in test); flow dips only at a recorded pump failure or in an hour whose record leaves the
   band; pump redundancy is lost while a pump is failed, and only while a pump is down or in test.
4. leaks: the CDU's leak detectors read Critical exactly over the recorded leaks, and the reservoir level
   falls only while one is active.
5. heat: each hall's heat removed, hour by hour, equals the liquid share of its racks' power in the GPU
   telemetry (the GPUs plus the rest of the rack, ``config/telemetry_cdu.yaml``).
6. formula: every minute, HeatRemovedkW equals flow x density x specific heat x delta T.
7. facility_water: the primary supply, hour by hour, has the mean in ``energy/meters_hourly.csv``.
8. filter: the filter's pressure drop (corrected for flow) falls only at a recorded filter change, and falls
   at every one.
9. pump_power: the CDUs' own draw fits inside the metered mechanical UPS input of their hall, every hour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from scorecard import site_model as S
from scorecard.telemetry import MIN, Check, _csv, _jsonl, parse

HOUR = 60


def undelta(d: list[int]) -> np.ndarray:
    return np.cumsum(np.asarray(d, dtype=np.int64))


@dataclass
class CduData:
    dir: Path
    minutes_dir: Path
    manifest: dict
    hourly: list[dict]
    states: list[dict]
    records: dict[tuple[str, str], dict]
    events: list[dict]
    bms_leaks: list[dict]
    leak_events: list[dict]
    pm: list[dict]
    meters: dict[str, dict]
    rack_hourly: list[dict]
    _minutes: dict

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def cdus(self) -> list[str]:
        return sorted(self.manifest["cdus"])

    def minutes(self, cdu: str) -> dict[str, np.ndarray]:
        if cdu not in self._minutes:
            raw = json.loads((self.minutes_dir / f"{cdu}.json").read_text(encoding="utf-8"))
            self._minutes[cdu] = {"raw": raw, **{k: undelta(v) for k, v in raw["fields"].items()}}
        return self._minutes[cdu]

    def m_of(self, ts: str) -> int:
        """Index of the first reading at or after ts."""
        s = (parse(ts) - self.start).total_seconds() / 60
        return max(0, int(-(-s // 1)))


def load(cdu_dir: str | Path, minutes_dir: str | Path, health_dir: str | Path, sample_dir: str | Path,
         energy_dir: str | Path | None, gpu_dir: str | Path) -> CduData:
    d, sd = Path(cdu_dir), Path(sample_dir)
    pm = [r for r in _csv(sd / "landlord" / "pm_records.csv") if r.get("system") == "CDUs" and "Filter" in r.get("task", "")]
    return CduData(dir=d, minutes_dir=Path(minutes_dir),
                   manifest=json.loads((d / "manifest.json").read_text(encoding="utf-8")),
                   hourly=_csv(d / "cdu_hourly.csv"), states=_jsonl(d / "states.jsonl"),
                   records={(r["cdu"], r["hour"]): r for r in _csv(Path(health_dir) / "cdu_hourly.csv")},
                   events=_jsonl(sd / "facility" / "cdu_redfish_events.jsonl"),
                   bms_leaks=_jsonl(sd / "telemetry" / "bms_cdu_events.jsonl"),
                   leak_events=_jsonl(sd / "facility" / "leak_events.jsonl"), pm=pm,
                   meters={r["hour"]: r for r in _csv(Path(energy_dir) / "meters_hourly.csv")} if energy_dir else {},
                   rack_hourly=_csv(Path(gpu_dir) / "rack_hourly.csv"), _minutes={})


def _hour_iso(t: CduData, h: int) -> str:
    return (t.start + h * HOUR * MIN).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pump_records(t: CduData, cdu: str, M: int) -> dict[str, Any]:
    """From the Redfish events: per pump, minutes down (failed or isolated) and in test; failures; redundancy."""
    down = {1: np.zeros(M, bool), 2: np.zeros(M, bool)}
    test = {1: np.zeros(M, bool), 2: np.zeros(M, bool)}
    fail, red = [], np.zeros(M, bool)
    since: dict[tuple, int] = {}
    for e in sorted((e for e in t.events if e["cdu"] == cdu), key=lambda e: e["timestamp"]):
        m, prop, val = t.m_of(e["timestamp"]), e["property"], e["value"]
        if "/Pumps/" in e["resource"]:
            p = int(e["resource"].rsplit("/", 1)[1])
            if prop == "Status.Health" and val == "Critical":
                since[("crit", p)] = m
                fail.append((p, m, e["timestamp"]))
            elif prop == "Status.Health" and val == "OK":
                if ("crit", p) in since:
                    down[p][since.pop(("crit", p)):m] = True
                if ("test", p) in since:
                    test[p][since.pop(("test", p)):m] = True
            elif prop == "Status.State" and val == "Disabled":
                since[("dis", p)] = m
            elif prop == "Status.State" and val == "Enabled" and ("dis", p) in since:
                down[p][since.pop(("dis", p)):m] = True
            elif prop == "Status.State" and val == "InTest":
                if ("crit", p) in since:
                    down[p][since.pop(("crit", p)):m] = True
                since[("test", p)] = m
        elif prop == "PumpRedundancy.Status.Health":
            if val == "OK" and "red" in since:
                red[since.pop("red"):m] = True
            elif val != "OK":
                since.setdefault("red", m)
    for key, a in since.items():
        if key == "red":
            red[a:] = True
        else:
            (test if key[0] == "test" else down)[key[1]][a:] = True
    return {"down": down, "test": test, "fail": fail, "red": red}


def _leak_records(t: CduData, cdu: str, M: int) -> set[tuple[int, int, int]]:
    out, on = set(), {}
    for e in sorted(t.bms_leaks, key=lambda e: e["timestamp"]):
        if e.get("cdu") == cdu and e.get("alarm") == "LeakDetected":
            k = (2, e.get("point"))
            if e["state"] == "active":
                on.setdefault(k, t.m_of(e["timestamp"]))
            elif k in on:
                out.add((2, on.pop(k), t.m_of(e["timestamp"])))
    for e in sorted(t.leak_events, key=lambda e: e["timestamp"]):
        if e.get("label") == f"Under {cdu}":
            k = (1, e["label"])
            if e["event"] == "LEAK":
                on.setdefault(k, t.m_of(e["timestamp"]))
            elif e["event"] == "NORMAL" and k in on:
                out.add((1, on.pop(k), t.m_of(e["timestamp"])))
    for (det, _), a in on.items():
        out.add((det, a, M))
    return out


def agreements(t: CduData, cfg: dict[str, Any], health_cfg: dict[str, Any], site: dict | None = None) -> list[Check]:
    site = site or S.load_site()
    ck = cfg["checks"]
    co = cfg["coolant"]
    band = ck["flow_band_lpm"]
    design = health_cfg["cdu"]["flow_lpm"]
    supply = Check("supply", "Secondary supply: each hour's mean and max equal the CDU hourly record")
    flow = Check("flow", "Secondary flow: each hour's mean and min equal the CDU hourly record")
    pumps = Check("pumps", "Pumps: states, speeds, failover dips, and redundancy match the Redfish events")
    leaks = Check("leaks", "Leak detectors read Critical exactly over the recorded leaks; the reservoir falls only then")
    heat = Check("heat", "Heat removed per hall equals the liquid share of its racks' power in the GPU telemetry")
    formula = Check("formula", "HeatRemovedkW equals flow x density x specific heat x delta T, every minute")
    fw = Check("facility_water", "Primary supply: each hour's mean equals the metered facility water temperature")
    filt = Check("filter", "Filter pressure drop falls only at a recorded filter change, and at every one")
    power = Check("pump_power", "The CDUs' draw fits inside the metered mechanical UPS input of their hall")

    hall_of = {c: v["hall"] for c, v in t.manifest["cdus"].items()}
    by_hall_hour: dict[tuple[str, str], float] = {}
    pw_hall_hour: dict[tuple[str, str], float] = {}
    for c in t.cdus:
        x = t.minutes(c)
        M = int(x["raw"]["minutes"])
        H = M // HOUR
        s, f = x["sec_supply_c"], x["sec_flow_lpm"]
        # 1, 2: the hourly records
        for h in range(H):
            rec = t.records.get((c, _hour_iso(t, h)))
            sl = slice(h * HOUR, (h + 1) * HOUR)
            if rec is None:
                supply(False, f"{c} hour {_hour_iso(t, h)}: no record")
                continue
            ms, mx = int(s[sl].sum()), int(s[sl].max())
            supply(ms == round(float(rec["supply_c"]) * 100) * HOUR and mx == round(float(rec["supply_max_c"]) * 100),
                   f"{c} {rec['hour']}: telemetry mean {ms / HOUR / 100:.4f} max {mx / 100}; record {rec['supply_c']} / {rec['supply_max_c']}")
            mf, mn = int(f[sl].sum()), int(f[sl].min())
            flow(mf == int(rec["flow_lpm"]) * 10 * HOUR and mn == int(rec["flow_min_lpm"]) * 10,
                 f"{c} {rec['hour']}: telemetry mean {mf / HOUR / 10:.2f} min {mn / 10}; record {rec['flow_lpm']} / {rec['flow_min_lpm']}")
        # 3: pumps
        pr = _pump_records(t, c, M)
        p1, p2 = x["pump1_pct"], x["pump2_pct"]
        speed = {1: p1, 2: p2}
        for p in (1, 2):
            dn = pr["down"][p]
            if dn.any():
                pumps(not (speed[p][dn] > 0).any(), f"{c} pump {p} runs while the records show it failed or isolated")
        testing = pr["test"][1] | pr["test"][2]
        running = (p1 > 0).astype(int) + (p2 > 0).astype(int)
        bad = np.flatnonzero((running != 1) & ~testing)
        pumps(len(bad) == 0, f"{c}: {len(bad)} minutes without exactly one pump running, first minute {bad[:1].tolist()}")
        pumps.checked += M - 1
        bad = np.flatnonzero(testing & (running != 2))
        pumps(len(bad) == 0, f"{c}: a pump in test is not running at minute {bad[:1].tolist()}")
        drop = np.zeros(M, bool)
        drop[1:] = (f[:-1] - f[1:]) > 1000            # more than 100 L/min in a minute
        allowed = np.zeros(M, bool)
        for p, m, ts in pr["fail"]:
            hr = (parse(ts) - t.start).total_seconds() // 3600
            lo = int(hr * HOUR)
            ok = drop[lo: min(M, m + 3)].any()
            pumps(bool(ok), f"{c} pump {p} failed at {ts} with no flow dip")
            allowed[lo: min(M, m + 3)] = True
        for h in range(H):
            rec = t.records.get((c, _hour_iso(t, h)))
            if rec and int(rec["flow_min_lpm"]) < band:
                allowed[max(0, h * HOUR - HOUR): (h + 2) * HOUR] = True
        stray = np.flatnonzero(drop & ~allowed)
        pumps(len(stray) == 0, f"{c}: flow dips with no recorded pump failure at minutes {stray[:3].tolist()}")
        any_down = pr["down"][1] | pr["down"][2] | testing
        failed = np.zeros(M, bool)
        for p, m, _ts in pr["fail"]:
            nxt = np.flatnonzero(~pr["down"][p][m:])
            failed[m: m + (int(nxt[0]) if len(nxt) else M - m)] = True
        pumps(not (pr["red"] & ~any_down).any(), f"{c}: pump redundancy lost with both pumps available")
        pumps(not (failed & ~pr["red"]).any(), f"{c}: a pump failed with pump redundancy still reported OK")
        # 4: leaks
        want = _leak_records(t, c, M)
        got, on = set(), {}
        for st in t.states:
            if st["cdu"] != c or st["property"] != "DetectorState":
                continue
            det = int(st["resource"].rsplit("/", 1)[1])
            if st["value"] == "Critical":
                on[det] = st["m"]
            elif det in on:
                got.add((det, on.pop(det), st["m"]))
        for det, a in on.items():
            got.add((det, a, M))
        for w in sorted(want):
            leaks(w in got, f"{c} detector {w[0]}: recorded leak at minutes {w[1]} to {w[2]} not shown")
        for g in sorted(got - want):
            leaks(False, f"{c} detector {g[0]}: Critical at minutes {g[1]} to {g[2]} with no recorded leak")
        lv = x["reservoir_pct"]
        active = np.zeros(M, bool)
        for _d, a, b in want:
            active[a: min(M, b + 1)] = True
        blk = lv[: M // 10 * 10].reshape(-1, 10).mean(axis=1)
        act_blk = active[: M // 10 * 10].reshape(-1, 10).any(axis=1)
        for i in range(3, len(blk)):
            if blk[i - 3] - blk[i] > 3:                  # tenths of a percent over 30 minutes
                leaks(bool(act_blk[i - 3: i + 1].any()), f"{c}: reservoir falls at minute {i * 10} with no leak active")
        leaks(True, f"{c}: reservoir")
        # 6: heat formula, every minute
        dt = x["sec_dt_c"]
        pumps(bool((dt == x["sec_return_c"] - s).all()), f"{c}: DeltaTemperatureCelsius is not return minus supply")
        q = f / 10 / 60 * co["density_kg_per_l"] * co["cp_kj_per_kg_k"] * dt / 100
        err = np.abs(x["heat_kw"] / 10 - q)
        worst = int(np.argmax(err))
        formula(bool(err[worst] <= ck["heat_formula_kw"]), f"{c} minute {worst}: HeatRemovedkW {x['heat_kw'][worst] / 10} vs {q[worst]:.1f}")
        formula.checked += M - 1
        # 7, 9 inputs; 5 by hall below
        for h in range(H):
            hk = _hour_iso(t, h)
            sl = slice(h * HOUR, (h + 1) * HOUR)
            k = (hall_of[c], hk)
            by_hall_hour[k] = by_hall_hour.get(k, 0.0) + float(x["heat_kw"][sl].sum()) / HOUR / 10
            pw_hall_hour[k] = pw_hall_hour.get(k, 0.0) + float(x["power_w"][sl].sum()) / HOUR / 1000
            met = t.meters.get(hk)
            if met:
                got_c = int(x["pri_supply_c"][sl].sum()) / HOUR / 100
                fw(abs(got_c - float(met["fw_supply_c"])) <= 0.006,
                   f"{c} {hk}: primary supply mean {got_c:.3f}, metered {met['fw_supply_c']}")
        # 8: filter
        norm = x["filter_dp_kpa"] / 10 / np.maximum((f / 10 / design) ** 2, 0.05)
        changes = [t.m_of(r["completed_at"]) for r in t.pm if r["asset"] == c and r.get("completed_at")]
        steps = []
        for m in range(10, M - 10, 5):
            if np.median(norm[m - 10: m]) - np.median(norm[m: m + 10]) > ck["filter_step_kpa"]:
                steps.append(m)
        for m in changes:
            filt(any(abs(s_ - m) <= 10 for s_ in steps), f"{c}: no fall in filter pressure drop at the recorded change, minute {m}")
        stray = [s_ for s_ in steps if not any(abs(s_ - m) <= 10 for m in changes)]
        filt(not stray, f"{c}: filter pressure drop falls with no recorded change at minutes {stray[:3]}")

    # 5: heat balance by hall
    rr = cfg["rack_rest"]
    want_hall: dict[tuple[str, str], float] = {}
    for r in t.rack_hourly:
        hall = S.hall_by_id(site, r["hall"])
        lf = S.product(site, hall["rack_product"])["liquid_fraction"]
        k = (r["hall"], r["hour"])
        kw = rr["per_gpu_w"] * int(r["samples"]) / HOUR / 1000 + (1 + rr["per_gpu_watt"]) * float(r["power_kwh"] or 0)
        want_hall[k] = want_hall.get(k, 0.0) + lf * kw
    for k in sorted(by_hall_hour):
        w = want_hall.get(k, 0.0)
        got_k = by_hall_hour[k]
        heat(abs(got_k - w) <= max(ck["heat_balance_kw"], ck["heat_balance_fraction"] * w),
             f"{k[0]} {k[1]}: heat removed {got_k:.0f} kW, racks' liquid load {w:.0f} kW")
        met = t.meters.get(k[1])
        if met:
            mech = float(met.get(f"mech_{k[0][-1].lower()}_kwh") or 0)
            power(pw_hall_hour[k] <= mech, f"{k[0]} {k[1]}: CDUs draw {pw_hall_hour[k]:.1f} kW, mechanical UPS input {mech} kWh")
    return [supply, flow, pumps, leaks, heat, formula, fw, filt, power]
