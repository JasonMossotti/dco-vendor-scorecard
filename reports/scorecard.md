<!-- GENERATED FILE. DO NOT EDIT BY HAND. Run: python scripts/build_scorecard.py -->

# Vendor SLA Scorecard

> Synthetic data for a portfolio demonstration. All sites, people, serials, events, and commercial terms are fictional.

**Site:** Site AUS-1 (fictional)  
**Supplier:** Ridgeline Site Services, LLC  
**Measurement period:** 2026-08-31 00:00 UTC to 2026-09-28 00:00 UTC (4 weeks)

## Headline

The supplier's weekly reports claimed every SLA was met in 4 of 4 weeks, and raised no escalations. Measured from the Telemetry of Record, the period has **4 Minimum Service Level Defaults** (CSL-07, CSL-08, CSL-09, CSL-11), **14 S1 items** in the severity log, and **$188,700 in Service Level Credits**.

Fleet availability looks almost identical either way (99.927% reported, 99.927% measured): a handful of hidden hours disappears inside 75 tickets on a 2,300-GPU hall. The gaps show up in restoration, repair quality, and record integrity, which is why the scorecard measures each incident, not just the average.

## Vendor reported vs. measured

| Service level | Vendor reported | Measured from telemetry | Gap |
|---|:-:|:-:|:-:|
| CSL-01 Supplier-Attributable GPU Availability | 99.93% | **99.93%** | +0.00 pts |
| CSL-03 P1 Restoration Within 4 Hours | 100.00% | **100.00%** | +0.00 pts |
| CSL-04 P2 Restoration Within 8 Hours | 100.00% | **92.31%** | -7.69 pts |
| CSL-05 P3 Restoration Within 24 Hours | 100.00% | **100.00%** | +0.00 pts |
| CSL-06 First-Time Fix Rate | 100.00% | **90.28%** | -9.72 pts |
| CSL-07 Validated Return to Service | 100.00% | **97.22%** | -2.78 pts |
| CSL-10 Qualified Staffing Fill Rate | 100.00% | **98.90%** | -1.10 pts |

Record integrity (CSL-11), repeat failures (CSL-08), deployment adherence (CSL-09), and worst-rack availability (CSL-12) do not appear in the supplier's report at all.

## Critical Service Levels

| ID | Service level | Expected | Minimum | Measured | Status | Credit | Basis |
|---|---|:-:|:-:|:-:|---|--:|---|
| CSL-01 | Supplier-Attributable GPU Availability | ≥ 99.5% | ≥ 99% | 99.93% | Met | - | 1,279 capacity-weighted GPU-hours lost of 1,760,490 installed |
| CSL-02 | P1 Engaged On-Site Within 15 Minutes | 100% | ≥ 95% | 100.00% | Met | - | 3 of 3 P1 incidents with a badge-verified technician within 15 min. Small-sample rule: 3 events, 0 misses. |
| CSL-03 | P1 Restoration Within 4 Hours | ≥ 95% | ≥ 90% | 100.00% | Met | - | 3 of 3 P1 Tickets of Record restored within 4 hrs. Small-sample rule: 3 events, 0 misses. |
| CSL-04 | P2 Restoration Within 8 Hours | ≥ 95% | ≥ 90% | 92.31% | Below Expected | - | 48 of 52 P2 Tickets of Record restored within 8 hrs |
| CSL-05 | P3 Restoration Within 24 Hours | ≥ 95% | ≥ 90% | 100.00% | Met | - | 17 of 17 P3 Tickets of Record restored within 24 hrs |
| CSL-06 | First-Time Fix Rate | ≥ 92% | ≥ 88% | 90.28% | Below Expected | - | 65 of 72 repairs fixed the first time |
| CSL-07 | Validated Return to Service | 100% | ≥ 98% | 97.22% | **Minimum default** | $55,500 | 70 of 72 returns to service had the full validation checklist |
| CSL-08 | 30-Day Repeat Failure Rate | ≤ 3% | ≤ 5% | 9.72% | **Minimum default (severe)** | $44,400 | 7 of 72 repaired units failed again within 30 days |
| CSL-09 | Deployment Milestone Adherence | ≥ 95% | ≥ 90% | 76.92% | **Minimum default (severe)** | $44,400 | 10 of 13 racks due this period reached Validated Handoff on time |
| CSL-10 | Qualified Staffing Fill Rate | ≥ 98% | ≥ 95% | 98.90% | Met | - | 4,320 of 4,368 committed technician hours badge-verified |
| CSL-11 | Record Integrity | ≥ 99% | ≥ 97% | 82.67% | **Minimum default (severe)** | $44,400 | 13 of 75 closed tickets did not reconcile with telemetry |
| CSL-12 | Worst-Rack Availability | ≥ 99% | ≥ 97.5% | 99.49% | Met | - | Worst rack A15: 247 GPU-hours lost |

## Service Level Credits

| CSL | Credit | Calculation | Earnback eligible |
|---|--:|---|:-:|
| CSL-07 | $55,500 | At-Risk Amount $222,000 (12% of $1,850,000) × 25% allocation = $55,500 | Yes |
| CSL-08 | $44,400 | At-Risk Amount $222,000 (12% of $1,850,000) × 20% allocation = $44,400 | Yes |
| CSL-09 | $44,400 | At-Risk Amount $222,000 (12% of $1,850,000) × 20% allocation = $44,400 | Yes |
| CSL-11 | $44,400 | At-Risk Amount $222,000 (12% of $1,850,000) × 20% allocation = $44,400 | No |
| **Total** | **$188,700** | | |

Payable after the monthly cap (the At-Risk Amount): **$188,700**.

## Week by week

| Week starting | Availability (vendor / measured) | P2 restore (vendor / measured) | First-time fix (vendor / measured) | Staffing (vendor / measured) | Findings | Vendor's note |
|---|:-:|:-:|:-:|:-:|:-:|---|
| 2026-08-31 | 99.943% / 99.925% | 100.0% / **66.7%** | 100.0% / **68.4%** | 100.0% / 97.8% | 7 | All SLAs met. No open escalations. |
| 2026-09-07 | 99.954% / 99.955% | 100.0% / **100.0%** | 100.0% / **94.4%** | 100.0% / 100.0% | 5 | All SLAs met. No open escalations. |
| 2026-09-14 | 99.917% / 99.917% | 100.0% / **100.0%** | 100.0% / **100.0%** | 100.0% / 97.8% | 3 | All SLAs met. No open escalations. |
| 2026-09-21 | 99.895% / 99.917% | 100.0% / **100.0%** | 100.0% / **100.0%** | 100.0% / 100.0% | 3 | All SLAs met. No open escalations. |

## Corrective action plans

17 plans drafted automatically: one per affected ticket group (or service level) for every S1 and S2 item. Plans are raised at this period review; due dates follow the severity index (S1: 5 business days, S2: 10).

| CAP | Severity | Tickets | Triggers | Required actions | Owner | Raised | Due |
|---|:-:|---|---|---|---|---|---|
| CAP-001 | S1 | INC3100068, INC3100085 | F-001 Ticket split to restart the clock; INC3100068 P2 restore 10.4 hrs vs 8-hr target | Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold. RCA on the delay (dispatch, diagnosis, parts, or validation) with a corrective action for the cause. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-002 | S1 | INC3100136, INC3100170 | F-002 Ticket split to restart the clock; INC3100136 P2 restore 11.1 hrs vs 8-hr target; F-011 Link errors continued after optic replacement | Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold. RCA on the delay (dispatch, diagnosis, parts, or validation) with a corrective action for the cause. Require inspection of both link ends before replacing an optic. Merge the follow-up ticket under TR-2. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-003 | S1 | INC3100221, INC3100238 | F-003 Ticket split to restart the clock; INC3100221 P2 restore 9.9 hrs vs 8-hr target | Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold. RCA on the delay (dispatch, diagnosis, parts, or validation) with a corrective action for the cause. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-004 | S1 | INC3100289 | F-004 On-site claim before badge-in | Correct the engaged time from badge data. Review the record with the vendor site manager and agree on corrective steps for the technician. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-005 | S1 | INC3100357 | F-005 Ticket opened late (clock shift); INC3100357 P2 restore 9.0 hrs vs 8-hr target | Recalculate restoration from telemetry T0. Confirm the alerting integration opened the Ticket of Record at T0 and find out why the vendor ticket started later. RCA on the delay (dispatch, diagnosis, parts, or validation) with a corrective action for the cause. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-006 | S1 | INC3100510 | F-006 Returned to service without validation | Drain the unit and run the full validation checklist now. Audit other returns by the same technician this period. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-007 | S1 | INC3100629 | F-007 Part swap not confirmed by inventory | Physically verify the serial in the slot. If the part was not replaced, reopen the ticket, replace it, and stop the RMA of the still-installed serial. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-008 | S1 | INC3100748 | F-008 Returned to service without validation | Drain the unit and run the full validation checklist now. Audit other returns by the same technician this period. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-009 | S1 | INC3100935 | F-009 Part swap not confirmed by inventory | Physically verify the serial in the slot. If the part was not replaced, reopen the ticket, replace it, and stop the RMA of the still-installed serial. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-010 | S1 | INC3101241 | F-010 On-site claim before badge-in | Correct the engaged time from badge data. Review the record with the vendor site manager and agree on corrective steps for the technician. | Supplier site manager | 2026-09-28 | 2026-10-05 |
| CAP-011 | S2 | INC3100204, INC3100391 | F-012 Same fault recurred after a reseat | Replace rather than reseat on any recurrence. Add a one-reseat-maximum rule to the break-fix runbook and require an RCA. | Supplier site manager | 2026-09-28 | 2026-10-12 |
| CAP-012 | S2 | INC3100102, INC3100374, INC3100595 | F-013 Repeat-failing unit not escalated | Remove the unit from service and open an OEM RMA. Find out why the lemon rule did not trigger an escalation. | Supplier site manager | 2026-09-28 | 2026-10-12 |
| CAP-013 | S2 | INC3100663, INC3100833 | F-014 Same fault recurred after a reseat | Replace rather than reseat on any recurrence. Add a one-reseat-maximum rule to the break-fix runbook and require an RCA. | Supplier site manager | 2026-09-28 | 2026-10-12 |
| CAP-014 | S2 | Rack A29 | F-015 Change without an approved change record | Verify firmware against the approved baseline and roll back if needed. Require a vendor RCA on the change-control breach. | Supplier site manager | 2026-09-28 | 2026-10-12 |
| CAP-015 | S2 | - | CSL-08 30-Day Repeat Failure Rate: Minimum default (severe) | Supplier RCA and corrective action plan for CSL-08 (SLA Section 17). | Supplier site manager | 2026-09-28 | 2026-10-12 |
| CAP-016 | S2 | - | CSL-09 Deployment Milestone Adherence: Minimum default (severe) | Supplier RCA and corrective action plan for CSL-09 (SLA Section 17). | Supplier site manager | 2026-09-28 | 2026-10-12 |
| CAP-017 | S2 | - | CSL-11 Record Integrity: Minimum default (severe) | Supplier RCA and corrective action plan for CSL-11 (SLA Section 17). | Supplier site manager | 2026-09-28 | 2026-10-12 |

## Severity log

**S1:** 14 · **S2:** 8 · **S3:** 4 · **S4:** 2

| Severity | Kind | Reference | Tickets | What happened |
|:-:|---|---|---|---|
| S1 | Discrepancy | F-001 | INC3100068, INC3100085 | Ticket split to restart the clock |
| S1 | Restore breach | INC3100068 | INC3100068, INC3100085 | P2 restore 10.4 hrs vs 8-hr target |
| S1 | Discrepancy | F-002 | INC3100136, INC3100170 | Ticket split to restart the clock |
| S1 | Restore breach | INC3100136 | INC3100136, INC3100170 | P2 restore 11.1 hrs vs 8-hr target |
| S1 | Discrepancy | F-003 | INC3100221, INC3100238 | Ticket split to restart the clock |
| S1 | Restore breach | INC3100221 | INC3100221, INC3100238 | P2 restore 9.9 hrs vs 8-hr target |
| S1 | Discrepancy | F-004 | INC3100289 | On-site claim before badge-in |
| S1 | Discrepancy | F-005 | INC3100357 | Ticket opened late (clock shift) |
| S1 | Restore breach | INC3100357 | INC3100357 | P2 restore 9.0 hrs vs 8-hr target |
| S1 | Discrepancy | F-006 | INC3100510 | Returned to service without validation |
| S1 | Discrepancy | F-007 | INC3100629 | Part swap not confirmed by inventory |
| S1 | Discrepancy | F-008 | INC3100748 | Returned to service without validation |
| S1 | Discrepancy | F-009 | INC3100935 | Part swap not confirmed by inventory |
| S1 | Discrepancy | F-010 | INC3101241 | On-site claim before badge-in |
| S2 | Discrepancy | F-011 | INC3100136, INC3100170 | Link errors continued after optic replacement |
| S2 | Discrepancy | F-012 | INC3100204, INC3100391 | Same fault recurred after a reseat |
| S2 | Discrepancy | F-013 | INC3100102, INC3100374, INC3100595 | Repeat-failing unit not escalated |
| S2 | Discrepancy | F-014 | INC3100663, INC3100833 | Same fault recurred after a reseat |
| S2 | Discrepancy | F-015 | - | Change without an approved change record |
| S2 | Service level | CSL-08 | - | 30-Day Repeat Failure Rate: Minimum default (severe) |
| S2 | Service level | CSL-09 | - | Deployment Milestone Adherence: Minimum default (severe) |
| S2 | Service level | CSL-11 | - | Record Integrity: Minimum default (severe) |
| S3 | Discrepancy | F-016 | - | Rostered technicians not on site |
| S3 | Discrepancy | F-017 | INC3100612 | Part used but not issued from spares |
| S3 | Discrepancy | F-018 | - | Rostered technicians not on site |
| S3 | Service level | CSL-07 | - | Validated Return to Service: Minimum default |
| S4 | Service level | CSL-04 | - | P2 Restoration Within 8 Hours: Below Expected |
| S4 | Service level | CSL-06 | - | First-Time Fix Rate: Below Expected |

Discrepancy details and evidence: [discrepancy_report.md](discrepancy_report.md).

## Key Measurements

| ID | Key measurement | Target | Measured | Result | Basis |
|---|---|:-:|:-:|:-:|---|
| KM-01 | P2 Engaged On-Site Within 30 Minutes | ≥ 95% | 88.46% | **Missed** | 46 of 52 P2 incidents with a badge-verified technician within 30 min |
| KM-02 | P1 Containment Within 60 Minutes (leak and safety incidents) | 100% | 100.00% | Met | 1 of 1 leaks contained within 60 minutes |
| KM-03 | P3 Engaged On-Site Within 4 Hours | ≥ 95% | 94.12% | **Missed** | 16 of 17 P3 incidents with a badge-verified technician within 240 min |
| KM-04 | P4 Completed Within 5 Days | ≥ 90% | n/a | n/a | Not measured in the demo data |
| KM-05 | Incident Update Cadence Adherence | ≥ 95% | n/a | n/a | Not measured in the demo data |
| KM-06 | Spares at or Above Minimum Stock (by FRU class, daily) | ≥ 98% | 87.50% | **Missed** | 28 of 32 counted spares classes at or above minimum |
| KM-07 | Spares Cycle Count Accuracy | ≥ 99% | 96.88% | **Missed** | 31 of 32 cycle counts matched the ledger |
| KM-08 | RMA Shipped to OEM Within 5 Business Days | ≥ 95% | 100.00% | Met | 53 of 53 failed parts shipped to the OEM within 5 business days |
| KM-09 | Lemon Units Escalated Within 2 Business Days | 100% | 0.00% | **Missed** | 1 lemon unit(s) not escalated |
| KM-10 | Change Compliance (all changes CAB-approved and in window) | 100% | 66.67% | **Missed** | 36 of 54 firmware changes covered by an approved change record |
| KM-11 | P1 Final RCA Delivered Within 5 Business Days | 100% | n/a | n/a | Not measured in the demo data |
| KM-12 | Corrective Actions Closed On Time | ≥ 90% | n/a | n/a | Not measured in the demo data |
| KM-13 | Backlog Aging (P3 and P4 tickets open more than 14 days) | ≤ 5% | n/a | n/a | Not measured in the demo data |
| KM-14 | Ticket Data Completeness (required fields populated at closure) | ≥ 98% | n/a | n/a | Not measured in the demo data |
| KM-15 | Training and Certification Currency | 100% | n/a | n/a | Not measured in the demo data |
| KM-16 | Chronic Units (more than 12 Supplier-attributable down-hours in a rolling 30 days) | ≤ 0 units | 0 units | Met | None |
| KM-17 | Redundancy Exposure (hours per month running without power or cooling redundancy) | ≤ 24 hrs | 0.8 hrs | Met | 0.8 hours running without power or cooling redundancy |
| KM-18 | Ticket Reopen Rate (TR-1 early failures and TR-2 reopens) | ≤ 3% | 4.17% | **Missed** | 3 Tickets of Record reopened under TR-1 or TR-2 |
| KM-19 | Manual Data Overrides (manually entered serials and audited timestamp edits) | ≤ 1% | n/a | n/a | Not measured in the demo data |

## Method

- Every number above is computed from the Telemetry of Record by the reference implementation in `src/scorecard/`.
- Restoration is measured per Ticket of Record from telemetry T0 to Validated RTS, with the ticket handling rules (TR-1 early failure, TR-2 reopen) applied, so split tickets count as one incident.
- Engagement is badge-verified: the assigned technician's first badge-in to the hall after T0.
- Availability uses capacity-weighted GPU-hours (degraded links count at 25%); deployment racks count from Validated Handoff.
- Simplifications for the demo: the 4-week window is treated as the Measurement Period; no approved clock pauses exist in the data, so all lost capacity is Supplier-attributable; repeat-default history before the window is unknown, so no credit doubling applies; Key Measurements with no source data are marked n/a.
