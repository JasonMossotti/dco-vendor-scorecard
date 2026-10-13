# Security Discrepancy Report

Each finding is a place where the Security Partner's post log, dispatch log, visitor log, or chain-of-custody log does not reconcile with the Customer's access control system, Redfish inventory, or the RMA shipments. A finding starts a review; it is not by itself proof of intent.

| ID | Severity | Type | Where | Summary |
|---|:-:|---|---|---|
| S-001 | S1 Critical | Post reported staffed with no guard badged in | Hall A entrance | The post log reports Hall A entrance staffed by LGP-011 for the day shift starting 2026-09-02 12:00 UTC, but no guard badged in at the post reader during the shift. |
| S-002 | S1 Critical | Storage media shipped without a destruction certificate | Tray CTSXQ9HJ60 | Compute tray CTSXQ9HJ60 (INC3100476) shipped at 2026-09-10 13:17 UTC. Its Redfish inventory lists drive E1S46F6ZGWWD in bay 5, but there is no destruction certificate and no chain-of-custody handover. |
| S-003 | S1 Critical | Door alarm closed with no guard at the door | DOCK-INNER | Door held open at DOCK-INNER (P2) at 2026-09-16 14:56 UTC. The dispatch log closed SIR-00016 at 2026-09-16 15:05 UTC as 'Door checked and secured', but no guard badged the door's reader between the alarm and the close. |
| S-004 | S1 Critical | Visitor entered a hall without the escort | HALL-A | Visitor V-3038 (Network carrier, VIS-0038) badged into HALL-A at 2026-09-23 12:20 UTC with RSS-006 (IT Partner) named as escort, but the escort did not badge in within 2 minutes; the escort's nearest badge-in to HALL-A was 2026-09-23 12:50 UTC. |

## S-001: Post reported staffed with no guard badged in (S1 Critical)

The post log reports Hall A entrance staffed by LGP-011 for the day shift starting 2026-09-02 12:00 UTC, but no guard badged in at the post reader during the shift.

| Source | When | Detail |
|---|---|---|
| `security/post_log.csv` | 2026-09-02 12:00 UTC | POST-HA day shift: Staffed (LGP-011) |
| `security/guard_badges.csv` |  | No badge-in at 'Post: Hall A entrance' from 2026-09-02 11:30 UTC to 2026-09-02 23:30 UTC |

**Recommended action:** Recount the post as unstaffed. Audit the post log against post reader badges for the period and confirm relief procedures.

**SLA references:** SEC-CSL-01, SEC-CSL-07

## S-002: Storage media shipped without a destruction certificate (S1 Critical)

Compute tray CTSXQ9HJ60 (INC3100476) shipped at 2026-09-10 13:17 UTC. Its Redfish inventory lists drive E1S46F6ZGWWD in bay 5, but there is no destruction certificate and no chain-of-custody handover.

| Source | When | Detail |
|---|---|---|
| `security/tray_drives.csv` |  | CTSXQ9HJ60 bay 5: E1S46F6ZGWWD (E1.S 7.68 TB NVMe) |
| `vendor/rma_shipments.csv` | 2026-09-10 13:17 UTC | INC3100476 compute tray CTSXQ9HJ60 shipped |
| `security/chain_of_custody.csv` |  | No handover recorded for E1S46F6ZGWWD |
| `security/destruction_certificates.csv` |  | No certificate for E1S46F6ZGWWD |

**Recommended action:** Contact the carrier and the OEM to recover the drive. Stop all RMA shipments until every waiting part is reconciled against the destruction log.

**SLA references:** SEC-CSL-06, SEC-CSL-07

## S-003: Door alarm closed with no guard at the door (S1 Critical)

Door held open at DOCK-INNER (P2) at 2026-09-16 14:56 UTC. The dispatch log closed SIR-00016 at 2026-09-16 15:05 UTC as 'Door checked and secured', but no guard badged the door's reader between the alarm and the close.

| Source | When | Detail |
|---|---|---|
| `security/door_alarms.jsonl` | 2026-09-16 14:56 UTC | ACS-00016 Door held open at DOCK-INNER; console acknowledged 2026-09-16 14:56 UTC |
| `security/dispatch_log.json` | 2026-09-16 15:05 UTC | SIR-00016 closed: Door checked and secured (dispatched LGP-004) |
| `security/guard_badges.csv` |  | No guard badge at DOCK-INNER from 2026-09-16 14:56 UTC to 2026-09-16 15:05 UTC |

**Recommended action:** Recount the alarm as not responded. Review the door with the Customer and retrain on badging the door reader on arrival.

**SLA references:** SEC-CSL-02, SEC-CSL-07

## S-004: Visitor entered a hall without the escort (S1 Critical)

Visitor V-3038 (Network carrier, VIS-0038) badged into HALL-A at 2026-09-23 12:20 UTC with RSS-006 (IT Partner) named as escort, but the escort did not badge in within 2 minutes; the escort's nearest badge-in to HALL-A was 2026-09-23 12:50 UTC.

| Source | When | Detail |
|---|---|---|
| `security/visits.csv` | 2026-09-23 12:12 UTC | VIS-0038 signed in under VR-2038; escort RSS-006 |
| `security/visitor_badges.csv` | 2026-09-23 12:20 UTC | V-3038 in at HALL-A |
| `access/badge_events.csv` | 2026-09-23 12:50 UTC | RSS-006 nearest hall badge-in |

**Recommended action:** Review the video for the visit under a Customer-approved request. Suspend the escort's escort privilege pending review.

**SLA references:** SEC-CSL-03, SEC-CSL-07

## Engine self-check

Detected 4 of 4 planted discrepancies; 0 false positives.

| Type | Planted | Detected |
|---|:-:|:-:|
| door_alarm_closed_no_response | 1 | 1 |
| media_shipped_without_destruction | 1 | 1 |
| post_reported_unstaffed | 1 | 1 |
| visitor_without_escort | 1 | 1 |
