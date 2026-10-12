"""Incident comms log: the joint bridge, the leads' updates, and the Incident Commander's leadership updates.

The scenario (config/incident_comms.yaml) gives the minute of each entry; this layer adds the second from its own
random stream, keeping the scenario's order within a minute. Nothing else in the dataset is read or moved.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "config" / "incident_comms.yaml"


def build(seed: int | str, scenario: Path = SCENARIO) -> dict[str, list[dict[str, Any]]]:
    cfg = yaml.safe_load(scenario.read_text(encoding="utf-8"))
    rng = random.Random(f"{seed}:incident-comms")          # independent of every other stream
    out: dict[str, list[dict[str, Any]]] = {}
    for ref, inc in cfg["incidents"].items():
        by_minute: dict[str, list[int]] = defaultdict(list)
        for i, e in enumerate(inc["events"]):
            by_minute[e["at"]].append(i)
        secs: dict[int, int] = {}
        for idx in by_minute.values():
            for i, s in zip(idx, sorted(rng.sample(range(60), len(idx)))):
                secs[i] = s
        rows = []
        for i, e in enumerate(inc["events"]):
            row = {"t": f"{inc['date']}T{e['at']}:{secs[i]:02d}Z", "kind": e["kind"], "party": e["party"],
                   "role": e["role"], "text": e["text"]}
            if e.get("to"):
                row["to"] = e["to"]
            rows.append(row)
        out[ref] = rows
    return out


def write(logs: dict[str, list[dict[str, Any]]], dest: str | Path, source: str = "") -> dict[str, int]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    counts = {}
    for ref, rows in logs.items():
        (dest / f"{ref}.json").write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        counts[f"{ref}.json"] = len(rows)
    (dest / "manifest.json").write_text(json.dumps({
        "disclaimer": "Synthetic incident comms log for a portfolio demonstration: when the joint bridge opened, who "
                      "joined, each lead's updates to the Incident Commander, and the Incident Commander's updates to "
                      "leadership. Roles only; no person is named.",
        "source": source, "files": counts}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return counts
