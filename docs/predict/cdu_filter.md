# Model card: CDU filter

**Predicts:** a CDU's strainer or filter reaching its change limit before its next scheduled change, at least 7 days
ahead, so the change can be brought forward. It also says when a filter due by the calendar is still clean.

**Owner of the work:** Landlord (Interface Agreement RACI row "CDUs and the hall secondary header"). The Customer raises
it as a request; the Landlord SLA's maintenance schedule governs until the parties agree a condition-based interval.

## Inputs

`cdu_readings.csv`: flow and filter pressure drop, averaged over a regular period (an hour, or four), from each CDU's
Redfish service. `filter_changes.csv` (optional): the last change before the readings start, from the Landlord's PM records.

## Method

1. **Correct to design flow.** Pressure drop goes with the square of flow, so each reading is scaled to 1,800 L/min:
   dp × (1800 / flow)². A filter does not look dirtier because the hall ran harder.
2. **Find the changes.** A daily level that falls 2 kPa or more is a change; drops within a day of each other are one.
3. **Project.** A Theil-Sen trend over the last 7 days since the change (none in the first 3 days) gives the date the
   corrected pressure drop reaches 28 kPa.
4. **Decide.** The limit falls before the next scheduled change (last change + 91 days) and within 30 days: a work
   request. Before the next change but further out: watch. After it: healthy, however long since the last change.

## Limits and their basis

| Limit | Value | Basis |
|---|---|---|
| Change limit | 28 kPa at design flow | Twice the clean pressure drop (`config/telemetry_cdu.yaml`); a rule of thumb, and the filter maker's terminal pressure drop governs |
| Scheduled interval | 91 days | The rated quarterly service (`config/telemetry_cdu.yaml`) |

## Measured on the synthetic history

* Backtest: 1 filter reached its limit early (the planted fouling); it was warned 29.5 days ahead, with 0 false alarms.
* Robustness, 60 generated histories with the fouled CDU and its timing moved: 60 of 60 warned at least 7 days
  ahead, 0 false alarms.
* Now (the sample month): all 8 filters healthy. CDU-A1 and CDU-A2 are overdue by the calendar but clean by condition,
  with the limit projected for late January and early February 2027.

## Blind spots

* Fouling that comes all at once (a slug of debris after a pipe repair); a trend cannot see it ahead.
* A pressure-drop sensor that drifts; the corrected level and the clean level after a change both move.

## What to recheck on real data

1. The filter maker's terminal pressure drop and the sensor's position (across the strainer only, or the strainer and a valve).
2. That changes appear in the readings as a clear drop; otherwise feed `filter_changes.csv` from the PM records.
3. The real clean pressure drop of each CDU after its first change.
