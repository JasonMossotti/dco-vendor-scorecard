"""Poll every configured device and turn readings into records in the dataset contract.

Each device keeps its last known state; a record is emitted when something
changes (a pump's health, a busway leaving tolerance, a leak alarm), plus one
reading per poll for running generators, matching what the synthetic
generator writes. Every poll also writes a feed-health record, so a device
that stops answering becomes a measured gap (OT-KM-06), not a silent one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .config import secret

UTC = timezone.utc


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class DeviceState:
    last: dict[Any, Any] = field(default_factory=dict)
    failures: int = 0
    next_attempt: datetime | None = None


class Collector:
    def __init__(self, config: dict[str, Any], clock: Callable[[], datetime] | None = None):
        self.cfg = config
        self.clock = clock or (lambda: datetime.now(UTC))
        self.devices = config["devices"]
        self.state = {d["name"]: DeviceState() for d in self.devices}

    # ------------------------------------------------------------------ polling
    def poll_once(self) -> dict[str, list[dict[str, Any]]]:
        """One pass over every device. Returns records keyed by dataset file."""
        now = self.clock()
        out: dict[str, list[dict[str, Any]]] = {}
        for d in self.devices:
            st = self.state[d["name"]]
            if st.next_attempt and now < st.next_attempt:
                continue                                  # backing off a device that is not answering
            started = datetime.now(UTC)
            try:
                records = getattr(self, f"_poll_{d['kind']}")(d, st, now)
                for path, rec in records:
                    out.setdefault(path, []).append(rec)
                st.failures, st.next_attempt = 0, None
                ok, err = True, None
            except Exception as exc:                      # one bad device never stops the others
                st.failures += 1
                backoff = min(self.cfg["poll_interval_s"] * 2 ** st.failures, self.cfg["max_backoff_s"])
                st.next_attempt = now + timedelta(seconds=backoff)
                ok, err = False, f"{type(exc).__name__}: {exc}"[:300]
            out.setdefault("collector/feed_health.jsonl", []).append({
                "timestamp": iso(now), "device": d["name"], "protocol": d["protocol"], "ok": ok,
                "latency_ms": round((datetime.now(UTC) - started).total_seconds() * 1000, 1), "error": err})
        return out

    # ------------------------------------------------------------------ device kinds
    def _redfish(self, d):
        from .redfish import RedfishReader
        return RedfishReader(d["base_url"], secret(d, "username"), secret(d, "password"),
                             verify=d.get("verify_tls", True), timeout=self.cfg["timeout_s"])

    def _modbus(self, d):
        from .modbus import ModbusReader
        r = ModbusReader(d["host"], d.get("port", 502), d.get("device_id", 1), timeout=self.cfg["timeout_s"])
        r.connect()
        return r

    def _poll_cdu(self, d, st: DeviceState, now: datetime):
        from .redfish import cdu_snapshot
        state, readings = cdu_snapshot(self._redfish(d), d["cdu_id"])
        recs = []
        for (resource, prop), value in state.items():
            if st.last.get((resource, prop), "OK" if prop.endswith("Health") else "Enabled") != value:
                recs.append(("facility/cdu_redfish_events.jsonl",
                             {"timestamp": iso(now), "cdu": d["site_id"], "resource": resource, "property": prop, "value": value}))
            st.last[(resource, prop)] = value
        recs.append(("facility/cdu_readings.jsonl", {"timestamp": iso(now), "cdu": d["site_id"], **readings}))
        return recs

    def _poll_generator(self, d, st: DeviceState, now: datetime):
        r = self._modbus(d)
        try:
            v = r.read_points(d["points"])
        finally:
            r.close()
        states = {int(k): s for k, s in d["engine_state_codes"].items()}
        state = states.get(int(v["engine_operating_state"]), f"Unknown ({int(v['engine_operating_state'])})")
        kw = round(float(v["gen_total_kw"]), 1)
        rec = {"timestamp": iso(now), "generator": d["site_id"], "engine_operating_state": state,
               "gen_total_kw": kw, "gen_pct_rated_kw": round(kw / d["rated_kw"] * 100, 1)}
        prev = st.last.get("state")
        st.last["state"] = state
        if state != "Stopped" or prev not in (None, "Stopped"):
            return [("facility/emcp_readings.jsonl", rec)]
        return []

    def _poll_busway(self, d, st: DeviceState, now: datetime):
        r = self._modbus(d)
        try:
            v = r.read_points(d["points"])
        finally:
            r.close()
        recs = []
        volts = round(float(v["voltage_ll_avg"]), 1)
        lo, hi = d["tolerance_v"]
        inside = "in_tolerance" if lo <= volts <= hi else "out_of_tolerance"
        if st.last.get("voltage", "in_tolerance") != inside:
            recs.append(("facility/busway_cpm_events.jsonl", {"timestamp": iso(now), "busway": d["site_id"],
                                                              "point": "Voltage L-L avg", "value_v": volts, "state": inside}))
        st.last["voltage"] = inside
        for t in d.get("tapoffs", []):
            closed = int(v[t["point"]]) == 1
            key = ("tap", t["tapoff"])
            if st.last.get(key, True) != closed:
                rec = {"timestamp": iso(now), "busway": d["site_id"], "tapoff": t["tapoff"], "point": "Tap-off breaker",
                       "event": "Breaker closed" if closed else "Breaker open"}
                if t.get("rack"):
                    rec["rack"] = t["rack"]
                recs.append(("facility/busway_cpm_events.jsonl", rec))
            st.last[key] = closed
        return recs

    def _poll_leak(self, d, st: DeviceState, now: datetime):
        r = self._modbus(d)
        try:
            v = r.read_points(d["points"])
        finally:
            r.close()
        recs = []
        for c in d["circuits"]:
            alarm = int(v[c["alarm_point"]]) == 1
            if st.last.get(c["circuit"], False) != alarm:
                recs.append(("facility/leak_events.jsonl", {
                    "timestamp": iso(now), "controller": d["site_id"], "circuit": c["circuit"], "label": c["label"],
                    "event": "LEAK" if alarm else "NORMAL",
                    "distance_m": round(float(v[c["distance_point"]]), 1) if alarm else None}))
            st.last[c["circuit"]] = alarm
        return recs
