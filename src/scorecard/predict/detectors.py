"""The detectors. Each takes plain rows (the input contract in docs/predict/README.md) and a config
section (``config/predict.yaml`` ``detectors``), and says per device: healthy, watch, or act.

"Act" is the state that raises a proposed work request. Every result carries the evidence that
produced it (the level, the trend, the projected date) so a person can check it by hand.

Standard library only, except ``gpu_memory``, which reuses the GPU Health tab's early-warning rule.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any

from .methods import cusum_step, days_to_level, robust_sigma, theil_sen

UTC = timezone.utc
DAY = timedelta(days=1)
RANK = {"healthy": 0, "watch": 1, "act": 2}


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Optics: each module's daily DOM, trended toward its warning threshold
# --------------------------------------------------------------------------- #
def _param_states(v: list[float], lim: dict, c: dict) -> list[dict]:
    """Days a module's reading is far from its own baseline AND trending steadily toward the warning."""
    bad = 1 if lim["bad"] == "high" else -1
    base = v[:c["baseline_days"]]
    if len(base) < 5:
        return []
    # Scatter from day-to-day differences, so a module already drifting when the data starts still gets an honest one.
    med = median(base)
    sig = max(c["sigma_floor"], robust_sigma([b - a for a, b in zip(base, base[1:])]) / 2 ** 0.5)
    T, out = c["trend_days"], []
    for i in range(T - 1, len(v)):
        w = v[i - T + 1: i + 1]
        moved = bad * (w[-1] - w[0])
        if (i < len(base) or bad * (v[i] - med) < c["screen_sigma"] * sig) and moved < c["screen_sigma"] * sig:
            continue                                   # the cheap screen: nothing unusual today
        steps = [bad * (b - a) for a, b in zip(w, w[1:])]
        if sum(1 for x in steps if x > 0) < c["trend_consistent"] or moved <= 0 or max(steps) > c["max_step_share"] * moved:
            continue                                   # a step, a dip, or noise: not a steady trend
        slope, icpt = theil_sen(list(range(T)), w)
        now = icpt + slope * (T - 1)
        d = days_to_level(now, slope, lim["warn"], bad)
        if d is None:
            continue
        state = "act" if d <= c["act_days"] else "watch" if d <= c["watch_days"] else None
        if state:
            out.append({"i": i, "state": state, "level": round(now, 2), "slope": round(slope, 3), "days_to_warn": round(d, 1)})
    return out


def optics(modules: list[dict[str, Any]], c: dict[str, Any]) -> list[dict[str, Any]]:
    """Modules wearing out toward a DOM warning, named by the end that is failing.

    ``modules``: one per module, with ``serial``, ``location``, ``peer`` (the far end's location),
    ``first_day`` (YYYY-MM-DD), and daily lists ``bias_ma``, ``tx_dbm``, ``rx_dbm``. A receive-power
    trend whose far end's transmit power trends at the same time belongs to the far end's module.
    """
    found: dict[str, dict[str, list[dict]]] = {}
    days: dict[str, tuple[int, int]] = {}
    for m in modules:
        d0 = date.fromisoformat(m["first_day"]).toordinal()
        days[m["serial"]] = (d0, d0 + len(m["rx_dbm"]) - 1)
        for p, lim in c["limits"].items():
            st = _param_states(m[p], lim, c)
            if st:
                for s in st:
                    s["day"] = d0 + s["i"]
                found.setdefault(m["serial"], {})[p] = st
    at_loc: dict[str, list[dict]] = {}
    for m in modules:
        at_loc.setdefault(m["location"], []).append(m)

    def peer_tx_trending(m: dict, day: int) -> bool:
        for pm in at_loc.get(m["peer"], []):
            for s in found.get(pm["serial"], {}).get("tx_dbm", []):
                if abs(s["day"] - day) <= 3:
                    return True
        return False

    out = []
    for m in modules:
        f = found.get(m["serial"])
        if not f:
            continue
        states = [dict(s, param=p) for p, ss in f.items() for s in ss
                  if not (p == "rx_dbm" and peer_tx_trending(m, s["day"]))]
        if not states:
            continue
        states.sort(key=lambda s: (s["day"], -RANK[s["state"]]))
        first_act = next((s for s in states if s["state"] == "act"), None)
        first_watch = states[0]
        last = days[m["serial"]][1]
        now = max((s for s in states if s["day"] == last), key=lambda s: RANK[s["state"]], default=None)

        def when(s: dict | None) -> dict | None:
            if not s:
                return None
            d = date.fromordinal(s["day"])
            return {"day": d.isoformat(), "flagged": iso(datetime(d.year, d.month, d.day, tzinfo=UTC) + DAY), "param": s["param"],
                    "level": s["level"], "slope_per_day": s["slope"], "days_to_warn": s["days_to_warn"],
                    "warn_by": (d + timedelta(days=round(s["days_to_warn"]))).isoformat(), "state": s["state"]}
        out.append({"serial": m["serial"], "location": m["location"], "peer": m["peer"], "first_watch": when(first_watch),
                    "first_act": when(first_act), "now": now["state"] if now else "healthy",
                    "last_day": date.fromordinal(last).isoformat()})
    return out


# --------------------------------------------------------------------------- #
# GPU memory: the GPU Health tab's early-warning rule, reused as is
# --------------------------------------------------------------------------- #
class _Counters:
    def __init__(self, counters: list[dict], watches: list[dict]):
        self.counters, self.watches = counters, watches


def gpu_memory(counters: list[dict[str, Any]], xids: list[dict[str, Any]], gpu_health_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """``counters``: daily rows (date, host, tray_serial, gpu, sbe_day, uce_day, remapped_rows, remap_pending).
    ``xids``: uncorrectable memory XIDs (xid, host, tray_serial, gpu, opened), used only to report what followed.

    The rule flags a GPU once. Over months a GPU that was reset or reseated can wear toward a second
    failure, so the rule runs once per episode: each GPU's days are split after every day with an
    uncorrectable error, and each piece is judged on its own.
    """
    from scorecard.gpu_health import early_warning
    by: dict[tuple, list[dict]] = {}
    for r in counters:
        by.setdefault((r["host"], r["tray_serial"], r["gpu"]), []).append(r)
    pieces: list[tuple[str, str, list[dict]]] = []          # (after, until, rows): dates bounding each episode
    for rows in by.values():
        rows.sort(key=lambda r: r["date"])
        cuts = [r["date"] for r in rows if r["uce_day"]]
        lo = ""
        for c in cuts + ["9999-12-31"]:
            part = [r for r in rows if lo < r["date"] <= c]
            if part:
                pieces.append((lo, c, part))
            lo = c
    out = []
    for lo, hi, part in pieces:
        key = (part[0]["host"], part[0]["tray_serial"], part[0]["gpu"])
        mine = [w for w in xids if (w["host"], w["tray_serial"], w["gpu"]) == key and lo < w["opened"][:10] <= hi]
        out += early_warning(_Counters(part, mine), gpu_health_cfg)
    return sorted(out, key=lambda f: (f["flagged"], f["host"], f["gpu"]))


# --------------------------------------------------------------------------- #
# CDU filter: pressure drop at design flow, trended to the change limit
# --------------------------------------------------------------------------- #
def _period(rows: list[dict]) -> timedelta:
    ts = sorted({parse(r["timestamp"]) for r in rows})
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    return min(gaps) if gaps else timedelta(hours=1)


def cdu_filter(readings: list[dict[str, Any]], c: dict[str, Any], last_change: dict[str, str] | None = None) -> dict[str, dict]:
    """Per CDU, evaluated at the end of each day: the filter's pressure drop corrected to design flow, its
    trend since the last change, the day it reaches the change limit, and whether that comes before the
    next scheduled change.

    ``readings``: rows with ``timestamp`` (start of the averaging period), ``cdu``, ``flow_lpm``,
    ``filter_dp_kpa``. ``last_change``: the last recorded filter change per CDU before the first reading
    (from the PM records), if known; changes inside the data are found from the pressure drop itself.
    """
    out = {}
    by: dict[str, list[dict]] = {}
    for r in readings:
        by.setdefault(r["cdu"], []).append(r)
    for cdu, rows in sorted(by.items()):
        rows.sort(key=lambda r: r["timestamp"])
        per = _period(rows)
        pts = []
        for r in rows:
            q = float(r["flow_lpm"]) / c["design_flow_lpm"]
            if q > 0.3:
                pts.append((parse(r["timestamp"]) + per, float(r["filter_dp_kpa"]) / (q * q)))
        changes = [parse(last_change[cdu])] if last_change and last_change.get(cdu) else []
        for (t0, a), (t1, b) in zip(pts, pts[1:]):
            if a - b >= c["step_kpa"] and not (changes and t1 - changes[-1] <= DAY):
                changes.append(t1 - per / 2)   # a change inside an averaging period can show as two drops: one change
        evals, first_act, first_watch, acts = [], None, None, []
        day = pts[0][0].replace(hour=0, minute=0, second=0) + DAY
        while day <= pts[-1][0]:
            since = max([x for x in changes if x <= day], default=None)
            win = [(t, v) for t, v in pts if t <= day and t > day - c["trend_days"] * DAY and (since is None or t > since)]
            ev = {"date": (day - DAY).date().isoformat(), "level": None, "slope_per_day": None, "limit_on": None,
                  "next_change": None, "state": "healthy", "since_change_days": round((day - since).total_seconds() / 86400, 1) if since else None}
            if win:
                ev["level"] = round(win[-1][1], 2)
            nxt = since + timedelta(days=c["service_days"]) if since else None
            ev["next_change"] = nxt.date().isoformat() if nxt else None
            enough = len(win) >= 3 and (since is None or (day - since) >= c["min_days"] * DAY)
            if enough:
                xs = [(t - day).total_seconds() / 86400 for t, _ in win]
                slope, icpt = theil_sen(xs, [v for _, v in win])
                d = days_to_level(icpt, slope, c["change_kpa"], 1)
                ev.update(level=round(icpt, 2), slope_per_day=round(slope, 3))
                if d is not None:
                    on = day + timedelta(days=d)
                    ev["limit_on"] = on.date().isoformat()
                    before_change = nxt is None or on < nxt or nxt <= day
                    if d == 0:
                        ev["state"] = "act"
                    elif before_change and d <= c["act_days"]:
                        ev["state"] = "act"
                    elif before_change and (nxt is not None and nxt > day or d <= 2 * c["act_days"]):
                        ev["state"] = "watch"
            if ev["state"] == "act" and not (acts and acts[-1]["_since"] == since):
                acts.append(dict(ev, flagged=iso(day), _since=since))
            if ev["state"] == "act" and not first_act:
                first_act = dict(ev, flagged=iso(day))
            if ev["state"] != "healthy" and not first_watch:
                first_watch = dict(ev, flagged=iso(day))
            evals.append(ev)
            day += DAY
        out[cdu] = {"cdu": cdu, "days": evals, "changes": [iso(x) for x in changes], "first_act": first_act,
                    "first_watch": first_watch, "acts": [{k: v for k, v in a.items() if k != "_since"} for a in acts],
                    "now": evals[-1] if evals else None}
    return out


# --------------------------------------------------------------------------- #
# CDU pumps: speed needed for the flow, against the pump's own baseline
# --------------------------------------------------------------------------- #
def cdu_pump(readings: list[dict[str, Any]], events: list[dict[str, Any]], c: dict[str, Any]) -> dict[str, dict]:
    """Per pump: a pump that wears needs more speed for the same flow. The expected speed is the pump's own
    speed-for-flow from its first days on duty (reset when it is replaced); a one-sided CUSUM on the
    residual raises a watch, and a residual past ``act_pct`` a work request.

    ``readings``: rows with ``timestamp``, ``cdu``, ``flow_lpm``, ``pump1_pct``, ``pump2_pct`` (averages).
    ``events``: Redfish pump events (``resource`` .../Pumps/n, ``property`` Status.Health, ``value``);
    a pump whose health returns to OK after Critical was repaired or replaced, so its baseline restarts.
    """
    out = {}
    by: dict[str, list[dict]] = {}
    for r in readings:
        by.setdefault(r["cdu"], []).append(r)
    for cdu, rows in sorted(by.items()):
        rows.sort(key=lambda r: r["timestamp"])
        per = _period(rows)
        for pump in (1, 2):
            res = f"/Pumps/{pump}"
            evs = sorted((e for e in events if e.get("cdu") == cdu and e["resource"].endswith(res) and e["property"] == "Status.Health"),
                         key=lambda e: e["timestamp"])
            failures = [e["timestamp"] for e in evs if e["value"] == "Critical"]
            resets = [parse(b["timestamp"]) for a, b in zip(evs, evs[1:]) if a["value"] == "Critical" and b["value"] == "OK"]
            other = f"pump{3 - pump}_pct"
            base: list[tuple[datetime, float]] = []
            b0 = sig = None
            s = 0.0
            pts, first_act, first_watch, acts, acted, seg = [], None, None, [], False, []
            seg_start = parse(rows[0]["timestamp"])
            for r in rows:
                t = parse(r["timestamp"])
                if any(seg_start < x <= t for x in resets):
                    seg_start, base, b0, sig, s, acted, seg = t, [], None, None, 0.0, False, []   # a new pump: learn it again
                sp, q = float(r[f"pump{pump}_pct"]), float(r["flow_lpm"]) / c["design_flow_lpm"]
                if sp < c["min_running_pct"] or float(r[other]) > 0 or q < 0.3:
                    continue                               # standby, a rotation or a test inside the period
                if b0 is None:
                    base.append((t, sp / q))
                    if (t - base[0][0]) >= c["baseline_days"] * DAY and len(base) >= c["min_baseline_readings"]:
                        b0 = median(v for _, v in base)
                        sig = robust_sigma([(v / b0 - 1) * 100 for _, v in base], 0.05)
                    continue
                resid = (sp / (b0 * q) - 1) * 100
                s = cusum_step(s, resid, c["cusum_k_sigma"] * sig)
                recent = [p["residual_pct"] for p in seg[-2:]] + [resid]
                state = "act" if median(recent) >= c["act_pct"] else "watch" if s > c["cusum_h_sigma"] * sig else "healthy"
                p = {"t": iso(t + per), "speed_pct": sp, "expected_pct": round(b0 * q, 2), "residual_pct": round(resid, 2),
                     "cusum": round(s, 2), "state": state}
                pts.append(p)
                seg.append(p)
                if state == "act" and not acted:
                    acts.append(p)
                    acted = True
                if state == "act" and not first_act:
                    first_act = p
                if state != "healthy" and not first_watch:
                    first_watch = p
            out[f"{cdu}/{pump}"] = {"cdu": cdu, "pump": pump, "points": pts, "failures": failures, "replaced": [iso(x) for x in resets],
                                    "baseline_pct_at_design": round(b0, 2) if b0 else None, "first_act": first_act, "first_watch": first_watch, "acts": acts,
                                    "now": pts[-1]["state"] if pts else "healthy"}
    return out
