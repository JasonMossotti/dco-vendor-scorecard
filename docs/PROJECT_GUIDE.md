# Project Guide

How this project fits together and how to change it. Written so that someone new (a reviewer, a collaborator, or an AI assistant in a fresh conversation) can pick it up from the repository alone.

## The idea in one paragraph

At a partner-operated GPU data center site, a vendor does the hands-on work and the customer's site lead owns the outcome. This project shows how to hold that vendor accountable with **independent telemetry instead of vendor self-reporting**: a machine-readable SLA, synthetic site data with planted discrepancies, an engine that reconciles vendor records against telemetry, and a scorecard comparing what the vendor reported with what actually happened. Everything is synthetic and fictional.

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
