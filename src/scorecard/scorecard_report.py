"""Render the scorecard as Markdown (for people) and JSON (for tools and the app)."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime
from typing import Any

from scorecard.engine.core import fmt_t
from scorecard.kpi import ScoredIncident

NEEDS_ATTENTION = ("below_minimum", "deep_below_minimum")


def _plain(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, ScoredIncident):
        d = asdict(v)
        d.update({"measured_min": round(v.measured_min, 1), "engaged_min": None if v.engaged_min is None else round(v.engaged_min, 1),
                  "first_time_fix": v.first_time_fix})
        return _plain(d)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, float):
        return round(v, 4)
    return v


def scorecard_json(sc: dict[str, Any]) -> dict[str, Any]:
    return _plain(sc)


def _num(v: float | None, unit: str = "%", digits: int = 2) -> str:
    if v is None:
        return "n/a"
    if unit == "%":
        return f"{v:.{digits}f}%"
    return f"{v:g}{unit}"


def _money(v: float) -> str:
    return f"${v:,.0f}"


def _target(direction: str, v: float, unit: str) -> str:
    sym = "≥" if direction == "higher_is_better" else "≤"
    return f"{sym} {v:g}{unit}" if not (v == 100 and unit == "%" and direction == "higher_is_better") else "100%"


def _cell(s: Any) -> str:
    return str(s).replace("|", "/").replace("\n", " ")


def scorecard_markdown(sc: dict[str, Any]) -> str:
    csl = {r["id"]: r for r in sc["csl"]}
    weeks = sc["weeks"]
    t = sc["totals"]
    cr = sc["credits"]
    clean_weeks = sum(1 for w in weeks if w["vendor_note"].startswith("All SLAs met"))
    defaults = [r for r in sc["csl"] if r["status"] in NEEDS_ATTENTION]
    levels = Counter(e["level"] for e in sc["severity_log"])
    L: list[str] = []
    L += ["<!-- GENERATED FILE. DO NOT EDIT BY HAND. Run: python scripts/build_scorecard.py -->", "",
          "# Vendor SLA Scorecard", "",
          "> Synthetic data for a portfolio demonstration. All sites, people, serials, events, and commercial terms are fictional.", "",
          f"**Site:** {sc['site']}  ",
          f"**Supplier:** {sc['supplier']}  ",
          f"**Measurement period:** {fmt_t(sc['window']['start'])} to {fmt_t(sc['window']['end'])} ({len(weeks)} weeks)", "",
          "## Headline", "",
          f"The supplier's weekly reports claimed every SLA was met in {clean_weeks} of {len(weeks)} weeks"
          + (", reported only minor exceptions in the others," if clean_weeks < len(weeks) else ",")
          + " and raised no escalations. "
          f"Measured from the Telemetry of Record, the period has **{len(defaults)} Minimum Service Level Defaults** "
          f"({', '.join(r['id'] for r in defaults) or 'none'}), **{levels.get('S1', 0)} S1 items** in the severity log, "
          f"and **{_money(cr['payable'])} in Service Level Credits**"
          + (f" (capped from {_money(cr['uncapped'])})." if cr["capped"] else "."), "",
          f"Fleet availability looks almost identical either way ({_num(csl['CSL-01']['vendor_reported'], digits=3)} reported, "
          f"{_num(csl['CSL-01']['actual'], digits=3)} measured): a handful of hidden hours disappears inside "
          f"{t['tickets']} tickets on a 2,300-GPU hall. The gaps show up in restoration, repair quality, and record integrity, "
          "which is why the scorecard measures each incident, not just the average.", ""]

    L += ["## Vendor reported vs. measured", "",
          "| Service level | Vendor reported | Measured from telemetry | Gap |", "|---|:-:|:-:|:-:|"]
    for r in sc["csl"]:
        if r["vendor_reported"] is None:
            continue
        gap = r["actual"] - r["vendor_reported"] if r["actual"] is not None else None
        L.append(f"| {r['id']} {r['name']} | {_num(r['vendor_reported'])} | **{_num(r['actual'])}** | "
                 f"{'n/a' if gap is None else f'{gap:+.2f} pts'} |")
    L += ["", "Record integrity (CSL-11), repeat failures (CSL-08), deployment adherence (CSL-09), and worst-rack availability "
          "(CSL-12) do not appear in the supplier's report at all.", ""]

    L += ["## Critical Service Levels", "",
          "| ID | Service level | Expected | Minimum | Measured | Status | Credit | Basis |", "|---|---|:-:|:-:|:-:|---|--:|---|"]
    for r in sc["csl"]:
        status = f"**{r['status_text']}**" if r["status"] in NEEDS_ATTENTION else r["status_text"]
        L.append(f"| {r['id']} | {r['name']} | {_target(r['direction'], r['expected'], r['unit'])} | "
                 f"{_target(r['direction'], r['minimum'], r['unit'])} | {_num(r['actual'])} | {status} | "
                 f"{_money(r['credit']) if r['credit'] else '-'} | {_cell(r['detail'])}{('. ' + r['note']) if r['note'] else ''} |")
    L += ["", "## Service Level Credits", "",
          "| CSL | Credit | Calculation | Earnback eligible |", "|---|--:|---|:-:|"]
    for c in cr["items"]:
        L.append(f"| {c['csl']} | {_money(c['credit'])} | {c['explanation']} | {'Yes' if c['earnback_eligible'] else 'No'} |")
    L += [f"| **Total** | **{_money(cr['uncapped'])}** | | |",
          "", f"Payable after the monthly cap (the At-Risk Amount): **{_money(cr['payable'])}**."
          + (" The cap applied." if cr["capped"] else ""), ""]

    L += ["## Week by week", "",
          "| Week starting | Availability (vendor / measured) | P2 restore (vendor / measured) | First-time fix (vendor / measured) "
          "| Staffing (vendor / measured) | Findings | Vendor's note |", "|---|:-:|:-:|:-:|:-:|:-:|---|"]
    for w in weeks:
        v, m = w["vendor"], w["measured"]
        L.append(f"| {w['week_start'].strftime('%Y-%m-%d')} | {_num(v['CSL-01'], digits=3)} / {_num(m['CSL-01'], digits=3)} | "
                 f"{_num(v['CSL-04'], digits=1)} / **{_num(m['CSL-04'], digits=1)}** | {_num(v['CSL-06'], digits=1)} / "
                 f"**{_num(m['CSL-06'], digits=1)}** | {_num(v['CSL-10'], digits=1)} / {_num(m['CSL-10'], digits=1)} | "
                 f"{w['findings']} | {_cell(w['vendor_note'])} |")
    L.append("")

    L += ["## Corrective action plans", "",
          f"{len(sc['corrective_actions'])} plans drafted automatically: one per affected ticket group (or service level) for "
          "every S1 and S2 item. Due dates follow the severity index (S1: 5 business days, S2: 10).", "",
          "| CAP | Severity | Tickets | Triggers | Required actions | Owner | Due |", "|---|:-:|---|---|---|---|---|"]
    for c in sc["corrective_actions"]:
        L.append(f"| {c['id']} | {c['level']} | {', '.join(c['tickets']) or (c['unit'] or '-')} | "
                 f"{_cell('; '.join(c['triggers']))} | {_cell(' '.join(c['actions']))} | {c['owner']} | {c['due'].strftime('%Y-%m-%d')} |")
    L.append("")

    L += ["## Severity log", "",
          " · ".join(f"**{lvl}:** {levels.get(lvl, 0)}" for lvl in ("S1", "S2", "S3", "S4")), "",
          "| Severity | Kind | Reference | Tickets | What happened |", "|:-:|---|---|---|---|"]
    for e in sc["severity_log"]:
        L.append(f"| {e['level']} | {e['kind']} | {e['ref']} | {', '.join(e['tickets']) or '-'} | {_cell(e['title'])} |")
    L += ["", "Discrepancy details and evidence: [discrepancy_report.md](discrepancy_report.md).", ""]

    L += ["## Key Measurements", "",
          "| ID | Key measurement | Target | Measured | Result | Basis |", "|---|---|:-:|:-:|:-:|---|"]
    for k in sc["km"]:
        result = "n/a" if k["met"] is None else ("Met" if k["met"] else "**Missed**")
        measured = _num(k["actual"], k["unit"])
        L.append(f"| {k['id']} | {k['name']} | {_target(k['direction'], k['target'], k['unit'])} | "
                 f"{measured} | {result} | {_cell(k['detail'])} |")
    L += ["", "## Method", "",
          "- Every number above is computed from the Telemetry of Record by the reference implementation in `src/scorecard/`.",
          "- Restoration is measured per Ticket of Record from telemetry T0 to Validated RTS, with the ticket handling rules "
          "(TR-1 early failure, TR-2 reopen) applied, so split tickets count as one incident.",
          "- Engagement is badge-verified: the assigned technician's first badge-in to the hall after T0.",
          "- Availability uses capacity-weighted GPU-hours (degraded links count at 25%); deployment racks count from Validated Handoff.",
          "- Simplifications for the demo: the 4-week window is treated as the Measurement Period; no approved clock pauses "
          "exist in the data, so all lost capacity is Supplier-attributable; repeat-default history before the window is "
          "unknown, so no credit doubling applies; Key Measurements with no source data are marked n/a.", ""]
    return "\n".join(L).rstrip() + "\n"
