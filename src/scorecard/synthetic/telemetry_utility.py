"""Synthetic utility mains metering for Site AUS-1, and the UPS ride-through it leaves the site.

Portfolio demo; all data fictional. Runs on a finished month after its power telemetry, with its own random stream
(``{seed}:telemetry:utility``), and writes beside it, never into it.

* **Mains** (PowerLogic ION9000 revenue meters on the 13.8 kV mains MV-A and MV-B, read through the Landlord's PME):
  kW is the site's load each minute (the power layer's ``site_load_kw``) while the utility carries it, pinned hour by
  hour so both mains add up to ``utility_kwh`` in the energy meters. It splits by bus: each UPS's input on the bus its
  unit substation sits on, the rest of the site half and half. The meters sit on the utility side of the main breakers,
  so from the utility trip to the closed-transition retransfer they read no voltage and no current, and the trip's
  undervoltage sag shows in the lowest voltage of its minute. Frequency is the utility frequency the UPS inputs see.
* **Ride-through**: each minute, the shortest battery runtime among the IT UPSs carrying load (and among the mechanical
  UPSs, which keep the CDU pumps and thermal-wall fans running), as each UPS's network management card reports it in
  the power telemetry. Nothing new is drawn for it; it is the published UPS runtimes, gathered.

Published tiers (see ``write_utility``): hourly per main, hourly ride-through, and minute windows around every
breaker change, committed; the one-minute series per main and the ride-through built at publish time with checksums
in the manifest. Settings: ``config/telemetry_utility.yaml``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from scorecard.synthetic.telemetry import MIN, _csv, _dump, iso
from scorecard.synthetic.telemetry_power import HOUR_MIN, SQRT3, PowerTelemetry, _ar, device_fields, pack, pin_sum

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "telemetry_utility.yaml"

MAINS_HOURLY = ["hour", "main", "kwh", "kw_avg", "kw_max", "amps_max", "v_avg", "v_min", "v_max", "dead_min", "pf_avg", "hz_min", "hz_max",
                "thd_max"]
RIDE_HOURLY = ["hour", "scope", "min_s", "ups", "avg_s"]


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rng(seed: int, *parts: object) -> np.random.Generator:
    key = ":".join(str(p) for p in (seed, "telemetry", "utility") + parts)
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def bus_of(ups: str, cfg: dict[str, Any]) -> str:
    """The MV bus a UPS's unit substation sits on: by the parity of its number."""
    n = int(ups.split("-")[1][1:])
    return cfg["split"]["ups_bus"]["odd" if n % 2 else "even"]


class UtilityTelemetry:
    """One-minute readings for both 13.8 kV mains, and the site's UPS ride-through each minute."""

    def __init__(self, power: PowerTelemetry, pout: dict[str, Any], cfg: dict[str, Any] | None = None):
        self.power, self.pout = power, pout
        self.cfg = cfg or load_config()
        self.seed, self.start, self.end, self.M, self.H = power.seed, power.start, power.end, power.M, power.H
        self.mains = list(self.cfg["mains"])

    def t_of(self, m: int) -> datetime:
        return self.start + m * MIN

    # ----------------------------------------------------------------- mains
    def dead(self) -> tuple[np.ndarray, np.ndarray, list[dict]]:
        """Seconds of each minute without the utility, whether each minute's read finds the main breaker closed, and the
        outages (trip and retransfer, from the EPMS)."""
        p = self.power
        secs = np.zeros(self.M)
        brk = np.ones(self.M, dtype=np.int64)
        outs = p.outages()
        for o in outs:
            secs += p.overlap(o["trip"], o["back"])
            brk[p.m_of(o["trip"]):p.m_of(o["back"])] = 0
        return np.minimum(secs, 60.0), brk, outs

    def series(self) -> dict[str, dict[str, np.ndarray]]:
        p, el, M = self.power, self.cfg["electrical"], self.M
        dead_s, brk, outs = self.dead()
        on = 1 - dead_s / 60
        site = p.site_load_kw(self.pout["ups"]) * on
        # both mains together, tenths of kW per minute, pinned to the meter's utility energy each hour
        total = np.zeros(M, dtype=np.int64)
        for k in range(self.H):
            sl = slice(k * HOUR_MIN, (k + 1) * HOUR_MIN)
            row = p.meters.get(iso(self.t_of(k * HOUR_MIN)))
            target = int(round(float(row["utility_kwh"]) * 600)) if row else 0
            total[sl] = pin_sum(np.maximum(site[sl], 0.0), target) if target else 0
        # split by bus: each UPS's input on its bus, the rest half and half (with a little wander)
        ups_in = {b: np.zeros(M) for b in self.mains}
        for u, x in self.pout["ups"].items():
            ups_in[bus_of(u, self.cfg)] += x["in_kw"] * on
        rest = np.maximum(site - sum(ups_in.values()), 0.0)
        share = self.cfg["split"]["rest_share_a"] * (1 + _ar(_rng(self.seed, "split"), M, self.cfg["split"]["rest_share_sd_pct"] / 100, 0.99))
        raw_a = ups_in[self.mains[0]] + rest * share
        raw_b = ups_in[self.mains[1]] + rest * (1 - share)
        den = raw_a + raw_b
        kw_a = np.where(den > 0, np.round(total * raw_a / np.where(den > 0, den, 1.0)), 0).astype(np.int64)
        kw10 = {self.mains[0]: kw_a, self.mains[1]: total - kw_a}
        # voltage: one utility wander shared by both mains (the same substation) plus each transformer's own
        common = _ar(_rng(self.seed, "v", "common"), M, el["v_sd_pct"] / 100, el["v_rho"])
        hz_u = p.utility_hz()
        trip_m = {p.floor_m(o["trip"]) for o in outs}
        out = {}
        for b in self.mains:
            r = _rng(self.seed, b)
            v = el["nominal_v"] * (1 + common + _ar(r, M, el["v_sd_pct"] / 400, 0.99))
            off = r.normal(0, el["phase_sd_pct"] / 100, 3)
            off -= off.mean()
            ph = [v * (1 + off[k] + r.normal(0, 0.0003, M)) for k in range(3)]
            v_avg = (ph[0] + ph[1] + ph[2]) / 3
            pf = np.minimum(float(r.uniform(*el["pf"])) + _ar(r, M, 0.002, 0.95), 0.999)
            thd = float(r.uniform(*el["thd_pct"])) * (1 + _ar(r, M, 0.06, 0.98))
            kw = kw10[b] / 10.0
            amps = kw * 1000 / (SQRT3 * v_avg * pf)          # the minute's average, at the voltage while the utility was in
            ia = r.normal(0, el["current_imbalance_pct"] / 100, 3)
            ia -= ia.mean()
            amps_ph = [amps * (1 + ia[k]) for k in range(3)]
            kvar = kw * np.sqrt(np.maximum(1 - pf * pf, 0.0)) / pf
            # the read at each minute finds the line side dead from the trip until the utility is back
            live = brk == 1
            dip = 1 - np.abs(r.normal(0, 0.0015, M))
            v_min = v_avg * dip
            for m in trip_m:
                v_min[m] = 0.0                                # the sag, then nothing, inside the trip's minute
            v_min = np.where(dead_s >= 60, 0.0, v_min)
            for m in range(M):
                if 0 < dead_s[m] < 60 and m not in trip_m:
                    v_min[m] = 0.0                            # the retransfer's minute began without the utility
            out[b] = {"v_ab": np.where(live, ph[0], 0.0), "v_bc": np.where(live, ph[1], 0.0), "v_ca": np.where(live, ph[2], 0.0),
                      "v_min": v_min, "a_a": amps_ph[0], "a_b": amps_ph[1], "a_c": amps_ph[2], "kw10": kw10[b],
                      "kvar": kvar, "pf": np.where(kw > 0, pf, 0.0), "hz": np.where(live, hz_u, 0.0),
                      "thd": np.where(live, thd, 0.0), "brk": brk.copy(), "dead_s": dead_s}
        return out

    # ----------------------------------------------------------------- ride-through
    def ride_through(self, dev: dict[str, dict]) -> dict[str, Any]:
        """Per minute: the shortest runtime among the IT UPSs carrying load (site and per hall), and among the
        mechanical UPSs, with the UPS that sets it. From the UPSs' published runtime and output fields."""
        floor = int(round(self.cfg["ride_through"]["min_load_kw"] * 10))
        ups = sorted(d for d, x in dev.items() if x["family"] == "ups")
        it = [u for u in ups if dev[u]["kind"] == "it"]
        mech = [u for u in ups if dev[u]["kind"] == "mech"]
        halls = sorted({dev[u]["hall"] for u in it})

        def least(ids: list[str], need_load: bool) -> tuple[np.ndarray, np.ndarray]:
            big = np.iinfo(np.int64).max
            rt = np.stack([np.where(dev[u]["fields"]["out_kw"] >= floor, dev[u]["fields"]["runtime_s"], big) if need_load
                           else dev[u]["fields"]["runtime_s"] for u in ids])
            k = np.argmin(rt, axis=0)
            v = rt[k, np.arange(self.M)]
            return np.where(v == big, -1, v), np.where(v == big, -1, k)
        scopes = {"SITE-IT": (it, True), "SITE-COOLING": (mech, False)}
        for h in halls:
            scopes[h] = ([u for u in it if dev[u]["hall"] == h], True)
        out = {}
        for s, (ids, need) in scopes.items():
            v, k = least(ids, need)
            out[s] = {"ups": ids, "s": v.astype(np.int64), "k": k.astype(np.int64)}
        return out

    def run(self) -> dict[str, Any]:
        dev = device_fields(self.pout)
        return {"mains": self.series(), "ride": self.ride_through(dev),
                "outages": [{k: iso(v) if isinstance(v, datetime) else v for k, v in o.items() if k != "events"} for o in self.power.outages()]}


# --------------------------------------------------------------------- publish
def main_fields(out: dict[str, Any], cfg: dict[str, Any]) -> dict[str, dict[str, np.ndarray]]:
    """Every main's one-minute integer series (value x the field's scale)."""
    scale = {f["key"]: f["scale"] for f in cfg["fields"]}
    res = {}
    for b, x in out["mains"].items():
        f = {}
        for key in scale:
            a = x["kw10"] if key == "kw" else x[key]
            f[key] = a.astype(np.int64) if key in ("kw", "brk") else np.round(np.asarray(a, dtype=np.float64) * scale[key]).astype(np.int64)
        res[b] = f
    return res


def hourly_rows(fields: dict[str, dict[str, np.ndarray]], out: dict[str, Any], start: datetime, M: int) -> tuple[list[dict], list[dict]]:
    H = M // HOUR_MIN
    sh = (H, HOUR_MIN)
    hours = [iso(start + h * HOUR_MIN * MIN) for h in range(H)]
    mains = []
    for b, f in fields.items():
        kw = f["kw"].reshape(sh)
        amax = np.maximum(np.maximum(f["a_a"], f["a_b"]), f["a_c"]).reshape(sh)
        vavg = ((f["v_ab"] + f["v_bc"] + f["v_ca"]) / 3).reshape(sh)
        vmin = f["v_min"].reshape(sh)
        live = (f["brk"] == 1).reshape(sh)
        dead = (out["mains"][b]["dead_s"] >= 60).reshape(sh)
        pf, hz, thd = f["pf"].reshape(sh), f["hz"].reshape(sh), f["thd"].reshape(sh)
        for h in range(H):
            lv = live[h]
            mains.append({"hour": hours[h], "main": b, "kwh": round(int(kw[h].sum()) / 600, 2), "kw_avg": round(int(kw[h].sum()) / 600, 1),
                          "kw_max": round(int(kw[h].max()) / 10, 1), "amps_max": round(int(amax[h].max()) / 10, 1),
                          "v_avg": round(float(vavg[h][lv].mean()), 0) if lv.any() else 0, "v_min": int(vmin[h].min()),
                          "v_max": int(max(f["v_ab"].reshape(sh)[h].max(), f["v_bc"].reshape(sh)[h].max(), f["v_ca"].reshape(sh)[h].max())),
                          "dead_min": int(dead[h].sum()),
                          "pf_avg": round(float(pf[h][kw[h] > 0].mean()) / 1000, 3) if (kw[h] > 0).any() else 0,
                          "hz_min": round(int(hz[h][lv].min()) / 100, 2) if lv.any() else 0, "hz_max": round(int(hz[h].max()) / 100, 2),
                          "thd_max": round(int(thd[h].max()) / 100, 2)})
    ride = []
    for h in range(H):
        for s, x in out["ride"].items():
            v, k = x["s"].reshape(sh)[h], x["k"].reshape(sh)[h]
            ok = v >= 0
            if not ok.any():
                ride.append({"hour": hours[h], "scope": s, "min_s": "", "ups": "", "avg_s": ""})
                continue
            i = int(np.argmin(np.where(ok, v, np.iinfo(np.int64).max)))
            ride.append({"hour": hours[h], "scope": s, "min_s": int(v[i]), "ups": x["ups"][int(k[i])],
                         "avg_s": int(round(float(v[ok].mean())))})
    return mains, ride


def _windows(fields: dict[str, dict[str, np.ndarray]], out: dict[str, Any], start: datetime, M: int, before: int, after: int) -> list[dict]:
    """One-minute windows on each main around every breaker change (trip and retransfer, merged where they overlap)."""
    res = []
    for b, f in fields.items():
        ch = [m for m in range(1, M) if f["brk"][m] != f["brk"][m - 1]] + [m for m in range(M) if 0 < out["mains"][b]["dead_s"][m] < 60]
        merged: list[list[int]] = []
        for a, z in sorted((max(0, m - before), min(M, m + after)) for m in ch):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], z)
            else:
                merged.append([a, z])
        for a, z in merged:
            res.append({"device": b, "family": "main", "from": iso(start + a * MIN), "minutes": z - a, "m0": a,
                        "fields": {k: v[a:z].tolist() for k, v in f.items()}})
    return res


def write_utility(layer: UtilityTelemetry, out: dict[str, Any], dest: str | Path, source: str = "",
                  minutes_dest: str | Path | None = None) -> dict[str, Any]:
    """Write the committed tiers to dest and the publish-time tier to minutes_dest if given."""
    cfg = layer.cfg
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    win = dest / "windows"
    if win.exists():
        for p in win.glob("*.json"):
            p.unlink()
    win.mkdir(exist_ok=True)
    fields = main_fields(out, cfg)
    mains, ride = hourly_rows(fields, out, layer.start, layer.M)
    (dest / "mains_hourly.csv").write_text(_csv(mains, MAINS_HOURLY), encoding="utf-8", newline="\n")
    (dest / "ride_through_hourly.csv").write_text(_csv(ride, RIDE_HOURLY), encoding="utf-8", newline="\n")
    index = []
    for w in _windows(fields, out, layer.start, layer.M, cfg["tiers"]["window_before_min"], cfg["tiers"]["window_after_min"]):
        name = f"{w['device']}_{w['from'][:16].replace('-', '').replace(':', '')}"
        (win / f"{name}.json").write_text(_dump(w), encoding="utf-8", newline="\n")
        index.append({"file": f"windows/{name}.json", "device": w["device"], "from": w["from"], "minutes": w["minutes"]})
    enc = "first value, then minute-to-minute steps; [n] is n minutes unchanged; divide by the field's scale"
    minutes = {f"{b}.json": _dump({"device": b, "start": iso(layer.start), "minutes": layer.M, "encoding": enc,
                                   "fields": {k: pack(v) for k, v in f.items()}}) for b, f in fields.items()}
    minutes["ride_through.json"] = _dump({"start": iso(layer.start), "minutes": layer.M, "encoding": enc + " (seconds; -1 when no UPS in scope carries load)",
                                          "scopes": {s: {"ups": x["ups"], "s": pack(x["s"]), "k": pack(x["k"])} for s, x in out["ride"].items()}})
    if minutes_dest is not None:
        md = Path(minutes_dest)
        md.mkdir(parents=True, exist_ok=True)
        for name, text in minutes.items():
            (md / name).write_text(text, encoding="utf-8", newline="\n")
    # each outage: how long the UPSs bridged, and the ride-through they had when it began
    outs = []
    for o in out["outages"]:
        m = layer.power.floor_m(datetime.fromisoformat(o["trip"].replace("Z", "+00:00")))
        bridge = (datetime.fromisoformat(o["ties_closed"].replace("Z", "+00:00")) - datetime.fromisoformat(o["trip"].replace("Z", "+00:00"))).total_seconds()
        outs.append({**o, "bridge_s": int(round(bridge)), "ride_it_s": int(out["ride"]["SITE-IT"]["s"][m]),
                     "ride_cooling_s": int(out["ride"]["SITE-COOLING"]["s"][m])})
    man = {"disclaimer": "Synthetic utility metering for a portfolio demonstration, under PowerLogic ION measurement labels. "
                         "All names and readings are fictional.",
           "source": source, "window": {"start": iso(layer.start), "end": iso(layer.end)},
           "mains": {b: {"bus": x["bus"], "breaker": x["breaker"],
                         "ups": sorted(u for u in layer.pout["ups"] if bus_of(u, cfg) == b)} for b, x in cfg["mains"].items()},
           "scopes": {s: x["ups"] for s, x in out["ride"].items()}, "outages": outs,
           "files": {"mains_hourly.csv": len(mains), "ride_through_hourly.csv": len(ride), "windows": len(index)},
           "windows": index,
           "minutes": {name: {"sha256": hashlib.sha256(t.encode()).hexdigest(), "bytes": len(t.encode())} for name, t in minutes.items()}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
