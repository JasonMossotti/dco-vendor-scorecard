<!--
  GENERATED FILE. DO NOT EDIT BY HAND.
  Source: sla/ot_partner.yaml + sla/common.yaml  |  Generator: scripts/render_sla.py
  Edit the YAML and re-run: python scripts/render_sla.py
-->

# Service Level Agreement: Data Center Lease Services

**Schedule C (Landlord Service Levels) to the Data Center Lease**

> **MOCK / ILLUSTRATIVE.** This is a fictional, illustrative landlord service level agreement created for a portfolio demonstration. All parties, sites, quantities, prices, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.

| Document ID | Version | Effective date | Term | Timezone |
|---|---|---|---|---|
| SLA-CCF-AUS1-001 | 1.0.0 | 2026-10-05 | 120 months | UTC |

## Contents

1. [Purpose and Structure](#1-purpose-and-structure)
2. [Parties and Leased Premises](#2-parties-and-leased-premises)
3. [Scope and Ownership](#3-scope-and-ownership)
4. [Alarm Priority Matrix](#4-alarm-priority-matrix)
5. [Measurement and Telemetry of Record](#5-measurement-and-telemetry-of-record)
6. [Work Order Handling Rules](#6-work-order-handling-rules)
7. [Measurement Specification by Fault Class](#7-measurement-specification-by-fault-class)
8. [Critical Service Levels](#8-critical-service-levels)
9. [Key Measurements](#9-key-measurements)
10. [Return-to-Service Validation Requirements](#10-return-to-service-validation-requirements)
11. [Maintenance Requirements](#11-maintenance-requirements)
12. [Service Level Credits and Earnback](#12-service-level-credits-and-earnback)
13. [Chronic Failure](#13-chronic-failure)
14. [Excused Events](#14-excused-events)
15. [Root Cause Analysis and Corrective Action](#15-root-cause-analysis-and-corrective-action)
16. [Governance and Reporting Cadence](#16-governance-and-reporting-cadence)
17. [Staffing and Qualifications](#17-staffing-and-qualifications)
18. [Change Management](#18-change-management)
19. [Security and Chain of Custody](#19-security-and-chain-of-custody)
20. [Environmental, Health, and Safety](#20-environmental-health-and-safety)
21. [Spares](#21-spares)
22. [Energy Reporting and PUE](#22-energy-reporting-and-pue)
23. [SLA Change Control and Continuous Improvement](#23-sla-change-control-and-continuous-improvement)
- [Appendix A: Internal Breach Severity Index](#appendix-a-internal-breach-severity-index)
- [Appendix B: Worked Examples](#appendix-b-worked-examples)

---

## 1. Purpose and Structure

This Schedule defines the service levels Caprock Critical Facilities, LLC ("Landlord", and the "Supplier" for the purposes of the common terms in this Schedule) must meet in operating the facility the Customer leases at Site AUS-1 (fictional), how performance is measured, and what happens when service levels are missed.

Landlord SLAs are usually drafted by the landlord. The terms below are the Customer's negotiated position: measurement from Customer-read telemetry, credits against rent, and read-only device access under the Interface Agreement.

Each service level has an **Expected** level (missing it triggers root cause analysis) and a **Minimum** level (missing it triggers a Service Level Credit against rent). Two principles shape this Schedule:

1. **Telemetry of Record.** Performance is measured from device telemetry the Customer reads directly under the Interface Agreement, not from the Landlord's own reports.
2. **Redundancy restored means proven.** A repair is complete only when redundancy is restored and verified by telemetry, not when an alarm clears or a work order closes.

## 2. Parties and Leased Premises

| Party | Name | Role |
|---|---|---|
| Customer (tenant) | Customer | Owns site outcomes; directs the IT partner; operates the Telemetry of Record; holds the Landlord to its SLA. |
| Landlord | Caprock Critical Facilities, LLC *(fictional)* | Owns and operates the building, power, cooling, fire protection, and building monitoring; leases Halls A and B (and Hall C on delivery) to the Customer. |
| IT Partner | Ridgeline Site Services, LLC *(fictional)* | Separate services agreement and IT Partner SLA (Schedule B). |
| Utility | Serving utility (ERCOT region) | Contracts with the Landlord. Named here only to define ownership boundaries. |

**Premises:** Site AUS-1 (fictional). **Charges basis:** Monthly rent and services fees for 8.4 MW of leased critical capacity (illustrative).

| Hall | State | Racks |
|---|---|:-:|
| HALL-A | production | 32 |
| HALL-B | deployment | 32 |

## 3. Scope and Ownership

### 3.1 Landlord services

| ID | Service | Description |
|---|---|---|
| LL-PWR | Critical power | Utility interface, 13.8 kV switchgear, generators and fuel, unit substations, UPS and batteries, and busway through the tap-off output. |
| LL-COOL | Cooling | Chillers, facility water, CDUs and the secondary header up to the rack manifold isolation valves, thermal walls, and electrical-room CRAHs. |
| LL-FLS | Fire and life safety | Fire alarm, VESDA, pre-action suppression, and building leak detection. |
| LL-MON | Building monitoring | Operating the BMS and EPMS, and providing the Customer's read-only feeds under the Interface Agreement. |
| LL-MAINT | Maintenance | Preventive and corrective maintenance of all Landlord equipment under NFPA 70B, 110, 72, 25, and manufacturer schedules. |

### 3.2 Not Landlord scope

- Racks, power shelves, whips from the tap-off output, rack manifolds, quick-disconnects, and cold plates (IT Partner).
- Customer networks and workloads (Customer).
- The 138 kV substation (Utility).

### 3.3 Break-fix ownership matrix

Exhibit from the Interface Agreement (IA-AUS1-001, version 1.1.0), which governs demarcation, fault attribution, and joint operations between the parties.

**R** = Responsible: performs the work; **A** = Accountable: owns the outcome and approves; **C** = Consulted; **I** = Informed.

| Component | Customer | IT Partner | Landlord | OEM | Utility |
|---|:-:|:-:|:-:|:-:|:-:|
| Compute tray (GPU, CPU, memory, cold plate) | A | R | - | C | - |
| NVLink switch tray and NVLink backplane | A | R | - | C | - |
| Rack power shelves, PSUs, and whips from the tap-off output | A | R | C | C | - |
| Busway, tap-off units, and tap-off breakers | I | C | A/R | - | - |
| UPS, batteries, unit substations, and switchgear | I | I | A/R | - | - |
| Generators, paralleling controls, and fuel | I | - | A/R | - | - |
| 138 kV substation and utility transformers | - | - | C | - | A/R |
| Rack manifold, isolation valves, quick-disconnects | A | R | C | C | - |
| CDUs and the hall secondary header | I | C | A/R | - | - |
| Chillers, facility water, and pumps | I | - | A/R | - | - |
| Thermal walls, CRAHs, and hot-aisle containment | I | C | A/R | - | - |
| Building leak detection (cable and controllers) | I | C | A/R | - | - |
| Fire alarm, VESDA, and pre-action suppression | I | I | A/R | - | - |
| BMS and EPMS operation | C | - | A/R | - | - |
| Customer Telemetry of Record collector and read-only taps | A/R | I | C | - | - |
| Back-end fabric optics, cables, and fiber | A | R | - | C | - |
| Leaf and spine switches (physical replacement) | A | R | - | C | - |
| BMC and out-of-band management network (physical) | A | R | - | C | - |
| Meet-me rooms and cross-connects | C | C | A/R | - | - |
| Spares cage, inventory, and RMA shipments | A | R | - | C | - |
| Building perimeter, lobby, and access control system | C | I | A/R | - | - |
| Customer halls and cage access lists | A | R | R | - | - |

## 4. Alarm Priority Matrix

"Engaged on-site" means a qualified engineer badged into the room with the alarmed equipment.

| Priority | Acknowledge | Engaged on-site | Containment | Restore (Validated RTS) | Updates every |
|---|---|---|---|---|---|
| **P1 Critical** | 5 min | 15 min | 30 min | 4 hrs | 30 min |
| **P2 Major** | 15 min | 30 min | n/a | 8 hrs | 1 hr |
| **P3 Minor** | 1 hr | 4 hrs | n/a | 24 hrs | 24 hrs |
| **P4 Planned** | 24 hrs | n/a | n/a | 5 days | n/a |

### P1: Critical

**Criteria:**

- Loss of power or cooling to any leased rack.
- A power or cooling path serving racks with no redundancy remaining.
- Any building leak alarm, VESDA Action or higher, or unplanned fire protection impairment.
- Any EHS event involving injury, fire, smoke, or electrical hazard.

**Examples:** Both feeds lost to rack A-07. CDU-B2 out with the Hall B header at N. TraceTek leak at 14.2 m on the circuit under CDU-A3.

**Escalation:** Immediate page to the Customer Incident Commander; Landlord chief engineer engaged.

### P2: Major

**Criteria:**

- Loss of redundancy on a power or cooling path (N+1 to N, or 2N to N).
- A generator fails to start or accept load.
- A UPS on bypass with redundancy remaining.

**Examples:** UPS-A3 module failed; Hall A still 4 make 3 with margin. GEN-4 alarm shutdown during the monthly test.

**Escalation:** Landlord duty manager notifies the Customer site lead.

### P3: Minor

**Criteria:**

- A degraded component with redundancy intact.
- A BMS point or sensor failure with coverage maintained.

**Examples:** One thermal-wall fan failed; TW-A2 still in service.

**Escalation:** Reviewed in the daily standup.

### P4: Planned

**Criteria:**

- Requests and planned work with no current risk.

**Examples:** Relabel a busway tap-off after a rack move.

**Escalation:** Scheduled through the Landlord maintenance system.

## 5. Measurement and Telemetry of Record

Performance is measured from Customer-operated Telemetry of Record, not from Supplier self-reporting. Supplier ticket and work order data is used for work content and narrative, and is reconciled against telemetry. Where they disagree, the higher-precedence source prevails.

### 5.1 Clock rules

- **Clock starts:** T0, the earliest evidence of the fault across all sources.
- **Clock stops:** Validated RTS.
- **The clock may pause only for:**
  - A Customer-requested hold, recorded in the ticket or work order with Customer approval.
  - Customer-controlled access delays (e.g., cage access withheld by the Customer).
  - An approved Excused Event.
- **The clock does not pause for:**
  - Waiting for parts when Customer spares were at or above minimum stock.
  - Supplier staffing shortfalls or shift changes.
  - Waiting on Supplier internal escalation.
- **Timestamps:** All systems record UTC and are NTP-synchronized; records with clock skew over 5 seconds are flagged.

### 5.2 Data sources and precedence

Precedence 1 is most authoritative. When sources disagree, the higher-precedence source prevails.

| ID | Source | Measures | Owner | Precedence |
|---|---|---|---|:-:|
| DS-DCGM | GPU telemetry (DCGM and driver XID events) | GPU faults, ECC and XID events, diagnostic results, burn-in results. | Customer | 1 |
| DS-REDFISH | BMC Redfish API | Hardware inventory and serial numbers, PSU health, tray leak detection, power state. | Customer | 1 |
| DS-NMX | NVLink fabric management telemetry | NVLink switch tray health, NVLink domain state, link errors. | Customer | 1 |
| DS-UFM | InfiniBand fabric manager | Port state, link-down events, symbol and error counters. | Customer | 1 |
| DS-HEALTH | Cluster health-check and automated recovery platform | Periodic and job-boundary health checks; node drain and return events. | Customer | 1 |
| DS-SCHED | Customer workload scheduler | Node state (available, drained, down) and capacity returned to production. | Customer | 1 |
| DS-BMS | Building management system feed (EcoStruxure Building Operation, operated by the Landlord) | Chillers, pumps, thermal walls, CRAHs, CDU summary points, alarm acknowledgments, point overrides and alarm inhibits. | Landlord | 2 |
| DS-EPMS | Electrical power monitoring (EcoStruxure Power Monitoring Expert export) | Switchgear breaker states, utility and generator source, meter readings, power quality events. | Landlord | 2 |
| DS-UPS | UPS network management cards (SNMPv3, Customer read-only user) | UPS mode (normal, battery, bypass), module status, load, battery state of charge, alarms. | Customer | 1 |
| DS-BUSWAY | Busway Critical Power Monitors (Modbus TCP, Customer read-only) | Per-segment voltage, current, and power at each A and B busway; tap-off breaker state. | Customer | 1 |
| DS-EMCP | Generator controllers (EMCP 4.4 via Modbus TCP, Customer read-only) | Engine run state, kW load, percent of nameplate, exhaust temperature, start and transfer events, alarms. | Customer | 1 |
| DS-CDU | CDU controllers (Redfish, Customer read-only account) | Secondary supply and return temperature, flow, pressure, pump status and redundancy, coolant level, CDU leak sensors. | Customer | 1 |
| DS-LEAK | Leak detection (TraceTek TTDM-128 via Modbus gateway, Customer read-only) | Leak alarms with distance along the cable, cable breaks, circuit faults. | Customer | 1 |
| DS-FIRE | Fire alarm and aspirating smoke detection (VESDA via HLI, secondary monitoring) | VESDA Alert, Action, Fire 1, and Fire 2; detector faults; fire system impairments. The fire panel remains the life-safety system of record. | Landlord | 2 |
| DS-CMMS | Landlord maintenance management system | Work orders, preventive maintenance schedule and completion, method of procedure (MOP) references, Landlord-recorded timestamps. | Landlord | 3 |
| DS-BADGE | Access control system | Technician and engineer presence by hall and equipment room, time on site, staffing fill. | Customer | 1 |
| DS-CAB | Customer change management system | Approved changes and maintenance windows. | Customer | 1 |
| DS-ITSM | Supplier ticketing system | Ticket lifecycle, work notes, parts used, priority, Supplier-recorded timestamps. | Supplier | 3 |
| DS-SPARES | Supplier spares and RMA system | Stock levels, consumption, cycle counts, RMA shipments. | Supplier | 3 |

### 5.3 Reporting

- **Weekly:** Operating scorecard by Monday 12:00 UTC, generated automatically from telemetry and ticket or work order data.
- **Monthly:** Service Level Report within 5 business days after month end, including all defaults, credits, and trends.
- **Raw data:** The Customer may access ticket and work order data through API at any time; the Supplier must keep all records for the Term plus 2 years.
- **Failure to report:** If the Supplier fails to provide data required to measure a service level, that service level is deemed to have a Minimum Service Level Default for the period.

### 5.4 Reference implementation

Every calculation in this SLA is implemented in the scorecard source code (src/scorecard), which both parties receive and may run. That reference implementation, applied to the Telemetry of Record, is the agreed method of calculation, so any disagreement is about data, never about math. Changes to it follow SLA change control.

### 5.5 Calibration period

For the first 90 days, both parties measure every service level in parallel and reconcile every difference weekly. Credits do not apply during calibration; defaults are recorded and reviewed, and the Measurement Specification is corrected before credits begin.

### 5.6 Reconciliation and disputes

Each week the scorecard lists every record where Supplier data and telemetry disagree. The Supplier responds to each item before the weekly operations review.

The Supplier may dispute a measurement within 5 business days of the weekly scorecard, with evidence from a Telemetry of Record source. Undisputed measurements are final. Disputes unresolved after 10 business days escalate to the monthly service review.

### 5.7 Audit

Each month the Customer audits a random 5% of closed tickets or work orders (minimum 10) end to end against raw telemetry, badge, and inventory records. Audit findings count toward CSL-11.

### 5.8 Records access

The Customer reads the Supplier's ticket and work order records directly, so no service level depends on a Supplier export or summary. This term sets out the raw data access above.

| ID | Term | Requirement |
|---|---|---|
| RA-1 | Read-only account | The Supplier issues one read-only API service account for each system that holds Site records (ticketing or maintenance management, and spares and RMA), scoped to the Customer's records. No write credentials are issued, and the Customer never changes a Supplier record. |
| RA-2 | Content | Every ticket, work order, and preventive maintenance record for the Site, with its full history: state and priority changes, all timestamps, work notes, assignee, parts with removed and installed serial numbers, and linked change or MOP references. |
| RA-3 | Edit history | The field audit log (each change to a timestamp, priority, state, or fault class, with user, time, and reason) is readable through the same account. |
| RA-4 | Freshness | A new record or a change to a record is readable within 15 minutes, the record integrity tolerance. |
| RA-5 | Outages | The Customer logs any gap in access over 15 minutes and tells the Supplier. Data the Supplier cannot provide for a period is handled under Failure to report. |
| RA-6 | Use and sharing | The Customer uses the records to measure the service levels, attribute outages, and audit. It shares a record with the other Site partner only as needed for attribution under the Interface Agreement. |

## 6. Work Order Handling Rules

Ticket handling is standardized so that no individual's habits or preferences can change a measurement. These rules apply to every fault class; the Measurement Specification adds the class-specific details.

### 6.1 Work Order of Record

- Telemetry-detected faults open the Work Order of Record automatically through the Customer alerting integration, stamped with T0, the fault class, and the Service Unit Key. The Supplier works that work order in its maintenance system and does not open its own for the same fault.
- Faults found by people first (visible leak, physical damage, smoke, odor) are opened by the Supplier immediately. T0 is still the earliest evidence from any source.
- One Work Order of Record per fault per Service Unit Key. A second work order for the same unit opened while the first is open or in MONITORING is merged into the first and keeps the earliest T0.
- The fault class, chosen from the controlled list in the Measurement Specification, sets the priority, evidence, validation, and stability rules. It cannot be changed without Customer approval.

### 6.2 Required work order fields

Every Work Order of Record carries these fields. Fault classes in Section 7 add their own.

- Work Order of Record ID and fault class
- Service Unit Key
- T0 (system-generated)
- Priority (from the Measurement Specification)
- Assigned engineer (person ID)
- Parts removed and installed, with scanned serial numbers
- Validation record IDs linked from the BMS and device telemetry
- Close code and root-cause category (controlled lists)

### 6.3 Work order states

| State | Clock | Meaning |
|---|:-:|---|
| `NEW` | running | Opened from telemetry or by the Supplier. |
| `ASSIGNED` | running | Acknowledged by a qualified person. |
| `IN_PROGRESS` | running | Engineer at the Equipment. |
| `PENDING_CUSTOMER` | paused | Allowed only with an approved pause code and a named Customer approver. |
| `VALIDATING` | running | Repair complete; validation checks running. |
| `MONITORING` | stopped | Validated RTS reached; unit in production for its stability window. |
| `REOPENED` | running | Fault recurred during MONITORING; clock resumes under TR-1 or TR-2. |
| `CLOSED` | stopped | Stability window passed with no fault. Set automatically, never manually. |

### 6.4 Pause codes

The clock pauses only under one of these codes, each requiring a named Customer approver.

| Code | Meaning |
|---|---|
| `CUST_HOLD` | Customer-requested hold, such as a job checkpoint before work starts. |
| `CUST_ACCESS` | Access withheld by the Customer. |
| `EXCUSED` | Approved Excused Event. |

### 6.5 Data integrity

- All timestamps are system-generated in UTC. Manual timestamp entry is disabled; any edit to a timestamp, priority, state, or fault class is audit-logged with user, time, and reason.
- Part and component serial numbers are captured by scanning the part label. Manual entry requires a reason code and is flagged for audit.
- Fault class, close code, root-cause category, and pause code come from controlled lists. Free text is narrative only and is never used to calculate a service level.
- Validation evidence is linked from the BMS and device telemetry by record ID. Pasted text, typed summaries, and screenshots are not evidence.

### 6.6 Stability, reopen, and recurrence rules

**A repair is finished when the unit stays up, not when it comes up.**

| Rule | Name | Rule text |
|---|---|---|
| **TR-1** | Early failure | If the same Service Unit Key faults again within 60 minutes of Validated RTS, the earlier restore is void. The work order reopens and the clock runs continuously from the original T0, including the minutes the unit was up. |
| **TR-2** | Reopen within the stability window | If the same Service Unit Key faults again after 60 minutes but within its fault class's stability window, the original work order reopens. Measured restoration time is the cumulative downtime of every down interval since the original T0, and the work order is restored only when a Validated RTS survives a full stability window. |
| **TR-3** | Automatic closure | Work orders stay in MONITORING for the stability window and close automatically when it passes with no fault. They cannot be closed manually before then. |
| **TR-4** | Stability runs in production | The stability window runs with the unit in production. Holding a repaired unit out of production to wait out the window counts as downtime. |
| **TR-5** | Linked recurrence | A fault on the same Service Unit Key after the stability window but within its recurrence window opens a new work order, automatically linked to the original as a child. The child has its own clock; the original counts as a First-Time Fix failure (CSL-06) and a Repeat Failure (CSL-08). |
| **TR-6** | No work order splitting | Opening a new work order for a fault that TR-1 or TR-2 requires to reopen an existing work order is a Record Integrity Finding (CSL-11, aggravator AGG-INTEGRITY). The work orders are merged for measurement. |
| **TR-7** | Unrelated-fault dispute | The Supplier may show with telemetry evidence that a recurrence is unrelated to the repair (for example, a CDU pump failure days after a filter change on the same unit). The default presumption is that a recurrence is related. Disputes follow the measurement dispute process. |

How the same refault is treated follows the same timing rules as the IT Partner SLA: a refault within 60 minutes voids the restore (TR-1); within the fault class's stability window it reopens the work order (TR-2); after the stability window but within the recurrence window it is a new linked work order that fails first-time fix (TR-5).

## 7. Measurement Specification by Fault Class

Each fault class below is a rule card: the single approved way to detect, classify, evidence, validate, and time that kind of fault. The Customer alerting integration assigns the fault class when it opens the Work Order of Record.

| Class | Fault | Service Unit Key | Detected by | Default priority | Stability window | Recurrence window |
|---|---|---|---|:-:|:-:|:-:|
| OT-FC-PWR | Busway or tap-off power loss | Busway segment and side (A or B) | DS-BUSWAY | P2 | 24 hrs | 7 days |
| OT-FC-UPS | UPS module or system fault | UPS system and module number | DS-UPS | P2 | 72 hrs | 14 days |
| OT-FC-GEN | Generator failure | Generator number | DS-EMCP | P2 | 72 hrs | 30 days |
| OT-FC-CDU | CDU fault (pump, controls, or redundancy lost) | CDU and pump number | DS-CDU | P2 | 72 hrs | 14 days |
| OT-FC-CHW | Chiller, pump, or facility water fault | Chiller or pump number | DS-BMS | P2 | 72 hrs | 14 days |
| OT-FC-AIR | Thermal wall or CRAH fault | Unit ID | DS-BMS | P3 | 24 hrs | 14 days |
| OT-FC-LEAK | Building leak (CDU, header, or facility water) | Leak circuit and distance | DS-LEAK | P1 | 24 hrs | 30 days |
| OT-FC-FIRE | Fire protection alarm or impairment | Detector, zone, or system | DS-FIRE | P1 | 24 hrs | 30 days |

### OT-FC-PWR: Busway or tap-off power loss

| | |
|---|---|
| **Service Unit Key** | Busway segment and side (A or B) |
| **Detection signal** | Critical Power Monitor voltage out of tolerance or zero on a busway segment, or a tap-off breaker open. Source: DS-BUSWAY. |
| **T0 rule** | First out-of-tolerance reading. |
| **Recurrence signal** | Any power loss on the same busway segment and side. |
| **Priority** | P2 by default. P1 if both feeds of any rack are lost, or the surviving feed exceeds 80% of its rating. |
| **Additional work order fields** | Racks on the segment; Surviving feed load at T0 |
| **Repair evidence** | Breaker or component serials replaced; infrared scan after repair. |
| **Validation** | Section 10 checklist: Electrical distribution (busway, tap-off, breaker) |
| **Clock stops** | Both feeds in tolerance for every rack on the segment. |
| **Stability window** | 24 hours in production (TR-2, TR-3) |
| **Recurrence window** | 7 days (TR-5) |
| **Capacity impact** | No compute lost; counts against redundancy service levels (OT-CSL-02, OT-CSL-05) |

### OT-FC-UPS: UPS module or system fault

| | |
|---|---|
| **Service Unit Key** | UPS system and module number |
| **Detection signal** | NMC trap or poll: module failed, UPS on bypass, or on battery without a source event. Source: DS-UPS. |
| **T0 rule** | Timestamp of the first UPS alarm. |
| **Recurrence signal** | Any module or mode alarm on the same UPS. |
| **Priority** | P2 by default. P1 if a UPS transfers to bypass or battery while carrying racks with no redundancy remaining. |
| **Additional work order fields** | UPS load and mode at T0; Battery state of charge |
| **Repair evidence** | Module serials scanned; OEM field service report. |
| **Validation** | Section 10 checklist: UPS module |
| **Clock stops** | UPS in normal mode with all modules healthy and redundancy restored. |
| **Stability window** | 72 hours in production (TR-2, TR-3) |
| **Recurrence window** | 14 days (TR-5) |
| **Capacity impact** | No compute lost; counts against redundancy service levels (OT-CSL-02, OT-CSL-05) |

### OT-FC-GEN: Generator failure

| | |
|---|---|
| **Service Unit Key** | Generator number |
| **Detection signal** | EMCP alarm shutdown, failure to start or to reach rated voltage and frequency, or failure to accept load. Source: DS-EMCP. |
| **T0 rule** | Timestamp of the EMCP event. |
| **Recurrence signal** | Any start, load, or shutdown alarm on the same generator. |
| **Priority** | P2 by default. P1 during a utility outage, or if generator redundancy is lost (fewer than N+1 available). |
| **Additional work order fields** | Run hours; Fuel level; Load at failure |
| **Repair evidence** | Dealer service report; parts replaced with serials. |
| **Validation** | Section 10 checklist: Generator |
| **Clock stops** | Successful start and loaded run at 30% of nameplate or more for 30 minutes, recorded by the EMCP. |
| **Stability window** | 72 hours in production (TR-2, TR-3) |
| **Recurrence window** | 30 days (TR-5) |
| **Capacity impact** | No compute lost; counts against redundancy service levels (OT-CSL-02, OT-CSL-05) |

### OT-FC-CDU: CDU fault (pump, controls, or redundancy lost)

| | |
|---|---|
| **Service Unit Key** | CDU and pump number |
| **Detection signal** | Redfish: pump failed or redundancy lost, or secondary supply temperature or flow outside the rack band. Source: DS-CDU. |
| **T0 rule** | Timestamp the condition first appeared. |
| **Recurrence signal** | Any pump or band alarm on the same CDU. |
| **Priority** | P2 by default. P1 if secondary supply temperature or flow at any rack leaves the band, or the header loses N+1. |
| **Additional work order fields** | Supply and return temperatures and flow at T0 and at restore |
| **Repair evidence** | Removed and installed pump assembly serials scanned. |
| **Validation** | Section 10 checklist: CDU component (pump, filter, sensor) |
| **Clock stops** | Pump redundancy restored, failover test passed, and the hall header in band. |
| **Stability window** | 72 hours in production (TR-2, TR-3) |
| **Recurrence window** | 14 days (TR-5) |
| **Capacity impact** | No compute lost; counts against redundancy service levels (OT-CSL-02, OT-CSL-05) |

### OT-FC-CHW: Chiller, pump, or facility water fault

| | |
|---|---|
| **Service Unit Key** | Chiller or pump number |
| **Detection signal** | BMS: chiller or facility water pump alarm or trip, or facility water supply temperature above setpoint plus 2 C. Source: DS-BMS. |
| **T0 rule** | Timestamp of the first BMS alarm. |
| **Recurrence signal** | Any alarm on the same chiller or pump. |
| **Priority** | P2 by default. P1 if facility water supply leaves its band or plant redundancy is lost at design conditions. |
| **Additional work order fields** | Outdoor temperature; Plant load |
| **Repair evidence** | Service report; refrigerant work logged by an EPA 608 certified technician. |
| **Validation** | Section 10 checklist: Chiller, pump, or air handler |
| **Clock stops** | Unit back in service and plant redundancy restored. |
| **Stability window** | 72 hours in production (TR-2, TR-3) |
| **Recurrence window** | 14 days (TR-5) |
| **Capacity impact** | No compute lost; counts against redundancy service levels (OT-CSL-02, OT-CSL-05) |

### OT-FC-AIR: Thermal wall or CRAH fault

| | |
|---|---|
| **Service Unit Key** | Unit ID |
| **Detection signal** | BMS: unit alarm, fan failure, or hall cold-aisle temperature above its limit. Source: DS-BMS. |
| **T0 rule** | Timestamp of the first BMS alarm. |
| **Recurrence signal** | Any alarm on the same unit. |
| **Priority** | P3 by default. P2 if air-side redundancy is lost in a hall; P1 if a cold aisle exceeds its limit. |
| **Additional work order fields** | Cold-aisle temperatures |
| **Repair evidence** | Fan or component serials replaced. |
| **Validation** | Section 10 checklist: Chiller, pump, or air handler |
| **Clock stops** | Unit back in service; cold aisles within limit. |
| **Stability window** | 24 hours in production (TR-2, TR-3) |
| **Recurrence window** | 14 days (TR-5) |
| **Capacity impact** | No compute lost; counts against redundancy service levels (OT-CSL-02, OT-CSL-05) |

### OT-FC-LEAK: Building leak (CDU, header, or facility water)

| | |
|---|---|
| **Service Unit Key** | Leak circuit and distance |
| **Detection signal** | TraceTek leak alarm with location on a circuit under a CDU, along the header, or on facility water piping. Source: DS-LEAK. |
| **T0 rule** | Timestamp of the leak alarm. |
| **Recurrence signal** | Any leak alarm within 3 m on the same circuit. |
| **Priority** | P1 by default. |
| **Additional work order fields** | Estimated volume; Containment time |
| **Repair evidence** | Source identified and repaired; cable section replaced if wetted. |
| **Validation** | Section 10 checklist: Leak detection zone |
| **Clock stops** | Source repaired, area dry, cable restored, and a 30-minute hold with no alarm. |
| **Stability window** | 24 hours in production (TR-2, TR-3) |
| **Recurrence window** | 30 days (TR-5) |
| **Capacity impact** | No compute lost; counts against redundancy service levels (OT-CSL-02, OT-CSL-05) |

### OT-FC-FIRE: Fire protection alarm or impairment

| | |
|---|---|
| **Service Unit Key** | Detector, zone, or system |
| **Detection signal** | VESDA Action, Fire 1, or Fire 2; a detector or panel fault; or an unplanned impairment. Source: DS-FIRE. |
| **T0 rule** | Timestamp of the first alarm or fault. |
| **Recurrence signal** | Any alarm or fault in the same zone. |
| **Priority** | P1 by default. P2 for a detector fault with coverage maintained by adjacent detection. |
| **Additional work order fields** | Smoke level at alarm; Fire watch start time if impaired |
| **Repair evidence** | Fire contractor report under NFPA 72 or NFPA 25. |
| **Validation** | Section 10 checklist: Fire protection system |
| **Clock stops** | System restored, tested, and any impairment closed with the Customer notified. |
| **Stability window** | 24 hours in production (TR-2, TR-3) |
| **Recurrence window** | 30 days (TR-5) |
| **Capacity impact** | No compute lost; counts against redundancy service levels (OT-CSL-02, OT-CSL-05) |

## 8. Critical Service Levels

Critical Service Levels are measured each calendar month and tracked each ISO week (Monday 00:00 UTC to Sunday 23:59 UTC). A result worse than **Minimum** is a Minimum Service Level Default and earns the credit described in Section 12.

| ID | Service level | Category | Expected | Minimum | Credit allocation |
|---|---|---|:-:|:-:|:-:|
| OT-CSL-01 | Rack Power Availability | Power and Cooling Availability | ≥ 99.999% | ≥ 99.995% | 30% |
| OT-CSL-02 | Power Redundancy Availability | Power and Cooling Availability | ≥ 99.9% | ≥ 99.5% | 15% |
| OT-CSL-03 | Cooling Within Band at the Rack | Power and Cooling Availability | ≥ 99.99% | ≥ 99.95% | 30% |
| OT-CSL-04 | Critical Alarm Response | Response and Restoration | ≥ 98% | ≥ 95% | 15% |
| OT-CSL-05 | Redundancy Restored Within Target | Response and Restoration | ≥ 95% | ≥ 90% | 20% |
| OT-CSL-06 | Preventive Maintenance On Time, Evidence-Verified | Maintenance and Change Discipline | ≥ 98% | ≥ 95% | 20% |
| OT-CSL-07 | Critical Work Under Approved MOP | Maintenance and Change Discipline | 100% | ≥ 98% | 15% |
| OT-CSL-08 | Record Integrity | Workforce and Record Integrity | ≥ 98% | ≥ 95% | 25% |
| OT-CSL-09 | Qualified Staffing Fill | Workforce and Record Integrity | ≥ 98% | ≥ 95% | 10% |
| OT-CSL-10 | Worst-Hall Cooling Within Band | Power and Cooling Availability | ≥ 99.95% | ≥ 99.9% | 10% |
| | **Total allocation** | | | | **190%** (pool limit 200%) |

### OT-CSL-01: Rack Power Availability

Share of rack-minutes with at least one feed in tolerance at the busway tap-off.

- **Formula:** (Rack-minutes with at least one feed in tolerance) ÷ (Leased rack-minutes) × 100
- **Expected:** ≥ 99.999%. **Minimum:** ≥ 99.995%.
- **Telemetry:** DS-BUSWAY, DS-UPS, DS-EPMS

### OT-CSL-02: Power Redundancy Availability

Share of rack-minutes with both feeds in tolerance.

- **Formula:** (Rack-minutes with both feeds in tolerance) ÷ (Leased rack-minutes) × 100
- **Expected:** ≥ 99.9%. **Minimum:** ≥ 99.5%.
- **Telemetry:** DS-BUSWAY, DS-UPS

### OT-CSL-03: Cooling Within Band at the Rack

Share of rack-minutes with CDU secondary supply temperature, flow, and pressure within the rack band, and the cold aisle within its limit.

- **Formula:** (Rack-minutes in band) ÷ (Leased rack-minutes) × 100
- **Expected:** ≥ 99.99%. **Minimum:** ≥ 99.95%.
- **Telemetry:** DS-CDU, DS-BMS

### OT-CSL-04: Critical Alarm Response

P1 alarms acknowledged within 5 minutes and a qualified engineer at the equipment within 15 minutes (badge evidence).

- **Formula:** (P1 alarms meeting both targets) ÷ (P1 alarms) × 100
- **Expected:** ≥ 98%. **Minimum:** ≥ 95%.
- **Telemetry:** DS-BMS, DS-BADGE, DS-CMMS

### OT-CSL-05: Redundancy Restored Within Target

Redundancy-loss events restored and validated within the priority's restore target.

- **Formula:** (Events restored within target) ÷ (Redundancy-loss events) × 100
- **Expected:** ≥ 95%. **Minimum:** ≥ 90%.
- **Telemetry:** DS-UPS, DS-CDU, DS-EMCP, DS-BMS, DS-CMMS

### OT-CSL-06: Preventive Maintenance On Time, Evidence-Verified

Scheduled maintenance completed within its window, counted only when device telemetry or badge records confirm the work (for example, EMCP data for an NFPA 110 test).

- **Formula:** (Maintenance tasks completed on time with evidence) ÷ (Maintenance tasks due) × 100
- **Expected:** ≥ 98%. **Minimum:** ≥ 95%.
- **Telemetry:** DS-CMMS, DS-EMCP, DS-BADGE, DS-BMS

### OT-CSL-07: Critical Work Under Approved MOP

Work on critical power, cooling, or fire systems performed under an approved method of procedure within its window.

- **Formula:** (Critical work events with an approved MOP) ÷ (Critical work events seen in telemetry) × 100
- **Expected:** 100%. **Minimum:** ≥ 98%.
- **Telemetry:** DS-CMMS, DS-CAB, DS-BADGE, DS-BMS

### OT-CSL-08: Record Integrity

Landlord work orders and maintenance records that reconcile with device telemetry and badge records within the common tolerance.

- **Formula:** (Reconciled records) ÷ (Records sampled) × 100
- **Expected:** ≥ 98%. **Minimum:** ≥ 95%.
- **Telemetry:** DS-CMMS, DS-EMCP, DS-UPS, DS-CDU, DS-BADGE

### OT-CSL-09: Qualified Staffing Fill

Badge-verified hours by qualified critical facilities engineers against the committed roster.

- **Formula:** (Qualified badge-verified hours) ÷ (Committed hours) × 100
- **Expected:** ≥ 98%. **Minimum:** ≥ 95%.
- **Telemetry:** DS-BADGE

### OT-CSL-10: Worst-Hall Cooling Within Band

OT-CSL-03 for the worst hall in the period, so a good site average cannot hide one hall.

- **Formula:** (Rack-minutes in band (worst hall)) ÷ (Leased rack-minutes (that hall)) × 100
- **Expected:** ≥ 99.95%. **Minimum:** ≥ 99.9%.
- **Telemetry:** DS-CDU

## 9. Key Measurements

Key Measurements carry no credits. Any miss requires a root cause analysis and corrective action plan (Section 15), and repeated misses may lead the Customer to promote the measurement to a Critical Service Level (Section 22).

| ID | Key measurement | Target | Telemetry |
|---|---|:-:|---|
| OT-KM-01 | P2 Alarm Response (acknowledge 15 min, at equipment 30 min) | ≥ 95% | DS-BMS, DS-BADGE |
| OT-KM-02 | Generator Monthly Tests Meeting NFPA 110 Load (30% for 30 min) | 100% | DS-EMCP |
| OT-KM-03 | Coolant Samples Within Specification | 100% | DS-CMMS, DS-CDU |
| OT-KM-04 | Annual Fuel Quality Tests On Schedule | 100% | DS-CMMS |
| OT-KM-05 | BMS Overrides or Alarm Inhibits Open Over 24 Hours Without a Change Reference | ≤ 0 items | DS-BMS, DS-CAB |
| OT-KM-06 | Monitoring Feed Availability to the Customer | ≥ 99.9% | DS-BMS, DS-EPMS |
| OT-KM-07 | Planned Maintenance Notified 10 Business Days Ahead | 100% | DS-CMMS, DS-CAB |
| OT-KM-08 | Corrective Action Plans Closed On Time | ≥ 95% | DS-CMMS |

## 10. Return-to-Service Validation Requirements

Facility equipment is returned to service only when its redundancy is restored and proven, not when an alarm clears.

Each check is recorded in the Landlord maintenance system under a standard check ID, so validation evidence is linked by record, never retyped.

**Electrical distribution (busway, tap-off, breaker)** (check IDs: `busway_in_tolerance`, `ir_scan`)

- [ ] Critical Power Monitor shows both feeds in tolerance for every rack on the segment.
- [ ] Infrared scan of the repaired connection under load.

**UPS module** (check IDs: `ups_normal_mode`, `redundancy_restored`)

- [ ] UPS in normal (double-conversion) mode with all modules healthy.
- [ ] Redundancy confirmed from the NMC, not from the work order.

**Generator** (check IDs: `gen_loaded_run`)

- [ ] EMCP records a start and a run at 30% of nameplate or more for 30 minutes.

**CDU component (pump, filter, sensor)** (check IDs: `cdu_flow_baseline`, `pump_failover_test`)

- [ ] Flow, supply temperature, and return temperature within baseline.
- [ ] Pump redundancy confirmed by failover test; leak alarms clear; coolant conductivity and pH within specification after any fluid work.

**Chiller, pump, or air handler** (check IDs: `unit_in_service`, `plant_redundancy`)

- [ ] Unit running in auto with no active alarms.
- [ ] Plant or hall redundancy restored at current load.

**Leak detection zone** (check IDs: `leak_hold_30m`, `cable_continuity`)

- [ ] 30-minute hold with no leak alarm.
- [ ] Cable continuity and circuit healthy on the TTDM-128.

**Fire protection system** (check IDs: `fire_test`, `impairment_closed`)

- [ ] Function test under NFPA 72 or NFPA 25 passed.
- [ ] Impairment closed with the Customer notified.

## 11. Maintenance Requirements

A maintenance task counts as done only when telemetry or badge records confirm it.

| System | Task | Requirement | Frequency |
|---|---|---|---|
| Generators | Monthly loaded exercise | At least 30% of nameplate kW for 30 minutes (NFPA 110), recorded by the EMCP. | Monthly |
| Generators | Supplemental load bank | 50% of nameplate for 30 minutes then 75% for 60 minutes when monthly tests did not reach 30%. | Annual |
| Generators | Endurance test | 4 continuous hours under load (NFPA 110, Level 1). | Every 36 months |
| Generators | Fuel quality test | Sampled and tested; results on file. | Annual |
| UPS and batteries | Preventive maintenance and battery health check | Manufacturer schedule and NFPA 70B. | Semiannual |
| Switchgear and busway | Infrared thermography under load | NFPA 70B. | Annual |
| CDUs | Filter change and coolant sample | Manufacturer schedule; conductivity, pH, and inhibitor within specification. | Quarterly |
| Chillers | Preventive maintenance | Manufacturer schedule; refrigerant work by EPA 608 certified technicians. | Quarterly |
| Fire protection | Inspection and testing | NFPA 72 and NFPA 25 intervals; VESDA per manufacturer. | Per code |

## 12. Service Level Credits and Earnback

- **At-Risk Amount:** 10% of monthly charges (illustratively $1,180,000/month, so **$118,000** at risk each month).
- **Pool:** Credit allocations across all Critical Service Levels total 190% of the At-Risk Amount (pool limit 200%), with no single CSL above 40%. A pool above 100% concentrates financial attention on the Customer's priorities while the monthly cap protects the Supplier.
- **Credit formula:** Credit = At-Risk Amount × CSL allocation %.
- **Monthly cap:** Total credits in a Measurement Period never exceed the At-Risk Amount.
- **Repeat defaults:** A Minimum Service Level Default on the same CSL for 3 consecutive periods earns 2× the credit. Doubled credits are not eligible for Earnback.
- **Earnback:** Supplier earns back a Service Level Credit for a Critical Service Level if it meets or exceeds the Expected Service Level for that same Critical Service Level in each of the 3 Measurement Periods immediately following the default. Earnback is not available when:
  - The credit was doubled under the repeat-default rule.
  - The default involved a confirmed Record Integrity finding (AGG-INTEGRITY).
  - The default involved an EHS or security event (AGG-EHS, AGG-SECURITY).
- **Application:** Credits are applied against the next month's rent and services fees.
- **EHS Credits:** handled separately under Section 22; outside this monthly cap and never earned back.
- **Nature of credits:** Service Level Credits are a rent adjustment reflecting reduced value of the leased capacity. They are not a penalty and do not limit the Customer's other rights under the Lease, including chronic failure rights and EHS Credits.

See Appendix B.1 for worked credit examples.

 Chronic Failure and Termination

## 13. Chronic Failure

Any of the following is a Chronic Failure:

- **CF-1:** A Minimum Service Level Default on the same CSL in 3 consecutive Measurement Periods.
- **CF-2:** A Minimum Service Level Default on the same CSL in any 4 of 6 rolling Measurement Periods.
- **CF-3:** Total Service Level Credits over 50% of the cumulative At-Risk Amount in any rolling 6 Measurement Periods.
- **CF-4:** Any confirmed deliberate falsification of records.

On a Chronic Failure, the Customer may:

- Terminate the affected services or the entire Site scope for cause, without termination charges.
- Require a Supplier executive-sponsored recovery plan within 10 business days.
- Step-in: the Customer or a third party may perform the affected services at the Supplier's cost during recovery.

## 14. Excused Events

The Supplier must claim an Excused Event within 5 business days, with supporting evidence. Only the following qualify:

- Force majeure as defined in the Agreement.
- Failures attributed to another party under the Interface Agreement, for the time that party's fault is active (the Supplier must still respond, protect equipment, and notify).
- Customer-caused delays, including withheld access or Customer-requested holds recorded in the ticket or work order.
- Approved maintenance inside an approved change window, within the approved duration.
- OEM part unavailability, ONLY if Customer spares for that FRU class were at or above minimum stock and the Supplier notified the Customer within 4 hours.

**Treatment:** The excused occurrence is removed from both the numerator and the denominator of the affected service level. The rest of the Measurement Period is still measured.

**Supplier duty:** The Supplier must use commercially reasonable efforts to perform despite the Excused Event.

## 15. Root Cause Analysis and Corrective Action

**Triggers:**

- Any Expected or Minimum Service Level Default.
- Any Key Measurement miss.
- Any P1 incident.
- Any Lemon Unit.
- Any Record Integrity Finding.
- Any reopened ticket or work order (TR-1 or TR-2).

**Timelines:** P1 preliminary RCA within 24 hours; P1 final RCA within 5 business days; all other RCAs within 10 business days.

**Corrective action plan (CAP) requirements:**

- Root cause stated in terms of process, people, parts, or tooling; not 'technician error' alone.
- Each action has a single named owner, a due date, and an evidence-of-completion definition.
- Effectiveness check: the triggering metric is reviewed for 2 Measurement Periods after closure.

**Overdue CAPs:** CAPs more than 10 business days overdue escalate to the monthly service review.

## 16. Governance and Reporting Cadence

| Forum | Frequency | Attendees | Inputs |
|---|---|---|---|
| Daily operations standup | Daily, 15 minutes | Supplier shift leads; Customer site lead | Open P1 and P2 incidents, today's deployment plan, blockers, spares alerts. |
| Weekly operations review | Weekly | Supplier site manager; Customer site lead | Automated weekly scorecard, breach severity log, CAP status, staffing, lemon units. |
| Monthly service review | Monthly | Supplier account manager; Customer DCO leadership | Service Level Report, credits and earnback, chronic-failure watch, trends. |
| Quarterly business review | Quarterly | Supplier executive sponsor; Customer DCO leadership | Trend analysis, SLA change proposals, roadmap and capacity plan, program-wide lessons learned. |

## 17. Staffing and Qualifications

**Coverage:** 24x7x365 on site.

| Shift | Engineers | Shift leads |
|---|:-:|:-:|
| Day (07:00 to 19:00 local) | 3 | 1 |
| Night (19:00 to 07:00 local) | 2 | 1 |

**Key personnel:**

- Chief engineer (named; replacement requires 30 days notice and Customer consultation)
- EHS coordinator

**Required qualifications:**

- NFPA 70E qualified person for the electrical tasks performed
- Manufacturer training for Galaxy UPS, CHx2000 CDUs, and Cat EMCP 4.4
- EPA Section 608 certification for refrigerant work
- Lockout/tagout and group lockout
- Customer site security and escort procedures

Only badge-verified hours by engineers with current qualifications count toward OT-CSL-09.

## 18. Change Management

- All non-emergency changes require Customer change approval before work starts.
- Standard changes (pre-approved runbook FRU swaps) may proceed under an open incident.
- Emergency changes require verbal approval from the Customer Incident Commander, recorded in the ticket or work order within 1 hour.
- Work outside the approved window or scope is an unauthorized change and counts against KM-10.

**Landlord critical systems:** Changes to critical power, cooling, or fire systems require an approved MOP, notice under the Interface Agreement, and a Customer-approved window when redundancy is reduced. Coordination across parties follows the Interface Agreement.

## 19. Security and Chain of Custody

- Badge access only for Customer-approved personnel; no tailgating; visitors escorted at all times.
- Daily reconciliation of badge records against the shift roster.
- Storage media (e.g., E1.S drives) never leave the Site intact; media is sanitized or destroyed on site under the Customer's media sanitization standard, with a certificate per serial number.
- Every failed part is logged into chain of custody at removal, with serial, ticket or work order, technician, and timestamp.
- Cameras and photography in the data hall are prohibited except for Customer-approved documentation.

**Incident reporting:** Suspected security incidents are reported to the Customer within 1 hour of discovery.

## 20. Environmental, Health, and Safety

These terms are common to every partner SLA at the Site and bind every subcontractor. They are not subject to the monthly credit cap and cannot be weakened by any partner SLA.

### 20.1 Principles

- Safety is never traded for speed, schedule, or a service level. No target in any partner SLA justifies an unsafe act.
- Every person on Site has stop-work authority and must use it for any unsafe condition. Stopping work is never a violation and never counts against a service level.
- Consequences attach to confirmed violations of required controls, never to injuries, illnesses, or near misses that are reported. Reporting is protected (29 CFR 1904.35(b)(1)(iv)).
- Where a regulation and a requirement below differ, the more protective one applies.

### 20.2 Required standards

Each partner complies with the edition in force; where an edition is shown, it is the edition current when this SLA version was issued.

| ID | Standard | Edition | Applies to |
|---|---|:-:|---|
| OSHA-1910 | OSHA 29 CFR 1910, General Industry | In force | All work. Includes Subpart S (electrical), 1910.147 (hazardous energy control), 1910.132 to .138 (PPE, including 1910.137 electrical protective equipment), 1910.1200 (hazard communication: PG25 coolant, diesel, lithium-ion), 1910.178 (powered industrial trucks), 1910.95 (noise), 1910.38 and .39 (emergency action and fire prevention plans), and Subpart D (walking-working surfaces). |
| OSHA-1926 | OSHA 29 CFR 1926, Construction | In force | Build-out, fit-out, and installation work during deployment, including Subpart K (electrical) and Subpart M (fall protection). |
| OSHA-1904 | OSHA 29 CFR 1904, Recordkeeping and Reporting | In force | Injury and illness records, severe-injury reporting (1904.39), and the prohibition on discouraging reports (1904.35). |
| OSHA-GDC | OSH Act Section 5(a)(1), General Duty Clause | In force | Recognized hazards without a specific standard, including heat stress. Texas has no state plan; federal OSHA has jurisdiction. |
| NFPA-70E | NFPA 70E, Standard for Electrical Safety in the Workplace | 2027 | Electrical safety program, qualified persons, energized work permits, approach boundaries, arc flash and shock PPE, battery and DC systems. |
| NFPA-70B | NFPA 70B, Standard for Electrical Equipment Maintenance | 2026 | Documented electrical maintenance program; supports the 70E condition-of-maintenance assumption. |
| NFPA-855 | NFPA 855, Installation of Stationary Energy Storage Systems | 2026 | Lithium-ion UPS battery rooms and any energy storage in the 800 VDC pilot. |
| NFPA-110 | NFPA 110, Emergency and Standby Power Systems | In force | Generator testing and maintenance, including safe running-equipment practices. |
| NFPA-72-25 | NFPA 72 and NFPA 25 | In force | Fire alarm and water-based fire protection inspection, testing, and impairment handling. |
| NFPA-51B | NFPA 51B, Fire Prevention During Welding, Cutting, and Other Hot Work | In force | Hot work permits and fire watch. |
| ISO-45001 | ISO 45001:2018 or ANSI/ASSP Z10.0 | In force | Each partner operates an occupational health and safety management system aligned to one of these. |

### 20.3 Site safety rules

| ID | Rule | Requirement | Standards |
|---|---|---|---|
| EHS-R1 | Pre-task planning | Every non-routine task starts with a written job hazard analysis and a job briefing covering hazards, energy sources, boundaries, PPE, and emergency response. | NFPA-70E, OSHA-1910 |
| EHS-R2 | Hazardous energy control | Lockout/tagout under a written, task-specific procedure for any work requiring de-energization, with test-before-touch absence-of-voltage verification by a qualified person. Group lockout for multi-partner work, with every worker applying a personal lock. | OSHA-1910, NFPA-70E |
| EHS-R3 | Energized electrical work | Prohibited unless de-energizing creates a greater hazard or is infeasible, and then only under an energized electrical work permit approved in advance by the Customer. Where the permit specifies shock or arc flash PPE, a second person trained in contact release and emergency response is present outside the boundary, as NFPA 70E (2027) requires. Arc flash labels and the incident energy study are kept current. | NFPA-70E, OSHA-1910 |
| EHS-R4 | Battery rooms and DC systems | Work on lithium-ion UPS batteries and any 800 VDC equipment requires a risk assessment that addresses chemical, contact thermal, shock, and arc flash hazards, PPE for each, authorized entry only, and the battery system's emergency procedures. | NFPA-70E, NFPA-855 |
| EHS-R5 | Liquid cooling and coolant | Safety data sheets for PG25 coolant on hand; spill kits at every CDU and row end; quick-disconnect service only on isolated loops; leak alarms answered under the site spill procedure. | OSHA-1910 |
| EHS-R6 | Rack and heavy equipment moves | Racks (well over a metric ton loaded) move only on rated powered equipment run by trained operators, with a route survey, floor-load check, and a dedicated spotter. Team lifts and lift assists for trays and power shelves. | OSHA-1910 |
| EHS-R7 | Heat illness prevention | A written heat illness prevention plan for outdoor work (generator and chiller yards) and hot aisles. At a heat index of 80 F: drinking water, shade, and acclimatization for new and returning workers. At 90 F: at least 15 minutes of rest in shade every 2 hours, buddy system or check-ins, and observation for heat illness. Thresholds are modeled on OSHA's proposed heat rule; the rule is not final, so this agreement makes them binding. | OSHA-GDC |
| EHS-R8 | Generators and running equipment | Hearing protection in posted areas; exclusion zones around running engines and during load-bank tests; diesel spills handled under the site spill procedure. | OSHA-1910, NFPA-110 |
| EHS-R9 | Working at height | Rated ladders and platforms for overhead busway and cable tray work; fall protection where required; no standing on racks, CDUs, or containment. | OSHA-1910, OSHA-1926 |
| EHS-R10 | Working alone | No lone work on energized equipment, in battery rooms, or outdoors at a heat index of 90 F or above. Other lone work requires check-ins at least every 60 minutes. | NFPA-70E, OSHA-GDC |
| EHS-R11 | Hot work and fire protection impairment | Hot work only under permit with a fire watch. Any impairment of fire alarm, detection, or suppression is notified to the Customer before it begins and tracked to restoration. | NFPA-51B, NFPA-72-25 |
| EHS-R12 | Electrostatic discharge | ESD-safe handling for all electronic components (equipment protection, tracked with the safety rules). | Site rule |

### 20.4 Partner qualification

- Experience Modification Rate (EMR) of 1.0 or lower, or a Customer-approved improvement plan.
- Three years of injury rates (TRIR and DART) and five years of OSHA citation history disclosed before mobilization and annually.
- Workers' compensation coverage for every person on Site. Texas allows employers to opt out of workers' compensation; partners at this Site may not.
- A written safety program and a named, on-site EHS coordinator.
- Training records on Site for every worker: NFPA 70E qualified-person training for electrical tasks, lockout/tagout, powered equipment operation, heat illness, hazard communication, and site orientation. Supervisors hold OSHA 30-hour training.
- Subcontractors meet the same requirements; the partner remains responsible for them.

### 20.5 Reporting

- **Injuries and recordables:** to the Customer within 1 hour.
- **Near misses:** within 24 hours.
- **Severe events:** Fatalities, in-patient hospitalizations, amputations, and losses of an eye are reported to the Customer immediately and to OSHA within the 29 CFR 1904.39 deadlines (8 hours for a fatality, 24 hours for the others).
- **Monthly:** Hours worked, recordables, near misses, stop-work uses, permits issued, and open corrective actions, by partner.

### 20.6 Independent investigation

- **Trigger:** Any suspected violation of a site rule or standard above, from any source: observation, audit, telemetry, permit and badge records, or a report.
- **Investigator:** Customer EHS, or an independent third-party Certified Safety Professional engaged by the Customer. The partner whose work is investigated may not lead the investigation.
- **Partner response:** within 5 business days of notice, before a finding is confirmed.
- **Standard of proof:** Preponderance of the evidence.
- **Evidence:** Permits, job hazard analyses, lockout records, telemetry (for example, power present on a circuit recorded as locked out), badge records, witness statements, and photographs taken for the investigation.
- **Disputes:** Disputed findings go to the monthly service review, then to the independent Certified Safety Professional, whose determination of fact is final for EHS credits.

### 20.7 Violation classes and consequences

EHS Credits apply only to violations confirmed by the investigation above. Amounts are a percentage of the partner's own monthly charges (illustrated at $1,180,000/month for this SLA).

| Class | Examples | EHS Credit | Consequences |
|---|---|:-:|---|
| EHS-C1 Life-critical | Energized electrical work without an approved permit, or without the required second person.<br>Lockout/tagout not applied or not verified before work.<br>Entering an arc flash or shock boundary without the required PPE.<br>Bypassing or defeating a safety interlock, guard, or fire protection system.<br>A rack move without the required equipment, operator, or spotter. | 1.0% ($11,800) | Immediate stop of the task and removal of the individuals involved from Site work pending review.<br>Partner-wide safety stand-down at the Site within 24 hours.<br>Root cause analysis and corrective action plan within 5 business days.<br>Internal severity S1.<br>Customer's investigation and stand-down costs reimbursed. |
| EHS-C2 Serious | Work performed without a required job hazard analysis or permit, where no life-critical control was missed.<br>A worker performing a task without current required qualification.<br>Required PPE missing outside a hazard boundary.<br>Heat illness controls not provided at a triggering heat index. | 0.25% ($2,950) | Correction before work resumes.<br>Corrective action plan within 10 business days.<br>Internal severity S2. |
| EHS-C3 Administrative | Incomplete or late paperwork where the required control was in place.<br>Training records not available on Site. | None | Corrected and tracked in the weekly operations review.<br>Internal severity S3. |

### 20.8 EHS Credits

- **Outside the monthly cap:** EHS Credits are never counted toward, or limited by, the monthly cap in Section 12.
- **No earnback:** EHS Credits are never eligible for Earnback.
- **Repeat violations:** a second EHS-C1 violation within 90 days carries 2× the EHS Credit.
- **Self-reporting and concealment:** A violation the partner reports to the Customer within the reporting window and corrects before work resumes has its EHS Credit reduced by the percentage above. A violation the partner knew of and did not report, or whose records were altered, has its EHS Credit multiplied as above and is also a record-integrity finding. (Reduction: 50%. Concealment multiplier: 2×.)
- **Never based on reporting:** No EHS Credit, charge, or adverse action is ever based on the number of injuries, illnesses, or near misses reported, or on the use of stop-work authority.
- **Cost recovery:** For Life-critical violations, the partner also reimburses the Customer's documented costs of the independent investigation and of any Customer-directed stand-down.
- **Nature of EHS Credits:** EHS Credits are a price adjustment reflecting that services were not delivered to the contracted safety standard. Their amounts are a reasonable pre-estimate of costs the Customer incurs from a confirmed violation (investigation, re-verification of affected work, and operational disruption), which are real but impractical to quantify in advance. They are not a penalty, are not subject to the monthly credit cap, cannot be earned back, and do not limit the Customer's other rights, including recovery of actual costs and termination.

### 20.9 Escalation and termination

- Two Life-critical violations by one partner in any rolling 90 days: executive review and a partner-wide safety improvement plan approved by the Customer.
- Three Life-critical violations by one partner in any rolling 12 months, or one resulting in a fatality or permanent disability: a material breach, giving the Customer the right to terminate for cause.
- The Customer may require removal of any individual from Site work for safety reasons at any time.

See Appendix B.2 for a worked example.

## 21. Spares

Spares are Landlord-owned and Landlord-managed.

| Field-replaceable unit | Minimum stock per hall |
|---|:-:|
| UPS power module | 1 |
| CDU pump assembly | 1 |
| CDU filter set | 4 |
| Busway tap-off unit | 2 |
| Thermal-wall fan assembly | 1 |
| VFD | 1 |

- **Reorder:** Replenished within 10 business days of use.
- **Cycle counts:** Quarterly, reported to the Customer.

## 22. Energy Reporting and PUE

The Landlord reports the site's energy use every month from the meters it operates, so the Customer can track power usage effectiveness (PUE) from the same records. The PUE target is a Key Measurement with no service credits; a miss calls for an energy improvement plan.

- **Standard:** ISO/IEC 30134-2:2026, Power usage effectiveness (PUE). PUE is total facility energy divided by IT energy, both measured as energy over the period.
- **Total facility energy:** Energy delivered to the site by the utility (revenue meters on MV-A and MV-B) and by the generators while they carry the site. Generator energy into a portable load bank during a test is not facility energy.
- **IT energy:** Measured at the UPS outputs of each hall. UPS losses are facility overhead, not IT load.
- **Partial PUE:** Cooling (chiller yard, facility water pumps, mechanical UPS for CDUs and thermal walls, electrical-room CRAHs) and the power path (UPS losses and distribution losses) are reported separately, so the overhead can be traced to its source.

| ID | Term | Requirement |
|---|---|---|
| OT-EN-01 | Monthly Energy Report | By the fifth business day of each month, the Landlord submits total facility energy, IT energy, PUE, and partial PUE for the prior period, with the meters used. The figures must reconcile with the meter data in the Customer's facility feed within rounding. |
| OT-EN-02 | PUE Over 52 Weeks | PUE over the most recent 52 weeks at most 1.35. Key Measurement; no service credits. A miss requires an energy improvement plan within 30 days. |
| OT-EN-03 | Free-Cooling Availability | Free cooling (economizer) on a chiller may be disabled for more than 24 hours only under an approved MOP or change record. A lockout left in place after maintenance is a records discrepancy and is reported with its estimated energy cost. |

## 23. SLA Change Control and Continuous Improvement

- Promote a Key Measurement to a Critical Service Level, or demote a CSL, with 90 days notice (maximum 2 changes per contract year).
- Reallocate credit allocation percentages with 90 days notice, within the pool and per-CSL caps.
- Add new service levels; targets are set from 6 months of measured baseline, or by mutual agreement.

**Continuous improvement:** At each contract anniversary, the Expected and Minimum levels of each CSL tighten by 10% of the remaining gap to perfect performance, using the trailing 12 months of results, unless the parties agree otherwise.

**Versioning:** Every change to this file is a new SLA version, reviewed through pull request and approved by both parties.

---

## Appendix A: Internal Breach Severity Index

> **Customer-internal.** Translates a breach into a single severity so readers immediately understand how serious it was. Severity is the worst level across all dimensions, then adjusted by aggravators. This index guides escalation only. It is not a contractual remedy and is not shared with the Supplier.

### A.1 Severity levels

| Level | Name | Escalation |
|---|---|---|
| **S1** | Critical | Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review. |
| **S2** | Major | Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure. |
| **S3** | Minor | Supplier RCA within 10 business days; discussed in the weekly operations review. |
| **S4** | Watch | Logged and trended in the weekly scorecard; no formal action unless it repeats. |

### A.2 Event breaches (a single late incident)

Severity is the **worse** of the two dimensions below, then adjusted by aggravators.

| Level | Overrun past target | GPU-hours lost beyond target |
|---|:-:|:-:|
| S4 Watch | ≤ 10% | ≤ 72 |
| S3 Minor | 10 to 50% | 72 to 500 |
| S2 Major | 50 to 200% | 500 to 5,000 |
| S1 Critical | > 200% | > 5,000 |

- **Overrun:** How far past the target time the event ran: (actual - target) / target.
- **GPU-hours:** GPU-hours lost after the target expired (GPUs affected x hours late). 72 GPU-hours = one NVL72 rack-hour.

### A.3 Period breaches (a CSL over a week or month)

| Condition | Level |
|---|:-:|
| Expected level met; no breach. | None |
| Below Expected but at or above Minimum. | S4 |
| Below Minimum (credit-bearing default). | S3 |
| Below Minimum by more than the Expected-to-Minimum gap. | S2 |
| Minimum default on the same CSL for 3 or more consecutive periods (chronic failure CF-1). | S1 |

### A.4 Aggravators

| ID | Trigger | Effect |
|---|---|---|
| AGG-REPEAT | Same CSL or same Service Unit breached within the previous 30 days. | Raise by 1 level |
| AGG-RACKWIDE | Breach affected an entire NVL72 rack or a CDU loop. | Raise to at least S2 |
| AGG-INTEGRITY | Breach involved a Record Integrity Finding (vendor record contradicted by telemetry). | Raise to at least S1 |
| AGG-EHS | Breach involved an EHS recordable, stop-work event, or uncontained leak. | Raise to at least S1 |
| AGG-SECURITY | Breach involved a security or chain-of-custody failure. | Raise to at least S1 |

Aggravators adjust an existing breach; they never create one.

### A.5 Discrepancy types

The discrepancy engine reports each mismatch between vendor records and the Telemetry of Record as one of these types. Severity starts at the base level (or the event-breach level, if a restore target was missed) and the listed aggravators are then applied.

| Type | Base | Aggravators | SLA references | Recommended corrective action |
|---|:-:|---|---|---|
| Generator test reported without load (`gen_test_no_load`) | S2 | AGG-INTEGRITY | OT-CSL-06, OT-KM-02, OT-CSL-08 | Recount the test as not done. Confirm EMCP data for every generator test in the period and schedule a compliant test. |
| Maintenance closed without evidence (`pm_without_evidence`) | S2 | AGG-INTEGRITY | OT-CSL-06, OT-CSL-08 | Reopen the task. Audit the engineer's other closures in the period against badge and device records. |
| BMS override or alarm inhibit without a change record (`bms_override_unrecorded`) | S1 | AGG-INTEGRITY | OT-CSL-07, OT-KM-05 | Release the override or inhibit, or record it under an approved change with an expiry. Review alarm suppression controls. |
| Alarm acknowledged but never dispatched (`alarm_acked_no_dispatch`) | S2 | None | OT-CSL-04, OT-CSL-05 | Recalculate response from badge evidence. Review the acknowledgment workflow so an acknowledgment cannot stand in for a response. |
| Work order restored before the telemetry (`landlord_clock_shift`) | S2 | AGG-INTEGRITY | OT-CSL-05, OT-CSL-08 | Recalculate restoration from the device telemetry. Confirm work orders take their restore time from the telemetry, not from the engineer's entry. |
| Fault attributed to another party against the telemetry (`attribution_contradicted`) | S1 | AGG-INTEGRITY | OT-CSL-01, OT-CSL-02, OT-CSL-08 | Apply the Interface Agreement attribution rules from the Telemetry of Record and correct the work order. Review with both parties at the monthly service review. |
| Critical work without an approved MOP (`critical_work_no_mop`) | S1 | None | OT-CSL-07 | Stop similar work until MOP control is confirmed. Joint review with the Customer change board. |

## Appendix B: Worked Examples

*These examples are computed by `src/scorecard/sla_model.py` from this SLA's own parameters every time the document is generated, so the document and the scoring engine always agree.*

### B.1 Service Level Credits

**Single default: OT-CSL-03 (cooling within band) misses Minimum once.** At-Risk Amount $118,000 (10% of $1,180,000) × 30% allocation = $35,400. **Credit: $35,400.** Earnback eligible: Yes.

**Integrity-aggravated default: OT-CSL-06 (maintenance) misses Minimum after generator tests were reported without load.** At-Risk Amount $118,000 (10% of $1,180,000) × 20% allocation = $23,600. **Credit: $23,600.** Earnback eligible: No.

**Monthly cap.** A severe month with Minimum defaults on OT-CSL-01, OT-CSL-03, OT-CSL-05, OT-CSL-06, and OT-CSL-08: uncapped credits total $147,500 (125% of the At-Risk Amount). The cap limits the payable credit to **$118,000**.

### B.2 EHS Credits

Three violations confirmed by independent investigation in one quarter, at $1,180,000/month:

| Violation | Class | Confirmed | Base | Adjustments | EHS Credit |
|---|---|:-:|:-:|---|:-:|
| EHS-1: busway tap-off worked with no lockout applied | EHS-C1 | 2026-10-06 | $11,800 | None | **$11,800** |
| EHS-2: energized work permit without the second person, self-reported | EHS-C1 | 2026-11-17 | $11,800 | repeat within 90 days: x2; self-reported and corrected: -50% | **$11,800** |
| EHS-3: expired qualification, roster altered to hide it | EHS-C2 | 2026-12-01 | $2,950 | concealed: x2; also a record-integrity finding | **$5,900** |

Total EHS Credits: **$29,500**, payable in addition to any Service Level Credits for the same months and not reduced by the monthly cap.

---

*Generated from `sla/ot_partner.yaml` and the common terms in `sla/common.yaml` (schema 1.0, SLA version 1.0.0, common terms version 1.3.0). This is a fictional, illustrative landlord service level agreement created for a portfolio demonstration. All parties, sites, quantities, prices, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.*
