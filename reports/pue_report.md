<!--
  GENERATED FILE. DO NOT EDIT BY HAND.
  Source: data/energy/ (meters), sla/ot_partner.yaml (section 22)  |  Generator: scripts/render_energy.py
-->

# PUE Report: Site AUS-1

Sample month Aug 31, 2026 to Sep 27, 2026 (UTC). Synthetic meter data; all names fictional. PUE per ISO/IEC 30134-2:2026: total facility energy divided by IT energy, both as energy over the period; IT energy at the UPS outputs.

## Summary

| Measure | Value |
|---|---|
| PUE, this month (metered) | 1.353 |
| PUE, Landlord's report | 1.313 |
| PUE, 52 weeks (OT-EN-02, target at most 1.35) | 1.318 (met) |
| Partial PUE, cooling | 1.256 |
| Partial PUE, power path | 1.044 |
| House load per IT kWh | 0.052 |
| Total facility energy | 6,935.2 MWh (utility 6,928.1 MWh, generators 7.1 MWh) |
| IT energy (UPS outputs) | 5,125.1 MWh |
| Cooling | 1,314.1 MWh |
| Power path losses | 227.2 MWh (UPS 158.5 MWh, distribution 68.7 MWh) |
| House load | 268.8 MWh |

## By week

| Week | PUE | Cooling pPUE | Power pPUE | Facility | IT |
|---|---|---|---|---|---|
| 1. Aug 31 to Sep 6 | 1.347 | 1.250 | 1.044 | 1,734.3 MWh | 1,288.0 MWh |
| 2. Sep 7 to Sep 13 | 1.342 | 1.246 | 1.044 | 1,723.7 MWh | 1,284.4 MWh |
| 3. Sep 14 to Sep 20 | 1.365 | 1.268 | 1.044 | 1,739.4 MWh | 1,274.3 MWh |
| 4. Sep 21 to Sep 27 | 1.359 | 1.262 | 1.044 | 1,737.8 MWh | 1,278.4 MWh |

## 52 weeks by four-week period

| Period | Mean outdoor | PUE | Cooling pPUE | Power pPUE | IT |
|---|---|---|---|---|---|
| Sep 29 to Oct 26 | 23.2 C | 1.350 | 1.222 | 1.044 | 3,195.7 MWh |
| Oct 27 to Nov 23 | 17.5 C | 1.291 | 1.168 | 1.044 | 3,370.2 MWh |
| Nov 24 to Dec 21 | 11.7 C | 1.248 | 1.129 | 1.043 | 3,551.0 MWh |
| Dec 22 to Jan 18 | 10.6 C | 1.237 | 1.121 | 1.043 | 3,699.6 MWh |
| Jan 19 to Feb 15 | 13.8 C | 1.250 | 1.138 | 1.043 | 3,879.8 MWh |
| Feb 16 to Mar 15 | 15.3 C | 1.258 | 1.148 | 1.043 | 4,023.3 MWh |
| Mar 16 to Apr 12 | 17.3 C | 1.276 | 1.168 | 1.044 | 4,178.2 MWh |
| Apr 13 to May 10 | 22.7 C | 1.325 | 1.219 | 1.044 | 4,353.0 MWh |
| May 11 to Jun 7 | 24.4 C | 1.341 | 1.238 | 1.044 | 4,523.4 MWh |
| Jun 8 to Jul 5 | 26.4 C | 1.359 | 1.257 | 1.044 | 4,676.1 MWh |
| Jul 6 to Aug 2 | 30.6 C | 1.401 | 1.301 | 1.045 | 4,839.2 MWh |
| Aug 3 to Aug 30 | 28.9 C | 1.382 | 1.284 | 1.045 | 4,996.7 MWh |
| Aug 31 to Sep 27 (this month) | 26.1 C | 1.353 | 1.256 | 1.044 | 5,125.1 MWh |

52-week PUE (Sep 29, 2025 to Sep 27, 2026): **1.318**. The periods before the sample month are synthetic history (Hall B ramping up as it deployed).

## Findings

### EN-F1: Monthly energy report does not reconcile with the meters

The Landlord reported PUE 1.313 for the month; the meters give 1.353. Reported total facility energy 6,935.2 MWh against 6,935.2 MWh metered; reported IT energy 5,283.6 MWh against 5,125.1 MWh metered. Likely cause: IT energy was taken at the UPS inputs, so UPS losses were counted as IT load; the standard measures IT energy at the UPS outputs and counts the losses as facility overhead.

- Contract: OT-EN-01, OT-EN-02
- Evidence: landlord_energy_report.json; meters_hourly.csv: utility, generator, UPS output, and sub-meter totals

### EN-F2: Free cooling left disabled on CH-03

Free cooling on CH-03 was disabled at 2026-09-13 12:24 UTC (PM-0015 Preventive maintenance) and stayed off for 6.0 days (re-enabled by the BMS), with no change record covering it. The work record closed the task while the BMS still showed the local override. 64 of those hours were cool enough for free cooling; the plant model estimates 2.7 MWh of extra chiller energy (about $179).

- Contract: OT-EN-03
- Evidence: chiller_events.jsonl; landlord/pm_records.csv: PM-0015; meters_hourly.csv: chiller yard and outdoor temperature
- Estimated extra energy: 2.7 MWh (about $179 at $0.065 per kWh; plant model estimate)

## Free-cooling log

| Chiller | Disabled | Enabled | Hours | Record |
|---|---|---|---|---|
| CH-06 | 2026-09-08 11:40 | 2026-09-08 17:21 | 5.7 | PM-0014 Preventive maintenance |
| CH-10 | 2026-09-11 15:45 | 2026-09-11 22:27 | 6.7 | PM-0016 Preventive maintenance |
| CH-03 | 2026-09-13 12:24 | 2026-09-19 11:23 | 143.0 | PM-0015 Preventive maintenance |

## Contract terms (Landlord SLA section 22)

- **OT-EN-01 Monthly Energy Report.** By the fifth business day of each month, the Landlord submits total facility energy, IT energy, PUE, and partial PUE for the prior period, with the meters used. The figures must reconcile with the meter data in the Customer's facility feed within rounding.
- **OT-EN-02 PUE Over 52 Weeks.** PUE over the most recent 52 weeks at most 1.35. Key Measurement; no service credits. A miss requires an energy improvement plan within 30 days.
- **OT-EN-03 Free-Cooling Availability.** Free cooling (economizer) on a chiller may be disabled for more than 24 hours only under an approved MOP or change record. A lockout left in place after maintenance is a records discrepancy and is reported with its estimated energy cost.

## Engine self-check

Detected **2 of 2** planted energy discrepancies, **0 false positives**; the likely cause named correctly for 1 report mismatch. The check cannot read the answer key.
