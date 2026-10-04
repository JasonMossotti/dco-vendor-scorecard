"""Site model: load site/site.yaml, expand it into named equipment, and check it.

The site file says *what kinds* of equipment exist and how many. This module
turns that into the named things operators talk about (UPS-A3, CDU-B2,
busway BW-A-R2-PG-A1-A) and answers three questions:

* ``expand_site``: every rack with its row, CDU, power group, and A/B feeds.
* ``power_path`` / ``cooling_path``: what a rack depends on, upstream to the
  utility, the generators, and the chillers. Fault attribution (which partner
  owns an outage) walks these paths.
* ``capacity_checks``: does every system carry its load with its stated
  redundancy (UPS 4-make-3, CDU N+1, generators N+1, ...)? The site will not
  load if any check fails, the same way the SLA refuses to load if inconsistent.

Standard library + PyYAML only, so it runs anywhere the scorecard runs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SITE_PATH = Path(__file__).resolve().parents[2] / "site" / "site.yaml"

POWER_FACTOR = 0.99            # rack power shelves are power-factor corrected
UPS_RECHARGE_ALLOWANCE = 0.10  # extra UPS input while recharging batteries
BUSWAY_FAILURE_LIMIT = 0.90    # max fraction of busway rating with one feed lost
MVSST_EFFICIENCY = 0.985       # Eaton's published system efficiency (up to)


class SiteValidationError(ValueError):
    """Raised when the site file is inconsistent or under-built."""


@dataclass(frozen=True)
class Check:
    """One capacity check: can `capacity` carry `load` with the stated redundancy?"""

    scope: str          # "Hall A", "Site"
    system: str         # "UPS (single module lost)"
    load: float
    capacity: float
    unit: str           # "kW", "A", "LPM", "kVA"
    basis: str          # one-line explanation of the arithmetic
    limit: float = 1.0  # pass if load <= capacity * limit

    @property
    def utilization(self) -> float:
        return self.load / self.capacity if self.capacity else math.inf

    @property
    def passed(self) -> bool:
        return self.load <= self.capacity * self.limit + 1e-9


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #
def load_site(path: str | Path = DEFAULT_SITE_PATH, validate: bool = True) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        site = yaml.safe_load(fh)
    if validate:
        validate_site(site)
    return site


def validate_site(site: dict[str, Any]) -> None:
    """Structural checks, then capacity checks. Raises with every problem found."""
    errors: list[str] = []
    products = site.get("products", {})

    def need_product(key: str | None, where: str) -> None:
        if key is not None and key not in products:
            errors.append(f"{where}: unknown product '{key}'")

    for hall in site.get("halls", []):
        hid = hall["id"]
        need_product(hall.get("rack_product"), hid)
        need_product(hall.get("fabric"), hid)
        p, c = hall["power"], hall["cooling"]
        for k in ("ups_product", "battery_product", "unit_sub_product", "busway_product",
                  "mech_ups_product", "mvsst_product"):
            need_product(p.get(k), f"{hid}.power.{k}")
        for k in ("cdu_product", "thermal_wall_product", "electrical_room_crah_product"):
            need_product(c.get(k), f"{hid}.cooling.{k}")
        if p["architecture"] == "distributed_redundant":
            groups = p["groups"]
            if sum(g["racks"] for g in groups) != rack_count(hall):
                errors.append(f"{hid}: power groups cover {sum(g['racks'] for g in groups)} racks, "
                              f"hall has {rack_count(hall)}")
            n = p["ups_count"]
            for g in groups:
                a, b = g["feeds"]
                if a == b:
                    errors.append(f"{g['id']}: A and B feeds on the same UPS (UPS-{hall['letter']}{a})")
                if not (1 <= a <= n and 1 <= b <= n):
                    errors.append(f"{g['id']}: feed outside UPS-{hall['letter']}1..{n}")
            pairs = {tuple(sorted(g["feeds"])) for g in groups}
            if pairs != set(combinations(range(1, n + 1), 2)):
                errors.append(f"{hid}: distributed redundant groups must use every UPS pairing exactly once")

    plants = site["plants"]
    need_product(plants["generators"]["product"], "plants.generators")
    need_product(plants["heat_rejection"]["chiller_product"], "plants.heat_rejection")
    need_product(plants["utility"]["transformer_product"], "plants.utility")
    for dc in site["monitoring"]["device_classes"]:
        for prod in dc["products"]:
            need_product(prod, f"monitoring.{dc['class']}")
        if dc["system"] not in {s["id"] for s in site["monitoring"]["systems"]}:
            errors.append(f"monitoring.{dc['class']}: unknown system {dc['system']}")

    if errors:
        raise SiteValidationError("Site file is inconsistent:\n  - " + "\n  - ".join(errors))

    failed = [c for c in capacity_checks(site) if not c.passed]
    if failed:
        raise SiteValidationError("Site is under-built:\n  - " + "\n  - ".join(
            f"{c.scope} {c.system}: {c.load:,.0f} {c.unit} on {c.capacity:,.0f} {c.unit} "
            f"({c.utilization:.0%}, limit {c.limit:.0%})" for c in failed))


# --------------------------------------------------------------------------- #
# Expansion into named equipment
# --------------------------------------------------------------------------- #
def rack_count(hall: dict[str, Any]) -> int:
    return hall["rows"] * hall["racks_per_row"]


def product(site: dict[str, Any], key: str) -> dict[str, Any]:
    return site["products"][key]


def hall_by_id(site: dict[str, Any], hall_id: str) -> dict[str, Any]:
    return next(h for h in site["halls"] if h["id"] == hall_id)


def ups_ids(hall: dict[str, Any]) -> list[str]:
    return [f"UPS-{hall['letter']}{i}" for i in range(1, hall["power"].get("ups_count", 0) + 1)]


def mv_bus_for(index: int) -> str:
    """Odd-numbered equipment lands on MV-A, even on MV-B."""
    return "MV-A" if index % 2 else "MV-B"


def racks(site: dict[str, Any], hall_id: str | None = None) -> list[dict[str, Any]]:
    """Every rack with its position, CDU, power group, and A/B feeds."""
    out = []
    for hall in site["halls"]:
        if hall_id and hall["id"] != hall_id:
            continue
        L, per_row = hall["letter"], hall["racks_per_row"]
        cdus = hall["cooling"]["cdu_count"]
        rows_per_cdu = max(1, hall["rows"] // cdus) if cdus <= hall["rows"] else 1
        group_of: list[dict[str, Any]] = []
        for g in hall["power"].get("groups", []):
            group_of += [g] * g["racks"]
        for i in range(1, rack_count(hall) + 1):
            row = (i - 1) // per_row + 1
            rack = {"rack": f"{L}{i:02d}", "hall": hall["id"], "index": i, "row": row,
                    "position": (i - 1) % per_row + 1,
                    "cdu": f"CDU-{L}{min((row - 1) // rows_per_cdu + 1, cdus)}"}
            if group_of:
                g = group_of[i - 1]
                rack["group"] = g["id"]
                rack["feeds"] = {"A": f"UPS-{L}{g['feeds'][0]}", "B": f"UPS-{L}{g['feeds'][1]}"}
            else:
                n = hall["power"]["mvsst_count"]
                rack["group"] = None
                rack["feeds"] = {"A": f"MVSST-{L}1", "B": f"MVSST-{L}{min(2, n)}"}
            out.append(rack)
    return out


def busway_segments(site: dict[str, Any], hall_id: str) -> list[dict[str, Any]]:
    """Contiguous runs of racks in one row and one power group, each with an A and a B busway."""
    segs: list[dict[str, Any]] = []
    for r in racks(site, hall_id):
        if r["group"] is None:
            continue
        last = segs[-1] if segs else None
        if last and last["row"] == r["row"] and last["group"] == r["group"]:
            last["racks"].append(r["rack"])
        else:
            segs.append({"row": r["row"], "group": r["group"], "racks": [r["rack"]], "feeds": r["feeds"]})
    for s in segs:
        s["id"] = f"BW-{hall_id[-1]}-R{s['row']}-{s['group']}"
    return segs


def equipment(site: dict[str, Any]) -> list[dict[str, str]]:
    """A flat inventory of every named piece of infrastructure (for docs and the monitoring map)."""
    inv: list[dict[str, str]] = []

    def add(id_: str, prod: str, location: str, fed_from: str = "") -> None:
        inv.append({"id": id_, "product": prod, "location": location, "fed_from": fed_from})

    pl = site["plants"]
    for i in range(1, pl["utility"]["transformer_count"] + 1):
        add(f"TX-{i}", pl["utility"]["transformer_product"], "Utility substation", "138 kV utility")
    for i in range(1, pl["generators"]["count"] + 1):
        add(f"GEN-{i}", pl["generators"]["product"], "Generator yard", "Paralleling bus")
    for i in range(1, pl["heat_rejection"]["chiller_count"] + 1):
        add(f"CH-{i:02d}", pl["heat_rejection"]["chiller_product"], "Chiller yard",
            f"USS-CH{(i - 1) % pl['mechanical_power']['chiller_unit_subs'] + 1}")
    for i in range(1, pl["heat_rejection"]["pump_count"] + 1):
        add(f"FWP-{i}", pl["heat_rejection"]["pump_product"], "Central plant", "USS-CH" + str((i - 1) % 2 + 1))
    for i in range(1, pl["mechanical_power"]["chiller_unit_subs"] + 1):
        add(f"USS-CH{i}", pl["mechanical_power"]["unit_sub_product"], "Chiller yard", mv_bus_for(i))
    for hall in site["halls"]:
        L, name, p, c = hall["letter"], hall["name"], hall["power"], hall["cooling"]
        for i, u in enumerate(ups_ids(hall), 1):
            add(f"USS-{L}{i}", p["unit_sub_product"], f"{name} electrical room", mv_bus_for(i))
            add(u, p["ups_product"], f"{name} electrical room", f"USS-{L}{i}")
        for i in range(1, p.get("mech_ups_count", 0) + 1):
            add(f"MUPS-{L}{i}", p["mech_ups_product"], f"{name} electrical room", mv_bus_for(i))
        for i in range(1, p.get("mvsst_count", 0) + 1):
            add(f"MVSST-{L}{i}", p["mvsst_product"], f"{name} electrical yard", mv_bus_for(i))
        for s in busway_segments(site, hall["id"]):
            for side in ("A", "B"):
                add(f"{s['id']}-{side}", p["busway_product"], f"{name} row {s['row']}", s["feeds"][side])
        for i in range(1, c["cdu_count"] + 1):
            add(f"CDU-{L}{i}", c["cdu_product"], f"{name} row {min(i, hall['rows'])}",
                f"MUPS-{L}1 / MUPS-{L}2" if p.get("mech_ups_count") else f"MVSST-{L}1 / MVSST-{L}2")
        for i in range(1, c.get("thermal_wall_count", 0) + 1):
            add(f"TW-{L}{i}", c["thermal_wall_product"], f"{name} gallery", f"MUPS-{L}{(i - 1) % 2 + 1}")
        for i in range(1, c.get("electrical_room_crah_count", 0) + 1):
            add(f"CRAH-{L}{i}", c["electrical_room_crah_product"], f"{name} electrical room", "House power")
    return inv


# --------------------------------------------------------------------------- #
# Dependency paths (used later for fault attribution)
# --------------------------------------------------------------------------- #
def power_path(site: dict[str, Any], rack_id: str) -> dict[str, list[str]]:
    """Upstream chain for each feed: rack -> busway -> UPS -> unit sub -> MV bus -> sources."""
    r = next(x for x in racks(site) if x["rack"] == rack_id)
    sources = ["TX-1", "TX-2", "GEN paralleling bus"]
    out = {}
    if r["group"] is None:
        for side, src in r["feeds"].items():
            idx = int(src[-1])
            out[side] = [rack_id, "800 VDC busway", src, mv_bus_for(idx)] + sources
        return out
    seg = next(s for s in busway_segments(site, r["hall"]) if rack_id in s["racks"])
    for side, ups in r["feeds"].items():
        idx = int(ups[-1])
        out[side] = [rack_id, f"{seg['id']}-{side}", ups, f"USS-{ups[4:]}", mv_bus_for(idx)] + sources
    return out


def cooling_path(site: dict[str, Any], rack_id: str) -> list[str]:
    """rack -> hall secondary header -> CDUs (N+1) -> facility water -> chiller plant."""
    r = next(x for x in racks(site) if x["rack"] == rack_id)
    hall = hall_by_id(site, r["hall"])
    L, n = hall["letter"], hall["cooling"]["cdu_count"]
    return [rack_id, f"{hall['name']} secondary header", f"CDU-{L}1..{L}{n} (N+1)",
            "Facility water loop", "Chiller plant"]


# --------------------------------------------------------------------------- #
# Loads
# --------------------------------------------------------------------------- #
def hall_it_kw(site: dict[str, Any], hall: dict[str, Any]) -> float:
    return rack_count(hall) * product(site, hall["rack_product"])["design_kw"]


def hall_liquid_kw(site: dict[str, Any], hall: dict[str, Any]) -> float:
    return hall_it_kw(site, hall) * product(site, hall["rack_product"])["liquid_fraction"]


def hall_air_kw(site: dict[str, Any], hall: dict[str, Any]) -> float:
    return hall_it_kw(site, hall) - hall_liquid_kw(site, hall)


def hall_power_conversion_loss_kw(site: dict[str, Any], hall: dict[str, Any]) -> float:
    p = hall["power"]
    if p["architecture"] == "distributed_redundant":
        return hall_it_kw(site, hall) * (1 / product(site, p["ups_product"])["efficiency"] - 1)
    return hall_it_kw(site, hall) * (1 / MVSST_EFFICIENCY - 1)


def hall_mech_kw(site: dict[str, Any], hall: dict[str, Any]) -> float:
    """CDU pumps and thermal-wall fans (the load on the mechanical UPS)."""
    c = hall["cooling"]
    kw = c["cdu_count"] * product(site, c["cdu_product"])["power_kw"]
    if c.get("thermal_wall_count"):
        kw += c["thermal_wall_count"] * product(site, c["thermal_wall_product"])["power_kw"]
    return kw


def hall_crah_kw(site: dict[str, Any], hall: dict[str, Any]) -> float:
    c = hall["cooling"]
    return c.get("electrical_room_crah_count", 0) * product(site, c["electrical_room_crah_product"])["power_kw"]


def site_heat_kw(site: dict[str, Any]) -> float:
    """Everything the chiller plant must reject on a design day."""
    return sum(hall_it_kw(site, h) + hall_power_conversion_loss_kw(site, h) + hall_mech_kw(site, h)
               + hall_crah_kw(site, h) for h in site["halls"])


def chiller_plant_kw(site: dict[str, Any]) -> float:
    hr = site["plants"]["heat_rejection"]
    chiller = product(site, hr["chiller_product"])
    pumps = (hr["pump_count"] - hr["pump_redundancy"]) * product(site, hr["pump_product"])["power_kw"]
    return site_heat_kw(site) / chiller["cop_at_design_ambient"] + pumps


def site_peak_kw(site: dict[str, Any]) -> float:
    """Design-day electrical load at the 13.8 kV bus (what the generators must carry)."""
    halls = sum(hall_it_kw(site, h) + hall_power_conversion_loss_kw(site, h) + hall_mech_kw(site, h)
                + hall_crah_kw(site, h) for h in site["halls"])
    return halls + chiller_plant_kw(site) + site["site"]["house_load_kw"]


# --------------------------------------------------------------------------- #
# Capacity checks
# --------------------------------------------------------------------------- #
def _ups_loads(site: dict[str, Any], hall: dict[str, Any], lost: int | None = None) -> dict[int, float]:
    """kW on each UPS module, normally or with module `lost` failed."""
    rack_kw = product(site, hall["rack_product"])["design_kw"]
    loads = {i: 0.0 for i in range(1, hall["power"]["ups_count"] + 1)}
    for g in hall["power"]["groups"]:
        a, b = g["feeds"]
        kw = g["racks"] * rack_kw
        if lost == a:
            loads[b] += kw
        elif lost == b:
            loads[a] += kw
        else:
            loads[a] += kw / 2
            loads[b] += kw / 2
    if lost:
        loads.pop(lost)
    return loads


def amps(kw: float, volts: float) -> float:
    return kw * 1000 / (math.sqrt(3) * volts * POWER_FACTOR)


def capacity_checks(site: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    volts = site["site"]["utilization_voltage_v"]
    for hall in site["halls"]:
        name, p, c = hall["name"], hall["power"], hall["cooling"]
        it = hall_it_kw(site, hall)
        rack_kw = product(site, hall["rack_product"])["design_kw"]
        if p["architecture"] == "distributed_redundant":
            ups = product(site, p["ups_product"])
            normal = max(_ups_loads(site, hall).values())
            worst = max(max(_ups_loads(site, hall, lost=i).values()) for i in range(1, p["ups_count"] + 1))
            checks.append(Check(name, "UPS, normal (busiest module)", normal, ups["rating_kw"], "kW",
                                f"{p['ups_count']} x {ups['rating_kw']:,} kW sharing {it:,.0f} kW", limit=0.8))
            checks.append(Check(name, f"UPS, one module lost ({p['ups_count']} make {p['ups_count'] - 1})",
                                worst, ups["rating_kw"], "kW",
                                "lost module's groups shift to their other feed"))
            sub = product(site, p["unit_sub_product"])
            checks.append(Check(name, "Unit substation (worst UPS input)",
                                worst / ups["efficiency"] * (1 + UPS_RECHARGE_ALLOWANCE) / POWER_FACTOR,
                                sub["rating_kva"], "kVA", "UPS input at worst case plus battery recharge"))
            bus = product(site, p["busway_product"])
            seg = max(len(s["racks"]) for s in busway_segments(site, hall["id"]))
            checks.append(Check(name, "Busway, one feed lost (largest segment)", amps(seg * rack_kw, volts),
                                bus["rating_a"], "A", f"{seg} racks x {rack_kw} kW on one {bus['rating_a']} A busway",
                                limit=BUSWAY_FAILURE_LIMIT))
            mups = product(site, p["mech_ups_product"])
            checks.append(Check(name, "Mechanical UPS (2N, one unit carries all)", hall_mech_kw(site, hall),
                                mups["rating_kw"], "kW", "CDU pumps and thermal-wall fans"))
        else:
            mv = product(site, p["mvsst_product"])
            checks.append(Check(name, "MVSST (2N, one unit carries all)", it / MVSST_EFFICIENCY,
                                mv["rating_kw"], "kW", f"{rack_count(hall)} racks x {rack_kw} kW"))
        cdu = product(site, c["cdu_product"])
        n_cdu = c["cdu_count"] - c["cdu_redundancy"]
        liquid = hall_liquid_kw(site, hall)
        checks.append(Check(name, f"CDU heat, N+{c['cdu_redundancy']}", liquid, n_cdu * cdu["capacity_kw"], "kW",
                            f"{n_cdu} of {c['cdu_count']} CDUs carry the liquid load"))
        checks.append(Check(name, f"CDU flow, N+{c['cdu_redundancy']}", liquid * cdu["flow_per_kw_lpm"],
                            n_cdu * cdu["secondary_flow_lpm"], "LPM",
                            f"{cdu['flow_per_kw_lpm']} LPM per kW of liquid load"))
        if c.get("thermal_wall_count"):
            tw = product(site, c["thermal_wall_product"])
            n_tw = c["thermal_wall_count"] - c["thermal_wall_redundancy"]
            checks.append(Check(name, f"Thermal walls, N+{c['thermal_wall_redundancy']}", hall_air_kw(site, hall),
                                n_tw * tw["capacity_kw"], "kW", "air-side share of rack heat"))
        crah = product(site, c["electrical_room_crah_product"])
        n_crah = c["electrical_room_crah_count"] - c["electrical_room_crah_redundancy"]
        checks.append(Check(name, f"Electrical room CRAH, N+{c['electrical_room_crah_redundancy']}",
                            hall_power_conversion_loss_kw(site, hall), n_crah * crah["capacity_kw"], "kW",
                            "power conversion losses"))

    pl = site["plants"]
    hr = pl["heat_rejection"]
    ch = product(site, hr["chiller_product"])
    n_ch = hr["chiller_count"] - hr["chiller_redundancy"]
    checks.append(Check("Site", f"Chillers at {site['site']['design_ambient_c']} C, N+{hr['chiller_redundancy']}",
                        site_heat_kw(site), n_ch * ch["capacity_at_design_ambient_kw"], "kW",
                        f"{n_ch} x {ch['capacity_at_design_ambient_kw']:,} kW derated"))
    g = pl["generators"]
    gen = product(site, g["product"])
    n_gen = g["count"] - g["redundancy"]
    checks.append(Check("Site", f"Generators, N+{g['redundancy']}", site_peak_kw(site), n_gen * gen["rating_kw"],
                        "kW", f"{n_gen} x {gen['rating_kw']:,} kW at design-day peak", limit=0.9))
    tx = product(site, pl["utility"]["transformer_product"])
    checks.append(Check("Site", "Utility transformers (2N, one carries all)", site_peak_kw(site) / 0.95,
                        tx["rating_kva"], "kVA", "design-day peak at 0.95 power factor", limit=0.8))
    return checks
