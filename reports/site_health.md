# Site health

Site AUS-1, Aug 31, 2026 to Sep 28, 2026 (the sample month). One page for the whole site at any hour of the month: whether each system still has its redundant unit, each device family's main readings, and every rack's state on the hall map. It shows readings and redundancy, not alarms; alarms are on the Alarm Board. Everything here is fictional.

  Source: data/telemetry/ (every section's hourly tier and recorded state changes), site/site.yaml  |  Thresholds: config/site_health.yaml  |  Generator: scripts/render_telemetry.py

## Redundancy over the month

Units in service against the units the design needs; each hour counts its worst minute.

| System | Where | Design | Hours with no redundant unit | Hours below N |
|---|---|---|---:|---:|
| Utility feeds | Site | 2N | 0 | 1 |
| Generators | Site | N+1 | 0 | 0 |
| IT UPSs | Hall A | 4 make 3 | 4 | 0 |
| Mechanical UPSs | Hall A | 2N | 0 | 0 |
| Rack feeds (racks with both feeds) | Hall A | 2N | 0 | 5 |
| CDUs | Hall A | N+1 | 0 | 0 |
| CDU pumps (CDUs with a spare pump) | Hall A | N+1 in each CDU | 6 | 0 |
| Thermal walls | Hall A | N+1 | 0 | 0 |
| Electrical-room CRAHs | Hall A | N+1 | 0 | 0 |
| Thermal-wall fans (walls with every fan) | Hall A | N+1 in each wall (6 fans) | 4 | 0 |
| IT UPSs | Hall B | 4 make 3 | 3 | 0 |
| Mechanical UPSs | Hall B | 2N | 0 | 0 |
| Rack feeds (racks with both feeds) | Hall B | 2N | 2 | 0 |
| CDUs | Hall B | N+1 | 0 | 0 |
| CDU pumps (CDUs with a spare pump) | Hall B | N+1 in each CDU | 12 | 0 |
| Thermal walls | Hall B | N+1 | 0 | 0 |
| Electrical-room CRAHs | Hall B | N+1 | 0 | 0 |
| Thermal-wall fans (walls with every fan) | Hall B | N+1 in each wall (6 fans) | 0 | 0 |
| Chillers | Site | N+1 | 22 | 0 |
| Facility water pumps | Site | N+1 | 0 | 0 |
| Management aggregation | Hall A | N+1 | 0 | 0 |
| Management aggregation | Hall B | N+1 | 0 | 0 |

## Each family's state

| Family | Normal | Degraded | Lost |
|---|---:|---:|---:|
| GPUs | 143 h | 526 h | 3 h |
| CDUs | 648 h | 18 h | 6 h |
| Power | 651 h | 15 h | 6 h |
| Network | 657 h | 15 h | 0 h |
| Mechanical | 646 h | 26 h | 0 h |
| Management network | 607 h | 65 h | 0 h |

## Conditions other than GPU racks

GPU rack conditions (drained nodes, thermal slowdown, missing GPUs) are on the page's hall map and in the GPU telemetry report.

| From | To | Family | Where | Condition |
|---|---|---|---|---|
| Sep 1 05:00 | Sep 1 10:00 | Mechanical | Site | Chillers: 10 of 11, no redundant unit (CH-08 compressor trip) |
| Sep 1 08:00 | Sep 1 09:00 | Management network | Hall A | a31-ct11: BMC not answering |
| Sep 4 01:00 | Sep 4 02:00 | Management network | Hall A | a05-ct18: BMC not answering |
| Sep 4 19:00 | Sep 4 20:00 | CDUs | Hall B | CDU-B3: pump 2 isolated for planned work, no spare pump |
| Sep 4 20:00 | Sep 4 22:00 | Management network | Hall A | a03-ct14: BMC not answering |
| Sep 5 00:00 | Sep 5 02:00 | Management network | Hall A | a29-ct03: BMC not answering |
| Sep 6 02:00 | Sep 6 09:00 | CDUs | Hall B | CDU-B3: pump 2 failed, no spare pump |
| Sep 6 13:00 | Sep 6 14:00 | Management network | Hall A | a09-ct10: BMC not answering |
| Sep 7 03:00 | Sep 7 04:00 | Management network | Hall A | a22-ct07: BMC not answering |
| Sep 7 07:00 | Sep 7 09:00 | Management network | Hall A | A03_PowerShelf_3: BMC not answering |
| Sep 8 13:00 | Sep 8 15:00 | CDUs | Hall B | CDU-B4: pump 2 isolated for planned work, no spare pump |
| Sep 8 13:00 | Sep 8 14:00 | Management network | Hall A | a26-ct16: BMC not answering |
| Sep 8 14:00 | Sep 8 18:00 | Mechanical | Site | Chillers: 10 of 11, no redundant unit (CH-06 held off by the BMS (planned maintenance)) |
| Sep 10 15:00 | Sep 10 18:00 | Management network | Hall A | a21-ct09: BMC not answering |
| Sep 11 13:00 | Sep 11 15:00 | CDUs | Hall B | CDU-B2: pump 2 isolated for planned work, no spare pump |
| Sep 11 19:00 | Sep 11 23:00 | Mechanical | Site | Chillers: 10 of 11, no redundant unit (CH-10 held off by the BMS (planned maintenance)) |
| Sep 13 03:00 | Sep 13 05:00 | Management network | Hall A | a14-ct07: BMC not answering |
| Sep 13 17:00 | Sep 13 21:00 | Mechanical | Site | Chillers: 10 of 11, no redundant unit (CH-03 held off by the BMS (planned maintenance)) |
| Sep 13 19:00 | Sep 13 23:00 | Power | Hall A | IT UPSs (Hall A): 3 of 4, no redundant unit (UPS-A1 on static bypass) |
| Sep 14 09:00 | Sep 14 12:00 | CDUs | Hall A | CDU-A1: leak detected (A06 leak rope) |
| Sep 14 09:00 | Sep 15 06:00 | Management network | Hall A | a27-mgmt1 down: rack A27, its 35 BMCs unreachable |
| Sep 15 10:00 | Sep 15 11:00 | Management network | Hall A | a07-ct04: BMC not answering |
| Sep 15 14:00 | Sep 15 15:00 | Management network | Hall A | a01-ct05: BMC not answering |
| Sep 15 15:00 | Sep 15 20:00 | Power | Hall A | A07: both power feeds lost |
| Sep 15 20:00 | Sep 15 22:00 | Management network | Hall A | a14-ct14: BMC not answering |
| Sep 16 02:00 | Sep 16 03:00 | Management network | Hall A | a23-ct04: BMC not answering |
| Sep 16 10:00 | Sep 16 15:00 | Mechanical | Site | Chillers: 10 of 11, no redundant unit (CH-05 compressor trip) |
| Sep 17 11:00 | Sep 17 12:00 | Management network | Hall A | A23_PowerShelf_7: BMC not answering |
| Sep 17 14:00 | Sep 17 15:00 | Management network | Hall A | a03-ct02: BMC not answering |
| Sep 18 12:00 | Sep 18 14:00 | Management network | Hall A | a19-mgmt1: uplink swp50 down (no redundant uplink) |
| Sep 18 17:00 | Sep 18 20:00 | CDUs | Hall A | CDU-A4: leak detected (Under CDU-A4) |
| Sep 20 08:00 | Sep 20 11:00 | Management network | Hall B | b12-mgmt2: uplink swp49 down (no redundant uplink) |
| Sep 20 19:00 | Sep 20 20:00 | CDUs | Hall A | CDU-A3: pump 2 isolated for planned work, no spare pump |
| Sep 22 01:00 | Sep 22 03:00 | Management network | Hall A | a22-ct02: BMC not answering |
| Sep 22 09:00 | Sep 22 13:00 | Mechanical | Hall A | TW-A4: fan 6 failed, 5 of 6 fans |
| Sep 22 21:00 | Sep 22 23:00 | Management network | Hall A | a10-ct12: BMC not answering |
| Sep 23 00:00 | Sep 23 06:00 | Power | Hall A | UPS-A2: power module out, 5 of 6 (no module redundancy) |
| Sep 23 04:00 | Sep 23 09:00 | CDUs | Hall A | CDU-A2: pump 2 failed, no spare pump |
| Sep 23 07:00 | Sep 23 08:00 | Management network | Hall A | a19-ct15: BMC not answering |
| Sep 23 13:00 | Sep 23 14:00 | Management network | Hall A | a13-ct01: BMC not answering |
| Sep 23 19:00 | Sep 23 22:00 | Power | Hall B | IT UPSs (Hall B): 3 of 4, no redundant unit (UPS-B3 on static bypass) |
| Sep 24 01:00 | Sep 24 04:00 | Management network | Hall A | a09-ct14: BMC not answering |
| Sep 24 17:00 | Sep 24 19:00 | Management network | Hall A | a01-ct10: BMC not answering |
| Sep 24 17:00 | Sep 24 19:00 | Power | Hall B | B09: one power feed lost (no redundancy) |
| Sep 24 21:00 | Sep 24 22:00 | Power | Site | Utility feeds: 0 of 2, site on generators (MV-A main breaker tripped; MV-B main breaker tripped) |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall A | MUPS-A1: on battery 14 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall A | MUPS-A2: on battery 11 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall B | MUPS-B1: on battery 13 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall B | MUPS-B2: on battery 11 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall A | UPS-A1: on battery 11 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall A | UPS-A2: on battery 14 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall A | UPS-A3: on battery 11 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall A | UPS-A4: on battery 11 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall B | UPS-B1: on battery 12 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall B | UPS-B2: on battery 13 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall B | UPS-B3: on battery 13 s |
| Sep 24 21:00 | Sep 24 22:00 | Power | Hall B | UPS-B4: on battery 12 s |
| Sep 25 01:00 | Sep 25 02:00 | Management network | Hall A | a30-ct08: BMC not answering |
| Sep 25 08:00 | Sep 25 10:00 | Management network | Hall A | a15-nvsw3: BMC not answering |
| Sep 25 09:00 | Sep 25 10:00 | Network | Hall A | A15: 1 NVLink tray not reporting |
| Sep 26 01:00 | Sep 26 02:00 | Management network | Hall A | a20-ct07: BMC not answering |
| Sep 27 11:00 | Sep 27 12:00 | Management network | Site | Telemetry of Record poller restarted: no BMC polled |

InfiniBand link drops: 13 spans in 14 hours (each on the Network page).

## Agreement with the hourly figures

The dashboard's state comes from each section's recorded state changes; these checks hold it to the hourly figures each section publishes.

| Check | Agrees |
|---|---:|
| A UPS counts as out in exactly the hours its hourly row reports minutes on bypass | 8,064 of 8,064 |
| A busway's racks lose that feed in exactly the hours its hourly row reports minutes without voltage | 24,192 of 24,192 |
| A chiller counts as out in exactly the hours its hourly row reports alarm or BMS-off minutes | 7,392 of 7,392 |
| A thermal wall loses a fan in exactly the hours its hourly row reports fewer fans running | 5,376 of 5,376 |
| Every hour a CDU reports pump redundancy lost, the dashboard has a pump out | 12 of 12 |
| A rack shows no GPUs reporting only in hours it lost both feeds, and in every hour it had none all hour | 26,301 of 26,301 |
| Every hour the utility feeds are lost, every generator runs | 1 of 1 |
| A management switch counts as down in exactly the hours its hourly row reports fewer than 60 minutes up | 88,704 of 88,704 |
| Each hall's GPU power and UPS output add up from the hourly rows | 1,344 of 1,344 |

## Sources

- ASHRAE TC 9.9, Thermal Guidelines for Data Processing Environments, 5th edition (recommended 18 to 27 C; A1 allowable 15 to 32 C): https://www.ashrae.org/technical-resources/bookstore/datacom-series (checked 2026-10-11)
