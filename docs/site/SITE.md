# Site AUS-1 (fictional): site description

> Generated from `site/site.yaml` by `scripts/render_site.py`. Do not edit by hand.
>
> Fictional site for a portfolio demonstration. Equipment models are real products; the site, its layout, quantities, and operators are invented. Schematic only: not a construction document.

Central Texas, USA (fictional parcel), on the ERCOT grid. Utility service at 138 kV, site distribution at 13.8 kV, utilization at 480 V. The building is about 48 m by 29 m. Design-day IT load is 10,288 kW and the design-day peak at the 13.8 kV bus is 15,169 kW.

## Halls

| Hall | State | Racks | Design IT load | Power | CDUs | Compute fabric |
|---|---|---|---|---|---|---|
| Hall A | production | 32 x GB200 NVL72 | 4,224 kW | 4 x Galaxy VX, distributed redundant (4 make 3) | 4 x CHx2000 (N+1) | Quantum-2 QM9700 NDR InfiniBand switch |
| Hall B | deployment | 32 x GB300 NVL72 | 4,224 kW | 4 x Galaxy VX, distributed redundant (4 make 3) | 4 x CHx2000 (N+1) | Quantum-X800 Q3400-RA XDR InfiniBand switch |
| Hall C (800 VDC pilot) | planned | 8 x 800 VDC rack, Vera Rubin class (planned) | 1,840 kW | 2 x Eaton MVSST, 2N, 800 VDC | 3 x CHx2000 (N+1) | Quantum-X800 Q3400-RA XDR InfiniBand switch |

## Security zones

The Security Partner guards and patrols the whole property (Security SLA, SEC-POST; Interface Agreement, DM-SEC). Zones Z0 to Z2 are on sheet A-002, Z3 to Z6 on sheet A-102.

| Zone | Where | Who may enter | How | Controlled by | Patrolled by | Response |
|---|---|---|---|---|---|---|
| Z0 Public approach | Outside the property fence: the access road to the main gate and the pedestrian turnstile. | Anyone. No badge. | None; the main gate's intercom and plate camera (CAM-X-01) at the fence line. | Customer | Security Partner, by camera from the security console; the exterior tour checks the fence line from inside. | A person or vehicle loitering at the gate: P3 (camera review, intercom challenge). |
| Z1 Perimeter and grounds | Inside the property fence: roads, staff and visitor parking, the truck court, the guard house, and the fire lane. | Badge holders of any party; pre-registered visitors and drivers on a Customer-approved request. | Badge or plate read at the main gate, or the security console opening the gate after an intercom check; the pedestrian turnstile reads badges. | Customer | Security Partner: the exterior tour (POST-PATROL) and the exterior cameras. | An intruder inside the fence: P1 (guard engaged in 3 minutes). A gate or the fence found open: P2 (5 minutes). |
| Z2 Equipment yards | The generator yard, the chiller yard with USS-CH1 to USS-CH4, and the MV switchgear and MVSST pad, each behind its own yard fence. | The Landlord's staff and its vendors; others only with a Landlord escort. | The Landlord's yard readers (Generator yard, Chiller yard, MV switchgear) on its base building access control. | Landlord | Security Partner, outside the yard fences: the exterior tour checks each yard gate is shut and locked. | A yard gate found open with no Landlord work under way: P2, the console calls the Landlord's operator. |
| Z3 Building shell and lobby | The security lobby and mantrap, the secure corridor, the NOC, staging and burn-in, and the receiving dock. | Badge holders of any party; visitors signed in at the security console. | The Landlord's Main lobby reader and the mantrap; the Customer's OPS-MAIN reader at the NOC; the dock door opened by the dock post. | Landlord (lobby and mantrap), Customer (NOC, dock) | Security Partner: the security console, the receiving dock post (day), and the interior tour (Receiving dock, Corridor east). | Tailgating through the mantrap: P1. A dock door held open: P2. |
| Z4 Landlord plant rooms | The electrical rooms (ER-A, ER-B, ER-C), the meet-me rooms (MMR-1, MMR-2), the fire riser, and the pump room. | The Landlord's staff and its vendors; carriers in the meet-me rooms with a Landlord escort; the fire department. | The Landlord's readers (Hall A electrical room, Hall B electrical room, and the riser, pump room, and meet-me room doors). | Landlord | Landlord. The Security Partner passes the doors on the interior tour but does not enter. | The Landlord's door alarms go to the Landlord's operator; the console sends a guard on request. |
| Z5 Customer halls | Hall A, Hall B, Hall C (planned), and the telecom room (the out-of-band network). | People on the hall's access list; visitors only with a named escort who badges in with them. | The Customer's hall door readers (HALL-A, HALL-B) beside a guard post; emergency exits on door contacts only. | Customer | Security Partner: the Hall A and Hall B entrance posts and the interior tour; and the hall cameras. | Door forced: P1 (guard engaged in 3 minutes). Door held past 60 seconds: P2. A visitor without an escort: P2. |
| Z6 Spares cage and media room | The spares cage (trays, PSUs, optics, drives) and the media destruction room beside it. | Spares cage: the IT Partner's named technicians. Media room: the Security Partner's destruction operator with a witness. | The Customer's SPARES-CAGE reader; the media room reader admits two people together (two-person rule). | Customer | Security Partner: the interior tour (Hall A spares aisle) and the spares cage cameras. | Door forced, or media unaccounted for in the chain of custody: P1. |

| Gate | Name | Kind | Zone | Reader | Camera |
|---|---|---|---|---|---|
| GATE-MAIN | Main vehicle gate | Sliding vehicle gate with a crash-rated wedge barrier inside it | Z1 | Badge and plate read; intercom to the security console | CAM-X-01 |
| GATE-PED | Pedestrian turnstile | Full-height turnstile | Z1 | Badge reader; intercom to the security console | CAM-X-02 |
| GATE-TRUCK | Truck court gate | Swing gate | Z1 | Opened by the receiving dock post (day) or the console for a booked delivery | CAM-X-04 |
| GATE-FIRE | Fire lane gate | Swing gate, normally locked | Z1 | Fire department key box; the console can open it | CAM-X-14 |
| GATE-GEN | Generator yard gate | Yard gate | Z2 | Landlord reader: Generator yard | CAM-X-07 |
| GATE-CH | Chiller yard gate | Yard gate | Z2 | Landlord reader: Chiller yard | CAM-X-13 |
| GATE-MV | MV switchgear yard gate | Yard gate | Z2 | Landlord reader: MV switchgear | CAM-X-11 |
| GATE-UTIL | Utility substation gate | Utility gate on the east fence | utility | Utility lock; the utility's crews enter the substation from outside and never cross the property | CAM-X-10 |

Exterior tour every 4 hours: XC-1 Main gate, XC-2 Fence north-west, XC-3 Generator yard gate, XC-4 Fence north-east, XC-5 Substation fence, XC-6 Chiller yard gate, XC-7 Fire lane gate, XC-8 Truck court gate. Recorded on the patrol's handheld; the tour rule in the Security SLA measures the interior checkpoints only in this version. 16 exterior cameras record to NVR-5. Guard house: Patrol start reader, the locked shotgun rack (on a door contact and a camera), the exterior tour kit, and a radio base.

## Drawings

| Sheet | Title |
|---|---|
| A-001 | [Campus plan](A-001_campus_plan.svg) |
| A-002 | [Security site plan](A-002_security_site_plan.svg) |
| A-101 | [Building plan](A-101_building_plan.svg) |
| A-102 | [Building security zones](A-102_building_security_zones.svg) |
| A-201 | [Hall A floor plan](A-201_hall_a_plan.svg) |
| A-202 | [Hall B floor plan](A-202_hall_b_plan.svg) |
| A-203 | [Hall C (800 VDC pilot) floor plan](A-203_hall_c_plan.svg) |
| E-001 | [Electrical one-line](E-001_one_line.svg) |
| M-001 | [Cooling flow diagram](M-001_cooling_flow.svg) |
| D-101 | [GB200 NVL72 rack, front and rear elevation](D-101_gb200_nvl72_rack.svg) |
| D-102 | [GB300 NVL72 rack, front and rear elevation](D-102_gb300_nvl72_rack.svg) |
| D-201 | [CHx2000 CDU, front and rear](D-201_chx2000_cdu.svg) |
| D-202 | [Liebert CWA thermal wall, front and section](D-202_liebert_cwa_thermal_wall.svg) |
| D-203 | [Liebert AFC free-cooling chiller, side elevation](D-203_liebert_afc_free_cooling_chiller.svg) |
| D-301 | [Galaxy VX 1500 kW UPS line-up](D-301_galaxy_vx_1500_kw_ups_line_up.svg) |
| D-302 | [Galaxy VL 300 kW UPS, front elevation](D-302_galaxy_vl_300_kw_ups.svg) |
| D-303 | [Track busway section and tap-off](D-303_track_busway_section_and_tap_off.svg) |
| D-401 | [Cat C175-16 generator set, side elevation](D-401_cat_c175_16_generator_set.svg) |
| D-501 | [VESDA-E VEP aspirating smoke detector](D-501_vesda_e_vep_aspirating_smoke_detector.svg) |
| D-502 | [TraceTek leak detection, controller and circuits](D-502_tracetek_leak_detection.svg) |
| D-601 | [Quantum-2 QM9700 InfiniBand leaf switch, port side](D-601_quantum_2_qm9700_infiniband_leaf_switch.svg) |

### A-001 Campus plan

![Campus plan](A-001_campus_plan.svg)

### A-002 Security site plan

![Security site plan](A-002_security_site_plan.svg)

### A-101 Building plan

![Building plan](A-101_building_plan.svg)

### A-102 Building security zones

![Building security zones](A-102_building_security_zones.svg)

### A-201 Hall A floor plan

![Hall A floor plan](A-201_hall_a_plan.svg)

### A-202 Hall B floor plan

![Hall B floor plan](A-202_hall_b_plan.svg)

### A-203 Hall C (800 VDC pilot) floor plan

![Hall C (800 VDC pilot) floor plan](A-203_hall_c_plan.svg)

### E-001 Electrical one-line

![Electrical one-line](E-001_one_line.svg)

### M-001 Cooling flow diagram

![Cooling flow diagram](M-001_cooling_flow.svg)

### D-101 GB200 NVL72 rack, front and rear elevation

![GB200 NVL72 rack, front and rear elevation](D-101_gb200_nvl72_rack.svg)

### D-102 GB300 NVL72 rack, front and rear elevation

![GB300 NVL72 rack, front and rear elevation](D-102_gb300_nvl72_rack.svg)

### D-201 CHx2000 CDU, front and rear

![CHx2000 CDU, front and rear](D-201_chx2000_cdu.svg)

### D-202 Liebert CWA thermal wall, front and section

![Liebert CWA thermal wall, front and section](D-202_liebert_cwa_thermal_wall.svg)

### D-203 Liebert AFC free-cooling chiller, side elevation

![Liebert AFC free-cooling chiller, side elevation](D-203_liebert_afc_free_cooling_chiller.svg)

### D-301 Galaxy VX 1500 kW UPS line-up

![Galaxy VX 1500 kW UPS line-up](D-301_galaxy_vx_1500_kw_ups_line_up.svg)

### D-302 Galaxy VL 300 kW UPS, front elevation

![Galaxy VL 300 kW UPS, front elevation](D-302_galaxy_vl_300_kw_ups.svg)

### D-303 Track busway section and tap-off

![Track busway section and tap-off](D-303_track_busway_section_and_tap_off.svg)

### D-401 Cat C175-16 generator set, side elevation

![Cat C175-16 generator set, side elevation](D-401_cat_c175_16_generator_set.svg)

### D-501 VESDA-E VEP aspirating smoke detector

![VESDA-E VEP aspirating smoke detector](D-501_vesda_e_vep_aspirating_smoke_detector.svg)

### D-502 TraceTek leak detection, controller and circuits

![TraceTek leak detection, controller and circuits](D-502_tracetek_leak_detection.svg)

### D-601 Quantum-2 QM9700 InfiniBand leaf switch, port side

![Quantum-2 QM9700 InfiniBand leaf switch, port side](D-601_quantum_2_qm9700_infiniband_leaf_switch.svg)

## Who operates what

| Party | Name | Role |
|---|---|---|
| Customer | Customer | Leases the halls; owns the IT equipment and site outcomes; operates the Telemetry of Record. |
| It partner | Ridgeline Site Services, LLC (fictional) | Deployment, break-fix, and data hall IT operations. |
| Landlord | Caprock Critical Facilities, LLC (fictional) | Wholesale data center owner-operator: owns and operates the building, power, cooling, fire protection, and building monitoring; leases the halls to the Customer. |
| Security partner | Llano Gate Protective Services, LLC (fictional) | Armed Level III officers for the whole property: gates and perimeter, the security console, the hall entrance posts, patrols, visitors, and media destruction (sheets A-002 and A-102). |
| Utility | Serving utility (ERCOT region) | Owns the 138 kV substation and its transformers; serves the Landlord. |

## Equipment

| Category | Product | Count | Rating | Management interfaces |
|---|---|---|---|---|
| Compute rack | NVIDIA GB200 NVL72 | 32 | 132 kW | Redfish (BMC); NVLink telemetry via NMX; InfiniBand via UFM |
| Compute rack | NVIDIA GB300 NVL72 | 32 | 132 kW | Redfish (BMC); NVLink telemetry via NMX; InfiniBand via UFM |
| Compute rack | NVIDIA ecosystem (to be selected) 800 VDC rack, Vera Rubin class (planned) | 8 | 230 kW | Redfish (BMC) |
| UPS | Schneider Electric Galaxy VX 1500 kW, 480 V | 8 | 1,500 kW | SNMPv3 (Network Management Card); Modbus TCP; HTTPS |
| UPS | Schneider Electric Galaxy VL 300 kW, 480 V (mechanical UPS) | 4 | 300 kW | SNMPv3 (Network Management Card); Modbus TCP |
| Battery | Schneider Electric Galaxy Lithium-ion Battery System | 12 (one per UPS) |  | Reported through the UPS |
| Busway | Starline (Legrand) Track Busway 1200T5 with Critical Power Monitor | 36 | 1,200 A | Modbus TCP / SNMP via Critical Power Monitor |
| Transformer | 13.8 kV to 480 V unit substation, 2500 kVA (to be selected) | 12 | 2,500 kVA | Metered via PowerLogic into Power Monitoring Expert |
| Transformer | 138 kV to 13.8 kV power transformer, 25 MVA (utility-owned) | 2 | 25,000 kVA | Utility SCADA (not customer accessible); site metering at the 13.8 kV mains |
| Solid-state transformer | Eaton MVSST, 15 kV class, 2.5 MW (pilot) | 2 | 2,500 kW | To be confirmed in pilot submittals |
| Generator | Caterpillar C175-16, 13.8 kV, EMCP 4.4 | 7 | 3,000 kW | Modbus TCP (EMCP 4.4); Modbus RTU; EMCP 4.4 master panel to BMS |
| CDU | CoolIT Systems CHx2000 row-based CDU | 11 | 2,000 kW | Redfish; SNMP; Modbus TCP; BACnet |
| Thermal wall | Vertiv Liebert CWA thermal wall, 400 kW configuration | 8 | 400 kW | BACnet/IP via unit controller |
| CRAH | Vertiv Liebert CW perimeter CRAH, 100 kW (electrical rooms) | 8 | 100 kW | BACnet/IP via unit controller |
| Chiller | Vertiv Liebert AFC air-cooled free-cooling chiller, 1500 kW nominal | 11 | 1,500 kW | BACnet/IP; Modbus |
| Pump | Facility water pump, VFD driven (to be selected) | 3 |  | BACnet/IP via VFD |
| Smoke detection | Xtralis (Honeywell) VESDA-E VEP aspirating smoke detector | 5 |  | VESDAnet to fire panel (primary); Modbus HLI to BMS (secondary) |
| Fire panel | Notifier (Honeywell) Addressable fire alarm control panel | 1 |  | BACnet gateway to BMS (secondary monitoring) |
| Suppression | Double-interlock pre-action sprinkler zone (landlord standard) | 5 |  | Valve tamper, low air, and waterflow switches to the fire panel |
| Suppression | Clean agent total-flooding system (landlord standard) | 3 |  | Release circuit and container pressure switch on the fire panel |
| Leak detection | Chemelex (nVent RAYCHEM TraceTek) TTDM-128 alarm and locator module | 3 |  | Modbus RTU (RS-485) via gateway to Modbus TCP |
| Leak cable | Chemelex (nVent RAYCHEM TraceTek) Water and conductive-fluid sensing cable (PG25 coolant) | 21 circuits |  | Monitored by TTDM-128 |
| Leak cable | Chemelex (nVent RAYCHEM TraceTek) TT5000 hydrocarbon sensing cable (generator diesel) | 7 circuits (one per fuel tank) |  | Monitored by TTDM-128 |
| InfiniBand switch | NVIDIA Quantum-2 QM9700 NDR InfiniBand switch | set in fabric design |  | UFM; SNMP; gNMI |
| InfiniBand switch | NVIDIA Quantum-X800 Q3400-RA XDR InfiniBand switch | set in fabric design |  | UFM; gNMI |
| Management switch | NVIDIA Spectrum SN2201 1G management switch | 128 |  | SNMPv3 (IF-MIB, ENTITY-SENSOR-MIB, traps); Serial console; Cumulus Linux NVUE |
| Management aggregation switch | NVIDIA Spectrum SN5600 (management aggregation) | 4 |  | SNMPv3 (IF-MIB, ENTITY-SENSOR-MIB, traps); Serial console |
| Console server | 48-port serial console server (to be selected) | 8 |  | SNMPv3; SSH to each serial port; Session log export |
| Ethernet switch (storage fabric) | NVIDIA Spectrum SN5600 (storage and in-band Ethernet fabric) | 24 |  | SNMPv3 (IF-MIB, traps); Serial console; Cumulus Linux NVUE |
| Storage node | All-flash NVMe storage node (2U, 24 drive bays, 2 x 400 GbE) (to be selected) | 32 |  | Redfish (Drive, Storage); SNMPv3; Storage cluster REST API |

Busway counts are A and B tracks per row segment. Every count comes from the site model, so a change to `site/site.yaml` updates this table and the drawings together.

## Capacity checks

Every check must pass or the site file will not load, the same way the SLA refuses to load if inconsistent.

| Scope | Check | Load | Capacity | Utilization | Limit | Result | Basis |
|---|---|---|---|---|---|---|---|
| Hall A | UPS, normal (busiest module) | 1,056 kW | 1,500 kW | 70% | 80% | Pass | 4 x 1,500 kW sharing 4,224 kW |
| Hall A | UPS, one module lost (4 make 3) | 1,452 kW | 1,500 kW | 97% | 100% | Pass | lost module's groups shift to their other feed |
| Hall A | Unit substation (worst UPS input) | 1,663 kVA | 2,500 kVA | 67% | 100% | Pass | UPS input at worst case plus battery recharge |
| Hall A | Busway, one feed lost (largest segment) | 962 A | 1,200 A | 80% | 90% | Pass | 6 racks x 132 kW on one 1200 A busway |
| Hall A | Mechanical UPS (2N, one unit carries all) | 129 kW | 300 kW | 43% | 100% | Pass | CDU pumps and thermal-wall fans |
| Hall A | CDU heat, N+1 | 3,675 kW | 6,000 kW | 61% | 100% | Pass | 3 of 4 CDUs carry the liquid load |
| Hall A | CDU flow, N+1 | 4,410 LPM | 5,400 LPM | 82% | 100% | Pass | 1.2 LPM per kW of liquid load |
| Hall A | Thermal walls, N+1 | 549 kW | 1,200 kW | 46% | 100% | Pass | air-side share of rack heat |
| Hall A | Electrical room CRAH, N+1 | 131 kW | 200 kW | 65% | 100% | Pass | power conversion losses |
| Hall B | UPS, normal (busiest module) | 1,056 kW | 1,500 kW | 70% | 80% | Pass | 4 x 1,500 kW sharing 4,224 kW |
| Hall B | UPS, one module lost (4 make 3) | 1,452 kW | 1,500 kW | 97% | 100% | Pass | lost module's groups shift to their other feed |
| Hall B | Unit substation (worst UPS input) | 1,663 kVA | 2,500 kVA | 67% | 100% | Pass | UPS input at worst case plus battery recharge |
| Hall B | Busway, one feed lost (largest segment) | 962 A | 1,200 A | 80% | 90% | Pass | 6 racks x 132 kW on one 1200 A busway |
| Hall B | Mechanical UPS (2N, one unit carries all) | 129 kW | 300 kW | 43% | 100% | Pass | CDU pumps and thermal-wall fans |
| Hall B | CDU heat, N+1 | 3,802 kW | 6,000 kW | 63% | 100% | Pass | 3 of 4 CDUs carry the liquid load |
| Hall B | CDU flow, N+1 | 4,562 LPM | 5,400 LPM | 84% | 100% | Pass | 1.2 LPM per kW of liquid load |
| Hall B | Thermal walls, N+1 | 422 kW | 1,200 kW | 35% | 100% | Pass | air-side share of rack heat |
| Hall B | Electrical room CRAH, N+1 | 131 kW | 200 kW | 65% | 100% | Pass | power conversion losses |
| Hall C (800 VDC pilot) | MVSST (2N, one unit carries all) | 1,868 kW | 2,500 kW | 75% | 100% | Pass | 8 racks x 230 kW |
| Hall C (800 VDC pilot) | CDU heat, N+1 | 1,840 kW | 4,000 kW | 46% | 100% | Pass | 2 of 3 CDUs carry the liquid load |
| Hall C (800 VDC pilot) | CDU flow, N+1 | 2,208 LPM | 3,600 LPM | 61% | 100% | Pass | 1.2 LPM per kW of liquid load |
| Hall C (800 VDC pilot) | Electrical room CRAH, N+1 | 28 kW | 100 kW | 28% | 100% | Pass | power conversion losses |
| Site | Chillers at 43 C, N+1 | 10,912 kW | 11,500 kW | 95% | 100% | Pass | 10 x 1,150 kW derated |
| Site | Generators, N+1 | 15,169 kW | 18,000 kW | 84% | 90% | Pass | 6 x 3,000 kW at design-day peak |
| Site | Utility transformers (2N, one carries all) | 15,968 kVA | 25,000 kVA | 64% | 80% | Pass | design-day peak at 0.95 power factor |

## Dependencies (used for fault attribution)

Each rack's power and cooling paths, upstream to the sources. When a rack goes down, walking these paths shows which system, and therefore which partner, owns the event. Example, rack A07:

- **Power, A feed:** A07 -> BW-A-R1-PG-A2-A -> UPS-A3 -> USS-A3 -> MV-A -> TX-1 -> TX-2 -> GEN paralleling bus
- **Power, B feed:** A07 -> BW-A-R1-PG-A2-B -> UPS-A4 -> USS-A4 -> MV-B -> TX-1 -> TX-2 -> GEN paralleling bus
- **Cooling:** A07 -> Hall A secondary header -> CDU-A1..A4 (N+1) -> Facility water loop -> Chiller plant

## Monitoring map

The Landlord runs EcoStruxure day to day. Under the Interface Agreement, the Customer's Telemetry of Record collector reads critical devices directly and read-only, and also receives the BMS feed, so a point overridden or an alarm inhibited at the BMS shows up as a mismatch.

| System | Role | Operated by |
|---|---|---|
| EcoStruxure Building Operation | BMS: HVAC, chillers, CDUs, thermal walls, fire and leak (secondary) | Caprock Critical Facilities, LLC |
| EcoStruxure Power Monitoring Expert | EPMS: switchgear, metering, power quality | Caprock Critical Facilities, LLC |
| EcoStruxure IT | DCIM: UPS, busway, rack power, capacity | Caprock Critical Facilities, LLC |
| Notifier fire alarm control panel | Fire alarm system of record (life safety) | Caprock Critical Facilities, LLC |
| NVIDIA UFM | InfiniBand fabric management | Ridgeline Site Services, LLC |
| NVIDIA NMX | NVLink domain management (per rack) | Ridgeline Site Services, LLC |
| Management network (out of band and in band) | BMC, switch-tray, and switch management; console servers | Customer |
| Customer Telemetry of Record collector | Independent, read-only aggregation of every source; basis for SLA measurement | Customer |

| Device class | Protocol | Day-to-day system | Customer tap |
|---|---|---|---|
| UPS | SNMPv3 | EcoStruxure IT | direct (SNMPv3 read-only user) |
| Busway | Modbus TCP | EcoStruxure IT | direct (read-only) |
| Switchgear and meters | Modbus TCP | EcoStruxure Power Monitoring Expert | PME export |
| Generators | Modbus TCP (EMCP 4.4) | EcoStruxure Building Operation | direct (read-only) |
| CDUs | Redfish | EcoStruxure Building Operation | direct (Redfish read-only account) |
| Thermal walls and CRAHs | BACnet/IP | EcoStruxure Building Operation | BMS feed |
| Chillers and pumps | BACnet/IP | EcoStruxure Building Operation | BMS feed |
| Leak detection | Modbus TCP (via gateway) | EcoStruxure Building Operation | direct (read-only) |
| Aspirating smoke | Modbus HLI | EcoStruxure Building Operation | BMS feed (fire panel is the system of record) |
| Compute racks | Redfish | Customer Telemetry of Record collector | direct |
| BMCs (compute trays, NVLink switch trays, power shelves) | Redfish service root, polled each minute | Customer Telemetry of Record collector | direct (over the OOB network) |
| Management switches and console servers | SNMPv3 and traps; console session logs | Management network (out of band and in band) | direct (read-only SNMPv3 user) |
| Storage nodes and drives | Redfish Drive resources, polled each minute; the cluster's own event log | Customer Telemetry of Record collector | direct (read-only) |
| Storage and in-band Ethernet fabric | SNMPv3 and traps | Customer Telemetry of Record collector | direct (read-only SNMPv3 user) |
| InfiniBand fabric | UFM REST / events | NVIDIA UFM | UFM event export |

## Engineering assumptions

- Rack design envelope 132 kW for GB200 and GB300 (GB300 power-capped to the hall envelope); 230 kW for the 800 VDC pilot racks.
- Hot-day design dry bulb of 43 C; each 1,500 kW chiller derated to 1,150 kW, plant COP 3.0 on that day.
- UPS double-conversion efficiency 97%; UPS input sized with a 10% battery-recharge allowance; power factor 0.99.
- Busway may carry up to 90% of its rating with one feed lost.
- One facility water loop at 20 C supply / 30 C return serves CDUs, thermal walls, and CRAHs.
- Thermal-wall fan power 20 kW per unit; CRAH fan power 5 kW; facility water pumps 110 kW each.
- Lithium-ion runtime 5 minutes; 48 hours of generator fuel at full load; 400 kW of house load.

## Sources

Product facts in `site/site.yaml` were checked against these manufacturer and trade sources:

- NVIDIA GB200 NVL72: <https://www.szsanyi.com/en/blog/nvidia-hvdc>
- NVIDIA GB200 NVL72: <https://blog.qct.io/wp-content/uploads/2025/04/QCT-Qoolrack-Stand-Alone_Advanced-Liquid-Cooling-for-NVIDIA-GB200-NVL72-Systems.pdf>
- NVIDIA GB300 NVL72: <https://lenovopress.lenovo.com/lp2357.pdf>
- NVIDIA ecosystem (to be selected) 800 VDC rack, Vera Rubin class (planned): <https://www.moduledge.com/blog/nvidia-vera-rubin>
- Schneider Electric Galaxy VX 1500 kW, 480 V: <https://www.merten.de/produkt/gvxp250kd-galaxy-vx-250-kva-400-480-v-pwr-cab.html>
- Schneider Electric Galaxy VX 1500 kW, 480 V: <https://www.se.com/us/en/product/AP9644/network-management-card-4-nmc4-for-galaxy-vs-galaxy-vl-galaxy-vxl-remote-ups-monitoring-and-management/>
- Schneider Electric Galaxy VL 300 kW, 480 V (mechanical UPS): <https://www.merten.de/produkt/gvlopt006-galaxy-vl-vxl-paralleles-kommunikationskit-weltweit.html>
- Schneider Electric Galaxy Lithium-ion Battery System: <https://www.se.com/ie/en/work/products/master-ranges/galaxy/>
- Starline (Legrand) Track Busway 1200T5 with Critical Power Monitor: <https://www.cablinginstall.com/articles/2016/12/starline-1200t5-track-busway-system.html>
- Starline (Legrand) Track Busway 1200T5 with Critical Power Monitor: <https://starlinepower.com/products>
- Eaton MVSST, 15 kV class, 2.5 MW (pilot): <https://www.eaton.com/us/en-us/catalog/medium-voltage-power-distribution-control-systems/medium-voltage-solid-state-transformer.html>
- Caterpillar C175-16, 13.8 kV, EMCP 4.4: <https://pesa.com.br/pesaenergia-specsheets/diesel/DataSheetC175-16-3750kVAStand-by.pdf>
- Caterpillar C175-16, 13.8 kV, EMCP 4.4: <https://www.warrencat.com/new/power-systems/electric-power/switchgear-and-paralleling-controls/emcp-4-4-master-control-panel/>
- CoolIT Systems CHx2000 row-based CDU: <https://www.coolitsystems.com/product/chx2000-cdu/>
- CoolIT Systems CHx2000 row-based CDU: <https://www.coolitsystems.com/cdu-product/chx2000/>
- Vertiv Liebert CWA thermal wall, 400 kW configuration: <https://www.vertiv.com/en-us/products-catalog/thermal-management/room-cooling/liebert-cwa-chilled-water-thermal-wall-unit-from-200-to-500kw/>
- Vertiv Liebert CW perimeter CRAH, 100 kW (electrical rooms): <https://www.intelligentcio.com/north-america/2024/10/17/vertiv-codevelops-with-nvidia-complete-power-and-cooling-blueprint-for-nvidia-gb200-nvl72-platform/>
- Vertiv Liebert AFC air-cooled free-cooling chiller, 1500 kW nominal: <https://www.vertiv.com/49dc08/globalassets/products/thermal-management/free-cooling-chillers/liebert-afc-ds-en-emea-rev0---03.2020.pdf>
- Xtralis (Honeywell) VESDA-E VEP aspirating smoke detector: <https://xtralis.com/file/8501>
- Chemelex (nVent RAYCHEM TraceTek) TTDM-128 alarm and locator module: <https://cdn.chemelex.com/Product%20Documents/Design%20Guides-Forms/RAYCHEM-DG-EU0614-TraceTekOverview-EN.pdf>
- Chemelex (nVent RAYCHEM TraceTek) Water and conductive-fluid sensing cable (PG25 coolant): <https://go.nvent.com/rs/760-EGW-100/images/RaychemTraceTek-AR-H58709-FMClass7745-EN.pdf>
- Chemelex (nVent RAYCHEM TraceTek) TT5000 hydrocarbon sensing cable (generator diesel): <https://go.nvent.com/rs/760-EGW-100/images/RaychemTraceTek-AR-H53147-SensingAppGuide-EN.pdf>
- NVIDIA Quantum-2 QM9700 NDR InfiniBand switch: <https://networking-docs.nvidia.com/cablevalidationtool/2.0.1/installation-notes>
- NVIDIA Quantum-X800 Q3400-RA XDR InfiniBand switch: <https://networking-docs.nvidia.com/cablevalidationtool/2.0.1/installation-notes>
- NVIDIA Spectrum SN2201 1G management switch: <https://docs.nvidia.com/networking/display/sn2201switchesum/introduction>
- NVIDIA Spectrum SN2201 1G management switch: <https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-gb200/latest/network-fabrics.html>
- NVIDIA Spectrum SN5600 (management aggregation): <https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-gb200/latest/network-fabrics.html>
- NVIDIA Spectrum SN5600 (storage and in-band Ethernet fabric): <https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-gb200/latest/network-fabrics.html>
