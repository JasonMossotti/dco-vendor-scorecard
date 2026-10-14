<!--
  GENERATED FILE. DO NOT EDIT BY HAND.
  Source: sla/security_partner.yaml + sla/common.yaml  |  Generator: scripts/render_sla.py
  Edit the YAML and re-run: python scripts/render_sla.py
-->

# Service Level Agreement: Site Security Services

**Schedule D (Security Service Levels) to the Security Services Agreement**

> **MOCK / ILLUSTRATIVE.** This is a fictional, illustrative security services level agreement created for a portfolio demonstration. All parties, sites, quantities, prices, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.

| Document ID | Version | Effective date | Term | Timezone |
|---|---|---|---|---|
| SLA-LGP-AUS1-001 | 1.0.0 | 2026-10-05 | 36 months | UTC |

## Contents

1. [Purpose and Structure](#1-purpose-and-structure)
2. [Parties and Site](#2-parties-and-site)
3. [Scope and Ownership](#3-scope-and-ownership)
4. [Alarm Priority Matrix](#4-alarm-priority-matrix)
5. [Measurement and Telemetry of Record](#5-measurement-and-telemetry-of-record)
6. [Guard Posts and Patrols](#6-guard-posts-and-patrols)
7. [Door Alarms](#7-door-alarms)
8. [Visitors and Escorts](#8-visitors-and-escorts)
9. [Video System](#9-video-system)
10. [Badge Administration and Access Reviews](#10-badge-administration-and-access-reviews)
11. [Media Destruction](#11-media-destruction)
12. [Critical Service Levels](#12-critical-service-levels)
13. [Key Measurements](#13-key-measurements)
14. [Service Level Credits and Earnback](#14-service-level-credits-and-earnback)
15. [Chronic Failure](#15-chronic-failure)
16. [Excused Events](#16-excused-events)
17. [Root Cause Analysis and Corrective Action](#17-root-cause-analysis-and-corrective-action)
18. [Governance and Reporting Cadence](#18-governance-and-reporting-cadence)
19. [Change Management](#19-change-management)
20. [Security and Chain of Custody](#20-security-and-chain-of-custody)
21. [Environmental, Health, and Safety](#21-environmental-health-and-safety)
22. [SLA Change Control and Continuous Improvement](#22-sla-change-control-and-continuous-improvement)
- [Appendix A: Internal Breach Severity Index](#appendix-a-internal-breach-severity-index)
- [Appendix B: Worked Examples](#appendix-b-worked-examples)

---

## 1. Purpose and Structure

This Schedule defines the service levels Llano Gate Protective Services, LLC ("Security Partner", and the "Supplier" for the purposes of the common terms in this Schedule) must meet in securing the Customer halls at Site AUS-1 (fictional), how performance is measured, and what happens when service levels are missed.

Security contractors usually report their own post coverage and alarm response. Here every service level is measured from the Customer's own systems (access control, video, identity feed), and the Security Partner's post log, dispatch log, visitor log, and destruction certificates are reconciled against them.

Each service level has an **Expected** level (missing it triggers root cause analysis) and a **Minimum** level (missing it triggers a Service Level Credit). Three principles shape this Schedule:

1. **The Customer owns the policy and the systems; the Security Partner runs them.** Access approvals, the access control system, the video system, and the identity feed are the Customer's. The Security Partner operates them under the Customer's security policy.
2. **A badge is evidence; a log entry is a claim.** A post is staffed when a guard badges in at the post, a door alarm is answered when a guard badges the alarmed door, and an escort is present when the escort badges into the hall.
3. **No storage media leaves the Site intact.** Every drive from a failed part is destroyed on site and certified by serial number before the part ships.

## 2. Parties and Site

| Party | Name | Role |
|---|---|---|
| Customer | Customer | Owns site outcomes; directs the IT partner; operates the Telemetry of Record; holds the Landlord to its SLA. |
| Security Partner | Llano Gate Protective Services, LLC *(fictional)* | Staffs the Customer hall guard posts and patrols, monitors and responds to door alarms, runs visitor sign-in and escort monitoring, operates the video system, removes badges for people who leave, and destroys storage media on site. |
| IT Partner | Ridgeline Site Services, LLC *(fictional)* | Separate services agreement and IT Partner SLA (Schedule B). |
| Landlord | Caprock Critical Facilities, LLC *(fictional)* | Separate lease and Landlord SLA (Schedule C). Bound by the common terms, including EHS. |

**Site:** Site AUS-1 (fictional). **Charges basis:** Monthly fee for five guard posts, patrols, the security console, and media destruction (illustrative).

## 3. Scope and Ownership

### 3.1 Security Partner services

| ID | Service | Description |
|---|---|---|
| SEC-POST | Guard posts and patrols | The Hall A and Hall B entrance posts, the security console, the receiving dock post (day shift), and a roving patrol of the Customer halls with tour checkpoints. |
| SEC-ALARM | Door alarm monitoring and response | Watching the access control system for door forced and door held alarms on the Customer's doors, acknowledging them at the console, and sending a guard to the door. |
| SEC-VISIT | Visitor sign-in and escort monitoring | Signing visitors in against a Customer-approved request, issuing visitor badges, and confirming an escort badges in with each visitor. |
| SEC-VIDEO | Video system operation | Watching camera health on the Customer's video system, raising faults, and confirming each recorder keeps 90 days of video. The Security Partner views video only for an incident and never exports it. |
| SEC-ACCESS | Badge administration | Issuing and removing badges on the Customer's access control system under Customer approval, removing the badges of people who leave, and preparing the quarterly access review. |
| SEC-MEDIA | Media destruction | Receiving storage media from the IT Partner under chain of custody, destroying it on site, and issuing a certificate per serial number before the part it came from leaves the Site. |

### 3.2 Not Security Partner scope

- The building perimeter, lobby, and base building access control (Landlord, DM-SEC).
- Security policy, access approvals, and the access control, video, and identity systems themselves (Customer).
- Removing failed parts and their media from the racks (IT Partner, HO-5).

### 3.3 Break-fix ownership matrix

Exhibit from the Interface Agreement (IA-AUS1-001, version 1.2.0), which governs demarcation, fault attribution, and joint operations between the parties.

**R** = Responsible: performs the work; **A** = Accountable: owns the outcome and approves; **C** = Consulted; **I** = Informed.

| Component | Customer | IT Partner | Landlord | OEM | Utility | Security Partner |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Compute tray (GPU, CPU, memory, cold plate) | A | R | - | C | - | - |
| NVLink switch tray and NVLink backplane | A | R | - | C | - | - |
| Rack power shelves, PSUs, and whips from the tap-off output | A | R | C | C | - | - |
| Busway, tap-off units, and tap-off breakers | I | C | A/R | - | - | - |
| UPS, batteries, unit substations, and switchgear | I | I | A/R | - | - | - |
| Generators, paralleling controls, and fuel | I | - | A/R | - | - | - |
| 138 kV substation and utility transformers | - | - | C | - | A/R | - |
| Rack manifold, isolation valves, quick-disconnects | A | R | C | C | - | - |
| CDUs and the hall secondary header | I | C | A/R | - | - | - |
| Chillers, facility water, and pumps | I | - | A/R | - | - | - |
| Thermal walls, CRAHs, and hot-aisle containment | I | C | A/R | - | - | - |
| Building leak detection (cable and controllers) | I | C | A/R | - | - | - |
| Fire alarm, VESDA, and pre-action suppression | I | I | A/R | - | - | - |
| BMS and EPMS operation | C | - | A/R | - | - | - |
| Customer Telemetry of Record collector and read-only taps | A/R | I | C | - | - | - |
| Back-end fabric optics, cables, and fiber | A | R | - | C | - | - |
| Leaf and spine switches (physical replacement) | A | R | - | C | - | - |
| BMC and out-of-band management network (physical) | A | R | - | C | - | - |
| Storage nodes and drives (physical) | A | R | - | C | - | C |
| Meet-me rooms and cross-connects | C | C | A/R | - | - | - |
| Spares cage, inventory, and RMA shipments | A | R | - | C | - | C |
| Building perimeter, lobby, and access control system | C | I | A/R | - | - | C |
| Customer halls and cage access lists | A | R | R | - | - | R |
| Guard posts and patrols in the Customer halls | A | I | I | - | - | R |
| Customer hall door alarms (forced and held) and guard response | A | I | I | - | - | R |
| Visitor sign-in, visitor badges, and escorts in the Customer halls | A | C | C | I | - | R |
| Cameras and video recorders covering the Customer halls | A | - | C | - | - | R |
| Storage media destruction from failed parts | A | C | - | I | - | R |

## 4. Alarm Priority Matrix

"Engaged on-site" means a guard badged at the alarmed door's reader, or at the location of the event. The Customer has final authority over priority. The access control and video systems set the initial priority. The Supplier may request a change but may not downgrade an event without written Customer approval. The Supplier must notify the Customer Incident Commander as soon as it believes any target is at risk, and no later than 50% of the target time elapsed.

| Priority | Acknowledge | Engaged on-site | Containment | Restore | Updates every |
|---|---|---|---|---|---|
| **P1 Critical** | 1 min | 3 min | 15 min | 1 hr | 30 min |
| **P2 High** | 2 min | 5 min | n/a | 4 hrs | 1 hr |
| **P3 Medium** | 15 min | 30 min | n/a | 24 hrs | 24 hrs |
| **P4 Low** | 4 hrs | n/a | n/a | 5 days | n/a |

### P1: Critical

**Criteria:**

- Door forced at a Customer hall, mantrap, or cage.
- Confirmed tailgating or an unbadged person in a Customer hall.
- Storage media unaccounted for at any point in chain of custody.
- Every camera covering a Customer hall entrance offline.

**Examples:** Door forced alarm on the Hall B mantrap inner door. A drive serial missing from the destruction log for a tray waiting to ship.

**Escalation:** Immediate page to the Customer Incident Commander; Security Partner site manager engaged.

### P2: High

**Criteria:**

- Door held open past its allowed time at a Customer hall or the receiving dock.
- A visitor in a Customer hall without an escort.
- A camera covering a Customer hall door offline.

**Examples:** Door held alarm on the Hall A receiving door during a delivery. Camera CAM-B-04 offline over the Hall B entrance.

**Escalation:** Security Partner shift supervisor; Customer on-call informed.

### P3: Medium

**Criteria:**

- A camera offline that covers no Customer hall door.
- A guard tour checkpoint missed.
- A badge reader fault with the door secured.

**Examples:** Camera CAM-A-11 over the Hall A spares aisle offline.

**Escalation:** Reviewed in the daily standup.

### P4: Low

**Criteria:**

- Badge requests, visitor pre-registration, and access review preparation.

**Examples:** Pre-register three OEM engineers for a Hall B visit.

**Escalation:** Tracked in the weekly operations review.

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
| DS-BADGE | Access control system | Technician, engineer, and guard presence by hall, post, and equipment room; time on site; staffing fill; door forced and door held alarms; visitor badge entries. | Customer | 1 |
| DS-VMS | Video management system (camera health and recorder retention, Customer-owned) | Camera recording state by minute, recorder storage and the age of the oldest recording. No video leaves the system for measurement. | Customer | 1 |
| DS-GUARD | Security Partner post log, guard tour, and dispatch system | Posts reported staffed, guard tour checkpoint scans, door alarm dispatch and closure, Supplier-recorded timestamps. | Security Partner | 3 |
| DS-VISIT | Visitor management system | Visitor sign-in and sign-out, the named escort, and the visitor badge issued. | Security Partner | 3 |
| DS-IDM | Customer identity feed (separations from each party's HR system) | Time each person left a party's employment or the Site assignment; badge deactivation time from the access control system. | Customer | 1 |
| DS-COC | Chain-of-custody and media destruction log | Storage media handed over at removal, destroyed on site, and certified by serial number. | Security Partner | 3 |
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

## 6. Guard Posts and Patrols

A post is staffed only when the assigned guard is badged in at the post reader. A post log entry, a radio call, or a relief arriving late does not count.

| Shift | Hours |
|---|---|
| Day (07:00 to 19:00 local) | 12 |
| Night (19:00 to 07:00 local) | 12 |

| Post | Name | Post reader | Shifts |
|---|---|---|---|
| POST-HA | Hall A entrance | Post: Hall A entrance | day, night |
| POST-HB | Hall B entrance | Post: Hall B entrance | day, night |
| POST-SOC | Security console | Post: Security console | day, night |
| POST-DOCK | Receiving dock | Post: Receiving dock | day |
| POST-PATROL | Roving patrol | Post: Patrol start | day, night |

**Tours:** Each patrol shift scans every checkpoint once every 2 hours; a scan more than 15 minutes late counts as missed.

**Required qualifications:**

- Texas Department of Public Safety Private Security Program registration, current for every guard
- Site security orientation and the Customer's escort and media handling procedures
- CPR and first aid for at least one guard on every shift

## 7. Door Alarms

The access control system raises the alarm and records the console acknowledgement; the guard's badge at the alarmed door is the evidence of response. A dispatch log entry is narrative, never evidence. A door may be held open for 60 seconds before the access control system raises a door held alarm.

- A door forced alarm on a Customer door is P1; a door held alarm is P2.
- The guard badges the alarmed door's reader on arrival, so the response time is measured, not typed.
- An alarm closed in the dispatch log with no guard badge at the door within the target is a Record Integrity finding as well as a response miss.

## 8. Visitors and Escorts

- Every visitor is pre-registered under a Customer-approved request naming the escort.
- The escort badges into the hall with the visitor, within 2 minutes, and leaves with or after the visitor.
- Visitor badges open only the hall doors on the request and expire at sign-out or at the end of the day.

## 9. Video System

**Retention:** 90 days on every recorder.

- Every camera records continuously; motion-only recording does not count as recording.
- Each recorder keeps at least 90 days of video. The daily audit reads the oldest recording on each recorder.
- Video is viewed only for an incident under a Customer-approved request and never leaves the video system.
- No video is used to measure these service levels; the video system's health and retention records are.

## 10. Badge Administration and Access Reviews

- **Leavers:** the badge of every person who leaves a party's employment or the Site assignment is deactivated within 24 hours of the separation time in the Customer's identity feed (SEC-CSL-05).
- **Quarterly review:** The Security Partner prepares, and the Customer approves, a review of every active badge against each party's roster at the end of each quarter; badges not on a roster are removed the same day.

## 11. Media Destruction

**Standard:** NIST SP 800-88 Rev. 2 (Destroy), under the Customer's media sanitization standard.

- The IT Partner removes every storage drive from a failed part before the part leaves the rack area and hands the drives to the Security Partner under chain of custody (Interface Agreement HO-5).
- The Security Partner destroys each drive on site by shredding, witnessed by a second person, and issues a certificate per serial number.
- No part that held storage media ships until every one of its drive serials has a certificate.

## 12. Critical Service Levels

Critical Service Levels are measured each calendar month and tracked each ISO week (Monday 00:00 UTC to Sunday 23:59 UTC). A result worse than **Minimum** is a Minimum Service Level Default and earns the credit described in Section 14.

| ID | Service level | Category | Expected | Minimum | Credit allocation |
|---|---|---|:-:|:-:|:-:|
| SEC-CSL-01 | Guard Post Coverage | Coverage and Response | ≥ 99.5% | ≥ 98% | 30% |
| SEC-CSL-02 | Door Alarm Response | Coverage and Response | ≥ 98% | ≥ 95% | 30% |
| SEC-CSL-03 | Visitor Escort Compliance | Access Control and Visitors | 100% | ≥ 99% | 25% |
| SEC-CSL-04 | Camera Availability | Video and Chain of Custody | ≥ 99.9% | ≥ 99.5% | 20% |
| SEC-CSL-05 | Leaver Badges Removed Within 24 Hours | Access Control and Visitors | 100% | ≥ 98% | 25% |
| SEC-CSL-06 | Media Destroyed On Site Before Shipment | Video and Chain of Custody | 100% | ≥ 99.9% | 30% |
| SEC-CSL-07 | Security Record Integrity | Record Integrity | ≥ 99% | ≥ 97% | 25% |
| | **Total allocation** | | | | **185%** (pool limit 200%) |

### SEC-CSL-01: Guard Post Coverage

Share of committed post-minutes with the assigned guard badged in at the post reader.

- **Formula:** (Post-minutes with a guard badged in at the post) ÷ (Committed post-minutes) × 100
- **Expected:** ≥ 99.5%. **Minimum:** ≥ 98%.
- **Telemetry:** DS-BADGE, DS-GUARD

### SEC-CSL-02: Door Alarm Response

Door forced and door held alarms with a guard badged at the alarmed door within the priority's on-site target (3 minutes for P1, 5 minutes for P2).

- **Formula:** (Door alarms with a guard at the door within target) ÷ (Door forced and door held alarms) × 100
- **Expected:** ≥ 98%. **Minimum:** ≥ 95%.
- **Telemetry:** DS-BADGE, DS-GUARD

### SEC-CSL-03: Visitor Escort Compliance

Visitor entries into a Customer hall with the named escort badged into the same hall within 2 minutes of the visitor.

- **Formula:** (Visitor hall entries with the escort badged in within 2 minutes) ÷ (Visitor hall entries) × 100
- **Expected:** 100%. **Minimum:** ≥ 99%.
- **Telemetry:** DS-BADGE, DS-VISIT
- **Small-sample rule:** When there are fewer than 100 qualifying events in the period, any miss is a Minimum Service Level Default regardless of the percentage.

### SEC-CSL-04: Camera Availability

Share of camera-minutes recording on the Customer's video system.

- **Formula:** (Camera-minutes recording) ÷ (Camera-minutes) × 100
- **Expected:** ≥ 99.9%. **Minimum:** ≥ 99.5%.
- **Telemetry:** DS-VMS

### SEC-CSL-05: Leaver Badges Removed Within 24 Hours

People who left a party's employment or the Site assignment whose badges were deactivated within 24 hours of the separation time in the identity feed.

- **Formula:** (Leavers deactivated within 24 hours) ÷ (Leavers) × 100
- **Expected:** 100%. **Minimum:** ≥ 98%.
- **Telemetry:** DS-IDM, DS-BADGE
- **Small-sample rule:** When there are fewer than 50 qualifying events in the period, any miss is a Minimum Service Level Default regardless of the percentage.

### SEC-CSL-06: Media Destroyed On Site Before Shipment

Storage media serials from parts that left the Site with a destruction certificate dated before the part shipped.

- **Formula:** (Media serials certified destroyed before the part shipped) ÷ (Media serials in shipped parts) × 100
- **Expected:** 100%. **Minimum:** ≥ 99.9%.
- **Telemetry:** DS-COC, DS-SPARES, DS-REDFISH
- **Small-sample rule:** When there are fewer than 1000 qualifying events in the period, any miss is a Minimum Service Level Default regardless of the percentage.

### SEC-CSL-07: Security Record Integrity

Share of the Security Partner's records (posts reported staffed, door alarms closed, visitor escorts named, media certified) that reconcile with the Customer's systems.

- **Formula:** (Records that reconcile) ÷ (Records checked) × 100
- **Expected:** ≥ 99%. **Minimum:** ≥ 97%.
- **Telemetry:** DS-BADGE, DS-GUARD, DS-VISIT, DS-COC

## 13. Key Measurements

Key Measurements carry no credits. Any miss requires a root cause analysis and corrective action plan (Section 17), and repeated misses may lead the Customer to promote the measurement to a Critical Service Level (Section 22).

| ID | Key measurement | Target | Telemetry |
|---|---|:-:|---|
| SEC-KM-01 | Recorder Retention at 90 Days (daily audit) | 100% | DS-VMS |
| SEC-KM-02 | Door Alarms Acknowledged at the Console Within Target (1 min P1, 2 min P2) | ≥ 98% | DS-BADGE |
| SEC-KM-03 | Guard Tour Checkpoints Scanned On Time | ≥ 98% | DS-GUARD |
| SEC-KM-04 | Quarterly Access Review Completed by Its Due Date | 100% | DS-BADGE, DS-IDM |

## 14. Service Level Credits and Earnback

- **At-Risk Amount:** 12% of monthly charges (illustratively $186,000/month, so **$22,320** at risk each month).
- **Pool:** Credit allocations across all Critical Service Levels total 185% of the At-Risk Amount (pool limit 200%), with no single CSL above 40%.
- **Credit formula:** Credit = At-Risk Amount × CSL allocation %.
- **Monthly cap:** Total credits in a Measurement Period never exceed the At-Risk Amount.
- **Repeat defaults:** A Minimum Service Level Default on the same CSL for 3 consecutive periods earns 2× the credit. Doubled credits are not eligible for Earnback.
- **Earnback:** Supplier earns back a Service Level Credit for a Critical Service Level if it meets or exceeds the Expected Service Level for that same Critical Service Level in each of the 3 Measurement Periods immediately following the default. Earnback is not available when:
  - The credit was doubled under the repeat-default rule.
  - The default involved a confirmed Record Integrity finding (AGG-INTEGRITY).
  - The default involved a security or chain-of-custody failure (AGG-SECURITY).
- **Application:** Credits are applied against the next month's invoice.
- **EHS Credits:** handled separately under Section 21; outside this monthly cap and never earned back.
- **Nature of credits:** Service Level Credits reflect the reduced value of the services. They are not a penalty and do not limit the Customer's other rights, including chronic failure rights and EHS Credits.

See Appendix B.1 for worked credit examples.

## 15. Chronic Failure

Any of the following is a Chronic Failure:

- **CF-1:** A Minimum Service Level Default on the same CSL in 3 consecutive Measurement Periods.
- **CF-2:** A Minimum Service Level Default on the same CSL in any 4 of 6 rolling Measurement Periods.
- **CF-3:** Total Service Level Credits over 50% of the cumulative At-Risk Amount in any rolling 6 Measurement Periods.
- **CF-4:** Any confirmed deliberate falsification of records, or any storage media leaving the Site intact.

On a Chronic Failure, the Customer may:

- Terminate the affected services or the entire agreement for cause, without termination charges.
- Require a Supplier executive-sponsored recovery plan within 10 business days.
- Step-in: the Customer or a third party may perform the affected services at the Supplier's cost during recovery.

**Termination assistance:** The Supplier provides up to 90 days of transition assistance at the then-current service levels, including post orders, tour routes, and all records.

## 16. Excused Events

The Supplier must claim an Excused Event within 5 business days, with supporting evidence. Only the following qualify:

- Force majeure as defined in the Agreement.
- Failures attributed to another party under the Interface Agreement, for the time that party's fault is active (the Supplier must still respond, protect equipment, and notify).
- Customer-caused delays, including withheld access or Customer-requested holds recorded in the ticket or work order.
- Approved maintenance inside an approved change window, within the approved duration.
- OEM part unavailability, ONLY if Customer spares for that FRU class were at or above minimum stock and the Supplier notified the Customer within 4 hours.

**Treatment:** The excused occurrence is removed from both the numerator and the denominator of the affected service level. The rest of the Measurement Period is still measured.

**Supplier duty:** The Supplier must use commercially reasonable efforts to perform despite the Excused Event.

## 17. Root Cause Analysis and Corrective Action

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

## 18. Governance and Reporting Cadence

| Forum | Frequency | Attendees | Inputs |
|---|---|---|---|
| Daily operations standup | Daily, 15 minutes | Supplier shift leads; Customer site lead | Open P1 and P2 incidents, today's deployment plan, blockers, spares alerts. |
| Weekly operations review | Weekly | Supplier site manager; Customer site lead | Automated weekly scorecard, breach severity log, CAP status, staffing, lemon units. |
| Monthly service review | Monthly | Supplier account manager; Customer DCO leadership | Service Level Report, credits and earnback, chronic-failure watch, trends. |
| Quarterly business review | Quarterly | Supplier executive sponsor; Customer DCO leadership | Trend analysis, SLA change proposals, roadmap and capacity plan, program-wide lessons learned. |

## 19. Change Management

- All non-emergency changes require Customer change approval before work starts.
- Standard changes (pre-approved runbook FRU swaps) may proceed under an open incident.
- Emergency changes require verbal approval from the Customer Incident Commander, recorded in the ticket or work order within 1 hour.
- Work outside the approved window or scope is an unauthorized change and counts against KM-10.

Changes to door schedules, reader groups, and camera recording settings are changes to the Customer's systems and follow the Customer's change process. Coordination across parties follows the Interface Agreement.

## 20. Security and Chain of Custody

- Badge access only for Customer-approved personnel; no tailgating; visitors escorted at all times.
- Daily reconciliation of badge records against the shift roster.
- Storage media (e.g., E1.S drives) never leave the Site intact; media is sanitized or destroyed on site under the Customer's media sanitization standard, with a certificate per serial number.
- Every failed part is logged into chain of custody at removal, with serial, ticket or work order, technician, and timestamp.
- Cameras and photography in the data hall are prohibited except for Customer-approved documentation.

**Incident reporting:** Suspected security incidents are reported to the Customer within 1 hour of discovery.

## 21. Environmental, Health, and Safety

These terms are common to every partner SLA at the Site and bind every subcontractor. They are not subject to the monthly credit cap and cannot be weakened by any partner SLA.

### 21.1 Principles

- Safety is never traded for speed, schedule, or a service level. No target in any partner SLA justifies an unsafe act.
- Every person on Site has stop-work authority and must use it for any unsafe condition. Stopping work is never a violation and never counts against a service level.
- Consequences attach to confirmed violations of required controls, never to injuries, illnesses, or near misses that are reported. Reporting is protected (29 CFR 1904.35(b)(1)(iv)).
- Where a regulation and a requirement below differ, the more protective one applies.

### 21.2 Required standards

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

### 21.3 Site safety rules

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

### 21.4 Partner qualification

- Experience Modification Rate (EMR) of 1.0 or lower, or a Customer-approved improvement plan.
- Three years of injury rates (TRIR and DART) and five years of OSHA citation history disclosed before mobilization and annually.
- Workers' compensation coverage for every person on Site. Texas allows employers to opt out of workers' compensation; partners at this Site may not.
- A written safety program and a named, on-site EHS coordinator.
- Training records on Site for every worker: NFPA 70E qualified-person training for electrical tasks, lockout/tagout, powered equipment operation, heat illness, hazard communication, and site orientation. Supervisors hold OSHA 30-hour training.
- Subcontractors meet the same requirements; the partner remains responsible for them.

### 21.5 Reporting

- **Injuries and recordables:** to the Customer within 1 hour.
- **Near misses:** within 24 hours.
- **Severe events:** Fatalities, in-patient hospitalizations, amputations, and losses of an eye are reported to the Customer immediately and to OSHA within the 29 CFR 1904.39 deadlines (8 hours for a fatality, 24 hours for the others).
- **Monthly:** Hours worked, recordables, near misses, stop-work uses, permits issued, and open corrective actions, by partner.

### 21.6 Independent investigation

- **Trigger:** Any suspected violation of a site rule or standard above, from any source: observation, audit, telemetry, permit and badge records, or a report.
- **Investigator:** Customer EHS, or an independent third-party Certified Safety Professional engaged by the Customer. The partner whose work is investigated may not lead the investigation.
- **Partner response:** within 5 business days of notice, before a finding is confirmed.
- **Standard of proof:** Preponderance of the evidence.
- **Evidence:** Permits, job hazard analyses, lockout records, telemetry (for example, power present on a circuit recorded as locked out), badge records, witness statements, and photographs taken for the investigation.
- **Disputes:** Disputed findings go to the monthly service review, then to the independent Certified Safety Professional, whose determination of fact is final for EHS credits.

### 21.7 Violation classes and consequences

EHS Credits apply only to violations confirmed by the investigation above. Amounts are a percentage of the partner's own monthly charges (illustrated at $186,000/month for this SLA).

| Class | Examples | EHS Credit | Consequences |
|---|---|:-:|---|
| EHS-C1 Life-critical | Energized electrical work without an approved permit, or without the required second person.<br>Lockout/tagout not applied or not verified before work.<br>Entering an arc flash or shock boundary without the required PPE.<br>Bypassing or defeating a safety interlock, guard, or fire protection system.<br>A rack move without the required equipment, operator, or spotter. | 1.0% ($1,860) | Immediate stop of the task and removal of the individuals involved from Site work pending review.<br>Partner-wide safety stand-down at the Site within 24 hours.<br>Root cause analysis and corrective action plan within 5 business days.<br>Internal severity S1.<br>Customer's investigation and stand-down costs reimbursed. |
| EHS-C2 Serious | Work performed without a required job hazard analysis or permit, where no life-critical control was missed.<br>A worker performing a task without current required qualification.<br>Required PPE missing outside a hazard boundary.<br>Heat illness controls not provided at a triggering heat index. | 0.25% ($465) | Correction before work resumes.<br>Corrective action plan within 10 business days.<br>Internal severity S2. |
| EHS-C3 Administrative | Incomplete or late paperwork where the required control was in place.<br>Training records not available on Site. | None | Corrected and tracked in the weekly operations review.<br>Internal severity S3. |

### 21.8 EHS Credits

- **Outside the monthly cap:** EHS Credits are never counted toward, or limited by, the monthly cap in Section 14.
- **No earnback:** EHS Credits are never eligible for Earnback.
- **Repeat violations:** a second EHS-C1 violation within 90 days carries 2× the EHS Credit.
- **Self-reporting and concealment:** A violation the partner reports to the Customer within the reporting window and corrects before work resumes has its EHS Credit reduced by the percentage above. A violation the partner knew of and did not report, or whose records were altered, has its EHS Credit multiplied as above and is also a record-integrity finding. (Reduction: 50%. Concealment multiplier: 2×.)
- **Never based on reporting:** No EHS Credit, charge, or adverse action is ever based on the number of injuries, illnesses, or near misses reported, or on the use of stop-work authority.
- **Cost recovery:** For Life-critical violations, the partner also reimburses the Customer's documented costs of the independent investigation and of any Customer-directed stand-down.
- **Nature of EHS Credits:** EHS Credits are a price adjustment reflecting that services were not delivered to the contracted safety standard. Their amounts are a reasonable pre-estimate of costs the Customer incurs from a confirmed violation (investigation, re-verification of affected work, and operational disruption), which are real but impractical to quantify in advance. They are not a penalty, are not subject to the monthly credit cap, cannot be earned back, and do not limit the Customer's other rights, including recovery of actual costs and termination.

### 21.9 Escalation and termination

- Two Life-critical violations by one partner in any rolling 90 days: executive review and a partner-wide safety improvement plan approved by the Customer.
- Three Life-critical violations by one partner in any rolling 12 months, or one resulting in a fatality or permanent disability: a material breach, giving the Customer the right to terminate for cause.
- The Customer may require removal of any individual from Site work for safety reasons at any time.

See Appendix B.2 for a worked example.

## 22. SLA Change Control and Continuous Improvement

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
| Post reported staffed with no guard badged in (`post_reported_unstaffed`) | S2 | AGG-INTEGRITY | SEC-CSL-01, SEC-CSL-07 | Recount the post as unstaffed. Audit the post log against post reader badges for the period and confirm relief procedures. |
| Door alarm closed with no guard at the door (`door_alarm_closed_no_response`) | S2 | AGG-INTEGRITY, AGG-SECURITY | SEC-CSL-02, SEC-CSL-07 | Recount the alarm as not responded. Review the door with the Customer and retrain on badging the door reader on arrival. |
| Visitor entered a hall without the escort (`visitor_without_escort`) | S2 | AGG-SECURITY | SEC-CSL-03, SEC-CSL-07 | Review the video for the visit under a Customer-approved request. Suspend the escort's escort privilege pending review. |
| Storage media shipped without a destruction certificate (`media_shipped_without_destruction`) | S1 | AGG-SECURITY | SEC-CSL-06, SEC-CSL-07 | Contact the carrier and the OEM to recover the drive. Stop all RMA shipments until every waiting part is reconciled against the destruction log. |

## Appendix B: Worked Examples

*These examples are computed by `src/scorecard/sla_model.py` from this SLA's own parameters every time the document is generated, so the document and the scoring engine always agree.*

### B.1 Service Level Credits

**Single default: SEC-CSL-04 (camera availability) misses Minimum once.** At-Risk Amount $22,320 (12% of $186,000) × 20% allocation = $4,464. **Credit: $4,464.** Earnback eligible: Yes.

**Integrity-aggravated default: SEC-CSL-07 (record integrity) misses Minimum after posts were logged staffed with no guard badged in.** At-Risk Amount $22,320 (12% of $186,000) × 25% allocation = $5,580. **Credit: $5,580.** Earnback eligible: No.

**Small-sample rule.** SEC-CSL-03 with 44 visitor hall entries in the month, fewer than 100, and 1 entry without the escort: measured 97.7%. Under the small-sample rule any miss is a Minimum Service Level Default, whatever the percentage, so a quiet month cannot hide an unescorted visitor.

**Monthly cap.** A severe month with Minimum defaults on SEC-CSL-01, SEC-CSL-02, SEC-CSL-03, SEC-CSL-06, and SEC-CSL-07: uncapped credits total $31,248 (140% of the At-Risk Amount). The cap limits the payable credit to **$22,320**.

### B.2 EHS Credits

Three violations confirmed by independent investigation in one quarter, at $186,000/month:

| Violation | Class | Confirmed | Base | Adjustments | EHS Credit |
|---|---|:-:|:-:|---|:-:|
| EHS-1: busway tap-off worked with no lockout applied | EHS-C1 | 2026-10-06 | $1,860 | None | **$1,860** |
| EHS-2: energized work permit without the second person, self-reported | EHS-C1 | 2026-11-17 | $1,860 | repeat within 90 days: x2; self-reported and corrected: -50% | **$1,860** |
| EHS-3: expired qualification, roster altered to hide it | EHS-C2 | 2026-12-01 | $465 | concealed: x2; also a record-integrity finding | **$930** |

Total EHS Credits: **$4,650**, payable in addition to any Service Level Credits for the same months and not reduced by the monthly cap.

---

*Generated from `sla/security_partner.yaml` and the common terms in `sla/common.yaml` (schema 1.0, SLA version 1.0.0, common terms version 1.4.0). This is a fictional, illustrative security services level agreement created for a portfolio demonstration. All parties, sites, quantities, prices, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.*
