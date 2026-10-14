# Management network telemetry (Site AUS-1, synthetic)

Synthetic management network telemetry under the published Redfish, IF-MIB, ENTITY-SENSOR-MIB, and SNMPv2 trap names. Window Aug 31, 2026 to Sep 28, 2026: every BMC's Redfish service root polled once a minute by the Telemetry of Record, every management switch and console server read over SNMPv3 once a minute with its traps, and the console servers' session logs. All names and readings are fictional; no vendor's internal tooling is implied.

Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py

The management network is how the Telemetry of Record reaches every BMC and how the IT Partner works on a rack without walking to it. The IT Partner SLA measures its PSU and serial-swap clocks through the BMC, so a span with no answers is a span with no evidence. A gap is not a finding by itself; it becomes one when a record claims something the gap makes impossible.

## Halls

| Hall | Racks | BMC endpoints | Rack switches | Aggregation pair | Console servers | Polls answered |
|---|---:|---:|---:|---|---:|---:|
| Hall A | 32 | 1,120 | 64 | oob-agg-a1, oob-agg-a2 | 4 | 99.888% of 45,152,800 |
| Hall B | 32 | 1,120 | 64 | oob-agg-b1, oob-agg-b2 | 4 | 99.999% of 10,279,930 |

## Racks

| Rack | BMCs | In service from | Polls answered | Failed polls | Gaps over 15 min | Out-of-band switch up h | In-band switch up h |
|---|---:|---|---:|---:|---:|---:|---:|
| A01 | 35 | start of month | 99.995% | 61 | 2 | 672.0 | 672.0 |
| A02 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| A03 | 35 | start of month | 99.991% | 126 | 3 | 672.0 | 672.0 |
| A04 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| A05 | 35 | start of month | 99.997% | 30 | 1 | 672.0 | 672.0 |
| A06 | 35 | start of month | 99.999% | 10 | 0 | 672.0 | 672.0 |
| A07 | 35 | start of month | 99.481% | 7,323 | 36 | 668.5 | 668.5 |
| A08 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| A09 | 35 | start of month | 99.989% | 148 | 2 | 672.0 | 672.0 |
| A10 | 35 | start of month | 99.998% | 26 | 1 | 672.0 | 672.0 |
| A11 | 35 | start of month | 99.999% | 3 | 0 | 672.0 | 672.0 |
| A12 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| A13 | 35 | start of month | 99.997% | 34 | 1 | 672.0 | 672.0 |
| A14 | 35 | start of month | 99.995% | 65 | 2 | 672.0 | 672.0 |
| A15 | 35 | start of month | 99.993% | 87 | 1 | 672.0 | 672.0 |
| A16 | 35 | start of month | 99.999% | 10 | 0 | 672.0 | 672.0 |
| A17 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| A18 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| A19 | 35 | start of month | 99.997% | 33 | 1 | 672.0 | 672.0 |
| A20 | 35 | start of month | 99.997% | 29 | 1 | 672.0 | 672.0 |
| A21 | 35 | start of month | 99.991% | 120 | 1 | 672.0 | 672.0 |
| A22 | 35 | start of month | 99.995% | 59 | 2 | 672.0 | 672.0 |
| A23 | 35 | start of month | 99.995% | 63 | 2 | 672.0 | 672.0 |
| A24 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| A25 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| A26 | 35 | start of month | 99.998% | 22 | 1 | 672.0 | 672.0 |
| A27 | 35 | start of month | 97.029% | 41,920 | 35 | 652.1 | 672.0 |
| A28 | 35 | start of month | 99.999% | 3 | 0 | 672.0 | 672.0 |
| A29 | 35 | start of month | 99.998% | 17 | 1 | 672.0 | 672.0 |
| A30 | 35 | start of month | 99.996% | 45 | 1 | 672.0 | 672.0 |
| A31 | 35 | start of month | 99.995% | 60 | 1 | 672.0 | 672.0 |
| A32 | 35 | start of month | 100.0% | 0 | 0 | 672.0 | 672.0 |
| B01 | 35 | 2026-09-04T20:46:00Z | 100.0% | 0 | 0 | 555.3 | 555.3 |
| B02 | 35 | 2026-09-05T17:08:00Z | 100.0% | 0 | 0 | 534.9 | 534.9 |
| B03 | 35 | 2026-09-06T11:39:00Z | 100.0% | 0 | 0 | 516.4 | 516.4 |
| B04 | 35 | 2026-09-08T17:47:00Z | 100.0% | 0 | 0 | 462.2 | 462.2 |
| B05 | 35 | 2026-09-09T12:28:00Z | 100.0% | 0 | 0 | 443.6 | 443.6 |
| B06 | 35 | 2026-09-11T15:44:00Z | 99.997% | 22 | 0 | 392.3 | 392.3 |
| B07 | 35 | 2026-09-13T01:38:00Z | 99.999% | 6 | 0 | 358.4 | 358.4 |
| B08 | 35 | 2026-09-13T18:50:00Z | 100.0% | 0 | 0 | 341.2 | 341.2 |
| B09 | 35 | 2026-09-15T11:02:00Z | 99.999% | 3 | 0 | 301.0 | 301.0 |
| B10 | 35 | 2026-09-16T18:39:00Z | 100.0% | 0 | 0 | 269.4 | 269.4 |
| B11 | 35 | 2026-09-19T00:28:00Z | 100.0% | 0 | 0 | 215.6 | 215.6 |
| B12 | 35 | 2026-09-19T16:17:00Z | 100.0% | 0 | 0 | 199.8 | 199.8 |
| B13 | 35 | 2026-09-21T00:44:00Z | 100.0% | 0 | 0 | 167.3 | 167.3 |
| B14 | 35 | 2026-09-22T10:12:00Z | 100.0% | 0 | 0 | 133.8 | 133.8 |
| B15 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B16 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B17 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B18 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B19 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B20 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B21 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B22 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B23 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B24 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B25 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B26 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B27 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B28 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B29 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B30 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B31 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |
| B32 | 35 | not this month |  | 0 | 0 | 0.0 | 0.0 |

## Findings

Records that do not reconcile; each is a case to look into, not a claim that anyone misled.

### MP-1: psu_redundancy on A03_PowerShelf_3 passed while its BMC was not answering

A return-to-service check that reads the shelf's redundancy through Redfish is recorded as passing at a time the Telemetry of Record could not reach that shelf's controller. Ask for the check's raw output; until then the validation does not reconcile with the management network.

Owner: IT Partner. Contract: IT Partner SLA: PSU replacement clock stop (BMC reports redundancy restored); validation before return to service.

- psu_redundancy on /redfish/v1/Chassis/A03_PowerShelf_3/PowerSubsystem/PowerSupplies/3: started 2026-09-07T07:54:21Z, passed 2026-09-07T07:59:21Z (health check record)
- A03_PowerShelf_3 answered no Redfish poll from 2026-09-07T07:56:00Z to 2026-09-07T08:57:00Z (61 min), so the check's final read could not have reached it
- INC3100408 closed as 'Hardware replaced' at 2026-09-07T08:04:05Z with validation attached

### MP-2: B05: 3 BMCs first answered 10 h after M4

M4 for B05 was reported complete while 3 of its compute tray BMCs had never answered on the out-of-band network; their ports came up hours later, as when cables are landed after the fact.

Owner: IT Partner. Contract: Deployment step R-M4 (DEP-B-RK-04); IT Partner SLA rack acceptance exit criteria (BMCs reachable on OOB).

- M4 (power-on and firmware baseline) for B05 reported complete at 2026-09-09T21:02:38Z (deployment milestones)
- Its checklist (DEP-B-RK-04) requires POST on every tray and every BMC reachable on the out-of-band network
- b05-ct02 first answered at 2026-09-10T07:05:00Z
- b05-ct07 first answered at 2026-09-10T07:05:00Z
- b05-ct10 first answered at 2026-09-10T07:07:00Z

### MP-3: a27-mgmt1 down 19.9 h with no ticket

Rack A27's out-of-band switch was down for 19.9 h while the rack ran, so none of its 35 BMCs could be read or reached; the IT Partner worked on it from the console, but no ticket records the outage, its cause, or its restoration.

Owner: IT Partner. Contract: Interface Agreement RACI: BMC and out-of-band management network (physical); IT Partner SLA scope (OOB networks).

- a27-mgmt1 dark from 2026-09-14T09:58:00Z to 2026-09-15T05:54:00Z (19.9 h): both aggregation switches lost its uplinks, and it sent coldStart at 2026-09-15T05:53:09Z
- All 35 BMCs in rack A27 stopped answering over the span; the rack stayed powered (no power loss on record)
- No IT Partner ticket on rack A27 opened within 2 h of the span
- IT Partner console session on con-a4 port 5 (a27-mgmt1 login:) from 2026-09-15T05:30:14Z to 2026-09-15T06:02:40Z, 23 minutes before it came back

### MP-4: con-b2 ports 3 and 4 labelled the wrong way round

The console server's port map does not match what is on the line. In an outage, the person on the console would be working on the wrong switch.

Owner: IT Partner. Contract: IT Partner SLA scope: cabling and labeling for back-end, front-end, and OOB networks.

- con-b2 port map: port 3 is labelled b10-mgmt2
- Session 2026-09-16T18:47:48Z to 2026-09-16T18:56:31Z on port 3 printed 'b10-mgmt1 login:'
- con-b2 port map: port 4 is labelled b10-mgmt1
- Session 2026-09-16T19:10:41Z to 2026-09-16T19:28:25Z on port 4 printed 'b10-mgmt2 login:'

## Events

| From | To | Device | What | Records |
|---|---|---|---|---|
| 2026-09-01T08:14:00Z | 2026-09-01T08:41:00Z | a31-ct11 | Out of the rack for 27 min: new serial CTCSZAT677 at its first answer | INC3100068 |
| 2026-09-01T13:49:00Z | 2026-09-01T13:55:00Z | a31-ct11 | Reseated: the tray out of the rack for 6 min, port down and up | INC3100085 |
| 2026-09-02T14:18:00Z | 2026-09-02T14:23:00Z | a20-ct15 | Reseated: the tray out of the rack for 5 min, port down and up | INC3100119 |
| 2026-09-04T01:14:00Z | 2026-09-04T01:44:00Z | a05-ct18 | Out of the rack for 30 min: new serial CTURP0NAVO at its first answer | INC3100187 |
| 2026-09-04T08:11:00Z | 2026-09-04T08:14:00Z | a22-ct07 | Reseated: the tray out of the rack for 3 min, port down and up | INC3100204 |
| 2026-09-04T17:13:00Z | 2026-09-04T17:17:00Z | a06-ct13 | Reseated: the tray out of the rack for 4 min, port down and up | INC3100238 |
| 2026-09-04T20:45:00Z | 2026-09-04T21:20:00Z | a03-ct14 | Out of the rack for 35 min: new serial CTJR4KV5MF at its first answer | INC3100255 |
| 2026-09-04T23:16:00Z | 2026-09-04T23:19:00Z | a28-ct04 | Reseated: the tray out of the rack for 3 min, port down and up | INC3100289 |
| 2026-09-05T00:46:00Z | 2026-09-05T01:03:00Z | a29-ct03 | Out of the rack for 17 min: new serial CTYQHB1QYO at its first answer | INC3100306 |
| 2026-09-06T13:20:00Z | 2026-09-06T13:51:00Z | a09-ct10 | Out of the rack for 31 min: new serial CTE7O3B1KK at its first answer | INC3100357 |
| 2026-09-07T03:11:00Z | 2026-09-07T03:41:00Z | a22-ct07 | Out of the rack for 30 min: new serial CTYL4B1OFK at its first answer | INC3100391 |
| 2026-09-07T07:56:00Z | 2026-09-07T08:57:00Z | A03_PowerShelf_3 | BMC not answering for 61 min, with its port up, while a validation check recorded a pass | INC3100408, MP-1 |
| 2026-09-08T13:33:00Z | 2026-09-08T13:55:00Z | a26-ct16 | Out of the rack for 22 min: new serial CTCSI7BAHY at its first answer | INC3100476 |
| 2026-09-09T21:02:38Z | 2026-09-10T07:07:00Z | B05 | 3 BMCs still unanswered after M4 was reported complete | MP-2 |
| 2026-09-09T22:16:00Z | 2026-09-09T22:28:00Z | a14-ct02 | Out of the rack for 12 min: new serial CTO1QURPRE at its first answer | INC3100510 |
| 2026-09-10T15:52:00Z | 2026-09-10T17:46:00Z | a21-ct09 | BMC not answering for 114 min, with its port up; nothing on record was read through it meanwhile |  |
| 2026-09-10T18:50:00Z | 2026-09-10T18:53:00Z | a15-ct07 | Reseated: the tray out of the rack for 3 min, port down and up | INC3100527 |
| 2026-09-11T17:17:00Z | 2026-09-11T17:30:00Z | a31-ct17 | Out of the rack for 13 min: new serial CT9ZVON3U5 at its first answer | INC3100544 |
| 2026-09-12T08:35:00Z | 2026-09-12T08:38:00Z | a23-ct18 | Reseated: the tray out of the rack for 3 min, port down and up | INC3100595 |
| 2026-09-13T03:34:00Z | 2026-09-13T04:06:00Z | a14-ct07 | Out of the rack for 32 min: new serial CT0UUKF7PD at its first answer | INC3100612 |
| 2026-09-13T08:12:00Z | 2026-09-13T08:26:00Z | a31-ct15 | Out of the rack for 14 min: new serial CTSI2I94FD at its first answer | INC3100646 |
| 2026-09-13T09:00:00Z | 2026-09-13T09:05:00Z | a23-ct04 | Reseated: the tray out of the rack for 5 min, port down and up | INC3100663 |
| 2026-09-14T09:58:00Z | 2026-09-15T05:54:00Z | a27-mgmt1 | Out-of-band switch down 19.9 h: every BMC in rack A27 unreachable while the rack ran | MP-3 |
| 2026-09-15T10:13:00Z | 2026-09-15T10:43:00Z | a07-ct04 | Out of the rack for 30 min: new serial CTB6MJ86MN at its first answer | INC3100748 |
| 2026-09-15T14:07:00Z | 2026-09-15T14:31:00Z | a01-ct05 | Out of the rack for 24 min: new serial CTHRKSC5D5 at its first answer | INC3100765 |
| 2026-09-15T15:43:00Z | 2026-09-15T20:02:00Z | A07 | Rack power lost: all 35 BMCs and both switches dark; switches booted (coldStart) and every BMC answered before the trays returned |  |
| 2026-09-15T20:38:00Z | 2026-09-15T20:43:00Z | a16-ct01 | Reseated: the tray out of the rack for 5 min, port down and up | INC3100782 |
| 2026-09-15T20:49:00Z | 2026-09-15T21:10:00Z | a14-ct14 | Out of the rack for 21 min: new serial CT2C0C43HJ at its first answer | INC3100799 |
| 2026-09-15T22:33:00Z | 2026-09-15T22:38:00Z | a16-ct14 | Reseated: the tray out of the rack for 5 min, port down and up | INC3100816 |
| 2026-09-16T02:04:00Z | 2026-09-16T02:26:00Z | a23-ct04 | Out of the rack for 22 min: new serial CTOWTIOY08 at its first answer | INC3100833 |
| 2026-09-17T11:02:00Z | 2026-09-17T11:29:00Z | A23_PowerShelf_7 | Out of the rack for 27 min: new serial PS2DWQG7M1 at its first answer | INC3100850 |
| 2026-09-17T14:10:00Z | 2026-09-17T14:40:00Z | a03-ct02 | Out of the rack for 30 min: new serial CTYTHUSWR9 at its first answer | INC3100867 |
| 2026-09-18T12:24:00Z | 2026-09-18T13:49:00Z | a19-mgmt1 | Uplink swp50 down 85 min; the other uplink carried the switch, so no BMC was lost |  |
| 2026-09-20T08:58:00Z | 2026-09-20T10:08:00Z | b12-mgmt2 | Uplink swp49 down 70 min; the other uplink carried the switch, so no BMC was lost |  |
| 2026-09-20T17:20:00Z | 2026-09-20T17:32:00Z | a30-ct06 | Out of the rack for 12 min: new serial CTCINKQ6FS at its first answer | INC3100884 |
| 2026-09-21T01:41:00Z | 2026-09-21T01:49:00Z | a13-ct10 | Reseated: the tray out of the rack for 8 min, port down and up | INC3100918 |
| 2026-09-22T01:48:00Z | 2026-09-22T02:14:00Z | a22-ct02 | Out of the rack for 26 min: new serial CTZJW9UV9F at its first answer | INC3100952 |
| 2026-09-22T21:59:00Z | 2026-09-22T22:19:00Z | a10-ct12 | Out of the rack for 20 min: new serial CT0J26BZ88 at its first answer | INC3100986 |
| 2026-09-23T07:26:00Z | 2026-09-23T07:59:00Z | a19-ct15 | Out of the rack for 33 min: new serial CT8R6YFJW4 at its first answer | INC3101020 |
| 2026-09-23T13:14:00Z | 2026-09-23T13:40:00Z | a13-ct01 | Out of the rack for 26 min: new serial CTF6Z2KQFU at its first answer | INC3101054 |
| 2026-09-24T01:36:00Z | 2026-09-24T03:33:00Z | a09-ct14 | BMC not answering for 117 min, with its port up; nothing on record was read through it meanwhile |  |
| 2026-09-24T17:45:00Z | 2026-09-24T18:08:00Z | a01-ct10 | Out of the rack for 23 min: new serial CT0BAICYWL at its first answer | INC3101139 |
| 2026-09-25T01:21:00Z | 2026-09-25T01:54:00Z | a30-ct08 | Out of the rack for 33 min: new serial CT8YSKS5OG at its first answer | INC3101156 |
| 2026-09-25T08:10:00Z | 2026-09-25T09:34:00Z | a15-nvsw3 | Failed switch tray: NMX unreachable and the BMC silent for 84 min until the replacement answered new serial NS82PHK3SG at its first answer | INC3101173 |
| 2026-09-25T23:40:00Z | 2026-09-25T23:54:00Z | a01-ct03 | Out of the rack for 14 min: new serial CTDXTIZBHU at its first answer | INC3101224 |
| 2026-09-26T01:20:00Z | 2026-09-26T01:44:00Z | a20-ct07 | Out of the rack for 24 min: new serial CTK2B6KLTK at its first answer | INC3101241 |
| 2026-09-27T11:55:00Z | 2026-09-27T12:00:00Z | TOR | The Telemetry of Record's poller restarted: no BMC polled for 5 min (its own log); not a BMC failure |  |

## Console sessions

| Opened | Closed | Console port | Labelled | Prompt |
|---|---|---|---|---|
| 2026-09-02T21:57:50Z | 2026-09-02T22:00:33Z | con-a3 port 6 | a19-mgmt2 | `a19-mgmt2 login:` |
| 2026-09-04T21:11:10Z | 2026-09-04T21:45:32Z | con-b1 port 2 | b01-mgmt2 | `b01-mgmt2 login:` |
| 2026-09-04T21:16:19Z | 2026-09-04T21:42:08Z | con-b1 port 1 | b01-mgmt1 | `b01-mgmt1 login:` |
| 2026-09-05T01:23:19Z | 2026-09-05T01:31:28Z | con-a3 port 16 | a24-mgmt2 | `a24-mgmt2 login:` |
| 2026-09-05T17:25:10Z | 2026-09-05T17:56:32Z | con-b1 port 4 | b02-mgmt2 | `b02-mgmt2 login:` |
| 2026-09-05T17:39:27Z | 2026-09-05T17:54:15Z | con-b1 port 3 | b02-mgmt1 | `b02-mgmt1 login:` |
| 2026-09-06T11:46:38Z | 2026-09-06T12:10:13Z | con-b1 port 6 | b03-mgmt2 | `b03-mgmt2 login:` |
| 2026-09-06T11:49:54Z | 2026-09-06T12:09:19Z | con-b1 port 5 | b03-mgmt1 | `b03-mgmt1 login:` |
| 2026-09-07T10:13:59Z | 2026-09-07T10:19:35Z | con-a2 port 12 | a14-mgmt2 | `a14-mgmt2 login:` |
| 2026-09-08T18:05:09Z | 2026-09-08T18:40:25Z | con-b1 port 7 | b04-mgmt1 | `b04-mgmt1 login:` |
| 2026-09-08T18:16:52Z | 2026-09-08T18:48:55Z | con-b1 port 8 | b04-mgmt2 | `b04-mgmt2 login:` |
| 2026-09-09T12:41:56Z | 2026-09-09T13:07:37Z | con-b1 port 10 | b05-mgmt2 | `b05-mgmt2 login:` |
| 2026-09-09T12:45:07Z | 2026-09-09T13:08:53Z | con-b1 port 9 | b05-mgmt1 | `b05-mgmt1 login:` |
| 2026-09-10T18:01:20Z | 2026-09-10T18:04:27Z | con-a2 port 9 | a13-mgmt1 | `a13-mgmt1 login:` |
| 2026-09-10T22:24:01Z | 2026-09-10T22:31:51Z | con-a3 port 14 | a23-mgmt2 | `a23-mgmt2 login:` |
| 2026-09-11T09:19:59Z | 2026-09-11T09:34:46Z | con-a4 port 16 | a32-mgmt2 | `a32-mgmt2 login:` |
| 2026-09-11T16:00:22Z | 2026-09-11T16:24:18Z | con-b1 port 12 | b06-mgmt2 | `b06-mgmt2 login:` |
| 2026-09-11T16:18:45Z | 2026-09-11T16:27:34Z | con-b1 port 11 | b06-mgmt1 | `b06-mgmt1 login:` |
| 2026-09-13T02:03:24Z | 2026-09-13T02:35:44Z | con-b1 port 13 | b07-mgmt1 | `b07-mgmt1 login:` |
| 2026-09-13T02:16:38Z | 2026-09-13T02:46:09Z | con-b1 port 14 | b07-mgmt2 | `b07-mgmt2 login:` |
| 2026-09-13T19:03:43Z | 2026-09-13T19:30:55Z | con-b1 port 16 | b08-mgmt2 | `b08-mgmt2 login:` |
| 2026-09-13T19:10:46Z | 2026-09-13T19:34:06Z | con-b1 port 15 | b08-mgmt1 | `b08-mgmt1 login:` |
| 2026-09-15T05:30:14Z | 2026-09-15T06:02:40Z | con-a4 port 5 | a27-mgmt1 | `a27-mgmt1 login:` |
| 2026-09-15T11:17:04Z | 2026-09-15T11:39:07Z | con-b2 port 2 | b09-mgmt2 | `b09-mgmt2 login:` |
| 2026-09-15T11:40:41Z | 2026-09-15T12:07:11Z | con-b2 port 1 | b09-mgmt1 | `b09-mgmt1 login:` |
| 2026-09-16T18:47:48Z | 2026-09-16T18:56:31Z | con-b2 port 3 | b10-mgmt2 | `b10-mgmt1 login:` |
| 2026-09-16T19:10:41Z | 2026-09-16T19:28:25Z | con-b2 port 4 | b10-mgmt1 | `b10-mgmt2 login:` |
| 2026-09-17T16:38:17Z | 2026-09-17T16:42:56Z | con-a2 port 4 | a10-mgmt2 | `a10-mgmt2 login:` |
| 2026-09-19T00:34:04Z | 2026-09-19T00:44:43Z | con-b2 port 5 | b11-mgmt1 | `b11-mgmt1 login:` |
| 2026-09-19T00:51:46Z | 2026-09-19T01:07:23Z | con-b2 port 6 | b11-mgmt2 | `b11-mgmt2 login:` |
| 2026-09-19T16:43:40Z | 2026-09-19T16:52:26Z | con-b2 port 7 | b12-mgmt1 | `b12-mgmt1 login:` |
| 2026-09-19T16:54:01Z | 2026-09-19T17:03:58Z | con-b2 port 8 | b12-mgmt2 | `b12-mgmt2 login:` |
| 2026-09-20T09:26:36Z | 2026-09-20T09:37:12Z | con-a2 port 10 | a13-mgmt2 | `a13-mgmt2 login:` |
| 2026-09-21T00:47:57Z | 2026-09-21T01:03:31Z | con-b2 port 9 | b13-mgmt1 | `b13-mgmt1 login:` |
| 2026-09-21T00:47:21Z | 2026-09-21T01:02:28Z | con-b2 port 10 | b13-mgmt2 | `b13-mgmt2 login:` |
| 2026-09-22T00:27:41Z | 2026-09-22T00:42:33Z | con-a3 port 11 | a22-mgmt1 | `a22-mgmt1 login:` |
| 2026-09-22T10:26:47Z | 2026-09-22T10:43:34Z | con-b2 port 12 | b14-mgmt2 | `b14-mgmt2 login:` |
| 2026-09-22T10:49:04Z | 2026-09-22T11:20:25Z | con-b2 port 11 | b14-mgmt1 | `b14-mgmt1 login:` |
| 2026-09-22T17:29:45Z | 2026-09-22T17:33:28Z | con-a4 port 14 | a31-mgmt2 | `a31-mgmt2 login:` |

## What is read

| Field | Source | Unit | Meaning |
|---|---|---|---|
| `GET /redfish/v1/` | Redfish (DSP0266) | answered or not | The service root of each BMC, once a minute; an answer within the timeout is a good poll, a timeout or error a failed one |
| `ifOperStatus` | IF-MIB 1.3.6.1.2.1.2.2.1.8 | up(1), down(2) | Each switch port's operational state, polled once a minute |
| `ifName` | IF-MIB 1.3.6.1.2.1.31.1.1.1.1 | text | The port's name as the switch gives it (swp1 to swp52 on Cumulus Linux) |
| `ifHCInOctets, ifHCOutOctets` | IF-MIB 1.3.6.1.2.1.31.1.1.1.6 and .10 | octets (Counter64) | Bytes in and out of each uplink; the page shows the switch's management traffic in kbit/s |
| `sysUpTime` | SNMPv2-MIB 1.3.6.1.2.1.1.3 | hundredths of a second | Time since the switch's agent started; it falls back to zero when the switch reboots |
| `entPhySensorValue` | ENTITY-SENSOR-MIB 1.3.6.1.2.1.99.1.1.1.4 | degrees C (celsius sensor) | The switch's ASIC temperature |
| `linkDown, linkUp` | IF-MIB notifications 1.3.6.1.6.3.1.1.5.3 and .4 | trap | Sent by the switch when a port goes down or comes up, with its ifIndex and ifName |
| `coldStart` | SNMPv2-MIB notification 1.3.6.1.6.3.1.1.5.1 | trap | Sent by the switch when it boots |
| `Console session log` | console server | opened, closed, user, prompt | Who opened which serial port and when, and the login prompt the device printed |

## Agreement with the records

| Check | Agrees |
|---|---:|
| Every Redfish event and inventory change falls in a minute its BMC answered | 104 of 104 |
| Each rack power loss stops its BMCs and switches; they answer again before the trays return | 74 of 74 |
| Each replacement and reseat shows the part out of the rack, with the new serial at its first answer | 68 of 68 |
| Each NMX unreachable drops the switch tray's eth0 and BMC; each healthy finds them up | 4 of 4 |
| No Hall B BMC answers before its rack's leak test or before its switches boot | 980 of 980 |
| The hourly BMC counts equal the poll gap log, the first answers, and the collector log | 43,008 of 43,008 |
| The trap log gives every switch's hourly port and uplink counts and minutes up | 88,704 of 88,704 |
| Every rack-wide BMC loss is its power loss or its out-of-band switch down | 2 of 2 |

## Sources

- NVIDIA DGX SuperPOD GB200 reference architecture: network fabrics (OOB network on SN2201; in-band aggregation on SN5600): https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-gb200/latest/network-fabrics.html (checked 2026-10-14)
- NVIDIA SN2201 1G management switch user manual (48 x 1GBASE-T, 4 x 100 GbE QSFP28, console and management ports, Cumulus Linux): https://docs.nvidia.com/networking/display/sn2201switchesum/introduction (checked 2026-10-14)
- NVIDIA Mission Control: GB200 rack verification checklist (BMC connectivity tested for each compute tray and switch): https://docs.nvidia.com/mission-control/docs/rack-bring-up-install/2.2.0/config-for-provisioning/gb200-rack-verification-checklist.html (checked 2026-10-14)
- DMTF DSP0266 Redfish Specification (the service root /redfish/v1/): https://www.dmtf.org/standards/redfish (checked 2026-10-14)
- RFC 2863, The Interfaces Group MIB (ifOperStatus, ifName, ifHCInOctets, linkDown and linkUp): https://www.rfc-editor.org/rfc/rfc2863 (checked 2026-10-14)
- RFC 3418, Management Information Base for SNMP (sysUpTime, coldStart): https://www.rfc-editor.org/rfc/rfc3418 (checked 2026-10-14)
- RFC 3433, Entity Sensor MIB (entPhySensorValue): https://www.rfc-editor.org/rfc/rfc3433 (checked 2026-10-14)
