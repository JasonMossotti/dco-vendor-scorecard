# DCO Vendor Scorecard

[![CI](https://github.com/RexFeral/dco-vendor-scorecard/actions/workflows/ci.yml/badge.svg)](https://github.com/RexFeral/dco-vendor-scorecard/actions/workflows/ci.yml)

**Vendor performance and repair-verification scorecard for partner-operated GPU data center sites.**

> Portfolio demonstration. All data, parties, sites, and commercial terms are synthetic and fictional. Not affiliated with, or based on internal information from, any real company.

## The idea

At a partner-operated site, the vendor does the hands-on work and the site lead owns the outcome. The core principle of this project: **verify vendor performance with independent telemetry, not vendor self-reporting.** The scorecard reconciles what the vendor's tickets say against what the hardware itself reports (GPU telemetry, BMC inventory, fabric counters, badge access), then scores the result against a contractual SLA.

## Status

| Component | Status |
|---|---|
| SLA as code (`sla/vendor_sla.yaml`) | Done |
| Generated SLA document ([`docs/SLA.md`](docs/SLA.md)) | Done |
| SLA model: validation, credits, breach severity | Done, tested |
| Synthetic GB200 NVL72 site data generator ([`docs/DATA_MODEL.md`](docs/DATA_MODEL.md)) | Done, tested |
| Connectors and discrepancy engine | Next |
| Weekly scorecard | Planned |
| Interactive demo (GitHub Pages) | Planned |

## SLA as code

The SLA lives in one YAML file. The human-readable contract is generated from it, and the scoring engine reads its thresholds from it, so the contract and the code can never disagree. CI fails if the document is out of date.

```bash
pip install -r requirements.txt
python scripts/render_sla.py     # validate the SLA and regenerate docs/SLA.md
python scripts/generate_data.py  # regenerate the synthetic sample in data/sample
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

## Project layout

```
sla/vendor_sla.yaml              Single source of truth for the SLA
config/synthetic.yaml            Generator settings: fault rates, vendor behavior, planted discrepancies
src/scorecard/sla_model.py       Load, validate, credit math, severity classification
src/scorecard/measurement.py     Ticket handling rules (TR-1 to TR-6) as the reference implementation
src/scorecard/synthetic/         Synthetic GB200 site data generator
scripts/render_sla.py            Generates docs/SLA.md from the YAML
scripts/generate_data.py         Generates the synthetic dataset
templates/sla.md.j2              Document template
docs/SLA.md                      Generated SLA (do not edit by hand)
docs/DATA_MODEL.md               What each data file represents
data/sample/                     Committed synthetic dataset (4 weeks)
tests/                           Pytest suite
```
