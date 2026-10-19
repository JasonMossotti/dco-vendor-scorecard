"""Condition history for predictive maintenance (the half-year before the sample month).

The failure history (``data/history/``) says *when* things failed. This layer adds what a
condition-monitoring feed would have shown *before* they failed, in the formats a site
already collects:

* ``optic_dom_daily.csv``: each optic module's daily worst-lane laser bias, transmit power,
  and receive power (CMIS DOM, as UFM Telemetry or mlxlink reads it), one row per module with
  its days as a space-separated series. Some module failures wear out visibly first (bias
  creeping up, power sagging); the rest fail suddenly. Fiber faults dip both ends for a day,
  and a few links step down and stay (a disturbed connector): neither is a module failure.
* ``gpu_memory_daily.csv``: corrected memory errors and remapped rows per GPU per day, in the
  GPU Health layer's columns, before and after every uncorrectable memory XID in the history.
* ``cdu_condition.csv``: each Hall A CDU's filter pressure drop and pump speeds at the
  history's 4-hour readings (Redfish ``Sensors/FilterDP`` and ``Pumps/n``), with the planted
  filter fouling of the failure history and one pump that wears out before it fails.
* ``pump_events.jsonl``: the Redfish pump events (failure, replacement) the history lacked.
* ``answer_key.json``: what was planted. The detectors never read it.

Its random stream is its own (seeded from a string) and it only reads ``data/history/``, so
every existing file and report is unchanged.
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .generator import _write_csv, _write_json, _write_jsonl, iso
from .history import LINK_RAILS, link_for

UTC = timezone.utc
DAY = timedelta(days=1)
MEMORY_XIDS = (48, 94, 95)
PUMP_PATH = "/redfish/v1/ThermalEquipment/CDUs/{cdu}/Pumps/{pump}"


def parse(s: str) -> datetime:
    if len(s) == 10:
        return datetime.fromisoformat(s).replace(tzinfo=UTC)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def series_text(values: list[float], scale: int = 10) -> str:
    return " ".join(str(int(round(v * scale))) for v in values)


class PredictGenerator:
    def __init__(self, history_dir: str | Path, topology: dict, config: dict, cdu_config: dict, seed: int | None = None,
                 vary: bool = False):
        self.h = Path(history_dir)
        man = json.loads((self.h / "manifest.json").read_text(encoding="utf-8"))
        self.window = man["window"]
        self.seed = self.window["seed"] if seed is None else seed
        self.rng = random.Random(f"predict-{self.seed}")
        self.start, self.end = parse(self.window["start"]), parse(self.window["end"])
        self.days = (self.end - self.start).days
        self.cfg = json.loads(json.dumps(config["condition"]))
        self.det = config["detectors"]
        self.cdu_cfg = cdu_config
        self.racks = [r for r in topology["racks"] if r["hall"] == self.window["hall"]]
        self.cdus = sorted({r["cdu"] for r in self.racks})
        if vary:
            self._vary()

    def _u(self, lo: float, hi: float) -> float:
        return self.rng.uniform(lo, hi)

    def _vary(self) -> None:
        """Robustness runs: move the planted pump failures (the history moves everything else)."""
        c = self.cfg["cdu"]
        wear, sudden = c["pump_wear"], c["sudden_pump_failure"]
        wear["cdu"], sudden["cdu"] = self.rng.choice(self.cdus), self.rng.choice(self.cdus)
        wear["wear_days"] = self.rng.randint(28, 56)
        wear["peak_pct"] = round(self._u(3.5, 6.0), 2)
        lo = self.start + timedelta(days=wear["wear_days"] + 21)
        wear["pump"], wear["fails_at"] = self._duty_moment(wear["cdu"], lo, self.end - timedelta(days=4))
        sudden["pump"], sudden["fails_at"] = self._duty_moment(sudden["cdu"], self.start + timedelta(days=14), self.end - timedelta(days=4))

    def _duty_moment(self, cdu: str, lo: datetime, hi: datetime) -> tuple[int, str]:
        t = datetime.fromtimestamp(self._u(lo.timestamp(), hi.timestamp()), tz=UTC).replace(second=0, microsecond=0)
        return self.duty_pump(cdu, t), iso(t)

    # ------------------------------------------------------------------ optics
    def optics(self) -> tuple[list[dict], dict]:
        oc, lim = self.cfg["optics"], self.det["optics"]["limits"]
        inv = _csv(self.h / "customer" / "optic_inventory.csv")
        ufm = _jsonl(self.h / "telemetry" / "ufm_port_events.jsonl")
        n = self.days
        # Link ends: host "a01-ct01:mlx5_0" and switch "leaf-a01-r0:swp1"; the peer of each and the link's loss.
        peer: dict[str, str] = {}
        for rack in self.racks:
            for tray in rack["compute_trays"]:
                for rail in range(LINK_RAILS):
                    lk = link_for(rack, tray["slot"], rail)
                    a, b = f"{lk['host']}:{lk['hca']}", f"{lk['switch']}:swp{lk['port']}"
                    peer[a], peer[b] = b, a
        links = sorted({tuple(sorted((a, b))) for a, b in peer.items()})
        nl = self.det_net_loss = {lk: self._u(0.4, 1.6) for lk in links}   # config/telemetry_network.yaml link_loss_db
        loss = {a: nl[tuple(sorted((a, peer[a])))] for a in peer}

        occupants: dict[str, list[dict]] = {}
        for r in inv:
            m = {"row": r, "bias0": self._u(*oc["bias_ma"]), "tx0": self._u(0.8, 2.2),     # config/telemetry_network.yaml tx_dbm
                 "first": max(0, (parse(r["installed"]) - self.start).days),
                 "last": min(n - 1, (parse(r["removed"]) - self.start).days) if r["removed"] else n - 1,
                 "deg": None}
            occupants.setdefault(r["location"], []).append(m)
        by_serial = {m["row"]["serial"]: m for ms in occupants.values() for m in ms}

        key_failures = []
        for e in ufm:
            if e["event"] != "module_alarm":
                continue
            m = by_serial[e["module_serial"]]
            at = parse(e["timestamp"])
            pre = self.rng.random() < oc["precursor_probability"]
            span = self._u(*oc["precursor_days"]) if pre else 0.0
            m["deg"] = {"alarm": e["alarm"], "at": at, "begin": at - timedelta(days=span), "span": span}
            key_failures.append({"serial": m["row"]["serial"], "location": m["row"]["location"], "alarm": e["alarm"],
                                 "alarm_at": e["timestamp"], "precursor": pre,
                                 "precursor_begin": iso(at - timedelta(days=span)) if pre else None})

        def drift(m: dict, t_end: datetime) -> float:
            """Fraction of the way to the alarm level by t_end (0 healthy, 1 at the alarm)."""
            d = m["deg"]
            if not d or t_end < d["begin"]:
                return 0.0
            if t_end >= d["at"] or d["span"] == 0:
                return 1.0 if t_end >= d["at"] else 0.0
            return ((t_end - d["begin"]).total_seconds() / (d["span"] * 86400)) ** oc["shape"]

        def day_end(i: int, m: dict) -> datetime:
            t = self.start + (i + 1) * DAY - timedelta(seconds=1)
            return min(t, m["deg"]["at"]) if m["deg"] and m["deg"]["at"] < t else t

        tx_noise, rx_noise, b_noise = oc["noise"]["tx_dbm"], oc["noise"]["rx_dbm"], oc["noise"]["bias_ma"]
        # Each module's own bias and transmit power, per day it is installed.
        for ms in occupants.values():
            for m in ms:
                m["bias"], m["tx"], m["rxdeg"] = {}, {}, {}
                for i in range(m["first"], m["last"] + 1):
                    f = drift(m, day_end(i, m))
                    al = m["deg"]["alarm"] if m["deg"] else None
                    m["bias"][i] = m["bias0"] + (f * (lim["bias_ma"]["alarm"] - m["bias0"]) if al == "TX bias high" else 0.0) + self.rng.gauss(0, b_noise)
                    m["tx"][i] = m["tx0"] + (f * (lim["tx_dbm"]["alarm"] - m["tx0"]) if al == "TX power low" else 0.0) + self.rng.gauss(0, tx_noise)
                    m["rxdeg"][i] = f if al == "RX power low" else 0.0

        # Fiber faults (a link down with no DOM alarm): both ends read low on the day of the fault.
        dips: dict[tuple[str, int], float] = {}
        alarms = {(e["location"], e["timestamp"][:13]) for e in ufm if e["event"] == "module_alarm"}
        alarm_at = {}
        for e in ufm:
            if e["event"] == "module_alarm":
                alarm_at.setdefault(e["location"], []).append(parse(e["timestamp"]))
        for e in ufm:
            if e["event"] != "link_down":
                continue
            a, b = f"{e['peer_host']}:{e['peer_hca']}", f"{e['switch']}:swp{e['port']}"
            t = parse(e["timestamp"])
            if any(abs((x - t).total_seconds()) < 3600 for loc in (a, b) for x in alarm_at.get(loc, [])):
                continue   # a module failure, not a fiber fault
            i, db = (t - self.start).days, self._u(*oc["fiber_dip_db"])
            for loc in (a, b):
                dips[(loc, i)] = dips.get((loc, i), 0.0) + db
        del alarms

        # Step decoys: a disturbed connector; both ends lose 1 to 3 dB and stay there. No failure follows.
        failed_links = {tuple(sorted((k["location"], peer[k["location"]]))) for k in key_failures}
        quiet = [lk for lk in links if lk not in failed_links]
        steps = []
        for lk in self.rng.sample(quiet, oc["step_decoys"]):
            i, db = self.rng.randint(20, n - 20), round(self._u(*oc["step_db"]), 2)
            steps.append({"link": list(lk), "from_day": iso(self.start + i * DAY)[:10], "db": db})
            for loc in lk:
                for j in range(i, n):
                    dips[(loc, j)] = dips.get((loc, j), 0.0) + db

        rows = []
        for loc in sorted(occupants):
            ms = sorted(occupants[loc], key=lambda m: (m["first"], m["row"]["installed"]))
            pms = occupants[peer[loc]]
            for m in ms:
                rx = []
                for i in range(m["first"], m["last"] + 1):
                    ptx = min((p["tx"][i] for p in pms if i in p["tx"]), default=m["tx0"])   # the far end's worst occupant that day
                    healthy = ptx - loss[loc]
                    v = healthy + m["rxdeg"][i] * (lim["rx_dbm"]["alarm"] - healthy) - dips.get((loc, i), 0.0)
                    rx.append(v + self.rng.gauss(0, rx_noise))
                r = m["row"]
                days = range(m["first"], m["last"] + 1)
                rows.append({"serial": r["serial"], "location": loc, "end": r["end"], "peer": peer[loc], "lot": r["lot"],
                             "first_day": iso(self.start + m["first"] * DAY)[:10], "days": len(days),
                             "bias_ma": series_text([m["bias"][i] for i in days]),
                             "tx_dbm": series_text([m["tx"][i] for i in days]),
                             "rx_dbm": series_text(rx)})
        return rows, {"failures": key_failures, "step_decoys": steps}

    # -------------------------------------------------------------- GPU memory
    def gpu_memory(self) -> tuple[list[dict], dict]:
        gc = self.cfg["gpu_memory"]
        xids = [e for e in _jsonl(self.h / "telemetry" / "dcgm_xid_events.jsonl") if e["xid"] in MEMORY_XIDS]
        tickets = json.loads((self.h / "vendor" / "tickets.json").read_text(encoding="utf-8"))
        # Tray serial timeline per host, from the tickets that replaced trays (in force from the ticket's resolution).
        swaps: dict[str, list[tuple[datetime, str, str]]] = {}
        for t in tickets:
            for p in t["parts_used"]:
                if p["part"] == "Compute tray":
                    swaps.setdefault(p["location"], []).append((parse(t["resolved_at"]), p["removed_serial"], p["installed_serial"]))
        final = {tr["host"]: tr["serial"] for r in self.racks for tr in r["compute_trays"]}

        def serial_at(host: str, t: datetime) -> str:
            ss = sorted(swaps.get(host, []))
            for at, removed, _ in ss:
                if t < at:
                    return removed
            return ss[-1][2] if ss else final[host]

        def swapped_after(host: str, serial: str) -> datetime | None:
            return next((at for at, removed, _ in sorted(swaps.get(host, [])) if removed == serial), None)

        def reset_at(host: str, t: datetime) -> datetime:
            """The repair ticket for the XID: the GPU is reset (the pending remap completes) when it closes."""
            tk = [x for x in tickets if x.get("configuration_item") == host and parse(x["opened_at"]) >= t - timedelta(minutes=1)]
            return min((parse(x["resolved_at"]) for x in tk), default=t + timedelta(hours=6))

        rows: dict[tuple[str, int, str, int], dict] = {}

        def put(day: int, host: str, gpu: int, serial: str, **kw: int) -> None:
            if not 0 <= day < self.days:
                return
            r = rows.setdefault((host, gpu, serial, day), {"date": iso(self.start + day * DAY)[:10], "host": host, "tray_serial": serial,
                                                           "gpu": gpu, "sbe_day": 0, "uce_day": 0, "remapped_rows": 0, "remap_pending": 0})
            for k, v in kw.items():
                r[k] = max(r[k], v) if k != "sbe_day" else r[k] + v

        # GPUs that carried a remapped row or two from before the window, unchanged until their tray leaves.
        gpus = [(tr["host"], g) for r in self.racks for tr in r["compute_trays"] for g in range(4)]
        stable = {(host, g, serial_at(host, self.start)): self.rng.randint(1, 2)
                  for host, g in self.rng.sample(gpus, round(len(gpus) * gc["stable_remap_fraction"]))}
        base = dict(stable)

        key = []
        for e in sorted(xids, key=lambda e: e["timestamp"]):
            host, g, serial, at = e["host"], e["gpu_index"], e["tray_serial"], parse(e["timestamp"])
            day = (at - self.start).days
            pre = self.rng.random() < gc["precursor_probability"]
            k0 = base.get((host, g, serial), 0)
            if pre:
                span = self.rng.randint(*gc["precursor_days"])
                sbe, rows_now = self._u(*gc["sbe_start"]), k0
                for j in range(day - span, day):
                    if self.rng.random() < 0.6:
                        rows_now += 1
                    put(j, host, g, serial, sbe_day=round(sbe), remapped_rows=rows_now)
                    sbe *= self._u(*gc["sbe_growth"])
                k0 = rows_now
            k0 += self.rng.randint(1, 2)
            base[(host, g, serial)] = k0
            put(day, host, g, serial, uce_day=1, remapped_rows=k0, remap_pending=1)
            r_at = reset_at(host, at)
            for j in range(day + 1, min(self.days, (r_at - self.start).days + 1)):
                put(j, host, g, serial, remapped_rows=k0, remap_pending=1 if self.start + (j + 1) * DAY <= r_at else 0)
            key.append({"host": host, "gpu": g, "tray_serial": serial, "xid": e["xid"], "at": e["timestamp"], "precursor": pre})
        # Remapped rows stay with the GPU every day until its tray is replaced.
        for kk in sorted({x[:3] for x in rows} | set(stable)):
            host, g, serial = kk
            gone = swapped_after(host, serial)
            known = sorted(d for (h2, g2, s2, d) in rows if (h2, g2, s2) == kk)
            level = stable.get(kk, 0)
            for j in range(0 if kk in stable else known[0], self.days):
                if gone and self.start + j * DAY >= gone:
                    break
                if (host, g, serial, j) in rows:
                    level = max(level, rows[(host, g, serial, j)]["remapped_rows"])
                elif level:
                    put(j, host, g, serial, remapped_rows=level)
        # Decoys: a one-day burst of corrected errors that does not recur.
        bursts = []
        for _ in range(round(gc["sbe_burst_decoys_per_week"] * self.days / 7)):
            host, g = self.rng.choice(gpus)
            j = self.rng.randrange(self.days)
            serial = serial_at(host, self.start + j * DAY + timedelta(hours=12))
            put(j, host, g, serial, sbe_day=self.rng.randint(150, 400))
            bursts.append({"host": host, "gpu": g, "date": iso(self.start + j * DAY)[:10]})
        out = sorted(rows.values(), key=lambda r: (r["date"], r["host"], r["gpu"]))
        return out, {"failures": key, "sbe_bursts": bursts}

    # --------------------------------------------------------------------- CDUs
    def duty_pump(self, cdu: str, t: datetime) -> int:
        """Lead-lag rotation: the duty pump changes every week (config/telemetry_cdu.yaml rotation_hours)."""
        hours = self.cdu_cfg["unit"]["rotation_hours"]
        k = int((t - self.start).total_seconds() // (hours * 3600))
        return 1 + (k + self.cdus.index(cdu)) % 2

    def cdus_condition(self) -> tuple[list[dict], list[dict], dict]:
        c, u, fc = self.cfg["cdu"], self.cdu_cfg["unit"], self.cdu_cfg["filter"]
        readings = _jsonl(self.h / "facility" / "cdu_secondary.jsonl")
        pm = [r for r in _csv(self.h / "landlord" / "pm_records.csv") if "Filter" in r["task"]]
        truth = json.loads((self.h / "ground_truth" / "planted_patterns.json").read_text(encoding="utf-8"))
        drift = next(x for x in truth if x["type"] == "cdu_drift")
        d_begin = parse(drift["drift_begin"])
        d_fix = parse(drift["fixed"]) if drift["fixed"] else None
        changes = {cdu: sorted(parse(r["completed_at"]) for r in pm if r["asset"] == cdu) for cdu in self.cdus}
        design, step = self.det["cdu_filter"]["design_flow_lpm"], timedelta(hours=c["reading_hours"])

        def fouling(cdu: str, t: datetime) -> float:
            if cdu != drift["group"] or t < d_begin or (d_fix and t >= d_fix):
                return 0.0
            ramp = ((d_fix or self.end) - d_begin).total_seconds()
            return c["filter_fouling_kpa"] * min(1.0, (t - d_begin).total_seconds() / ramp)

        # Pump failures: the worn pump and the sudden one; each is replaced a day or two later.
        fails = []
        for kind in ("pump_wear", "sudden_pump_failure"):
            p = c[kind]
            at = parse(p["fails_at"])
            if self.duty_pump(p["cdu"], at) != p["pump"]:
                raise ValueError(f"{kind}: {p['cdu']} pump {p['pump']} is not the duty pump at {p['fails_at']}")
            back = (at + timedelta(hours=self._u(*p["replaced_after_h"]))).replace(microsecond=0)
            fails.append({"kind": kind, "cdu": p["cdu"], "pump": p["pump"], "at": at, "back": back,
                          "wear_begin": at - timedelta(days=p["wear_days"]) if kind == "pump_wear" else None})

        def down(cdu: str, pump: int, t: datetime) -> bool:
            return any(f["cdu"] == cdu and f["pump"] == pump and f["at"] <= t < f["back"] for f in fails)

        def wear(cdu: str, pump: int, t: datetime) -> float:
            p = c["pump_wear"]
            f = fails[0]
            if cdu != f["cdu"] or pump != f["pump"] or t < f["wear_begin"] or t >= f["at"]:
                return 0.0
            return p["peak_pct"] * ((t - f["wear_begin"]).total_seconds() / (p["wear_days"] * 86400)) ** p["shape"]

        rows, limit_at = [], None
        lim = self.det["cdu_filter"]["change_kpa"]
        for r in readings:
            cdu, t0 = r["cdu"], parse(r["timestamp"])
            mid = t0 + step / 2
            done = [x for x in changes[cdu] if x <= mid]
            last = done[-1] if done else (changes[cdu][0] - timedelta(days=fc["rated_service_days"]) if changes[cdu] else self.start - timedelta(days=30))
            age = (mid - last).total_seconds() / 86400
            ratio = r["flow_lpm"] / design
            clean = fc["clean_kpa"] + fc["rise_kpa_per_day"] * age + fouling(cdu, mid)
            if limit_at is None and cdu == drift["group"] and clean >= lim:
                limit_at = t0
            dp = clean * ratio * ratio + self.rng.gauss(0, 0.05)
            # Pumps over the 4-hour reading: the duty pump, unless it is down; a failure inside the reading splits it.
            speeds = {1: 0.0, 2: 0.0}
            for k in range(4):
                t = t0 + step * (k + 0.5) / 4
                duty = self.duty_pump(cdu, t)
                if down(cdu, duty, t):
                    duty = 3 - duty
                speeds[duty] += u["duty_speed_pct"] * ratio * (1 + wear(cdu, duty, t) / 100) / 4
            for p in (1, 2):
                if speeds[p]:
                    speeds[p] += self.rng.gauss(0, c["pump_noise_pct"])
            rows.append({"timestamp": r["timestamp"], "cdu": cdu, "flow_lpm": r["flow_lpm"], "filter_dp_kpa": round(dp, 2),
                         "pump1_pct": round(speeds[1], 2), "pump2_pct": round(speeds[2], 2)})

        events = []
        for f in fails:
            res = PUMP_PATH.format(cdu=f["cdu"], pump=f["pump"])
            events += [{"cdu": f["cdu"], "property": "Status.Health", "resource": res, "timestamp": iso(f["at"]), "value": "Critical"},
                       {"cdu": f["cdu"], "property": "Status.State", "resource": res, "timestamp": iso(f["back"]), "value": "Enabled",
                        "note": "pump replaced"},
                       {"cdu": f["cdu"], "property": "Status.Health", "resource": res, "timestamp": iso(f["back"]), "value": "OK"}]
        key = {"filter": {"cdu": drift["group"], "fouling_begin": drift["drift_begin"], "fixed": drift["fixed"],
                          "limit_at": iso(limit_at) if limit_at else None},
               "pumps": [{"cdu": f["cdu"], "pump": f["pump"], "fails_at": iso(f["at"]), "replaced_at": iso(f["back"]),
                          "precursor": f["kind"] == "pump_wear", "wear_begin": iso(f["wear_begin"]) if f["wear_begin"] else None}
                         for f in fails]}
        return rows, sorted(events, key=lambda e: (e["timestamp"], e["resource"], e["property"])), key

    def run(self) -> dict[str, Any]:
        dom, k_opt = self.optics()
        mem, k_mem = self.gpu_memory()
        cdu, events, k_cdu = self.cdus_condition()
        return {"window": dict(self.window, seed=self.seed),
                "streams": {"optic_dom_daily.csv": dom, "gpu_memory_daily.csv": mem, "cdu_condition.csv": cdu,
                            "pump_events.jsonl": events,
                            "answer_key.json": {"optics": k_opt, "gpu_memory": k_mem, "cdu_filter": k_cdu["filter"],
                                                "cdu_pumps": k_cdu["pumps"]}}}


NOTE = ("Condition history for predictive maintenance, on the failure history in data/history/. answer_key.json records what "
        "was planted; the detectors must not read it.")


def write_predict(data: dict[str, Any], out_dir: str | Path) -> dict[str, int]:
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
        "generator": "scorecard.synthetic.predict",
        "disclaimer": "Synthetic data for a portfolio demonstration. All sites, people, serials, and events are fictional.",
        "window": data["window"], "files": counts, "note": NOTE})
    return counts
