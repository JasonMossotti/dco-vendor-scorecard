"""Append collector records to a dataset folder that satisfies the dataset contract.

Files the live adapters do not produce yet (Landlord work orders, maintenance
records, the BMS export, and so on) are created empty and listed in the
manifest as ``not_collected``, so the engines load the dataset and simply see
no records from those sources.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

CONTRACT_FILES = [
    "facility/ups_nmc_events.jsonl", "facility/ups_status.jsonl", "facility/busway_cpm_events.jsonl",
    "facility/emcp_readings.jsonl", "facility/cdu_redfish_events.jsonl", "facility/bms_events.jsonl",
    "facility/epms_events.jsonl", "facility/leak_events.jsonl", "facility/vesda_events.jsonl",
    "access/landlord_badge_events.csv", "customer/landlord_mop_approvals.json", "landlord/work_orders.json",
    "landlord/pm_records.csv", "landlord/roster.csv", "landlord/self_reported_weekly.json",
]
CSV_HEADERS = {
    "access/landlord_badge_events.csv": "timestamp,person_id,reader,direction",
    "landlord/pm_records.csv": "task_id,system,asset,task,due_start,due_end,completed_at,engineer,result,evidence,mop_ref",
    "landlord/roster.csv": "shift_start,shift,engineer",
}


class DatasetWriter:
    def __init__(self, out_dir: str | Path, window_start: datetime):
        self.dir = Path(out_dir)
        self.window_start = window_start
        self.collected: set[str] = set()
        for rel in CONTRACT_FILES:
            p = self.dir / rel
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                if rel.endswith(".csv"):
                    p.write_text(CSV_HEADERS[rel] + "\n", encoding="utf-8")
                elif rel.endswith(".json"):
                    p.write_text("[]\n", encoding="utf-8")
                else:
                    p.write_text("", encoding="utf-8")

    def append(self, records: dict[str, list[dict[str, Any]]], now: datetime) -> None:
        for rel, rows in records.items():
            p = self.dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8", newline="\n") as fh:
                for r in rows:
                    fh.write(json.dumps(r, sort_keys=True) + "\n")
            self.collected.add(rel)
        manifest = {
            "window": {"start": self.window_start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "source": "live collector (read-only)",
            "collected": sorted(self.collected),
            "not_collected": sorted(set(CONTRACT_FILES) - self.collected),
        }
        (self.dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
