#!/usr/bin/env python3
"""Render the PUE report: reports/pue_report.md and the Energy tab (/energy/).

PUE and partial PUE from the energy meters (data/energy/), checked against the Landlord's monthly
energy report and the chiller free-cooling log, under Landlord SLA section 22 (OT-EN-01 to 03).

Usage:
    python scripts/render_energy.py                    # write reports/pue_report.md
    python scripts/render_energy.py --check            # fail if it is stale (CI)
    python scripts/render_energy.py --robustness 60    # plant and find the cases in 60 generated months
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import energy as N  # noqa: E402
from scorecard import sitenav  # noqa: E402
from scorecard.synthetic import energy as E  # noqa: E402

OUT = ROOT / "reports" / "pue_report.md"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CAUSE = {"ups_input_as_it": "IT energy taken at the UPS inputs", "house_omitted": "house load left out",
         "generator_omitted": "generator energy left out", None: "no common cause matches"}


def day(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{MON[int(m) - 1]} {int(d)}, {y}"


def short(iso: str) -> str:
    _, m, d = iso[:10].split("-")
    return f"{MON[int(m) - 1]} {int(d)}"


def mwh(kwh: float) -> str:
    return f"{kwh / 1000:,.1f} MWh"


def prepare() -> dict:
    cfg = E.load_config()
    d = N.load()
    r = N.analyse(d, cfg)
    ev = N.evaluate(r, d.key) if d.key else None
    terms = N.energy_terms()
    keep = ("facility_kwh", "it_kwh", "cooling_kwh", "power_loss_kwh", "ups_loss_kwh", "unmetered_kwh", "other_kwh",
            "utility_kwh", "generator_kwh", "pue", "ppue_cooling", "ppue_power", "other_per_it", "outdoor_c")
    rnd = lambda x: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()}   # noqa: E731
    return {
        "standard": cfg["standard"], "tariff": cfg["tariff_usd_per_kwh"],
        "window": {"start": E.iso(d.start), "end": E.iso(d.end)},
        "month": rnd({k: r.month[k] for k in keep}),
        "weeks": [rnd({k: w[k] for k in ("start", "end") + keep}) for w in r.weeks],
        "days": [rnd({k: x[k] for k in ("date", "pue", "ppue_cooling", "ppue_power", "outdoor_c", "it_kwh", "facility_kwh",
                                        "generator_kwh")}) for x in r.days],
        "periods": [rnd(p) for p in r.periods],
        "year": rnd(r.year) if r.year else None,
        "kpi": rnd(r.kpi),
        "report": r.report,
        "variants": {k: {"facility_kwh": round(f, 1), "it_kwh": round(i, 1), "pue": round(f / i, 4)}
                     for k, (f, i) in N.report_variants(r.month).items()},
        "findings": [f.as_dict() for f in r.findings],
        "lockouts": [{k: v for k, v in sp.items() if k in ("chiller", "start", "end")} | {
            "note": sp["disabled_by"].get("note", ""), "hours": round((E.parse(sp["end"]) - E.parse(sp["start"])).total_seconds() / 3600, 1)}
            for sp in r.lockouts],
        "terms": [{k: t.get(k) for k in ("id", "name", "rule", "target")} for t in terms.values()],
        "check": {"planted": ev.planted, "detected": ev.detected, "false_positives": len(ev.false_positives),
                  "cause_named": ev.cause_named} if ev else None,
        "checks": cfg["checks"],
    }


def markdown(f: dict) -> str:
    m, y, k, rep = f["month"], f["year"], f["kpi"], f["report"]
    w = f["window"]
    L = ["<!--", "  GENERATED FILE. DO NOT EDIT BY HAND.",
         "  Source: data/energy/ (meters), sla/ot_partner.yaml (section 22)  |  Generator: scripts/render_energy.py",
         "-->", "", "# PUE Report: Site AUS-1", "",
         f"Sample month {day(w['start'])} to {day(E.iso(E.parse(w['end']) - timedelta(hours=1)))} (UTC). Synthetic meter data; "
         f"all names fictional. PUE per {f['standard']['name']}: total facility energy divided by IT energy, both as energy over "
         "the period; IT energy at the UPS outputs.", "",
         "## Summary", "",
         "| Measure | Value |", "|---|---|",
         f"| PUE, this month (metered) | {m['pue']:.3f} |",
         f"| PUE, Landlord's report | {rep['pue']:.3f} |",
         f"| PUE, 52 weeks ({k['id']}, target at most {k['target']:.2f}) | {k['actual']:.3f} ({'met' if k['met'] else 'not met'}) |",
         f"| Partial PUE, cooling | {m['ppue_cooling']:.3f} |",
         f"| Partial PUE, power path | {m['ppue_power']:.3f} |",
         f"| House load per IT kWh | {m['other_per_it']:.3f} |",
         f"| Total facility energy | {mwh(m['facility_kwh'])} (utility {mwh(m['utility_kwh'])}, generators {mwh(m['generator_kwh'])}) |",
         f"| IT energy (UPS outputs) | {mwh(m['it_kwh'])} |",
         f"| Cooling | {mwh(m['cooling_kwh'])} |",
         f"| Power path losses | {mwh(m['power_loss_kwh'])} (UPS {mwh(m['ups_loss_kwh'])}, distribution {mwh(m['unmetered_kwh'])}) |",
         f"| House load | {mwh(m['other_kwh'])} |", "",
         "## By week", "", "| Week | PUE | Cooling pPUE | Power pPUE | Facility | IT |", "|---|---|---|---|---|---|"]
    for i, x in enumerate(f["weeks"], 1):
        L.append(f"| {i}. {short(x['start'])} to {short(E.iso(E.parse(x['end']) - timedelta(hours=1)))} | {x['pue']:.3f} | "
                 f"{x['ppue_cooling']:.3f} | {x['ppue_power']:.3f} | {mwh(x['facility_kwh'])} | {mwh(x['it_kwh'])} |")
    L += ["", "## 52 weeks by four-week period", "",
          "| Period | Mean outdoor | PUE | Cooling pPUE | Power pPUE | IT |", "|---|---|---|---|---|---|"]
    for p in f["periods"]:
        L.append(f"| {short(p['start'])} to {short(p['end'])}{' (this month)' if p['month'] else ''} | {p['outdoor_c']:.1f} C | "
                 f"{p['pue']:.3f} | {p['ppue_cooling']:.3f} | {p['ppue_power']:.3f} | {mwh(p['it_kwh'])} |")
    if y:
        L += ["", f"52-week PUE ({short(y['start'])}, {y['start'][:4]} to {short(y['end'])}, {y['end'][:4]}): **{y['pue']:.3f}**. "
                  "The periods before the sample month are synthetic history (Hall A only: no Hall B rack drew power before September 5)."]
    L += ["", "## Findings", ""]
    if not f["findings"]:
        L.append("None: the Landlord's report reconciles with the meters and no free-cooling lockout ran past 24 hours.")
    for x in f["findings"]:
        L += [f"### {x['id']}: {x['title']}", "", x["summary"], "",
              f"- Contract: {', '.join(x['refs'])}", f"- Evidence: {'; '.join(x['evidence'])}"]
        if x["extra_kwh"] is not None:
            L.append(f"- Estimated extra energy: {mwh(x['extra_kwh'])} (about ${x['extra_usd']:,.0f} at ${f['tariff']:.3f} per kWh; plant model estimate)")
        L.append("")
    L += ["## Free-cooling log", "", "| Chiller | Disabled | Enabled | Hours | Record |", "|---|---|---|---|---|"]
    for s in f["lockouts"]:
        L.append(f"| {s['chiller']} | {s['start'][:16].replace('T', ' ')} | {s['end'][:16].replace('T', ' ')} | {s['hours']:.1f} | {s['note']} |")
    L += ["", "## Contract terms (Landlord SLA section 22)", ""]
    L += [f"- **{t['id']} {t['name']}.** {t['rule']}" for t in f["terms"]]
    if f["check"]:
        c = f["check"]
        L += ["", "## Engine self-check", "",
              f"Detected **{c['detected']} of {c['planted']}** planted energy discrepancies, **{c['false_positives']} false positives**; "
              f"the likely cause named correctly for {c['cause_named']} report mismatch. The check cannot read the answer key."]
    return "\n".join(L) + "\n"


def html_page() -> str:
    f = prepare()
    tpl = sitenav.inject((ROOT / "templates" / "energy.html").read_text(encoding="utf-8"), "energy")
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(f, sort_keys=True).replace("</", "<\\/")))


def robustness_month(k: int) -> dict:
    """PUE checks on generated month k. The meters follow the racks, so the month's GPU Health layer and GPU telemetry
    (rack_hourly.csv) are built first."""
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    from scorecard.synthetic import gpu_health as GH
    from scorecard.synthetic import telemetry as TS
    from scorecard.synthetic.energy import EnergyLayer, write_energy
    syn = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    cfg, hcfg = E.load_config(), GH.load_config()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        write_dataset(SiteGenerator(load_sla(), syn, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run(), d)
        GH.write_gpu_health(GH.GpuHealthLayer(d, 2000 + k, hcfg).run(), d / "gpu_health")
        TS.write_telemetry(TS.Published(TS.GpuTelemetry(d, d / "gpu_health", 2000 + k, None, hcfg)).run(), d / "telemetry", "", None)
        write_energy(EnergyLayer(d, 2000 + k, cfg, rack_hourly=d / "telemetry" / "rack_hourly.csv").run(), d / "energy")
        data = N.load(d / "energy")
        ev = N.evaluate(N.analyse(data, cfg), data.key)
    return {"month": k, "kind": data.key["report_error"], "planted": ev.planted, "detected": ev.detected, "named": ev.cause_named,
            "missed": list(ev.missed), "fps": list(ev.false_positives)}


def robustness(n: int, jobs: int = 1, resume: Path | None = None) -> int:
    """PUE checks on n generated months, jobs at a time; with resume, each month's result is kept in that folder and
    a rerun skips the months already there."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    done: dict[int, dict] = {}
    if resume:
        resume.mkdir(parents=True, exist_ok=True)
        for p in resume.glob("month_*.json"):
            r = json.loads(p.read_text(encoding="utf-8"))
            if r["month"] < n:
                done[r["month"]] = r
    todo = [k for k in range(n) if k not in done]

    def keep(r: dict) -> None:
        done[r["month"]] = r
        if resume:
            (resume / f"month_{r['month']:03d}.json").write_text(json.dumps(r) + "\n", encoding="utf-8")

    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            for f in as_completed([ex.submit(robustness_month, k) for k in todo]):
                keep(f.result())
    else:
        for k in todo:
            keep(robustness_month(k))
    planted = detected = named = mismatches = 0
    fps, by_kind = [], {}
    for k in range(n):
        r = done[k]
        kind = r["kind"]
        by_kind.setdefault(kind, [0, 0])
        by_kind[kind][1] += 1
        by_kind[kind][0] += kind == "none" or not any(m.startswith("report_mismatch") for m in r["missed"])
        planted, detected, named = planted + r["planted"], detected + r["detected"], named + r["named"]
        mismatches += kind != "none"
        fps += [(k, x) for x in r["fps"]]
        for m in r["missed"]:
            print(f"  month {k}: missed {m}")
    print(f"PUE checks on {n} generated months (report errors and lockouts planted, weather and loads vary):")
    for kind, (ok, tot) in sorted(by_kind.items()):
        print(f"  report {kind:<20} {'correct, not flagged' if kind == 'none' else 'found'} {ok}/{tot}")
    print(f"  cause named          {named}/{mismatches}")
    print(f"  detected             {detected}/{planted}, {len(fps)} false positives")
    for k, x in fps:
        print(f"  month {k}: false positive: {x[:100]}")
    return 0 if detected == planted and not fps else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, metavar="N")
    ap.add_argument("--jobs", type=int, default=1, help="months to run at once (robustness)")
    ap.add_argument("--resume", type=Path, metavar="DIR", help="keep each month's result here and skip months already done")
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness, args.jobs, args.resume)
    f = prepare()
    text = markdown(f)
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_energy.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}: month PUE {f['month']['pue']:.3f}, 52-week {f['kpi']['actual']:.3f}, "
          f"{len(f['findings'])} findings")
    if f["check"]:
        print(f"Detected {f['check']['detected']} of {f['check']['planted']} planted, {f['check']['false_positives']} false positives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
