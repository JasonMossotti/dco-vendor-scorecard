# Predictive maintenance: running it at a real site

The detectors in `src/scorecard/predict/` read condition data a site already collects, say per device whether it is
**healthy**, on **watch**, or needs a **work request**, and show the evidence (the level, the trend, the projected date)
so a person can check it by hand. This page is the input contract, the command, and the path from a pilot to daily use.
Each detector has a model card beside it:

| Detector | Model card | Failure it predicts | Owner (Interface Agreement RACI) |
|---|---|---|---|
| Optics | [optics.md](optics.md) | An optic module reaching its own DOM warning (laser wear, falling power) | IT Partner, for the Customer |
| GPU memory | [gpu_memory.md](gpu_memory.md) | An uncorrectable memory error (XID 48, 94, 95) | IT Partner, for the Customer |
| CDU filter | [cdu_filter.md](cdu_filter.md) | A filter reaching its change limit before its next scheduled change | Landlord |
| CDU pumps | [cdu_pump.md](cdu_pump.md) | A pump wearing out (more speed for the same flow) before it fails | Landlord |

A prediction is a forecast that proposes work. It is not a finding, and it changes no SLA result: the contracts measure
what happened, not what was forecast.

## The input contract

Put any of these CSV files in one folder. Each detector runs only when its file is there. Times are UTC, ISO 8601.

| File | Columns | Where a site gets it (read-only) |
|---|---|---|
| `optic_dom.csv` | `date, serial, location, peer, bias_ma, tx_dbm, rx_dbm`: one row per module per day, the worst lane of the day | The fabric manager's telemetry (UFM Telemetry's `rx_power_lane_N`, `tx_power_lane_N`, `tx_bias_lane_N`), or `mlxlink -m` on each port, kept as a daily minimum or maximum. `peer` is the far end's location, from the cabling map. |
| `gpu_memory.csv` | `date, host, tray_serial, gpu, sbe_day, uce_day, remapped_rows, remap_pending` | DCGM: corrected and uncorrected volatile ECC counts per day, and the row remap counters (`DCGM_FI_DEV_ROW_REMAP_*`), with the tray serial from the asset register |
| `gpu_xids.csv` (optional) | `opened, host, tray_serial, gpu, xid` | The driver's XID log through the node agent; used only to report what followed a warning |
| `cdu_readings.csv` | `timestamp, cdu, flow_lpm, filter_dp_kpa, pump1_pct, pump2_pct`: averages over a regular period (an hour, or four) | Each CDU's Redfish service: `ThermalEquipment/CDUs/{id}` flow, the filter pressure-drop sensor, and `Pumps/{n}` speed (the collector's Redfish adapter already reads these) |
| `cdu_events.csv` | `timestamp, cdu, resource, property, value` | Redfish events for `Pumps/{n}` `Status.Health`; Critical then OK means the pump was repaired or replaced, and its baseline is learned again |
| `filter_changes.csv` (optional) | `cdu, completed_at` | The Landlord's PM records: the last filter change before the readings start |

The detectors use the Python standard library only (GPU memory also uses the GPU Health tab's rule from this package).
Every threshold, and its basis, is in `config/predict.yaml`. A site edits only the `detectors` and `work_requests`
sections; the `condition` section shapes this repository's synthetic history and is not used on real data.

## The command

```bash
python scripts/predict.py --source exports/ --out predictions/
python scripts/predict.py --source exports/ --out predictions/ --since 2026-09-01   # only requests raised since
python scripts/predict.py --demo --out predictions/      # this site's synthetic history, exported in the same files
```

It writes three files to `--out` and nothing anywhere else:

* `watch_list.csv`: every device not healthy on its last reading (`detector, device, serial, state, since, detail`).
* `work_requests.csv`: one row per work request (`id, flagged, detector, device, serial, mode, evidence, due_by,
  owner_party, accountable, raci_component`), a shape any maintenance system can import. The owner is the party that
  does the work under the Interface Agreement RACI; the accountable party is beside it.
* `predictions.json`: everything, with each detector's full evidence.

It never connects to a device. The inputs are files the site has already exported, so it runs wherever Python 3.11 or
later does, including a locked-down analysis host.

`--demo` exports the committed condition history (`data/predict/`) in the contract's shape and runs on it; its 107 work
requests are exactly the backtest's on the Predictive view (a test holds the two together).

## From a pilot to daily use

1. **Wire the inputs.** Most sites already keep these readings in a historian or metrics store; the work is a daily
   export query per file. The collector in `src/scorecard/live/` reads the CDU's Redfish service today.
2. **Shadow mode for 90 days.** Run the command daily, keep every output, and act on none of it. At the end, score it
   against what actually failed with the same rules as this backtest: a warning counts only if it came the stated lead
   time ahead, and a work request no failure followed is a false alarm.
3. **Recalibrate on the site's own data.** Each model card lists what to check first. The thresholds here were set on
   synthetic data and say nothing about real equipment until step 2 has run.
4. **Route the work requests.** Optics and GPU trays go to the IT Partner; CDU filters and pumps to the Landlord as a
   request under the Interface Agreement's data access and maintenance terms. A Landlord prediction is a request, not a
   default: the Landlord SLA's maintenance schedule still governs until the parties agree a condition-based interval.
5. **Review monthly.** Warnings that came in time, failures with no warning, and false alarms, beside the failure
   pattern review.

## Standards frame

The layers follow the condition monitoring data-processing model of ISO 13374 (acquire, manipulate, detect the state,
assess health, forecast, advise), and the forecasting terms follow ISO 13381-1 (2025 edition) on prognostics. Recheck
the editions when deploying.

| ISO 13374 layer | Here |
|---|---|
| Data acquisition | The site's exports (the input contract) |
| Data manipulation | Daily worst lane; pressure drop corrected to design flow; speed against flow |
| State detection | The screen and the steady-trend test (optics); the CUSUM (pumps) |
| Health assessment | Healthy, watch, act |
| Prognostic assessment | Days to the warning or the change limit (Theil-Sen trend); the fleet's Weibull outlook |
| Advisory generation | Work requests with evidence, due-by date, and owner |

## What this is not

* Not a trained model. Each detector is a rule a facilities engineer can check by hand. A site can replace any of them
  with a learned model behind the same input and output files.
* Not a controller. Nothing here writes to a device or opens a ticket by itself.
* Not evidence about real equipment. The history is synthetic and the wear-outs are planted; every lead time and false
  alarm rate on the Predictive view is measured on that history.

LatentView's PULSE (a predictive maintenance product for manufacturing) offers remaining useful life, FMEA, a scenario
planner, and causality analysis. This project has the same four shapes: the projected date to a limit, the failure
pattern review, the fleet outlook against spares minimums, and the cross-partner attribution. It does not copy or claim
to know PULSE's methods, which its public pages do not describe.
