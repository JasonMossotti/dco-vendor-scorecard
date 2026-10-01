# Synthetic Data Model

> All data is synthetic and fictional: sites, people, serial numbers, and events are generated. Record formats are simplified versions of what the named classes of systems produce. They are not copies of any vendor's real schema.

## Two views of one reality

The generator simulates a fictional GB200 NVL72 site (Hall A in production with 32 racks and 2,304 GPUs; Hall B under deployment) and records each event twice:

1. **Telemetry of Record.** What the hardware and Customer systems observed. Under the SLA, this is authoritative for timing, inventory, and health.
2. **Vendor records.** What the Supplier reports. Normally consistent with telemetry, except the vendor's clock starts when a ticket is opened rather than when the fault occurred.

Then it plants realistic discrepancies between the two views. The answer key in `ground_truth/` lets us measure how many the discrepancy engine catches. **The engine never reads `ground_truth/`.**

## Files

| File | Mimics | Key fields | Used to verify |
|---|---|---|---|
| `site/topology.json` | Asset inventory baseline | racks, trays, serials, firmware, CDU mapping | Starting serial and firmware state |
| `telemetry/dcgm_xid_events.jsonl` | GPU driver XID events via DCGM | timestamp, host, xid, tray_serial | Fault start (T0), recurrences |
| `telemetry/redfish_events.jsonl` | BMC alerts (Redfish-style) | resource, event_type (LeakDetected, PowerSupplyFailed) | Leak and power fault timing |
| `telemetry/redfish_inventory_changes.jsonl` | BMC inventory polling | resource, property (SerialNumber, FirmwareVersion), old/new | Part swaps actually happened; unapproved firmware changes |
| `telemetry/nmx_events.jsonl` | NVLink fabric management | rack, unit, state | Switch tray failure and recovery |
| `telemetry/ufm_port_events.jsonl` | InfiniBand fabric manager | switch, port, event (link_down, symbol_errors) | Link faults, and whether errors stopped after repair |
| `telemetry/bms_cdu_events.jsonl` | Building management system | cdu, alarm, state | Cooling faults and alarm clear times |
| `telemetry/health_checks.jsonl` | Cluster health-check platform | target, check, result, times | Return-to-service validation actually ran |
| `telemetry/scheduler_node_states.jsonl` | Workload scheduler | node, state (drain/idle) | When capacity was lost and returned |
| `access/badge_events.csv` | Access control system | person_id, door, direction | Staffing presence; technician on site |
| `customer/cab_changes.json` | Customer change management | rack, window_start, window_end | Whether changes were approved |
| `customer/deployment_plan.csv` | Customer deployment plan | rack, committed_handoff | Milestone commitments |
| `vendor/tickets.json` | Vendor ticketing system (ServiceNow-style) | opened_at, work_notes, parts_used, resolved_at | The vendor's account of each incident |
| `vendor/personnel.csv` | Vendor staff list | person_id, role, crew, badge_id | Joins badges to people |
| `vendor/roster.csv` | Vendor shift roster | shift_start, person_id, status | Committed staffing |
| `vendor/spares_ledger.csv` | Vendor spares system | transaction, fru, qty, balance_after | Parts issued against tickets |
| `vendor/spares_cycle_counts.csv` | Weekly physical counts | system_qty, counted_qty | Ledger accuracy |
| `vendor/rma_shipments.csv` | RMA logistics | serial, removed_at, shipped_at | RMA turnaround (KM-08) |
| `vendor/deployment_milestones.csv` | Vendor deployment tracker | rack, milestone, reported_complete_at | Deployment adherence (CSL-09) |
| `vendor/self_reported_weekly.json` | Vendor weekly summary | availability, restore %, staffing % | What the vendor claims |
| `ground_truth/incidents.json` | Answer key | true timeline per incident | Evaluation only |
| `ground_truth/planted_discrepancies.json` | Answer key | type, ticket, evidence, sla_refs | Evaluation only |

## Planted discrepancy types

| Type | What happened | How it is detectable | SLA reference |
|---|---|---|---|
| `phantom_fix` | Tray reseated and ticket closed; the same fault family recurs 1 to 4 days later | New XID of the same family on the same host after the 24-hour stability window but within 7 days (TR-5 linked recurrence) | CSL-06, CSL-08 |
| `ticket_split` | Tray refaults minutes after return to service; vendor opens a new ticket so the clock restarts | Refault within 60 minutes of Validated RTS (TR-1). Each vendor ticket is on time; measured continuously from the first T0 it breaches | TR-1, TR-6, CSL-04, CSL-11 |
| `unverified_swap` | Ticket claims a tray replacement with a new serial | That serial never appears in BMC inventory; the old serial keeps reporting | CSL-11 |
| `skipped_validation` | Node returned to service minutes after repair | No validation health checks between repair and return; ticket still claims validation | CSL-07, CSL-11 |
| `clock_shift` | Ticket opened about 2 hours after the fault | XID precedes ticket open; on time by vendor clock, late by telemetry | CSL-04, CSL-11 |
| `ghost_engagement` | Work note says "on site" within target | Assigned technician's hall badge-in came later | CSL-02 / KM-01, CSL-11 |
| `wrong_end_optic` | Switch-side optic replaced; ticket closed | Symbol errors continue on the same port until the host side is replaced. Under TR-2 the errors reopen the original ticket, so the vendor's second ticket is also a split | CSL-06, CSL-08, TR-2 |
| `lemon_unit` | One tray fails 3 times in 30 days, reseated each time | Three tickets on one unit, none escalated for RMA | KM-09, CSL-08 |
| `staffing_gap` | Two rostered technicians never showed up | Roster lists them; no badge-in during the shift | CSL-10 |
| `spares_drift` | Part used but never issued from the ledger | Ticket and inventory show a swap; ledger has no issue; cycle count short | KM-06, KM-07, CSL-11 |
| `unauthorized_change` | Firmware changed on a whole rack overnight | Inventory shows firmware changes; no approved change record covers them | KM-10 |

Each planted scenario maps to one Ticket Handling rule (SLA Section 7.6): refaults inside 60 minutes are `ticket_split` (TR-1), refaults after the stability window are `phantom_fix` (TR-5), and continued link errors are `wrong_end_optic` (TR-2).

## Honest behavior (not planted)

These are real performance outcomes the scorecard should report, not discrepancies:

- **Natural SLA misses:** some technicians arrive late, and some faults take longer to diagnose.
- **Systematic vendor clock offset:** vendor durations start at ticket open, a few minutes after the true fault time. This always flatters the vendor slightly; the clock-shift anomaly is the extreme version.
- **Deployment slips:** some Hall B racks miss their committed handoff date.

## Simplifications

- Incidents occur only in Hall A (production). Hall B produces deployment data only.
- Each compute tray is one scheduler node.
- Base incidents never hit the same unit twice, so every repeat failure in the data is a planted scenario. This keeps the answer key unambiguous.
- Incidents start at least 36 hours before the window ends, so every ticket is closed within the window.
- Fault rates are illustrative, tuned for roughly 20 tickets per week in one production hall.

## Regenerating

```bash
python scripts/generate_data.py                  # rebuild the committed sample (data/sample)
python scripts/generate_data.py --latest         # 4 weeks ending with the most recent complete week
python scripts/generate_data.py --seed 7 --out data/seed7
```

Tuning lives in `config/synthetic.yaml`: fault rates, vendor behavior, and how many of each discrepancy to plant.
