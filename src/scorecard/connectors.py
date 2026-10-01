"""Data connectors: the only way the engine reads site data.

The engine depends on the ``SiteDataSource`` interface, never on files directly.
``FileConnector`` serves the synthetic dataset from disk. A production
deployment would implement the same interface against live systems, for example:

* ``xid_events``          -> DCGM exporter / Prometheus query
* ``inventory_changes``   -> Redfish polling of each BMC (SerialNumber, FirmwareVersion)
* ``ufm_events``          -> InfiniBand fabric manager REST API
* ``nmx_events``          -> NVLink fabric management API
* ``health_checks``       -> cluster health-check platform API
* ``scheduler_states``    -> workload scheduler node history
* ``badge_events``        -> access control system export
* ``tickets``             -> vendor ITSM API (ServiceNow-style table API)

Nothing else in the engine changes when a connector is swapped.

The connector also enforces a rule the evaluation depends on: the answer key in
``ground_truth/`` is never readable through it.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

# Logical source name -> relative path in a dataset directory.
SOURCES: dict[str, str] = {
    "topology": "site/topology.json",
    "xid_events": "telemetry/dcgm_xid_events.jsonl",
    "redfish_events": "telemetry/redfish_events.jsonl",
    "inventory_changes": "telemetry/redfish_inventory_changes.jsonl",
    "nmx_events": "telemetry/nmx_events.jsonl",
    "ufm_events": "telemetry/ufm_port_events.jsonl",
    "bms_events": "telemetry/bms_cdu_events.jsonl",
    "health_checks": "telemetry/health_checks.jsonl",
    "scheduler_states": "telemetry/scheduler_node_states.jsonl",
    "badge_events": "access/badge_events.csv",
    "cab_changes": "customer/cab_changes.json",
    "deployment_plan": "customer/deployment_plan.csv",
    "tickets": "vendor/tickets.json",
    "personnel": "vendor/personnel.csv",
    "roster": "vendor/roster.csv",
    "spares_ledger": "vendor/spares_ledger.csv",
    "cycle_counts": "vendor/spares_cycle_counts.csv",
    "rma_shipments": "vendor/rma_shipments.csv",
    "deployment_milestones": "vendor/deployment_milestones.csv",
    "vendor_weekly": "vendor/self_reported_weekly.json",
    "manifest": "manifest.json",
}

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_INT = re.compile(r"^-?\d+$")


class SiteDataSource(Protocol):
    def get(self, source: str) -> Any: ...


def _convert(value: Any) -> Any:
    """Parse ISO-8601 UTC strings to aware datetimes and integer strings to ints, recursively."""
    if isinstance(value, str):
        if _ISO.match(value):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    if isinstance(value, list):
        return [_convert(v) for v in value]
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items()}
    return value


def _convert_csv_row(row: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v == "":
            out[k] = None
        elif _INT.match(v):
            out[k] = int(v)
        else:
            out[k] = _convert(v)
    return out


class FileConnector:
    """Reads a dataset directory written by ``scorecard.synthetic.write_dataset``."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._cache: dict[str, Any] = {}

    def _path(self, source: str) -> Path:
        if source not in SOURCES:
            raise KeyError(f"Unknown source '{source}'. Known: {', '.join(sorted(SOURCES))}")
        rel = SOURCES[source]
        if "ground_truth" in Path(rel).parts:
            raise PermissionError("The engine may not read ground_truth/")
        return self.root / rel

    def get(self, source: str) -> Any:
        if source in self._cache:
            return self._cache[source]
        path = self._path(source)
        if not path.exists():
            data: Any = []
        elif path.suffix == ".jsonl":
            data = [_convert(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        elif path.suffix == ".json":
            data = _convert(json.loads(path.read_text(encoding="utf-8")))
        elif path.suffix == ".csv":
            with open(path, encoding="utf-8", newline="") as fh:
                data = [_convert_csv_row(r) for r in csv.DictReader(fh)]
        else:
            raise ValueError(f"Unsupported file type: {path}")
        self._cache[source] = data
        return data

    def read_path(self, relative: str) -> Any:
        """Explicitly blocked: the engine must go through named sources."""
        raise PermissionError("Direct path access is not allowed; use get(source)")
