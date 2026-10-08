"""Deployment program for Site AUS-1: the Hall B GB300 NVL72 rollout, as gates, steps, and calculations.

Three sources, kept apart:

* **Standard work** (judgment): ``config/deployments.yaml``. Gates G0 to G3, every step's procedure,
  acceptance criteria, records, sign-off roles, and inspections; the authority profile (who has
  jurisdiction); the statewide determinations; the calculation inputs the site model does not hold.
* **The site** (facts about what is built): ``site/site.yaml`` through ``scorecard.site_model`` and the
  device directory. Rack positions, power groups, busways, CDUs, and cabling all come from there.
* **The record** (facts about what happened): the sample data. The Customer's deployment plan, the IT
  Partner's self-reported milestones, and the Customer's own measurements (the 24-hour burn-in in the
  health checks, Validated Handoff in the scheduler). A reported milestone is a claim; the measurement is
  the fact, the same rule as every scorecard.

Rack milestones M1 to M7 and the rack cycle come from the IT Partner SLA, so the program and CSL-09
cannot drift apart.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import site_model as S

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "deployments.yaml"
SAMPLE = ROOT / "data" / "sample"
STEP_KEYS = {"id", "name", "milestone", "owner", "after", "level", "doc", "standards", "procedure", "acceptance",
             "records", "signoff", "inspections", "when"}
INSPECTION_KINDS = {"internal", "third_party", "ahj"}


class DeploymentConfigError(ValueError):
    pass


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# --------------------------------------------------------------------------------------------- steps
def steps(cfg: dict[str, Any], sla: dict[str, Any]) -> list[dict[str, Any]]:
    """Every step in order, with its gate, its predecessors resolved, and rack milestones filled in from the SLA.
    A step with no ``after`` follows the previous gate's last step (the first step of all has none)."""
    ms = {m["id"]: m for m in sla["deployment"]["milestones"]}
    out: list[dict[str, Any]] = []
    prev_last: str | None = None
    for g in cfg["gates"]:
        for s in g["steps"]:
            st = dict(s, gate=g["id"], per_rack=bool(g.get("per_rack")))
            if "milestone" in s:
                m = ms[s["milestone"]]
                st.setdefault("name", m["name"])
                st.setdefault("acceptance", [m["exit_criteria"]])
                st["target_days"] = m["target_days_from_receipt"]
            st["after"] = list(s.get("after") or ([prev_last] if prev_last else []))
            st.setdefault("acceptance", [])
            st.setdefault("inspections", [])
            st.setdefault("standards", [])
            out.append(st)
        prev_last = g["steps"][-1]["id"]
    return out


def validate(cfg: dict[str, Any], sla: dict[str, Any]) -> list[str]:
    """Problems in the standard work, empty when it is consistent. Every reference must resolve."""
    errs: list[str] = []
    roles, stds, srcs = cfg["roles"], cfg["standards"], cfg["sources"]
    profiles = cfg["authorities"]
    ms = {m["id"] for m in sla["deployment"]["milestones"]}
    if cfg["program"]["jurisdiction"] not in profiles:
        errs.append(f"program jurisdiction {cfg['program']['jurisdiction']!r} has no authority profile")
    seen: dict[str, int] = {}
    docs: Counter = Counter()
    for g in cfg["gates"]:
        if g["owner"] not in roles:
            errs.append(f"{g['id']}: unknown owner {g['owner']}")
        for s in g["steps"]:
            seen[s["id"]] = seen.get(s["id"], 0) + 1
            docs[s["doc"]["id"]] += 1
            if extra := set(s) - STEP_KEYS:
                errs.append(f"{s['id']}: unknown keys {sorted(extra)}")
            if "milestone" in s and s["milestone"] not in ms:
                errs.append(f"{s['id']}: milestone {s['milestone']} is not in the IT Partner SLA")
            if "milestone" not in s and not s.get("name"):
                errs.append(f"{s['id']}: no name")
            if not s.get("procedure"):
                errs.append(f"{s['id']}: no procedure")
            if not s.get("signoff"):
                errs.append(f"{s['id']}: no sign-off roles")
            if not s.get("records"):
                errs.append(f"{s['id']}: no records")
            for r in [s["owner"], *s.get("signoff", []), *(i["by"] for i in s.get("inspections", []))]:
                if r not in roles:
                    errs.append(f"{s['id']}: unknown role {r}")
            for st in s.get("standards", []):
                if st not in stds:
                    errs.append(f"{s['id']}: unknown standard {st}")
            for i in s.get("inspections", []):
                if i["kind"] not in INSPECTION_KINDS:
                    errs.append(f"{s['id']}: inspection kind {i['kind']}")
                if i.get("profile") and i["profile"] not in profiles:
                    errs.append(f"{s['id']}: unknown authority profile {i['profile']}")
    order = [s["id"] for g in cfg["gates"] for s in g["steps"]]
    for g in cfg["gates"]:
        for s in g["steps"]:
            for a in s.get("after", []):
                if a not in seen:
                    errs.append(f"{s['id']}: after {a}, which does not exist")
                elif order.index(a) >= order.index(s["id"]):
                    errs.append(f"{s['id']}: after {a}, which comes later")
    errs += [f"step id {k} used {n} times" for k, n in seen.items() if n > 1]
    errs += [f"document {k} used {n} times" for k, n in docs.items() if n > 1]
    for sid, st in stds.items():
        if st["source"] not in srcs:
            errs.append(f"standard {sid}: unknown source {st['source']}")
    for name, p in profiles.items():
        for pm in p["permits"]:
            if pm["by"] not in roles or pm["source"] not in srcs:
                errs.append(f"permit {pm['id']}: unknown role or source")
    for c in cfg["statewide"]:
        if c["source"] not in srcs:
            errs.append(f"{c['id']}: unknown source {c['source']}")
    for k, v in cfg["calc"].items():
        if "source" in v and v["source"] not in srcs:
            errs.append(f"calc {k}: unknown source {v['source']}")
        if not v.get("basis"):
            errs.append(f"calc {k}: no basis")
    return errs


def applies(item: dict[str, Any], profile: str) -> bool:
    """An inspection or step tied to an authority profile applies only under that profile."""
    return not item.get("profile") or item["profile"] == profile


# ---------------------------------------------------------------------------------------- calculations
def _row(group: str, check: str, load: float, cap: float, unit: str, basis: str, limit: float = 1.0,
         control: str = "") -> dict[str, Any]:
    util = load / cap if cap else math.inf
    return {"group": group, "check": check, "load": round(load, 1), "capacity": round(cap, 1), "unit": unit,
            "utilization": round(util, 4), "limit": limit, "passed": load <= cap * limit + 1e-9, "basis": basis,
            "control": control}


def next_standard(amps: float, sizes: list[int]) -> int | None:
    return next((s for s in sizes if s >= amps - 1e-9), None)


def calculations(site: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """The calculation sheet: the site model's capacity checks for the hall at the design figure, the same
    power checks at the rack's reported peak, then the per-rack figures (tap-off, cooling, floor)."""
    c = {k: v["value"] for k, v in cfg["calc"].items()}
    hall = S.hall_by_id(site, cfg["program"]["hall"])
    name, p = hall["name"], hall["power"]
    rack = S.product(site, hall["rack_product"])
    design, peak = rack["design_kw"], c["rack_peak_kw"]
    volts = site["site"]["utilization_voltage_v"]
    rows = [_row("Hall at design", ch.system, ch.load, ch.capacity, ch.unit, ch.basis, ch.limit)
            for ch in S.capacity_checks(site) if ch.scope == name]

    # The same power checks with every rack at its reported peak. A failure here is not a design error:
    # it names the control (the rack power limit) that keeps the design figure true.
    scaled = dict(site, products={**site["products"], hall["rack_product"]: dict(rack, design_kw=peak)})
    control = f"Rack power limit set at or below {design} kW before energization (M4)"
    for ch in S.capacity_checks(scaled):
        if ch.scope == name and (ch.unit in ("A", "kVA") or ch.system.startswith("UPS")):
            rows.append(_row("Hall at reported peak", ch.system, ch.load, ch.capacity, ch.unit,
                             ch.basis.replace(f"{design} kW", f"{peak} kW"), ch.limit,
                             control if ch.load > ch.capacity * ch.limit + 1e-9 else ""))

    # Per rack: one feed carries the whole rack when the other side is lost (N+N power shelves). The
    # tap-off breaker must be at least 125% of that continuous load, rounded up to a standard size.
    sizes, k, fitted = c["standard_breaker_a"], c["continuous_factor"], c["tap_off_breaker_a"]
    for label, kw in (("design", design), ("reported peak", peak)):
        a = S.amps(kw, volts)
        need = next_standard(a * k, sizes) or math.inf
        rows.append(_row("Per rack", f"Tap-off breaker, one feed carries the rack ({label})", need, fitted, "A",
                         f"{kw} kW at {volts} V, PF {S.POWER_FACTOR}: {a:,.0f} A continuous; x {k} = "
                         f"{a * k:,.0f} A, next standard size {need} A against the {fitted} A tap-off",
                         control="" if need <= fitted else control))
    liquid = design * rack["liquid_fraction"]
    cdu = S.product(site, hall["cooling"]["cdu_product"])
    lpm = liquid * cdu["flow_per_kw_lpm"]
    dt = liquid / (lpm / 60 * c["coolant_density_kg_per_l"] * c["coolant_cp_kj_per_kg_k"])
    w, (fw, fd) = c["rack_weight_kg"], rack["footprint_mm"]
    kpa = w * 9.80665 / (fw / 1000 * fd / 1000) / 1000
    rows.append(_row("Per rack", "Floor load under the rack footprint", kpa, c["floor_rating_kpa"], "kPa",
                     f"{w:,} kg on {fw} x {fd} mm"))
    # Figures, not checks: what each rack position needs from the cooling system.
    rows += [dict(_row("Per rack", "Liquid heat to the CDU header", liquid, 0, "kW",
                       f"{rack['liquid_fraction']:.0%} of {design} kW"), figure=True),
             dict(_row("Per rack", "Coolant flow", lpm, 0, "LPM", f"{cdu['flow_per_kw_lpm']} LPM per kW of liquid heat"),
                  figure=True),
             dict(_row("Per rack", "Coolant temperature rise across the rack", dt, 0, "K",
                       f"Q = m x cp x dT with {c['coolant_density_kg_per_l']} kg/L and "
                       f"{c['coolant_cp_kj_per_kg_k']} kJ/kg K"), figure=True),
             dict(_row("Per rack", "Air-side heat to the thermal walls", design - liquid, 0, "kW",
                       f"{1 - rack['liquid_fraction']:.0%} of {design} kW"), figure=True)]
    for r in rows:
        if r.get("figure"):
            r.update(capacity=None, utilization=None, passed=None)
    return rows


def cabling(cfg: dict[str, Any], directory: dict[str, Any] | None = None) -> dict[str, Any]:
    """What gets cabled and connected in the hall, counted from the device directory (the site model)."""
    from . import devices
    d = (directory or devices.load())["devices"]
    letter = cfg["program"]["hall"][-1]
    racks = sorted(k for k, v in d.items() if v["kind"] == "rack" and k.startswith(letter))
    trays = [k for k, v in d.items() if v["kind"] == "compute_tray" and k[0].upper() == letter]
    leaves = sorted(k for k, v in d.items() if v["kind"] == "leaf" and k.startswith(f"leaf-{letter.lower()}"))
    rails = sum(1 for row in d[racks[0]]["conn"] if row[0].startswith("Rail ")) if racks else 0
    return {"racks": len(racks), "compute_trays": len(trays), "rails": rails, "leaf_switches": len(leaves),
            "backend_links": len(trays) * rails, "links_per_rack": len(trays) * rails // max(len(racks), 1),
            "power_cords": 2 * len(racks), "coolant_hoses": 2 * len(racks)}


def determinations(site: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Statewide items with what the site model can say about them. Only the large-load test is
    arithmetic; the others are recorded decisions, shown as open until a record exists."""
    out = []
    for item in cfg["statewide"]:
        row = {"id": item["id"], "name": item["name"], "detail": " ".join(item["detail"].split()),
               "source": cfg["sources"][item["source"]]}
        if "threshold_mw" in item:
            mw = S.site_peak_kw(site) / 1000
            row["result"] = (f"Site design-day peak {mw:,.1f} MW is below the {item['threshold_mw']} MW threshold: "
                             "not a large load under the default definition."
                             if mw < item["threshold_mw"] else
                             f"Site design-day peak {mw:,.1f} MW meets the {item['threshold_mw']} MW threshold.")
        elif "test" in item:
            row["result"] = f"Determination to record: {item['test']}"
        else:
            row["result"] = "Applies to all electrical work."
        out.append(row)
    return out


# ------------------------------------------------------------------------------------------- racks
def _csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def rack_status(site: dict[str, Any], cfg: dict[str, Any], sla: dict[str, Any], data_dir: Path = SAMPLE) -> dict[str, Any]:
    """Each rack's plan, the IT Partner's reported milestones, and the Customer's measurements.

    ``measured_burn_in``: the 24-hour rack burn-in in the Customer's health checks (M6).
    ``measured_handoff``: the first tray of the rack released to the scheduler as a validated handoff (M7),
    the same measurement CSL-09 uses. A rack is late when its measured handoff is after the committed date,
    or when the committed date has passed with no handoff."""
    hall = cfg["program"]["hall"]
    end = _ts(json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))["window"]["end"])
    plan = {r["rack"]: r for r in _csv(data_dir / "customer" / "deployment_plan.csv") if r["hall"] == hall}
    reported: dict[str, dict[str, str]] = {}
    for r in _csv(data_dir / "vendor" / "deployment_milestones.csv"):
        reported.setdefault(r["rack"], {})[r["milestone"]] = r["reported_complete_at"]
    burn: dict[str, str] = {}
    for h in _jsonl(data_dir / "telemetry" / "health_checks.jsonl"):
        if h["check"] == "rack_burn_in_24h" and h["result"] == "pass":
            burn[h["target"]] = min(burn.get(h["target"], h["completed_at"]), h["completed_at"])
    handoff: dict[str, str] = {}
    for s in _jsonl(data_dir / "telemetry" / "scheduler_node_states.jsonl"):
        if s["reason"] == "validated handoff":
            r = s["node"].split("-")[0].upper()
            handoff[r] = min(handoff.get(r, s["timestamp"]), s["timestamp"])
    ms = [m["id"] for m in sla["deployment"]["milestones"]]
    out = []
    for r in S.racks(site, hall):
        rid = r["rack"]
        p = plan.get(rid, {})
        rep = reported.get(rid, {})
        due = p.get("committed_handoff")
        got = handoff.get(rid)
        if got:
            state = "handed off late" if due and _ts(got) > _ts(due) else "handed off"
        elif due and _ts(due) < end:
            state = "late"
        elif rep:
            state = "in progress"
        else:
            state = "not received"
        out.append({"rack": rid, "row": r["row"], "wave": r["row"], "group": r["group"], "cdu": r["cdu"],
                    "planned_receipt": p.get("planned_receipt"), "committed_handoff": due,
                    "reported": {m: rep[m] for m in ms if m in rep},
                    "last_reported": next((m for m in reversed(ms) if m in rep), None),
                    "measured_burn_in": burn.get(rid), "measured_handoff": got, "state": state})
    return {"as_of": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "milestones": ms, "racks": out,
            "counts": dict(Counter(x["state"] for x in out))}


# ------------------------------------------------------------------------------------------- build
def build(data_dir: Path = SAMPLE, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the page and the plan document show, from the three sources."""
    from .sla_model import load_sla
    cfg = cfg or load_config()
    sla = load_sla()
    if errs := validate(cfg, sla):
        raise DeploymentConfigError("; ".join(errs))
    site = S.load_site()
    profile = cfg["program"]["jurisdiction"]
    st = steps(cfg, sla)
    for s in st:
        s["inspections"] = [i for i in s["inspections"] if applies(i, profile)]
    hall = S.hall_by_id(site, cfg["program"]["hall"])
    return {"meta": cfg["meta"], "program": dict(cfg["program"], hall_name=hall["name"],
                                                 rack_model=S.product(site, hall["rack_product"])["model"],
                                                 cycle_days=sla["deployment"]["rack_cycle_target_days"]),
            "roles": cfg["roles"], "standards": cfg["standards"], "sources": cfg["sources"],
            "authority": dict(cfg["authorities"][profile], id=profile,
                              summary=" ".join(cfg["authorities"][profile]["summary"].split())),
            "profiles": {k: v["name"] for k, v in cfg["authorities"].items()},
            "statewide": determinations(site, cfg),
            "gates": [{k: g[k] for k in ("id", "name", "owner", "exit")} | {"per_rack": bool(g.get("per_rack"))}
                      for g in cfg["gates"]],
            "steps": st, "calc": calculations(site, cfg),
            "calc_inputs": cfg["calc"], "cabling": cabling(cfg), "racks": rack_status(site, cfg, sla, data_dir)}
