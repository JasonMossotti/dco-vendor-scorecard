#!/usr/bin/env python3
"""Render the predictive maintenance review: reports/predictive_maintenance.md and the page data.

Usage:
    python scripts/render_predict.py                    # write reports/predictive_maintenance.md
    python scripts/render_predict.py --check            # fail if the report is stale (CI)
    python scripts/render_predict.py --robustness 60    # score the detectors on 60 generated histories

The page is the Predictive view of the Failure Pattern Review (scripts/render_patterns.py calls ``prepare``).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard.predict import review as R  # noqa: E402

OUT = ROOT / "reports" / "predictive_maintenance.md"
PAGE = "https://jasonmossotti.github.io/dco-vendor-scorecard/patterns/#predict"
NAMES = {"optics": "Optics (DOM trend)", "gpu_memory": "GPU memory (corrected errors and remaps)",
         "cdu_filter": "CDU filter (pressure drop to the change limit)", "cdu_pump": "CDU pumps (speed for the flow)"}
FAILS = {"optics": "module failures (the module's own DOM alarm)", "gpu_memory": "uncorrectable memory XIDs",
         "cdu_filter": "times a filter reached its change limit", "cdu_pump": "pump failures (Redfish health Critical)"}


def day(iso: str, year: bool = False) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")) if "T" in iso else datetime.fromisoformat(iso)
    return f"{t:%b} {t.day}, {t.year}" if year else f"{t:%b} {t.day}"


def _examples(bt: dict, pdir: Path, cfg: dict) -> list[dict]:
    """A few modules to draw: one warned failure per alarm type (the one nearest the median lead), one sudden
    failure, and one link that stepped down and was rightly left alone."""
    mods = {m["serial"]: m for m in R.modules(pdir)}
    key = json.loads((pdir / "answer_key.json").read_text(encoding="utf-8"))
    lim = cfg["detectors"]["optics"]["limits"]
    res = {f["serial"]: f for f in bt["results"]["optics"]}
    out = []
    warned = [r for r in bt["optics"]["failures"] if r["warned"]]
    for alarm in ("TX bias high", "TX power low", "RX power low"):
        rows = [r for r in warned if r["alarm"] == alarm]
        if not rows:
            continue
        mid = median(r["lead_h"] for r in rows)
        r = min(rows, key=lambda r: (abs(r["lead_h"] - mid), r["serial"]))
        p = res[r["serial"]]["first_act"]["param"]
        out.append({"kind": "warned", "serial": r["serial"], "location": r["location"], "alarm": alarm, "alarm_at": r["at"],
                    "param": p, "act": res[r["serial"]]["first_act"], "lead_h": r["lead_h"]})
    sudden = [r for r in bt["optics"]["failures"] if not r["warned"] and not r["too_early"]]
    if sudden:
        r = sorted(sudden, key=lambda r: r["at"])[len(sudden) // 2]
        p = {"TX bias high": "bias_ma", "TX power low": "tx_dbm", "RX power low": "rx_dbm"}[r["alarm"]]
        out.append({"kind": "sudden", "serial": r["serial"], "location": r["location"], "alarm": r["alarm"], "alarm_at": r["at"],
                    "param": p, "act": None, "lead_h": None})
    steps = key["optics"]["step_decoys"]
    if steps:
        loc = steps[0]["link"][1]
        m = next(m for m in mods.values() if m["location"] == loc and m["first_day"] <= steps[0]["from_day"])
        out.append({"kind": "step", "serial": m["serial"], "location": loc, "alarm": None, "alarm_at": None, "param": "rx_dbm",
                    "act": None, "lead_h": None, "step_from": steps[0]["from_day"]})
    for e in out:
        m = mods[e["serial"]]
        e.update(first_day=m["first_day"], values=m[e["param"]], warn=lim[e["param"]]["warn"], alarm_level=lim[e["param"]]["alarm"],
                 name=R.PARAM[e["param"]][0], unit=R.PARAM[e["param"]][1])
    return out


def _gpu_example(bt: dict) -> dict | None:
    flags = [f for f in bt["results"]["gpu_memory"] if f["xid_after"] and not f["xid_before"]]
    if not flags:
        return None
    mid = median(f["xid_after"]["lead_h"] for f in flags)
    f = min(flags, key=lambda f: (abs(f["xid_after"]["lead_h"] - mid), f["host"], f["gpu"]))
    return {"host": f["host"], "gpu": f["gpu"], "flagged": f["flagged"], "why": f["why"], "xid_after": f["xid_after"], "series": f["series"]}


def prepare(pdir: Path = R.PREDICT, hdir: Path = R.HISTORY) -> dict:
    cfg = R.config()
    bt = R.backtest(pdir, hdir, cfg)
    s = R.summary(bt, cfg)
    w = bt["window"]
    last = (datetime.fromisoformat(w["end"].replace("Z", "+00:00")) - timedelta(days=1)).isoformat()
    det = cfg["detectors"]
    filt = bt["results"]["cdu_filter"]
    pumps = bt["results"]["cdu_pump"]
    failed_pumps = [k for k, v in pumps.items() if v["failures"]]
    f = {
        "window": w, "window_txt": f"{day(w['start'], year=True)} to {day(last, year=True)}",
        "summary": s, "names": NAMES, "fails": FAILS,
        "owners": {k: R.raci(v) for k, v in cfg["work_requests"]["raci"].items()},
        "limits": {"optics": det["optics"]["limits"], "change_kpa": det["cdu_filter"]["change_kpa"], "act_pct": det["cdu_pump"]["act_pct"],
                   "service_days": det["cdu_filter"]["service_days"], "trend_days": det["optics"]["trend_days"],
                   "act_days_optics": det["optics"]["act_days"], "act_days_filter": det["cdu_filter"]["act_days"],
                   "cusum_h": det["cdu_pump"]["cusum_h_sigma"]},
        "requests": [{k: v for k, v in r.items()} for r in bt["requests"]],
        "filter_chart": {"start": w["start"][:10], "cdus": {k: [d["level"] for d in v["days"]] for k, v in filt.items()},
                         "changes": {k: v["changes"] for k, v in filt.items()},
                         "acts": {k: v["acts"] for k, v in filt.items() if v["acts"]},
                         "crossings": bt["cdu_filter"]["crossings"]},
        "pump_charts": [{"key": k, "cdu": pumps[k]["cdu"], "pump": pumps[k]["pump"], "failures": pumps[k]["failures"],
                         "replaced": pumps[k]["replaced"], "acts": pumps[k]["acts"],
                         "points": [{"t": p["t"], "r": p["residual_pct"], "s": p["state"]} for p in pumps[k]["points"]],
                         "warned": next((r["warned"] for r in bt["cdu_pump"]["failures"] if (r["cdu"], r["pump"]) == (pumps[k]["cdu"], pumps[k]["pump"])), False)}
                        for k in failed_pumps],
        "optic_examples": _examples(bt, pdir, cfg),
        "gpu_example": _gpu_example(bt),
        "now": R.now(),
        "fleet": R.fleet(hdir),
    }
    f["now"]["as_of_txt"] = day(f["now"]["as_of"], year=True)
    return f


def owner_txt(o: dict) -> str:
    return o["accountable"] if o["accountable"] == o["responsible"] else f"{o['responsible']} (does the work), {o['accountable']} (accountable)"


def _table(head: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]


def _pct(a: int, b: int) -> str:
    return f"{round(100 * a / b)}%" if b else "n/a"


def markdown(f: dict) -> str:
    s, n, fl, lim = f["summary"], f["now"], f["fleet"], f["limits"]
    L = ["<!-- GENERATED by scripts/render_predict.py from data/predict/, data/history/, and the sample month. Do not edit by hand. -->", "",
         "# Predictive Maintenance Review", "",
         f"**Site AUS-1 (fictional), Hall A.** Backtest over the condition history, {f['window_txt']} (26 weeks), and the sample month as of "
         f"{n['as_of_txt']}. Interactive version: [Predictive view of the Failure Pattern Review]({PAGE}).", "",
         "> A prediction is a forecast that proposes work. It is not a finding and changes no SLA result. The backtest runs the detectors over "
         "the history as if they had been running then; nobody acted on the warnings, so every failure in the records still happens.", "",
         "## Backtest", ""]
    rows = []
    for k in ("optics", "gpu_memory", "cdu_filter", "cdu_pump"):
        x = s[k]
        base = x.get("scored", x["failures"])
        rows.append([NAMES[k], f"{x['warned']} of {base} {FAILS[k]}" + (f" ({x['too_early']} more in the first {lim['trend_days']} days of data, too early to judge)" if x.get("too_early") else ""),
                     _pct(x["warned"], base), x["lead_rule"], f"{x['median_lead_days']} days" if x["median_lead_days"] is not None else "n/a",
                     x["false_alarms"], owner_txt(f["owners"][k])])
    L += _table(["Detector", "Warned in time", "Share", "Lead needed", "Median lead", "False alarms", "Owner (Interface Agreement RACI)"], rows)
    L += ["", f"Failures the detectors did not warn of gave no sign in the readings they watch (a module that fails at once, a pump that stops "
              f"without wearing first); nothing in the data could have predicted them. {s['gpu_memory']['after_the_fact']} GPU memory flags came "
              f"after the XID they follow and are not counted as warnings.", "",
          "## Now (as of the sample month's last day)", "", f"### CDU filters ({n['as_of_txt']})", ""]
    L += _table(["CDU", "Pressure drop at design flow", "Rising", f"Reaches {lim['change_kpa']:g} kPa", "Since last change", "Next scheduled change", "State"],
                [[x["cdu"], f"{x['level']:.1f} kPa", f"{x['slope_per_day']:.2f} kPa a day", day(x["limit_on"], year=True) if x["limit_on"] else "not rising",
                  f"{x['since_change_days']:.0f} days" if x["since_change_days"] is not None else "no change on record",
                  (day(x["next_change"], year=True) + (" (overdue by the schedule)" if x["overdue"] else "")) if x["next_change"] else "not on record",
                  x["state"]] for x in n["cdu_filter"]])
    fails = [x for x in n["cdu_pump"] if x["failures"]]
    L += ["", "### CDU pumps", "",
          f"{sum(1 for x in n['cdu_pump'] if x['state'] == 'healthy')} of {len(n['cdu_pump'])} pumps healthy; no pump drifted from its own speed-for-flow. "
          + " ".join(f"{x['cdu']} pump {x['pump']} failed {day(x['failures'][0])} with no drift before it (a sudden failure)." for x in fails), "",
          "### GPU memory (the GPU Health tab's early-warning rule)", ""]
    watch = [g for g in n["gpu_memory"] if not g["xid_before"] and not g["xid_after"]]
    L += [("GPUs on the watch list (remaps rising, no uncorrectable error yet): " + ", ".join(f"{g['host']} GPU {g['gpu']} (flagged {day(g['flagged'])}, {g['remapped_rows']} remapped rows)" for g in watch) + ".")
          if watch else "No GPU on the watch list.", "",
          "### Optics", "", "The sample month's network layer keeps DOM readings only in the minute windows around events, so there is no daily "
          "series to trend. A live deployment polls each module's DOM daily (docs/predict/README.md).", "",
          f"## Fleet outlook (next {fl['horizon_days']} days)", ""]
    o, g = fl["optics"], fl["gpu_memory"]
    L += _table(["Part", "Model", "Expected failures", "Range (90%)", "Shelf minimum per hall (IT Partner SLA)"],
                [["800G OSFP optic", f"Weibull fit on {o['fit']['units']:,} modules, {o['fit']['failures']} failures: shape {o['fit']['beta']:g} "
                  f"({'about 1: failures random in time at this age' if 0.85 <= o['fit']['beta'] <= 1.2 else 'wear-out' if o['fit']['beta'] > 1.2 else 'early life'})",
                  o["expected"], f"{o['range'][0]} to {o['range'][1]}", o["shelf_minimum"]],
                 ["Compute tray (GPU memory)", f"{g['failures']} uncorrectable memory XIDs on {g['gpus']:,} GPUs in {g['days']} days "
                  f"({g['per_1000_gpu_months']:g} per 1,000 GPU-months); {g['swap_share_pct']}% of them ended in a tray replacement",
                  f"{g['expected']} XIDs, {g['expected_swaps']} tray replacements", f"{g['range'][0]} to {g['range'][1]} XIDs", g["shelf_minimum"]]])
    L += ["", "Optic failure rate by lot (the Failure Pattern Review's lot pattern, as an outlook):", ""]
    L += _table(["Lot", "Installed now", "Failures", "Per module-year", f"Expected in {fl['horizon_days']} days"],
                [[x["lot"], x["installed_now"], x["failures"], f"{x['per_module_year']:g}", f"{x['expected']:g}"] for x in o["lots"]])
    L += ["", f"## Proposed work requests (backtest, {len(f['requests'])})", "",
          "What the detectors would have raised. Each goes to the party that does the work; nobody acted on them here.", ""]
    L += _table(["ID", "Raised", "Device", "Failure mode", "Evidence", "Due by", "Owner", "What happened"],
                [[r["id"], day(r["flagged"]), r["device"], r["mode"], r["evidence"], day(r["due_by"]), r["owner"]["responsible"], r["outcome"]] for r in f["requests"]])
    L += ["", "## Method", "",
          "- **Optics:** each module's daily worst-lane laser bias, transmit power, and receive power. A reading far from the module's own "
          f"baseline, moving steadily toward its warning threshold over {lim['trend_days']} days (a step or a one-day dip is not a trend), is projected "
          f"with a Theil-Sen slope; a warning reached within {lim['act_days_optics']} days raises a work request. A receive-power trend whose far end's "
          "transmit power is falling belongs to the far end's module.",
          "- **GPU memory:** the GPU Health tab's early-warning rule (remapped rows or corrected errors rising), run once per episode.",
          f"- **CDU filter:** pressure drop corrected to design flow (it scales with flow squared), trended since the last change; a work request "
          f"when it will reach {lim['change_kpa']:g} kPa (twice the clean pressure drop) before the next scheduled change ({lim['service_days']} days) and "
          f"within {lim['act_days_filter']} days.",
          f"- **CDU pumps:** speed against flow, compared with the pump's own first days on duty (relearned when it is replaced); a CUSUM on the "
          f"residual raises a watch, and {lim['act_pct']:g}% more speed than the flow needs raises a work request.",
          "- **Fleet outlook:** a Weibull fit of module lifetimes with censoring and left truncation; a Poisson rate for GPU memory failures.",
          "- Every threshold and its basis is in `config/predict.yaml`; each detector's inputs, limits, and blind spots are in `docs/predict/`.",
          "", "*Synthetic data for a portfolio demonstration; all names and events are fictional.*", ""]
    return "\n".join(L)


def robustness(n: int) -> int:
    from generate_history import generate as gen_history
    from generate_predict import generate as gen_predict
    from scorecard.synthetic.history import write_history
    from scorecard.synthetic.predict import write_predict
    cfg = R.config()
    tot: dict[str, dict[str, int]] = {}
    notes = []
    for seed in range(1, n + 1):
        with tempfile.TemporaryDirectory() as d:
            h, p = Path(d) / "history", Path(d) / "predict"
            write_history(gen_history(seed, vary=True), h)
            data = gen_predict(h, seed, vary=True)
            write_predict(data, p)
            s = R.score(R.backtest(p, h, cfg), data["streams"]["answer_key.json"], cfg)
        for k, v in s.items():
            t = tot.setdefault(k, {})
            for kk, vv in v.items():
                if isinstance(vv, list):
                    notes += [f"seed {seed}: {k} missed {x}" for x in vv]
                else:
                    t[kk] = t.get(kk, 0) + vv
        print(f"  seed {seed}: " + ", ".join(f"{k} {v['warned']}/{v['planted']} fa {v['false_alarms']}" for k, v in s.items()), flush=True)
    print(f"Predictive maintenance detectors on {n} generated histories (every planted wear-out moved each time):")
    for k, t in tot.items():
        extra = ", ".join(f"{kk.replace('_', ' ')} {vv}" for kk, vv in t.items() if kk not in ("planted", "warned"))
        print(f"  {k:<11} warned in time {t['warned']}/{t['planted']}; {extra}")
    for x in notes:
        print("  " + x)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, metavar="N")
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness)
    text = markdown(prepare())
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_predict.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
