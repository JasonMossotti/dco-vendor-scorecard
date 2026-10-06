"""Synthetic change-work layer for Site AUS-1: declarations, delivery logs, and planted cases.

Portfolio demo; all data fictional. Runs on a finished dataset (the committed
sample or a generated month) with its own random stream, and writes beside it:

* ``impact_declarations.json``: one structured declaration per change record,
  derived from the change-type catalog in ``config/change_alarms.yaml``.
* ``notification_log.json``: what each partner sent the Customer under today's
  SLAs (P1 paged; P2 by one call or email; nothing on change scope).
* ``ground_truth/change_alarm_key.json``: the answer key. On the sample it holds
  only the natural case (the rack outage during tap-off work); robustness months
  also get planted cases and decoys, appended to that month's own files.

The committed sample's records are never touched (``plant=False``).
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scorecard import alarms as A
from scorecard import site_model as S
from scorecard.connectors import FileConnector

DECL, LOG, KEY = "impact_declarations.json", "notification_log.json", "ground_truth/change_alarm_key.json"
RECIPIENT = {"page": "Customer Incident Commander", "email": "Customer site lead", "phone": "Customer site lead"}


def _iso(dt: datetime) -> str:
    return A.iso(dt)


def _read(path: Path) -> list[dict]:
    if path.suffix == ".jsonl":
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, rows: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jsonl":
        rows = sorted(rows, key=lambda r: (r["timestamp"], json.dumps(r, sort_keys=True)))
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8", newline="\n")
    else:
        path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


class ChangeLayer:
    def __init__(self, data_dir: str | Path, seed: int, cfg: dict | None = None, utc_offset_h: int = -5):
        self.dir = Path(data_dir)
        self.cfg = cfg or A.load_config()
        self.rng = random.Random(f"{seed}:changes")        # independent of every other stream
        self.seed = seed
        self.offset = timedelta(hours=utc_offset_h)
        man = _read(self.dir / "manifest.json")
        self.start, self.end = A.parse(man["window"]["start"]), A.parse(man["window"]["end"])
        self.site = S.load_site()
        self.topology = _read(self.dir / "site" / "topology.json")
        self.sitemap = A.SiteMap(self.site, self.topology)
        self.key: list[dict] = []
        self.busy: list[tuple[datetime, datetime, str]] = []   # (start, end, hall) taken by plants

    # ------------------------------------------------------------------ helpers
    def _f(self, rel: str) -> Path:
        return self.dir / rel

    def _append(self, rel: str, rows: list[dict]) -> None:
        cur = _read(self._f(rel))
        _write(self._f(rel), cur + rows)

    def _slot(self, hall: str, hours: float, local=(9, 15), devices: set[str] = frozenset()) -> datetime:
        """A work time with nothing else going on in the hall or on the devices, several hours either side."""
        margin = timedelta(hours=6)
        changes = A.change_records(FileConnector(self.dir))
        for _ in range(2000):
            t = self.start + timedelta(hours=self.rng.uniform(48, (self.end - self.start).total_seconds() / 3600 - 48))
            if not local[0] <= (t + self.offset).hour < local[1]:
                continue
            t = t.replace(second=self.rng.randint(0, 59), microsecond=0)
            lo, hi = t - margin, t + timedelta(hours=hours) + margin
            if any(s < hi and lo < e and h == hall for s, e, h in self.busy):
                continue
            if any(A.parse(c["window_start"]) < hi and lo < A.parse(c["window_end"])
                   and any(self.sitemap.hall_of(x.replace("rack:", ""), x[5:] if x.startswith("rack:") else None) == hall
                           for x in c["assets"]) for c in changes):
                continue
            if any(lo <= a.raised <= hi and a.keys & devices for a in self.clean):
                continue
            self.busy.append((lo, hi, hall))
            return t
        raise RuntimeError("no quiet slot for a planted change")

    def _mop(self, title: str, asset: str, ws: datetime, we: datetime) -> str:
        mops = _read(self._f("customer/landlord_mop_approvals.json"))
        n = max(int(m["mop_id"].split("-")[1]) for m in mops) + 1 if mops else 301
        mid = f"MOP-{n}"
        mops.append({"mop_id": mid, "title": title, "assets": [asset], "window_start": _iso(ws), "window_end": _iso(we),
                     "approved_by": "Customer change board", "approved_at": _iso(ws - timedelta(days=self.rng.randint(12, 21)))})
        _write(self._f("customer/landlord_mop_approvals.json"), sorted(mops, key=lambda m: (m["window_start"], m["mop_id"])))
        return mid

    def _pump(self, cdu: str, pump: int, t: datetime, value: str) -> dict:
        return {"timestamp": _iso(t), "cdu": cdu, "resource": f"/redfish/v1/ThermalEquipment/CDUs/{cdu}/Pumps/{pump}",
                "property": "Status.State", "value": value}

    # ------------------------------------------------------------------ planted cases (robustness months only)
    def plant(self) -> None:
        n = self.cfg["synthetic"]["robustness_plants"]
        halls = sorted(self.sitemap.halls)
        for _ in range(n.get("undeclared_equipment", 0)):
            h = self.rng.choice(halls)
            i, j = self.rng.sample(self.sitemap.halls[h]["cdus"], 2)
            t = self._slot(h, 2, devices={i, j})
            m = self._mop(f"Filter change and coolant sample: {i}", i, t - timedelta(minutes=30), t + timedelta(minutes=90))
            wrong = t + timedelta(minutes=self.rng.uniform(3, 8))
            self._append("facility/cdu_redfish_events.jsonl", [
                self._pump(i, 2, t, "Disabled"), self._pump(i, 2, t + timedelta(minutes=30), "Enabled"),
                self._pump(j, 1, wrong, "Disabled"), self._pump(j, 1, wrong + timedelta(minutes=self.rng.uniform(6, 15)), "Enabled")])
            self.key.append({"kind": "change", "type": "undeclared_equipment", "change": m, "device": j, "signal": "Pump isolated",
                             "at": _iso(wrong), "expect": A.OUT_OF_SCOPE})
        for _ in range(n.get("exceeds_declared", 0)):
            prod = [r for r in self.topology["racks"] if r["state"] == "production"]
            rack = self.rng.choice(prod)
            R = rack["rack"]
            t = self._slot(R[0], 5, local=(1, 2), devices={f"rack:{R}"})
            ws = t.replace(minute=0, second=0)
            we = ws + timedelta(hours=4)
            cab = _read(self._f("customer/cab_changes.json"))
            cid = f"CHG{2_049_000 + 31 * (len(cab) + 1):07d}"
            cab.append({"change_id": cid, "summary": f"Compute tray firmware 1.3.7 -> 1.3.8 on rack {R}", "rack": R,
                        "approved_by": "Customer CAB", "window_start": _iso(ws), "window_end": _iso(we), "state": "Approved"})
            _write(self._f("customer/cab_changes.json"), cab)
            fail = ws + timedelta(minutes=self.rng.uniform(40, 120))
            sw = self.rng.choice(rack["switch_trays"])["name"]
            self._append("telemetry/nmx_events.jsonl", [
                {"message": "NVLink switch tray unreachable; NVLink domain degraded", "rack": R, "state": "failed",
                 "timestamp": _iso(fail), "unit": f"NVLink switch tray {sw}"},
                {"message": "NVLink domain healthy", "rack": R, "state": "healthy",
                 "timestamp": _iso(fail + timedelta(minutes=self.rng.uniform(40, 120))), "unit": f"NVLink switch tray {sw}"}])
            self.key.append({"kind": "change", "type": "exceeds_declared", "change": cid, "device": f"rack:{R}",
                             "signal": "NVLink switch tray failed", "at": _iso(fail), "expect": A.OUT_OF_SCOPE})
        for _ in range(n.get("early_start", 0)):
            bw = self.rng.choice(sorted(self.sitemap.segments))
            h = bw[3]
            t = self._slot(h, 3, devices={bw, self.sitemap.segments[bw]["sibling"]})
            tap = f"TO-{h}{self.rng.randint(1, 32):02d}"
            m = self._mop(f"Energize tap-off {tap} for a new rack (HO-4)", bw, t, t + timedelta(minutes=120))
            opened = t - timedelta(minutes=self.rng.uniform(30, 90))
            self._append("facility/busway_cpm_events.jsonl", [
                {"timestamp": _iso(opened), "busway": bw, "tapoff": tap, "point": "Tap-off breaker", "event": "Breaker open"},
                {"timestamp": _iso(opened + timedelta(minutes=self.rng.uniform(15, 25))), "busway": bw, "tapoff": tap,
                 "point": "Tap-off breaker", "event": "Breaker closed"}])
            self.key.append({"kind": "change", "type": "early_start", "change": m, "device": bw, "signal": "Tap-off breaker open",
                             "at": _iso(opened), "expect": A.OUT_OF_WINDOW})
        for _ in range(n.get("overrun", 0)):
            h = self.rng.choice(halls)
            k = self.rng.choice(self.sitemap.halls[h]["cdus"])
            ch = self.rng.choice(self._chillers())
            t = self._slot(h, 5, devices={k, ch})
            ws, we = t - timedelta(minutes=30), t + timedelta(minutes=90)
            m = self._mop(f"Filter change and coolant sample: {k}", k, ws, we)
            back = we + timedelta(minutes=self.rng.uniform(45, 120))
            self._append("facility/cdu_redfish_events.jsonl", [self._pump(k, 2, t, "Disabled"), self._pump(k, 2, back, "Enabled")])
            g = timedelta(minutes=self.cfg["grace_min"])
            self.key.append({"kind": "change", "type": "overrun", "change": m, "device": k, "signal": "Change window overrun",
                             "at": _iso(we + g), "expect": A.OUT_OF_WINDOW})
            if n.get("decoy_unconnected", 0):
                at = t + timedelta(minutes=self.rng.uniform(10, 40))
                self._append("facility/bms_events.jsonl", [
                    {"alarm": "Condenser fan fault", "device": ch, "kind": "alarm", "priority": "P3", "state": "active", "timestamp": _iso(at)},
                    {"alarm": "Condenser fan fault", "device": ch, "kind": "alarm", "state": "cleared",
                     "timestamp": _iso(at + timedelta(minutes=self.rng.uniform(30, 60)))}])
                self.key.append({"kind": "change", "type": "decoy_unconnected", "change": m, "device": ch,
                                 "signal": "Condenser fan fault", "at": _iso(at), "expect": A.NOT_CHANGE})
        if n.get("decoy_within_grace", 0) or n.get("decoy_other_domain", 0):
            h = self.rng.choice(halls)
            ups = self.rng.choice(self.sitemap.halls[h]["ups"])
            racks = sorted({r for bw, s in self.sitemap.segments.items() if s["ups"] == ups for r in s["racks"]})
            t = self._slot(h, 5, devices={ups} | {f"rack:{r}" for r in racks})
            ws, we = t - timedelta(minutes=30), t + timedelta(minutes=180)
            m = self._mop(f"Preventive maintenance and battery health check: {ups}", ups, ws, we)
            back = we + timedelta(minutes=self.rng.uniform(4, 12))
            self._append("facility/ups_nmc_events.jsonl", [
                {"timestamp": _iso(t), "ups": ups, "event": "upsBasicOutputStatus switchedBypass", "severity": "warning"},
                {"timestamp": _iso(back), "ups": ups, "event": "upsBasicOutputStatus onLine", "severity": "informational"}])
            self.key.append({"kind": "change", "type": "decoy_within_grace", "change": m, "device": ups,
                             "signal": "UPS on maintenance bypass", "at": _iso(t), "expect": A.EXPECTED})
            topo = {r["rack"]: r for r in self.topology["racks"]}
            tray = self.rng.choice(topo[self.rng.choice(racks)]["compute_trays"])
            at = t + timedelta(minutes=self.rng.uniform(20, 120))
            self._append("telemetry/dcgm_xid_events.jsonl", [
                {"gpu_index": self.rng.randint(0, 3), "host": tray["host"], "message": "Contained ECC error",
                 "timestamp": _iso(at), "tray_serial": tray["serial"], "xid": 94}])
            self.key.append({"kind": "change", "type": "decoy_other_domain", "change": m, "device": tray["host"],
                             "signal": "GPU error (XID)", "at": _iso(at), "expect": A.NOT_CHANGE})

    def _chillers(self) -> list[str]:
        return [e["id"] for e in S.equipment(self.site) if e["id"].startswith("CH-")]

    # ------------------------------------------------------------------ the natural case
    def natural_key(self) -> None:
        """The rack outage during A-side tap-off work: what the check must find in every month."""
        planted = _read(self._f("ground_truth/facility_planted_discrepancies.json"))
        mops = _read(self._f("customer/landlord_mop_approvals.json"))
        bus = _read(self._f("facility/busway_cpm_events.jsonl"))
        g = timedelta(minutes=self.cfg["grace_min"])
        for p in planted:
            if p.get("scenario") != "rack_power_outage":
                continue
            ev = next(e for e in bus if e["busway"] == p["busway"] and e["timestamp"] == p["at"])
            rack = ev["rack"]
            mop = next(m for m in mops if m["title"] == f"Retorque A-side tap-off for rack {rack}")
            t0, we = p["at"], A.parse(mop["window_end"])
            self.key += [
                {"kind": "change", "type": "natural_wrong_feed", "change": mop["mop_id"], "device": p["busway"],
                 "signal": "Tap-off breaker open", "at": t0, "expect": A.OUT_OF_SCOPE},
                {"kind": "change", "type": "natural_rack_power", "change": mop["mop_id"], "device": f"Rack {rack}",
                 "signal": "Rack input power lost (both feeds)", "at": t0, "expect": A.OUT_OF_SCOPE},
                {"kind": "change", "type": "natural_rack_outage", "change": mop["mop_id"], "device": f"Rack {rack}",
                 "signal": "Rack outage", "at": t0, "expect": A.OUT_OF_SCOPE},
                {"kind": "change", "type": "natural_overrun", "change": mop["mop_id"], "device": mop["assets"][0],
                 "signal": "Change window overrun", "at": _iso(we + g), "expect": A.OUT_OF_WINDOW}]

    # ------------------------------------------------------------------ what the partners send today
    def notification_log(self, plant: bool) -> list[dict]:
        nt = self.cfg["synthetic"]["notify_today"]
        alarms = A.normalize(FileConnector(self.dir), self.cfg)
        drop, late = set(), set()
        if plant:
            n = self.cfg["synthetic"]["robustness_plants"]
            pool = [a for a in alarms if a.severity == "critical" and a.signal != "Smoke alarm"]
            picks = self.rng.sample(pool, min(len(pool), n.get("notify_missing", 0) + n.get("notify_late", 0)))
            drop = {a.id for a in picks[: n.get("notify_missing", 0)]}
            late = {a.id for a in picks[n.get("notify_missing", 0):]}
            for a in picks:
                self.key.append({"kind": "notification", "type": "notify_missing" if a.id in drop else "notify_late",
                                 "party": a.partner, "device": a.device, "at": _iso(a.raised),
                                 "expect": "missing" if a.id in drop else "late"})
        log = []
        for a in alarms:
            if a.severity == "critical":
                spec = nt["critical"]
            elif a.severity == "major":
                spec = nt["major"][a.partner]
            else:
                continue
            delay = self.rng.uniform(*spec["delay_min"])
            if a.id in drop:
                continue
            if a.id in late:
                delay = self.rng.uniform(9, 20)
            for k, ch in enumerate(spec["channels"]):
                log.append({"party": a.partner, "device": a.device, "signal": a.signal, "alarm_time": _iso(a.raised),
                            "sent_at": _iso(a.raised + timedelta(minutes=delay + 0.2 * k)), "channel": ch,
                            "recipient": RECIPIENT[ch], "change_ref": ""})
        return sorted(log, key=lambda x: (x["sent_at"], x["party"], x["device"], x["channel"]))

    # ------------------------------------------------------------------ everything
    def run(self, plant: bool = False) -> dict[str, Any]:
        self.clean = A.normalize(FileConnector(self.dir), self.cfg)
        if plant:
            self.plant()
        self.natural_key()
        decls = [A.declare(c, self.cfg) for c in A.change_records(FileConnector(self.dir))]
        log = self.notification_log(plant)
        key = sorted(self.key, key=lambda k: (k["at"], k["type"]))
        for n, k in enumerate(key, 1):
            k["case_id"] = f"CK-{n:03d}"
        return {"declarations": decls, "log": log, "key": key}


def write_changes(out: dict, changes_dir: str | Path, window: dict, seed: int, source: str) -> dict[str, int]:
    d = Path(changes_dir)
    files = {DECL: out["declarations"], LOG: out["log"], KEY: out["key"]}
    for rel, rows in files.items():
        _write(d / rel, rows)
    counts = {rel: len(rows) for rel, rows in files.items()}
    _write(d / "manifest.json", {
        "generator": "scorecard.synthetic.changes", "seed": seed, "window": window, "source_dataset": source, "files": counts,
        "disclaimer": "Synthetic data for a portfolio demonstration. All sites, people, and events are fictional.",
        "note": "Derived from the dataset beside it with its own random stream; ground_truth/ is the answer key and the check never reads it."})
    return counts
