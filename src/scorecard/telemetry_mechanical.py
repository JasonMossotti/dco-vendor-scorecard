"""Agreements between the mechanical telemetry and every record already written for the month.

Like the GPU, CDU, power, and network sets, each check reads only what the mechanical telemetry publishes
(``data/telemetry/mechanical/`` and the files built at publish time) and the existing records, never the generator's
internals, and returns how many cases it checked and which ones disagree.

1. meters: each hour, the chillers' summed draw equals the chiller meter, the pumps' the pump meter, and the CRAHs' the
   CRAH meter (``data/energy/meters_hourly.csv``).
2. walls: each hall's thermal walls plus its CDUs' own draw (CDU telemetry) equal its mechanical UPS output (power
   telemetry), every hour.
3. heat: the chillers' summed capacity equals the heat the plant rejects (every UPS input, the mechanical UPSs, and the
   CRAHs), the loop's flow equals the CDUs' primary flow plus the walls' and CRAHs' chilled water, and flow times the
   header difference is that heat.
4. water: the supply header's hourly mean is the metered facility water temperature, every running chiller leaves water
   near it, and every chiller's ambient reading averages to the metered outdoor temperature.
5. staging: as many chillers run as the plant needs, and none runs while tripped or held off by the BMS.
6. trips: each compressor trip on record shows at its minute: condensing pressure at the trip limit, BV 35 active and
   the compressor in ALARM exactly until the alarm cleared.
7. overrides: each BMS chiller-enable override holds the chiller off exactly over its span, each condenser fan override
   runs the fans at 100%, and each free-cooling lockout inhibits free cooling exactly over its span (the chiller runs on
   its compressors meanwhile).
8. air_events: each thermal-wall fan failure shows that fan failed and the other five carrying it exactly over the
   alarm, and each alarm inhibit sets Event_Algorithm_Inhibit exactly over its span.
9. quiet: no alarm, failed fan, BMS hold, or inhibit appears that the records do not have, and supply air never reaches
   the high supply limit (nothing was hidden by an inhibit).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from scorecard.telemetry import Check, _csv, _jsonl, parse
from scorecard.telemetry_power import unpack

HOUR = 60


@dataclass
class MechData:
    dir: Path
    minutes_dir: Path
    manifest: dict
    chiller_hourly: list[dict]
    pump_hourly: list[dict]
    loop_hourly: list[dict]
    air_hourly: list[dict]
    states: list[dict]
    bms: list[dict]
    fc_events: list[dict]
    meters: dict[str, dict]
    cdu_hourly: list[dict]
    ups_hourly: list[dict]
    _minutes: dict

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def M(self) -> int:
        return int((parse(self.manifest["window"]["end"]) - self.start).total_seconds() // 60)

    def devices(self, family: str) -> list[str]:
        return sorted(d for d, x in self.manifest["devices"].items() if x["family"] == family)

    def minutes(self, device: str) -> dict[str, np.ndarray]:
        if device not in self._minutes:
            raw = json.loads((self.minutes_dir / f"{device}.json").read_text(encoding="utf-8"))
            self._minutes[device] = {k: unpack(v) for k, v in raw["fields"].items()}
        return self._minutes[device]

    def m_of(self, ts: str) -> int:
        return max(0, min(self.M, math.ceil((parse(ts) - self.start).total_seconds() / 60 - 1e-9)))

    def hour(self, h: int) -> str:
        return (self.start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(mech_dir: str | Path, minutes_dir: str | Path, sample_dir: str | Path, energy_dir: str | Path,
         cdu_dir: str | Path, power_dir: str | Path) -> MechData:
    d = Path(mech_dir)
    return MechData(dir=d, minutes_dir=Path(minutes_dir), manifest=json.loads((d / "manifest.json").read_text(encoding="utf-8")),
                    chiller_hourly=_csv(d / "chiller_hourly.csv"), pump_hourly=_csv(d / "pump_hourly.csv"),
                    loop_hourly=_csv(d / "loop_hourly.csv"), air_hourly=_csv(d / "air_hourly.csv"), states=_jsonl(d / "states.jsonl"),
                    bms=sorted(_jsonl(Path(sample_dir) / "facility" / "bms_events.jsonl"), key=lambda e: (e["timestamp"], e["device"])),
                    fc_events=sorted(_jsonl(Path(energy_dir) / "chiller_events.jsonl"), key=lambda e: (e["timestamp"], e["chiller"])),
                    meters={r["hour"]: r for r in _csv(Path(energy_dir) / "meters_hourly.csv")},
                    cdu_hourly=_csv(Path(cdu_dir) / "cdu_hourly.csv"), ups_hourly=_csv(Path(power_dir) / "ups_hourly.csv"), _minutes={})


# ------------------------------------------------------------------------- the records, read the way a client would
def record_spans(t: MechData) -> dict[str, dict[str, list[tuple[int, int, Any]]]]:
    """Per device: trips, chiller-enable holds, condenser fan overrides, fan failures (with the fan), inhibits, and
    free-cooling lockouts, as minute spans [a, b)."""
    out: dict[str, dict[str, list]] = {}
    open_: dict[tuple[str, str], tuple[int, Any]] = {}

    def put(dev: str, kind: str, a: int, b: int, extra: Any = None) -> None:
        out.setdefault(dev, {}).setdefault(kind, []).append((a, b, extra))
    for e in t.bms:
        dev, m = e["device"], t.m_of(e["timestamp"])
        if e.get("kind") == "alarm" and e["state"] in ("active", "cleared"):
            if dev.startswith("CH-") and e["alarm"].startswith("Compressor trip"):
                kind, extra = "trip", None
            elif dev.startswith("TW-") and e["alarm"].startswith("Fan "):
                kind, extra = f"fan{e['alarm'].split()[1]}", int(e["alarm"].split()[1])
            else:
                continue
            if e["state"] == "active":
                open_[(dev, kind)] = (m, extra)
            elif (dev, kind) in open_:
                a, x = open_.pop((dev, kind))
                put(dev, "fan" if kind.startswith("fan") else kind, a, m, x)
        elif e.get("kind") in ("override", "inhibit"):
            kind = {"Chiller enable": "off", "Condenser fan speed": "fan100", "High supply air temperature alarm": "inhibit"}.get(e.get("point", ""))
            if kind is None:
                continue
            if e["action"] == "set":
                open_[(dev, kind)] = (m, e)
            elif (dev, kind) in open_:
                a, x = open_.pop((dev, kind))
                put(dev, kind, a, m, x)
    for e in t.fc_events:
        dev, m = e["chiller"], t.m_of(e["timestamp"])
        if e["event"] == "Free cooling disabled":
            open_[(dev, "lock")] = (m, e)
        elif (dev, "lock") in open_:
            a, x = open_.pop((dev, "lock"))
            put(dev, "lock", a, m, x)
    for (dev, kind), (a, x) in open_.items():
        put(dev, "fan" if kind.startswith("fan") else kind, a, t.M, x)
    return out


def _mask(spans: list, M: int) -> np.ndarray:
    out = np.zeros(M, dtype=bool)
    for a, b, *_ in spans:
        out[a:b] = True
    return out


def agreements(t: MechData, cfg: dict[str, Any], ecfg: dict[str, Any], site: dict[str, Any]) -> list[Check]:
    ck = cfg["checks"]
    meters_c = Check("meters", "Chillers, pumps, and CRAHs add up to their energy meters every hour")
    walls_c = Check("walls", "Each hall's thermal walls plus its CDUs equal its mechanical UPS output every hour")
    heat_c = Check("heat", "Chiller capacity equals the plant's heat; loop flow equals the CDUs', walls', and CRAHs' water")
    water_c = Check("water", "Supply header equals the metered water temperature; ambient equals the outdoor meter")
    stage_c = Check("staging", "Enough chillers run, and none while tripped or held off")
    trip_c = Check("trips", "Each compressor trip on record shows at its minute and clears at its clear time")
    ovr_c = Check("overrides", "BMS holds, condenser fan overrides, and free-cooling lockouts hold exactly over their spans")
    air_c = Check("air_events", "Each wall fan failure and alarm inhibit holds exactly over its span")
    quiet_c = Check("quiet", "No alarm, hold, or inhibit the records do not have; supply air never at its high limit")
    H = t.M // HOUR
    halls = [h for h in site["halls"] if h["state"] in ("production", "deployment")]
    # 1: meters
    sums: dict[tuple[str, str], float] = {}
    for rows, fam in ((t.chiller_hourly, "chillers"), (t.pump_hourly, "pumps")):
        for r in rows:
            sums[(fam, r["hour"])] = sums.get((fam, r["hour"]), 0.0) + float(r["kwh"])
    for r in t.air_hourly:
        if r["kind"] == "crah":
            sums[("crah", r["hour"])] = sums.get(("crah", r["hour"]), 0.0) + float(r["kwh"])
        else:
            sums[(r["hall"], r["hour"])] = sums.get((r["hall"], r["hour"]), 0.0) + float(r["kwh"])
    for k in range(H):
        hk = t.hour(k)
        met = t.meters.get(hk)
        if met is None:
            continue
        for fam, col in (("chillers", "chillers_kwh"), ("pumps", "pumps_kwh"), ("crah", "crah_kwh")):
            got = sums.get((fam, hk), 0.0)
            meters_c(abs(got - float(met[col])) <= ck["energy_kwh_tolerance"], f"{hk} {fam}: {got:.2f} kWh, meter {met[col]}")
    # 2: walls + CDUs = mechanical UPS output
    cdu: dict[tuple[str, str], dict[str, float]] = {}
    for r in t.cdu_hourly:
        x = cdu.setdefault((r["hall"], r["hour"]), {"power": 0.0, "heat": 0.0, "flow": 0.0})
        x["power"] += float(r["power_kwh"] or 0)
        x["heat"] += float(r["heat_kwh"] or 0)
        x["flow"] += float(r["pri_flow_lpm"] or 0)
    mups: dict[tuple[str, str], float] = {}
    for r in t.ups_hourly:
        if r["kind"] == "mech":
            mups[(r["hall"], r["hour"])] = mups.get((r["hall"], r["hour"]), 0.0) + float(r["out_kwh"])
    for h in halls:
        for k in range(H):
            hk = t.hour(k)
            if (h["id"], hk) not in mups:
                continue
            got = sums.get((h["id"], hk), 0.0) + cdu.get((h["id"], hk), {}).get("power", 0.0)
            walls_c(abs(got - mups[(h["id"], hk)]) <= ck["energy_kwh_tolerance"],
                    f"{h['id']} {hk}: walls + CDUs {got:.2f} kWh, mechanical UPS output {mups[(h['id'], hk)]:.2f}")
    # 3: heat and flow
    cap: dict[str, float] = {}
    for r in t.chiller_hourly:
        cap[r["hour"]] = cap.get(r["hour"], 0.0) + float(r["cap_kwh"])
    airflow: dict[str, float] = {}
    for r in t.air_hourly:
        airflow[r["hour"]] = airflow.get(r["hour"], 0.0) + float(r["flow_lps"])
    cp = cfg["water"]["cp_kj_per_kg_k"] * cfg["water"]["density_kg_per_l"]
    for r in t.loop_hourly:
        hk = r["hour"]
        met = t.meters.get(hk)
        if met is None:
            continue
        q = sum(float(met[f"ups_in_{h['letter'].lower()}_kwh"]) + float(met[f"mech_{h['letter'].lower()}_kwh"]) for h in halls) + float(met["crah_kwh"])
        heat_c(abs(cap.get(hk, 0.0) - q) <= ck["heat_kwh_tolerance"], f"{hk}: chiller capacity {cap.get(hk, 0.0):.1f} kWh, plant heat {q:.1f}")
        want = sum(cdu.get((h["id"], hk), {}).get("flow", 0.0) for h in halls) / 60 + airflow.get(hk, 0.0)
        heat_c(abs(float(r["flow_lps"]) - want) <= want * ck["flow_tolerance_pct"] / 100 + 0.05,
               f"{hk}: loop {r['flow_lps']} L/s, CDUs + walls + CRAHs {want:.2f}")
        dt = float(r["return_c"]) - float(r["supply_c"])
        heat_c(abs(float(r["flow_lps"]) * cp * dt - q) <= q * 0.01 + 1.0, f"{hk}: flow x header difference {float(r['flow_lps']) * cp * dt:.1f} kW, heat {q:.1f}")
    # 4: water and ambient
    for r in t.loop_hourly:
        met = t.meters.get(r["hour"])
        if met is not None:
            water_c(abs(float(r["supply_c"]) - float(met["fw_supply_c"])) <= ck["temp_tolerance_c"] / 6,
                    f"{r['hour']}: supply header {r['supply_c']}, meter {met['fw_supply_c']}")
    loop = {r["hour"]: float(r["supply_c"]) for r in t.loop_hourly}
    for r in t.chiller_hourly:
        met = t.meters.get(r["hour"])
        if met is None:
            continue
        water_c(abs(float(r["ambient_c"]) - float(met["outdoor_c"])) <= ck["temp_tolerance_c"],
                f"{r['chiller']} {r['hour']}: ambient {r['ambient_c']}, outdoor meter {met['outdoor_c']}")
        if r["outlet_c"] != "":
            water_c(abs(float(r["outlet_c"]) - loop[r["hour"]]) <= 0.25, f"{r['chiller']} {r['hour']}: leaving {r['outlet_c']}, header {loop[r['hour']]}")
    # 5 to 9 read the minutes
    spans = record_spans(t)
    stat = {v: k for k, v in cfg["chiller"]["unit_status"].items()}
    cst = {v: k for k, v in cfg["chiller"]["compressor_status"].items()}
    run_tot = np.zeros(t.M, dtype=np.int64)
    for c in t.devices("chiller"):
        f = t.minutes(c)
        sp = spans.get(c, {})
        running = (f["status"] == stat["Local On"]) | (f["status"] == stat["Power Failure"])
        run_tot += running
        trip, off, fan100, lock = (_mask(sp.get(k, []), t.M) for k in ("trip", "off", "fan100", "lock"))
        stage_c(not (running & (trip | off)).any(), f"{c}: runs while tripped or held off")
        for a, b, _ in sp.get("trip", []):
            trip_c(int(f["hp1_alarm"][a]) == 1 and (a == 0 or int(f["hp1_alarm"][a - 1]) == 0),
                   f"{c} {t.hour(0)}+{a} min: BV 35 not raised at the trip minute")
            trip_c(a == 0 or int(f["hp1_bar"][a - 1]) >= cfg["chiller"]["hp_alarm_bar"] * 10,
                   f"{c}: condensing pressure {f['hp1_bar'][a - 1] / 10} bar before the trip, limit {cfg['chiller']['hp_alarm_bar']}")
            trip_c(bool((f["cmp1"][a:b] == cst["ALARM"]).all()) and bool((f["status"][a:b] == stat["Alarm Off"]).all()),
                   f"{c}: compressor not in ALARM for the whole trip")
            trip_c(b >= t.M or int(f["hp1_alarm"][b]) == 0, f"{c}: BV 35 still active after the alarm cleared")
        ovr_c(bool(((f["enable"] == 0) == off).all()), f"{c}: chiller enable differs from the BMS holds on record")
        ovr_c(bool((f["cap_kw"][off] == 0).all()), f"{c}: carries load while held off")
        ovr_c(bool((f["fan1_pct"][fan100 & running] == 100).all()), f"{c}: condenser fans not at 100% under the override")
        ovr_c(bool(((f["fc_inhibit"] == 1) == lock).all()), f"{c}: free-cooling inhibit differs from the lockouts on record")
        ovr_c(not (f["fc"][lock] == 1).any(), f"{c}: free cooling active while inhibited")
        loaded = lock & (f["cap_kw"] > 0)
        ovr_c(bool((f["mech_kw"][loaded] == f["cap_kw"][loaded]).all()), f"{c}: locked out but not all on compressors")
        quiet_c(bool(((f["alarm"] == 1) == trip).all()), f"{c}: alarm minutes differ from the trips on record")
    need = np.repeat(np.array([int(r["chillers_needed"]) for r in t.loop_hourly]), HOUR)[: t.M]
    short = np.flatnonzero(run_tot < need)
    stage_c(len(short) == 0, f"{len(short)} minutes with fewer chillers running than needed")
    hi = cfg["air"]["high_supply_c"] * 100
    for u in t.devices("wall") + t.devices("crah"):
        f = t.minutes(u)
        sp = spans.get(u, {})
        fail = np.zeros(t.M, dtype=np.int64)
        for a, b, fan in sp.get("fan", []):
            fail[a:b] = fan
            air_c(bool((f["fan_failed"][a:b] == fan).all()) and bool((f["fans_ok"][a:b] == cfg["air"]["fans_per_wall"] - 1).all()),
                  f"{u}: fan {fan} not failed for the whole alarm")
            air_c(bool((f["fan_alarm"][a:b] == 1).all()), f"{u}: Al_EvpFan not active for the whole alarm")
        inh = _mask(sp.get("inhibit", []), t.M)
        for a, b, _ in sp.get("inhibit", []):
            air_c(bool((f["hi_inhibit"][a:b] == 1).all()), f"{u}: Event_Algorithm_Inhibit not TRUE for the whole inhibit")
        quiet_c(bool((f["fan_failed"] == fail).all()), f"{u}: failed fans differ from the records")
        quiet_c(bool(((f["hi_inhibit"] == 1) == inh).all()), f"{u}: inhibit minutes differ from the records")
        quiet_c(int(f["sup_c"].max()) < hi, f"{u}: supply air reached {f['sup_c'].max() / 100} C (limit {hi / 100})")
        quiet_c(not f["hi_alarm"].any(), f"{u}: a high supply temperature alarm the records do not have")
    return [meters_c, walls_c, heat_c, water_c, stage_c, trip_c, ovr_c, air_c, quiet_c]
