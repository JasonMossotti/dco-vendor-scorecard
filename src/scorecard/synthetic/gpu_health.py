"""Synthetic GPU health data for Site AUS-1, modeled on public DCGM-style health checks.

Portfolio demo; all data fictional. Runs on a finished month (the committed sample or a generated
month) with its own random stream and writes beside it, never into it:

* ``watches.jsonl``: health watch results (subsystem, Warn or Fail) per GPU, opened and cleared.
  Every XID in the month's DCGM feed (``telemetry/dcgm_xid_events.jsonl``) appears here at the same
  time on the same GPU, and clears when the scheduler returns the node to service or the tray is
  replaced, so nothing contradicts the records already shown. An uncorrectable memory error also
  leaves a row remap pending until the GPU is reset.
* ``gpu_counters.csv``: a daily snapshot for every GPU with a non-zero counter: corrected and
  uncorrected memory errors that day, remapped rows, remap pending, and the day's peak temperatures.
* ``thermal_episodes.jsonl``: hardware thermal slowdown episodes per GPU.
* ``cdu_hourly.csv``: CDU secondary supply temperature and flow per hour (mean, and the hour's worst).
* ``rack_daily.csv``: per rack per day, the trays reporting and the peak GPU and HBM temperatures.
* ``answer_key.json``: what was planted, for the self-check only.

Sizes come from ``data/<month>/site/topology.json``; every assumption from ``config/gpu_health.yaml``.
"""

from __future__ import annotations

import csv
import io
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from scorecard import xid as X

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "gpu_health.yaml"
UTC = timezone.utc
DAY, HOUR = timedelta(days=1), timedelta(hours=1)
PRODUCT = {"HALL-A": "gb200_nvl72", "HALL-B": "gb300_nvl72"}

COUNTER_COLUMNS = ["date", "host", "tray_serial", "gpu", "sbe_day", "uce_day", "remapped_rows", "remap_pending",
                   "gpu_temp_max_c", "hbm_temp_max_c"]
CDU_COLUMNS = ["hour", "cdu", "supply_c", "supply_max_c", "flow_lpm", "flow_min_lpm"]
RACK_COLUMNS = ["date", "rack", "hall", "cdu", "trays_reporting", "gpu_temp_max_c", "hbm_temp_max_c"]


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


class GpuHealthLayer:
    def __init__(self, data_dir: str | Path, seed: int, cfg: dict[str, Any] | None = None):
        self.dir = Path(data_dir)
        self.cfg = cfg or load_config()
        self.rng = random.Random(f"{seed}:gpu-health")       # independent of every other stream
        man = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))["window"]
        self.start, self.end = parse(man["start"]), parse(man["end"])
        self.days = [self.start + i * DAY for i in range((self.end - self.start) // DAY)]
        topo = json.loads((self.dir / "site" / "topology.json").read_text(encoding="utf-8"))
        self.racks = topo["racks"]
        self.xids = sorted(_jsonl(self.dir / "telemetry" / "dcgm_xid_events.jsonl"), key=lambda e: e["timestamp"])
        self.sched = sorted(_jsonl(self.dir / "telemetry" / "scheduler_node_states.jsonl"), key=lambda e: e["timestamp"])
        self.incidents = json.loads((self.dir / "ground_truth" / "incidents.json").read_text(encoding="utf-8"))
        self.cdu_events = _jsonl(self.dir / "facility" / "cdu_redfish_events.jsonl")
        inv = _jsonl(self.dir / "telemetry" / "redfish_inventory_changes.jsonl")
        self.swaps: dict[str, list[tuple[datetime, str, str]]] = {}
        for i in sorted(inv, key=lambda i: i["observed_at"]):
            if i["property"] == "SerialNumber" and i.get("host"):
                self.swaps.setdefault(i["host"], []).append((parse(i["observed_at"]), i["old_value"], i["new_value"]))
        self.reporting_from = self._reporting_from()
        self.blocked: dict[str, list[tuple[datetime, datetime]]] = {}     # drained or down: no load, no throttling
        for i, e in enumerate(self.sched):
            if e["state"] in ("drain", "down"):
                back = next((parse(x["timestamp"]) for x in self.sched[i + 1:] if x["node"] == e["node"] and x["state"] == "idle"), self.end)
                self.blocked.setdefault(e["node"], []).append((parse(e["timestamp"]), back))

    # ----------------------------------------------------------------- the site over the month
    def _reporting_from(self) -> dict[str, datetime]:
        """Hall A reports all month; a Hall B rack from its power-on milestone (M4)."""
        out = {r["rack"]: self.start for r in self.racks if r["hall"] == "HALL-A"}
        p = self.dir / "vendor" / "deployment_milestones.csv"
        if p.exists():
            for m in csv.DictReader(p.open(encoding="utf-8")):
                if m["milestone"] == "M4" and m["reported_complete_at"]:
                    out[m["rack"]] = max(self.start, parse(m["reported_complete_at"]))
        return out

    def clear(self, host: str, s: datetime, e: datetime, lo: datetime, hi: datetime) -> tuple[datetime, datetime] | None:
        """Move an episode out of any span where the node was drained or down, within [lo, hi); None if it cannot fit."""
        dur, gap = e - s, timedelta(minutes=10)
        for _ in range(6):
            hit = next(((a, b) for a, b in self.blocked.get(host, []) if s < b and s + dur > a), None)
            if hit is None:
                return s, s + dur
            a, b = hit
            s = b + gap if b + gap + dur < hi else a - gap - dur
            if s < lo:
                return None
        return None

    def serials(self, host: str, initial: str) -> list[tuple[datetime, datetime, str]]:
        """The trays installed in a host over the month: (from, to, serial)."""
        out, t, cur = [], self.start, initial
        for at, _old, new in self.swaps.get(host, []):
            out.append((t, at, cur))
            t, cur = at, new
        out.append((t, self.end, cur))
        return out

    def trays(self) -> list[dict]:
        out = []
        for r in self.racks:
            if r["rack"] not in self.reporting_from:
                continue
            for c in r["compute_trays"]:
                out.append({"rack": r["rack"], "hall": r["hall"], "cdu": r["cdu"], "host": c["host"],
                            "product": PRODUCT[r["hall"]], "from": self.reporting_from[r["rack"]],
                            "serials": self.serials(c["host"], c["serial"])})
        return out

    def _returned(self, host: str, after: datetime) -> datetime | None:
        return next((parse(e["timestamp"]) for e in self.sched if e["node"] == host and e["state"] == "idle"
                     and e["reason"] == "returned to service" and parse(e["timestamp"]) > after), None)

    def _incident(self, e: dict) -> dict | None:
        t = parse(e["timestamp"])
        return next((i for i in self.incidents if i.get("host") == e["host"] and i.get("xid") == e["xid"]
                     and abs((parse(i["t0"]) - t).total_seconds()) < 600), None)

    # ----------------------------------------------------------------- CDU secondary loop
    def cdu_hours(self, excursion: dict | None) -> list[dict]:
        c, out = self.cfg["cdu"], []
        trips = {}
        for e in self.cdu_events:
            if e["property"] == "Status.Health" and "/Pumps/" in e["resource"] and e["value"] == "Critical":
                t = parse(e["timestamp"])
                trips[(e["cdu"], t.replace(minute=0, second=0))] = True
        cdus = sorted({r["cdu"] for r in self.racks})
        level = {k: 0.0 for k in cdus}
        t = self.start
        while t < self.end:
            for k in cdus:
                level[k] = 0.8 * level[k] + self.rng.gauss(0, c["noise_c"])
                supply = c["setpoint_c"] + level[k]
                flow = c["flow_lpm"] + self.rng.gauss(0, 10)
                smax, fmin = supply + abs(self.rng.gauss(0, 0.15)), flow - abs(self.rng.gauss(0, 15))
                if trips.get((k, t)):
                    fmin = flow - self.rng.uniform(*c["failover_dip_lpm"])     # the standby pump ramps in; stays in band
                if excursion and excursion["cdu"] == k and excursion["start"] < t + HOUR and excursion["end"] > t:
                    smax, fmin = max(smax, excursion["supply_max_c"]), min(fmin, excursion["flow_min_lpm"])
                    supply, flow = (supply + smax) / 2, (flow + fmin) / 2
                out.append({"hour": iso(t), "cdu": k, "supply_c": round(supply, 2), "supply_max_c": round(smax, 2),
                            "flow_lpm": round(flow), "flow_min_lpm": round(fmin)})
            t += HOUR
        return out

    # ----------------------------------------------------------------- the month
    def run(self, excursion: bool | None = None) -> dict[str, Any]:
        cfg, pc, rng = self.cfg, self.cfg["plants"], self.rng
        trays = self.trays()
        by_host = {t["host"]: t for t in trays}
        watches: list[dict] = []
        counters: dict[tuple[str, str, int], dict[str, dict]] = {}   # (host, serial, gpu) -> date -> fields
        key: dict[str, Any] = {"early_warning": [], "rts_pending": [], "hot_trays": [], "excursions": [],
                               "decoys": {"stable_remaps": 0, "error_bursts": 0, "brief_slowdowns": 0}}

        def day_of(t: datetime) -> str:
            return t.strftime("%Y-%m-%d")

        def ctr(host: str, serial: str, gpu: int) -> dict[str, dict]:
            return counters.setdefault((host, serial, gpu), {})

        # Healthy trays that saw no incident this month: candidates for the planted IT-side cases.
        touched = {e["host"] for e in self.xids} | {i.get("host") for i in self.incidents}
        quiet = [t for t in trays if t["host"] not in touched and len(t["serials"]) == 1 and t["from"] == self.start]

        # ---- 1. XIDs: a watch on the same GPU at the same time; memory errors leave a remap pending
        memory = set(cfg["memory_xids"])
        precursor_at: list[tuple[str, str, int, datetime]] = []
        mem_incidents = []
        for e in self.xids:
            t, host, gpu, serial = parse(e["timestamp"]), e["host"], int(e["gpu_index"]), e["tray_serial"]
            system, result = cfg["xid_watch"].get(e["xid"], ["Driver", "Fail"])
            inc = self._incident(e)
            back = self._returned(host, t)
            swap = next((at for at, old, _new in self.swaps.get(host, []) if old == serial and at > t), None)
            cleared = min([x for x in (back, swap) if x], default=None)
            watches.append({"opened": iso(t), "cleared": iso(cleared) if cleared else None, "host": host, "tray_serial": serial,
                            "gpu": gpu, "system": system, "result": result, "xid": e["xid"],
                            "message": f"XID {e['xid']}: {X.names().get(e['xid'], e['message'])}"})
            if e["xid"] in memory:
                mem_incidents.append((e, inc, t, back, swap))
                precursor_at.append((host, serial, gpu, t))

        # A planted return to service with the remap still pending: an uncorrectable memory error the
        # IT Partner closed without resetting the GPU (only where no tray was swapped).
        eligible = [m for m in mem_incidents if m[1] and not m[1].get("swap") and m[3] and not m[4]
                    and "phantom_fix" not in (m[1].get("anomalies") or [])]
        planted = set()
        for m in rng.sample(eligible, min(pc["rts_pending"], len(eligible))):
            planted.add(id(m[0]))
        for e, inc, t, back, swap in mem_incidents:
            host, gpu, serial = e["host"], int(e["gpu_index"]), e["tray_serial"]
            phantom = inc is not None and "phantom_fix" in (inc.get("anomalies") or [])
            if swap and (not back or swap <= back):
                cleared, how = swap, "tray replaced"
            elif id(e) in planted or phantom:
                cleared, how = swap, ("tray replaced" if swap else None)
                if back:
                    key["rts_pending"].append({"host": host, "tray_serial": serial, "gpu": gpu, "rts": iso(back),
                                               "kind": "planted" if id(e) in planted else "phantom_fix",
                                               "ticket": inc.get("ticket_number") if inc else None})
            else:
                lo = max(t + timedelta(minutes=5), back - timedelta(minutes=40)) if back else None
                cleared = lo + (back - lo) * rng.uniform(0.2, 0.8) if back else None
                how = "GPU reset" if back else None
            watches.append({"opened": iso(t), "cleared": iso(cleared) if cleared else None, "host": host, "tray_serial": serial,
                            "gpu": gpu, "system": "Memory", "result": "Warn", "xid": None,
                            "message": "Row remap pending: the GPU must be reset to complete it" + (f" (cleared by {how})" if how else "")})
            c = ctr(host, serial, gpu)
            d = c.setdefault(day_of(t), {})
            d["uce_day"] = d.get("uce_day", 0) + 1
            d["remap_add"] = d.get("remap_add", 0) + 1
            d.setdefault("pending_spans", []).append((t, cleared))

        # ---- 2. Early warning: rising corrected errors and remaps before some memory XIDs, and on a few
        # GPUs that have not failed yet (the drain-and-replace watch list)
        lo_d, hi_d = pc["precursor_days"]

        def ramp(host: str, serial: str, gpu: int, begin: datetime, until: datetime) -> None:
            c = ctr(host, serial, gpu)
            base, growth, k = rng.uniform(120, 250), rng.uniform(1.4, 2.0), 0
            d = begin
            while d < until and d < self.end:
                x = c.setdefault(day_of(d), {})
                x["sbe_day"] = x.get("sbe_day", 0) + int(base * growth ** k * rng.uniform(0.95, 1.05)) + k
                if k and rng.random() < 0.45:
                    x["remap_add"] = x.get("remap_add", 0) + 1
                d, k = d + DAY, k + 1

        for host, serial, gpu, t in precursor_at:
            if rng.random() >= pc["precursor_probability"]:
                continue
            first = (t - timedelta(days=rng.randint(lo_d, hi_d))).replace(hour=0, minute=0, second=0)
            tr = by_host.get(host)
            span = next((a for a, _b, s2 in tr["serials"] if s2 == serial), None) if tr else None
            if span is None or first < max(span, tr["from"]) or any(h == host and s == serial and g == gpu and first <= t2 < t
                                         for h, s, g, t2 in precursor_at):
                continue        # the ramp would start before the data or the tray was installed, or cross an earlier XID
            ramp(host, serial, gpu, first, t.replace(hour=0, minute=0, second=0))
            key["early_warning"].append({"host": host, "tray_serial": serial, "gpu": gpu, "kind": "precursor",
                                         "ramp_from": day_of(first), "xid_at": iso(t)})
        n = rng.randint(*pc["watch_list"])
        for tr in rng.sample(quiet, min(n, len(quiet))):
            gpu, serial = rng.randrange(cfg["gpus_per_tray"]), tr["serials"][0][2]
            first = self.end - timedelta(days=rng.randint(5, 12))
            ramp(tr["host"], serial, gpu, first, self.end)
            key["early_warning"].append({"host": tr["host"], "tray_serial": serial, "gpu": gpu, "kind": "watch_list",
                                         "ramp_from": day_of(first), "xid_at": None})
            quiet.remove(tr)

        # Background: GPUs carrying a remapped row or two from earlier months, unchanged; and one-day bursts.
        bg = cfg["background"]
        for tr in trays:
            for gpu in range(cfg["gpus_per_tray"]):
                if rng.random() < bg["stable_remap_fraction"]:
                    serial = tr["serials"][0][2]
                    ctr(tr["host"], serial, gpu).setdefault("_base", {})["remapped"] = rng.choice([1, 1, 2])
                    key["decoys"]["stable_remaps"] += 1
        for tr in rng.sample(quiet, min(bg["sbe_burst_decoys"], len(quiet))):
            gpu, serial = rng.randrange(cfg["gpus_per_tray"]), tr["serials"][0][2]
            when = self.start + DAY * rng.randrange(len(self.days))
            ctr(tr["host"], serial, gpu).setdefault(day_of(when), {})["sbe_day"] = rng.randint(300, 900)
            key["decoys"]["error_bursts"] += 1
            quiet.remove(tr)

        # ---- 3. Thermal: CDU supply, a planted hot tray (inside the rack), and in generated months a
        # CDU excursion that throttles the racks it serves
        exc = None
        if excursion is None:
            excursion = rng.random() < pc["cdu_excursion_probability"]
        if excursion:
            prod = sorted({t["cdu"] for t in trays if t["from"] == self.start})
            cdu = rng.choice(prod)
            begin = self.start + DAY * rng.randrange(2, len(self.days) - 1) + timedelta(minutes=rng.randrange(0, 1440))
            begin = min(begin, self.end - 3 * HOUR)
            exc = {"cdu": cdu, "start": begin, "end": begin + timedelta(minutes=rng.randint(25, 100)),
                   "supply_max_c": round(rng.uniform(29.0, 31.5), 2), "flow_min_lpm": rng.randint(850, 1250)}
        cdu_rows = self.cdu_hours(exc)
        daily_supply_max = {}
        for r in cdu_rows:
            k = (r["cdu"], r["hour"][:10])
            daily_supply_max[k] = max(daily_supply_max.get(k, 0.0), r["supply_c"])
        hot = rng.sample([t for t in quiet if t["hall"] == "HALL-A"], min(pc["hot_tray"], len(quiet)))
        hot_rise = {t["host"]: (rng.uniform(*pc["hot_tray_rise_c"]), self.start + DAY * rng.randrange(0, len(self.days) // 2))
                    for t in hot}
        for t in hot:
            key["hot_trays"].append({"host": t["host"], "rack": t["rack"], "tray_serial": t["serials"][0][2],
                                     "from": day_of(hot_rise[t["host"]][1])})

        th = cfg["thermal"]
        episodes: list[dict] = []
        rack_daily: dict[tuple[str, str], dict] = {}
        for tr in trays:
            over = th["gpu_over_supply_c"][tr["product"]]
            for d in self.days:
                if d + DAY - timedelta(minutes=1) < tr["from"]:
                    continue                    # no sample today: the tray powers on in the day's last minute or later
                ds = day_of(d)
                # a tray that powers on today cannot throttle before it reports (the first whole minute after power-on)
                on = tr["from"].replace(second=0, microsecond=0) + timedelta(minutes=1)
                serial = next(s for a, b, s in tr["serials"] if a <= d + DAY / 2 < b or b == self.end)
                supply = daily_supply_max[(tr["cdu"], ds)]
                rise = 0.0
                if tr["host"] in hot_rise and d >= hot_rise[tr["host"]][1]:
                    rise = hot_rise[tr["host"]][0]
                peaks = [supply + over + rise + rng.gauss(0, th["daily_sd_c"]) for _ in range(cfg["gpus_per_tray"])]
                for g, p in enumerate(peaks):
                    if p >= th["slowdown_c"]:
                        for _ in range(rng.randint(1, 3)):
                            s = max(d + timedelta(minutes=rng.randrange(60, 1380)), on)
                            e = s + timedelta(seconds=rng.randint(180, 900))
                            s, e = self.clear(tr["host"], s, e, max(d, on), d + DAY) or (s, e)
                            episodes.append({"start": iso(s), "end": iso(e),
                                             "host": tr["host"], "tray_serial": serial, "gpu": g,
                                             "gpu_temp_max_c": round(min(p, th["slowdown_c"] + 3.5), 1)})
                if rng.random() < th["blip_probability"]:
                    key["decoys"]["brief_slowdowns"] += 1
                    g = rng.randrange(cfg["gpus_per_tray"])
                    s = max(d + timedelta(minutes=rng.randrange(60, 1380)), on)
                    e = s + timedelta(seconds=rng.randint(30, 110))
                    s, e = self.clear(tr["host"], s, e, max(d, on), d + DAY) or (s, e)
                    blip = round(th["slowdown_c"] + rng.uniform(0.1, 1.2), 1)
                    episodes.append({"start": iso(s), "end": iso(e), "host": tr["host"], "tray_serial": serial, "gpu": g,
                                     "gpu_temp_max_c": blip})
                    peaks[g] = max(peaks[g], blip)      # the day's peak is at least the episode's own reading
                if exc and tr["cdu"] == exc["cdu"] and d <= exc["start"] < d + DAY and tr["from"] <= exc["start"]:
                    for g in range(cfg["gpus_per_tray"]):
                        if rng.random() < 0.7:
                            s = exc["start"] + timedelta(minutes=rng.uniform(2, 10))
                            e = min(exc["end"] + timedelta(minutes=rng.uniform(0, 5)), s + timedelta(hours=2),
                                    d + DAY - timedelta(seconds=1))     # recorded on the day it began
                            temp = th["slowdown_c"] + rng.uniform(0.5, 3.5)
                            if any(s < b and e > a for a, b in self.blocked.get(tr["host"], [])):
                                continue                # a drained or dark tray draws no load and does not throttle
                            episodes.append({"start": iso(s), "end": iso(e), "host": tr["host"], "tray_serial": serial,
                                             "gpu": g, "gpu_temp_max_c": round(temp, 1)})
                            peaks[g] = max(peaks[g], temp)
                for g, p in enumerate(peaks):
                    p = min(p, th["slowdown_c"] + 3.5)
                    c = counters.get((tr["host"], serial, g))
                    if c is not None:
                        c.setdefault(ds, {})["_temps"] = (round(p, 1), round(p + th["hbm_over_gpu_c"], 1))
                rd = rack_daily.setdefault((ds, tr["rack"]), {"date": ds, "rack": tr["rack"], "hall": tr["hall"], "cdu": tr["cdu"],
                                                               "trays_reporting": 0, "gpu_temp_max_c": 0.0, "hbm_temp_max_c": 0.0})
                rd["trays_reporting"] += 1
                pm = min(max(peaks), th["slowdown_c"] + 3.5)
                rd["gpu_temp_max_c"] = round(max(rd["gpu_temp_max_c"], pm), 1)
                rd["hbm_temp_max_c"] = round(max(rd["hbm_temp_max_c"], pm + th["hbm_over_gpu_c"]), 1)
        if exc:
            racks = sorted({t["rack"] for t in trays if t["cdu"] == exc["cdu"] and t["from"] <= exc["start"]})
            key["excursions"].append({"cdu": exc["cdu"], "start": iso(exc["start"]), "end": iso(exc["end"]), "racks": racks})

        return {"watches": sorted(watches, key=lambda w: (w["opened"], w["host"], w["gpu"], w["system"])),
                "counters": self._counter_rows(counters, by_host),
                "episodes": sorted(episodes, key=lambda e: (e["start"], e["host"], e["gpu"])),
                "cdu": cdu_rows,
                "racks": [rack_daily[k] for k in sorted(rack_daily)],
                "key": key,
                "window": {"start": iso(self.start), "end": iso(self.end)}}

    def _counter_rows(self, counters: dict, by_host: dict) -> list[dict]:
        """Daily snapshots: cumulative remapped rows, that day's error counts, pending at the day's end."""
        th, out = self.cfg["thermal"], []
        for (host, serial, gpu), days in sorted(counters.items()):
            tr = by_host.get(host)
            if not tr:
                continue
            span = next(((a, b) for a, b, s in tr["serials"] if s == serial), None)
            if not span:
                continue
            remapped = days.get("_base", {}).get("remapped", 0)
            pendings: list[tuple[datetime, datetime | None]] = []
            for d in self.days:
                if d + DAY <= max(span[0], tr["from"]) or d >= span[1]:
                    continue
                ds = d.strftime("%Y-%m-%d")
                x = days.get(ds, {})
                remapped += x.get("remap_add", 0)
                pendings += x.get("pending_spans", [])
                eod = min(d + DAY, self.end) - timedelta(seconds=1)
                pending = any(a <= eod and (b is None or b > eod) for a, b in pendings)
                if not (remapped or x.get("sbe_day") or x.get("uce_day")):
                    continue
                g, h = x.get("_temps", (None, None))
                if g is None:
                    g = round(self.cfg["cdu"]["setpoint_c"] + th["gpu_over_supply_c"][tr["product"]] + self.rng.gauss(0, th["daily_sd_c"]), 1)
                    h = round(g + th["hbm_over_gpu_c"], 1)
                out.append({"date": ds, "host": host, "tray_serial": serial, "gpu": gpu, "sbe_day": x.get("sbe_day", 0),
                            "uce_day": x.get("uce_day", 0), "remapped_rows": remapped, "remap_pending": int(pending),
                            "gpu_temp_max_c": g, "hbm_temp_max_c": h})
        return sorted(out, key=lambda r: (r["date"], r["host"], r["gpu"], r["tray_serial"]))


def _csv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def write_gpu_health(out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, int]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    files = {
        "watches.jsonl": "".join(json.dumps(w, sort_keys=True) + "\n" for w in out["watches"]),
        "gpu_counters.csv": _csv(out["counters"], COUNTER_COLUMNS),
        "thermal_episodes.jsonl": "".join(json.dumps(e, sort_keys=True) + "\n" for e in out["episodes"]),
        "cdu_hourly.csv": _csv(out["cdu"], CDU_COLUMNS),
        "rack_daily.csv": _csv(out["racks"], RACK_COLUMNS),
        "answer_key.json": json.dumps(out["key"], indent=2, sort_keys=True) + "\n",
    }
    counts = {"watches.jsonl": len(out["watches"]), "gpu_counters.csv": len(out["counters"]),
              "thermal_episodes.jsonl": len(out["episodes"]), "cdu_hourly.csv": len(out["cdu"]),
              "rack_daily.csv": len(out["racks"]), "answer_key.json": 1}
    files["manifest.json"] = json.dumps({
        "disclaimer": "Synthetic GPU health data for a portfolio demonstration, modeled on public DCGM-style health "
                      "checks and NVIDIA's public XID catalog. All names, serials, and events are fictional.",
        "source": source, "window": out["window"], "files": counts}, indent=2, sort_keys=True) + "\n"
    for name, text in files.items():
        (dest / name).write_text(text, encoding="utf-8", newline="\n")
    return counts
