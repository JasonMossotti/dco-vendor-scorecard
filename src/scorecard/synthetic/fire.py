"""Fire protection layer: the fire panel's history log, the Landlord's impairment log, and the Customer's record of
impairment notices for one month (data/fire/). Own random stream ("<seed>:fire").

Reads, never writes, the month's dataset: its window, the VESDA events (each one reaches the panel), the Landlord's
maintenance records and MOP approvals (the VESDA inspection is a planned impairment), and the Landlord roster (who
logged it). Interface Agreement section 12 (FPI-1 to FPI-6) sets the rules the records follow.

What the month holds:

- Every VESDA event, as the panel logs it a few seconds later: an isolation is a disabled point, a fault a trouble,
  a smoke test from an isolated detector a test alarm with no outputs.
- Planned impairments: the VESDA inspection from the maintenance records, plus 3 to 5 pre-action valve trip tests and
  clean agent inspections. Each has a notice 26 to 96 hours ahead, a window, a restoration inside it, a restoration
  notice, and a fire watch when it lasts more than 4 hours. One runs past its window with an extension notice sent in
  time (a decoy).
- Sometimes an unplanned impairment: a pre-action zone's air compressor fails, notified within 15 minutes.
- Signals that are not impairments: low air for a few minutes while a compressor catches up, a ground fault on a
  panel loop, agent container pressure on a hot afternoon.
- Planted (the answer key): an impairment logged restored inside its window while the panel shows the point
  disabled for hours after, with no extension; and a pre-action control valve closed for hours that no log names.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CFG = ROOT / "config" / "fire.yaml"
SITE = ROOT / "site" / "site.yaml"
FRAMING = "Synthetic fire panel history, impairment log, and notices for a portfolio demonstration. All names and records are fictional."

IMPAIRMENT_COLS = ["imp_id", "type", "system", "devices", "reason", "mop_ref", "pm_ref", "start", "window_end", "restored_at",
                   "fire_watch_start", "fire_watch_end", "engineer"]
NOTICE_COLS = ["notice_id", "received_at", "imp_id", "kind", "text", "new_end"]
PANEL_KEYS = ["timestamp", "panel", "device", "point", "signal", "state", "text"]


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def iso(t: datetime | None) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else ""


def minute(t: datetime) -> datetime:
    """A time as a person types it into a log: to the minute."""
    return t.replace(second=0, microsecond=0)


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def fire_devices(site: dict[str, Any]) -> dict[str, list[str]]:
    """The suppression devices in halls that are not still planned (a planned hall's fire protection is not yet in service)."""
    out: dict[str, list[str]] = {"paz": [], "cas": []}
    for h in site["halls"]:
        if h["state"] == "planned":
            continue
        fls, L = h["fire_life_safety"], h["letter"]
        out["paz"] += [f"PAZ-{L}{n}" for n in range(1, fls.get("preaction_zones", 0) + 1)]
        out["cas"] += [f"CAS-{L}{n}" for n in range(1, fls.get("clean_agent_systems", 0) + 1)]
    return out


# The panel's point for each kind of signal on a device
POINT = {"tamper": "valve tamper", "low_air": "low air", "release": "release circuit", "pressure": "container pressure"}


class FireLayer:
    def __init__(self, data_dir: str | Path, seed: int, cfg: dict[str, Any] | None = None):
        self.d = Path(data_dir)
        self.cfg = cfg or yaml.safe_load(CFG.read_text(encoding="utf-8"))
        self.rng = random.Random(f"{seed}:fire")
        man = json.loads((self.d / "manifest.json").read_text(encoding="utf-8"))
        self.window = man["window"]
        self.start, self.end = parse(self.window["start"]), parse(self.window["end"])
        self.dev = fire_devices(yaml.safe_load(SITE.read_text(encoding="utf-8")))
        self.vesda = sorted(_jsonl(self.d / "facility" / "vesda_events.jsonl"), key=lambda e: e["timestamp"])
        self.pm = [r for r in _csv(self.d / "landlord" / "pm_records.csv") if r["system"] == "Fire protection"]
        self.mops = {m["mop_id"]: m for m in json.loads((self.d / "customer" / "landlord_mop_approvals.json").read_text(encoding="utf-8"))}
        self.roster = _csv(self.d / "landlord" / "roster.csv")
        self.panel: list[dict[str, Any]] = []
        self.imps: list[dict[str, Any]] = []
        self.notices: list[dict[str, Any]] = []
        self.busy: dict[str, list[tuple[datetime, datetime]]] = {}
        self.key: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ helpers
    def on_duty(self, t: datetime) -> str:
        names = [r["engineer"] for r in self.roster if parse(r["shift_start"]) <= t < parse(r["shift_start"]) + timedelta(hours=12)]
        return self.rng.choice(names) if names else "CCF-E01"

    def log(self, t: datetime, device: str, point: str, signal: str, state: str, text: str) -> None:
        self.panel.append({"timestamp": iso(t), "panel": self.cfg["panel"], "device": device, "point": point,
                           "signal": signal, "state": state, "text": text})

    def free(self, device: str, a: datetime, b: datetime, margin_h: float = 2) -> bool:
        m = timedelta(hours=margin_h)
        return a >= self.start + timedelta(hours=2) and b <= self.end - timedelta(hours=2) and \
            all(b + m <= x or a - m >= y for x, y in self.busy.get(device, []))

    def take(self, device: str, a: datetime, b: datetime) -> None:
        self.busy.setdefault(device, []).append((a, b))

    def slot(self, devices: list[str], hours: float, weekday: bool = True, utc_hours: tuple[int, int] | None = None,
             tries: int = 400) -> tuple[str, datetime] | None:
        span = (self.end - self.start).total_seconds()
        for _ in range(tries):
            dev = self.rng.choice(devices)
            t = self.start + timedelta(seconds=self.rng.uniform(0, span))
            if utc_hours:
                t = t.replace(hour=self.rng.randint(*utc_hours), minute=self.rng.randrange(0, 60, 5), second=0)
            if weekday and t.weekday() >= 5:
                continue
            if self.free(dev, t, t + timedelta(hours=hours)):
                return dev, t
        return None

    def notice(self, at: datetime, imp: str, kind: str, text: str, new_end: datetime | None = None) -> None:
        self.notices.append({"received_at": iso(at), "imp_id": imp, "kind": kind, "text": text, "new_end": iso(new_end)})

    # ------------------------------------------------------------------ the month
    def run(self) -> dict[str, Any]:
        self.mirror_vesda()
        self.planned()
        self.unplanned()
        self.unlogged()
        self.noise()
        return self.finish()

    def mirror_vesda(self) -> None:
        """Every VESDA event reaches the panel a few seconds later; an inspection's isolation is a planned impairment."""
        isolated: dict[str, datetime] = {}
        for e in self.vesda:
            t = parse(e["timestamp"]) + timedelta(seconds=self.rng.randint(1, 20))
            det = e["detector"]
            if e["event"] == "Isolate":
                isolated[det] = parse(e["timestamp"])
                self.log(t, det, "detector", "Disable", "Active", f"Point disabled: {e['detail'].lower()}")
            elif e["event"] == "Normal" and det in isolated:
                self.log(t, det, "detector", "Disable", "Cleared", "Point enabled")
                self.vesda_impairment(det, isolated.pop(det), t)
            elif e["event"] == "Fault":
                self.log(t, det, "detector", "Trouble", "Active", e["detail"])
            elif e["event"] == "Normal":
                self.log(t, det, "detector", "Trouble", "Cleared", e["detail"])
            elif det in isolated:
                self.log(t, det, "detector", "Alarm", "Test", f"{e['level']} from a disabled point: no outputs")
            else:
                self.log(t, det, "detector", "Alarm", "Active", e["level"] or e["event"])
            self.take(det, parse(e["timestamp"]), parse(e["timestamp"]) + timedelta(minutes=1))

    def vesda_impairment(self, det: str, start: datetime, restored: datetime) -> None:
        pm = next((p for p in self.pm if p["asset"] == det and abs((parse(p["completed_at"]) - restored).total_seconds()) < 300), None)
        mop = self.mops.get(pm["mop_ref"]) if pm and pm["mop_ref"] else None
        end = parse(mop["window_end"]) if mop else minute(restored) + timedelta(minutes=30)
        imp = {"type": "planned", "system": "Smoke detection", "devices": [det], "reason": pm["task"] if pm else "VESDA inspection",
               "mop_ref": mop["mop_id"] if mop else "", "pm_ref": pm["task_id"] if pm else "", "start": minute(start),
               "window_end": end, "restored_at": minute(restored), "engineer": pm["engineer"] if pm else self.on_duty(start)}
        self.add_planned(imp, restored)

    def add_planned(self, imp: dict[str, Any], panel_restored: datetime, extension: datetime | None = None) -> None:
        """The impairment, its notices, and its fire watch, all as the Landlord's records show them."""
        self.imps.append(imp)
        imp["_n"] = len(self.imps)
        start, restored = imp["start"], imp["restored_at"]
        self.notice(start - timedelta(hours=self.rng.uniform(26, 96)), imp, "start",
                    f"Planned impairment of {', '.join(imp['devices'])} ({imp['reason']}), window to {iso(imp['window_end'])}")
        if extension:
            self.notice(imp["window_end"] - timedelta(minutes=self.rng.uniform(10, 40)), imp, "extension",
                        f"Work on {', '.join(imp['devices'])} needs more time; new end time given", extension)
        self.notice(restored + timedelta(minutes=self.rng.uniform(2, 20)), imp, "restored", f"{', '.join(imp['devices'])} restored to service")
        self.watch(imp)
        for dv in imp["devices"]:
            self.take(dv, start, max(panel_restored, imp["window_end"]))

    def watch(self, imp: dict[str, Any]) -> None:
        """A fire watch for an impairment that lasts more than 4 hours (FPI-3): from the start when the window says so,
        from just before the fourth hour when the work runs over."""
        start, restored = imp["start"], imp["restored_at"]
        if restored - start <= timedelta(hours=4):
            imp["fire_watch_start"] = imp["fire_watch_end"] = None
            return
        fw = start if imp["window_end"] - start > timedelta(hours=4) else start + timedelta(hours=4) - timedelta(minutes=self.rng.uniform(5, 30))
        imp["fire_watch_start"] = minute(fw)
        imp["fire_watch_end"] = minute(restored + timedelta(minutes=self.rng.uniform(0, 10)))

    def planned(self) -> None:
        c = self.cfg["planned"]
        jobs = c["jobs"]
        n = self.rng.randint(*c["count"])
        ext_left = self.cfg["noise"]["extension"]
        late_left = self.cfg["planted"]["restored_late"]
        for k in range(n):
            job = jobs[k % len(jobs)] if k < len(jobs) else self.rng.choice(jobs)
            window = round(self.rng.uniform(*job["window_h"]) * 2) / 2
            late = late_left > 0 and k == 0                     # the first job carries the planted late restoration
            ext = not late and ext_left > 0 and k == 1          # the second runs over with an extension (decoy)
            over = self.rng.uniform(1, 3) if ext else 0
            tail = self.rng.uniform(*self.cfg["planted"]["late_hours"]) if late else 0
            got = self.slot(self.dev[job["kind"]], window + over + tail + 1, utc_hours=tuple(c["utc_start_hours"]))
            if not got:
                continue
            dev, start = got
            end = start + timedelta(hours=window)
            used = window * self.rng.uniform(*job["used"])
            restored = start + timedelta(hours=used, seconds=self.rng.randint(0, 59))
            if ext:
                restored = end + timedelta(hours=over, seconds=self.rng.randint(0, 59))
            panel_restored = end + timedelta(hours=tail, seconds=self.rng.randint(0, 59)) if late else restored
            kind = "tamper" if job["kind"] == "paz" else "release"
            sig = "Supervisory" if kind == "tamper" else "Disable"
            self.log(start + timedelta(seconds=self.rng.randint(5, 50)), dev, POINT[kind], sig, "Active",
                     "Control valve closed" if kind == "tamper" else "Release circuit disabled")
            if job["kind"] == "paz":                          # the trip drops the air; the zone is re-pressurized
                a = start + timedelta(minutes=self.rng.uniform(20, 40))
                self.log(a, dev, POINT["low_air"], "Supervisory", "Active", "Low air pressure")
                self.log(a + timedelta(minutes=self.rng.uniform(20, 50)), dev, POINT["low_air"], "Supervisory", "Cleared", "Air pressure normal")
            self.log(panel_restored + timedelta(seconds=self.rng.randint(0, 30)), dev, POINT[kind], sig, "Cleared",
                     "Control valve open" if kind == "tamper" else "Release circuit enabled")
            imp = {"type": "planned", "system": job["system"], "devices": [dev], "reason": job["task"], "mop_ref": "", "pm_ref": "",
                   "start": minute(start), "window_end": minute(end), "restored_at": minute(restored), "engineer": self.on_duty(start)}
            self.add_planned(imp, panel_restored, extension=minute(end + timedelta(hours=over + 1)) if ext else None)
            if late:
                late_left -= 1
                self.key.append({"kind": "restored_late", "device": dev, "logged_restored": iso(imp["restored_at"]),
                                 "panel_restored": iso(panel_restored)})
                imp["_key"] = self.key[-1]
            if ext:
                ext_left -= 1

    def unplanned(self) -> None:
        c = self.cfg["unplanned"]
        if self.rng.random() >= c["probability"]:
            return
        hours = self.rng.uniform(*c["hours"])
        got = self.slot(self.dev["paz"], hours + 1, weekday=False)
        if not got:
            return
        dev, start = got
        restored = start + timedelta(hours=hours)
        self.log(start, dev, POINT["low_air"], "Supervisory", "Active", "Low air pressure")
        self.log(restored, dev, POINT["low_air"], "Supervisory", "Cleared", "Air pressure normal")
        found = start + timedelta(minutes=self.rng.uniform(3, 10))
        imp = {"type": "unplanned", "system": "Pre-action sprinkler", "devices": [dev], "reason": "Air compressor failed; zone held on nitrogen bottles",
               "mop_ref": "", "pm_ref": "", "start": minute(start), "window_end": None, "restored_at": minute(restored),
               "engineer": self.on_duty(start)}
        self.imps.append(imp)
        imp["_n"] = len(self.imps)
        self.notice(found + timedelta(minutes=self.rng.uniform(1, 3)), imp, "start", f"Unplanned impairment of {dev}: air compressor failed")
        self.notice(restored + timedelta(minutes=self.rng.uniform(2, 20)), imp, "restored", f"{dev} restored to service")
        self.watch(imp)
        self.take(dev, start, restored)

    def unlogged(self) -> None:
        """Planted: a pre-action control valve closed for hours with nothing on the log and no notice."""
        for _ in range(self.cfg["planted"]["unlogged"]):
            hours = self.rng.uniform(*self.cfg["planted"]["unlogged_hours"])
            got = self.slot(self.dev["paz"], hours, utc_hours=(14, 20))
            if not got:
                continue
            dev, start = got
            restored = start + timedelta(hours=hours)
            self.log(start, dev, POINT["tamper"], "Supervisory", "Active", "Control valve closed")
            self.log(restored, dev, POINT["tamper"], "Supervisory", "Cleared", "Control valve open")
            self.take(dev, start, restored)
            self.key.append({"kind": "unlogged", "device": dev, "start": iso(start), "end": iso(restored)})

    def noise(self) -> None:
        c = self.cfg["noise"]
        for key, kind, dev_kind, texts in (("low_air_short", "low_air", "paz", ("Low air pressure", "Air pressure normal")),
                                           ("agent_pressure", "pressure", "cas", ("Container pressure low", "Container pressure normal"))):
            for _ in range(self.rng.randint(*c[key])):
                m = self.rng.uniform(*c[f"{key}_minutes"])
                got = self.slot(self.dev[dev_kind], m / 60, weekday=False)
                if not got:
                    continue
                dev, t = got
                self.log(t, dev, POINT[kind], "Supervisory", "Active", texts[0])
                self.log(t + timedelta(minutes=m), dev, POINT[kind], "Supervisory", "Cleared", texts[1])
                self.take(dev, t, t + timedelta(minutes=m))
        for _ in range(self.rng.randint(*c["ground_fault"])):
            m = self.rng.uniform(*c["ground_fault_minutes"])
            t = self.start + timedelta(seconds=self.rng.uniform(3 * 3600, (self.end - self.start).total_seconds() - 3 * 3600))
            loop = f"Loop {self.rng.randint(1, 4)}"
            self.log(t, self.cfg["panel"], loop, "Trouble", "Active", "Ground fault")
            self.log(t + timedelta(minutes=m), self.cfg["panel"], loop, "Trouble", "Cleared", "Ground fault cleared")

    def finish(self) -> dict[str, Any]:
        self.panel.sort(key=lambda e: (e["timestamp"], e["device"], e["point"]))
        order = sorted(self.imps, key=lambda i: (i["start"], i["devices"][0]))
        for k, imp in enumerate(order, 1):
            imp["imp_id"] = f"IMP-{k:04d}"
            if "_key" in imp:
                imp["_key"]["imp_id"] = imp["imp_id"]
        rows = [{c: (iso(imp.get(c)) if isinstance(imp.get(c), datetime) else
                     ";".join(imp[c]) if c == "devices" else imp.get(c) or "") for c in IMPAIRMENT_COLS} for imp in order]
        notes = sorted(self.notices, key=lambda x: (x["received_at"], x["imp_id"]["imp_id"]))
        notes = [{"notice_id": f"FPN-{k:04d}", **{**x, "imp_id": x["imp_id"]["imp_id"]}} for k, x in enumerate(notes, 1)]
        return {"panel": self.panel, "impairments": rows, "notices": notes, "key": sorted(self.key, key=lambda x: (x["kind"], x["device"]))}


def _dump(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_fire(layer: FireLayer, out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, Any]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "facp_history.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for e in out["panel"]:
            f.write(json.dumps({k: e[k] for k in PANEL_KEYS}, sort_keys=True) + "\n")
    _dump(dest / "impairments.csv", out["impairments"], IMPAIRMENT_COLS)
    _dump(dest / "impairment_notices.csv", out["notices"], NOTICE_COLS)
    (dest / "answer_key.json").write_text(json.dumps(out["key"], indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    man = {"disclaimer": FRAMING, "source": source, "window": layer.window,
           "files": {"facp_history.jsonl": len(out["panel"]), "impairments.csv": len(out["impairments"]),
                     "impairment_notices.csv": len(out["notices"])}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
