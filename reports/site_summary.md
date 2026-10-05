# Site Summary: Site AUS-1

Window 2026-08-31 to 2026-09-28. Each partner is measured against its own SLA from the Customer's Telemetry of Record; outages that cross the demarcation are attributed under the Interface Agreement. Synthetic data; all names fictional.

| | IT Partner (Ridgeline) | Landlord (Caprock) |
|---|:-:|:-:|
| Self-report | Every SLA met or minor exceptions | Every SLA met |
| Minimum defaults (measured) | 4 | 4 |
| Credits payable | $188,700 | $106,200 (against rent) |
| Findings (S1) | 18 (14) | 8 (7) |
| Engine self-check | 17 of 17, 0 false positives | 8 of 8, 0 false positives |

## Outages that crossed the demarcation

**Rack A07 lost both feeds at the tap-offs (TO-A07-B opened while the other side was open).** Telemetry attributes it to the **Landlord** (FA-1): both of the rack's feeds were out at the tap-offs from 2026-09-15 15:42 UTC until the Landlord's handoff at 2026-09-15 19:06 UTC. Under FA-3 the IT Partner's clock started at the handoff; its ticket INC3900001 validated the rack and returned it to service at 2026-09-15 20:01 UTC.

## What attribution changed for the IT Partner

The same telemetry, scored with the IT Partner's clock starting at the power loss instead of the Landlord's handoff:

| | With attribution (contract) | Without attribution |
|---|:-:|:-:|
| Minimum defaults | 4 | 5 |
| Credits payable | $188,700 | $222,000 |
| CSL-03 P1 restoration within 4 hours | 100.0% | 66.7% |
| CSL-12 worst-rack availability | 99.489% | 99.356% |

Without attribution the IT Partner would be charged for hours the Landlord's equipment kept the rack dark. With it, each party is charged only for its own side of the demarcation.
