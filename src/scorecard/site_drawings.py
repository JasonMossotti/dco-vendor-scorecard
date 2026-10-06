"""Schematic drawings of the site, generated from site/site.yaml.

Every sheet is drawn from the site model, so the drawings, the SLA, and the
telemetry always agree on what exists and where. Sheets follow drawing-set
conventions (A = architectural, E = electrical, M = mechanical) and carry a
title strip. They are schematic: plan sheets are drawn to a stated scale,
diagrams are not to scale, and nothing here is a construction document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from scorecard import site_model as S

# --------------------------------------------------------------------------- #
# Drawing tokens
# --------------------------------------------------------------------------- #
INK = "#1e2933"
MUTED = "#6b7785"
FAINT = "#c9d0d8"
GRID = "#eef1f4"
PAPER = "#ffffff"
RACK = "#d5dbe2"
FEED_A = "#1f5fbf"        # A-side power
FEED_B = "#c0640f"        # B-side power
SUPPLY = "#0b78a8"        # facility water supply
RETURN = "#c2362b"        # facility water return
SECONDARY = "#2f8f5b"     # CDU secondary loop (PG25)
COLD_AISLE = "#eaf3fa"
HOT_AISLE = "#fbeceb"
LEAK = "#0f9d8a"
VESDA = "#7a4fd0"
EQUIP = "#e3efe8"
FONT = "Helvetica, Arial, sans-serif"

PROJECT = "Site AUS-1 (fictional)  |  DCO Vendor Scorecard"


@dataclass
class Svg:
    width: float
    height: float
    parts: list[str] = field(default_factory=list)
    marks: dict[str, list[list[float]]] = field(default_factory=dict)

    def mark(self, name: str, x: float, y: float, w: float, h: float) -> None:
        """Record where ``name`` is drawn (a box in sheet coordinates). Not rendered: the location
        popups read these boxes to outline an item on the sheet (see ``scorecard.locations``)."""
        self.marks.setdefault(name, []).append([round(x, 1), round(y, 1), round(w, 1), round(h, 1)])

    def add(self, s: str) -> None:
        self.parts.append(s)

    def rect(self, x, y, w, h, fill="none", stroke=INK, sw=1.0, rx=0, dash=None, opacity=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        o = f' fill-opacity="{opacity}"' if opacity is not None else ""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}{o}/>')

    def line(self, x1, y1, x2, y2, stroke=INK, sw=1.0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def poly(self, pts, stroke=INK, sw=1.0, fill="none", dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.add(f'<polyline points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def circle(self, cx, cy, r, fill=PAPER, stroke=INK, sw=1.0):
        self.add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, s, size=11, anchor="start", fill=INK, weight="normal", italic=False):
        st = ' font-style="italic"' if italic else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
                 f'text-anchor="{anchor}" fill="{fill}" font-weight="{weight}"{st}>{escape(str(s))}</text>')

    def done(self, marks: dict | None) -> str:
        if marks is not None:
            marks.update(self.marks)
        return self.render()

    def render(self) -> str:
        body = "\n".join(self.parts)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" height="{self.height:.0f}" '
                f'viewBox="0 0 {self.width:.0f} {self.height:.0f}">\n'
                f'<rect width="100%" height="100%" fill="{PAPER}"/>\n{body}\n</svg>\n')


def detail_refs(site: dict, keys: list[str], halls: list[dict] | None = None) -> str:
    """ "rack D-101, CDU D-201": the detail sheets for the products these halls use (keys into the hall,
    its power, or its cooling), in sheet order. Products without a detail sheet are left out."""
    from scorecard.detail_drawings import sheet_products
    have = sheet_products()
    word = {"rack_product": "rack", "cdu_product": "CDU", "ups_product": "UPS line-up", "busway_product": "busway and tap-off"}
    found = {}
    for h in halls or site["halls"]:
        for k in keys:
            p = h.get(k) or h["power"].get(k) or h["cooling"].get(k)
            if p in have:
                found.setdefault(have[p], f"{word[k]} {have[p]}")
    return ", ".join(found[n] for n in sorted(found))


def frame(svg: Svg, sheet: str, title: str, scale: str) -> None:
    """Border plus a title strip along the bottom edge."""
    W, H = svg.width, svg.height
    svg.rect(8, 8, W - 16, H - 16, stroke=INK, sw=1.4)
    y = H - 52
    svg.line(8, y, W - 8, y, sw=1.4)
    svg.text(20, y + 19, title, size=15, weight="bold")
    svg.text(20, y + 37, f"{PROJECT}  |  {scale}  |  Schematic, not for construction", size=10, fill=MUTED)
    svg.line(W - 120, y, W - 120, H - 8, sw=1.0)
    svg.text(W - 64, y + 21, "Sheet", size=9, anchor="middle", fill=MUTED)
    svg.text(W - 64, y + 40, sheet, size=17, anchor="middle", weight="bold")


def legend(svg: Svg, x: float, y: float, items: list[tuple[str, str, str]], title: str = "Legend") -> float:
    """items: (kind, color, label) with kind in line|dash|dot|box. Returns the bottom y."""
    svg.text(x, y, title, size=11, weight="bold")
    yy = y + 16
    for kind, color, label in items:
        if kind == "box":
            svg.rect(x, yy - 9, 18, 11, fill=color, stroke=INK, sw=0.6)
        else:
            dash = {"line": None, "dash": "6 3", "dot": "1.5 3"}[kind]
            svg.line(x, yy - 4, x + 18, yy - 4, stroke=color, sw=2.4 if kind != "dot" else 2.0, dash=dash)
        svg.text(x + 26, yy, label, size=10)
        yy += 17
    return yy


# --------------------------------------------------------------------------- #
# Hall geometry (meters), shared by the hall and building plans
# --------------------------------------------------------------------------- #
def hall_geometry(site: dict, hall: dict) -> dict:
    lay = site["layout"]
    rp = S.product(site, hall["rack_product"])
    rack_w, rack_d = rp["footprint_mm"][0] / 1000, rp["footprint_mm"][1] / 1000
    cdu_w = S.product(site, hall["cooling"]["cdu_product"])["footprint_mm"][0] / 1000
    n_cdu, rows = hall["cooling"]["cdu_count"], hall["rows"]
    extra = max(0, n_cdu - rows)                       # CDUs beyond one per row sit at the west end
    gallery = lay["thermal_wall_depth_m"] if hall["cooling"].get("thermal_wall_count") else 0.0
    row_len = hall["racks_per_row"] * rack_w + cdu_w + (cdu_w if extra else 0)
    width = 2 * gallery + 2 * lay["end_clearance_m"] + row_len
    pods = rows // 2
    pod_d = 2 * rack_d + lay["hot_aisle_m"]
    depth = (pods + 1) * lay["cold_aisle_m"] + pods * pod_d
    return {"rack_w": rack_w, "rack_d": rack_d, "cdu_w": cdu_w, "gallery": gallery, "row_len": row_len,
            "width": width, "depth": depth, "pods": pods, "pod_d": pod_d, "extra_cdus": extra}


def row_origin(site: dict, hall: dict, g: dict, row: int) -> tuple[float, float, bool]:
    """(x of first rack, y of row top, faces_north) in hall meters. Rows pair back to back."""
    lay = site["layout"]
    pod = (row - 1) // 2
    y_pod = lay["cold_aisle_m"] * (pod + 1) + pod * g["pod_d"]
    first = (row - 1) % 2 == 0
    y = y_pod if first else y_pod + g["rack_d"] + lay["hot_aisle_m"]
    x = g["gallery"] + lay["end_clearance_m"] + (g["cdu_w"] if g["extra_cdus"] else 0)
    return x, y, first


# --------------------------------------------------------------------------- #
# A-201..: hall plans
# --------------------------------------------------------------------------- #
def hall_plan(site: dict, hall_id: str, sheet: str, marks: dict | None = None) -> str:
    hall = S.hall_by_id(site, hall_id)
    g = hall_geometry(site, hall)
    k = 52.0                                            # px per meter
    ox, oy = 60.0, 92.0
    W = max(ox + g["width"] * k + 330, 1000)
    H = max(oy + g["depth"] * k + 150, 760)
    svg = Svg(W, H)
    L = hall["letter"]
    rp = S.product(site, hall["rack_product"])
    maker = "" if "to be selected" in rp["manufacturer"] else rp["manufacturer"] + " "
    svg.text(ox, 40, f"{hall['name']}: {S.rack_count(hall)} x {maker}{rp['model']}", size=17, weight="bold")
    air = ("Hot aisles contained; air enters from the thermal walls." if hall["cooling"].get("thermal_wall_count")
           else "Fully liquid-cooled racks; no thermal walls.")
    svg.text(ox, 60, f"State: {hall['state']}.  Design load {S.hall_it_kw(site, hall):,.0f} kW IT "
                     f"({rp['design_kw']} kW per rack).  {air}", size=11, fill=MUTED)

    def X(m): return ox + m * k
    def Y(m): return oy + m * k

    # metre grid, hall outline, cold aisles
    for i in range(int(g["width"]) + 1):
        svg.line(X(i), Y(0), X(i), Y(g["depth"]), stroke=GRID, sw=0.6)
    for j in range(int(g["depth"]) + 1):
        svg.line(X(0), Y(j), X(g["width"]), Y(j), stroke=GRID, sw=0.6)
    svg.rect(X(0), Y(0), g["width"] * k, g["depth"] * k, stroke=INK, sw=2.4)
    svg.mark(hall_id, X(0), Y(0), g["width"] * k, g["depth"] * k)
    lay = site["layout"]
    inner_x0, inner_x1 = g["gallery"], g["width"] - g["gallery"]
    for p in range(g["pods"] + 1):
        y = p * (lay["cold_aisle_m"] + g["pod_d"])
        svg.rect(X(inner_x0), Y(y), (inner_x1 - inner_x0) * k, lay["cold_aisle_m"] * k, fill=COLD_AISLE, stroke="none")
        svg.text(X(inner_x1) - 6, Y(y + lay["cold_aisle_m"] / 2) + 4, "cold aisle", size=9, anchor="end", fill=MUTED)

    # thermal walls in the galleries
    tw_n = hall["cooling"].get("thermal_wall_count", 0)
    if tw_n:
        per_side = (tw_n + 1) // 2
        for side in (0, 1):
            gx = 0 if side == 0 else g["width"] - g["gallery"]
            svg.rect(X(gx), Y(0), g["gallery"] * k, g["depth"] * k, fill="#f6f7f9", stroke=FAINT, sw=0.8)
            count = per_side if side == 0 else tw_n - per_side
            h = g["depth"] / max(count, 1)
            for i in range(count):
                n = i + 1 + (0 if side == 0 else per_side)
                svg.rect(X(gx + 0.35), Y(i * h + 0.5), (g["gallery"] - 0.7) * k, (h - 1.0) * k, fill="#dfe9f3", stroke=INK, sw=1)
                svg.mark(f"TW-{L}{n}", X(gx + 0.35), Y(i * h + 0.5), (g["gallery"] - 0.7) * k, (h - 1.0) * k)
                svg.text(X(gx + g["gallery"] / 2), Y(i * h + h / 2) + 4, f"TW-{L}{n}", size=11, anchor="middle", weight="bold")
                ax = X(gx + g["gallery"]) + 4 if side == 0 else X(gx) - 4
                arrow = "→" if side == 0 else "←"
                svg.text(ax, Y(i * h + h / 2) + 18, arrow, size=16, anchor="start" if side == 0 else "end", fill=SUPPLY)

    # racks, CDUs, busways, leak cable
    segs = S.busway_segments(site, hall_id)
    by_rack = {r["rack"]: r for r in S.racks(site, hall_id)}
    for row in range(1, hall["rows"] + 1):
        x0, y0, north = row_origin(site, hall, g, row)
        row_racks = [r for r in by_rack.values() if r["row"] == row]
        if north:   # hot aisle below the first row of each pod
            west = g["cdu_w"] if g["extra_cdus"] else 0.0
            svg.rect(X(x0 - west - 0.1), Y(y0 + g["rack_d"]), (len(row_racks) * g["rack_w"] + g["cdu_w"] + west + 0.2) * k,
                     lay["hot_aisle_m"] * k, fill=HOT_AISLE, stroke=RETURN, sw=0.8, dash="4 3")
            svg.text(X(x0 - west + 0.1), Y(y0 + g["rack_d"] + lay["hot_aisle_m"] / 2) + 4,
                     "hot aisle (contained)", size=9, fill=RETURN)
        for r in row_racks:
            rx = X(x0 + (r["position"] - 1) * g["rack_w"])
            svg.rect(rx, Y(y0), g["rack_w"] * k, g["rack_d"] * k, fill=RACK, stroke=INK, sw=0.9)
            svg.mark(r["rack"], rx, Y(y0), g["rack_w"] * k, g["rack_d"] * k)
            svg.text(rx + g["rack_w"] * k / 2, Y(y0 + g["rack_d"] / 2) + 4, r["rack"], size=9.5, anchor="middle")
        # CDU at the east end of the row (and an extra one at the west end where needed)
        cx = X(x0 + len(row_racks) * g["rack_w"])
        cdu_name = f"CDU-{L}{row}"
        svg.rect(cx, Y(y0), g["cdu_w"] * k, g["rack_d"] * k, fill=EQUIP, stroke=SECONDARY, sw=1.6)
        svg.mark(cdu_name, cx, Y(y0), g["cdu_w"] * k, g["rack_d"] * k)
        svg.text(cx + g["cdu_w"] * k / 2, Y(y0 + g["rack_d"] / 2) - 2, "CDU", size=8, anchor="middle", fill=SECONDARY)
        svg.text(cx + g["cdu_w"] * k / 2, Y(y0 + g["rack_d"] / 2) + 9, cdu_name[4:], size=9, anchor="middle", weight="bold")
        if g["extra_cdus"] and row <= g["extra_cdus"]:
            ex = X(x0 - g["cdu_w"])
            n = hall["rows"] + row
            svg.rect(ex, Y(y0), g["cdu_w"] * k, g["rack_d"] * k, fill=EQUIP, stroke=SECONDARY, sw=1.6)
            svg.mark(f"CDU-{L}{n}", ex, Y(y0), g["cdu_w"] * k, g["rack_d"] * k)
            svg.text(ex + g["cdu_w"] * k / 2, Y(y0 + g["rack_d"] / 2) - 2, "CDU", size=8, anchor="middle", fill=SECONDARY)
            svg.text(ex + g["cdu_w"] * k / 2, Y(y0 + g["rack_d"] / 2) + 9, f"{L}{n}", size=9, anchor="middle", weight="bold")
            svg.rect(ex - 3, Y(y0) - 3, g["cdu_w"] * k + 6, g["rack_d"] * k + 6, stroke=LEAK, sw=1.4, dash="6 3")
        # leak sensing cable around the row's manifold side and under the CDU
        ly = Y(y0 + g["rack_d"]) + 3 if north else Y(y0) - 3
        lx0 = X(x0 - g["cdu_w"]) if g["extra_cdus"] and row <= g["extra_cdus"] else X(x0)
        svg.line(lx0 - 4, ly, cx + g["cdu_w"] * k + 4, ly, stroke=LEAK, sw=1.6, dash="6 3")
        svg.rect(cx - 3, Y(y0) - 3, g["cdu_w"] * k + 6, g["rack_d"] * k + 6, stroke=LEAK, sw=1.4, dash="6 3")
        # overhead busways: A and B tracks drawn over the cold-aisle edge of the row
        for s in [s for s in segs if s["row"] == row]:
            first = by_rack[s["racks"][0]]["position"]
            sx0 = X(x0 + (first - 1) * g["rack_w"]) + 2
            sx1 = X(x0 + (first - 1 + len(s["racks"])) * g["rack_w"]) - 2
            base = Y(y0) + 6 if north else Y(y0 + g["rack_d"]) - 12
            svg.line(sx0, base, sx1, base, stroke=FEED_A, sw=2.6)
            svg.line(sx0, base + 6, sx1, base + 6, stroke=FEED_B, sw=2.6)
            for side, yy_ in (("A", base), ("B", base + 6)):
                svg.mark(f"{s['id']}-{side}", sx0, yy_ - 2.5, sx1 - sx0, 5)
                svg.mark(s["group"], sx0, yy_ - 2.5, sx1 - sx0, 5)
                for i_, rk in enumerate(s["racks"]):
                    tx_ = X(x0 + (first - 1 + i_) * g["rack_w"])
                    svg.mark(f"TO-{rk}-{side}", tx_ + 2, yy_ - 2.5, g["rack_w"] * k - 4, 5)
            ty = Y(y0) - 6 if north else Y(y0 + g["rack_d"]) + 14
            svg.text((sx0 + sx1) / 2, ty, s["group"], size=8.5, anchor="middle", fill=MUTED)

    # VESDA sampling pipe along each cold aisle and the detector
    for p in range(g["pods"] + 1):
        y = p * (lay["cold_aisle_m"] + g["pod_d"]) + lay["cold_aisle_m"] * 0.8
        svg.line(X(inner_x0 + 0.4), Y(y), X(inner_x1 - 0.4), Y(y), stroke=VESDA, sw=1.6, dash="1.5 3")
    svg.rect(X(inner_x0 + 0.2), Y(0.15), 44, 14, fill="#efe9fb", stroke=VESDA, sw=1)
    svg.mark(f"VESDA-{L}1", X(inner_x0 + 0.2), Y(0.15), 44, 14)
    svg.text(X(inner_x0 + 0.2) + 22, Y(0.15) + 10.5, "VESDA", size=8.5, anchor="middle", fill=VESDA)

    # scale bar
    sy = Y(g["depth"]) + 30
    for i in range(5):
        svg.rect(X(i), sy, k, 6, fill=INK if i % 2 == 0 else PAPER, stroke=INK, sw=0.8)
    svg.text(X(0), sy + 20, "0", size=9)
    svg.text(X(5), sy + 20, "5 m", size=9, anchor="middle")

    # legend and notes
    lx = X(g["width"]) + 34
    yy = legend(svg, lx, oy + 4, [
        ("box", RACK, f"{rp['model']} rack"),
        ("box", EQUIP, "CoolIT CHx2000 CDU (in row)"),
        ("box", "#dfe9f3", "Liebert CWA thermal wall"),
        ("box", HOT_AISLE, "Contained hot aisle"),
        ("line", FEED_A, "A-side busway (overhead)"),
        ("line", FEED_B, "B-side busway (overhead)"),
        ("dash", LEAK, "TraceTek leak sensing cable"),
        ("dot", VESDA, "VESDA sampling pipe"),
    ] if tw_n else [
        ("box", RACK, "800 VDC rack (planned)"),
        ("box", EQUIP, "CoolIT CHx2000 CDU (in row)"),
        ("box", HOT_AISLE, "Hot aisle"),
        ("dash", LEAK, "TraceTek leak sensing cable"),
        ("dot", VESDA, "VESDA sampling pipe"),
    ])
    yy += 10
    svg.text(lx, yy, "Notes", size=11, weight="bold")
    c = hall["cooling"]
    notes = [f"CDUs share one secondary header (N+{c['cdu_redundancy']}).",
             "A rack is served by the header, not",
             "only by the CDU in its row.",
             "",
             "Leak cable runs along the manifold",
             "side of every row and under every CDU.",
             "Racks back onto the hot aisle."]
    if hall["power"]["architecture"] == "distributed_redundant":
        notes += ["", "Labels above busways are power",
                  "groups; each group pairs two UPS",
                  "modules (see sheet E-001)."]
    else:
        notes += ["", "800 VDC busway layout is set in", "pilot design (see sheet E-001)."]
    refs = detail_refs(site, ["rack_product", "cdu_product", "busway_product"], [hall])
    if refs:
        notes += ["", "Typical details:"] + [f"  {r}" for r in refs.split(", ")]
    for i, n in enumerate(notes):
        svg.text(lx, yy + 16 + i * 14, n, size=10, fill=MUTED if n else INK)
    frame(svg, sheet, f"{hall['name']} floor plan", "Scale: grid 1 m")
    return svg.done(marks)


DOCK_W, NORTH_D, SOUTH_D = 11.0, 9.0, 7.0


def building_dims(site: dict) -> tuple[float, float]:
    """(width, depth) of the building in meters, from the halls it contains."""
    geos = [hall_geometry(site, h) for h in site["halls"]]
    return DOCK_W + sum(g["width"] for g in geos), NORTH_D + max(g["depth"] for g in geos) + SOUTH_D


# --------------------------------------------------------------------------- #
# A-101: building plan
# --------------------------------------------------------------------------- #
def building_plan(site: dict, sheet: str = "A-101", marks: dict | None = None) -> str:
    k = 17.0
    ox, oy = 50.0, 110.0
    halls = site["halls"]
    geos = [hall_geometry(site, h) for h in halls]
    dock_w, north_d, south_d = DOCK_W, NORTH_D, SOUTH_D
    hall_d = max(g["depth"] for g in geos)
    widths = [g["width"] for g in geos]
    bw = dock_w + sum(widths)
    bd = north_d + hall_d + south_d
    W, H = ox + bw * k + 300, oy + bd * k + 140
    svg = Svg(W, H)
    svg.text(ox, 42, "Building plan", size=17, weight="bold")
    svg.text(ox, 62, "Electrical rooms on the north side of each hall, support spaces and a secure corridor to the south.",
             size=11, fill=MUTED)

    def X(m): return ox + m * k
    def Y(m): return oy + m * k

    svg.rect(X(0), Y(0), bw * k, bd * k, sw=2.6)
    # dock and staging zone
    svg.rect(X(0), Y(0), dock_w * k, (north_d + hall_d) * k, fill="#f6f7f9", stroke=INK, sw=1.2)
    svg.text(X(dock_w / 2), Y(4), "Loading dock", size=11, anchor="middle", weight="bold")
    svg.text(X(dock_w / 2), Y(5.2), "2 truck positions", size=9, anchor="middle", fill=MUTED)
    svg.line(X(0), Y(9), X(dock_w), Y(9), sw=1.0)
    svg.text(X(dock_w / 2), Y(12), "Staging and", size=11, anchor="middle", weight="bold")
    svg.text(X(dock_w / 2), Y(13.2), "burn-in", size=11, anchor="middle", weight="bold")
    svg.text(X(dock_w / 2), Y(14.5), "rack receiving, power-on", size=9, anchor="middle", fill=MUTED)
    svg.text(X(dock_w / 2), Y(15.6), "and acceptance tests", size=9, anchor="middle", fill=MUTED)
    for i in (0, 1):
        svg.rect(X(1.5 + i * 4.4), Y(-0.6), 3.6 * k, 0.6 * k, fill=INK, stroke=INK)

    x = dock_w
    for h, g in zip(halls, geos):
        # electrical room band
        svg.rect(X(x), Y(0), g["width"] * k, north_d * k, fill="#fdf6ec", stroke=INK, sw=1.2)
        svg.mark(f"ER-{h['letter']}", X(x), Y(0), g["width"] * k, north_d * k)
        short = h["name"].split(" (")[0]
        if h["power"].get("ups_count"):
            split = g["width"] * 0.62
            svg.line(X(x + split), Y(0), X(x + split), Y(north_d), sw=0.8)
            cx_ = x + split / 2
            svg.text(X(cx_), Y(3.2), f"{short} electrical", size=10, anchor="middle", weight="bold")
            svg.text(X(cx_), Y(4.4), f"UPS-{h['letter']}1..{h['letter']}{h['power']['ups_count']}, "
                     f"MUPS-{h['letter']}1/{h['letter']}2", size=8.5, anchor="middle", fill=MUTED)
            svg.text(X(cx_), Y(5.5), f"CRAH-{h['letter']}1..{h['letter']}{h['cooling']['electrical_room_crah_count']}",
                     size=8.5, anchor="middle", fill=MUTED)
            svg.text(X(x + split + (g["width"] - split) / 2), Y(4.4), "Li-ion", size=9, anchor="middle", fill=MUTED)
            svg.text(X(x + split + (g["width"] - split) / 2), Y(5.5), "battery", size=9, anchor="middle", fill=MUTED)
        else:
            svg.text(X(x + g["width"] / 2), Y(3.2), f"{short} electrical", size=10, anchor="middle", weight="bold")
            svg.text(X(x + g["width"] / 2), Y(4.4), "800 VDC", size=8.5, anchor="middle", fill=MUTED)
            svg.text(X(x + g["width"] / 2), Y(5.5), "distribution", size=8.5, anchor="middle", fill=MUTED)
        # hall
        svg.rect(X(x), Y(north_d), g["width"] * k, hall_d * k, fill=PAPER, stroke=INK, sw=2.0)
        svg.mark(h["id"], X(x), Y(north_d), g["width"] * k, hall_d * k)
        for row in range(1, h["rows"] + 1):
            rx, ry, _ = row_origin(site, h, g, row)
            n = h["racks_per_row"]
            svg.rect(X(x + rx), Y(north_d + ry), n * g["rack_w"] * k, g["rack_d"] * k, fill=RACK, stroke=INK, sw=0.7)
            for p_ in range(n):
                svg.mark(f"{h['letter']}{(row - 1) * n + p_ + 1:02d}", X(x + rx + p_ * g["rack_w"]), Y(north_d + ry),
                         g["rack_w"] * k, g["rack_d"] * k)
            svg.rect(X(x + rx + n * g["rack_w"]), Y(north_d + ry), g["cdu_w"] * k, g["rack_d"] * k,
                     fill=EQUIP, stroke=SECONDARY, sw=1.0)
            svg.mark(f"CDU-{h['letter']}{row}", X(x + rx + n * g["rack_w"]), Y(north_d + ry), g["cdu_w"] * k, g["rack_d"] * k)
            if g["extra_cdus"] and row <= g["extra_cdus"]:
                svg.rect(X(x + rx - g["cdu_w"]), Y(north_d + ry), g["cdu_w"] * k, g["rack_d"] * k,
                         fill=EQUIP, stroke=SECONDARY, sw=1.0)
                svg.mark(f"CDU-{h['letter']}{h['rows'] + row}", X(x + rx - g["cdu_w"]), Y(north_d + ry),
                         g["cdu_w"] * k, g["rack_d"] * k)
        if g["gallery"]:
            for gx in (x, x + g["width"] - g["gallery"]):
                svg.rect(X(gx), Y(north_d), g["gallery"] * k, hall_d * k, fill="#dfe9f3", stroke=FAINT, sw=0.6)
        svg.text(X(x + g["width"] / 2), Y(north_d + hall_d) - 9, f"{h['name'].split(' (')[0]} ({h['state']})",
                 size=10.5, anchor="middle", weight="bold")
        x += g["width"]

    # south band: corridor and support rooms
    sy = north_d + hall_d
    svg.rect(X(0), Y(sy), bw * k, 2.4 * k, fill="#f3f5f7", stroke=INK, sw=1.0)
    svg.text(X(bw / 2), Y(sy + 1.5), "Secure corridor (badge and camera coverage)", size=9.5, anchor="middle", fill=MUTED)
    rooms = [("Security lobby", "mantrap, guard desk", 7.0), ("MMR-1", "meet-me room, west", 5.0),
             ("NOC", "site ops and IC desk", 7.0), ("Spares cage", "trays, PSUs, optics", 6.0),
             ("Fire riser", "FACP", 4.0), ("Pump room", "FWP-1..3", 6.0),
             ("Telecom", "OOB network", 5.0)]
    used = sum(r[2] for r in rooms)
    rooms.append(("MMR-2", "meet-me room, east", bw - used))
    rx = 0.0
    for name, sub, w in rooms:
        svg.rect(X(rx), Y(sy + 2.4), w * k, (south_d - 2.4) * k, fill=PAPER, stroke=INK, sw=1.0)
        svg.mark(name, X(rx), Y(sy + 2.4), w * k, (south_d - 2.4) * k)
        svg.text(X(rx + w / 2), Y(sy + 4.4), name, size=10, anchor="middle", weight="bold")
        svg.text(X(rx + w / 2), Y(sy + 5.5), sub, size=8.5, anchor="middle", fill=MUTED)
        rx += w
    # compass and scale
    cx, cy = X(bw) + 60, oy + 20
    svg.line(cx, cy + 22, cx, cy - 18, sw=1.6)
    svg.poly([(cx - 6, cy - 8), (cx, cy - 20), (cx + 6, cy - 8)], sw=1.6)
    svg.text(cx, cy + 38, "N", size=12, anchor="middle", weight="bold")
    sy2 = Y(bd) + 24
    for i in range(4):
        svg.rect(X(i * 5), sy2, 5 * k, 6, fill=INK if i % 2 == 0 else PAPER, stroke=INK, sw=0.8)
    svg.text(X(0), sy2 + 20, "0", size=9)
    svg.text(X(20), sy2 + 20, "20 m", size=9, anchor="middle")
    legend(svg, X(bw) + 28, oy + 80, [("box", RACK, "Compute racks"), ("box", EQUIP, "CDUs"),
                                      ("box", "#dfe9f3", "Thermal-wall gallery"), ("box", "#fdf6ec", "Electrical rooms")])
    frame(svg, sheet, "Building plan", "Scale: as shown")
    return svg.done(marks)


# --------------------------------------------------------------------------- #
# A-001: campus plan
# --------------------------------------------------------------------------- #
def campus_plan(site: dict, sheet: str = "A-001", marks: dict | None = None) -> str:
    k = 3.4
    ox, oy = 50.0, 100.0
    PW, PD = 250.0, 160.0
    W, H = ox + PW * k + 280, oy + PD * k + 120
    svg = Svg(W, H)
    svg.text(ox, 42, "Campus plan", size=17, weight="bold")
    svg.text(ox, 62, f"{site['site']['location']}.  Grid: {site['site']['grid']}.  "
                     f"Utility service {site['site']['service_voltage_kv']} kV.", size=11, fill=MUTED)

    def X(m): return ox + m * k
    def Y(m): return oy + m * k

    svg.rect(X(0), Y(0), PW * k, PD * k, fill="#fafbf8", stroke=INK, sw=1.2, dash="10 4 2 4")
    svg.text(X(2), Y(-2), "Property line", size=9, fill=MUTED)
    svg.rect(X(10), Y(10), (PW - 20) * k, (PD - 20) * k, stroke=MUTED, sw=1.2, dash="3 3")
    svg.text(X(12), Y(14), "Security fence", size=9, fill=MUTED)

    # building, drawn at its true footprint from the hall geometry
    bw_, bd_ = building_dims(site)
    bx, by = 95.0, 58.0
    svg.rect(X(bx), Y(by), bw_ * k, bd_ * k, fill="#e9edf1", stroke=INK, sw=2.2)
    svg.mark("Data center", X(bx), Y(by), bw_ * k, bd_ * k)
    svg.text(X(bx + bw_ / 2), Y(by + bd_ / 2), "Data center", size=11, anchor="middle", weight="bold")
    svg.text(X(bx + bw_ / 2), Y(by + bd_ / 2) + 14, f"{bw_:.0f} x {bd_:.0f} m (sheet A-101)", size=9,
             anchor="middle", fill=MUTED)
    svg.rect(X(bx), Y(by), DOCK_W * k, NORTH_D * k, fill="#dde3ea", stroke=INK, sw=1.0)
    svg.text(X(bx + DOCK_W / 2), Y(by + NORTH_D / 2) + 3, "dock", size=8.5, anchor="middle")

    # entrance road, guard house, truck court at the dock, parking by the lobby
    svg.line(X(0), Y(64), X(62), Y(64), stroke=MUTED, sw=7)
    svg.text(X(4), Y(60), "Main gate and access road", size=9, fill=MUTED)
    svg.rect(X(16), Y(67), 9 * k, 6 * k, fill="#f6e9e9", stroke=INK, sw=1.0)
    svg.text(X(20.5), Y(78), "Guard house", size=9, anchor="middle")
    svg.rect(X(62), Y(52), 33 * k, 18 * k, fill="#f3f5f7", stroke=FAINT, sw=0.8)
    svg.text(X(78.5), Y(62), "Truck court", size=9, anchor="middle", fill=MUTED)
    for i in range(9):
        svg.rect(X(40 + i * 5.5), Y(90), 2.6 * k, 5 * k, stroke=FAINT, sw=0.8)
    svg.text(X(40), Y(101), "Staff and visitor parking (lobby entrance)", size=9, fill=MUTED)

    # generator yard, north of the electrical rooms
    g = site["plants"]["generators"]
    gw, gap = 12.0, 2.5
    gx0, gy = bx - 4, 30.0
    svg.rect(X(gx0 - 2), Y(gy - 3), (g["count"] * (gw + gap) + 1.5) * k, 11 * k, stroke=MUTED, sw=0.8, dash="3 3")
    svg.mark("Generator yard", X(gx0 - 2), Y(gy - 3), (g["count"] * (gw + gap) + 1.5) * k, 11 * k)
    for i in range(g["count"]):
        x = gx0 + i * (gw + gap)
        svg.rect(X(x), Y(gy), gw * k, 5 * k, fill="#fff3d6", stroke=INK, sw=1.0)
        svg.mark(f"GEN-{i + 1}", X(x), Y(gy), gw * k, 5 * k)
        svg.text(X(x + gw / 2), Y(gy + 3.3), f"GEN-{i + 1}", size=8.5, anchor="middle")
    svg.text(X(gx0 - 2), Y(gy - 6), f"Generator yard: {g['count']} x Cat C175-16 on sub-base fuel tanks "
             f"({g['fuel_hours_at_full_load']} h), hydrocarbon leak cable", size=9.5)

    # chiller yard, south of the pump room
    hr = site["plants"]["heat_rejection"]
    cy0 = by + bd_ + 18
    per_row = (hr["chiller_count"] + 1) // 2
    for i in range(hr["chiller_count"]):
        r, c = divmod(i, per_row)
        x = bx + c * 13.0
        svg.rect(X(x), Y(cy0 + r * 8), 11.5 * k, 4.5 * k, fill="#dff0f7", stroke=INK, sw=1.0)
        svg.mark(f"CH-{i + 1:02d}", X(x), Y(cy0 + r * 8), 11.5 * k, 4.5 * k)
        svg.mark("Chiller yard", X(x), Y(cy0 + r * 8), 11.5 * k, 4.5 * k)
        svg.text(X(x + 5.75), Y(cy0 + r * 8 + 3.0), f"CH-{i + 1:02d}", size=8.5, anchor="middle")
    svg.text(X(bx), Y(cy0 - 4), f"Chiller yard: {hr['chiller_count']} x Liebert AFC free-cooling chillers "
             f"(N+{hr['chiller_redundancy']}), air-cooled, no process water", size=9.5)
    ux = bx + per_row * 13.0 + 3
    svg.rect(X(ux), Y(cy0), 14 * k, 12.5 * k, fill="#fdf6ec", stroke=INK, sw=1.0)
    for i in range(1, site["plants"]["mechanical_power"]["chiller_unit_subs"] + 1):
        svg.mark(f"USS-CH{i}", X(ux), Y(cy0), 14 * k, 12.5 * k)
    svg.text(X(ux + 7), Y(cy0 + 5.5), "USS-CH", size=8.5, anchor="middle")
    svg.text(X(ux + 7), Y(cy0 + 8.5), f"1..{site['plants']['mechanical_power']['chiller_unit_subs']}",
             size=8.5, anchor="middle")

    # MV switchgear, MVSST pad (by Hall C at the east end), utility substation
    mx = bx + bw_ + 8
    svg.rect(X(mx), Y(by + 2), 26 * k, 11 * k, fill="#fdf6ec", stroke=INK, sw=1.2)
    svg.mark("MV switchgear", X(mx), Y(by + 2), 26 * k, 11 * k)
    svg.text(X(mx + 13), Y(by + 6.6), "MV switchgear", size=9, anchor="middle")
    svg.text(X(mx + 13), Y(by + 9.8), "13.8 kV", size=8.5, anchor="middle", fill=MUTED)
    svg.rect(X(mx), Y(by + 17), 16 * k, 9 * k, fill="#e9f1e8", stroke=INK, sw=1.0)
    for h in site["halls"]:
        for i in range(1, h["power"].get("mvsst_count", 0) + 1):
            svg.mark(f"MVSST-{h['letter']}{i}", X(mx), Y(by + 17), 16 * k, 9 * k)
    svg.text(X(mx + 8), Y(by + 20.8), "MVSST", size=8.5, anchor="middle")
    svg.text(X(mx + 8), Y(by + 23.8), "C1 / C2", size=8.5, anchor="middle", fill=MUTED)
    sx = mx + 34
    svg.rect(X(sx), Y(40), 50 * k, 36 * k, fill="#f1f1f1", stroke=INK, sw=1.2, dash="6 3")
    svg.text(X(sx + 25), Y(48), "Utility substation", size=10, anchor="middle", weight="bold")
    svg.text(X(sx + 25), Y(53), "138 kV, utility-owned", size=9, anchor="middle", fill=MUTED)
    for i in (0, 1):
        svg.circle(X(sx + 13 + i * 24), Y(65), 15)
        svg.mark(f"TX-{i + 1}", X(sx + 13 + i * 24) - 15, Y(65) - 15, 30, 30)
        svg.text(X(sx + 13 + i * 24), Y(65) + 3.5, f"TX-{i + 1}", size=8.5, anchor="middle")

    # compass, scale, legend
    cx, cy = X(PW) + 60, oy + 20
    svg.line(cx, cy + 22, cx, cy - 18, sw=1.6)
    svg.poly([(cx - 6, cy - 8), (cx, cy - 20), (cx + 6, cy - 8)], sw=1.6)
    svg.text(cx, cy + 38, "N", size=12, anchor="middle", weight="bold")
    sy = Y(PD) + 22
    for i in range(5):
        svg.rect(X(i * 10), sy, 10 * k, 6, fill=INK if i % 2 == 0 else PAPER, stroke=INK, sw=0.8)
    svg.text(X(0), sy + 20, "0", size=9)
    svg.text(X(50), sy + 20, "50 m", size=9, anchor="middle")
    legend(svg, X(PW) + 28, oy + 80, [("box", "#e9edf1", "Data center building"), ("box", "#fff3d6", "Generators"),
                                      ("box", "#dff0f7", "Chillers"), ("box", "#fdf6ec", "Electrical"),
                                      ("box", "#e9f1e8", "800 VDC pilot (MVSST)")])
    frame(svg, sheet, "Campus plan", "Scale: as shown")
    return svg.done(marks)


# --------------------------------------------------------------------------- #
# E-001: electrical one-line
# --------------------------------------------------------------------------- #
def breaker(svg: Svg, x: float, y: float) -> None:
    svg.rect(x - 6, y - 6, 12, 12, fill=PAPER, stroke=INK, sw=1.2)


def transformer(svg: Svg, x: float, y: float, r: float = 9) -> None:
    svg.circle(x, y - r * 0.6, r)
    svg.circle(x, y + r * 0.6, r, fill="none")


def one_line(site: dict, sheet: str = "E-001", marks: dict | None = None) -> str:
    pl = site["plants"]
    feeders: dict[str, list[tuple[str, str, str]]] = {"MV-A": [], "MV-B": []}   # (id, kind, label)
    for h in site["halls"]:
        L = h["letter"]
        for i in range(1, h["power"].get("ups_count", 0) + 1):
            feeders[S.mv_bus_for(i)].append((f"UPS-{L}{i}", "ups", f"USS-{L}{i}"))
        for i in range(1, h["power"].get("mech_ups_count", 0) + 1):
            feeders[S.mv_bus_for(i)].append((f"MUPS-{L}{i}", "mups", "house sub"))
        for i in range(1, h["power"].get("mvsst_count", 0) + 1):
            feeders[S.mv_bus_for(i)].append((f"MVSST-{L}{i}", "mvsst", ""))
    for i in range(1, pl["mechanical_power"]["chiller_unit_subs"] + 1):
        feeders[S.mv_bus_for(i)].append((f"USS-CH{i}", "chiller", ""))
    step = 88.0
    nA, nB = len(feeders["MV-A"]), len(feeders["MV-B"])
    left = 70.0
    # MV-A: TX-1 at the outer (left) end, feeders, generator tie at the inner end. MV-B mirrors it.
    a_tx = left + 20
    a_feed0 = a_tx + 80
    a_gen = a_feed0 + (nA - 1) * step + 70
    a_end = a_gen + 20
    b_start = a_end + 90
    b_gen = b_start + 20
    b_feed0 = b_gen + 70
    b_tx = b_feed0 + (nB - 1) * step + 80
    b_end = b_tx + 20
    W = b_end + 60
    max_groups = max((len(h["power"].get("groups", [])) for h in site["halls"]), default=0)
    H = max(760, 300 + 250 + 62 + max_groups * 22 + 76)   # the power-group matrix stays clear of the title strip
    svg = Svg(W, H)
    svg.text(left, 40, "Electrical one-line", size=17, weight="bold")
    svg.text(left, 60, "13.8 kV main-tie-main with a generator paralleling bus. Halls A and B: distributed redundant UPS "
                       "(4 make 3). Hall C: 2N MVSST to 800 VDC.", size=11, fill=MUTED)
    yb = 300.0
    for i, (tx, bx0, bx1) in enumerate(((a_tx, left, a_end), (b_tx, b_start, b_end))):
        svg.rect(tx - 50, 92, 100, 30, fill="#f1f1f1", stroke=INK, sw=1.0, dash="5 3")
        svg.text(tx, 111, "Utility 138 kV", size=10, anchor="middle")
        svg.line(tx, 122, tx, 145, sw=1.4)
        transformer(svg, tx, 160, 11)
        svg.mark(f"TX-{i + 1}", tx - 12, 142, 24, 36)
        lx, anchor = (tx + 18, "start") if i == 0 else (tx - 18, "end")
        svg.text(lx, 158, f"TX-{i + 1}", size=10, weight="bold", anchor=anchor)
        svg.text(lx, 171, "25 MVA, 138/13.8 kV", size=9, fill=MUTED, anchor=anchor)
        svg.line(tx, 178, tx, yb, sw=1.4)
        breaker(svg, tx, 250)
        svg.mark(f"MV-{'AB'[i]} main breaker", tx - 7, 243, 14, 14)
        svg.text(tx + (12 if i == 0 else -12), 254, "main", size=9, fill=MUTED, anchor=anchor)
        svg.line(bx0, yb, bx1, yb, sw=4)
        svg.mark(f"MV-{'AB'[i]}", bx0, yb - 4, bx1 - bx0, 8)
        svg.mark("MV switchgear", bx0, yb - 4, bx1 - bx0, 8)
        svg.text((a_feed0 if i == 0 else b_feed0) - 20, yb - 10, f"MV-{'AB'[i]}  13.8 kV", size=11, weight="bold")
    # tie
    svg.line(a_end, yb, b_start, yb, sw=2)
    breaker(svg, (a_end + b_start) / 2, yb)
    svg.text((a_end + b_start) / 2, yb + 22, "tie (N.O., auto)", size=9, anchor="middle", fill=MUTED)
    # generator paralleling bus above the tie
    n = pl["generators"]["count"]
    span = max(b_gen - a_gen + 120, 70 * (n - 1) + 40)
    gx0 = (a_gen + b_gen) / 2 - span / 2
    gx1 = gx0 + span
    gy = 200.0
    svg.line(gx0, gy, gx1, gy, sw=3)
    svg.text((gx0 + gx1) / 2, gy - 50, f"Generator paralleling bus: {n} x Cat C175-16 (N+{pl['generators']['redundancy']}), "
             "EMCP 4.4 master", size=10, weight="bold", anchor="middle")
    for i in range(n):
        x = gx0 + 20 + i * (span - 40) / (n - 1)
        svg.circle(x, gy - 22, 11)
        svg.mark(f"GEN-{i + 1}", x - 12, gy - 34, 24, 24)
        svg.text(x, gy - 18, "G", size=11, anchor="middle", weight="bold")
        svg.text(x, gy - 37, f"GEN-{i + 1}", size=8, anchor="middle", fill=MUTED)
        svg.line(x, gy - 11, x, gy, sw=1.2)
    for x in (a_gen, b_gen):
        svg.line(x, gy, x, yb, sw=1.6)
        breaker(svg, x, (gy + yb) / 2 + 20)
    # feeders
    for bus, x_first in (("MV-A", a_feed0), ("MV-B", b_feed0)):
        for j, (fid, kind, sub) in enumerate(feeders[bus]):
            x = x_first + j * step
            svg.line(x, yb, x, yb + 40, sw=1.3)
            breaker(svg, x, yb + 30)
            if kind in ("ups", "chiller", "mups"):
                transformer(svg, x, yb + 62, 9)
                svg.mark(fid if kind == "chiller" else f"USS-{fid[4:]}" if kind == "ups" else f"{fid}-sub",
                         x - 10, yb + 47, 20, 30)
                svg.text(x + 12, yb + 66, sub if kind != "chiller" else fid, size=8, fill=MUTED)
                svg.line(x, yb + 71, x, yb + 110, sw=1.3)
            else:
                svg.line(x, yb + 40, x, yb + 110, sw=1.3)
            box = {"ups": ("#fdf6ec", "Galaxy VX", "1.5 MW", "to busways"),
                   "mups": ("#fdf6ec", "Galaxy VL", "300 kW", "CDUs, walls"),
                   "mvsst": ("#e9f1e8", "MVSST", "to 800 VDC", "Hall C busway")}
            if kind in box:
                fill, l1, l2, below = box[kind]
                svg.rect(x - 36, yb + 110, 72, 50, fill=fill, stroke=INK, sw=1.2)
                svg.mark(fid, x - 36, yb + 110, 72, 50)
                svg.text(x, yb + 126, fid, size=10, anchor="middle", weight="bold")
                svg.text(x, yb + 139, l1, size=8, anchor="middle", fill=MUTED)
                svg.text(x, yb + 151, l2, size=8, anchor="middle", fill=MUTED)
                svg.line(x, yb + 160, x, yb + 182, sw=1.3)
                svg.text(x, yb + 196, below, size=8, anchor="middle", fill=MUTED)
            else:
                svg.text(x, yb + 124, "chillers", size=8.5, anchor="middle", fill=MUTED)
                chillers = [f"{c:02d}" for c in range(1, pl["heat_rejection"]["chiller_count"] + 1)
                            if (c - 1) % pl["mechanical_power"]["chiller_unit_subs"] + 1 == int(fid[-1])]
                svg.text(x, yb + 138, "CH " + ", ".join(chillers), size=8, anchor="middle", fill=MUTED)

    # distributed redundant matrix for each UPS hall
    my = yb + 250
    svg.text(left, my, "Power groups (distributed redundant). Each group's A busway is fed by one UPS and its B busway "
                       "by another; every pairing is used once, so a lost module's load spreads over the other three.",
             size=10.5)
    mx = left
    for h in [h for h in site["halls"] if h["power"]["architecture"] == "distributed_redundant"]:
        L = h["letter"]
        n_ups = h["power"]["ups_count"]
        y0 = my + 30
        svg.text(mx, y0, f"{h['name']}", size=11, weight="bold")
        cw, rh = 64, 22
        for u in range(n_ups):
            svg.text(mx + 140 + u * cw + cw / 2, y0 + 22, f"UPS-{L}{u + 1}", size=9.5, anchor="middle")
        for gi, g in enumerate(h["power"]["groups"]):
            yy = y0 + 32 + gi * rh
            svg.text(mx, yy + 15, f"{g['id']}  ({g['racks']} racks)", size=9.5)
            svg.mark(g["id"], mx - 4, yy + 1, 140 + n_ups * cw, rh - 2)
            for u in range(n_ups):
                cx = mx + 140 + u * cw
                svg.rect(cx + 4, yy + 3, cw - 8, rh - 6, fill=PAPER, stroke=FAINT, sw=0.6)
                if u + 1 == g["feeds"][0]:
                    svg.rect(cx + 4, yy + 3, cw - 8, rh - 6, fill=FEED_A, stroke=FEED_A, opacity=0.85)
                    svg.text(cx + cw / 2, yy + 15, "A", size=10, anchor="middle", fill=PAPER, weight="bold")
                elif u + 1 == g["feeds"][1]:
                    svg.rect(cx + 4, yy + 3, cw - 8, rh - 6, fill=FEED_B, stroke=FEED_B, opacity=0.85)
                    svg.text(cx + cw / 2, yy + 15, "B", size=10, anchor="middle", fill=PAPER, weight="bold")
        mx += 140 + n_ups * cw + 70
    chk = {c.system: c for c in S.capacity_checks(site) if c.scope == "Hall A"}
    worst = next(c for k_, c in chk.items() if k_.startswith("UPS, one module lost"))
    svg.text(mx, my + 52, "With any one UPS lost, the busiest", size=10)
    svg.text(mx, my + 66, f"remaining module carries {worst.load:,.0f} kW", size=10)
    svg.text(mx, my + 80, f"of {worst.capacity:,.0f} kW ({worst.utilization:.0%}).", size=10)
    svg.text(mx, my + 104, "Equipment numbered odd lands on MV-A,", size=10, fill=MUTED)
    svg.text(mx, my + 118, "even on MV-B; the automatic tie covers", size=10, fill=MUTED)
    svg.text(mx, my + 132, "the loss of either 13.8 kV main.", size=10, fill=MUTED)
    svg.text(mx, my + 156, "Typical details: " + detail_refs(site, ["ups_product", "busway_product"]) + ".", size=10, fill=MUTED)
    frame(svg, sheet, "Electrical one-line", "Not to scale")
    return svg.done(marks)


# --------------------------------------------------------------------------- #
# M-001: cooling flow diagram
# --------------------------------------------------------------------------- #
def cooling_flow(site: dict, sheet: str = "M-001", marks: dict | None = None) -> str:
    hr = site["plants"]["heat_rejection"]
    halls = site["halls"]
    n_ch = hr["chiller_count"]
    left = 70.0
    col_w = 470.0
    W = left + col_w * len(halls) + 40
    H = 860
    svg = Svg(W, H)
    svg.text(left, 40, "Cooling flow diagram", size=17, weight="bold")
    svg.text(left, 60, f"One facility water loop ({hr['supply_c']} C supply / {hr['return_c']} C return) serves CDUs, "
                       "thermal walls, and electrical-room CRAHs. CDUs isolate the PG25 secondary loop to the racks.",
             size=11, fill=MUTED)
    # chillers discharge into a plant header, the pumps push into the distribution header
    cw = min(72.0, (W - 2 * left - 200) / n_ch - 8)
    yp, ys, yr = 150.0, 176.0, 196.0
    for i in range(n_ch):
        x = left + i * (cw + 8)
        svg.rect(x, 86, cw, 40, fill="#dff0f7", stroke=INK, sw=1.0)
        svg.mark(f"CH-{i + 1:02d}", x, 86, cw, 40)
        svg.text(x + cw / 2, 104, f"CH-{i + 1:02d}", size=9.5, anchor="middle", weight="bold")
        svg.text(x + cw / 2, 118, "AFC", size=8, anchor="middle", fill=MUTED)
        svg.line(x + cw * 0.3, 126, x + cw * 0.3, yp, stroke=SUPPLY, sw=1.6)
        svg.line(x + cw * 0.7, 126, x + cw * 0.7, yr, stroke=RETURN, sw=1.6)
    plant_end = left + n_ch * (cw + 8) + 30 + hr["pump_count"] * 34
    svg.line(left + cw * 0.3, yp, plant_end, yp, stroke=SUPPLY, sw=3)
    for i in range(hr["pump_count"]):
        x = left + n_ch * (cw + 8) + 22 + i * 34
        svg.circle(x, yp, 10, fill=PAPER, stroke=SUPPLY, sw=1.6)
        svg.mark(f"FWP-{i + 1}", x - 11, yp - 11, 22, 22)
        svg.poly([(x - 5, yp + 5), (x + 6, yp), (x - 5, yp - 5)], stroke=SUPPLY, sw=1.2)
    svg.text(left + n_ch * (cw + 8) + 10, yp - 16, f"FWP-1..{hr['pump_count']} (N+{hr['pump_redundancy']})",
             size=9, fill=MUTED)
    svg.line(plant_end, yp, plant_end, ys, stroke=SUPPLY, sw=3)
    svg.line(left - 20, ys, W - 40, ys, stroke=SUPPLY, sw=4)
    svg.line(left - 20, yr, W - 40, yr, stroke=RETURN, sw=4)
    svg.text(W - 44, ys - 6, f"supply {hr['supply_c']} C", size=9.5, anchor="end", fill=SUPPLY)
    svg.text(W - 44, yr + 15, f"return {hr['return_c']} C", size=9.5, anchor="end", fill=RETURN)
    # per hall
    for hi, h in enumerate(halls):
        x0 = left + hi * col_w
        L, c = h["letter"], h["cooling"]
        top = 240.0
        svg.rect(x0 - 10, top, col_w - 30, 560, stroke=FAINT, sw=1.0, rx=4)
        svg.text(x0 + 44, top + 22, h["name"], size=13, weight="bold")
        svg.text(x0 + 44, top + 38, f"{S.hall_liquid_kw(site, h):,.0f} kW to liquid, {S.hall_air_kw(site, h):,.0f} kW to air",
                 size=9.5, fill=MUTED)
        # drops from headers
        sx, rx_ = x0 + 14, x0 + 28
        svg.line(sx, ys, sx, top + 520, stroke=SUPPLY, sw=2)
        svg.line(rx_, yr, rx_, top + 530, stroke=RETURN, sw=2)
        items = [(f"CDU-{L}{i}", "cdu") for i in range(1, c["cdu_count"] + 1)]
        items += [(f"TW-{L}{i}", "tw") for i in range(1, c.get("thermal_wall_count", 0) + 1)]
        items += [(f"CRAH-{L}{i}", "crah") for i in range(1, c.get("electrical_room_crah_count", 0) + 1)]
        for j, (name, kind) in enumerate(items):
            y = top + 62 + j * 41
            bx = x0 + 60
            fill = {"cdu": EQUIP, "tw": "#dfe9f3", "crah": "#eef2f6"}[kind]
            svg.line(sx, y + 10, bx, y + 10, stroke=SUPPLY, sw=1.2)
            svg.line(rx_, y + 22, bx, y + 22, stroke=RETURN, sw=1.2)
            svg.rect(bx, y, 92, 32, fill=fill, stroke=INK, sw=1.0)
            svg.mark(name, bx, y, 92, 32)
            svg.text(bx + 46, y + 14, name, size=9.5, anchor="middle", weight="bold")
            sub = {"cdu": "CHx2000", "tw": "Liebert CWA", "crah": "elec. room"}[kind]
            svg.text(bx + 46, y + 26, sub, size=8, anchor="middle", fill=MUTED)
            if kind == "cdu":
                svg.line(bx + 92, y + 10, x0 + 250, y + 10, stroke=SECONDARY, sw=1.4)
                svg.line(bx + 92, y + 22, x0 + 250, y + 22, stroke=SECONDARY, sw=1.4, dash="5 3")
        n_cdu = c["cdu_count"]
        hy0, hy1 = top + 62 + 10, top + 62 + (n_cdu - 1) * 41 + 22
        svg.line(x0 + 250, hy0, x0 + 250, hy1, stroke=SECONDARY, sw=3)
        svg.text(x0 + 258, hy0 - 6, "shared secondary", size=9, fill=SECONDARY)
        svg.text(x0 + 258, hy0 + 6, "header (PG25)", size=9, fill=SECONDARY)
        rp = S.product(site, h["rack_product"])
        ry = (hy0 + hy1) / 2 - 30
        svg.line(x0 + 250, ry + 30, x0 + 290, ry + 30, stroke=SECONDARY, sw=2)
        svg.rect(x0 + 290, ry, 140, 60, fill=RACK, stroke=INK, sw=1.0)
        svg.mark(f"racks:{h['id']}", x0 + 290, ry, 140, 60)
        svg.mark(f"header:{h['id']}", x0 + 246, hy0, 8, hy1 - hy0)
        svg.text(x0 + 360, ry + 22, f"{S.rack_count(h)} racks", size=10.5, anchor="middle", weight="bold")
        svg.text(x0 + 360, ry + 37, rp["model"][:24], size=8.5, anchor="middle", fill=MUTED)
        svg.text(x0 + 360, ry + 50, "cold plates and manifolds", size=8, anchor="middle", fill=MUTED)
        svg.rect(x0 + 286, ry - 4, 148, 68, stroke=LEAK, sw=1.2, dash="6 3")
        svg.text(x0 + 290, ry + 78, "leak cable at manifolds and CDUs", size=8.5, fill=LEAK)
        svg.text(x0 + 290, ry + 92, f"CDUs N+{c['cdu_redundancy']} on the header", size=8.5, fill=MUTED)
    ly = legend(svg, left + (len(halls) - 1) * col_w + 44, 640, [("line", SUPPLY, "Facility water supply"), ("line", RETURN, "Facility water return"),
                                     ("line", SECONDARY, "CDU secondary supply (PG25)"),
                                     ("dash", SECONDARY, "CDU secondary return"), ("dash", LEAK, "Leak detection zone")])
    svg.text(left + (len(halls) - 1) * col_w + 44, ly + 8, "Typical details: " + detail_refs(site, ["cdu_product", "rack_product"]) + ".",
             size=10, fill=MUTED)
    frame(svg, sheet, "Cooling flow diagram", "Not to scale")
    return svg.done(marks)


# --------------------------------------------------------------------------- #
# Sheet index
# --------------------------------------------------------------------------- #
def sheets(site: dict, marks: dict | None = None) -> list[tuple[str, str, str, str]]:
    """(sheet number, file name, title, svg) for every drawing. Pass ``marks`` (a dict) to also collect,
    per sheet number, where each named item is drawn: {sheet: {name: [[x, y, w, h], ...]}}."""
    m = (lambda num: marks.setdefault(num, {})) if marks is not None else (lambda num: None)
    out = [("A-001", "A-001_campus_plan.svg", "Campus plan", campus_plan(site, marks=m("A-001"))),
           ("A-101", "A-101_building_plan.svg", "Building plan", building_plan(site, marks=m("A-101")))]
    for i, h in enumerate(site["halls"], 1):
        num = f"A-2{i:02d}"
        slug = h["name"].split(" (")[0].lower().replace(" ", "_")
        out.append((num, f"{num}_{slug}_plan.svg", f"{h['name']} floor plan", hall_plan(site, h["id"], num, marks=m(num))))
    out.append(("E-001", "E-001_one_line.svg", "Electrical one-line", one_line(site, marks=m("E-001"))))
    out.append(("M-001", "M-001_cooling_flow.svg", "Cooling flow diagram", cooling_flow(site, marks=m("M-001"))))
    from scorecard.detail_drawings import detail_sheets
    return out + detail_sheets(marks)
