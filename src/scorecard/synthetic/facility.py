"""Synthetic facility (Landlord) data for Site AUS-1. Portfolio demo; all data fictional.

Writes two views of the same month, like the IT generator:

* What the devices recorded, read by the Customer under the Interface Agreement:
  UPS network management cards (PowerNet MIB ``upsBasicOutputStatus`` values),
  busway Critical Power Monitors, generator controllers (EMCP 4.4, one reading a
  minute while running), CDU controllers (DMTF Redfish ``ThermalEquipment/CDUs``
  resources and ``CoolantConnector`` readings), TraceTek leak controllers
  (alarm with distance along the cable), VESDA detectors (Alert, Action,
  Fire 1, Fire 2, faults), the EPMS (breaker and source events), the BMS
  (alarms, acknowledgments, overrides, inhibits), and badge entries.
* What the Landlord recorded: work orders, maintenance records, its roster,
  and its weekly self-report.

Planted discrepancies go to an answer key in ``ground_truth/`` that the engine
cannot read. Names confirmed against vendor or standards documentation are
used as-is; EMCP parameters use descriptive names (see docs/DATA_MODEL.md).

This generator has its own random stream, so it never changes the IT data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any

from scorecard import site_model as S

UTC = timezone.utc
GEN_KW = 3000
UPS_STATES = ("onLine", "onBattery", "switchedBypass", "hardwareFailureBypass", "eConversion")  # PowerNet MIB values


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def mins(n: float) -> timedelta:
    return timedelta(minutes=n)


def room_for(unit: str) -> str:
    """The badge reader that proves someone was at a piece of equipment (or the room a PM names)."""
    if unit.startswith("Hall "):
        return unit
    if unit.startswith("GEN-"):
        return "Generator yard"
    if unit.startswith(("CH-", "USS-CH")):
        return "Chiller yard"
    if unit.startswith("FWP-"):
        return "Pump room"
    letter = unit.split("-")[1][0] if "-" in unit else "A"
    if unit.startswith(("UPS-", "MUPS-", "CRAH-")) or (unit.startswith("VESDA-") and unit.endswith("2")):
        return f"Hall {letter} electrical room"
    return f"Hall {letter}"


@dataclass
class FacIncident:
    gt_id: str
    fault_class: str
    unit: str
    room: str
    t0: datetime
    priority: str
    description: str
    ack_at: datetime | None = None
    engaged_at: datetime | None = None          # true badge time; None if nobody came
    restored_at: datetime | None = None         # telemetry restoration
    engineer: str | None = None
    wo: str = ""
    wo_engaged_at: datetime | None = None       # what the work order claims
    wo_restored_at: datetime | None = None
    attribution_claim: str = "Landlord"
    notes: str = ""
    mop_ref: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class FacilityGenerator:
    def __init__(self, site: dict, landlord_sla: dict, config: dict, start: datetime, end: datetime,
                 seed: int, utc_offset: timedelta):
        self.site, self.sla, self.cfg = site, landlord_sla, config["facility"]
        self.start, self.end, self.utc_offset = start, end, utc_offset
        self.rng = random.Random(f"{seed}:facility")      # independent of the IT stream
        self.seed = seed
        self.prio = {p["id"]: p for p in landlord_sla["priorities"]}
        self.out: dict[str, list] = {k: [] for k in (
            "ups_events", "ups_status", "busway", "emcp", "cdu", "bms", "epms", "leak", "fire", "badges",
            "work_orders", "pm", "mops", "roster", "weekly", "gt_incidents", "planted")}
        self.rack_outages: list[dict] = []     # handed to the IT generator for the IT side of the event
        self.incidents: list[FacIncident] = []
        self._n = 0
        self._wo = 41000
        self._mop = 300
        self._pm_n = 0
        self._build_assets()
        self._build_staff()

    # ------------------------------------------------------------------ setup
    def _build_assets(self) -> None:
        live = [h for h in self.site["halls"] if h["state"] != "planned"]
        self.halls = live
        inv = S.equipment(self.site)
        live_letters = {h["letter"] for h in live}
        def keep(e: dict) -> bool:
            for prefix in ("UPS-", "MUPS-", "CDU-", "TW-", "CRAH-", "USS-"):
                if e["id"].startswith(prefix) and e["id"][len(prefix)] not in live_letters and not e["id"].startswith("USS-CH"):
                    return False
            return not e["id"].startswith("MVSST-") and not e["id"].startswith("BW-C")
        self.inv = {e["id"]: e for e in inv if keep(e)}
        self.ups = sorted(i for i in self.inv if i.startswith(("UPS-", "MUPS-")))
        self.cdus = sorted(i for i in self.inv if i.startswith("CDU-"))
        self.gens = sorted((i for i in self.inv if i.startswith("GEN-")), key=lambda x: int(x[4:]))
        self.chillers = sorted(i for i in self.inv if i.startswith("CH-"))
        self.walls = sorted(i for i in self.inv if i.startswith("TW-"))
        self.busways = sorted(i for i in self.inv if i.startswith("BW-"))
        self.vesda = [f"VESDA-{h['letter']}{n}" for h in live for n in range(1, h["fire_life_safety"]["vesda_detectors"] + 1)]

    def room(self, unit: str) -> str:
        return room_for(unit)

    def _local(self, dt: datetime) -> datetime:
        return dt + self.utc_offset

    def _build_staff(self) -> None:
        """Landlord critical facilities engineers on 12-hour shifts, 4 on / 4 off."""
        st = self.sla["staffing"]["committed_per_shift"]
        self.engineers = [f"CCF-E{n:02d}" for n in range(1, 13)]
        crews = {"D1": self.engineers[0:4], "D2": self.engineers[4:8], "N1": self.engineers[8:10], "N2": self.engineers[10:12]}
        day_n = st[0]["technicians"] + st[0]["shift_leads"]
        night_n = st[1]["technicians"] + st[1]["shift_leads"]
        self.shifts: list[tuple[datetime, datetime, list[str]]] = []
        d0 = self._local(self.start).date() - timedelta(days=1)
        for k in range((self.end - self.start).days + 2):
            day = d0 + timedelta(days=k)
            rot = ((day - self._local(self.start).date()).days // 4) % 2 + 1
            for shift, hour, n in (("day", 7, day_n), ("night", 19, night_n)):
                s = datetime.combine(day, time(hour), tzinfo=UTC) - self.utc_offset
                e = s + timedelta(hours=12)
                if e <= self.start or s >= self.end:
                    continue
                crew = crews[f"{'D' if shift == 'day' else 'N'}{rot}"][:n]
                self.shifts.append((s, e, crew))
                for eng in crew:
                    self.out["roster"].append({"shift_start": iso(s), "shift": shift, "engineer": eng})
                    self.out["badges"].append({"timestamp": iso(max(s, self.start) + mins(self.rng.uniform(-12, 3))),
                                               "person_id": eng, "reader": "Main lobby", "direction": "in"})

    def on_duty(self, t: datetime) -> list[str]:
        return next((crew for s, e, crew in self.shifts if s <= t < e), self.engineers[:2])

    def badge(self, who: str, room: str, t: datetime) -> None:
        self.out["badges"].append({"timestamp": iso(t), "person_id": who, "reader": room, "direction": "in"})

    def _gt(self) -> str:
        self._n += 1
        return f"FGT-{self._n:04d}"

    def _next_wo(self) -> str:
        self._wo += self.rng.randint(1, 9)
        return f"WO-{self._wo}"

    def _next_mop(self) -> str:
        self._mop += 1
        return f"MOP-{self._mop}"

    def _rand_t(self, lo_h: float = 2, hi_margin_h: float = 30, local_hours: tuple[int, int] | None = None) -> datetime:
        for _ in range(500):
            t = self.start + timedelta(hours=self.rng.uniform(lo_h, (self.end - self.start).total_seconds() / 3600 - hi_margin_h))
            if local_hours is None or local_hours[0] <= self._local(t).hour < local_hours[1]:
                return t.replace(second=self.rng.randint(0, 59), microsecond=0)
        raise RuntimeError("no time slot found")

    def _plant(self, kind: str, **kw) -> None:
        self.out["planted"].append({"type": kind, **kw})

    def mop(self, title: str, assets: list[str], start: datetime, end: datetime) -> str:
        m = self._next_mop()
        self.out["mops"].append({"mop_id": m, "title": title, "assets": assets, "window_start": iso(start),
                                 "window_end": iso(end), "approved_by": "Customer change board",
                                 "approved_at": iso(start - timedelta(days=self.rng.randint(12, 21)))})
        return m

    # ------------------------------------------------------------------ alarms and response
    def bms_alarm(self, unit: str, text: str, t: datetime, priority: str, cleared: datetime | None,
                  ack_at: datetime | None, ack_by: str | None) -> None:
        self.out["bms"].append({"timestamp": iso(t), "kind": "alarm", "device": unit, "alarm": text, "state": "active",
                                "priority": priority})
        if ack_at:
            self.out["bms"].append({"timestamp": iso(ack_at), "kind": "alarm", "device": unit, "alarm": text,
                                    "state": "acknowledged", "user": ack_by})
        if cleared:
            self.out["bms"].append({"timestamp": iso(cleared), "kind": "alarm", "device": unit, "alarm": text,
                                    "state": "cleared"})

    def respond(self, inc: FacIncident, repair_min: tuple[float, float], late: bool | None = None,
                dispatch: bool = True) -> None:
        """Acknowledge, badge in, repair, restore; honest work order by default."""
        p = self.prio[inc.priority]
        ack_t = p["acknowledge_min"]
        inc.ack_at = inc.t0 + mins(self.rng.uniform(0.6, ack_t * 0.8))
        crew = self.on_duty(inc.t0)
        inc.engineer = self.rng.choice(crew)
        on_site = p["engaged_on_site_min"] or 240
        if late is None:
            late = self.rng.random() < self.cfg["behavior"]["late_engagement_probability"]
        if dispatch:
            inc.engaged_at = inc.ack_at + mins(self.rng.uniform(on_site * 1.1, on_site * 1.8) if late
                                               else self.rng.uniform(2, max(3, on_site * 0.7)))
            self.badge(inc.engineer, inc.room, inc.engaged_at)
        restore_t = p["restore_min"]
        lo, hi = repair_min
        dur = self.rng.uniform(lo, hi)
        if self.rng.random() < self.cfg["behavior"]["late_restore_probability"]:
            dur = max(dur, restore_t * self.rng.uniform(1.1, 1.6))
        else:
            dur = min(dur, restore_t * 0.9)
        inc.restored_at = inc.t0 + mins(dur)
        if dispatch and inc.engaged_at and inc.restored_at < inc.engaged_at + mins(15):
            inc.restored_at = inc.engaged_at + mins(self.rng.uniform(15, 45))   # hands-on repair starts when someone arrives
        inc.wo = self._next_wo()
        inc.wo_engaged_at = inc.engaged_at
        inc.wo_restored_at = inc.restored_at
        self.incidents.append(inc)

    # ------------------------------------------------------------------ fault classes
    def fault_cdu(self, t0: datetime, cdu: str | None = None) -> FacIncident:
        cdu = cdu or self.rng.choice(self.cdus)
        pump = self.rng.choice([1, 2])
        inc = FacIncident(self._gt(), "OT-FC-CDU", cdu, self.room(cdu), t0, "P2",
                          f"{cdu} pump {pump} failed; pump redundancy lost", extra={"pump": pump})
        self.respond(inc, (180, 420))
        base = f"/redfish/v1/ThermalEquipment/CDUs/{cdu}"
        self.out["cdu"] += [
            {"timestamp": iso(t0), "cdu": cdu, "resource": f"{base}/Pumps/{pump}", "property": "Status.Health", "value": "Critical"},
            {"timestamp": iso(t0), "cdu": cdu, "resource": base, "property": "PumpRedundancy.Status.Health", "value": "Warning"},
            {"timestamp": iso(inc.restored_at - mins(12)), "cdu": cdu, "resource": f"{base}/Pumps/{pump}", "property": "Status.State", "value": "InTest"},
            {"timestamp": iso(inc.restored_at), "cdu": cdu, "resource": f"{base}/Pumps/{pump}", "property": "Status.Health", "value": "OK"},
            {"timestamp": iso(inc.restored_at), "cdu": cdu, "resource": base, "property": "PumpRedundancy.Status.Health", "value": "OK"},
        ]
        self.bms_alarm(cdu, f"Pump {pump} fault", t0, "P2", inc.restored_at, inc.ack_at, inc.engineer)
        inc.extra["parts"] = f"Pump assembly SN CHX-P{self.rng.randint(10000, 99999)} installed"
        return inc

    def fault_ups(self, t0: datetime) -> FacIncident:
        ups = self.rng.choice([u for u in self.ups if u.startswith("UPS-")])
        mod = self.rng.randint(1, 6)
        inc = FacIncident(self._gt(), "OT-FC-UPS", ups, self.room(ups), t0, "P2",
                          f"{ups} power module {mod} failed; module redundancy reduced", extra={"module": mod})
        self.respond(inc, (240, 600))
        self.out["ups_events"] += [
            {"timestamp": iso(t0), "ups": ups, "event": f"Power module {mod} fault", "severity": "warning"},
            {"timestamp": iso(inc.restored_at - mins(30)), "ups": ups, "event": f"Power module {mod} replaced", "severity": "informational"},
            {"timestamp": iso(inc.restored_at), "ups": ups, "event": "Power module redundancy restored", "severity": "informational"},
        ]
        self.bms_alarm(ups, f"Module {mod} fault", t0, "P2", inc.restored_at, inc.ack_at, inc.engineer)
        inc.extra["parts"] = f"Power module SN GVX-M{self.rng.randint(10000, 99999)} installed by OEM field service"
        return inc

    def fault_chiller(self, t0: datetime, dispatch: bool = True) -> FacIncident:
        ch = self.rng.choice(self.chillers)
        inc = FacIncident(self._gt(), "OT-FC-CHW", ch, self.room(ch), t0, "P2", f"{ch} compressor trip on high condenser pressure")
        self.respond(inc, (60, 300), dispatch=dispatch)
        self.bms_alarm(ch, "Compressor trip (high condenser pressure)", t0, "P2", inc.restored_at, inc.ack_at, inc.engineer)
        return inc

    def fault_wall(self, t0: datetime) -> FacIncident:
        tw = self.rng.choice(self.walls)
        fan = self.rng.randint(1, 6)
        inc = FacIncident(self._gt(), "OT-FC-AIR", tw, self.room(tw), t0, "P3", f"{tw} fan {fan} failure")
        self.respond(inc, (120, 900))
        self.bms_alarm(tw, f"Fan {fan} failure", t0, "P3", inc.restored_at, inc.ack_at, inc.engineer)
        return inc

    def fault_busway(self, t0: datetime) -> FacIncident:
        bw = self.rng.choice([b for b in self.busways if b.startswith(("BW-A", "BW-B"))])
        inc = FacIncident(self._gt(), "OT-FC-PWR", bw, self.room(bw), t0, "P2",
                          f"{bw} feed lost: upstream feeder breaker tripped; racks on the segment running on their other feed")
        self.respond(inc, (60, 200))
        feeder = self.inv[bw]["fed_from"]
        self.out["busway"] += [
            {"timestamp": iso(t0), "busway": bw, "point": "Voltage L-L avg", "value_v": 0.0, "state": "out_of_tolerance"},
            {"timestamp": iso(inc.restored_at), "busway": bw, "point": "Voltage L-L avg", "value_v": round(self.rng.uniform(476, 484), 1), "state": "in_tolerance"},
        ]
        self.out["epms"] += [
            {"timestamp": iso(t0 - timedelta(seconds=1)), "device": f"{feeder} output feeder to {bw}", "event": "Breaker trip (short-time overcurrent)"},
            {"timestamp": iso(inc.restored_at - timedelta(seconds=20)), "device": f"{feeder} output feeder to {bw}", "event": "Breaker closed"},
        ]
        self.bms_alarm(bw, "Busway undervoltage", t0, "P2", inc.restored_at, inc.ack_at, inc.engineer)
        return inc

    def fault_leak(self, t0: datetime) -> FacIncident:
        hall = self.rng.choice(self.halls)
        L = hall["letter"]
        n_cdu = hall["cooling"]["cdu_count"]
        cdu_n = self.rng.randint(1, n_cdu)
        circuit = hall["rows"] + cdu_n
        dist = round(self.rng.uniform(2.0, 18.0), 1)
        inc = FacIncident(self._gt(), "OT-FC-LEAK", f"TTDM-{L}/C{circuit}", f"Hall {L}", t0, "P1",
                          f"Leak under CDU-{L}{cdu_n}: fitting weep on the secondary header connection",
                          extra={"distance_m": dist, "cdu": f"CDU-{L}{cdu_n}"})
        self.respond(inc, (90, 200))
        self.out["leak"] += [
            {"timestamp": iso(t0), "controller": f"TTDM-{L}", "circuit": circuit, "label": f"Under CDU-{L}{cdu_n}",
             "event": "LEAK", "distance_m": dist},
            {"timestamp": iso(inc.restored_at), "controller": f"TTDM-{L}", "circuit": circuit, "label": f"Under CDU-{L}{cdu_n}",
             "event": "NORMAL", "distance_m": None},
        ]
        self.bms_alarm(f"TTDM-{L}", f"Leak circuit {circuit} at {dist} m", t0, "P1", inc.restored_at, inc.ack_at, inc.engineer)
        return inc

    def fault_fire(self, t0: datetime) -> FacIncident:
        det = self.rng.choice(self.vesda)
        inc = FacIncident(self._gt(), "OT-FC-FIRE", det, self.room(det), t0, "P2",
                          f"{det} airflow fault (low flow on pipe 2); coverage maintained by adjacent detection")
        self.respond(inc, (60, 240))
        self.out["fire"] += [
            {"timestamp": iso(t0), "detector": det, "event": "Fault", "detail": "Airflow Low", "level": None},
            {"timestamp": iso(inc.restored_at), "detector": det, "event": "Normal", "detail": "Fault cleared", "level": None},
        ]
        self.bms_alarm(det, "Detector fault: airflow low", t0, "P2", inc.restored_at, inc.ack_at, inc.engineer)
        return inc

    # ------------------------------------------------------------------ utility outage
    def utility_outage(self) -> None:
        self.outage_windows: list[tuple[datetime, datetime]] = []
        for _ in range(self.cfg["utility_outages"]):
            t0 = self._rand_t(48, 72, local_hours=(13, 18))
            dur = self.rng.uniform(35, 60)
            load_mw = self.rng.uniform(*self.cfg["site_load_mw"])
            back = t0 + mins(dur)
            self.outage_windows.append((t0, back + mins(5)))
            self.out["epms"] += [
                {"timestamp": iso(t0), "device": "MV-A main breaker", "event": "Trip (utility undervoltage)"},
                {"timestamp": iso(t0), "device": "MV-B main breaker", "event": "Trip (utility undervoltage)"},
                {"timestamp": iso(t0 + timedelta(seconds=10)), "device": "Generator paralleling bus", "event": "Bus live (7 of 7 generators)"},
                {"timestamp": iso(t0 + timedelta(seconds=12)), "device": "Generator tie breakers", "event": "Closed to MV-A and MV-B"},
                {"timestamp": iso(back), "device": "MV-A main breaker", "event": "Closed (utility restored, closed-transition retransfer)"},
                {"timestamp": iso(back), "device": "MV-B main breaker", "event": "Closed (utility restored, closed-transition retransfer)"},
                {"timestamp": iso(back + timedelta(seconds=5)), "device": "Generator tie breakers", "event": "Open"},
            ]
            for u in self.ups:
                self.out["ups_events"] += [
                    {"timestamp": iso(t0), "ups": u, "event": "upsBasicOutputStatus onBattery", "severity": "warning"},
                    {"timestamp": iso(t0 + timedelta(seconds=self.rng.randint(11, 14))), "ups": u,
                     "event": "upsBasicOutputStatus onLine", "severity": "informational"},
                ]
            # The load the generators carry is the site's own load at that minute: the power telemetry builds it
            # from the racks (data/telemetry/power). The draws stay so every other record keeps its values.
            per_gen = load_mw * 1000 / len(self.gens)
            for g in self.gens:
                self._emcp_run(g, t0 + timedelta(seconds=2), back + mins(5), per_gen, cooldown_min=5, keep=False)
            inc = FacIncident(self._gt(), "UTILITY", "138 kV utility service", "MV switchgear", t0, "P1",
                              f"Utility outage {dur:.0f} min; generators carried the site; no IT impact",
                              attribution_claim="Utility")
            self.respond(inc, (dur, dur + 1), late=False)
            inc.restored_at = inc.wo_restored_at = back
            self.bms_alarm("MV switchgear", "Utility power lost", t0, "P1", back, inc.ack_at, inc.engineer)

    def _emcp_run(self, gen: str, start: datetime, end: datetime, kw: float, cooldown_min: float = 5,
                  keep: bool = True) -> None:
        rows: list[dict] = []
        self._emcp_rows(rows, gen, start, end, kw, cooldown_min)
        if keep:
            self.out["emcp"] += rows

    def _emcp_rows(self, out: list[dict], gen: str, start: datetime, end: datetime, kw: float, cooldown_min: float) -> None:
        out.append({"timestamp": iso(start), "generator": gen, "engine_operating_state": "Starting",
                    "gen_total_kw": 0.0, "gen_pct_rated_kw": 0.0})
        t = start + timedelta(minutes=1)
        loaded_until = end - mins(cooldown_min)
        while t < end:
            load = kw * self.rng.uniform(0.96, 1.04) if t < loaded_until else 0.0
            state = "Running" if t < loaded_until else "Cooldown"
            out.append({"timestamp": iso(t), "generator": gen, "engine_operating_state": state,
                        "gen_total_kw": round(load, 1), "gen_pct_rated_kw": round(load / GEN_KW * 100, 1)})
            t += timedelta(minutes=1)
        out.append({"timestamp": iso(end), "generator": gen, "engine_operating_state": "Stopped",
                    "gen_total_kw": 0.0, "gen_pct_rated_kw": 0.0})

    # ------------------------------------------------------------------ maintenance
    def _pm(self, system: str, asset: str, task: str, due: datetime, done: datetime, engineer: str,
            evidence: str, result: str = "Pass", mop: str = "") -> dict:
        self._pm_n += 1
        row = {"task_id": f"PM-{self._pm_n:04d}", "system": system, "asset": asset, "task": task,
               "due_start": iso(due), "due_end": iso(due + timedelta(days=7)), "completed_at": iso(done),
               "engineer": engineer, "result": result, "evidence": evidence, "mop_ref": mop}
        self.out["pm"].append(row)
        return row

    def maintenance(self) -> None:
        planted = self.cfg["planted"]
        days = (self.end - self.start).days
        no_load = set(self.rng.sample(self.gens, planted.get("gen_test_no_load", 0)))
        for i, g in enumerate(self.gens):
            day = self.start + timedelta(days=int(i * (days - 2) / len(self.gens)) + 1)
            t = day.replace(hour=0) + timedelta(hours=9 + self.rng.uniform(0, 5)) - self.utc_offset
            dur = self.rng.uniform(32, 40)          # loaded minutes; NFPA 110 excludes the cooldown
            # a test is never started while the sets are carrying a utility outage: it moves to the next day
            if any(a - mins(dur + 30) < t < b + mins(30) for a, b in getattr(self, "outage_windows", ())):
                t += timedelta(days=1)
            eng = self.rng.choice(self.on_duty(t))
            self.badge(eng, "Generator yard", t - mins(self.rng.uniform(4, 12)))
            if g in no_load:
                kw = GEN_KW * self.rng.uniform(0.03, 0.08)
                self._plant("gen_test_no_load", generator=g, test_start=iso(t), claimed="Pass at 40% load",
                            evidence="EMCP shows the engine ran unloaded")
            else:
                kw = GEN_KW * self.rng.uniform(0.35, 0.55)
            self._emcp_run(g, t, t + mins(dur + 5), kw, cooldown_min=5)
            self._pm("Generators", g, "Monthly loaded exercise", day, t + mins(dur + 5), eng,
                     "EMCP run record; portable load bank", "Pass at 40% load" if g in no_load else
                     f"Pass at {kw / GEN_KW * 100:.0f}% load")

        # Device-evidenced maintenance: (system, task, assets, minutes, room evidence, device evidence fn)
        hall_cdus = self.rng.sample(self.cdus, 4)
        jobs = [("CDUs", "Filter change and coolant sample", a, 30) for a in hall_cdus]
        jobs += [("UPS and batteries", "Preventive maintenance and battery health check", a, 150)
                 for a in self.rng.sample([u for u in self.ups if u.startswith("UPS-")], 2)]
        jobs += [("Chillers", "Preventive maintenance", a, 180) for a in self.rng.sample(self.chillers, 3)]
        jobs += [("Fire protection", "VESDA inspection and smoke test", self.rng.choice(self.vesda), 45)]
        jobs += [("Switchgear and busway", "Infrared thermography under load", f"Hall {h['letter']} electrical room", 120)
                 for h in self.halls[:1]]
        skip = self.rng.randrange(len(jobs)) if planted.get("pm_without_evidence") else None
        deferred = None
        while skip is not None and jobs[skip][0] in ("CDUs", "UPS and batteries", "Fire protection"):
            skip = self.rng.randrange(len(jobs))                       # plant on equipment without a MOP
        for k, (system, task, asset, minutes) in enumerate(jobs):
            t = self._rand_t(12, 40, local_hours=(8, 15))
            eng = self.rng.choice(self.on_duty(t))
            room = self.room(asset)
            critical = system in ("CDUs", "UPS and batteries", "Fire protection")
            mop = self.mop(f"{task}: {asset}", [asset], t - mins(30), t + mins(minutes + 60)) if critical else ""
            end = t + mins(minutes)
            if k == skip:
                deferred = (system, asset, task, minutes, mop)
                continue
            self.badge(eng, room, t - mins(self.rng.uniform(3, 10)))
            if system == "CDUs":
                base = f"/redfish/v1/ThermalEquipment/CDUs/{asset}"
                self.out["cdu"] += [
                    {"timestamp": iso(t), "cdu": asset, "resource": f"{base}/Pumps/2", "property": "Status.State", "value": "Disabled"},
                    {"timestamp": iso(end), "cdu": asset, "resource": f"{base}/Pumps/2", "property": "Status.State", "value": "Enabled"},
                ]
                ev = f"Pump 2 isolated in Redfish; coolant pH {self.rng.uniform(8.6, 9.4):.1f}, conductivity {self.rng.randint(180, 420)} uS/cm"
            elif system == "UPS and batteries":
                self.out["ups_events"] += [
                    {"timestamp": iso(t), "ups": asset, "event": "upsBasicOutputStatus switchedBypass", "severity": "warning"},
                    {"timestamp": iso(end), "ups": asset, "event": "upsBasicOutputStatus onLine", "severity": "informational"},
                ]
                ev = "NMC shows maintenance bypass for the work window"
            elif system == "Chillers":
                ref = f"PM-{self._pm_n + 1:04d}"
                self.out["bms"] += [
                    {"timestamp": iso(t), "kind": "override", "device": asset, "point": "Chiller enable", "value": "Off",
                     "user": eng, "change_ref": ref, "action": "set"},
                    {"timestamp": iso(end), "kind": "override", "device": asset, "point": "Chiller enable", "value": "Auto",
                     "user": eng, "change_ref": ref, "action": "release"},
                ]
                ev = "BMS shows the chiller locked out for the work window"
            elif system == "Fire protection":
                self.out["fire"] += [
                    {"timestamp": iso(t), "detector": asset, "event": "Isolate", "detail": "Inspection", "level": None},
                    {"timestamp": iso(t + mins(15)), "detector": asset, "event": "Alarm", "detail": "Smoke test", "level": "Fire 1"},
                    {"timestamp": iso(end), "detector": asset, "event": "Normal", "detail": "De-isolated", "level": None},
                ]
                ev = "VESDA isolate, test alarm, and de-isolate recorded"
            else:
                ev = "Thermography report; badge entry"
            self._pm(system, asset, task, t - timedelta(days=2), end, eng, ev, mop=mop)
        self._deferred_pm = deferred

    # ------------------------------------------------------------------ planned critical work and overrides
    def planned_work(self) -> None:
        planted = self.cfg["planted"]
        deploy = [h for h in self.halls if h["state"] == "deployment"] or self.halls
        segs = [b for b in self.busways if b.startswith(f"BW-{deploy[0]['letter']}")]
        picks = self.rng.sample(segs, 3)
        bad = set(picks[: planted.get("critical_work_no_mop", 0)])
        for bw in picks:
            t = self._rand_t(12, 40, local_hours=(9, 15))
            eng = self.rng.choice(self.on_duty(t))
            self.badge(eng, self.room(bw), t - mins(6))
            tap = f"TO-{bw[3]}{self.rng.randint(1, 32):02d}"
            mop = "" if bw in bad else self.mop(f"Energize tap-off {tap} for a new rack (HO-4)", [bw], t - mins(30), t + mins(90))
            self.out["busway"] += [
                {"timestamp": iso(t), "busway": bw, "tapoff": tap, "point": "Tap-off breaker", "event": "Breaker open"},
                {"timestamp": iso(t + mins(self.rng.uniform(20, 45))), "busway": bw, "tapoff": tap, "point": "Tap-off breaker", "event": "Breaker closed"},
            ]
            wo = self._next_wo()
            self.out["work_orders"].append({"wo": wo, "opened": iso(t - mins(45)), "priority": "P4", "fault_class": None,
                                            "unit": bw, "room": self.room(bw), "acknowledged_at": None, "engaged_at": iso(t),
                                            "restored_at": None, "closed": iso(t + mins(60)), "engineer": eng,
                                            "mop_ref": mop, "attribution": "Landlord", "parts": "",
                                            "notes": f"Tap-off {tap} retorque and energization"})
            if bw in bad:
                self._plant("critical_work_no_mop", busway=bw, tapoff=tap, at=iso(t), wo=wo,
                            evidence="Breaker operated with no approved MOP")

        # Honest inhibit during the VESDA inspection is already change-referenced; plant an unrecorded override.
        for _ in range(planted.get("bms_override_unrecorded", 0)):
            t = self._rand_t(24, 90)
            dev = self.rng.choice(self.walls + self.chillers)
            hold = self.rng.uniform(30, 60)
            who = self.rng.choice(self.on_duty(t))
            kind, point, val = (("inhibit", "High supply air temperature alarm", "Inhibited") if dev.startswith("TW")
                                else ("override", "Condenser fan speed", "100%"))
            self.out["bms"] += [
                {"timestamp": iso(t), "kind": kind, "device": dev, "point": point, "value": val, "user": who,
                 "change_ref": "", "action": "set"},
                {"timestamp": iso(t + timedelta(hours=hold)), "kind": kind, "device": dev, "point": point, "value": "Auto",
                 "user": who, "change_ref": "", "action": "release"},
            ]
            self._plant("bms_override_unrecorded", device=dev, point=point, set_at=iso(t), hours=round(hold, 1))

    # ------------------------------------------------------------------ rack outage caused by Landlord work
    def rack_power_outage(self) -> None:
        """Planned A-side tap-off work under a MOP; the B-side tap-off for the same rack is opened by mistake.

        The rack loses both feeds (FA-1: Landlord). The B tap-off unit fails on reclose and is replaced, so the
        rack is dark for 3 to 4 hours. The IT Partner validates the rack after the handoff (HO-1, FA-3).
        """
        prod = next(h for h in self.halls if h["state"] == "production")
        for _ in range(self.cfg.get("rack_power_outages", 0)):
            rack = f"{prod['letter']}{self.rng.randint(1, S.rack_count(prod)):02d}"
            seg = next(s for s in S.busway_segments(self.site, prod["id"]) if rack in s["racks"])
            bw_a, bw_b = f"{seg['id']}-A", f"{seg['id']}-B"
            t_a = self._rand_t(30, 50, local_hours=(9, 13))
            eng = self.rng.choice(self.on_duty(t_a))
            self.badge(eng, self.room(bw_a), t_a - mins(8))
            mop = self.mop(f"Retorque A-side tap-off for rack {rack}", [bw_a], t_a - mins(30), t_a + mins(120))
            t0 = t_a + mins(self.rng.uniform(10, 30))
            handoff = t0 + mins(self.rng.uniform(190, 250))
            a_close = handoff + mins(self.rng.uniform(15, 30))
            tap = f"TO-{rack}"
            self.out["busway"] += [
                {"timestamp": iso(t_a), "busway": bw_a, "tapoff": f"{tap}-A", "rack": rack, "point": "Tap-off breaker", "event": "Breaker open"},
                {"timestamp": iso(t0), "busway": bw_b, "tapoff": f"{tap}-B", "rack": rack, "point": "Tap-off breaker", "event": "Breaker open"},
                {"timestamp": iso(handoff), "busway": bw_b, "tapoff": f"{tap}-B", "rack": rack, "point": "Tap-off breaker", "event": "Breaker closed"},
                {"timestamp": iso(a_close), "busway": bw_a, "tapoff": f"{tap}-A", "rack": rack, "point": "Tap-off breaker", "event": "Breaker closed"},
            ]
            inc = FacIncident(self._gt(), "OT-FC-PWR", f"Rack {rack}", self.room(bw_a), t0, "P1",
                              f"Rack {rack} lost both feeds: B-side tap-off opened in error during A-side work; B tap-off unit replaced")
            inc.ack_at = t0 + mins(self.rng.uniform(1, 3))
            inc.engineer, inc.engaged_at = eng, t0 + mins(self.rng.uniform(1, 4))
            self.badge(eng, inc.room, inc.engaged_at)
            inc.restored_at = inc.wo_restored_at = handoff
            inc.wo_engaged_at, inc.wo = inc.engaged_at, self._next_wo()
            inc.notes = f"Wrong tap-off ({tap}-B) opened during {mop}; B tap-off unit failed on reclose and was replaced"
            self.incidents.append(inc)
            self.bms_alarm(f"Rack {rack}", "Rack input power lost (both feeds)", t0, "P1", handoff, inc.ack_at, eng)
            self._plant("critical_work_no_mop", busway=bw_b, at=iso(t0), wo=inc.wo, scenario="rack_power_outage",
                        evidence="B-side tap-off opened with no MOP; the MOP covered only the A side")
            self.rack_outages.append({"rack": rack, "t0": t0, "handoff": handoff, "wo": inc.wo, "gt_id": inc.gt_id})

    # ------------------------------------------------------------------ faults, with planted record problems
    def faults(self) -> None:
        planted = self.cfg["planted"]
        makers = {"OT-FC-CDU": self.fault_cdu, "OT-FC-UPS": self.fault_ups, "OT-FC-CHW": self.fault_chiller,
                  "OT-FC-AIR": self.fault_wall, "OT-FC-PWR": self.fault_busway, "OT-FC-LEAK": self.fault_leak,
                  "OT-FC-FIRE": self.fault_fire}
        made: dict[str, list[FacIncident]] = {k: [] for k in makers}
        for cls, n in self.cfg["fault_counts"].items():
            for _ in range(n):
                made[cls].append(makers[cls](self._rand_t()))
        if planted.get("landlord_clock_shift") and made["OT-FC-CDU"]:
            inc = made["OT-FC-CDU"][0]
            inc.wo_restored_at = inc.restored_at - mins(self.rng.uniform(90, 200))
            self._plant("landlord_clock_shift", gt_id=inc.gt_id, unit=inc.unit,
                        telemetry_restored=iso(inc.restored_at), wo_restored=iso(inc.wo_restored_at))
        if planted.get("attribution_contradicted") and made["OT-FC-PWR"]:
            inc = made["OT-FC-PWR"][0]
            rack = self.rng.choice(next(s for s in S.busway_segments(self.site, f"HALL-{inc.unit[3]}")
                                        if inc.unit.startswith(s["id"]))["racks"])
            inc.attribution_claim = "IT Partner"
            inc.notes = f"Tenant whip fault on rack {rack}; Landlord equipment healthy"
            self._plant("attribution_contradicted", gt_id=inc.gt_id, unit=inc.unit, rack=rack,
                        evidence="Busway CPM shows the feed lost at the busway, upstream of the tap-off")

    # ------------------------------------------------------------------ records that claim attendance nobody made
    def _quiet(self, room: str, start: datetime, end: datetime, person: str | None = None) -> bool:
        for b in self.out["badges"]:
            t = datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00"))
            if b["reader"] == room and start <= t <= end and (person is None or b["person_id"] == person):
                return False
        return True

    def plant_quiet_records(self) -> None:
        """Placed last, after every badge exists, so the planted absence is unambiguous."""
        deferred = getattr(self, "_deferred_pm", None)
        if deferred:
            system, asset, task, minutes, mop = deferred
            room = self.room(asset)
            for _ in range(500):
                end = self._rand_t(12, 40, local_hours=(9, 16))
                quiet = [e for e in self.on_duty(end) if self._quiet(room, end - timedelta(hours=8), end, e)]
                if quiet:
                    break
            self._pm(system, asset, task, end - timedelta(days=2), end, self.rng.choice(quiet), "Engineer sign-off", mop=mop)
            self._plant("pm_without_evidence", task=f"PM-{self._pm_n:04d}", asset=asset, claimed_complete=iso(end),
                        evidence="No badge entry and no device signal")
        for _ in range(self.cfg["planted"].get("alarm_acked_no_dispatch", 0)):
            for _ in range(500):
                t0 = self._rand_t()
                # the room must be empty from the alarm until well after any plausible clear
                if self._quiet("Chiller yard", t0 - timedelta(minutes=30), t0 + timedelta(hours=8)):
                    break
            inc = self.fault_chiller(t0, dispatch=False)
            inc.wo_engaged_at = inc.ack_at + mins(self.rng.uniform(8, 20))
            inc.notes = "Engineer attended and reset the unit"
            self._plant("alarm_acked_no_dispatch", wo_unit=inc.unit, t0=iso(inc.t0), gt_id=inc.gt_id,
                        evidence="Acknowledged in the BMS; no badge entry before the alarm cleared")

    # ------------------------------------------------------------------ outputs
    def finalize(self) -> None:
        for inc in sorted(self.incidents, key=lambda i: i.t0):
            self.out["work_orders"].append({
                "wo": inc.wo, "opened": iso(inc.t0 + mins(self.rng.uniform(0.2, 1.5))), "priority": inc.priority,
                "fault_class": inc.fault_class if inc.fault_class != "UTILITY" else None, "unit": inc.unit,
                "room": inc.room, "acknowledged_at": iso(inc.ack_at) if inc.ack_at else None,
                "engaged_at": iso(inc.wo_engaged_at) if inc.wo_engaged_at else None,
                "restored_at": iso(inc.wo_restored_at), "closed": iso(inc.wo_restored_at + mins(self.rng.uniform(20, 90))),
                "engineer": inc.engineer, "mop_ref": inc.mop_ref, "attribution": inc.attribution_claim,
                "parts": inc.extra.get("parts", ""), "notes": inc.notes or inc.description})
            self.out["gt_incidents"].append({
                "gt_id": inc.gt_id, "wo": inc.wo, "fault_class": inc.fault_class, "unit": inc.unit, "t0": iso(inc.t0),
                "priority": inc.priority, "acknowledged_at": iso(inc.ack_at) if inc.ack_at else None,
                "engaged_at": iso(inc.engaged_at) if inc.engaged_at else None, "restored_at": iso(inc.restored_at),
                "true_attribution": "Utility" if inc.fault_class == "UTILITY" else "Landlord",
                "rack_capacity_lost": inc.unit.startswith("Rack "),
                "description": inc.description})
        for p in self.out["planted"]:
            if "gt_id" in p:
                p["wo"] = next(i.wo for i in self.incidents if i.gt_id == p["gt_id"])
        for n, p in enumerate(self.out["planted"], 1):
            p["anomaly_id"] = f"FPD-{n:03d}"
        # Hourly-ish UPS status poll (every 4 hours), so normal operation is visible, not only exceptions.
        t = self.start
        while t < self.end:
            # IT UPS load follows the racks, so it lives in the power telemetry (data/telemetry/power), not here;
            # the draw stays so every other record keeps its values. Mechanical UPS load stays in the poll.
            for u in self.ups:
                load = round(self.rng.uniform(55, 72) if u.startswith("UPS-") else self.rng.uniform(30, 45), 1)
                row = {"timestamp": iso(t), "ups": u, "upsBasicOutputStatus": "onLine"}
                if u.startswith("MUPS-"):
                    row["load_pct"] = load
                self.out["ups_status"].append(row)
            t += timedelta(hours=4)
        # Weekly self-report: the Landlord says every service level was met.
        for w in range((self.end - self.start).days // 7):
            ws = self.start + timedelta(weeks=w)
            self.out["weekly"].append({"week_start": iso(ws), "reported_by": "Caprock Critical Facilities, LLC",
                                       "results": {c["id"]: c["expected"] for c in self.sla["critical_service_levels"]},
                                       "note": "All SLAs met. Utility event handled with no customer impact." if any(
                                           i.fault_class == "UTILITY" and ws <= i.t0 < ws + timedelta(weeks=1) for i in self.incidents)
                                       else "All SLAs met."})
        for k in ("ups_events", "busway", "emcp", "cdu", "bms", "epms", "leak", "fire", "badges", "work_orders", "pm", "mops"):
            key = "opened" if k == "work_orders" else "completed_at" if k == "pm" else "window_start" if k == "mops" else "timestamp"
            self.out[k].sort(key=lambda r: (r[key], str(r)))

    def run(self) -> dict[str, list]:
        self.utility_outage()
        self.maintenance()
        self.planned_work()
        self.rack_power_outage()
        self.faults()
        self.plant_quiet_records()
        self.finalize()
        self.out["rack_outages"] = self.rack_outages
        return self.out


FACILITY_FILES = {
    "facility/ups_nmc_events.jsonl": "ups_events",
    "facility/ups_status.jsonl": "ups_status",
    "facility/busway_cpm_events.jsonl": "busway",
    "facility/emcp_readings.jsonl": "emcp",
    "facility/cdu_redfish_events.jsonl": "cdu",
    "facility/bms_events.jsonl": "bms",
    "facility/epms_events.jsonl": "epms",
    "facility/leak_events.jsonl": "leak",
    "facility/vesda_events.jsonl": "fire",
    "access/landlord_badge_events.csv": "badges",
    "customer/landlord_mop_approvals.json": "mops",
    "landlord/work_orders.json": "work_orders",
    "landlord/pm_records.csv": "pm",
    "landlord/roster.csv": "roster",
    "landlord/self_reported_weekly.json": "weekly",
    "ground_truth/facility_incidents.json": "gt_incidents",
    "ground_truth/facility_planted_discrepancies.json": "planted",
}
