"""Agreements between the utility mains metering, the ride-through, and the records already written for the month.

Like the power set (``scorecard.telemetry_power``), each check reads only what is published (``data/telemetry/utility/``,
the power telemetry, the energy meters, and the EPMS events) and the files built at publish time, never the
generator's internals.

1. energy: both mains together carry the energy meters' utility energy every hour, and each main's hourly kWh equals
   its minutes.
2. outage: each main reads no voltage and its breaker reads open from the EPMS trip to the retransfer, its current
   and kW are zero over every minute wholly inside, the trip's minute records the sag (lowest voltage zero), and every
   other minute is live.
3. ohms_law: each live minute's current equals kW over (sqrt 3 x V x PF), and kVAR agrees with the power factor.
4. quality: voltage stays inside the service band and frequency matches the frequency every UPS input publishes,
   whenever the main is live.
5. buses: each main carries at least the input of the UPSs whose unit substations sit on its bus, every live minute.
6. ride_through: each minute's published ride-through is the shortest runtime among the UPSs in scope carrying load,
   from the UPSs' own published fields, and names the UPS that sets it.
7. runtime: each UPS's reported runtime agrees with its battery capacity (5 minutes at full rated load) times its charge
   over its load, or the network management card's cap at light load.
8. bridge: in each utility outage, every UPS's seconds on battery equal the EPMS trip to the generator ties closing, and
   that bridge is shorter than the ride-through the site had when the utility failed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from scorecard.telemetry import MIN, Check, _csv, _jsonl, parse
from scorecard.telemetry_power import PowerData, unpack

HOUR = 60


@dataclass
class UtilityData:
    dir: Path
    minutes_dir: Path
    manifest: dict
    mains_hourly: list[dict]
    ride_hourly: list[dict]
    power: PowerData
    _minutes: dict

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def M(self) -> int:
        return int((parse(self.manifest["window"]["end"]) - self.start).total_seconds() // 60)

    def minutes(self, main: str) -> dict[str, np.ndarray]:
        if main not in self._minutes:
            raw = json.loads((self.minutes_dir / f"{main}.json").read_text(encoding="utf-8"))
            self._minutes[main] = {k: unpack(v) for k, v in raw["fields"].items()}
        return self._minutes[main]

    def ride(self) -> dict[str, dict]:
        if "_ride" not in self._minutes:
            raw = json.loads((self.minutes_dir / "ride_through.json").read_text(encoding="utf-8"))
            self._minutes["_ride"] = {s: {"ups": x["ups"], "s": unpack(x["s"]), "k": unpack(x["k"])} for s, x in raw["scopes"].items()}
        return self._minutes["_ride"]


def load(utility_dir: str | Path, minutes_dir: str | Path, power: PowerData) -> UtilityData:
    d = Path(utility_dir)
    return UtilityData(dir=d, minutes_dir=Path(minutes_dir), manifest=json.loads((d / "manifest.json").read_text(encoding="utf-8")),
                       mains_hourly=_csv(d / "mains_hourly.csv"), ride_hourly=_csv(d / "ride_through_hourly.csv"), power=power, _minutes={})


def outages(t: UtilityData) -> list[dict]:
    """Trip and retransfer per outage, read from the EPMS the way a client would."""
    out, cur = [], None
    for e in t.power.epms:
        if e["device"].endswith("main breaker") and "Trip (utility undervoltage)" in e["event"]:
            if cur is None or parse(e["timestamp"]) != cur["trip"]:
                cur = {"trip": parse(e["timestamp"])}
                out.append(cur)
        elif cur is not None and e["device"] == "Generator tie breakers" and e["event"].startswith("Closed"):
            cur.setdefault("ties_closed", parse(e["timestamp"]))
        elif cur is not None and e["device"].endswith("main breaker") and "utility restored" in e["event"]:
            cur.setdefault("back", parse(e["timestamp"]))
    return out


def agreements(t: UtilityData, cfg: dict[str, Any], pcfg: dict[str, Any]) -> list[Check]:
    ck = cfg["checks"]
    p = t.power
    M, H = t.M, t.M // HOUR
    mains = sorted(t.manifest["mains"])
    f = {b: t.minutes(b) for b in mains}
    outs = outages(t)
    dead_s = np.zeros(M)
    closed = np.ones(M, dtype=bool)
    for o in outs:
        dead_s += p.seconds(o["trip"], o["back"])
        closed[p.m_of(o["trip"]):p.m_of(o["back"])] = False
    trip_m = {int((o["trip"] - t.start).total_seconds() // 60) for o in outs}
    checks = []

    c = Check("energy", "Both mains together carry the energy meters' utility energy every hour; each main's hourly kWh is its minutes")
    hourly = {(r["main"], r["hour"]): r for r in t.mains_hourly}
    for h in range(H):
        hr = p.hour(h)
        meter = p.meters.get(hr)
        mine = sum(float(f[b]["kw"][h * HOUR:(h + 1) * HOUR].sum()) / 600 for b in mains)
        if meter is not None:
            c(abs(mine - float(meter["utility_kwh"])) <= ck["energy_kwh_tolerance"], f"{hr}: mains {mine:.1f} kWh, meter {meter['utility_kwh']}")
        for b in mains:
            r = hourly.get((b, hr))
            got = float(f[b]["kw"][h * HOUR:(h + 1) * HOUR].sum()) / 600
            c(r is not None and abs(float(r["kwh"]) - got) <= 0.01, f"{b} {hr}: hourly table {r and r['kwh']}, minutes {got:.2f}")
    checks.append(c)

    c = Check("outage", "Each main is dead and open from the EPMS trip to the retransfer, carries nothing inside, records the sag, and is live otherwise")
    for b in mains:
        x = f[b]
        live = (x["v_ab"] > 0) & (x["v_bc"] > 0) & (x["v_ca"] > 0)
        for m in range(M):
            if not closed[m]:
                c(not live[m] and x["brk"][m] == 0 and x["hz"][m] == 0, f"{b} minute {m}: read live inside the outage")
                if dead_s[m] >= 60:
                    c(x["kw"][m] == 0 and x["a_a"][m] == 0 and x["a_b"][m] == 0 and x["a_c"][m] == 0, f"{b} minute {m}: current inside the outage")
            else:
                c(bool(live[m]) and x["brk"][m] == 1 and x["kw"][m] > 0, f"{b} minute {m}: dead or open outside an outage")
        for m in trip_m:
            c(x["v_min"][m] == 0, f"{b}: the trip's minute {m} does not record the sag")
    checks.append(c)

    c = Check("ohms_law", "Each live minute's current is kW over (sqrt 3 x V x PF), and kVAR agrees with the power factor")
    for b in mains:
        x = f[b]
        for m in np.nonzero((dead_s == 0) & (x["kw"] > 0))[0]:
            v = (x["v_ab"][m] + x["v_bc"][m] + x["v_ca"][m]) / 3
            pf = x["pf"][m] / 1000
            kw = x["kw"][m] / 10
            want = kw * 1000 / (math.sqrt(3) * v * pf)
            got = (x["a_a"][m] + x["a_b"][m] + x["a_c"][m]) / 30
            kvar = kw * math.sqrt(max(1 - pf * pf, 0.0)) / pf
            c(abs(got - want) <= want * ck["amps_tolerance_pct"] / 100 + 0.1 and abs(x["kvar"][m] / 10 - kvar) <= kw * 0.003 + 0.5,
              f"{b} minute {m}: {got:.1f} A against {want:.1f} A")
    checks.append(c)

    c = Check("quality", "Voltage stays inside the service band, and frequency matches every UPS input's, while the main is live")
    lo, hi = cfg["checks"]["voltage_band_pct"]
    nom = cfg["electrical"]["nominal_v"]
    ups = p.devices("ups")
    in_hz = np.stack([p.minutes(u)["in_hz"] for u in ups]) / 10
    for b in mains:
        x = f[b]
        for m in np.nonzero(closed)[0]:
            vs = (x["v_ab"][m], x["v_bc"][m], x["v_ca"][m])
            ok_v = all(nom * (1 + lo / 100) <= v <= nom * (1 + hi / 100) for v in vs)
            # in a minute the utility failed or returned, the UPS inputs saw the generators' frequency too
            ok_hz = dead_s[m] > 0 or bool(np.all(np.abs(in_hz[:, m] - x["hz"][m] / 100) <= ck["frequency_tolerance_hz"] + 1e-9))
            c(ok_v and ok_hz, f"{b} minute {m}: {vs} V, {x['hz'][m] / 100} Hz")
    checks.append(c)

    c = Check("buses", "Each main carries at least the input of the UPSs on its bus, every minute the utility carries the site")
    for b in mains:
        on_bus = t.manifest["mains"][b]["ups"]
        need = sum(p.minutes(u)["in_kw"] for u in on_bus) / 10
        x = f[b]
        for m in np.nonzero(dead_s == 0)[0]:
            c(x["kw"][m] / 10 >= need[m] - 0.5, f"{b} minute {m}: {x['kw'][m] / 10} kW, its UPSs draw {need[m]:.1f} kW")
    checks.append(c)

    c = Check("ride_through", "Each minute's ride-through is the shortest runtime among the UPSs in scope carrying load, and names that UPS")
    floor = int(round(cfg["ride_through"]["min_load_kw"] * 10))
    ride = t.ride()
    for s, x in ride.items():
        need_load = s != "SITE-COOLING"
        rt = np.stack([p.minutes(u)["runtime_s"] for u in x["ups"]])
        kw = np.stack([p.minutes(u)["out_kw"] for u in x["ups"]])
        for m in range(M):
            ok = kw[:, m] >= floor if need_load else np.ones(len(x["ups"]), dtype=bool)
            want = int(rt[ok, m].min()) if ok.any() else -1
            k = int(x["k"][m])
            names = want < 0 or (0 <= k < len(x["ups"]) and ok[k] and rt[k, m] == want)
            c(int(x["s"][m]) == want and names, f"{s} minute {m}: published {x['s'][m]} s, UPSs give {want} s")
    rows = {(r["scope"], r["hour"]): r for r in t.ride_hourly}
    for s, x in ride.items():
        for h in range(H):
            r = rows.get((s, p.hour(h)))
            v = x["s"][h * HOUR:(h + 1) * HOUR]
            want = str(int(v[v >= 0].min())) if (v >= 0).any() else ""
            c(r is not None and r["min_s"] == want, f"{s} {p.hour(h)}: hourly {r and r['min_s']}, minutes {want}")
    checks.append(c)

    c = Check("runtime", "Each UPS's reported runtime agrees with its battery capacity times its charge over its load (or the card's cap)")
    cap_s = pcfg["ups"]["battery"]["runtime_cap_min"] * 60
    for u in ups:
        x = p.minutes(u)
        rating = p.manifest["devices"][u]["rating_kw"]
        cap_kwh = rating * 5 / 60
        load = np.maximum(x["out_kw"] / 10, 1.0)
        est = np.minimum(cap_kwh * x["soc_pct"] / 100 / load * 3600, cap_s)
        # the charge is published in whole percent: allow its rounding on top of the runtime's 10 s
        slack = ck["runtime_tolerance_s"] + cap_kwh * 0.5 / 100 / load * 3600
        bad = np.nonzero(np.abs(x["runtime_s"] - est) > slack)[0]
        for m in range(0, M, HOUR):
            c(not ((bad >= m) & (bad < m + HOUR)).any(), f"{u} hour {m // HOUR}: runtime {x['runtime_s'][m]} s, capacity gives {est[m]:.0f} s")
    checks.append(c)

    c = Check("bridge", "In each utility outage every UPS's battery seconds equal the trip to the ties closing, shorter than the ride-through then")
    by = {(r["ups"], r["hour"]): int(r["battery_s"]) for r in p.ups_hourly}
    for o in outs:
        bridge = (o["ties_closed"] - o["trip"]).total_seconds()
        hr = o["trip"].replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        for u in ups:
            got = by.get((u, hr))
            c(got is not None and abs(got - bridge) <= 2, f"{u} {hr}: {got} s on battery, EPMS bridge {bridge:.0f} s")
        m = int((o["trip"] - t.start).total_seconds() // 60)
        for s in ("SITE-IT", "SITE-COOLING"):
            c(int(ride[s]["s"][m]) > bridge, f"{s}: ride-through {ride[s]['s'][m]} s at the trip, bridge {bridge:.0f} s")
        mo = next((x for x in t.manifest["outages"] if x["trip"] == o["trip"].strftime("%Y-%m-%dT%H:%M:%SZ")), None)
        c(mo is not None and mo["bridge_s"] == round(bridge) and mo["ride_it_s"] == int(ride["SITE-IT"]["s"][m]),
          f"manifest outage at {o['trip']}: {mo}")
    checks.append(c)
    return checks


def summary(checks: list[Check]) -> dict[str, Any]:
    return {"checks": len(checks), "cases": sum(c.checked for c in checks), "agree": sum(c.checked - len(c.misses) for c in checks)}


def fmt_s(s: int) -> str:
    """Seconds as m:ss (the ride-through's form)."""
    return f"{s // 60}:{s % 60:02d}" if s >= 0 else "–"


__all__ = ["UtilityData", "load", "agreements", "outages", "summary", "fmt_s", "MIN"]
