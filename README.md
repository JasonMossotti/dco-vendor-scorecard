# DCO Vendor Scorecard

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
| Synthetic GB200 NVL72 site data generator | Next |
| Connectors and discrepancy engine | Planned |
| Weekly scorecard | Planned |
| Interactive demo (GitHub Pages) | Planned |

## SLA as code

The SLA lives in one YAML file. The human-readable contract is generated from it, and the scoring engine reads its thresholds from it, so the contract and the code can never disagree. CI fails if the document is out of date.

```bash
pip install -r requirements.txt
python scripts/render_sla.py     # validate the SLA and regenerate docs/SLA.md
pytest -q                        # run the test suite
```

Highlights of the SLA design:

- **Telemetry of Record:** repair clocks start at the first machine-detected fault, not when a ticket is opened.
- **"Fixed" means validated:** clocks stop only when the component passes its return-to-service checks (diagnostics, NVLink health, leak hold, burn-in).
- **Record Integrity service level:** credits apply when vendor records do not reconcile with telemetry (e.g., a part swap claimed but the serial number never changed).
- **Internal breach severity index (S1 to S4):** combines how late an incident was with how many GPU-hours were lost, plus aggravators like repeat failures or safety events.

## Project layout

```
sla/vendor_sla.yaml        Single source of truth for the SLA
src/scorecard/sla_model.py Load, validate, credit math, severity classification
scripts/render_sla.py      Generates docs/SLA.md from the YAML
templates/sla.md.j2        Document template
docs/SLA.md                Generated SLA (do not edit by hand)
tests/                     Pytest suite
```
