# DCO Vendor Scorecard

[![CI](https://github.com/JasonMossotti/dco-vendor-scorecard/actions/workflows/ci.yml/badge.svg)](https://github.com/JasonMossotti/dco-vendor-scorecard/actions/workflows/ci.yml)

**Vendor performance and repair-verification scorecard for partner-operated GPU data center sites.**

**▶ [Open the interactive demo](https://jasonmossotti.github.io/dco-vendor-scorecard/)** (runs entirely in your browser; first load takes 20 to 40 seconds)

> Portfolio demonstration. All data, parties, sites, and commercial terms are synthetic and fictional. Not affiliated with, or based on internal information from, any real company.

![Scorecard overview: vendor reported vs. measured from telemetry](docs/images/overview.png)

**In 30 seconds:** a GPU site vendor's weekly reports say every SLA was met. This project rebuilds every incident from hardware telemetry (GPU faults, BMC inventory, fabric counters, badge access) and finds 4 Minimum Service Level Defaults, $188,700 in credits, and 18 places where the vendor's records do not match what the hardware recorded, each with evidence, a severity, and a corrective action. The contract itself is code, so changing a target in the SLA changes every result.

## The idea

At a partner-operated site, the vendor does the hands-on work and the site lead owns the outcome. The core principle of this project: **verify vendor performance with independent telemetry, not vendor self-reporting.** The scorecard reconciles what the vendor's tickets say against what the hardware itself reports (GPU telemetry, BMC inventory, fabric counters, badge access), then scores the result against a contractual SLA.

## Status

| Component | Status |
|---|---|
| SLA as code (`sla/common.yaml` + `sla/it_partner.yaml`) | Done |
| Generated IT partner SLA ([`docs/sla/IT_PARTNER_SLA.md`](docs/sla/IT_PARTNER_SLA.md)) | Done |
| Landlord SLA ([`docs/sla/LANDLORD_SLA.md`](docs/sla/LANDLORD_SLA.md)) and Interface Agreement ([`docs/sla/INTERFACE_AGREEMENT.md`](docs/sla/INTERFACE_AGREEMENT.md)) | Done, tested |
| Synthetic facility data: UPS, busway, generators, CDUs, BMS, leak, VESDA, Landlord records ([`docs/DATA_MODEL.md`](docs/DATA_MODEL.md#facility-landlord-data)) | Done, tested |
| Landlord engine and scorecard ([`reports/landlord_scorecard.md`](reports/landlord_scorecard.md)), cross-partner attribution ([`reports/attribution_report.md`](reports/attribution_report.md), [`reports/site_summary.md`](reports/site_summary.md)) | Done, tested |
| SLA model: validation, credits, breach severity | Done, tested |
| Synthetic GB200 NVL72 site data generator ([`docs/DATA_MODEL.md`](docs/DATA_MODEL.md)) | Done, tested |
| Connectors and discrepancy engine ([`reports/discrepancy_report.md`](reports/discrepancy_report.md)) | Done, tested |
| Weekly scorecard ([`reports/scorecard.md`](reports/scorecard.md)) | Done, tested |
| Interactive demo ([live](https://jasonmossotti.github.io/dco-vendor-scorecard/)) | Done, tested |
| Site model and drawings ([`docs/site/SITE.md`](docs/site/SITE.md)) | Done, tested |

## The site

Site AUS-1 is a fictional AI data center in Central Texas, run the way many AI companies run capacity: the Customer leases the halls from a wholesale owner-operator (the Landlord, which runs the building, power, and cooling) and contracts a separate IT partner for the data hall work. The site is built from real, interoperable equipment: Schneider Electric Galaxy UPS and EcoStruxure monitoring, CoolIT CHx2000 CDUs, Vertiv Liebert thermal walls and free-cooling chillers, Caterpillar C175-16 generators, VESDA aspirating smoke detection, TraceTek leak detection, NVIDIA InfiniBand, and an Eaton MVSST feeding an 800 VDC pilot hall. Three halls: Hall A in production (32 x GB200 NVL72), Hall B in deployment (32 x GB300 NVL72), and Hall C planned as the 800 VDC pilot.

The site is code too. [`site/site.yaml`](site/site.yaml) lists every product with its rating, management interfaces, and source documentation; the model expands it into named equipment, traces each rack's power and cooling paths, and runs 25 capacity checks (UPS 4-make-3, CDU N+1, generators N+1, chillers at a 43 C design day). The site refuses to load if any check fails, and the drawing set is generated from the same file. See [`docs/site/SITE.md`](docs/site/SITE.md).

![Hall A floor plan](docs/site/A-201_hall_a_plan.svg)

```bash
python scripts/render_site.py    # validate the site model and regenerate docs/site/
```

## SLA as code

The SLA lives in YAML. Terms every partner shares (Telemetry of Record measurement, excused events, corrective action, governance, security, EHS, and the severity framework) are in `sla/common.yaml`; each partner's service levels, credits, and finding types are in its own file that extends the common terms: `sla/it_partner.yaml` for Ridgeline (IT) and `sla/ot_partner.yaml` for Caprock (the Landlord). `sla/interface_agreement.yaml` joins them: demarcation points (power at the busway tap-off output, liquid cooling at the rack manifold isolation valves), one break-fix ownership matrix with exactly one Accountable party per component, fault attribution by walking each rack's power and cooling paths in the site model, joint incident command, and the Customer's negotiated read-only access to facility telemetry. A partner file may add terms but never override a common one, so no contract can quietly weaken a site-wide standard. Each partner's contract is generated as a self-contained document, and the scoring engine reads its thresholds from the same files, so the contract and the code can never disagree. CI fails if the document is out of date.

```bash
pip install -r requirements.txt
python scripts/render_sla.py     # validate the SLA and regenerate docs/sla/IT_PARTNER_SLA.md
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
- **EHS for every vendor:** site-wide safety terms in `sla/common.yaml` (OSHA 1910/1926/1904, NFPA 70E-2027, 70B, 855, 110, 72, 51B), 12 site safety rules including energized-work permits with the 70E second person, battery and DC work, and a Central Texas heat plan, and three violation classes. EHS Credits apply only to violations confirmed by independent investigation, sit outside the monthly cap, are never earned back, and are never based on reported injuries or near misses; self-reporting halves a credit and concealment doubles it.
- **Internal breach severity index (S1 to S4):** combines how late an incident was with how many GPU-hours were lost, plus aggravators like repeat failures or safety events.

## Synthetic site data

`scripts/generate_data.py` simulates a fictional GB200 NVL72 site for four weeks and writes two views of the same events: what the **hardware and Customer systems** recorded (GPU XID events, BMC inventory and alarms, fabric events, CDU alarms, scheduler states, validation health checks, badge access) and what the **vendor** reported (tickets, roster, spares ledger, deployment milestones, weekly self-report).

It then plants 11 types of realistic discrepancies, such as a repair ticket claiming a part swap the BMC inventory never saw, or a technician "on site" before badging into the hall, and writes an answer key so the engine's detection rate can be measured.

The committed sample in [`data/sample/`](data/sample) covers 4 weeks and 17 planted discrepancies across 11 types. In it, the vendor's self-report shows 100% across the board; the telemetry does not agree. See [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) for every file and discrepancy type.

## The scorecard: vendor reported vs. measured

`scripts/build_scorecard.py` measures every service level from telemetry and puts it beside the vendor's own weekly report. From the committed sample ([full scorecard](reports/scorecard.md)):

| Service level | Vendor reported | Measured from telemetry |
|---|:-:|:-:|
| P2 restoration within 8 hours | 100% | 92.3% |
| First-time fix rate | 100% | 90.1% |
| Validated return to service | 100% | 97.2% (Minimum default) |
| Record integrity | not reported | 82.4% (Minimum default) |

The vendor's weekly notes said all SLAs were met or showed only minor exceptions. Measured, the period has 4 Minimum Service Level Defaults, $188,700 in Service Level Credits (inside the $222,000 monthly cap), and 17 corrective action plans drafted automatically with owners and due dates. Fleet availability, by contrast, is 99.93% either way, which is why the scorecard measures each incident rather than trusting the average.

`build_scorecard(sla, result)` is a pure function of the SLA and the data. A contract amendment is a one-line change to the YAML, and rerunning shows its effect on breaches, credits, and corrective actions from the same telemetry.

## The Landlord scorecard

`scripts/run_landlord.py` holds Caprock, the Landlord, to its SLA the same way: it rebuilds every facility event from device telemetry the Customer reads under the Interface Agreement (UPS management cards, busway monitors, generator controllers, CDU Redfish, leak and VESDA controllers, the BMS, and badge entries), compares that with the Landlord's work orders and maintenance records, and scores the result. On the committed sample the Landlord reported every service level met; measured, there are 4 Minimum defaults (rack power availability, evidence-verified maintenance, work under an approved MOP, record integrity) and $106,200 in credits against rent ([Landlord scorecard](reports/landlord_scorecard.md), [discrepancy report](reports/landlord_discrepancy_report.md)).

Examples of what it catches: a monthly generator test recorded as "Pass at 40% load" while the generator controller shows it ran unloaded (NFPA 110 needs 30% for 30 minutes), maintenance closed by an engineer who never badged into that room, a BMS override left on for two days with no change record, and a work order that blames the tenant's whip for a power loss the busway monitor shows happening upstream. It finds all 8 planted Landlord discrepancies on the sample and **480 of 480 across 60 generated months with 0 false positives**.

### When one partner's failure lands on the other's scorecard

In the sample month the Landlord, doing planned work on one side of rack A07's power, opens the other side's tap-off by mistake. The rack goes dark for more than three hours, and the IT partner's telemetry shows 72 GPUs down. The Customer's telemetry decides who owns it: both feeds were out at the tap-offs, on the Landlord's side of the demarcation, so the Interface Agreement attributes the outage to the Landlord (FA-1) and starts the IT partner's clock only at the Landlord's handoff (FA-3). The IT partner's headline stays at 4 defaults and $188,700; scored without attribution, it would show 5 defaults and $222,000 for hours that were not its fault. The Landlord takes a rack power availability default instead, and the wrong-breaker operation is flagged as critical work with no approved MOP ([site summary](reports/site_summary.md)). Across 60 generated months, each with such an outage, the IT engine still finds 1,020 of 1,020 with 0 false positives.

## Toward live data: the read-only collector

`scripts/collect.py` reads real facility equipment and writes the same files the synthetic generator writes, so the engines, scorecards, reports, and app run on live data without changes. The dataset contract in [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) has two producers: synthetic and live.

- **Four protocols:** Redfish (CDUs, DMTF `ThermalEquipment` schema), Modbus TCP (generator controllers, busway monitors, leak controllers), SNMPv3 with authentication and AES privacy (UPS management cards, PowerNet MIB `upsBasicOutputStatus`), and BACnet/IP (BMS points, with overrides read from the priority array).
- **Read-only by construction:** the collector issues only Redfish GET and Modbus read requests (function codes 3 and 4). A test scans the collector's code and fails on any write-capable call, and the simulators record every request to prove it.
- **Tested against device simulators** in CI: a Redfish server with authentication, pymodbus's Modbus server, a pysnmp SNMPv3 agent, and a bacpypes3 BACnet device. End-to-end tests drive a simulated CDU pump failure and a BMS operator override through the collector into the unchanged Landlord engine. [`docs/LIVE_READINESS.md`](docs/LIVE_READINESS.md) lists what is proven and what a real deployment still needs.
- **Credentials stay out of the repository** (named environment variables only), register maps are site configuration verified at commissioning ([example](config/collector.example.yaml)), and a device that stops answering becomes a measured feed gap with backoff, not a silent one.

```bash
pip install -r requirements-live.txt
python scripts/collect.py --config /secure/collector.yaml --out data/live --once
```

## Discrepancy engine

`scripts/run_engine.py` reads the telemetry and vendor records through a connector layer, rebuilds every incident from telemetry alone using the SLA's ticket handling rules, and reports each place the vendor's records do not reconcile, with the exact evidence, an S1 to S4 severity, and the corrective action defined in the SLA.

**Results:** on the committed sample it finds all 17 planted discrepancies with no false positives (see the [discrepancy report](reports/discrepancy_report.md)). Across 60 freshly generated months it detected **1,020 of 1,020** with **0 false positives**. The engine cannot read the answer key: the connector blocks it, and a test deletes the answer key and confirms the findings do not change.

Production integration is a matter of swapping connectors: each data source (GPU telemetry, BMC Redfish inventory, fabric managers, scheduler, badge system, vendor ITSM) sits behind one interface in [`src/scorecard/connectors.py`](src/scorecard/connectors.py).

```bash
python scripts/run_engine.py                    # data/sample -> reports/
python scripts/run_engine.py --robustness 20    # also test 20 freshly generated months
```

## Interactive demo

The [demo](https://jasonmossotti.github.io/dco-vendor-scorecard/) runs the whole pipeline in the browser (Python via WebAssembly, no server). You can:

- Open on the **site summary**: both partners side by side, the outage that crossed the demarcation, and what attribution changed for the IT partner.
- Switch views to the **IT partner (Ridgeline)** or **Landlord (Caprock)** scorecard: reported vs. measured, service levels, findings with evidence, and (for the Landlord) every facility event with its attribution.
- Switch between the committed sample, the latest 4 weeks (regenerated every Monday by GitHub Actions), or a brand-new random month.
- Drill into each finding's evidence, the corrective action plans, and every incident.

<img src="docs/images/finding.png" alt="A finding with its evidence: a compute tray returned to service with no validation checks recorded" width="680">

Run it locally with `pip install -r requirements-app.txt` and `streamlit run app/streamlit_app.py`. To host it on AWS (S3, EC2, or a production-shaped architecture), see [docs/DEPLOY_AWS.md](docs/DEPLOY_AWS.md).

## Project layout

```
sla/common.yaml                  Terms shared by every partner SLA (add-only merge)
sla/it_partner.yaml              IT partner SLA: service levels, credits, finding types
sla/ot_partner.yaml              Landlord SLA: power, cooling, maintenance, response, credits against rent
sla/interface_agreement.yaml     Demarcation, ownership matrix, fault attribution, joint operations, data access
site/site.yaml                   Single source of truth for the site: equipment, topology, monitoring
src/scorecard/site_model.py      Site expansion, power and cooling paths, capacity checks
src/scorecard/site_drawings.py   Schematic drawing set (SVG) generated from the site model
scripts/render_site.py           Generates docs/site/ (SITE.md and drawings)
config/synthetic.yaml            Generator settings: fault rates, vendor behavior, planted discrepancies
src/scorecard/sla_model.py       Load, validate, credit math, severity classification
src/scorecard/measurement.py     Ticket handling rules (TR-1 to TR-6) as the reference implementation
src/scorecard/connectors.py      Data access layer (one interface per source; answer key blocked)
src/scorecard/engine/            Discrepancy engine: context, 11 detectors, evaluation, reports
src/scorecard/kpi.py             Service level measurement from telemetry, for any period
src/scorecard/builder.py         Scorecard: SLA results, vendor vs. measured, credits, severity log, CAPs
src/scorecard/app_support.py     App logic: pipeline runner, display tables
app/streamlit_app.py             Interactive app (Streamlit; runs in the browser via stlite)
src/scorecard/synthetic/         Synthetic GB200 site data generator
scripts/render_sla.py            Generates docs/sla/IT_PARTNER_SLA.md from the YAML
scripts/generate_data.py         Generates the synthetic dataset
scripts/run_engine.py            Runs the engine and writes reports/
scripts/run_landlord.py          Runs the Landlord engine; writes the Landlord scorecard, discrepancy, and attribution reports
scripts/collect.py               Read-only live collector (Redfish, Modbus, SNMPv3, BACnet/IP) writing the dataset contract
src/scorecard/live/              Collector, adapters, dataset writer (optional: requirements-live.txt)
src/scorecard/engine/landlord.py Landlord context, detectors, attribution, measurement, scorecard
scripts/build_scorecard.py       Builds the scorecard and writes reports/
scripts/build_site.py            Builds the static GitHub Pages site
templates/sla.md.j2              Document template
docs/sla/                        Generated contracts: IT partner SLA, Landlord SLA, Interface Agreement (do not edit by hand)
docs/DATA_MODEL.md               What each data file represents
docs/PROJECT_GUIDE.md            How the project fits together and how to change it
docs/DEPLOY_AWS.md               Hosting on AWS: S3, EC2, and production architecture
docs/images/                     Screenshots used in this README
data/sample/                     Committed synthetic dataset (4 weeks)
reports/                         Generated: scorecard.md, discrepancy_report.md, and their JSON
tests/                           Pytest suite
```

New to the code? Start with [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md).
