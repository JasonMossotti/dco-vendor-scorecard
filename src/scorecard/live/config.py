"""Collector configuration: devices, point maps, and credentials from the environment.

Credentials never live in the config file. A device names environment
variables (``username_env``, ``password_env``); they are resolved when the
device connects, so a missing secret fails that device clearly without
stopping the others.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROTOCOLS = {"redfish", "modbus", "snmp", "bacnet"}
KINDS = {"cdu", "generator", "busway", "leak", "ups", "bms"}


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> dict[str, Any]:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    errors = []
    names = set()
    for d in cfg.get("devices", []):
        if d.get("name") in names:
            errors.append(f"duplicate device name {d.get('name')}")
        names.add(d.get("name"))
        if d.get("protocol") not in PROTOCOLS:
            errors.append(f"{d.get('name')}: protocol must be one of {sorted(PROTOCOLS)}")
        if d.get("kind") not in KINDS:
            errors.append(f"{d.get('name')}: kind must be one of {sorted(KINDS)}")
        if d.get("protocol") == "snmp" and d.get("version", 3) != 3:
            errors.append(f"{d.get('name')}: only SNMPv3 (authPriv) is allowed; v1 and v2c send community strings in cleartext")
        for k in ("password", "username", "secret", "community", "auth_key", "priv_key"):
            if k in d:
                errors.append(f"{d.get('name')}: '{k}' must not be in the config; use '{k}_env' to name an environment variable")
    if errors:
        raise ConfigError("Collector config is invalid:\n  - " + "\n  - ".join(errors))
    cfg.setdefault("poll_interval_s", 60)
    cfg.setdefault("timeout_s", 5)
    cfg.setdefault("max_backoff_s", 900)
    return cfg


def secret(device: dict[str, Any], key: str) -> str | None:
    """Resolve ``<key>_env`` from the environment. Returns None when the device does not use it."""
    var = device.get(f"{key}_env")
    if var is None:
        return None
    value = os.environ.get(var)
    if value is None:
        raise ConfigError(f"{device['name']}: environment variable {var} is not set")
    return value
