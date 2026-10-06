"""Failure history for the half-year before the sample month (feeds the failure pattern review).

Writes the Telemetry of Record and the IT Partner's tickets for one production
hall over a number of weeks, on the committed fleet (``site/topology.json``),
with a few multi-month failure patterns planted and recorded in
``ground_truth/planted_patterns.json``. The pattern analysis never reads it.

Its random stream is its own (seeded from a string, not the sample's integer
seed) and it never touches the sample generator, so the sample month and every
report built from it are unchanged. Tray serials chain into the sample: the
last tray installed in each slot during the history is the serial the sample
month starts with.
"""

from __future__ import annotations

import heapq
import json
import math
import random
import string
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from .generator import XID_MESSAGES, _write_csv, _write_json, _write_jsonl, iso

UTC = timezone.utc
DAY = timedelta(days=1)
LINK_RAILS = 4
STABILITY_DAYS = 30
COMMISSIONED = "2026-02-16"   # Hall A optics installed at commissioning
THERMAL_REASON = "HW Thermal Slowdown"


def link_for(rack: dict, slot: int, rail: int) -> dict:
    """Same rail-optimized cabling as the sample generator."""
    letter = rack["rack"][0].lower()
    return {"host": f"{rack['rack'].lower()}-ct{slot:02d}", "hca": f"mlx5_{rail}",
            "switch": f"leaf-{letter}{(rack['index'] - 1) // 2 + 1:02d}-r{rail}",
            "port": ((rack["index"] - 1) % 2) * 18 + slot}


class HistoryGenerator:
    def __init__(self, topology: dict, config: dict, seed: int | None = None, vary: bool = False):
        self.cfg = config
        self.seed = config["seed"] if seed is None else seed
        self.rng = random.Random(f"failure-history-{self.seed}")
        self.start = datetime.combine(date.fromisoformat(config["start"]), time(0), tzinfo=UTC)
        if self.start.weekday() != 0:
            raise ValueError("start must be a Monday")
        self.weeks = config["weeks"]
        self.end = self.start + timedelta(weeks=self.weeks)
        self.racks = [r for r in topology["racks"] if r["hall"] == config["hall"]]
        self.cdus = sorted({r["cdu"] for r in self.racks})
        self.planted = json.loads(json.dumps(config["planted"]))
        if vary:
            self._vary()
        self._serials = {t["serial"] for r in topology["racks"] for t in r["compute_trays"]}
        self.events: list[dict] = []
        self.tickets: list[dict] = []

    # ------------------------------------------------------------------ utils
    def _u(self, lo: float, hi: float) -> float:
        return self.rng.uniform(lo, hi)

    def _poisson(self, lam: float) -> int:
        if lam > 30:   # normal approximation keeps Knuth's loop out of underflow
            return max(0, round(self.rng.gauss(lam, math.sqrt(lam))))
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= limit:
                return k
            k += 1

    def _serial(self, prefix: str) -> str:
        while True:
            s = prefix + "".join(self.rng.choices(string.ascii_uppercase + string.digits, k=8))
            if s not in self._serials:
                self._serials.add(s)
                return s

    def _t(self, lo: datetime | None = None, hi: datetime | None = None) -> datetime:
        lo, hi = lo or self.start, hi or self.end
        return datetime.fromtimestamp(self.rng.uniform(lo.timestamp(), hi.timestamp()), tz=UTC).replace(microsecond=0)

    def _vary(self) -> None:
        """Robustness runs: move every planted pattern and change its size."""
        p, lots = self.planted, self.cfg["optics"]["lots"]
        p["optic_lot"]["lot"] = self.rng.choice([k for k, v in lots.items() if v >= 0.10])
        p["optic_lot"]["rate_multiplier"] = round(self._u(3.0, 4.5), 2)
        p["cdu_drift"]["cdu"] = self.rng.choice(self.cdus)
        p["cdu_drift"]["start_week"] = self.rng.randint(3, 12)
        p["cdu_drift"]["peak_rise_c"] = round(self._u(2.0, 2.9), 2)
        p["cdu_drift"]["thermal_per_week_at_peak"] = round(self._u(4, 8), 1)
        p["reseat_recurrence"]["xid"] = self.rng.choice([79, 94, 145])   # signatures with at least 20% of GPU faults
        p["reseat_recurrence"]["recurrence_probability"] = round(self._u(0.35, 0.55), 2)
        p["decoy"]["rack"] = self.rng.choice(self.racks)["rack"]

    # ------------------------------------------------------------------- CDUs
    def _filter_changes(self) -> dict[str, list[datetime]]:
        """Quarterly filter changes, staggered two weeks apart across the hall's CDUs."""
        out = {}
        for i, cdu in enumerate(self.cdus):
            first = self.start + timedelta(days=7 + 14 * i, hours=15)
            out[cdu] = [first + timedelta(days=self.cfg["cdu"]["filter_change_days"] * k) for k in range(4)
                        if first + timedelta(days=self.cfg["cdu"]["filter_change_days"] * k) < self.end]
        return out

    def _drift_window(self, changes: dict[str, list[datetime]]) -> tuple[datetime, datetime | None]:
        d = self.planted["cdu_drift"]
        begin = self.start + timedelta(weeks=d["start_week"])
        # The fouled filter is replaced at the first scheduled change at least six weeks after fouling begins.
        fix = next((c for c in changes[d["cdu"]] if c >= begin + timedelta(weeks=6)), None)
        return begin, fix

    def rise(self, cdu: str, t: datetime) -> float:
        """Degrees above setpoint from the planted fouling at time t."""
        d = self.planted["cdu_drift"]
        if cdu != d["cdu"] or t < self.drift_begin or (self.drift_fix and t >= self.drift_fix):
            return 0.0
        ramp = ((self.drift_fix or self.end) - self.drift_begin).total_seconds()
        return d["peak_rise_c"] * min(1.0, (t - self.drift_begin).total_seconds() / ramp)

    def cdu_readings(self) -> list[dict]:
        c, out = self.cfg["cdu"], []
        t = self.start
        while t < self.end:
            for cdu in self.cdus:
                r = self.rise(cdu, t)
                frac = r / self.planted["cdu_drift"]["peak_rise_c"]
                supply = c["setpoint_c"] + r + self.rng.gauss(0, c["noise_c"])
                flow = c["flow_lpm"] * (1 - 0.07 * frac) + self.rng.gauss(0, 12)
                out.append({"cdu": cdu, "timestamp": iso(t), "supply_c": round(supply, 2),
                            "return_c": round(supply + 9.0 + self.rng.gauss(0, 0.3), 2), "flow_lpm": round(flow)})
            t += timedelta(hours=4)
        return out

    # ---------------------------------------------------------------- failures
    def _event(self, kind: str, t: datetime, rack: dict, **kw: Any) -> dict:
        e = {"kind": kind, "t": t, "rack": rack["rack"], "row_cdu": rack["cdu"], **kw}
        self.events.append(e)
        return e

    def _tray_events(self, queue: list) -> None:
        xids, weights = zip(*self.cfg["xid_mix"].items())
        for _ in range(self._poisson(self.cfg["rates_per_week"]["tray_gpu"] * self.weeks)):
            rack = self.rng.choice(self.racks)
            tray = self.rng.choice(rack["compute_trays"])
            heapq.heappush(queue, (self._t(), len(queue), "tray", rack, tray, int(self.rng.choices(xids, weights)[0])))
        # Decoy: a handful of unrelated faults on one rack, so it tops a ticket-count league table.
        d = self.planted["decoy"]
        rack = next(r for r in self.racks if r["rack"] == d["rack"])
        for i in range(d["extra_events"]):
            x = xids[i % len(xids)]
            heapq.heappush(queue, (self._t(), len(queue), "tray", rack, self.rng.choice(rack["compute_trays"]), int(x)))

    def _thermal_events(self, queue: list) -> None:
        for _ in range(self._poisson(self.cfg["rates_per_week"]["thermal"] * self.weeks)):
            rack = self.rng.choice(self.racks)
            heapq.heappush(queue, (self._t(), len(queue), "thermal", rack, self.rng.choice(rack["compute_trays"]), None))
        # Planted: thermal slowdowns in the racks the drifting CDU serves, growing with the rise (thinning).
        d = self.planted["cdu_drift"]
        peak = d["thermal_per_week_at_peak"] / (7 * 24)
        row = [r for r in self.racks if r["cdu"] == d["cdu"]]
        t = self.drift_begin
        while True:
            t += timedelta(hours=self.rng.expovariate(peak))
            if t >= (self.drift_fix or self.end):
                break
            if self.rng.random() < (self.rise(d["cdu"], t) / d["peak_rise_c"]) ** 2:
                rack = self.rng.choice(row)
                heapq.heappush(queue, (t.replace(microsecond=0), len(queue), "thermal", rack, self.rng.choice(rack["compute_trays"]), None))

    def _psu_events(self, queue: list) -> None:
        for _ in range(self._poisson(self.cfg["rates_per_week"]["psu"] * self.weeks)):
            rack = self.rng.choice(self.racks)
            shelf = self.rng.choice(rack["power_shelves"])
            heapq.heappush(queue, (self._t(), len(queue), "psu", rack, shelf, self.rng.randint(1, 6)))

    def _optics(self) -> None:
        o = self.cfg["optics"]
        lots, shares = zip(*o["lots"].items())
        self.inventory: list[dict] = []
        self.modules: list[dict] = []           # one per link end, current occupant
        for rack in self.racks:
            for tray in rack["compute_trays"]:
                for rail in range(LINK_RAILS):
                    lk = link_for(rack, tray["slot"], rail)
                    for end, loc in (("host", f"{lk['host']}:{lk['hca']}"), ("switch", f"{lk['switch']}:swp{lk['port']}")):
                        row = {"location": loc, "end": end, "rack": rack["rack"], "serial": self._serial("OS"),
                               "lot": self.rng.choices(lots, shares)[0], "installed": COMMISSIONED, "removed": ""}
                        self.inventory.append(row)
                        self.modules.append({"row": row, "link": lk, "rack": rack, "tray": tray})

    def _optic_events(self, queue: list) -> None:
        o, p = self.cfg["optics"], self.planted["optic_lot"]
        per_module = o["failures_per_module_year"] * self.weeks / 52.18
        by_lot: dict[str, list[dict]] = {}
        for m in self.modules:
            by_lot.setdefault(m["row"]["lot"], []).append(m)
        for lot in sorted(by_lot):
            mods = by_lot[lot]
            lam = per_module * len(mods) * (p["rate_multiplier"] if lot == p["lot"] else 1.0)
            for m in self.rng.sample(mods, min(len(mods), self._poisson(lam))):
                heapq.heappush(queue, (self._t(), len(queue), "optic_module", m["rack"], m, m["row"]))
        for _ in range(self._poisson(o["fiber_faults_per_week"] * self.weeks)):
            m = self.rng.choice(self.modules)
            heapq.heappush(queue, (self._t(), len(queue), "optic_fiber", m["rack"], m, None))

    # ----------------------------------------------------------------- repairs
    def run(self) -> dict[str, Any]:
        changes = self._filter_changes()
        self.drift_begin, self.drift_fix = self._drift_window(changes)
        readings = self.cdu_readings()
        self._optics()
        queue: list = []
        self._tray_events(queue)
        self._thermal_events(queue)
        self._psu_events(queue)
        self._optic_events(queue)

        xid, thermal, ufm, redfish = [], [], [], []
        tray_swaps: dict[str, list[dict]] = {}
        n = 0
        rs = self.planted["reseat_recurrence"]
        while queue:
            t0, _, kind, rack, unit, detail = heapq.heappop(queue)
            if t0 >= self.end or (kind == "optic_module" and detail is not unit["row"]):
                continue   # past the window, or the module failed after it had already been replaced
            n += 1
            opened = t0 + timedelta(minutes=self._u(1, 6))
            done = opened + timedelta(minutes=self._u(40, 240))
            resolved = done + timedelta(minutes=self._u(30, 150))
            ticket = {"number": f"INC{3_000_000 + n * 17:07d}", "priority": "P2", "state": "Closed", "rack": rack["rack"],
                      "hall": rack["hall"], "opened_at": iso(opened), "resolved_at": iso(resolved), "parts_used": []}
            recur_p = self.cfg["recurrence_probability"]
            if kind in ("tray", "thermal"):
                host, gpu = unit["host"], self.rng.randrange(4)
                swap = self.rng.random() < (self.cfg["tray_swap_probability"] if kind == "tray" else 0.5)
                ev = {"gpu_index": gpu, "host": host, "timestamp": iso(t0), "tray_serial": None}
                if kind == "tray":
                    ev.update({"xid": detail, "message": XID_MESSAGES[detail]})
                    xid.append(ev)
                    ticket.update({"category": "tray_gpu", "short_description": f"Compute tray {host}: XID {detail}"})
                    if not swap and detail == rs["xid"]:
                        recur_p = rs["recurrence_probability"]
                else:
                    ev.update({"event": "clocks_event", "reason": THERMAL_REASON})
                    thermal.append(ev)
                    ticket.update({"category": "tray_gpu", "short_description": f"Compute tray {host}: GPU {gpu} thermal slowdown"})
                ticket["configuration_item"] = host
                ticket["close_code"] = "Hardware replaced" if swap else "Cleaned/reseated"
                if swap:
                    rec = {"part": "Compute tray", "location": host, "removed_serial": None, "installed_serial": None}
                    ticket["parts_used"].append(rec)
                    tray_swaps.setdefault(host, []).append({"at": done, "rec": rec})
                ev["_swap_host"] = host
                if self.rng.random() < recur_p:
                    heapq.heappush(queue, (resolved + timedelta(days=self._u(2, 26)), len(queue), kind, rack, unit, detail))
            elif kind == "psu":
                shelf, psu = unit, detail
                path = f"{shelf['redfish']}/PowerSubsystem/PowerSupplies/{psu}"
                redfish.append({"resource": path, "property": "Status.Health", "value": "Critical", "timestamp": iso(t0)})
                redfish.append({"resource": path, "property": "Status.Health", "value": "OK", "timestamp": iso(done)})
                ticket.update({"category": "psu", "priority": "P3", "short_description": f"PSU {psu} in {rack['rack']} power shelf {shelf['slot']}",
                               "configuration_item": f"PSU {psu} in {rack['rack']} power shelf {shelf['slot']}", "close_code": "Hardware replaced"})
                ticket["parts_used"].append({"part": "PSU (5.5 kW)", "location": ticket["configuration_item"],
                                             "removed_serial": self._serial("PU"), "installed_serial": self._serial("PU")})
                if self.rng.random() < recur_p:
                    heapq.heappush(queue, (resolved + timedelta(days=self._u(2, 26)), len(queue), kind, rack, unit, detail))
            else:
                m = unit
                lk, row = m["link"], m["row"]
                down = {"event": "link_down", "switch": lk["switch"], "port": lk["port"], "peer_host": lk["host"],
                        "peer_hca": lk["hca"], "timestamp": iso(t0)}
                if kind == "optic_module":
                    ufm.append({"event": "module_alarm", "alarm": self.rng.choice(["TX bias high", "RX power low", "TX power low"]),
                                "location": row["location"], "module_serial": row["serial"],
                                "timestamp": iso(t0 - timedelta(minutes=self._u(2, 40)))})
                ufm.append(down)
                ufm.append({**down, "event": "link_up", "timestamp": iso(done)})
                replace = kind == "optic_module" or self.rng.random() < self.cfg["optics"]["fiber_fault_replace_probability"]
                ticket.update({"priority": self.rng.choice(["P2", "P2", "P3"]), "category": "optic_link",
                               "short_description": f"Link {lk['host']}:{lk['hca']} <-> {lk['switch']}:swp{lk['port']}",
                               "configuration_item": lk["host"], "close_code": "Hardware replaced" if replace else "Cleaned/reseated"})
                if replace:
                    # A fiber fault with no DOM alarm leaves the technician guessing which end; either is replaced.
                    if kind == "optic_fiber":
                        m = self.rng.choice([x for x in self.modules if x["link"] == lk])
                        row = m["row"]
                    new = {"location": row["location"], "end": row["end"], "rack": row["rack"], "serial": self._serial("OS"),
                           "lot": self.rng.choice(self.cfg["optics"]["spares_lots"]), "installed": iso(done)[:10], "removed": ""}
                    row["removed"] = iso(done)[:10]
                    self.inventory.append(new)
                    ticket["parts_used"].append({"part": "800G OSFP optic", "location": f"{row['location']} ({row['end']} side)",
                                                 "removed_serial": row["serial"], "installed_serial": new["serial"]})
                    m["row"] = new
                    if new["lot"] == self.planted["optic_lot"]["lot"]:
                        lam = self.cfg["optics"]["failures_per_module_year"] * self.planted["optic_lot"]["rate_multiplier"]
                        lam *= (self.end - done).days / 365.25
                        if self.rng.random() < lam:
                            heapq.heappush(queue, (self._t(done + DAY, self.end), len(queue), "optic_module", rack, m, new))
                if self.rng.random() < recur_p:
                    heapq.heappush(queue, (resolved + timedelta(days=self._u(2, 26)), len(queue), "optic_fiber", rack, m, None))
            self.tickets.append(ticket)

        self._chain_tray_serials(tray_swaps, xid + thermal)
        for ev in xid + thermal:
            ev.pop("_swap_host", None)
        pm = [{"task_id": f"PMH-{i:04d}", "system": "CDUs", "asset": cdu, "task": "Filter change and coolant sample",
               "completed_at": iso(t + timedelta(minutes=self._u(0, 90))), "result": "Complete", "evidence": "Badge entry; CDU filter differential pressure reset"}
              for i, (cdu, t) in enumerate(sorted(((c, t) for c, ts in changes.items() for t in ts), key=lambda x: x[1]), 1)]
        return {
            "window": {"start": iso(self.start), "end": iso(self.end), "seed": self.seed, "hall": self.cfg["hall"]},
            "streams": {
                "telemetry/dcgm_xid_events.jsonl": sorted(xid, key=lambda e: (e["timestamp"], e["host"])),
                "telemetry/dcgm_thermal_events.jsonl": sorted(thermal, key=lambda e: (e["timestamp"], e["host"])),
                "telemetry/ufm_port_events.jsonl": sorted(ufm, key=lambda e: (e["timestamp"], e["event"])),
                "telemetry/redfish_events.jsonl": sorted(redfish, key=lambda e: (e["timestamp"], e["resource"])),
                "facility/cdu_secondary.jsonl": readings,
                "facility/cdu_setpoints.json": {"source": "BMS configuration export (read-only)", "setpoint_c": self.cfg["cdu"]["setpoint_c"],
                                                "alarm_high_c": self.cfg["cdu"]["alarm_high_c"], "cdus": self.cdus},
                "landlord/pm_records.csv": pm,
                "customer/optic_inventory.csv": self.inventory,
                "vendor/tickets.json": self.tickets,
                "ground_truth/planted_patterns.json": self.answer_key(),
            },
        }

    def _chain_tray_serials(self, swaps: dict[str, list[dict]], events: list[dict]) -> None:
        """Serial history per slot, ending with the serial the sample month starts with."""
        final = {t["host"]: t["serial"] for r in self.racks for t in r["compute_trays"]}
        timeline: dict[str, list[tuple[datetime, str]]] = {}
        for host, ss in swaps.items():
            ss.sort(key=lambda s: s["at"])
            chain = [self._serial("CT") for _ in ss] + [final[host]]
            for i, s in enumerate(ss):
                s["rec"]["removed_serial"], s["rec"]["installed_serial"] = chain[i], chain[i + 1]
            timeline[host] = [(datetime.min.replace(tzinfo=UTC), chain[0])] + [(s["at"], chain[i + 1]) for i, s in enumerate(ss)]
        for ev in events:
            host, t = ev["_swap_host"], datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
            ev["tray_serial"] = next((sn for at, sn in reversed(timeline.get(host, [])) if at <= t), final[host])

    def answer_key(self) -> list[dict]:
        p = self.planted
        row = sorted(r["rack"] for r in self.racks if r["cdu"] == p["cdu_drift"]["cdu"])
        return [
            {"type": "optic_lot", "dimension": "optic_lot", "group": p["optic_lot"]["lot"], "signature": "optic_module",
             "owner": "Customer", "rate_multiplier": p["optic_lot"]["rate_multiplier"]},
            {"type": "cdu_drift", "dimension": "cdu_row", "group": p["cdu_drift"]["cdu"], "signature": "thermal",
             "owner": "Landlord", "racks": row, "drift_begin": iso(self.drift_begin),
             "fixed": iso(self.drift_fix) if self.drift_fix else None, "peak_rise_c": p["cdu_drift"]["peak_rise_c"]},
            {"type": "reseat_recurrence", "dimension": "fix", "group": "Cleaned/reseated", "signature": f"xid_{p['reseat_recurrence']['xid']}",
             "owner": "IT Partner", "recurrence_probability": p["reseat_recurrence"]["recurrence_probability"]},
            {"type": "decoy", "dimension": "rack", "group": p["decoy"]["rack"], "signature": "all",
             "extra_events": p["decoy"]["extra_events"], "note": "Chance clustering; must not be flagged."},
        ]


HISTORY_NOTE = ("Failure history for the failure pattern review. ground_truth/ is the answer key for scoring the review; "
                "the pattern analysis must not read it.")


def write_history(data: dict[str, Any], out_dir: str | Path) -> dict[str, int]:
    out = Path(out_dir)
    counts = {}
    for rel, rows in data["streams"].items():
        path = out / rel
        if rel.endswith(".jsonl"):
            _write_jsonl(path, rows)
        elif rel.endswith(".csv"):
            _write_csv(path, rows)
        else:
            _write_json(path, rows)
        counts[rel] = len(rows) if isinstance(rows, list) else 1
    _write_json(out / "manifest.json", {
        "generator": "scorecard.synthetic.history",
        "disclaimer": "Synthetic data for a portfolio demonstration. All sites, people, serials, and events are fictional.",
        "window": data["window"], "files": counts, "note": HISTORY_NOTE})
    return counts
