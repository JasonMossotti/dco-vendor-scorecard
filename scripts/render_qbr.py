#!/usr/bin/env python3
"""Quarterly business review: one pack per partner for the quarter's three months (reports/qbr.md).

Usage:
    python scripts/render_qbr.py                   # write reports/qbr.md
    python scripts/render_qbr.py --check           # fail if the report is stale
    python scripts/render_qbr.py --robustness 20   # generate 20 consecutive quarters (60 months) and check every rule

The Scorecards page's Quarterly review view (/app/#qbr) is built from the same data (scorecard.qbr.page_data) by
scripts/render_scorecards.py.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import qbr as Q  # noqa: E402

OUT = ROOT / "reports" / "qbr.md"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
STATUS = {"met_expected": "Met", "below_expected": "Below Expected", "below_minimum": "Below Minimum",
          "deep_below_minimum": "Below Minimum", "no_events": "n/a", "not_applicable": "n/a"}
RULES = {"corrective_action_plan": "Corrective action plan", "review_measure": "Review the measure", "tighten": "Tighten"}


def prepare() -> dict:
    return Q.page_data()


def md(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{MON[d.month - 1]} {d.day}"


def usd(v: float) -> str:
    return f"${v:,.0f}"


def thr(lv: dict, v: float) -> str:
    return ("≥ " if lv["direction"] == "higher_is_better" else "≤ ") + f"{v:g}{lv['unit']}"


def pct(v: float | None, d: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{d}f}%"


def _table(head: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"] + ["| " + " | ".join(r) + " |" for r in rows]


def pack_md(p: dict, months: list[dict], notes: dict | None) -> list[str]:
    labels = [m["label"] for m in months]
    c, ch = p["credits"], p["chronic"]
    out = [f"## {p['name']} ({p['supplier']})", ""]
    if notes and p["key"] in notes.get("summary", {}):
        out += [f"> {notes['summary'][p['key']].strip()}", "", f"> *{notes['chair']}, at the review on {notes['meeting']}.*", ""]
    defaults = [sum(1 for lv in p["levels"] if lv["months"][i]["status"] in Q.DEFAULT) for i in range(len(months))]
    out += [f"Minimum defaults by month: {', '.join(str(x) for x in defaults)}. Credits for the quarter {usd(c['quarter_payable'])} as "
            f"published, {usd(c['quarter_adjusted'])} with the repeat-default rule applied. "
            f"{len(ch['cf1'])} chronic failure trigger{'s' if len(ch['cf1']) != 1 else ''} (CF-1).", ""]

    out += ["### Service levels by month", "", "Each month's column is that month's published scorecard.", ""]
    rows = []
    for lv in p["levels"]:
        cells = ["n/a" if m["actual"] is None else f"{m['measured']} ({STATUS[m['status']]})" for m in lv["months"]]
        rows.append([lv["id"], lv["name"], thr(lv, lv["expected"]), thr(lv, lv["minimum"])] + cells + [lv["trend"]])
    out += _table(["ID", "Service level", "Expected", "Minimum"] + labels + ["Trend"], rows) + [""]

    out += ["### Service credits", "", f"At-risk cap {usd(c['at_risk'])} a month ({p['terms']['at_risk_pct']}% of "
            f"{usd(p['terms']['monthly_charges'])}).", ""]
    rows = [[lab, ", ".join(m["items"]) or "none", usd(m["uncapped"]), usd(m["payable"]), "Yes" if m["capped"] else "No"]
            for lab, m in zip(labels, c["months"])]
    rows.append(["**Quarter**", "", "", f"**{usd(c['quarter_payable'])}**", f"of {usd(c['quarter_at_risk'])} at risk"])
    out += _table(["Month", "Below Minimum", "Uncapped", "Payable", "Capped"], rows) + [""]

    out += ["### Multi-month rules", ""]
    if c["adjustments"]:
        for a in c["adjustments"]:
            lab = labels[[m["id"] for m in months].index(a["month"])]
            items = "; ".join(f"{x['csl']} {usd(x['published'])} to {usd(x['doubled'])} ({x['run']} consecutive defaults)" for x in a["csls"])
            out += [f"**Repeat-default doubling, {lab}:** {items}. Doubled credits {usd(a['uncapped'])}"
                    + (f", held to the {usd(c['at_risk'])} cap" if a["capped"] else "")
                    + f": an adjustment of **{usd(a['adjustment'])}** beside the published {usd(a['published'])}, which stays as published.", ""]
    else:
        out += [f"**Repeat-default doubling:** no service level was below Minimum in {p['terms']['doubling_after']} consecutive months.", ""]
    out += ["**Earnback** (Expected met in each of the 3 months after a default):", ""]
    rows = [[labels[[m["id"] for m in months].index(e["month"])], e["csl"], usd(e["credit"]), e["state"], e["why"]] for e in p["earnback"]]
    out += (_table(["Default in", "Service level", "Credit", "Earnback", "Why"], rows) if rows else ["No defaults this quarter."]) + [""]
    cf1 = ", ".join(f"{x['csl']}" for x in ch["cf1"]) or "none"
    cf2 = ", ".join(f"{x['csl']} {x['defaults']} of 3" for x in ch["cf2"]) or "none"
    out += [f"**Chronic failure:** CF-1 (below Minimum on the same service level in 3 consecutive months): {cf1}. "
            f"CF-2 (4 of 6 rolling months) watch, months below Minimum this quarter: {cf2}. "
            f"CF-3 (credits over half the at-risk amount in 6 rolling months, {usd(ch['cf3']['threshold'])}): "
            f"{usd(ch['cf3']['credits'])} this quarter, {ch['cf3']['share'] * 100:.0f}% of the threshold. "
            "CF-4 (deliberate falsification) is a determination people make; a finding means records do not reconcile, so the pack does not apply it.", ""]

    out += ["### Self-report against measurement", "",
            "Service levels where the partner's own report met Expected while the measurement did not, by month: "
            + ", ".join(str(x) for x in p["overstated_by_month"]) + ".", ""]
    rows = []
    for s in p["self_report"]:
        if not s["overstated"]:
            continue
        rows.append([s["id"]] + [f"{pct(x['reported'])} / {pct(x['actual'])}" + (" (overstated)" if x["overstated"] else "") for x in s["months"]])
    out += (_table(["ID"] + [f"{lab}: reported / measured" for lab in labels], rows) if rows else ["None."]) + [""]

    out += ["### Findings by type", "", "A type seen in two months or more repeats: the same kind of record keeps failing to reconcile.", ""]
    rows = [[f["title"], f["type"]] + [str(x) for x in f["months"]] + [str(f["total"]), "Yes" if f["repeat"] else ""] for f in p["findings"]]
    out += _table(["Finding", "Type"] + labels + ["Quarter", "Repeat"], rows) + [""]

    a = p["actions"]["summary"]
    out += ["### Corrective actions", ""]
    rows = [[lab, str(x["opened"]), str(x["due_in_quarter"]) if p["key"] == "it" else "n/a"] for lab, x in zip(labels, p["caps"])]
    out += _table(["Month", "Plans drafted at the month's review" if p["key"] == "it" else "S1 findings (each needs a plan)",
                   "Due inside the quarter"], rows) + [""]
    med = "n/a" if a["ehs_median_days"] is None else f"{a['ehs_median_days']:g} days"
    out += [f"September's programs: post-incident review actions {a['pir']} ({a['pir_complete']} complete), quality audit findings {a['audit']}, "
            f"EHS actions {a['ehs']} ({a['ehs_closed']} closed, {a['ehs_on_time']} on time, median {med} to close). "
            "Closure of the monthly plans is not in the records; on-time closure is computed only where a record carries its close date (EHS actions).", ""]

    s = p["staffing"]
    out += ["### Staffing fill", ""]
    out += _table(["Month", s["id"], "Status", "Basis"],
                  [[lab, m["measured"], STATUS[m["status"]], d] for lab, m, d in zip(labels, s["months"], s["detail"])]) + [""]

    out += ["### SLA change proposals", ""]
    notes_by = {(n["csl"], n["rule"]): n["text"].strip() for n in (notes or {}).get("proposals", []) if n["partner"] == p["key"]}
    rows = [[RULES[x["rule"]], x["csl"], x["fact"], notes_by.get((x["csl"], x["rule"]), "")] for x in p["proposals"]]
    out += (_table(["Rule", "Service level", "The fact", "What the review said"], rows) if rows else ["None this quarter."]) + [""]
    return out


def markdown(q: dict) -> str:
    months, r, notes = q["months"], q["roadmap"], q["notes"]
    first, last = months[0], months[-1]
    out = ["# Quarterly business review", "",
           f"Site AUS-1 (synthetic), {q['quarter']}: {md(first['start'])} to {md(last['end'])}, {last['end'][:4]}, three 4-week Measurement "
           "Periods. Generated by `scripts/render_qbr.py`; do not edit by hand.", "",
           "The contract's quarterly forum (`sla/common.yaml`, governance): trend analysis, SLA change proposals, the roadmap and capacity "
           "plan, and program-wide lessons learned. The last month is the committed sample; the two before it are generated by the same "
           "site generator with their own seeds and their planted problems drawn by chance (`config/qbr.yaml`, `data/quarter/`). "
           "September's stories (the rack A07 outage, the Hall B rollout, the audit and EHS cases) are in September only.", "",
           "The record starts with the quarter: a doubling needs three consecutive defaults inside it, and an earnback, which needs the "
           "three months after a default, can only be on track, pending, or lost. A doubling is shown as an adjustment beside the "
           "published month; the published scorecard does not change.", "",
           f"Proposal rules (`config/qbr.yaml`): **corrective action plan** when a service level is below Minimum in {q['rule']['cap_min_defaults']} "
           "months or more; **review the measure** when the partner's report met Expected while the measurement did not in every month; "
           f"**tighten** when Expected was met every month with the worst month beyond Expected by at least {q['rule']['tighten_margin_share']:g} "
           "of the Expected-to-Minimum gap. What each proposal means is the review's judgment, in `qbr/notes/`.", ""]
    for p in q["packs"].values():
        out += pack_md(p, months, notes)
    hb, hc = r["hall_b"], r["hall_c"]
    out += ["## Roadmap and capacity", "",
            f"Hall B: {hb['handed_off']} of {hb['racks']} racks handed off by {md(hb['as_of'])}; {hb['on_time']} of the {hb['due']} due by then "
            f"reached Validated Handoff on time. The last committed handoff is {md(hb['last_committed'])}.", "",
            f"Hall C: first compute committed {md(hc['committed'])}, forecast {md(hc['forecast'])} ({hc['slip_days']} day"
            f"{'s' if hc['slip_days'] != 1 else ''} late; the critical path starts with {hc['critical_path'][0].lower() + hc['critical_path'][1:]}).", ""]
    if notes and notes.get("lessons"):
        out += ["## Program-wide lessons", ""] + [f"- {x.strip()}" for x in notes["lessons"]] + [""]
    return "\n".join(out)


# --------------------------------------------------------------------------- robustness
def robustness_quarter(k: int) -> dict:
    """A generated quarter: three consecutive months, each generated as the earlier months are."""
    from scorecard.synthetic.quarter import generate_month
    cfg = Q.load_config()
    start = date(2025, 1, 6) + timedelta(weeks=12 * k)
    with tempfile.TemporaryDirectory() as tmp:
        ms = []
        for j in range(3):
            m = {"id": f"q{k}m{j + 1}", "start": start + timedelta(weeks=4 * j), "seed": 5000 + 3 * k + j}
            d = Path(tmp) / str(m["start"])
            generate_month(m, d, cfg)
            ms.append((m, d))
        q = Q.build_quarter(ms, cfg)
        bad = Q.check(q)
        # Each month's column equals that month's own scorecard, built again on its own.
        for (m, d), i in zip(ms, range(3)):
            one = Q.build_quarter([(m, d)], cfg)
            for key, p in q["packs"].items():
                solo = one["packs"][key]
                if [lv["months"][i] for lv in p["levels"]] != [lv["months"][0] for lv in solo["levels"]]:
                    bad.append(f"{key} month {i + 1}: column differs from the month's own scorecard")
                if p["credits"]["months"][i] != solo["credits"]["months"][0]:
                    bad.append(f"{key} month {i + 1}: credits differ from the month's own scorecard")
    return {"quarter": k, "bad": bad,
            "doubled": sum(len(a["csls"]) for p in q["packs"].values() for a in p["credits"]["adjustments"]),
            "cf1": sum(len(p["chronic"]["cf1"]) for p in q["packs"].values()),
            "proposals": sum(len(p["proposals"]) for p in q["packs"].values()),
            "earnback": sum(len(p["earnback"]) for p in q["packs"].values())}


def robustness(n: int, jobs: int = 1) -> int:
    from concurrent.futures import ProcessPoolExecutor
    t0 = time.time()
    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            res = list(ex.map(robustness_quarter, range(n)))
    else:
        res = [robustness_quarter(k) for k in range(n)]
    for r in res:
        for b in r["bad"]:
            print(f"  quarter {r['quarter']}: {b}")
    ok = sum(1 for r in res if not r["bad"])
    print(f"Quarterly review on {n} generated quarters ({3 * n} months, {time.time() - t0:.0f} s): {ok}/{n} quarters hold every rule "
          f"(totals equal the months, each column equals its month's own scorecard, doubling, earnback, and chronic rules); "
          f"{sum(r['doubled'] for r in res)} doubled credits, {sum(r['cf1'] for r in res)} CF-1 triggers, "
          f"{sum(r['earnback'] for r in res)} earnback cases, {sum(r['proposals'] for r in res)} proposals")
    return 0 if ok == n else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--robustness", type=int, metavar="N")
    ap.add_argument("--jobs", type=int, default=1)
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness, args.jobs)
    q = prepare()
    text = markdown(q)
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_qbr.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    bad = Q.check(q)
    for k, p in q["packs"].items():
        c = p["credits"]
        print(f"{p['name']}: credits {' + '.join(usd(m['payable']) for m in c['months'])} = {usd(c['quarter_payable'])}; "
              f"with doubling {usd(c['quarter_adjusted'])}; CF-1 {', '.join(x['csl'] for x in p['chronic']['cf1']) or 'none'}; "
              f"{len(p['proposals'])} proposals")
    print(f"Wrote {OUT.relative_to(ROOT)}" + ("" if not bad else "; CHECK FAILED: " + "; ".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
