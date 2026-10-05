"""Modbus TCP reader (read function codes only) with configurable point maps.

Register addresses, data types, and scaling come from the site's point map,
verified against each vendor's documentation at commissioning. Only function
codes 3 (read holding registers) and 4 (read input registers) are used.
"""

from __future__ import annotations

from typing import Any

from pymodbus.client import ModbusTcpClient

TYPES = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}


class ModbusReader:
    def __init__(self, host: str, port: int = 502, device_id: int = 1, timeout: float = 5):
        self.client = ModbusTcpClient(host, port=port, timeout=timeout)
        self.device_id = device_id

    def connect(self) -> None:
        if not self.client.connect():
            raise ConnectionError(f"Modbus TCP connection to {self.client.comm_params.host} failed")

    def close(self) -> None:
        self.client.close()

    def read_point(self, point: dict[str, Any]) -> float | int:
        kind = point.get("type", "uint16")
        count = TYPES[kind]
        table = point.get("table", "holding")
        if table == "holding":
            r = self.client.read_holding_registers(point["register"], count=count, device_id=self.device_id)
        elif table == "input":
            r = self.client.read_input_registers(point["register"], count=count, device_id=self.device_id)
        else:
            raise ValueError(f"unsupported register table {table!r} (read-only collector: holding or input)")
        if r.isError():
            raise IOError(f"Modbus exception reading {point['name']} at {point['register']}: {r}")
        dt = {"uint16": self.client.DATATYPE.UINT16, "int16": self.client.DATATYPE.INT16,
              "uint32": self.client.DATATYPE.UINT32, "int32": self.client.DATATYPE.INT32,
              "float32": self.client.DATATYPE.FLOAT32}[kind]
        raw = self.client.convert_from_registers(r.registers, data_type=dt, word_order=point.get("word_order", "big"))
        if "bit" in point:
            return (int(raw) >> int(point["bit"])) & 1
        return raw * point.get("scale", 1) + point.get("offset", 0)

    def read_points(self, points: list[dict[str, Any]]) -> dict[str, Any]:
        return {p["name"]: self.read_point(p) for p in points}
