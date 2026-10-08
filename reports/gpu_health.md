<!--
  GENERATED FILE. DO NOT EDIT BY HAND.
  Source: data/gpu_health/ (health layer), data/sample/ (XIDs, scheduler, tickets)  |  Generator: scripts/render_gpu_health.py
-->

# GPU Health Review: Site AUS-1

Sample month Aug 31, 2026 to Sep 27, 2026 (UTC). Synthetic health data modeled on public DCGM-style health checks and NVIDIA's public XID catalog. All names and serials are fictional; every threshold is an assumption in config/gpu_health.yaml.

## Summary

| Measure | Value |
|---|---|
| GPUs reporting at the end of the month | 3,312 |
| Health watches raised | 33 Fail, 18 Warn |
| Uncorrectable memory XIDs warned at least 24 hours ahead | 3 of 10 |
| GPUs on the early-warning list | 5 |
| Returned to service with a row remap pending | 2 |
| Trays throttling with the CDU in band | 1 |
| CDU excursions that throttled GPUs | 0 |

## Findings

### GH-F1: 1 GPU to drain and replace before it fails

Remapped rows or corrected memory errors are rising with no uncorrectable error yet. Each is a candidate to drain at a convenient time and replace under the IT Partner's break-fix process, rather than wait for an XID.

- Owner: IT Partner
- Contract: CSL-01
- a16-ct18 GPU 2: corrected errors rising from 2026-09-24; 2 remapped rows, peak 1,799 corrected errors in a day

### GH-F2: a31-ct11 returned to service with a row remap pending

The scheduler returned a31-ct11 to service while GPU 0 still needed a reset to complete a row remap from an uncorrectable memory error. Validation before return to service should include the GPU reset.

- Owner: IT Partner
- Contract: FC-GPU
- Remap pending from 2026-09-01 12:54 UTC (health watch, Memory Warn)
- Returned to service 2026-09-01 16:11 UTC (scheduler)
- INC3100085 closed as 'Cleaned/reseated'
- Still pending at the end of the month

### GH-F3: a22-ct07 returned to service with a row remap pending

The scheduler returned a22-ct07 to service while GPU 0 still needed a reset to complete a row remap from an uncorrectable memory error. Validation before return to service should include the GPU reset.

- Owner: IT Partner
- Contract: FC-GPU
- Remap pending from 2026-09-04 07:21 UTC (health watch, Memory Warn)
- Returned to service 2026-09-04 10:29 UTC (scheduler)
- INC3100204 closed as 'Cleaned/reseated'
- Pending until 2026-09-07 03:40 UTC

### GH-F4: a09-ct04 throttling with its CDU in band

GPUs on a09-ct04 hit thermal slowdown on 16 days (375 minutes) while CDU-A2 held the rack band, so the cause is inside the rack, downstream of the manifold isolation valves (DM-COOL): the tray's quick-disconnects, hoses, or cold plates. No ticket is open for it.

- Owner: IT Partner
- Contract: DM-COOL, FA-2
- Slowdown on GPUs 0, 1, 2, 3, up to 88.8 C
- CDU-A2 supply at most 26.3 C, flow at least 1,549 L/min over those days

## Early warning

A GPU is flagged at the end of the first day its remapped rows have risen by 2 within 7 days, or its corrected memory errors have stayed above 100 a day and risen 3 days running.

| GPU | Flagged | Why | Remapped rows | Then |
|---|---|---|---|---|
| a13-ct10 GPU 3 | Sep 16 | corrected errors rising | 4 | XID 48 Sep 21 00:54 (121 h later) |
| a16-ct18 GPU 2 | Sep 24 | corrected errors rising | 2 | No uncorrectable error yet |
| a22-ct07 GPU 0 | Sep 8 | remapped rows rising | 2 | No uncorrectable error yet |
| a30-ct06 GPU 0 | Sep 19 | corrected errors rising | 3 | XID 94 Sep 20 16:29 (40 h later) |
| a30-ct08 GPU 3 | Sep 23 | corrected errors rising | 3 | XID 94 Sep 25 00:43 (49 h later) |

| Uncorrectable memory XID | GPU | Warned ahead |
|---|---|---|
| XID 94 Sep 1 05:48 | a31-ct11 GPU 0 | no |
| XID 94 Sep 1 12:54 | a31-ct11 GPU 0 | no |
| XID 94 Sep 4 07:21 | a22-ct07 GPU 0 | no |
| XID 48 Sep 7 02:24 | a22-ct07 GPU 0 | no |
| XID 94 Sep 10 18:01 | a15-ct07 GPU 3 | no |
| XID 94 Sep 13 03:50 | a05-ct15 GPU 1 | no |
| XID 94 Sep 20 16:29 | a30-ct06 GPU 0 | yes, 40 h |
| XID 48 Sep 21 00:54 | a13-ct10 GPU 3 | yes, 121 h |
| XID 94 Sep 23 06:51 | a19-ct15 GPU 1 | no |
| XID 94 Sep 25 00:43 | a30-ct08 GPU 3 | yes, 49 h |

## Cooling events and the GPUs they serve

| CDU | Pump redundancy lost | Racks reporting | Lowest flow | Highest supply | In band | GPUs throttled |
|---|---|---|---|---|---|---|
| CDU-B3 | Sep 6 02:51 to Sep 6 08:30 | 0 | 1,591 L/min | 25.1 C | yes | 0 |
| CDU-A2 | Sep 23 04:34 to Sep 23 08:18 | 8 | 1,549 L/min | 25.3 C | yes | 0 |

Brief one-off slowdowns (a GPU touching 87 C for under two minutes) on 19 trays are workload peaks, not findings.

## Engine self-check

Found **7 of 7** planted cases, **0 false positives**. Decoys not flagged: 36 GPUs with old, unchanging remapped rows, 2 one-day error bursts, 19 brief slowdowns. The checks cannot read the answer key.

## Sources

- NVIDIA DCGM user guide: health monitoring (public): https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/feature-overview.html (checked 2026-10-07)
- NVIDIA Xid catalog (public): https://docs.nvidia.com/deploy/xid-errors/latest/analyzing-xid-catalog.html (checked 2026-10-07)
