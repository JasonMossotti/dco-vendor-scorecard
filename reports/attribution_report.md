# Attribution Report

Every facility event in the window, attributed under the Interface Agreement (FA-1 to FA-6) from the Customer's Telemetry of Record, beside the party the Landlord's work order named. Events where no rack capacity was lost are redundancy events (FA-5) and never touch the IT Partner's clocks.

| T0 | Event | Class | Owner (telemetry) | Rule | Rack capacity lost | Work order | Work order says | Agrees |
|---|---|---|---|:-:|:-:|---|---|:-:|
| 2026-09-01 05:00 UTC | CH-08: Compressor trip (high condenser pressure) | OT-FC-CHW | Landlord | FA-5 | No | WO-41035 | Landlord | Yes |
| 2026-09-06 02:51 UTC | CDU-B3 pump redundancy lost (Redfish PumpRedundancy Warning) | OT-FC-CDU | Landlord | FA-5 | No | WO-41031 | Landlord | Yes |
| 2026-09-09 16:58 UTC | BW-B-R3-PG-B4-B feed lost (Voltage L-L avg 0.0 V) | OT-FC-PWR | Landlord | FA-5 | No | WO-41043 | IT Partner | **No** |
| 2026-09-15 15:42 UTC | Rack A07 lost both feeds at the tap-offs (TO-A07-B opened while the other side was open) | OT-FC-PWR | Landlord | FA-1 | Yes | WO-41023 | Landlord | Yes |
| 2026-09-15 17:09 UTC | VESDA-B2 Airflow Low | OT-FC-FIRE | Landlord | FA-5 | No | WO-41054 | Landlord | Yes |
| 2026-09-16 10:54 UTC | CH-05: Compressor trip (high condenser pressure) | OT-FC-CHW | Landlord | FA-5 | No | WO-41062 | Landlord | Yes |
| 2026-09-18 17:50 UTC | Leak Under CDU-A4 at 13.2 m | OT-FC-LEAK | Landlord | FA-5 | No | WO-41051 | Landlord | Yes |
| 2026-09-22 09:47 UTC | TW-A4: Fan 6 failure | OT-FC-AIR | Landlord | FA-5 | No | WO-41041 | Landlord | Yes |
| 2026-09-23 00:02 UTC | UPS-A2: Power module 6 fault | OT-FC-UPS | Landlord | FA-5 | No | WO-41034 | Landlord | Yes |
| 2026-09-23 04:34 UTC | CDU-A2 pump redundancy lost (Redfish PumpRedundancy Warning) | OT-FC-CDU | Landlord | FA-5 | No | WO-41024 | Landlord | Yes |
| 2026-09-24 21:14 UTC | Utility outage: both 13.8 kV mains tripped on undervoltage | UTILITY | Utility | FA-6 | No | WO-41009 | Utility | Yes |
