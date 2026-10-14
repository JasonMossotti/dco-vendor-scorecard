<!--
  GENERATED FILE. DO NOT EDIT BY HAND.
  Source: data/sample/ (scheduler, tickets, badges, health checks, spares, RMA) and the IT engine  |  Generator: scripts/render_availability.py
-->

# Availability and Repair Turnaround: Site AUS-1

Sample month Aug 31, 2026 to Sep 27, 2026 (UTC). Synthetic data; all names fictional. This view reads the records and the engine's measurement; it scores nothing new.

## Summary

| Measure | Value |
|---|---|
| Fleet availability, scheduler view | 99.918% (1,440.2 of 1,760,490 GPU-hours could not take work) |
| CSL-01 Supplier-attributable availability | 99.927% (minimum 99.0%): 1,279 capacity-weighted GPU-hours lost of 1,760,490 installed |
| CSL-12 worst rack | 99.489%: Worst rack A15: 247 GPU-hours lost |
| GPU-hours lost under the contracts | 1,524.9 |
| HALL-A, scheduler view | 99.907% (32 racks installed, 1,440.2 GPU-hours lost) |
| HALL-B, scheduler view | 100.000% (13 racks installed, 0.0 GPU-hours lost) |

## GPU-hours lost by owner

| Owner | GPU-hours | Basis |
|---|---|---|
| IT Partner | 1,279.2 | CSL-01: capacity-weighted, Tickets of Record from the first fault signal to validated return to service |
| Landlord | 245.7 | Rack power loss to the Landlord's handoff (Interface Agreement FA-1, FA-3) |
| OEM | 0.0 | Excused only for part unavailability with spares at minimum; none claimed |
| Customer | 0.0 | Customer holds and withheld access; none recorded |
| Planned work | 0.0 | Approved maintenance drains; none in the scheduler record |

## Scheduler to contracts

| Step | GPU-hours |
|---|---|
| **GPU-hours the scheduler could not place work on** | **1,440.2** |
| The node went back to the scheduler after its validated return to service | -10.5 |
| The contract clock starts at the first fault signal; the scheduler drained the node a little later | +6.4 |
| A repair that did not hold (TR-1, TR-2): the contract counts from the first fault, through the time the node ran between the failed repair and the repeat fault | +42.4 |
| Degraded links count at 25% under the contract; the scheduler kept the node in service | +46.4 |
| **GPU-hours lost under the contracts (all owners)** | **1,524.9** |

Beside the bridge, not in either total: GPU-hours idle on storage. The scheduler kept these nodes in service while their running jobs waited on storage I/O behind a flapping storage fabric uplink (reports/storage_telemetry.md).

| From | Uplink | Minutes | Racks | Nodes | GPU-hours idle |
|---|---|---|---|---|---|
| 2026-09-19T00:55:00Z | eth-b1-1 swp64 | 22 | B02, B03, B05, B08 | 72 | 107.5 |
| 2026-09-20T18:35:00Z | eth-a3-2 swp61 | 34 | A21, A22, A23, A24 | 72 | 164.1 |
| **2 storage stalls** |  |  |  |  | **271.6** |

## By cause

| Cause | Incidents | IT Partner | Landlord | Total | Share | Worst rack |
|---|---|---|---|---|---|---|
| Compute tray (GPU) | 39 | 633.0 | 0.0 | 633.0 | 41.5% | A31 (74.8) |
| Rack power loss | 1 | 58.3 | 245.7 | 304.0 | 19.9% | A07 (304.0) |
| NVLink switch tray | 1 | 234.7 | 0.0 | 234.7 | 15.4% | A15 (234.7) |
| Coolant leak | 1 | 203.3 | 0.0 | 203.3 | 13.3% | A06 (203.3) |
| Optic or link | 22 | 150.0 | 0.0 | 150.0 | 9.8% | A13 (53.7) |
| PSU | 7 | 0.0 | 0.0 | 0.0 | 0.0% | none: no GPUs out of service |
| Power shelf | 1 | 0.0 | 0.0 | 0.0 | 0.0% | none: no GPUs out of service |

## By week (the weekly review's weeks)

| Week | Scheduler | CSL-01 measured | IT Partner reported | IT Partner GPU-hours | Landlord GPU-hours |
|---|---|---|---|---|---|
| 1. Aug 31 to Sep 6 | 99.941% | 99.925% | 99.943% | 289.4 | 0.0 |
| 2. Sep 7 to Sep 13 | 99.955% | 99.955% | 99.954% | 178.7 | 0.0 |
| 3. Sep 14 to Sep 20 | 99.862% | 99.917% | 99.917% | 380.5 | 245.7 |
| 4. Sep 21 to Sep 27 | 99.923% | 99.917% | 99.895% | 430.5 | 0.0 |

## Repair turnaround by stage (per ticket)

Median, with the 90th percentile in parentheses. Stages run one after another and add up to the measured time: Detect, fault signal to ticket; Acknowledge, ticket to acknowledged; Reach the rack, acknowledged to on site (badge into the hall); Repair, on site to repair done; Validate, repair to validated return to service.

| Cause | Tickets | Detect | Acknowledge | Reach the rack | Repair | Validate |
|---|---|---|---|---|---|---|
| Compute tray (GPU) | 41 | 3 min (6 min) | 7 min (10 min) | 5 min (18 min) | 1 h 07 min (1 h 46 min) | 2 h 15 min (2 h 15 min) |
| Optic or link | 23 | 4 min (5 min) | 12 min (36 min) | 12 min (1 h 49 min) | 38 min (46 min) | 35 min (35 min) |
| PSU | 7 | 4 min (5 min) | 28 min (41 min) | 1 h 56 min (2 h 06 min) | 18 min (22 min) | 5 min (5 min) |
| Coolant leak | 1 | 4 min (4 min) | 2 min (2 min) | 4 min (4 min) | 23 min (23 min) | 2 h 16 min (2 h 16 min) |
| NVLink switch tray | 1 | 2 min (2 min) | 4 min (4 min) | 0 min (0 min) | 1 h 55 min (1 h 55 min) | 1 h 15 min (1 h 15 min) |
| Power shelf | 1 | 4 min (4 min) | 6 min (6 min) | 7 min (7 min) | 28 min (28 min) | 10 min (10 min) |
| Rack power loss | 1 | 0 min (0 min) | 0 min (0 min) | 5 min (5 min) | 5 min (5 min) | 39 min (39 min) |

## Restoration: measured against reported

| Cause | Tickets of Record | Tickets | Measured median (P90) | Reported median (P90) | Longest measured | Longest reported |
|---|---|---|---|---|---|---|
| Compute tray (GPU) | 39 | 41 | 3 h 40 min (4 h 28 min) | 3 h 36 min (4 h 28 min) | 10 h 23 min | 7 h 13 min |
| Optic or link | 22 | 23 | 1 h 43 min (7 h 37 min) | 1 h 36 min (6 h 14 min) | 11 h 04 min | 9 h 28 min |
| PSU | 7 | 7 | 2 h 45 min (3 h 03 min) | 2 h 50 min (3 h 05 min) | 3 h 06 min | 3 h 07 min |
| Coolant leak | 1 | 1 | 2 h 49 min (2 h 49 min) | 2 h 51 min (2 h 51 min) | 2 h 49 min | 2 h 51 min |
| NVLink switch tray | 1 | 1 | 3 h 16 min (3 h 16 min) | 3 h 18 min (3 h 18 min) | 3 h 16 min | 3 h 18 min |
| Power shelf | 1 | 1 | 55 min (55 min) | 55 min (55 min) | 55 min | 55 min |
| Rack power loss | 1 | 1 | 49 min (49 min) | 55 min (55 min) | 49 min | 55 min |

Tickets with a stage that has no record: INC3100510 (no validation record; F-006); INC3100748 (no validation record; F-008).

## Spares

| FRU class | Minimum | Start | End | Lowest | Days below minimum | Issued | Received |
|---|---|---|---|---|---|---|---|
| 800G OSFP optic | 150 | 225 | 218 | 218 | 0 of 28 | 17 | 10 |
| Compute tray | 6 | 9 | 1 | 1 | 16 of 28 | 26 | 19 |
| E1.S drive | 20 | 30 | 30 | 30 | 0 of 28 | 0 | 0 |
| Fiber and DAC cable kits | 100 | 150 | 150 | 150 | 0 of 28 | 0 | 0 |
| Manifold hose and quick-disconnect kit | 10 | 15 | 15 | 14 | 0 of 28 | 1 | 1 |
| NVLink switch tray | 2 | 3 | 2 | 2 | 0 of 28 | 1 | 0 |
| PSU (5.5 kW) | 24 | 36 | 34 | 33 | 0 of 28 | 7 | 5 |
| Power shelf | 4 | 6 | 6 | 5 | 0 of 28 | 1 | 1 |

## RMA to the OEM

| FRU class | Shipped | Median business days | Longest | Within 5 business days |
|---|---|---|---|---|
| 800G OSFP optic | 17 | 3 | 5 | 17 of 17 |
| Compute tray | 27 | 3 | 5 | 27 of 27 |
| NVLink switch tray | 1 | 0 | 0 | 1 of 1 |
| PSU (5.5 kW) | 7 | 3 | 5 | 7 of 7 |
| Power shelf | 1 | 3 | 3 | 1 of 1 |

Parts the tickets say were removed: 53; with a shipment record: 53.

| Key Measurement | Target | Measured | Detail |
|---|---|---|---|
| KM-06 Spares at or Above Minimum Stock (by FRU class, daily) | 98% | 87.5% (not met) | 28 of 32 counted spares classes at or above minimum |
| KM-07 Spares Cycle Count Accuracy | 99% | 96.9% (not met) | 31 of 32 cycle counts matched the ledger |
| KM-08 RMA Shipped to OEM Within 5 Business Days | 95% | 100.0% (met) | 53 of 53 failed parts shipped to the OEM within 5 business days |
