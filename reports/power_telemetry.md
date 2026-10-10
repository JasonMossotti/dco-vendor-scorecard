# Power telemetry (Site AUS-1, synthetic)

Synthetic power telemetry in the manufacturers' published SNMP and Modbus point maps. Window Aug 31, 2026 to Sep 28, 2026: one read a minute of every UPS (SNMPv3 through its network management card), every busway run and tap-off (the Starline M70 meter, SNMP), and every generator (the EMCP 4.4 controller, Modbus TCP). All names and readings are fictional; no vendor's internal tooling is implied.

Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py

The series are built from the bottom up: each rack's power (its GPUs from the GPU telemetry plus the rest of the rack) splits across its A and B tap-offs, the tap-offs add up to their busway run, and the runs add up to the UPS that feeds them. Each hall's UPS output equals its energy meter every hour.

## Halls

| Hall | UPSs | Racks on busway | IT load avg / peak kW | Design load (4-make-3) kW | One UPS out: each other UPS at the peak |
|---|---|---:|---:|---:|---:|
| Hall A | UPS-A1, UPS-A2, UPS-A3, UPS-A4 | 32 | 2,978.8 / 3,162.0 | 4,500 | 70.3% of 1,500 kW |
| Hall B | UPS-B1, UPS-B2, UPS-B3, UPS-B4 | 32 | 732.8 / 1,564.2 | 4,500 | 34.8% of 1,500 kW |

## UPSs

| UPS | Model | Output avg / peak kW | Load avg / peak % | Energy out / in MWh | Bypass min | On battery s | Lowest charge % |
|---|---|---:|---:|---:|---:|---:|---:|
| MUPS-A1 | Galaxy VL 300 kW, 480 V (mechanical UPS) | 112.8 / 134.1 | 37.6 / 45.3 | 75.8 / 78.1 | 0 | 14 | 98 |
| MUPS-A2 | Galaxy VL 300 kW, 480 V (mechanical UPS) | 113.2 / 134.4 | 37.7 / 45.5 | 76.1 / 78.4 | 0 | 11 | 99 |
| MUPS-B1 | Galaxy VL 300 kW, 480 V (mechanical UPS) | 115.6 / 134.0 | 38.5 / 45.6 | 77.7 / 80.1 | 0 | 13 | 98 |
| MUPS-B2 | Galaxy VL 300 kW, 480 V (mechanical UPS) | 112.5 / 136.2 | 37.5 / 46.2 | 75.6 / 77.9 | 0 | 11 | 99 |
| UPS-A1 | Galaxy VX 1500 kW, 480 V | 744.0 / 799.9 | 49.6 / 55.1 | 500.0 / 520.4 | 151 | 11 | 98 |
| UPS-A2 | Galaxy VX 1500 kW, 480 V | 746.3 / 798.7 | 49.8 / 54.9 | 501.5 / 522.0 | 0 | 14 | 98 |
| UPS-A3 | Galaxy VX 1500 kW, 480 V | 744.9 / 799.2 | 49.7 / 55.1 | 500.6 / 521.1 | 0 | 11 | 98 |
| UPS-A4 | Galaxy VX 1500 kW, 480 V | 743.6 / 791.4 | 49.6 / 56.0 | 499.7 / 520.2 | 0 | 11 | 98 |
| UPS-B1 | Galaxy VX 1500 kW, 480 V | 241.1 / 452.1 | 16.1 / 30.6 | 162.0 / 172.1 | 0 | 12 | 99 |
| UPS-B2 | Galaxy VX 1500 kW, 480 V | 221.0 / 339.7 | 14.7 / 23.1 | 148.5 / 158.1 | 0 | 13 | 99 |
| UPS-B3 | Galaxy VX 1500 kW, 480 V | 146.6 / 450.9 | 9.8 / 30.8 | 98.5 / 106.6 | 151 | 13 | 99 |
| UPS-B4 | Galaxy VX 1500 kW, 480 V | 124.1 / 360.9 | 8.3 / 26.3 | 83.4 / 91.0 | 0 | 12 | 99 |

## Busway runs

Rated 1,200 A; with one feed lost a run may carry up to 90% of that.

| Run | UPS | Racks | Energy MWh | Amps avg / peak | Peak if its partner feed failed A | Voltage min / max | Minutes without feed |
|---|---|---|---:|---:|---:|---:|---:|
| BW-A-R1-PG-A1-A | UPS-A1 | A01 to A06 | 186.7 | 338.0 / 389.1 | 749.6 | 477.4 / 480.9 | 0 |
| BW-A-R1-PG-A1-B | UPS-A2 | A01 to A06 | 187.4 | 339.1 / 390.4 | 749.6 | 477.5 / 480.9 | 0 |
| BW-A-R1-PG-A2-A | UPS-A3 | A07 to A08 | 64.0 | 115.4 / 132.7 | 253.6 | 478.0 / 481.3 | 0 |
| BW-A-R1-PG-A2-B | UPS-A4 | A07 to A08 | 63.5 | 114.6 / 189.7 | 253.6 | 477.9 / 481.3 | 0 |
| BW-A-R2-PG-A2-A | UPS-A3 | A09 to A12 | 124.2 | 224.7 / 258.2 | 493.7 | 477.8 / 481.1 | 0 |
| BW-A-R2-PG-A2-B | UPS-A4 | A09 to A12 | 123.5 | 223.3 / 256.6 | 493.7 | 477.6 / 481.1 | 0 |
| BW-A-R2-PG-A3-A | UPS-A1 | A13 to A16 | 126.6 | 228.9 / 260.0 | 496.5 | 477.8 / 481.2 | 0 |
| BW-A-R2-PG-A3-B | UPS-A3 | A13 to A16 | 123.2 | 222.9 / 253.1 | 496.5 | 477.6 / 481.1 | 0 |
| BW-A-R3-PG-A3-A | UPS-A1 | A17 to A17 | 30.4 | 54.8 / 66.1 | 132.2 | 478.1 / 481.9 | 0 |
| BW-A-R3-PG-A3-B | UPS-A3 | A17 to A17 | 30.9 | 55.9 / 67.4 | 132.2 | 478.2 / 481.4 | 0 |
| BW-A-R3-PG-A4-A | UPS-A2 | A18 to A22 | 158.2 | 286.6 / 322.0 | 618.7 | 477.6 / 480.9 | 0 |
| BW-A-R3-PG-A4-B | UPS-A4 | A18 to A22 | 156.6 | 283.6 / 318.4 | 618.7 | 477.6 / 480.9 | 0 |
| BW-A-R3-PG-A5-A | UPS-A1 | A23 to A24 | 61.5 | 111.3 / 133.1 | 261.9 | 477.9 / 481.7 | 0 |
| BW-A-R3-PG-A5-B | UPS-A4 | A23 to A24 | 62.2 | 112.4 / 134.6 | 261.9 | 478.0 / 481.4 | 0 |
| BW-A-R4-PG-A5-A | UPS-A1 | A25 to A27 | 94.7 | 171.1 / 194.8 | 373.0 | 477.8 / 481.4 | 0 |
| BW-A-R4-PG-A5-B | UPS-A4 | A25 to A27 | 93.9 | 169.6 / 193.4 | 373.0 | 477.8 / 481.0 | 0 |
| BW-A-R4-PG-A6-A | UPS-A2 | A28 to A32 | 155.9 | 281.8 / 317.6 | 621.6 | 477.6 / 481.0 | 0 |
| BW-A-R4-PG-A6-B | UPS-A3 | A28 to A32 | 158.2 | 285.9 / 322.4 | 621.6 | 477.7 / 480.9 | 0 |
| BW-B-R1-PG-B1-A | UPS-B1 | B01 to B06 | 147.8 | 266.7 / 419.6 | 821.5 | 477.2 / 481.3 | 0 |
| BW-B-R1-PG-B1-B | UPS-B2 | B01 to B06 | 148.5 | 268.0 / 422.0 | 821.5 | 477.3 / 481.4 | 0 |
| BW-B-R1-PG-B2-A | UPS-B3 | B07 to B08 | 36.3 | 65.6 / 143.0 | 279.7 | 478.0 / 481.5 | 0 |
| BW-B-R1-PG-B2-B | UPS-B4 | B07 to B08 | 35.4 | 63.9 / 139.3 | 279.7 | 478.2 / 481.6 | 0 |
| BW-B-R2-PG-B2-A | UPS-B3 | B09 to B12 | 48.3 | 87.4 / 283.9 | 557.1 | 477.6 / 481.5 | 0 |
| BW-B-R2-PG-B2-B | UPS-B4 | B09 to B12 | 48.0 | 86.8 / 345.7 | 557.1 | 477.7 / 481.8 | 0 |
| BW-B-R2-PG-B3-A | UPS-B1 | B13 to B16 | 14.2 | 25.7 / 143.1 | 280.0 | 478.1 / 481.6 | 0 |
| BW-B-R2-PG-B3-B | UPS-B3 | B13 to B16 | 13.9 | 25.1 / 139.5 | 280.0 | 478.0 / 481.6 | 0 |
| BW-B-R3-PG-B3-A | UPS-B1 | B17 to B17 | 0.0 | 0.0 / 0.0 | 0.0 | 478.0 / 481.6 | 0 |
| BW-B-R3-PG-B3-B | UPS-B3 | B17 to B17 | 0.0 | 0.0 / 0.0 | 0.0 | 478.2 / 481.7 | 0 |
| BW-B-R3-PG-B4-A | UPS-B2 | B18 to B22 | 0.0 | 0.0 / 0.0 | 0.0 | 478.3 / 481.6 | 0 |
| BW-B-R3-PG-B4-B | UPS-B4 | B18 to B22 | 0.0 | 0.0 / 0.0 | 0.0 | 0.0 / 481.6 | 130 |
| BW-B-R3-PG-B5-A | UPS-B1 | B23 to B24 | 0.0 | 0.0 / 0.0 | 0.0 | 478.3 / 481.7 | 0 |
| BW-B-R3-PG-B5-B | UPS-B4 | B23 to B24 | 0.0 | 0.0 / 0.0 | 0.0 | 478.4 / 481.5 | 0 |
| BW-B-R4-PG-B5-A | UPS-B1 | B25 to B27 | 0.0 | 0.0 / 0.0 | 0.0 | 478.3 / 481.6 | 0 |
| BW-B-R4-PG-B5-B | UPS-B4 | B25 to B27 | 0.0 | 0.0 / 0.0 | 0.0 | 478.4 / 481.7 | 0 |
| BW-B-R4-PG-B6-A | UPS-B2 | B28 to B32 | 0.0 | 0.0 / 0.0 | 0.0 | 478.1 / 481.7 | 0 |
| BW-B-R4-PG-B6-B | UPS-B3 | B28 to B32 | 0.0 | 0.0 / 0.0 | 0.0 | 478.1 / 481.5 | 0 |

## Generators

| Generator | Minutes running | Energy MWh | Peak kW (% of rated) | Fuel at month end % | Hour meter at month end |
|---|---:|---:|---:|---:|---:|
| GEN-1 | 87 | 1.64 | 1,682.3 (56.1%) | 85.8 | 541.75 |
| GEN-2 | 86 | 1.47 | 1,382.7 (46.1%) | 88.7 | 675.97 |
| GEN-3 | 90 | 1.57 | 1,446.3 (48.2%) | 92.4 | 548.74 |
| GEN-4 | 89 | 0.73 | 1,062.8 (35.4%) | 85.4 | 634.22 |
| GEN-5 | 86 | 1.43 | 1,345.4 (44.8%) | 91.8 | 563.19 |
| GEN-6 | 85 | 1.3 | 1,120.8 (37.4%) | 87.2 | 608.93 |
| GEN-7 | 84 | 1.49 | 1,550.7 (51.7%) | 91.3 | 644.26 |

## Events

| From | To | Device | What | Records |
|---|---|---|---|---|
| 2026-09-01T14:28:29Z | 2026-09-01T15:10:07Z | GEN-1 | Monthly loaded exercise: 36 min running, up to 1,682 kW (56.1% of rated) on the load bank | PM-0001 |
| 2026-09-04T16:55:09Z | 2026-09-04T17:36:59Z | GEN-2 | Monthly loaded exercise: 36 min running, up to 1,383 kW (46.1% of rated) on the load bank | PM-0002 |
| 2026-09-04T18:09:27Z | 2026-09-04T18:50:12Z | TO-B29-B | Tap-off breaker open: rack B29 was not yet drawing power, so no load moved. The CPM record names BW-B-R1-PG-B1-B; the tap-off is on BW-B-R4-PG-B6-B. | WO-41017, MOP-308 |
| 2026-09-08T15:26:41Z | 2026-09-08T16:11:35Z | GEN-3 | Monthly loaded exercise: 39 min running, up to 1,446 kW (48.2% of rated) on the load bank | PM-0003 |
| 2026-09-09T16:58:25Z | 2026-09-09T19:08:24Z | BW-B-R3-PG-B4-B | Feed lost: the feeder breaker tripped and the run read 0 V; none of its racks was drawing power yet (not yet in service), so nothing moved | WO-41043 |
| 2026-09-12T17:24:31Z | 2026-09-12T18:08:03Z | GEN-4 | Monthly loaded exercise: 38 min running, up to 100 kW (3.3% of rated) on the load bank | PM-0004, L-003 |
| 2026-09-13T17:54:59Z | 2026-09-13T18:15:54Z | TO-B18-B | Tap-off breaker open: rack B18 was not yet drawing power, so no load moved. | WO-41021, MOP-309 |
| 2026-09-13T19:50:13Z | 2026-09-13T22:20:13Z | UPS-A1 | On bypass for 150 min: maintenance on the UPS (the load rode the bypass, unprotected) | PM-0012, MOP-305 |
| 2026-09-15T15:16:03Z | 2026-09-15T19:22:05Z | TO-A07-A | Tap-off breaker open: rack A07 lost both feeds while TO-A07-B was open too, and went dark. | WO-41023, MOP-310 |
| 2026-09-15T15:42:11Z | 2026-09-15T19:06:55Z | TO-A07-B | Tap-off breaker open: rack A07 lost both feeds while TO-A07-A was open too, and went dark. | WO-41023, MOP-310 |
| 2026-09-15T18:23:51Z | 2026-09-15T19:04:38Z | GEN-5 | Monthly loaded exercise: 35 min running, up to 1,345 kW (44.8% of rated) on the load bank | PM-0005 |
| 2026-09-19T17:15:17Z | 2026-09-19T17:55:25Z | GEN-6 | Monthly loaded exercise: 35 min running, up to 1,121 kW (37.4% of rated) on the load bank | PM-0006 |
| 2026-09-23T00:02:56Z | 2026-09-23T05:48:33Z | UPS-A2 | Power module 6 fault: one power cabinet out, the UPS ran without its spare cabinet until it was replaced | WO-41034 |
| 2026-09-23T16:23:35Z | 2026-09-23T17:02:09Z | GEN-7 | Monthly loaded exercise: 33 min running, up to 1,551 kW (51.7% of rated) on the load bank | PM-0007 |
| 2026-09-23T19:21:58Z | 2026-09-23T21:51:58Z | UPS-B3 | On bypass for 150 min: maintenance on the UPS (the load rode the bypass, unprotected) | PM-0013, MOP-306 |
| 2026-09-24T17:22:19Z | 2026-09-24T18:02:49Z | TO-B09-A | Tap-off breaker open: rack B09 ran on its other feed. The CPM record names BW-B-R3-PG-B4-A; the tap-off is on BW-B-R2-PG-B2-A. | WO-41014 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:34Z | MUPS-A1 | On battery for 14 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:31Z | MUPS-A2 | On battery for 11 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:33Z | MUPS-B1 | On battery for 13 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:31Z | MUPS-B2 | On battery for 11 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:56:06Z | SITE | Utility outage: both MV mains tripped on undervoltage; the UPSs bridged 12 s on battery until the generator ties closed, then the generators carried the site until the utility returned (closed-transition retransfer) | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:31Z | UPS-A1 | On battery for 11 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:34Z | UPS-A2 | On battery for 14 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:31Z | UPS-A3 | On battery for 11 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:31Z | UPS-A4 | On battery for 11 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:32Z | UPS-B1 | On battery for 12 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:33Z | UPS-B2 | On battery for 13 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:33Z | UPS-B3 | On battery for 13 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:32Z | UPS-B4 | On battery for 12 s: the utility failed and the generators took the load | WO-41009 |
| 2026-09-24T21:14:22Z | 2026-09-24T22:01:06Z | GEN-1 | Utility outage: 41 min running, carrying the site in parallel, up to 1,076 kW (35.9% of rated) | WO-41009 |
| 2026-09-24T21:14:22Z | 2026-09-24T22:01:06Z | GEN-2 | Utility outage: 41 min running, carrying the site in parallel, up to 1,064 kW (35.5% of rated) | WO-41009 |
| 2026-09-24T21:14:22Z | 2026-09-24T22:01:06Z | GEN-3 | Utility outage: 41 min running, carrying the site in parallel, up to 1,065 kW (35.5% of rated) | WO-41009 |
| 2026-09-24T21:14:22Z | 2026-09-24T22:01:06Z | GEN-4 | Utility outage: 41 min running, carrying the site in parallel, up to 1,063 kW (35.4% of rated) | WO-41009 |
| 2026-09-24T21:14:22Z | 2026-09-24T22:01:06Z | GEN-5 | Utility outage: 41 min running, carrying the site in parallel, up to 1,065 kW (35.5% of rated) | WO-41009 |
| 2026-09-24T21:14:22Z | 2026-09-24T22:01:06Z | GEN-6 | Utility outage: 41 min running, carrying the site in parallel, up to 1,068 kW (35.6% of rated) | WO-41009 |
| 2026-09-24T21:14:22Z | 2026-09-24T22:01:06Z | GEN-7 | Utility outage: 41 min running, carrying the site in parallel, up to 1,069 kW (35.6% of rated) | WO-41009 |

## Agreement with the records

| Check | Agrees |
|---|---:|
| Each rack's A plus B tap-offs carry its power from the GPU telemetry, every hour | 32,256 of 32,256 |
| Tap-off breakers open and close exactly at the recorded busway CPM events | 12 of 12 |
| A run reads 0 V exactly while its feed is recorded lost; no run exceeds its single-feed limit | 48,395 of 48,395 |
| Tap-offs add up to their runs, runs to their UPS, and each hall's UPSs to the energy meters | 32,256 of 32,256 |
| UPS output source and working power modules match the NMC events, minute by minute | 36 of 36 |
| Batteries discharge only while on battery, recover after, and match the seconds on battery | 70 of 70 |
| Mechanical UPSs read their recorded polls, equal the meter, and cover the CDUs' draw | 3,360 of 3,360 |
| Generators match every EMCP reading, are stopped otherwise, and carry the outage energy | 335 of 335 |
| Voltage and frequency stay inside the bands except where the records show a feed lost | 24,254 of 24,254 |

## Sources

- IETF RFC 1628, UPS Management Information Base (UPS-MIB, mib-2 33): https://www.rfc-editor.org/rfc/rfc1628 (checked 2026-10-09)
- APC PowerNet-MIB, upsAdvBattery and upsBasicOutputStatus objects (enterprise 318): https://mibs.observium.org/object/PowerNet-MIB/upsAdvBattery (checked 2026-10-09)
- Schneider Electric, Galaxy VX Modbus Register Map, 990-5915F (2026-01-20); FAQ FA321205: https://www.se.com/us/en/download/document/SPD_CDIG_GalaxyVX-MM-EN (checked 2026-10-09)
- Schneider Electric, NMC4 for Galaxy VS, VL and VXL (SNMPv3 network management card): https://www.se.com/us/en/product/AP9644/network-management-card-4-nmc4-for-galaxy-vs-galaxy-vl-galaxy-vxl-remote-ups-monitoring-and-management/ (checked 2026-10-09)
- Starline M70 CPM SNMP OID map, firmware 1.08 (enterprise 35774, cpmAcMeter): https://starlinepower.com/sites/default/files/files/M70-CPM-SNMP-OID-MAP-fw1.08.pdf (checked 2026-10-09)
- Starline M70 Critical Power Monitor data sheet: https://starlinepower.com/sites/default/files/2025-01/BUS_M70_DataSheet_4.24.2024.pdf (checked 2026-10-09)
- Caterpillar, Application and Installation Guide: EMCP 4 SCADA Data Links (register numbers): https://www.ccontrols.com/support/dp/ManualEMCP4.pdf (checked 2026-10-09)
- Caterpillar EMCP 3 Modbus map (electrical-point resolution on the same registers): https://store.chipkin.com/articles/cat-m5x-modbus-memory-map-ecmp-31-32-33 (checked 2026-10-09)
- NFPA 110 monthly exercise: 30% of nameplate for 30 minutes (as cited by finding L-003): https://www.nfpa.org/codes-and-standards/nfpa-110-standard-development/110 (checked 2026-10-09)
