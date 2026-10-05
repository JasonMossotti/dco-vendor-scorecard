"""Redfish reader (HTTP GET only) for CDUs, using the DMTF ThermalEquipment schema.

Reads ``/redfish/v1/ThermalEquipment/CDUs/{id}``: the ``PumpRedundancy`` group,
each pump's ``Status.State`` and ``Status.Health``, and the secondary coolant
connectors' ``SupplyTemperatureCelsius``, ``ReturnTemperatureCelsius``,
``FlowLitersPerMinute``, and ``SupplyPressurekPa`` readings.
"""

from __future__ import annotations

from typing import Any

import requests

READINGS = ("SupplyTemperatureCelsius", "ReturnTemperatureCelsius", "FlowLitersPerMinute", "SupplyPressurekPa")


class RedfishReader:
    """A read-only Redfish client: the only HTTP method it can issue is GET."""

    def __init__(self, base_url: str, username: str | None, password: str | None, verify: bool | str = True,
                 timeout: float = 5):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        if username is not None:
            self.session.auth = (username, password or "")
        self.session.verify = verify
        self.session.headers["Accept"] = "application/json"
        self.timeout = timeout

    def get(self, path: str) -> dict[str, Any]:
        r = self.session.get(self.base + path, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def members(self, path: str) -> list[str]:
        return [m["@odata.id"] for m in self.get(path).get("Members", [])]


def cdu_snapshot(reader: RedfishReader, cdu_id: str) -> tuple[dict[tuple[str, str], Any], dict[str, Any]]:
    """(state, readings) for one CDU.

    state maps (resource, property) to a value, for change detection.
    readings maps "connector/property" to the sensor reading.
    """
    base = f"/redfish/v1/ThermalEquipment/CDUs/{cdu_id}"
    unit = reader.get(base)
    state: dict[tuple[str, str], Any] = {}
    groups = unit.get("PumpRedundancy") or []
    worst = "OK"
    for g in groups if isinstance(groups, list) else [groups]:
        h = (g.get("Status") or {}).get("Health", "OK")
        worst = h if h != "OK" else worst
    state[(base, "PumpRedundancy.Status.Health")] = worst
    for pump in reader.members(f"{base}/Pumps"):
        p = reader.get(pump)
        st = p.get("Status") or {}
        state[(pump, "Status.Health")] = st.get("Health")
        state[(pump, "Status.State")] = st.get("State")
    readings: dict[str, Any] = {}
    for conn in reader.members(f"{base}/SecondaryCoolantConnectors"):
        c = reader.get(conn)
        for prop in READINGS:
            v = c.get(prop)
            if isinstance(v, dict):
                readings[f"{conn.rsplit('/', 1)[-1]}/{prop}"] = v.get("Reading")
    return state, readings
