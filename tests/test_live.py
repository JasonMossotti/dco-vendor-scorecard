"""Live collector: read-only by construction, tested against in-process device simulators.

The Redfish simulator is a local HTTP server serving DMTF-shaped CDU resources
behind basic authentication. The Modbus simulator is pymodbus's own server
(SimDevice), whose access hook records every function code the collector uses.
"""

import asyncio
import base64
import json
import re
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

pytest.importorskip("pymodbus")
pytest.importorskip("requests")

from pymodbus.server import ServerAsyncStop, StartAsyncTcpServer  # noqa: E402
from pymodbus.simulator import DataType, SimData, SimDevice  # noqa: E402

from scorecard.live.collector import Collector  # noqa: E402
from scorecard.live.config import ConfigError, load_config, secret  # noqa: E402
from scorecard.live.writer import CONTRACT_FILES, DatasetWriter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "src" / "scorecard" / "live"
UTC = timezone.utc
T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --------------------------------------------------------------------------- #
# Simulators
# --------------------------------------------------------------------------- #
class RedfishSim:
    """CDU at /redfish/v1/ThermalEquipment/CDUs/1 with two pumps and one secondary connector."""

    def __init__(self, user="ro", password="secret"):
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.methods: list[str] = []
        self.pumps = {"1": {"State": "Enabled", "Health": "OK"}, "2": {"State": "Enabled", "Health": "OK"}}
        self.redundancy = "OK"
        self.supply_c = 30.2
        sim = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _deny(self):
                sim.methods.append(self.command)
                self.send_response(405)
                self.end_headers()

            do_POST = do_PATCH = do_PUT = do_DELETE = _deny

            def do_GET(self):
                sim.methods.append("GET")
                if self.headers.get("Authorization") != sim.auth:
                    self.send_response(401)
                    self.end_headers()
                    return
                body = sim.resource(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", free_port()), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def resource(self, path):
        base = "/redfish/v1/ThermalEquipment/CDUs/1"
        if path == base:
            return {"@odata.id": base, "Id": "1", "PumpRedundancy": [{"Status": {"Health": self.redundancy}}]}
        if path == f"{base}/Pumps":
            return {"Members": [{"@odata.id": f"{base}/Pumps/{n}"} for n in self.pumps]}
        m = re.fullmatch(rf"{base}/Pumps/(\d)", path)
        if m:
            return {"@odata.id": path, "Status": dict(self.pumps[m.group(1)])}
        if path == f"{base}/SecondaryCoolantConnectors":
            return {"Members": [{"@odata.id": f"{base}/SecondaryCoolantConnectors/1"}]}
        if path == f"{base}/SecondaryCoolantConnectors/1":
            return {"SupplyTemperatureCelsius": {"Reading": self.supply_c}, "ReturnTemperatureCelsius": {"Reading": 40.1},
                    "FlowLitersPerMinute": {"Reading": 1380.0}, "SupplyPressurekPa": {"Reading": 210.0}}
        return None

    def stop(self):
        self.server.shutdown()


class ModbusSim:
    """A Modbus TCP device whose registers the test can change; logs every function code used."""

    def __init__(self, registers: dict[int, int]):
        self.regs = dict(registers)
        self.codes: list[int] = []
        self.port = free_port()
        sim = self

        async def action(function_code, start_address, address, count, current_registers, set_values):
            sim.codes.append(function_code)
            for i in range(count):
                if address + i in sim.regs:
                    current_registers[address + i - start_address] = sim.regs[address + i]
            return None

        dev = SimDevice(id=1, simdata=[SimData(1, count=1000, values=0, datatype=DataType.REGISTERS)], action=action)
        self.loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(StartAsyncTcpServer(context=dev, address=("127.0.0.1", self.port)))

        threading.Thread(target=run, daemon=True).start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

    def stop(self):
        asyncio.run_coroutine_threadsafe(ServerAsyncStop(), self.loop).result(5)


def float32(v: float) -> list[int]:
    import struct
    a, b = struct.unpack(">HH", struct.pack(">f", v))
    return [a, b]


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def tick(self, minutes=1):
        self.t += timedelta(minutes=minutes)


@pytest.fixture
def redfish(monkeypatch):
    sim = RedfishSim()
    monkeypatch.setenv("CDU_RO_USER", "ro")
    monkeypatch.setenv("CDU_RO_PASSWORD", "secret")
    yield sim
    sim.stop()


def cdu_device(sim):
    return {"name": "cdu-a1", "kind": "cdu", "protocol": "redfish", "site_id": "CDU-A1", "base_url": sim.url,
            "cdu_id": "1", "username_env": "CDU_RO_USER", "password_env": "CDU_RO_PASSWORD"}


def config(*devices):
    return {"devices": list(devices), "poll_interval_s": 60, "timeout_s": 2, "max_backoff_s": 900}


# --------------------------------------------------------------------------- #
# Read-only by construction
# --------------------------------------------------------------------------- #
FORBIDDEN = [r"\bwrite_register", r"\bwrite_coil", r"\bmask_write", r"\breadwrite_registers", r"\.post\(", r"\.patch\(",
             r"\.put\(", r"\.delete\(", r"\bsetCmd\b", r"\bset_cmd\b", r"WriteProperty", r"\bwrite_property\b",
             r"\brequest\(\s*['\"](POST|PATCH|PUT|DELETE)"]


def test_collector_code_contains_no_write_capable_calls():
    for path in LIVE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN:
            assert not re.search(pattern, text), f"{path.name} contains write-capable call /{pattern}/"


def test_the_scanner_catches_write_calls():
    """The guard above must actually fire on the calls it exists to block."""
    samples = ["client.write_register(10, 1)", "client.write_coils(1, [True])", "session.post(url, json=x)",
               "s.patch(url)", "await setCmd(engine, auth)", "WriteProperty(obj, value)", "s.delete(url)"]
    for code in samples:
        assert any(re.search(p, code) for p in FORBIDDEN), code


def test_modbus_reader_refuses_tables_it_could_write_to():
    from scorecard.live.modbus import ModbusReader
    r = ModbusReader("127.0.0.1", free_port())
    with pytest.raises(ValueError, match="read-only"):
        r.read_point({"name": "x", "register": 1, "table": "coil"})


# --------------------------------------------------------------------------- #
# Configuration and credentials
# --------------------------------------------------------------------------- #
def test_example_config_loads_and_keeps_secrets_out():
    cfg = load_config(ROOT / "config" / "collector.example.yaml")
    assert {d["kind"] for d in cfg["devices"]} == {"cdu", "generator", "busway", "leak"}
    text = (ROOT / "config" / "collector.example.yaml").read_text(encoding="utf-8")
    assert "PLACEHOLDER" in text and "password:" not in text


def test_inline_secrets_are_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"devices": [{"name": "x", "kind": "cdu", "protocol": "redfish", "password": "hunter2"}]}))
    with pytest.raises(ConfigError, match="password_env"):
        load_config(p)


def test_missing_credential_fails_that_device_only(monkeypatch, redfish):
    monkeypatch.delenv("CDU_RO_PASSWORD")
    with pytest.raises(ConfigError, match="CDU_RO_PASSWORD"):
        secret(cdu_device(redfish), "password")
    out = Collector(config(cdu_device(redfish)), clock=Clock()).poll_once()
    (health,) = out["collector/feed_health.jsonl"]
    assert not health["ok"] and "CDU_RO_PASSWORD" in health["error"]


# --------------------------------------------------------------------------- #
# Redfish CDU
# --------------------------------------------------------------------------- #
def test_redfish_pump_failure_and_recovery_become_contract_events(redfish):
    clock = Clock()
    c = Collector(config(cdu_device(redfish)), clock=clock)
    first = c.poll_once()
    assert "facility/cdu_redfish_events.jsonl" not in first, "a healthy CDU produces no events"
    assert first["facility/cdu_readings.jsonl"][0]["1/SupplyTemperatureCelsius"] == 30.2
    redfish.pumps["2"]["Health"], redfish.redundancy = "Critical", "Warning"
    clock.tick()
    fail = c.poll_once()["facility/cdu_redfish_events.jsonl"]
    assert {(e["property"], e["value"]) for e in fail} == {("Status.Health", "Critical"), ("PumpRedundancy.Status.Health", "Warning")}
    assert all(e["resource"].startswith("/redfish/v1/ThermalEquipment/CDUs/1") and e["cdu"] == "CDU-A1" for e in fail)
    redfish.pumps["2"]["Health"], redfish.redundancy = "OK", "OK"
    clock.tick(30)
    ok = c.poll_once()["facility/cdu_redfish_events.jsonl"]
    assert {e["value"] for e in ok} == {"OK"}
    assert set(redfish.methods) == {"GET"}, "the collector only ever issued GET"


def test_redfish_wrong_password_is_a_feed_gap_with_backoff(monkeypatch, redfish):
    monkeypatch.setenv("CDU_RO_PASSWORD", "wrong")
    clock = Clock()
    c = Collector(config(cdu_device(redfish)), clock=clock)
    (h,) = c.poll_once()["collector/feed_health.jsonl"]
    assert not h["ok"] and "401" in h["error"]
    clock.tick(1)
    assert "collector/feed_health.jsonl" not in c.poll_once(), "the device is skipped while backing off"
    clock.tick(5)
    assert c.poll_once()["collector/feed_health.jsonl"][0]["ok"] is False


# --------------------------------------------------------------------------- #
# Modbus: generator, busway, leak
# --------------------------------------------------------------------------- #
def test_generator_run_is_recorded_each_poll_and_only_read_codes_are_used():
    sim = ModbusSim({100: 0, 102: 0, 103: 0})
    try:
        dev = {"name": "gen-1", "kind": "generator", "protocol": "modbus", "site_id": "GEN-1", "host": "127.0.0.1",
               "port": sim.port, "rated_kw": 3000,
               "points": [{"name": "engine_operating_state", "register": 100}, {"name": "gen_total_kw", "register": 102, "type": "int32"}],
               "engine_state_codes": {0: "Stopped", 1: "Starting", 2: "Running", 3: "Cooldown"}}
        clock = Clock()
        c = Collector(config(dev), clock=clock)
        assert "facility/emcp_readings.jsonl" not in c.poll_once(), "a stopped generator writes nothing"
        sim.regs.update({100: 2, 102: 0, 103: 1200})
        rows = []
        for _ in range(3):
            clock.tick()
            rows += c.poll_once()["facility/emcp_readings.jsonl"]
        assert [r["engine_operating_state"] for r in rows] == ["Running"] * 3
        assert rows[0]["gen_total_kw"] == 1200 and rows[0]["gen_pct_rated_kw"] == 40.0
        sim.regs.update({100: 0, 103: 0})
        clock.tick()
        (stop,) = c.poll_once()["facility/emcp_readings.jsonl"]
        assert stop["engine_operating_state"] == "Stopped"
        assert set(sim.codes) <= {3, 4}, f"only read function codes; saw {sorted(set(sim.codes))}"
    finally:
        sim.stop()


def test_busway_voltage_and_tapoff_events():
    sim = ModbusSim({200: float32(479.6)[0], 201: float32(479.6)[1], 300: 1})
    try:
        dev = {"name": "bw", "kind": "busway", "protocol": "modbus", "site_id": "BW-A-R1-PG-A1-B", "host": "127.0.0.1",
               "port": sim.port, "tolerance_v": [432, 528],
               "points": [{"name": "voltage_ll_avg", "register": 200, "type": "float32", "table": "input"},
                          {"name": "tap_a01", "register": 300}],
               "tapoffs": [{"tapoff": "TO-A01-B", "rack": "A01", "point": "tap_a01"}]}
        clock = Clock()
        c = Collector(config(dev), clock=clock)
        assert "facility/busway_cpm_events.jsonl" not in c.poll_once()
        sim.regs.update({200: float32(0.0)[0], 201: float32(0.0)[1], 300: 0})
        clock.tick()
        ev = c.poll_once()["facility/busway_cpm_events.jsonl"]
        assert {"state": "out_of_tolerance"}.items() <= ev[0].items() and ev[0]["value_v"] == 0.0
        assert ev[1]["event"] == "Breaker open" and ev[1]["rack"] == "A01"
    finally:
        sim.stop()


def test_leak_alarm_carries_its_distance():
    sim = ModbusSim({400: 0, 401: 0})
    try:
        dev = {"name": "ttdm", "kind": "leak", "protocol": "modbus", "site_id": "TTDM-A", "host": "127.0.0.1",
               "port": sim.port,
               "points": [{"name": "a", "register": 400}, {"name": "d", "register": 401, "scale": 0.1}],
               "circuits": [{"circuit": 5, "label": "Under CDU-A1", "alarm_point": "a", "distance_point": "d"}]}
        clock = Clock()
        c = Collector(config(dev), clock=clock)
        c.poll_once()
        sim.regs.update({400: 1, 401: 142})
        clock.tick()
        (e,) = c.poll_once()["facility/leak_events.jsonl"]
        assert e["event"] == "LEAK" and e["distance_m"] == 14.2 and e["circuit"] == 5
    finally:
        sim.stop()


def test_unreachable_device_does_not_stop_the_others(redfish):
    dead = {"name": "gen-x", "kind": "generator", "protocol": "modbus", "site_id": "GEN-7", "host": "127.0.0.1",
            "port": free_port(), "rated_kw": 3000, "points": [], "engine_state_codes": {}}
    out = Collector(config(dead, cdu_device(redfish)), clock=Clock()).poll_once()
    health = {h["device"]: h["ok"] for h in out["collector/feed_health.jsonl"]}
    assert health == {"gen-x": False, "cdu-a1": True}


# --------------------------------------------------------------------------- #
# End to end: live data through the unchanged Landlord engine
# --------------------------------------------------------------------------- #
def test_live_dataset_runs_through_the_landlord_engine(tmp_path, redfish):
    from scorecard.connectors import FileConnector
    from scorecard.engine.landlord import LandlordContext, build_facility_incidents
    from scorecard.sla_model import PARTNER_FILES, load_sla
    clock = Clock()
    c = Collector(config(cdu_device(redfish)), clock=clock)
    w = DatasetWriter(tmp_path, T0)
    w.append(c.poll_once(), clock())
    redfish.pumps["1"]["Health"], redfish.redundancy = "Critical", "Warning"
    clock.tick(5)
    w.append(c.poll_once(), clock())
    redfish.pumps["1"]["Health"], redfish.redundancy = "OK", "OK"
    clock.tick(180)
    w.append(c.poll_once(), clock())
    for rel in CONTRACT_FILES:
        assert (tmp_path / rel).exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "facility/cdu_redfish_events.jsonl" in manifest["collected"] and "landlord/work_orders.json" in manifest["not_collected"]
    ctx = LandlordContext(load_sla(PARTNER_FILES["landlord"]), FileConnector(tmp_path))
    (inc,) = build_facility_incidents(ctx)
    assert inc.fault_class == "OT-FC-CDU" and inc.unit == "CDU-A1" and round(inc.restore_min) == 180
