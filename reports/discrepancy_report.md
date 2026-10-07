<!-- GENERATED FILE. DO NOT EDIT BY HAND. Run: python scripts/run_engine.py -->

# Discrepancy Report

> Synthetic data for a portfolio demonstration. All sites, people, serials, and events are fictional.

**Window:** 2026-08-31 00:00 UTC to 2026-09-28 00:00 UTC  
**Vendor tickets reviewed:** 75  
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

### F-001 · S1 Critical · Ticket split to restart the clock

**Tickets:** INC3100068, INC3100085  
**Unit:** a31-ct11  
**Observed:** 2026-09-01 05:48 UTC

a31-ct11 failed again 29 minutes after return to service, and the follow-up was logged as a new ticket. Under TR-1 (early failure) it is one Ticket of Record: measured restoration 10.4 hrs against the 8-hour target (vendor tickets show 6.6 and 3.2 hrs).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/scheduler_node_states.jsonl` | 2026-09-01 05:48 UTC | Down interval 2026-09-01 05:48 UTC to 2026-09-01 12:25 UTC |
| `telemetry/scheduler_node_states.jsonl` | 2026-09-01 12:54 UTC | Down interval 2026-09-01 12:54 UTC to 2026-09-01 16:11 UTC |
| `vendor/tickets.json` | 2026-09-01 05:51 UTC | INC3100068 opened; vendor-reported restoration 6.6 hrs |
| `vendor/tickets.json` | 2026-09-01 12:59 UTC | INC3100085 opened; vendor-reported restoration 3.2 hrs |

**Severity:** Overrun 30% past target → S3; 10 GPU-hours lost beyond target (4 GPUs) → S4; Base level for ticket split to restart the clock: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold.  
**SLA:** TR-1, TR-2, TR-6, CSL-11

### F-002 · S1 Critical · Ticket split to restart the clock

**Tickets:** INC3100136, INC3100170  
**Unit:** leaf-a07-r1:swp18  
**Observed:** 2026-09-03 12:04 UTC

leaf-a07-r1:swp18 failed again 78 minutes after return to service, and the follow-up was logged as a new ticket. Under TR-2 (reopen within stability window) it is one Ticket of Record: measured restoration 11.1 hrs against the 8-hour target (vendor tickets show 1.2 and 3.4 hrs).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/ufm_port_events.jsonl` | 2026-09-03 12:04 UTC | Down interval 2026-09-03 12:04 UTC to 2026-09-03 13:15 UTC |
| `telemetry/ufm_port_events.jsonl` | 2026-09-03 14:33 UTC | Down interval 2026-09-03 14:33 UTC to 2026-09-04 00:26 UTC |
| `vendor/tickets.json` | 2026-09-03 12:06 UTC | INC3100136 opened; vendor-reported restoration 1.2 hrs |
| `vendor/tickets.json` | 2026-09-03 21:02 UTC | INC3100170 opened; vendor-reported restoration 3.4 hrs |

**Severity:** Overrun 38% past target → S3; 12 GPU-hours lost beyond target (4 GPUs) → S4; Base level for ticket split to restart the clock: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold.  
**SLA:** TR-1, TR-2, TR-6, CSL-11

### F-003 · S1 Critical · Ticket split to restart the clock

**Tickets:** INC3100221, INC3100238  
**Unit:** a06-ct13  
**Observed:** 2026-09-04 09:37 UTC

a06-ct13 failed again 12 minutes after return to service, and the follow-up was logged as a new ticket. Under TR-1 (early failure) it is one Ticket of Record: measured restoration 9.9 hrs against the 8-hour target (vendor tickets show 6.5 and 3.2 hrs).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/scheduler_node_states.jsonl` | 2026-09-04 09:37 UTC | Down interval 2026-09-04 09:37 UTC to 2026-09-04 16:09 UTC |
| `telemetry/scheduler_node_states.jsonl` | 2026-09-04 16:22 UTC | Down interval 2026-09-04 16:22 UTC to 2026-09-04 19:33 UTC |
| `vendor/tickets.json` | 2026-09-04 09:42 UTC | INC3100221 opened; vendor-reported restoration 6.5 hrs |
| `vendor/tickets.json` | 2026-09-04 16:23 UTC | INC3100238 opened; vendor-reported restoration 3.2 hrs |

**Severity:** Overrun 24% past target → S3; 8 GPU-hours lost beyond target (4 GPUs) → S4; Base level for ticket split to restart the clock: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Merge the tickets under TR-6 and recalculate restoration from the original T0. Require an RCA on why the first repair did not hold.  
**SLA:** TR-1, TR-2, TR-6, CSL-11

### F-004 · S1 Critical · On-site claim before badge-in

**Tickets:** INC3100289  
**Unit:** a28-ct04  
**Observed:** 2026-09-04 22:21 UTC

Work note claims on site at 2026-09-04 22:21 UTC, 28 minutes before Taylor Haddad badged into HALL-A. Claimed engagement 28 min after T0; badge-verified 56 min against the 30-minute target.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-04 22:21 UTC | INC3100289 work note by Taylor Haddad: "On site at rack A28 (HALL-A)." |
| `access/badge_events.csv` | 2026-09-04 22:49 UTC | First HALL-A badge-in by Taylor Haddad (RSS-014) |

**Severity:** Base level for on-site claim before badge-in: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Correct the engaged time from badge data. Review the record with the vendor site manager and agree on corrective steps for the technician.  
**SLA:** CSL-02, KM-01, CSL-11

### F-005 · S1 Critical · Ticket opened late (clock shift)

**Tickets:** INC3100357  
**Unit:** a09-ct10  
**Observed:** 2026-09-06 08:52 UTC

Ticket opened 109 minutes after the telemetry fault. Vendor-reported restoration 7.2 hrs; measured from T0 9.0 hrs against the 8-hour P2 target (a breach hidden by the late start).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-06 08:52 UTC | Fault signal: XID 145 (NVLINK: RLW Error) on a09-ct10 |
| `vendor/tickets.json` | 2026-09-06 10:41 UTC | INC3100357 opened; reported outage start 2026-09-06 10:41 UTC |
| `vendor/tickets.json` | 2026-09-06 17:54 UTC | INC3100357 resolved |

**Severity:** Overrun 13% past target → S3; 4 GPU-hours lost beyond target (4 GPUs) → S4; Base level for ticket opened late (clock shift): S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Recalculate restoration from telemetry T0. Confirm the alerting integration opened the Ticket of Record at T0 and find out why the vendor ticket started later.  
**SLA:** CSL-03, CSL-04, CSL-05, CSL-11

### F-006 · S1 Critical · Returned to service without validation

**Tickets:** INC3100510  
**Unit:** a14-ct02  
**Observed:** 2026-09-09 23:00 UTC

a14-ct02 returned to service with 5 of 5 required 'Compute tray' checks missing (burn_in_1h, dcgm_diag_r3, leak_hold_30m, nccl_allreduce_rack, nvlink_domain); the ticket still claims validation passed.

| Source | Time | Evidence |
|---|---|---|
| `telemetry/health_checks.jsonl` | - | Passed checks on a14-ct02 for this repair: none |
| `vendor/tickets.json` | 2026-09-09 23:00 UTC | INC3100510: "Validation complete; all return-to-service checks passed. Returned to production." |

**Severity:** Base level for returned to service without validation: S2; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Drain the unit and run the full validation checklist now. Audit other returns by the same technician this period.  
**SLA:** CSL-07, CSL-11

### F-007 · S1 Critical · Part swap not confirmed by inventory

**Tickets:** INC3100629  
**Unit:** a05-ct15  
**Observed:** 2026-09-13 08:19 UTC

INC3100629 records a compute tray replacement at a05-ct15, but BMC inventory never showed the installed serial CT3PQ9DACL; the original part appears to still be in place.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-13 08:19 UTC | INC3100629 parts: removed CTYCX5H7TS, installed CT3PQ9DACL at a05-ct15 |
| `telemetry/redfish_inventory_changes.jsonl` | - | No SerialNumber change to CT3PQ9DACL observed on any BMC |
| `vendor/rma_shipments.csv` | 2026-09-16 07:00 UTC | RMA shipped for CTYCX5H7TS, which inventory shows is still installed |

**Severity:** Base level for part swap not confirmed by inventory: S2; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Physically verify the serial in the slot. If the part was not replaced, reopen the ticket, replace it, and stop the RMA of the still-installed serial.  
**SLA:** CSL-11

### F-008 · S1 Critical · Returned to service without validation

**Tickets:** INC3100748  
**Unit:** a07-ct04  
**Observed:** 2026-09-15 11:26 UTC

a07-ct04 returned to service with 5 of 5 required 'Compute tray' checks missing (burn_in_1h, dcgm_diag_r3, leak_hold_30m, nccl_allreduce_rack, nvlink_domain); the ticket still claims validation passed.

| Source | Time | Evidence |
|---|---|---|
| `telemetry/health_checks.jsonl` | - | Passed checks on a07-ct04 for this repair: none |
| `vendor/tickets.json` | 2026-09-15 11:26 UTC | INC3100748: "Validation complete; all return-to-service checks passed. Returned to production." |

**Severity:** Base level for returned to service without validation: S2; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Drain the unit and run the full validation checklist now. Audit other returns by the same technician this period.  
**SLA:** CSL-07, CSL-11

### F-009 · S1 Critical · Part swap not confirmed by inventory

**Tickets:** INC3100935  
**Unit:** a10-ct13  
**Observed:** 2026-09-21 09:27 UTC

INC3100935 records a compute tray replacement at a10-ct13, but BMC inventory never showed the installed serial CT7K064GC5; the original part appears to still be in place.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-21 09:27 UTC | INC3100935 parts: removed CTX4GH2MXS, installed CT7K064GC5 at a10-ct13 |
| `telemetry/redfish_inventory_changes.jsonl` | - | No SerialNumber change to CT7K064GC5 observed on any BMC |
| `vendor/rma_shipments.csv` | 2026-09-26 16:19 UTC | RMA shipped for CTX4GH2MXS, which inventory shows is still installed |

**Severity:** Base level for part swap not confirmed by inventory: S2; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Physically verify the serial in the slot. If the part was not replaced, reopen the ticket, replace it, and stop the RMA of the still-installed serial.  
**SLA:** CSL-11

### F-010 · S1 Critical · On-site claim before badge-in

**Tickets:** INC3101241  
**Unit:** a20-ct07  
**Observed:** 2026-09-26 00:23 UTC

Work note claims on site at 2026-09-26 00:23 UTC, 32 minutes before Reese Moreau badged into HALL-A. Claimed engagement 27 min after T0; badge-verified 59 min against the 30-minute target.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-26 00:23 UTC | INC3101241 work note by Reese Moreau: "On site at rack A20 (HALL-A)." |
| `access/badge_events.csv` | 2026-09-26 00:55 UTC | First HALL-A badge-in by Reese Moreau (RSS-023) |

**Severity:** Base level for on-site claim before badge-in: S3; AGG-INTEGRITY: raised to at least S1 (Breach involved a Record Integrity Finding (vendor record contradicted by telemetry)).  
**Escalation:** Same-day notification to Customer DCO leadership; Supplier executive engaged within 24 hours; CAP within 5 business days; chronic-failure and contract-remedy review.  
**Recommended action:** Correct the engaged time from badge data. Review the record with the vendor site manager and agree on corrective steps for the technician.  
**SLA:** CSL-02, KM-01, CSL-11

### F-011 · S2 Major · Link errors continued after optic replacement

**Tickets:** INC3100136, INC3100170  
**Unit:** leaf-a07-r1:swp18  
**Observed:** 2026-09-03 14:33 UTC

INC3100136 replaced the switch-side optic on leaf-a07-r1:swp18, but link errors resumed 76 minutes after closure. The fault was likely at the other end; under TR-2 the original ticket should have reopened.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-03 13:18 UTC | INC3100136 replaced the switch-side optic and closed the ticket |
| `telemetry/ufm_port_events.jsonl` | 2026-09-03 14:33 UTC | 10 error events on leaf-a07-r1:swp18 within 24 hrs after closure; first: symbol_errors (258) |
| `vendor/tickets.json` | 2026-09-03 21:02 UTC | Follow-up INC3100170 replaced the optic at a13-ct18 (host side) |

**Severity:** Base level for link errors continued after optic replacement: S3; AGG-REPEAT: +1 level (Same CSL or same Service Unit breached within the previous 30 days).  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Require inspection of both link ends before replacing an optic. Merge the follow-up ticket under TR-2.  
**SLA:** CSL-06, CSL-08, TR-2

### F-012 · S2 Major · Same fault recurred after a reseat

**Tickets:** INC3100204, INC3100391  
**Unit:** a22-ct07  
**Observed:** 2026-09-07 02:24 UTC

INC3100204 closed a22-ct07 as 'Cleaned/reseated' with no part replaced; the same ecc fault (XID 48) recurred 64 hours after return to service, inside the recurrence window (TR-5).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-04 07:21 UTC | Original fault: XID 94 (Contained memory error) |
| `vendor/tickets.json` | 2026-09-04 10:32 UTC | INC3100204 closed as 'Cleaned/reseated', no part used |
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-07 02:24 UTC | Recurrence: XID 48 (Double Bit ECC Error) |

**Severity:** Base level for same fault recurred after a reseat: S3; AGG-REPEAT: +1 level (Same CSL or same Service Unit breached within the previous 30 days).  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Replace rather than reseat on any recurrence. Add a one-reseat-maximum rule to the break-fix runbook and require an RCA.  
**SLA:** CSL-06, CSL-08

### F-013 · S2 Major · Repeat-failing unit not escalated

**Tickets:** INC3100102, INC3100374, INC3100595  
**Unit:** a23-ct18  
**Observed:** 2026-09-12 07:45 UTC

a23-ct18 needed 3 repairs in 10 days (INC3100102, INC3100374, INC3100595) with no OEM RMA escalation. KM-09 requires escalation within 2 business days.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-01 13:48 UTC | INC3100102: Compute tray a23-ct18: XID 145, closed 'Cleaned/reseated' |
| `vendor/tickets.json` | 2026-09-06 16:24 UTC | INC3100374: Compute tray a23-ct18: XID 79, closed 'Cleaned/reseated' |
| `vendor/tickets.json` | 2026-09-12 07:47 UTC | INC3100595: Compute tray a23-ct18: XID 119, closed 'Cleaned/reseated' |

**Severity:** Base level for repeat-failing unit not escalated: S2.  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Remove the unit from service and open an OEM RMA. Find out why the lemon rule did not trigger an escalation.  
**SLA:** KM-09, CSL-08

### F-014 · S2 Major · Same fault recurred after a reseat

**Tickets:** INC3100663, INC3100833  
**Unit:** a23-ct04  
**Observed:** 2026-09-16 01:29 UTC

INC3100663 closed a23-ct04 as 'Cleaned/reseated' with no part replaced; the same gsp fault (XID 119) recurred 62 hours after return to service, inside the recurrence window (TR-5).

| Source | Time | Evidence |
|---|---|---|
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-13 08:10 UTC | Original fault: XID 119 (GSP RPC Timeout) |
| `vendor/tickets.json` | 2026-09-13 11:27 UTC | INC3100663 closed as 'Cleaned/reseated', no part used |
| `telemetry/dcgm_xid_events.jsonl` | 2026-09-16 01:29 UTC | Recurrence: XID 119 (GSP RPC Timeout) |

**Severity:** Base level for same fault recurred after a reseat: S3; AGG-REPEAT: +1 level (Same CSL or same Service Unit breached within the previous 30 days).  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Replace rather than reseat on any recurrence. Add a one-reseat-maximum rule to the break-fix runbook and require an RCA.  
**SLA:** CSL-06, CSL-08

### F-015 · S2 Major · Change without an approved change record

**Tickets:** n/a  
**Unit:** Rack A29  
**Observed:** 2026-09-21 08:14 UTC

Firmware changed (1.3.6 -> 1.3.7) on 18 components in rack A29 between 2026-09-21 08:14 UTC and 2026-09-21 09:56 UTC with no approved change record.

| Source | Time | Evidence |
|---|---|---|
| `telemetry/redfish_inventory_changes.jsonl` | 2026-09-21 08:14 UTC | 18 FirmwareVersion changes in rack A29, first on a29-ct01 |
| `customer/cab_changes.json` | - | No approved change covers rack A29 at these times |

**Severity:** Base level for change without an approved change record: S2; AGG-RACKWIDE: present; already at or above S2.  
**Escalation:** Formal CAP within 10 business days; reviewed jointly by Customer site lead and Supplier account manager; tracked to verified closure.  
**Recommended action:** Verify firmware against the approved baseline and roll back if needed. Require a vendor RCA on the change-control breach.  
**SLA:** KM-10

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

**Tickets:** INC3100612  
**Unit:** Compute tray  
**Observed:** 2026-09-13 06:45 UTC

INC3100612 used 1 x Compute tray but the spares ledger records 0 issue(s); the next cycle count was 1 short.

| Source | Time | Evidence |
|---|---|---|
| `vendor/tickets.json` | 2026-09-13 06:45 UTC | INC3100612 used 1 x Compute tray |
| `vendor/spares_ledger.csv` | - | 0 issue(s) of Compute tray recorded against INC3100612 |
| `vendor/spares_cycle_counts.csv` | 2026-09-13 23:00 UTC | Cycle count Compute tray: ledger 4, counted 3 |

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
