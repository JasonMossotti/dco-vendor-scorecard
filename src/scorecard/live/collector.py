"""Poll every configured device and turn readings into records in the dataset contract.

Each device keeps its last known state; a record is emitted when something
changes (a pump's health, a busway leaving tolerance, a leak alarm), plus one
reading per poll for running generators, matching what the synthetic
generator writes. Every poll also writes a feed-health record, so a device
that stops answering becomes a measured gap (OT-KM-06), not a silent one.

Beside the records, ``latest`` keeps each device's most recent values and
``feeds`` each device's feed state; ``scorecard.live.now`` turns them into the
Live page's ``now.json`` (docs/live/NOW_SCHEMA.md).
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
        self.latest: dict[str, dict[str, Any]] = {}     # site id -> the device's values at its last good poll
        self.feeds: dict[str, dict[str, Any]] = {}      # device name -> ok, last good poll, first failure, error

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
            f = self.feeds.setdefault(d["name"], {"device": d["name"], "site_id": d.get("site_id"), "kind": d["kind"],
                                                   "protocol": d["protocol"], "last_ok": None, "failing_since": None})
            f.update(ok=ok, error=err, polled=iso(now))
            if ok:
                f["last_ok"], f["failing_since"] = iso(now), None
            elif f["failing_since"] is None:
                f["failing_since"] = iso(now)
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
        self.latest[d["site_id"]] = {"kind": "cdu", "health": {f"{res.rsplit('/', 1)[-1]} {prop}": v for (res, prop), v in state.items()},
                                     "readings": readings}
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
        self.latest[d["site_id"]] = {"kind": "generator", "state": state, "kw": kw,
                                     "breaker": None if "breaker" not in v else ("closed" if int(v["breaker"]) == 1 else "open"),
                                     "fuel_pct": None if "fuel_pct" not in v else round(float(v["fuel_pct"]), 1)}
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
        self.latest[d["site_id"]] = {"kind": "busway", "voltage_ll": volts, "in_tolerance": inside == "in_tolerance",
                                     "tapoffs_open": [t["tapoff"] for t in d.get("tapoffs", []) if int(v[t["point"]]) != 1]}
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

    def _poll_ups(self, d, st: DeviceState, now: datetime):
        from .snmp import OUTPUT_STATUS, UPS_ADV_BATTERY_CAPACITY, UPS_ADV_BATTERY_RUNTIME, UPS_BASIC_OUTPUT_STATUS, SnmpV3Reader
        r = SnmpV3Reader(d["host"], d.get("port", 161), d["user"], secret(d, "auth_key"), secret(d, "priv_key"),
                         d.get("auth_protocol", "sha"), d.get("priv_protocol", "aes128"), timeout=self.cfg["timeout_s"])
        oids = ([UPS_BASIC_OUTPUT_STATUS] + ([d["load_oid"]] if d.get("load_oid") else [])
                + ([UPS_ADV_BATTERY_RUNTIME, UPS_ADV_BATTERY_CAPACITY] if d.get("battery") else []))
        v = r.get(oids)
        code = int(v[UPS_BASIC_OUTPUT_STATUS])
        status = OUTPUT_STATUS.get(code, f"code {code}")
        recs = []
        if st.last.get("status", "onLine") != status:
            recs.append(("facility/ups_nmc_events.jsonl", {"timestamp": iso(now), "ups": d["site_id"],
                         "event": f"upsBasicOutputStatus {status}",
                         "severity": "informational" if status in ("onLine", "eConversion") else "warning"}))
        st.last["status"] = status
        row = {"timestamp": iso(now), "ups": d["site_id"], "upsBasicOutputStatus": status}
        if d.get("load_oid"):
            row["load_pct"] = float(v[d["load_oid"]])
        if d.get("battery"):                              # TimeTicks are hundredths of a second
            row["runtime_s"] = int(v[UPS_ADV_BATTERY_RUNTIME]) // 100
            row["charge_pct"] = float(v[UPS_ADV_BATTERY_CAPACITY])
        recs.append(("facility/ups_status.jsonl", row))
        self.latest[d["site_id"]] = {"kind": "ups", "status": status, "load_pct": row.get("load_pct"),
                                     "runtime_s": row.get("runtime_s"), "charge_pct": row.get("charge_pct")}
        return recs

    def _poll_bms(self, d, st: DeviceState, now: datetime):
        from .bacnet import read_points
        pts = {p["object"]: p for p in d["points"]}
        v = read_points(d["address"], d["local_address"], d.get("local_device_id", 3999), list(pts), self.cfg["timeout_s"])
        manual = set(d.get("override_priorities", list(range(1, 9))))
        recs = []
        for obj, val in v.items():
            p = pts[obj]
            held = {s: x for s, x in val["slots"].items() if s in manual}
            for kind, active, value in (("override", bool(held), next(iter(held.values()), None)),
                                        ("inhibit", val["out_of_service"], "Out of service")):
                key = (obj, kind)
                if st.last.get(key, False) != active:
                    recs.append(("facility/bms_events.jsonl", {
                        "timestamp": iso(now), "kind": kind, "device": p["device"], "point": p["label"],
                        "value": value if active else "Auto", "user": None, "change_ref": None,
                        "action": "set" if active else "release", "source": "bacnet",
                        "priority": min(held) if active and kind == "override" else None}))
                st.last[key] = active
        self.latest[d.get("site_id") or d["name"]] = {
            "kind": "bms", "held": [f"{pts[o]['device']} {pts[o]['label']}" for o in v
                                    if st.last.get((o, "override")) or st.last.get((o, "inhibit"))]}
        return recs

    def _poll_mains(self, d, st: DeviceState, now: datetime):
        """A utility main's revenue meter: one reading per poll (the meter publishes every minute)."""
        r = self._modbus(d)
        try:
            v = r.read_points(d["points"])
        finally:
            r.close()
        rec = {"timestamp": iso(now), "main": d["site_id"], "v_ll": round(float(v["voltage_ll_avg"]), 1),
               "i_avg": round(float(v["current_avg"]), 1), "kw": round(float(v["kw_total"]), 1),
               "pf": round(float(v["pf_total"]), 3), "hz": round(float(v["frequency"]), 2)}
        if "breaker" in v:
            rec["breaker"] = "closed" if int(v["breaker"]) == 1 else "open"
        self.latest[d["site_id"]] = {"kind": "mains", **{k: x for k, x in rec.items() if k not in ("timestamp", "main")}}
        return [("facility/utility_mains.jsonl", rec)]

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
        self.latest[d["site_id"]] = {"kind": "leak", "alarms": [c["label"] for c in d["circuits"] if st.last.get(c["circuit"])]}
        return recs
