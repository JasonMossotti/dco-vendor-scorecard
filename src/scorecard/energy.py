"""PUE report for Site AUS-1: power usage effectiveness from the meters, checked against the Landlord's report.

Facts come from the meters (``data/energy/``, see ``scorecard.synthetic.energy``):

* **PUE** = total facility energy / IT energy, both measured as energy over the period (ISO/IEC
  30134-2:2026). Total facility energy is what the utility and the generators delivered to the site;
  IT energy is measured at the UPS outputs.
* **Partial PUE** splits the overhead: cooling (chillers, facility water pumps, CDUs and thermal walls on
  the mechanical UPS, electrical-room CRAHs) and the power path (UPS losses plus unmetered distribution
  losses). House load (offices, lighting, security) is the rest. The three add up: PUE = 1 + cooling/IT +
  power/IT + other/IT.

The checks (each a finding means the records do not reconcile, not that anyone misled):

* ``report_mismatch``: the Landlord's monthly report differs from the meters by more than rounding. The
  check also names the likely preparation error by recomputing the figure the common ways it goes wrong.
* ``free_cooling_lockout``: a chiller's free cooling stayed disabled longer than the Landlord SLA allows
  (OT-EN-03) without a change record. The extra energy in the hours the weather allowed free cooling is
  estimated with the plant model (labelled as an estimate).
* ``unmetered_share``: the facility meters and the sub-meters disagree by more than distribution losses
  explain (a meter fault or an unmetered load).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scorecard.synthetic import energy as E

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "energy"
HALLS = ("a", "b")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
@dataclass
class EnergyData:
    meters: list[dict[str, Any]]
    events: list[dict[str, Any]]
    report: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)
    key: dict[str, Any] | None = None

    @property
    def start(self) -> datetime:
        return E.parse(self.report["period"]["start"])

    @property
    def end(self) -> datetime:
        return E.parse(self.report["period"]["end"])


def _rows(text: str) -> list[dict[str, Any]]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        out.append({k: (v if k in ("hour", "date") else float(v)) for k, v in r.items()})
    return out


def load(path: str | Path = DATA) -> EnergyData:
    p = Path(path)
    read = lambda name: (p / name).read_text(encoding="utf-8")   # noqa: E731
    hist = p / "history_daily.csv"
    key = p / "answer_key.json"
    return EnergyData(
        meters=_rows(read("meters_hourly.csv")),
        events=[json.loads(x) for x in read("chiller_events.jsonl").splitlines() if x.strip()],
        report=json.loads(read("landlord_energy_report.json")),
        history=_rows(hist.read_text(encoding="utf-8")) if hist.exists() else [],
        key=json.loads(key.read_text(encoding="utf-8")) if key.exists() else None,
    )


# --------------------------------------------------------------------------- #
# The numbers
# --------------------------------------------------------------------------- #
def totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Energy by category over ``rows`` (hourly meter rows), and the ratios."""
    s = {m: sum(r[m] for r in rows) for m in E.METERS}
    facility = s["utility_kwh"] + s["generator_kwh"]
    it = sum(s[f"ups_out_{h}_kwh"] for h in HALLS)
    ups_loss = sum(s[f"ups_in_{h}_kwh"] - s[f"ups_out_{h}_kwh"] for h in HALLS)
    cooling = s["chillers_kwh"] + s["pumps_kwh"] + s["crah_kwh"] + sum(s[f"mech_{h}_kwh"] for h in HALLS)
    other = s["house_kwh"]
    submetered = sum(s[f"ups_in_{h}_kwh"] for h in HALLS) + cooling + other
    unmetered = facility - submetered
    power = ups_loss + unmetered
    out = {"facility_kwh": facility, "it_kwh": it, "cooling_kwh": cooling, "power_loss_kwh": power, "ups_loss_kwh": ups_loss,
           "unmetered_kwh": unmetered, "other_kwh": other, "utility_kwh": s["utility_kwh"], "generator_kwh": s["generator_kwh"],
           "hours": len(rows)}
    out.update(ratios(out))
    if rows:
        out["outdoor_c"] = sum(r["outdoor_c"] for r in rows) / len(rows)
    return out


def ratios(t: dict[str, float]) -> dict[str, float]:
    it = t["it_kwh"]
    if not it:
        return {"pue": None, "ppue_cooling": None, "ppue_power": None, "other_per_it": None}
    return {"pue": t["facility_kwh"] / it, "ppue_cooling": (it + t["cooling_kwh"]) / it,
            "ppue_power": (it + t["power_loss_kwh"]) / it, "other_per_it": t["other_kwh"] / it}


def weeks(d: EnergyData) -> list[dict[str, Any]]:
    """The month's four weeks (the weekly pack's weeks: seven days from the window start, UTC)."""
    out, ws = [], d.start
    while ws < d.end:
        we = min(ws + timedelta(days=7), d.end)
        rows = [r for r in d.meters if ws <= E.parse(r["hour"]) < we]
        out.append({"start": E.iso(ws), "end": E.iso(we), **totals(rows)})
        ws = we
    return out


def days(d: EnergyData) -> list[dict[str, Any]]:
    """Daily PUE for the month, by UTC day (the month and its weeks start at midnight UTC)."""
    by: dict[str, list] = {}
    for r in d.meters:
        by.setdefault(r["hour"][:10], []).append(r)
    return [{"date": k, **totals(v)} for k, v in sorted(by.items())]


def periods(d: EnergyData) -> list[dict[str, Any]]:
    """The 12 four-week periods before the month (from the history) and the month itself."""
    out = []
    for i in range(0, len(d.history), 28):
        chunk = d.history[i:i + 28]
        t = {k: sum(r[k] for r in chunk) for k in ("facility_kwh", "it_kwh", "cooling_kwh", "power_loss_kwh", "other_kwh")}
        t.update(ratios(t))
        out.append({"start": chunk[0]["date"], "end": chunk[-1]["date"], "outdoor_c": sum(r["outdoor_c"] for r in chunk) / len(chunk),
                    "month": False, **t})
    m = totals(d.meters)
    out.append({"start": d.start.date().isoformat(), "end": (d.end - timedelta(hours=1)).date().isoformat(),
                "month": True, **{k: m[k] for k in ("facility_kwh", "it_kwh", "cooling_kwh", "power_loss_kwh", "other_kwh",
                                                    "pue", "ppue_cooling", "ppue_power", "other_per_it", "outdoor_c")}})
    return out


def year(d: EnergyData) -> dict[str, Any] | None:
    """PUE over the 52 weeks ending with the month: the figure the standard reports."""
    ps = periods(d)
    if len(ps) < 13:
        return None
    t = {k: sum(p[k] for p in ps) for k in ("facility_kwh", "it_kwh", "cooling_kwh", "power_loss_kwh", "other_kwh")}
    t.update(ratios(t))
    return {"start": ps[0]["start"], "end": ps[-1]["end"], "days": 28 * len(ps), **t}


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    id: str
    type: str
    title: str
    summary: str
    refs: list[str]
    evidence: list[str]
    known: str                      # when the records first allowed the finding (UTC)
    extra_kwh: float | None = None
    extra_usd: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def report_variants(t: dict[str, float]) -> dict[str, tuple[float, float]]:
    """(facility kWh, IT kWh) the way the standard asks, and the common ways a report gets them wrong."""
    ups_in = t["it_kwh"] + t["ups_loss_kwh"]
    return {"none": (t["facility_kwh"], t["it_kwh"]),
            "ups_input_as_it": (t["facility_kwh"], ups_in),
            "house_omitted": (t["facility_kwh"] - t["other_kwh"], t["it_kwh"]),
            "generator_omitted": (t["utility_kwh"], t["it_kwh"])}


EXPLAIN = {
    "ups_input_as_it": "IT energy was taken at the UPS inputs, so UPS losses were counted as IT load; the standard "
                       "measures IT energy at the UPS outputs and counts the losses as facility overhead",
    "house_omitted": "the house panel (offices, lighting, security) was left out of total facility energy; the standard "
                     "counts every load the site's meters serve",
    "generator_omitted": "generator energy delivered during the utility outage was left out; total facility energy "
                         "includes every source that served the site",
}


def check_report(d: EnergyData, t: dict[str, float], cfg: dict[str, Any]) -> Finding | None:
    c = cfg["checks"]
    rep = d.report
    fac, it = rep["total_facility_kwh"], rep["it_kwh"]
    ok = (abs(fac - t["facility_kwh"]) <= c["kwh_tolerance"] and abs(it - t["it_kwh"]) <= c["kwh_tolerance"]
          and abs(rep["pue"] - t["pue"]) <= c["pue_tolerance"])
    if ok:
        return None
    variants = report_variants(t)
    cause = next((k for k, (f, i) in variants.items() if k != "none"
                  and abs(fac - f) <= c["kwh_tolerance"] and abs(it - i) <= c["kwh_tolerance"]), None)
    why = EXPLAIN.get(cause, "the difference does not match a common preparation error; the Landlord should show its meter list")
    summary = (f"The Landlord reported PUE {rep['pue']:.3f} for the month; the meters give {t['pue']:.3f}. "
               f"Reported total facility energy {fac / 1000:,.1f} MWh against {t['facility_kwh'] / 1000:,.1f} MWh metered; "
               f"reported IT energy {it / 1000:,.1f} MWh against {t['it_kwh'] / 1000:,.1f} MWh metered. Likely cause: {why}.")
    return Finding("EN-F1", "report_mismatch", "Monthly energy report does not reconcile with the meters", summary,
                   ["OT-EN-01", "OT-EN-02"],
                   ["landlord_energy_report.json", "meters_hourly.csv: utility, generator, UPS output, and sub-meter totals"],
                   E.iso(d.end), detail={"reported_pue": rep["pue"], "metered_pue": t["pue"], "cause": cause,
                                         "reported_facility_kwh": fac, "reported_it_kwh": it})


def lockouts(d: EnergyData) -> list[dict[str, Any]]:
    """Each spell of free cooling disabled on a chiller: start, end (or the month end), and the records."""
    out: list[dict[str, Any]] = []
    open_: dict[str, dict] = {}
    for e in sorted(d.events, key=lambda e: (e["timestamp"], e["chiller"])):
        if e["event"] == "Free cooling disabled":
            open_[e["chiller"]] = e
        elif e["chiller"] in open_:
            s = open_.pop(e["chiller"])
            out.append({"chiller": e["chiller"], "start": s["timestamp"], "end": e["timestamp"], "disabled_by": s, "enabled_by": e})
    for ch, s in open_.items():
        out.append({"chiller": ch, "start": s["timestamp"], "end": E.iso(d.end), "disabled_by": s, "enabled_by": None})
    return sorted(out, key=lambda x: x["start"])


def lockout_cost(d: EnergyData, spell: dict[str, Any], cfg: dict[str, Any], plant: E.Plant) -> tuple[float, int]:
    """Estimated extra chiller energy over the spell (plant model, this hour's heat and weather), and the
    hours in it when the weather allowed free cooling."""
    s, e = E.parse(spell["start"]), E.parse(spell["end"])
    extra, hours = 0.0, 0
    one = lambda: 1.0   # noqa: E731
    for r in d.meters:
        t = E.parse(r["hour"])
        if not (s <= t + timedelta(minutes=30) < e):
            continue
        if plant.free_fraction(r["outdoor_c"]) > 0:
            hours += 1
        it = {h.upper(): r[f"ups_out_{h}_kwh"] for h in HALLS}
        mech = {h.upper(): r[f"mech_{h}_kwh"] * plant.mups_eff[h.upper()] for h in HALLS}
        lh = E.local(t).hour
        extra += plant.hour(r["outdoor_c"], it, mech, 1, lh, one)["chillers_kwh"] - plant.hour(r["outdoor_c"], it, mech, 0, lh, one)["chillers_kwh"]
    return extra, hours


def check_lockouts(d: EnergyData, cfg: dict[str, Any], plant: E.Plant) -> list[Finding]:
    out = []
    limit = timedelta(hours=cfg["checks"]["lockout_hours"])
    for sp in lockouts(d):
        dur = E.parse(sp["end"]) - E.parse(sp["start"])
        if dur <= limit:
            continue
        extra, hours = lockout_cost(d, sp, cfg, plant)
        note = sp["disabled_by"].get("note", "")
        days_ = dur.total_seconds() / 86400
        usd = extra * cfg["tariff_usd_per_kwh"]
        closed = "re-enabled by the BMS" if sp["enabled_by"] else "still disabled at the month end"
        summary = (f"Free cooling on {sp['chiller']} was disabled at {sp['start'][:16].replace('T', ' ')} UTC ({note}) and stayed "
                   f"off for {days_:.1f} days ({closed}), with no change record covering it. The work record closed the task "
                   f"while the BMS still showed the local override. " + (
                       f"{hours} of those hours were cool enough for free cooling; the plant model estimates "
                       f"{extra / 1000:,.1f} MWh of extra chiller energy (about ${usd:,.0f})." if hours else
                       "No hour in it was cool enough for free cooling, so it cost no energy this time."))
        out.append(Finding(f"EN-F{len(out) + 2}", "free_cooling_lockout", f"Free cooling left disabled on {sp['chiller']}",
                           summary, ["OT-EN-03"], ["chiller_events.jsonl", "landlord/pm_records.csv: " + note.split(" ")[0],
                                                     "meters_hourly.csv: chiller yard and outdoor temperature"],
                           E.iso(E.parse(sp["start"]) + limit), round(extra, 1), round(usd, 2),
                           {"chiller": sp["chiller"], "start": sp["start"], "end": sp["end"], "days": round(days_, 2),
                            "free_cooling_hours": hours, "record": note.split(" ")[0]}))
    return out


def check_unmetered(d: EnergyData, t: dict[str, float], cfg: dict[str, Any]) -> Finding | None:
    lo, hi = cfg["checks"]["unmetered_band"]
    share = t["unmetered_kwh"] / t["facility_kwh"]
    if lo <= share <= hi:
        return None
    return Finding("EN-F9", "unmetered_share", "Facility and sub-meters do not reconcile",
                   f"Unmetered energy is {share:.1%} of total facility energy; distribution losses explain "
                   f"{lo:.1%} to {hi:.1%}. A meter may be faulty or a load unmetered.", ["OT-EN-01"],
                   ["meters_hourly.csv"], E.iso(d.end), detail={"share": share})


@dataclass
class Result:
    month: dict[str, Any]
    weeks: list[dict[str, Any]]
    days: list[dict[str, Any]]
    periods: list[dict[str, Any]]
    year: dict[str, Any] | None
    findings: list[Finding]
    kpi: dict[str, Any]
    report: dict[str, Any]
    lockouts: list[dict[str, Any]]


def analyse(d: EnergyData, cfg: dict[str, Any] | None = None, sla: dict[str, Any] | None = None) -> Result:
    cfg = cfg or E.load_config()
    plant = E.Plant(cfg)
    t = totals(d.meters)
    findings: list[Finding] = []
    f = check_report(d, t, cfg)
    if f:
        findings.append(f)
    findings += check_lockouts(d, cfg, plant)
    f = check_unmetered(d, t, cfg)
    if f:
        findings.append(f)
    y = year(d)
    term = energy_terms(sla)["OT-EN-02"]
    basis = y["pue"] if y else t["pue"]
    kpi = {"id": "OT-EN-02", "name": term["name"], "target": term["target"], "actual": basis,
           "basis": "52 weeks" if y else "month", "met": basis <= term["target"], "month_pue": t["pue"]}
    return Result(t, weeks(d), days(d), periods(d), y, findings, kpi, d.report, lockouts(d))


def energy_terms(sla: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    if sla is None:
        from scorecard.sla_model import PARTNER_FILES, load_sla
        sla = load_sla(PARTNER_FILES["landlord"])
    return {t["id"]: t for t in sla["energy_reporting"]["terms"]}


# --------------------------------------------------------------------------- #
# Self-check against the answer key
# --------------------------------------------------------------------------- #
@dataclass
class Evaluation:
    planted: int
    detected: int
    false_positives: list[str]
    missed: list[str]
    cause_named: int = 0


def evaluate(res: Result, key: dict[str, Any]) -> Evaluation:
    planted = detected = named = 0
    missed, fps = [], []
    rep = [f for f in res.findings if f.type == "report_mismatch"]
    if key["report_error"] != "none":
        planted += 1
        if rep:
            detected += 1
            named += rep[0].detail["cause"] == key["report_error"]
        else:
            missed.append(f"report_mismatch ({key['report_error']})")
    else:
        fps += [f.summary for f in rep]
    found = [f for f in res.findings if f.type == "free_cooling_lockout"]
    for k in key["lockouts"]:
        planted += 1
        hit = next((f for f in found if f.detail["chiller"] == k["chiller"] and f.detail["start"] == k["start"]), None)
        if hit:
            detected += 1
            found.remove(hit)
        else:
            missed.append(f"free_cooling_lockout {k['chiller']}")
    fps += [f.summary for f in found]
    fps += [f.summary for f in res.findings if f.type == "unmetered_share"]
    return Evaluation(planted, detected, fps, missed, named)
