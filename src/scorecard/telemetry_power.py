"""Agreements between the power telemetry and every record already written for the month.

Like the GPU and CDU sets (``scorecard.telemetry``, ``scorecard.telemetry_cdu``), each check reads only what the
power telemetry publishes (``data/telemetry/power/`` and the files built at publish time) and the existing
records, never the generator's internals, and returns how many cases it checked and which ones disagree.

1. racks: each rack's A plus B tap-off energy equals its input energy from the GPU telemetry, every hour
   (``rack_input_kwh``: the GPUs plus the rest of the rack); a rack with no samples draws nothing.
2. breakers: each tap-off's breaker is open exactly over the recorded CPM breaker events, and carries nothing in
   an hour it is open throughout.
3. feed_loss: a busway run reads 0 V exactly while the CPM records its feed lost, its tap-offs carry nothing then,
   and no run carries more than its single-feed limit (90% of 1,200 A) in any hour.
4. tree: each run's energy equals its tap-offs' plus the conductor loss; each UPS's output equals its runs';
   each hall's UPS output equals the meter every hour, and its input the meter less the bypass saving.
5. modes: each UPS's output source and working power modules equal the NMC events, minute by minute.
6. battery: charge falls only while a UPS is on battery, every discharge recovers, and each hour's seconds on
   battery equal the NMC events.
7. mech: each mechanical UPS reads its recorded load poll at the poll's minute; each hall's mechanical UPS input
   equals the meter every hour, and their output covers the CDUs' own draw.
8. generators: every EMCP reading on record is the generator's state, kW and percent kW at its minute; a
   generator outside a run is stopped; in a utility outage the sets carry the metered generator energy; run
   hours and fuel move only while running.
9. quality: UPS and busway voltage and frequency stay inside the bands, except a busway run whose feed the
   records show lost.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from scorecard import site_model as S
from scorecard.telemetry import MIN, Check, _csv, _jsonl, parse

HOUR = 60


def unpack(p: list) -> np.ndarray:
    """A published minute series: the first value, then the steps, with [n] for n unchanged minutes."""
    steps: list[int] = []
    for x in p:
        if isinstance(x, list):
            steps.extend([0] * x[0])
        else:
            steps.append(x)
    return np.cumsum(np.asarray(steps, dtype=np.int64))


@dataclass
class PowerData:
    dir: Path
    minutes_dir: Path
    manifest: dict
    ups_hourly: list[dict]
    busway_hourly: list[dict]
    generator_hourly: list[dict]
    states: list[dict]
    tapoff_hourly: dict
    nmc: list[dict]
    polls: list[dict]
    cpm: list[dict]
    epms: list[dict]
    emcp: list[dict]
    meters: dict[str, dict]
    rack_hourly: list[dict]
    cdu_hourly: list[dict]
    _minutes: dict

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def M(self) -> int:
        return int((parse(self.manifest["window"]["end"]) - self.start).total_seconds() // 60)

    def devices(self, family: str, **kw: Any) -> list[str]:
        return sorted(d for d, x in self.manifest["devices"].items()
                      if x["family"] == family and all(x.get(k) == v for k, v in kw.items()))

    def minutes(self, device: str) -> dict[str, np.ndarray]:
        if device not in self._minutes:
            raw = json.loads((self.minutes_dir / f"{device}.json").read_text(encoding="utf-8"))
            self._minutes[device] = {k: unpack(v) for k, v in raw["fields"].items()}
        return self._minutes[device]

    def m_of(self, ts: str | datetime) -> int:
        """Index of the first reading at or after ts."""
        t = parse(ts) if isinstance(ts, str) else ts
        return max(0, min(self.M, math.ceil((t - self.start).total_seconds() / 60 - 1e-9)))

    def floor_m(self, ts: str) -> int:
        return max(0, min(self.M - 1, int((parse(ts) - self.start).total_seconds() // 60)))

    def hour(self, h: int) -> str:
        return (self.start + h * HOUR * MIN).strftime("%Y-%m-%dT%H:%M:%SZ")

    def seconds(self, a: datetime, b: datetime) -> np.ndarray:
        """Seconds of each minute inside [a, b)."""
        out = np.zeros(self.M)
        s0 = max(0.0, (a - self.start).total_seconds())
        s1 = min(self.M * 60.0, (b - self.start).total_seconds())
        for m in range(int(s0 // 60), int(math.ceil(s1 / 60))):
            out[m] = max(0.0, min(s1, (m + 1) * 60.0) - max(s0, m * 60.0))
        return out


def load(power_dir: str | Path, minutes_dir: str | Path, sample_dir: str | Path, energy_dir: str | Path,
         gpu_dir: str | Path, cdu_dir: str | Path) -> PowerData:
    d, sd = Path(power_dir), Path(sample_dir)
    fac = sd / "facility"
    return PowerData(dir=d, minutes_dir=Path(minutes_dir),
                     manifest=json.loads((d / "manifest.json").read_text(encoding="utf-8")),
                     ups_hourly=_csv(d / "ups_hourly.csv"), busway_hourly=_csv(d / "busway_hourly.csv"),
                     generator_hourly=_csv(d / "generator_hourly.csv"), states=_jsonl(d / "states.jsonl"),
                     tapoff_hourly=json.loads((Path(minutes_dir) / "tapoff_hourly.json").read_text(encoding="utf-8")),
                     nmc=sorted(_jsonl(fac / "ups_nmc_events.jsonl"), key=lambda e: (e["timestamp"], e["ups"])),
                     polls=_jsonl(fac / "ups_status.jsonl"),
                     cpm=sorted(_jsonl(fac / "busway_cpm_events.jsonl"), key=lambda e: e["timestamp"]),
                     epms=sorted(_jsonl(fac / "epms_events.jsonl"), key=lambda e: e["timestamp"]),
                     emcp=_jsonl(fac / "emcp_readings.jsonl"),
                     meters={r["hour"]: r for r in _csv(Path(energy_dir) / "meters_hourly.csv")},
                     rack_hourly=_csv(Path(gpu_dir) / "rack_hourly.csv"),
                     cdu_hourly=_csv(Path(cdu_dir) / "cdu_hourly.csv"), _minutes={})


# ------------------------------------------------------------------------- the records, read the way a client would
def nmc_spans(t: PowerData, ups: str) -> dict[str, list[tuple[datetime, datetime]]]:
    since: dict[str, datetime] = {}
    out: dict[str, list] = {"bypass": [], "battery": [], "module": []}
    for e in t.nmc:
        if e["ups"] != ups:
            continue
        ts, x = parse(e["timestamp"]), e["event"]
        if x.endswith("switchedBypass"):
            since["bypass"] = ts
        elif x.endswith("onBattery"):
            since["battery"] = ts
        elif x.endswith("onLine"):
            for k in ("bypass", "battery"):
                if k in since:
                    out[k].append((since.pop(k), ts))
        elif x.startswith("Power module") and x.endswith("fault"):
            since["module"] = ts
        elif x == "Power module redundancy restored" and "module" in since:
            out["module"].append((since.pop("module"), ts))
    end = t.start + t.M * MIN
    for k, a in since.items():
        out[k].append((a, end))
    return out


def breaker_spans(t: PowerData) -> dict[str, list[tuple[int, int]]]:
    """Open spans (minutes) per tap-off TO-<rack>-<side>. A record that names the tap-off without its side takes
    the side from its busway's suffix."""
    out: dict[str, list] = {}
    since: dict[str, int] = {}
    for e in t.cpm:
        if e.get("point") != "Tap-off breaker":
            continue
        tap = e["tapoff"] if e["tapoff"][-2:] in ("-A", "-B") else f"{e['tapoff']}-{e['busway'][-1]}"
        m = t.m_of(e["timestamp"])
        if e["event"] == "Breaker open":
            since[tap] = m
        elif tap in since:
            out.setdefault(tap, []).append((since.pop(tap), m))
    for tap, a in since.items():
        out.setdefault(tap, []).append((a, t.M))
    return out


def dead_spans(t: PowerData) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list] = {}
    since: dict[str, int] = {}
    for e in t.cpm:
        if e.get("point") != "Voltage L-L avg":
            continue
        m = t.m_of(e["timestamp"])
        if e["state"] == "out_of_tolerance":
            since[e["busway"]] = m
        elif e["busway"] in since:
            out.setdefault(e["busway"], []).append((since.pop(e["busway"]), m))
    for bw, a in since.items():
        out.setdefault(bw, []).append((a, t.M))
    return out


def _per_hour(mask: np.ndarray) -> np.ndarray:
    return mask.reshape(-1, HOUR).sum(axis=1)


def rack_input_kwh(row: dict[str, Any], rest: dict[str, float]) -> float:
    """A rack's input energy in one row of rack_hourly.csv: its GPUs' energy plus the rest of the rack
    (config/telemetry_cdu.yaml's rack model: a fixed draw per GPU-minute and a share of each GPU watt)."""
    return int(row["samples"]) * rest["per_gpu_w"] / 60 / 1000 + (1 + rest["per_gpu_watt"]) * float(row["power_kwh"])


def agreements(t: PowerData, cfg: dict[str, Any], rack_rest: dict[str, float], energy_cfg: dict[str, Any],
               site: dict | None = None) -> list[Check]:
    site = site or S.load_site()
    ck = cfg["checks"]
    uc = cfg["ups"]
    el = cfg["electrical"]
    gc = cfg["generator"]
    loss = energy_cfg["busway_loss_fraction"]
    M, H = t.M, t.M // HOUR
    racks_c = Check("racks", "Each rack's A plus B tap-offs carry its power from the GPU telemetry, every hour")
    brk_c = Check("breakers", "Tap-off breakers open and close exactly at the recorded busway CPM events")
    feed_c = Check("feed_loss", "A run reads 0 V exactly while its feed is recorded lost; no run exceeds its single-feed limit")
    tree_c = Check("tree", "Tap-offs add up to their runs, runs to their UPS, and each hall's UPSs to the energy meters")
    modes_c = Check("modes", "UPS output source and working power modules match the NMC events, minute by minute")
    batt_c = Check("battery", "Batteries discharge only while on battery, recover after, and match the seconds on battery")
    mech_c = Check("mech", "Mechanical UPSs read their recorded polls, equal the meter, and cover the CDUs' draw")
    gen_c = Check("generators", "Generators match every EMCP reading, are stopped otherwise, and carry the outage energy")
    pq_c = Check("quality", "Voltage and frequency stay inside the bands except where the records show a feed lost")

    taps = t.tapoff_hourly["tapoffs"]
    tap_wh = {k: v["wh"] for k, v in taps.items()}
    hidx = {t.hour(h): h for h in range(H)}
    racks_dev = {x["rack"] for x in t.manifest["devices"].values() if x["family"] == "tapoff"}

    # 1: racks
    seen = set()
    for r in t.rack_hourly:
        h = hidx.get(r["hour"])
        if h is None or r["rack"] not in racks_dev:
            continue
        seen.add((r["rack"], h))
        want = rack_input_kwh(r, rack_rest) * 1000
        got = sum(tap_wh.get(f"TO-{r['rack']}-{s}", [0] * H)[h] for s in ("A", "B"))
        racks_c(abs(got - want) <= 2, f"{r['rack']} {r['hour']}: tap-offs {got} Wh, rack {want:.0f} Wh")
    for tap, wh in sorted(tap_wh.items()):
        rack = taps[tap]["rack"]
        for h in range(H):
            if (rack, h) not in seen:
                racks_c(wh[h] == 0, f"{tap} {t.hour(h)}: {wh[h]} Wh with no rack telemetry that hour")

    # 2: breakers
    bs = breaker_spans(t)
    for tap in sorted(set(bs) | {k for k, v in taps.items() if any(v["open_min"])}):
        mask = np.zeros(M, bool)
        for a, b in bs.get(tap, []):
            mask[a:b] = True
        want = _per_hour(mask)
        got = taps.get(tap, {}).get("open_min", [0] * H)
        bad = [t.hour(h) for h in range(H) if int(got[h]) != int(want[h])]
        brk_c(not bad, f"{tap}: open minutes differ from the CPM record in hours {bad[:3]}")
        for h in np.flatnonzero(want == HOUR):
            brk_c(tap_wh.get(tap, [0] * H)[h] == 0, f"{tap} {t.hour(int(h))}: carries load with its breaker open")
    rec_changes = sorted((e["timestamp"], e["event"].split()[-1]) for e in t.cpm if e.get("point") == "Tap-off breaker")
    st_changes = sorted((s["time"], s["value"]) for s in t.states if s["point"] == "cpmAcBrkrCurrentStatus")
    brk_c(rec_changes == st_changes, f"breaker states {len(st_changes)} vs CPM events {len(rec_changes)}")

    # 3: feed loss and the single-feed limit
    ds = dead_spans(t)
    rating = S.product(site, "starline_1200t5")["rating_a"]
    run_rows: dict[str, list[dict]] = {}
    for r in t.busway_hourly:
        run_rows.setdefault(r["run"], []).append(r)
    dev = t.manifest["devices"]
    for run, rows in sorted(run_rows.items()):
        mask = np.zeros(M, bool)
        for a, b in ds.get(run, []):
            mask[a:b] = True
        want = _per_hour(mask)
        for h, r in enumerate(rows):
            feed_c(int(r["dead_min"]) == int(want[h]), f"{run} {r['hour']}: {r['dead_min']} minutes at 0 V, CPM record {want[h]}")
            feed_c(float(r["amps_max"]) <= ck["busway_limit"] * rating,
                   f"{run} {r['hour']}: {r['amps_max']} A over {ck['busway_limit'] * rating:.0f} A")
            if want[h] == HOUR:
                for tap in dev[run]["tapoffs"]:
                    feed_c(tap_wh.get(tap, [0] * H)[h] == 0, f"{tap} {r['hour']}: carries load with its run's feed lost")
    for run, spans in ds.items():
        trips = [e for e in t.epms if e["device"].endswith(f"feeder to {run}")]
        for a, b in spans:
            near = [e for e in trips if abs(t.m_of(e["timestamp"]) - a) <= 1 or abs(t.m_of(e["timestamp"]) - b) <= 1]
            feed_c(len(near) >= 1, f"{run}: feed lost at minute {a} with no EPMS feeder event")

    # 4: the tree
    run_kwh = {(r["run"], r["hour"]): float(r["kwh"]) for r in t.busway_hourly}
    ups_rows = {(r["ups"], r["hour"]): r for r in t.ups_hourly}
    for run in sorted(run_rows):
        for h in range(H):
            hk = t.hour(h)
            want = sum(tap_wh.get(tap, [0] * H)[h] for tap in dev[run]["tapoffs"]) / 1000 * (1 + loss)
            tree_c(abs(run_kwh[(run, hk)] - want) <= 0.06, f"{run} {hk}: {run_kwh[(run, hk)]} kWh, tap-offs {want:.3f}")
    it_ups = t.devices("ups", kind="it")
    for u in it_ups:
        feeds = [r for r, x in dev.items() if x["family"] == "busway" and x["ups"] == u]
        for h in range(H):
            hk = t.hour(h)
            got = float(ups_rows[(u, hk)]["out_kwh"])
            want = sum(run_kwh[(r, hk)] for r in feeds)
            tree_c(abs(got - want) <= 0.01 * (len(feeds) + 1), f"{u} {hk}: output {got} kWh, its runs {want:.2f}")
    halls = sorted({dev[u]["hall"] for u in it_ups})
    for hall in halls:
        letter = hall[-1].lower()
        ids = [u for u in it_ups if dev[u]["hall"] == hall]
        eff = S.product(site, S.hall_by_id(site, hall)["power"]["ups_product"])["efficiency"]
        saving = np.zeros(M)
        battery = np.zeros(M)
        for u in ids:
            x = t.minutes(u)
            for a, b in nmc_spans(t, u)["bypass"]:
                saving += x["out_kw"] / 10 / 60 * t.seconds(a, b) / 60 * (1 / eff - 1 / uc["bypass_efficiency"])
            # a discharge lowers the input and the recharge after it raises it: the battery's own DC readings (V x A)
            # say by how much; the float trickle (well under 2 A) is left out
            ba = x["batt_a"] / 10
            battery += np.where(np.abs(ba) > 2.0, ba * x["batt_v"] / 10 / 1000 / 60, 0.0)
        for h in range(H):
            hk = t.hour(h)
            met = t.meters.get(hk)
            if met is None:
                continue
            out = sum(float(ups_rows[(u, hk)]["out_kwh"]) for u in ids)
            tree_c(abs(out - float(met[f"ups_out_{letter}_kwh"])) <= ck["energy_kwh_tolerance"],
                   f"{hall} {hk}: UPS output {out:.1f} kWh, meter {met[f'ups_out_{letter}_kwh']}")
            got = sum(float(ups_rows[(u, hk)]["in_kwh"]) for u in ids)
            want = float(met[f"ups_in_{letter}_kwh"]) - float(saving[h * HOUR:(h + 1) * HOUR].sum()) \
                + float(battery[h * HOUR:(h + 1) * HOUR].sum())
            tree_c(abs(got - want) <= ck["energy_kwh_tolerance"],
                   f"{hall} {hk}: UPS input {got:.1f} kWh, meter less bypass saving, plus battery recharge less discharge {want:.1f}")

    # 5, 6: modes and battery
    src = uc["output_source"]
    for u in t.devices("ups"):
        x = t.minutes(u)
        sp = nmc_spans(t, u)
        want = np.full(M, src["normal"], dtype=np.int64)
        for a, b in sp["bypass"]:
            want[t.m_of(a):t.m_of(b)] = src["bypass"]
        for a, b in sp["battery"]:
            want[t.m_of(a):t.m_of(b)] = src["battery"]
        bad = np.flatnonzero(x["source"] != want)
        modes_c(len(bad) == 0, f"{u}: output source differs from the NMC events at {len(bad)} minutes, first {bad[:1].tolist()}")
        n = int(dev[u]["modules"])
        wmod = np.full(M, n, dtype=np.int64)
        for a, b in sp["module"]:
            wmod[t.m_of(a):t.m_of(b)] = n - 1
        bad = np.flatnonzero(x["modules_ok"] != wmod)
        modes_c(len(bad) == 0, f"{u}: working power modules differ from the NMC events at {len(bad)} minutes")
        rows = [ups_rows[(u, t.hour(h))] for h in range(H)]
        byp = np.zeros(M)
        for a, b in sp["bypass"]:
            byp += t.seconds(a, b)
        bad = [r["hour"] for h, r in enumerate(rows) if int(r["bypass_min"]) != int((byp[h * HOUR:(h + 1) * HOUR] > 0).sum())]
        modes_c(not bad, f"{u}: bypass minutes differ from the NMC events in hours {bad[:3]}")
        # 6: battery
        bat = np.zeros(M)
        for a, b in sp["battery"]:
            bat += t.seconds(a, b)
        bad = [r["hour"] for h, r in enumerate(rows) if int(r["battery_s"]) != int(round(float(bat[h * HOUR:(h + 1) * HOUR].sum())))]
        batt_c(not bad, f"{u}: seconds on battery differ from the NMC events in hours {bad[:3]}")
        soc = x["soc_pct"]
        falls = np.flatnonzero(np.diff(soc) < 0) + 1
        stray = [int(m) for m in falls if bat[max(0, m - 1):m + 1].sum() == 0]
        batt_c(not stray, f"{u}: charge falls with the UPS not on battery at minutes {stray[:3]}")
        for a, b in sp["battery"]:
            m = t.m_of(b)
            # the charge reads in whole percent: an event that drew under 1% of the battery need not show a fall
            idle = dev[u]["rating_kw"] * energy_cfg["ups_no_load_fraction"] if dev[u]["kind"] == "it" else 0.0
            seg = slice(max(0, int((a - t.start).total_seconds() // 60) - 1), m + 1)      # from the minute before the event's own
            drew = float(((x["out_kw"][seg] / 10 / dev[u]["eff"] + idle) * t.seconds(a, b)[seg] / 3600).sum())
            cap = dev[u]["rating_kw"] * 5 / 60
            if drew >= 0.01 * cap:
                batt_c(int(soc[seg].min()) < int(soc[seg][0]),
                       f"{u}: on battery at {a} with no fall in charge")
            batt_c(int(soc[seg].min()) >= int(soc[seg][0]) - math.ceil(100 * drew / cap) - 1,
                   f"{u}: charge fell more than the battery supplied at {a}")
            back = np.flatnonzero(soc[m:] >= 100)
            batt_c(len(back) > 0 and back[0] <= 120, f"{u}: charge not back to 100% within two hours of {b}")
        batt_c(int(soc[0]) == 100, f"{u}: month starts below full charge")

    # 7: mechanical UPSs
    for p in t.polls:
        u = p["ups"]
        if not u.startswith("MUPS-") or "load_pct" not in p or u not in dev:
            continue
        x = t.minutes(u)
        m = t.m_of(p["timestamp"])
        if m >= M:
            continue
        want = int(round(float(p["load_pct"]) * dev[u]["rating_kw"] / 100 * 10))
        mech_c(int(x["out_kw"][m]) == want, f"{u} {p['timestamp']}: {x['out_kw'][m] / 10} kW, poll {want / 10} kW")
    cdu_kw: dict[tuple[str, str], float] = {}
    for r in t.cdu_hourly:
        cdu_kw[(r["hall"], r["hour"])] = cdu_kw.get((r["hall"], r["hour"]), 0.0) + float(r["power_kwh"])
    for hall in halls:
        letter = hall[-1].lower()
        ids = t.devices("ups", kind="mech", hall=hall)
        for h in range(H):
            hk = t.hour(h)
            met = t.meters.get(hk)
            if met is None:
                continue
            got = sum(float(ups_rows[(u, hk)]["in_kwh"]) for u in ids)
            mech_c(abs(got - float(met[f"mech_{letter}_kwh"])) <= ck["energy_kwh_tolerance"],
                   f"{hall} {hk}: mechanical UPS input {got:.1f} kWh, meter {met[f'mech_{letter}_kwh']}")
            out = sum(float(ups_rows[(u, hk)]["out_kwh"]) for u in ids)
            mech_c(out >= cdu_kw.get((hall, hk), 0.0), f"{hall} {hk}: mechanical UPS output {out:.1f} kWh under the CDUs' {cdu_kw.get((hall, hk), 0.0):.1f}")

    # 8: generators
    codes = gc["states"]
    gen_rows = {(r["generator"], r["hour"]): r for r in t.generator_hourly}
    for g in t.devices("generator"):
        x = t.minutes(g)
        last: dict[int, dict] = {}
        for r in sorted((r for r in t.emcp if r["generator"] == g), key=lambda r: r["timestamp"]):
            last[t.floor_m(r["timestamp"])] = r                 # a minute reads the latest reading in it
        for m, r in sorted(last.items()):
            gen_c(int(x["state"][m]) == codes[r["engine_operating_state"]] and int(x["kw"][m]) == round(float(r["gen_total_kw"]) * 10)
                  and int(x["pct_kw"][m]) == round(float(r["gen_pct_rated_kw"]) * 10),
                  f"{g} {r['timestamp']}: telemetry {x['state'][m]} {x['kw'][m] / 10} kW {x['pct_kw'][m] / 10}%, EMCP "
                  f"{r['engine_operating_state']} {r['gen_total_kw']} kW {r['gen_pct_rated_kw']}%")
        # runs from the published states: Starting to Stopped
        allowed = np.zeros(M, bool)
        start = None
        for s in sorted((s for s in t.states if s["device"] == g), key=lambda s: s["time"]):
            if s["value"] == "Starting":
                start = s["m"]
            elif s["value"] == "Stopped" and start is not None:
                allowed[start:s["m"]] = True
                start = None
        if start is not None:
            allowed[start:] = True
        gen_c(not ((x["state"] != codes["Stopped"]) & ~allowed).any(), f"{g}: not stopped outside a recorded run")
        running = (x["state"] == codes["Running"]) | (x["state"] == codes["Cooldown"])
        gen_c(not ((np.diff(x["hours"]) != 0) & ~running[1:]).any(), f"{g}: run hours advance while not running")
        gen_c(not ((np.diff(x["fuel_pct"]) != 0) & ~running[1:]).any(), f"{g}: fuel level moves while not running")
        gen_c(bool((np.diff(x["fuel_pct"]) <= 0).all()), f"{g}: fuel level rises with no recorded delivery")
        gen_c(not ((x["kw"] > 0) & ~allowed).any(), f"{g}: kW outside a recorded run")
    for o in t.manifest["outages"]:
        a, b = parse(o["trip"]), parse(o["back"])
        h0, h1 = t.m_of(a) // HOUR, (t.m_of(b) - 1) // HOUR
        got = sum(float(gen_rows[(g, t.hour(h))]["kwh"]) for g in t.devices("generator") for h in range(h0, h1 + 1)
                  if not _test_hour(t, g, h))
        # the meter books the site to the generators from the utility trip; the sets carry it from the ties closing
        # (the UPS and mechanical UPS batteries bridge the seconds between), so each hour's share is the carried part
        tc = parse(o["ties_closed"])
        span = lambda lo, hi, h: max(0.0, (min(hi, t.start + (h + 1) * HOUR * MIN) - max(lo, t.start + h * HOUR * MIN)).total_seconds())  # noqa: E731
        # the meter also books a flat share of the hour; the UPS inputs show how far the load in the carried minutes
        # sat above or below the hour's average
        it = sum(t.minutes(u)["in_kw"] / 10 for u in t.devices("ups"))
        carried = t.seconds(tc, b)
        want = sum(float(t.meters[t.hour(h)]["generator_kwh"]) * span(tc, b, h) / max(span(a, b, h), 1e-9)
                   + float(((it[h * HOUR:(h + 1) * HOUR] - it[h * HOUR:(h + 1) * HOUR].mean()) * carried[h * HOUR:(h + 1) * HOUR]).sum() / 3600)
                   for h in range(h0, h1 + 1) if t.hour(h) in t.meters)
        gen_c(abs(got - want) <= ck["generator_energy_tolerance"] * max(want, 1.0),
              f"outage {o['trip']}: generators {got:.1f} kWh, metered generator energy {want:.1f} kWh")

    # 9: power quality
    band = ck["voltage_band_pct"] / 100
    hz_band = ck["frequency_band_hz"]
    for u in t.devices("ups"):
        x = t.minutes(u)
        for f in ("in_v", "byp_v", "out_v"):
            dev_v = np.abs(x[f] - el["ln_v"]) / el["ln_v"]
            pq_c(bool((dev_v <= band).all()), f"{u} {f}: {x[f].min()} to {x[f].max()} V outside {el['ln_v']} V +/-{ck['voltage_band_pct']}%")
        hz = x["in_hz"] / 10
        pq_c(bool((np.abs(hz - el["hz"]) <= hz_band).all()), f"{u}: frequency {hz.min()} to {hz.max()} Hz")
    for r in t.busway_hourly:
        dead = int(r["dead_min"]) > 0
        lo, hi = float(r["v_min"]), float(r["v_max"])
        ok = hi <= el["ll_v"] * (1 + band) and (dead or lo >= el["ll_v"] * (1 - band))
        pq_c(ok, f"{r['run']} {r['hour']}: {lo} to {hi} V")
    for g in t.devices("generator"):
        x = t.minutes(g)
        on = x["state"] >= codes["Running"]
        if on.any():
            v = x["v_ll"][on]
            pq_c(bool((np.abs(v - el["gen_v_ll"]) <= el["gen_v_ll"] * band).all()), f"{g}: running at {v.min()} to {v.max()} V")
            hz = x["hz"][on] / 100
            pq_c(bool((np.abs(hz - el["hz"]) <= hz_band).all()), f"{g}: running at {hz.min()} to {hz.max()} Hz")
    return [racks_c, brk_c, feed_c, tree_c, modes_c, batt_c, mech_c, gen_c, pq_c]


def _test_hour(t: PowerData, g: str, h: int) -> bool:
    """An hour holding one of the generator's own recorded test readings (load bank, not site load)."""
    a, b = t.start + h * HOUR * MIN, t.start + (h + 1) * HOUR * MIN
    return any(r["generator"] == g and a <= parse(r["timestamp"]) < b and float(r["gen_total_kw"]) > 0 for r in t.emcp)


def summary(checks: list[Check]) -> dict[str, Any]:
    return {"agreements": sum(c.ok for c in checks), "of": len(checks),
            "cases": sum(c.checked for c in checks), "misses": sum(len(c.misses) for c in checks)}


