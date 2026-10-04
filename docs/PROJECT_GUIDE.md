# Project Guide

How this project fits together and how to change it. Written so that someone new (a reviewer, a collaborator, or an AI assistant in a fresh conversation) can pick it up from the repository alone.

**Starting a new conversation with an AI assistant?** Give it the repository link and ask it to read this guide first. The sections "Current status", "How we work", and "Build history" below are the handoff.

## The idea in one paragraph

At a partner-operated GPU data center site, vendors do the hands-on work and the customer's site lead owns the outcome. This project shows how to hold that vendor accountable with **independent telemetry instead of vendor self-reporting**: a machine-readable SLA, synthetic site data with planted discrepancies, an engine that reconciles vendor records against telemetry, and a scorecard comparing what the vendor reported with what actually happened. Everything is synthetic and fictional.

## Current status (as of 2026-10-04)

**Complete and live.** Every planned component is built, tested, and deployed:

| Component | Where |
|---|---|
| Repository | https://github.com/JasonMossotti/dco-vendor-scorecard (public; the owner renamed the account from RexFeral on 2026-10-04) |
| Live demo (GitHub Pages) | https://jasonmossotti.github.io/dco-vendor-scorecard/ |
| SLA (generated) | `docs/sla/IT_PARTNER_SLA.md` from `sla/it_partner.yaml` + `sla/common.yaml`: 24 sections plus appendices |
| Scorecard and discrepancy reports (generated) | `reports/scorecard.md`, `reports/discrepancy_report.md` |
| Site model and drawings (generated) | `site/site.yaml` -> `docs/site/SITE.md` plus 7 SVG sheets |
| Tests | 126 (pytest), run by CI on every push and before every Pages deploy |
| AWS hosting guide | `docs/DEPLOY_AWS.md` |

Headline results on the committed sample (seed 2026, 2026-08-31 to 2026-09-28): 5 Minimum Service Level Defaults, $222,000 credits payable (capped from $255,300), 18 findings (14 S1 items in the severity log), 17 corrective action plans. Engine accuracy: 17 of 17 planted discrepancies on the sample, and 1,020 of 1,020 across 60 generated months, with zero false positives.

**In progress: multi-vendor expansion.** The site is becoming a customer-owned AI data center in Central Texas with two contracted partners: Ridgeline Site Services (IT partner, the existing SLA) and Caprock Critical Facilities (OT partner, new). Phase 1 (site model and drawings), Phase 2 (SLA split into common terms and the IT partner SLA), and 2b (EHS strengthening) are complete; see "Roadmap" below for Phases 2 to 6. The "What if the SLA were different?" sliders were removed from the app at the owner's request: the SLA is the signed contract, and the app reports against it.

**Purpose:** a portfolio project for a Data Center Operations Lead (partner-operated sites) application. Keep everything synthetic and fictional; never imply knowledge of any real company's internal systems.

## How we work

The owner works on **Windows, using Git Bash**, with the repository at `C:\Users\jmoss\Desktop\GitHubRepos\dco-vendor-scorecard` (`/c/Users/jmoss/Desktop/GitHubRepos/dco-vendor-scorecard` in Git Bash). The owner is a data center and NOC operations professional, comfortable with the domain and newer to Git and Python tooling, so give exact commands and say what success looks like.

The delivery loop that has worked well:

1. The assistant makes changes in its own environment, regenerates every generated file, and runs the full test suite before handing anything over.
2. It delivers the **whole repository as a zip** (`dco-vendor-scorecard.zip`, whose top folder is `dco-vendor-scorecard/`).
3. The owner deletes any old `dco-vendor-scorecard` folder in Downloads, unzips the new zip there, and copies it over the repository, including hidden files:
   ```bash
   cp -R ~/Downloads/dco-vendor-scorecard/. /c/Users/jmoss/Desktop/GitHubRepos/dco-vendor-scorecard/
   cd /c/Users/jmoss/Desktop/GitHubRepos/dco-vendor-scorecard
   git add .
   git commit -m "Describe the change"
   git push
   ```
4. The owner checks that the GitHub Actions runs are green (CI and "Deploy demo to GitHub Pages"), then checks the live demo and sends screenshots of anything that looks wrong.

Working practices that caught real bugs, worth keeping:

- **Plan before building** larger features, and say which judgment calls the owner should be ready to defend.
- **Never ship untested UI code.** The app is tested end to end against `tests/fake_streamlit.py`. If the app uses a new Streamlit feature, teach the stand-in that feature, including the real-world behavior that matters (for example, a pair of `$` signs renders as math, widgets read from session state, and buttons run their `on_click` callback first).
- **Measure the engine on months it was not tuned on** (`python scripts/run_engine.py --robustness 60`). Investigate every miss or false positive to its root cause before changing anything.
- **Verify fast-changing external facts** (GitHub Actions versions, stlite version, AWS commands) against current documentation rather than memory. The stlite version is pinned in one constant in `scripts/build_site.py`.
- **Review the live app screen by screen** before sharing; several display bugs were only visible there.

## Pipeline

```
sla/common.yaml + sla/it_partner.yaml ──► docs/sla/IT_PARTNER_SLA.md   (scripts/render_sla.py)
        │
        ├──► synthetic generator ──► data/sample/        (scripts/generate_data.py; config/synthetic.yaml)
        │                                │
        │                                ▼
        ├──► discrepancy engine ──► reports/discrepancy_report.md, findings.json   (scripts/run_engine.py)
        │                                │
        │                                ▼
        └──► scorecard ──────────► reports/scorecard.md, scorecard.json            (scripts/build_scorecard.py)
                                         │
                                         ▼
                              interactive app (app/streamlit_app.py) ──► GitHub Pages (scripts/build_site.py)

site/site.yaml ──► docs/site/SITE.md + drawing sheets        (scripts/render_site.py)
```

The SLA YAML is the single source of truth for the contract (`load_sla()` merges `it_partner.yaml` onto `common.yaml`; a key set in both files is an error, so a partner file can add terms but never override a common one); `site/site.yaml` is the single source of truth for the equipment, topology, and monitoring. The document, generator, engine, scorecard, and app read the SLA; the drawings and site description read the site model, and tests check that the two agree (halls, rack counts, CDUs, rack-to-CDU mapping).

## Where things live

| Concern | File |
|---|---|
| Site-wide terms: Customer and site parties, site profile, measurement principles, excused events, corrective action, governance, security, EHS, SLA change control, severity levels and aggravators | `sla/common.yaml` |
| IT partner terms: commercials, scope, priorities, ticket handling, rule cards, CSLs, KMs, validation, deployment, staffing, spares, chronic failure, finding types | `sla/it_partner.yaml` |
| SLA document layout | `templates/sla.md.j2` |
| SLA loading, validation, credit math, severity | `src/scorecard/sla_model.py` |
| Ticket handling rules TR-1 to TR-6 (Tickets of Record) | `src/scorecard/measurement.py` |
| Synthetic site, incidents, telemetry, vendor records, planted discrepancies | `src/scorecard/synthetic/generator.py` |
| Generator tuning (fault rates, vendor behavior, how many of each discrepancy) | `config/synthetic.yaml` |
| Data access (one interface per source; answer key blocked) | `src/scorecard/connectors.py` |
| Engine: data context, ticket/telemetry linking, Tickets of Record | `src/scorecard/engine/core.py` |
| Engine: one detector per discrepancy type | `src/scorecard/engine/detectors.py` |
| Engine self-check against the answer key | `src/scorecard/engine/evaluate.py` |
| Service level measurement for any period | `src/scorecard/kpi.py` |
| Scorecard assembly: credits, severity log, corrective action plans | `src/scorecard/builder.py` |
| App logic (pipeline runner, tables), testable without Streamlit | `src/scorecard/app_support.py` |
| Site equipment, ratings, interfaces, sources, topology, monitoring map | `site/site.yaml` |
| Site expansion, power and cooling paths, capacity checks | `src/scorecard/site_model.py` |
| Drawing sheets (SVG), generated from the site model | `src/scorecard/site_drawings.py` |
| App layout | `app/streamlit_app.py` |
| What each data file represents | `docs/DATA_MODEL.md` |

## Common changes

**Change a target, window, or credit term.** Edit `sla/it_partner.yaml` (or `sla/common.yaml` for a site-wide term), then run the regeneration commands below. The validator rejects inconsistent edits (for example, an Expected level easier than its Minimum, or allocations over the pool).

**Add a Key Measurement or Critical Service Level.** Add it to the YAML (keep total credit allocation within the pool), then add its calculation to `measure_period()` in `kpi.py`. If it is vendor-reported, map it in `VENDOR_FIELDS` in `builder.py`.

**Add a discrepancy type.** Add it under `breach_severity.finding_types` in the YAML (base severity, aggravators, SLA references, corrective action). Write a detector in `engine/detectors.py` decorated with `@detector`. To test it, plant it in the generator (`plant_anomalies()`, plus a count in `config/synthetic.yaml`) and add an evidence test in `tests/test_synthetic.py`. The robustness test then checks detection across unseen months.

**Add a fault class.** Add a rule card under `measurement_spec`, a validation checklist with `check_ids` under `rts_validation`, the category mapping in `engine/core.py` (`CATEGORY_TO_CLASS`, `telemetry_t0`, `validation_target`), and generation in the synthetic generator.

**Change site equipment or quantities.** Edit `site/site.yaml`, then `python scripts/render_site.py`. The model refuses to load if any capacity check fails (for example, too few chillers for the design day), and the drawings and `docs/site/SITE.md` regenerate from the same file. Mark engineering assumptions in the `assumptions` list and cite manufacturer sources under the product.

**Change the app.** Logic goes in `app_support.py` (tested); layout goes in `app/streamlit_app.py`. If the app starts using a new Streamlit feature, add it to `tests/fake_streamlit.py`.

## Regenerate everything after a change

```bash
python scripts/render_sla.py        # SLA document
python scripts/render_site.py       # site description and drawings
python scripts/generate_data.py     # committed sample data
python scripts/run_engine.py        # discrepancy report
python scripts/build_scorecard.py   # scorecard
pytest -q                           # all tests; CI fails if any generated file is stale
```

Preview the browser app locally:

```bash
pip install -r requirements-app.txt
streamlit run app/streamlit_app.py
# or the exact browser build:
python scripts/build_site.py && python -m http.server -d _site 8000
```

## Conventions

- **Generated files are never edited by hand:** `docs/sla/`, `docs/site/`, `data/sample/`, and everything in `reports/`. Tests fail if they are out of date.
- **The engine never reads `ground_truth/`.** Only `engine/evaluate.py` does, after the engine has finished.
- **A finding means records do not reconcile, not that someone lied.** Keep that framing in report text.
- **Synthetic data only.** No real company's information, names, or documents.
- **Line endings are LF** on every platform (`.gitattributes`) so generated files compare byte for byte.

## Key design decisions

| Decision | Why |
|---|---|
| Telemetry of Record clocks (T0 to Validated RTS) | Removes vendor ticket timing from measurement |
| Tickets of Record rebuilt from telemetry | Makes ticket splitting visible and measurable (TR-6) |
| Record-integrity findings are S1 | Trust in the records underpins every other measurement |
| Worst-rack floor (CSL-12) | Fleet averages hide one failing rack |
| Expected vs. Minimum levels, credit pool, monthly cap, earnback | Standard outsourcing structure |
| Pure-Python scorecard function of (SLA, data) | Runs in the browser; a contract amendment is a one-line YAML change |
| Site model as code with capacity checks | Drawings, docs, and telemetry agree on what exists; an under-built site will not load |
| Distributed redundant UPS (4 make 3) with all six UPS pairings | A lost module's load spreads over the other three (worst case 97%) |
| Shared N+1 CDU secondary header per hall | A single CDU loss does not drop racks; the row's CDU is only the primary |
| Customer Telemetry of Record reads devices directly, read-only | The OT partner runs the BMS; the customer still has an independent source |
| 1-hour post-repair burn-in | A 4-hour burn-in made the 4-hour P1 restore target impossible |

## Build history

In the order it was built, with the decisions that shaped each step:

1. **SLA as code.** One YAML file was the single source of truth (split in step 9), rendered to a Markdown contract. Structure: Expected/Minimum levels, an at-risk amount (12% of monthly charges), a 250% allocation pool with a monthly cap, credit doubling, earnback, and chronic-failure termination rights. Telemetry of Record clocks run from T0 to Validated RTS.
2. **Synthetic GB200 NVL72 data.** A seeded generator for one site (Hall A in production with 32 racks; Hall B in deployment) writes telemetry and vendor records plus an answer key. The 4-hour tray burn-in was cut to 1 hour because it made the 4-hour P1 restore target impossible.
3. **Measurement specification and ticket handling** (the owner's ideas): one rule card per fault class so the vendor and customer measure identically, and TR-1 to TR-7 so a repair that fails again soon after cannot restart the clock. Also added capacity-weighted availability, a worst-rack floor (CSL-12), and KM-16 to KM-19.
4. **Discrepancy engine.** Connectors (answer key blocked), Tickets of Record rebuilt from telemetry, and 11 detectors. Severity and corrective actions come from `breach_severity.finding_types` in the SLA. Testing found two real bugs: the engine matched PSU faults by rack instead of slot, and the generator planted a discrepancy inside the SLA's 15-minute tolerance.
5. **Scorecard.** Every service level measured from telemetry beside the vendor's self-report, with credits, a severity log, and corrective action plans raised at the period review. `build_scorecard(sla, result)` is a pure function, so results always follow the contract as written.
6. **Interactive demo.** A Streamlit app running in the browser through stlite on GitHub Pages, refreshed every Monday with a "latest 4 weeks" dataset. The owner's review caught a reset bug (sliders now reset through an `on_click` callback), dollar signs rendering as math, stacked bars, an unreadable weekly chart (now a vendor-vs-measured gap chart), and corrective action plans that looked overdue (due dates now count from the review date).
7. **Polish.** README screenshots and a 30-second summary, the AWS guide, and the account rename to JasonMossotti.
8. **What-if removed; Phase 1 site model.** The sidebar sliders were removed (a test confirms none are drawn). Equipment was researched against manufacturer documentation and chosen for interoperability under one monitoring layer. `site/site.yaml` and `site_model.py` define three halls (A: 32 x GB200 NVL72 in production; B: 32 x GB300 NVL72 in deployment; C: 8-rack 800 VDC pilot, planned), 7 x Cat C175-16 generators (N+1), 11 x Liebert AFC chillers (N+1 at 43 C), 4 x Galaxy VX per hall in a distributed redundant 4-make-3 design, 4 x CoolIT CHx2000 per hall (N+1), and 2 x Eaton MVSST for Hall C. 25 capacity checks pass. Seven schematic sheets (A-001 campus, A-101 building, A-201 to A-203 halls, E-001 one-line, M-001 cooling) are generated and were reviewed visually. Decisions: the MVSST serves only the 800 VDC pilot because GB200 and GB300 power shelves take AC; leak cable senses water and conductive fluids because the coolant is PG25 (hydrocarbon cable only at the diesel tanks); Galaxy VX rather than VXL because the VXL is a 400 V IEC product and the site is 480 V. Regenerating left every report byte-identical.
9. **Phase 2: SLA split.** `sla/vendor_sla.yaml` became `sla/common.yaml` (site-wide terms) and `sla/it_partner.yaml` (`extends: common.yaml`). `load_sla()` performs an add-only merge (`merge_terms`); the merged result was verified identical to the old file, and every data, report, and site file stayed byte-identical. The rendered contract moved to `docs/sla/IT_PARTNER_SLA.md` and differs from the old `docs/SLA.md` only in its two source lines. Content changes (OT partner replacing the colocation "Facility Provider" wording and RACI column) were deliberately left for Phase 3.
10. **EHS strengthening (owner request).** `ehs` in `sla/common.yaml` binds every partner: principles, required standards with editions checked in October 2026 (NFPA 70E-2027 took effect May 6, 2026; NFPA 70B and 855 are 2026 editions; no final federal heat rule, so the contract sets 80 F and 90 F heat-index triggers modeled on the proposal), 12 site rules, partner qualification (EMR 1.0 or lower; workers' comp required because Texas allows opting out), reporting, independent investigation, three violation classes, and escalation to termination. `compute_ehs_credits()` applies the credits. Owner decisions: EHS Credits sit outside the monthly cap and are never earned back (validation enforces both). Design choices to defend: credits attach only to confirmed violations of required controls, never to reported injuries (29 CFR 1904.35); amounts are framed as a price adjustment and a reasonable pre-estimate of the Customer's costs, because courts do not enforce penalties; self-reporting halves a credit and concealment doubles it and is a record-integrity finding. Worked example in Appendix B.4. Not legal advice. Data and reports were unchanged.

## Roadmap (agreed with the owner; plan before building each phase)

3. **OT partner SLA and interface agreement.** `sla/ot_partner.yaml` (critical power availability per feed, cooling within band, alarm acknowledgment and response, redundancy restoration time, NFPA 110 generator testing, NFPA 72 inspections, coolant chemistry, MOP compliance, record integrity) and `sla/interface_agreement.yaml` (demarcation points, break-fix ownership matrix, joint incident command, fault-attribution rules using the site model's power and cooling paths).
4. **OT telemetry and detection.** Synthetic OT telemetry with real point and alarm names (UPS NMC SNMP, EMCP 4.4 Modbus, CHx2000 Redfish, VESDA Alert/Action/Fire 1/Fire 2, TraceTek leak location), OT detectors (for example, a generator test reported passed with no load transfer, maintenance marked complete with no evidence, a BMS point overridden or an alarm inhibited with no change record), cross-vendor attribution, OT and site scorecards, robustness runs. Use a separate random stream so the IT sample and its headline numbers do not change.
5. **App.** Partner selector, site rollup, attribution view.
6. **Live-readiness adapters.** SNMP, Modbus, Redfish, and BACnet connectors tested against protocol simulators. Real use would still need a security review, a read-only path segmented from the OT network, and site acceptance testing.

Later: a security partner (access control, CCTV, escorts).

## Open items

- [ ] Fix the repository topic "gp" to "gpu" (GitHub repo page, gear icon next to About).
- [ ] Confirm the Git commit email uses GitHub's numbered noreply address (`git log -1 --format='%ae'`).
- [ ] Next: Phase 3 (OT partner SLA and interface agreement). Present the plan, then build.
