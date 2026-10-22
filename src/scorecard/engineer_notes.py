"""Engineer notes: the fields a technician, engineer, or officer fills in by hand on each Incident Portal record.

The partners' systems carry free-text and hand-entered fields beside the fields the system stamps: a ServiceNow
incident's work notes and close notes, a Maximo work order's work log and failure reporting, a PM's checklist and
readings, a MOP's step log, a guard's narrative, an impairment's tag and fire watch. The sample month's records
carry few of them, so this module composes them for every record from the record's own facts, on its own random
stream ({seed}:engineer_notes:<record>), and a handful are written by hand in tickets/engineer_notes.yaml.

Notes follow the partner's own record (what the person knew and wrote), never the Customer's measurement, and add
no finding: where records do not reconcile, the finding on the record says so. check() proves every time, number,
serial, device, person ID, and record number in every note is the record's own, and that no person is named.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config" / "engineer_notes.yaml"
HAND = ROOT / "tickets" / "engineer_notes.yaml"
OUT = ROOT / "data" / "engineer_notes"
AUDIT = ROOT / "data" / "audit"
CDT = timezone(timedelta(hours=-5))
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/%-]*[A-Za-z0-9%]|[0-9]")


def tokens(s: str) -> set[str]:
    return set(TOKEN.findall(s))


def config(path: Path = CFG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def hand_written(path: Path = HAND) -> dict[str, Any]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def hm(s: str) -> str:
    """A UTC timestamp as the Central clock time a person writes (CDT, 24-hour)."""
    return _t(s).astimezone(CDT).strftime("%H:%M")


def hours(a: str, b: str) -> float:
    return round((_t(b) - _t(a)).total_seconds() / 3600, 2)


def audit_plants(audit_dir: Path = AUDIT) -> dict[str, set[str]]:
    """Record -> the walk-down items the Quality audit found missing; notes on those records never claim them."""
    p = audit_dir / "answer_key.json"
    out: dict[str, set[str]] = {}
    for k in json.loads(p.read_text(encoding="utf-8")) if p.exists() else []:
        out.setdefault(k["record"], set()).add(k["kind"])
    return out


class Composer:
    def __init__(self, records: list[dict[str, Any]], seed: int, cfg: dict[str, Any] | None = None,
                 plants: dict[str, set[str]] | None = None):
        self.by_id = {r["id"]: r for r in records}
        self.seed, self.cfg, self.plants = seed, cfg or config(), plants or {}

    # -- helpers ---------------------------------------------------------------------------------------------
    def pick(self, rng: random.Random, x: Any) -> str:
        return rng.choice(x) if isinstance(x, list) else x

    def events(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        evs = list(r["timeline"])
        for ref in r["related"]:
            if ref in self.by_id:
                evs += self.by_id[ref]["timeline"]
        return sorted(evs, key=lambda e: e["t"])

    def first(self, r: dict[str, Any], test) -> str | None:
        return next((e["t"] for e in self.events(r) if test(e)), None)

    @staticmethod
    def field(spec: dict[str, Any], **v: Any) -> dict[str, Any]:
        return {"key": spec["key"], "label": spec["label"], "visibility": spec["visibility"], "kind": spec["kind"], **v}

    # -- compose ---------------------------------------------------------------------------------------------
    def compose(self, r: dict[str, Any]) -> dict[str, Any]:
        rng = random.Random(f"{self.seed}:engineer_notes:{r['id']}")
        t = self.cfg["types"][r["type"]]
        vals = getattr(self, "_" + r["type"])(r, rng)
        return {"id": r["id"], "type": r["type"], "title": t["title"], "system": t["system"], "source": "composed",
                "fields": [self.field(s, **vals[s["key"]]) for s in t["fields"] if s["key"] in vals]}

    def _inc(self, r, rng):
        c, n = self.cfg["inc"], r["native"]
        by, notes = r["assigned"], r["notes"]
        ci = n.get("configuration_item") or r["device"]
        link = r["category"] == "optic_link"
        if link:
            ci = r["summary"].split(" ", 1)[1] if r["summary"].startswith("Link ") else ci
        where = f"rack {r['rack']}" if r["rack"] else r["location"]
        fill = dict(ci=ci, where=where, summary=r["summary"], close_code=n.get("close_code", ""))
        out: dict[str, dict] = {"work_notes": {"entries": [{"at": x["at"], "by": x["by"], "text": x["text"]} for x in notes]}}
        com = []
        ack = next((x for x in notes if x["text"].startswith("Acknowledged")), notes[0] if notes else None)
        if ack:
            key = "comments_open_link" if link else "comments_open_power" if r["category"] in ("psu", "power_shelf") else "comments_open"
            com.append({"at": ack["at"], "by": by, "text": self.pick(rng, c[key]).format(**fill)})
        if notes and notes[-1]["text"].startswith("Validation complete"):
            com.append({"at": notes[-1]["at"], "by": by, "text": self.pick(rng, c["comments_closed"]).format(**fill)})
        out["comments"] = {"entries": com}
        alarm = r["alarms"][0]["summary"] if r["alarms"] else r["summary"]
        alarm = alarm.split(": ", 1)[1] if alarm.startswith(ci + " ") and ": " in alarm else alarm
        reseat = n.get("close_code") == "Cleaned/reseated"
        cat = {"tray_gpu": "tray_gpu_reseat" if reseat else "tray_gpu",
               "optic_link": "optic_link_clean" if reseat else "optic_link"}.get(r["category"], r["category"])
        out["cause"] = {"text": self.pick(rng, c["cause"].get(cat, c["cause"]["other"])).format(alarm=alarm, **fill)}
        val = c["validation"] if n.get("validation_attached") else ""
        p = r["parts"][0] if r["parts"] else None
        if p and p.get("removed_serial") and p.get("installed_serial"):
            at = p["location"] if p["location"].lower().startswith(p["part"].lower()) else f"{p['part']} at {p['location']}"
            text = self.pick(rng, c["close_replaced"]).format(item=at, removed=p["removed_serial"], installed=p["installed_serial"],
                                                              validation=val, **fill)
        elif reseat:
            text = self.pick(rng, c["close_clean" if link else "close_reseat"]).format(location=ci, validation=val, **fill)
        else:
            text = self.pick(rng, c["close_other"]).format(validation=val, **fill)
        out["close_notes"] = {"text": text}
        on = next((x for x in notes if x["text"].startswith("On site")), ack)
        work = [x for x in notes if on and x["at"] > on["at"] and not x["text"].startswith("Validation")]
        if on and work:
            out["time_worked"] = {"entries": [{"by": by, "from": on["at"], "to": work[-1]["at"], "hours": hours(on["at"], work[-1]["at"]),
                                               "what": "On site to repair complete (work notes)"}]}
        return out

    def _chg(self, r, rng):
        c = self.cfg["chg"]["firmware"]
        m = re.search(r"(\S+) -> (\S+) on rack (\S+)", r["summary"])
        frm, to, rack = m.groups() if m else ("", "", r["rack"])
        rf = [e for e in r["timeline"] if e["event"].startswith("Redfish:") and to in e["event"]]
        fill = dict(rack=rack, from_v=frm, to_v=to)
        out = {k: {"text": c[k].format(**fill)} for k in ("implementation_plan", "backout_plan", "test_plan")}
        if rf:
            fill.update(first=rf[0]["event"].split()[1], last=rf[-1]["event"].split()[1])
            out["work_notes"] = {"entries": [{"at": rf[0]["t"], "by": "", "text": c["started"].format(**fill)},
                                             {"at": rf[-1]["t"], "by": "", "text": c["finished"].format(**fill)}]}
            out["close_code"] = {"text": c["successful"]}
            out["close_notes"] = {"text": c["close_notes"].format(**fill)}
        return out

    def _wo(self, r, rng):
        c, n = self.cfg["wo"], r["native"]
        by = n["engineer"]
        planned = n.get("fault_class") is None and n.get("attribution") != "Utility"
        fill = dict(notes=n["notes"], unit=n.get("unit") or r["device"], room=n.get("room") or r["location"])
        out = {"long_description": {"text": (c["long_description_planned"] if planned else self.pick(rng, c["long_description"])).format(**fill)}}
        log = []
        if n.get("acknowledged_at"):
            log.append({"at": n["acknowledged_at"], "by": by, "text": self.pick(rng, c["ack"])})
        if n.get("engaged_at"):
            log.append({"at": n["engaged_at"], "by": by, "text": self.pick(rng, c["planned_engaged" if planned else "engaged"]).format(**fill)})
        if n.get("restored_at") and not planned:
            parts = "; ".join(p["part"] for p in r["parts"])
            log.append({"at": n["restored_at"], "by": by, "text": self.pick(rng, c["restored_parts"]).format(parts=parts) if parts else self.pick(rng, c["restored"])})
        if n.get("closed"):
            log.append({"at": n["closed"], "by": by, "text": self.pick(rng, c["planned_closed" if planned else "closed"])})
        out["work_log"] = {"entries": log}
        key = "utility" if n.get("attribution") == "Utility" else "planned" if planned else n["fault_class"]
        f = c["failure"][key]
        out["failure"] = {"rows": [["Failure class", n.get("fault_class") or "None"], ["Problem", f["problem"]], ["Cause", f["cause"]], ["Remedy", f["remedy"]]]}
        end = n.get("restored_at") or n.get("closed")
        if n.get("engaged_at") and end:
            out["labor"] = {"entries": [{"by": by, "from": n["engaged_at"], "to": end, "hours": hours(n["engaged_at"], end), "what": "Engaged to restored (work order)"}]}
        return out

    def _pm(self, r, rng):
        c, n = self.cfg["pm"], r["native"]
        steps = list(c["checklists"].get(n["system"], c["checklists"]["other"]))
        if "pm_tag" not in self.plants.get(r["id"], set()):
            steps.append(c["tag_step"])
        ok = n["result"].startswith("Pass")
        out = {"checklist": {"items": [{"step": s, "result": "Pass" if ok else "See observations"} for s in steps]}}
        rows = []
        m = re.search(r"at (\d+%) load", n["result"])
        if m:
            rows.append(["Load on the load bank", m.group(1)])
        for k, v in re.findall(r"(pH|conductivity) ([\d.]+(?: uS/cm)?)", n["evidence"]):
            rows.append(["Coolant " + k, v])
        rows.append(["Result", n["result"]])
        out["readings"] = {"rows": rows}
        out["observations"] = {"text": self.pick(rng, c["observations"]).format(evidence=n["evidence"].rstrip("."))}
        out["follow_up"] = {"text": c["follow_up_no"]}
        done = n.get("completed_at")
        badge = [e["t"] for e in r["timeline"] if "badged in" in e["event"] and n["engineer"] in e["event"] and done and e["t"] < done]
        if badge and done:
            out["labor"] = {"entries": [{"by": n["engineer"], "from": badge[-1], "to": done, "hours": hours(badge[-1], done), "what": "Badge-in at the work area to completion (maintenance record)"}]}
        return out

    def _mop(self, r, rng):
        c, n = self.cfg["mop"], r["native"]
        title, asset = n["title"], ", ".join(n["assets"])
        kind = ("cdu" if "CDU" in title else "ups" if "UPS" in title else "vesda" if "VESDA" in title
                else "tapoff" if "tap-off" in title.lower() else "other")
        rel = [x for x in r["related"] if x in self.by_id]
        pm = next((x for x in rel if x.startswith("PM-")), "")
        wo = next((x for x in rel if x.startswith("WO-")), "")
        who = next((self.by_id[x]["assigned"] for x in rel if self.by_id[x]["assigned"]), "")
        evs = self.events(r)
        expected = [a for a in r["alarms"] if a["cls"] == "expected"]
        done = self.first(r, lambda e: (pm and e["event"].startswith(pm + " closed by")) or (wo and e["event"] == f"Work order {wo} closed"))
        cleared = next((e["t"] for e in evs if expected and e["event"] == f"Alarm {expected[-1]['id']} cleared"), None)
        times = [n["window_start"], expected[0]["raised"] if expected else None, done, cleared, n["window_end"]]
        steps = c["steps"][kind]
        if len(steps) != len(times):
            times = [n["window_start"]] + [None] * (len(steps) - 2) + [n["window_end"]]
        out = {"step_log": {"items": [{"step": s.format(pm=pm, wo=wo, asset=asset), "result": "Done", "at": t, "by": who}
                                      for s, t in zip(steps, times)]}}
        out["deviations"] = {"text": c["deviations_none"]}
        out["backout_used"] = {"text": c["backout_no"]}
        out["as_left"] = {"text": c["as_left"].format(asset=asset)}
        out["completion_notes"] = {"text": self.pick(rng, c["completion"]).format(related=" and ".join(rel) or "The work")}
        return out

    def _sir(self, r, rng):
        c, n = self.cfg["sir"], r["native"]
        by, door = n["dispatched"], n["door"]
        log = [{"at": n["opened"], "by": by, "text": self.pick(rng, c["narrative_dispatched"]).format(door=door)}]
        if n.get("on_scene"):
            log.append({"at": n["on_scene"], "by": by, "text": self.pick(rng, c["narrative_on_scene"]).format(door=door)})
        log.append({"at": n["closed"], "by": by, "text": self.pick(rng, c["narrative_closed"]).format(disposition=n["disposition"].rstrip("."))})
        d = n["disposition"]
        return {"narrative": {"entries": log}, "actions": {"text": c["actions"].get(d, c["actions"]["default"])},
                "follow_up": {"text": c["follow_up"].get(d, c["follow_up"]["default"])}, "review": {"text": self.pick(rng, c["review"])}}

    def _imp(self, r, rng):
        c, n = self.cfg["imp"], r["native"]
        by, dev = n["engineer"], n["devices"]
        log = [{"at": n["start"], "by": by, "text": c["tag_on"].format(device=dev)}]
        if n.get("restored_at"):
            log.append({"at": n["restored_at"], "by": by, "text": c["tag_off"].format(device=dev)})
        notice = next((m.group(0) for e in r["timeline"] for m in [re.search(r"FPN-\d+", e["event"])] if m), "the notice on file")
        out = {"tag": {"entries": log},
               "notifications": {"text": c["notifications_planned" if n["type"] == "planned" else "notifications_unplanned"].format(notice=notice)}}
        ext = next((m.group(0) for e in r["timeline"] if e["event"].startswith("Extension notice") for m in [re.search(r"FPN-\d+", e["event"])] if m), "")
        if ext:
            out["notifications"]["text"] += " " + c["extension"].format(notice=ext)
        if n.get("fire_watch_start"):
            fw = f"Fire watch from {hm(n['fire_watch_start'])} to {hm(n['fire_watch_end'])} CDT. " + c["fire_watch_kept"]
        elif n.get("restored_at") and hours(n["start"], n["restored_at"]) <= 4:
            fw = c["fire_watch_none"]
        else:
            fw = "None logged."
        out["fire_watch"] = {"text": fw}
        if n.get("restored_at"):
            out["restoration"] = {"text": c["restoration"].format(device=dev)}
        out["notes"] = {"text": self.pick(rng, c["notes"]).format(reason=n["reason"].rstrip("."))}
        return out


def apply_hand(note: dict[str, Any], hand: dict[str, Any]) -> dict[str, Any]:
    """Replace or add the hand-written fields (same shape as composed ones) and mark the note hand-written."""
    if not hand:
        return note
    by_key = {f["key"]: f for f in note["fields"]}
    for k, v in hand.items():
        by_key[k].update(v)
    note["source"] = "hand-written"
    return note


def build(records: list[dict[str, Any]], seed: int, cfg: dict[str, Any] | None = None, hand: dict[str, Any] | None = None,
          plants: dict[str, set[str]] | None = None) -> dict[str, dict[str, Any]]:
    comp = Composer(records, seed, cfg, plants)
    hand = hand or {}
    return {r["id"]: apply_hand(comp.compose(r), hand.get(r["id"], {})) for r in records}


# -- the facts rule -------------------------------------------------------------------------------------------------
def _strings(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return []


def _times(v: Any, keys=("at", "from", "to")) -> list[str]:
    if isinstance(v, dict):
        return [x for k, x in v.items() if k in keys and isinstance(x, str) and x] + [t for x in v.values() for t in _times(x, keys)]
    if isinstance(v, list):
        return [t for x in v for t in _times(x, keys)]
    return []


def check(records: list[dict[str, Any]], notes: dict[str, dict[str, Any]], cfg: dict[str, Any] | None = None,
          names: list[str] | None = None) -> list[str]:
    """Every problem with the notes against their records (an empty list means every note reconciles)."""
    cfg = cfg or config()
    static = tokens(" ".join(_strings(cfg)))
    by_id = {r["id"]: r for r in records}
    bad: list[str] = []
    for r in records:
        n = notes.get(r["id"])
        if not n:
            bad.append(f"{r['id']}: no notes")
            continue
        want = [f["key"] for f in cfg["types"][r["type"]]["fields"]]
        if [f["key"] for f in n["fields"]] != [k for k in want if k in {f["key"] for f in n["fields"]}]:
            bad.append(f"{r['id']}: fields out of order or unknown")
        scope = [r] + [x for x in records if x["id"] != r["id"] and (x["id"] in r["related"] or r["id"] in x["related"]
                                                                      or r["id"] in json.dumps(x["native"]))]
        facts = tokens(json.dumps([{k: x[k] for k in ("id", "summary", "device", "location", "rack", "assigned", "native", "timeline",
                                                "alarms", "parts", "notes", "related", "category")} for x in scope], ensure_ascii=False))
        stamps = {e["t"] for x in scope for e in x["timeline"]} | {v for x in scope for v in _strings(x["native"]) if re.match(r"\d{4}-\d\d-\d\dT", v)}
        clocks = {hm(s) for s in stamps}
        for t in _times(n["fields"]):
            if t not in stamps:
                bad.append(f"{r['id']}: time {t} is not on the record")
        for f in n["fields"]:
            for e in f.get("entries", []):
                if "hours" in e and e["hours"] != hours(e["from"], e["to"]):
                    bad.append(f"{r['id']}: {f['key']} hours {e['hours']} do not equal its span")
                if e.get("by") and e["by"] not in facts:
                    bad.append(f"{r['id']}: person {e['by']} is not on the record")
            for s in _strings({k: v for k, v in f.items() if k not in ("key", "label", "visibility", "kind")}):
                if re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:]+Z", s):
                    continue
                for c in CLOCK.findall(s):
                    if c not in clocks:
                        bad.append(f"{r['id']}: clock time {c} in {f['key']} is not on the record")
                for tok in tokens(CLOCK.sub(" ", s)):
                    if any(ch.isdigit() for ch in tok) and tok not in facts and tok not in static:
                        bad.append(f"{r['id']}: '{tok}' in {f['key']} is not on the record")
                for name in names or []:
                    if name in s:
                        bad.append(f"{r['id']}: names a person")
    return bad
