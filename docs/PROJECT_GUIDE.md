# Project Guide

How this project fits together and how to change it. Written so that someone new (a reviewer, a collaborator, or an AI assistant in a fresh conversation) can pick it up from the repository alone.

**Starting a new conversation with an AI assistant?** Give it the repository link and ask it to read this guide first. The sections "Current status", "How we work", and "Build history" below are the handoff.

## The idea in one paragraph

At a partner-operated GPU data center site, a vendor does the hands-on work and the customer's site lead owns the outcome. This project shows how to hold that vendor accountable with **independent telemetry instead of vendor self-reporting**: a machine-readable SLA, synthetic site data with planted discrepancies, an engine that reconciles vendor records against telemetry, and a scorecard comparing what the vendor reported with what actually happened. Everything is synthetic and fictional.

## Current status (as of 2026-10-04)

**Complete and live.** Every planned component is built, tested, and deployed:

| Component | Where |
|---|---|
| Repository | https://github.com/JasonMossotti/dco-vendor-scorecard (public; the owner renamed the account from RexFeral on 2026-10-04) |
| Live demo (GitHub Pages) | https://jasonmossotti.github.io/dco-vendor-scorecard/ |
| SLA document (generated) | `docs/SLA.md`: 24 sections plus appendices |
| Scorecard and discrepancy reports (generated) | `reports/scorecard.md`, `reports/discrepancy_report.md` |
| Tests | 99 (pytest), run by CI on every push and before every Pages deploy |
| AWS hosting guide | `docs/DEPLOY_AWS.md` |

Headline results on the committed sample (seed 2026, 2026-08-31 to 2026-09-28): 5 Minimum Service Level Defaults, $222,000 credits payable (capped from $255,300), 18 findings (14 S1 items in the severity log), 17 corrective action plans. Engine accuracy: 17 of 17 planted discrepancies on the sample, and 1,020 of 1,020 across 60 generated months, with zero false positives.

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
sla/vendor_sla.yaml ──► docs/SLA.md                     (scripts/render_sla.py)
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
```

The SLA YAML is the single source of truth. The document, generator, engine, scorecard, and app all read it.

## Where things live

| Concern | File |
|---|---|
| Every target, rule, credit term, severity band, discrepancy type | `sla/vendor_sla.yaml` |
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
| App logic (what-if overrides, tables), testable without Streamlit | `src/scorecard/app_support.py` |
| App layout | `app/streamlit_app.py` |
| What each data file represents | `docs/DATA_MODEL.md` |

## Common changes

**Change a target, window, or credit term.** Edit `sla/vendor_sla.yaml`, then run the regeneration commands below. The validator rejects inconsistent edits (for example, an Expected level easier than its Minimum, or allocations over the pool).

**Add a Key Measurement or Critical Service Level.** Add it to the YAML (keep total credit allocation within the pool), then add its calculation to `measure_period()` in `kpi.py`. If it is vendor-reported, map it in `VENDOR_FIELDS` in `builder.py`.

**Add a discrepancy type.** Add it under `breach_severity.finding_types` in the YAML (base severity, aggravators, SLA references, corrective action). Write a detector in `engine/detectors.py` decorated with `@detector`. To test it, plant it in the generator (`plant_anomalies()`, plus a count in `config/synthetic.yaml`) and add an evidence test in `tests/test_synthetic.py`. The robustness test then checks detection across unseen months.

**Add a fault class.** Add a rule card under `measurement_spec`, a validation checklist with `check_ids` under `rts_validation`, the category mapping in `engine/core.py` (`CATEGORY_TO_CLASS`, `telemetry_t0`, `validation_target`), and generation in the synthetic generator.

**Change the app.** Logic goes in `app_support.py` (tested); layout goes in `app/streamlit_app.py`. If the app starts using a new Streamlit feature, add it to `tests/fake_streamlit.py`.

## Regenerate everything after a change

```bash
python scripts/render_sla.py        # SLA document
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

- **Generated files are never edited by hand:** `docs/SLA.md`, `data/sample/`, and everything in `reports/`. Tests fail if they are out of date.
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
| Pure-Python scorecard function of (SLA, data) | Enables what-if analysis and runs in the browser |
| 1-hour post-repair burn-in | A 4-hour burn-in made the 4-hour P1 restore target impossible |

## Build history

In the order it was built, with the decisions that shaped each step:

1. **SLA as code.** `sla/vendor_sla.yaml` is the single source of truth, rendered to `docs/SLA.md`. Structure: Expected/Minimum levels, an at-risk amount (12% of monthly charges), a 250% allocation pool with a monthly cap, credit doubling, earnback, and chronic-failure termination rights. Telemetry of Record clocks run from T0 to Validated RTS.
2. **Synthetic GB200 NVL72 data.** A seeded generator for one site (Hall A in production with 32 racks; Hall B in deployment) writes telemetry and vendor records plus an answer key. The 4-hour tray burn-in was cut to 1 hour because it made the 4-hour P1 restore target impossible.
3. **Measurement specification and ticket handling** (the owner's ideas): one rule card per fault class so the vendor and customer measure identically, and TR-1 to TR-7 so a repair that fails again soon after cannot restart the clock. Also added capacity-weighted availability, a worst-rack floor (CSL-12), and KM-16 to KM-19.
4. **Discrepancy engine.** Connectors (answer key blocked), Tickets of Record rebuilt from telemetry, and 11 detectors. Severity and corrective actions come from `breach_severity.finding_types` in the SLA. Testing found two real bugs: the engine matched PSU faults by rack instead of slot, and the generator planted a discrepancy inside the SLA's 15-minute tolerance.
5. **Scorecard.** Every service level measured from telemetry beside the vendor's self-report, with credits, a severity log, and corrective action plans raised at the period review. `build_scorecard(sla, result)` is a pure function, which enables what-if analysis.
6. **Interactive demo.** A Streamlit app running in the browser through stlite on GitHub Pages, refreshed every Monday with a "latest 4 weeks" dataset. The owner's review caught a reset bug (sliders now reset through an `on_click` callback), dollar signs rendering as math, stacked bars, an unreadable weekly chart (now a vendor-vs-measured gap chart), and corrective action plans that looked overdue (due dates now count from the review date).
7. **Polish.** README screenshots and a 30-second summary, the AWS guide, and the account rename to JasonMossotti.

## Open items

- [ ] Fix the repository topic "gp" to "gpu" (GitHub repo page, gear icon next to About).
- [ ] Confirm the Git commit email uses GitHub's numbered noreply address (`git log -1 --format='%ae'`).
- [ ] Next: the owner has new ideas for larger project updates. Start by asking what they are, then plan before building.
