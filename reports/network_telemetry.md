# Network telemetry (Site AUS-1, synthetic)

Synthetic network telemetry under the published UFM Telemetry, node_exporter, SNMP, gNMI, and NMX-T names. Window Aug 31, 2026 to Sep 28, 2026: every back-end InfiniBand leaf port read once a minute through the fabric manager's telemetry (UFM Telemetry, Prometheus endpoint), the tray end of each link through node_exporter, each leaf's chassis over SNMP (Quantum-2) or gNMI (Quantum-X800), and each NVL72 rack's NVLink switch trays through NMX-T. All names and readings are fictional; no vendor's internal tooling is implied.

Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py

Each GPU's tray has one link per rail to that rail's leaf (rail-optimized); a link carries traffic only while its tray's GPUs report and the link is up, and every fabric event, ticket, and device-directory connection agrees with the counters.

## Halls

| Hall | Leaf switch | Leaves | Racks | Links cabled (start / end) | Data sent PB | Symbol errors | Link drops | Leaf power avg kW |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Hall A | NVIDIA Quantum-2 QM9700 (400G) | 64 | 32 | 2,304 / 2,304 of 2,304 | 166,122.8 | 71,260 | 109 | 71.9 |
| Hall B | NVIDIA Quantum-X800 Q3400-RA (800G) | 28 | 14 | 0 / 1,008 of 1,008 | 65,976.1 | 0 | 0 | 54.9 |

## Leaf switches

| Leaf | Rail | Racks | Links cabled | Data sent PB | Symbol errors | Link drops | ASIC max °C | Power avg W | Links with records |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| leaf-a01-r0 | 0 | A01, A02 | 36 of 36 | 2,602.1 | 0 | 0 | 67 | 1,122 |  |
| leaf-a01-r1 | 1 | A01, A02 | 36 of 36 | 2,603.1 | 0 | 0 | 64 | 1,123 |  |
| leaf-a01-r2 | 2 | A01, A02 | 36 of 36 | 2,602.1 | 7,056 | 0 | 62 | 1,124 | swp31 |
| leaf-a01-r3 | 3 | A01, A02 | 36 of 36 | 2,602.0 | 0 | 0 | 62 | 1,124 |  |
| leaf-a02-r0 | 0 | A03, A04 | 36 of 36 | 2,474.6 | 0 | 0 | 64 | 1,124 |  |
| leaf-a02-r1 | 1 | A03, A04 | 36 of 36 | 2,474.6 | 0 | 0 | 63 | 1,122 |  |
| leaf-a02-r2 | 2 | A03, A04 | 36 of 36 | 2,475.2 | 0 | 2 | 61 | 1,121 | swp11 |
| leaf-a02-r3 | 3 | A03, A04 | 36 of 36 | 2,475.5 | 0 | 4 | 65 | 1,123 | swp8 |
| leaf-a03-r0 | 0 | A05, A06 | 36 of 36 | 2,612.0 | 0 | 0 | 67 | 1,124 |  |
| leaf-a03-r1 | 1 | A05, A06 | 36 of 36 | 2,612.4 | 0 | 0 | 65 | 1,126 |  |
| leaf-a03-r2 | 2 | A05, A06 | 36 of 36 | 2,613.0 | 0 | 0 | 64 | 1,124 |  |
| leaf-a03-r3 | 3 | A05, A06 | 36 of 36 | 2,612.4 | 0 | 0 | 63 | 1,126 |  |
| leaf-a04-r0 | 0 | A07, A08 | 36 of 36 | 2,624.2 | 0 | 18 | 65 | 1,123 |  |
| leaf-a04-r1 | 1 | A07, A08 | 36 of 36 | 2,623.8 | 0 | 18 | 63 | 1,122 |  |
| leaf-a04-r2 | 2 | A07, A08 | 36 of 36 | 2,622.9 | 0 | 18 | 66 | 1,125 |  |
| leaf-a04-r3 | 3 | A07, A08 | 36 of 36 | 2,623.2 | 0 | 21 | 66 | 1,125 | swp26 |
| leaf-a05-r0 | 0 | A09, A10 | 36 of 36 | 2,596.9 | 0 | 0 | 62 | 1,126 |  |
| leaf-a05-r1 | 1 | A09, A10 | 36 of 36 | 2,598.3 | 0 | 0 | 60 | 1,126 |  |
| leaf-a05-r2 | 2 | A09, A10 | 36 of 36 | 2,598.1 | 0 | 0 | 65 | 1,122 |  |
| leaf-a05-r3 | 3 | A09, A10 | 36 of 36 | 2,599.6 | 5,298 | 0 | 61 | 1,124 | swp28 |
| leaf-a06-r0 | 0 | A11, A12 | 36 of 36 | 2,573.2 | 0 | 0 | 64 | 1,124 |  |
| leaf-a06-r1 | 1 | A11, A12 | 36 of 36 | 2,574.2 | 0 | 0 | 62 | 1,123 |  |
| leaf-a06-r2 | 2 | A11, A12 | 36 of 36 | 2,573.8 | 0 | 0 | 68 | 1,125 |  |
| leaf-a06-r3 | 3 | A11, A12 | 36 of 36 | 2,572.6 | 0 | 0 | 63 | 1,125 |  |
| leaf-a07-r0 | 0 | A13, A14 | 36 of 36 | 2,575.2 | 0 | 0 | 66 | 1,124 |  |
| leaf-a07-r1 | 1 | A13, A14 | 36 of 36 | 2,575.4 | 8,549 | 5 | 62 | 1,123 | swp18, swp34 |
| leaf-a07-r2 | 2 | A13, A14 | 36 of 36 | 2,573.9 | 5,371 | 0 | 61 | 1,123 | swp16 |
| leaf-a07-r3 | 3 | A13, A14 | 36 of 36 | 2,574.0 | 0 | 0 | 66 | 1,122 |  |
| leaf-a08-r0 | 0 | A15, A16 | 36 of 36 | 2,573.8 | 0 | 0 | 65 | 1,125 |  |
| leaf-a08-r1 | 1 | A15, A16 | 36 of 36 | 2,574.2 | 0 | 0 | 65 | 1,125 |  |
| leaf-a08-r2 | 2 | A15, A16 | 36 of 36 | 2,574.2 | 0 | 0 | 63 | 1,121 |  |
| leaf-a08-r3 | 3 | A15, A16 | 36 of 36 | 2,575.2 | 0 | 0 | 64 | 1,125 |  |
| leaf-a09-r0 | 0 | A17, A18 | 36 of 36 | 2,593.5 | 7,881 | 0 | 65 | 1,122 | swp21 |
| leaf-a09-r1 | 1 | A17, A18 | 36 of 36 | 2,592.4 | 0 | 0 | 66 | 1,123 |  |
| leaf-a09-r2 | 2 | A17, A18 | 36 of 36 | 2,593.0 | 8,378 | 0 | 60 | 1,123 | swp17 |
| leaf-a09-r3 | 3 | A17, A18 | 36 of 36 | 2,593.9 | 0 | 0 | 67 | 1,125 |  |
| leaf-a10-r0 | 0 | A19, A20 | 36 of 36 | 2,666.3 | 0 | 2 | 64 | 1,125 | swp21 |
| leaf-a10-r1 | 1 | A19, A20 | 36 of 36 | 2,666.4 | 0 | 0 | 66 | 1,124 |  |
| leaf-a10-r2 | 2 | A19, A20 | 36 of 36 | 2,666.4 | 0 | 0 | 64 | 1,126 |  |
| leaf-a10-r3 | 3 | A19, A20 | 36 of 36 | 2,667.5 | 0 | 0 | 62 | 1,126 |  |
| leaf-a11-r0 | 0 | A21, A22 | 36 of 36 | 2,641.4 | 0 | 0 | 66 | 1,123 |  |
| leaf-a11-r1 | 1 | A21, A22 | 36 of 36 | 2,640.3 | 0 | 0 | 66 | 1,121 |  |
| leaf-a11-r2 | 2 | A21, A22 | 36 of 36 | 2,641.5 | 0 | 0 | 65 | 1,124 |  |
| leaf-a11-r3 | 3 | A21, A22 | 36 of 36 | 2,641.4 | 0 | 4 | 64 | 1,123 | swp2 |
| leaf-a12-r0 | 0 | A23, A24 | 36 of 36 | 2,584.3 | 7,553 | 3 | 63 | 1,124 | swp2, swp7 |
| leaf-a12-r1 | 1 | A23, A24 | 36 of 36 | 2,583.4 | 0 | 0 | 62 | 1,127 |  |
| leaf-a12-r2 | 2 | A23, A24 | 36 of 36 | 2,583.2 | 0 | 0 | 64 | 1,124 |  |
| leaf-a12-r3 | 3 | A23, A24 | 36 of 36 | 2,585.2 | 0 | 0 | 62 | 1,123 |  |
| leaf-a13-r0 | 0 | A25, A26 | 36 of 36 | 2,603.2 | 7,196 | 0 | 64 | 1,124 | swp32 |
| leaf-a13-r1 | 1 | A25, A26 | 36 of 36 | 2,605.0 | 4,081 | 4 | 64 | 1,125 | swp28, swp35 |
| leaf-a13-r2 | 2 | A25, A26 | 36 of 36 | 2,603.5 | 0 | 0 | 64 | 1,124 |  |
| leaf-a13-r3 | 3 | A25, A26 | 36 of 36 | 2,604.5 | 0 | 3 | 61 | 1,124 | swp10 |
| leaf-a14-r0 | 0 | A27, A28 | 36 of 36 | 2,605.0 | 0 | 0 | 63 | 1,123 |  |
| leaf-a14-r1 | 1 | A27, A28 | 36 of 36 | 2,604.6 | 0 | 0 | 63 | 1,123 |  |
| leaf-a14-r2 | 2 | A27, A28 | 36 of 36 | 2,606.4 | 0 | 0 | 63 | 1,123 |  |
| leaf-a14-r3 | 3 | A27, A28 | 36 of 36 | 2,606.2 | 0 | 0 | 66 | 1,125 |  |
| leaf-a15-r0 | 0 | A29, A30 | 36 of 36 | 2,641.9 | 5,458 | 4 | 60 | 1,125 | swp17, swp33 |
| leaf-a15-r1 | 1 | A29, A30 | 36 of 36 | 2,641.7 | 4,439 | 0 | 62 | 1,124 | swp10 |
| leaf-a15-r2 | 2 | A29, A30 | 36 of 36 | 2,642.2 | 0 | 0 | 63 | 1,123 |  |
| leaf-a15-r3 | 3 | A29, A30 | 36 of 36 | 2,642.0 | 0 | 0 | 60 | 1,122 |  |
| leaf-a16-r0 | 0 | A31, A32 | 36 of 36 | 2,560.1 | 0 | 3 | 63 | 1,123 | swp33 |
| leaf-a16-r1 | 1 | A31, A32 | 36 of 36 | 2,560.2 | 0 | 0 | 66 | 1,121 |  |
| leaf-a16-r2 | 2 | A31, A32 | 36 of 36 | 2,560.2 | 0 | 0 | 63 | 1,123 |  |
| leaf-a16-r3 | 3 | A31, A32 | 36 of 36 | 2,560.3 | 0 | 0 | 64 | 1,123 |  |
| leaf-b01-r0 | 0 | B01, B02 | 36 of 36 | 3,689.6 | 0 | 0 | 64 | 2,069 |  |
| leaf-b01-r1 | 1 | B01, B02 | 36 of 36 | 3,691.7 | 0 | 0 | 66 | 2,073 |  |
| leaf-b01-r2 | 2 | B01, B02 | 36 of 36 | 3,692.1 | 0 | 0 | 67 | 2,071 |  |
| leaf-b01-r3 | 3 | B01, B02 | 36 of 36 | 3,690.6 | 0 | 0 | 61 | 2,070 |  |
| leaf-b02-r0 | 0 | B03, B04 | 36 of 36 | 3,516.1 | 0 | 0 | 60 | 2,049 |  |
| leaf-b02-r1 | 1 | B03, B04 | 36 of 36 | 3,518.4 | 0 | 0 | 65 | 2,047 |  |
| leaf-b02-r2 | 2 | B03, B04 | 36 of 36 | 3,514.2 | 0 | 0 | 64 | 2,050 |  |
| leaf-b02-r3 | 3 | B03, B04 | 36 of 36 | 3,516.2 | 0 | 0 | 67 | 2,048 |  |
| leaf-b03-r0 | 0 | B05, B06 | 36 of 36 | 2,857.9 | 0 | 0 | 62 | 2,000 |  |
| leaf-b03-r1 | 1 | B05, B06 | 36 of 36 | 2,857.2 | 0 | 0 | 65 | 1,999 |  |
| leaf-b03-r2 | 2 | B05, B06 | 36 of 36 | 2,857.4 | 0 | 0 | 61 | 1,997 |  |
| leaf-b03-r3 | 3 | B05, B06 | 36 of 36 | 2,856.7 | 0 | 0 | 65 | 2,000 |  |
| leaf-b04-r0 | 0 | B07, B08 | 36 of 36 | 2,473.0 | 0 | 0 | 65 | 1,968 |  |
| leaf-b04-r1 | 1 | B07, B08 | 36 of 36 | 2,472.3 | 0 | 0 | 65 | 1,965 |  |
| leaf-b04-r2 | 2 | B07, B08 | 36 of 36 | 2,472.7 | 0 | 0 | 67 | 1,967 |  |
| leaf-b04-r3 | 3 | B07, B08 | 36 of 36 | 2,473.4 | 0 | 0 | 62 | 1,965 |  |
| leaf-b05-r0 | 0 | B09, B10 | 36 of 36 | 1,791.8 | 0 | 0 | 65 | 1,923 |  |
| leaf-b05-r1 | 1 | B09, B10 | 36 of 36 | 1,791.5 | 0 | 0 | 66 | 1,921 |  |
| leaf-b05-r2 | 2 | B09, B10 | 36 of 36 | 1,792.0 | 0 | 0 | 64 | 1,922 |  |
| leaf-b05-r3 | 3 | B09, B10 | 36 of 36 | 1,791.6 | 0 | 0 | 65 | 1,922 |  |
| leaf-b06-r0 | 0 | B11, B12 | 36 of 36 | 1,315.7 | 0 | 0 | 63 | 1,881 |  |
| leaf-b06-r1 | 1 | B11, B12 | 36 of 36 | 1,315.0 | 0 | 0 | 61 | 1,883 |  |
| leaf-b06-r2 | 2 | B11, B12 | 36 of 36 | 1,314.9 | 0 | 0 | 68 | 1,881 |  |
| leaf-b06-r3 | 3 | B11, B12 | 36 of 36 | 1,315.3 | 0 | 0 | 62 | 1,882 |  |
| leaf-b07-r0 | 0 | B13, B14 | 36 of 36 | 849.6 | 0 | 0 | 67 | 1,848 |  |
| leaf-b07-r1 | 1 | B13, B14 | 36 of 36 | 850.0 | 0 | 0 | 62 | 1,847 |  |
| leaf-b07-r2 | 2 | B13, B14 | 36 of 36 | 849.2 | 0 | 0 | 60 | 1,847 |  |
| leaf-b07-r3 | 3 | B13, B14 | 36 of 36 | 850.0 | 0 | 0 | 63 | 1,848 |  |

## NVLink switch trays (per rack)

| Rack | Trays | Data sent PB | Tray-minutes reporting | ASIC max °C |
|---|---:|---:|---:|---:|
| A01 | 9 | 50,854.4 | 362,880 | 50 |
| A02 | 9 | 50,869.7 | 362,880 | 49 |
| A03 | 9 | 50,117.5 | 362,880 | 50 |
| A04 | 9 | 46,617.4 | 362,880 | 49 |
| A05 | 9 | 50,818.9 | 362,880 | 50 |
| A06 | 9 | 51,296.1 | 362,880 | 49 |
| A07 | 9 | 51,619.1 | 360,999 | 50 |
| A08 | 9 | 50,944.4 | 362,880 | 50 |
| A09 | 9 | 51,241.0 | 362,880 | 50 |
| A10 | 9 | 50,346.5 | 362,880 | 50 |
| A11 | 9 | 50,360.1 | 362,880 | 50 |
| A12 | 9 | 50,224.6 | 362,880 | 50 |
| A13 | 9 | 50,919.1 | 362,880 | 49 |
| A14 | 9 | 49,697.6 | 362,880 | 49 |
| A15 | 9 | 49,832.1 | 362,729 | 49 |
| A16 | 9 | 50,786.8 | 362,880 | 50 |
| A17 | 9 | 50,259.9 | 362,880 | 50 |
| A18 | 9 | 51,111.4 | 362,880 | 49 |
| A19 | 9 | 51,405.3 | 362,880 | 50 |
| A20 | 9 | 52,806.5 | 362,880 | 50 |
| A21 | 9 | 52,228.2 | 362,880 | 50 |
| A22 | 9 | 51,002.3 | 362,880 | 50 |
| A23 | 9 | 50,852.6 | 362,880 | 50 |
| A24 | 9 | 50,148.7 | 362,880 | 50 |
| A25 | 9 | 51,642.9 | 362,880 | 49 |
| A26 | 9 | 50,133.3 | 362,880 | 50 |
| A27 | 9 | 50,166.5 | 362,880 | 50 |
| A28 | 9 | 51,674.2 | 362,880 | 50 |
| A29 | 9 | 51,377.1 | 362,880 | 50 |
| A30 | 9 | 51,901.0 | 362,880 | 50 |
| A31 | 9 | 49,041.9 | 362,880 | 50 |
| A32 | 9 | 51,034.6 | 362,880 | 50 |
| B01 | 9 | 40,109.4 | 297,288 | 50 |
| B02 | 9 | 38,376.1 | 286,848 | 50 |
| B03 | 9 | 38,412.4 | 273,564 | 50 |
| B04 | 9 | 33,580.1 | 244,287 | 50 |
| B05 | 9 | 32,410.2 | 234,873 | 49 |
| B06 | 9 | 29,165.9 | 207,252 | 48 |
| B07 | 9 | 26,165.7 | 189,099 | 50 |
| B08 | 9 | 25,341.5 | 182,313 | 49 |
| B09 | 9 | 20,498.7 | 158,292 | 50 |
| B10 | 9 | 19,462.4 | 143,217 | 50 |
| B11 | 9 | 14,915.3 | 111,798 | 50 |
| B12 | 9 | 13,911.6 | 103,203 | 50 |
| B13 | 9 | 11,038.0 | 85,581 | 50 |
| B14 | 9 | 8,976.8 | 68,526 | 50 |

## Events

| From | To | Where | What | Records |
|---|---|---|---|---|
| 2026-08-31T14:14:07Z | 2026-08-31T22:36:37Z | leaf-a12-r0:swp7 | 5 symbol-error reports, 7,553 errors (over the UFM threshold 1 time); host end replaced (INC3100034), errors stopped | INC3100034 |
| 2026-09-03T08:19:46Z | 2026-09-03T23:09:50Z | leaf-a07-r2:swp16 | 5 symbol-error reports, 5,371 errors (over the UFM threshold 1 time); host end replaced (INC3100153), errors stopped | INC3100153 |
| 2026-09-03T12:04:38Z | 2026-09-03T23:51:40Z | leaf-a07-r1:swp18 | Link dropped 3 times; 10 symbol-error reports, 8,549 errors (over the UFM threshold 1 time); switch end replaced (INC3100136), errors continued; host end replaced (INC3100170), errors stopped | INC3100136, INC3100170, F-002, F-011 |
| 2026-09-04T15:22:55Z | 2026-09-05T00:29:59Z | leaf-a15-r0:swp33 | 5 symbol-error reports, 5,458 errors (over the UFM threshold 1 time); host end replaced (INC3100272), errors stopped | INC3100272 |
| 2026-09-05T02:33:54Z | 2026-09-06T20:17:53Z | B01 | Rack B01 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-10 |
| 2026-09-05T21:09:22Z | 2026-09-06T04:01:02Z | leaf-a15-r1:swp10 | 5 symbol-error reports, 4,439 errors (over the UFM threshold 1 time); host end replaced (INC3100340), errors stopped | INC3100340 |
| 2026-09-05T21:40:11Z | 2026-09-11T07:59:44Z | B02 | Rack B02 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-18 |
| 2026-09-06T22:59:41Z | 2026-09-08T19:00:14Z | B03 | Rack B03 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-26 |
| 2026-09-07T12:17:22Z | 2026-09-07T13:12:36Z | leaf-a04-r3:swp26 | Link dropped 3 times; cleaned, no part replaced (INC3100425), errors stopped | INC3100425 |
| 2026-09-08T03:04:06Z | 2026-09-08T03:31:58Z | leaf-a16-r0:swp33 | Link dropped 3 times; cleaned, no part replaced (INC3100442), errors stopped | INC3100442 |
| 2026-09-08T06:46:41Z | 2026-09-08T08:05:15Z | leaf-a07-r1:swp34 | Link dropped 2 times; cleaned, no part replaced (INC3100459), errors stopped | INC3100459 |
| 2026-09-08T15:20:32Z | 2026-09-08T15:58:03Z | leaf-a02-r2:swp11 | Link dropped 2 times; cleaned, no part replaced (INC3100493), errors stopped | INC3100493 |
| 2026-09-09T05:12:54Z | 2026-09-10T23:32:33Z | B04 | Rack B04 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-34 |
| 2026-09-09T23:38:30Z | 2026-09-12T05:44:37Z | B05 | Rack B05 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-42 |
| 2026-09-11T16:17:59Z | 2026-09-11T17:15:38Z | leaf-a13-r3:swp10 | Link dropped 3 times; switch end replaced (INC3100561), errors stopped | INC3100561 |
| 2026-09-11T22:03:51Z | 2026-09-11T22:46:49Z | leaf-a11-r3:swp2 | Link dropped 4 times; switch end replaced (INC3100578), errors stopped | INC3100578 |
| 2026-09-12T01:54:20Z | 2026-09-16T04:09:04Z | B06 | Rack B06 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-50 |
| 2026-09-13T10:26:04Z | 2026-09-14T18:21:20Z | B07 | Rack B07 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-58 |
| 2026-09-13T10:44:21Z | 2026-09-13T11:20:13Z | leaf-a02-r3:swp8 | Link dropped 4 times; cleaned, no part replaced (INC3100680), errors stopped | INC3100680 |
| 2026-09-14T00:07:10Z | 2026-09-16T03:44:37Z | B08 | Rack B08 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-66 |
| 2026-09-14T02:15:12Z | 2026-09-14T02:48:58Z | leaf-a10-r0:swp21 | Link dropped 2 times; host end replaced (INC3100697), errors stopped | INC3100697 |
| 2026-09-14T18:30:00Z | 2026-09-14T19:05:21Z | leaf-a13-r1:swp35 | Link dropped 4 times; switch end replaced (INC3100731), errors stopped | INC3100731 |
| 2026-09-15T15:42:12Z | 2026-09-15T19:19:02Z | A07 | Rack A07 lost input power: its 72 back-end links went down within 2 s (the trays' NICs lost power, so the fabric logged Link is Down on every port), and came back as the trays booted after power returned | INC3900001, WO-41023 |
| 2026-09-15T19:29:17Z | 2026-09-17T22:52:52Z | B09 | Rack B09 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-74 |
| 2026-09-17T00:50:48Z | 2026-09-20T08:37:44Z | B10 | Rack B10 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-82 |
| 2026-09-19T10:05:45Z | 2026-09-20T17:14:42Z | B11 | Rack B11 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-90 |
| 2026-09-20T01:33:07Z | 2026-09-22T04:27:56Z | B12 | Rack B12 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-98 |
| 2026-09-21T09:55:31Z | 2026-09-22T21:21:26Z | B13 | Rack B13 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-106 |
| 2026-09-22T17:41:28Z | 2026-09-24T23:57:10Z | B14 | Rack B14 cabled: 72 back-end links came up one tray at a time (Link is Up, 4 rails per tray) | RSS-DEP-114 |
| 2026-09-22T21:52:52Z | 2026-09-23T10:59:27Z | leaf-a09-r2:swp17 | 5 symbol-error reports, 8,378 errors (over the UFM threshold 1 time); host end replaced (INC3101003), errors stopped | INC3101003 |
| 2026-09-23T02:06:02Z | 2026-09-23T11:23:42Z | leaf-a05-r3:swp28 | 5 symbol-error reports, 5,298 errors (over the UFM threshold 1 time); host end replaced (INC3101037), errors stopped | INC3101037 |
| 2026-09-23T17:05:32Z | 2026-09-24T05:22:07Z | leaf-a13-r0:swp32 | 5 symbol-error reports, 7,196 errors (over the UFM threshold 1 time); switch end replaced (INC3101071), errors stopped | INC3101071 |
| 2026-09-23T22:47:24Z | 2026-09-24T07:53:15Z | leaf-a09-r0:swp21 | 5 symbol-error reports, 7,881 errors (over the UFM threshold 1 time); host end replaced (INC3101105), errors stopped | INC3101105 |
| 2026-09-24T04:20:02Z | 2026-09-24T05:16:31Z | leaf-a12-r0:swp2 | Link dropped 3 times; switch end replaced (INC3101088), errors stopped | INC3101088 |
| 2026-09-24T05:37:14Z | 2026-09-24T14:23:27Z | leaf-a01-r2:swp31 | 5 symbol-error reports, 7,056 errors (over the UFM threshold 1 time); host end replaced (INC3101122), errors stopped | INC3101122 |
| 2026-09-25T08:09:50Z | 2026-09-25T10:40:26Z | a15-nvsw3 | NVLink switch tray unreachable for 151 min (NMX: domain degraded); the rack's other trays carried its share | INC3101173 |
| 2026-09-25T10:19:54Z | 2026-09-25T19:09:52Z | leaf-a13-r1:swp28 | 5 symbol-error reports, 4,081 errors (over the UFM threshold 1 time); host end replaced (INC3101190), errors stopped | INC3101190 |
| 2026-09-26T04:13:31Z | 2026-09-26T04:57:26Z | leaf-a15-r0:swp17 | Link dropped 4 times; cleaned, no part replaced (INC3101258), errors stopped | INC3101258 |

## Agreement with the records

| Check | Agrees |
|---|---:|
| Every symbol-error count the fabric manager reported equals the port counter's rise over that report | 4,463 of 4,463 |
| Each link is down exactly between its recorded link-down and link-up, and LinkDownedCounter rises once per drop | 6,698 of 6,698 |
| Every link's far end is the tray and NIC the device directory and the fabric events name | 5,700 of 5,700 |
| A link moves data only while its tray's GPUs report and the link is up; a busy tray's links all move data | 6,624 of 6,624 |
| Each Hall B rack cabled this month has its 72 links, up from its recorded Link is Up, with no symbol errors | 3,056 of 3,056 |
| Each optic replacement on record follows a failing optic's signature, and clears it only if it ended the errors | 57 of 57 |
| Each leaf's uplinks carry their share of its downlink traffic, every hour | 184 of 184 |
| Each NVLink switch tray reports while its rack's GPUs report, except exactly while the NMX records it failed | 419 of 419 |
| Module temperature, receive power, and switch temperature stay inside the published ranges | 6,716 of 6,716 |

## Sources

- rdma-core libibmad fields.c: IBTA PortCounters and PortCountersExtended field names (perfquery): https://github.com/linux-rdma/rdma-core/blob/master/libibmad/fields.c (checked 2026-10-10)
- Linux kernel ABI, sysfs-class-infiniband (port_xmit_data and port_rcv_data are octets divided by 4): https://www.kernel.org/doc/Documentation/ABI/stable/sysfs-class-infiniband (checked 2026-10-10)
- NVIDIA UFM Enterprise: high-frequency (primary) telemetry fields: https://networking-docs.nvidia.com/ufmenterprisearum/6193/high-frequency-primary-telemetry-fields (checked 2026-10-10)
- NVIDIA UFM Enterprise: low-frequency (secondary) telemetry fields: https://networking-docs.nvidia.com/ufmenterpriseum/6242/low-frequency-secondary-telemetry-fields (checked 2026-10-10)
- NVIDIA UFM Telemetry: Prometheus endpoint (/metrics; labels node_guid, port_guid, port_num): https://networking-docs.nvidia.com/ufmtelemetryum/1212/prometheus-endpoint-support (checked 2026-10-10)
- NVIDIA UFM Enterprise: threshold-crossing events reference (event IDs and default thresholds): https://networking-docs.nvidia.com/ufmenterpriseum/62311/threshold-crossing-events-reference (checked 2026-10-10)
- NVIDIA MFT: mlxlink utility (Module Info block and the module's own threshold ranges): https://networking-docs.nvidia.com/mftswum/4350/mlxlink-utility (checked 2026-10-10)
- NVIDIA QM9700/QM9790 hardware manual: specifications (32 OSFP cages, 64 NDR ports, 747 W typical): https://networking-docs.nvidia.com/qm97x0hw/specifications (checked 2026-10-10)
- NVIDIA MLNX-OS 3.12.6200: InfiniBand interface (port names ib 1/<cage>/<port>): https://docs.nvidia.com/networking/display/nvidiamlnxosusermanualv3126200lts/infiniband-interface (checked 2026-10-10)
- NVIDIA MLNX-OS 3.12.6200: network management interfaces (ENTITY-MIB, ENTITY-SENSOR-MIB supported): https://docs.nvidia.com/networking/display/nvidiamlnxosusermanualv3126200lts/network-management-interfaces (checked 2026-10-10)
- NVIDIA XDR switches hardware manual: Q3400-RA (144 XDR ports on 72 OSFP cages, air-cooled, 8 PSUs, 10 fans): https://networking-docs.nvidia.com/xdrswitcheshw/introduction (checked 2026-10-10)
- NVIDIA NVOS for InfiniBand: gNMI streaming (port 9339, openconfig-platform, interfaces named sw<cage>p<port>): https://networking-docs.nvidia.com/nvosinfinibandum/25.02.8008/gnmi-streaming (checked 2026-10-10)
- Prometheus node_exporter InfiniBand collector (node_infiniband_* metric names): https://github.com/prometheus/node_exporter/blob/master/collector/infiniband_linux.go (checked 2026-10-10)
- NVIDIA NMX-Telemetry: collected data (full metric list not public): https://networking-docs.nvidia.com/nmxtswum/123/collected-data (checked 2026-10-10)
- NVIDIA NetQ 5.3: NVLink monitoring with Prometheus (published NMX-T metric names): https://docs.nvidia.com/networking-ethernet-software/cumulus-netq-53/NVLink-Management/Monitor-with-Prometheus/ (checked 2026-10-10)
- CMIS optical monitors (module temperature, per-lane Tx and Rx power) as encoded in SONiC's public CMIS memory map: https://github.com/sonic-net/sonic-platform-common/tree/master/sonic_platform_base/sonic_xcvr/mem_maps/public/cmis/pages (checked 2026-10-10)
