# Landlord Discrepancy Report

Each finding is a place where the Landlord's work orders or maintenance records do not reconcile with the device telemetry the Customer reads under the Interface Agreement. A finding starts a review; it is not by itself proof of intent.

| ID | Severity | Type | Unit | Summary |
|---|:-:|---|---|---|
| L-001 | S1 Critical | Fault attributed to another party against the telemetry | BW-A-R3-PG-A4-B | WO-41051 attributes the BW-A-R3-PG-A4-B event to the IT Partner ('Tenant whip fault on rack A18; Landlord equipment healthy'), but the Telemetry of Record shows the fault on Landlord equipment (BW-A-R3-PG-A4-B feed lost (Voltage L-L avg 0.0 V)). Rule FA-5 applies. |
| L-002 | S1 Critical | Maintenance closed without evidence | Hall A electrical room | PM-0018 (Infrared thermography under load, Hall A electrical room) was closed by CCF-E02 at 2026-09-10 20:08 UTC, but CCF-E02 never badged into Hall A electrical room in the 6 hours before. |
| L-003 | S1 Critical | Generator test reported without load | GEN-4 | GEN-4 monthly test recorded as 'Pass at 40% load', but the EMCP shows 38 running minutes peaking at 3% of rated kW. NFPA 110 needs 30% for 30 minutes. |
| L-004 | S1 Critical | BMS override or alarm inhibit without a change record | TW-B2 | Inhibit on TW-B2 'High supply air temperature alarm' set to Inhibited by CCF-E09 with no change reference, held 34.3 hours. |
| L-005 | S1 Critical | Work order restored before the telemetry | CDU-A1 | WO-41025 records CDU-A1 restored at 2026-09-24 00:12 UTC, 154 minutes before the telemetry shows restoration at 2026-09-24 02:47 UTC. Measured restoration is 292 minutes, not 138. |
| L-006 | S1 Critical | Critical work without an approved MOP | BW-B-R3-PG-B4-A | Tap-off TO-B09 breaker opened on BW-B-R3-PG-B4-A at 2026-09-24 17:22 UTC with no approved MOP covering that asset and time (WO-41014: Tap-off TO-B09 retorque and energization). |
| L-007 | S2 Major | Alarm acknowledged but never dispatched | CH-01 | CH-01 alarm acknowledged at 2026-09-13 23:46 UTC and WO-41070 says an engineer attended at 2026-09-13 23:57 UTC, but nobody badged into Chiller yard before it cleared at 2026-09-14 04:39 UTC. |

## L-001: Fault attributed to another party against the telemetry (S1 Critical)

WO-41051 attributes the BW-A-R3-PG-A4-B event to the IT Partner ('Tenant whip fault on rack A18; Landlord equipment healthy'), but the Telemetry of Record shows the fault on Landlord equipment (BW-A-R3-PG-A4-B feed lost (Voltage L-L avg 0.0 V)). Rule FA-5 applies.

| Source | When | Detail |
|---|---|---|
| `landlord/work_orders.json` | 2026-09-04 03:25 UTC | Attribution: IT Partner |
| `DS-BUSWAY` | 2026-09-04 03:24 UTC | BW-A-R3-PG-A4-B feed lost (Voltage L-L avg 0.0 V) |

**Recommended action:** Apply the Interface Agreement attribution rules from the Telemetry of Record and correct the work order. Review with both parties at the monthly service review.

**SLA references:** OT-CSL-01, OT-CSL-02, OT-CSL-08

## L-002: Maintenance closed without evidence (S1 Critical)

PM-0018 (Infrared thermography under load, Hall A electrical room) was closed by CCF-E02 at 2026-09-10 20:08 UTC, but CCF-E02 never badged into Hall A electrical room in the 6 hours before.

| Source | When | Detail |
|---|---|---|
| `landlord/pm_records.csv` | 2026-09-10 20:08 UTC | PM-0018 closed: Pass; evidence 'Engineer sign-off' |
| `access/landlord_badge_events.csv` |  | No entry to Hall A electrical room by CCF-E02 |

**Recommended action:** Reopen the task. Audit the engineer's other closures in the period against badge and device records.

**SLA references:** OT-CSL-06, OT-CSL-08

## L-003: Generator test reported without load (S1 Critical)

GEN-4 monthly test recorded as 'Pass at 40% load', but the EMCP shows 38 running minutes peaking at 3% of rated kW. NFPA 110 needs 30% for 30 minutes.

| Source | When | Detail |
|---|---|---|
| `landlord/pm_records.csv` | 2026-09-12 18:08 UTC | PM-0004 Monthly loaded exercise: Pass at 40% load |
| `facility/emcp_readings.jsonl` | 2026-09-12 17:25 UTC | 38 minutes running; 0 at or above 30%; peak 3.3% |

**Recommended action:** Recount the test as not done. Confirm EMCP data for every generator test in the period and schedule a compliant test.

**SLA references:** OT-CSL-06, OT-KM-02, OT-CSL-08

## L-004: BMS override or alarm inhibit without a change record (S1 Critical)

Inhibit on TW-B2 'High supply air temperature alarm' set to Inhibited by CCF-E09 with no change reference, held 34.3 hours.

| Source | When | Detail |
|---|---|---|
| `facility/bms_events.jsonl` | 2026-09-19 01:27 UTC | inhibit set: High supply air temperature alarm = Inhibited, change_ref empty |
| `facility/bms_events.jsonl` | 2026-09-20 11:47 UTC | released |

**Recommended action:** Release the override or inhibit, or record it under an approved change with an expiry. Review alarm suppression controls.

**SLA references:** OT-CSL-07, OT-KM-05

## L-005: Work order restored before the telemetry (S1 Critical)

WO-41025 records CDU-A1 restored at 2026-09-24 00:12 UTC, 154 minutes before the telemetry shows restoration at 2026-09-24 02:47 UTC. Measured restoration is 292 minutes, not 138.

| Source | When | Detail |
|---|---|---|
| `landlord/work_orders.json` | 2026-09-24 00:12 UTC | WO-41025 restored_at |
| `DS-CDU` | 2026-09-24 02:47 UTC | Device reports redundancy restored |

**Recommended action:** Recalculate restoration from the device telemetry. Confirm work orders take their restore time from the telemetry, not from the engineer's entry.

**SLA references:** OT-CSL-05, OT-CSL-08

## L-006: Critical work without an approved MOP (S1 Critical)

Tap-off TO-B09 breaker opened on BW-B-R3-PG-B4-A at 2026-09-24 17:22 UTC with no approved MOP covering that asset and time (WO-41014: Tap-off TO-B09 retorque and energization).

| Source | When | Detail |
|---|---|---|
| `facility/busway_cpm_events` | 2026-09-24 17:22 UTC | Tap-off TO-B09 breaker opened |
| `customer/landlord_mop_approvals.json` |  | No approved MOP for BW-B-R3-PG-B4-A at that time |

**Recommended action:** Stop similar work until MOP control is confirmed. Joint review with the Customer change board.

**SLA references:** OT-CSL-07

## L-007: Alarm acknowledged but never dispatched (S2 Major)

CH-01 alarm acknowledged at 2026-09-13 23:46 UTC and WO-41070 says an engineer attended at 2026-09-13 23:57 UTC, but nobody badged into Chiller yard before it cleared at 2026-09-14 04:39 UTC.

| Source | When | Detail |
|---|---|---|
| `facility/bms_events.jsonl` | 2026-09-13 23:46 UTC | Alarm acknowledged |
| `landlord/work_orders.json` | 2026-09-13 23:57 UTC | WO-41070: Engineer attended and reset the unit |
| `access/landlord_badge_events.csv` |  | No entry to Chiller yard between alarm and clear |

**Recommended action:** Recalculate response from badge evidence. Review the acknowledgment workflow so an acknowledgment cannot stand in for a response.

**SLA references:** OT-CSL-04, OT-CSL-05

## Engine self-check

Detected 7 of 7 planted discrepancies; 0 false positives.

| Type | Planted | Detected |
|---|:-:|:-:|
| alarm_acked_no_dispatch | 1 | 1 |
| attribution_contradicted | 1 | 1 |
| bms_override_unrecorded | 1 | 1 |
| critical_work_no_mop | 1 | 1 |
| gen_test_no_load | 1 | 1 |
| landlord_clock_shift | 1 | 1 |
| pm_without_evidence | 1 | 1 |
