"""Synthetic security layer for Site AUS-1: the Customer's security systems and the Security Partner's own records.

Portfolio demo; all data fictional. Runs on a finished dataset (the committed sample or a generated month) with its
own random stream (``{seed}:security``), reads it, never writes it, and writes beside it:

* Customer systems, the evidence: ``guard_badges.csv`` and ``visitor_badges.csv`` (access control, DS-BADGE),
  ``door_alarms.jsonl`` (access control alarms), ``cameras.json``, ``camera_events.jsonl``, ``retention_audit.csv``
  (video system, DS-VMS), ``leavers.csv`` (identity feed, DS-IDM), ``tray_drives.csv`` (Redfish drive inventory of
  each compute tray that shipped, DS-REDFISH), ``access_reviews.csv``.
* Security Partner records, the claims: ``post_log.csv``, ``tour_scans.csv``, ``dispatch_log.json`` (DS-GUARD),
  ``visits.csv`` (DS-VISIT), ``chain_of_custody.csv`` and ``destruction_certificates.csv`` (DS-COC), and
  ``self_reported_weekly.json``.
* ``ground_truth/security_planted.json``: the answer key. The engine never reads it.

Escorts are drawn from the IT Partner's and the Landlord's existing hall badge-ins, and drives from the compute trays
in the existing RMA shipments, so the new records line up with the old ones.

Every month gets four planted discrepancies (a post logged staffed with no badge-in, a door alarm closed with no guard
at the door, a visitor in a hall without the escort, a drive serial shipped with no destruction certificate) and one
decoy of each kind that must not be flagged.
"""

from __future__ import annotations

import csv
import io
import json
import random
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from scorecard.sla_model import PARTNER_FILES, load_sla

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "security.yaml"
UTC = timezone.utc
KEY = "ground_truth/security_planted.json"
PLANTED_TYPES = ("post_reported_unstaffed", "door_alarm_closed_no_response", "visitor_without_escort",
                 "media_shipped_without_destruction")


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def iso(t: datetime | None) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else ""


def _csv_rows(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8", newline="")))


class SecurityLayer:
    def __init__(self, data_dir: str | Path, seed: int, cfg: dict | None = None, plants: set[str] | None = None):
        self.data = Path(data_dir)
        self.plants = set(PLANTED_TYPES) if plants is None else set(plants)    # the quarter's earlier months plant a subset
        self.cfg = cfg or yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.sla = load_sla(PARTNER_FILES["security"])
        self.rng = random.Random(f"{seed}:security")
        w = json.loads((self.data / "manifest.json").read_text(encoding="utf-8"))["window"]
        self.window = w
        self.start, self.end = parse(w["start"]), parse(w["end"])
        self.days = int((self.end - self.start).total_seconds() // 86400)
        self.partner = self.sla["parties"]["supplier"]["name"]
        self.key: list[dict] = []
        self._n = {"sir": 0, "acs": 0, "vis": 0, "cod": 0}

    # ------------------------------------------------------------------ helpers
    def _u(self, a: float, b: float) -> float:
        return self.rng.uniform(a, b)

    def _id(self, kind: str, fmt: str) -> str:
        self._n[kind] += 1
        return fmt.format(self._n[kind])

    def _serial(self, prefix: str, n: int = 9) -> str:
        return prefix + "".join(self.rng.choice(string.ascii_uppercase + string.digits) for _ in range(n))

    # ------------------------------------------------------------------ guards and posts
    def guards(self) -> list[dict]:
        n, base = self.cfg["guards"], self.cfg["guard_badge_base"]
        return [{"guard_id": f"LGP-{i:03d}", "badge_id": f"B{base + i}", "crew": f"C{(i - 1) // 8 + 1}",
                 "dps_registration": "current"} for i in range(1, n + 1)]

    def shifts(self) -> list[tuple[datetime, str]]:
        """Shift starts in UTC: night at 19:00 local (00:00Z), day at 07:00 local (12:00Z), fixed UTC-5 as elsewhere."""
        out, t = [], self.start
        while t < self.end:
            out.append((t, "night" if t.hour == 0 else "day"))
            t += timedelta(hours=12)
        return out

    def posts(self, guards: list[dict]):
        """The post log (claims) and the post reader badge-ins (evidence)."""
        by_crew: dict[str, list[dict]] = {}
        for g in guards:
            by_crew.setdefault(g["crew"], []).append(g)
        post_log, badges = [], []
        posts = self.sla["posts"]["list"]
        for k, (t, shift) in enumerate(self.shifts()):
            day = k // 2
            crew = by_crew[("C1", "C2")[(day // 2) % 2] if shift == "day" else ("C3", "C4")[(day // 2) % 2]]
            on = [p for p in posts if shift in p["shifts"]]
            for j, p in enumerate(on):
                g = crew[(j + day) % len(crew)]
                post_log.append({"shift_start": iso(t), "shift": shift, "post": p["id"], "guard_id": g["guard_id"], "reported": "Staffed"})
                badges.append({"timestamp": iso(t + timedelta(minutes=self._u(-12, 3), seconds=self.rng.randint(0, 59))),
                               "guard_id": g["guard_id"], "badge_id": g["badge_id"], "reader": p["reader"], "direction": "in",
                               "_post": p["id"], "_shift": iso(t)})
        return post_log, badges

    def tours(self, post_log: list[dict]) -> list[dict]:
        c = self.cfg["tours"]
        out = []
        for row in [r for r in post_log if r["post"] == "POST-PATROL"]:
            t0 = parse(row["shift_start"])
            for rnd in range(12 // c["every_h"]):
                for i, cp in enumerate(c["checkpoints"]):
                    due = t0 + timedelta(hours=rnd * c["every_h"], minutes=15 + 10 * i)
                    late = self.rng.random() < c["late_rate"]
                    at = due + timedelta(minutes=self._u(c["late_after_min"] + 1, 45) if late else self._u(*c["scan_jitter_min"]))
                    out.append({"shift_start": row["shift_start"], "guard_id": row["guard_id"], "round": rnd + 1,
                                "checkpoint": cp, "due": iso(due), "scanned_at": iso(at)})
        return out

    # ------------------------------------------------------------------ door alarms
    def door_alarms(self, post_log: list[dict], guards: list[dict]):
        c = self.cfg["door_alarms"]
        badge_of = {g["guard_id"]: g["badge_id"] for g in guards}
        patrol = {r["shift_start"]: r["guard_id"] for r in post_log if r["post"] == "POST-PATROL"}
        dock = {r["shift_start"]: r["guard_id"] for r in post_log if r["post"] == "POST-DOCK"}
        events = []
        for d in range(self.days):
            for _ in range(2):
                if self.rng.random() < c["held_per_day"] / 2:
                    t = self.start + timedelta(days=d, hours=self._u(13, 23.5))
                    events.append((t, "held", self.rng.choice(c["held_doors"])))
        for _ in range(c["forced_per_month"]):
            events.append((self.start + timedelta(seconds=self._u(3600, (self.end - self.start).total_seconds() - 4 * 3600)),
                           "forced", self.rng.choice(c["forced_doors"])))
        events.sort()
        alarms, dispatch, badges = [], [], []
        for t, kind, door in events:
            t = t.replace(microsecond=0)
            prio = "P1" if kind == "forced" else "P2"
            target_s = next(p for p in self.sla["priorities"] if p["id"] == prio)["acknowledge_min"] * 60
            ack_s = self._u(target_s + 10, target_s + 90) if self.rng.random() < c["late_ack_rate"] else self._u(*c["ack_s"][prio])
            ack = t + timedelta(seconds=int(ack_s))
            shift = self.start + timedelta(hours=12 * int((t - self.start).total_seconds() // 43200))
            guard = dock.get(iso(shift)) if door == "DOCK-INNER" and iso(shift) in dock else patrol[iso(shift)]
            arrive = t + timedelta(minutes=self._u(*c["response_min"][prio]), seconds=self.rng.randint(0, 5))
            # A forced exit re-latches within a couple of minutes; a held door closes once the cart or delivery is through.
            cleared = t + timedelta(minutes=self._u(0.5, 2.0) if kind == "forced" else self._u(0.3, 6.0))
            acs = self._id("acs", "ACS-{:05d}")
            sir = self._id("sir", "SIR-{:05d}")
            alarms.append({"alarm_id": acs, "timestamp": iso(t), "door": door, "event": "Door forced open" if kind == "forced" else "Door held open",
                           "priority": prio, "console_ack_at": iso(ack), "cleared_at": iso(cleared)})
            badges.append({"timestamp": iso(arrive), "guard_id": guard, "badge_id": badge_of[guard], "reader": door, "direction": "in",
                           "_alarm": acs})
            closed = arrive + timedelta(minutes=self._u(2, 12))
            dispatch.append({"sir": sir, "alarm_id": acs, "door": door, "type": "Door forced" if kind == "forced" else "Door held",
                             "priority": prio, "opened": iso(ack + timedelta(seconds=self.rng.randint(5, 40))), "dispatched": guard,
                             "on_scene": iso(arrive), "closed": iso(closed),
                             "disposition": self.rng.choice(c["dispositions"][kind]), "logged_by": "Security console"})
        return alarms, dispatch, badges

    # ------------------------------------------------------------------ visitors
    def escort_entries(self) -> list[dict]:
        """Hall badge-ins by people who can escort: IT Partner technicians (HALL-A) and Landlord engineers (Hall A/B)."""
        out = []
        for b in _csv_rows(self.data / "access" / "badge_events.csv"):
            if b["door"].startswith("HALL-") and b["direction"] == "in":
                out.append({"t": parse(b["timestamp"]), "person": b["person_id"], "party": "IT Partner", "hall": b["door"][-1]})
        for b in _csv_rows(self.data / "access" / "landlord_badge_events.csv"):
            if b["reader"] in ("Hall A", "Hall B") and b["direction"] == "in":
                out.append({"t": parse(b["timestamp"]), "person": b["person_id"], "party": "Landlord", "hall": b["reader"][-1]})
        return sorted(out, key=lambda e: (e["t"], e["person"]))

    def visits(self):
        c = self.cfg["visitors"]
        entries = self.escort_entries()
        n = round(c["per_week"] * self.days / 7)
        daytime = [e for e in entries if 13 <= e["t"].hour <= 22]     # visits run 8 a.m. to 6 p.m. local
        pool = daytime if len(daytime) >= n else entries
        chosen = sorted(self.rng.sample(pool, min(n, len(pool))), key=lambda e: (e["t"], e["person"]))
        visits, badges = [], []
        for e in chosen:
            vid = self._id("vis", "VIS-{:04d}")
            entry = e["t"] + timedelta(seconds=self.rng.randint(*c["escort_window_s"]))
            stay = timedelta(minutes=self._u(*c["stay_min"]))
            v = {"visit_id": vid, "request": f"VR-{2000 + int(vid[4:])}", "company": self.rng.choice(c["companies"]),
                 "visitor_badge": f"V-{3000 + int(vid[4:])}", "hall": f"HALL-{e['hall']}", "escort": e["person"], "escort_party": e["party"],
                 "signed_in": iso(entry - timedelta(minutes=self._u(4, 15))), "signed_out": iso(entry + stay + timedelta(minutes=self._u(2, 8)))}
            visits.append(v)
            badges.append({"timestamp": iso(entry), "badge_id": v["visitor_badge"], "reader": v["hall"], "direction": "in", "_visit": vid})
            badges.append({"timestamp": iso(entry + stay), "badge_id": v["visitor_badge"], "reader": v["hall"], "direction": "out", "_visit": vid})
        return visits, badges, entries

    # ------------------------------------------------------------------ video
    def video(self):
        c = self.cfg["cameras"]
        cams, k = [], 0
        for a in c["areas"]:
            for i in range(1, a["count"] + 1):
                cams.append({"camera": f"{a['prefix']}-{i:02d}", "area": a["where"], "recorder": c["recorders"][k % len(c["recorders"])],
                             "covers_door": i in a["doors"]})
                k += 1
        events = []
        span = (self.end - self.start).total_seconds()
        for _ in range(c["outages_per_month"] * self.days // 28):
            cam = self.rng.choice(cams)
            t = self.start + timedelta(seconds=int(self._u(600, span - 6 * 3600)))
            d = timedelta(minutes=self._u(*c["outage_min"]))
            reason = self.rng.choice(["Video loss", "Network timeout", "Camera reboot"])
            events += [{"timestamp": iso(t), "camera": cam["camera"], "recorder": cam["recorder"], "event": "Recording stopped", "reason": reason},
                       {"timestamp": iso(t + d), "camera": cam["camera"], "recorder": cam["recorder"], "event": "Recording resumed", "reason": ""}]
        rebuild = None
        if self.rng.random() < c["disk_rebuilds_per_month"]:
            rebuild = (self.rng.choice(c["recorders"]), self.rng.randint(0, self.days - 3), self.rng.randint(2, 3))
        audit = []
        for d in range(self.days):
            for r in c["recorders"]:
                days = self.rng.randint(*c["retention_days"])
                if rebuild and r == rebuild[0] and rebuild[1] <= d < rebuild[1] + rebuild[2]:
                    days = self.rng.randint(84, 89)
                audit.append({"date": (self.start + timedelta(days=d)).strftime("%Y-%m-%d"), "recorder": r,
                              "oldest_recording_days": days, "audited_at": iso(self.start + timedelta(days=d, hours=11, minutes=5))})
        return cams, events, audit

    # ------------------------------------------------------------------ identity
    def leavers(self) -> list[dict]:
        c = self.cfg["leavers"]
        prefix = {"IT Partner": "RSS-1", "Landlord": "CCF-L", "Security Partner": "LGP-1", "Customer": "CUS-0"}
        out = []
        span = (self.end - self.start).total_seconds()
        for i in range(c["per_month"] * self.days // 28):
            party = self.rng.choice(list(prefix))
            sep = self.start + timedelta(seconds=int(self._u(0, span - 10 * 3600)))
            out.append({"person_id": f"{prefix[party]}{i + 1:02d}" if party != "Security Partner" else f"LGP-1{i + 1:02d}",
                        "party": party, "badge_id": f"B7{self.rng.randint(1000, 9999)}", "separated_at": iso(sep),
                        "deactivated_at": iso(sep + timedelta(hours=self._u(*c["deactivate_h"])))})
        return sorted(out, key=lambda r: r["separated_at"])

    def access_reviews(self) -> list[dict]:
        c = self.cfg["access_reviews"]
        out = []
        y, q = self.start.year - 1, 1
        while True:
            q_end = datetime(y + (q == 4), 1 if q == 4 else 3 * q + 1, 1, tzinfo=UTC)
            due = q_end + timedelta(days=c["due_after_quarter_days"])
            if q_end > self.end:
                break
            if due >= self.start - timedelta(days=370):
                done = due - timedelta(days=self.rng.randint(*c["completed_before_due_days"]), hours=self._u(1, 6))
                out.append({"quarter": f"{y}-Q{q}", "due": iso(due), "completed_at": iso(done) if done <= self.end else "",
                            "badges_reviewed": self.rng.randint(410, 470), "badges_removed": self.rng.randint(2, 9),
                            "approved_by": "Customer site security lead" if done <= self.end else ""})
            y, q = (y + 1, 1) if q == 4 else (y, q + 1)
        return out

    # ------------------------------------------------------------------ media
    def media(self, guards: list[dict]):
        c = self.cfg["media"]
        trays = [r for r in _csv_rows(self.data / "vendor" / "rma_shipments.csv") if r["fru"] == "Compute tray"]
        drives, custody, certs = [], [], []
        for r in trays:
            removed, shipped = parse(r["removed_at"]), parse(r["shipped_at"])
            latest = shipped - timedelta(hours=c["ship_margin_h"])
            for bay in range(c["drives_per_tray"]):
                serial = self._serial("E1S")
                drives.append({"ticket": r["ticket"], "tray_serial": r["serial"], "bay": bay, "drive_serial": serial,
                               "model": "E1.S 7.68 TB NVMe"})
                room = max((latest - removed).total_seconds() / 3600, 0.2)
                hand = removed + timedelta(hours=min(self._u(*c["handover_h"]), room / 3))
                dest = hand + timedelta(hours=min(self._u(*c["destroy_h"]), (latest - hand).total_seconds() / 3600 * 0.9))
                custody.append({"drive_serial": serial, "tray_serial": r["serial"], "ticket": r["ticket"], "from": "IT Partner",
                                "to": "Security Partner", "handed_over_at": iso(hand)})
                certs.append({"certificate": self._id("cod", "COD-{:05d}"), "drive_serial": serial, "destroyed_at": iso(dest),
                              "method": "Shred to 2 mm (NIST SP 800-88 Rev. 2, Destroy)", "operator": self.rng.choice(guards)["guard_id"],
                              "witness": "IT Partner technician"})
        return trays, drives, custody, certs

    # ------------------------------------------------------------------ plants and decoys
    def plant(self, post_log, post_badges, alarms, dispatch, door_badges, visits, visitor_badges, entries, trays, drives, custody, certs):
        rng = self.rng
        if "post_reported_unstaffed" in self.plants:
            self._plant_post(rng, post_badges)
        if "door_alarm_closed_no_response" in self.plants:
            self._plant_door(rng, post_log, alarms, dispatch, door_badges)
        if "visitor_without_escort" in self.plants:
            self._plant_visit(rng, visits, visitor_badges, entries)
        if "media_shipped_without_destruction" in self.plants:
            self._plant_media(rng, trays, drives, custody, certs)

    def _plant_post(self, rng, post_badges):
        # 1. A post logged staffed with no badge-in at the post reader for the whole shift.
        cand = [b for b in post_badges if b["_post"] in ("POST-HA", "POST-HB", "POST-DOCK")]
        b = rng.choice(cand)
        post_badges.remove(b)
        self.key.append({"type": "post_reported_unstaffed", "post": b["_post"], "shift_start": b["_shift"], "guard_id": b["guard_id"],
                         "evidence": "Post log says staffed; no badge-in at the post reader during the shift"})
        decoy = rng.choice([x for x in post_badges if x["_post"] != b["_post"] or x["_shift"] != b["_shift"]])
        decoy["timestamp"] = iso(parse(decoy["_shift"]) + timedelta(minutes=rng.uniform(9, 14)))   # late relief, still staffed

    def _plant_door(self, rng, post_log, alarms, dispatch, door_badges):
        # 2. A door held alarm closed in the dispatch log with no guard at the door.
        held = [a for a in alarms if a["priority"] == "P2"]
        a = rng.choice(held)
        door_badges[:] = [x for x in door_badges if x["_alarm"] != a["alarm_id"]]
        d = next(x for x in dispatch if x["alarm_id"] == a["alarm_id"])
        d["on_scene"] = ""
        d["closed"] = iso(parse(a["console_ack_at"]) + timedelta(minutes=rng.uniform(6, 12)))
        d["disposition"] = "Door checked and secured"
        self.key.append({"type": "door_alarm_closed_no_response", "alarm_id": a["alarm_id"], "sir": d["sir"], "door": a["door"],
                         "evidence": "Dispatch log closed; no guard badge at the door between the alarm and the close"})
        other = rng.choice([x for x in dispatch if x["alarm_id"] != a["alarm_id"]])
        other["dispatched"] = rng.choice(sorted({r["guard_id"] for r in post_log if r["guard_id"] != other["dispatched"]}))

    def _plant_visit(self, rng, visits, visitor_badges, entries):
        # 3. A visitor in a hall with the named escort nowhere near the door.
        def escort_near(v, t):
            return any(e["person"] == v["escort"] and f"HALL-{e['hall']}" == v["hall"] and abs((e["t"] - t).total_seconds()) <= 120
                       for e in entries)
        for v in rng.sample(visits, len(visits)):
            ins = [x for x in visitor_badges if x["_visit"] == v["visit_id"] and x["direction"] == "in"][0]
            t = parse(ins["timestamp"]) - timedelta(minutes=rng.uniform(20, 45))
            if t > self.start + timedelta(hours=1) and not escort_near(v, t):
                ins["timestamp"] = iso(t)
                v["signed_in"] = iso(t - timedelta(minutes=rng.uniform(4, 15)))
                self.key.append({"type": "visitor_without_escort", "visit_id": v["visit_id"], "hall": v["hall"], "escort": v["escort"],
                                 "evidence": "Visitor badged into the hall; the named escort did not badge in within 2 minutes"})
                break
        planted_visit = self.key[-1]["visit_id"]
        v = rng.choice([x for x in visits if x["visit_id"] != planted_visit])
        e = next(e for e in entries if e["person"] == v["escort"] and f"HALL-{e['hall']}" == v["hall"]
                 and 0 < (parse(next(x for x in visitor_badges if x["_visit"] == v["visit_id"] and x["direction"] == "in")["timestamp"]) - e["t"]).total_seconds() <= 120)
        ins = next(x for x in visitor_badges if x["_visit"] == v["visit_id"] and x["direction"] == "in")
        ins["timestamp"] = iso(e["t"] - timedelta(seconds=rng.randint(30, 100)))    # escort a step behind, inside 2 minutes

    def _plant_media(self, rng, trays, drives, custody, certs):
        # 4. A drive serial in a shipped tray with no chain of custody and no certificate.
        if trays:
            dr = rng.choice(drives)
            custody[:] = [x for x in custody if x["drive_serial"] != dr["drive_serial"]]
            certs[:] = [x for x in certs if x["drive_serial"] != dr["drive_serial"]]
            self.key.append({"type": "media_shipped_without_destruction", "drive_serial": dr["drive_serial"], "ticket": dr["ticket"],
                             "tray_serial": dr["tray_serial"], "evidence": "Tray shipped; the drive has no handover and no destruction certificate"})
            others = [x for x in drives if x["ticket"] != dr["ticket"]]
            if others:
                o = rng.choice(others)
                shipped = parse(next(t for t in trays if t["ticket"] == o["ticket"])["shipped_at"])
                c = next(x for x in certs if x["drive_serial"] == o["drive_serial"])
                c["destroyed_at"] = iso(shipped - timedelta(minutes=rng.uniform(20, 60)))   # just in time, still before shipping

    # ------------------------------------------------------------------ self-report
    def self_report(self) -> list[dict]:
        out = []
        t = self.start
        while t < self.end:
            res = {c["id"]: 100.0 for c in self.sla["critical_service_levels"]}
            res["SEC-CSL-04"] = round(self.rng.uniform(99.95, 99.99), 2)
            out.append({"week_start": iso(t), "reported_by": self.partner, "results": res, "note": "All SLAs met. All posts staffed."})
            t += timedelta(days=7)
        return out

    # ------------------------------------------------------------------ run
    def run(self) -> dict[str, Any]:
        guards = self.guards()
        post_log, post_badges = self.posts(guards)
        tours = self.tours(post_log)
        alarms, dispatch, door_badges = self.door_alarms(post_log, guards)
        visits, visitor_badges, entries = self.visits()
        cams, cam_events, audit = self.video()
        leavers = self.leavers()
        reviews = self.access_reviews()
        trays, drives, custody, certs = self.media(guards)
        self.plant(post_log, post_badges, alarms, dispatch, door_badges, visits, visitor_badges, entries, trays, drives, custody, certs)
        strip = lambda rows: sorted(({k: v for k, v in r.items() if not k.startswith("_")} for r in rows),
                                    key=lambda r: (r["timestamp"], json.dumps(r, sort_keys=True)))
        return {
            "guards.csv": guards,
            "post_log.csv": post_log,
            "guard_badges.csv": strip(post_badges + door_badges),
            "tour_scans.csv": tours,
            "door_alarms.jsonl": alarms,
            "dispatch_log.json": dispatch,
            "visits.csv": visits,
            "visitor_badges.csv": strip(visitor_badges),
            "cameras.json": cams,
            "camera_events.jsonl": sorted(cam_events, key=lambda r: (r["timestamp"], r["camera"])),
            "retention_audit.csv": audit,
            "leavers.csv": leavers,
            "access_reviews.csv": reviews,
            "tray_drives.csv": drives,
            "chain_of_custody.csv": custody,
            "destruction_certificates.csv": certs,
            "self_reported_weekly.json": self.self_report(),
            KEY: self.key,
        }


def _dump(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0]) if rows else ["empty"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        text = buf.getvalue()
    elif path.suffix == ".jsonl":
        text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    else:
        text = json.dumps(rows, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def write_security(out: dict[str, list], sec_dir: str | Path, window: dict, seed: int, source: str) -> dict[str, int]:
    d = Path(sec_dir)
    for rel, rows in out.items():
        _dump(d / rel, rows)
    counts = {rel: len(rows) for rel, rows in out.items()}
    _dump(d / "manifest.json", {
        "generator": "scorecard.synthetic.security", "seed": seed, "window": window, "source_dataset": source, "files": counts,
        "disclaimer": "Synthetic data for a portfolio demonstration. All sites, people, and events are fictional.",
        "note": "Derived from the dataset beside it with its own random stream; ground_truth/ is the answer key and the engine never reads it."})
    return counts


def generate(data_dir: str | Path, sec_dir: str | Path, source: str = "") -> dict[str, int]:
    window = json.loads((Path(data_dir) / "manifest.json").read_text(encoding="utf-8"))["window"]
    out = SecurityLayer(data_dir, window["seed"]).run()
    return write_security(out, sec_dir, window, window["seed"], source or str(data_dir))
