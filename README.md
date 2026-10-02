# DCO Vendor Scorecard

[![CI](https://github.com/RexFeral/dco-vendor-scorecard/actions/workflows/ci.yml/badge.svg)](https://github.com/RexFeral/dco-vendor-scorecard/actions/workflows/ci.yml)

**Vendor performance and repair-verification scorecard for partner-operated GPU data center sites.**

**▶ [Open the interactive demo](https://rexferal.github.io/dco-vendor-scorecard/)** (runs entirely in your browser; first load takes 20 to 40 seconds)

> Portfolio demonstration. All data, parties, sites, and commercial terms are synthetic and fictional. Not affiliated with, or based on internal information from, any real company.

![Scorecard overview: vendor reported vs. measured from telemetry](docs/images/overview.png)

**In 30 seconds:** a GPU site vendor's weekly reports say every SLA was met. This project rebuilds every incident from hardware telemetry (GPU faults, BMC inventory, fabric counters, badge access) and finds 5 Minimum Service Level Defaults, $222,000 in credits, and 18 places where the vendor's records do not match what the hardware recorded, each with evidence, a severity, and a corrective action. The contract itself is code, so changing a target in the SLA changes every result.

## The idea

At a partner-operated site, the vendor does the hands-on work and the site lead owns the outcome. The core principle of this project: **verify vendor performance with independent telemetry, not vendor self-reporting.** The scorecard reconciles what the vendor's tickets say against what the hardware itself reports (GPU telemetry, BMC inventory, fabric counters, badge access), then scores the result against a contractual SLA.

## Status

| Component | Status |
|---|---|
| SLA as code (`sla/vendor_sla.yaml`) | Done |
| Generated SLA document ([`docs/SLA.md`](docs/SLA.md)) | Done |
| SLA model: validation, credits, breach severity | Done, tested |
| Synthetic GB200 NVL72 site data generator ([`docs/DATA_MODEL.md`](docs/DATA_MODEL.md)) | Done, tested |
| Connectors and discrepancy engine ([`reports/discrepancy_report.md`](reports/discrepancy_report.md)) | Done, tested |
| Weekly scorecard ([`reports/scorecard.md`](reports/scorecard.md)) | Done, tested |
| Interactive demo ([live](https://rexferal.github.io/dco-vendor-scorecard/)) | Done, tested |

## SLA as code

The SLA lives in one YAML file. The human-readable contract is generated from it, and the scoring engine reads its thresholds from it, so the contract and the code can never disagree. CI fails if the document is out of date.

```bash
pip install -r requirements.txt
python scripts/render_sla.py     # validate the SLA and regenerate docs/SLA.md
python scripts/generate_data.py  # regenerate the synthetic sample in data/sample
python scripts/run_engine.py     # run the discrepancy engine, write reports/
python scripts/build_scorecard.py  # build the scorecard, write reports/
pytest -q                        # run the test suite
```

Highlights of the SLA design:

- **Telemetry of Record:** repair clocks start at the first machine-detected fault, not when a ticket is opened.
- **"Fixed" means validated:** clocks stop only when the component passes its return-to-service checks (diagnostics, NVLink health, leak hold, burn-in).
- **Record Integrity service level:** credits apply when vendor records do not reconcile with telemetry (e.g., a part swap claimed but the serial number never changed).
- **Ticket handling rules:** a repair is finished when the unit *stays* up. A refault within 60 minutes voids the restore and the clock runs continuously; a refault within the stability window reopens the ticket and downtime accumulates; opening a new ticket to restart the clock is a record-integrity finding.
- **Measurement specification:** one rule card per fault class (GPU, NVLink switch, link, PSU, power shelf, CDU, leak) defining the exact detection signal, T0 rule, evidence, validation, clock-stop event, and stability window, so the vendor and the customer measure identically.
- **Capacity accounting:** downtime is measured in capacity-weighted GPU-hours (degraded links count), with a worst-rack floor so a good fleet average cannot hide one failing rack.
- **Internal breach severity index (S1 to S4):** combines how late an incident was with how many GPU-hours were lost, plus aggravators like repeat failures or safety events.

## Synthetic site data

`scripts/generate_data.py` simulates a fictional GB200 NVL72 site for four weeks and writes two views of the same events: what the **hardware and Customer systems** recorded (GPU XID events, BMC inventory and alarms, fabric events, CDU alarms, scheduler states, validation health checks, badge access) and what the **vendor** reported (tickets, roster, spares ledger, deployment milestones, weekly self-report).

It then plants 11 types of realistic discrepancies, such as a repair ticket claiming a part swap the BMC inventory never saw, or a technician "on site" before badging into the hall, and writes an answer key so the engine's detection rate can be measured.

The committed sample in [`data/sample/`](data/sample) covers 4 weeks and 17 planted discrepancies across 11 types. In it, the vendor's self-report shows 100% across the board; the telemetry does not agree. See [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) for every file and discrepancy type.

## The scorecard: vendor reported vs. measured

`scripts/build_scorecard.py` measures every service level from telemetry and puts it beside the vendor's own weekly report. From the committed sample ([full scorecard](reports/scorecard.md)):

| Service level | Vendor reported | Measured from telemetry |
|---|:-:|:-:|
| P2 restoration within 8 hours | 100% | 92.6% |
| First-time fix rate | 100% | 90.7% |
| Validated return to service | 100% | 97.3% (Minimum default) |
| Record integrity | not reported | 83.3% (Minimum default) |

The vendor's weekly notes said all SLAs were met or showed only minor exceptions. Measured, the period has 5 Minimum Service Level Defaults, $222,000 in Service Level Credits (after the monthly cap), and 17 corrective action plans drafted automatically with owners and due dates. Fleet availability, by contrast, is 99.94% either way, which is why the scorecard measures each incident rather than trusting the average.

`build_scorecard(sla, result)` is a pure function of the SLA and the data, so changing a target (for example, a 4-hour P2 restore) and rerunning immediately shows the new breaches, credits, and corrective actions. The interactive demo is built on that.

## Discrepancy engine

`scripts/run_engine.py` reads the telemetry and vendor records through a connector layer, rebuilds every incident from telemetry alone using the SLA's ticket handling rules, and reports each place the vendor's records do not reconcile, with the exact evidence, an S1 to S4 severity, and the corrective action defined in the SLA.

**Results:** on the committed sample it finds all 17 planted discrepancies with no false positives (see the [discrepancy report](reports/discrepancy_report.md)). Across 60 freshly generated months it detected **1,020 of 1,020** with **0 false positives**. The engine cannot read the answer key: the connector blocks it, and a test deletes the answer key and confirms the findings do not change.

Production integration is a matter of swapping connectors: each data source (GPU telemetry, BMC Redfish inventory, fabric managers, scheduler, badge system, vendor ITSM) sits behind one interface in [`src/scorecard/connectors.py`](src/scorecard/connectors.py).

```bash
python scripts/run_engine.py                    # data/sample -> reports/
python scripts/run_engine.py --robustness 20    # also test 20 freshly generated months
```

## Interactive demo

The [demo](https://rexferal.github.io/dco-vendor-scorecard/) runs the whole pipeline in the browser (Python via WebAssembly, no server). You can:

- Switch between the committed sample, the latest 4 weeks (regenerated every Monday by GitHub Actions), or a brand-new random month.
- Change SLA terms in the sidebar (restore targets, ticket handling windows, service level thresholds, at-risk amount) and watch every result recalculate from the same telemetry.
- Drill into each finding's evidence, the corrective action plans, and every incident.

<p>
  <img src="docs/images/finding.png" alt="A finding with its evidence: a compute tray returned to service with no validation checks recorded" width="680">
  <img src="docs/images/what-if.png" alt="What-if controls in the sidebar" width="190">
</p>

Run it locally with `pip install -r requirements-app.txt` and `streamlit run app/streamlit_app.py`. To host it on AWS (S3, EC2, or a production-shaped architecture), see [docs/DEPLOY_AWS.md](docs/DEPLOY_AWS.md).

## Project layout

```
sla/vendor_sla.yaml              Single source of truth for the SLA
config/synthetic.yaml            Generator settings: fault rates, vendor behavior, planted discrepancies
src/scorecard/sla_model.py       Load, validate, credit math, severity classification
src/scorecard/measurement.py     Ticket handling rules (TR-1 to TR-6) as the reference implementation
src/scorecard/connectors.py      Data access layer (one interface per source; answer key blocked)
src/scorecard/engine/            Discrepancy engine: context, 11 detectors, evaluation, reports
src/scorecard/kpi.py             Service level measurement from telemetry, for any period
src/scorecard/builder.py         Scorecard: SLA results, vendor vs. measured, credits, severity log, CAPs
src/scorecard/app_support.py     App logic: what-if overrides, pipeline runner, display tables
app/streamlit_app.py             Interactive app (Streamlit; runs in the browser via stlite)
src/scorecard/synthetic/         Synthetic GB200 site data generator
scripts/render_sla.py            Generates docs/SLA.md from the YAML
scripts/generate_data.py         Generates the synthetic dataset
scripts/run_engine.py            Runs the engine and writes reports/
scripts/build_scorecard.py       Builds the scorecard and writes reports/
scripts/build_site.py            Builds the static GitHub Pages site
templates/sla.md.j2              Document template
docs/SLA.md                      Generated SLA (do not edit by hand)
docs/DATA_MODEL.md               What each data file represents
docs/PROJECT_GUIDE.md            How the project fits together and how to change it
docs/DEPLOY_AWS.md               Hosting on AWS: S3, EC2, and production architecture
docs/images/                     Screenshots used in this README
data/sample/                     Committed synthetic dataset (4 weeks)
reports/                         Generated: scorecard.md, discrepancy_report.md, and their JSON
tests/                           Pytest suite
```

New to the code? Start with [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md).
