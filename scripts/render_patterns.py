#!/usr/bin/env python3
"""Render the failure pattern review: reports/failure_patterns.md and the interactive page.

Usage:
    python scripts/render_patterns.py                    # write reports/failure_patterns.md
    python scripts/render_patterns.py --check            # fail if the report is stale (CI)
    python scripts/render_patterns.py --html OUT.html    # write the page (scripts/build_site.py does this)
    python scripts/render_patterns.py --robustness 60    # score the analysis on 60 generated histories
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import sitenav  # noqa: E402
from scorecard.patterns import (MIN_EVENTS, MIN_RATIO, RECURRENCE_DAYS, WATCH_P, History,  # noqa: E402
                                build_review, followup, score)

HISTORY = ROOT / "data" / "history"
SAMPLE = ROOT / "data" / "sample"
TOPOLOGY = SAMPLE / "site" / "topology.json"
LESSONS = ROOT / "patterns" / "lessons.yaml"
OUT = ROOT / "reports" / "failure_patterns.md"
PAGE = "https://jasonmossotti.github.io/dco-vendor-scorecard/patterns/"


def day(iso: str, year: bool = False) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return f"{t:%b} {t.day}, {t.year}" if year else f"{t:%b} {t.day}"


def last_day(iso_end: str, year: bool = True) -> str:
    """The last day of a period whose end is exclusive."""
    from datetime import timedelta
    return day((datetime.fromisoformat(iso_end.replace("Z", "+00:00")) - timedelta(days=1)).isoformat(), year=year)


def lessons() -> dict:
    return yaml.safe_load(LESSONS.read_text(encoding="utf-8"))


def facts(history: Path = HISTORY) -> dict:
    return build_review(History(history, TOPOLOGY, ROOT / "sla"))


def prepare() -> dict:
    """Facts plus judgment plus the display strings the Markdown and the page both print."""
    f, ls = facts(), lessons()
    w = f["window"]
    f["window_txt"] = f"{day(w['start'], year=True)} to {last_day(w['end'])}"
    f["lessons"] = ls
    tickets = json.loads((SAMPLE / "vendor" / "tickets.json").read_text(encoding="utf-8"))
    f["followup"] = followup(f, tickets, ls["review_meeting"])
    for p in f["patterns"]:
        p["judgment"] = ls["patterns"][p["key"]]
        p["owner_txt"] = f"{p['raci']['accountable']} (accountable), {p['raci']['responsible']} (does the work)" \
            if p["raci"]["accountable"] != p["raci"]["responsible"] else p["raci"]["accountable"]
        p["span_txt"] = f"{day(p['first'])} to {day(p['last'])}"
        p["window_weeks"] = w["weeks"]
        p["observed_txt"], p["expected_txt"] = _observed(p)
        p["facts_txt"] = _facts_lines(p)
        p["followup"] = f["followup"].get(p["key"], [])
    for wi in f["watch"]:
        wi["ruling"] = ls["watch_rulings"][wi["key"]]
        wi["observed_txt"] = _observed(wi)[0]
    return f


def _observed(p: dict) -> tuple[str, str]:
    """What was counted for the test, and what chance predicts."""
    if p["dimension"] == "fix":
        return f"{p['events']} of {p['repairs']} repairs came back", f"{p['expected']:.1f}"
    noun = {"optic_module": "modules", "optic_fiber": "links", "psu": "PSUs"}.get(p["signature"], "trays")
    return f"{p['events']} {noun}", f"{p['expected']:.1f}"


def _facts_lines(p: dict) -> list[str]:
    e = p["evidence"]
    if e["kind"] == "cooling":
        ep = e["episode"]
        return [
            f"{e['cdu']} ran {1.0:.1f} °C or more above its {e['setpoint_c']:.1f} °C setpoint (daily mean) for {ep['days']} days, "
            f"{day(ep['from'])} to {last_day(ep['to'], year=False)}, peaking at {e['peak_c']:.1f} °C on {day(e['peak_at'])}; its high-supply alarm is "
            f"{e['alarm_high_c']:.1f} °C, which it {'never reached' if e['below_alarm'] else 'reached'}. The other CDUs peaked at {e['others_peak_c']:.1f} °C.",
            f"Secondary flow fell {e['flow_drop_pct']:.1f}% ({e['flow_before_lpm']:,} to {e['flow_end_lpm']:,} L/min, median).",
            f"In the {e['racks_count']} racks it serves ({ep['racks'][0]} to {ep['racks'][-1]}), {p['events']} trays had their first GPU thermal slowdown "
            f"during that time, against {p['expected']:.1f} expected from the rest of the hall: {p['ratio_txt']} the rate.",
            f"{e['events']} of the hall's {e['events'] + e['others']} thermal slowdowns in the {p['window_weeks']} weeks happened in those racks while "
            f"{e['cdu']} ran warm; " + ("none" if not e["others_warm"] else str(e["others_warm"])) + f" of the other {e['others']} happened where a CDU was running warm.",
            (f"The quarterly filter change on {day(e['ended_by_filter_change'])} ended it; the racks had {e['events_after']} thermal slowdowns "
             f"in the {e['days_after']} days after." if e["ended_by_filter_change"] else "No filter change ended it in the window."),
            f"Repairs while it ran warm: {e['tray_swaps']} tray replacements and {e['reseats']} reseats.",
        ]
    if e["kind"] == "asset_lot":
        return [
            f"{e['lot']} is {e['share_of_base']}% of the installed optic modules and {e['share_of_failures']}% of module failures: "
            f"{p['failures']} failures against {p['expected']:.1f} expected, {p['ratio_txt']} the rate of the other lots.",
            f"The failures are spread across {e['racks']} of {e['rack_total']} racks and both ends of the link "
            f"({e['host_end']} host side, {e['switch_end']} switch side).",
            f"{e['still_installed']} of the lot's {e['installed_at_start']} modules are still installed; "
            f"{'the lot is also in the spares pool' if e['in_spares'] else 'none of the lot is in the spares pool'}.",
        ]
    if e["kind"] == "fix":
        return [
            f"{e['recurred']} of {e['repairs']} '{e['fix']}' repairs came back within {RECURRENCE_DAYS} days "
            f"(median {e['median_days_to_recur']} days later), against {p['rest_rate_pct']:.1f}% for every other repair: {p['ratio_txt']} the rate.",
            f"'{e['alt_fix']}' for the same fault: {e['alt_recurred']} of {e['alt_repairs']} came back.",
            f"Counted only for repairs with a full {RECURRENCE_DAYS} days left in the window to show a recurrence.",
        ]
    return [f"{p['events']} failing units against {p['expected']:.1f} expected."]


def _table(head: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]


def markdown(f: dict) -> str:
    ls, m, w = f["lessons"], f["method"], f["window"]
    L = ["<!-- GENERATED by scripts/render_patterns.py from data/history/ and patterns/lessons.yaml. Do not edit by hand. -->", "",
         f"# Failure Pattern Review {ls['id']}", "",
         f"**Site AUS-1 (fictional), Hall A.** {f['window_txt']} ({w['weeks']} weeks, {w['racks']} production racks). "
         f"Prepared {day(ls['prepared'], year=True)}; reviewed {day(ls['review_meeting'], year=True)} by the {', '.join(ls['authors'])}. "
         f"Interactive version: [Failure Pattern Review page]({PAGE}).", "",
         "> A pattern means failures cluster beyond what chance explains. It is not proof of a bad batch or a careless partner "
         "until the cause is confirmed; the confidence of each cause is stated.", "",
         "## Summary", "", ls["summary"], ""]
    L += _table(["#", "Pattern", "Owner", "Observed", "Expected by chance", "Rate vs. the rest", "Confidence"],
                [[p["number"], p["judgment"]["title"], p["owner_txt"], p["observed_txt"], p["expected_txt"], p["ratio_txt"],
                  p["judgment"]["confidence"]] for p in f["patterns"]])
    for p in f["patterns"]:
        j = p["judgment"]
        L += ["", f"## {p['number']}. {j['title']}", "",
              f"*Signal:* {p['signature_name']} · *Grouped by:* {p['dimension_name']} · *Failures:* {p['span_txt']} · "
              f"*p* {'' if p['p_txt'].startswith('<') else '= '}{p['p_txt']} (threshold {p['threshold_txt']}) · *Owner (Interface Agreement RACI, {p['raci']['component']}):* {p['owner_txt']}", "",
              "**What the data shows**", ""] + [f"- {x}" for x in p["facts_txt"]]
        L += ["", f"**Root cause.** {j['root_cause']}", "", f"**Cost.** {j['cost']}", "", f"**Lesson.** {j['lesson']}", "",
              "**Standard-work changes**", ""]
        L += _table(["Document", "Clause", "Change"], [[DOCS[c["doc"]], c["ref"], c["change"]] for c in j["standard_changes"]])
        L += ["", f"**Actions** (status as of {day(ls['status_as_of'], year=True)})", ""]
        L += _table(["ID", "Action", "Owner", "Priority", "Due", "Status", "Done when"],
                    [[a["id"], a["action"], a["owner"], a["priority"], a["due"], a["status"], a["success"]] for a in j["actions"]])
        if p["followup"]:
            L += ["", "**Since the review (September data):** " + "; ".join(
                f"{x['number']} on {x['unit']} ({day(x['opened_at'])}) was still closed '{p['evidence']['fix']}'" for x in p["followup"]) + "."]
    L += ["", "## Watch items", "",
          f"Groups with at least {MIN_EVENTS} failures and {MIN_RATIO:.0f} times the rate of the rest that chance could still explain once the "
          f"number of tests is accounted for. With {m['tests_total']} tests, about {m['chance_watch']} would reach p < {WATCH_P} by chance alone.", ""]
    L += _table(["Group", "Observed", "Expected by chance", "Rate vs. the rest", "p", "Ruling"],
                [[wi["title"], wi["observed_txt"], f"{wi['expected']:.1f}", wi["ratio_txt"], wi["p_txt"], wi["ruling"]] for wi in f["watch"]]) \
        if f["watch"] else ["None."]
    L += ["", "## The busiest racks", "", "What a ticket-count league table would show, tested the same way as everything else.", ""]
    L += _table(["Rack", "Tickets", "Kinds of failure", "Failing units", "Expected by chance", "Rate vs. the rest", "p", "Pattern?"],
                [[r["rack"], str(r["tickets"]), str(r["signatures"]), str(r["units"]), f"{r['expected']:.1f}", r["ratio_txt"], r["p_txt"],
                  "yes" if r["verdict"] == "pattern" else "no"] for r in f["league"]])
    L += ["", ls["league_note"]]
    L += ["", "## Method", "",
          f"- **Failures come from the Telemetry of Record**, never from ticket text: DCGM (XIDs and thermal slowdowns), UFM (link down, and "
          f"transceiver DOM alarms that name the failed module), and Redfish (PSU health). {f['totals']['failures']} failures, each matched to the "
          f"ticket that repaired it ({f['totals']['matched']} matched); the ticket supplies only the fix applied.",
          "- **Groups.** Each failure signature by rack, by the racks a CDU serves, by tray slot, and by optic lot; every failure together by rack "
          "and by CDU; each signature by fix (does a reseat or clean hold for 30 days?); and GPU thermal slowdowns in the racks a CDU serves "
          "while that CDU ran warm (daily mean 1.0 °C or more above setpoint for at least 7 days).",
          "- **Tests.** Location and lot: exact binomial test of the group's share of failing units against its share of the installed base "
          "(a unit that fails again counts once; repeat failures on one unit are CSL-08 and KM-09's job). Fix: one-sided Fisher exact test of "
          "30-day recurrence against every other repair.",
          f"- **A pattern** needs at least {MIN_EVENTS} failures, {MIN_RATIO:.0f} times the rate of the rest, and p under 0.05 divided by the "
          "number of tests in its family (Bonferroni): " + ", ".join(f"{k} {v} ({m['tests'][k]} test{'' if m['tests'][k] == 1 else 's'})" for k, v in m["thresholds"].items()) + ".",
          "- **Owner.** The component's row in the Interface Agreement RACI. A thermal pattern explained by the CDU is the Landlord's "
          "(DM-COOL: the Landlord owns the CDUs and the header up to the rack manifold valves).",
          "- **Judgment** (root cause, lessons, standard-work changes, actions) is written by people in `patterns/lessons.yaml` and tested against "
          "these facts: every number must match and no individual is named.",
          "", "*Synthetic data for a portfolio demonstration; all names and events are fictional.*", ""]
    return "\n".join(L)


DOCS = {"interface_agreement": "Interface Agreement", "ot_partner": "Landlord SLA", "it_partner": "IT Partner SLA"}


def html_page() -> str:
    f = prepare()
    f["docs"] = DOCS
    tpl = sitenav.inject((ROOT / "templates" / "patterns.html").read_text(encoding="utf-8"), "patterns")
    return sitenav.finish(tpl.replace("__DATA__", json.dumps(f, sort_keys=True, default=str).replace("</", "<\\/")))


def robustness(n: int) -> int:
    from generate_history import generate
    from scorecard.synthetic.history import write_history
    tot = {"planted": 0, "found": 0, "owner_ok": 0, "decoys_flagged": 0, "other": 0, "watch": 0}
    by_type: dict[str, list[int]] = {}
    misses, extras = [], []
    for seed in range(1, n + 1):
        with tempfile.TemporaryDirectory() as d:
            data = generate(seed, vary=True)
            write_history(data, d)
            r = build_review(History(d, TOPOLOGY, ROOT / "sla"))
        key = data["streams"]["ground_truth/planted_patterns.json"]
        s = score(r, key)
        for k in ("planted", "found", "owner_ok", "decoys_flagged"):
            tot[k] += s[k]
        tot["other"] += len(s["other_flags"])
        tot["watch"] += len(r["watch"])
        for a in key:
            if a["type"] != "decoy":
                by_type.setdefault(a["type"], [0, 0])[1] += 1
                by_type[a["type"]][0] += a["type"] not in s["missed"]
        misses += [(seed, m) for m in s["missed"]]
        extras += [(seed, x) for x in s["other_flags"]]
    print(f"Failure pattern analysis on {n} generated histories (patterns moved and resized each time):")
    for t, (found, planted) in by_type.items():
        print(f"  {t:<20} found {found}/{planted}")
    print(f"  owner correct        {tot['owner_ok']}/{tot['found']}")
    print(f"  decoy racks flagged  {tot['decoys_flagged']}/{n}")
    print(f"  other flags          {tot['other']} in {n} histories " + ("(" + "; ".join(f"seed {a}: {b}" for a, b in extras) + ")" if extras else ""))
    print(f"  watch items          {tot['watch'] / n:.1f} per history")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--html", metavar="OUT")
    ap.add_argument("--robustness", type=int, metavar="N")
    args = ap.parse_args()
    if args.robustness:
        return robustness(args.robustness)
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(html_page(), encoding="utf-8")
        print(f"Wrote {args.html}")
        return 0
    text = markdown(prepare())
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_patterns.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
