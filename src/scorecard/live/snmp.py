"""SNMPv3 reader (GET only, authPriv only) for UPS network management cards.

Reads PowerNet MIB ``upsBasicOutputStatus`` (1.3.6.1.4.1.318.1.1.1.4.1.1.0) and
any other configured OIDs. SNMPv1 and v2c are refused: community strings are
cleartext. Requires a read-only USM user on the card (no write view).
"""

from __future__ import annotations

import asyncio
from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget, UsmUserData, get_cmd,
    usmAesCfb128Protocol, usmHMAC192SHA256AuthProtocol, usmHMACSHAAuthProtocol,
)

UPS_BASIC_OUTPUT_STATUS = "1.3.6.1.4.1.318.1.1.1.4.1.1.0"
# PowerNet MIB upsBasicOutputStatus values. Verify against the MIB revision on the card's firmware.
OUTPUT_STATUS = {1: "unknown", 2: "onLine", 3: "onBattery", 4: "onSmartBoost", 5: "timedSleeping", 6: "softwareBypass",
                 7: "off", 8: "rebooting", 9: "switchedBypass", 10: "hardwareFailureBypass",
                 11: "sleepingUntilPowerReturn", 12: "onSmartTrim", 20: "eConversion"}
AUTH = {"sha": usmHMACSHAAuthProtocol, "sha256": usmHMAC192SHA256AuthProtocol}
PRIV = {"aes128": usmAesCfb128Protocol}


class SnmpV3Reader:
    def __init__(self, host: str, port: int, user: str, auth_key: str, priv_key: str, auth: str = "sha",
                 priv: str = "aes128", timeout: float = 5):
        if auth not in AUTH or priv not in PRIV:
            raise ValueError(f"unsupported SNMPv3 protocols auth={auth} priv={priv}")
        self.addr = (host, port)
        self.user = UsmUserData(user, auth_key, priv_key, authProtocol=AUTH[auth], privProtocol=PRIV[priv])
        self.timeout = timeout

    async def _get(self, oids: list[str]) -> dict[str, Any]:
        target = await UdpTransportTarget.create(self.addr, timeout=self.timeout, retries=1)
        err_ind, err_stat, err_idx, binds = await get_cmd(
            SnmpEngine(), self.user, target, ContextData(), *[ObjectType(ObjectIdentity(o)) for o in oids])
        if err_ind:
            raise ConnectionError(f"SNMPv3: {err_ind}")
        if err_stat:
            raise IOError(f"SNMPv3 error status {err_stat.prettyPrint()} at {err_idx}")
        out = {}
        for name, value in binds:
            try:
                out[str(name)] = int(value)
            except (TypeError, ValueError):
                out[str(name)] = value.prettyPrint()
        return out

    def get(self, oids: list[str]) -> dict[str, Any]:
        return asyncio.run(self._get(oids))
