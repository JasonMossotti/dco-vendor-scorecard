"""Score the engine against the generator's answer key.

This module is the ONLY code that reads ground_truth/, and it runs after the
engine has finished. Matching rules:

* Detected: a finding of the same type that references the planted ticket (or
  any of a lemon unit's tickets, the same shift for staffing gaps, the same
  rack for unauthorized changes).
* Corroborating: a finding of a different type that touches a ticket involved
  in a planted discrepancy (for example, the wrong-end optic's follow-up ticket
  is also a ticket split). Correct, but not the planted type.
* False positive: a finding unrelated to any planted discrepancy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scorecard.engine.core import Finding


@dataclass
class Evaluation:
    planted: int
    detected: int
    by_type: dict[str, dict[str, int]]
    missed: list[dict[str, Any]] = field(default_factory=list)
    corroborating: list[Finding] = field(default_factory=list)
    false_positives: list[Finding] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.detected / self.planted if self.planted else 1.0

    @property
    def precision(self) -> float:
        relevant = self.detected + len(self.corroborating)
        total = relevant + len(self.false_positives)
        return relevant / total if total else 1.0


def _matches(p: dict, f: Finding) -> bool:
    if f.type != p["type"]:
        return False
    if p["type"] == "staffing_gap":
        return f.keys.get("shift_start") is not None and f.keys["shift_start"].strftime("%Y-%m-%dT%H:%M:%SZ") == p["shift_start"]
    if p["type"] == "unauthorized_change":
        return f.keys.get("rack") == p["rack"]
    if p["type"] == "lemon_unit":
        return bool(set(p["tickets"]) & set(f.tickets))
    return p.get("ticket") in f.tickets


def evaluate(findings: list[Finding], dataset_dir: str | Path) -> Evaluation:
    planted = json.loads((Path(dataset_dir) / "ground_truth" / "planted_discrepancies.json").read_text(encoding="utf-8"))
    involved = set()
    for p in planted:
        involved |= {p.get("ticket"), p.get("recurrence_ticket"), *p.get("tickets", [])}
    involved.discard(None)

    used: set[str] = set()
    by_type: dict[str, dict[str, int]] = {}
    missed = []
    for p in planted:
        row = by_type.setdefault(p["type"], {"planted": 0, "detected": 0})
        row["planted"] += 1
        hit = next((f for f in findings if _matches(p, f)), None)
        if hit:
            row["detected"] += 1
            used.add(hit.id)
        else:
            missed.append(p)
    corroborating, false_pos = [], []
    for f in findings:
        if f.id in used:
            continue
        if any(_matches(p, f) for p in planted):
            corroborating.append(f)        # second finding for an already-detected item
        elif set(f.tickets) & involved:
            corroborating.append(f)
        else:
            false_pos.append(f)
    return Evaluation(len(planted), len(planted) - len(missed), by_type, missed, corroborating, false_pos)


# --------------------------------------------------------------------------- #
# Landlord engine
# --------------------------------------------------------------------------- #
def _landlord_match(p: dict[str, Any], f: Finding) -> bool:
    k = f.keys
    if f.type != p["type"]:
        return False
    if p["type"] == "gen_test_no_load":
        return k.get("asset") == p["generator"]
    if p["type"] == "pm_without_evidence":
        return k.get("task") == p["task"]
    if p["type"] == "bms_override_unrecorded":
        return k.get("device") == p["device"] and k.get("set_at").strftime("%Y-%m-%dT%H:%M:%SZ") == p["set_at"]
    if p["type"] == "critical_work_no_mop":
        return k.get("asset") == p["busway"]
    return p.get("wo") in f.tickets


def evaluate_landlord(findings: list[Finding], data_dir: str | Path) -> Evaluation:
    """Score the Landlord engine against the facility answer key (read only here, after the engine ran)."""
    planted = json.loads((Path(data_dir) / "ground_truth" / "facility_planted_discrepancies.json").read_text(encoding="utf-8"))
    by_type: dict[str, dict[str, int]] = {}
    matched: set[int] = set()
    missed = []
    for p in planted:
        bt = by_type.setdefault(p["type"], {"planted": 0, "detected": 0})
        bt["planted"] += 1
        hit = next((i for i, f in enumerate(findings) if _landlord_match(p, f)), None)
        if hit is None:
            missed.append(p)
        else:
            bt["detected"] += 1
            matched.add(hit)
    fps = [f for i, f in enumerate(findings) if i not in matched]
    return Evaluation(planted=len(planted), detected=len(planted) - len(missed), by_type=by_type,
                      missed=missed, false_positives=fps)
