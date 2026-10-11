#!/usr/bin/env python3
"""Render the availability report: reports/availability.md and the Availability tab (/availability/).

Fleet availability from the scheduler, GPU-hours lost by owner under the contracts, a bridge between
the two, repair turnaround in stages, and the spares and RMA pipeline. It reads existing records and the
engine's own measurement, and scores nothing new.

Usage:
    python scripts/render_availability.py                    # write reports/availability.md
    python scripts/render_availability.py --check            # fail if it is stale (CI)
    python scripts/render_availability.py --robustness 60    # check the reconciliations on 60 generated months
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import availability as AV  # noqa: E402
from scorecard import sitenav  # noqa: E402

OUT = ROOT / "reports" / "availability.md"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def day(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{MON[int(m) - 1]} {int(d)}, {y}"


def short(iso: str) -> str:
    _, m, d = iso[:10].split("-")
    return f"{MON[int(m) - 1]} {int(d)}"


def last(iso: str) -> str:
    from datetime import datetime
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def hm(minutes: float | None) -> str:
    if minutes is None:
        return "no record"
    m = int(round(minutes))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def prepare() -> dict:
    return AV.build()


def markdown(f: dict) -> str:
    w = f["window"]
    owners = {o["owner"]: o["hours"] for o in f["owners"]}
    L = ["<!--", "  GENERATED FILE. DO NOT EDIT BY HAND.",
         "  Source: data/sample/ (scheduler, tickets, badges, health checks, spares, RMA) and the IT engine  |  Generator: scripts/render_availability.py",
         "-->", "", "# Availability and Repair Turnaround: Site AUS-1", "",
         f"Sample month {day(w['start'])} to {day(last(w['end']))} (UTC). Synthetic data; all names fictional. This view reads the "
         "records and the engine's measurement; it scores nothing new.", "",
         "## Summary", "", "| Measure | Value |", "|---|---|",
         f"| Fleet availability, scheduler view | {f['sched']['pct']:.3f}% ({f['sched']['lost']:,.1f} of {f['installed']:,.0f} GPU-hours could not take work) |",
         f"| CSL-01 Supplier-attributable availability | {f['csl01']['actual']:.3f}% (minimum {f['csl01']['minimum']:.1f}%): {f['csl01']['detail']} |",
         f"| CSL-12 worst rack | {f['csl12']['actual']:.3f}%: {f['csl12']['detail']} |",
         f"| GPU-hours lost under the contracts | {f['contract_lost']:,.1f} |"]
    for h, x in f["halls"].items():
        L.append(f"| {h}, scheduler view | {x['pct']:.3f}% ({x['racks']} racks installed, {x['sched_lost']:,.1f} GPU-hours lost) |")
    L += ["", "## GPU-hours lost by owner", "", "| Owner | GPU-hours | Basis |", "|---|---|---|",
          f"| IT Partner | {owners['IT Partner']:,.1f} | CSL-01: capacity-weighted, Tickets of Record from the first fault signal to validated return to service |",
          f"| Landlord | {owners['Landlord']:,.1f} | Rack power loss to the Landlord's handoff (Interface Agreement FA-1, FA-3) |",
          f"| OEM | {owners['OEM']:,.1f} | Excused only for part unavailability with spares at minimum; none claimed |",
          f"| Customer | {owners['Customer']:,.1f} | Customer holds and withheld access; none recorded |",
          f"| Planned work | {owners['Planned work']:,.1f} | Approved maintenance drains; none in the scheduler record |",
          "", "## Scheduler to contracts", "", "| Step | GPU-hours |", "|---|---|"]
    for r in f["bridge"]["rows"]:
        L.append(f"| {r['label']} | {r['hours']:+,.1f} |" if r["key"] not in ("sched", "contract") else f"| **{r['label']}** | **{r['hours']:,.1f}** |")
    L += ["", "## By cause", "", "| Cause | Incidents | IT Partner | Landlord | Total | Share | Worst rack |", "|---|---|---|---|---|---|---|"]
    for c in f["causes"]:
        L.append(f"| {c['cause']} | {c['incidents']} | {c['it']:,.1f} | {c['landlord']:,.1f} | {c['total']:,.1f} | {c['share']:.1f}% | "
                 f"{c['worst_rack'] + ' (' + format(c['worst_hours'], ',.1f') + ')' if c['worst_rack'] else 'none: no GPUs out of service'} |")
    L += ["", "## By week (the weekly review's weeks)", "",
          "| Week | Scheduler | CSL-01 measured | IT Partner reported | IT Partner GPU-hours | Landlord GPU-hours |", "|---|---|---|---|---|---|"]
    for i, x in enumerate(f["weeks"], 1):
        L.append(f"| {i}. {short(x['start'])} to {short(last(x['end']))} | {x['sched_pct']:.3f}% | {x['csl01']:.3f}% | "
                 f"{x['reported']:.3f}% | {x['it_lost']:,.1f} | {x['landlord_lost']:,.1f} |")
    L += ["", "## Repair turnaround by stage (per ticket)", "",
          "Median, with the 90th percentile in parentheses. Stages run one after another and add up to the measured time: "
          + "; ".join(f"{s['short']}, {s['name'].lower()}" for s in f["stages"]) + ".", "",
          "| Cause | Tickets | " + " | ".join(s["short"] for s in f["stages"]) + " |", "|---|---|" + "---|" * len(f["stages"])]
    for r in f["stage_summary"]:
        L.append(f"| {r['cause']} | {r['tickets']} | " + " | ".join(
            f"{hm(r['stages'][s['key']]['median'])} ({hm(r['stages'][s['key']]['p90'])})" if r["stages"][s["key"]]["n"] else "no record"
            for s in f["stages"]) + " |")
    L += ["", "## Restoration: measured against reported", "",
          "| Cause | Tickets of Record | Tickets | Measured median (P90) | Reported median (P90) | Longest measured | Longest reported |",
          "|---|---|---|---|---|---|---|"]
    for r in f["restoration"]:
        L.append(f"| {r['cause']} | {r['tors']} | {r['tickets']} | {hm(r['measured']['median'])} ({hm(r['measured']['p90'])}) | "
                 f"{hm(r['reported']['median'])} ({hm(r['reported']['p90'])}) | {hm(r['measured']['max'])} | {hm(r['reported']['max'])} |")
    miss = [t for t in f["tickets"] if t["missing"]]
    if miss:
        L += ["", "Tickets with a stage that has no record: " + "; ".join(
            f"{t['ticket']} (no {', '.join(t['missing'])}{'; ' + ', '.join(t['findings']) if t['findings'] else ''})" for t in miss) + "."]
    s = f["spares"]
    L += ["", "## Spares", "", "| FRU class | Minimum | Start | End | Lowest | Days below minimum | Issued | Received |", "|---|---|---|---|---|---|---|---|"]
    for r in s["rows"]:
        L.append(f"| {r['fru']} | {r['minimum'] if r['minimum'] is not None else 'none set'} | {r['opening']} | {r['closing']} | {r['low']} | "
                 f"{r['days_below'] if r['days_below'] is not None else ''} of {s['days']} | {r['issued']} | {r['received']} |")
    L += ["", "## RMA to the OEM", "", "| FRU class | Shipped | Median business days | Longest | Within 5 business days |", "|---|---|---|---|---|"]
    for r in s["rma_by_fru"]:
        L.append(f"| {r['fru']} | {r['shipped']} | {r['median_days']:g} | {r['max_days']} | {r['within_5']} of {r['shipped']} |")
    L += ["", f"Parts the tickets say were removed: {s['removed']}; with a shipment record: {s['removed'] - len(s['no_rma'])}."
          + (" Without one: " + ", ".join(f"{x['ticket']} ({x['part']})" for x in s["no_rma"]) + "." if s["no_rma"] else ""), "",
          "| Key Measurement | Target | Measured | Detail |", "|---|---|---|---|"]
    for k in s["kms"]:
        L.append(f"| {k['id']} {k['name']} | {k['target']:g}% | {k['actual']:.1f}% ({'met' if k['met'] else 'not met'}) | {k['detail']} |")
    return "\n".join(L) + "\n"


def html_page() -> str:
    f = prepare()
    tpl = sitenav.inject((ROOT / "templates" / "availability.html").read_text(encoding="utf-8"), "availability")
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(f, sort_keys=True).replace("</", "<\\/")))


def robustness_month(k: int) -> dict:
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    syn = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        write_dataset(SiteGenerator(load_sla(), syn, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run(), d)
        b = AV.build(d)
    it = next(o["hours"] for o in b["owners"] if o["owner"] == "IT Partner")
    csl = float(re.search(r"([\d,]+) capacity", b["csl01"]["detail"])[1].replace(",", ""))
    stage_sum = all(t["missing"] or abs(sum(v or 0 for v in t["stages"].values()) - t["measured_min"]) <= 0.5 for t in b["tickets"])
    return {"month": k, "closes": b["bridge"]["closes"], "it_matches": abs(it - csl) <= 0.55,   # the detail rounds to whole GPU-hours, the owner row to 0.1
            "unmatched": next((r["hours"] for r in b["bridge"]["rows"] if r["key"] == "unmatched"), 0.0),
            "stages_add_up": stage_sum, "missing": sum(1 for t in b["tickets"] if t["missing"]),
            "missing_with_finding": sum(1 for t in b["tickets"] if t["missing"] and t["findings"]),
            "no_rma": len(b["spares"]["no_rma"]), "tickets": len(b["tickets"])}


def robustness(n: int) -> int:
    rs = []
    for k in range(n):
        rs.append(robustness_month(k))
        r = rs[-1]
        if not (r["closes"] and r["it_matches"] and r["stages_add_up"]):
            print(f"  month {k}: bridge {'closes' if r['closes'] else 'does not close'}, IT Partner "
                  f"{'equals' if r['it_matches'] else 'differs from'} CSL-01, stages {'add up' if r['stages_add_up'] else 'do not add up'}")
    ok = lambda key: sum(1 for r in rs if r[key])   # noqa: E731
    print(f"Availability reconciliations on {n} generated months:")
    print(f"  bridge scheduler to contracts closes   {ok('closes')}/{n}")
    print(f"  IT Partner GPU-hours equal CSL-01      {ok('it_matches')}/{n}")
    print(f"  ticket stages add up to measured time  {ok('stages_add_up')}/{n}")
    print(f"  scheduler GPU-hours with no incident   {sum(r['unmatched'] for r in rs):,.1f}")
    print(f"  tickets with a stage with no record    {sum(r['missing'] for r in rs)} of {sum(r['tickets'] for r in rs)}, "
          f"{sum(r['missing_with_finding'] for r in rs)} of them with an engine finding")
    print(f"  removed parts with no RMA record       {sum(r['no_rma'] for r in rs)}")
    return 0 if ok("closes") == ok("it_matches") == ok("stages_add_up") == n else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, metavar="N")
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness)
    f = prepare()
    text = markdown(f)
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_availability.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    owners = {o["owner"]: o["hours"] for o in f["owners"]}
    print(f"Wrote {OUT.relative_to(ROOT)}: scheduler {f['sched']['pct']:.3f}%, CSL-01 {f['csl01']['actual']:.3f}%, "
          f"lost IT Partner {owners['IT Partner']:,.1f} / Landlord {owners['Landlord']:,.1f} GPU-hours, "
          f"bridge {'closes' if f['bridge']['closes'] else 'DOES NOT CLOSE'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
