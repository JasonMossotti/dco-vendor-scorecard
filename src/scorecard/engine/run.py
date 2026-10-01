"""Run every detector, apply SLA severity, and order the findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scorecard.connectors import SiteDataSource
from scorecard.engine.core import Context, Finding
from scorecard.engine.detectors import DETECTORS
from scorecard.sla_model import classify_finding

SEVERITY_ORDER = {"S1": 0, "S2": 1, "S3": 2, "S4": 3, None: 4}


@dataclass
class EngineResult:
    context: Context
    findings: list[Finding]

    def by_type(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.type, []).append(f)
        return out


def _apply_severity(sla: dict[str, Any], f: Finding) -> None:
    m = f.metrics
    res = classify_finding(sla, f.type, m.get("target_min") if "measured_restore_min" in m else None,
                           m.get("measured_restore_min"), m.get("gpus", 0))
    f.severity, f.severity_name, f.escalation, f.severity_reasons = res.level, res.name, res.escalation, res.reasons


def run_engine(sla: dict[str, Any], source: SiteDataSource) -> EngineResult:
    ctx = Context(sla, source)
    findings: list[Finding] = []
    for detect in DETECTORS:
        findings.extend(detect(ctx))
    for f in findings:
        _apply_severity(sla, f)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.observed_at or ctx.window_start, f.type))
    for n, f in enumerate(findings, start=1):
        f.id = f"F-{n:03d}"
    return EngineResult(ctx, findings)
