# Synthetic Data Model

> All data is synthetic and fictional: sites, people, serial numbers, and events are generated. Record formats are simplified versions of what the named classes of systems produce. They are not copies of any vendor's real schema.

## Two views of one reality

The generator simulates a fictional GB200 NVL72 site (Hall A in production with 32 racks and 2,304 GPUs; Hall B under deployment) and records each event twice:

1. **Telemetry of Record.** What the hardware and Customer systems observed. Under the SLA, this is authoritative for timing, inventory, and health.
2. **Vendor records.** What the Supplier reports. Normally consistent with telemetry, except the vendor's clock starts when a ticket is opened rather than when the fault occurred.

Then it plants realistic discrepancies between the two views. The answer key in `ground_truth/` lets us measure how many the discrepancy engine catches. **The engine never reads `ground_truth/`.**

The dataset has these committed layers: the [sample month](#files) and its [facility data](#facility-landlord-data) (`data/sample/`), [failure history](#failure-history-datahistory), [changes](#change-layer-datachanges), [security](#security-layer-datasecurity), [GPU health](#gpu-health-datagpu_health), [telemetry](#telemetry-datatelemetry), [energy meters](#energy-meters-dataenergy), [incident comms](#incident-comms-dataincident_comms), [deployment program](#deployment-program-datadeployments), [Hall C readiness](#hall-c-readiness-datareadiness), [asset register](#asset-register-dataassets), and [fire protection](#fire-protection-datafire). Each layer after the sample is derived from finished records with its own random stream and never writes the layers it reads.

## Files

| File | Mimics | Key fields | Used to verify |
|---|---|---|---|
| `site/topology.json` | Asset inventory baseline | racks, trays, serials, firmware, CDU mapping | Starting serial and firmware state |
| `telemetry/dcgm_xid_events.jsonl` | GPU driver XID events via DCGM | timestamp, host, xid, tray_serial | Fault start (T0), recurrences |
| `telemetry/redfish_events.jsonl` | BMC alerts (Redfish-style) | resource, event_type (LeakDetected, PowerSupplyFailed) | Leak and power fault timing |
| `telemetry/redfish_inventory_changes.jsonl` | BMC inventory polling | resource, property (SerialNumber, FirmwareVersion), old/new | Part swaps actually happened; unapproved firmware changes |
| `telemetry/nmx_events.jsonl` | NVLink fabric management | rack, unit, state | Switch tray failure and recovery |
| `telemetry/ufm_port_events.jsonl` | InfiniBand fabric manager | switch, port, event (link_down, symbol_errors) | Link faults, and whether errors stopped after repair |
| `telemetry/bms_cdu_events.jsonl` | Building management system | cdu, alarm, state | Cooling faults and alarm clear times |
| `telemetry/health_checks.jsonl` | Cluster health-check platform | target, check, result, times | Return-to-service validation actually ran |
| `telemetry/scheduler_node_states.jsonl` | Workload scheduler | node, state (drain/idle) | When capacity was lost and returned |
| `access/badge_events.csv` | Access control system | person_id, door, direction | Staffing presence; technician on site |
| `customer/cab_changes.json` | Customer change management | rack, window_start, window_end | Whether changes were approved |
| `customer/deployment_plan.csv` | Customer deployment plan | rack, planned_receipt, committed_handoff | Milestone commitments. Only the first 14 Hall B racks arrive in the sample month (`deployment.racks_received_in_window`); the OEM shipment for the rest is late, so racks from B15 on have a planned receipt but no milestones yet |
| `vendor/tickets.json` | Vendor ticketing system (ServiceNow-style) | opened_at, work_notes, parts_used, resolved_at | The vendor's account of each incident |
| `vendor/personnel.csv` | Vendor staff list | person_id, role, crew, badge_id | Joins badges to people |
| `vendor/roster.csv` | Vendor shift roster | shift_start, person_id, status | Committed staffing |
| `vendor/spares_ledger.csv` | Vendor spares system | transaction, fru, qty, balance_after | Parts issued against tickets |
| `vendor/spares_cycle_counts.csv` | Weekly physical counts | system_qty, counted_qty | Ledger accuracy |
| `vendor/rma_shipments.csv` | RMA logistics | serial, removed_at, shipped_at | RMA turnaround (KM-08) |
| `vendor/deployment_milestones.csv` | Vendor deployment tracker | rack, milestone, reported_complete_at | Deployment adherence (CSL-09) |
| `vendor/self_reported_weekly.json` | Vendor weekly summary | availability, restore %, staffing % | What the vendor claims |
| `ground_truth/incidents.json` | Answer key | true timeline per incident | Evaluation only |
| `ground_truth/planted_discrepancies.json` | Answer key | type, ticket, evidence, sla_refs | Evaluation only |

## Planted discrepancy types

| Type | What happened | How it is detectable | SLA reference |
|---|---|---|---|
| `phantom_fix` | Tray reseated and ticket closed; the same fault family recurs 1 to 4 days later | New XID of the same family on the same host after the 24-hour stability window but within 7 days (TR-5 linked recurrence) | CSL-06, CSL-08 |
| `ticket_split` | Tray refaults minutes after return to service; vendor opens a new ticket so the clock restarts | Refault within 60 minutes of Validated RTS (TR-1). Each vendor ticket is on time; measured continuously from the first T0 it breaches | TR-1, TR-6, CSL-04, CSL-11 |
| `unverified_swap` | Ticket claims a tray replacement with a new serial | That serial never appears in BMC inventory; the old serial keeps reporting | CSL-11 |
| `skipped_validation` | Node returned to service minutes after repair | No validation health checks between repair and return; ticket still claims validation | CSL-07, CSL-11 |
| `clock_shift` | Ticket opened about 2 hours after the fault | XID precedes ticket open; on time by vendor clock, late by telemetry | CSL-04, CSL-11 |
| `ghost_engagement` | Work note says "on site" within target | Assigned technician's hall badge-in came later | CSL-02 / KM-01, CSL-11 |
| `wrong_end_optic` | Switch-side optic replaced; ticket closed | Symbol errors continue on the same port until the host side is replaced. Under TR-2 the errors reopen the original ticket, so the vendor's second ticket is also a split | CSL-06, CSL-08, TR-2 |
| `lemon_unit` | One tray fails 3 times in 30 days, reseated each time | Three tickets on one unit, none escalated for RMA | KM-09, CSL-08 |
| `staffing_gap` | Two rostered technicians never showed up | Roster lists them; no badge-in during the shift | CSL-10 |
| `spares_drift` | Part used but never issued from the ledger | Ticket and inventory show a swap; ledger has no issue; cycle count short | KM-06, KM-07, CSL-11 |
| `unauthorized_change` | Firmware changed on a whole rack overnight | Inventory shows firmware changes; no approved change record covers them | KM-10 |

Each planted scenario maps to one Ticket Handling rule (SLA Section 7.6): refaults inside 60 minutes are `ticket_split` (TR-1), refaults after the stability window are `phantom_fix` (TR-5), and continued link errors are `wrong_end_optic` (TR-2).

## Honest behavior (not planted)

These are real performance outcomes the scorecard should report, not discrepancies:

- **Natural SLA misses:** some technicians arrive late, and some faults take longer to diagnose.
- **Systematic vendor clock offset:** vendor durations start at ticket open, a few minutes after the true fault time. This always flatters the vendor slightly; the clock-shift anomaly is the extreme version.
- **Deployment slips:** some Hall B racks miss their committed handoff date.

## Simplifications

- Incidents occur only in Hall A (production). Hall B produces deployment data only.
- Each compute tray is one scheduler node.
- Base incidents never hit the same unit twice, so every repeat failure in the data is a planted scenario. This keeps the answer key unambiguous.
- Incidents start at least 36 hours before the window ends, so every ticket is closed within the window.
- Fault rates are illustrative, tuned for roughly 20 tickets per week in one production hall.

## Facility (Landlord) data

`src/scorecard/synthetic/facility.py` generates the Landlord's month from its own random stream (seed plus `:facility`), so it never changes the IT data. It covers Halls A and B, the generator and chiller yards, and the switchgear. Tuning is under `facility:` in `config/synthetic.yaml`.

### What the devices recorded (read by the Customer under the Interface Agreement)

| File | Source | Contents |
|---|---|---|
| `facility/ups_nmc_events.jsonl` | UPS network management cards (SNMPv3) | Module faults and repairs; output state changes using PowerNet MIB `upsBasicOutputStatus` values (`onLine`, `onBattery`, `switchedBypass`, ...) |
| `facility/ups_status.jsonl` | Same, polled every 4 hours | `upsBasicOutputStatus` per UPS; load percent for the mechanical UPSs only (the IT UPSs' load follows the racks and is in `data/telemetry/power/`) |
| `facility/busway_cpm_events.jsonl` | Starline Critical Power Monitors | Feed lost and restored per busway (voltage), tap-off breaker operations |
| `facility/emcp_readings.jsonl` | Generator controllers (EMCP 4.4) | One reading a minute while running a monthly test: engine state, kW, percent of rated kW (a utility outage's readings follow the site load and are in `data/telemetry/power/`) |
| `facility/cdu_redfish_events.jsonl` | CDU controllers (Redfish) | Changes on `/redfish/v1/ThermalEquipment/CDUs/{id}` resources: pump `Status.Health` and `Status.State`, `PumpRedundancy` health |
| `facility/bms_events.jsonl` | BMS (EcoStruxure Building Operation export) | Alarms with acknowledgments (user) and clears; overrides and alarm inhibits with the change reference (or none) |
| `facility/epms_events.jsonl` | Power monitoring | Utility trips, generator bus, breaker trips and closes |
| `facility/leak_events.jsonl` | TraceTek TTDM-128 | Leak alarms with circuit and distance along the cable, and returns to normal |
| `facility/vesda_events.jsonl` | VESDA high-level interface | Alarm levels (Alert, Action, Fire 1, Fire 2), faults, isolates |
| `access/landlord_badge_events.csv` | Access control | Landlord engineers' shift entries and equipment-room entries. These readers record entries only, so two entries in a row mean the person left and came back; `access/badge_events.csv` records entries and exits |
| `customer/landlord_mop_approvals.json` | Customer change board | Approved methods of procedure with assets and windows |

**Point-name provenance.** The PowerNet MIB output-state names and the Redfish `ThermalEquipment`, `CoolantConnector`, and pump status names follow the published MIB and DMTF schemas. VESDA alarm levels and the TraceTek distance-located leak alarm follow the manufacturers' documentation. EMCP 4.4 values use descriptive parameter names (engine operating state, total kW, percent of rated kW) rather than register numbers, and BMS and EPMS events use descriptive text, because those exports are site-configured.

### What the Landlord recorded

| File | Contents |
|---|---|
| `landlord/work_orders.json` | Work orders: priority, fault class, unit, acknowledged, engaged (as claimed), restored (as claimed), MOP reference, the party the Landlord attributes the fault to, notes |
| `landlord/pm_records.csv` | Maintenance tasks with completion time, engineer, result, and claimed evidence |
| `landlord/roster.csv` | Engineers by shift |
| `landlord/self_reported_weekly.json` | The Landlord's weekly self-report (every service level met) |

### Facility scenarios in the sample month

One utility outage (UPS ride-through on battery for about 12 seconds, 7 generators carry the site, closed-transition retransfer), 7 monthly generator tests, maintenance on CDUs, UPS, chillers, VESDA, and switchgear, 3 planned tap-off energizations for Hall B, and faults across the Landlord rule cards (CDU pump, UPS module, chiller, thermal wall, busway feed, building leak, VESDA fault).

### A rack outage that crosses the demarcation

During planned A-side tap-off work on a Hall A rack (under a MOP), the Landlord opens the B-side tap-off by mistake. The rack loses both feeds; the B tap-off unit fails on reclose and is replaced, so the rack is dark for 3 to 4 hours. The busway monitors record every tap-off breaker operation with the rack, and the Landlord's work order is a P1 for `Rack Axx`. On the IT side (generated from its own random stream, so no existing IT record changes), all 18 nodes go `down` with reason `NotResponding (rack input power lost)`, an IT technician badges in after the handoff and out after return to service, the rack passes the `Rack return to service` checks, and an IT ticket in category `rack_facility` records the work with its clock starting at the handoff (Interface Agreement FA-3). The B-side opening is in the Landlord answer key as `critical_work_no_mop`.

### Planted Landlord discrepancies

Answer key: `ground_truth/facility_planted_discrepancies.json` (blocked from the engine).

| Type | What the records say | What the telemetry shows |
|---|---|---|
| `gen_test_no_load` | Monthly test passed at 40% load | EMCP shows the engine ran unloaded |
| `pm_without_evidence` | Maintenance completed and signed off | No badge into the equipment's room and no device signal |
| `bms_override_unrecorded` | Nothing | An override or alarm inhibit with no change reference, held for a day or more |
| `alarm_acked_no_dispatch` | Engineer attended and reset the unit | Acknowledged in the BMS; nobody badged in before it cleared |
| `critical_work_no_mop` | Routine tap-off work | Breaker operated with no approved MOP |
| `landlord_clock_shift` | Redundancy restored at time X | Redfish shows redundancy restored hours later |
| `attribution_contradicted` | Tenant whip fault; Landlord not responsible | Busway monitor shows the feed lost at the busway, upstream of the tap-off |

Planted "nobody was there" records are placed after all other activity, so no coincidental badge can make them look evidenced. `python scripts/check_facility_data.py` runs the evidence tests against 60 freshly generated months.

## Failure history (data/history/)

The 26 weeks before the sample month for Hall A, written by `scripts/generate_history.py` from its own random stream and read only by the failure pattern review. It uses the committed fleet (`data/sample/site/topology.json`); the last tray installed in each slot is the serial the sample month starts with.

| File | What it represents |
|---|---|
| `telemetry/dcgm_xid_events.jsonl` | GPU XID events by host and tray serial |
| `telemetry/dcgm_thermal_events.jsonl` | GPU clock events with reason HW Thermal Slowdown |
| `telemetry/ufm_port_events.jsonl` | Link down and up, and transceiver DOM alarms that name the failed module's serial |
| `telemetry/redfish_events.jsonl` | PSU health changes |
| `facility/cdu_secondary.jsonl` | CDU secondary supply and return temperature and flow, 4-hour averages (Customer read-only Redfish poll) |
| `facility/cdu_setpoints.json` | The BMS supply setpoint and high-supply alarm (read-only configuration export) |
| `landlord/pm_records.csv` | Quarterly CDU filter changes |
| `customer/optic_inventory.csv` | Every optic module installed during the window: location, end, serial, lot, installed, removed |
| `vendor/tickets.json` | The IT Partner's tickets (fix applied, parts with serials); no work notes and no names |
| `ground_truth/planted_patterns.json` | Answer key for scoring the review; the analysis never reads it |

Planted patterns (moved and resized on each robustness history): an optic lot that fails several times faster than the others; a CDU whose filter fouls so its supply creeps up but stays under the alarm, with GPU thermal slowdowns in the racks it serves until the next quarterly filter change; reseats of one XID that usually come back within 30 days; and a decoy rack with extra unrelated faults that must not be flagged. Tuning lives in `config/history.yaml`.

## Change layer (`data/changes/`)

Derived from `data/sample/` by `scripts/generate_changes.py` with its own random stream; the sample itself is never written.

| File | What it represents |
|---|---|
| `impact_declarations.json` | One structured impact declaration per approved change (Landlord MOPs and IT CAB changes): owner, assets, expected alarms per asset, worst severity, domains, redundancy reduced, window, grace. Derived from the change-type catalog in `config/change_alarms.yaml`; under Interface Agreement section 10 the partners file these themselves |
| `notification_log.json` | Each partner's delivery log: alarm (device, signal, time), channel (page, email, phone), recipient, sent time, and the change it names (empty today). Reflects the current SLAs: P1 paged, P2 one call or email, nothing on change scope |
| `ground_truth/change_alarm_key.json` | Answer key: the flags the check must raise (the natural rack outage in every month; planted cases and decoys in robustness months only) and planted notification failures. The check never reads it |
| `manifest.json` | Window, seed, source dataset, counts |

Planted only in generated robustness months (appended to that month's own files): the wrong CDU isolated during a filter change, an NVLink switch tray failure during tray firmware work, a tap-off opened before its window, a CDU pump left isolated past its window, and three decoys (a chiller alarm during a CDU change, a GPU error on a rack fed by a UPS under maintenance, a UPS back online inside the grace), plus one missing and one late P1 page.

## Security layer (`data/security/`)

Derived by `scripts/generate_security.py` from `data/sample/` with its own random stream (`{seed}:security`); the sample is never written. Settings in `config/security.yaml`. Escorts are drawn from the IT Partner's and the Landlord's existing hall badge-ins, and drives from the compute trays in the existing RMA shipments, so the new records line up with the old ones. The Customer's systems are the evidence; the Security Partner's records are the claims.

| File | What it represents |
|---|---|
| `guard_badges.csv` | Guard badge reads at the post readers (Customer access control, DS-BADGE) |
| `visitor_badges.csv` | Visitor badge reads at the hall readers (DS-BADGE) |
| `door_alarms.jsonl` | Access control door alarms (door held open and similar): priority, console acknowledgement, cleared time |
| `cameras.json` | The camera list: area, recorder, whether it covers a door (video system, DS-VMS) |
| `camera_events.jsonl` | Recording stopped and restored events per camera (DS-VMS) |
| `retention_audit.csv` | Daily check of the oldest recording held on each recorder (DS-VMS) |
| `leavers.csv` | Identity feed of people who left: separated and badge deactivated times (DS-IDM) |
| `tray_drives.csv` | The Redfish drive inventory of each compute tray that shipped under RMA: bay, drive serial, model (DS-REDFISH) |
| `access_reviews.csv` | Quarterly badge access reviews: due, completed, badges reviewed and removed |
| `guards.csv` | The Security Partner's guard list: badge, crew, state registration number |
| `post_log.csv` | The Security Partner's post log: each shift and post as reported staffed (DS-GUARD) |
| `tour_scans.csv` | Guard tour checkpoint scans: round, checkpoint, due, scanned (DS-GUARD) |
| `dispatch_log.json` | The Security Partner's alarm dispatch log: guard dispatched, on scene, closed, disposition (DS-GUARD) |
| `visits.csv` | The Security Partner's visitor log: request, company, badge, hall, escort, signed in and out (DS-VISIT) |
| `chain_of_custody.csv` | Drive handovers from the IT Partner to the Security Partner, by ticket (DS-COC) |
| `destruction_certificates.csv` | Media destruction certificates by drive serial: method, operator, witness (DS-COC) |
| `self_reported_weekly.json` | The Security Partner's weekly SLA summary (what it claims) |
| `ground_truth/security_planted.json` | Answer key: a post logged staffed with no badge-in, a door alarm closed with no guard at the door, a visitor in a hall without the escort, and a drive shipped with no destruction certificate. Each month also gets one decoy of each kind, which must not be flagged. The engine never reads it |
| `manifest.json` | Window, seed, source dataset, counts |

## GPU health (`data/gpu_health/`)

Derived by `scripts/generate_gpu_health.py` from `data/sample/` (topology, DCGM XID feed, scheduler states, tray replacements) with its own random stream (`{seed}:gpu-health`); the sample is never written. Settings in `config/gpu_health.yaml`. Modeled on public DCGM-style health checks and NVIDIA's public XID catalog. Every XID in `telemetry/dcgm_xid_events.jsonl` appears here at the same time on the same GPU.

| File | What it represents |
|---|---|
| `watches.jsonl` | Health watch results per GPU (subsystem, Warn or Fail, message, XID), opened and cleared. A watch clears when the scheduler returns the node to service or the tray is replaced |
| `gpu_counters.csv` | A daily snapshot for every GPU with a non-zero counter: corrected and uncorrected memory errors that day, remapped rows, remap pending, peak GPU and HBM temperatures |
| `thermal_episodes.jsonl` | Hardware thermal slowdown episodes per GPU |
| `cdu_hourly.csv` | CDU secondary supply temperature and flow per hour (mean, and the hour's worst) |
| `rack_daily.csv` | Per rack per day: trays reporting, peak GPU and HBM temperatures |
| `answer_key.json` | What was planted: memory errors that warn ahead, a GPU returned to service with a row remap still pending, a tray throttling with its CDU in band, CDU excursions (none in the sample), and decoys. The checks never read it |
| `manifest.json` | Window, source, counts |

## Telemetry (`data/telemetry/`)

Written by `scripts/generate_telemetry.py`, one layer per folder, each with its own random stream and settings file. Each layer runs on the finished month and writes beside the records it reads, never into them; nothing in `data/sample/` or any other layer is written, except that the same script rebuilds `data/energy/` between the GPU and CDU layers (see [Energy meters](#energy-meters-dataenergy)). The order is GPU, CDU (with the energy meters built around it), power, network, mechanical, management network, storage. Each folder holds a `manifest.json` (window, source, device list, counts, and an index of the windows).

Most layers publish in tiers. The committed tiers are hourly summaries, a `states.jsonl` of every state change with the record it matches, and `windows/` with one-minute samples around each event. The full one-minute or per-port series for the GPU, CDU, power, mechanical, and network layers are built into the git-ignored `build/telemetry/` (`gpu_hourly/`, `cdu_minutes/`, `power_minutes/`, `mechanical_minutes/`, `network_hourly/`); only their SHA-256 checksums and sizes are committed, in each manifest, and `scripts/build_site.py` publishes them. The management network and storage layers are committed in full.

### GPU (`data/telemetry/gpu/`)

Stream keys `{seed}:telemetry:gpu:<rack>` and related `{seed}:telemetry:*` keys per GPU; settings in `config/telemetry.yaml`. Read from `data/sample/` and `data/gpu_health/`. Every GPU (3,312) is sampled once a minute in the published format of NVIDIA's open-source DCGM exporter (`DCGM_FI_DEV_*` field names in the per-GPU tier), shaped to agree with the daily peaks, every XID, scheduler drains, rack power loss, thermal slowdown episodes, and Hall B power-on and handoff milestones.

| File | What it represents |
|---|---|
| `rack_hourly.csv` | Per rack per hour: GPUs reporting, samples, utilization, energy, peak GPU and HBM temperatures, minimum loaded SM clock, thermal and power violation time, XIDs, nodes drained |
| `gaps.jsonl` | Spans where a GPU or a whole tray reported nothing, with the reason |
| `windows/<host>_<start>.json` | One-minute samples for the four GPUs of a tray around each event |

### CDU (`data/telemetry/cdu/`)

Stream `{seed}:telemetry:cdu`; settings in `config/telemetry_cdu.yaml`. Read from `data/sample/`, `data/gpu_health/`, `data/energy/`, and the GPU telemetry. Every CDU (8) is read once a minute in the published DMTF Redfish schema for cooling units (CoolingUnit, primary and secondary CoolantConnectors, Pumps, Filter, Reservoir, LeakDetectors, EnvironmentMetrics), over the Customer's read-only account. No vendor's register map is implied.

| File | What it represents |
|---|---|
| `cdu_hourly.csv` | Per CDU per hour: secondary supply, return, flow, differential pressure, heat; primary supply, return, flow, valve; pump speeds, filter differential pressure, reservoir level, energy, leak minutes, minutes without pump redundancy |
| `states.jsonl` | Each Redfish property change (pump state, leak detector state, and others) at its minute, with the record it matches |
| `windows/<cdu>_<start>.json` | One-minute series around each event |

### Power (`data/telemetry/power/`)

Stream `{seed}:telemetry:power`; settings in `config/telemetry_power.yaml`. Read from `data/sample/`, `data/energy/`, and the GPU telemetry. One reading a minute per device, built from the bottom up: tap-offs and busway runs (plug-in and end-feed meters), IT and mechanical UPSs (SNMPv3, UPS-MIB and PowerNet-MIB point names), and generators (Modbus point names), in the manufacturers' published point maps. Each hall's UPS output equals the metered UPS output every hour.

| File | What it represents |
|---|---|
| `ups_hourly.csv` | Per UPS per hour: kind (IT or mechanical), output and input energy, load, amps, minimum battery charge, bypass minutes, battery seconds, power modules |
| `busway_hourly.csv` | Per busway run per hour: feeding UPS, energy, amps, voltage range, minutes without feed, enclosure temperature |
| `generator_hourly.csv` | Per generator per hour: run minutes, energy, peak kW and load, coolant temperature, fuel level, engine hours |
| `states.jsonl` | Each device state or breaker change at its minute, with the record it matches |
| `windows/<device>_<start>.json` | One-minute series around each event |

### Mechanical (`data/telemetry/mechanical/`)

Stream `{seed}:telemetry:mechanical`; settings in `config/telemetry_mechanical.yaml`. Read from `data/sample/`, `data/energy/`, and the CDU and power telemetry. Splits the energy meters into each machine, one reading a minute, under the point names Vertiv publishes for its iCOM controllers over BACnet (ASHRAE 135): 11 chillers, the facility water pumps and loop, 8 thermal walls, and 6 electrical-room CRAHs.

| File | What it represents |
|---|---|
| `chiller_hourly.csv` | Per chiller per hour: status, run, free-cooling, inhibit, BMS-off, and alarm minutes; energy, capacity, free-cooling and mechanical heat; water and ambient temperatures, flow, head pressure, fan speed |
| `pump_hourly.csv` | Per facility water pump per hour: run minutes, speed, frequency, energy, flow |
| `loop_hourly.csv` | The facility water loop per hour: supply, return, flow, differential pressure, heat, chillers running and needed |
| `air_hourly.csv` | Per thermal wall and CRAH per hour: supply and return air, fan speed and fans running, valve, chilled water in and out, flow, load, energy, alarm and inhibit minutes |
| `states.jsonl` | Each BMS point change (compressor trips, enable and fan overrides, free-cooling lockouts, fan failures, alarm inhibits) with the record it matches |
| `windows/<device>_<start>.json` | One-minute series around each event |

### Network (`data/telemetry/network/`)

Stream `{seed}:telemetry:network`; settings in `config/telemetry_network.yaml`. Read from `data/sample/` and the GPU telemetry. Every back-end InfiniBand link (3,312, one tray NIC to one leaf port by the generator's cabling rule) and every NVLink switch tray (414), under the published UFM Telemetry and IBTA PortCountersExtended names for the fabric and NMX-T names for the NVLink trays. Symbol errors and link drops are exactly the ones the fabric manager recorded; every optic fault on record has a physical signature at the end the records name.

| File | What it represents |
|---|---|
| `fabric_hourly.csv` | Per hall and rail per hour: leaves, links cabled and up, traffic, uplink traffic, utilization, symbol errors, link downs, module and ASIC temperatures, switch power |
| `nvlink_hourly.csv` | Per rack per hour: NVLink trays reporting, traffic, ASIC temperature, power, link downs |
| `states.jsonl` | Each port and tray state change, and the start and end of each optic signature, with the record it matches |
| `windows/<leaf>_<port>_<start>.json` | One-minute series around each fabric event |

### Management network (`data/telemetry/mgmt/`)

Stream `{seed}:telemetry:mgmt`; settings in `config/telemetry_mgmt.yaml`. Read from `data/sample/` and `site/site.yaml`. Every BMC (compute tray, NVLink switch tray, and power shelf controller: 2,240) answers a once-a-minute Redfish service-root poll over its rack's out-of-band switch, or does not, and only for a reason the records give or this layer plants. The rack and aggregation switches report IF-MIB port state and send SNMP linkDown, linkUp, and coldStart traps. All of it is committed.

| File | What it represents |
|---|---|
| `bmc_hourly.csv` | Per rack per hour: endpoints, endpoints polled and answering, failed polls |
| `poll_gaps.jsonl` | Each span an endpoint did not answer: endpoint, Redfish resource, from, to |
| `first_answer.json` | When each Hall B endpoint first answered |
| `switch_hourly.csv` | Per management switch per hour: minutes up, ports up, uplinks up, temperature, traffic |
| `traps.jsonl` | SNMP traps: linkDown, linkUp, coldStart, by switch and port |
| `collector.jsonl` | The Telemetry of Record collector's own log (poller stopped and restarted) |
| `console_ports.json` | Each console server's port map (port to device label) |
| `console_sessions.jsonl` | The IT Partner's console sessions: console, port, label, the prompt printed, opened and closed |
| `windows/<device or rack>_<start>.json` | One-minute endpoint, port, and switch state around each event |
| `answer_key.json` | Planted: an out-of-band switch down for hours with no ticket, a power shelf controller that stops answering during a passing validation check, late BMCs in a Hall B rack after M4, and two console ports labelled the wrong way round; and decoys. The checks never read it |

### Storage (`data/telemetry/storage/`)

Stream `{seed}:telemetry:storage`; settings in `config/telemetry_storage.yaml`. Read from `data/sample/`, `data/telemetry/mgmt/`, and `site/site.yaml`. Every storage node's drive bays (32 nodes, 768 drives, erasure coding 8+2) under the Redfish Drive names, the storage and in-band Ethernet fabric's IF-MIB counters and traps, and the clients' I/O stalls from the Customer's job telemetry, beside the IT Partner's drive and optic tickets and custody handovers. A compute tray's storage ports follow the tray's host management port in the management layer. All of it is committed; there is no `windows/` folder.

| File | What it represents |
|---|---|
| `drive_inventory.csv` | Each bay's drive serial at the start and end of the month |
| `drive_events.jsonl` | Redfish drive events (Failed, PredictedFailure, Warning, Cleared, Removed, Inserted, RebuildComplete) with health, state, indicator, serial |
| `node_events.jsonl` | Storage nodes going offline and online (firmware reboots) |
| `nodes_hourly.csv` | Per node per hour: minutes online, drives ok, failed, absent, rebuilding, reads, writes, used capacity |
| `cluster_hourly.csv` | Per cluster per hour: nodes online, reads, writes, used capacity, minutes at reduced protection |
| `leaf_hourly.csv` | Per storage leaf per hour: tray ports, ports up, traffic |
| `ports_hourly.csv` | Per fabric port per hour: seconds up, traffic, input errors |
| `traps.jsonl` | SNMP linkDown and linkUp traps from the storage fabric |
| `client_stalls.jsonl` | Minutes each compute node's job waited on storage |
| `tickets.json` | The IT Partner's drive and optic tickets, including the customer impact each one states |
| `custody.csv` | Pulled drives handed to the Security Partner (Interface Agreement HO-5) |
| `spares_ledger.csv` | The IT Partner's storage spares ledger per hall (drives and optics) |
| `spares_cycle_counts.csv` | Physical counts of the storage spares shelf |
| `answer_key.json` | Planted: a flapping leaf uplink that stalls clients while its ticket says no impact, a pulled drive with no custody handover, a drive ticket resolved before the rebuild completed, and a ticket naming the bay next to the one whose serial changed; and decoys. The checks never read it |

## Energy meters (`data/energy/`)

Derived by `scripts/generate_energy.py` from `data/sample/` and the GPU and CDU telemetry, with its own random stream (`{seed}:energy`; the daily history uses `{seed}:energy-history`); the sample is never written. `scripts/generate_telemetry.py` runs the same step, because the meters follow the racks (`data/telemetry/gpu/rack_hourly.csv`), the CDUs, and the thermal walls. Settings in `config/energy.yaml`; sizes from `site/site.yaml`. Cooling follows a modeled Central Texas outdoor temperature.

| File | What it represents |
|---|---|
| `meters_hourly.csv` | One row per hour: utility and generator energy, UPS input and output per hall (output is IT energy), mechanical UPS per hall, chiller yard, facility water pumps, electrical-room CRAHs, house panel, outdoor and facility water temperatures |
| `chiller_events.jsonl` | Free-cooling lockouts and re-enables on each chiller, from the BMS, with the user and PM reference |
| `landlord_energy_report.json` | The Landlord's monthly energy report: its total facility and IT energy, method, and PUE figure |
| `history_daily.csv` | 12 four-week periods before the month, by day (committed sample only) |
| `answer_key.json` | Planted: a free-cooling lockout opened for PM work that stayed in place for days (the check allows 24 hours with no change record), and the report's error (UPS input counted as IT energy in the sample). The checks never read it |
| `manifest.json` | Source, counts |

## Incident comms (`data/incident_comms/`)

Derived by `scripts/generate_incident_comms.py` from the scenario in `config/incident_comms.yaml`, which gives the minute of each entry; the layer adds the second from its own random stream (`{seed}:incident-comms`), keeping the scenario's order within a minute. Only the sample's seed is read, and nothing else in the dataset is read or written.

| File | What it represents |
|---|---|
| `INC3900001.json` | The comms log for the A07 rack outage that the Incident Commander runbook replays: page acknowledgements, bridge opened and closed, IC declared, leads joined, each lead's updates, leadership updates, restoration and return to service, each with party and role (no names) |
| `manifest.json` | Source, counts |

## Deployment program (`data/deployments/`)

Derived by `scripts/generate_deployments.py` from `data/sample/` with its own random stream (`{seed}:deployments`; the planted cases use `{seed}:deployments:planted`); the sample is never written. Settings in `config/deployments_data.yaml` (the program itself is in `config/deployments.yaml`). The record of the Hall B GB300 rollout. The rack milestones in the IT Partner's project are its own self-report, at the same times as `data/sample/vendor/deployment_milestones.csv`. No person is named: Jira assignees are empty and sign-offs carry a role and an organization.

| File | What it represents |
|---|---|
| `jira/RSS-DEP.json` | The IT Partner's Jira project: epics per gate and an issue per step and rack, in the shape a Jira Cloud search returns (`/rest/api/3/search/jql`), so a real export reads through the same importer (`scorecard.jira_import`) |
| `jira/CCF-DEP.json` | The Landlord's Jira project, same shape (including each rack's energization, which falls between its leak test and its power-on) |
| `customer_steps.json` | The Customer's own step records: planned start, due, done, state |
| `signoffs.jsonl` | Sign-offs by step and rack: role, organization, decision, time |
| `inspections.jsonl` | Inspections by step and rack: third party, authority having jurisdiction, or Customer witness; result |
| `permits.json` | Permits: applied, issued, inspection, finaled |
| `determinations.json` | Recorded code determinations by step (for example, which NEC edition applies) |
| `answer_key.json` | Planted: a step done out of order, a step with no sign-off, a step with no inspection, a sign-off dated before the step was done; and decoys. The record checks never read it |
| `manifest.json` | Window, seed, source, counts |

## Hall C readiness (`data/readiness/`)

Derived by `scripts/generate_readiness.py` with its own random stream (`{seed}:readiness`; the planted cases use `{seed}:readiness:planted` and never move the rest). Only the sample's as-of date and seed are read; nothing else is written. Every day is placed relative to the as-of date, so each generated month holds a program at the same stage. Settings in `config/readiness_data.yaml` (the program itself is in `config/readiness.yaml`). The record of Hall C, the 800 VDC pilot. No person is named: signatures carry a role.

| File | What it represents |
|---|---|
| `program.json` | As-of date, baseline issued, committed first compute |
| `cx_scripts.json` | The commissioning agent's scripts (L1 to L5) per system: planned and scheduled dates, runs with results, signatures by role |
| `cx_issues.csv` | The commissioning issues log: system, level, script, category, opened, closed |
| `readiness_items.json` | The Customer's readiness items: state, started, done, evidence |
| `spares_receipts.csv` | Pilot spares received: FRU, quantity, purchase order |
| `answer_key.json` | Planted: a script passed with a category 1 issue open, a signature before the run, a script run out of sequence, and the spares item marked done before the last shipment of one spare arrived; and decoys. The record checks never read it |
| `manifest.json` | As-of date, source, counts |

## Asset register (`data/assets/`)

Derived by `scripts/generate_assets.py` from `data/sample/`, `data/security/`, `data/telemetry/mgmt/`, and `data/telemetry/storage/` with its own random stream (`{seed}:assets`); none of those is written. Every move mirrors a record that already exists (ticket parts, RMA shipments, ledger receipts, custody and destruction records, Hall B M1 and M4).

| File | What it represents |
|---|---|
| `register_opening.csv` | The register at the start of the month: one row per asset (tag, class, serial, status, location, maintainer, since, record) |
| `register_transactions.csv` | Every move the IT Partner recorded in the month: receive, issue, install, remove, RMA ship, custody, destroy, dispose, each with its record and when it was recorded |
| `inventory_baseline.csv` | What each slot (tray, switch tray, shelf, PSU, switch, storage node, drive bay) answered with at the first daily scan (Redfish or SNMP); later scans follow the recorded swaps |
| `oem_rma.csv` | The OEM's RMA portal: failed unit received, replacement shipped and delivered with proof of delivery |
| `disposals.csv` | Disposal certificates by serial (recycler, method, Security Partner witness) |
| `answer_key.json` | Planted findings (a live PSU held in stock, a disposed switch still answering, an OEM delivery never received) and decoys. The checks never read it |
| `manifest.json` | Window, seed, sources, counts |

## Fire protection (`data/fire/`)

Derived by `scripts/generate_fire.py` from `data/sample/` (window, VESDA events, the Landlord's maintenance records, MOP approvals, and roster) with its own random stream (`{seed}:fire`); the sample is never written. Settings in `config/fire.yaml`; the rules are Interface Agreement section 12 (FPI-1 to FPI-6).

| File | What it represents |
|---|---|
| `facp_history.jsonl` | The fire alarm control panel's history log: device, point, signal (Alarm, Supervisory, Trouble, Disable), state (Active, Cleared, Test), text. Every VESDA event appears a few seconds after the detector's own record |
| `impairments.csv` | The Landlord's impairment log: planned or unplanned, system, devices, reason, MOP and PM references, start, window end, logged restoration, fire watch start and end, the engineer's ID |
| `impairment_notices.csv` | Impairment notices as the Customer received them (FPN-n): start, extension (with the new end), restored |
| `answer_key.json` | Planted findings (an impairment logged restored inside its window while the panel shows it out for hours after; a control valve closed with nothing logged). The checks never read it |
| `manifest.json` | Window, seed, source, counts |

## Live collector output

`scripts/collect.py` (see `src/scorecard/live/`) writes the same contract files from real devices. It creates every contract file, leaves the ones it does not collect empty, and lists them in `manifest.json` under `not_collected` (Landlord work orders and maintenance records come from Landlord system exports, not device polling). It adds two files the synthetic data does not have:

| File | Contents |
|---|---|
| `facility/cdu_readings.jsonl` | One row per CDU per poll: secondary connector `SupplyTemperatureCelsius`, `ReturnTemperatureCelsius`, `FlowLitersPerMinute`, `SupplyPressurekPa` |
| `collector/feed_health.jsonl` | One row per device per poll: ok or error, latency. A device that stops answering is a measured gap (OT-KM-06), and the collector backs off from it |

## Regenerating

```bash
python scripts/generate_data.py                  # rebuild the committed sample (data/sample)
python scripts/generate_data.py --latest         # 4 weeks ending with the most recent complete week
python scripts/generate_data.py --seed 7 --out data/seed7
```

Tuning for the sample lives in `config/synthetic.yaml`: fault rates, vendor behavior, and how many of each discrepancy to plant. The other layers each have their own settings file, named in their sections above.

The full rebuild runs the generators in this order, with each layer's engine or report between them (the order in `CLAUDE.md`):

```bash
python scripts/generate_data.py                  # data/sample
python scripts/generate_security.py              # data/security
python scripts/generate_incident_comms.py        # data/incident_comms
python scripts/generate_history.py               # data/history
python scripts/generate_changes.py               # data/changes
python scripts/generate_gpu_health.py            # data/gpu_health
python scripts/generate_telemetry.py             # data/telemetry (all folders) and data/energy; build/telemetry
python scripts/generate_energy.py                # data/energy on its own (the same step generate_telemetry.py runs)
python scripts/generate_fire.py                  # data/fire
python scripts/generate_deployments.py           # data/deployments
python scripts/generate_readiness.py             # data/readiness
python scripts/generate_assets.py                # data/assets
```

The tests fail when a committed layer is stale.
