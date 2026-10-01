"""Render engine results as JSON (for tools) and Markdown (for people)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from scorecard.engine.core import Finding, fmt_t
from scorecard.engine.evaluate import Evaluation
from scorecard.engine.run import EngineResult


def _plain(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def finding_dict(f: Finding) -> dict[str, Any]:
    return _plain({
        "id": f.id, "type": f.type, "title": f.title, "severity": f.severity, "severity_name": f.severity_name,
        "summary": f.summary, "tickets": f.tickets, "unit": f.unit, "observed_at": f.observed_at,
        "evidence": f.evidence, "sla_refs": f.sla_refs, "severity_reasons": f.severity_reasons,
        "escalation": f.escalation, "recommended_action": f.recommended_action, "metrics": f.metrics, "keys": f.keys,
    })


def evaluation_dict(e: Evaluation) -> dict[str, Any]:
    return {
        "planted": e.planted, "detected": e.detected, "recall": round(e.recall, 4), "precision": round(e.precision, 4),
        "corroborating": [f.id for f in e.corroborating], "false_positives": [f.id for f in e.false_positives],
        "missed": [{"type": p["type"], "anomaly_id": p.get("anomaly_id")} for p in e.missed], "by_type": e.by_type,
    }


def to_json(result: EngineResult, evaluation: Evaluation | None = None) -> dict[str, Any]:
    ctx = result.context
    return {
        "window": {"start": _plain(ctx.window_start), "end": _plain(ctx.window_end)},
        "summary": dict(Counter(f.severity for f in result.findings)),
        "findings": [finding_dict(f) for f in result.findings],
        "evaluation": evaluation_dict(evaluation) if evaluation else None,
    }


def _cell(text: Any) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def to_markdown(result: EngineResult, evaluation: Evaluation | None = None) -> str:
    ctx, fs = result.context, result.findings
    sev_names = {lvl["id"]: lvl["name"] for lvl in ctx.sla["breach_severity"]["levels"]}
    counts = Counter(f.severity for f in fs)
    L: list[str] = []
    L += ["<!-- GENERATED FILE. DO NOT EDIT BY HAND. Run: python scripts/run_engine.py -->", "",
          "# Discrepancy Report", "",
          "> Synthetic data for a portfolio demonstration. All sites, people, serials, and events are fictional.", "",
          f"**Window:** {fmt_t(ctx.window_start)} to {fmt_t(ctx.window_end)}  ",
          f"**Vendor tickets reviewed:** {len(ctx.tickets)}  ",
          f"**Findings:** {len(fs)} ("
          + ", ".join(f"{counts.get(s, 0)} {s} {sev_names[s]}" for s in ("S1", "S2", "S3", "S4") if counts.get(s)) + ")", "",
          "Each finding is a place where the vendor's records do not reconcile with the Telemetry of Record. "
          "A finding starts a review; it is not by itself proof of intent. Severity follows the SLA's internal "
          "breach severity index, where any record-integrity finding is S1.", ""]

    L += ["## Summary by type", "", "| Type | Findings | Highest severity | SLA references |", "|---|:-:|:-:|---|"]
    by_type: dict[str, list[Finding]] = {}
    for f in fs:
        by_type.setdefault(f.type, []).append(f)
    for ft in ctx.sla["breach_severity"]["finding_types"]:
        items = by_type.get(ft["id"], [])
        top = min((f.severity for f in items), default=None)
        L.append(f"| {ft['name']} | {len(items)} | {top or '-'} | {', '.join(ft['sla_refs'])} |")
    L.append("")

    if evaluation:
        e = evaluation
        L += ["## Engine self-check against the answer key", "",
              f"The synthetic generator planted **{e.planted}** discrepancies and recorded them in an answer key the engine "
              f"cannot read. The engine found **{e.detected} of {e.planted}** "
              f"with **{len(e.false_positives)} false positive{'s' if len(e.false_positives) != 1 else ''}**"
              + (f" and {len(e.corroborating)} corroborating finding{'s' if len(e.corroborating) != 1 else ''} "
                 "(correct findings of a second type on the same tickets)." if e.corroborating else "."), "",
              "| Planted type | Planted | Detected |", "|---|:-:|:-:|"]
        for t, row in sorted(e.by_type.items()):
            L.append(f"| `{t}` | {row['planted']} | {row['detected']} |")
        L.append("")

    L += ["## Findings", ""]
    for f in fs:
        L += [f"### {f.id} · {f.severity} {f.severity_name} · {f.title}", "",
              f"**Tickets:** {', '.join(f.tickets) if f.tickets else 'n/a'}  ",
              f"**Unit:** {f.unit or 'n/a'}  ",
              f"**Observed:** {fmt_t(f.observed_at)}", "",
              f.summary, "",
              "| Source | Time | Evidence |", "|---|---|---|"]
        for item in f.evidence:
            L.append(f"| `{item['source']}` | {fmt_t(item['at']) if item['at'] else '-'} | {_cell(item['detail'])} |")
        L += ["",
              f"**Severity:** {'; '.join(f.severity_reasons)}.  ",
              f"**Escalation:** {f.escalation}  ",
              f"**Recommended action:** {f.recommended_action}  ",
              f"**SLA:** {', '.join(f.sla_refs)}", ""]
    return "\n".join(L).rstrip() + "\n"
