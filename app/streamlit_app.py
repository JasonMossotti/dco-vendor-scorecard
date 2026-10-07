"""DCO Vendor Scorecard: interactive demo.

Runs locally (``streamlit run app/streamlit_app.py``) or entirely in the browser
on GitHub Pages via stlite. All logic lives in ``scorecard.app_support``; this
file only lays out the page.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for cand in (here.parent, here.parent.parent, Path.cwd()):
        if (cand / "sla" / "it_partner.yaml").exists():
            return cand
    return here.parent


ROOT = _project_root()
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from scorecard import app_support as A  # noqa: E402
from scorecard.sla_model import load_sla  # noqa: E402

REPO = "https://github.com/JasonMossotti/dco-vendor-scorecard"
SEV_ORDER = ["S1", "S2", "S3", "S4"]

st.set_page_config(page_title="DCO Vendor Scorecard", page_icon="📊", layout="wide")
CONTRACT = load_sla(ROOT / "sla" / "it_partner.yaml")
# --------------------------------------------------------------------------- #
# Controls: which partner, and which dataset (the site's tab bar sits above the app)
# --------------------------------------------------------------------------- #
VIEWS = ["Site summary", "IT Partner (Ridgeline)", "Landlord (Caprock)"]
GENERATE = "Generate a new random month"
datasets = A.available_datasets(ROOT)
choices = list(datasets) + [GENERATE]


def _keep_view() -> None:
    """A segmented control can be clicked off; keep the last view instead of showing none."""
    if st.session_state.get("view") is None:
        st.session_state["view"] = st.session_state.get("last_view", VIEWS[0])


st.session_state.setdefault("view", VIEWS[0])
left, right, codes = st.columns([3, 2, 1], vertical_alignment="bottom")
with left:
    view = st.segmented_control("View", VIEWS, key="view", on_change=_keep_view) or st.session_state.get("last_view", VIEWS[0])
    st.session_state["last_view"] = view
with right:
    pick = st.selectbox("Dataset", choices, index=0)
with codes:
    # The static pages explain each code in a popup; here a small panel does, without leaving the page.
    with st.popover("Look up a code"):
        code_q = st.text_input("Code or ID", placeholder="CSL-07, TR-1, INC3100816, A07, CDU-B3 pump 2", key="code_lookup")
        loc = A.location_view(code_q)
        lines = A.lookup_lines(code_q)
        dev = A.device_lines(code_q)
        if (loc is None and not dev) or not lines[0].startswith("No code"):
            for line in lines:
                st.markdown(line)
        ref = code_q.strip().upper()
        if ref in A.portal_ids(A.ROOT / "data" / "sample"):
            # A ticket, change, or work order of the sample month: its full record is on the Incident Portal tab.
            st.markdown(f"[Open {ref} in the Incident Portal]({A.ticket_url(ref)})")
        if dev:
            # A device: what it is and what it connects to (the static pages show this in the code popup).
            st.markdown("\n\n".join(dev[:3]) + "\n\n" + "\n".join(dev[3:]))
        if loc:
            # A rack, room, or piece of equipment: where it is on the site drawings, outlined in red.
            st.markdown(f"**{A._md(loc['title'])}** · {loc['kind']} · {A._md(loc['text'])}")
            sheet = st.selectbox("Drawing", [v[0] for v in loc["views"]], key="code_lookup_sheet")
            st.image(dict(loc["views"])[sheet], width=640,
                     caption="Outlined in red; dashed: what feeds or serves it. Schematic, fictional site.")
if pick == GENERATE:
    c1, c2, _ = st.columns([1, 1, 3], vertical_alignment="bottom")
    with c1:
        seed = st.number_input("Seed", min_value=1, max_value=99999, value=7, step=1)
    with c2:
        if st.button("Generate"):
            with st.spinner("Generating a synthetic month..."):
                st.session_state["generated"] = (int(seed), str(A.generate_month(int(seed), ROOT)))
    gen = st.session_state.get("generated")
    if gen is None:
        st.info("Choose a seed and press **Generate**. Each seed is a different, reproducible month.")
        st.stop()
    data_dir = gen[1]
    st.caption(f"Showing generated month for seed {gen[0]}.")
else:
    data_dir = str(datasets[pick])
st.divider()

# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
with st.spinner("Reconciling vendor records against telemetry..."):
    result, sc, ev = A.run_pipeline(CONTRACT, data_dir)
facility = A.has_facility(data_dir)
if facility:
    with st.spinner("Reconciling the Landlord's records against facility telemetry..."):
        ll_result, ll_sc, ll_ev, it_plain = A.run_landlord_pipeline(data_dir)
WINDOW = f"{sc['window']['start']:%b %d} to {sc['window']['end']:%b %d, %Y}"
FOOT = "Synthetic data for a portfolio demonstration; all names and events are fictional."


def render_it(result, sc, ev) -> None:
    """The IT Partner (Ridgeline) scorecard: unchanged from the single-vendor demo."""
    sla = CONTRACT
    st.title("Vendor SLA Scorecard")
    st.caption(f"{sc['site']} · Supplier: {sc['supplier']} · {WINDOW} · {FOOT}")

    tabs = st.tabs(["Overview", "Service levels", "Findings", "Corrective actions", "Incidents", "About"])

    # ---- Overview ----------------------------------------------------------------
    with tabs[0]:
        st.markdown(A.headline(sc))
        t = sc["totals"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Minimum defaults", t["defaults"])
        c2.metric("Credits payable", f"${sc['credits']['payable']:,.0f}")
        c3.metric("S1 items", t["s1"])
        c4.metric("Corrective action plans", len(sc["corrective_actions"]))
        c5.metric("Discrepancies found", t["findings"])

        st.subheader("Vendor reported vs. measured from telemetry")
        vv = pd.DataFrame(A.vendor_vs_measured_rows(sc))
        st.dataframe(vv, hide_index=True)
        chart = vv.assign(**{"Service level": vv["Service level"].str.split(" ").str[0]})
        chart = chart.set_index("Service level")[["Vendor reported (%)", "Measured (%)"]]
        st.bar_chart(chart, stack=False)
        st.caption("Fleet availability is nearly identical either way: a few hidden hours vanish inside millions of "
                   "GPU-hours. The gaps show up in restoration, repair quality, and record integrity.")

        if ev is not None:
            st.subheader("Engine self-check")
            st.markdown(f"The data generator planted **{ev.planted}** discrepancies in an answer key the engine cannot read. "
                        f"The engine found **{ev.detected} of {ev.planted}** with **{len(ev.false_positives)} false "
                        f"positive{'s' if len(ev.false_positives) != 1 else ''}**.")

    # ---- Service levels ----------------------------------------------------------
    with tabs[1]:
        st.subheader("Critical Service Levels (credit-bearing)")
        st.dataframe(pd.DataFrame(A.csl_rows(sc)), hide_index=True)
        cr = sc["credits"]
        st.markdown(f"**Credits:** \\${cr['uncapped']:,.0f} before the monthly cap; **\\${cr['payable']:,.0f} payable**"
                    + (" (the cap applied)." if cr["capped"] else "."))
        st.subheader("Week by week: how far the vendor's report was from the telemetry")
        st.caption("Measured minus vendor-reported, in percentage points. 0 means the vendor's weekly report was "
                   "accurate; below 0 means it overstated performance.")
        gaps = pd.DataFrame(A.weekly_gap_rows(sc)).set_index("Week")
        st.line_chart(gaps, color=["#ff4b4b", "#ffa421", "#29b09d", "#7d8cff"])
        st.dataframe(pd.DataFrame(A.weekly_rows(sc)), hide_index=True)
        st.subheader("Key Measurements")
        st.dataframe(pd.DataFrame(A.km_rows(sc)), hide_index=True)

    # ---- Findings ----------------------------------------------------------------
    with tabs[2]:
        st.markdown("Each finding is a place where vendor records do not reconcile with telemetry. "
                    "A finding starts a review; it is not by itself proof of intent.")
        types = sorted({f.title for f in result.findings})
        f1, f2 = st.columns(2)
        sev_pick = f1.multiselect("Severity", SEV_ORDER, default=SEV_ORDER)
        type_pick = f2.multiselect("Type", types, default=types)
        shown = [f for f in result.findings if f.severity in sev_pick and f.title in type_pick]
        st.caption(f"{len(shown)} of {len(result.findings)} findings")
        for f in shown:
            with st.expander(f"{f.id} · {f.severity} {f.severity_name} · {f.title} · {', '.join(f.tickets) or f.unit}"):
                st.markdown(A.link_tickets(f.summary, data_dir))
                if A.portal_line(f.tickets, data_dir):
                    st.markdown(A.portal_line(f.tickets, data_dir))
                st.dataframe(pd.DataFrame(A.evidence_rows(f)), hide_index=True)
                st.markdown(f"**Why {f.severity}:** {'; '.join(f.severity_reasons)}.")
                st.markdown(f"**Recommended action:** {f.recommended_action}")
                st.markdown(f"**SLA references:** {A.explain_refs(f.sla_refs)}")

    # ---- Corrective actions ------------------------------------------------------
    with tabs[3]:
        st.subheader("Corrective action plans")
        st.caption("Drafted automatically at this period review for every S1 and S2 item, grouped by affected tickets. "
                   "Due dates count from the review: S1 within 5 business days, S2 within 10.")
        caps = A.cap_rows(sc)
        st.dataframe(pd.DataFrame(caps), hide_index=True)
        if A.portal_line([c["Tickets"] for c in caps], data_dir):
            st.caption(A.portal_line([c["Tickets"] for c in caps], data_dir))
        st.subheader("Severity log")
        sev = pd.DataFrame(A.severity_rows(sc))
        st.dataframe(sev, hide_index=True)
        if A.portal_line(sev["Tickets"], data_dir):
            st.caption(A.portal_line(sev["Tickets"], data_dir))

    # ---- Incidents ---------------------------------------------------------------
    with tabs[4]:
        st.markdown("One row per **Ticket of Record**, rebuilt from telemetry. Split vendor tickets are merged "
                    "(TR-1, TR-2), and restoration runs from telemetry T0 to Validated RTS.")
        targets = {p["id"]: p["restore_min"] for p in sla["priorities"]}
        inc_rows = A.incident_rows(sc, targets)
        linked = A.link_column(inc_rows, "Ticket of Record", data_dir)
        inc = pd.DataFrame(inc_rows)
        p_pick = st.multiselect("Priority", ["P1", "P2", "P3"], default=["P1", "P2", "P3"])
        only_late = st.checkbox("Only incidents past their restore target")
        view = inc[inc["Priority"].isin(p_pick)]
        if only_late:
            view = view[~view["Within target"]]
        # The Ticket of Record opens the ticket in the Incident Portal (sample month only).
        st.dataframe(view, hide_index=True, column_config={"Ticket of Record": st.column_config.LinkColumn(
            "Ticket of Record", display_text=r"#(.+)$", help="Opens the ticket in the Incident Portal")} if linked else None)

    # ---- About -------------------------------------------------------------------
    with tabs[5]:
        st.markdown(f"""
    **What this is.** A portfolio demonstration of vendor oversight at a partner-operated GPU data center
    (a fictional site of NVIDIA GB200 NVL72 racks). The core idea: **verify vendor performance with independent
    telemetry, not vendor self-reporting.**

    **How it works.**
    1. A machine-readable SLA defines every service level, ticket handling rule, and severity band.
    2. A synthetic data generator simulates four weeks of hardware telemetry and vendor records,
       then plants realistic discrepancies (split tickets, unverified part swaps, skipped validation, and more).
    3. A discrepancy engine rebuilds every incident from telemetry alone and flags where the vendor's records disagree.
    4. This scorecard measures every service level from telemetry and compares it with the vendor's own weekly report.

    **Everything here runs in your browser.** There is no server: Python runs locally via WebAssembly.

    **Read more:** [README]({REPO}#readme) · [The SLA]({REPO}/blob/main/docs/sla/IT_PARTNER_SLA.md) ·
    [Discrepancy report]({REPO}/blob/main/reports/discrepancy_report.md) ·
    [Data model]({REPO}/blob/main/docs/DATA_MODEL.md)

    *All data, people, sites, and commercial terms are synthetic and fictional. Not affiliated with, or based on
    internal information from, any real company.*
    """)


def render_site() -> None:
    st.title("Site AUS-1: two partners, one set of telemetry")
    st.caption(f"{WINDOW} · {FOOT}")
    st.markdown("The Customer leases the halls from a Landlord that runs the building, power, and cooling, and contracts an "
                "IT Partner for the data hall work. Each is measured against its own SLA from the Customer's Telemetry of "
                "Record. Outages that cross the boundary between them are attributed under the Interface Agreement.")
    st.subheader("Both partners, measured")
    st.dataframe(pd.DataFrame(A.site_rows(sc, ll_sc, ev, ll_ev)), hide_index=True)
    st.subheader("Outages that crossed the demarcation")
    crossing = A.crossing_outages(ll_sc, result)
    for line in crossing or ["No outage crossed the demarcation in this window."]:
        st.markdown(A.link_tickets(line, data_dir))
    st.subheader("What attribution changed for the IT Partner")
    st.caption("The same telemetry, scored with the IT Partner's clock starting at the power loss instead of the Landlord's handoff.")
    st.dataframe(pd.DataFrame(A.attribution_change_rows(sc, it_plain)), hide_index=True)
    st.markdown("Without attribution, the IT Partner would be charged for hours the Landlord's equipment kept the rack dark. "
                "With it, each party is charged only for its own side of the demarcation.")
    st.caption("Use IT Partner and Landlord above for each partner's full scorecard.")


def render_landlord() -> None:
    st.title("Landlord SLA Scorecard")
    st.caption(f"{ll_sc['supplier']} · {WINDOW} · {FOOT}")
    tabs = st.tabs(["Overview", "Service levels", "Findings", "Facility events", "About"])
    with tabs[0]:
        st.markdown(A.landlord_headline(ll_sc))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Minimum defaults", len(ll_sc["defaults"]))
        c2.metric("Credits against rent", f"${ll_sc['credits']['payable']:,.0f}")
        c3.metric("S1 findings", ll_sc["s1"])
        c4.metric("Discrepancies found", ll_sc["findings"])
        st.subheader("Landlord reported vs. measured from telemetry")
        st.dataframe(pd.DataFrame(A.landlord_vs_reported_rows(ll_sc)), hide_index=True)
        if ll_ev is not None:
            st.subheader("Engine self-check")
            st.markdown(f"The data generator planted **{ll_ev.planted}** Landlord discrepancies in an answer key the engine "
                        f"cannot read. The engine found **{ll_ev.detected} of {ll_ev.planted}** with "
                        f"**{len(ll_ev.false_positives)} false positive{'s' if len(ll_ev.false_positives) != 1 else ''}**.")
    with tabs[1]:
        st.subheader("Critical Service Levels (credit-bearing, against rent)")
        st.dataframe(pd.DataFrame(A.landlord_csl_rows(ll_sc)), hide_index=True)
        cr = ll_sc["credits"]
        st.markdown(f"**Credits:** \\${cr['payable']:,.0f} payable" + (" (the monthly cap applied)." if cr["capped"] else "."))
        st.subheader("Key Measurements")
        st.dataframe(pd.DataFrame(A.landlord_km_rows(ll_sc)), hide_index=True)
    with tabs[2]:
        st.markdown("Each finding is a place where the Landlord's work orders or maintenance records do not reconcile with "
                    "device telemetry. A finding starts a review; it is not by itself proof of intent.")
        for f in ll_result.findings:
            with st.expander(f"{f.id} · {f.severity} {f.severity_name} · {f.title} · {f.unit or ''}"):
                st.markdown(A.link_tickets(f.summary, data_dir))
                if A.portal_line(f.tickets, data_dir):
                    st.markdown(A.portal_line(f.tickets, data_dir))
                st.dataframe(pd.DataFrame(A.evidence_rows(f)), hide_index=True)
                st.markdown(f"**Recommended action:** {f.recommended_action}")
                st.markdown(f"**SLA references:** {A.explain_refs(f.sla_refs)}")
    with tabs[3]:
        st.markdown("Every facility event in the window, rebuilt from device telemetry and attributed under the Interface "
                    "Agreement, beside the party the Landlord's work order named.")
        att = A.attribution_display_rows(ll_sc)
        linked = A.link_column(att, "Work order", data_dir)
        st.dataframe(pd.DataFrame(att), hide_index=True, column_config={"Work order": st.column_config.LinkColumn(
            "Work order", display_text=r"#(.+)$", help="Opens the work order in the Incident Portal")} if linked else None)
    with tabs[4]:
        st.markdown(f"""
**What this is.** The Landlord's side of the same fictional site: a wholesale owner-operator that runs the building,
power, and cooling and leases the halls to the Customer. Its SLA is measured from device telemetry the Customer reads
under a negotiated term of the lease (UPS management cards, busway monitors, generator controllers, CDU Redfish, leak
and VESDA controllers, the BMS, and badge entries), not from the Landlord's own reports.

**Read more:** [Landlord SLA]({REPO}/blob/main/docs/sla/LANDLORD_SLA.md) ·
[Interface Agreement]({REPO}/blob/main/docs/sla/INTERFACE_AGREEMENT.md) ·
[Landlord discrepancy report]({REPO}/blob/main/reports/landlord_discrepancy_report.md) ·
[Site model and drawings]({REPO}/blob/main/docs/site/SITE.md)
""")


if view == "IT Partner (Ridgeline)" or not facility:
    if not facility and view != "IT Partner (Ridgeline)":
        st.info("This dataset has no facility data, so only the IT Partner view is available.")
    render_it(result, sc, ev)
elif view == "Landlord (Caprock)":
    render_landlord()
else:
    render_site()
