# Storage and storage fabric telemetry (Site AUS-1, synthetic)

Synthetic storage and fabric telemetry under the published Redfish Drive and IF-MIB names. Window Aug 31, 2026 to Sep 28, 2026: every storage node's drive bays read over Redfish once a minute, every switch of the storage and in-band Ethernet fabric read over SNMPv3 with its traps, the clients' I/O stalls from the Customer's job telemetry, and the IT Partner's drive and optic tickets with the custody log. All names and readings are fictional; no vendor's storage product or internal tooling is implied.

Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py

A storage fault idles GPUs that are healthy: the scheduler keeps the nodes in service while their jobs wait on I/O, so neither the scheduler's availability nor CSL-01 counts the time. This report measures it from the clients' side and names the owner.

## Clusters

| Cluster | Hall | Nodes | Drives | Raw capacity | Used at month end | Reads, average | Lowest protection | Hours below full protection | GPU-hours idle on storage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PFS-A | Hall A | 16 | 384 | 11,796 TB | 7,245 TB | 69.2 GB/s | 1 of 2 | 72 | 164.1 |
| PFS-B | Hall B | 16 | 384 | 11,796 TB | 7,047 TB | 10.9 GB/s | 1 of 2 | 9 | 107.5 |

## Client stalls

Flapping uplinks and the running jobs that waited on storage behind them.

| From | Minutes | Uplink | Downs | Racks | Nodes | GPU-hours idle | Records |
|---|---:|---|---:|---|---:|---:|---|
| 2026-09-19T00:55:00Z | 22 | eth-b1-1 swp64 | 10 | B02, B03, B05, B08 | 72 | 107.5 | INC3500010 |
| 2026-09-20T18:35:00Z | 34 | eth-a3-2 swp61 | 14 | A21, A22, A23, A24 | 72 | 164.1 | INC3500011 |

## Storage nodes

| Node | Cluster | Rack | Online h | Drives OK at end | Failed | Missing | Rebuilding | Swaps | Used TB |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| stg-a1-n01 | PFS-A | STG-A1 | 672.0 | 24 | 0 | 0 | 0 | 1 | 423.8 |
| stg-a1-n02 | PFS-A | STG-A1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 468.8 |
| stg-a1-n03 | PFS-A | STG-A1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 460.0 |
| stg-a1-n04 | PFS-A | STG-A1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 496.3 |
| stg-a1-n05 | PFS-A | STG-A1 | 672.0 | 24 | 0 | 0 | 0 | 1 | 436.0 |
| stg-a1-n06 | PFS-A | STG-A1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 421.8 |
| stg-a1-n07 | PFS-A | STG-A1 | 672.0 | 24 | 0 | 0 | 0 | 1 | 428.0 |
| stg-a1-n08 | PFS-A | STG-A1 | 671.8 | 24 | 0 | 0 | 0 | 1 | 460.1 |
| stg-a2-n01 | PFS-A | STG-A2 | 672.0 | 24 | 0 | 0 | 0 | 1 | 484.6 |
| stg-a2-n02 | PFS-A | STG-A2 | 671.8 | 24 | 0 | 0 | 0 | 0 | 441.1 |
| stg-a2-n03 | PFS-A | STG-A2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 492.7 |
| stg-a2-n04 | PFS-A | STG-A2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 428.0 |
| stg-a2-n05 | PFS-A | STG-A2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 441.7 |
| stg-a2-n06 | PFS-A | STG-A2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 502.1 |
| stg-a2-n07 | PFS-A | STG-A2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 401.7 |
| stg-a2-n08 | PFS-A | STG-A2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 458.2 |
| stg-b1-n01 | PFS-B | STG-B1 | 672.0 | 24 | 0 | 0 | 0 | 1 | 416.5 |
| stg-b1-n02 | PFS-B | STG-B1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 477.5 |
| stg-b1-n03 | PFS-B | STG-B1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 436.7 |
| stg-b1-n04 | PFS-B | STG-B1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 402.1 |
| stg-b1-n05 | PFS-B | STG-B1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 487.0 |
| stg-b1-n06 | PFS-B | STG-B1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 457.7 |
| stg-b1-n07 | PFS-B | STG-B1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 436.2 |
| stg-b1-n08 | PFS-B | STG-B1 | 672.0 | 24 | 0 | 0 | 0 | 0 | 485.7 |
| stg-b2-n01 | PFS-B | STG-B2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 481.8 |
| stg-b2-n02 | PFS-B | STG-B2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 404.9 |
| stg-b2-n03 | PFS-B | STG-B2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 401.4 |
| stg-b2-n04 | PFS-B | STG-B2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 391.6 |
| stg-b2-n05 | PFS-B | STG-B2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 503.4 |
| stg-b2-n06 | PFS-B | STG-B2 | 671.7 | 24 | 0 | 0 | 0 | 0 | 429.0 |
| stg-b2-n07 | PFS-B | STG-B2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 430.7 |
| stg-b2-n08 | PFS-B | STG-B2 | 672.0 | 24 | 0 | 0 | 0 | 0 | 404.8 |

## Fabric switches

| Switch | Role | Hall | Ports (trays, nodes, uplinks, downlinks) | Uplinks up (h) | linkDown traps | Input errors |
|---|---|---|---|---|---:|---:|
| eth-a-sp1 | Spine | Hall A | 0, 0, 0, 20 |  | 14 | 0 |
| eth-a-sp2 | Spine | Hall A | 0, 0, 0, 20 |  | 0 | 0 |
| eth-a-st1 | Storage leaf | Hall A | 0, 16, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 2 | 0 |
| eth-a-st2 | Storage leaf | Hall A | 0, 16, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 2 | 0 |
| eth-a1-1 | Row leaf | Hall A | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 27 | 0 |
| eth-a1-2 | Row leaf | Hall A | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 27 | 0 |
| eth-a2-1 | Row leaf | Hall A | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 10 | 0 |
| eth-a2-2 | Row leaf | Hall A | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 11 | 0 |
| eth-a3-1 | Row leaf | Hall A | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 11 | 0 |
| eth-a3-2 | Row leaf | Hall A | 144, 0, 4, 0 | swp61 671.8, swp62 672.0, swp63 672.0, swp64 672.0 | 25 | 242,092 |
| eth-a4-1 | Row leaf | Hall A | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 9 | 0 |
| eth-a4-2 | Row leaf | Hall A | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 10 | 0 |
| eth-b-sp1 | Spine | Hall B | 0, 0, 0, 20 |  | 2 | 0 |
| eth-b-sp2 | Spine | Hall B | 0, 0, 0, 20 |  | 11 | 0 |
| eth-b-st1 | Storage leaf | Hall B | 0, 16, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 2 | 0 |
| eth-b-st2 | Storage leaf | Hall B | 0, 16, 4, 0 | swp61 671.4, swp62 672.0, swp63 672.0, swp64 672.0 | 2 | 0 |
| eth-b1-1 | Row leaf | Hall B | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 671.8 | 10 | 127,019 |
| eth-b1-2 | Row leaf | Hall B | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 0 | 0 |
| eth-b2-1 | Row leaf | Hall B | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 670.5 | 1 | 0 |
| eth-b2-2 | Row leaf | Hall B | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 0 | 0 |
| eth-b3-1 | Row leaf | Hall B | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 0 | 0 |
| eth-b3-2 | Row leaf | Hall B | 144, 0, 4, 0 | swp61 672.0, swp62 670.6, swp63 672.0, swp64 672.0 | 1 | 0 |
| eth-b4-1 | Row leaf | Hall B | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 0 | 0 |
| eth-b4-2 | Row leaf | Hall B | 144, 0, 4, 0 | swp61 672.0, swp62 672.0, swp63 672.0, swp64 672.0 | 0 | 0 |

## Findings

Records that do not reconcile; each is a case to look into, not a claim that anyone misled.

### SP-1: INC3500001 names Bay23; the serial changed in Bay24

The ticket records the swap in stg-b1-n01 Bay23, but Redfish shows the drive it names as removed (NVWJNT8QR85V) leaving stg-b1-n01 Bay24, and Bay23 still holding its drive. The record of which bay was worked does not match the hardware.

Owner: IT Partner. Contract: Interface Agreement RACI: Storage nodes and drives (physical); IT Partner SLA ticket records.

- INC3500001 parts used: stg-b1-n01 Bay23, removed SN NVWJNT8QR85V, installed SN NV9K6GXTAEID
- Redfish: NVWJNT8QR85V removed from stg-b1-n01 Bay24 at 2026-09-01T03:43:55Z
- Redfish: no drive change in stg-b1-n01 Bay23

### SP-2: INC3500003 resolved before the rebuild finished

The ticket for stg-a1-n08 Bay08 was resolved 50 minutes before rebuild completion on the new drive, so the cluster was still short of full protection when the record says the work was done.

Owner: IT Partner. Contract: Interface Agreement RACI: Storage nodes and drives (physical); IT Partner SLA ticket records.

- INC3500003 resolved at 2026-09-04T22:52:36Z: "Rebuild complete; drive Status OK. Resolved."
- Redfish: NVF2GG6O8PEY in stg-a1-n08 Bay08 StatusIndicator Rebuild until 2026-09-04T23:42:54Z (RebuildComplete)

### SP-3: Drive NV9CH0U50QYC pulled with no custody handover

The drive pulled from stg-a1-n07 Bay16 has no chain-of-custody handover to the Security Partner within 24 h, so storage media is unaccounted for between the rack and destruction.

Owner: IT Partner. Contract: Interface Agreement HO-5 (storage media under chain of custody); Security SLA media destruction.

- Redfish: stg-a1-n07 Bay16 serial NV9CH0U50QYC removed at 2026-09-17T21:52:31Z
- INC3500009 records the swap (removed SN NV9CH0U50QYC)
- Chain-of-custody log: no handover of NV9CH0U50QYC by 2026-09-18T21:52:31Z

### SP-4: eth-a3-2 uplink flap idled 164.1 GPU-hours

A flapping uplink on eth-a3-2 stalled the storage I/O of 72 running nodes for up to 34 minutes. The GPUs were healthy and idle, so the time belongs to the storage fabric, not to the IT Partner's GPU repairs; the ticket for the optic says there was no customer impact.

Owner: IT Partner. Contract: Interface Agreement RACI: Leaf and spine switches (physical replacement); IT Partner SLA ticket records.

- eth-a3-2 swp61 (uplink to eth-a-sp1 swp11) went down 14 times from 2026-09-20T18:35:00Z to 2026-09-20T19:09:00Z; the other uplinks stayed up
- 72 running compute nodes in racks A21, A22, A23, A24 waited on storage I/O inside the episode: 164.1 GPU-hours idle (Customer job telemetry)
- The scheduler kept every one of them in service, so neither scheduler availability nor CSL-01 counts the time
- INC3500011 (optic replaced) records customer impact: "None (redundant uplinks)"

## Events

| When | Device | What | Records |
|---|---|---|---|
| 2026-08-31T07:07:56Z | stg-a1-n08 | Reboot for firmware update: out 10 min; the cluster kept serving |  |
| 2026-09-01T00:48:37Z | stg-b1-n01 | Bay24 NVWJNT8QR85V failed (StatusIndicator Fail) | INC3500001, SP-1 |
| 2026-09-01T03:43:55Z | stg-b1-n01 | Bay24 NVWJNT8QR85V pulled | INC3500001, SP-1 |
| 2026-09-01T06:55:56Z | stg-b1-n01 | Bay24 NV9K6GXTAEID rebuild complete |  |
| 2026-09-01T16:41:00Z | eth-a4-2 | swp11s3 down 2 min (to a27-ct08); the other port carried it |  |
| 2026-09-02T01:49:39Z | stg-a2-n01 | Bay17 NVQ2NQY56RMK predicted its own failure (FailurePredicted) | INC3500002 |
| 2026-09-02T09:38:36Z | stg-a1-n03 | Bay05 NV949NMETPQE warning (cleared on its own) |  |
| 2026-09-02T13:02:28Z | stg-a2-n01 | Bay17 NVQ2NQY56RMK pulled | INC3500002 |
| 2026-09-02T16:55:44Z | stg-a2-n01 | Bay17 NVGS6669FT6P rebuild complete |  |
| 2026-09-02T18:47:00Z | eth-b-st1 | swp3s1 down 3 min (to stg-b1-n06); the other port carried it |  |
| 2026-09-03T14:42:59Z | stg-a1-n08 | Bay08 NVIDY5GP23UT failed (StatusIndicator Fail) | INC3500003, SP-2 |
| 2026-09-04T20:52:48Z | stg-a1-n08 | Bay08 NVIDY5GP23UT pulled | INC3500003, SP-2 |
| 2026-09-04T23:42:54Z | stg-a1-n08 | Bay08 NVF2GG6O8PEY rebuild complete | SP-2 |
| 2026-09-05T06:43:47Z | stg-a1-n05 | Bay23 NVDIGJMPAYJA failed (StatusIndicator Fail) | INC3500004 |
| 2026-09-05T08:22:00Z | eth-b-st2 | swp61 down 36 min (to eth-b-sp1); the other uplinks carried it | INC3500005 |
| 2026-09-05T14:27:27Z | stg-a1-n05 | Bay23 NVDIGJMPAYJA pulled | INC3500004 |
| 2026-09-05T17:36:41Z | stg-a1-n05 | Bay23 NVQ9M4BLFB35 rebuild complete |  |
| 2026-09-05T21:38:39Z | stg-a1-n01 | Bay20 NV3K6IUSS5J5 predicted its own failure (FailurePredicted) | INC3500006 |
| 2026-09-06T14:47:34Z | stg-a1-n01 | Bay20 NV3K6IUSS5J5 pulled | INC3500006 |
| 2026-09-06T18:00:57Z | stg-a1-n01 | Bay20 NV71UZPWE3I6 rebuild complete |  |
| 2026-09-07T01:02:00Z | eth-b2-1 | swp64 down 91 min (to eth-b-sp2); the other uplinks carried it | INC3500007 |
| 2026-09-07T02:50:38Z | stg-a2-n03 | Bay15 NVXGCSNINPTO warning (cleared on its own) |  |
| 2026-09-17T06:34:00Z | eth-b3-2 | swp62 down 82 min (to eth-b-sp1); the other uplinks carried it | INC3500008 |
| 2026-09-17T11:16:33Z | stg-a1-n07 | Bay16 NV9CH0U50QYC failed (StatusIndicator Fail) | INC3500009, SP-3 |
| 2026-09-17T21:52:31Z | stg-a1-n07 | Bay16 NV9CH0U50QYC pulled | INC3500009, SP-3 |
| 2026-09-18T00:33:36Z | stg-a1-n07 | Bay16 NVMZ6HCCTEQJ rebuild complete |  |
| 2026-09-19T00:55:00Z | eth-b1-1 | swp64 flapped (10 downs, 22 min); 107.5 GPU-hours of jobs waited on I/O | INC3500010 |
| 2026-09-19T10:57:23Z | stg-a2-n02 | Reboot for firmware update: out 12 min; the cluster kept serving |  |
| 2026-09-20T18:35:00Z | eth-a3-2 | swp61 flapped (14 downs, 34 min); 164.1 GPU-hours of jobs waited on I/O | INC3500011, SP-4 |
| 2026-09-25T00:19:25Z | stg-b2-n03 | Bay22 NV1785QT662E warning (cleared on its own) |  |
| 2026-09-25T11:58:00Z | eth-a2-2 | swp36s3 down 2 min (to a16-ct18); the other port carried it |  |
| 2026-09-25T15:44:43Z | stg-a2-n05 | Bay24 NVVL6IVZQJR6 warning (cleared on its own) |  |
| 2026-09-27T07:58:44Z | stg-b2-n06 | Reboot for firmware update: out 18 min; the cluster kept serving |  |

## Tickets

| Number | Category | Item | Opened | Resolved | Customer impact |
|---|---|---|---|---|---|
| INC3500001 | storage_drive | stg-b1-n01 Bay23 | 2026-09-01T01:25:41Z | 2026-09-01T07:03:21Z | None: PFS-B kept serving (erasure coding 8+2) |
| INC3500002 | storage_drive | stg-a2-n01 Bay17 | 2026-09-02T02:27:39Z | 2026-09-02T17:10:06Z | None: PFS-A kept serving (erasure coding 8+2) |
| INC3500003 | storage_drive | stg-a1-n08 Bay08 | 2026-09-03T15:10:00Z | 2026-09-04T22:52:36Z | None: PFS-A kept serving (erasure coding 8+2) |
| INC3500004 | storage_drive | stg-a1-n05 Bay23 | 2026-09-05T07:18:35Z | 2026-09-05T18:26:48Z | None: PFS-A kept serving (erasure coding 8+2) |
| INC3500005 | fabric_optic | eth-b-st2 swp61 | 2026-09-05T08:24:27Z | 2026-09-05T09:27:48Z | None (redundant uplinks) |
| INC3500006 | storage_drive | stg-a1-n01 Bay20 | 2026-09-05T21:48:57Z | 2026-09-06T18:13:04Z | None: PFS-A kept serving (erasure coding 8+2) |
| INC3500007 | fabric_optic | eth-b2-1 swp64 | 2026-09-07T01:07:00Z | 2026-09-07T03:11:43Z | None (redundant uplinks) |
| INC3500008 | fabric_optic | eth-b3-2 swp62 | 2026-09-17T06:38:24Z | 2026-09-17T08:16:29Z | None (redundant uplinks) |
| INC3500009 | storage_drive | stg-a1-n07 Bay16 | 2026-09-17T11:42:37Z | 2026-09-18T01:08:19Z | None: PFS-A kept serving (erasure coding 8+2) |
| INC3500010 | fabric_optic | eth-b1-1 swp64 | 2026-09-19T00:59:14Z | 2026-09-19T01:28:00Z | I/O stalls on racks B02, B03, B05, B08 for 22 min; 107.5 GPU-hours idle |
| INC3500011 | fabric_optic | eth-a3-2 swp61 | 2026-09-20T18:38:57Z | 2026-09-20T19:22:26Z | None (redundant uplinks) |

## Chain of custody

| Drive | From | Ticket | Handed to the Security Partner |
|---|---|---|---|
| NVWJNT8QR85V | stg-b1-n01 Bay24 | INC3500001 | 2026-09-01T05:26:32Z |
| NVQ2NQY56RMK | stg-a2-n01 Bay17 | INC3500002 | 2026-09-02T14:02:20Z |
| NVIDY5GP23UT | stg-a1-n08 Bay08 | INC3500003 | 2026-09-04T23:05:09Z |
| NVDIGJMPAYJA | stg-a1-n05 Bay23 | INC3500004 | 2026-09-05T16:07:40Z |
| NV3K6IUSS5J5 | stg-a1-n01 Bay20 | INC3500006 | 2026-09-06T17:17:49Z |

## Storage spares shelf

The storage clusters' drives and the storage fabric's optics, kept on a shelf in each hall's storage row with their own ledger (IT Partner SLA, spares, storage spares shelf). KM-06, at or above minimum at the weekly count: 15 of 16. KM-07, the count equals the ledger: 16 of 16.

| Hall | Class | Minimum | Opening | Issued | Received | Lowest | Weekly counts |
|---|---|---:|---:|---:|---:|---:|---|
| Hall A | 800G OSFP optic (storage fabric) | 4 | 6 | 1 | 1 | 5 | 6, 6, 5, 6 |
| Hall A | NVMe SSD 30.72 TB (U.2) | 4 | 6 | 5 | 5 | 2 | 2, 6, 5, 6 |
| Hall B | 800G OSFP optic (storage fabric) | 4 | 6 | 4 | 4 | 4 | 5, 6, 4, 6 |
| Hall B | NVMe SSD 30.72 TB (U.2) | 4 | 6 | 1 | 1 | 5 | 5, 6, 6, 6 |

Below minimum: Hall A NVMe SSD 30.72 TB (U.2), 2 counted at 2026-09-06T23:00:00Z against a minimum of 4.

## What is read

| Field | Source | Unit | Meaning |
|---|---|---|---|
| `Status.Health, Status.State` | Redfish Drive | OK, Warning, Critical; Enabled, Disabled | The drive's health and whether it is in use |
| `StatusIndicator` | Redfish Drive | OK, Fail, Rebuild, PredictiveFailureAnalysis | What the bay's LED shows: a failed drive, a drive being rebuilt, or one predicted to fail |
| `Operations[].OperationName, PercentageComplete` | Redfish Drive | Rebuild, percent | A rebuild in progress and how far it has got |
| `SerialNumber` | Redfish Drive | text | The drive in the bay; a new serial is a swap |
| `FailurePredicted` | Redfish Drive | true or false | The drive's own prediction that it will fail (a planned swap) |
| `ifOperStatus` | IF-MIB 1.3.6.1.2.1.2.2.1.8 | up(1), down(2) | Each fabric port's state, polled once a minute |
| `ifHCInOctets, ifHCOutOctets` | IF-MIB 1.3.6.1.2.1.31.1.1.1.6 and .10 | octets (Counter64) | Bytes through each storage node port and each leaf uplink; the page shows GB/s |
| `ifInErrors` | IF-MIB 1.3.6.1.2.1.2.2.1.14 | packets | Received packets with errors; a failing optic shows here before it flaps |
| `linkDown, linkUp` | IF-MIB notifications 1.3.6.1.6.3.1.1.5.3 and .4 | trap | Sent by the switch when a port goes down or comes up |
| `I/O wait` | Customer job telemetry | minutes per node | Minutes a node's running job waited on storage; the GPUs are healthy and idle |

## Agreement with the records

| Check | Agrees |
|---|---:|
| The drive event log, replayed from the start inventory, gives the end inventory bay by bay | 800 of 800 |
| Each node's hourly drive counts and minutes online equal the drive and node logs | 21,504 of 21,504 |
| Each cluster hour is the sum of its nodes, and its lowest protection matches the nodes out | 1,344 of 1,344 |
| Every rebuild moves the drive's share of its node's data at 5.0 to 7.0 TB/h | 6 of 6 |
| Replaying the trap log gives every port's seconds up per hour and each row leaf's tray ports up | 107,520 of 107,520 |
| Each node's reads and writes equal its ports' octets, and each hall's traffic crosses every tier byte for byte | 22,848 of 22,848 |
| A tray's two storage ports are down whenever the tray is, and one is up whenever it is up | 774,144 of 774,144 |
| Every client stall falls in a flapping episode on its row's leaf uplinks, on a node running a job | 146 of 146 |
| Every part a storage ticket used is issued from its hall's spares shelf against that ticket before the swap, and every cycle count's system quantity equals the shelf ledger | 27 of 27 |

## Sources

- NVIDIA DGX SuperPOD GB200 reference architecture: network fabrics (storage and in-band Ethernet fabric on SN5600; compute trays at 4 x 200 GbE on BlueField-3, two ports for storage; a storage leaf pair per scalable unit): https://docs.nvidia.com/dgx-superpod/reference-architecture-scalable-infrastructure-gb200/latest/network-fabrics.html (checked 2026-10-14)
- DMTF Redfish Drive schema (Status, StatusIndicator: OK, Fail, Rebuild, PredictiveFailureAnalysis; Operations; SerialNumber; FailurePredicted): https://redfish.dmtf.org/schemas/v1/Drive.v1_2_8.json (checked 2026-10-14)
- Lenovo XClarity: GET Drive instance (an example Redfish Drive with Status, SerialNumber, FailurePredicted, PredictedMediaLifeLeftPercent): https://pubs.lenovo.com/tsm/get_driver_instance (checked 2026-10-14)
- RFC 2863, The Interfaces Group MIB (ifOperStatus, ifHCInOctets, ifInErrors, linkDown and linkUp): https://www.rfc-editor.org/rfc/rfc2863 (checked 2026-10-14)
