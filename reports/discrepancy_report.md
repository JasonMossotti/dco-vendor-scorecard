<!-- GENERATED FILE. DO NOT EDIT BY HAND. Run: python scripts/run_engine.py -->

# Discrepancy Report

> Synthetic data for a portfolio demonstration. All sites, people, serials, and events are fictional.

**Window:** 2026-08-31 00:00 UTC to 2026-09-28 00:00 UTC  
**Vendor tickets reviewed:** 78  
**Findings:** 18 (10 S1 Critical, 5 S2 Major, 3 S3 Minor)

Each finding is a place where the vendor's records do not reconcile with the Telemetry of Record. A finding starts a review; it is not by itself proof of intent. Severity follows the SLA's internal breach severity index, where any record-integrity finding is S1.

## Summary by type

| Type | Findings | Highest severity | SLA references |
|---|:-:|:-:|---|
| Ticket opened late (clock shift) | 1 | S1 | CSL-03, CSL-04, CSL-05, CSL-11 |
| Ticket split to restart the clock | 3 | S1 | TR-1, TR-2, TR-6, CSL-11 |
| On-site claim before badge-in | 2 | S1 | CSL-02, KM-01, CSL-11 |
| Returned to service without validation | 2 | S1 | CSL-07, CSL-11 |
| Part swap not confirmed by inventory | 2 | S1 | CSL-11 |
| Same fault recurred after a reseat | 2 | S2 | CSL-06, CSL-08 |
| Link errors continued after optic replacement | 1 | S2 | CSL-06, CSL-08, TR-2 |
| Repeat-failing unit not escalated | 1 | S2 | KM-09, CSL-08 |
| Rostered technicians not on site | 2 | S3 | CSL-10 |
| Part used but not issued from spares | 1 | S3 | KM-06, KM-07 |
| Change without an approved change record | 1 | S2 | KM-10 |

## Engine self-check against the answer key

The synthetic generator planted **17** discrepancies and recorded them in an answer key the engine cannot read. The engine found **17 of 17** with **0 false positives** and 1 corroborating finding (correct findings of a second type on the same tickets).

| Planted type | Planted | Detected |
|---|:-:|:-:|
| `clock_shift` | 1 | 1 |
| `ghost_engagement` | 2 | 2 |
| `lemon_unit` | 1 | 1 |
| `phantom_fix` | 2 | 2 |
| `skipped_validation` | 2 | 2 |
| `spares_drift` | 1 | 1 |
| `staffing_gap` | 2 | 2 |
| `ticket_split` | 2 | 2 |
| `unauthorized_change` | 1 | 1 |
| `unverified_swap` | 2 | 2 |
| `wrong_end_optic` | 1 | 1 |

## Findings

### F-001 · S1 Critical · Returned to service without validation

**Tickets:** INC3100153  
**Unit:** a05-ct18  
**Observed:** 2026-09-04 02:17 UTC

a05-ct18 returned to service with 5 of 5 required 'Compute tray' checks missing (burn_in_1h, dcgm_diag_r3, leak_hold_30m, nccl_allreduce_rack, nvlink_domain); the ticket still claims validation passed.

| Source | Time | Evidence |
|---|---|---|
| `telemetry/health_checks.jsonl` | - | Passed checks on a05-ct18 for this repair: none |
| `vendor/tickets.json` | 2026-09-04 02:17 UTC | INC3100153: "Validation complete; all return-to-service checks passed. Returned to production." |

**Severity:** Base level for returned to service without validation: S2; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Drain the unit and run the full validation checklist now. Audit other returns by the same technician this period.  
**SLA:** CSL-07, CSL-11

### F-002 · S1 Critical · Ticket split to restart the clock

**Tickets:** INC3100187, INC3100204  
**Unit:** a06-ct13  
**Observed:** 2026-09-04 09:37 UTC

a06-ct13 failed again 41 minutes after return to service, and the follow-up was logged as a new ticket. Under TR-1 (early failure) it is one Ticket of Record: measured restoration 11.0 hrs against the 8-hour target (vendor tickets show 7.2 and 3.1 hrs).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/scheduler_node_states.jsonl` | 2026-09-04 09:37 UTC | Down interval 2026-09-04 09:37 UTC to 2026-09-04 16:51 UTC |
| `telemetry/scheduler_node_states.jsonl` | 2026-09-04 17:31 UTC | Down interval 2026-09-04 17:31 UTC to 2026-09-04 20:36 UTC |
| `vendor/tickets.json` | 2026-09-04 09:41 UTC | INC3100187 opened; vendor-reported restoration 7.2 hrs |
| `vendor/tickets.json` | 2026-09-04 17:35 UTC | INC3100204 opened; vendor-reported restoration 3.1 hrs |

**Severity:** Overrun 37% past target → S3; 12 GPU-hours lost beyond target (4 GPUs) → S4; Base level for ticket split to restart the clock: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold.  
**SLA:** TR-1, TR-2, TR-6, CSL-11

### F-003 · S1 Critical · Returned to service without validation

**Tickets:** INC3100221  
**Unit:** a03-ct14  
**Observed:** 2026-09-04 21:42 UTC

a03-ct14 returned to service with 5 of 5 required 'Compute tray' checks missing (burn_in_1h, dcgm_diag_r3, leak_hold_30m, nccl_allreduce_rack, nvlink_domain); the ticket still claims validation passed.

| Source | Time | Evidence |
|---|---|---|
| `telemetry/health_checks.jsonl` | - | Passed checks on a03-ct14 for this repair: none |
| `vendor/tickets.json` | 2026-09-04 21:42 UTC | INC3100221: "Validation complete; all return-to-service checks passed. Returned to production." |

**Severity:** Base level for returned to service without validation: S2; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Drain the unit and run the full validation checklist now. Audit other returns by the same technician this period.  
**SLA:** CSL-07, CSL-11

### F-004 · S1 Critical · Part swap not confirmed by inventory

**Tickets:** INC3100323  
**Unit:** a09-ct10  
**Observed:** 2026-09-06 12:52 UTC

INC3100323 records a compute tray replacement at a09-ct10, but BMC inventory never showed the installed serial CTY3CUQ51W; the original part appears to still be in place.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-06 12:52 UTC | INC3100323 parts: removed CTQSRSX7QQ, installed CTY3CUQ51W at a09-ct10 |
| `telemetry/redfish_inventory_changes.jsonl` | - | No SerialNumber change to CTY3CUQ51W observed on any BMC |
| `vendor/rma_shipments.csv` | 2026-09-10 14:03 UTC | RMA shipped for CTQSRSX7QQ, which inventory shows is still installed |

**Severity:** Base level for part swap not confirmed by inventory: S2; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Physically verify the serial in the slot. If the part was not replaced, reopen the ticket, replace it, and stop the RMA of the still-installed serial.  
**SLA:** CSL-11

### F-005 · S1 Critical · Ticket split to restart the clock

**Tickets:** INC3100391, INC3100442  
**Unit:** leaf-a16-r0:swp33  
**Observed:** 2026-09-08 03:04 UTC

leaf-a16-r0:swp33 failed again 65 minutes after return to service, and the follow-up was logged as a new ticket. Under TR-2 (reopen within stability window) it is one Ticket of Record: measured restoration 12.6 hrs against the 8-hour target (vendor tickets show 1.6 and 3.4 hrs).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/ufm_port_events.jsonl` | 2026-09-08 03:04 UTC | Down interval 2026-09-08 03:04 UTC to 2026-09-08 04:37 UTC |
| `telemetry/ufm_port_events.jsonl` | 2026-09-08 05:42 UTC | Down interval 2026-09-08 05:42 UTC to 2026-09-08 16:42 UTC |
| `vendor/tickets.json` | 2026-09-08 03:07 UTC | INC3100391 opened; vendor-reported restoration 1.6 hrs |
| `vendor/tickets.json` | 2026-09-08 13:23 UTC | INC3100442 opened; vendor-reported restoration 3.4 hrs |

**Severity:** Overrun 57% past target → S2; 18 GPU-hours lost beyond target (4 GPUs) → S4; Base level for ticket split to restart the clock: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold.  
**SLA:** TR-1, TR-2, TR-6, CSL-11

### F-006 · S1 Critical · Ticket split to restart the clock

**Tickets:** INC3100425, INC3100476  
**Unit:** a26-ct16  
**Observed:** 2026-09-08 13:01 UTC

a26-ct16 failed again 36 minutes after return to service, and the follow-up was logged as a new ticket. Under TR-1 (early failure) it is one Ticket of Record: measured restoration 10.9 hrs against the 8-hour target (vendor tickets show 7.1 and 3.2 hrs).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/scheduler_node_states.jsonl` | 2026-09-08 13:01 UTC | Down interval 2026-09-08 13:01 UTC to 2026-09-08 20:07 UTC |
| `telemetry/scheduler_node_states.jsonl` | 2026-09-08 20:42 UTC | Down interval 2026-09-08 20:42 UTC to 2026-09-08 23:57 UTC |
| `vendor/tickets.json` | 2026-09-08 13:04 UTC | INC3100425 opened; vendor-reported restoration 7.1 hrs |
| `vendor/tickets.json` | 2026-09-08 20:46 UTC | INC3100476 opened; vendor-reported restoration 3.2 hrs |

**Severity:** Overrun 37% past target → S3; 12 GPU-hours lost beyond target (4 GPUs) → S4; Base level for ticket split to restart the clock: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold.  
**SLA:** TR-1, TR-2, TR-6, CSL-11

### F-007 · S1 Critical · On-site claim before badge-in

**Tickets:** INC3100663  
**Unit:** a23-ct04  
**Observed:** 2026-09-13 08:36 UTC

Work note claims on site at 2026-09-13 08:36 UTC, 28 minutes before Drew Chen badged into HALL-A. Claimed engagement 26 min after T0; badge-verified 54 min against the 30-minute target.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-13 08:36 UTC | INC3100663 work note by Drew Chen: "On site at rack A23 (HALL-A)." |
| `access/badge_events.csv` | 2026-09-13 09:04 UTC | First HALL-A badge-in by Drew Chen (RSS-026) |

**Severity:** Base level for on-site claim before badge-in: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Correct the engaged time from badge data. Review the record with the vendor site manager and agree on corrective steps for the technician.  
**SLA:** CSL-02, KM-01, CSL-11

### F-008 · S1 Critical · Ticket opened late (clock shift)

**Tickets:** INC3100799  
**Unit:** a01-ct05  
**Observed:** 2026-09-15 12:48 UTC

Ticket opened 100 minutes after the telemetry fault. Vendor-reported restoration 7.7 hrs; measured from T0 9.4 hrs against the 8-hour P2 target (a breach hidden by the late start).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-15 12:48 UTC | Fault signal: XID 79 (GPU has fallen off the bus) on a01-ct05 |
| `vendor/tickets.json` | 2026-09-15 14:28 UTC | INC3100799 opened; reported outage start 2026-09-15 14:28 UTC |
| `vendor/tickets.json` | 2026-09-15 22:11 UTC | INC3100799 resolved |

**Severity:** Overrun 17% past target → S3; 6 GPU-hours lost beyond target (4 GPUs) → S4; Base level for ticket opened late (clock shift): S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Recalculate restoration from telemetry T0. Confirm the alerting integration opened the Ticket of Record at T0 and find out why the vendor ticket started later.  
**SLA:** CSL-03, CSL-04, CSL-05, CSL-11

### F-009 · S1 Critical · Part swap not confirmed by inventory

**Tickets:** INC3100952  
**Unit:** a30-ct06  
**Observed:** 2026-09-20 20:06 UTC

INC3100952 records a compute tray replacement at a30-ct06, but BMC inventory never showed the installed serial CTPQPV9KMG; the original part appears to still be in place.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-20 20:06 UTC | INC3100952 parts: removed CTKX3ZU5J9, installed CTPQPV9KMG at a30-ct06 |
| `telemetry/redfish_inventory_changes.jsonl` | - | No SerialNumber change to CTPQPV9KMG observed on any BMC |
| `vendor/rma_shipments.csv` | 2026-09-24 20:30 UTC | RMA shipped for CTKX3ZU5J9, which inventory shows is still installed |

**Severity:** Base level for part swap not confirmed by inventory: S2; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Physically verify the serial in the slot. If the part was not replaced, reopen the ticket, replace it, and stop the RMA of the still-installed serial.  
**SLA:** CSL-11

### F-010 · S1 Critical · On-site claim before badge-in

**Tickets:** INC3101309  
**Unit:** a20-ct07  
**Observed:** 2026-09-26 00:24 UTC

Work note claims on site at 2026-09-26 00:24 UTC, 22 minutes before Reese Moreau badged into HALL-A. Claimed engagement 28 min after T0; badge-verified 50 min against the 30-minute target.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-26 00:24 UTC | INC3101309 work note by Reese Moreau: "On site at rack A20 (HALL-A)." |
| `access/badge_events.csv` | 2026-09-26 00:46 UTC | First HALL-A badge-in by Reese Moreau (RSS-023) |

**Severity:** Base level for on-site claim before badge-in: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Correct the engaged time from badge data. Review the record with the vendor site manager and agree on corrective steps for the technician.  
**SLA:** CSL-02, KM-01, CSL-11

### F-011 · S2 Major · Link errors continued after optic replacement

**Tickets:** INC3100391, INC3100442  
**Unit:** leaf-a16-r0:swp33  
**Observed:** 2026-09-08 05:42 UTC

INC3100391 replaced the switch-side optic on leaf-a16-r0:swp33, but link errors resumed 61 minutes after closure. The fault was likely at the other end; under TR-2 the original ticket should have reopened.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-08 04:41 UTC | INC3100391 replaced the switch-side optic and closed the ticket |
| `telemetry/ufm_port_events.jsonl` | 2026-09-08 05:42 UTC | 11 error events on leaf-a16-r0:swp33 within 24 hrs after closure; first: symbol_errors (367) |
| `vendor/tickets.json` | 2026-09-08 13:23 UTC | Follow-up INC3100442 replaced the optic at a32-ct15 (host side) |

**Severity:** Base level for link errors continued after optic replacement: S3; AGG-REPEAT: +1 level (Same CSL or same Service Unit breached within the previous 30 days).  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Require inspection of both link ends before replacing an optic. Merge the follow-up ticket under TR-2.  
**SLA:** CSL-06, CSL-08, TR-2

### F-012 · S2 Major · Repeat-failing unit not escalated

**Tickets:** INC3100085, INC3100374, INC3100697  
**Unit:** a31-ct06  
**Observed:** 2026-09-13 14:15 UTC

a31-ct06 needed 3 repairs in 11 days (INC3100085, INC3100374, INC3100697) with no OEM RMA escalation. KM-09 requires escalation within 2 business days.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-01 15:17 UTC | INC3100085: Compute tray a31-ct06: XID 119, closed 'Cleaned/reseated' |
| `vendor/tickets.json` | 2026-09-07 15:06 UTC | INC3100374: Compute tray a31-ct06: XID 145, closed 'Cleaned/reseated' |
| `vendor/tickets.json` | 2026-09-13 14:19 UTC | INC3100697: Compute tray a31-ct06: XID 94, closed 'Cleaned/reseated' |

**Severity:** Base level for repeat-failing unit not escalated: S2.  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Remove the unit from service and open an OEM RMA. Find out why the lemon rule did not trigger an escalation.  
**SLA:** KM-09, CSL-08

### F-013 · S2 Major · Same fault recurred after a reseat

**Tickets:** INC3100544, INC3100748  
**Unit:** a31-ct17  
**Observed:** 2026-09-14 13:45 UTC

INC3100544 closed a31-ct17 as 'Cleaned/reseated' with no part replaced; the same gsp fault (XID 119) recurred 67 hours after return to service, inside the recurrence window (TR-5).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-11 16:01 UTC | Original fault: XID 119 (Timeout waiting for GSP RPC response) |
| `vendor/tickets.json` | 2026-09-11 19:18 UTC | INC3100544 closed as 'Cleaned/reseated', no part used |
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-14 13:45 UTC | Recurrence: XID 119 (Timeout waiting for GSP RPC response) |

**Severity:** Base level for same fault recurred after a reseat: S3; AGG-REPEAT: +1 level (Same CSL or same Service Unit breached within the previous 30 days).  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Replace rather than reseat on any recurrence. Add a one-reseat-maximum rule to the break-fix runbook and require an RCA.  
**SLA:** CSL-06, CSL-08

### F-014 · S2 Major · Change without an approved change record

**Tickets:** n/a  
**Unit:** Rack A23  
**Observed:** 2026-09-16 08:54 UTC

Firmware changed (1.3.6 -> 1.3.7) on 18 components in rack A23 between 2026-09-16 08:54 UTC and 2026-09-16 10:36 UTC with no approved change record.

| Source | Time | Evidence |
|---|---|---|
| `telemetry/redfish_inventory_changes.jsonl` | 2026-09-16 08:54 UTC | 18 FirmwareVersion changes in rack A23, first on a23-ct01 |
| `customer/cab_changes.json` | - | No approved change covers rack A23 at these times |

**Severity:** Base level for change without an approved change record: S2; AGG-RACKWIDE: present; already at or above S2.  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Verify firmware against the approved baseline and roll back if needed. Require a vendor RCA on the change-control breach.  
**SLA:** KM-10

### F-015 · S2 Major · Same fault recurred after a reseat

**Tickets:** INC3100612, INC3100901  
**Unit:** a14-ct07  
**Observed:** 2026-09-17 08:35 UTC

INC3100612 closed a14-ct07 as 'Cleaned/reseated' with no part replaced; the same bus fault (XID 79) recurred 98 hours after return to service, inside the recurrence window (TR-5).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-13 03:06 UTC | Original fault: XID 79 (GPU has fallen off the bus) |
| `vendor/tickets.json` | 2026-09-13 06:37 UTC | INC3100612 closed as 'Cleaned/reseated', no part used |
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-17 08:35 UTC | Recurrence: XID 79 (GPU has fallen off the bus) |

**Severity:** Base level for same fault recurred after a reseat: S3; AGG-REPEAT: +1 level (Same CSL or same Service Unit breached within the previous 30 days).  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Replace rather than reseat on any recurrence. Add a one-reseat-maximum rule to the break-fix runbook and require an RCA.  
**SLA:** CSL-06, CSL-08

### F-016 · S3 Minor · Rostered technicians not on site

**Tickets:** n/a  
**Unit:** Crew D1  
**Observed:** 2026-09-01 12:00 UTC

Day shift starting 2026-09-01 12:00 UTC (crew D1): 2 rostered people never badged in (Marlowe Mensah (RSS-003), Jesse Kim (RSS-005)). 6 of 8 committed technicians were on site.

| Source | Time | Evidence |
|---|---|---|
| `vendor/roster.csv` | 2026-09-01 12:00 UTC | Roster lists 9 people for this shift |
| `access/badge_events.csv` | - | No OPS-MAIN badge-in for Marlowe Mensah (RSS-003), Jesse Kim (RSS-005) between one hour before and the end of the shift |

**Severity:** Base level for rostered technicians not on site: S3.  
**Escalation:** Supplier RCA within 10 business days; discussed in the weekly operations review.  
**Recommended action:** Reconcile the roster against badge data with the vendor. Require a written coverage plan for the affected shift pattern.  
**SLA:** CSL-10

### F-017 · S3 Minor · Part used but not issued from spares

**Tickets:** INC3100272  
**Unit:** Compute tray  
**Observed:** 2026-09-05 03:48 UTC

INC3100272 used 1 x Compute tray but the spares ledger records 0 issue(s); the next cycle count was 1 short.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-05 03:48 UTC | INC3100272 used 1 x Compute tray |
| `vendor/spares_ledger.csv` | - | 0 issue(s) of Compute tray recorded against INC3100272 |
| `vendor/spares_cycle_counts.csv` | 2026-09-06 23:00 UTC | Cycle count Compute tray: ledger 4, counted 3 |

**Severity:** Base level for part used but not issued from spares: S3.  
**Escalation:** Supplier RCA within 10 business days; discussed in the weekly operations review.  
**Recommended action:** Correct the ledger and recount the affected spares class. Enforce scan-to-issue before any part leaves the cage.  
**SLA:** KM-06, KM-07

### F-018 · S3 Minor · Rostered technicians not on site

**Tickets:** n/a  
**Unit:** Crew D1  
**Observed:** 2026-09-18 12:00 UTC

Day shift starting 2026-09-18 12:00 UTC (crew D1): 2 rostered people never badged in (Lane Haddad (RSS-004), Alex Novak (RSS-009)). 6 of 8 committed technicians were on site.

| Source | Time | Evidence |
|---|---|---|
| `vendor/roster.csv` | 2026-09-18 12:00 UTC | Roster lists 9 people for this shift |
| `access/badge_events.csv` | - | No OPS-MAIN badge-in for Lane Haddad (RSS-004), Alex Novak (RSS-009) between one hour before and the end of the shift |

**Severity:** Base level for rostered technicians not on site: S3.  
**Escalation:** Supplier RCA within 10 business days; discussed in the weekly operations review.  
**Recommended action:** Reconcile the roster against badge data with the vendor. Require a written coverage plan for the affected shift pattern.  
**SLA:** CSL-10
