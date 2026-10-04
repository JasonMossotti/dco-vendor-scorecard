#!/usr/bin/env python3
"""Render the site description and drawings from site/site.yaml.

Usage:
    python scripts/render_site.py            # validate + write docs/site/
    python scripts/render_site.py --check    # fail if docs/site/ is out of date (used in CI)

Writes docs/site/SITE.md (equipment, capacity checks, monitoring map) and one
SVG per drawing sheet. Nothing in docs/site/ is edited by hand.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import site_model as S  # noqa: E402
from scorecard.site_drawings import building_dims, sheets  # noqa: E402

OUT_DIR = ROOT / "docs" / "site"
CATEGORY_LABELS = {"ups": "UPS", "cdu": "CDU", "crah": "CRAH", "ib_switch": "InfiniBand switch",
                   "solid_state_transformer": "Solid-state transformer"}


def _table(headers: list[str], rows: list[list[object]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_markdown(site: dict, sheet_list: list[tuple[str, str, str, str]]) -> str:
    s, parties = site["site"], site["parties"]
    bw, bd = building_dims(site)
    lines: list[str] = []
    add = lines.append
    add(f"# {s['name']}: site description")
    add("")
    add("> Generated from `site/site.yaml` by `scripts/render_site.py`. Do not edit by hand.")
    add(">")
    add(f"> {site['meta']['disclaimer']}")
    add("")
    add(f"{s['location']}, on the {s['grid']} grid. Utility service at {s['service_voltage_kv']} kV, site distribution "
        f"at {s['distribution_voltage_kv']} kV, utilization at {s['utilization_voltage_v']} V. The building is about "
        f"{bw:.0f} m by {bd:.0f} m. Design-day IT load is {sum(S.hall_it_kw(site, h) for h in site['halls']):,.0f} kW "
        f"and the design-day peak at the 13.8 kV bus is {S.site_peak_kw(site):,.0f} kW.")
    add("")
    add("## Halls")
    add("")
    rows = []
    for h in site["halls"]:
        rp = S.product(site, h["rack_product"])
        power = ("4 x Galaxy VX, distributed redundant (4 make 3)" if h["power"]["architecture"] == "distributed_redundant"
                 else f"{h['power']['mvsst_count']} x Eaton MVSST, 2N, 800 VDC")
        rows.append([h["name"], h["state"], f"{S.rack_count(h)} x {rp['model']}", f"{S.hall_it_kw(site, h):,.0f} kW",
                     power, f"{h['cooling']['cdu_count']} x CHx2000 (N+{h['cooling']['cdu_redundancy']})",
                     S.product(site, h["fabric"])["model"]])
    add(_table(["Hall", "State", "Racks", "Design IT load", "Power", "CDUs", "Compute fabric"], rows))
    add("")
    add("## Drawings")
    add("")
    add(_table(["Sheet", "Title"], [[num, f"[{title}]({fn})"] for num, fn, title, _ in sheet_list]))
    add("")
    for num, fn, title, _ in sheet_list:
        add(f"### {num} {title}")
        add("")
        add(f"![{title}]({fn})")
        add("")
    add("## Who operates what")
    add("")
    add(_table(["Party", "Name", "Role"], [[k.replace("_", " ").capitalize(), v["name"]
                                             + (" (fictional)" if v.get("fictional") else ""), v["role"]]
                                            for k, v in parties.items()]))
    add("")
    add("## Equipment")
    add("")
    counts: dict[str, object] = dict(Counter(e["product"] for e in S.equipment(site)))
    water_circuits = 0
    for h in site["halls"]:
        counts[h["rack_product"]] = counts.get(h["rack_product"], 0) + S.rack_count(h)
        counts["vesda_e_vep"] = counts.get("vesda_e_vep", 0) + h["fire_life_safety"]["vesda_detectors"]
        counts["tracetek_ttdm128"] = counts.get("tracetek_ttdm128", 0) + 1
        water_circuits += h["fire_life_safety"]["leak_circuits"]
        counts[h["fabric"]] = "set in fabric design"
    ups_like = sum(1 for e in S.equipment(site) if e["id"].startswith(("UPS-", "MUPS-")))
    counts["galaxy_li_ion"] = f"{ups_like} (one per UPS)"
    counts["notifier_facp"] = 1
    counts["tracetek_water_cable"] = f"{water_circuits} circuits"
    counts["tracetek_tt5000"] = f"{site['plants']['generators']['count']} circuits (one per fuel tank)"
    rows = []
    for key, prod in site["products"].items():
        n = counts.get(key, "")
        rating = next((f"{prod[k]:,} {u}" for k, u in (("rating_kw", "kW"), ("capacity_kw", "kW"),
                                                       ("rating_kva", "kVA"), ("rating_a", "A"), ("design_kw", "kW"))
                       if k in prod), "")
        maker = prod["manufacturer"]
        name = (f"{prod['model']} ({maker.lower()})" if maker.lower().startswith(("to be selected", "utility"))
                else f"{maker} {prod['model']}")
        rows.append([CATEGORY_LABELS.get(prod["category"], prod["category"].replace("_", " ").capitalize()), name, n, rating, "; ".join(prod["interfaces"])])
    add(_table(["Category", "Product", "Count", "Rating", "Management interfaces"], rows))
    add("")
    add("Busway counts are A and B tracks per row segment. Every count comes from the site model, so a change "
        "to `site/site.yaml` updates this table and the drawings together.")
    add("")
    add("## Capacity checks")
    add("")
    add("Every check must pass or the site file will not load, the same way the SLA refuses to load if inconsistent.")
    add("")
    rows = [[c.scope, c.system, f"{c.load:,.0f} {c.unit}", f"{c.capacity:,.0f} {c.unit}", f"{c.utilization:.0%}",
             f"{c.limit:.0%}", "Pass" if c.passed else "**Fail**", c.basis] for c in S.capacity_checks(site)]
    add(_table(["Scope", "Check", "Load", "Capacity", "Utilization", "Limit", "Result", "Basis"], rows))
    add("")
    add("## Dependencies (used for fault attribution)")
    add("")
    add("Each rack's power and cooling paths, upstream to the sources. When a rack goes down, walking these "
        "paths shows which system, and therefore which partner, owns the event. Example, rack A07:")
    add("")
    for side, path in S.power_path(site, "A07").items():
        add(f"- **Power, {side} feed:** " + " -> ".join(path))
    add(f"- **Cooling:** " + " -> ".join(S.cooling_path(site, "A07")))
    add("")
    add("## Monitoring map")
    add("")
    add("The Landlord runs EcoStruxure day to day. Under the Interface Agreement, the Customer's Telemetry of Record collector reads critical "
        "devices directly and read-only, and also receives the BMS feed, so a point overridden or an alarm "
        "inhibited at the BMS shows up as a mismatch.")
    add("")
    systems = {x["id"]: x for x in site["monitoring"]["systems"]}
    add(_table(["System", "Role", "Operated by"],
               [[x["name"], x["role"], parties[x["operator"]]["name"]] for x in site["monitoring"]["systems"]]))
    add("")
    add(_table(["Device class", "Protocol", "Day-to-day system", "Customer tap"],
               [[d["class"], d["protocol"], systems[d["system"]]["name"], d["customer_tap"]]
                for d in site["monitoring"]["device_classes"]]))
    add("")
    add("## Engineering assumptions")
    add("")
    for a in site["assumptions"]:
        add(f"- {a}")
    add("")
    add("## Sources")
    add("")
    add("Product facts in `site/site.yaml` were checked against these manufacturer and trade sources:")
    add("")
    for key, prod in site["products"].items():
        for url in prod.get("sources", []):
            add(f"- {prod['manufacturer']} {prod['model']}: <{url}>")
    add("")
    return "\n".join(lines)


def build_outputs() -> dict[Path, str]:
    site = S.load_site()
    sheet_list = sheets(site)
    out = {OUT_DIR / fn: svg for _, fn, _, svg in sheet_list}
    out[OUT_DIR / "SITE.md"] = render_markdown(site, sheet_list)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if docs/site/ is out of date")
    args = ap.parse_args()
    outputs = build_outputs()
    if args.check:
        stale = [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        extra = [p for p in OUT_DIR.glob("*") if p not in outputs] if OUT_DIR.exists() else []
        if stale or extra:
            for p in stale:
                print(f"out of date: {p.relative_to(ROOT)}")
            for p in extra:
                print(f"not generated by render_site.py: {p.relative_to(ROOT)}")
            print("Run: python scripts/render_site.py")
            return 1
        print(f"docs/site/ is current ({len(outputs)} files).")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in OUT_DIR.glob("*"):
        if p not in outputs:
            p.unlink()
    for p, text in outputs.items():
        p.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {len(outputs)} files to {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
