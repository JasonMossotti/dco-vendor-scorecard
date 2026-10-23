"""Security sheets, generated from site/site.yaml (``security``) and config/security.yaml.

A-002 is the property: the fence and its gates, the guard house, the equipment yards behind their own fences, the
utility's substation, exterior cameras with what they see, pole lights, the exterior tour, and zones Z0 to Z2.
A-102 is the building: zones Z3 to Z6, every Customer door, post reader, and camera the security data names
(config/security.yaml), the readers in the access records (the Customer's OPS-MAIN and the Landlord's), and the
interior tour checkpoints. The geometry is the campus plan's (A-001) and the building plan's (A-101).
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from scorecard import site_model as S
from scorecard.site_drawings import (DOCK_W, EQUIP, FAINT, INK, MUTED, NORTH_D, PAPER, RACK, SOUTH_D, Svg,
                                     building_dims, frame, hall_geometry, legend, row_origin, south_rooms)

ROOT = Path(__file__).resolve().parents[2]
SECURITY_CONFIG = ROOT / "config" / "security.yaml"

ZONE_FILL = {"Z0": "#eceef0", "Z1": "#eef6e9", "Z2": "#fdf1dc", "Z3": "#e6eefa", "Z4": "#fbe6d6",
             "Z5": "#e3f4f1", "Z6": "#f4e3f1"}
CAMERA = "#7a3fb0"         # cameras and their view
TOUR = "#b0457a"           # tour route and checkpoints
READER = "#1f5fbf"         # card readers
POST = "#0f7a3b"           # guard posts
LIGHT = "#e0a800"

# Where a label sits beside its symbol on A-002, where the default (right and above) would collide: (anchor, dx, dy) in px.
LABEL_AT = {"GATE-MAIN": ("end", -8, 16), "GATE-PED": ("end", -8, -6), "GATE-GEN": ("end", -8, 15), "GATE-CH": ("end", -8, 17),
            "GATE-MV": ("start", 8, 17), "GATE-UTIL": ("end", -8, -8), "GATE-FIRE": ("start", 8, 16), "GATE-TRUCK": ("start", 8, 14),
            "XC-1": ("start", 6, -4), "XC-3": ("end", -6, -5), "XC-5": ("start", 6, -5), "XC-6": ("end", -7, 3), "XC-8": ("end", -6, -4)}

# The building's place on the campus grid (sheet A-001).
BX, BY = 95.0, 58.0


def security_config() -> dict:
    return yaml.safe_load(SECURITY_CONFIG.read_text(encoding="utf-8"))


def cameras(cfg: dict) -> list[dict]:
    """The Customer cameras as the security data lists them (``synthetic.security``): id, area, recorder, and whether it
    covers a door."""
    c, out, k = cfg["cameras"], [], 0
    for a in c["areas"]:
        for i in range(1, a["count"] + 1):
            out.append({"camera": f"{a['prefix']}-{i:02d}", "area": a["where"], "recorder": c["recorders"][k % len(c["recorders"])],
                        "covers_door": i in a["doors"]})
            k += 1
    return out


def _compass(svg: Svg, cx: float, cy: float) -> None:
    svg.line(cx, cy + 22, cx, cy - 18, sw=1.6)
    svg.poly([(cx - 6, cy - 8), (cx, cy - 20), (cx + 6, cy - 8)], sw=1.6)
    svg.text(cx, cy + 38, "N", size=12, anchor="middle", weight="bold")


def _camera(svg: Svg, x: float, y: float, deg: float, reach: float, label: str = "", spread: float = 32) -> None:
    a1, a2 = math.radians(deg - spread), math.radians(deg + spread)
    svg.poly([(x, y), (x + reach * math.cos(a1), y + reach * math.sin(a1)), (x + reach * math.cos(a2), y + reach * math.sin(a2)),
              (x, y)], stroke="none", fill=CAMERA, sw=0)
    svg.parts[-1] = svg.parts[-1].replace("/>", ' fill-opacity="0.13"/>')
    svg.circle(x, y, 2.6, fill=CAMERA, stroke=CAMERA)
    if label:
        svg.text(x + 4, y - 3, label, size=6.5, fill=CAMERA)


def _reader(svg: Svg, x: float, y: float, label: str = "", color: str = READER, size: float = 7) -> None:
    svg.rect(x - 3, y - 3, 6, 6, fill=color, stroke=color, sw=0.5)
    if label:
        svg.text(x + 5, y + 2.5, label, size=size, fill=color)


def _checkpoint(svg: Svg, x: float, y: float, label: str = "") -> None:
    svg.poly([(x, y - 4.5), (x + 4.5, y), (x, y + 4.5), (x - 4.5, y), (x, y - 4.5)], stroke=TOUR, fill=PAPER, sw=1.4)
    if label:
        svg.text(x + 6, y + 3, label, size=7, fill=TOUR, weight="bold")


def _post(svg: Svg, x: float, y: float, label: str) -> None:
    svg.circle(x, y, 5, fill=POST, stroke=POST)
    svg.text(x, y + 2.6, "P", size=7, anchor="middle", fill=PAPER, weight="bold")
    svg.text(x + 7, y + 3, label, size=7, fill=POST, weight="bold")


def _zone_key(svg: Svg, x: float, y: float, zones: list[dict], ids: list[str], width: float = 250) -> float:
    svg.text(x, y, "Zones", size=11, weight="bold")
    y += 8
    for z in zones:
        if z["id"] not in ids:
            continue
        svg.rect(x, y, 16, 12, fill=ZONE_FILL[z["id"]], stroke=MUTED, sw=0.6)
        svg.text(x + 22, y + 10, f"{z['id']}  {z['name']}", size=9.5, weight="bold")
        svg.text(x + 22, y + 22, f"Controlled by {z['controlled_by']}", size=8, fill=MUTED)
        y += 32
    return y


# --------------------------------------------------------------------------- #
# A-002: security site plan
# --------------------------------------------------------------------------- #
def security_site_plan(site: dict, sheet: str = "A-002", marks: dict | None = None) -> str:
    sec = site["security"]
    k = 3.4
    ox, oy = 50.0, 100.0
    PW, PD, inset = sec["property"]["width_m"], sec["property"]["depth_m"], sec["property"]["fence_inset_m"]
    W, H = ox + PW * k + 330, oy + PD * k + 120
    svg = Svg(W, H)
    svg.text(ox, 42, "Security site plan", size=17, weight="bold")
    svg.text(ox, 62, "The Security Partner guards and patrols the whole property. Zones Z0 to Z2 outside the building; "
                     "the building's zones are on sheet A-102.", size=11, fill=MUTED)

    def X(m): return ox + m * k
    def Y(m): return oy + m * k
    zones = {z["id"]: z for z in sec["zones"]}

    # Z0 band between the property line and the fence, Z1 inside the fence
    svg.rect(X(0), Y(0), PW * k, PD * k, fill=ZONE_FILL["Z0"], stroke=INK, sw=1.2, dash="10 4 2 4")
    svg.mark("Z0", X(0), Y(0), PW * k, PD * k)
    svg.text(X(2), Y(-2), "Property line", size=9, fill=MUTED)
    svg.rect(X(inset), Y(inset), (PW - 2 * inset) * k, (PD - 2 * inset) * k, fill=ZONE_FILL["Z1"], stroke=INK, sw=1.8, dash="9 2")
    svg.mark("Z1", X(inset), Y(inset), (PW - 2 * inset) * k, (PD - 2 * inset) * k)
    svg.mark("Security fence", X(inset), Y(inset), (PW - 2 * inset) * k, (PD - 2 * inset) * k)
    svg.text(X(inset + 12), Y(inset + 4.5), "Security fence (Z1 inside)", size=9, fill=INK)
    svg.text(X(2), Y(PD - 3), "Z0  Public approach", size=9, fill=MUTED, weight="bold")

    # roads, truck court, parking, fire lane
    svg.line(X(0), Y(64), X(62), Y(64), stroke="#9aa4ae", sw=7)
    svg.rect(X(62), Y(52), 33 * k, 18 * k, fill="#f3f5f7", stroke=FAINT, sw=0.8)
    svg.text(X(78.5), Y(67.5), "Truck court", size=9, anchor="middle", fill=MUTED)
    svg.line(X(70), Y(PD - inset), X(70), Y(96), stroke="#c3cad1", sw=5)
    svg.text(X(72), Y(140), "Fire lane", size=8.5, fill=MUTED)
    for i in range(9):
        svg.rect(X(40 + i * 5.5), Y(90), 2.6 * k, 5 * k, stroke=FAINT, sw=0.8)
    svg.text(X(40), Y(88.5), "Staff and visitor parking", size=9, fill=MUTED)

    # equipment yards (Z2), each behind its own fence
    g = site["plants"]["generators"]
    gw, gap, gy = 12.0, 2.5, 30.0
    gen_box = (BX - 6, gy - 3, g["count"] * (gw + gap) + 1.5, 11)
    hr = site["plants"]["heat_rejection"]
    bw_, bd_ = building_dims(site)
    cy0 = BY + bd_ + 18
    per_row = (hr["chiller_count"] + 1) // 2
    ch_box = (BX - 2, cy0 - 4, per_row * 13.0 + 3 + 14 + 2, 21)
    mv_box = (BX + bw_ + 6, BY, 30, 28)
    for name, (x, y, w, h) in (("Generator yard", gen_box), ("Chiller yard", ch_box), ("MV yard", mv_box)):
        svg.rect(X(x), Y(y), w * k, h * k, fill=ZONE_FILL["Z2"], stroke=INK, sw=1.2, dash="5 2")
        svg.mark("Z2", X(x), Y(y), w * k, h * k)
        svg.mark(name, X(x), Y(y), w * k, h * k)
    for i in range(g["count"]):
        x = BX - 4 + i * (gw + gap)
        svg.rect(X(x), Y(gy), gw * k, 5 * k, fill="#fff3d6", stroke=MUTED, sw=0.6)
        svg.text(X(x + gw / 2), Y(gy + 3.3), f"GEN-{i + 1}", size=7.5, anchor="middle", fill=MUTED)
    svg.text(X(gen_box[0]), Y(gen_box[1] - 1.5), "Z2  Generator yard (Landlord)", size=9, weight="bold")
    for i in range(hr["chiller_count"]):
        r, c = divmod(i, per_row)
        svg.rect(X(BX + c * 13.0), Y(cy0 + r * 8), 11.5 * k, 4.5 * k, fill="#dff0f7", stroke=MUTED, sw=0.6)
    svg.rect(X(BX + per_row * 13.0 + 3), Y(cy0), 14 * k, 12.5 * k, fill="#fdf6ec", stroke=MUTED, sw=0.6)
    svg.text(X(ch_box[0]), Y(ch_box[1] + ch_box[3] + 3.5), "Z2  Chiller yard and USS-CH (Landlord)", size=9, weight="bold")
    svg.rect(X(BX + bw_ + 8), Y(BY + 2), 26 * k, 11 * k, fill="#fdf6ec", stroke=MUTED, sw=0.6)
    svg.rect(X(BX + bw_ + 8), Y(BY + 17), 16 * k, 9 * k, fill="#e9f1e8", stroke=MUTED, sw=0.6)
    svg.text(X(BX + bw_ + 21), Y(BY + 8.5), "MV switchgear", size=7.5, anchor="middle", fill=MUTED)
    svg.text(X(BX + bw_ + 16), Y(BY + 22.5), "MVSST", size=7.5, anchor="middle", fill=MUTED)
    svg.text(X(mv_box[0]), Y(mv_box[1] + mv_box[3] + 3.5), "Z2  MV yard (Landlord)", size=9, weight="bold")

    # the utility's substation behind its own fence
    uf = sec["utility_fence"]
    ux, uy = uf["at"]
    uw, uh = uf["size"]
    svg.rect(X(ux), Y(uy), uw * k, uh * k, fill="#f1f1f1", stroke=INK, sw=1.2, dash="6 3")
    svg.mark("Utility substation", X(ux), Y(uy), uw * k, uh * k)
    svg.text(X(ux + uw / 2), Y(uy + 9), "Utility substation", size=10, anchor="middle", weight="bold")
    svg.text(X(ux + uw / 2), Y(uy + 13.5), "utility fence and gate;", size=8.5, anchor="middle", fill=MUTED)
    svg.text(X(ux + uw / 2), Y(uy + 17), "not patrolled", size=8.5, anchor="middle", fill=MUTED)
    for i in (0, 1):
        svg.circle(X(ux + 15 + i * 24), Y(uy + 30), 11, fill=PAPER, stroke=MUTED)
        svg.text(X(ux + 15 + i * 24), Y(uy + 30) + 3, f"TX-{i + 1}", size=7.5, anchor="middle", fill=MUTED)
    svg.line(X(ux + uw), Y(58), X(PW - inset), Y(58), stroke="#c3cad1", sw=4)

    # the building (its zones are on A-102)
    svg.rect(X(BX), Y(BY), bw_ * k, bd_ * k, fill=ZONE_FILL["Z3"], stroke=INK, sw=2.2)
    svg.mark("Data center", X(BX), Y(BY), bw_ * k, bd_ * k)
    svg.text(X(BX + bw_ / 2), Y(BY + bd_ / 2) - 4, "Data center", size=11, anchor="middle", weight="bold")
    svg.text(X(BX + bw_ / 2), Y(BY + bd_ / 2) + 10, "Z3 to Z6: sheet A-102", size=9, anchor="middle", fill=MUTED)
    svg.rect(X(BX), Y(BY), DOCK_W * k, NORTH_D * k, fill="#dde3ea", stroke=INK, sw=1.0)
    svg.text(X(BX + DOCK_W / 2), Y(BY + NORTH_D / 2) + 3, "dock", size=8.5, anchor="middle")
    svg.text(X(BX + 3.5), Y(BY + bd_) - 4, "lobby", size=8.5, anchor="middle")

    # lights along the fence
    sp = sec["lighting"]["fence_spacing_m"]
    pts = []
    x0, y0, x1, y1 = inset, inset, PW - inset, PD - inset
    for t in range(0, int(2 * ((x1 - x0) + (y1 - y0))), sp):
        if t < x1 - x0:
            pts.append((x0 + t, y0))
        elif t < (x1 - x0) + (y1 - y0):
            pts.append((x1, y0 + t - (x1 - x0)))
        elif t < 2 * (x1 - x0) + (y1 - y0):
            pts.append((x1 - (t - (x1 - x0) - (y1 - y0)), y1))
        else:
            pts.append((x0, y1 - (t - 2 * (x1 - x0) - (y1 - y0))))
    pts += [(46, 97.5), (65, 97.5), (88, 97.5), (78, 50)]
    for x, y in pts:
        svg.circle(X(x), Y(y), 2.2, fill=LIGHT, stroke=LIGHT)

    # exterior tour route and checkpoints, starting and ending at the guard house
    gh = sec["guard_house"]
    tour = sec["exterior_tour"]
    cps = {c["id"]: c for c in tour["checkpoints"]}
    route = [tuple(cps[w]["at"]) if isinstance(w, str) else tuple(w) for w in tour["route"]]
    svg.poly([(X(x), Y(y)) for x, y in route], stroke=TOUR, sw=1.3, dash="5 3")
    for c in tour["checkpoints"]:
        _checkpoint(svg, X(c["at"][0]), Y(c["at"][1]))
        anchor, dx, dy = LABEL_AT.get(c["id"], ("start", 6, 3))
        svg.text(X(c["at"][0]) + dx, Y(c["at"][1]) + dy, c["id"], size=7, fill=TOUR, weight="bold", anchor=anchor)
        svg.mark(c["id"], X(c["at"][0]) - 6, Y(c["at"][1]) - 6, 12, 12)

    # gates and barriers
    for gt in sec["gates"]:
        x, y = gt["at"]
        svg.rect(X(x) - 5, Y(y) - 5, 10, 10, fill=PAPER, stroke=INK, sw=1.6)
        svg.line(X(x) - 5, Y(y) - 5, X(x) + 5, Y(y) + 5, sw=1.0)
        svg.mark(gt["id"], X(x) - 6, Y(y) - 6, 12, 12)
        anchor, dx, dy = LABEL_AT.get(gt["id"], ("start", 7, -7))
        svg.text(X(x) + dx, Y(y) + dy, gt["id"], size=7.5, anchor=anchor, weight="bold")
    b1, b2 = sec["barriers"]
    svg.rect(X(b1["at"][0]) - 2, Y(b1["at"][1]) - 8, 4, 16, fill=INK, stroke=INK)
    svg.mark(b1["id"], X(b1["at"][0]) - 3, Y(b1["at"][1]) - 9, 6, 18)
    for i in range(int(b2["to"][0] - b2["at"][0]) // 2 + 1):
        svg.circle(X(b2["at"][0] + 2 * i), Y(b2["at"][1]), 1.6, fill=INK, stroke=INK)
    svg.mark(b2["id"], X(b2["at"][0]) - 2, Y(b2["at"][1]) - 2, (b2["to"][0] - b2["at"][0]) * k + 4, 4)

    # guard house (the patrol post starts here)
    svg.rect(X(gh["at"][0]), Y(gh["at"][1]), gh["size"][0] * k, gh["size"][1] * k, fill="#f6e9e9", stroke=INK, sw=1.2)
    svg.mark("Guard house", X(gh["at"][0]), Y(gh["at"][1]), gh["size"][0] * k, gh["size"][1] * k)
    svg.mark("POST-PATROL", X(gh["at"][0]), Y(gh["at"][1]), gh["size"][0] * k, gh["size"][1] * k)
    svg.text(X(gh["at"][0] + gh["size"][0] / 2), Y(gh["at"][1] + gh["size"][1]) + 11, "Guard house", size=9, anchor="middle")
    _post(svg, X(gh["at"][0] + 2.5), Y(gh["at"][1] + 3), "POST-PATROL")

    # exterior cameras
    for cam in sec["exterior_cameras"]:
        x, y = cam["at"]
        _camera(svg, X(x), Y(y), cam["dir"], 48, cam["id"].replace("CAM-", ""))
        svg.mark(cam["id"], X(x) - 4, Y(y) - 4, 8, 8)

    # compass, scale, legend, zone key
    _compass(svg, X(PW) + 60, oy + 20)
    sy = Y(PD) + 22
    for i in range(5):
        svg.rect(X(i * 10), sy, 10 * k, 6, fill=INK if i % 2 == 0 else PAPER, stroke=INK, sw=0.8)
    svg.text(X(0), sy + 20, "0", size=9)
    svg.text(X(50), sy + 20, "50 m", size=9, anchor="middle")
    lx = X(PW) + 28
    y = _zone_key(svg, lx, oy + 76, sec["zones"], ["Z0", "Z1", "Z2", "Z3"])
    y += 10
    svg.text(lx, y, "Symbols", size=11, weight="bold")
    y += 16
    for draw, text in ((lambda a, b: (svg.rect(a - 5, b - 5, 10, 10, fill=PAPER, stroke=INK, sw=1.6),
                                      svg.line(a - 5, b - 5, a + 5, b + 5)), "Gate (GATE-...)"),
                       (lambda a, b: _camera(svg, a, b, 0, 16), f"Exterior camera (CAM-X, on {sec['exterior_recorder']})"),
                       (lambda a, b: _checkpoint(svg, a, b), f"Exterior tour checkpoint, every {tour['every_h']} h"),
                       (lambda a, b: _post(svg, a, b, ""), "Guard post"),
                       (lambda a, b: svg.circle(a, b, 2.2, fill=LIGHT, stroke=LIGHT), "Pole light"),
                       (lambda a, b: svg.rect(a - 2, b - 8, 4, 16, fill=INK, stroke=INK), "Vehicle barrier")):
        draw(lx + 6, y - 3)
        svg.text(lx + 22, y, text, size=9)
        y += 19
    svg.line(lx, y - 3, lx + 12, y - 3, stroke=TOUR, sw=1.3, dash="5 3")
    svg.text(lx + 22, y, "Exterior tour route", size=9)
    frame(svg, sheet, "Security site plan", "Scale: as shown")
    return svg.done(marks)


# --------------------------------------------------------------------------- #
# A-102: building security zones
# --------------------------------------------------------------------------- #
def interior_positions(site: dict) -> dict:
    """Where each building item sits, in building meters (origin at the building's north-west corner)."""
    halls = site["halls"]
    geos = [hall_geometry(site, h) for h in halls]
    hall_d = max(g["depth"] for g in geos)
    bw, bd = building_dims(site)
    cy = NORTH_D + hall_d                       # corridor top
    rooms = {name: (x, w) for name, _, x, w in south_rooms(bw)}
    hx, x = {}, DOCK_W
    for h, g in zip(halls, geos):
        hx[h["id"]] = (x, g["width"])
        x += g["width"]
    ha, hb = hx["HALL-A"], hx["HALL-B"]
    room_top = cy + 2.4
    doors = {
        "HALL-A": (ha[0] + ha[1] / 2, cy), "HALL-B": (hb[0] + hb[1] / 2, cy),
        "HALL-A-EXIT-N": (ha[0] + 1.2, NORTH_D), "HALL-B-EXIT-N": (hb[0] + 1.2, NORTH_D),
        "SPARES-CAGE": (rooms["Spares cage"][0] + rooms["Spares cage"][1] / 2, room_top),
        "DOCK-INNER": (DOCK_W / 2, cy),
    }
    readers = {
        "Post: Hall A entrance": (ha[0] + ha[1] / 2 + 2.2, cy + 1.2),
        "Post: Hall B entrance": (hb[0] + hb[1] / 2 + 2.2, cy + 1.2),
        "Post: Security console": (3.5, room_top + 1.6),
        "Post: Receiving dock": (DOCK_W / 2 + 2.5, 6.5),
        "OPS-MAIN": (rooms["NOC"][0] + rooms["NOC"][1] / 2, room_top),
        "Main lobby": (3.5, bd),
        "Hall A electrical room": (ha[0] + ha[1] * 0.3, 0.7), "Hall B electrical room": (hb[0] + hb[1] * 0.3, 0.7),
        "Media room": (rooms["Media room"][0] + rooms["Media room"][1] / 2, room_top),
    }
    checkpoints = {
        "Hall A north": (ha[0] + ha[1] * 0.75, NORTH_D + 1.0), "Hall A south": (ha[0] + ha[1] * 0.25, cy - 1.0),
        "Hall A spares aisle": (ha[0] + 1.4, NORTH_D + hall_d / 2), "Hall B north": (hb[0] + hb[1] * 0.75, NORTH_D + 1.0),
        "Hall B south": (hb[0] + hb[1] * 0.25, cy - 1.0), "Hall B deployment area": (hb[0] + hb[1] - 1.4, NORTH_D + hall_d / 2),
        "Receiving dock": (DOCK_W / 2 - 2.5, 4.0), "Corridor east": (bw - 3.0, cy + 1.2),
    }
    return {"halls": hx, "rooms": rooms, "hall_d": hall_d, "bw": bw, "bd": bd, "cy": cy, "room_top": room_top,
            "doors": doors, "readers": readers, "checkpoints": checkpoints}


def _ring(x0: float, y0: float, w: float, h: float, n: int, first: tuple[float, float]) -> list[tuple[float, float]]:
    """n points around a rectangle's inside edge, starting nearest ``first`` and running clockwise."""
    per = 2 * (w + h)
    pts = []
    for i in range(n):
        t = per * i / n
        if t < w:
            pts.append((x0 + t, y0))
        elif t < w + h:
            pts.append((x0 + w, y0 + t - w))
        elif t < 2 * w + h:
            pts.append((x0 + w - (t - w - h), y0 + h))
        else:
            pts.append((x0, y0 + h - (t - 2 * w - h)))
    j = min(range(n), key=lambda i: (pts[i][0] - first[0]) ** 2 + (pts[i][1] - first[1]) ** 2)
    return pts[j:] + pts[:j]


def camera_positions(site: dict, cfg: dict | None = None) -> dict[str, tuple[float, float, float]]:
    """(x, y, direction) of every Customer camera on the building grid. Cameras that cover a door sit by it."""
    cfg = cfg or security_config()
    P = interior_positions(site)
    out: dict[str, tuple[float, float, float]] = {}
    areas = {a["where"]: a for a in cfg["cameras"]["areas"]}
    ha, hb = P["halls"]["HALL-A"], P["halls"]["HALL-B"]
    spares = P["rooms"]["Spares cage"]
    boxes = {"Hall A": (ha[0] + 0.6, NORTH_D + 0.6, ha[1] - 1.2, P["hall_d"] - 1.2, P["doors"]["HALL-A"]),
             "Hall B": (hb[0] + 0.6, NORTH_D + 0.6, hb[1] - 1.2, P["hall_d"] - 1.2, P["doors"]["HALL-B"]),
             "Spares cage": (spares[0] + 0.5, P["room_top"] + 0.5, spares[1] - 1.0, SOUTH_D - 2.4 - 1.0, P["doors"]["SPARES-CAGE"]),
             "Receiving dock": (0.6, 0.6, DOCK_W - 1.2, NORTH_D + P["hall_d"] - 1.2, P["doors"]["DOCK-INNER"])}
    for where, a in areas.items():
        prefix, n = a["prefix"], a["count"]
        if where in boxes:
            x0, y0, w, h, door = boxes[where]
            pts = _ring(x0, y0, w, h, n, door)
            cx, cy = x0 + w / 2, y0 + h / 2
            for i, (x, y) in enumerate(pts, 1):
                out[f"{prefix}-{i:02d}"] = (x, y, math.degrees(math.atan2(cy - y, cx - x)))
        else:                                   # corridor cameras, evenly along the corridor
            for i in range(1, n + 1):
                out[f"{prefix}-{i:02d}"] = (P["bw"] * (i - 0.5) / n, P["cy"] + 0.5, 0.0 if i % 2 else 180.0)
    return out


def building_security(site: dict, sheet: str = "A-102", marks: dict | None = None) -> str:
    sec, cfg = site["security"], security_config()
    P = interior_positions(site)
    k = 17.0
    ox, oy = 50.0, 110.0
    bw, bd, hall_d, cy = P["bw"], P["bd"], P["hall_d"], P["cy"]
    W, H = ox + bw * k + 330, oy + bd * k + 150
    svg = Svg(W, H)
    svg.text(ox, 42, "Building security zones", size=17, weight="bold")
    svg.text(ox, 62, "Every Customer door, post reader, and camera in the security data; the access records' other readers; "
                     "the interior tour.", size=11, fill=MUTED)

    def X(m): return ox + m * k
    def Y(m): return oy + m * k

    def zone(zid: str, name: str, x: float, y: float, w: float, h: float, sw: float = 1.0) -> None:
        svg.rect(X(x), Y(y), w * k, h * k, fill=ZONE_FILL[zid], stroke=INK, sw=sw)
        svg.mark(zid, X(x), Y(y), w * k, h * k)
        svg.mark(name, X(x), Y(y), w * k, h * k)

    svg.rect(X(0), Y(0), bw * k, bd * k, sw=2.6)
    # Z3: dock, staging, corridor; Z4 electrical rooms; Z5 halls
    zone("Z3", "Loading dock", 0, 0, DOCK_W, NORTH_D + hall_d, 1.2)
    svg.text(X(DOCK_W / 2), Y(2.4), "Receiving dock", size=10, anchor="middle", weight="bold")
    svg.text(X(DOCK_W / 2), Y(12.5), "Staging and burn-in", size=9.5, anchor="middle", weight="bold")
    svg.text(X(DOCK_W / 2), Y(13.6), "Z3", size=9, anchor="middle", fill=MUTED)
    for i in (0, 1):
        svg.rect(X(1.5 + i * 4.4), Y(-0.6), 3.6 * k, 0.6 * k, fill=INK, stroke=INK)
    for h in site["halls"]:
        x, w = P["halls"][h["id"]]
        short = h["name"].split(" (")[0]
        zone("Z4", f"ER-{h['letter']}", x, 0, w, NORTH_D, 1.2)
        svg.text(X(x + w / 2), Y(4.2), f"{short} electrical", size=9.5, anchor="middle", weight="bold")
        svg.text(X(x + w / 2), Y(5.4), "Z4  Landlord", size=8.5, anchor="middle", fill=MUTED)
        zone("Z5", h["id"], x, NORTH_D, w, hall_d, 2.0)
        g = hall_geometry(site, h)
        for row in range(1, h["rows"] + 1):
            rx, ry, _ = row_origin(site, h, g, row)
            svg.rect(X(x + rx), Y(NORTH_D + ry), h["racks_per_row"] * g["rack_w"] * k, g["rack_d"] * k, fill=RACK, stroke=FAINT, sw=0.5)
        svg.text(X(x + w / 2), Y(NORTH_D + hall_d / 2) + 4, f"{short}", size=11, anchor="middle", weight="bold")
        svg.text(X(x + w / 2), Y(NORTH_D + hall_d / 2) + 17, "Z5  Customer", size=8.5, anchor="middle", fill=MUTED)
    zone("Z3", "Secure corridor", 0, cy, bw, 2.4, 1.0)
    svg.text(X(bw * 0.62), Y(cy + 1.55), "Secure corridor (Z3)", size=9, anchor="middle", fill=MUTED)
    room_zone = {"Security lobby": "Z3", "NOC": "Z3", "MMR-1": "Z4", "MMR-2": "Z4", "Fire riser": "Z4", "Pump room": "Z4",
                 "Telecom": "Z5", "Spares cage": "Z6", "Media room": "Z6"}
    for name, note, x, w in south_rooms(bw):
        zid = room_zone[name]
        zone(zid, name, x, P["room_top"], w, SOUTH_D - 2.4)
        svg.text(X(x + w / 2), Y(P["room_top"] + 2.3), name, size=9 if w >= 4.5 else 8, anchor="middle", weight="bold")
        svg.text(X(x + w / 2), Y(P["room_top"] + 3.4), zid, size=8.5, anchor="middle", fill=MUTED)

    # doors on the Customer's access control system (config/security.yaml): reader and door contact
    door_names = {d["id"]: d["name"] for d in cfg["doors"]}
    for did, (x, y) in P["doors"].items():
        svg.rect(X(x) - 9, Y(y) - 2.5, 18, 5, fill=PAPER, stroke=READER, sw=1.4)
        svg.mark(did, X(x) - 10, Y(y) - 4, 20, 8)
        svg.mark(door_names[did], X(x) - 10, Y(y) - 4, 20, 8)
        exit_door = did.endswith("EXIT-N")
        if not exit_door:
            _reader(svg, X(x) - 13, Y(y) + (7 if y >= cy else -7))
        if exit_door:
            svg.text(X(x) + 11, Y(y) - 6, did + " (contact only)", size=7.5, fill=READER, weight="bold")
        elif did == "SPARES-CAGE":
            svg.text(X(x) + 11, Y(y) - 6, did, size=7.5, fill=READER, weight="bold")
        else:
            svg.text(X(x) - 11, Y(y) + 17, did, size=7.5, fill=READER, weight="bold", anchor="end")

    # post readers and posts; other readers in the access records
    posts = {p["id"]: p for p in sec["posts"]}
    post_reader = {"POST-HA": "Post: Hall A entrance", "POST-HB": "Post: Hall B entrance", "POST-SOC": "Post: Security console",
                   "POST-DOCK": "Post: Receiving dock"}
    for pid, rname in post_reader.items():
        x, y = P["readers"][rname]
        _post(svg, X(x), Y(y), pid)
        svg.mark(pid, X(x) - 6, Y(y) - 6, 12, 12)
        svg.mark(rname, X(x) - 6, Y(y) - 6, 12, 12)
        _reader(svg, X(x) - 10, Y(y))
    assert set(post_reader) | {"POST-PATROL"} == set(posts)
    for rname, color, lbl in (("OPS-MAIN", READER, "OPS-MAIN"), ("Main lobby", "#8a5a12", ""),
                              ("Hall A electrical room", "#8a5a12", "Landlord reader"),
                              ("Hall B electrical room", "#8a5a12", "Landlord reader"),
                              ("Media room", READER, "two-person")):
        x, y = P["readers"][rname]
        _reader(svg, X(x), Y(y) + (-5 if y >= P["room_top"] - 0.01 and rname != "Main lobby" else 0), lbl, color=color)
        svg.mark(rname if rname != "Media room" else "Media room reader", X(x) - 4, Y(y) - 4, 8, 8)
    lx, lby = P["readers"]["Main lobby"]
    svg.text(X(lx), Y(lby) + 15, "Main lobby reader (Landlord)", size=8, anchor="middle", fill="#8a5a12")
    svg.text(X(lx), Y(lby) + 26, "main entrance and mantrap", size=8, anchor="middle", fill=MUTED)

    # cameras
    for cam, (x, y, d) in camera_positions(site, cfg).items():
        _camera(svg, X(x), Y(y), d, 20, spread=28)
        svg.mark(cam, X(x) - 4, Y(y) - 4, 8, 8)
        short = cam.replace("CAM-", "").replace("-", "")
        svg.text(X(x) + 3, Y(y) - 3, short, size=5.5, fill=CAMERA)

    # interior tour checkpoints
    for name, (x, y) in P["checkpoints"].items():
        _checkpoint(svg, X(x), Y(y))
        svg.mark(f"Checkpoint: {name}", X(x) - 6, Y(y) - 6, 12, 12)

    _compass(svg, X(bw) + 60, oy + 20)
    sy2 = Y(bd) + 30
    for i in range(4):
        svg.rect(X(i * 5), sy2, 5 * k, 6, fill=INK if i % 2 == 0 else PAPER, stroke=INK, sw=0.8)
    svg.text(X(0), sy2 + 20, "0", size=9)
    svg.text(X(20), sy2 + 20, "20 m", size=9, anchor="middle")
    lx = X(bw) + 28
    y = _zone_key(svg, lx, oy + 76, sec["zones"], ["Z3", "Z4", "Z5", "Z6"])
    y += 10
    svg.text(lx, y, "Symbols", size=11, weight="bold")
    y += 16
    n_cams = sum(a["count"] for a in cfg["cameras"]["areas"])
    rec = ", ".join(cfg["cameras"]["recorders"])
    for draw, text in ((lambda a, b: svg.rect(a - 9, b - 2.5, 18, 5, fill=PAPER, stroke=READER, sw=1.4), "Customer door on a contact"),
                       (lambda a, b: _reader(svg, a, b), "Card reader (Customer)"),
                       (lambda a, b: _reader(svg, a, b, color="#8a5a12"), "Card reader (Landlord)"),
                       (lambda a, b: _post(svg, a, b, ""), "Guard post and its reader"),
                       (lambda a, b: _camera(svg, a, b, 0, 14, spread=28), f"Camera ({n_cams}, on {rec})"),
                       (lambda a, b: _checkpoint(svg, a, b), f"Interior tour checkpoint, every {cfg['tours']['every_h']} h")):
        draw(lx + 8, y - 3)
        svg.text(lx + 24, y, text, size=9)
        y += 19
    frame(svg, sheet, "Building security zones", "Scale: as shown")
    return svg.done(marks)
