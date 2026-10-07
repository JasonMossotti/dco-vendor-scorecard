#!/usr/bin/env python3
"""Render the Unified Site Management overview: the landing page at the site root.

Every number on it is computed from the same data and code as the page it links to,
and tests/test_hub.py checks they agree, so the overview can never disagree with a report.

Usage:
    python scripts/render_hub.py --html OUT.html    # scripts/build_site.py does this
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import app_support as A  # noqa: E402
from scorecard import sitenav  # noqa: E402
from scorecard.sla_model import load_sla  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
BLOB = f"{sitenav.REPO}/blob/main/"
# The contracts open on the Agreements tab; the rest are files in the repository.
DOCS = [
    ("IT Partner SLA", "agreements/it-partner-sla/"),
    ("Landlord SLA", "agreements/landlord-sla/"),
    ("Interface Agreement", "agreements/interface-agreement/"),
    ("Glossary of codes and acronyms", "glossary/"),
    ("Site model and drawings", "docs/site/SITE.md"),
    ("IT Partner scorecard", "reports/scorecard.md"),
    ("Landlord scorecard", "reports/landlord_scorecard.md"),
    ("Fault attribution report", "reports/attribution_report.md"),
    ("Change-aware alarm review", "reports/change_alarms.md"),
    ("Failure pattern review", "reports/failure_patterns.md"),
    ("PUE report", "reports/pue_report.md"),
    ("Live collector readiness", "docs/LIVE_READINESS.md"),
]


def facts() -> dict:
    """The overview's numbers, each from the module that renders the page it summarizes."""
    import render_alarms
    import render_energy
    import render_patterns
    import render_pir
    import render_weekly

    contract = load_sla(ROOT / "sla" / "it_partner.yaml")
    result, sc, ev = A.run_pipeline(contract, SAMPLE)
    ll_result, ll_sc, ll_ev, it_plain = A.run_landlord_pipeline(SAMPLE)
    al = render_alarms.prepare()
    cls = Counter(a["cls"] for a in al["alarms"])
    flagged = [a for a in al["alarms"] if a["cls"] in ("out_of_scope", "out_of_window")]
    pir = render_pir.reviews()[0]
    weeks = render_weekly.packs()
    pat = render_patterns.prepare()
    en = render_energy.prepare()
    from scorecard import tickets as T
    tk = T.build()
    start, end = sc["window"]["start"], sc["window"]["end"]
    return {
        "window": f"{start:%b} {start.day} to {end:%b} {end.day}, {end:%Y}",
        "it": {"name": sc["supplier"], "defaults": sc["totals"]["defaults"], "credits": sc["credits"]["payable"],
               "findings": sc["totals"]["findings"], "planted": ev.planted if ev else None, "detected": ev.detected if ev else None},
        "ll": {"name": ll_sc["supplier"], "defaults": len(ll_sc["defaults"]), "credits": ll_sc["credits"]["payable"],
               "findings": ll_sc["findings"], "planted": ll_ev.planted if ll_ev else None,
               "detected": ll_ev.detected if ll_ev else None},
        "crossing": A.crossing_outages(ll_sc, result),
        "alarms": {"total": len(al["alarms"]), "expected": cls["expected"], "flagged": len(flagged),
                   "flag_changes": sorted({a["change"] or "" for a in flagged} - {""}),
                   "changes": len(al["declarations"]), "tickets": len(al["tickets"]),
                   "notify": [(k["id"], k["party"], k["actual"], k["target"]) for k in al["key_measures"]]},
        "pir": {"id": pir["id"], "title": pir["title"], "status": pir["status"], "ref": pir["ref"],
                "actions": len(pir["actions"]), "open": sum(a["status"] != "Done" for a in pir["actions"])},
        "weeks": [(w["id"], w["title"]) for w in weeks],
        "week_status": [(p["role"], p["status"]) for p in weeks[-1]["partners"]],
        "tickets": {"records": len(tk["records"]), "incidents": tk["counts"]["inc"] + tk["counts"]["wo"],
                    "changes": tk["counts"]["chg"] + tk["counts"]["mop"], "pm": tk["counts"]["pm"],
                    "findings": sum(1 for r in tk["records"] if r["findings"])},
        "patterns": {"id": pat["id"], "window": pat["window_txt"], "failures": pat["totals"]["failures"],
                     "found": len(pat["patterns"]), "watch": len(pat["watch"]),
                     "titles": [p["title"] for p in pat["patterns"]]},
        "energy": {"pue": en["month"]["pue"], "reported": en["report"]["pue"], "year": en["kpi"]["actual"],
                   "target": en["kpi"]["target"], "met": en["kpi"]["met"], "cooling": en["month"]["ppue_cooling"],
                   "findings": [x["title"] for x in en["findings"]]},
    }


def money(v: float) -> str:
    return f"${v:,.0f}"


def md_inline(s: str) -> str:
    """The app's **bold** markdown, as HTML."""
    parts = escape(s).split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))


def tile(key: str, title: str, lead: str, stats: list[tuple[str, str]], links: list[tuple[str, str]], note: str = "") -> str:
    st = "".join(f'<div class="stat"><b>{escape(v)}</b><span>{escape(k)}</span></div>' for v, k in stats)
    ln = "".join(f'<a href="{escape(h)}">{escape(t)}</a>' for t, h in links)
    nt = f'<p class="note">{escape(note)}</p>' if note else ""
    return (f'<section class="tile" data-tile="{key}"><h2><a href="{escape(links[0][1])}">{escape(title)}</a></h2>'
            f'<p class="lead">{escape(lead)}</p><div class="stats">{st}</div>{nt}<div class="links">{ln}</div></section>')


def body(f: dict) -> str:
    it, ll, al, pir, pat, tk, en = f["it"], f["ll"], f["alarms"], f["pir"], f["patterns"], f["tickets"], f["energy"]
    check = lambda p: f"{p['detected']} of {p['planted']}" if p["planted"] is not None else "n/a"
    partners = (
        '<div class="partners">'
        f'<div class="partner ll"><div class="role">Landlord · building, power, cooling, CDUs</div><h3>{escape(ll["name"])}</h3>'
        f'<p>Reported: <b>every SLA met</b>. Measured: <b>{ll["defaults"]} Minimum defaults</b>, '
        f'<b>{money(ll["credits"])}</b> credits against rent, {ll["findings"]} findings.</p></div>'
        f'<div class="partner it"><div class="role">IT Partner · data hall work</div><h3>{escape(it["name"])}</h3>'
        f'<p>Reported: <b>every SLA met or minor exceptions</b>. Measured: <b>{it["defaults"]} Minimum defaults</b>, '
        f'<b>{money(it["credits"])}</b> credits payable, {it["findings"]} findings.</p></div></div>')
    crossing = "".join(f"<p>{md_inline(c)}</p>" for c in f["crossing"])
    follow = (
        '<section class="follow"><h2>Follow one incident through every tool</h2>'
        f'{crossing}<ol>'
        '<li><a href="alarms/#changes">Alarm Board, Change work</a>: the alarms MOP-310 raised outside its declared scope and window.</li>'
        f'<li><a href="tickets/#{pir["ref"]}">Incident Portal</a>: the IT Partner\'s ticket and the Landlord\'s work order as each partner recorded them, '
        'beside the Customer\'s measurement.</li>'
        '<li><a href="pir/">Post-Incident Review</a>: the completed review, its causes and owned actions.</li>'
        '<li><a href="weekly/#2026-W38">Weekly Review, week 3</a>: the outage and its actions in the weekly pack.</li>'
        '<li><a href="app/">Scorecards</a>: how attribution keeps the Landlord\'s outage off the IT Partner\'s scorecard.</li>'
        '</ol></section>')
    flag_note = f"Flagged change work: {', '.join(al['flag_changes'])}" if al["flag_changes"] else ""
    notify = ", ".join(f"{party} {actual:.1f}% (target {target:.0f}%)" for _, party, actual, target in al["notify"])
    tiles = [
        tile("scorecards", "Scorecards",
             "Each partner measured against its own SLA from the Customer's telemetry, beside what the partner reported.",
             [(str(it["defaults"]), "IT Partner Minimum defaults"), (money(it["credits"]), "IT Partner credits"),
              (str(ll["defaults"]), "Landlord Minimum defaults"), (money(ll["credits"]), "Landlord credits")],
             [("Open the scorecards", "app/")],
             f"Engine self-check: IT Partner {check(it)}, Landlord {check(ll)} planted discrepancies found. "
             "Runs Python in your browser; the first visit takes 20 to 40 seconds to start."),
        tile("alarms", "Alarm Board",
             "Every alarm checked against the change work that declared it; anything outside the declared impact is flagged.",
             [(str(al["total"]), "alarms this month"), (str(al["expected"]), "expected from change work"),
              (str(al["flagged"]), "outside declared impact"), (str(al["changes"]), "changes declared")],
             [("Board", "alarms/"), ("Live events", "alarms/#live"), ("Change work", "alarms/#changes"),
              ("Notifications", "alarms/#notify")],
             f"{flag_note}. Notifications on time under Interface Agreement section 10: {notify}." if flag_note else notify),
        tile("tickets", "Incident Portal",
             "Both partners' tickets, changes, and work orders as their own systems record them, each with a timeline and "
             "what the Customer's data says.",
             [(str(tk["records"]), "records"), (str(tk["incidents"]), "incidents and work orders"),
              (str(tk["changes"]), "changes and MOPs"), (str(tk["findings"]), "do not reconcile")],
             [("Open the portal", "tickets/"), ("The outage's ticket", f"tickets/#{pir['ref']}")],
             "Read only, under the Records access term of each SLA (RA-1 to RA-6)."),
        tile("pir", "Post-Incident Review",
             f"{pir['id']}: {pir['title']}.",
             [(pir["ref"], "incident"), (str(pir["actions"]), "owned actions"), (str(pir["open"]), "still open")],
             [("Completed example", "pir/"), ("Blank form", "pir/#blank")],
             f"Status: {pir['status']}."),
        tile("weekly", "Weekly Review",
             "One pack per week for both partners: month-to-date service levels, incidents, actions, next week's priorities.",
             [(str(len(f["weeks"])), "weekly packs"), (f["weeks"][-1][0], "latest")],
             [(wid.split("-")[1], f"weekly/#{wid}") for wid, _ in f["weeks"]],
             f"{f['weeks'][-1][1]}: " + "; ".join(f"{role} {status.lower()}" for role, status in f["week_status"]) + "."),
        tile("patterns", "Failure Patterns",
             f"{pat['id']}: patterns found by statistics on {pat['window']}, with owners and fixes.",
             [(f"{pat['failures']:,}", "failures reviewed"), (str(pat["found"]), "patterns found"), (str(pat["watch"]), "watch items")],
             [("Open the review", "patterns/")],
             "; ".join(pat["titles"]) + "."),
        tile("energy", "Energy",
             "PUE from the meters (ISO/IEC 30134-2:2026), checked against the Landlord's monthly report.",
             [(f"{en['pue']:.3f}", "PUE this month"), (f"{en['reported']:.3f}", "Landlord reported"),
              (f"{en['year']:.3f}", f"52 weeks (target {en['target']:.2f})")],
             [("Open the energy report", "energy/")],
             ("; ".join(en["findings"]) + ".") if en["findings"] else "The Landlord's report reconciles with the meters."),
    ]
    docs = "".join(f'<li><a href="{p if p.endswith("/") else BLOB + p}">{escape(t)}</a></li>' for t, p in DOCS)
    return (
        f'<section class="hero"><h1>Unified Site Management</h1>'
        f'<p class="sub">Site AUS-1, Central Texas · {escape(f["window"])} · synthetic data; all names and events are fictional.</p>'
        '<p>The Customer leases the halls from a Landlord that runs the building, power, and cooling, and contracts an IT Partner '
        'for the data hall work. Each is measured against its own SLA from the Customer\'s Telemetry of Record, and outages '
        'that cross the boundary between them are attributed under the Interface Agreement.</p></section>'
        f'{partners}<div class="grid">{"".join(tiles)}</div>{follow}'
        f'<section class="docs"><h2>Contracts and reports</h2><ul>{docs}</ul></section>')


def html_page() -> str:
    tpl = sitenav.inject((ROOT / "templates" / "hub.html").read_text(encoding="utf-8"), "overview", prefix="")
    return sitenav.finish(tpl.replace("__BODY__", body(facts())))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--html", metavar="OUT", required=True)
    args = ap.parse_args()
    Path(args.html).parent.mkdir(parents=True, exist_ok=True)
    Path(args.html).write_text(html_page(), encoding="utf-8", newline="\n")
    print(f"Overview -> {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
