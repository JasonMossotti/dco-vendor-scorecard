#!/usr/bin/env python3
"""Render the change-aware alarm review: reports/change_alarms.md and the alarm board page.

Usage:
    python scripts/render_alarms.py                     # write reports/change_alarms.md
    python scripts/render_alarms.py --check             # fail if the report is stale (CI)
    python scripts/render_alarms.py --html OUT.html     # write the board (scripts/build_site.py does this)
    python scripts/render_alarms.py --robustness 60     # score the check on 60 generated months with planted cases
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import alarms as A  # noqa: E402
from scorecard.connectors import FileConnector  # noqa: E402
from scorecard.sla_model import load_interface_agreement  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
CHANGES = ROOT / "data" / "changes"
OUT = ROOT / "reports" / "change_alarms.md"
PAGE = "https://jasonmossotti.github.io/dco-vendor-scorecard/alarms/"
PIR = "docs/pir/PIR-2026-001.md"
OFFSET = timedelta(hours=-5)    # site local time (Central Daylight Time), as config/synthetic.yaml


def hm(iso: str | None) -> str:
    return iso[11:16] + "Z" if iso else "open"


def lc(s: str) -> str:
    return s[:1].lower() + s[1:]


def day(iso: str) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return f"{t:%b} {t.day}"


def prepare() -> dict:
    r = A.run_check(SAMPLE, CHANGES)
    key = json.loads((CHANGES / "ground_truth" / "change_alarm_key.json").read_text(encoding="utf-8"))
    alarms = r["alarms"]
    s = A.score(alarms, r["owed"], key)
    owed_by_alarm: dict[str, list] = {}
    for o in r["owed"]:
        owed_by_alarm.setdefault(o["alarm"], []).append(o)
    rows = []
    for a in alarms:
        d = A.alarm_dict(a)
        d["owed"] = owed_by_alarm.get(a.id, [])
        d["keys"] = sorted(a.keys)
        rows.append(d)
    src = FileConnector(SAMPLE)
    sitemap = A.SiteMap(A.S.load_site(), src.get("topology"))
    decls = []
    for dcl in r["declarations"]:
        mine = [a for a in alarms if a.change == dcl["change_id"]]
        c = Counter(a.cls for a in mine)
        decls.append({**dcl, "scope": sorted(set().union(*(sitemap.scope(x) for x in dcl["assets"]))), "counts": {k: c.get(k, 0) for k in (A.EXPECTED, A.OUT_OF_SCOPE, A.OUT_OF_WINDOW)},
                      "alarms": [a.id for a in mine]})
    ia = load_interface_agreement()
    return {"window": r["window"], "alarms": rows, "declarations": decls, "owed": r["owed"], "key_measures": r["key_measures"],
            "conflicts": r["conflicts"], "tickets": A.trouble_tickets(src), "planned_work": A.planned_work(src),
            "routing": yaml.safe_load((ROOT / "config" / "customer_notifications.yaml").read_text(encoding="utf-8")), "score": s, "rules": ia["alarm_notification"],
            "class_text": A.CLASS_TEXT, "offset_h": OFFSET.total_seconds() / 3600, "pir": PIR,
            "a07": a07_facts(alarms, r["declarations"], r["owed"])}


def a07_facts(alarms: list[A.Alarm], decls: list[dict], owed: list[dict]) -> dict:
    """The rack outage of 2026-09-15 as the check sees it; tests hold these to the PIR's own times."""
    mop = next(d for d in decls if d["title"].startswith("Retorque"))
    mine = [a for a in alarms if a.change == mop["change_id"]]
    first = min((a for a in mine if a.cls == A.OUT_OF_SCOPE), key=lambda a: a.raised)
    over = next(a for a in mine if a.signal == "Change window overrun")
    exp = next(a for a in mine if a.cls == A.EXPECTED)
    return {"change": mop["change_id"], "title": mop["title"], "declared": mop["assets"], "window_start": mop["window_start"],
            "window_end": mop["window_end"], "expected_alarm": A.alarm_dict(exp), "first_flag": A.alarm_dict(first),
            "flags": [A.alarm_dict(a) for a in mine if a.cls in A.FLAGGED],
            "overrun": A.alarm_dict(over),
            "owed": [o for o in owed if o["change"] == mop["change_id"]]}


def _table(head: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in rows]


def markdown(f: dict) -> str:
    w = f["window"]
    al = f["alarms"]
    flagged = [a for a in al if a["cls"] in A.FLAGGED]
    sev = Counter((a["partner"], a["severity"]) for a in al)
    cls = Counter(a["cls"] for a in al)
    a7 = f["a07"]
    L = ["<!-- GENERATED FILE. DO NOT EDIT BY HAND. Source: data/sample + data/changes | Generator: scripts/render_alarms.py -->",
         "", "# Change-Aware Alarm Review: Site AUS-1", "",
         f"Synthetic sample month {w['start'][:10]} to {w['end'][:10]} (fictional site; all data synthetic). "
         f"Interactive board: [{PAGE}]({PAGE}). Rules: Interface Agreement section 10 (`sla/interface_agreement.yaml`); "
         "alarm map and change catalog: `config/change_alarms.yaml`; code: `src/scorecard/alarms.py`.", "",
         "A flag means an alarm does not reconcile with an approved change. It is not a finding against anyone.", "",
         "## Summary", ""]
    L += [f"- **{len(al)} alarms** from both partners' feeds: "
          + ", ".join(f"{p} {sev[(p, 'critical')]} critical, {sev[(p, 'major')]} major, {sev[(p, 'minor')]} minor"
                      for p in ("Landlord", "IT Partner")) + ".",
          f"- **{len(f['declarations'])} approved changes** with impact declarations; {cls[A.EXPECTED]} alarms expected under them.",
          f"- **{cls[A.OUT_OF_SCOPE]} out of scope and {cls[A.OUT_OF_WINDOW]} out of window**, all on {a7['change']} "
          f"({a7['title']}), the change behind PIR-2026-001."
          if {a["change"] for a in flagged} == {a7["change"]} else
          f"- **{cls[A.OUT_OF_SCOPE]} out of scope and {cls[A.OUT_OF_WINDOW]} out of window.**",
          f"- **{len(f['conflicts'])} change conflicts** (two redundancy-reducing changes on connected equipment at once).",
          "- **Notifications** under the new section 10, measured against what the partners sent under their current SLAs: "
          + "; ".join(f"{k['party']} {k['on_time']} of {k['owed']} on time" for k in f["key_measures"])
          + ". Every P1 was paged within 5 minutes, but P2 alarms get one call or email, and no notification names a change. "
          "That gap is what the clause closes.", ""]

    L += ["## Rack A07, September 15: what the check would have shown", "",
          f"Reconciles with [PIR-2026-001]({'../' + f['pir']}) (same records and times).", ""]
    ex, ff, ov = a7["expected_alarm"], a7["first_flag"], a7["overrun"]
    L += [f"- {a7['change']} declared one asset, `{a7['declared'][0]}`, window {hm(a7['window_start'])} to {hm(a7['window_end'])}.",
          f"- {hm(ex['raised'])}: {ex['summary']}. **Expected** (declared).",
          f"- {hm(ff['raised'])}: {ff['summary']}. **Out of scope**: {lc(ff['reason'])}. "
          "The Customer is alerted at this second by its own check; the partner owes an NT-3 notification within 5 minutes.",
          *[f"- {hm(a['raised'])}: {a['summary']} ({a['partner']}). **Out of scope**." for a in a7["flags"]
            if a["id"] not in (ff["id"], ov["id"])],
          f"- {hm(ov['raised'])}: {ov['summary']}. **Out of window**: {lc(ov['reason'])}. "
          "The PIR's factor F5 says nothing alerted on this; this alert would have.", ""]
    L += ["What the partners actually sent (their current SLAs):", ""]
    L += _table(["Alarm", "Owed by", "Rule", "Sent", "Channels", "Result"],
                [[f"{o['device']}: {o['signal']}", o["party"], o["rule"], hm(o.get("sent")), ", ".join(o.get("channels") or []) or "none",
                  o["status"].replace("_", " ")] for o in a7["owed"]])
    L += ["", "## Change work", ""]
    L += _table(["Change", "Owner", "Type", "Window", "Declared assets", "Expected", "Out of scope", "Out of window"],
                [[d["change_id"], d["owner"], d["type"], f"{day(d['window_start'])} {hm(d['window_start'])} to {hm(d['window_end'])}",
                  ", ".join(x.replace("rack:", "rack ") for x in d["assets"]),
                  str(d["counts"][A.EXPECTED]), str(d["counts"][A.OUT_OF_SCOPE]), str(d["counts"][A.OUT_OF_WINDOW])]
                 for d in f["declarations"]])
    L += ["", "## Alarms that do not reconcile with an approved change", ""]
    L += _table(["Alarm", "Raised", "Partner", "Severity", "Device", "Alarm text", "Change", "Result", "Why"],
                [[a["id"], f"{day(a['raised'])} {hm(a['raised'])}", a["partner"], a["severity"], a["device"], a["summary"],
                  a["change"], A.CLASS_TEXT[a["cls"]], a["reason"]] for a in flagged])
    L += ["", "## Change conflicts", ""]
    L += [f"- {c['text']}." for c in f["conflicts"]] or ["None in this month."]
    L += ["", "## Notifications owed under Interface Agreement section 10", "",
          "Measured against each partner's delivery log. The sample month predates the clause, so this is the baseline it starts from.", ""]
    L += _table(["Measure", "Party", "Owed", "On time", "Late", "Single channel or no change named", "Missing", "Actual", "Target",
                 "NT-1 (critical)", "NT-2 (major)", "NT-3 (change work)"],
                [[k["id"], k["party"], str(k["owed"]), str(k["on_time"]), str(k["late"]), str(k["incomplete"]), str(k["missing"]),
                  f"{k['actual']}%" if k["actual"] is not None else "n/a", f"{k['target']}%",
                  *[f"{k['by_rule'][r]['on_time']} of {k['by_rule'][r]['owed']}" for r in ("NT-1", "NT-2", "NT-3")]]
                 for k in f["key_measures"]])
    s = f["score"]
    L += ["", "## Self-check against the answer key", "",
          f"{s['found']} of {s['cases']} expected flags found; {s['decoys_flagged']} of {s['decoys']} decoys flagged; "
          f"{len(s['other_flags'])} other flags. The sample has no planted cases (only the natural rack outage); "
          "planted cases are scored on 60 generated months with `python scripts/render_alarms.py --robustness 60`.", "",
          "## How alarms are classified", "",
          "1. **Expected:** a declared asset raises a declared alarm, at or below the declared severity, inside the window "
          "(15 minutes grace either side). An alarm another approved change declared is accounted for.",
          "2. **Out of scope:** inside the window, an undeclared alarm or one too severe on a declared asset, or an alarm on "
          "connected equipment (redundant partner, or the load the asset serves, from the site model) of a kind the work could cause "
          "(power, cooling, fire, compute).",
          "3. **Out of window:** a declared alarm up to 4 hours before the window, or a declared asset still in its maintenance "
          "state 15 minutes after the window closes (raised as a Customer-check alarm at that moment).",
          "4. **Not change work:** everything else, including alarms during a window on equipment that is not connected.", ""]
    return "\n".join(L) + "\n"


def html_page() -> str:
    f = prepare()
    tpl = (ROOT / "templates" / "alarms.html").read_text(encoding="utf-8")
    return tpl.replace("__DATA__", json.dumps(f, sort_keys=True, default=str).replace("</", "<\\/"))


def explain(flag: A.Alarm, d: Path) -> str | None:
    """Ground truth behind a flag the key did not list (scorer only; the check never reads ground_truth/)."""
    gt = json.loads((d / "ground_truth" / "facility_incidents.json").read_text(encoding="utf-8"))
    for g in gt:
        t0 = A.parse(g["t0"])
        if abs(flag.raised - t0) <= timedelta(minutes=5) and (g["unit"] == flag.device or g["unit"].split("/")[0] in flag.keys
                                                              or g["fault_class"] == "UTILITY"):
            return f"facility fault {g['gt_id']} ({g['description'][:60]})"
    it = json.loads((d / "ground_truth" / "incidents.json").read_text(encoding="utf-8"))
    for g in it:
        t0 = A.parse(g.get("t0") or g.get("fault_start") or "")
        if t0 and flag.rack and g.get("rack") == flag.rack and abs(flag.raised - t0) <= timedelta(minutes=10):
            return f"IT fault {g['gt_id']} ({g['kind']})"
    pl = json.loads((d / "ground_truth" / "facility_planted_discrepancies.json").read_text(encoding="utf-8"))
    for p in pl:
        if p.get("busway") == flag.device and A.parse(p["at"]) == flag.raised:
            return f"Landlord work with no MOP ({p['anomaly_id']})"
    return None


def robustness(n: int) -> int:
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    from scorecard.synthetic.changes import ChangeLayer, write_changes
    cfg = yaml.safe_load((ROOT / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    by_type: dict[str, list[int]] = {}
    tot = Counter()
    unexplained, explained, conflicts = [], Counter(), 0
    for k in range(n):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = SiteGenerator(load_sla(), cfg, start=date(2025, 1, 6) + timedelta(weeks=4 * k), seed=2000 + k).run()
            write_dataset(data, d)
            out = ChangeLayer(d, 2000 + k).run(plant=True)
            write_changes(out, d / "changes", data["window"], 2000 + k, "generated")
            r = A.run_check(d, d / "changes")
            s = A.score(r["alarms"], r["owed"], out["key"])
            for t, (ok, tot_t) in s["by_type"].items():
                by_type.setdefault(t, [0, 0])
                by_type[t][0] += ok
                by_type[t][1] += tot_t
            for m in s["missed"]:
                print(f"  month {k}: missed {m}")
            ids = {a.id: a for a in r["alarms"]}
            for o in s["other_flags"]:
                why = explain(ids[o.split()[0]], d)
                if why:
                    explained[why.split(" (")[0].split(" FGT")[0].split(" GT")[0]] += 1
                else:
                    unexplained.append(f"month {k}: {o}")
            tot["other"] += len(s["other_flags"])
            conflicts += len(r["conflicts"])
    print(f"Change-aware alarm check on {n} generated months (cases moved each month):")
    for t, (ok, tt) in sorted(by_type.items()):
        word = "not flagged" if t.startswith("decoy") else "found"
        print(f"  {t:<22} {word} {ok}/{tt}")
    print(f"  other flags            {tot['other']} in {n} months; "
          + (", ".join(f"{v} {k}" for k, v in explained.items()) or "none")
          + f"; unexplained {len(unexplained)}")
    for u in unexplained:
        print("   ", u)
    print(f"  change conflicts       {conflicts} in {n} months")
    bad = sum(tt - ok for t, (ok, tt) in by_type.items())
    return 1 if bad or unexplained else 0


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
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_alarms.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
