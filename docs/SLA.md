<!--
  GENERATED FILE. DO NOT EDIT BY HAND.
  Source: sla/vendor_sla.yaml  |  Generator: scripts/render_sla.py
  Edit the YAML and re-run: python scripts/render_sla.py
-->

# Service Level Agreement: Partner-Operated GPU Site Operations

**Schedule B (Service Levels) to the Master Services Agreement**

> **MOCK / ILLUSTRATIVE.** This is a fictional, illustrative service level agreement created for a portfolio demonstration. All parties, sites, quantities, prices, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.

| Document ID | Version | Effective date | Term | Timezone |
|---|---|---|---|---|
| SLA-RSS-AUS1-001 | 1.0.0 | 2026-10-05 | 36 months | UTC |

## Contents

1. [Purpose and Structure](#1-purpose-and-structure)
2. [Parties and Site Profile](#2-parties-and-site-profile)
3. [Definitions](#3-definitions)
4. [Scope and Responsibility Matrix](#4-scope-and-responsibility-matrix)
5. [Incident Priority Matrix](#5-incident-priority-matrix)
6. [Measurement and Telemetry of Record](#6-measurement-and-telemetry-of-record)
7. [Critical Service Levels](#7-critical-service-levels)
8. [Key Measurements](#8-key-measurements)
9. [Return-to-Service Validation Requirements](#9-return-to-service-validation-requirements)
10. [Deployment Milestones](#10-deployment-milestones)
11. [Service Level Credits and Earnback](#11-service-level-credits-and-earnback)
12. [Chronic Failure and Termination](#12-chronic-failure-and-termination)
13. [Excused Events](#13-excused-events)
14. [Root Cause Analysis and Corrective Action](#14-root-cause-analysis-and-corrective-action)
15. [Governance and Reporting Cadence](#15-governance-and-reporting-cadence)
16. [Staffing and Qualifications](#16-staffing-and-qualifications)
17. [Change Management](#17-change-management)
18. [Security and Chain of Custody](#18-security-and-chain-of-custody)
19. [Environmental, Health, and Safety](#19-environmental-health-and-safety)
20. [Spares and RMA](#20-spares-and-rma)
21. [SLA Change Control and Continuous Improvement](#21-sla-change-control-and-continuous-improvement)
- [Appendix A: Internal Breach Severity Index](#appendix-a-internal-breach-severity-index)
- [Appendix B: Worked Examples](#appendix-b-worked-examples)

---

## 1. Purpose and Structure

This Schedule defines the service levels Ridgeline Site Services, LLC ("Supplier") must meet when operating the Site AUS-1 (fictional) on behalf of the Customer, how performance is measured, and what happens when service levels are missed.

The structure follows standard outsourcing practice. Each service level has an **Expected** level (missing it triggers root cause analysis) and a **Minimum** level (missing it triggers a Service Level Credit). Service levels are split into **Critical Service Levels**, which carry credits, and **Key Measurements**, which do not carry credits but drive corrective action and can be promoted to Critical Service Levels.

Two principles shape this agreement:

1. **Telemetry of Record.** Performance is measured from Customer-operated monitoring and inventory systems, not from Supplier self-reporting. Restoration clocks start at the first machine-detected evidence of a fault.
2. **"Fixed" means validated.** A repair is complete only when the component passes its Return-to-Service validation checks. Clocks stop at Validated Return to Service, not when a ticket is closed.

## 2. Parties and Site Profile

| Party | Name | Role |
|---|---|---|
| Customer | Customer | Owns site outcomes; directs priorities; operates the telemetry of record. |
| Supplier | Ridgeline Site Services, LLC *(fictional)* | Performs deployment, break-fix, and data hall operations under Customer direction. |
| Facility Provider | Facility Provider | Separate contract. Named here only to define ownership boundaries. |
| OEM / Integrator | OEM / System Integrator | Separate contract. Named here only to define ownership boundaries. |

**Site:** Site AUS-1 (fictional). **Platform:** NVIDIA GB200 NVL72 (rack-scale, direct-to-chip liquid cooled).

| Hall | State | Racks | GPUs |
|---|---|---|---|
| HALL-A | production | 32 | 2,304 |
| HALL-B | deployment | 32 | 2,304 |
| **Total** | | **64** | **4,608** |

Each rack contains 72 GPUs and 36 CPUs across 18 compute trays (4 GPUs per tray), 9 NVLink switch trays, and 8 power shelves, at roughly 120 kW nominal. Cooling is provided by 8 in-row liquid-to-liquid CDUs rated 1.3 MW, each serving up to 8 racks.

**Service units.** Impact is scored by the service unit affected:

| Service unit | GPUs affected | Note |
|---|---|---|
| Compute tray | 4 | Smallest GPU field-replaceable service unit. |
| NVLink switch tray | 72 | Treated as a rack-wide event until degraded operation is proven safe. |
| NVL72 rack | 72 | One NVLink domain; the Customer's smallest large-job scheduling unit. |
| CDU loop | 576 | One CDU serves up to 8 racks; a loss of cooling can affect all of them. |

## 3. Definitions

| Term | Definition |
|---|---|
| **Fault Detection Time (T0)** | The earliest timestamp at which a fault is evidenced by any Telemetry of Record source, a Supplier ticket, or a Customer notification, whichever is earliest. All restoration clocks start at T0. |
| **Acknowledge** | A qualified Supplier person has accepted the incident in the ticketing system and posted an initial assessment. Automated acknowledgments do not count. |
| **Engaged On-Site** | A qualified Supplier technician is physically at the affected equipment, as evidenced by badge access to the relevant data hall and a ticket work note. |
| **Containment** | For leak or safety incidents, the hazard is isolated and no longer spreading (e.g., affected loop isolated, fluid contained, area secured). |
| **Restore** | The affected Service Unit is returned to production, or an approved workaround returns the affected capacity to the Customer scheduler. |
| **Validated Return to Service (Validated RTS)** | Restore, plus complete evidence that every check in the Return-to-Service Validation Requirements for that component class passed. The restoration clock stops only at Validated RTS. |
| **Telemetry of Record** | The Customer-operated monitoring and inventory systems listed in the Measurement section. They are authoritative for all timing, inventory, and health measurements under this SLA. |
| **Supplier-Attributable Unavailability** | Time during which installed GPU capacity is unavailable and the next required action belongs to the Supplier (dispatch, diagnosis, repair, validation, or documentation). |
| **First-Time Fix** | A repair that reaches Validated RTS on the first attempt and does not experience a Same-Fault Recurrence within 7 days. |
| **Same-Fault Recurrence** | A new fault on the same Service Unit serial number in the same fault class (e.g., the same XID family, the same port, the same leak location). |
| **Repeat Failure** | Any fault on a Service Unit serial number within 30 days after it reached Validated RTS, regardless of fault class. |
| **Lemon Unit** | A Service Unit with 3 or more repair events within any rolling 30 days. |
| **Record Integrity Finding** | A closed ticket whose recorded actions or timestamps do not reconcile with the Telemetry of Record (e.g., a part swap claimed with no serial change in inventory, or a repair time that disagrees with telemetry by more than 15 minutes). |
| **GPU-Hours Lost** | The number of GPUs in the affected Service Unit multiplied by the hours of unavailability. Used for impact scoring; one NVL72 rack-hour equals 72 GPU-hours. |
| **Measurement Period** | One calendar month. Performance is also tracked weekly for the operating scorecard. |
| **Expected Service Level** | The level of performance the Supplier is expected to deliver. Missing it triggers a root cause analysis but no credit. |
| **Minimum Service Level** | The floor of acceptable performance. Missing it is a Minimum Service Level Default and triggers a Service Level Credit. |
| **Excused Event** | An event listed in the Excused Events section, claimed by the Supplier on time and approved by the Customer, that removes the affected occurrence from the calculation of a service level. |

## 4. Scope and Responsibility Matrix

### 4.1 In-scope services

| ID | Service | Description |
|---|---|---|
| SVC-BF | Break-fix | Triage, diagnosis, and replacement of field-replaceable units (compute trays, NVLink switch trays, power shelves and PSUs, optics, cables, E1.S drives, fans, management components) using Customer-owned spares. |
| SVC-DEP | Deployment | Rack receiving, inspection, placement, power and liquid connection, leak testing, cabling, power-on, firmware baselining, and burn-in through Validated Handoff. |
| SVC-LC | Liquid-cooling operations (rack side) | Rack manifolds, quick-disconnects, tray-level leak response, and secondary-loop CDU monitoring and first response, in coordination with the Facility Provider. |
| SVC-NET | Physical network operations | Optic and cable replacement, fiber cleaning and inspection, port troubleshooting, and labeling for back-end, front-end, and OOB networks. |
| SVC-RMA | Spares and RMA logistics | Spares cage management, cycle counts, failed-part handling, chain of custody, and RMA shipment to the OEM. |
| SVC-IR | Incident response support | 24x7 on-site response under the direction of the Customer Incident Commander, including post-incident data collection. |

### 4.2 Out of scope

- Building power, generators, UPS, and switchgear (Facility Provider).
- Facility water plant and primary-side cooling (Facility Provider).
- Logical configuration of Customer networks and workloads (Customer).
- Board-level repair and OEM warranty adjudication (OEM).

### 4.3 Break-fix ownership matrix (RACI)

**R** = Responsible: performs the work; **A** = Accountable: owns the outcome and approves; **C** = Consulted; **I** = Informed.

| Component | Supplier | Customer | Facility Provider | OEM |
|---|:-:|:-:|:-:|:-:|
| Compute tray (GPU, CPU, memory, cold plate) | R | A | I | C |
| NVLink switch tray and NVLink backplane | R | A | I | C |
| Power shelves and PSUs (in-rack) | R | A | C | C |
| Rack busbar, whips, and upstream PDUs and busway | C | A | R | I |
| Rack manifold and quick-disconnects | R | A | C | C |
| CDU (secondary loop: monitoring, first response, pumps, filters) | R | A | C | C |
| Facility water and primary loop | I | C | A/R | I |
| Back-end fabric optics, cables, and fiber | R | A | I | C |
| Leaf and spine switches (physical replacement) | R | A | I | C |
| BMC and out-of-band management network (physical) | R | A | I | C |
| Spares cage, inventory, and RMA shipments | R | A | I | C |
| Physical security of the Customer cage | R | A | R | I |

## 5. Incident Priority Matrix

The Customer has final authority over priority. Telemetry-based automatic classification sets the initial priority. The Supplier may request a change but may not downgrade an incident without written Customer approval. If priority changes, the stricter target applies from T0.

The Supplier must notify the Customer Incident Commander as soon as it believes any target is at risk, and no later than 50% of the target time elapsed.

| Priority | Acknowledge | Engaged on-site | Containment | Restore (Validated RTS) | Updates every |
|---|---|---|---|---|---|
| **P1 Critical** | 5 min | 15 min | 1 hr | 4 hrs | 30 min |
| **P2 High** | 15 min | 30 min | n/a | 8 hrs | 1 hr |
| **P3 Medium** | 1 hr | 4 hrs | n/a | 24 hrs | 24 hrs |
| **P4 Low** | 4 hrs | n/a | n/a | 5 days | n/a |

### P1: Critical

**Criteria:**

- Active coolant leak or any tray, rack, or CDU leak-detection alarm.
- CDU loss of flow, or loss of pump redundancy with rising temperatures.
- Rack-level outage (an entire NVL72 rack or more unavailable).
- NVLink switch tray failure (treated as rack-wide).
- Any EHS event involving injury, fire, smoke, or electrical hazard.
- Physical security breach of the Customer cage.

**Examples:** Leak detector alarm on rack A-14 manifold. CDU-3 flow drops below baseline; 8 racks at risk.

**Escalation:** Immediate page to Customer Incident Commander; Supplier site manager engaged.

### P2: High

**Criteria:**

- Single compute tray down in production (4 GPUs).
- Back-end fabric link down or flapping and impacting jobs.
- Power shelf failure with redundancy lost.
- CDU pump redundancy lost with stable temperatures.

**Examples:** XID 79 (GPU fallen off bus) on a production tray. Repeated link-down events on a leaf port serving rack B-03.

**Escalation:** Supplier shift lead; Customer on-call informed.

### P3: Medium

**Criteria:**

- Redundant component failed with redundancy still intact (e.g., one PSU).
- Degradation trend before failure (rising corrected errors, pre-FEC BER drift).
- Fault on a non-production or burn-in tray.

**Examples:** One 5.5 kW PSU failed in a power shelf; shelf redundancy intact. Rising symbol errors on an optic that has not yet flapped.

**Escalation:** Tracked in daily standup.

### P4: Low

**Criteria:**

- Service requests, planned work, labeling, audits, and cable management.

**Examples:** Re-label a row after a layout change.

**Escalation:** Tracked in weekly operations review.

## 6. Measurement and Telemetry of Record

Performance is measured from Customer-operated Telemetry of Record, not from Supplier self-reporting. Supplier ticket data is used for work content and narrative, and is reconciled against telemetry. Where they disagree, the higher-precedence source prevails.

### 6.1 Clock rules

- **Clock starts:** T0, the earliest evidence of the fault across all sources.
- **Clock stops:** Validated RTS.
- **The clock may pause only for:**
  - A Customer-requested hold, recorded in the ticket with Customer approval.
  - Customer-controlled access delays (e.g., cage access withheld by the Customer).
  - An approved Excused Event.
- **The clock does not pause for:**
  - Waiting for parts when Customer spares were at or above minimum stock.
  - Supplier staffing shortfalls or shift changes.
  - Waiting on Supplier internal escalation.
- **Timestamps:** All systems record UTC and are NTP-synchronized; records with clock skew over 5 seconds are flagged.

### 6.2 Data sources and precedence

Precedence 1 is most authoritative. When sources disagree, the higher-precedence source prevails.

| ID | Source | Measures | Owner | Precedence |
|---|---|---|---|:-:|
| DS-DCGM | GPU telemetry (DCGM and driver XID events) | GPU faults, ECC and XID events, diagnostic results, burn-in results. | Customer | 1 |
| DS-REDFISH | BMC Redfish API | Hardware inventory and serial numbers, PSU health, tray leak detection, power state. | Customer | 1 |
| DS-NMX | NVLink fabric management telemetry | NVLink switch tray health, NVLink domain state, link errors. | Customer | 1 |
| DS-UFM | InfiniBand fabric manager | Port state, link-down events, symbol and error counters. | Customer | 1 |
| DS-HEALTH | Cluster health-check and automated recovery platform | Periodic and job-boundary health checks; node drain and return events. | Customer | 1 |
| DS-SCHED | Customer workload scheduler | Node state (available, drained, down) and capacity returned to production. | Customer | 1 |
| DS-BMS | Building management system feed (via Facility Provider) | CDU flow, supply and return temperatures, pump status, room leak sensors. | Facility Provider | 2 |
| DS-BADGE | Access control system | Technician presence by hall, time on site, staffing fill. | Customer | 1 |
| DS-CAB | Customer change management system | Approved changes and maintenance windows. | Customer | 1 |
| DS-ITSM | Supplier ticketing system | Ticket lifecycle, work notes, parts used, priority, Supplier-recorded timestamps. | Supplier | 3 |
| DS-SPARES | Supplier spares and RMA system | Stock levels, consumption, cycle counts, RMA shipments. | Supplier | 3 |

### 6.3 Reporting

- **Weekly:** Operating scorecard by Monday 12:00 UTC, generated automatically from telemetry and ticket data.
- **Monthly:** Service Level Report within 5 business days after month end, including all defaults, credits, and trends.
- **Raw data:** The Customer may access ticket data through API at any time; the Supplier must keep all records for the Term plus 2 years.
- **Failure to report:** If the Supplier fails to provide data required to measure a service level, that service level is deemed to have a Minimum Service Level Default for the period.

## 7. Critical Service Levels

Critical Service Levels are measured each calendar month and tracked each ISO week (Monday 00:00 UTC to Sunday 23:59 UTC). A result worse than **Minimum** is a Minimum Service Level Default and earns the credit described in Section 11.

| ID | Service level | Category | Expected | Minimum | Credit allocation |
|---|---|---|:-:|:-:|:-:|
| CSL-01 | Supplier-Attributable GPU Availability | Availability and Restoration | ≥ 99.5% | ≥ 99% | 40% |
| CSL-02 | P1 Engaged On-Site Within 15 Minutes | Availability and Restoration | 100% | ≥ 95% | 20% |
| CSL-03 | P1 Restoration Within 4 Hours | Availability and Restoration | ≥ 95% | ≥ 90% | 30% |
| CSL-04 | P2 Restoration Within 8 Hours | Availability and Restoration | ≥ 95% | ≥ 90% | 20% |
| CSL-05 | P3 Restoration Within 24 Hours | Availability and Restoration | ≥ 95% | ≥ 90% | 10% |
| CSL-06 | First-Time Fix Rate | Repair Quality | ≥ 92% | ≥ 88% | 25% |
| CSL-07 | Validated Return to Service | Repair Quality | 100% | ≥ 98% | 25% |
| CSL-08 | 30-Day Repeat Failure Rate | Repair Quality | ≤ 3% | ≤ 5% | 20% |
| CSL-09 | Deployment Milestone Adherence | Deployment Delivery | ≥ 95% | ≥ 90% | 20% |
| CSL-10 | Qualified Staffing Fill Rate | Workforce and Record Integrity | ≥ 98% | ≥ 95% | 20% |
| CSL-11 | Record Integrity | Workforce and Record Integrity | ≥ 99% | ≥ 97% | 20% |
| | **Total allocation** | | | | **250%** (pool limit 250%) |

### CSL-01: Supplier-Attributable GPU Availability

Share of installed production GPU-hours not lost to Supplier-Attributable Unavailability. Racks count as installed from Validated Handoff.

- **Formula:** (Installed production GPU-hours minus Supplier-Attributable unavailable GPU-hours) ÷ (Installed production GPU-hours) × 100
- **Expected:** ≥ 99.5%. **Minimum:** ≥ 99%.
- **Telemetry:** DS-DCGM, DS-SCHED, DS-HEALTH, DS-ITSM

### CSL-02: P1 Engaged On-Site Within 15 Minutes

Share of P1 incidents where a qualified technician was Engaged On-Site within the target.

- **Formula:** (P1 incidents Engaged On-Site within 15 minutes of T0) ÷ (All P1 incidents) × 100
- **Expected:** 100%. **Minimum:** ≥ 95%.
- **Telemetry:** DS-BADGE, DS-ITSM, DS-DCGM, DS-REDFISH, DS-BMS
- **Small-sample rule:** When there are fewer than 20 qualifying events in the period, any miss is a Minimum Service Level Default regardless of the percentage. This prevents one incident in a quiet month from swinging the result unfairly in either direction.

### CSL-03: P1 Restoration Within 4 Hours

Share of P1 incidents reaching Validated RTS within 240 minutes of T0.

- **Formula:** (P1 incidents reaching Validated RTS within 240 minutes) ÷ (All P1 incidents) × 100
- **Expected:** ≥ 95%. **Minimum:** ≥ 90%.
- **Telemetry:** DS-DCGM, DS-REDFISH, DS-NMX, DS-SCHED, DS-BMS
- **Small-sample rule:** When there are fewer than 20 qualifying events in the period, more than 1 miss is a Minimum Service Level Default regardless of the percentage. This prevents one incident in a quiet month from swinging the result unfairly in either direction.

### CSL-04: P2 Restoration Within 8 Hours

Share of P2 incidents reaching Validated RTS within 480 minutes of T0.

- **Formula:** (P2 incidents reaching Validated RTS within 480 minutes) ÷ (All P2 incidents) × 100
- **Expected:** ≥ 95%. **Minimum:** ≥ 90%.
- **Telemetry:** DS-DCGM, DS-REDFISH, DS-UFM, DS-SCHED

### CSL-05: P3 Restoration Within 24 Hours

Share of P3 incidents reaching Validated RTS within 1,440 minutes of T0.

- **Formula:** (P3 incidents reaching Validated RTS within 1,440 minutes) ÷ (All P3 incidents) × 100
- **Expected:** ≥ 95%. **Minimum:** ≥ 90%.
- **Telemetry:** DS-DCGM, DS-REDFISH, DS-UFM, DS-ITSM

### CSL-06: First-Time Fix Rate

Share of repairs that pass validation on the first attempt with no Same-Fault Recurrence within 7 days. For repairs late in a month, the 7-day window closes in the following period and the result is finalized then.

- **Formula:** (Repairs meeting the First-Time Fix definition) ÷ (All repairs reaching Validated RTS in the period) × 100
- **Expected:** ≥ 92%. **Minimum:** ≥ 88%.
- **Telemetry:** DS-DCGM, DS-REDFISH, DS-UFM, DS-NMX, DS-ITSM

### CSL-07: Validated Return to Service

Share of units returned to production with complete Return-to-Service validation evidence.

- **Formula:** (Units returned to production with all required validation checks passed and recorded) ÷ (All units returned to production after Supplier work) × 100
- **Expected:** 100%. **Minimum:** ≥ 98%.
- **Telemetry:** DS-DCGM, DS-HEALTH, DS-NMX, DS-UFM, DS-REDFISH

### CSL-08: 30-Day Repeat Failure Rate

Share of repaired units with any new fault within 30 days of Validated RTS.

- **Formula:** (Repaired units with a Repeat Failure) ÷ (Units reaching Validated RTS in the trailing window) × 100
- **Expected:** ≤ 3%. **Minimum:** ≤ 5%.
- **Telemetry:** DS-DCGM, DS-REDFISH, DS-UFM, DS-NMX

### CSL-09: Deployment Milestone Adherence

Share of racks reaching Validated Handoff by the committed date in the deployment plan.

- **Formula:** (Racks reaching Validated Handoff on or before the committed date) ÷ (Racks with a committed Validated Handoff date in the period) × 100
- **Expected:** ≥ 95%. **Minimum:** ≥ 90%.
- **Telemetry:** DS-HEALTH, DS-SCHED, DS-REDFISH, DS-ITSM

### CSL-10: Qualified Staffing Fill Rate

Share of committed qualified-technician shift-hours actually staffed, verified by badge data.

- **Formula:** (Qualified technician hours present on site (badge-verified)) ÷ (Committed qualified technician shift-hours) × 100
- **Expected:** ≥ 98%. **Minimum:** ≥ 95%.
- **Telemetry:** DS-BADGE, DS-ITSM

### CSL-11: Record Integrity

Share of closed tickets whose recorded actions, parts, and timestamps reconcile with the Telemetry of Record (no Record Integrity Finding).

- **Formula:** (Closed tickets with no Record Integrity Finding) ÷ (All tickets closed in the period) × 100
- **Expected:** ≥ 99%. **Minimum:** ≥ 97%.
- **Telemetry:** DS-REDFISH, DS-DCGM, DS-BADGE, DS-ITSM, DS-SPARES

## 8. Key Measurements

Key Measurements carry no credits. Any miss requires a root cause analysis and corrective action plan (Section 14), and repeated misses may lead the Customer to promote the measurement to a Critical Service Level (Section 21).

| ID | Key measurement | Target | Telemetry |
|---|---|:-:|---|
| KM-01 | P2 Engaged On-Site Within 30 Minutes | ≥ 95% | DS-BADGE, DS-ITSM |
| KM-02 | P1 Containment Within 60 Minutes (leak and safety incidents) | 100% | DS-REDFISH, DS-BMS, DS-ITSM |
| KM-03 | P3 Engaged On-Site Within 4 Hours | ≥ 95% | DS-BADGE, DS-ITSM |
| KM-04 | P4 Completed Within 5 Days | ≥ 90% | DS-ITSM |
| KM-05 | Incident Update Cadence Adherence | ≥ 95% | DS-ITSM |
| KM-06 | Spares at or Above Minimum Stock (by FRU class, daily) | ≥ 98% | DS-SPARES, DS-REDFISH |
| KM-07 | Spares Cycle Count Accuracy | ≥ 99% | DS-SPARES |
| KM-08 | RMA Shipped to OEM Within 5 Business Days | ≥ 95% | DS-SPARES |
| KM-09 | Lemon Units Escalated Within 2 Business Days | 100% | DS-DCGM, DS-REDFISH, DS-ITSM |
| KM-10 | Change Compliance (all changes CAB-approved and in window) | 100% | DS-CAB, DS-ITSM, DS-REDFISH |
| KM-11 | P1 Final RCA Delivered Within 5 Business Days | 100% | DS-ITSM |
| KM-12 | Corrective Actions Closed On Time | ≥ 90% | DS-ITSM |
| KM-13 | Backlog Aging (P3 and P4 tickets open more than 14 days) | ≤ 5% | DS-ITSM |
| KM-14 | Ticket Data Completeness (required fields populated at closure) | ≥ 98% | DS-ITSM |
| KM-15 | Training and Certification Currency | 100% | DS-ITSM, DS-BADGE |

## 9. Return-to-Service Validation Requirements

A unit is not returned to production until every check for its component class has passed and the evidence is recorded in the ticket. Missing evidence counts as a failed validation for CSL-07.

**Compute tray**

- [ ] Serial number change recorded in Redfish inventory matches the ticket's parts record.
- [ ] Quick-disconnects verified seated; zero tray or rack leak alarms during a 30-minute post-insertion hold.
- [ ] GPU diagnostic (DCGM run level 3 or higher) passes on all 4 GPUs.
- [ ] NVLink domain healthy for the rack (IMEX domain up; all GPU NVLinks active).
- [ ] Rack NCCL all-reduce bandwidth within 5% of the rack's baseline.
- [ ] 4-hour burn-in with zero XID events.

**NVLink switch tray**

- [ ] Serial number change recorded in Redfish inventory.
- [ ] NVLink fabric management reports the tray and all ports healthy.
- [ ] Full-rack NVLink acceptance and NCCL all-reduce within 5% of baseline.
- [ ] Zero leak alarms during a 30-minute hold.

**Optic, cable, or fiber**

- [ ] Fiber end faces inspected and cleaned (inspection record attached).
- [ ] Port up with zero symbol errors and zero link-down events over a 30-minute soak.
- [ ] Pre-FEC bit error rate below the Customer threshold.
- [ ] Both link ends identified in the ticket (prevents fixing the wrong end).

**Power shelf or PSU**

- [ ] Redfish reports PSU health OK and redundancy restored.
- [ ] Serial number change recorded in inventory.

**CDU component (pump, filter, sensor)**

- [ ] Flow, supply temperature, and return temperature within baseline.
- [ ] Pump redundancy confirmed by failover test, coordinated with the Facility Provider.
- [ ] All leak alarms clear; coolant conductivity and pH within specification after any fluid work.

**E1.S drive or other storage media**

- [ ] Removed media logged into chain of custody (see Security).
- [ ] Node health check passes and RAID or volume rebuilt.

## 10. Deployment Milestones

Target cycle: **10 calendar days** from rack receipt to Validated Handoff. Surge capacity: +25% staffing on 72 hours notice; +100% on 10 business days notice.

| Milestone | Name | Exit criteria | Target (days from receipt) |
|---|---|---|:-:|
| M1 | Received and inspected | Shock and tilt indicators checked; no shipping damage; asset tags and serials reconciled to the ASN. | 1 |
| M2 | Positioned and connected | Rack set and secured; power whips and manifold connected to the CDU. | 3 |
| M3 | Leak test passed | Pressure hold at the OEM test pressure (typically 1.5x operating) for at least 30 minutes with no decay; zero leak alarms; coolant within specification. | 4 |
| M4 | Power-on and firmware baseline | POST clean on all trays; firmware matches the Customer baseline; BMCs reachable on OOB. | 5 |
| M5 | Network cabled and verified | Every back-end and front-end link up, error-free over soak, and matching the cabling plan. | 7 |
| M6 | Burn-in accepted | GPU diagnostics, NVLink domain acceptance, NCCL benchmarks, and 24-hour burn-in all pass. | 9 |
| M7 | Validated Handoff | Rack released to the Customer scheduler with the full acceptance record. CSL-09 is measured at this milestone. | 10 |

## 11. Service Level Credits and Earnback

- **At-Risk Amount:** 12% of monthly charges (illustratively $1,850,000/month, so **$222,000** at risk each month).
- **Pool:** Credit allocations across all Critical Service Levels total 250% of the At-Risk Amount (pool limit 250%), with no single CSL above 40%. A pool above 100% concentrates financial attention on the Customer's priorities while the monthly cap protects the Supplier.
- **Credit formula:** Credit = At-Risk Amount × CSL allocation %.
- **Monthly cap:** Total credits in a Measurement Period never exceed the At-Risk Amount.
- **Repeat defaults:** A Minimum Service Level Default on the same CSL for 3 consecutive periods earns 2× the credit. Doubled credits are not eligible for Earnback.
- **Earnback:** Supplier earns back a Service Level Credit for a Critical Service Level if it meets or exceeds the Expected Service Level for that same Critical Service Level in each of the 3 Measurement Periods immediately following the default. Earnback is not available when:
  - The credit was doubled under the repeat-default rule.
  - The default involved a confirmed Record Integrity finding (AGG-INTEGRITY).
  - The default involved an EHS or security event (AGG-EHS, AGG-SECURITY).
- **Application:** Credits appear on the invoice following the Measurement Period.
- **Nature of credits:** Service Level Credits are a price adjustment reflecting reduced service value. They are not a penalty and do not limit the Customer's other rights under the Agreement, including chronic failure termination rights.

See Appendix B for worked credit examples.

## 12. Chronic Failure and Termination

Any of the following is a Chronic Failure:

- **CF-1:** A Minimum Service Level Default on the same CSL in 3 consecutive Measurement Periods.
- **CF-2:** A Minimum Service Level Default on the same CSL in any 4 of 6 rolling Measurement Periods.
- **CF-3:** Total Service Level Credits over 50% of the cumulative At-Risk Amount in any rolling 6 Measurement Periods.
- **CF-4:** Any confirmed deliberate falsification of records.

On a Chronic Failure, the Customer may:

- Terminate the affected services or the entire Site scope for cause, without termination charges.
- Require a Supplier executive-sponsored recovery plan within 10 business days.
- Step-in: the Customer or a third party may perform the affected services at the Supplier's cost during recovery.

**Termination assistance:** The Supplier provides up to 6 months of transition assistance at the then-current service levels, including full transfer of performance data, procedures, and spares records to the successor.

## 13. Excused Events

The Supplier must claim an Excused Event within 5 business days, with supporting evidence. Only the following qualify:

- Force majeure as defined in the Agreement.
- Failures of Facility Provider systems outside Supplier scope (the Supplier must still respond and notify).
- Customer-caused delays, including withheld access or Customer-requested holds recorded in the ticket.
- Approved maintenance inside an approved change window, within the approved duration.
- OEM part unavailability, ONLY if Customer spares for that FRU class were at or above minimum stock and the Supplier notified the Customer within 4 hours.

**Treatment:** The excused occurrence is removed from both the numerator and the denominator of the affected service level. The rest of the Measurement Period is still measured.

**Supplier duty:** The Supplier must use commercially reasonable efforts to perform despite the Excused Event.

## 14. Root Cause Analysis and Corrective Action

**Triggers:**

- Any Expected or Minimum Service Level Default.
- Any Key Measurement miss.
- Any P1 incident.
- Any Lemon Unit.
- Any Record Integrity Finding.

**Timelines:** P1 preliminary RCA within 24 hours; P1 final RCA within 5 business days; all other RCAs within 10 business days.

**Corrective action plan (CAP) requirements:**

- Root cause stated in terms of process, people, parts, or tooling; not 'technician error' alone.
- Each action has a single named owner, a due date, and an evidence-of-completion definition.
- Effectiveness check: the triggering metric is reviewed for 2 Measurement Periods after closure.

**Overdue CAPs:** CAPs more than 10 business days overdue escalate to the monthly service review.

## 15. Governance and Reporting Cadence

| Forum | Frequency | Attendees | Inputs |
|---|---|---|---|
| Daily operations standup | Daily, 15 minutes | Supplier shift leads; Customer site lead | Open P1 and P2 incidents, today's deployment plan, blockers, spares alerts. |
| Weekly operations review | Weekly | Supplier site manager; Customer site lead | Automated weekly scorecard, breach severity log, CAP status, staffing, lemon units. |
| Monthly service review | Monthly | Supplier account manager; Customer DCO leadership | Service Level Report, credits and earnback, chronic-failure watch, trends. |
| Quarterly business review | Quarterly | Supplier executive sponsor; Customer DCO leadership | Trend analysis, SLA change proposals, roadmap and capacity plan, program-wide lessons learned. |

## 16. Staffing and Qualifications

**Coverage:** 24x7x365 on site.

| Shift | Technicians | Shift leads |
|---|:-:|:-:|
| Day (07:00 to 19:00 local) | 8 | 1 |
| Night (19:00 to 07:00 local) | 5 | 1 |

**Key personnel:**

- Site manager (named; replacement requires 30 days notice and Customer approval)
- EHS coordinator
- Spares and logistics coordinator

**Required qualifications:**

- OEM-authorized training for GB200 NVL72 field-replaceable unit service
- Liquid-cooling handling, quick-disconnect service, and spill response
- ESD control program training
- Electrical safety training appropriate to the tasks performed
- Lockout/tagout (hazardous energy control) training
- Fiber inspection and cleaning
- Customer site security and chain-of-custody procedures

Only badge-verified hours by technicians with current qualifications count toward CSL-10.

## 17. Change Management

- All non-emergency changes require Customer change approval before work starts.
- Standard changes (pre-approved runbook FRU swaps) may proceed under an open incident.
- Emergency changes require verbal approval from the Customer Incident Commander, recorded in the ticket within 1 hour.
- Work outside the approved window or scope is an unauthorized change and counts against KM-10.

**Firmware:** Firmware may only be loaded from the Customer-approved baseline; any deviation is an unauthorized change.

## 18. Security and Chain of Custody

- Badge access only for Customer-approved personnel; no tailgating; visitors escorted at all times.
- Daily reconciliation of badge records against the shift roster.
- Storage media (e.g., E1.S drives) never leave the Site intact; media is sanitized or destroyed on site under the Customer's media sanitization standard, with a certificate per serial number.
- Every failed part is logged into chain of custody at removal, with serial, ticket, technician, and timestamp.
- Cameras and photography in the data hall are prohibited except for Customer-approved documentation.

**Incident reporting:** Suspected security incidents are reported to the Customer within 1 hour of discovery.

## 19. Environmental, Health, and Safety

- Every technician has stop-work authority and must use it for any unsafe condition.
- Hazardous energy control (lockout/tagout) for any work requiring de-energization.
- Electrical safety practices appropriate to the task and approach boundaries.
- ESD-safe handling for all electronic components.
- Spill kits staged at every CDU and at row ends; coolant spills handled per the site spill procedure.
- Mechanical lift and team-lift procedures for trays and racks (a fully loaded NVL72 rack weighs well over a metric ton).

**Reporting:** Injuries and recordables within 1 hour; near misses within 24 hours.

EHS performance is not credit-bearing; safety must never be traded for speed. Any recordable injury or stop-work event triggers an internal S1 severity and a joint review. Serious or repeated EHS failures are a material breach of the Agreement.

## 20. Spares and RMA

Spares are Customer-owned and Supplier-managed.

| Field-replaceable unit | Minimum stock per hall |
|---|:-:|
| Compute tray | 6 |
| NVLink switch tray | 2 |
| Power shelf | 4 |
| PSU (5.5 kW) | 24 |
| 800G OSFP optic | 150 |
| Fiber and DAC cable kits | 100 |
| Manifold hose and quick-disconnect kit | 10 |
| E1.S drive | 20 |
| CDU pump assembly | 1 |

- **Reorder:** Replenishment requests are raised automatically when stock reaches minimum plus lead-time demand.
- **Cycle counts:** Weekly cycle count of high-value FRUs; full count monthly.

## 21. SLA Change Control and Continuous Improvement

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

## Appendix B: Worked Examples

*These examples are computed by `src/scorecard/sla_model.py` from this SLA's own parameters every time the document is generated, so the document and the scoring engine always agree.*

### B.1 Service Level Credits

**Single default: CSL-03 (P1 restoration) misses Minimum once.** At-Risk Amount $222,000 (12% of $1,850,000) × 30% allocation = $66,600. **Credit: $66,600.** Earnback eligible: Yes.

**Repeat default: CSL-03 misses Minimum for the 3rd consecutive month.** At-Risk Amount $222,000 (12% of $1,850,000) × 30% allocation = $66,600; ×2 for 3 consecutive defaults. **Credit: $133,200.** Earnback eligible: No.

**Integrity-aggravated default: CSL-11 (Record Integrity) misses Minimum.** At-Risk Amount $222,000 (12% of $1,850,000) × 20% allocation = $44,400. **Credit: $44,400.** Earnback eligible: No.

**Monthly cap.** A severe month with Minimum defaults on CSL-01, CSL-03, CSL-06, CSL-07, CSL-11: uncapped credits total $310,800 (140% of the At-Risk Amount). The cap limits the payable credit to **$222,000**.

### B.2 Breach severity

| Scenario | Target | Actual | GPUs | Aggravators | Severity | Why |
|---|:-:|:-:|:-:|---|:-:|---|
| P2 compute tray restored 40 min late | 8 hrs | 8 hrs 40 min | 4 | None | **S4 Watch** | Overrun 8% past target → S4; 3 GPU-hours lost beyond target (4 GPUs) → S4 |
| P2 tray late, same tray failed 2 weeks ago | 8 hrs | 12 hrs | 4 | AGG-REPEAT | **S2 Major** | Overrun 50% past target → S3; 16 GPU-hours lost beyond target (4 GPUs) → S4; AGG-REPEAT: +1 level (Same CSL or same Service Unit breached within the previous 30 days) |
| P1 rack outage restored at 8 hrs | 4 hrs | 8 hrs | 72 | AGG-RACKWIDE | **S2 Major** | Overrun 100% past target → S2; 288 GPU-hours lost beyond target (72 GPUs) → S3; AGG-RACKWIDE: present; already at or above S2 |
| P2 tray late; ticket claims swap but serial unchanged | 8 hrs | 10 hrs | 4 | AGG-INTEGRITY | **S1 Critical** | Overrun 25% past target → S3; 8 GPU-hours lost beyond target (4 GPUs) → S4; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)) |
| P1 CDU loop loss restored at ~18 hrs | 4 hrs | 18 hrs 20 min | 576 | AGG-RACKWIDE | **S1 Critical** | Overrun 358% past target → S1; 8,256 GPU-hours lost beyond target (576 GPUs) → S1; AGG-RACKWIDE: present; already at or above S2 |

| Period scenario | Result | Severity | Why |
|---|:-:|:-:|---|
| CSL-01 availability, single month | 99.3% | **S4 Watch** | CSL-01 actual 99.3 vs expected 99.5 / minimum 99: Below Expected but at or above Minimum. |
| CSL-06 first-time fix, single month | 87% | **S3 Minor** | CSL-06 actual 87 vs expected 92 / minimum 88: Below Minimum (credit-bearing default). |
| CSL-01 availability, single month | 98.2% | **S2 Major** | CSL-01 actual 98.2 vs expected 99.5 / minimum 99: Below Minimum by more than the Expected-to-Minimum gap. |
| CSL-10 staffing fill, 3rd consecutive Minimum default | 94% | **S1 Critical** | CSL-10 actual 94 vs expected 98 / minimum 95: Minimum default on the same CSL for 3 or more consecutive periods (chronic failure CF-1). |

---

*Generated from `sla/vendor_sla.yaml` (schema 1.0, SLA version 1.0.0). This is a fictional, illustrative service level agreement created for a portfolio demonstration. All parties, sites, quantities, prices, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.*
