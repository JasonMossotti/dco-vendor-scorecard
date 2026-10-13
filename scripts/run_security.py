#!/usr/bin/env python3
"""Run the security engine and write the Security Partner scorecard and discrepancy report.

Usage:
    python scripts/run_security.py                     # data/sample + data/security -> reports/
    python scripts/run_security.py --check             # fail if the committed reports are stale (CI)
    python scripts/run_security.py --robustness 60     # also test 60 freshly generated months
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard.engine.core import fmt_t  # noqa: E402
from scorecard.engine.evaluate import evaluate_security  # noqa: E402
from scorecard.engine.security import build_security_scorecard, run_security  # noqa: E402
from scorecard.sla_model import PARTNER_FILES, load_sla  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
SECURITY = ROOT / "data" / "security"
REPORTS = ROOT / "reports"


def _json_default(o):
    return o.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(o, datetime) else str(o)


def _pct(v, d=3):
    return "n/a" if v is None else f"{v:.{d}f}%"


STATUS = {"met_expected": "Met Expected", "below_expected": "Below Expected (RCA)", "below_minimum": "**Minimum default**",
          "deep_below_minimum": "**Minimum default**", "not_applicable": "n/a (no events)"}


def scorecard_md(sla, sc, ev) -> str:
    w = sc["window"]
    L = [f"# Security Partner Scorecard: {sc['supplier']}", "",
         f"Window {w['start']:%Y-%m-%d} to {w['end']:%Y-%m-%d}. Measured from the Customer's access control, video, and "
         f"identity systems, beside the Security Partner's own weekly report. Synthetic data; all names fictional.", "",
         f"**Headline:** the Security Partner reported every service level met and every post staffed. Measured: "
         f"**{len(sc['defaults'])} Minimum defaults**" + (f" ({', '.join(sc['defaults'])})" if sc["defaults"] else "")
         + f", **{sc['s1']} S1 findings**, and **${sc['credits']['payable']:,.0f}** in service credits"
         + (f" (capped from ${sc['credits']['uncapped']:,.0f})." if sc["credits"]["capped"] else "."), "",
         "## Critical Service Levels", "",
         "| ID | Service level | Security Partner reported | Measured | Expected / Minimum | Status | Credit | Basis |",
         "|---|---|:-:|:-:|:-:|---|:-:|---|"]
    for r in sc["csl"]:
        basis = r["detail"] + (f". {r['note']}" if r["note"] and r["status"] != "met_expected" else "")
        L.append(f"| {r['id']} | {r['name']} | {_pct(r['vendor_reported'], 2)} | {_pct(r['actual'])} | "
                 f"{r['expected']:g}% / {r['minimum']:g}% | {STATUS[r['status']]} | "
                 f"{'$' + format(r['credit'], ',.0f') if r['credit'] else ''} | {basis} |")
    L += ["", "## Key Measurements", "", "| ID | Key measurement | Target | Measured | Result | Basis |", "|---|---|:-:|:-:|:-:|---|"]
    for k in sc["km"]:
        val = "n/a" if k["actual"] is None else f"{k['actual']:.1f}%"
        res = "n/a" if k["met"] is None else ("Met" if k["met"] else "Missed")
        L.append(f"| {k['id']} | {k['name']} | >= {k['target']:g}% | {val} | {res} | {k['detail']} |")
    L += ["", "## Service credits", ""]
    for c in sc["credits"]["items"]:
        L.append(f"- {c['csl']}: {c['explanation']} = **${c['credit']:,.0f}**")
    L.append(f"- **Payable: ${sc['credits']['payable']:,.0f}**" + (" (monthly cap applied)" if sc["credits"]["capped"] else ""))
    if ev:
        L += ["", "## Engine self-check", "", f"Detected **{ev.detected} of {ev.planted}** planted security discrepancies, "
              f"**{len(ev.false_positives)} false positives**. The engine cannot read the answer key."]
    return "\n".join(L) + "\n"


def findings_md(result, ev) -> str:
    L = ["# Security Discrepancy Report", "",
         "Each finding is a place where the Security Partner's post log, dispatch log, visitor log, or chain-of-custody log "
         "does not reconcile with the Customer's access control system, Redfish inventory, or the RMA shipments. A finding "
         "starts a review; it is not by itself proof of intent.", "", "| ID | Severity | Type | Where | Summary |", "|---|:-:|---|---|---|"]
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


def outputs(data_dir: Path = SAMPLE, sec_dir: Path = SECURITY) -> dict[Path, str]:
    sla = load_sla(PARTNER_FILES["security"])
    result = run_security(sla, data_dir, sec_dir)
    ev = evaluate_security(result.findings, sec_dir)
    sc = build_security_scorecard(sla, result)
    findings = [{k: getattr(f, k) for k in ("id", "type", "title", "severity", "unit", "tickets", "summary", "sla_refs", "observed_at")}
                for f in result.findings]
    return {
        REPORTS / "security_scorecard.md": scorecard_md(sla, sc, ev),
        REPORTS / "security_scorecard.json": json.dumps(sc, indent=2, sort_keys=True, default=_json_default) + "\n",
        REPORTS / "security_discrepancy_report.md": findings_md(result, ev),
        REPORTS / "security_findings.json": json.dumps(findings, indent=2, sort_keys=True, default=_json_default) + "\n",
    }


def robustness(n: int) -> tuple[int, int, int]:
    from scorecard.synthetic import SiteGenerator, write_dataset
    from scorecard.synthetic.security import generate
    cfg = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    sla = load_sla(PARTNER_FILES["security"])
    planted = detected = fps = 0
    for k in range(n):
        d = Path(tempfile.mkdtemp(prefix=f"security_{k}_"))
        write_dataset(SiteGenerator(load_sla(), cfg, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run(), d)
        generate(d, d / "security")
        ev = evaluate_security(run_security(sla, d, d / "security").findings, d / "security")
        planted, detected, fps = planted + ev.planted, detected + ev.detected, fps + len(ev.false_positives)
        for m in ev.missed:
            print(f"  month {k}: missed {m['type']}")
        for f in ev.false_positives:
            print(f"  month {k}: false positive {f.type}: {f.summary[:120]}")
        shutil.rmtree(d, ignore_errors=True)
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
            print(f"{p.relative_to(ROOT)} is out of date. Run: python scripts/run_security.py")
        return 1 if stale else 0
    for p, t in docs.items():
        p.write_text(t, encoding="utf-8", newline="\n")
    sc = json.loads(docs[REPORTS / "security_scorecard.json"])
    print(f"Security Partner: {len(sc['defaults'])} Minimum defaults {sc['defaults']}, {sc['findings']} findings "
          f"({sc['s1']} S1), ${sc['credits']['payable']:,.0f} credits payable")
    print(docs[REPORTS / "security_scorecard.md"].split("## Engine self-check")[-1].strip().splitlines()[-1])
    if args.robustness:
        p, d, f = robustness(args.robustness)
        print(f"Robustness over {args.robustness} generated months: detected {d}/{p}, {f} false positives")
        return 0 if d == p and f == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
