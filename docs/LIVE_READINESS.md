# Live Readiness

What it would take to run this project against real equipment at a partner-operated site, what is already built and tested, and what is deliberately not claimed.

## Architecture

```
devices (read-only) ──► collector (scripts/collect.py) ──► dataset folder ──► engines, scorecards, reports, app
                          src/scorecard/live/                (docs/DATA_MODEL.md)   (unchanged)
```

The dataset contract in `docs/DATA_MODEL.md` has two producers: the synthetic generator and the live collector. Everything downstream reads the contract, so nothing downstream changes when the source does.

## Built and tested (against in-process simulators, in CI)

| Protocol | Equipment | Reads | Simulator in the tests |
|---|---|---|---|
| Redfish (HTTPS GET) | CDUs (DMTF `ThermalEquipment/CDUs`) | Pump health and state, `PumpRedundancy`, secondary connector temperature, flow, pressure | Local HTTP server with basic authentication |
| Modbus TCP (function codes 3, 4) | Generator controllers, busway monitors, leak controllers | Engine state, kW; voltage and tap-off breakers; leak alarm and distance | pymodbus `SimDevice`, whose hook logs every function code |
| SNMPv3 authPriv (GET) | UPS network management cards | PowerNet MIB `upsBasicOutputStatus` | pysnmp agent with a read-only USM user and a custom MIB controller that logs every operation |
| BACnet/IP (ReadProperty) | BMS points | Present value, priority array (overrides in manual slots), out-of-service | bacpypes3 device with a commandable object |

Library versions were checked on PyPI in October 2026 and are pinned in `requirements-live.txt`.

## Safety properties, and how each is proven

| Property | How it is enforced | How it is tested |
|---|---|---|
| Read-only | Adapters contain only read operations | A static scan fails on any write-capable call in `src/scorecard/live/`; a self-test proves the scan fires; every simulator logs requests and the tests assert only reads arrived; the Modbus reader refuses coil tables |
| No cleartext credentials in the repository | Config names environment variables; inline secrets are rejected | Config tests |
| No cleartext SNMP | SNMPv1 and v2c are rejected; SNMPv3 requires authentication and AES privacy | Config test; wrong-key test |
| One device cannot stop the others | Per-device error handling, backoff, and feed-health records | Tests with an unreachable Modbus device and a failing BACnet point |
| A silent device is visible | Every poll writes `collector/feed_health.jsonl` | Feed-health assertions in every adapter test |

## Findings from building it (worth knowing before a deployment)

1. **pymodbus 3.15** deprecates its old server context classes ahead of v4; the simulator uses the new `SimDevice` API.
2. **pysnmp 7.1.30** imports AES-CFB from `cryptography.hazmat.decrepit`, which cryptography 46 does not have: without `cryptography>=47`, SNMPv3 privacy silently fails ("Ciphering services not available").
3. **bacpypes3** raises BACnet errors as `ErrorRejectAbortNack`, a `BaseException`, not an `Exception`. Unconverted, one bad BMS point would crash a collector whose guards catch `Exception`. The adapter converts it at the boundary, and a test proves containment.
4. **BACnet/IP is UDP**, so reads retry a bounded number of times, as the standard's APDU retries do. Without retries, the tests timed out about one run in three.
5. **A device cannot say whether an override was authorized.** Live overrides carry an unknown change reference; the Landlord engine reconciles them against approved MOPs covering that device and time.

## Not claimed: what a real deployment still needs

- **Security review** of the collector host, its dependencies, and its network access, by the Customer's security team.
- **A segmented, read-only monitoring network:** the collector reaches only the listed device interfaces, approved by the Landlord, with no route to control networks. Read-only accounts on every device (Redfish role without write privileges, SNMPv3 user with no write view, BMS integration with read-only permission).
- **Point-map verification:** every Modbus register, BACnet object, and optional OID in the config is a placeholder until verified against the vendor's documentation and on the device. Register maps differ by vendor, firmware, and gateway.
- **Site acceptance testing:** induce known conditions with the Landlord (a planned UPS bypass, a generator test, a leak cable test) and confirm each appears correctly in the dataset and the reports.
- **Time synchronization:** NTP on the collector; device clocks checked against it (the common terms flag skew over 5 seconds).
- **Operations:** service supervision, log retention, alerting on feed gaps, and credential rotation.
- **Not built here:** IT-side live feeds (GPU telemetry, the InfiniBand fabric manager, the scheduler, the ticketing system, badge export) and the Landlord's work order and maintenance exports. They use separate APIs; the Redfish adapter already covers rack management controllers' resources in the same way.
- **Ticket and work order feeds for the Incident Portal:** the portal (`/tickets/`) reads the sample's records. Live, it needs a small server, because a static page cannot hold credentials: it polls each partner's records API with the read-only account the Records access term requires (RA-1), for example a ServiceNow-style table API for incidents and a Maximo-style REST API for work orders, at least every 15 minutes (RA-4), keeps its own copy with the field audit log (RA-3), and serves the page. It never writes to a partner's system.
