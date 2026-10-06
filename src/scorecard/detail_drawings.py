"""Equipment detail sheets, generated from site/details.yaml.

One sheet per product, typical of every instance of it (D-101 is every GB200
NVL72 rack on the site). Each sheet draws the parts that carry an alarm point,
plus what a reader needs to find them, in the style of the site sheets, and
records a box for every part (``Svg.mark``) so the location popups can outline
"compute tray 18" or "pump 2". The drawings are representative, built from
public product information, not manufacturer drawings; each sheet says so, and
``details.yaml`` gives the source or assumption behind every part.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .site_drawings import (EQUIP, FAINT, FEED_A, FEED_B, INK, LEAK, MUTED, PAPER, RACK, RETURN, SECONDARY,
                            SUPPLY, Svg, breaker, frame)

DETAILS_PATH = Path(__file__).resolve().parents[2] / "site" / "details.yaml"
W, H = 1400, 940
NOTE_X = 1010          # the notes column on every detail sheet
PS_FILL = "#fff3d6"
SW_FILL = "#e6e1f5"


@lru_cache(maxsize=1)
def load_details(path: str | Path = DETAILS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def parts(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every part of a product, with ranges expanded: "ct{n}" for n in 1..18 becomes ct1..ct18."""
    out: dict[str, dict[str, Any]] = {}
    for p in spec["parts"]:
        ns = range(p["n"][0], p["n"][1] + 1) if "n" in p else [None]
        ms = range(p["m"][0], p["m"][1] + 1) if "m" in p else [None]
        for n in ns:
            for m in ms:
                f = lambda t: t.replace("{n}", str(n)).replace("{m}", str(m))
                out[f(p["id"])] = {"tag": f(p["tag"]), "label": f(p["label"]), "basis": p["basis"],
                                   "position": p.get("position", "")}
    return out


def _wrap(text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def notes(svg: Svg, spec: dict[str, Any], y: float = 60, x: float = NOTE_X, wrap: int = 52) -> None:
    """The right-hand column: what the sheet is, its alarm points, and what is assumed."""
    svg.text(x, y, "Alarm points on this sheet", size=12, weight="bold")
    y += 20
    for where, what, frm in spec["alarm_points"]:
        svg.text(x, y, where, size=10, weight="bold")
        for ln in _wrap(f"{what} ({frm})", wrap):
            y += 14
            svg.text(x + 10, y, ln, size=10, fill=MUTED)
        y += 19
    y += 8
    svg.text(x, y, "Notes", size=12, weight="bold")
    for para in ("Representative drawing from public product information; not a manufacturer drawing. "
                 "Typical of every instance on the site: the popup names the instance.",
                 spec["order_note"],
                 "Sources and assumptions for every part: site/details.yaml."):
        y += 6
        for ln in _wrap(para, wrap):
            y += 14
            svg.text(x, y, ln, size=10, fill=MUTED)
        y += 4


def _tagged(svg: Svg, name: str, x, y, w, h, tag: str, fill=PAPER, size=10, anchor="middle", sw=1.0, weight="normal"):
    """A part: a box with its tag inside, recorded under ``name``."""
    svg.rect(x, y, w, h, fill=fill, stroke=INK, sw=sw)
    tx = x + w / 2 if anchor == "middle" else x + 6
    svg.text(tx, y + h / 2 + size * 0.36, tag, size=size, anchor=anchor, weight=weight)
    svg.mark(name, x, y, w, h)


def big_breaker(svg: Svg, cx: float, cy: float, s: float = 1.0) -> None:
    """A molded-case breaker as seen from the front: body, toggle slot, handle."""
    svg.rect(cx - 16 * s, cy - 22 * s, 32 * s, 44 * s, fill="#eef1f4", stroke=INK, sw=1.2, rx=2)
    svg.rect(cx - 5 * s, cy - 12 * s, 10 * s, 24 * s, fill=PAPER, stroke=INK, sw=0.8)
    svg.rect(cx - 4 * s, cy - 11 * s, 8 * s, 10 * s, fill=INK, stroke=INK, sw=0.5)


# --------------------------------------------------------------------------- #
# D-101 GB200 NVL72 rack
# --------------------------------------------------------------------------- #
U = 17


def rack_elevation(spec: dict[str, Any], marks: dict | None = None) -> str:
    svg = Svg(W, H)
    rw, top = 330, 96
    fx, rx = 110, 560                        # front and rear elevation, left edge of the rack's inner width
    # rows top to bottom (kind, label or index)
    rows = ([("mgmt", None)] * 2 + [("gap", None)] + [("ps", i) for i in range(1, 5)]
            + [("ct", i) for i in range(1, 11)] + [("nvsw", i) for i in range(1, 10)]
            + [("ct", i) for i in range(11, 19)] + [("ps", i) for i in range(5, 9)] + [("gap", None), ("drip", None)])
    n = len(rows)
    for x0, side in ((fx, "FRONT"), (rx, "REAR")):
        svg.text(x0 + rw / 2, top - 28, f"{side} ELEVATION", size=13, anchor="middle", weight="bold")
        svg.rect(x0 - 14, top - 10, rw + 28, n * U + 20, fill="#f4f6f8", stroke=INK, sw=1.6)     # rack frame
        svg.rect(x0 - 14, top + n * U + 10, rw + 28, 10, fill=INK, stroke=INK)                   # plinth
    svg.mark("device", fx - 14, top - 10, rw + 28, n * U + 30)
    svg.mark("device", rx - 14, top - 10, rw + 28, n * U + 30)
    # rack-unit scale on the front
    for i in range(n):
        if (n - i) % 5 == 0:
            svg.text(fx - 22, top + i * U + U * 0.7, str(n - i), size=8, anchor="end", fill=MUTED)
    svg.text(fx - 22, top - 14, "RU", size=8, anchor="end", fill=MUTED)

    # ---- front
    y_of: dict[tuple[str, Any], float] = {}
    i = 0
    while i < n:
        kind, k = rows[i]
        y = top + i * U
        if kind == "mgmt":
            _tagged(svg, "mgmt", fx, y, rw, 2 * U, "MGMT", fill="#e9edf1", size=9)
            svg.line(fx, y + U, fx + rw, y + U, stroke=FAINT)
            i += 2
            continue
        if kind == "ps":
            svg.rect(fx, y, rw, U, fill=PS_FILL, stroke=INK)
            svg.text(fx + 6, y + U * 0.68, f"PS {k}", size=9, weight="bold")
            svg.mark(f"ps{k}", fx, y, rw, U)
            pw = (rw - 50) / 6
            for m in range(1, 7):
                px = fx + 46 + (m - 1) * pw
                _tagged(svg, f"ps{k}-psu{m}", px + 1, y + 2, pw - 2, U - 4, str(m), fill=PAPER, size=8, sw=0.6)
        elif kind == "ct":
            svg.rect(fx, y, rw, U, fill=RACK, stroke=INK)
            svg.text(fx + 6, y + U * 0.68, f"CT {k}", size=9, weight="bold")
            for v in range(6):
                svg.rect(fx + 70 + v * 40, y + 4, 28, U - 8, fill="#c3cbd4", stroke="none")
            svg.mark(f"ct{k}", fx, y, rw, U)
        elif kind == "nvsw":
            svg.rect(fx, y, rw, U, fill=SW_FILL, stroke=INK)
            svg.text(fx + 6, y + U * 0.68, f"NVSW {k}", size=9, weight="bold")
            for v in range(16):
                svg.rect(fx + 80 + v * 15, y + 5, 9, U - 10, fill=PAPER, stroke=MUTED, sw=0.5)
            svg.mark(f"nvsw{k}", fx, y, rw, U)
        elif kind == "drip":
            svg.rect(fx, y, rw, U, fill="#e4f4f1", stroke=INK)
            svg.line(fx + 8, y + U - 4, fx + rw - 8, y + U - 4, stroke=LEAK, sw=2, dash="6 3")
            svg.text(fx + rw / 2, y + U * 0.62, "Drip pan and leak rope", size=9, anchor="middle")
            svg.mark("drip", fx, y, rw, U)
        y_of[(kind, k)] = y
        i += 1

    # group brackets on the front's right
    def bracket(y0, y1, text, color=INK):
        bx = fx + rw + 20
        svg.poly([(bx, y0 + 2), (bx + 6, y0 + 2), (bx + 6, y1 - 2), (bx, y1 - 2)], stroke=color, sw=1.2)
        svg.text(bx + 12, (y0 + y1) / 2 + 4, text, size=10, fill=color)
    bracket(y_of[("ps", 1)], y_of[("ps", 4)] + U, "A feed")
    bracket(y_of[("ct", 1)], y_of[("ct", 10)] + U, "10 trays")
    bracket(y_of[("nvsw", 1)], y_of[("nvsw", 9)] + U, "9 switch trays")
    bracket(y_of[("ct", 11)], y_of[("ct", 18)] + U, "8 trays")
    bracket(y_of[("ps", 5)], y_of[("ps", 8)] + U, "B feed")

    # ---- rear
    for (kind, k), y in y_of.items():
        if kind in ("ct", "nvsw", "ps"):
            svg.rect(rx, y, rw, U, fill={"ct": RACK, "nvsw": SW_FILL, "ps": PS_FILL}[kind], stroke=FAINT, opacity=0.55)
    svg.rect(rx, top, rw, 2 * U, fill="#e9edf1", stroke=FAINT)
    yd = y_of[("drip", None)]
    svg.rect(rx, yd, rw, U, fill="#e4f4f1", stroke=FAINT)
    y_ct0, y_ct1 = y_of[("ct", 1)], y_of[("ct", 18)] + U
    # manifold: supply and return risers with a quick-disconnect at every liquid-cooled tray
    mx = rx + 6
    svg.rect(mx, y_ct0 - 26, 62, y_ct1 - y_ct0 + 30, fill=PAPER, stroke=INK)
    svg.text(mx + 31, y_ct0 - 12, "Manifold", size=9, anchor="middle", weight="bold")
    svg.mark("manifold", mx, y_ct0 - 26, 62, y_ct1 - y_ct0 + 30)
    svg.line(mx + 18, y_ct0 - 2, mx + 18, y_ct1, stroke=SUPPLY, sw=4)
    svg.line(mx + 44, y_ct0 - 2, mx + 44, y_ct1, stroke=RETURN, sw=4)
    for (kind, k), y in y_of.items():
        if kind in ("ct", "nvsw"):
            for cx, col in ((mx + 18, SUPPLY), (mx + 44, RETURN)):
                svg.circle(cx, y + U / 2, 2.6, fill=col, stroke=col)
    # cable cartridges between the trays and the switch trays
    cx0 = rx + 86
    svg.rect(cx0, y_ct0, 130, y_ct1 - y_ct0, fill="#f1edf9", stroke=INK)
    for v in range(1, 4):
        svg.line(cx0 + v * 32, y_ct0 + 6, cx0 + v * 32, y_ct1 - 6, stroke="#b4a6dc", sw=1.2)
    ym = (y_ct0 + y_ct1) / 2
    svg.rect(cx0 + 10, ym - 22, 110, 36, fill=PAPER, stroke="none")
    svg.text(cx0 + 65, ym - 8, "NVLink cable", size=10, anchor="middle")
    svg.text(cx0 + 65, ym + 7, "Cartridges", size=10, anchor="middle", weight="bold")
    svg.mark("cartridge", cx0, y_ct0, 130, y_ct1 - y_ct0)
    # busbar
    bx = rx + 234
    y_b0, y_b1 = y_of[("ps", 1)], y_of[("ps", 8)] + U
    svg.rect(bx, y_b0, 30, y_b1 - y_b0, fill="#d9b44a", stroke=INK)
    svg.rect(bx + 1, (y_b0 + y_b1) / 2 - 10, 28, 14, fill=PAPER, stroke="none")
    svg.text(bx + 15, (y_b0 + y_b1) / 2, "Busbar", size=8, anchor="middle", weight="bold")
    svg.mark("busbar", bx, y_b0, 30, y_b1 - y_b0)
    # AC inputs at the power shelves, A above and B below
    for grp, (a, b), col, feed in ((1, (1, 4), FEED_A, "A"), (2, (5, 8), FEED_B, "B")):
        y0, y1 = y_of[("ps", a)], y_of[("ps", b)] + U
        ax = rx + 270
        svg.rect(ax, y0, 56, y1 - y0, fill=PAPER, stroke=col, sw=1.6)
        svg.text(ax + 28, (y0 + y1) / 2 - 2, "AC inputs", size=9, anchor="middle")
        svg.text(ax + 28, (y0 + y1) / 2 + 10, f"{feed} feed", size=9, anchor="middle", fill=col, weight="bold")
        svg.mark("ac-in", ax, y0, 56, y1 - y0)
        svg.line(ax + 56, (y0 + y1) / 2, rx + rw + 40, (y0 + y1) / 2, stroke=col, sw=2.2)
        svg.text(rx + rw + 44, (y0 + y1) / 2 + 4, f"to the rack's {feed} tap-off", size=9, fill=col)
    svg.text(rx + rw + 44, (y0 + y1) / 2 + 18, "(sheet D-303)", size=9, fill=MUTED)
    svg.text(rx + rw / 2, top + n * U + 42, "Manifold hoses run to the CDU header (sheet D-201)", size=9, anchor="middle", fill=MUTED)
    svg.rect(rx, yd, rw, U, fill="none", stroke=INK)

    notes(svg, spec)
    frame(svg, spec["sheet"], spec["title"] + " (representative)", "Not to scale")
    return svg.done(marks)


# --------------------------------------------------------------------------- #
# D-201 CHx2000 CDU
# --------------------------------------------------------------------------- #
def pump(svg: Svg, cx: float, cy: float, r: float = 26) -> None:
    svg.circle(cx, cy, r, fill=PAPER)
    svg.poly([(cx - r * 0.5, cy - r * 0.62), (cx + r * 0.8, cy), (cx - r * 0.5, cy + r * 0.62)], sw=1.2)


def cdu(spec: dict[str, Any], marks: dict | None = None) -> str:
    svg = Svg(W, H)
    top, cw, ch = 110, 300, 640
    fx, rx = 120, 560
    for x0, side in ((fx, "FRONT"), (rx, "REAR")):
        svg.text(x0 + cw / 2, top - 28, side, size=13, anchor="middle", weight="bold")
        svg.rect(x0, top, cw, ch, fill="#f4f6f8", stroke=INK, sw=1.6)
        svg.rect(x0, top + ch, cw, 10, fill=INK, stroke=INK)
        svg.mark("device", x0, top, cw, ch + 10)
    # front: controller up top, pumps on sliding trays at the bottom
    svg.rect(fx + 70, top + 40, 160, 90, fill="#e9edf1", stroke=INK)
    svg.rect(fx + 90, top + 50, 120, 50, fill="#cfe0ee", stroke=MUTED, sw=0.8)
    svg.text(fx + 150, top + 118, "Controller", size=10, anchor="middle", weight="bold")
    svg.mark("controller", fx + 70, top + 40, 160, 90)
    svg.rect(fx + 20, top + 170, cw - 40, 180, fill=PAPER, stroke=FAINT, dash="4 3")
    svg.text(fx + cw / 2, top + 192, "Service panel", size=10, anchor="middle", fill=MUTED)
    for k in (1, 2):
        px = fx + 20 + (k - 1) * 135
        y = top + 400
        svg.rect(px, y, 125, 200, fill=EQUIP, stroke=INK)
        pump(svg, px + 62, y + 90)
        svg.text(px + 62, y + 160, f"Pump {k}", size=11, anchor="middle", weight="bold")
        svg.text(px + 62, y + 178, "sliding tray", size=9, anchor="middle", fill=MUTED)
        svg.mark(f"pump{k}", px, y, 125, 200)
    # rear: connections on top, valve, heat exchanger, filters
    for j, (name, tag, col_s, col_r) in enumerate((("facility", "Facility water", SUPPLY, RETURN),
                                                    ("secondary", "Secondary loop", SECONDARY, "#7cbf96"))):
        x = rx + 20 + j * 140
        svg.rect(x, top + 20, 120, 70, fill=PAPER, stroke=INK)
        svg.text(x + 60, top + 80, tag, size=10, anchor="middle", weight="bold")
        for k, col, word in ((0, col_s, "S"), (1, col_r, "R")):
            cx = x + 34 + k * 52
            svg.line(cx, top + 34, cx, top - 6, stroke=col, sw=7)
            svg.circle(cx, top + 42, 9, fill=col, stroke=INK)
            svg.text(cx, top + 66, word, size=9, anchor="middle", fill=col, weight="bold")
        svg.mark(name, x, top + 20, 120, 70)
    svg.text(rx + 80, top - 12, "4 in tri-clamp", size=9, anchor="middle", fill=MUTED)
    vx, vy = rx + 30, top + 130
    svg.rect(vx, vy, 100, 70, fill=PAPER, stroke=INK)
    svg.poly([(vx + 30, vy + 14), (vx + 70, vy + 34), (vx + 70, vy + 14), (vx + 30, vy + 34), (vx + 30, vy + 14)], sw=1.4)
    svg.text(vx + 50, vy + 56, "Control valve", size=10, anchor="middle", weight="bold")
    svg.mark("valve", vx, vy, 100, 70)
    _tagged(svg, "hx", rx + 20, top + 240, cw - 40, 150, "Heat exchanger", fill=EQUIP, weight="bold")
    for v in range(1, 12):
        svg.line(rx + 20 + v * 21.7, top + 250, rx + 20 + v * 21.7, top + 300, stroke="#9fb9a9", sw=1)
    fy = top + 430
    svg.rect(rx + 20, fy, cw - 40, 170, fill=PAPER, stroke=INK)
    for k in range(2):
        svg.rect(rx + 70 + k * 100, fy + 20, 60, 110, fill="#eef1f4", stroke=INK, rx=6)
    svg.text(rx + cw / 2, fy + 155, "Filters", size=10, anchor="middle", weight="bold")
    svg.mark("filters", rx + 20, fy, cw - 40, 170)
    notes(svg, spec)
    frame(svg, spec["sheet"], spec["title"] + " (representative)", "Not to scale")
    return svg.done(marks)


# --------------------------------------------------------------------------- #
# D-301 Galaxy VX UPS line-up
# --------------------------------------------------------------------------- #
def ups_lineup(spec: dict[str, Any], marks: dict | None = None) -> str:
    svg = Svg(W, H)
    top, ch = 130, 380
    x = 50
    svg.text(x, top - 44, "FRONT ELEVATION, LEFT TO RIGHT", size=13, weight="bold")
    x0 = x
    # battery cabinets
    bw = 4 * 44
    for k in range(4):
        svg.rect(x + k * 44, top, 44, ch, fill="#eef4ea", stroke=INK)
        for r in range(8):
            svg.rect(x + k * 44 + 7, top + 30 + r * 38, 30, 28, fill=PAPER, stroke=FAINT)
    svg.rect(x + 4, top + ch - 34, bw - 8, 26, fill=PAPER, stroke=INK)
    svg.text(x + bw / 2, top + ch - 17, "Battery cabinets", size=10, anchor="middle", weight="bold")
    svg.mark("battery", x, top, bw, ch)
    x += bw + 12
    # I/O cabinet
    io_w = 120
    svg.rect(x, top, io_w, ch, fill="#e9edf1", stroke=INK, sw=1.4)
    svg.text(x + io_w / 2, top + ch - 14, "I/O cabinet", size=10, anchor="middle", weight="bold")
    svg.mark("io", x, top, io_w, ch)
    _tagged(svg, "nmc", x + 10, top + 24, io_w - 20, 70, "Display and NMC", fill=PAPER, size=9)
    _tagged(svg, "static", x + 10, top + 130, io_w - 20, 90, "Static switch", fill=PAPER, size=9)
    svg.rect(x + 30, top + 240, io_w - 60, 50, fill=PAPER, stroke=FAINT)
    svg.text(x + io_w / 2, top + 270, "BF2", size=9, anchor="middle", fill=MUTED)
    x += io_w
    # power cabinets, called power modules in the telemetry
    pw = 70
    for k in range(1, 8):
        svg.rect(x, top, pw, ch, fill=EQUIP, stroke=INK)
        for r in range(5):
            svg.line(x + 10, top + 60 + r * 12, x + pw - 10, top + 60 + r * 12, stroke="#9fb9a9")
        svg.rect(x + 9, top + 150, pw - 18, 120, fill=PAPER, stroke=FAINT)
        svg.text(x + pw / 2, top + ch - 30, f"PM {k}", size=11, anchor="middle", weight="bold")
        svg.text(x + pw / 2, top + ch - 14, "250 kW", size=9, anchor="middle", fill=MUTED)
        svg.mark(f"pm{k}", x, top, pw, ch)
        x += pw
    svg.rect(x0, top + ch, x - x0, 8, fill=INK, stroke=INK)
    svg.mark("device", x0, top, x - x0, ch + 8)
    ups_right = x
    # output switchboard
    x += 50
    sb_w = 200
    svg.text(x, top - 44, "OUTPUT SWITCHBOARD", size=13, weight="bold")
    svg.rect(x, top, sb_w, ch, fill="#f4f6f8", stroke=INK, sw=1.4)
    svg.rect(x, top + ch, sb_w, 8, fill=INK, stroke=INK)
    svg.rect(x + 14, top + 20, sb_w - 28, 100, fill=PAPER, stroke=INK)
    big_breaker(svg, x + sb_w / 2, top + 56)
    svg.text(x + sb_w / 2, top + 106, "Maintenance bypass", size=10, anchor="middle", weight="bold")
    svg.mark("mbb", x + 14, top + 20, sb_w - 28, 100)
    oy = top + 140
    svg.rect(x + 14, oy, sb_w - 28, 200, fill=PAPER, stroke=INK)
    for k in range(4):
        bx = x + 40 + k * 40
        big_breaker(svg, bx, oy + 40, s=0.7)
        svg.line(bx, oy + 60, bx, oy + 125, stroke=FEED_A if k % 2 == 0 else FEED_B, sw=2)
    svg.text(x + sb_w / 2, oy + 160, "Output feeders", size=10, anchor="middle", weight="bold")
    svg.text(x + sb_w / 2, oy + 178, "to A or B busways", size=9, anchor="middle", fill=MUTED)
    svg.mark("out-brk", x + 14, oy, sb_w - 28, 200)
    svg.line(ups_right, top + ch + 30, x, top + ch + 30, stroke=INK, sw=2)
    svg.text((ups_right + x) / 2, top + ch + 46, "UPS output", size=9, anchor="middle", fill=MUTED)
    # simplified one-line under the elevation: bypasses above the main path, battery below
    y = top + ch + 200
    svg.text(50, y - 120, "SIMPLIFIED ONE-LINE", size=13, weight="bold")
    xs = {"in": 70, "pm": 330, "out": 620, "fd": 840}
    svg.text(xs["in"], y + 18, "480 V from USS", size=10)
    svg.line(xs["in"], y, xs["fd"], y, sw=2)
    svg.rect(xs["pm"] - 75, y - 22, 150, 44, fill=EQUIP, stroke=INK)
    svg.text(xs["pm"], y + 4, "PM 1 to PM 7 (6+1)", size=10, anchor="middle")
    svg.poly([(xs["in"] + 120, y), (xs["in"] + 120, y - 45), (xs["out"] - 60, y - 45), (xs["out"] - 60, y)], sw=1.4)
    svg.text(xs["pm"], y - 51, "Static switch (in the I/O cabinet)", size=10, anchor="middle", fill=MUTED)
    svg.poly([(xs["in"] + 60, y), (xs["in"] + 60, y - 90), (xs["out"] + 40, y - 90), (xs["out"] + 40, y)], sw=1.4, dash="6 3")
    svg.text(xs["pm"], y - 96, "Maintenance bypass (in the output switchboard)", size=10, anchor="middle", fill=MUTED)
    for k in range(3):
        fx = xs["fd"] - 120 + k * 50
        svg.line(fx, y, fx, y + 40, sw=1.4)
        breaker(svg, fx, y + 22)
    svg.text(xs["fd"] - 70, y + 58, "Output feeders", size=9, anchor="middle", fill=MUTED)
    svg.line(xs["pm"], y + 22, xs["pm"], y + 70, stroke=INK, sw=1.2)
    svg.rect(xs["pm"] - 40, y + 70, 80, 30, fill="#eef4ea", stroke=INK)
    svg.text(xs["pm"] + 50, y + 90, "Battery (DC link)", size=10, fill=MUTED)
    notes(svg, spec, y=top - 44, x=1170, wrap=36)
    frame(svg, spec["sheet"], spec["title"] + " (representative)", "Not to scale")
    return svg.done(marks)


# --------------------------------------------------------------------------- #
# D-303 Track busway and tap-off
# --------------------------------------------------------------------------- #
def busway(spec: dict[str, Any], marks: dict | None = None) -> str:
    svg = Svg(W, H)
    svg.text(60, 70, "ELEVATION ALONG THE ROW", size=13, weight="bold")
    ty = 200
    # incoming feeder and end feed
    svg.line(110, 92, 110, ty - 10, stroke=FEED_A, sw=3)
    svg.text(122, 104, "From the UPS output feeder breaker (sheet D-301)", size=10, fill=FEED_A)
    svg.rect(50, ty - 30, 150, 180, fill="#e9edf1", stroke=INK, sw=1.4)
    svg.text(125, ty - 12, "End feed", size=11, anchor="middle", weight="bold")
    svg.mark("end-feed", 50, ty - 30, 150, 180)
    svg.rect(66, ty + 20, 118, 100, fill=PAPER, stroke=INK)
    svg.rect(84, ty + 30, 82, 26, fill="#cfe0ee", stroke=MUTED, sw=0.6)
    svg.text(125, ty + 76, "Feed meter", size=10, anchor="middle", weight="bold")
    svg.text(125, ty + 92, "V L-L, V L-N, A", size=8, anchor="middle", fill=MUTED)
    svg.mark("feed-cpm", 66, ty + 20, 118, 100)
    # track
    svg.rect(200, ty, 700, 60, fill="#f4f6f8", stroke=INK, sw=1.4)
    for k in range(4):
        svg.line(210, ty + 10 + k * 9, 890, ty + 10 + k * 9, stroke="#b08d2a", sw=1.6)
    svg.text(300, ty + 53, "Busway track", size=10, anchor="middle", weight="bold")
    svg.mark("track", 200, ty, 700, 60)
    svg.text(550, ty - 8, "Open channel: a tap-off plugs in anywhere along it", size=10, anchor="middle", fill=MUTED)
    svg.rect(900, ty, 14, 60, fill=INK, stroke=INK)
    svg.text(907, ty + 76, "End closure", size=9, anchor="middle", fill=MUTED)
    # tap-off (plug-in unit)
    px, py = 440, ty + 60
    svg.rect(px, py, 260, 220, fill=PAPER, stroke=INK, sw=1.6)
    svg.text(px + 130, py + 20, "Tap-off (plug-in unit)", size=11, anchor="middle", weight="bold")
    svg.mark("device", px, py, 260, 220)
    svg.rect(px + 120, py - 12, 20, 12, fill=INK, stroke=INK)
    svg.rect(px + 20, py + 40, 100, 120, fill="#fbeceb", stroke=INK)
    big_breaker(svg, px + 70, py + 82)
    svg.text(px + 70, py + 140, "Breaker", size=10, anchor="middle", weight="bold")
    svg.mark("to-brk", px + 20, py + 40, 100, 120)
    svg.rect(px + 140, py + 40, 100, 120, fill=PAPER, stroke=INK)
    svg.rect(px + 154, py + 54, 72, 30, fill="#cfe0ee", stroke=MUTED, sw=0.6)
    svg.text(px + 190, py + 110, "Meter", size=10, anchor="middle", weight="bold")
    svg.text(px + 190, py + 126, "A, breaker", size=8, anchor="middle", fill=MUTED)
    svg.text(px + 190, py + 137, "position", size=8, anchor="middle", fill=MUTED)
    svg.mark("to-cpm", px + 140, py + 40, 100, 120)
    svg.text(px + 130, py + 196, "Label: TO-<rack>-<A|B>", size=9, anchor="middle", fill=MUTED)
    # cord to the rack
    cy0 = py + 220
    svg.poly([(px + 130, cy0), (px + 130, cy0 + 70), (px + 300, cy0 + 70), (px + 300, cy0 + 150)], stroke=FEED_A, sw=4)
    svg.text(px + 214, cy0 + 62, "Cord to rack", size=10, anchor="middle", weight="bold")
    svg.mark("cord", px + 120, cy0, 190, 150)
    # rack top
    rx, ry = px + 200, cy0 + 150
    svg.rect(rx, ry, 300, 120, fill=RACK, stroke=INK, sw=1.4)
    svg.text(rx + 150, ry + 34, "Rack (sheet D-101)", size=11, anchor="middle", weight="bold")
    svg.text(rx + 150, ry + 52, "AC inputs to power shelves", size=9, anchor="middle", fill=MUTED)
    svg.rect(rx + 80, ry - 6, 40, 12, fill=PAPER, stroke=FEED_A, sw=1.4)
    svg.line(rx + 100, ry + 6, rx + 100, ry + 20, stroke=FEED_A, sw=2)
    # explanation of A and B
    y = 620
    svg.text(60, y, "Every rack has two tap-offs, one on its A-side busway and one on its B-side busway,", size=11)
    svg.text(60, y + 18, "each feeding half of the rack's power shelves. Both busways are built as shown.", size=11)
    svg.line(60, y + 44, 120, y + 44, stroke=FEED_A, sw=3)
    svg.text(130, y + 48, "A-side busway: TO-<rack>-A", size=10)
    svg.line(60, y + 64, 120, y + 64, stroke=FEED_B, sw=3)
    svg.text(130, y + 68, "B-side busway: TO-<rack>-B", size=10)
    notes(svg, spec)
    frame(svg, spec["sheet"], spec["title"] + " (representative)", "Not to scale")
    return svg.done(marks)


DRAWERS = {"gb200_nvl72": rack_elevation, "coolit_chx2000": cdu, "galaxy_vx_1500": ups_lineup,
           "starline_1200t5": busway}


def detail_sheets(marks: dict | None = None) -> list[tuple[str, str, str, str]]:
    """(sheet number, file name, title, svg) for every detail sheet, in sheet order."""
    out = []
    for key, spec in sorted(load_details()["products"].items(), key=lambda kv: kv[1]["sheet"]):
        num = spec["sheet"]
        slug = re.sub(r"[^a-z0-9]+", "_", spec["title"].split(",")[0].lower()).strip("_")
        m = marks.setdefault(num, {}) if marks is not None else None
        out.append((num, f"{num}_{slug}.svg", spec["title"], DRAWERS[key](spec, marks=m)))
    return out


def sheet_products() -> dict[str, str]:
    """product key -> detail sheet number."""
    return {k: v["sheet"] for k, v in load_details()["products"].items()}
