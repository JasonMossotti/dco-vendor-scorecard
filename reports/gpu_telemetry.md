# GPU telemetry

Site AUS-1, Aug 31, 2026 to Sep 28, 2026 (the sample month). Synthetic GPU telemetry in the published format of NVIDIA's open-source DCGM exporter. Everything here is fictional.

  Source: data/telemetry/gpu/ (committed tiers) and the per-GPU hourly tier built at publish time  |  Generator: scripts/generate_telemetry.py, scripts/render_telemetry.py

## What is collected

Every GPU (3,312 in 46 racks) is scraped once a minute from the DCGM exporter on each tray (port 9400, collect interval 30,000 ms, the exporter's published default). Fields, with the exporter's metric type:

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `DCGM_FI_DEV_GPU_TEMP` | gauge | °C | GPU temperature (in C). |
| `DCGM_FI_DEV_MEMORY_TEMP` | gauge | °C | Memory temperature (in C). |
| `DCGM_FI_DEV_POWER_USAGE` | gauge | W | Power draw (in W). |
| `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION` | counter | mJ | Total energy consumption since boot (in mJ). |
| `DCGM_FI_DEV_GPU_UTIL` | gauge | % | GPU utilization (in %). |
| `DCGM_FI_DEV_SM_CLOCK` | gauge | MHz | SM clock frequency (in MHz). |
| `DCGM_FI_DEV_FB_USED` | gauge | MiB | Framebuffer memory used (in MiB). |
| `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE` | gauge | ratio | Ratio of cycles the tensor (HMMA) pipe is active. |
| `DCGM_FI_DEV_XID_ERRORS` | gauge | XID | Value of the last XID error encountered. |
| `DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS` | counter | rows | Number of remapped rows for correctable errors. |
| `DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS` | counter | rows | Number of remapped rows for uncorrectable errors. |
| `DCGM_FI_DEV_ROW_REMAP_PENDING` | gauge | 0 or 1 | Whether remapping of rows is pending (the GPU must be reset). Enabled at this site; off in the default list. |
| `DCGM_FI_DEV_ECC_SBE_AGG_TOTAL` | counter | errors | Total number of single-bit persistent ECC errors. Enabled at this site; off in the default list. |
| `DCGM_FI_DEV_THERMAL_VIOLATION` | counter | ns | Throttling duration due to thermal constraints (in ns). Enabled at this site; off in the default list. |
| `DCGM_FI_DEV_POWER_VIOLATION` | counter | ns | Throttling duration due to power constraints (in ns). Enabled at this site; off in the default list. |

## The month by hall

| | Hall A | Hall B |
|---|---:|---:|
| GPU model | NVIDIA GB200 | NVIDIA GB300 |
| Racks reporting | 32 | 14 |
| Mean utilization | 86.6% | 83.9% |
| Mean GPU power | 927 W | 1,047 W |
| Power limit at this site | 1,200 W (product maximum 1,200 W) | 1,200 W (product maximum 1,400 W) |
| Time held at the power limit | 0.0% of samples | 63.9% of samples |
| Hardware thermal slowdown | 387 GPU-minutes | 10 GPU-minutes |
| Peak GPU temperature | 89 C | 88 C |
| GPU energy | 1,434.6 MWh | 361.0 MWh |
| XIDs | 41 | 0 |

## Agreement with the records

The telemetry is synthetic, so it is shaped never to contradict the records the other pages show. Each check reads only what the telemetry publishes and the existing records.

| Check | Agrees |
|---|---:|
| Rack daily peak temperatures and trays reporting equal the GPU Health layer | 1,103 of 1,103 |
| Each GPU with a counter row peaks at that row's temperature that day | 894 of 894 |
| Remapped rows, pending remaps, and corrected errors equal the daily counters | 895 of 895 |
| Every XID shows on the same GPU at the first sample after it | 41 of 41 |
| A drained node runs nothing in each whole hour of the drain | 428 of 428 |
| No samples while a GPU or tray is dark; rack power loss matches the Landlord's record | 100 of 100 |
| Slowdown temperature only inside recorded episodes, with a lower clock and matching violation time | 56,110 of 56,110 |
| A Hall B rack has no samples before its power-on milestone | 14 of 14 |
| GPU energy never exceeds the UPS output in any hour (GPU share of UPS output 25% to 47%) | 672 of 672 |

## Sources

- NVIDIA dcgm-exporter: default counter set etc/default-counters.csv (public, open source): https://github.com/NVIDIA/dcgm-exporter/blob/main/etc/default-counters.csv (checked 2026-10-09)
- NVIDIA DCGM documentation: Install DCGM Exporter (port 9400, --collect-interval default 30000 ms): https://docs.nvidia.com/datacenter/dcgm/latest/installation/install-dcgm-exporter.html (checked 2026-10-09)
- NVIDIA DCGM documentation: DCGM Exporter (Prometheus text format, HELP and TYPE lines): https://docs.nvidia.com/datacenter/cloud-native/gpu-telemetry/latest/dcgm-exporter.html (checked 2026-10-09)
- NVIDIA GB200 NVL72 product page (13.4 TB HBM3e per rack: 186 GB per GPU): https://www.nvidia.com/en-us/data-center/gb200-nvl72/ (checked 2026-10-09)
- B300 notes, glennklockwood.com (B300 1,400 W up from B200 1,200 W; 288 GB HBM3e): https://glennklockwood.com/garden/processors/B300 (checked 2026-10-09)
