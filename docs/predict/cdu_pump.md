# Model card: CDU pumps

**Predicts:** a CDU pump wearing out at least 7 days before it fails. A worn impeller or bearing needs more speed for the
same flow, and the CDU's own controller hides that by speeding up.

**Owner of the work:** Landlord (Interface Agreement RACI row "CDUs and the hall secondary header"), raised as a request.

## Inputs

`cdu_readings.csv`: flow and each pump's speed. `cdu_events.csv`: Redfish `Pumps/{n}` `Status.Health` events, where
Critical then OK means the pump was repaired or replaced.

## Method

1. **Keep the duty readings.** A pump below 40% speed, or a reading with both pumps running, is a rotation or a test.
2. **Speed for the flow.** Expected speed is the duty speed (82%) scaled by flow over design flow (1,800 L/min). The
   residual is the measured speed minus that, in percent.
3. **Baseline.** Each pump's own residual and its scatter, from its first 10 days on duty (at least 12 readings), learned
   again after each replacement.
4. **Detect.** A one-sided CUSUM on the residual (allowance 0.5 deviations, decision interval 8 deviations) is a watch.
   The median of the last three readings 1.0% or more above the baseline is a work request.

## Limits and their basis

| Limit | Value | Basis |
|---|---|---|
| Watch | CUSUM over 8 deviations | Detects a steady small rise; standard CUSUM settings |
| Act | 1.0% speed for the flow | About ten times the reading scatter; an assumption to recheck |

## Measured on the synthetic history

* Backtest: 2 pump failures; the one that wore out was warned 28.7 days ahead, the other was sudden (no wear) and could
  not be seen. 0 false alarms.
* Robustness, 60 generated histories with the worn pump moved: 60 of 60 warned at least 7 days ahead, no sudden
  failure warned (none could be), 0 false alarms.
* Now (the sample month): 16 of 16 pumps healthy. CDU-B3 pump 2 (Sep 6) and CDU-A2 pump 2 (Sep 23) failed suddenly.

## Blind spots

* Sudden failures: a seized bearing, a motor drive fault, a coupling.
* A controller that limits speed, so a worn pump shows as lower flow instead of higher speed.
* Changes to the secondary loop (a valve set, a new rack) that change the speed-for-flow curve: relearn the baseline
  after any recorded change to the loop.

## What to recheck on real data

1. The pump curve: the duty speed at design flow and whether speed scales linearly with flow in the working range.
2. The reading scatter of a healthy pump, and so whether 1.0% is still about ten times it.
3. Vibration or motor current, if the CDU exposes them; either sees bearing wear earlier than speed does.
