"""InfiniBand fabric events that are symptoms of a rack power loss, not link faults.

When a rack loses both feeds, every back-end link of its trays drops with the trays' power and comes back when they
power on; the fabric manager logs each one ("Link is Down" / "Link is Up"). Those 72 events are the rack outage seen
from the fabric. Fault attribution, the link clocks, and the alarm board treat them as part of that rack outage
(the scheduler's "NotResponding (rack input power lost)"), never as link faults of their own.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

LEAD = timedelta(minutes=2)      # the link drops seconds before the scheduler marks the node NotResponding


def _t(x: Any) -> datetime:
    return x if isinstance(x, datetime) else datetime.fromisoformat(str(x).replace("Z", "+00:00"))


def power_loss_spans(scheduler: Iterable[dict]) -> dict[str, list[tuple[datetime, datetime]]]:
    """Per node: (down - 2 min, back in service) for each scheduler "rack input power lost" span."""
    out: dict[str, list[tuple[datetime, datetime]]] = {}
    ev = sorted(scheduler, key=lambda e: (_t(e["timestamp"]), e["node"]))
    open_: dict[str, datetime] = {}
    for e in ev:
        if e["state"] == "down" and "rack input power lost" in e.get("reason", ""):
            open_[e["node"]] = _t(e["timestamp"])
        elif e["state"] == "idle" and e["node"] in open_:
            out.setdefault(e["node"], []).append((open_.pop(e["node"]) - LEAD, _t(e["timestamp"])))
    for node, t in open_.items():
        out.setdefault(node, []).append((t - LEAD, datetime.max.replace(tzinfo=t.tzinfo)))
    return out


def _key(e: dict) -> tuple:
    return e["switch"], e["port"], e["event"], e["timestamp"]


def power_loss_links(ufm: Iterable[dict], scheduler: Iterable[dict]) -> set[tuple]:
    """The link events that are a rack power loss seen from the fabric: each link's drop within 2 minutes of its
    tray's power loss, and that link's next Link is Up (the trays powering on). A link that drops again after the
    trays power on, while the scheduler still holds them out of service, is a fault of its own and is not folded."""
    spans = power_loss_spans(scheduler)
    out: set[tuple] = set()
    down: set[tuple] = set()
    for e in sorted(ufm, key=lambda e: _t(e["timestamp"])):
        port = (e["switch"], e["port"])
        if e["event"] == "link_down" and port not in down:
            t = _t(e["timestamp"])
            if any(a <= t <= a + 2 * LEAD for a, _ in spans.get(e.get("peer_host", ""), [])):
                out.add(_key(e))
                down.add(port)
        elif e["event"] == "link_up" and port in down:
            out.add(_key(e))
            down.discard(port)
    return out


def peer_power_lost(event: dict, lost: set[tuple]) -> bool:
    """True for a link event that is its tray's rack power loss (from power_loss_links)."""
    return _key(event) in lost
