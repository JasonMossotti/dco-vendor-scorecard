#!/usr/bin/env python3
"""Run the Landlord engine and write the Landlord scorecard, discrepancy report, and attribution report.

Usage:
    python scripts/run_landlord.py                     # data/sample -> reports/
    python scripts/run_landlord.py --check             # fail if the committed reports are stale (CI)
    python scripts/run_landlord.py --robustness 60     # also test 60 freshly generated months
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.connectors import FileConnector  # noqa: E402
from scorecard.engine.core import fmt_t  # noqa: E402
from scorecard.engine.evaluate import evaluate_landlord  # noqa: E402
from scorecard.engine.landlord import build_landlord_scorecard, run_landlord  # noqa: E402
from scorecard.sla_model import PARTNER_FILES, load_sla  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
REPORTS = ROOT / "reports"


def _json_default(o):
    return o.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(o, datetime) else str(o)


def _pct(v, d=3):
    return "n/a" if v is None else f"{v:.{d}f}%"


STATUS = {"met_expected": "Met Expected", "below_expected": "Below Expected (RCA)", "below_minimum": "**Minimum default**",
          "deep_below_minimum": "**Minimum default**", "not_applicable": "n/a (no events)"}


def scorecard_md(sla, sc, ev) -> str:
    w = sc["window"]
    L = [f"# Landlord Scorecard: {sc['supplier']}", "",
         f"Window {w['start']:%Y-%m-%d} to {w['end']:%Y-%m-%d}. Measured from the Customer's read-only facility telemetry "
         f"under the Interface Agreement, beside the Landlord's own weekly report. Synthetic data; all names fictional.", "",
         f"**Headline:** the Landlord reported every service level met. Measured: **{len(sc['defaults'])} Minimum defaults**"
         + (f" ({', '.join(sc['defaults'])})" if sc["defaults"] else "")
         + f", **{sc['s1']} S1 findings**, and **${sc['credits']['payable']:,.0f}** in credits against rent"
         + (f" (capped from ${sc['credits']['uncapped']:,.0f})." if sc["credits"]["capped"] else "."), "",
         "## Critical Service Levels", "",
         "| ID | Service level | Landlord reported | Measured | Expected / Minimum | Status | Credit | Basis |",
         "|---|---|:-:|:-:|:-:|---|:-:|---|"]
    for r in sc["csl"]:
        L.append(f"| {r['id']} | {r['name']} | {_pct(r['vendor_reported'], 2)} | {_pct(r['actual'])} | "
                 f"{r['expected']:g}% / {r['minimum']:g}% | {STATUS[r['status']]} | "
                 f"{'$' + format(r['credit'], ',.0f') if r['credit'] else ''} | {r['detail']} |")
    L += ["", "## Key Measurements", "", "| ID | Key measurement | Target | Measured | Result | Basis |", "|---|---|:-:|:-:|:-:|---|"]
    for k in sc["km"]:
        sym = ">=" if k["direction"] == "higher_is_better" else "<="
        val = "n/a" if k["actual"] is None else (f"{k['actual']:.1f}%" if k["unit"] == "%" else f"{k['actual']:g}{k['unit']}")
        res = "n/a" if k["met"] is None else ("Met" if k["met"] else "Missed")
        L.append(f"| {k['id']} | {k['name']} | {sym} {k['target']:g}{k['unit']} | {val} | {res} | {k['detail']} |")
    L += ["", "## Credits against rent", ""]
    for c in sc["credits"]["items"]:
        L.append(f"- {c['csl']}: {c['explanation']} = **${c['credit']:,.0f}**")
    L.append(f"- **Payable: ${sc['credits']['payable']:,.0f}**" + (" (monthly cap applied)" if sc["credits"]["capped"] else ""))
    if ev:
        L += ["", "## Engine self-check", "", f"Detected **{ev.detected} of {ev.planted}** planted Landlord discrepancies, "
              f"**{len(ev.false_positives)} false positives**. The engine cannot read the answer key."]
    return "\n".join(L) + "\n"


def findings_md(result, ev) -> str:
    L = ["# Landlord Discrepancy Report", "",
         "Each finding is a place where the Landlord's work orders or maintenance records do not reconcile with the "
         "device telemetry the Customer reads under the Interface Agreement. A finding starts a review; it is not by "
         "itself proof of intent.", "", "| ID | Severity | Type | Unit | Summary |", "|---|:-:|---|---|---|"]
    for f in result.findings:
        L.append(f"| {f.id} | {f.severity} {f.severity_name} | {f.title} | {f.unit or ''} | {f.summary} |")
    for f in result.findings:
        L += ["", f"## {f.id}: {f.title} ({f.severity} {f.severity_name})", "", f.summary, "", "| Source | When | Detail |", "|---|---|---|"]
        L += [f"| `{e['source']}` | {fmt_t(e['at']) if e['at'] else ''} | {e['detail']} |" for e in f.evidence]
        L += ["", f"**Recommended action:** {f.recommended_action}", "", f"**SLA references:** {', '.join(f.sla_refs)}"]
    if ev:
        L += ["", "## Engine self-check", "", f"Detected {ev.detected} of {ev.planted} planted discrepancies; "
              f"{len(ev.false_positives)} false positives.", "", "| Type | Planted | Detected |", "|---|:-:|:-:|"]
        L += [f"| {t} | {v['planted']} | {v['detected']} |" for t, v in sorted(ev.by_type.items())]
    return "\n".join(L) + "\n"


def attribution_md(sc) -> str:
    L = ["# Attribution Report", "",
         "Every facility event in the window, attributed under the Interface Agreement (FA-1 to FA-6) from the Customer's "
         "Telemetry of Record, beside the party the Landlord's work order named. Events where no rack capacity was lost "
         "are redundancy events (FA-5) and never touch the IT Partner's clocks.", "",
         "| T0 | Event | Class | Owner (telemetry) | Rule | Rack capacity lost | Work order | Work order says | Agrees |",
         "|---|---|---|---|:-:|:-:|---|---|:-:|"]
    for r in sc["attribution"]:
        L.append(f"| {fmt_t(r['t0'])} | {r['event']} | {r['fault_class']} | {r['owner']} | {r['rule']} | "
                 f"{'Yes' if r['capacity_lost'] else 'No'} | {r['work_order'] or ''} | {r['claimed_owner'] or ''} | "
                 f"{'Yes' if r['agrees'] else '**No**'} |")
    return "\n".join(L) + "\n"


def site_summary_md(it_sc, it_plain, ll_sc, ll_ev, it_ev, it_result) -> str:
    """Both partners side by side, and what attribution changed."""
    rack = [r for r in ll_sc["attribution"] if r["capacity_lost"]]
    it_rack = [i for i in it_result.context.tickets if i["category"] == "rack_facility"]
    L = ["# Site Summary: Site AUS-1", "",
         f"Window {ll_sc['window']['start']:%Y-%m-%d} to {ll_sc['window']['end']:%Y-%m-%d}. Each partner is measured against "
         "its own SLA from the Customer's Telemetry of Record; outages that cross the demarcation are attributed under the "
         "Interface Agreement. Synthetic data; all names fictional.", "",
         "| | IT Partner (Ridgeline) | Landlord (Caprock) |", "|---|:-:|:-:|",
         f"| Self-report | Every SLA met or minor exceptions | Every SLA met |",
         f"| Minimum defaults (measured) | {it_sc['totals']['defaults']} | {len(ll_sc['defaults'])} |",
         f"| Credits payable | ${it_sc['credits']['payable']:,.0f} | ${ll_sc['credits']['payable']:,.0f} (against rent) |",
         f"| Findings (S1) | {it_sc['totals']['findings']} ({it_sc['totals']['s1']}) | {ll_sc['findings']} ({ll_sc['s1']}) |"]
    if it_ev and ll_ev:
        L.append(f"| Engine self-check | {it_ev.detected} of {it_ev.planted}, {len(it_ev.false_positives)} false positives | "
                 f"{ll_ev.detected} of {ll_ev.planted}, {len(ll_ev.false_positives)} false positives |")
    L += ["", "## Outages that crossed the demarcation", ""]
    for r in rack:
        t = next((x for x in it_rack if r["unit"].endswith(x["rack"])), None)
        L += [f"**{r['event']}.** Telemetry attributes it to the **{r['owner']}** ({r['rule']}): both of the rack's feeds were "
              f"out at the tap-offs from {fmt_t(r['t0'])} until the Landlord's handoff at {fmt_t(r['restored'])}. Under FA-3 the "
              f"IT Partner's clock started at the handoff"
              + (f"; its ticket {t['number']} validated the rack and returned it to service at {fmt_t(t['resolved_at'])}." if t else "."), ""]
    rows = lambda sc: {c["id"]: c for c in sc["csl"]}
    a, b = rows(it_sc), rows(it_plain)
    L += ["## What attribution changed for the IT Partner", "",
          "The same telemetry, scored with the IT Partner's clock starting at the power loss instead of the Landlord's handoff:", "",
          "| | With attribution (contract) | Without attribution |", "|---|:-:|:-:|",
          f"| Minimum defaults | {it_sc['totals']['defaults']} | {it_plain['totals']['defaults']} |",
          f"| Credits payable | ${it_sc['credits']['payable']:,.0f} | ${it_plain['credits']['payable']:,.0f} |",
          f"| CSL-03 P1 restoration within 4 hours | {a['CSL-03']['actual']:.1f}% | {b['CSL-03']['actual']:.1f}% |",
          f"| CSL-12 worst-rack availability | {a['CSL-12']['actual']:.3f}% | {b['CSL-12']['actual']:.3f}% |", "",
          "Without attribution the IT Partner would be charged for hours the Landlord's equipment kept the rack dark. "
          "With it, each party is charged only for its own side of the demarcation.", ""]
    return "\n".join(L)


def outputs(data_dir: Path = SAMPLE) -> dict[Path, str]:
    sla = load_sla(PARTNER_FILES["landlord"])
    result = run_landlord(sla, FileConnector(data_dir))
    has_key = (data_dir / "ground_truth" / "facility_planted_discrepancies.json").exists()
    ev = evaluate_landlord(result.findings, data_dir) if has_key else None
    sc = build_landlord_scorecard(sla, result)
    findings = [{k: getattr(f, k) for k in ("id", "type", "title", "severity", "unit", "tickets", "summary", "sla_refs")}
                for f in result.findings]
    return {
        REPORTS / "landlord_scorecard.md": scorecard_md(sla, sc, ev),
        REPORTS / "landlord_scorecard.json": json.dumps(sc, indent=2, sort_keys=True, default=_json_default) + "\n",
        REPORTS / "landlord_discrepancy_report.md": findings_md(result, ev),
        REPORTS / "landlord_findings.json": json.dumps(findings, indent=2, sort_keys=True, default=_json_default) + "\n",
        REPORTS / "attribution_report.md": attribution_md(sc),
        REPORTS / "site_summary.md": _site_summary(data_dir, sc, ev),
    }


def _site_summary(data_dir: Path, ll_sc, ll_ev) -> str:
    from scorecard.builder import build_scorecard
    from scorecard.engine import run_engine
    from scorecard.engine.evaluate import evaluate
    it_sla = load_sla()
    src = FileConnector(data_dir)
    it_result = run_engine(it_sla, src)
    it_ev = evaluate(it_result.findings, data_dir) if (data_dir / "ground_truth").exists() else None
    return site_summary_md(build_scorecard(it_sla, it_result), build_scorecard(it_sla, run_engine(it_sla, src, attribution=False)),
                           ll_sc, ll_ev, it_ev, it_result)


def robustness(n: int) -> tuple[int, int, int]:
    from scorecard.synthetic import SiteGenerator, write_dataset
    cfg = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    sla = load_sla(PARTNER_FILES["landlord"])
    planted = detected = fps = 0
    for k in range(n):
        d = Path(tempfile.mkdtemp(prefix=f"landlord_{k}_"))
        write_dataset(SiteGenerator(load_sla(), cfg, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run(), d)
        ev = evaluate_landlord(run_landlord(sla, FileConnector(d)).findings, d)
        planted, detected, fps = planted + ev.planted, detected + ev.detected, fps + len(ev.false_positives)
        for m in ev.missed:
            print(f"  month {k}: missed {m['type']}")
        for f in ev.false_positives:
            print(f"  month {k}: false positive {f.type}: {f.summary[:100]}")
    return planted, detected, fps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, default=0, metavar="N")
    args = ap.parse_args()
    docs = outputs()
    if args.check:
        stale = [p for p, t in docs.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        for p in stale:
            print(f"{p.relative_to(ROOT)} is out of date. Run: python scripts/run_landlord.py")
        return 1 if stale else 0
    for p, t in docs.items():
        p.write_text(t, encoding="utf-8", newline="\n")
    sc = json.loads(docs[REPORTS / "landlord_scorecard.json"])
    print(f"Landlord: {len(sc['defaults'])} Minimum defaults {sc['defaults']}, {sc['findings']} findings "
          f"({sc['s1']} S1), ${sc['credits']['payable']:,.0f} credits payable")
    print(docs[REPORTS / "landlord_scorecard.md"].split("## Engine self-check")[-1].strip().splitlines()[-1])
    if args.robustness:
        p, d, f = robustness(args.robustness)
        print(f"Robustness over {args.robustness} generated months: detected {d}/{p}, {f} false positives")
        return 0 if d == p and f == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
