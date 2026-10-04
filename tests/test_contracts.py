"""The site's three contracts: the IT Partner SLA, the Landlord SLA, and the Interface Agreement."""

import copy
from pathlib import Path

import pytest

from scorecard import site_model as S
from scorecard.sla_model import (
    PARTNER_FILES,
    compute_credit,
    compute_ehs_credits,
    load_interface_agreement,
    load_sla,
    validate_interface_agreement,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "sla"


@pytest.fixture(scope="module")
def it():
    return load_sla(PARTNER_FILES["it"])


@pytest.fixture(scope="module")
def landlord():
    return load_sla(PARTNER_FILES["landlord"])


@pytest.fixture(scope="module")
def ia():
    return load_interface_agreement()


# ------------------------------------------------------------------ partner SLAs
def test_both_partner_slas_load_and_name_their_counterparty(it, landlord):
    assert it["partner_type"] == "it" and landlord["partner_type"] == "landlord"
    assert it["parties"]["supplier"]["name"] == it["parties"]["it_partner"]["name"]
    assert landlord["parties"]["supplier"]["name"] == landlord["parties"]["landlord"]["name"]


def test_common_terms_are_identical_in_both_contracts(it, landlord):
    for section in ("ehs", "security", "excused_events", "corrective_action", "governance", "measurement"):
        assert it[section] == landlord[section], section


def test_cdus_belong_to_the_landlord(it, landlord):
    assert not any("CDU" in fc["name"] for fc in it["measurement_spec"])
    cdu = next(fc for fc in landlord["measurement_spec"] if fc["id"] == "OT-FC-CDU")
    assert cdu["stability_window_hours"] == 72 and cdu["detection"]["source"] == "DS-CDU"


def test_landlord_service_levels_are_measured_from_customer_readable_sources(landlord):
    owners = {d["id"]: d["owner"] for d in landlord["measurement"]["data_sources"]}
    for c in landlord["critical_service_levels"]:
        if c["category"] == "CAT-OT-AVAIL":
            assert any(owners[ds] == "Customer" for ds in c["data_sources"]), c["id"]


def test_landlord_credit_math_and_ehs_use_the_landlords_own_charges(landlord):
    r = compute_credit(landlord, "OT-CSL-03", 1)
    c = landlord["commercial"]
    assert r.credit == pytest.approx(c["monthly_charges"] * c["at_risk_pct"] / 100 * 30 / 100)
    (e,) = compute_ehs_credits(landlord, [{"id": "v", "class": "EHS-C1", "confirmed": "2026-10-01"}])
    assert e.amount == c["monthly_charges"] * 0.01


def test_landlord_generator_testing_follows_nfpa_110(landlord):
    monthly = next(t for t in landlord["maintenance"]["schedule"] if t["task"] == "Monthly loaded exercise")
    assert "30% of nameplate" in monthly["requirement"] and "30 minutes" in monthly["requirement"]
    assert any(ft["id"] == "gen_test_no_load" for ft in landlord["breach_severity"]["finding_types"])


# ------------------------------------------------------------------ interface agreement
def test_every_component_has_exactly_one_accountable_party(ia):
    assert validate_interface_agreement(ia) == []
    bad = copy.deepcopy(ia)
    bad["raci"][0]["Landlord"] = "A"
    assert any("exactly one Accountable" in e for e in validate_interface_agreement(bad))
    bad = copy.deepcopy(ia)
    bad["demarcations"][0]["upstream"] = "colo_provider"
    assert any("unknown party" in e for e in validate_interface_agreement(bad))


def test_ownership_matrix_covers_the_site_model(ia):
    site = S.load_site()
    keywords = {"compute_rack": "Compute tray", "ups": "UPS", "battery": "batteries", "busway": "Busway",
                "transformer": "transformers", "generator": "Generators", "cdu": "CDUs", "chiller": "Chillers",
                "pump": "pumps", "thermal_wall": "Thermal walls", "crah": "CRAHs", "leak_detection": "leak detection",
                "leak_cable": "leak detection", "smoke_detection": "VESDA", "fire_panel": "Fire alarm",
                "ib_switch": "Leaf and spine", "solid_state_transformer": "switchgear"}
    components = " | ".join(r["component"] for r in ia["raci"])
    for key, prod in site["products"].items():
        assert keywords[prod["category"]].lower() in components.lower(), (key, prod["category"])


def test_landlord_equipment_is_landlord_accountable(ia):
    row = {r["component"]: r for r in ia["raci"]}
    for comp in ("CDUs and the hall secondary header", "Busway, tap-off units, and tap-off breakers",
                 "Generators, paralleling controls, and fuel", "Fire alarm, VESDA, and pre-action suppression"):
        assert "A" in row[comp]["Landlord"], comp
    assert row["Rack manifold, isolation valves, quick-disconnects"]["IT Partner"] == "R"


def test_demarcations_match_the_site_and_both_slas(ia, it, landlord):
    cool = next(d for d in ia["demarcations"] if d["id"] == "DM-COOL")
    assert "isolation valves" in cool["boundary"] and cool["upstream"] == "landlord"
    assert any("isolation valves" in x["description"] for x in landlord["scope"]["in_scope"])
    assert any("isolation valves" in x["description"] for x in it["scope"]["in_scope"])


def test_party_names_agree_across_site_model_and_contracts(it):
    site = S.load_site()
    assert site["parties"]["landlord"]["name"] == it["parties"]["landlord"]["name"]
    assert site["parties"]["it_partner"]["name"] == it["parties"]["it_partner"]["name"]


# ------------------------------------------------------------------ documents
def test_landlord_document_states_every_term(landlord):
    text = (DOCS / "LANDLORD_SLA.md").read_text(encoding="utf-8")
    for x in (landlord["critical_service_levels"] + landlord["key_measurements"] + landlord["measurement_spec"]
              + landlord["breach_severity"]["finding_types"]):
        assert x["id"] in text, x["id"]
    assert "Ticket of Record" not in text, "IT wording leaked into the Landlord SLA"
    assert "### B.2 EHS Credits" in text and "Section 12" in text


def test_interface_document_and_exhibits(ia):
    text = (DOCS / "INTERFACE_AGREEMENT.md").read_text(encoding="utf-8")
    for r in ia["raci"]:
        assert r["component"] in text
    for r in ia["fault_attribution"]["rules"] + ia["demarcations"] + ia["handoffs"]:
        assert r["id"] in text
    for doc in ("IT_PARTNER_SLA.md", "LANDLORD_SLA.md"):
        assert f"Exhibit from the Interface Agreement ({ia['document']['id']}" in (DOCS / doc).read_text(encoding="utf-8")
