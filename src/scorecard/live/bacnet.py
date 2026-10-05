"""BACnet/IP reader (ReadProperty only) for BMS points.

Reads present value, out-of-service, and the 16-slot priority array. A value
held in a manual or operator slot (by default 1 to 8; slot 8 is "manual
operator") is an override, which the Landlord engine reconciles against
change records. The collector cannot see why an override was made, so it
records the change reference as unknown (None) for the engine to reconcile.
"""

from __future__ import annotations

import asyncio
from typing import Any

from bacpypes3.apdu import ErrorRejectAbortNack   # note: subclasses BaseException, not Exception
from bacpypes3.app import Application
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject


def _slot_value(pv) -> Any:
    for attr in ("real", "unsigned", "integer", "enumerated", "boolean", "characterString"):
        v = getattr(pv, attr, None)
        if v is not None:
            return v
    return None


async def _rp(app, device_addr: str, obj: str, prop: str, timeout: float, retries: int = 2):
    """ReadProperty with bounded retries: BACnet/IP is UDP, so a lost datagram is normal (cf. APDU retries)."""
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(app.read_property(device_addr, obj, prop), timeout)
        except asyncio.TimeoutError:
            if attempt == retries:
                raise


async def _read(device_addr: str, local_addr: str, local_device_id: int, objects: list[str], timeout: float):
    dev = DeviceObject(objectIdentifier=("device", local_device_id), objectName="TOR-COLLECTOR", vendorIdentifier=999)
    port = NetworkPortObject(local_addr, objectIdentifier=("network-port", 1), objectName="NP-1")
    app = Application.from_object_list([dev, port])
    try:
        out = {}
        for obj in objects:
            pv = await _rp(app, device_addr, obj, "present-value", timeout)
            try:
                oos = await _rp(app, device_addr, obj, "out-of-service", timeout)
            except (Exception, ErrorRejectAbortNack):
                oos = False                    # optional property; not every BMS point implements it
            try:
                pa = await _rp(app, device_addr, obj, "priority-array", timeout)
                slots = {i + 1: _slot_value(x) for i, x in enumerate(pa or []) if getattr(x, "null", 1) is None}
            except (Exception, ErrorRejectAbortNack):
                slots = {}                     # not commandable: no priority array
            out[obj] = {"present_value": float(pv) if isinstance(pv, (int, float)) else str(pv),
                        "out_of_service": bool(oos), "slots": slots}
        return out
    finally:
        app.close()


def read_points(device_addr: str, local_addr: str, local_device_id: int, objects: list[str], timeout: float = 5):
    """Read every configured object. BACnet errors become IOError, so the collector's per-device guard catches them."""
    try:
        return asyncio.run(_read(device_addr, local_addr, local_device_id, objects, timeout))
    except ErrorRejectAbortNack as exc:
        raise IOError(f"BACnet error from {device_addr}: {exc}") from None
