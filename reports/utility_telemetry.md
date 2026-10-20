# Utility mains and UPS ride-through (Site AUS-1, synthetic)

Synthetic utility metering at the 13.8 kV mains, and the UPS ride-through it leaves the site if the utility fails. One read a minute of the Landlord's revenue meters on the two 13.8 kV mains (Schneider PowerLogic ION9000, one per 13.8 kV main, on the utility side of the main breaker), through the Landlord's Power Monitoring Expert (read-only account under the Interface Agreement data access clause). All names and readings are fictional; no vendor's internal tooling is implied.

Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py

Each hour's energy across both mains equals the energy meters' utility energy, so PUE and every headline are unchanged. Ride-through is the shortest battery runtime among the UPSs carrying load, as each UPS's network management card reports it.

## Mains

| Main | UPSs on its bus | Energy MWh | kW avg / peak | Amps peak | Voltage avg / lowest / highest | PF avg | THD max % | Minutes dead |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| MV-A | MUPS-A1, MUPS-B1, UPS-A1, UPS-A3, UPS-B1, UPS-B3 | 1,797.5 | 2,674.8 / 3,595.7 | 154.9 | 13,796 / 13,610 / 14,001 | 0.978 | 1.71 | 41 |
| MV-B | MUPS-A2, MUPS-B2, UPS-A2, UPS-A4, UPS-B2, UPS-B4 | 1,767.6 | 2,630.3 / 3,349.8 | 145.1 | 13,796 / 13,605 / 13,968 | 0.978 | 1.65 | 41 |

## Ride-through (m:ss)

| Scope | Lowest | When (hour) | Set by | Month average of the hourly lowest |
|---|---:|---|---|---:|
| SITE-IT | 9:00 | 2026-09-15 15:00Z | UPS-A4 | 9:39 |
| SITE-COOLING | 20:30 | 2026-09-22 10:00Z | MUPS-A2 | 21:52 |
| HALL-A | 9:00 | 2026-09-15 15:00Z | UPS-A4 | 9:39 |
| HALL-B | 16:10 | 2026-09-26 06:00Z | UPS-B3 | 31:23 |

## Utility outages

| Trip | Ties closed | Utility back | UPS bridge s | IT ride-through at the trip | Cooling ride-through at the trip | Margin |
|---|---|---|---:|---:|---:|---:|
| 2026-09-24T21:14:20Z | 2026-09-24T21:14:32Z | 2026-09-24T21:56:06Z | 12 | 9:10 | 21:30 | 8:58 |

The design reference for the generators taking load is 10 s (NFPA 110 Type 10). That applies to Level 1 emergency systems; the data halls' critical load is not one, so no take-load time binds the site and the UPS batteries bridge it.

## Agreement with the records

| Check | Agrees |
|---|---:|
| Both mains together carry the energy meters' utility energy every hour; each main's hourly kWh is its minutes | 2,016 of 2,016 |
| Each main is dead and open from the EPMS trip to the retransfer, carries nothing inside, records the sag, and is live otherwise | 80,724 of 80,724 |
| Each live minute's current is kW over (sqrt 3 x V x PF), and kVAR agrees with the power factor | 80,554 of 80,554 |
| Voltage stays inside the service band, and frequency matches every UPS input's, while the main is live | 80,556 of 80,556 |
| Each main carries at least the input of the UPSs on its bus, every minute the utility carries the site | 80,554 of 80,554 |
| Each minute's ride-through is the shortest runtime among the UPSs in scope carrying load, and names that UPS | 163,968 of 163,968 |
| Each UPS's reported runtime agrees with its battery capacity times its charge over its load (or the card's cap) | 8,064 of 8,064 |
| In each utility outage every UPS's battery seconds equal the trip to the ties closing, shorter than the ride-through then | 15 of 15 |

## Sources

- Schneider Electric, PowerLogic ION9000 data sheet (Modbus TCP; voltage, current, power, PF, frequency, U THD): https://www.farnell.com/datasheets/3771069.pdf (checked 2026-10-19)
- Schneider Electric FAQ FA362601: the ION9000 Modbus register map (attachment): https://www.se.com/ca/en/faqs/FA362601 (checked 2026-10-19)
- PowerLogic ION meters' Modbus maps (measurement labels Vll ab, I a, kW tot, kVAR tot, PF sign tot, Freq): https://www.aggsoft.com/modbus-data-logging/schneider-electric-powerlogic.htm (checked 2026-10-19)
- NFPA 110-2016 design considerations (Type 10: load terminals without power no more than 10 seconds): https://www.csemag.com/articles/nfpa-110-2016-design-considerations/ (checked 2026-10-19)
