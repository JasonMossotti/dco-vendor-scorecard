"""Security site plan (A-002) and building security zones (A-102): zones Z0 to Z6, gates, posts, doors, cameras, and tour
checkpoints drawn from site/site.yaml and config/security.yaml; the Security SLA's whole-property scope and post orders.
The synthetic security data is not touched (its own tests hold its headline)."""

import csv
import json
from pathlib import Path

import pytest

from scorecard import site_model as S
from scorecard.security_drawings import camera_positions, cameras, interior_positions, security_config
from scorecard.site_drawings import building_dims, sheets, south_rooms
from scorecard.sla_model import PARTNER_FILES, load_interface_agreement, load_sla

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def site():
    return S.load_site()


@pytest.fixture(scope="module")
def marks(site):
    m: dict = {}
    sheets(site, marks=m)
    return m


@pytest.fixture(scope="module")
def loc():
    return json.loads((ROOT / "docs" / "site" / "locations.json").read_text(encoding="utf-8"))


def test_zones_are_complete(site):
    zones = site["security"]["zones"]
    assert [z["id"] for z in zones] == [f"Z{i}" for i in range(7)]
    for z in zones:
        for k in ("name", "where", "entry", "method", "controlled_by", "patrolled_by", "response"):
            assert z[k].strip(), (z["id"], k)
    assert site["parties"]["security_partner"]["name"] == load_sla(PARTNER_FILES["security"])["parties"]["supplier"]["name"]


def test_a002_draws_the_property(site, marks):
    sec, m = site["security"], marks["A-002"]
    for name in ["Z0", "Z1", "Z2", "Guard house", "POST-PATROL", "Utility substation", "Data center",
                 "Generator yard", "Chiller yard", "MV yard"]:
        assert name in m, name
    assert {g["id"] for g in sec["gates"]} <= set(m)
    assert {c["id"] for c in sec["exterior_cameras"]} <= set(m)
    assert {c["id"] for c in sec["exterior_tour"]["checkpoints"]} <= set(m)
    gates_cam = {g["camera"] for g in sec["gates"]}
    assert gates_cam <= {c["id"] for c in sec["exterior_cameras"]}, "every gate has an exterior camera on it"


def test_exterior_tour_starts_and_ends_at_the_guard_house(site):
    t, gh = site["security"]["exterior_tour"], site["security"]["guard_house"]
    stops = [w for w in t["route"] if isinstance(w, str)]
    assert sorted(stops) == sorted(c["id"] for c in t["checkpoints"])
    x0, y0 = gh["at"]
    w, h = gh["size"]
    for end in (t["route"][0], t["route"][-1]):
        assert x0 <= end[0] <= x0 + w and y0 <= end[1] <= y0 + h


def test_a102_draws_every_door_post_and_camera_in_the_security_data(site, marks):
    cfg, m = security_config(), marks["A-102"]
    assert {d["id"] for d in cfg["doors"]} <= set(m)
    assert {p["id"] for p in site["security"]["posts"] if p["id"] != "POST-PATROL"} <= set(m)
    assert {c["camera"] for c in cameras(cfg)} <= set(m)
    assert {f"Checkpoint: {c}" for c in cfg["tours"]["checkpoints"]} <= set(m)
    assert {f"Z{i}" for i in range(3, 7)} <= set(m)


def test_cameras_match_the_security_data():
    """The drawing's cameras are the security data's, recorder for recorder; the exterior cameras are new and on NVR-5."""
    data = json.loads((ROOT / "data" / "security" / "cameras.json").read_text(encoding="utf-8"))
    keys = ("camera", "area", "recorder", "covers_door")
    assert [{k: c[k] for k in keys} for c in cameras(security_config())] == [{k: c[k] for k in keys} for c in data]
    assert not any(c["camera"].startswith("CAM-X") for c in data)


def test_door_cameras_sit_by_their_door(site):
    cfg, P = security_config(), interior_positions(site)
    pos = camera_positions(site, cfg)
    door_of = {"Hall A": "HALL-A", "Hall B": "HALL-B", "Spares cage": "SPARES-CAGE", "Receiving dock": "DOCK-INNER"}
    for c in cameras(cfg):
        if c["covers_door"] and c["area"] in door_of:
            dx, dy = P["doors"][door_of[c["area"]]]
            x, y, _ = pos[c["camera"]]
            assert abs(x - dx) + abs(y - dy) < 12, c["camera"]


def test_every_reader_in_the_access_records_has_a_location(loc):
    """The Landlord's readers, the Customer's OPS-MAIN, and the guard post readers all point at a place on the drawings."""
    names = set(loc["entries"]) | set(loc["aliases"])
    with (ROOT / "data" / "sample" / "access" / "landlord_badge_events.csv").open(encoding="utf-8") as f:
        readers = {r["reader"] for r in csv.DictReader(f)}
    with (ROOT / "data" / "sample" / "access" / "badge_events.csv").open(encoding="utf-8") as f:
        readers |= {r["door"] for r in csv.DictReader(f)}
    assert readers - {"HALL-A"} <= names, readers - names
    sla = load_sla(PARTNER_FILES["security"])
    assert {p["id"] for p in sla["posts"]["list"]} <= set(loc["entries"])


def test_posts_and_post_orders_match_the_sla(site):
    sla = load_sla(PARTNER_FILES["security"])
    ids = [p["id"] for p in sla["posts"]["list"]]
    assert sorted(p["id"] for p in site["security"]["posts"]) == sorted(ids)
    assert sorted(o["post"] for o in sla["posts"]["orders"]) == sorted(ids)
    assert all(len(o["orders"]) >= 2 for o in sla["posts"]["orders"])
    text = json.dumps(sla["posts"]["orders"])
    assert "never enters a data hall" in sla["posts"]["armed_posts"]["rule"] and "a shotgun never enters a data hall" in text


def test_the_security_partner_covers_the_whole_property():
    sla = load_sla(PARTNER_FILES["security"])
    post = next(s for s in sla["scope"]["in_scope"] if s["id"] == "SEC-POST")
    assert "whole property" in post["description"] and "utility substation" in post["description"]
    crit = {c for p in sla["priorities"] for c in p["criteria"]}
    assert {"An intruder inside the property fence.", "A property gate or the fence found open or breached.",
            "An exterior camera or a perimeter light out."} <= crit
    ia = load_interface_agreement()
    dm = next(d for d in ia["demarcations"] if d["id"] == "DM-SEC")
    assert dm["boundary"].startswith("The property line")
    row = next(r for r in ia["raci"] if r["component"] == "Property perimeter, gates, and patrols")
    assert row["Security Partner"] == "R" and row["Customer"] == "A" and row["Landlord"] == "C"


def test_media_room_is_on_the_building_plan(site, marks):
    assert "Media room" in [r[0] for r in south_rooms(building_dims(site)[0])]
    assert "Media room" in marks["A-101"] and "Media room" in marks["A-102"]


def test_security_devices_are_in_the_directory():
    d = json.loads((ROOT / "docs" / "site" / "devices.json").read_text(encoding="utf-8"))["devices"]
    assert d["CAM-B-04"]["conn"][0][1] == "NVR-2" and d["GATE-MAIN"]["conn"][0][1] == "CAM-X-01"
    assert sum(1 for e in d.values() if e["kind"] == "camera") == 72 + 16
    assert {f"NVR-{i}" for i in range(1, 6)} <= set(d)
