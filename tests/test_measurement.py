"""Tests for the Ticket Handling rules (TR-1 to TR-6) in scorecard.measurement.

Each test is a scenario a site lead would recognize. The repair is a P2 GPU
fault on a compute tray: restore target 8 hours, stability window 24 hours,
recurrence window 7 days, early-failure window 60 minutes.
"""

from datetime import datetime, timedelta, timezone

import pytest

from scorecard.measurement import Outage, build_tickets_of_record, fault_class, split_tickets
from scorecard.sla_model import load_sla

T0 = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)
M = timedelta(minutes=1)
LATER = T0 + timedelta(days=60)


@pytest.fixture(scope="module")
def sla():
    return load_sla()


def two_outages(gap: timedelta, first=7 * H, second=3 * H, refs=("INC-1", "INC-2")):
    rts1 = T0 + first
    t1 = rts1 + gap
    return [Outage("a14-ct07", T0, rts1, (refs[0],)), Outage("a14-ct07", t1, t1 + second, (refs[1],))]


def test_single_clean_repair(sla):
    [t] = build_tickets_of_record(sla, "FC-GPU", [Outage("a14-ct07", T0, T0 + 5 * H)], as_of=LATER)
    assert t.measured_restore_min == 300
    assert t.first_time_fix and t.status == "closed"


def test_tr1_refault_10_minutes_later_is_continuous(sla):
    """The exact loophole: up 10 minutes, new ticket, clock restarts. Not anymore."""
    tickets = build_tickets_of_record(sla, "FC-GPU", two_outages(10 * M), as_of=LATER)
    assert len(tickets) == 1
    t = tickets[0]
    assert t.early_failures == 1
    assert t.measured_restore_min == pytest.approx(7 * 60 + 10 + 3 * 60)  # uptime counts as downtime
    assert not t.first_time_fix
    assert split_tickets(t)


def test_tr2_refault_6_hours_later_is_cumulative(sla):
    [t] = build_tickets_of_record(sla, "FC-GPU", two_outages(6 * H), as_of=LATER)
    assert t.reopens == 1 and t.early_failures == 0
    assert t.measured_restore_min == pytest.approx(10 * 60)              # 7 h + 3 h, uptime excluded
    assert t.elapsed_min == pytest.approx(16 * 60)
    assert split_tickets(t)


def test_tr5_refault_3_days_later_is_linked_child(sla):
    parent, child = build_tickets_of_record(sla, "FC-GPU", two_outages(timedelta(days=3)), as_of=LATER)
    assert parent.measured_restore_min == 7 * 60 and child.measured_restore_min == 3 * 60
    assert child.parent_index == 0
    assert not parent.first_time_fix          # parent fails First-Time Fix
    assert not split_tickets(parent)          # separate tickets are correct here


def test_refault_after_recurrence_window_is_independent(sla):
    a, b = build_tickets_of_record(sla, "FC-GPU", two_outages(timedelta(days=10)), as_of=LATER)
    assert b.parent_index is None and a.first_time_fix


def test_boundaries_are_inclusive(sla):
    early = sla["ticket_handling"]["stability"]["early_failure_minutes"]
    [t] = build_tickets_of_record(sla, "FC-GPU", two_outages(early * M), as_of=LATER)
    assert t.early_failures == 1
    stab = fault_class(sla, "FC-GPU")["stability_window_hours"]
    [t] = build_tickets_of_record(sla, "FC-GPU", two_outages(stab * H), as_of=LATER)
    assert t.reopens == 1


def test_bouncing_unit_accumulates(sla):
    """A unit that keeps coming back and falling over stays on one ticket."""
    outs, t = [], T0
    for _ in range(4):
        outs.append(Outage("a14-ct07", t, t + 2 * H, ("INC",)))
        t = t + 2 * H + 3 * H                  # up 3 hours, then fails again
    [tor] = build_tickets_of_record(sla, "FC-GPU", outs, as_of=LATER)
    assert tor.reopens == 3 and tor.measured_restore_min == 4 * 2 * 60


def test_status_monitoring_until_stability_window_passes(sla):
    rts = T0 + 5 * H
    [t] = build_tickets_of_record(sla, "FC-GPU", [Outage("x", T0, rts)], as_of=rts + 2 * H)
    assert t.status == "monitoring"
    [t] = build_tickets_of_record(sla, "FC-GPU", [Outage("x", T0, rts)], as_of=rts + 25 * H)
    assert t.status == "closed"


def test_still_down_is_open(sla):
    [t] = build_tickets_of_record(sla, "FC-GPU", [Outage("x", T0, None)], as_of=T0 + H)
    assert t.status == "open" and t.measured_restore_min is None


def test_overlapping_faults_merge(sla):
    outs = [Outage("x", T0, T0 + 4 * H), Outage("x", T0 + H, T0 + 5 * H)]
    [t] = build_tickets_of_record(sla, "FC-GPU", outs, as_of=LATER)
    assert t.measured_restore_min == 300 and t.reopens == 0


def test_units_are_independent(sla):
    outs = [Outage("a", T0, T0 + H), Outage("b", T0 + H + 5 * M, T0 + 2 * H)]
    assert len(build_tickets_of_record(sla, "FC-GPU", outs, as_of=LATER)) == 2


def test_cdu_has_longer_stability_window(sla):
    """Rotating equipment gets 72 hours: a 2-day refault reopens a Landlord CDU work order but not a GPU ticket.

    The same ticket handling code measures both partners; only the SLA file differs.
    """
    from scorecard.sla_model import PARTNER_FILES
    landlord = load_sla(PARTNER_FILES["landlord"])
    gap = timedelta(days=2)
    [cdu] = build_tickets_of_record(landlord, "OT-FC-CDU", two_outages(gap), as_of=LATER)
    assert cdu.reopens == 1
    assert len(build_tickets_of_record(sla, "FC-GPU", two_outages(gap), as_of=LATER)) == 2
