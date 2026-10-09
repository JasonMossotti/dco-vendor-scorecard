# CDU telemetry (Site AUS-1, synthetic)

Synthetic CDU telemetry in the published DMTF Redfish schema for cooling units. Window Aug 31, 2026 to Sep 28, 2026: one Redfish read a minute of each of 8 CoolIT Systems CHx2000 row-based CDU units (2,000 kW, 1,800 L/min, PG25), at `/redfish/v1/ThermalEquipment/CDUs/{id}` with the Customer's read-only account.

Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py

No CDU maker publishes its Modbus register map or BACnet point list, so the readings use the DMTF Redfish schema (the open standard); the BMS point numbers on the page are illustrative.

## Fields

| Resource | Property | Unit | Meaning |
|---|---|---|---|
| `SecondaryCoolantConnectors/1` | `SupplyTemperatureCelsius` | °C | Coolant temperature leaving the CDU to the racks (the technology cooling system). |
| `SecondaryCoolantConnectors/1` | `ReturnTemperatureCelsius` | °C | Coolant temperature coming back from the racks. |
| `SecondaryCoolantConnectors/1` | `DeltaTemperatureCelsius` | °C | Return minus supply on the rack side. |
| `SecondaryCoolantConnectors/1` | `FlowLitersPerMinute` | L/min | Coolant flow to the racks. |
| `SecondaryCoolantConnectors/1` | `SupplyPressurekPa` | kPa | Pressure leaving the CDU to the racks. |
| `SecondaryCoolantConnectors/1` | `ReturnPressurekPa` | kPa | Pressure coming back from the racks. |
| `SecondaryCoolantConnectors/1` | `DeltaPressurekPa` | kPa | Supply minus return pressure across the rack loop. |
| `SecondaryCoolantConnectors/1` | `HeatRemovedkW` | kW | Heat the CDU takes out of the rack loop (its heat meter). |
| `SecondaryCoolantConnectors/1` | `SupplyTemperatureControlCelsius` | °C | The supply temperature the CDU controls to. |
| `PrimaryCoolantConnectors/1` | `SupplyTemperatureCelsius` | °C | Facility water temperature into the CDU. |
| `PrimaryCoolantConnectors/1` | `ReturnTemperatureCelsius` | °C | Facility water temperature back to the chiller loop. |
| `PrimaryCoolantConnectors/1` | `FlowLitersPerMinute` | L/min | Facility water flow through the heat exchanger. |
| `PrimaryCoolantConnectors/1` | `DeltaPressurekPa` | kPa | Facility water pressure drop across the CDU. |
| `Sensors/PrimaryValve` | `Reading` | % | Facility water control valve position (a Sensor: the CoolantConnector schema has no valve property). |
| `Pumps/1` | `PumpSpeedPercent` | % | Pump 1 speed; 0 while it stands by. |
| `Pumps/2` | `PumpSpeedPercent` | % | Pump 2 speed; 0 while it stands by. |
| `Sensors/FilterDP` | `Reading` | kPa | Pressure drop across the secondary filter (a Sensor: the Filter schema has no pressure property). It rises as the filter loads and falls when it is changed. |
| `Reservoirs/1` | `FluidLevelPercent` | % | Expansion tank level. |
| `EnvironmentMetrics` | `PowerWatts` | W | The CDU's own electrical draw (pumps and controls). |
| `EnvironmentMetrics` | `TemperatureCelsius` | °C | Air temperature at the CDU. |
| `EnvironmentMetrics` | `HumidityPercent` | % | Relative humidity at the CDU. |
| `EnvironmentMetrics` | `DewPointCelsius` | °C | Dew point at the CDU: the supply must stay above it so pipes do not sweat. |

## The month by CDU

| CDU | Supply avg / max C | Return avg C | Flow avg / min L/min | Heat avg / peak kW | Filter dP at end kPa | Leak min | Redundancy lost min |
|---|---:|---:|---:|---:|---:|---:|---:|
| CDU-A1 | 24.98 / 26.21 | 30.35 | 1,800 / 1,742 | 646 / 760 | 20.9 | 104 | 0 |
| CDU-A2 | 25.04 / 26.26 | 30.35 | 1,800 / 1,549 | 638 / 731 | 19.8 | 0 | 224 |
| CDU-A3 | 24.98 / 26.11 | 30.35 | 1,801 / 1,739 | 646 / 772 | 14.5 | 0 | 0 |
| CDU-A4 | 24.94 / 26.11 | 30.35 | 1,800 / 1,727 | 651 / 767 | 18.0 | 95 | 0 |
| CDU-B1 | 25.03 / 26.34 | 26.38 | 1,800 / 1,737 | 162 / 415 | 16.4 | 0 | 0 |
| CDU-B2 | 25.04 / 26.11 | 26.38 | 1,800 / 1,741 | 162 / 415 | 14.7 | 0 | 0 |
| CDU-B3 | 24.96 / 26.01 | 26.38 | 1,800 / 1,591 | 171 / 426 | 15.2 | 0 | 339 |
| CDU-B4 | 25.03 / 26.05 | 26.38 | 1,799 / 1,743 | 162 / 389 | 15.3 | 0 | 0 |

## Halls

| Hall | State | CDUs | Heat avg / peak kW | Capacity with one CDU down kW |
|---|---|---|---:|---:|
| Hall A | in service | CDU-A1, CDU-A2, CDU-A3, CDU-A4 | 2,581 / 2,738 | 6,000 |
| Hall B | in service | CDU-B1, CDU-B2, CDU-B3, CDU-B4 | 657 / 1,402 | 6,000 |
| Hall C (800 VDC pilot) | planned | CDU-C1, CDU-C2, CDU-C3 | 0 / 0 | 4,000 |

## Events

| From | To | CDU | What | Records |
|---|---|---|---|---|
| 2026-09-04T19:06:50Z | 2026-09-04T19:36:50Z | CDU-B3 | Pump 2 isolated for a filter change and coolant sample; filter changed when it was re-enabled | PM-0010, MOP-303 |
| 2026-09-06T02:51:39Z | 2026-09-06T08:30:41Z | CDU-B3 | Pump 2 failed: the standby pump took over (flow dipped for a minute); pump redundancy lost until the repair tested OK | WO-41031 |
| 2026-09-08T13:30:30Z | 2026-09-08T14:00:30Z | CDU-B4 | Pump 2 isolated for a filter change and coolant sample; filter changed when it was re-enabled | PM-0011, MOP-304 |
| 2026-09-11T13:53:49Z | 2026-09-11T14:23:49Z | CDU-B2 | Pump 2 isolated for a filter change and coolant sample; filter changed when it was re-enabled | PM-0008, MOP-301 |
| 2026-09-14T09:42:00Z | 2026-09-14T11:26:00Z | CDU-A1 | Leak detector 2 (row leak rope): A06 leak rope; the reservoir level fell until it was cleared | INC3100714 |
| 2026-09-15T15:43:00Z | 2026-09-15T19:15:00Z | A07 | Rack A07 lost input power: its heat left the Hall A header until it booted |  |
| 2026-09-18T17:51:00Z | 2026-09-18T19:26:00Z | CDU-A4 | Leak detector 1 (under the unit): Under CDU-A4; the reservoir level fell until it was cleared | WO-41051 |
| 2026-09-20T19:06:52Z | 2026-09-20T19:36:52Z | CDU-A3 | Pump 2 isolated for a filter change and coolant sample; filter changed when it was re-enabled | PM-0009, MOP-302 |
| 2026-09-23T04:34:15Z | 2026-09-23T08:18:06Z | CDU-A2 | Pump 2 failed: the standby pump took over (flow dipped for a minute); pump redundancy lost until the repair tested OK | WO-41024 |

## Agreement with the records

| Check | Agrees |
|---|---:|
| Secondary supply: each hour's mean and max equal the CDU hourly record | 5,376 of 5,376 |
| Secondary flow: each hour's mean and min equal the CDU hourly record | 5,376 of 5,376 |
| Pumps: states, speeds, failover dips, and redundancy match the Redfish events | 322,607 of 322,607 |
| Leak detectors read Critical exactly over the recorded leaks; the reservoir falls only then | 29 of 29 |
| Heat removed per hall equals the liquid share of its racks' power in the GPU telemetry | 1,344 of 1,344 |
| HeatRemovedkW equals flow x density x specific heat x delta T, every minute | 322,560 of 322,560 |
| Primary supply: each hour's mean equals the metered facility water temperature | 5,376 of 5,376 |
| Filter pressure drop falls only at a recorded filter change, and at every one | 12 of 12 |
| The CDUs' draw fits inside the metered mechanical UPS input of their hall | 1,344 of 1,344 |

## Sources

- DMTF, Redfish for Cooling Units (liquid cooling added in Redfish release 2023.1): https://www.dmtf.org/sites/default/files/Redfish_for_Cooling_Units_v1.0.pdf (checked 2026-10-09)
- DMTF Redfish schema CoolingUnit v1_6_0 (EquipmentType CDU; /redfish/v1/ThermalEquipment/CDUs/{id}): https://redfish.dmtf.org/schemas/v1/CoolingUnit.v1_6_0.json (checked 2026-10-09)
- DMTF Redfish schema CoolantConnector v1_1_0 (supply, return, delta, flow, pressures, HeatRemovedkW, control setpoints): https://redfish.dmtf.org/schemas/v1/CoolantConnector.v1_1_0.json (checked 2026-10-09)
- DMTF Redfish schemas Pump, Filter, Reservoir, LeakDetector v1_0_0: https://redfish.dmtf.org/schemas/v1/ (checked 2026-10-09)
- OCP Project Deschutes CDU specification v1.0 (monitored points, N+1 pumps, Modbus/TCP): https://www.opencompute.org/documents/ocp-specification-deschutes-v1-0-pdf (checked 2026-10-09)
- OCP OAI system liquid cooling guidelines (1.5 LPM/kW typical with PG25; about 10 C rise typical): https://www.opencompute.org/documents/oai-system-liquid-cooling-guidelines-in-ocp-template-mar-3-2023-update-pdf (checked 2026-10-09)
- ASHRAE liquid cooling facility water classes W17 to W45 (summary): https://www.upsite.com/blog/major-changes-to-ashraes-fifth-edition-of-thermal-guidelines-part-3-liquid-cooling-chapter-updates/ (checked 2026-10-09)
- Trane points list BAS-PTS007C (style reference: a BACnet object and a Modbus register per point, 32-bit floats): https://elibrary.tranetechnologies.com/public/commercial-hvac/Literature/Points%20List/BAS-PTS007C-EN_06302026.pdf (checked 2026-10-09)
