"""Where every rack, room, and piece of equipment is drawn, for the location popups.

The site drawings record a box for each item they draw (``Svg.mark`` in
``site_drawings``). This module turns those boxes into one entry per name the
pages use (A07, CDU-B3, TO-A07-B, "Hall B electrical room", ...): what it is, in
a sentence from the site model, and the sheets that show it, with the item to
outline and the items around it that answer the next question (what feeds it,
what it serves). ``scripts/render_site.py`` writes the result to
``docs/site/locations.json``; the pages embed the entries they need.

``resolve`` reads a field's text the way the popup script does: the most
specific name in it wins, so "Hall A, rack A07" points at the rack, and
"a23-ct18" (compute tray 18) points at rack A23 with a note naming the tray.
Names the drawings do not show (a fabric leaf switch, a leak controller) do
not resolve, and the field gets no pin.

Racks, CDUs, UPSs, busways, and tap-offs also have an equipment detail sheet
(``detail_drawings``, one per product). ``resolve_part`` reads an alarm's text
for the part it names ("Pump 2 fault" on CDU-B3 is pump 2), using the
``points`` patterns in ``site/details.yaml``, so the popup can open the detail
sheet with that part outlined.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import site_model as S
from .detail_drawings import load_details, parts as product_parts
from .site_drawings import sheets

# How specific each kind is: when a field names several things, the most specific wins.
RANK = {"area": 1, "hall": 2, "room": 3, "group": 4, "equipment": 5, "busway": 6, "rack": 6, "tapoff": 7}
KIND_LABEL = {"area": "Area", "hall": "Data hall", "room": "Room", "group": "Power group", "equipment": "Equipment",
              "busway": "Busway", "rack": "Rack", "tapoff": "Tap-off"}

# Names inside longer device strings. Each: (pattern, flags, name template, note template); {0} is the whole
# match, {1}.. the groups. Names are upper-cased. The same list drives the popup script, so keep it JS-safe.
RULES: list[tuple[str, str, str, str]] = [
    (r"(?<![\w-])TO-[A-C]\d{2}(?:-[AB])?(?![\w-])", "", "{0}", ""),
    (r"(?<![\w-])BW-[A-C]-R\d+-PG-[A-C]\d+-[AB](?![\w-])", "", "{0}", ""),
    (r"(?<![\w-])([a-c]\d{2})-ct(\d+)(?![\w-])", "i", "{1}", "Compute tray {2} in this rack"),
    (r"(?<![\w-])([a-c]\d{2})-nvsw(\d+)(?![\w-])", "i", "{1}", "NVLink switch tray {2} in this rack"),
    (r"(?<![\w-])([A-C]\d{2})_PowerShelf_(\d+)", "", "{1}", "Power shelf {2} in this rack"),
    (r"PSU (\d+) in ([A-C]\d{2}) power shelf (\d+)", "", "{2}", "PSU {1} in power shelf {3} of this rack"),
]


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def build(site: dict[str, Any]) -> dict[str, Any]:
    """Every location entry, the sheets they refer to, and the aliases and rules that find them in text."""
    marks: dict[str, dict[str, list[list[float]]]] = {}
    drawn = sheets(site, marks=marks)
    sheet_meta = {}
    for num, fname, title, svg in drawn:
        w, h = re.search(r'width="(\d+)" height="(\d+)"', svg).groups()
        sheet_meta[num] = {"file": fname, "title": title, "w": int(w), "h": int(h)}
    hall_sheet = {h["id"]: f"A-2{i:02d}" for i, h in enumerate(site["halls"], 1)}
    entries: dict[str, dict[str, Any]] = {}

    def view(sheet: str, primary: list[str], related: list[str] = ()) -> dict[str, Any]:
        boxes = []
        for names, p in ((primary, 1), (related, 0)):
            for n in names:
                if n not in marks[sheet]:
                    raise KeyError(f"{n} is not drawn on sheet {sheet}")
                boxes += [b + [p] for b in marks[sheet][n]]
        return {"s": sheet, "b": boxes}

    details = load_details()
    detail_of = {k: v["sheet"] for k, v in details["products"].items()}

    def add(name: str, kind: str, title: str, text: str, views: list[dict[str, Any]], product: str | None = None) -> None:
        if name in entries:
            raise ValueError(f"duplicate location {name}")
        entries[name] = {"kind": kind, "title": title, "text": text, "rank": RANK[kind], "views": views}
        if product:
            entries[name]["p"] = product
            if product in detail_of:           # the product's detail sheet, last: "what it looks like"
                views.append(view(detail_of[product], ["device"]))

    pl = site["plants"]
    aliases: dict[str, str] = {}
    for h in site["halls"]:
        L, hid, short = h["letter"], h["id"], h["name"].split(" (")[0]
        hs, p, c = hall_sheet[hid], h["power"], h["cooling"]
        rp = S.product(site, h["rack_product"])
        racks = S.racks(site, hid)
        cdus = [f"CDU-{L}{i}" for i in range(1, c["cdu_count"] + 1)]
        ups = S.ups_ids(h)
        add(hid, "hall", h["name"], f"{S.rack_count(h)} x {rp['model']} racks in {h['rows']} rows; state: {h['state']}.",
            [view("A-101", [hid]), view(hs, [hid])])
        aliases[short] = hid
        if h["name"] != short:
            aliases[h["name"]] = hid
        # electrical room on the north side of the hall
        er_items = ups + [f"MUPS-{L}{i}" for i in range(1, p.get("mech_ups_count", 0) + 1)] + \
            [f"MVSST-{L}{i}" for i in range(1, p.get("mvsst_count", 0) + 1)]
        er_text = (f"North of {short}: {_join(er_items)}, batteries, and electrical-room CRAHs." if ups
                   else f"North of {short}: 800 VDC distribution from {_join(er_items)}.")
        add(f"ER-{L}", "room", f"{short} electrical room", er_text, [view("A-101", [f"ER-{L}"]), view("E-001", er_items)])
        aliases[f"{short} electrical room"] = f"ER-{L}"
        # racks
        for r in racks:
            rid = r["rack"]
            if r["group"]:
                pw = (f"Power group {r['group']}: A feed {r['feeds']['A']}, B feed {r['feeds']['B']}.")
                e_view = view("E-001", [r["group"]], [r["feeds"]["A"], r["feeds"]["B"]])
            else:
                pw = f"800 VDC from {r['feeds']['A']} and {r['feeds']['B']} (2N)."
                e_view = view("E-001", [r["feeds"]["A"]], [r["feeds"]["B"]])
            add(rid, "rack", f"Rack {rid}",
                f"{rp['model']} in {short}, row {r['row']}, position {r['position']}. {pw} Cooled by the {short} "
                f"CDU header ({cdus[0]} to {cdus[-1]}, N+{c['cdu_redundancy']}).",
                [view(hs, [rid]), e_view, view("M-001", [f"racks:{hid}"], [f"header:{hid}"] + cdus),
                 view("A-101", [rid], [hid])], h["rack_product"])
        # busways, tap-offs, power groups
        for s in S.busway_segments(site, hid):
            for side in "AB":
                u = s["feeds"][side]
                add(f"{s['id']}-{side}", "busway", f"Busway {s['id']}-{side}",
                    f"{side}-side overhead busway over racks {s['racks'][0]} to {s['racks'][-1]} (row {s['row']}, "
                    f"power group {s['group']}), fed by {u}.",
                    [view(hs, [f"{s['id']}-{side}"], s["racks"]), view("E-001", [u], [s["group"]])], p.get("busway_product"))
            for rid in s["racks"]:
                add(f"TO-{rid}", "tapoff", f"Tap-offs above rack {rid}",
                    f"The A and B tap-offs feeding rack {rid}, on busways {s['id']}-A ({s['feeds']['A']}) and "
                    f"{s['id']}-B ({s['feeds']['B']}).",
                    [view(hs, [f"TO-{rid}-A", f"TO-{rid}-B"], [rid]),
                     view("E-001", [s["feeds"]["A"], s["feeds"]["B"]], [s["group"]])], p.get("busway_product"))
                for side in "AB":
                    add(f"TO-{rid}-{side}", "tapoff", f"Tap-off {rid} {side} side",
                        f"Plugs rack {rid}'s {side} feed into busway {s['id']}-{side}, fed by {s['feeds'][side]}.",
                        [view(hs, [f"TO-{rid}-{side}"], [rid]), view("E-001", [s["feeds"][side]], [s["group"]])],
                        p.get("busway_product"))
        for g in p.get("groups", []):
            gr = [r["rack"] for r in racks if r["group"] == g["id"]]
            a, b = f"UPS-{L}{g['feeds'][0]}", f"UPS-{L}{g['feeds'][1]}"
            add(g["id"], "group", f"Power group {g['id']}",
                f"Racks {gr[0]} to {gr[-1]} ({len(gr)} racks): A busways from {a}, B busways from {b}.",
                [view(hs, [g["id"]], gr), view("E-001", [g["id"]], [a, b])])
        # electrical equipment
        for i, u in enumerate(ups, 1):
            fed = [g["id"] for g in p.get("groups", []) if i in g["feeds"]]
            add(u, "equipment", u, f"{S.product(site, p['ups_product'])['model']} UPS in the {short} electrical room, "
                f"fed by USS-{L}{i} on {S.mv_bus_for(i)}. Feeds power groups {_join(fed)}.",
                [view("E-001", [u], [f"USS-{L}{i}"] + fed), view("A-101", [f"ER-{L}"])], p["ups_product"])
            add(f"USS-{L}{i}", "equipment", f"USS-{L}{i}", f"Unit substation, 13.8 kV to 480 V, from {S.mv_bus_for(i)} to {u}.",
                [view("E-001", [f"USS-{L}{i}"], [u, S.mv_bus_for(i)]), view("A-101", [f"ER-{L}"])])
        for i in range(1, p.get("mech_ups_count", 0) + 1):
            add(f"MUPS-{L}{i}", "equipment", f"MUPS-{L}{i}",
                f"Mechanical UPS in the {short} electrical room: CDU pumps and thermal-wall fans (2N), on {S.mv_bus_for(i)}.",
                [view("E-001", [f"MUPS-{L}{i}"]), view("A-101", [f"ER-{L}"])])
        for i in range(1, p.get("mvsst_count", 0) + 1):
            add(f"MVSST-{L}{i}", "equipment", f"MVSST-{L}{i}",
                f"Solid-state transformer, 13.8 kV to 800 VDC for {short} (2N), on {S.mv_bus_for(i)}.",
                [view("E-001", [f"MVSST-{L}{i}"]), view("A-001", [f"MVSST-{L}{i}"])])
        # cooling
        for i, cdu in enumerate(cdus, 1):
            add(cdu, "equipment", cdu, f"{S.product(site, c['cdu_product'])['model']} in {short}, on the shared "
                f"secondary header with {_join([x for x in cdus if x != cdu])} (N+{c['cdu_redundancy']}). "
                "Racks draw from the header, not from one CDU.",
                [view(hs, [cdu]), view("M-001", [cdu], [f"header:{hid}"]), view("A-101", [cdu], [hid])], c["cdu_product"])
        for i in range(1, c.get("thermal_wall_count", 0) + 1):
            add(f"TW-{L}{i}", "equipment", f"TW-{L}{i}",
                f"{S.product(site, c['thermal_wall_product'])['model']}, in the {short} gallery: "
                "cools the air side of the racks.", [view(hs, [f"TW-{L}{i}"]), view("M-001", [f"TW-{L}{i}"])])
        for i in range(1, c.get("electrical_room_crah_count", 0) + 1):
            add(f"CRAH-{L}{i}", "equipment", f"CRAH-{L}{i}", f"Air handler in the {short} electrical room.",
                [view("M-001", [f"CRAH-{L}{i}"]), view("A-101", [f"ER-{L}"])])
        for n in range(1, h["fire_life_safety"]["vesda_detectors"] + 1):
            if n == 1:
                add(f"VESDA-{L}1", "equipment", f"VESDA-{L}1",
                    f"Aspirating smoke detector for {short}; sampling pipes run along every cold aisle.",
                    [view(hs, [f"VESDA-{L}1"]), view("A-101", [hid])])
            else:
                add(f"VESDA-{L}{n}", "equipment", f"VESDA-{L}{n}",
                    f"Aspirating smoke detector for the {short} electrical room.", [view("A-101", [f"ER-{L}"])])

    # site plants
    for i in range(1, pl["utility"]["transformer_count"] + 1):
        add(f"TX-{i}", "equipment", f"TX-{i}", f"Utility transformer, 138 kV to 13.8 kV, feeding MV-{'AB'[i - 1]}.",
            [view("E-001", [f"TX-{i}"], [f"MV-{'AB'[i - 1]}"]), view("A-001", [f"TX-{i}"])])
    for bus in ("MV-A", "MV-B"):
        add(bus, "equipment", f"{bus} 13.8 kV bus", f"Medium-voltage bus; main-tie-main with the other bus.",
            [view("E-001", [bus]), view("A-001", ["MV switchgear"])])
        add(f"{bus} main breaker", "equipment", f"{bus} main breaker", f"The utility main breaker on {bus}.",
            [view("E-001", [f"{bus} main breaker"], [bus]), view("A-001", ["MV switchgear"])])
    add("MV switchgear", "equipment", "MV switchgear", "The 13.8 kV main-tie-main switchgear (MV-A and MV-B).",
        [view("A-001", ["MV switchgear"]), view("E-001", ["MV switchgear"])])
    gen = pl["generators"]
    for i in range(1, gen["count"] + 1):
        add(f"GEN-{i}", "equipment", f"GEN-{i}", f"Generator {i} of {gen['count']} (N+{gen['redundancy']}) on the "
            "paralleling bus.", [view("A-001", [f"GEN-{i}"], ["Generator yard"]), view("E-001", [f"GEN-{i}"])])
    hr = pl["heat_rejection"]
    subs = pl["mechanical_power"]["chiller_unit_subs"]
    for i in range(1, hr["chiller_count"] + 1):
        add(f"CH-{i:02d}", "equipment", f"CH-{i:02d}", f"Free-cooling chiller {i} of {hr['chiller_count']} "
            f"(N+{hr['chiller_redundancy']}), powered from USS-CH{(i - 1) % subs + 1}.",
            [view("A-001", [f"CH-{i:02d}"]), view("M-001", [f"CH-{i:02d}"])])
    for i in range(1, hr["pump_count"] + 1):
        add(f"FWP-{i}", "equipment", f"FWP-{i}", f"Facility water pump {i} of {hr['pump_count']} "
            f"(N+{hr['pump_redundancy']}), in the pump room.", [view("M-001", [f"FWP-{i}"]), view("A-101", ["Pump room"])])
    for i in range(1, subs + 1):
        add(f"USS-CH{i}", "equipment", f"USS-CH{i}", f"Unit substation for the chillers, on {S.mv_bus_for(i)}.",
            [view("E-001", [f"USS-CH{i}"], [S.mv_bus_for(i)]), view("A-001", [f"USS-CH{i}"])])
    add("Generator yard", "area", "Generator yard", f"{gen['count']} generators north of the building.",
        [view("A-001", ["Generator yard"])])
    add("Chiller yard", "area", "Chiller yard", f"{hr['chiller_count']} chillers south of the building.",
        [view("A-001", ["Chiller yard"])])
    for room, text in (("MMR-1", "Meet-me room, west: carrier entrance."), ("MMR-2", "Meet-me room, east: carrier entrance."),
                       ("NOC", "Site operations and the Incident Commander's desk."),
                       ("Spares cage", "On-site spares: trays, PSUs, optics."), ("Security lobby", "Mantrap and guard desk."),
                       ("Pump room", "Facility water pumps."), ("Fire riser", "Fire alarm control panel.")):
        add(room, "room", room, text, [view("A-101", [room])])
    parts_out = {}
    for key, spec in details["products"].items():
        num = spec["sheet"]
        ps = {}
        for pid, part in product_parts(spec).items():
            rel = [pid.split("-")[0]] if "-psu" in pid else []          # a PSU shows its shelf, dashed
            ps[pid] = {"label": part["label"], "b": view(num, [pid], rel)["b"]}
        parts_out[key] = {"sheet": num, "parts": ps}
    return {"sheets": sheet_meta, "entries": entries, "aliases": aliases, "rules": [list(r) for r in RULES],
            "details": parts_out, "points": [list(p) + [""] * (5 - len(p)) for p in details["points"]]}


LOCATIONS_JSON = Path(__file__).resolve().parents[2] / "docs" / "site" / "locations.json"


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """The generated locations (``docs/site/locations.json``, written by ``scripts/render_site.py``)."""
    return json.loads(LOCATIONS_JSON.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Reading names out of a field (mirrors the popup script)
# --------------------------------------------------------------------------- #
def _names_re(data: dict[str, Any]) -> re.Pattern:
    names = sorted(set(data["entries"]) | set(data["aliases"]), key=lambda n: (-len(n), n))
    return re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])")


def _fill(t: str, m: re.Match) -> str:
    return re.sub(r"\{(\d)\}", lambda x: m.group(int(x.group(1))), t)


def resolve(data: dict[str, Any], text: str) -> tuple[str, str] | None:
    """(location name, note) for the most specific location named in ``text``; None if it names none."""
    best = None   # (rank, -position, name, note)
    for pat, flags, name_t, note_t in data["rules"]:
        for m in re.finditer(pat, text, re.I if "i" in flags else 0):
            name = _fill(name_t, m).upper()
            if name in data["entries"]:
                cand = (data["entries"][name]["rank"], -m.start(), name, _fill(note_t, m))
                best = max(best, cand) if best else cand
    for m in _names_re(data).finditer(text):
        name = data["aliases"].get(m.group(0), m.group(0))
        cand = (data["entries"][name]["rank"], -m.start(), name, "")
        best = max(best, cand) if best else cand
    return (best[2], best[3]) if best else None


def resolve_field(data: dict[str, Any], value: str) -> tuple[str, str] | None:
    """A field's ``data-loc`` value: names separated by "|", most useful first (a device, then its room).
    Falling back past the first names it in the note, so the card never implies the drawing shows it."""
    parts = value.split("|")
    for i, part in enumerate(parts):
        r = resolve(data, part)
        if r and i and parts[0].strip():
            return r[0], f"The drawings do not show {parts[0].strip()}; shown at its recorded location"
        if r:
            return r
    return None


def _fill_part(t: str, m: re.Match) -> str:
    """Like ``_fill``, but numbers lose leading zeros: "a22-ct07" is compute tray 7."""
    return re.sub(r"\{(\d)\}", lambda x: str(int(m.group(int(x.group(1))))) if m.group(int(x.group(1))).isdigit()
                  else m.group(int(x.group(1))), t)


def resolve_part(data: dict[str, Any], name: str, text: str) -> tuple[str, str] | None:
    """(instance, part id) for the part of a device that ``text`` (an alarm's device, signal, and summary)
    names, when ``name`` (the location the field resolved to) or the device the pattern names has a detail
    sheet with that part. None when the text names no part: the card then opens the site sheets as before."""
    for pat, flags, product, part_t, inst_t in data["points"]:
        m = re.search(pat, text, re.I if "i" in flags else 0)
        if not m:
            continue
        inst = _fill(inst_t, m).upper() if inst_t else name
        e = data["entries"].get(inst)
        if not e or e.get("p") != product or product not in data["details"]:
            continue
        pid = _fill_part(part_t, m)
        if pid in data["details"][product]["parts"]:
            return inst, pid
    return None


def resolve_field_part(data: dict[str, Any], value: str, part_text: str = "") -> tuple[str, str] | None:
    """The part a field names, as the popup script reads it: from the field's ``data-loc`` value and its
    ``data-part`` text. Fields that fell back to a recorded location name no part."""
    r = resolve_field(data, value)
    if not r or r[1].startswith("The drawings do not show"):
        return None
    return resolve_part(data, r[0], (value + " " + part_text).strip())


def part_coverage(data: dict[str, Any], alarms: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """How many alarms land on a device whose product has a detail sheet, and those whose text names no
    part on it (other than the whole-device alarms listed in site/details.yaml). Used by the tests and by
    ``scripts/render_alarms.py --robustness``, so a new kind of alarm cannot silently lose its part."""
    whole = set(load_details().get("whole_device", []))
    checked, missing = 0, []
    for a in alarms:
        value, text = f"{a['device']}|{a['location']}", f"{a['signal']} {a['summary']}"
        r = resolve_field(data, value)
        if not r or r[1].startswith("The drawings do not show"):
            continue
        if data["entries"][r[0]].get("p") not in data["details"]:
            continue
        checked += 1
        if a["signal"] not in whole and not resolve_field_part(data, value, text):
            missing.append(f"{a['device']}: {a['signal']} ({a['summary']})")
    return checked, missing


def card(data: dict[str, Any], name: str, part: tuple[str, str] | None) -> tuple[str, list[tuple[dict, str]]]:
    """The card's title and its views with the label each one outlines, as the popup script builds them:
    a named part puts its product's detail sheet first, labeled with the instance ("CDU-B3 · Pump 2")."""
    e = data["entries"][name]
    label = e["title"] if name.startswith(("HALL-", "ER-")) else name
    views = [(v, label) for v in e["views"]]
    if not part:
        return e["title"], views
    inst, pid = part
    det = data["details"][data["entries"][inst]["p"]]
    pl = det["parts"][pid]["label"]
    first = ({"s": det["sheet"], "b": det["parts"][pid]["b"]}, f"{inst} · {re.sub(r' [(].*[)]$', '', pl)}")
    title = f"{e['title']} · {pl}" if inst == name else f"{e['title']} · {inst} {pl[0].lower() + pl[1:]}"
    return title, [first] + [x for x in views if x[0]["s"] != det["sheet"]]


def subset(data: dict[str, Any], text: str) -> dict[str, Any]:
    """The entries a page can need: every location named anywhere in its text, and the sheets they use."""
    used: set[str] = set()
    for pat, flags, name_t, _ in data["rules"]:
        for m in re.finditer(pat, text, re.I if "i" in flags else 0):
            used.add(_fill(name_t, m).upper())
    used |= {data["aliases"].get(m.group(0), m.group(0)) for m in _names_re(data).finditer(text)}
    # an alarm can name a device by pattern only (the UPS behind "UPS-B4 output feeder"): keep those too
    for pat, flags, _, _, inst_t in data["points"]:
        if inst_t:
            used |= {_fill(inst_t, m).upper() for m in re.finditer(pat, text, re.I if "i" in flags else 0)}
    entries = {n: e for n, e in data["entries"].items() if n in used}
    products = {e["p"] for e in entries.values() if e.get("p") in data["details"]}
    sheets_used = {v["s"] for e in entries.values() for v in e["views"]}
    return {"sheets": {k: v for k, v in data["sheets"].items() if k in sheets_used}, "entries": entries,
            "aliases": {a: n for a, n in data["aliases"].items() if n in entries}, "rules": data["rules"],
            "details": {k: v for k, v in data["details"].items() if k in products},
            "points": [p for p in data["points"] if p[2] in products]}


# --------------------------------------------------------------------------- #
# A highlighted drawing as one SVG (the Scorecards app, where no page script runs)
# --------------------------------------------------------------------------- #
def focus_box(view: dict[str, Any], sheet: dict[str, Any]) -> list[float]:
    """The part of the sheet to show: the outlined items with room around them, wide like the card.
    Same rule as the popup script's ``focusBox``."""
    x0 = min(b[0] for b in view["b"]); y0 = min(b[1] for b in view["b"])
    x1 = max(b[0] + b[2] for b in view["b"]); y1 = max(b[1] + b[3] for b in view["b"])
    w, h = x1 - x0, y1 - y0
    pad = max(90, 0.35 * max(w, h))
    w, h = max(w + 2 * pad, 560), max(h + 2 * pad, 350)
    if w / h < 1.6:
        w = h * 1.6
    else:
        h = w / 1.6
    if w >= sheet["w"] * 0.85 or h >= sheet["h"] * 0.85:
        return [0, 0, sheet["w"], sheet["h"]]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return [min(max(cx - w / 2, 0), sheet["w"] - w), min(max(cy - h / 2, 0), sheet["h"] - h), w, h]


def highlighted_svg(data: dict[str, Any], svg: str, view: dict[str, Any], label: str) -> str:
    """``svg`` cropped to the item, with the red outline, the dashed connected items, and a labeled arrow."""
    import math
    from xml.sax.saxutils import escape
    vb = focus_box(view, data["sheets"][view["s"]])
    f = vb[2] / 700
    parts = []
    for x, y, w, h, p in sorted(view["b"], key=lambda b: b[4]):
        if p:
            parts.append(f'<rect x="{x - 3 * f:.1f}" y="{y - 3 * f:.1f}" width="{w + 6 * f:.1f}" height="{h + 6 * f:.1f}" rx="{2 * f:.1f}" '
                         f'fill="#d62728" fill-opacity="0.08" stroke="#d62728" stroke-width="{3 * f:.1f}"/>')
        else:
            parts.append(f'<rect x="{x - 2 * f:.1f}" y="{y - 2 * f:.1f}" width="{w + 4 * f:.1f}" height="{h + 4 * f:.1f}" rx="{2 * f:.1f}" '
                         f'fill="none" stroke="#e8833a" stroke-width="{2 * f:.1f}" stroke-dasharray="{6 * f:.1f} {4 * f:.1f}"/>')
    x, y, w, _, _ = next(b for b in view["b"] if b[4])
    right, up = x + w + (60 + len(label) * 7.6 + 16) * f < vb[0] + vb[2], y - 90 * f > vb[1]
    tip_x, tip_y = (x + w + 3 * f if right else x - 3 * f), (y - 3 * f if up else y + 3 * f)
    tx, ty = tip_x + (46 if right else -46) * f, tip_y + (-40 if up else 40) * f
    parts.append(f'<line x1="{tx:.1f}" y1="{ty:.1f}" x2="{tip_x + (7 if right else -7) * f:.1f}" y2="{tip_y + (-6 if up else 6) * f:.1f}" '
                 f'stroke="#d62728" stroke-width="{3 * f:.1f}" stroke-linecap="round"/>')
    a, ln, s = math.atan2(tip_y - ty, tip_x - tx), 13 * f, 0.45
    pts = [(tip_x, tip_y), (tip_x - ln * math.cos(a - s), tip_y - ln * math.sin(a - s)),
           (tip_x - ln * math.cos(a + s), tip_y - ln * math.sin(a + s))]
    parts.append(f'<polygon points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in pts)}" fill="#d62728"/>')
    fs, lw, lh = 13 * f, (len(label) * 7.6 + 16) * f, 22 * f
    lx, ly = (tx if right else tx - lw), (ty - lh if up else ty)
    parts.append(f'<rect x="{lx:.1f}" y="{ly:.1f}" width="{lw:.1f}" height="{lh:.1f}" rx="{3 * f:.1f}" fill="#d62728"/>')
    parts.append(f'<text x="{lx + lw / 2:.1f}" y="{ly + lh / 2 + fs * 0.36:.1f}" font-family="Helvetica, Arial, sans-serif" '
                 f'font-size="{fs:.1f}" font-weight="bold" fill="#fff" text-anchor="middle">{escape(label)}</text>')
    head = re.sub(r'width="\d+" height="\d+" viewBox="[^"]*"',
                  f'viewBox="{vb[0]:.1f} {vb[1]:.1f} {vb[2]:.1f} {vb[3]:.1f}" preserveAspectRatio="xMidYMid meet"', svg, count=1)
    return head.replace("</svg>", '<g class="loc-hl">' + "".join(parts) + "</g>\n</svg>")
