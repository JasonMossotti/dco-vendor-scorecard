"""Measurement rules from the SLA's Ticket Handling section, as code.

This module is the reference implementation of how outages on one Service Unit
become Tickets of Record, so the Supplier and the Customer compute restoration
time the same way:

* TR-1 Early failure: a fault within ``early_failure_minutes`` of Validated RTS
  voids that restore. The clock runs continuously from the original T0.
* TR-2 Reopen: a fault within the fault class's stability window reopens the
  ticket. Restoration time is the cumulative downtime of every down interval.
* TR-3 Closure: a ticket closes only after a Validated RTS survives the full
  stability window.
* TR-5 Linked recurrence: a fault after the stability window but within the
  recurrence window is a new, linked ticket with its own clock, and the original
  counts as a First-Time Fix failure.

Input is telemetry-derived outages (T0 and Validated RTS per fault), never
vendor ticket boundaries, which is what makes ticket splitting (TR-6) visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable


@dataclass(frozen=True)
class Outage:
    """One telemetry-observed down period on a Service Unit."""

    unit_key: str
    t0: datetime
    rts: datetime | None          # Validated RTS; None while still down
    refs: tuple[str, ...] = ()    # Vendor ticket numbers or event IDs, for traceability


@dataclass
class TicketOfRecord:
    unit_key: str
    fault_class: str
    t0: datetime
    intervals: list[list[datetime | None]] = field(default_factory=list)  # [start, end] down intervals
    outages: list[Outage] = field(default_factory=list)
    early_failures: int = 0
    reopens: int = 0
    parent_index: int | None = None   # Index of the ticket this one is linked to (TR-5)
    has_linked_child: bool = False
    status: str = "open"              # open | monitoring | closed

    @property
    def final_rts(self) -> datetime | None:
        return self.intervals[-1][1] if self.intervals else None

    @property
    def measured_restore_min(self) -> float | None:
        """Cumulative downtime across all down intervals (TR-1 and TR-2 applied)."""
        if any(end is None for _, end in self.intervals):
            return None
        return sum((end - start).total_seconds() for start, end in self.intervals) / 60.0

    @property
    def elapsed_min(self) -> float | None:
        """Wall-clock time from original T0 to final Validated RTS."""
        return None if self.final_rts is None else (self.final_rts - self.t0).total_seconds() / 60.0

    @property
    def first_time_fix(self) -> bool:
        return self.early_failures == 0 and self.reopens == 0 and not self.has_linked_child

    @property
    def vendor_ticket_refs(self) -> list[str]:
        return [r for o in self.outages for r in o.refs]


def fault_class(sla: dict[str, Any], class_id: str) -> dict[str, Any]:
    for fc in sla["measurement_spec"]:
        if fc["id"] == class_id:
            return fc
    raise KeyError(f"Unknown fault class {class_id}")


def build_tickets_of_record(
    sla: dict[str, Any],
    class_id: str,
    outages: Iterable[Outage],
    as_of: datetime,
) -> list[TicketOfRecord]:
    """Group one fault class's outages into Tickets of Record per Service Unit Key."""
    fc = fault_class(sla, class_id)
    early = timedelta(minutes=sla["ticket_handling"]["stability"]["early_failure_minutes"])
    stability = timedelta(hours=fc["stability_window_hours"])
    recurrence = timedelta(days=fc["recurrence_window_days"])

    by_unit: dict[str, list[Outage]] = {}
    for o in outages:
        by_unit.setdefault(o.unit_key, []).append(o)

    tickets: list[TicketOfRecord] = []
    for unit in sorted(by_unit):
        current: TicketOfRecord | None = None
        for o in sorted(by_unit[unit], key=lambda x: x.t0):
            if current is not None:
                last_rts = current.final_rts
                if last_rts is None or o.t0 <= last_rts:
                    # Overlapping fault while still down: same outage, extend it.
                    current.outages.append(o)
                    if o.rts is None or (last_rts is not None and o.rts > last_rts):
                        current.intervals[-1][1] = o.rts
                    continue
                gap = o.t0 - last_rts
                if gap <= early:                       # TR-1: restore void, clock continuous
                    current.intervals[-1][1] = o.rts
                    current.outages.append(o)
                    current.early_failures += 1
                    continue
                if gap <= stability:                   # TR-2: reopen, cumulative downtime
                    current.intervals.append([o.t0, o.rts])
                    current.outages.append(o)
                    current.reopens += 1
                    continue
                parent_idx = len(tickets) - 1 if gap <= recurrence else None   # TR-5
                if parent_idx is not None:
                    current.has_linked_child = True
                current = None
            else:
                parent_idx = None
            current = TicketOfRecord(unit_key=unit, fault_class=class_id, t0=o.t0,
                                     intervals=[[o.t0, o.rts]], outages=[o], parent_index=parent_idx)
            tickets.append(current)

    for t in tickets:                                  # TR-3: closure only after a stable window
        if t.final_rts is None:
            t.status = "open"
        elif as_of < t.final_rts + stability:
            t.status = "monitoring"
        else:
            t.status = "closed"
    return tickets


def split_tickets(tor: TicketOfRecord) -> bool:
    """TR-6: True when one Ticket of Record was spread across several vendor tickets."""
    return len(set(tor.vendor_ticket_refs)) > 1 and (tor.early_failures > 0 or tor.reopens > 0)
