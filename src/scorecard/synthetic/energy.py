"""Synthetic energy meters for Site AUS-1: hourly kWh at the meters a PUE report reads.

Portfolio demo; all data fictional. Runs on a finished month (the committed sample or a generated
month) with its own random stream and writes beside it, never into it:

* ``meters_hourly.csv``: one row per hour. Utility and generator energy delivered to the site, UPS
  input and output per hall (output is IT energy), the mechanical UPS per hall (CDU pumps and
  thermal-wall fans), the chiller yard, the facility water pumps, the electrical-room CRAHs, the
  house panel, and the outdoor and facility water temperatures.
* ``chiller_events.jsonl``: free-cooling lockouts and re-enables on each chiller, from the BMS.
* ``landlord_energy_report.json``: the Landlord's monthly energy report (its own PUE figure).
* ``answer_key.json``: what was planted, for the engine self-check only.
* ``history_daily.csv`` (committed sample only): 12 four-week periods before the month, by day.

IT energy follows the UPS load readings already in the month (``facility/ups_status.jsonl``);
generator energy counts toward the site only while the utility mains are open (``epms_events``),
so a monthly loaded exercise on a portable load bank is left out. Cooling follows a modeled Central
Texas temperature and the heat the halls reject. Sizes come from ``site/site.yaml`` and the
assumptions from ``config/energy.yaml``.
"""

from __future__ import annotations

import csv
import io
import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from scorecard import site_model as S

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "energy.yaml"
UTC = timezone.utc
HOUR = timedelta(hours=1)

METERS = ["utility_kwh", "generator_kwh", "ups_in_a_kwh", "ups_out_a_kwh", "ups_in_b_kwh", "ups_out_b_kwh",
          "mech_a_kwh", "mech_b_kwh", "chillers_kwh", "pumps_kwh", "crah_kwh", "house_kwh"]
COLUMNS = ["hour", "outdoor_c", "fw_supply_c"] + METERS
HISTORY_COLUMNS = ["date", "outdoor_c", "facility_kwh", "it_kwh", "cooling_kwh", "power_loss_kwh", "other_kwh"]


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_offset_h(dt: datetime) -> int:
    """Central time offset from UTC: -5 in daylight time (second Sunday of March to first Sunday of
    November, 2 a.m. local), -6 otherwise. Computed, so no time zone database is needed (Windows)."""
    y = dt.year
    mar = date(y, 3, 8) + timedelta(days=(6 - date(y, 3, 8).weekday()) % 7)
    nov = date(y, 11, 1) + timedelta(days=(6 - date(y, 11, 1).weekday()) % 7)
    on = datetime(y, mar.month, mar.day, 8, tzinfo=UTC)     # 2 a.m. CST
    off = datetime(y, nov.month, nov.day, 7, tzinfo=UTC)    # 2 a.m. CDT
    return -5 if on <= dt < off else -6


def local(dt: datetime) -> datetime:
    return dt + timedelta(hours=utc_offset_h(dt))


def _read(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(x) for x in text.splitlines() if x.strip()]
    if path.suffix == ".csv":
        return list(csv.DictReader(io.StringIO(text)))
    return json.loads(text)


# --------------------------------------------------------------------------- #
# The physical model, shared by the month and the history
# --------------------------------------------------------------------------- #
class Plant:
    """Site sizes from site/site.yaml and the energy assumptions; one call per hour."""

    def __init__(self, cfg: dict[str, Any], site: dict[str, Any] | None = None):
        self.cfg, self.site = cfg, site or S.load_site()
        s = self.site
        self.halls = {h["letter"]: h for h in s["halls"] if h["state"] in ("production", "deployment")}
        self.ups_eff = {k: S.product(s, h["power"]["ups_product"])["efficiency"] for k, h in self.halls.items()}
        self.mups_eff = {k: S.product(s, h["power"]["mech_ups_product"])["efficiency"] for k, h in self.halls.items()}
        self.ups_kw = {k: S.product(s, h["power"]["ups_product"])["rating_kw"] for k, h in self.halls.items()}
        self.mups_kw = {k: S.product(s, h["power"]["mech_ups_product"])["rating_kw"] for k, h in self.halls.items()}
        self.crah_kw = sum(S.hall_crah_kw(s, h) for h in self.halls.values())
        hr = s["plants"]["heat_rejection"]
        self.chillers = [f"CH-{i:02d}" for i in range(1, hr["chiller_count"] + 1)]
        self.cop_design = S.product(s, hr["chiller_product"])["cop_at_design_ambient"]
        self.design_c = s["site"]["design_ambient_c"]
        self.duty_pumps = hr["pump_count"] - hr["pump_redundancy"]
        self.pump_kw = S.product(s, hr["pump_product"])["power_kw"]
        self.design_heat = S.site_heat_kw(s)
        self.house_kw = s["site"]["house_load_kw"]

    def cop(self, t: float) -> float:
        p = self.cfg["plant"]
        return min(p["cop_max"], self.cop_design + p["cop_slope_per_c"] * (self.design_c - t))

    def free_fraction(self, t: float) -> float:
        p = self.cfg["plant"]
        lo, hi = p["free_cooling_full_below_c"], p["free_cooling_none_above_c"]
        return max(0.0, min(1.0, (hi - t) / (hi - lo)))

    def running(self, heat_kw: float) -> int:
        return max(2, math.ceil(heat_kw / self.cfg["plant"]["chiller_running_kw"]))

    def hour(self, t_out: float, it: dict[str, float], mech_out: dict[str, float], locked: int, local_hour: int,
             noise: Any) -> dict[str, float]:
        """kW for one hour (equal to kWh). ``it`` and ``mech_out`` are UPS output kW per hall; ``locked`` is the
        number of chillers with free cooling disabled; ``noise()`` returns a multiplier near 1."""
        p = self.cfg["plant"]
        r: dict[str, float] = {}
        heat = 0.0
        for k in self.halls:
            r[f"ups_out_{k.lower()}_kwh"] = it[k]
            r[f"ups_in_{k.lower()}_kwh"] = it[k] / self.ups_eff[k]
            r[f"mech_{k.lower()}_kwh"] = mech_out[k] / self.mups_eff[k]
            heat += r[f"ups_in_{k.lower()}_kwh"] + r[f"mech_{k.lower()}_kwh"]
        r["crah_kwh"] = self.crah_kw * noise()
        heat += r["crah_kwh"]
        n = self.running(heat)
        free = self.free_fraction(t_out) * max(0.0, 1 - locked / n)
        r["chillers_kwh"] = heat * (free * p["free_cooling_kw_per_kw"] + (1 - free) / self.cop(t_out)) * noise()
        speed = max(p["pump_floor"], min(1.0, heat / self.design_heat))
        r["pumps_kwh"] = self.duty_pumps * self.pump_kw * speed ** p["pump_exponent"] * noise()
        day = 7 <= local_hour < 19
        r["house_kwh"] = self.house_kw * self.cfg["house_day_factor" if day else "house_night_factor"] * noise()
        metered = sum(v for k, v in r.items() if not k.startswith("ups_out"))
        r["facility_kwh"] = metered * (1 + self.cfg["distribution_loss_fraction"])
        return r


class Weather:
    """Hourly outdoor dry bulb: monthly normal, a daily cycle, and a persistent daily anomaly."""

    def __init__(self, cfg: dict[str, Any], rng: random.Random):
        self.w, self.rng, self.anom, self.day = cfg["weather"], rng, 0.0, None

    def at(self, dt: datetime) -> float:
        loc = local(dt)
        if loc.date() != self.day:
            self.day = loc.date()
            a = self.w["anomaly_persistence"]
            self.anom = a * self.anom + math.sqrt(1 - a * a) * self.rng.gauss(0, self.w["anomaly_sd_c"])
        mean = self.w["monthly_mean_c"][loc.month]
        phase = 2 * math.pi * (loc.hour - self.w["coldest_local_hour"]) / 24
        return mean + self.anom - self.w["diurnal_half_range_c"] * math.cos(phase)


# --------------------------------------------------------------------------- #
# One month of meters
# --------------------------------------------------------------------------- #
class EnergyLayer:
    def __init__(self, data_dir: str | Path, seed: int, cfg: dict[str, Any] | None = None, site: dict | None = None):
        self.dir = Path(data_dir)
        self.cfg = cfg or load_config()
        self.plant = Plant(self.cfg, site)
        self.seed = seed
        self.rng = random.Random(f"{seed}:energy")          # independent of every other stream
        man = _read(self.dir / "manifest.json")
        self.start, self.end = parse(man["window"]["start"]), parse(man["window"]["end"])

    def _noise(self) -> float:
        return 1 + self.rng.gauss(0, self.cfg["meter_noise_sd"])

    # ---- the month's own records
    def _ups_series(self) -> dict[str, list[tuple[datetime, float]]]:
        series: dict[str, list[tuple[datetime, float]]] = {}
        for r in _read(self.dir / "facility" / "ups_status.jsonl"):
            series.setdefault(r["ups"], []).append((parse(r["timestamp"]), r["load_pct"]))
        return {k: sorted(v) for k, v in series.items()}

    @staticmethod
    def _interp(series: list[tuple[datetime, float]], t: datetime) -> float:
        if t <= series[0][0]:
            return series[0][1]
        for (t0, v0), (t1, v1) in zip(series, series[1:]):
            if t0 <= t < t1:
                return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        return series[-1][1]

    def outages(self) -> list[tuple[datetime, datetime]]:
        """When the utility mains were open and the generators carried the site (EPMS breaker events)."""
        out, opened = [], None
        for e in sorted(_read(self.dir / "facility" / "epms_events.jsonl"), key=lambda e: e["timestamp"]):
            if e["device"] != "MV-A main breaker":
                continue
            if "utility undervoltage" in e["event"]:
                opened = parse(e["timestamp"])
            elif "utility restored" in e["event"] and opened:
                out.append((opened, parse(e["timestamp"])))
                opened = None
        return out

    def generator_kwh(self) -> dict[datetime, float]:
        """Generator energy delivered to the site per hour: EMCP readings inside a utility outage only."""
        spans = self.outages()
        by_gen: dict[str, list[dict]] = {}
        for r in _read(self.dir / "facility" / "emcp_readings.jsonl"):
            by_gen.setdefault(r["generator"], []).append(r)
        out: dict[datetime, float] = {}
        for rows in by_gen.values():
            rows.sort(key=lambda r: r["timestamp"])
            for a, b in zip(rows, rows[1:]):
                t0, t1 = parse(a["timestamp"]), min(parse(b["timestamp"]), parse(a["timestamp"]) + timedelta(minutes=2))
                for s0, s1 in spans:
                    lo, hi = max(t0, s0), min(t1, s1)
                    while lo < hi:
                        h = lo.replace(minute=0, second=0, microsecond=0)
                        step = min(hi, h + HOUR)
                        out[h] = out.get(h, 0.0) + a["gen_total_kw"] * (step - lo).total_seconds() / 3600
                        lo = step
        return out

    def chiller_pms(self) -> list[dict]:
        rows = _read(self.dir / "landlord" / "pm_records.csv")
        return sorted((r for r in rows if r["system"] == "Chillers" and r["completed_at"]), key=lambda r: r["completed_at"])

    # ---- planted cases
    def plan_lockouts(self) -> tuple[list[dict], list[dict]]:
        """Every chiller PM disables free cooling on its unit while the work is done and re-enables it at
        the end (a short lockout, not a finding). On one PM the re-enable is missed: free cooling stays
        locked out for days with no change record (the planted finding)."""
        pc = self.cfg["plants"]
        pms = self.chiller_pms()
        events, key = [], []
        miss = self.rng.randrange(len(pms)) if pms else None
        for i, pm in enumerate(pms):
            done = parse(pm["completed_at"])
            began = done - timedelta(hours=self.rng.uniform(*pc["decoy_lockout_hours"]))
            events.append({"timestamp": iso(began), "chiller": pm["asset"], "event": "Free cooling disabled",
                           "mode": "Local override", "user": pm["engineer"], "note": f"{pm['task_id']} {pm['task']}"})
            if i == miss:
                back = min(done + timedelta(days=self.rng.uniform(*pc["lockout_days"])), self.end - timedelta(hours=1))
                key.append({"chiller": pm["asset"], "start": iso(began), "end": iso(back), "pm": pm["task_id"]})
                events.append({"timestamp": iso(back), "chiller": pm["asset"], "event": "Free cooling enabled",
                               "mode": "BMS auto", "user": "BMS", "note": "Restored to BMS auto during a plant review"})
            else:
                events.append({"timestamp": iso(done), "chiller": pm["asset"], "event": "Free cooling enabled",
                               "mode": "BMS auto", "user": pm["engineer"], "note": f"{pm['task_id']} complete"})
        return sorted(events, key=lambda e: (e["timestamp"], e["chiller"])), key

    def _locked_at(self, events: list[dict], t: datetime) -> int:
        state: dict[str, bool] = {}
        for e in events:
            if parse(e["timestamp"]) > t:
                break
            state[e["chiller"]] = e["event"] == "Free cooling disabled"
        return sum(state.values())

    # ---- the month
    def run(self, report_error: str | None = None) -> dict[str, Any]:
        ups = self._ups_series()
        gens = self.generator_kwh()
        events, lockouts = self.plan_lockouts()
        weather = Weather(self.cfg, self.rng)
        rows = []
        t = self.start
        while t < self.end:
            mid = t + HOUR / 2
            it, mech = {}, {}
            for k in self.plant.halls:
                it[k] = sum(self._interp(ups[u], mid) / 100 * self.plant.ups_kw[k] for u in ups if u.startswith(f"UPS-{k}")) * self._noise()
                mech[k] = sum(self._interp(ups[u], mid) / 100 * self.plant.mups_kw[k] for u in ups if u.startswith(f"MUPS-{k}")) * self._noise()
            t_out = weather.at(mid)
            r = self.plant.hour(t_out, it, mech, self._locked_at(events, mid), local(mid).hour, self._noise)
            gen = gens.get(t, 0.0)
            row = {"hour": iso(t), "outdoor_c": round(t_out, 1), "fw_supply_c": round(self.cfg["plant"]["supply_c"] + self.rng.gauss(0, 0.15), 1),
                   "generator_kwh": round(gen, 1), "utility_kwh": round(max(0.0, r["facility_kwh"] - gen), 1)}
            row.update({m: round(r[m], 1) for m in METERS if m not in row})
            rows.append(row)
            t += HOUR
        kind = report_error or self.rng.choice(self.cfg["plants"]["report_errors"])
        return {"meters": rows, "chiller_events": events, "report": self.landlord_report(rows, kind),
                "key": {"report_error": kind, "lockouts": lockouts}}

    def landlord_report(self, rows: list[dict], kind: str) -> dict[str, Any]:
        """The Landlord's monthly energy report, as submitted. ``kind`` is how it was prepared:
        ``none`` follows the standard; the others are the preparation errors the check looks for."""
        tot = {m: sum(r[m] for r in rows) for m in METERS}
        facility = tot["utility_kwh"] + tot["generator_kwh"]
        it = tot["ups_out_a_kwh"] + tot["ups_out_b_kwh"]
        if kind == "ups_input_as_it":
            it = tot["ups_in_a_kwh"] + tot["ups_in_b_kwh"]
        elif kind == "house_omitted":
            facility -= tot["house_kwh"]
        elif kind == "generator_omitted":
            facility = tot["utility_kwh"]
        facility, it = round(facility, -2), round(it, -2)
        return {"supplier": "Caprock Critical Facilities, LLC", "period": {"start": iso(self.start), "end": iso(self.end)},
                "standard": self.cfg["standard"]["name"], "total_facility_kwh": facility, "it_kwh": it,
                "pue": round(facility / it, 3),
                "method": "Total facility energy from the site revenue and generator meters; IT energy at the UPS meters."}


# --------------------------------------------------------------------------- #
# The 12 periods before the sample (the trend and the 52-week PUE)
# --------------------------------------------------------------------------- #
def history(month_rows: list[dict], start: datetime, seed: int, cfg: dict[str, Any] | None = None,
            site: dict | None = None) -> list[dict]:
    """Daily totals for the 12 four-week periods before ``start``. The IT load is the month's average per
    hall (Hall B ramping up as it deployed) with day-to-day variation; the rest follows the same model."""
    cfg = cfg or load_config()
    plant = Plant(cfg, site)
    rng = random.Random(f"{seed}:energy-history")
    noise = lambda: 1 + rng.gauss(0, cfg["meter_noise_sd"])   # noqa: E731
    n = len(month_rows)
    base_it = {k: sum(r[f"ups_out_{k.lower()}_kwh"] for r in month_rows) / n for k in plant.halls}
    base_mech = {k: sum(r[f"mech_{k.lower()}_kwh"] for r in month_rows) / n * plant.mups_eff[k] for k in plant.halls}
    periods = cfg["history"]["periods"]
    lo, hi = cfg["history"]["hall_b_ramp"]
    first = start - timedelta(days=28 * periods)
    weather = Weather(cfg, rng)
    out = []
    for d in range(28 * periods):
        day0 = first + timedelta(days=d)
        ramp = {k: 1.0 for k in plant.halls}
        ramp["B"] = lo + (hi - lo) * (d // 28) / max(1, periods - 1)
        level = {k: rng.gauss(1, 0.015) * ramp[k] for k in plant.halls}
        tot = {c: 0.0 for c in HISTORY_COLUMNS[1:]}
        for h in range(24):
            mid = day0 + timedelta(hours=h, minutes=30)
            t_out = weather.at(mid)
            it = {k: base_it[k] * level[k] * noise() for k in plant.halls}
            mech = {k: base_mech[k] * level[k] * noise() for k in plant.halls}
            r = plant.hour(t_out, it, mech, 0, local(mid).hour, noise)
            ups_in = sum(r[f"ups_in_{k.lower()}_kwh"] for k in plant.halls)
            tot["outdoor_c"] += t_out / 24
            tot["facility_kwh"] += r["facility_kwh"]
            tot["it_kwh"] += sum(it.values())
            tot["cooling_kwh"] += r["chillers_kwh"] + r["pumps_kwh"] + r["crah_kwh"] + sum(r[f"mech_{k.lower()}_kwh"] for k in plant.halls)
            tot["other_kwh"] += r["house_kwh"]
            tot["power_loss_kwh"] += ups_in - sum(it.values()) + r["facility_kwh"] - (r["facility_kwh"] / (1 + cfg["distribution_loss_fraction"]))
        out.append({"date": day0.date().isoformat(),
                    **{k: round(v, 1) for k, v in tot.items()}})
    return out


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def _csv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def write_energy(out: dict[str, Any], dest: str | Path, hist: list[dict] | None = None, source: str = "") -> dict[str, int]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    files = {
        "meters_hourly.csv": _csv(out["meters"], COLUMNS),
        "chiller_events.jsonl": "".join(json.dumps(e, sort_keys=True) + "\n" for e in out["chiller_events"]),
        "landlord_energy_report.json": json.dumps(out["report"], indent=2, sort_keys=True) + "\n",
        "answer_key.json": json.dumps(out["key"], indent=2, sort_keys=True) + "\n",
    }
    if hist is not None:
        files["history_daily.csv"] = _csv(hist, HISTORY_COLUMNS)
    counts = {"meters_hourly.csv": len(out["meters"]), "chiller_events.jsonl": len(out["chiller_events"]),
              "landlord_energy_report.json": 1, "answer_key.json": 1}
    if hist is not None:
        counts["history_daily.csv"] = len(hist)
    manifest = {"disclaimer": "Synthetic data for a portfolio demonstration. All sites, people, and events are fictional.",
                "source": source, "files": counts}
    files["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    for name, text in files.items():
        (dest / name).write_text(text, encoding="utf-8", newline="\n")
    return counts
