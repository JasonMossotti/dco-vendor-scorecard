# Model card: optics

**Predicts:** an optic module reaching its own DOM warning (laser bias rising, transmit or receive power falling)
at least 24 hours before it gets there, so it can be swapped in a planned window instead of after a link flap.

**Owner of the work:** IT Partner, for the Customer (Interface Agreement RACI row "Back-end fabric optics, cables, and fiber").

## Inputs

`optic_dom.csv`: one row per module per day, the worst lane of the day (`bias_ma` the highest, `tx_dbm` and `rx_dbm`
the lowest), with the module's location and the far end's location from the cabling map. CMIS modules report these
through the fabric manager's telemetry or `mlxlink -m`.

## Method

1. **Baseline.** Each module's own level from its first 14 days in service. Its scatter is the robust deviation (MAD)
   of its day-to-day moves, never below the stored resolution (0.1).
2. **Screen.** Today is 4 deviations from the baseline, or has moved 4 deviations within the last 5 days (a module
   already wearing when the data starts has a baseline that already includes some of the wear).
3. **Confirm a trend, not a step.** Over the last 5 days, at least 4 of the 4 day-to-day moves go the bad way, and no
   single move is more than 60% of the total. A connector reseated or a fiber patched moves the level once; wear moves it
   every day.
4. **Attribute.** A receive power trend is dropped when the far end's transmit power is trending the same way within 3
   days: the far module is the one wearing, and it gets its own flag.
5. **Project.** A Theil-Sen trend over the last 5 days gives the days to the warning. Within 14 days is a work request
   (act); within 45 days is watch.

## Limits and their basis

| Reading | Warning | Alarm | Basis |
|---|---|---|---|
| Receive power | −10.4 dBm | −13.4 dBm | `config/telemetry_network.yaml` (mlxlink's example module), warning 3 dB inside the alarm |
| Transmit power | −8.4 dBm | −11.4 dBm | The same |
| Laser bias | 11.0 mA | 13.0 mA | Assumption: not in the mlxlink example |

On real equipment each module's CMIS threshold page sets its own limits; read them from the module.

## Measured on the synthetic history

* Backtest on the committed history: 108 modules reached their warning; 69 were warned at least 24 hours ahead
  (median lead 10.0 days), 4 more were degrading before the data starts (too early to judge), and 0 work requests had
  no failure follow them. The other modules failed with no precursor (the history plants about 40% of failures with
  none), which no detector on these readings can see.
* Against the answer key (only modules with a planted precursor): 69 of 69, 0 false alarms.
* Robustness: `python scripts/render_predict.py --robustness 60`, 60 generated histories with every wear-out moved: 3,723
  of 3,723 planted modules warned in time and 0 false alarms; no step decoy raised a request. One of them was a receive
  alarm caused by the far end's transmitter wearing at the same time; the detector named the far end (peer attribution)
  and warned it 13 days ahead, which counts as warned. Seeds 1 to 14 were used while the rules were set.

## Blind spots

* A module that fails with no gradual precursor (a sudden laser death, a cracked fiber).
* Wear faster than the 5-day trend window allows (a module that goes from healthy to warning in two days).
* A daily worst-lane poll hides a lane that dips for minutes; that is a link-flap question, not a wear question.

## What to recheck on real data

1. The thresholds on the module's own threshold page, per part number.
2. The day-to-day scatter of healthy modules: if it is larger than 0.1, the 4-deviation screen fires less often.
3. How long real laser wear takes from the first visible drift to the warning; the 5-day window assumes weeks.
4. Whether reseats and fiber cleans are logged, so a step after one can be checked against the record.
