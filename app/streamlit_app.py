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
        if (cand / "sla" / "vendor_sla.yaml").exists():
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
CONTRACT = load_sla(ROOT / "sla" / "vendor_sla.yaml")
DEFAULTS = A.contract_defaults(CONTRACT)
WIDGET_DEFAULTS = A.widget_defaults(CONTRACT)
for _k, _v in WIDGET_DEFAULTS.items():          # widgets read their values from session state
    st.session_state.setdefault(_k, _v)


def reset_to_contract() -> None:
    """Runs before the next render, so the sliders themselves move back (not just the data)."""
    for k, v in WIDGET_DEFAULTS.items():
        st.session_state[k] = v

# --------------------------------------------------------------------------- #
# Sidebar: dataset and what-if controls
# --------------------------------------------------------------------------- #
st.sidebar.header("Data")
datasets = A.available_datasets(ROOT)
choices = list(datasets) + ["Generate a new random month"]
pick = st.sidebar.radio("Dataset", choices, index=0)
if pick == "Generate a new random month":
    seed = st.sidebar.number_input("Seed", min_value=1, max_value=99999, value=7, step=1)
    if st.sidebar.button("Generate"):
        with st.spinner("Generating a synthetic month..."):
            st.session_state["generated"] = (int(seed), str(A.generate_month(int(seed), ROOT)))
    gen = st.session_state.get("generated")
    if gen is None:
        st.info("Choose a seed and press **Generate** in the sidebar. Each seed is a different, reproducible month.")
        st.stop()
    data_dir = gen[1]
    st.sidebar.caption(f"Showing generated month for seed {gen[0]}.")
else:
    data_dir = str(datasets[pick])

st.sidebar.header("What if the SLA were different?")
st.sidebar.caption("Change contract terms and every result recalculates from the same telemetry.")
st.sidebar.button("Reset to contract values", on_click=reset_to_contract)

with st.sidebar.expander("Restore targets", expanded=True):
    restore = {p: st.slider(f"{p} restore target (hours)", 1.0, 48.0 if p == "P3" else 16.0,
                            step=0.5, key=f"wf_restore_{p}")
               for p in ("P1", "P2", "P3")}
with st.sidebar.expander("Ticket handling"):
    early = st.slider("Early-failure window, TR-1 (minutes)", 0, 240, step=5, key="wf_early")
    stability = st.slider("Stability window, TR-2 (hours)", 2, 72, step=1, key="wf_stability")
with st.sidebar.expander("Service level thresholds"):
    csl_names = {c["id"]: f"{c['id']} {c['name']}" for c in CONTRACT["critical_service_levels"]}
    cid = st.selectbox("Service level", list(csl_names), format_func=lambda c: csl_names[c], key="wf_csl")
    exp = st.number_input("Expected (%)", 0.0, 100.0, step=0.1, key=f"wf_exp_{cid}")
    mn = st.number_input("Minimum (%)", 0.0, 100.0, step=0.1, key=f"wf_min_{cid}")
with st.sidebar.expander("Commercials"):
    at_risk = st.slider("At-risk amount (% of monthly charges)", 5.0, 20.0, step=0.5, key="wf_atrisk")

overrides = {"restore_hours": restore, "early_failure_minutes": early, "stability_hours": stability,
             "at_risk_pct": at_risk, "thresholds": {cid: (exp, mn)}}
sla = A.apply_overrides(CONTRACT, overrides)
changes = A.changed_from_contract(CONTRACT, overrides)
direction_ok = next(c for c in sla["critical_service_levels"] if c["id"] == cid)
if (direction_ok["direction"] == "higher_is_better" and exp < mn) or (direction_ok["direction"] == "lower_is_better" and exp > mn):
    st.sidebar.error("Expected must be at least as demanding as Minimum. Threshold change ignored.")
    overrides["thresholds"] = {}
    sla = A.apply_overrides(CONTRACT, overrides)
    changes = A.changed_from_contract(CONTRACT, overrides)

st.sidebar.divider()
st.sidebar.markdown(f"[Source code and SLA on GitHub]({REPO})")

# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
with st.spinner("Reconciling vendor records against telemetry..."):
    result, sc, ev = A.run_pipeline(sla, data_dir)
ctx = result.context

st.title("Vendor SLA Scorecard")
st.caption(f"{sc['site']} · Supplier: {sc['supplier']} · {sc['window']['start']:%b %d} to "
           f"{sc['window']['end']:%b %d, %Y} · Synthetic data for a portfolio demonstration; all names and events are fictional.")
if changes:
    st.warning("**What-if mode.** Results use modified SLA terms: " + "; ".join(changes) + ".")

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
            st.markdown(f.summary)
            st.dataframe(pd.DataFrame(A.evidence_rows(f)), hide_index=True)
            st.markdown(f"**Why {f.severity}:** {'; '.join(f.severity_reasons)}.")
            st.markdown(f"**Recommended action:** {f.recommended_action}")
            st.markdown(f"**SLA references:** {', '.join(f.sla_refs)}")

# ---- Corrective actions ------------------------------------------------------
with tabs[3]:
    st.subheader("Corrective action plans")
    st.caption("Drafted automatically at this period review for every S1 and S2 item, grouped by affected tickets. "
               "Due dates count from the review: S1 within 5 business days, S2 within 10.")
    st.dataframe(pd.DataFrame(A.cap_rows(sc)), hide_index=True)
    st.subheader("Severity log")
    sev = pd.DataFrame(A.severity_rows(sc))
    st.dataframe(sev, hide_index=True)

# ---- Incidents ---------------------------------------------------------------
with tabs[4]:
    st.markdown("One row per **Ticket of Record**, rebuilt from telemetry. Split vendor tickets are merged "
                "(TR-1, TR-2), and restoration runs from telemetry T0 to Validated RTS.")
    targets = {p["id"]: p["restore_min"] for p in sla["priorities"]}
    inc = pd.DataFrame(A.incident_rows(sc, targets))
    p_pick = st.multiselect("Priority", ["P1", "P2", "P3"], default=["P1", "P2", "P3"])
    only_late = st.checkbox("Only incidents past their restore target")
    view = inc[inc["Priority"].isin(p_pick)]
    if only_late:
        view = view[~view["Within target"]]
    st.dataframe(view, hide_index=True)

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

**Read more:** [README]({REPO}#readme) · [The SLA]({REPO}/blob/main/docs/SLA.md) ·
[Discrepancy report]({REPO}/blob/main/reports/discrepancy_report.md) ·
[Data model]({REPO}/blob/main/docs/DATA_MODEL.md)

*All data, people, sites, and commercial terms are synthetic and fictional. Not affiliated with, or based on
internal information from, any real company.*
""")
