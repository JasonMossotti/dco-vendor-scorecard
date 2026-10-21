"""The quarter's earlier months (data/quarter/<start>/): the same site generator and Security Partner layer as the
sample month, each with its own seed and its planted counts drawn by chance around their usual rates.

The sample month is never touched. Each earlier month is a complete dataset in the sample's layout, with its Security
Partner layer under ``security/``, so every engine runs on it unchanged.
"""

from __future__ import annotations

import copy
import json
import math
import random
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CFG = ROOT / "config" / "qbr.yaml"
SYN = ROOT / "config" / "synthetic.yaml"
OUT = ROOT / "data" / "quarter"


def poisson(rng: random.Random, mean: float) -> int:
    """Knuth's method; small means only."""
    if mean <= 0:
        return 0
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def month_config(syn: dict[str, Any], seed: int, cfg: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The generator settings for one earlier month and the Security Partner plants it keeps."""
    from scorecard.synthetic.security import PLANTED_TYPES
    rng = random.Random(f"{seed}:quarter")
    c = copy.deepcopy(syn)
    for k in sorted(c["anomalies"]):
        c["anomalies"][k] = poisson(rng, c["anomalies"][k])
    f = c["facility"]
    for k in sorted(f["planted"]):
        f["planted"][k] = poisson(rng, f["planted"][k])
    for k in ("utility_outages", "rack_power_outages"):
        f[k] = poisson(rng, f[k])
    c["deployment"]["racks_received_in_window"] = cfg["generate"]["deployment_racks"]
    c["deployment"]["plan_first_receipt"] = str(cfg["generate"]["plan_first_receipt"])
    plants = [t for t in PLANTED_TYPES if poisson(rng, 1.0) > 0]
    return c, plants


def generate_month(m: dict[str, Any], out: Path, cfg: dict[str, Any] | None = None, syn: dict[str, Any] | None = None) -> dict[str, Any]:
    from scorecard.sla_model import load_sla
    from scorecard.synthetic import SiteGenerator, write_dataset
    from scorecard.synthetic.security import SecurityLayer, write_security
    cfg = cfg or yaml.safe_load(CFG.read_text(encoding="utf-8"))
    syn = syn or yaml.safe_load(SYN.read_text(encoding="utf-8"))
    c, plants = month_config(syn, m["seed"], cfg)
    start = m["start"] if isinstance(m["start"], date) else date.fromisoformat(str(m["start"]))
    data = SiteGenerator(load_sla(), c, start=start, seed=m["seed"]).run()
    write_dataset(data, out)
    window = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["window"]
    sec = SecurityLayer(out, window["seed"], plants=set(plants)).run()
    write_security(sec, out / "security", window, window["seed"], f"data/quarter/{start.isoformat()}")
    return {"start": start.isoformat(), "seed": m["seed"], "anomalies": c["anomalies"], "landlord": c["facility"]["planted"],
            "utility_outages": c["facility"]["utility_outages"], "rack_power_outages": c["facility"]["rack_power_outages"],
            "security": plants, "planted": len(data["planted"])}


def generate_all(out_root: Path = OUT, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = cfg or yaml.safe_load(CFG.read_text(encoding="utf-8"))
    return [generate_month(m, out_root / str(m["start"])) for m in cfg["months"] if not m.get("sample")]
