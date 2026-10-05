# Landlord Scorecard: Caprock Critical Facilities, LLC

Window 2026-08-31 to 2026-09-28. Measured from the Customer's read-only facility telemetry under the Interface Agreement, beside the Landlord's own weekly report. Synthetic data; all names fictional.

**Headline:** the Landlord reported every service level met. Measured: **4 Minimum defaults** (OT-CSL-05, OT-CSL-06, OT-CSL-07, OT-CSL-08), **6 S1 findings**, and **$94,400** in credits against rent.

## Critical Service Levels

| ID | Service level | Landlord reported | Measured | Expected / Minimum | Status | Credit | Basis |
|---|---|:-:|:-:|:-:|---|:-:|---|
| OT-CSL-01 | Rack Power Availability | 100.00% | 100.000% | 99.999% / 99.995% | Met Expected |  | 64 leased racks; minutes with at least one feed in tolerance |
| OT-CSL-02 | Power Redundancy Availability | 99.90% | 99.979% | 99.9% / 99.5% | Met Expected |  | 64 leased racks; minutes with both feeds in tolerance |
| OT-CSL-03 | Cooling Within Band at the Rack | 99.99% | 100.000% | 99.99% / 99.95% | Met Expected |  | No rack-level cooling excursion in the window |
| OT-CSL-04 | Critical Alarm Response | 98.00% | 100.000% | 98% / 95% | Met Expected |  | 2 of 2 P1 events acknowledged and attended in time (badge) |
| OT-CSL-05 | Redundancy Restored Within Target | 95.00% | 83.333% | 95% / 90% | **Minimum default** | $23,600 | 5 of 6 redundancy events restored within target (telemetry) |
| OT-CSL-06 | Preventive Maintenance On Time, Evidence-Verified | 98.00% | 88.889% | 98% / 95% | **Minimum default** | $23,600 | 16 of 18 tasks on time with evidence |
| OT-CSL-07 | Critical Work Under Approved MOP | 100.00% | 90.000% | 100% / 98% | **Minimum default** | $17,700 | 9 of 10 critical work events under an approved MOP |
| OT-CSL-08 | Record Integrity | 98.00% | 80.645% | 98% / 95% | **Minimum default** | $29,500 | 25 of 31 work orders and maintenance records reconcile |
| OT-CSL-09 | Qualified Staffing Fill | 98.00% | 100.000% | 98% / 95% | Met Expected |  | 168 of 168 rostered shifts badge-verified |
| OT-CSL-10 | Worst-Hall Cooling Within Band | 99.95% | 100.000% | 99.95% / 99.9% | Met Expected |  | No hall-level cooling excursion in the window |

## Key Measurements

| ID | Key measurement | Target | Measured | Result | Basis |
|---|---|:-:|:-:|:-:|---|
| OT-KM-01 | P2 Alarm Response (acknowledge 15 min, at equipment 30 min) | >= 95% | 85.7% | Missed | 6 of 7 P2 events acknowledged and attended in time (badge) |
| OT-KM-02 | Generator Monthly Tests Meeting NFPA 110 Load (30% for 30 min) | >= 100% | 85.7% | Missed | 6 of 7 monthly tests met 30% for 30 minutes (EMCP) |
| OT-KM-03 | Coolant Samples Within Specification | >= 100% | 100.0% | Met | 4 coolant samples, all within specification |
| OT-KM-04 | Annual Fuel Quality Tests On Schedule | >= 100% | n/a | n/a | No fuel quality test due in the window |
| OT-KM-05 | BMS Overrides or Alarm Inhibits Open Over 24 Hours Without a Change Reference | <= 0 items | 1 items | Missed | 1 override or inhibit held over 24 hours without a change reference |
| OT-KM-06 | Monitoring Feed Availability to the Customer | >= 99.9% | 100.0% | Met | No gap in the Customer's facility feeds |
| OT-KM-07 | Planned Maintenance Notified 10 Business Days Ahead | >= 100% | 77.8% | Missed | 7 of 9 MOPs approved at least 10 business days before the work |
| OT-KM-08 | Corrective Action Plans Closed On Time | >= 95% | n/a | n/a | No corrective action plan due in the window |

## Credits against rent

- OT-CSL-05: At-Risk Amount $118,000 (10% of $1,180,000) × 20% allocation = $23,600 = **$23,600**
- OT-CSL-06: At-Risk Amount $118,000 (10% of $1,180,000) × 20% allocation = $23,600 = **$23,600**
- OT-CSL-07: At-Risk Amount $118,000 (10% of $1,180,000) × 15% allocation = $17,700 = **$17,700**
- OT-CSL-08: At-Risk Amount $118,000 (10% of $1,180,000) × 25% allocation = $29,500 = **$29,500**
- **Payable: $94,400**

## Engine self-check

Detected **7 of 7** planted Landlord discrepancies, **0 false positives**. The engine cannot read the answer key.
