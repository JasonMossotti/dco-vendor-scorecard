# Mechanical telemetry (Site AUS-1, synthetic)

Synthetic mechanical telemetry over BACnet/IP, with the point names Vertiv publishes for its iCOM controllers. Window Aug 31, 2026 to Sep 28, 2026: one read a minute of every chiller, facility water pump, the facility water loop, every thermal wall, and every electrical-room CRAH, over BACnet/IP from the Landlord's BMS server. All names and readings are fictional; no vendor's internal tooling is implied.

Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py

The series split the hourly energy meters into each machine. Each hall's thermal walls carry the heat its CDUs do not (the racks' air-side heat), and their fans plus the CDUs' pumps are that hall's mechanical UPS load. The chillers carry everything the plant rejects, staged by load with a weekly lead rotation.

## Plant

| Measure | Value |
|---|---|
| Chillers | 11 x Liebert AFC air-cooled free-cooling chiller, 1500 kW nominal (R-513A) |
| Running | 3 to 4 at once |
| Facility water supply / return, mean | 20.0 C / 27.36 C |
| Loop flow, mean / peak | 135.0 / 166.56 L/s |
| Heat rejected | 2,798.1 MWh (peak 5,161 kW) |
| Chiller energy | 453.6 MWh |
| Pump energy | 13.8 MWh |

## Chillers

| Chiller | Running h | Free cooling h | Energy MWh | Heat MWh | Heat per kWh | Free-cooling share | Highest condensing bar | Tripped min | Held off min | FC inhibited h |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CH-01 | 336.0 | 162.0 | 63.5 | 398.4 | 6.27 | 15.2% | 13.1 | 0 | 0 | 0.0 |
| CH-02 | 336.0 | 162.0 | 63.5 | 398.4 | 6.27 | 15.2% | 13.1 | 0 | 0 | 0.0 |
| CH-03 | 305.0 | 85.0 | 57.0 | 342.9 | 6.01 | 9.6% | 13.2 | 0 | 180 | 143.0 |
| CH-04 | 168.0 | 94.0 | 29.1 | 191.7 | 6.58 | 18.9% | 12.5 | 0 | 0 | 0.0 |
| CH-05 | 171.0 | 97.0 | 29.6 | 194.9 | 6.59 | 18.9% | 20.4 | 201 | 0 | 0.0 |
| CH-06 | 163.8 | 87.5 | 28.4 | 186.3 | 6.55 | 18.7% | 12.5 | 0 | 180 | 5.7 |
| CH-07 | 234.9 | 113.9 | 41.8 | 254.0 | 6.08 | 14.1% | 13.2 | 0 | 0 | 0.0 |
| CH-08 | 171.0 | 74.0 | 32.6 | 190.5 | 5.84 | 12.2% | 20.4 | 273 | 0 | 0.0 |
| CH-09 | 165.0 | 71.0 | 31.5 | 183.8 | 5.83 | 12.3% | 13.2 | 0 | 0 | 0.0 |
| CH-10 | 208.3 | 93.6 | 42.1 | 252.2 | 5.98 | 12.9% | 13.2 | 0 | 180 | 6.7 |
| CH-11 | 168.0 | 77.0 | 34.3 | 205.1 | 5.98 | 13.5% | 13.1 | 0 | 0 | 0.0 |

## Facility water pumps

| Pump | Running h | Energy MWh | Speed when running % | Flow when running L/s |
|---|---:|---:|---:|---:|
| FWP-1 | 336.0 | 3.4 | 38.1 | 67.2 |
| FWP-2 | 504.0 | 5.5 | 39.1 | 69.1 |
| FWP-3 | 504.0 | 4.9 | 37.3 | 66.1 |

## Thermal walls and CRAHs

| Unit | Hall | Supply air mean / max C | Return air mean C | Fan speed mean % | Cooling mean kW | Draw mean kW | Fewest fans running | Fan alarm min | Alarm inhibited h |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TW-A1 | Hall A | 25.0 / 25.7 | 29.7 | 84.9 | 133.2 | 12.55 | 6 | 0 | 0.0 |
| TW-A2 | Hall A | 24.99 / 25.65 | 29.66 | 84.3 | 131.1 | 12.3 | 6 | 0 | 0.0 |
| TW-A3 | Hall A | 25.0 / 25.57 | 29.78 | 86.3 | 137.4 | 13.13 | 6 | 0 | 0.0 |
| TW-A4 | Hall A | 25.0 / 25.59 | 29.69 | 84.8 | 132.4 | 12.49 | 5 | 174 | 0.0 |
| CRAH-A1 | Hall A | 25.0 / 25.59 | 30.88 | 80.0 | 47.1 | 5.0 | 1 | 0 | 0.0 |
| CRAH-A2 | Hall A | 25.0 / 25.61 | 30.89 | 80.0 | 47.1 | 5.0 | 1 | 0 | 0.0 |
| CRAH-A3 | Hall A | 24.99 / 25.6 | 30.88 | 80.0 | 47.1 | 5.0 | 1 | 0 | 0.0 |
| TW-B1 | Hall B | 25.0 / 25.62 | 27.22 | 58.1 | 43.9 | 4.3 | 6 | 0 | 0.0 |
| TW-B2 | Hall B | 25.0 / 25.69 | 27.31 | 59.0 | 46.3 | 4.46 | 6 | 0 | 34.3 |
| TW-B3 | Hall B | 25.0 / 25.56 | 27.26 | 58.3 | 44.8 | 4.36 | 6 | 0 | 0.0 |
| TW-B4 | Hall B | 25.0 / 25.59 | 27.24 | 58.2 | 44.3 | 4.33 | 6 | 0 | 0.0 |
| CRAH-B1 | Hall B | 25.0 / 25.58 | 27.95 | 80.0 | 23.6 | 5.0 | 1 | 0 | 0.0 |
| CRAH-B2 | Hall B | 25.0 / 25.58 | 27.95 | 80.0 | 23.6 | 5.0 | 1 | 0 | 0.0 |
| CRAH-B3 | Hall B | 25.0 / 25.63 | 27.95 | 80.0 | 23.6 | 5.0 | 1 | 0 | 0.0 |

## Events

| From | To | Device | What | Records |
|---|---|---|---|---|
| 2026-09-01T05:00:35Z | 2026-09-01T09:33:43Z | CH-08 | Compressor trip: circuit 1 condensing pressure reached 20.4 bar and BV 35 (High Condensing Pressure) went active; the unit read Alarm Off for 4.5 h, and CH-03 started to carry its load | WO-41035 |
| 2026-09-08T11:40:28Z | 2026-09-08T17:21:24Z | CH-06 | Free cooling inhibited (Stop or Inhibit FC activation = 1) for 5.7 h: the chiller ran 3 h on its compressors only, 3 h of them while the other running chillers were free cooling | PM-0014 |
| 2026-09-08T14:21:24Z | 2026-09-08T17:21:24Z | CH-06 | BMS hold: Chiller enable written Off at priority 8 (Manual Operator) for 3.0 h; the unit read BMS Off with no load while the other chillers carried the plant, then the write was relinquished | PM-0014 |
| 2026-09-11T15:45:03Z | 2026-09-11T22:27:23Z | CH-10 | Free cooling inhibited (Stop or Inhibit FC activation = 1) for 6.7 h: the chiller ran 4 h on its compressors only, 1 h of them while the other running chillers were free cooling | PM-0016 |
| 2026-09-11T19:27:23Z | 2026-09-11T22:27:23Z | CH-10 | BMS hold: Chiller enable written Off at priority 8 (Manual Operator) for 3.0 h; the unit read BMS Off with no load while the other chillers carried the plant, then the write was relinquished | PM-0016 |
| 2026-09-13T12:24:49Z | 2026-09-19T11:23:20Z | CH-03 | Free cooling inhibited (Stop or Inhibit FC activation = 1) for 6.0 days: the chiller ran 140 h on its compressors only, 62 h of them while the other running chillers were free cooling | PM-0015, EN-F2 |
| 2026-09-13T17:08:28Z | 2026-09-13T20:08:28Z | CH-03 | BMS hold: Chiller enable written Off at priority 8 (Manual Operator) for 3.0 h; the unit read BMS Off with no load while the other chillers carried the plant, then the write was relinquished | PM-0015 |
| 2026-09-16T10:54:33Z | 2026-09-16T14:15:48Z | CH-05 | Compressor trip: circuit 1 condensing pressure reached 20.4 bar and BV 35 (High Condensing Pressure) went active; the unit read Alarm Off for 3.4 h, and CH-09 started to carry its load | WO-41062, L-008 |
| 2026-09-19T01:27:21Z | 2026-09-20T11:47:52Z | TW-B2 | High supply temperature alarm inhibited (Event_Algorithm_Inhibit TRUE) for 34.3 h with no change record: supply air read 24.4 to 25.5 C over the span, under the 30 C limit, so the inhibit hid no excursion | L-005 |
| 2026-09-22T09:47:39Z | 2026-09-22T12:41:31Z | TW-A4 | Fan 6 failed (FanSts_OV[6] Alarm, Al_EvpFan active) for 2.9 h: the other five ran at up to 100% and held supply air at up to 25.6 C | WO-41041 |
| 2026-09-24T21:14:20Z | 2026-09-24T21:19:00Z | SITE | Utility outage: the 4 running chillers read Power Failure until the generators carried the plant, and Quick Start had them back to full capacity 5 min later; meanwhile the water in the loop took the heat, and the supply header warmed 0.8 C and recovered | WO-41009 |

## Agreement with the records

| Check | Agrees |
|---|---:|
| Chillers, pumps, and CRAHs add up to their energy meters every hour | 2,016 of 2,016 |
| Each hall's thermal walls plus its CDUs equal its mechanical UPS output every hour | 1,344 of 1,344 |
| Chiller capacity equals the plant's heat; loop flow equals the CDUs', walls', and CRAHs' water | 2,016 of 2,016 |
| Supply header equals the metered water temperature; ambient equals the outdoor meter | 10,503 of 10,503 |
| Enough chillers run, and none while tripped or held off | 12 of 12 |
| Each compressor trip on record shows at its minute and clears at its clear time | 8 of 8 |
| BMS holds, condenser fan overrides, and free-cooling lockouts hold exactly over their spans | 66 of 66 |
| Each wall fan failure and alarm inhibit holds exactly over its span | 3 of 3 |
| No alarm, hold, or inhibit the records do not have; supply air never at its high limit | 67 of 67 |

## Sources

- Vertiv, CoolLoop Chiller Screw Communication Points List, 80340 Rev A (iCOM 3, V1C application; BACnet/IP B-ASC, Modbus TCP, SNMP): https://www.vertiv.com/4aad3b/globalassets/shared/80340-coolloop-chiller-screw-communication-rev-a_10-25.pdf (checked 2026-10-11)
- Vertiv, Liebert AFC packaged air-cooled free-cooling chiller installer guide (iCOM V1C control application, two screw circuits): https://www.vertiv.com/49c08b/globalassets/shared/liebert--afc-packaged-air-cooled-free-cooling-chiller-installer-guide-sl-70790.pdf (checked 2026-10-11)
- Vertiv, Liebert PDX and Liebert PCW V1A Application Monitoring Installer/User Guide for Liebert iCOM 3 (chilled-water point names): https://www.vertiv.com/49d3e3/globalassets/products/thermal-management/room-cooling/liebert-pdx-and-liebert-pcw-v1a-application-monitoring-user-guide-installeruser-guide-for-liebert-icom-3.pdf (checked 2026-10-11)
- Vertiv, Liebert CWA chilled water thermal wall (200 to 500 kW): https://www.vertiv.com/en-us/products-catalog/thermal-management/room-cooling/liebert-cwa-chilled-water-thermal-wall-unit-from-200-to-500kw/ (checked 2026-10-11)
- BACnet International, ANSI/ASHRAE 135-2024 published (the current edition): https://bacnet.org/news/ansi-ashrae-135-2024-now-published/ (checked 2026-10-11)
- ASHRAE 135 engineering units, status flags, and reliability enumerations as encoded in BACpypes: https://github.com/JoelBender/bacpypes/blob/master/py34/bacpypes/basetypes.py (checked 2026-10-11)
- Vertiv Unity card BACnet PICS (BACnet International listing): https://www.bacnetinternational.net/catalog/manu/vertiv/BACnet-PICS-Unity-20170711.pdf (checked 2026-10-11)
