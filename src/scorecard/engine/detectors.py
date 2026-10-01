"""Detectors: one per discrepancy type in the SLA's finding_types.

Each detector reads only telemetry and vendor records through the Context and
returns Findings carrying the exact records that prove them. Severity and the
recommended corrective action come from the SLA (breach_severity.finding_types),
not from this file.

A finding means "the records do not reconcile", not "someone lied". Many
discrepancies turn out to be process errors; the finding starts the review.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Callable

from scorecard.engine.core import (
    XID_FAMILY, Context, Finding, ev, fmt_t, minutes_between,
)
from scorecard.measurement import split_tickets
from scorecard.sla_model import finding_type

TICKETS = "vendor/tickets.json"
DETECTORS: list[Callable[[Context], list[Finding]]] = []


def detector(fn: Callable[[Context], list[Finding]]) -> Callable[[Context], list[Finding]]:
    DETECTORS.append(fn)
    return fn


def new_finding(ctx: Context, type_id: str, summary: str, tickets: list[str], unit: str | None,
                observed_at, evidence: list[dict], **kw) -> Finding:
    ft = finding_type(ctx.sla, type_id)
    return Finding(type=type_id, title=ft["name"], summary=summary, tickets=tickets, unit=unit,
                   observed_at=observed_at, evidence=evidence, sla_refs=list(ft["sla_refs"]),
                   recommended_action=ft["action"], **kw)


def on_site_note(t: dict):
    return next((n for n in t["work_notes"] if n["text"].startswith("On site")), None)


# --------------------------------------------------------------------------- #
@detector
def detect_clock_shift(ctx: Context) -> list[Finding]:
    """Ticket opened well after the telemetry T0, so the vendor's clock started late."""
    out = []
    for t in ctx.tickets:
        t0, src, what = ctx.telemetry_t0(t)
        if t0 is None:
            continue
        delay = t["opened_at"] - t0
        if delay <= ctx.tolerance:
            continue
        target = ctx.restore_target[t["priority"]]
        vendor_min = minutes_between(t["reported_outage_start"], t["resolved_at"])
        true_min = minutes_between(t0, t["resolved_at"])
        hidden = vendor_min <= target < true_min
        out.append(new_finding(
            ctx, "clock_shift",
            f"Ticket opened {delay.total_seconds() / 60:.0f} minutes after the telemetry fault. "
            f"Vendor-reported restoration {vendor_min / 60:.1f} hrs; measured from T0 {true_min / 60:.1f} hrs "
            f"against the {target // 60}-hour {t['priority']} target"
            + (" (a breach hidden by the late start)." if hidden else "."),
            [t["number"]], t["_unit"], t0,
            [ev(src, t0, f"Fault signal: {what}"),
             ev(TICKETS, t["opened_at"], f"{t['number']} opened; reported outage start {fmt_t(t['reported_outage_start'])}"),
             ev(TICKETS, t["resolved_at"], f"{t['number']} resolved")],
            metrics={"delay_min": round(delay.total_seconds() / 60, 1), "vendor_restore_min": round(vendor_min, 1),
                     "measured_restore_min": round(true_min, 1), "target_min": target,
                     "gpus": ctx.fault_classes[t["_class"]]["capacity_impact"]["gpus"]},
        ))
    return out


@detector
def detect_ticket_split(ctx: Context) -> list[Finding]:
    """One Ticket of Record (TR-1/TR-2) spread over several vendor tickets (TR-6)."""
    out = []
    for fc_id, tors in ctx.tors.items():
        fc = ctx.fault_classes[fc_id]
        for tor in tors:
            if not split_tickets(tor):
                continue
            refs = list(dict.fromkeys(tor.vendor_ticket_refs))
            first = ctx.ticket_by_no[refs[0]]
            target = ctx.restore_target[first["priority"]]
            rule = "TR-1 (early failure)" if tor.early_failures else "TR-2 (reopen within stability window)"
            vendor_parts = [minutes_between(ctx.ticket_by_no[n]["reported_outage_start"], ctx.ticket_by_no[n]["resolved_at"]) for n in refs]
            evidence = [ev("telemetry/scheduler_node_states.jsonl" if fc_id == "FC-GPU" else "telemetry/ufm_port_events.jsonl",
                           o.t0, f"Down interval {fmt_t(o.t0)} to {fmt_t(o.rts)}") for o in tor.outages]
            evidence += [ev(TICKETS, ctx.ticket_by_no[n]["opened_at"],
                            f"{n} opened; vendor-reported restoration {m / 60:.1f} hrs") for n, m in zip(refs, vendor_parts)]
            out.append(new_finding(
                ctx, "ticket_split",
                f"{tor.unit_key} failed again {_gap_text(tor)} after return to service, and the follow-up was logged as "
                f"a new ticket. Under {rule} it is one Ticket of Record: measured restoration "
                f"{tor.measured_restore_min / 60:.1f} hrs against the {target // 60}-hour target "
                f"(vendor tickets show {' and '.join(f'{m / 60:.1f}' for m in vendor_parts)} hrs).",
                refs, tor.unit_key, tor.t0, evidence,
                metrics={"measured_restore_min": round(tor.measured_restore_min, 1), "target_min": target,
                         "gpus": fc["capacity_impact"]["gpus"], "early_failures": tor.early_failures, "reopens": tor.reopens},
            ))
    return out


def _gap_text(tor) -> str:
    gaps = [minutes_between(a.rts, b.t0) for a, b in zip(tor.outages, tor.outages[1:]) if a.rts and b.t0 > a.rts]
    if not gaps:
        return "shortly"
    g = min(gaps)
    return f"{g:.0f} minutes" if g < 120 else f"{g / 60:.1f} hours"


@detector
def detect_ghost_engagement(ctx: Context) -> list[Finding]:
    """'On site' work note earlier than the technician's badge-in to the hall."""
    out = []
    for t in ctx.tickets:
        note = on_site_note(t)
        if note is None:
            continue
        door = f"HALL-{t['hall'][-1]}"
        t0 = ctx.telemetry_t0(t)[0] or t["opened_at"]
        entries = [b["timestamp"] for b in ctx.badges_by_person.get(t["assigned_to"], [])
                   if b["door"] == door and b["direction"] == "in"
                   and t0 - timedelta(minutes=5) <= b["timestamp"] <= t["resolved_at"]]
        person = ctx.personnel.get(t["assigned_to"], {}).get("name", t["assigned_to"])
        if not entries:
            gap_text, first_in = "with no badge-in to the hall at all", None
        else:
            first_in = min(entries)
            if first_in - note["at"] <= ctx.tolerance:
                continue
            gap_text = f"{minutes_between(note['at'], first_in):.0f} minutes before {person} badged into {door}"
        target = ctx.engaged_target.get(t["priority"])
        claimed = minutes_between(t0, note["at"])
        actual = minutes_between(t0, first_in) if first_in else None
        out.append(new_finding(
            ctx, "ghost_engagement",
            f"Work note claims on site at {fmt_t(note['at'])}, {gap_text}. "
            f"Claimed engagement {claimed:.0f} min after T0; badge-verified "
            + (f"{actual:.0f} min" if actual is not None else "never")
            + (f" against the {target}-minute target." if target else "."),
            [t["number"]], t["_unit"], note["at"],
            [ev(TICKETS, note["at"], f"{t['number']} work note by {note['author']}: \"{note['text']}\""),
             ev("access/badge_events.csv", first_in, f"First {door} badge-in by {person} ({t['assigned_to']})"
                if first_in else f"No {door} badge-in by {person} between T0 and resolution")],
            metrics={"claimed_engaged_min": round(claimed, 1), "badge_engaged_min": round(actual, 1) if actual else None,
                     "target_min": target},
        ))
    return out


@detector
def detect_skipped_validation(ctx: Context) -> list[Finding]:
    """Unit returned to service without the full Return-to-Service checklist on record."""
    out = []
    for t in ctx.tickets:
        target, vclass = ctx.validation_target(t)
        if target is None:
            continue
        required = ctx.check_ids[vclass]
        start = ctx.telemetry_t0(t)[0] or t["opened_at"]
        done = {h["check"] for h in ctx.health_by_target.get(target, [])
                if start <= h["started_at"] and h["completed_at"] <= t["resolved_at"] + timedelta(minutes=15)
                and h["result"] == "pass"}
        missing = sorted(required - done)
        if not missing:
            continue
        claim = next((n for n in reversed(t["work_notes"]) if "Validation complete" in n["text"]), None)
        out.append(new_finding(
            ctx, "skipped_validation",
            f"{t['_unit']} returned to service with {len(missing)} of {len(required)} required '{vclass}' checks "
            f"missing ({', '.join(missing)})" + ("; the ticket still claims validation passed." if claim else "."),
            [t["number"]], t["_unit"], t["resolved_at"],
            [ev("telemetry/health_checks.jsonl", None, f"Passed checks on {target} for this repair: "
                + (", ".join(sorted(done)) if done else "none")),
             ev(TICKETS, claim["at"] if claim else t["resolved_at"],
                f"{t['number']}: \"{claim['text']}\"" if claim else f"{t['number']} resolved")],
            metrics={"missing_checks": missing, "required_checks": sorted(required)},
        ))
    return out


@detector
def detect_unverified_swap(ctx: Context) -> list[Finding]:
    """Ticket records an installed serial that never appeared in BMC inventory."""
    tracked = {"Compute tray", "NVLink switch tray", "PSU (5.5 kW)", "Power shelf"}
    rma_by_serial = {r["serial"]: r for r in ctx.rma}
    out = []
    for t in ctx.tickets:
        for part in t["parts_used"]:
            if part["part"] not in tracked or not part["installed_serial"]:
                continue
            if part["installed_serial"] in ctx.inventory_new_values:
                continue
            evidence = [ev(TICKETS, t["resolved_at"], f"{t['number']} parts: removed {part['removed_serial']}, "
                                                       f"installed {part['installed_serial']} at {part['location']}"),
                        ev("telemetry/redfish_inventory_changes.jsonl", None,
                           f"No SerialNumber change to {part['installed_serial']} observed on any BMC")]
            later = [e for e in ctx.xid_by_host.get(t["configuration_item"], [])
                     if e["timestamp"] > t["resolved_at"] and e.get("tray_serial") == part["removed_serial"]]
            if later:
                evidence.append(ev("telemetry/dcgm_xid_events.jsonl", later[0]["timestamp"],
                                   f"GPU telemetry still reports the 'removed' serial {part['removed_serial']}"))
            rma = rma_by_serial.get(part["removed_serial"])
            if rma:
                evidence.append(ev("vendor/rma_shipments.csv", rma["shipped_at"],
                                   f"RMA shipped for {part['removed_serial']}, which inventory shows is still installed"))
            out.append(new_finding(
                ctx, "unverified_swap",
                f"{t['number']} records a {part['part'].lower()} replacement at {part['location']}, but BMC inventory "
                f"never showed the installed serial {part['installed_serial']}; the original part appears to still be in place.",
                [t["number"]], t["_unit"], t["resolved_at"], evidence,
                metrics={"claimed_serial": part["installed_serial"], "removed_serial": part["removed_serial"]},
            ))
    return out


@detector
def detect_phantom_fix(ctx: Context) -> list[Finding]:
    """Reseat closed as fixed; the same fault family recurred inside the recurrence window (TR-5)."""
    out = []
    tors = ctx.tors["FC-GPU"]
    for child in tors:
        if child.parent_index is None:
            continue
        parent = tors[child.parent_index]
        if not parent.vendor_ticket_refs:
            continue
        pt = ctx.ticket_by_no[parent.vendor_ticket_refs[-1]]
        if pt["parts_used"] and any(p["installed_serial"] for p in pt["parts_used"]):
            continue                                   # a part was replaced: not a reseat
        def first_xid(tor):
            xs = [e for e in ctx.xid_by_host.get(tor.unit_key, []) if tor.t0 - timedelta(minutes=10) <= e["timestamp"] <= tor.t0 + timedelta(minutes=10)]
            return min(xs, key=lambda e: e["timestamp"]) if xs else None
        px, cx = first_xid(parent), first_xid(child)
        if not px or not cx or XID_FAMILY.get(px["xid"]) != XID_FAMILY.get(cx["xid"]):
            continue
        gap_h = (child.t0 - parent.final_rts).total_seconds() / 3600
        out.append(new_finding(
            ctx, "phantom_fix",
            f"{pt['number']} closed {parent.unit_key} as '{pt['close_code']}' with no part replaced; the same "
            f"{XID_FAMILY[px['xid']]} fault (XID {cx['xid']}) recurred {gap_h:.0f} hours after return to service, "
            f"inside the recurrence window (TR-5).",
            [pt["number"]] + list(child.vendor_ticket_refs), parent.unit_key, child.t0,
            [ev("telemetry/dcgm_xid_events.jsonl", px["timestamp"], f"Original fault: XID {px['xid']} ({px['message']})"),
             ev(TICKETS, pt["resolved_at"], f"{pt['number']} closed as '{pt['close_code']}', no part used"),
             ev("telemetry/dcgm_xid_events.jsonl", cx["timestamp"], f"Recurrence: XID {cx['xid']} ({cx['message']})")],
            metrics={"recurrence_gap_hours": round(gap_h, 1)},
        ))
    return out


@detector
def detect_wrong_end_optic(ctx: Context) -> list[Finding]:
    """Optic replaced on one end; errors continued on the same link afterwards."""
    stability = timedelta(hours=ctx.fault_classes["FC-LINK"]["stability_window_hours"])
    out = []
    for t in ctx.tickets:
        if t["category"] != "optic_link":
            continue
        swapped = [p for p in t["parts_used"] if p["part"].endswith("optic") and p["installed_serial"]]
        if not swapped:
            continue
        side = "switch" if "(switch side)" in swapped[0]["location"] else "host" if "(host side)" in swapped[0]["location"] else "unknown"
        after = [e for e in ctx.ufm_by_link.get(t["_unit"], [])
                 if t["resolved_at"] < e["timestamp"] <= t["resolved_at"] + stability
                 and e["event"] in ("symbol_errors", "link_down", "symbol_error_threshold")]
        if not after:
            continue
        follow = [x for x in ctx.tickets_by_unit[t["_unit"]] if x["opened_at"] > t["resolved_at"]]
        evidence = [ev(TICKETS, t["resolved_at"], f"{t['number']} replaced the {side}-side optic and closed the ticket"),
                    ev("telemetry/ufm_port_events.jsonl", after[0]["timestamp"],
                       f"{len(after)} error events on {t['_unit']} within {stability.total_seconds() / 3600:.0f} hrs after closure; "
                       f"first: {after[0]['event']} ({after[0]['count']})")]
        if follow:
            fp = [p for p in follow[0]["parts_used"] if p["installed_serial"]]
            evidence.append(ev(TICKETS, follow[0]["opened_at"], f"Follow-up {follow[0]['number']}"
                               + (f" replaced the optic at {fp[0]['location']}" if fp else "")))
        out.append(new_finding(
            ctx, "wrong_end_optic",
            f"{t['number']} replaced the {side}-side optic on {t['_unit']}, but link errors resumed "
            f"{minutes_between(t['resolved_at'], after[0]['timestamp']):.0f} minutes after closure. "
            "The fault was likely at the other end; under TR-2 the original ticket should have reopened.",
            [t["number"]] + [f["number"] for f in follow[:1]], t["_unit"], after[0]["timestamp"], evidence,
            metrics={"error_events_after_close": len(after)},
        ))
    return out


@detector
def detect_lemon_unit(ctx: Context) -> list[Finding]:
    """Three or more Tickets of Record on one unit within 30 days, with no RMA escalation."""
    out = []
    by_unit = defaultdict(list)
    for tor in ctx.tors["FC-GPU"]:
        by_unit[tor.unit_key].append(tor)
    for unit, tors in by_unit.items():
        tors.sort(key=lambda x: x.t0)
        for i in range(len(tors)):
            group = [x for x in tors[i:] if x.t0 - tors[i].t0 <= timedelta(days=30)]
            if len(group) < 3:
                continue
            nums = list(dict.fromkeys(n for x in group for n in x.vendor_ticket_refs))
            escalated = any("Escalated" in note["text"] and "RMA" in note["text"]
                            for n in nums for note in ctx.ticket_by_no[n]["work_notes"])
            if escalated:
                break
            out.append(new_finding(
                ctx, "lemon_unit",
                f"{unit} needed {len(group)} repairs in {(group[-1].t0 - group[0].t0).days} days "
                f"({', '.join(nums)}) with no OEM RMA escalation. KM-09 requires escalation within 2 business days.",
                nums, unit, group[-1].t0,
                [ev(TICKETS, ctx.ticket_by_no[n]["opened_at"],
                    f"{n}: {ctx.ticket_by_no[n]['short_description']}, closed '{ctx.ticket_by_no[n]['close_code']}'") for n in nums],
                metrics={"repairs_30d": len(group)},
            ))
            break
    return out


@detector
def detect_staffing_gap(ctx: Context) -> list[Finding]:
    """Rostered technicians with no badge-in during their shift."""
    out = []
    shifts = defaultdict(list)
    for r in ctx.roster:
        shifts[(r["shift_start"], r["shift_end"], r["shift"], r["crew"])].append(r)
    for (start, end, shift, crew), rows in sorted(shifts.items()):
        if end <= ctx.window_start or start >= ctx.window_end:
            continue
        missing = [r for r in rows if not any(
            b["door"] == "OPS-MAIN" and b["direction"] == "in" and start - timedelta(hours=1) <= b["timestamp"] <= end
            for b in ctx.badges_by_person.get(r["person_id"], []))]
        if not missing:
            continue
        names = ", ".join(f"{r['name']} ({r['person_id']})" for r in missing)
        techs = [r for r in rows if r["role"] == "technician"]
        present = len(techs) - sum(1 for r in missing if r["role"] == "technician")
        out.append(new_finding(
            ctx, "staffing_gap",
            f"{shift.title()} shift starting {fmt_t(start)} (crew {crew}): {len(missing)} rostered "
            f"{'person' if len(missing) == 1 else 'people'} never badged in ({names}). "
            f"{present} of {len(techs)} committed technicians were on site.",
            [], f"Crew {crew}", start,
            [ev("vendor/roster.csv", start, f"Roster lists {len(rows)} people for this shift"),
             ev("access/badge_events.csv", None, f"No OPS-MAIN badge-in for {names} between one hour before and the end of the shift")],
            metrics={"missing": len(missing), "technicians_present": present, "technicians_committed": len(techs)},
            keys={"shift_start": start, "missing_person_ids": sorted(r["person_id"] for r in missing)},
        ))
    return out


@detector
def detect_spares_drift(ctx: Context) -> list[Finding]:
    """Parts recorded as used on a ticket with no matching issue in the spares ledger."""
    issued = defaultdict(int)
    for row in ctx.ledger:
        if row["transaction"] == "issue" and row["ticket"]:
            issued[(row["ticket"], row["fru"])] += -row["qty"]
    variances = [c for c in ctx.cycle_counts if c["system_qty"] != c["counted_qty"]]
    out = []
    for t in ctx.tickets:
        used = defaultdict(int)
        for p in t["parts_used"]:
            used[p["part"]] += 1
        for fru, n in used.items():
            if issued[(t["number"], fru)] >= n:
                continue
            count = next((c for c in variances if c["fru"] == fru and c["counted_at"] > t["resolved_at"] - timedelta(days=1)), None)
            evidence = [ev(TICKETS, t["resolved_at"], f"{t['number']} used {n} x {fru}"),
                        ev("vendor/spares_ledger.csv", None, f"{issued[(t['number'], fru)]} issue(s) of {fru} recorded against {t['number']}")]
            if count:
                evidence.append(ev("vendor/spares_cycle_counts.csv", count["counted_at"],
                                   f"Cycle count {fru}: ledger {count['system_qty']}, counted {count['counted_qty']}"))
            out.append(new_finding(
                ctx, "spares_drift",
                f"{t['number']} used {n} x {fru} but the spares ledger records {issued[(t['number'], fru)]} issue(s)"
                + (f"; the next cycle count was {count['system_qty'] - count['counted_qty']} short." if count else "."),
                [t["number"]], fru, t["resolved_at"], evidence,
            ))
    return out


@detector
def detect_unauthorized_change(ctx: Context) -> list[Finding]:
    """Firmware changes with no approved change record covering that rack and time."""
    by_rack = defaultdict(list)
    for e in ctx.inventory:
        if e["property"] != "FirmwareVersion":
            continue
        covered = any(c["rack"] == e["rack"] and c["state"] == "Approved"
                      and c["window_start"] <= e["observed_at"] <= c["window_end"] for c in ctx.cab)
        if not covered:
            by_rack[e["rack"]].append(e)
    out = []
    for rack, events in sorted(by_rack.items()):
        events.sort(key=lambda e: e["observed_at"])
        versions = sorted({f"{e['old_value']} -> {e['new_value']}" for e in events})
        out.append(new_finding(
            ctx, "unauthorized_change",
            f"Firmware changed ({', '.join(versions)}) on {len(events)} components in rack {rack} between "
            f"{fmt_t(events[0]['observed_at'])} and {fmt_t(events[-1]['observed_at'])} with no approved change record.",
            [], f"Rack {rack}", events[0]["observed_at"],
            [ev("telemetry/redfish_inventory_changes.jsonl", events[0]["observed_at"],
                f"{len(events)} FirmwareVersion changes in rack {rack}, first on {events[0]['host'] or events[0]['resource']}"),
             ev("customer/cab_changes.json", None, f"No approved change covers rack {rack} at these times")],
            metrics={"components_changed": len(events)},
            keys={"rack": rack},
        ))
    return out
