"""Site model: structure, capacity, topology, drawings, and agreement with the SLA."""

import copy
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scorecard import site_model as S
from scorecard.site_drawings import sheets
from scorecard.sla_model import load_sla

ROOT = Path(__file__).resolve().parents[1]
SVG_NS = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module")
def site():
    return S.load_site()


@pytest.fixture(scope="module")
def drawn(site):
    return {num: svg for num, _, _, svg in sheets(site)}


def svg_text(svg: str) -> set[str]:
    return {t.text for t in ET.fromstring(svg).iter(f"{SVG_NS}text") if t.text}


# ------------------------------------------------------------------ capacity
def test_every_capacity_check_passes(site):
    failed = [c for c in S.capacity_checks(site) if not c.passed]
    assert not failed, failed


def test_distributed_redundant_ups_spreads_a_lost_module_over_the_other_three(site):
    hall = S.hall_by_id(site, "HALL-A")
    normal = S._ups_loads(site, hall)
    assert len(set(round(v) for v in normal.values())) == 1, "modules share load evenly"
    for lost in normal:
        after = S._ups_loads(site, hall, lost=lost)
        gained = {u: after[u] - normal[u] for u in after}
        assert all(v > 0 for v in gained.values()), f"UPS-A{lost} load must spread to all three others"
        assert sum(gained.values()) == pytest.approx(normal[lost])


def test_no_rack_has_both_feeds_on_one_ups(site):
    for r in S.racks(site):
        assert r["feeds"]["A"] != r["feeds"]["B"], r


def test_under_built_site_is_rejected(site):
    short = copy.deepcopy(site)
    short["plants"]["heat_rejection"]["chiller_count"] = 9
    with pytest.raises(S.SiteValidationError, match="Chillers"):
        S.validate_site(short)
    hot = copy.deepcopy(site)
    hot["products"]["gb200_nvl72"]["design_kw"] = 160
    with pytest.raises(S.SiteValidationError, match="UPS, one module lost"):
        S.validate_site(hot)


def test_inconsistent_power_groups_are_rejected(site):
    bad = copy.deepcopy(site)
    bad["halls"][0]["power"]["groups"][0]["feeds"] = [1, 1]
    with pytest.raises(S.SiteValidationError, match="same UPS"):
        S.validate_site(bad)
    bad = copy.deepcopy(site)
    bad["halls"][0]["power"]["groups"][0]["racks"] = 7
    with pytest.raises(S.SiteValidationError, match="cover 33 racks"):
        S.validate_site(bad)


def test_unknown_product_is_rejected(site):
    bad = copy.deepcopy(site)
    bad["halls"][1]["cooling"]["cdu_product"] = "not_a_cdu"
    with pytest.raises(S.SiteValidationError, match="unknown product 'not_a_cdu'"):
        S.validate_site(bad)


# ------------------------------------------------------------------ topology
def test_power_path_reaches_both_sources_through_different_ups(site):
    paths = S.power_path(site, "A07")
    assert paths["A"][2] != paths["B"][2]
    for p in paths.values():
        assert p[0] == "A07" and p[-3:] == ["TX-1", "TX-2", "GEN paralleling bus"]
        assert p[1].startswith("BW-A-R1-")


def test_cooling_path_runs_through_the_hall_header(site):
    assert S.cooling_path(site, "B12")[1:3] == ["Hall B secondary header", "CDU-B1..B4 (N+1)"]


def test_busway_segment_ids_are_unique_and_cover_every_rack(site):
    for hall in site["halls"]:
        segs = S.busway_segments(site, hall["id"])
        if hall["power"]["architecture"] != "distributed_redundant":
            assert segs == []
            continue
        assert len({s["id"] for s in segs}) == len(segs)
        assert sum(len(s["racks"]) for s in segs) == S.rack_count(hall)


# ------------------------------------------------------------------ agreement with the SLA and data
def test_site_and_sla_describe_the_same_halls(site):
    sla_halls = {h["id"]: h for h in load_sla()["site"]["halls"]}
    for hid, h in sla_halls.items():
        assert S.rack_count(S.hall_by_id(site, hid)) == h["racks"]
        assert S.hall_by_id(site, hid)["state"] == h["state"]


def test_site_and_sla_agree_on_cdus(site):
    cooling = load_sla()["site"]["cooling"]
    halls = [S.hall_by_id(site, h["id"]) for h in load_sla()["site"]["halls"]]
    assert sum(h["cooling"]["cdu_count"] for h in halls) == cooling["cdus_total"]
    cdu = S.product(site, halls[0]["cooling"]["cdu_product"])
    assert cooling["cdu_capacity_mw"] == cdu["capacity_kw"] / 1000
    assert cdu["model"].split()[0] in cooling["cdu_type"] and cdu["manufacturer"].split()[0] in cooling["cdu_type"]


def test_rack_to_cdu_mapping_matches_the_synthetic_topology(site):
    topo = json.loads((ROOT / "data" / "sample" / "site" / "topology.json").read_text(encoding="utf-8"))
    model = {r["rack"]: r["cdu"] for r in S.racks(site)}
    for r in topo["racks"]:
        assert model[r["rack"]] == r["cdu"], r["rack"]


def test_monitoring_map_covers_every_critical_device_class(site):
    mapped = {p for d in site["monitoring"]["device_classes"] for p in d["products"]}
    for cat in ("ups", "generator", "cdu", "chiller", "leak_detection", "smoke_detection", "busway"):
        products = [k for k, v in site["products"].items() if v["category"] == cat]
        assert products and set(products) & mapped, f"no monitoring path for {cat}"
    assert any(s["operator"] == "customer" for s in site["monitoring"]["systems"]), "Telemetry of Record exists"


# ------------------------------------------------------------------ drawings
def test_every_sheet_is_valid_svg(drawn):
    for num, svg in drawn.items():
        root = ET.fromstring(svg)
        assert root.tag == f"{SVG_NS}svg", num
        assert num in svg_text(svg), f"{num} title strip shows its sheet number"


def test_hall_plans_show_every_rack_and_cdu(site, drawn):
    for i, hall in enumerate(site["halls"], 1):
        texts = svg_text(drawn[f"A-2{i:02d}"])
        for r in S.racks(site, hall["id"]):
            assert r["rack"] in texts
        L = hall["letter"]
        for n in range(1, hall["cooling"]["cdu_count"] + 1):
            assert f"{L}{n}" in texts


def test_one_line_and_cooling_diagram_show_named_equipment(site, drawn):
    one_line, cooling = svg_text(drawn["E-001"]), svg_text(drawn["M-001"])
    for e in S.equipment(site):
        if e["id"].startswith(("UPS-", "MUPS-", "MVSST-")):
            assert e["id"] in one_line, e["id"]
        if e["id"].startswith(("CDU-", "TW-", "CRAH-", "CH-")):
            assert e["id"] in cooling, e["id"]


def test_generated_site_docs_are_current():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "render_site.py"), "--check"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
