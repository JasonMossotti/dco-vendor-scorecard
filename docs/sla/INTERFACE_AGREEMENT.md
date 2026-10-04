<!--
  GENERATED FILE. DO NOT EDIT BY HAND.
  Source: sla/interface_agreement.yaml (+ party names from sla/common.yaml)  |  Generator: scripts/render_sla.py
  Edit the YAML and re-run: python scripts/render_sla.py
-->

# Interface Agreement: Site AUS-1

**Joined to the Data Center Lease (Schedule C) and the IT Partner Services Agreement (Schedule B)**

> **MOCK / ILLUSTRATIVE.** This is a fictional, illustrative interface agreement created for a portfolio demonstration. All parties, sites, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.

| Document ID | Version | Effective date |
|---|---|---|
| IA-AUS1-001 | 1.0.0 | 2026-10-05 |

## Contents

1. [Purpose and Principles](#1-purpose-and-principles)
2. [Parties](#2-parties)
3. [Demarcation Points](#3-demarcation-points)
4. [Break-Fix Ownership Matrix](#4-break-fix-ownership-matrix)
5. [Fault Attribution](#5-fault-attribution)
6. [Joint Incident Command](#6-joint-incident-command)
7. [Handoffs](#7-handoffs)
8. [Change Coordination](#8-change-coordination)
9. [Customer Data Access](#9-customer-data-access)

---

## 1. Purpose and Principles

This agreement joins the Landlord SLA and the IT Partner SLA. It says where each party's equipment ends, who owns each component, how an outage is attributed to exactly one party, and how the parties work together during incidents and changes. Where it conflicts with a partner SLA on any of these points, this agreement governs.

- Every component has exactly one Accountable party.
- Boundaries are physical points a technician can see and touch, so ownership is never a matter of opinion.
- Outages are attributed from the Customer's Telemetry of Record by walking the site's power and cooling paths, never from ticket text alone.
- No party's SLA clock runs for time another party's fault is active, and no outage goes unowned.
- The common terms, including EHS, bind every party working at the Site.

## 2. Parties

| Party | Name | Role |
|---|---|---|
| Customer | Customer | Owns site outcomes; directs the IT partner; operates the Telemetry of Record; holds the Landlord to its SLA. |
| Landlord | Caprock Critical Facilities, LLC *(fictional)* | Separate lease and Landlord SLA (Schedule C). Bound by the common terms, including EHS. |
| IT Partner | Ridgeline Site Services, LLC *(fictional)* | Separate services agreement and IT Partner SLA (Schedule B). |
| OEM | OEM / System Integrator | Separate contract. Named here only to define ownership boundaries. |
| Utility | Serving utility (ERCOT region) | Contracts with the Landlord. Named here only to define ownership boundaries. |

## 3. Demarcation Points

| ID | System | Boundary | Upstream owner | Downstream owner | Evidence on each side |
|---|---|---|---|---|---|
| DM-PWR | Power | Output terminals of the busway tap-off unit. | Caprock Critical Facilities, LLC | Ridgeline Site Services, LLC | Busway Critical Power Monitor at the segment (Landlord side); rack power shelf input via Redfish (IT side). |
| DM-COOL | Liquid cooling | Rack manifold isolation valves (supply and return). | Caprock Critical Facilities, LLC | Ridgeline Site Services, LLC | CDU secondary supply temperature, flow, and pressure via Redfish (Landlord side); tray and manifold leak sensors via the rack BMC (IT side). |
| DM-AIR | Air cooling | Cold aisle supply air at the rack face. | Caprock Critical Facilities, LLC | Ridgeline Site Services, LLC | Cold-aisle temperature sensors in the BMS; rack inlet temperatures via Redfish. |
| DM-UTIL | Utility service | 13.8 kV main breakers in the Landlord's switchgear. | Serving utility (ERCOT region) | Caprock Critical Facilities, LLC | Utility revenue metering; main breaker status in the EPMS. |
| DM-NET | Network | Meet-me room cross-connect panel. | Caprock Critical Facilities, LLC | Ridgeline Site Services, LLC | Cross-connect records; optical power at the IT side of the panel. |
| DM-MON | Monitoring | The read-only interfaces listed under Customer data access. | Caprock Critical Facilities, LLC | Customer | Feed availability measured by the Customer collector (OT-KM-06). |

## 4. Break-Fix Ownership Matrix

**R** = Responsible: performs the work; **A** = Accountable: owns the outcome and approves; **C** = Consulted; **I** = Informed. Every component has exactly one Accountable party.

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

## 5. Fault Attribution

When the Telemetry of Record shows rack capacity lost, the Customer walks that rack's power and cooling paths in the site model (site/site.yaml) as of T0. The first unhealthy component, starting from the source, decides which party owns the outage.

| Rule | Text |
|---|---|
| **FA-1** | If every feed of the rack was out of tolerance at the tap-off at or before T0, or the CDU secondary supply at the rack was out of band, the outage is Landlord-attributed from T0. |
| **FA-2** | If the Landlord side was healthy at T0, the outage is IT Partner-attributed and runs under the IT Partner SLA. |
| **FA-3** | When a Landlord-attributed outage ends (Landlord restoration declared and confirmed by telemetry), the IT Partner's clock starts at that handoff time, for validating the rack's return to service. The IT Partner is never measured for the Landlord's minutes. |
| **FA-4** | If one party's action caused another party's equipment to fail (for example, an IT Partner whip fault tripping a tap-off breaker), the outage is attributed to the party whose action caused it, as found by the joint post-incident review. |
| **FA-5** | Loss of one feed or of N+1 cooling with no capacity lost is a Landlord redundancy event (OT-CSL-02, OT-CSL-05) and does not stop or start any IT Partner clock. |
| **FA-6** | Utility outages are Utility-attributed; the Landlord is measured on carrying the load (transfer, generators, and UPS) and is attributed any capacity lost during a utility event. |

**Disputes:** The Customer determines attribution from the Telemetry of Record within 2 business days. A party may appeal to the monthly service review with evidence; attribution is never decided from ticket or work order text alone.

## 6. Joint Incident Command

- **Commander:** The Customer is Incident Commander for any P1 under either SLA and for any event involving more than one party.
- Landlord lead: facility status, isolation, and restoration.
- IT Partner lead: rack protection, controlled shutdowns, and return-to-service validation.
- Customer Incident Commander: priorities, decisions, and all communications to Customer leadership.

- **Bridge:** A joint bridge opens within 15 minutes of a multi-party P1. Each lead updates the Incident Commander at the stricter of the two SLAs' update cadences.
- **Post-incident review:** A joint post-incident review within 5 business days produces one timeline from the Telemetry of Record, the attribution decision, and actions tracked in each party's corrective action process.

## 7. Handoffs

| ID | Handoff | Rule |
|---|---|---|
| HO-1 | Facility restored to IT validation | The Landlord declares restoration in the joint bridge; the Customer confirms it from telemetry (feeds in tolerance, cooling in band); the IT Partner then validates each affected rack. |
| HO-2 | De-energizing a tap-off for rack work | The IT Partner requests it under an approved change; the Landlord isolates under group lockout with both parties' locks applied (EHS-R2). |
| HO-3 | Leak at a rack | The IT Partner isolates at the rack manifold valves; the Landlord isolates at the header if the leak is upstream of the valves; both follow the spill procedure (EHS-R5). |
| HO-4 | New rack energization | The Landlord energizes the tap-off and opens the isolation valves only after the IT Partner confirms the rack is set, leak-tested, and ready; the time is recorded as the deployment milestone handoff. |

## 8. Change Coordination

- Any change touching a demarcation point needs a joint method of procedure approved by the Customer and both parties.
- Landlord work that reduces redundancy is notified at least 10 business days ahead and done in a Customer-approved window; emergency work is notified as soon as it is known and at least 1 hour ahead where possible.
- Group lockout under EHS-R2 for any multi-party work.
- BMS point overrides and alarm inhibits carry a change reference and an expiry, and are visible to the Customer in real time.

## 9. Customer Data Access

The Customer's right to read facility telemetry is a negotiated term of the Lease, not a courtesy. Without it, the Landlord SLA would be measured by the Landlord.

- Read-only access to: UPS network management cards (SNMPv3), busway Critical Power Monitors (Modbus TCP), generator controllers (EMCP 4.4, Modbus TCP), CDU controllers (Redfish), and leak detection controllers (Modbus via gateway).
- A real-time export of BMS and EPMS alarms, acknowledgments, point overrides, and alarm inhibits, and one-minute trend data for the points that measure the Landlord SLA.
- Read-only access is enforced at each device (no write credentials are issued) over a segmented monitoring network the Landlord approves.
- The Landlord may not disable, filter, or delay the feeds. A feed outage over 15 minutes is a Landlord P2 and counts against OT-KM-06.
- The Landlord keeps 13 months of BMS and EPMS history and provides it within 5 business days of a request.
- All systems are NTP-synchronized; clock skew over 5 seconds is flagged under the common measurement terms.
- The Customer uses the data only to measure the SLAs, attribute outages, and protect safety, and shares it with the IT Partner only as needed for attribution.

---

*Generated from `sla/interface_agreement.yaml` (version 1.0.0). This is a fictional, illustrative interface agreement created for a portfolio demonstration. All parties, sites, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.*
