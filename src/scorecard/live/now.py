"""Write the Live page's ``now.json`` from the collector's polls (docs/live/NOW_SCHEMA.md).

The collector keeps each device's latest values and feed state; this module turns them into one small document a web
server or file share serves to the Live page every poll: where the power comes from (both utility mains), every UPS
with its runtime, the ride-through per scope, the generators, the conditions the collector can see, and which feeds
are answering. It decides states with a short, published rule list (``conditions``) that follows Site health's where
the same reading exists; it does not compute redundancy, which needs Site health's group rules.

The file is replaced atomically (written beside it, then renamed), so the page never reads half a document.
"""

from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "aus1-live-now/1"
SCHEMA_FILE = Path(__file__).resolve().parents[3] / "docs" / "live" / "now.schema.json"

# upsBasicOutputStatus (PowerNet MIB) to the contract's output words
OUTPUT = {"onLine": "normal", "eConversion": "normal", "onSmartBoost": "normal", "onSmartTrim": "normal",
          "onBattery": "battery", "softwareBypass": "bypass", "switchedBypass": "bypass", "hardwareFailureBypass": "bypass"}
GEN_STATES = {"stopped", "starting", "running", "cooldown"}
FAMILY = {"mains": "power", "ups": "power", "generator": "power", "busway": "power", "cdu": "cdu", "leak": "cdu", "bms": "mechanical"}
RANK = {"degraded": 1, "lost": 2}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class NowWriter:
    """Builds and writes now.json after every poll. ``cfg`` is the collector config; its optional ``now`` block names
    the site, the take-load time, and the staleness limit. Each UPS device may give ``rating_kw``, ``role`` (it or
    cooling), and ``hall``."""

    def __init__(self, cfg: dict[str, Any], path: str | Path | None = None):
        self.cfg = cfg
        self.opts = cfg.get("now") or {}
        self.path = Path(path) if path else None
        self.history_min = int(self.opts.get("history_min", 60))
        self.kw: dict[str, deque] = {}
        self.since: dict[tuple, str] = {}

    # ------------------------------------------------------------------ the document
    def build(self, collector, now: datetime) -> dict[str, Any]:
        latest, feeds = collector.latest, collector.feeds
        devs = {d.get("site_id") or d["name"]: d for d in self.cfg["devices"]}
        answering = {f["site_id"] or f["device"] for f in feeds.values() if f["ok"]}
        mains, ups, gens = {}, {}, {}
        for sid, x in latest.items():
            k = x["kind"]
            if k == "mains":
                h = self.kw.setdefault(sid, deque(maxlen=self.history_min))
                h.append(x["kw"] if sid in answering else None)
                mains[sid] = {"v_ll": x["v_ll"], "i_avg": x["i_avg"], "kw": x["kw"], "pf": x["pf"], "hz": x["hz"],
                              "breaker": x.get("breaker"), "kw_last_hour": list(h)}
            elif k == "ups":
                d = devs[sid]
                kw = None if x["load_pct"] is None or "rating_kw" not in d else round(x["load_pct"] * d["rating_kw"] / 100, 1)
                ups[sid] = {"output": OUTPUT.get(x["status"], "other"), "load_kw": kw, "load_pct": x["load_pct"],
                            "runtime_s": x["runtime_s"], "charge_pct": x["charge_pct"]}
            elif k == "generator":
                st = str(x["state"]).lower()
                gens[sid] = {"state": st if st in GEN_STATES else "other", "kw": x["kw"], "breaker": x["breaker"], "fuel_pct": x["fuel_pct"]}
        ride = self._ride(ups, devs)
        doc = {
            "schema": SCHEMA, "site": self.opts.get("site", "AUS-1"), "generated_at": iso(now),
            "source": {"kind": "collector", "poll_interval_s": self.cfg["poll_interval_s"],
                       "note": "Read-only live collector (scripts/collect.py)."},
            "stale_after_s": int(self.opts.get("stale_after_s", 3 * self.cfg["poll_interval_s"])),
            "take_load_s": self.opts.get("take_load_s"),
            "mains": mains, "ups": ups, "ride_through": ride, "generators": gens,
            "conditions": self._conditions(latest, feeds, mains, ups, gens, ride, devs, now),
            "feeds": sorted(({"device": f["device"], "site_id": f["site_id"], "family": FAMILY[f["kind"]], "protocol": f["protocol"],
                              "ok": f["ok"], "last_ok": f["last_ok"], "error": f["error"]} for f in feeds.values()), key=lambda f: f["device"]),
        }
        return doc

    def _ride(self, ups: dict, devs: dict) -> dict[str, Any]:
        """The shortest runtime among the UPSs in each scope that carry load: the site keeps its load until the first
        of them runs out. Scopes: SITE-IT, SITE-COOLING, and each hall's IT UPSs."""
        scopes: dict[str, list[str]] = {}
        for u in ups:
            d = devs[u]
            role = d.get("role", "it")
            scopes.setdefault("SITE-IT" if role == "it" else "SITE-COOLING", []).append(u)
            if role == "it" and d.get("hall"):
                scopes.setdefault(d["hall"], []).append(u)
        out = {}
        for s, us in sorted(scopes.items()):
            have = [(ups[u]["runtime_s"], u) for u in us
                    if ups[u]["runtime_s"] is not None and (ups[u]["load_pct"] is None or ups[u]["load_pct"] > 0)]
            out[s] = {"s": min(have)[0], "set_by": min(have)[1]} if have else {"s": None, "set_by": None}
        return out

    def _conditions(self, latest, feeds, mains, ups, gens, ride, devs, now) -> list[dict[str, Any]]:
        """The rules in docs/live/NOW_SCHEMA.md, section "States the collector sets"."""
        found: list[tuple] = []          # (key, family, hall, state, text, device)

        def add(key, fam, dev, state, text):
            found.append((key, fam, devs.get(dev, {}).get("hall"), state, text, dev))

        dead = [b for b, x in mains.items() if x["v_ll"] == 0 or x["breaker"] == "open"]
        if mains and len(dead) == len(mains):
            add(("mains", "all"), "power", None, "lost", "Site on generators: every utility main dead or open")
        else:
            for b in dead:
                add(("mains", b), "power", b, "degraded", f"{b}: {'dead' if mains[b]['v_ll'] == 0 else 'main breaker open'}")
        for u, x in ups.items():
            if x["output"] == "battery":
                add(("ups", u), "power", u, "degraded", f"{u}: on battery")
            elif x["output"] == "bypass":
                add(("ups", u), "power", u, "degraded", f"{u}: on static bypass")
        take = self.opts.get("take_load_s")
        for s, r in ride.items():
            if take is not None and r["s"] is not None and r["s"] <= take:
                add(("ride", s), "power", r["set_by"], "lost", f"{s}: ride-through {r['s']} s, at or below the {take} s take-load")
        fuel = self.opts.get("fuel_amber_pct", 50.0)
        for g, x in gens.items():
            if x["fuel_pct"] is not None and x["fuel_pct"] < fuel:
                add(("fuel", g), "power", g, "degraded", f"{g}: fuel {x['fuel_pct']:.0f}%")
        for sid, x in latest.items():
            if x["kind"] == "busway":
                if not x["in_tolerance"]:
                    add(("busway", sid), "power", sid, "degraded", f"{sid}: voltage {x['voltage_ll']} V out of tolerance")
                for t in x["tapoffs_open"]:
                    add(("tap", t), "power", sid, "degraded", f"{t}: tap-off breaker open")
            elif x["kind"] == "cdu":
                bad = sorted(k for k, v in x["health"].items() if k.endswith("Health") and v not in (None, "OK"))
                if bad:
                    add(("cdu", sid), "cdu", sid, "degraded", f"{sid}: {', '.join(bad)} not OK")
            elif x["kind"] == "leak":
                for label in x["alarms"]:
                    add(("leak", sid, label), "cdu", sid, "lost", f"{sid}: leak detected ({label})")
            elif x["kind"] == "bms":
                for h in x["held"]:
                    add(("bms", sid, h), "mechanical", sid, "degraded", f"{h}: held by an operator or out of service")
        for f in feeds.values():
            if not f["ok"]:
                dev = f["site_id"] or f["device"]
                add(("feed", f["device"]), FAMILY[f["kind"]], dev, "degraded",
                    f"{dev}: not answering ({f['protocol']}); its last values are shown")
        keys = {k for k, *_ in found}
        self.since = {k: v for k, v in self.since.items() if k in keys}
        out = []
        for key, fam, hall, state, text, dev in found:
            self.since.setdefault(key, iso(now))
            out.append({"family": fam, "hall": hall, "state": state, "text": text, "device": dev, "since": self.since[key]})
        return sorted(out, key=lambda c: (-RANK[c["state"]], c["since"], c["text"]))

    # ------------------------------------------------------------------ writing
    def write(self, doc: dict[str, Any], path: str | Path | None = None) -> Path:
        """Replace the file atomically: write beside it, then rename over it."""
        p = Path(path) if path else self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, p)
        return p


def validate(doc: dict[str, Any]) -> None:
    """Raise if ``doc`` does not satisfy docs/live/now.schema.json (needs the jsonschema package)."""
    import jsonschema
    jsonschema.validate(doc, json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
