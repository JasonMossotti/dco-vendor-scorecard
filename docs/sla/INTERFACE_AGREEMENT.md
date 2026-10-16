<!--
  GENERATED FILE. DO NOT EDIT BY HAND.
  Source: sla/interface_agreement.yaml (+ party names from sla/common.yaml)  |  Generator: scripts/render_sla.py
  Edit the YAML and re-run: python scripts/render_sla.py
-->

# Interface Agreement: Site AUS-1

**Joined to the Data Center Lease (Schedule C), the IT Partner Services Agreement (Schedule B), and the Security Services Agreement (Schedule D)**

> **MOCK / ILLUSTRATIVE.** This is a fictional, illustrative interface agreement created for a portfolio demonstration. All parties, sites, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.

| Document ID | Version | Effective date |
|---|---|---|
| IA-AUS1-001 | 1.4.0 | 2026-10-16 |

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
10. [Change-Aware Alarm Notification](#10-change-aware-alarm-notification)
11. [Asset Register](#11-asset-register)

---

## 1. Purpose and Principles

This agreement joins the Landlord SLA, the IT Partner SLA, and the Security Partner SLA. It says where each party's equipment ends, who owns each component, how an outage is attributed to exactly one party, and how the parties work together during incidents and changes. Where it conflicts with a partner SLA on any of these points, this agreement governs.

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
| Security Partner | Llano Gate Protective Services, LLC *(fictional)* | Separate security services agreement and Security Partner SLA (Schedule D). Runs the Customer's security policy on the Customer's own systems. |
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
| DM-SEC | Physical security | The Customer hall entrance doors: the Landlord secures the perimeter, lobby, and corridors up to each door; the Security Partner covers the door and everything inside it. | Caprock Critical Facilities, LLC | Llano Gate Protective Services, LLC | Landlord lobby badge reader events; Customer access control system events at each hall door (door alarms, guard post readers). |

## 4. Break-Fix Ownership Matrix

**R** = Responsible: performs the work; **A** = Accountable: owns the outcome and approves; **C** = Consulted; **I** = Informed. Every component has exactly one Accountable party.

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
| Fire alarm panel, VESDA, pre-action sprinklers, and clean agent suppression | I | I | A/R | - | - | - |
| BMS and EPMS operation | C | - | A/R | - | - | - |
| Core network services: DNS, DHCP, and NTP and PTP time | A/R | I | I | - | - | - |
| Firewalls and network segmentation, including the monitoring network | A/R | I | C | - | - | - |
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

- **Commander:** The Customer is Incident Commander for any P1 under any partner SLA and for any event involving more than one party.
- Landlord lead: facility status, isolation, and restoration.
- IT Partner lead: rack protection, controlled shutdowns, and return-to-service validation.
- Security Partner lead: guard posts, door control, escorts, and chain of custody for any media involved.
- Customer Incident Commander: priorities, decisions, and all communications to Customer leadership.

- **Bridge:** A joint bridge opens within 15 minutes of a multi-party P1. Each lead updates the Incident Commander at the strictest of the involved partners' SLA update cadences.
- **Post-incident review:** A joint post-incident review within 5 business days produces one timeline from the Telemetry of Record, the attribution decision, and actions tracked in each party's corrective action process.

## 7. Handoffs

| ID | Handoff | Rule |
|---|---|---|
| HO-1 | Facility restored to IT validation | The Landlord declares restoration in the joint bridge; the Customer confirms it from telemetry (feeds in tolerance, cooling in band); the IT Partner then validates each affected rack. |
| HO-2 | De-energizing a tap-off for rack work | The IT Partner requests it under an approved change; the Landlord isolates under group lockout with both parties' locks applied (EHS-R2). |
| HO-3 | Leak at a rack | The IT Partner isolates at the rack manifold valves; the Landlord isolates at the header if the leak is upstream of the valves; both follow the spill procedure (EHS-R5). |
| HO-4 | New rack energization | The Landlord energizes the tap-off and opens the isolation valves only after the IT Partner confirms the rack is set, leak-tested, and ready; the time is recorded as the deployment milestone handoff. |
| HO-5 | Storage media from a failed part | The IT Partner removes every drive from a failed part in the rack area and hands the drives to the Security Partner under chain of custody, by serial number; the Security Partner destroys them on site and certifies each serial before the part may ship. |

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

## 10. Change-Aware Alarm Notification

Planned work causes alarms the parties can predict. Each change therefore declares the alarms it expects, and anything else that happens on the equipment it touches reaches the Customer at once, automatically, from the party doing the work. The Customer runs its own check on the same feeds so that it never depends on a party's notification alone.

**Impact declaration**

- Every change record, method of procedure, and planned work order (other than routine preventive maintenance with no expected alarm) declares its impact in the Customer's schema before approval: the assets touched, the alarms each asset is expected to raise, the worst severity the work may cause, whether redundancy is reduced, and the window.
- A change without a declaration is not approved. A declaration is part of the approved change: work outside it is outside the approval (common terms, change management).
- An alarm counts as expected only on a declared asset, with a declared alarm, at or below the declared severity, inside the window plus 15 minutes either side.

**Out of scope and out of window**

- Out of scope: during a window, an alarm on a declared asset that the declaration did not list or that exceeds the declared severity, or an alarm on equipment connected to a declared asset (the same load, a redundant partner, or the load it serves, from the site model) of a kind the work could cause.
- Out of window: a declared alarm raised before the window opens, or a declared asset still in its maintenance state 15 minutes after the window closes.
- An out-of-scope or out-of-window alarm means the records do not reconcile with the approved change; it is not by itself a finding against anyone.

**Notifications owed to the Customer**

| ID | Trigger | Within | Channels | Owed by |
|---|---|---|---|---|
| NT-1 | Critical alarm (P1 under any partner SLA) not expected under a declared change | 5 min | Page to the Customer Incident Commander plus email or SMS | The party that owns the equipment |
| NT-2 | Major alarm (P2) not expected under a declared change | 15 min | Two of email, SMS, and the Customer alarm feed | The party that owns the equipment |
| NT-3 | Any out-of-scope or out-of-window alarm on change work | 5 min | Two of email, SMS, and the Customer alarm feed; a page as well if the alarm is critical | The party doing the change, whoever owns the equipment |

- Notifications are sent by each party's monitoring system without a person deciding whether to send. A call from a duty manager does not count toward the two channels.
- Each notification carries the alarm, device, location, severity, the change it relates to, and the party's ticket or work order.
- Each party keeps a delivery log (alarm, channel, recipient, sent, delivered) and gives the Customer read access to it, with the alarm feeds under section 9.
- Whether a notification was owed is decided from the Customer's Telemetry of Record and the declarations, not from the party's own classification.

**Customer backstop:** The Customer's alarm board reads both parties' feeds, classifies every alarm against the declared changes, and alerts the Customer's on-call directly. A missed or late party notification is still counted against that party.

**Key measures**

| ID | Party | Measure | Target | Data sources |
|---|---|---|---|---|
| IA-KM-01 | Landlord | Change-aware notifications on time (NT-1 to NT-3) | 99.0% | Customer alarm board; Landlord delivery log |
| IA-KM-02 | IT Partner | Change-aware notifications on time (NT-1 to NT-3) | 99.0% | Customer alarm board; IT Partner delivery log |

Key measures report and trigger corrective action; they carry no service credit. Moving them to credit-bearing service levels is a later negotiation once both delivery logs have proved reliable.

## 11. Asset Register

One register follows every asset at the site by serial, from receipt to install, RMA, and disposal. A quantity count shows how many parts are on the shelf; only the serials show which, and only the devices' own answers show what is really installed.

| ID | Rule | Text |
|---|---|---|
| REG-1 | One register | The Customer's asset register holds every asset at the site by serial: installed devices and their field-replaceable parts, spares, parts removed for RMA, and storage media removed from service. Each party records the assets it maintains: the IT Partner its IT equipment and the spares cage, the Landlord its facility equipment, and the Security Partner the media in its custody. |
| REG-2 | Record every move within 4 hours | Every receipt, install, removal, RMA shipment, custody handover, destruction, and disposal is recorded by serial within 4 hours of the work, citing the ticket, work order, RMA, milestone, or certificate. |
| REG-3 | Receive deliveries within 24 hours | A delivery signed for at the dock (carrier proof of delivery) is received into the register and the spares ledger within 24 hours. |
| REG-4 | Daily reconciliation | The Customer reconciles the register every day against the serials the devices report (Redfish SerialNumber; SNMP entPhysicalSerialNum), the spares ledger, RMA shipments, the OEM's RMA portal, custody handovers, and destruction and disposal certificates. A device that does not answer is a gap in evidence, not a finding. |
| REG-5 | Disposal by serial | A disposal certificate names the serial of every asset it covers and is witnessed by the Security Partner. A disposed serial that answers on any network is an asset whose disposal is unconfirmed: the party that disposed of it and the Security Partner trace it the same day. |
| REG-6 | Serial-level cycle counts | The monthly full count of the spares cage checks serials, not only quantities, so a removed part returned to the shelf in place of a good one is found. |

## 12. Fire Protection Impairments

The Landlord owns fire protection; the Customer's halls depend on it. An impairment is any time all or part of a fire alarm, detection, or suppression system is out of service, planned or not (NFPA 25, 2026 edition, chapter 15; NFPA 72, 2025 edition; NFPA 2001, 2025 edition for clean agent). The fire panel's history log records when protection was out; the Landlord's impairment log says why and who. A trouble on one detector while adjacent detection keeps coverage is not an impairment.

| ID | Rule | Text |
|---|---|---|
| FPI-1 | Notice before planned work | A planned impairment is notified to the Customer at least 24 hours before it begins, naming the points to be disabled, the window, and the method of procedure where one applies. |
| FPI-2 | Unplanned impairment | An unplanned impairment is notified to the Customer within 15 minutes of discovery and handled as a P1 under OT-FC-FIRE. |
| FPI-3 | Fire watch | When an impairment lasts more than 4 hours, a fire watch patrols the affected area from no later than the fourth hour until restoration, logged with its start and end. Where the authority having jurisdiction sets a stricter threshold, that threshold applies. |
| FPI-4 | Restore within the window, or extend with notice | A planned impairment is restored by the end of its window, or an extension naming the new end time is notified to the Customer before the window ends. |
| FPI-5 | Restoration is what the panel shows | An impairment is restored when the fire panel shows every disabled point enabled and every supervisory signal on it cleared. The Landlord's impairment log records that time within 15 minutes and notifies the Customer within 30 minutes. |
| FPI-6 | Log every impairment | A disabled point or a supervisory signal on a suppression valve or release circuit that lasts more than 30 minutes is an impairment and goes on the log. The Customer reconciles the log with the panel's history every day. |

---

*Generated from `sla/interface_agreement.yaml` (version 1.4.0). This is a fictional, illustrative interface agreement created for a portfolio demonstration. All parties, sites, and terms are invented. It is not legal advice and is not derived from any real organization's internal documents or contracts.*
