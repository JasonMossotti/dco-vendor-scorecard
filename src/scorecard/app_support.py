"""Logic behind the interactive app, kept free of Streamlit so it can be tested.

The app is a thin display layer over these functions:

* ``run_pipeline``: engine -> scorecard -> self-check, cached per dataset.
* ``run_landlord_pipeline``: the Landlord engine, its scorecard, and the IT scorecard without attribution.
* ``generate_month``: make a brand-new synthetic month in a temporary folder.
* ``*_rows``: plain list-of-dict tables the app turns into DataFrames.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from scorecard.builder import build_scorecard
from scorecard.connectors import FileConnector
from scorecard.engine import run_engine
from scorecard.engine.core import fmt_t
from scorecard.engine.evaluate import evaluate
from scorecard.sla_model import load_sla
from scorecard.synthetic import SiteGenerator, write_dataset

ROOT = Path(__file__).resolve().parents[2]
# The Incident Portal opens any ticket, change, or work order of the committed sample month.
PORTAL = "https://jasonmossotti.github.io/dco-vendor-scorecard/tickets/"


# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #
def portal_ids(data_dir: str | Path) -> frozenset[str]:
    """The record numbers the Incident Portal holds, when the app shows the month the portal covers (else none:
    a generated month reuses the same numbers for different records)."""
    from scorecard import tickets
    d = Path(data_dir)
    if not (d / "manifest.json").exists() or d.resolve() != (ROOT / "data" / "sample").resolve():
        return frozenset()
    return frozenset(tickets.ids(d))


def ticket_url(ref: str) -> str:
    return PORTAL + "#" + ref


def link_tickets(text: str, data_dir: str | Path) -> str:
    """Markdown with each ticket, change, or work order number linked to the Incident Portal."""
    from scorecard import tickets
    ids = portal_ids(data_dir)
    return tickets.ID_RE.sub(lambda m: f"[{m.group(0)}]({ticket_url(m.group(0))})" if m.group(0) in ids else m.group(0), text or "")


def portal_line(refs, data_dir: str | Path) -> str:
    """One line of links to the records a table names, or "" when there are none in the portal."""
    from scorecard import tickets
    ids = portal_ids(data_dir)
    found = sorted({m for r in refs for m in tickets.ID_RE.findall(str(r))} & ids)
    return ("Open in the Incident Portal: " + " · ".join(f"[{x}]({ticket_url(x)})" for x in found)) if found else ""


def link_column(rows: list[dict[str, Any]], col: str, data_dir: str | Path) -> bool:
    """Turn a one-number column into Incident Portal URLs (shown as the number by a link column). False: leave it."""
    ids = portal_ids(data_dir)
    if not ids or not rows or not all(not r[col] or r[col] in ids for r in rows):
        return False
    for r in rows:
        r[col] = ticket_url(r[col]) if r[col] else None
    return True


def available_datasets(root: Path = ROOT) -> dict[str, Path]:
    """Label -> dataset folder for the datasets shipped with the app."""
    out = {}
    sample = root / "data" / "sample"
    if (sample / "manifest.json").exists():
        out["Committed sample (Aug 31 to Sep 27, 2026)"] = sample
    latest = root / "data" / "latest"
    if (latest / "manifest.json").exists():
        w = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))["window"]
        out[f"Latest 4 weeks ({w['start'][:10]} to {w['end'][:10]}, refreshed weekly)"] = latest
    return out


def generate_month(seed: int, root: Path = ROOT, start: date | None = None) -> Path:
    """Generate a fresh 4-week dataset for ``seed`` into a temporary folder."""
    cfg = yaml.safe_load((root / "config" / "synthetic.yaml").read_text(encoding="utf-8"))
    if start is None:
        today = date.today()
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=cfg["weeks"])
    out = Path(tempfile.mkdtemp(prefix=f"month_{seed}_"))
    write_dataset(SiteGenerator(load_sla(), cfg, start=start, seed=seed).run(), out)
    return out


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=12)
def _run_cached(data_dir: str, sla_json: str):
    sla = json.loads(sla_json)
    result = run_engine(sla, FileConnector(data_dir))
    sc = build_scorecard(sla, result)
    has_key = (Path(data_dir) / "ground_truth" / "planted_discrepancies.json").exists()
    ev = evaluate(result.findings, data_dir) if has_key else None   # read only after the engine has finished
    return result, sc, ev


def run_pipeline(sla: dict[str, Any], data_dir: str | Path):
    """(engine result, scorecard, evaluation or None) for a dataset and SLA."""
    return _run_cached(str(data_dir), json.dumps(sla, sort_keys=True, default=str))


# --------------------------------------------------------------------------- #
# Tables for display
# --------------------------------------------------------------------------- #
def _pct(v: float | None, d: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{d}f}%"


def _round(v: float | None, d: int) -> float | None:
    return None if v is None else round(v, d)


def _threshold(direction: str, v: float) -> str:
    if direction == "higher_is_better" and v == 100:
        return "100%"
    return f"{'≥' if direction == 'higher_is_better' else '≤'} {v:g}%"


def headline(sc: dict[str, Any]) -> str:
    defaults = [r["id"] for r in sc["csl"] if r["status"] in ("below_minimum", "deep_below_minimum")]
    clean = sum(1 for w in sc["weeks"] if w["vendor_note"].startswith("All SLAs met"))
    cr = sc["credits"]
    s1 = sum(1 for e in sc["severity_log"] if e["level"] == "S1")
    return (f"The supplier's weekly reports claimed every SLA was met in {clean} of {len(sc['weeks'])} weeks. "
            f"Measured from telemetry: **{len(defaults)} Minimum defaults**"
            + (f" ({', '.join(defaults)})" if defaults else "")
            + f", **{s1} S1 items**, and **\\${cr['payable']:,.0f}** in credits"
            + (f" (capped from \\${cr['uncapped']:,.0f})." if cr["capped"] else "."))


def vendor_vs_measured_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Service level": f"{r['id']} {r['name']}", "Vendor reported (%)": _round(r["vendor_reported"], 2),
             "Measured (%)": _round(r["actual"], 2),
             "Gap (pts)": None if r["actual"] is None else round(r["actual"] - r["vendor_reported"], 2)}
            for r in sc["csl"] if r["vendor_reported"] is not None]


def csl_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"ID": r["id"], "Service level": r["name"],
             "Expected": _threshold(r["direction"], r["expected"]), "Minimum": _threshold(r["direction"], r["minimum"]),
             "Measured": _pct(r["actual"]), "Vendor reported": _pct(r["vendor_reported"]),
             "Status": r["status_text"], "Credit": f"${r['credit']:,.0f}" if r["credit"] else "",
             "Basis": r["detail"] + (f". {r['note']}" if r["note"] else "")} for r in sc["csl"]]


def km_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for k in sc["km"]:
        sym = "≥" if k["direction"] == "higher_is_better" else "≤"
        unit = k["unit"]
        val = "n/a" if k["actual"] is None else (_pct(k["actual"]) if unit == "%" else f"{k['actual']:g}{unit}")
        rows.append({"ID": k["id"], "Key measurement": k["name"], "Target": f"{sym} {k['target']:g}{unit}",
                     "Measured": val, "Result": "n/a" if k["met"] is None else ("Met" if k["met"] else "Missed"),
                     "Basis": k["detail"]})
    return rows


def weekly_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for w in sc["weeks"]:
        v, m = w["vendor"], w["measured"]
        out.append({"Week": w["week_start"].strftime("%Y-%m-%d"),
                    "P2 restore, vendor": _round(v["CSL-04"], 1), "P2 restore, measured": _round(m["CSL-04"], 1),
                    "First-time fix, vendor": _round(v["CSL-06"], 1), "First-time fix, measured": _round(m["CSL-06"], 1),
                    "Staffing, vendor": _round(v["CSL-10"], 1), "Staffing, measured": _round(m["CSL-10"], 1),
                    "Findings": w["findings"], "Vendor's note": w["vendor_note"]})
    return out


GAP_SERIES = {"P2 restore": "CSL-04", "First-time fix": "CSL-06", "Validated return to service": "CSL-07",
              "Staffing fill": "CSL-10"}


def weekly_gap_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    """Measured minus vendor-reported, in points, per week. 0 means the vendor's report was accurate;
    below 0 means the vendor overstated performance."""
    out = []
    for w in sc["weeks"]:
        row: dict[str, Any] = {"Week": w["week_start"].strftime("%Y-%m-%d")}
        for label, cid in GAP_SERIES.items():
            v, m = w["vendor"].get(cid), w["measured"].get(cid)
            row[label] = None if v is None or m is None else round(m - v, 1)
        out.append(row)
    return out


def incident_rows(sc: dict[str, Any], target_min: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for i in sc["incidents"]:
        tgt = target_min[i.priority]
        rows.append({"Ticket of Record": i.key, "Class": i.fault_class, "Priority": i.priority, "Unit": i.unit,
                     "Rack": i.rack, "T0": fmt_t(i.t0),
                     "Measured restore (hrs)": round(i.measured_min / 60, 2),
                     "Vendor restore (hrs)": round(sum(i.vendor_restore_min) / 60, 2),
                     "Target (hrs)": tgt / 60, "Within target": i.measured_min <= tgt,
                     "First-time fix": i.first_time_fix, "Validated": i.validated,
                     "Vendor tickets": ", ".join(i.tickets)})
    return rows


def cap_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"CAP": c["id"], "Severity": c["level"], "Tickets": ", ".join(c["tickets"]) or (c["unit"] or "-"),
             "Triggers": "; ".join(c["triggers"]), "Required actions": " ".join(c["actions"]),
             "Owner": c["owner"], "Raised": c["raised"].strftime("%Y-%m-%d"), "Due": c["due"].strftime("%Y-%m-%d"),
             "Status": c["status"]}
            for c in sc["corrective_actions"]]


def severity_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Severity": e["level"], "Kind": e["kind"], "Reference": e["ref"],
             "Tickets": ", ".join(e["tickets"]) or "-", "What happened": e["title"]} for e in sc["severity_log"]]


def evidence_rows(finding) -> list[dict[str, Any]]:
    return [{"Source": e["source"], "Time": fmt_t(e["at"]) if e["at"] else "-", "Evidence": e["detail"]}
            for e in finding.evidence]


# --------------------------------------------------------------------------- #
# Landlord and site views
# --------------------------------------------------------------------------- #
def has_facility(data_dir: str | Path) -> bool:
    return (Path(data_dir) / "facility").exists()


@lru_cache(maxsize=12)
def _landlord_cached(data_dir: str):
    from scorecard.engine import run_engine
    from scorecard.engine.evaluate import evaluate_landlord
    from scorecard.engine.landlord import build_landlord_scorecard, run_landlord
    from scorecard.sla_model import PARTNER_FILES
    sla = load_sla(PARTNER_FILES["landlord"])
    src = FileConnector(data_dir)
    result = run_landlord(sla, src)
    sc = build_landlord_scorecard(sla, result)
    key = Path(data_dir) / "ground_truth" / "facility_planted_discrepancies.json"
    ev = evaluate_landlord(result.findings, data_dir) if key.exists() else None
    it_sla = load_sla()
    it_plain = build_scorecard(it_sla, run_engine(it_sla, src, attribution=False))
    return result, sc, ev, it_plain


def run_landlord_pipeline(data_dir: str | Path):
    """(Landlord result, Landlord scorecard, evaluation or None, IT scorecard scored without attribution)."""
    return _landlord_cached(str(data_dir))


_LL_STATUS = {"met_expected": "Met Expected", "below_expected": "Below Expected (RCA)", "below_minimum": "Minimum default",
              "deep_below_minimum": "Minimum default", "not_applicable": "n/a (no events)"}


def landlord_headline(sc: dict[str, Any]) -> str:
    d = sc["defaults"]
    return (f"The Landlord's weekly reports claimed every service level was met. Measured from the Customer's read-only "
            f"facility telemetry: **{len(d)} Minimum defaults**" + (f" ({', '.join(d)})" if d else "")
            + f", **{sc['s1']} S1 findings**, and **\\${sc['credits']['payable']:,.0f}** in credits against rent.")


def landlord_csl_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"ID": r["id"], "Service level": r["name"], "Expected": _threshold(r["direction"], r["expected"]),
             "Minimum": _threshold(r["direction"], r["minimum"]), "Measured": _pct(r["actual"], 3),
             "Landlord reported": _pct(r["vendor_reported"]), "Status": _LL_STATUS[r["status"]],
             "Credit": f"${r['credit']:,.0f}" if r["credit"] else "", "Basis": r["detail"]} for r in sc["csl"]]


def landlord_vs_reported_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Service level": f"{r['id']} {r['name']}", "Landlord reported (%)": _round(r["vendor_reported"], 3),
             "Measured (%)": _round(r["actual"], 3),
             "Gap (pts)": None if r["actual"] is None else round(r["actual"] - r["vendor_reported"], 3)} for r in sc["csl"]]


def landlord_km_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for k in sc["km"]:
        sym = "≥" if k["direction"] == "higher_is_better" else "≤"
        unit = k["unit"].strip()
        noun = unit[:-1] if unit.endswith("s") and k["actual"] == 1 else unit
        val = "n/a" if k["actual"] is None else (_pct(k["actual"], 1) if unit == "%" else f"{k['actual']:g} {noun}")
        rows.append({"ID": k["id"], "Key measurement": k["name"], "Target": f"{sym} {k['target']:g}{'%' if unit == '%' else ' ' + unit}",
                     "Measured": val, "Result": "n/a" if k["met"] is None else ("Met" if k["met"] else "Missed"),
                     "Basis": k["detail"]})
    return rows


def attribution_display_rows(sc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"T0": fmt_t(r["t0"]), "Event": r["event"], "Owner (telemetry)": r["owner"], "Rule": r["rule"],
             "Rack capacity lost": "Yes" if r["capacity_lost"] else "No", "Work order": r["work_order"] or "",
             "Work order says": r["claimed_owner"] or "", "Agrees": "Yes" if r["agrees"] else "No"}
            for r in sc["attribution"]]


def site_rows(it_sc: dict[str, Any], ll_sc: dict[str, Any], it_ev, ll_ev) -> list[dict[str, Any]]:
    rows = [{"Measure": "Self-report", "IT Partner": "Every SLA met or minor exceptions", "Landlord": "Every SLA met"},
            {"Measure": "Minimum defaults (measured)", "IT Partner": str(it_sc["totals"]["defaults"]), "Landlord": str(len(ll_sc["defaults"]))},
            {"Measure": "Credits payable", "IT Partner": f"${it_sc['credits']['payable']:,.0f}",
             "Landlord": f"${ll_sc['credits']['payable']:,.0f} (against rent)"},
            {"Measure": "Findings (S1)", "IT Partner": f"{it_sc['totals']['findings']} ({it_sc['totals']['s1']})",
             "Landlord": f"{ll_sc['findings']} ({ll_sc['s1']})"}]
    if it_ev is not None and ll_ev is not None:
        rows.append({"Measure": "Engine self-check",
                     "IT Partner": f"{it_ev.detected} of {it_ev.planted}, {len(it_ev.false_positives)} false positives",
                     "Landlord": f"{ll_ev.detected} of {ll_ev.planted}, {len(ll_ev.false_positives)} false positives"})
    return rows


def crossing_outages(ll_sc: dict[str, Any], it_result) -> list[str]:
    """Plain-language account of each outage that crossed the demarcation."""
    out = []
    tickets = [t for t in it_result.context.tickets if t["category"] == "rack_facility"]
    for r in [x for x in ll_sc["attribution"] if x["capacity_lost"]]:
        t = next((x for x in tickets if r["unit"].endswith(x["rack"])), None)
        hours = (r["restored"] - r["t0"]).total_seconds() / 3600
        out.append(f"**{r['unit']} went dark for {hours:.1f} hours.** Both feeds were out at the tap-offs, on the Landlord's "
                   f"side of the demarcation, so the telemetry attributes it to the **{r['owner']}** ({r['rule']}). "
                   f"The IT Partner's clock started at the Landlord's handoff ({fmt_t(r['restored'])}, rule FA-3)"
                   + (f"; its ticket {t['number']} returned the rack to service at {fmt_t(t['resolved_at'])}." if t else "."))
    return out


def attribution_change_rows(it_sc: dict[str, Any], it_plain: dict[str, Any]) -> list[dict[str, Any]]:
    a = {c["id"]: c["actual"] for c in it_sc["csl"]}
    b = {c["id"]: c["actual"] for c in it_plain["csl"]}
    return [{"IT Partner": "Minimum defaults", "With attribution (contract)": str(it_sc["totals"]["defaults"]),
             "Without attribution": str(it_plain["totals"]["defaults"])},
            {"IT Partner": "Credits payable", "With attribution (contract)": f"${it_sc['credits']['payable']:,.0f}",
             "Without attribution": f"${it_plain['credits']['payable']:,.0f}"},
            {"IT Partner": "CSL-03 P1 restoration within 4 hours", "With attribution (contract)": _pct(a["CSL-03"], 1),
             "Without attribution": _pct(b["CSL-03"], 1)},
            {"IT Partner": "CSL-12 worst-rack availability", "With attribution (contract)": _pct(a["CSL-12"], 3),
             "Without attribution": _pct(b["CSL-12"], 3)}]


# --------------------------------------------------------------------------- #
# Codes: what they mean (the static pages show this in a popup; the app in a lookup box)
# --------------------------------------------------------------------------- #
def _md(s: str) -> str:
    """Glossary text, safe for st.markdown (a $ would start LaTeX)."""
    return s.replace("$", "\\$")


def explain_refs(refs: list[str], page: str = "scorecards") -> str:
    """'CSL-07 (Validated Return to Service), CSL-11 (Record Integrity)': each code with its meaning."""
    from scorecard import glossary
    gl = glossary.load()
    out = []
    for r in refs:
        found = gl.lookup(r, page)
        out.append(f"{r} ({_md(found[0].senses[0].title if not found[0].expansion else found[0].expansion)})" if found else r)
    return ", ".join(out)


def lookup_lines(query: str, page: str = "scorecards", limit: int = 12) -> list[str]:
    """Markdown for the app's "Look up a code" box: the meaning of an exact code or ID, or the codes that match."""
    from scorecard import glossary
    q = (query or "").strip()
    if not q:
        return ["Type a code or ID from any table, such as CSL-07, TR-1, FA-5, OT-KM-03, or INC3100816. "
                "The Glossary tab lists them all."]
    gl = glossary.load()
    labels = {t["key"]: t["label"] for t in glossary.config()["types"]}
    found = gl.lookup(q.upper(), page) or gl.lookup(q, page)
    if found:
        lines = []
        for e in found:
            d = glossary.entry_data(e)
            head = f"**{_md(q.upper() if e.pattern else e.term)}** · {labels.get(e.type, e.type)}"
            if e.expansion:
                head += f" · {_md(e.expansion)}"
            lines.append(head)
            for s in d["senses"]:
                text = (f"**{_md(s['title'])}.** " if s["title"] and s["title"] != e.expansion else "") + _md(s["text"])
                where = "; ".join(f"{w['doc']}, {w['section']}" for w in s["where"])
                lines.append(text + (f" *Defined in {_md(where)} (Agreements tab).*" if where else ""))
            if e.source:
                lines.append(f"*Source: [{_md(e.source['label'])}]({e.source['href']}).*")
        return lines
    ql = q.lower()
    hits = [e for e in gl.entries() if ql in e.term.lower() or ql in e.title.lower()][:limit]
    if not hits:
        return [f"No code or ID matches “{_md(q)}”. Check the Glossary tab."]
    return ["Matching codes:"] + [f"- **{_md(e.term)}** · {_md(e.title)}" for e in hits]


@lru_cache(maxsize=1)
def _site_drawings() -> tuple[dict, dict]:
    """The location entries and the drawings, built from site/site.yaml (the bundle carries no SVG files)."""
    from scorecard import locations, site_model
    from scorecard.site_drawings import sheets
    site = site_model.load_site()
    return locations.build(site), {num: svg for num, _, _, svg in sheets(site)}


def location_view(query: str) -> dict[str, Any] | None:
    """For the lookup box: when the query names a rack, room, or piece of equipment, what it is and each
    drawing that shows it, highlighted (title, sheet label, SVG). A query that names a part ("CDU-B3 pump 2",
    "a23-ct18") shows the equipment detail sheet first. None when it names no location."""
    from scorecard import locations
    q = (query or "").strip()
    if not q:
        return None
    data, svgs = _site_drawings()
    for text in (q, q.upper()):
        hit = locations.resolve_field(data, text)
        if hit:
            break
    if not hit:
        return None
    name, note = hit
    e = data["entries"][name]
    part = locations.resolve_field_part(data, text)
    title, views = locations.card(data, name, part)
    return {"name": name, "title": title, "kind": locations.KIND_LABEL[e["kind"]],
            "text": (note + ". " if note and not part else "") + e["text"],
            "views": [(f"{v['s']} {data['sheets'][v['s']]['title']}", locations.highlighted_svg(data, svgs[v["s"]], v, label))
                      for v, label in views]}


@lru_cache(maxsize=1)
def _device_directory() -> dict:
    """The device directory, built from the site model and the IT Partner SLA (the bundle carries no docs/site/)."""
    from scorecard import devices, site_model
    from scorecard.sla_model import load_sla
    data, _ = _site_drawings()
    return devices.build(site_model.load_site(), load_sla(ROOT / "sla" / "it_partner.yaml")["site"], data["entries"])


def device_lines(query: str) -> list[str]:
    """For the lookup box: when the query names a device (leaf-a07-r1 port 18, a13-ct18, CDU-B3, Rack A07),
    its description and what it connects to, as the code popups show them. Empty when it names no device."""
    from scorecard import devices
    q = (query or "").strip()
    if not q:
        return []
    data = _device_directory()
    for text in (q, q.upper(), q.lower()):
        e = devices.lookup(data, text)
        if e:
            break
    if not e:
        return []
    lines = [f"**This device** · {_md(data['kinds'][e['kind']])}" + (f" · {_md(e['title'])}" if e.get("title") else ""),
             _md(e["text"]), "**Connected to**"]
    lines += [f"- {_md(rel)}: " + (f"**{_md(n)}** " if n else "") + _md(note) for rel, n, note in e["conn"]]
    return lines
