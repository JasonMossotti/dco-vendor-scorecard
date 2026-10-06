<!-- GENERATED FILE. DO NOT EDIT BY HAND. Source: data/sample + data/changes | Generator: scripts/render_alarms.py -->

# Change-Aware Alarm Review: Site AUS-1

Synthetic sample month 2026-08-31 to 2026-09-28 (fictional site; all data synthetic). Interactive board: [https://jasonmossotti.github.io/dco-vendor-scorecard/alarms/](https://jasonmossotti.github.io/dco-vendor-scorecard/alarms/). Rules: Interface Agreement section 10 (`sla/interface_agreement.yaml`); alarm map and change catalog: `config/change_alarms.yaml`; code: `src/scorecard/alarms.py`.

A flag means an alarm does not reconcile with an approved change. It is not a finding against anyone.

## Summary

- **120 alarms** from both partners' feeds: Landlord 4 critical, 35 major, 5 minor, IT Partner 4 critical, 46 major, 26 minor.
- **12 approved changes** with impact declarations; 11 alarms expected under them.
- **3 out of scope and 1 out of window**, all on MOP-310 (Retorque A-side tap-off for rack A07), the change behind PIR-2026-001.
- **0 change conflicts** (two redundancy-reducing changes on connected equipment at once).
- **Notifications** under the new section 10, measured against what the partners sent under their current SLAs: Landlord 2 of 29 on time; IT Partner 4 of 50 on time. Every P1 was paged within 5 minutes, but P2 alarms get one call or email, and no notification names a change. That gap is what the clause closes.

## Rack A07, September 15: what the check would have shown

Reconciles with [PIR-2026-001](../docs/pir/PIR-2026-001.md) (same records and times).

- MOP-310 declared one asset, `BW-A-R1-PG-A2-A`, window 14:46Z to 17:16Z.
- 15:16Z: Tap-off TO-A07-A open on BW-A-R1-PG-A2-A. **Expected** (declared).
- 15:42Z: Tap-off TO-A07-B open on BW-A-R1-PG-A2-B. **Out of scope**: connected to BW-A-R1-PG-A2-A (power), not declared. The Customer is alerted at this second by its own check; the partner owes an NT-3 notification within 5 minutes.
- 15:42Z: Rack input power lost (both feeds) (Landlord). **Out of scope**.
- 15:42Z: Rack A07: 18 nodes not responding (IT Partner). **Out of scope**.
- 17:31Z: MOP-310 window has closed with this still in effect: Tap-off TO-A07-A open on BW-A-R1-PG-A2-A. **Out of window**: still in its maintenance state 2 h 06 min after the window closed. The PIR's factor F5 says nothing alerted on this; this alert would have.

What the partners actually sent (their current SLAs):

| Alarm | Owed by | Rule | Sent | Channels | Result |
|---|---|---|---|---|---|
| BW-A-R1-PG-A2-B: Tap-off breaker open | Landlord | NT-3+NT-2 | 15:49Z | phone | late |
| Rack A07: Rack input power lost (both feeds) | Landlord | NT-3+NT-1 | 15:43Z | email, page | incomplete |
| Rack A07: Rack outage | Landlord | NT-3 | open | none | missing |
| BW-A-R1-PG-A2-A: Change window overrun | Landlord | NT-3 | open | none | missing |

## Change work

| Change | Owner | Type | Window | Declared assets | Expected | Out of scope | Out of window |
|---|---|---|---|---|---|---|---|
| MOP-308 | Landlord | tapoff_energize | Sep 4 17:39Z to 19:39Z | BW-B-R1-PG-B1-B | 1 | 0 | 0 |
| MOP-303 | Landlord | cdu_filter | Sep 4 18:36Z to 20:36Z | CDU-B3 | 1 | 0 | 0 |
| MOP-307 | Landlord | vesda_test | Sep 5 16:55Z to 19:10Z | VESDA-B1 | 2 | 0 | 0 |
| CHG2040062 | IT Partner | tray_firmware | Sep 7 06:00Z to 10:00Z | rack A18 | 0 | 0 | 0 |
| MOP-304 | Landlord | cdu_filter | Sep 8 13:00Z to 15:00Z | CDU-B4 | 1 | 0 | 0 |
| MOP-301 | Landlord | cdu_filter | Sep 11 13:23Z to 15:23Z | CDU-B2 | 1 | 0 | 0 |
| MOP-309 | Landlord | tapoff_energize | Sep 13 17:24Z to 19:24Z | BW-B-R3-PG-B4-B | 1 | 0 | 0 |
| MOP-305 | Landlord | ups_pm | Sep 13 19:20Z to 23:20Z | UPS-A1 | 1 | 0 | 0 |
| CHG2040031 | IT Partner | tray_firmware | Sep 14 06:00Z to 10:00Z | rack A05 | 0 | 0 | 0 |
| MOP-310 | Landlord | tapoff_work | Sep 15 14:46Z to 17:16Z | BW-A-R1-PG-A2-A | 1 | 3 | 1 |
| MOP-302 | Landlord | cdu_filter | Sep 20 18:36Z to 20:36Z | CDU-A3 | 1 | 0 | 0 |
| MOP-306 | Landlord | ups_pm | Sep 23 18:51Z to 22:51Z | UPS-B3 | 1 | 0 | 0 |

## Alarms that do not reconcile with an approved change

| Alarm | Raised | Partner | Severity | Device | Alarm text | Change | Result | Why |
|---|---|---|---|---|---|---|---|---|
| ALM-0063 | Sep 15 15:42Z | Landlord | major | BW-A-R1-PG-A2-B | Tap-off TO-A07-B open on BW-A-R1-PG-A2-B | MOP-310 | Out of scope | Connected to BW-A-R1-PG-A2-A (power), not declared |
| ALM-0064 | Sep 15 15:42Z | Landlord | critical | Rack A07 | Rack input power lost (both feeds) | MOP-310 | Out of scope | Connected to BW-A-R1-PG-A2-A (power), not declared |
| ALM-0065 | Sep 15 15:42Z | IT Partner | critical | Rack A07 | Rack A07: 18 nodes not responding | MOP-310 | Out of scope | Connected to BW-A-R1-PG-A2-A (power), not declared |
| ALM-0120 | Sep 15 17:31Z | Landlord | major | BW-A-R1-PG-A2-A | MOP-310 window has closed with this still in effect: Tap-off TO-A07-A open on BW-A-R1-PG-A2-A | MOP-310 | Out of window | Still in its maintenance state 2 h 06 min after the window closed |

## Change conflicts

None in this month.

## Notifications owed under Interface Agreement section 10

Measured against each partner's delivery log. The sample month predates the clause, so this is the baseline it starts from.

| Measure | Party | Owed | On time | Late | Single channel or no change named | Missing | Actual | Target | NT-1 (critical) | NT-2 (major) | NT-3 (change work) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IA-KM-01 | Landlord | 29 | 2 | 16 | 9 | 2 | 6.9% | 99.0% | 2 of 3 | 0 of 24 | 0 of 4 |
| IA-KM-02 | IT Partner | 50 | 4 | 28 | 18 | 0 | 8.0% | 99.0% | 4 of 4 | 0 of 46 | 0 of 0 |

## Self-check against the answer key

4 of 4 expected flags found; 0 of 0 decoys flagged; 0 other flags. The sample has no planted cases (only the natural rack outage); planted cases are scored on 60 generated months with `python scripts/render_alarms.py --robustness 60`.

## How alarms are classified

1. **Expected:** a declared asset raises a declared alarm, at or below the declared severity, inside the window (15 minutes grace either side). An alarm another approved change declared is accounted for.
2. **Out of scope:** inside the window, an undeclared alarm or one too severe on a declared asset, or an alarm on connected equipment (redundant partner, or the load the asset serves, from the site model) of a kind the work could cause (power, cooling, fire, compute).
3. **Out of window:** a declared alarm up to 4 hours before the window, or a declared asset still in its maintenance state 15 minutes after the window closes (raised as a Customer-check alarm at that moment).
4. **Not change work:** everything else, including alarms during a window on equipment that is not connected.

