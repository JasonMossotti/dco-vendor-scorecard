# Attribution Report

Every facility event in the window, attributed under the Interface Agreement (FA-1 to FA-6) from the Customer's Telemetry of Record, beside the party the Landlord's work order named. Events where no rack capacity was lost are redundancy events (FA-5) and never touch the IT Partner's clocks.

| T0 | Event | Class | Owner (telemetry) | Rule | Rack capacity lost | Work order | Work order says | Agrees |
|---|---|---|---|:-:|:-:|---|---|:-:|
| 2026-09-04 03:24 UTC | BW-A-R3-PG-A4-B feed lost (Voltage L-L avg 0.0 V) | OT-FC-PWR | Landlord | FA-5 | No | WO-41051 | IT Partner | **No** |
| 2026-09-07 08:44 UTC | Leak Under CDU-A4 at 15.0 m | OT-FC-LEAK | Landlord | FA-5 | No | WO-41060 | Landlord | Yes |
| 2026-09-13 06:36 UTC | UPS-B3: Power module 6 fault | OT-FC-UPS | Landlord | FA-5 | No | WO-41035 | Landlord | Yes |
| 2026-09-13 23:43 UTC | CH-01: Compressor trip (high condenser pressure) | OT-FC-CHW | Landlord | FA-5 | No | WO-41070 | Landlord | Yes |
| 2026-09-14 13:57 UTC | VESDA-B1 Airflow Low | OT-FC-FIRE | Landlord | FA-5 | No | WO-41068 | Landlord | Yes |
| 2026-09-16 21:51 UTC | CDU-B3 pump redundancy lost (Redfish PumpRedundancy Warning) | OT-FC-CDU | Landlord | FA-5 | No | WO-41032 | Landlord | Yes |
| 2026-09-17 15:18 UTC | TW-B1: Fan 5 failure | OT-FC-AIR | Landlord | FA-5 | No | WO-41047 | Landlord | Yes |
| 2026-09-23 21:55 UTC | CDU-A1 pump redundancy lost (Redfish PumpRedundancy Warning) | OT-FC-CDU | Landlord | FA-5 | No | WO-41025 | Landlord | Yes |
| 2026-09-24 21:14 UTC | Utility outage: both 13.8 kV mains tripped on undervoltage | UTILITY | Utility | FA-6 | No | WO-41009 | Utility | Yes |
| 2026-09-26 00:51 UTC | CH-03: Compressor trip (high condenser pressure) | OT-FC-CHW | Landlord | FA-5 | No | WO-41042 | Landlord | Yes |
