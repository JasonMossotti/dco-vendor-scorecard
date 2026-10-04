#!/usr/bin/env python3
"""Render the site's contracts: the IT Partner SLA, the Landlord SLA, and the Interface Agreement.

Usage:
    python scripts/render_sla.py            # validate + write docs/sla/*.md
    python scripts/render_sla.py --check    # fail if any document is out of date (used in CI)

Each partner SLA is rendered as a self-contained document that includes the
common terms, because each partner signs only its own contract.

The worked examples in Appendix B are computed with the same functions the
scorecard uses, so the document can never drift from the scoring engine.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datetime import datetime, timedelta, timezone  # noqa: E402

from scorecard.measurement import Outage, build_tickets_of_record  # noqa: E402
from scorecard.sla_model import (  # noqa: E402
    HIGHER,
    at_risk_amount,
    cap_monthly_credits,
    classify_event_breach,
    classify_period_breach,
    compute_credit,
    compute_ehs_credits,
    evaluate_csl,
    load_interface_agreement,
    load_sla,
    sla_sources,
)

SLA_PATH = ROOT / "sla" / "it_partner.yaml"
OT_PATH = ROOT / "sla" / "ot_partner.yaml"
IA_PATH = ROOT / "sla" / "interface_agreement.yaml"
DOC_DIR = ROOT / "docs" / "sla"
IT_NUM = {"measurement": 6, "credits": 14, "excused": 16, "rca": 17, "governance": 18, "security": 21, "ehs": 22,
          "change_control": 24, "ehs_example": "B.4"}
OT_NUM = {"measurement": 5, "credits": 12, "excused": 14, "rca": 15, "governance": 16, "security": 19, "ehs": 20,
          "change_control": 22, "ehs_example": "B.2"}
TEMPLATE_DIR = ROOT / "templates"


# --------------------------------------------------------------------------- #
# Template filters
# --------------------------------------------------------------------------- #
def fmt_duration(minutes: float | None) -> str:
    """240 -> '4 hrs', 15 -> '15 min', 7200 -> '5 days'."""
    if minutes is None:
        return "n/a"
    minutes = float(minutes)
    if minutes < 60:
        return f"{minutes:g} min"
    if minutes % 1440 == 0 and minutes >= 2880:
        return f"{minutes / 1440:g} days"
    hours, mins = divmod(round(minutes), 60)
    hrs = f"{hours} hr" if hours == 1 else f"{hours} hrs"
    return hrs if mins == 0 else f"{hrs} {mins} min"


def fmt_target(item: dict, value: float) -> str:
    unit = item.get("unit", "")
    if item["direction"] == HIGHER and value == 100 and unit == "%":
        return "100%"
    symbol = "≥" if item["direction"] == HIGHER else "≤"
    return f"{symbol} {value:g}{unit}"


def ticket_handling_examples(sla: dict) -> dict:
    """Appendix B.3: one repair that refaults at different times, run through the
    reference implementation of TR-1, TR-2, and TR-5."""
    fc = next(f for f in sla["measurement_spec"] if f["id"] == "FC-GPU")
    target = next(p for p in sla["priorities"] if p["id"] == fc["default_priority"])["restore_min"]
    first, second = 420, 180          # 7 hrs, then 3 hrs
    t0 = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)
    rts1 = t0 + timedelta(minutes=first)
    gaps = [
        ("10 minutes", timedelta(minutes=10)),
        ("6 hours", timedelta(hours=6)),
        ("3 days", timedelta(days=3)),
        ("10 days", timedelta(days=10)),
    ]
    rows = []
    for label, gap in gaps:
        t1 = rts1 + gap
        outages = [Outage("a14-ct07", t0, rts1, ("INC-1",)), Outage("a14-ct07", t1, t1 + timedelta(minutes=second), ("INC-2",))]
        tors = build_tickets_of_record(sla, "FC-GPU", outages, as_of=t1 + timedelta(days=30))
        tor = tors[0]
        if tor.early_failures:
            rule = "TR-1"
        elif tor.reopens:
            rule = "TR-2"
        elif tors[1].parent_index == 0:
            rule = "TR-5"
        else:
            rule = "New ticket"
        merged = rule in ("TR-1", "TR-2")
        measured = tor.measured_restore_min
        sev = classify_event_breach(sla, target, measured, fc["capacity_impact"]["gpus"])
        rows.append({
            "gap_label": label,
            "rule": rule,
            "vendor_view": (f"Two tickets: {fmt_duration(first)} and {fmt_duration(second)}, both on time"
                            if merged else "Two separate tickets (correct)"),
            "measured": measured,
            "met": measured <= target,
            "severity": f"{sev.level} {sev.name}" if sev.level else "None",
            "ftf": tor.first_time_fix,
        })
    return {"tr_examples": rows, "tr_first": first, "tr_second": second, "tr_target": target,
            "tr_target_label": f"{fc['default_priority']} {fc['name']}"}


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #
def severity_table(sla: dict) -> list[dict]:
    """Collapse band definitions into one row per level for the document."""
    dims = sla["breach_severity"]["event_dimensions"]
    rows = {lvl["id"]: {"level": f"{lvl['id']} {lvl['name']}"} for lvl in sla["breach_severity"]["levels"]}

    def ranges(bands: list[dict], suffix: str, fmt=lambda v: f"{v:,g}") -> dict[str, str]:
        out, lower = {}, 0
        for b in bands:
            if b["max"] is None:
                out[b["level"]] = f"> {fmt(lower)}{suffix}"
            elif lower == 0:
                out[b["level"]] = f"≤ {fmt(b['max'])}{suffix}"
            else:
                out[b["level"]] = f"{fmt(lower)} to {fmt(b['max'])}{suffix}"
            lower = b["max"] if b["max"] is not None else lower
        return out

    over = ranges(dims["overrun_pct"]["bands"], "%")
    gpuh = ranges(dims["gpu_hours_beyond_target"]["bands"], "")
    ordered = sorted(sla["breach_severity"]["levels"], key=lambda lvl: lvl["rank"])
    table = []
    for lvl in ordered:
        row = rows[lvl["id"]]
        row["overrun"] = over.get(lvl["id"], "")
        row["gpu_hours"] = gpuh.get(lvl["id"], "")
        table.append(row)
    return table


def base_context(sla: dict) -> dict:
    """Context every partner document shares: parties, measurement, severity, EHS."""
    charges = sla["commercial"]["monthly_charges"]
    ehs_classes = [dict(vc, dollars=charges * vc["credit_pct_of_monthly_charges"] / 100)
                   for vc in sla["ehs"]["violation_classes"]]
    ehs_specs = [
        ("EHS-1", "EHS-C1", "2026-10-06", False, False, "busway tap-off worked with no lockout applied"),
        ("EHS-2", "EHS-C1", "2026-11-17", True, False, "energized work permit without the second person, self-reported"),
        ("EHS-3", "EHS-C2", "2026-12-01", False, True, "expired qualification, roster altered to hide it"),
    ]
    notes = {vid: note for vid, _, _, _, _, note in ehs_specs}
    rows = compute_ehs_credits(sla, [{"id": vid, "class": cls, "confirmed": day, "self_reported": sr, "concealed": cc}
                                     for vid, cls, day, sr, cc, _ in ehs_specs])
    return {
        "sla": sla, "d": sla["document"], "p": sla["parties"], "s": sla["site"], "c": sla["commercial"],
        "m": sla["measurement"], "sev": sla["breach_severity"], "sev_table": severity_table(sla),
        "categories": {cat["id"]: cat["name"] for cat in sla["performance_categories"]},
        "total_alloc": sum(x["credit_allocation_pct"] for x in sla["critical_service_levels"]),
        "at_risk": at_risk_amount(sla), "ehs_classes": ehs_classes,
        "ehs_example": {"rows": [dict(vars(x), note=notes[x.violation_id]) for x in rows],
                        "total": sum(x.amount for x in rows)},
        "ia": load_interface_agreement(IA_PATH),
    }


def landlord_context(sla: dict) -> dict:
    ctx = base_context(sla)
    ctx["num"] = OT_NUM
    ctx["credit_examples"] = [
        {"title": "Single default: OT-CSL-03 (cooling within band) misses Minimum once",
         "result": compute_credit(sla, "OT-CSL-03", 1)},
        {"title": "Integrity-aggravated default: OT-CSL-06 (maintenance) misses Minimum after generator tests were reported without load",
         "result": compute_credit(sla, "OT-CSL-06", 1, aggravators=["AGG-INTEGRITY"])},
    ]
    bad = [compute_credit(sla, cid, 1) for cid in ("OT-CSL-01", "OT-CSL-03", "OT-CSL-05", "OT-CSL-06", "OT-CSL-08")]
    uncapped, payable, _ = cap_monthly_credits(sla, bad)
    ctx["cap_example"] = {"uncapped": uncapped, "payable": payable, "pct_of_ara": round(uncapped / ctx["at_risk"] * 100)}
    return ctx


def build_context(sla: dict) -> dict:
    site = sla["site"]
    tray = site["per_rack"]["gpus_per_compute_tray"]
    rack = site["per_rack"]["gpus"]
    cdu_loop = rack * site["cooling"]["racks_per_cdu"]
    p1 = next(p for p in sla["priorities"] if p["id"] == "P1")["restore_min"]
    p2 = next(p for p in sla["priorities"] if p["id"] == "P2")["restore_min"]

    credit_examples = [
        {"title": "Single default: CSL-03 (P1 restoration) misses Minimum once",
         "result": compute_credit(sla, "CSL-03", 1)},
        {"title": "Repeat default: CSL-03 misses Minimum for the 3rd consecutive month",
         "result": compute_credit(sla, "CSL-03", 3)},
        {"title": "Integrity-aggravated default: CSL-11 (Record Integrity) misses Minimum",
         "result": compute_credit(sla, "CSL-11", 1, aggravators=["AGG-INTEGRITY"])},
    ]

    bad_month = ["CSL-01", "CSL-03", "CSL-06", "CSL-07", "CSL-11"]
    bad_credits = [compute_credit(sla, cid, 1) for cid in bad_month]
    uncapped, payable, _ = cap_monthly_credits(sla, bad_credits)
    ara = at_risk_amount(sla)
    cap_example = {
        "title": f"A severe month with Minimum defaults on {', '.join(bad_month)}",
        "uncapped": uncapped,
        "payable": payable,
        "pct_of_ara": round(uncapped / ara * 100),
    }

    sev_specs = [
        ("P2 compute tray restored 40 min late", p2, p2 + 40, tray, []),
        ("P2 tray late, same tray failed 2 weeks ago", p2, p2 * 1.5, tray, ["AGG-REPEAT"]),
        ("P1 rack outage restored at 8 hrs", p1, p1 * 2, rack, ["AGG-RACKWIDE"]),
        ("P2 tray late; ticket claims swap but serial unchanged", p2, p2 + 120, tray, ["AGG-INTEGRITY"]),
        ("P1 row outage (8 racks) restored at ~18 hrs", p1, 1100, cdu_loop, ["AGG-RACKWIDE"]),
    ]
    severity_examples = [
        {"title": t, "target": tgt, "actual": act, "gpus": g, "aggs": a,
         "result": classify_event_breach(sla, tgt, act, g, a)}
        for t, tgt, act, g, a in sev_specs
    ]

    period_specs = [
        ("CSL-01 availability, single month", "CSL-01", 99.3, 1, []),
        ("CSL-06 first-time fix, single month", "CSL-06", 87.0, 1, []),
        ("CSL-01 availability, single month", "CSL-01", 98.2, 1, []),
        ("CSL-10 staffing fill, 3rd consecutive Minimum default", "CSL-10", 94.0, 3, []),
    ]
    period_examples = []
    for title, cid, actual, consec, aggs in period_specs:
        res = evaluate_csl(sla, cid, actual)
        period_examples.append({
            "title": title,
            "actual": f"{actual:g}%",
            "result": classify_period_breach(sla, res, consec, aggs),
        })

    return {
        **base_context(sla),
        "num": IT_NUM,
        "d": sla["document"],
        "p": sla["parties"],
        "s": site,
        "c": sla["commercial"],
        "m": sla["measurement"],
        "sev": sla["breach_severity"],
        "categories": {cat["id"]: cat["name"] for cat in sla["performance_categories"]},
        "total_racks": sum(h["racks"] for h in site["halls"]),
        "total_gpus": sum(h["racks"] for h in site["halls"]) * rack,
        "total_alloc": sum(x["credit_allocation_pct"] for x in sla["critical_service_levels"]),
        "at_risk": ara,
        "sev_table": severity_table(sla),
        "credit_examples": credit_examples,
        "cap_example": cap_example,
        "severity_examples": severity_examples,
        "period_examples": period_examples,
        "th": sla["ticket_handling"],
        "ms": sla["measurement_spec"],
        "ca": sla["capacity_accounting"],
        **ticket_handling_examples(sla),
    }


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,  # a typo in the template fails loudly
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    env.filters["dur"] = fmt_duration
    env.filters["target"] = fmt_target
    return env


def _tidy(text: str) -> str:
    """Collapse runs of blank lines left by template control blocks."""
    lines, out, blank = text.splitlines(), [], 0
    for line in lines:
        blank = blank + 1 if not line.strip() else 0
        if blank <= 1:
            out.append(line.rstrip())
    return "\n".join(out).strip() + "\n"


def render(sla_path: Path = SLA_PATH) -> str:
    """The IT Partner SLA."""
    sla = load_sla(sla_path)  # raises SLAValidationError if the SLA is inconsistent
    return _tidy(_env().get_template("it_partner.md.j2").render(src=sla_sources(sla_path), **build_context(sla)))


def render_landlord(sla_path: Path = OT_PATH) -> str:
    sla = load_sla(sla_path)
    return _tidy(_env().get_template("landlord.md.j2").render(src=sla_sources(sla_path), **landlord_context(sla)))


def render_interface(ia_path: Path = IA_PATH) -> str:
    ia = load_interface_agreement(ia_path)
    common = load_sla(SLA_PATH)            # party names and EHS references come from the common terms
    names = {k: v["name"] for k, v in common["parties"].items()}
    return _tidy(_env().get_template("interface_agreement.md.j2").render(ia=ia, names=names, parties=common["parties"]))


def outputs() -> dict[Path, str]:
    return {DOC_DIR / "IT_PARTNER_SLA.md": render(), DOC_DIR / "LANDLORD_SLA.md": render_landlord(),
            DOC_DIR / "INTERFACE_AGREEMENT.md": render_interface()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any rendered document is stale")
    args = ap.parse_args()
    docs = outputs()
    if args.check:
        stale = [p for p, t in docs.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        for p in stale:
            print(f"{p.relative_to(ROOT)} is out of date. Run: python scripts/render_sla.py")
        if not stale:
            print(f"docs/sla/ is up to date ({len(docs)} documents).")
        return 1 if stale else 0
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    for p, t in docs.items():
        p.write_text(t, encoding="utf-8", newline="\n")
        print(f"Wrote {p.relative_to(ROOT)} ({len(t.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
