# Model card: GPU memory

**Predicts:** an uncorrectable GPU memory error (XID 48, 94, or 95) at least 24 hours ahead, so the job can be drained
and the tray swapped before the error kills it.

**Owner of the work:** IT Partner, for the Customer (Interface Agreement RACI row "Compute tray (GPU, CPU, memory, cold plate)").

## Inputs

`gpu_memory.csv`: one row per GPU per day with corrected (`sbe_day`) and uncorrected (`uce_day`) volatile ECC counts and
the row remap counters (`remapped_rows`, `remap_pending`), from DCGM. `gpu_xids.csv` (optional) lists the XIDs that
followed, only to score the warning.

## Method

The GPU Health tab's early-warning rule (`config/gpu_health.yaml`), reused as is:

* remapped rows up by 2 or more within 7 days, or
* corrected errors at 100 or more a day and higher each day for 3 days in a row.

The GPU is flagged at the end of the first day either holds.

The backtest runs it once per episode: the series is split after each day with an uncorrectable error, because the
rule flags a GPU once and a second episode on the same GPU needs its own warning.

## Measured on the synthetic history

* Backtest: 68 uncorrectable memory errors; 36 were warned at least 24 hours ahead (median lead 4.6 days), 0 work
  requests had no error follow them, and 16 flags came after the error (the counters only moved on the day).
* Against the answer key (episodes with a planted precursor): 36 of 36, 0 false alarms.
* Robustness, 60 generated histories: 2,208 of 2,208 planted episodes warned in time, 0 false alarms; 45 more came in
  the first 4 days of data, when the climb began before the data starts (too early to judge).
* Decoys: bursts of corrected errors that settle (about one every two weeks in the fleet) and GPUs with a few stable
  remapped rows. Neither raises a request.

## Blind spots

* An uncorrectable error with no corrected-error climb first (about half of the planted errors have none; how many real
  errors give warning is the first thing a shadow run measures).
* A tray swapped without the serial changing in the asset register: the remap counters carry over wrongly.

## What to recheck on real data

1. The fleet's normal corrected-error rate per GPU model and driver; the 100-a-day floor depends on it.
2. Whether the driver resets volatile counts at reboot, so a daily count is a true daily count.
3. How fast remapped rows rise on a GPU that later fails, against one that settles.
