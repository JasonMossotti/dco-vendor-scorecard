"""The management network telemetry: agreements with the records, and the findings where records do not reconcile.

Like the other telemetry sections, every check reads only what the layer publishes (``data/telemetry/mgmt/``) and the
records already written for the month (``data/sample/``), never the generator's internals.

Agreements (the telemetry never contradicts the records; each returns cases checked and disagreements):

1. records: every Redfish event and BMC inventory change the Telemetry of Record logged falls in a minute that BMC
   answered its poll.
2. power: each rack power loss on record (the scheduler's NotResponding, rack input power lost) stops every BMC in the
   rack within a minute, both rack switches go dark and boot again (coldStart), and every BMC answers again before the
   first tray is returned to service.
3. swaps: each tray or shelf replacement shows that BMC out of the rack just before, with its new serial at the first
   answer (the gap ends at the inventory change's minute); each reseat shows the tray out in the minutes before the
   note; the out-of-band port drops and returns with it (linkDown, linkUp).
4. nmx: each NMX "unreachable" on an NVLink switch tray drops that tray's eth0 port and its BMC at that minute; each
   "healthy" finds them up.
5. handover: no Hall B BMC answers before its rack's leak test (M3) or before its switches boot.
6. hourly: the hourly BMC counts equal the poll gap log, the first answers, and the collector's own log, hour by hour.
7. ports: replaying the trap log gives every switch's hourly port and uplink counts and its minutes up.
8. rackwide: every minute a whole rack's BMCs fail together, the rack has lost power or its out-of-band switch is down.

A record that falls inside a rack power loss on record (a tray swapped or reseated while the rack had no power, which a few
generated months contain) cannot be read from its BMC, so checks 1 and 3 leave it out.

Findings (records that do not reconcile; config/telemetry_mgmt.yaml ``checks``):

* MP-OUT: an out-of-band switch down longer than ``outage_ticket_min`` with its rack powered, and no IT Partner ticket.
* MP-VAL: a Redfish validation check recorded as passing while its BMC was not answering.
* MP-M4: Hall B BMCs first answering after M4 (whose checklist confirms "BMC reachable on the out-of-band network")
  was reported complete.
* MP-CON: a console session printing a different device's name than the console server's port map gives the port.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from scorecard.telemetry import Check, _csv, _jsonl, parse

HOUR = 60
ANSWER, FAIL, UNPOLLED, OFF = 0, 1, 2, -1


@dataclass
class MgmtData:
    dir: Path
    sample: Path
    manifest: dict
    bmc_hourly: list[dict]
    switch_hourly: list[dict]
    gaps: list[dict]
    traps: list[dict]
    collector: list[dict]
    sessions: list[dict]
    ports: dict[str, dict[str, str]]
    first: dict[str, str]
    events: list[dict]
    inventory: list[dict]
    checks: list[dict]
    nmx: list[dict]
    sched: list[dict]
    tickets: list[dict]
    milestones: dict[str, dict[str, str]]

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def M(self) -> int:
        return int((parse(self.manifest["window"]["end"]) - self.start).total_seconds() // 60)

    def m_of(self, ts: str) -> int:
        return max(0, min(self.M, math.ceil((parse(ts) - self.start).total_seconds() / 60 - 1e-9)))

    def iso(self, m: int) -> str:
        return (self.start + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def devices(self, family: str) -> list[str]:
        return sorted(d for d, x in self.manifest["devices"].items() if x["family"] == family)

    def endpoint_of(self, resource: str) -> str | None:
        m = re.match(r"/redfish/v1/Chassis/([A-C]\d{2})_([A-Za-z]+)_(\d+)", resource or "")
        if not m:
            return None
        rack, kind, n = m.groups()
        name = f"{rack.lower()}-ct{int(n):02d}" if kind == "ComputeTray" else f"{rack.lower()}-nvsw{int(n)}" if kind == "SwitchTray" \
            else f"{rack}_{kind}_{n}"
        return name if name in self.manifest["devices"] else None


def load(mgmt_dir: str | Path, sample_dir: str | Path) -> MgmtData:
    d, s = Path(mgmt_dir), Path(sample_dir)
    ms: dict[str, dict[str, str]] = {}
    mp = s / "vendor" / "deployment_milestones.csv"
    if mp.exists():
        for r in csv.DictReader(mp.open(encoding="utf-8")):
            if r["reported_complete_at"]:
                ms.setdefault(r["rack"], {})[r["milestone"]] = r["reported_complete_at"]
    tel = s / "telemetry"
    return MgmtData(dir=d, sample=s, manifest=json.loads((d / "manifest.json").read_text(encoding="utf-8")),
                    bmc_hourly=_csv(d / "bmc_hourly.csv"), switch_hourly=_csv(d / "switch_hourly.csv"), gaps=_jsonl(d / "poll_gaps.jsonl"),
                    traps=_jsonl(d / "traps.jsonl"), collector=_jsonl(d / "collector.jsonl"), sessions=_jsonl(d / "console_sessions.jsonl"),
                    ports=json.loads((d / "console_ports.json").read_text(encoding="utf-8")),
                    first=json.loads((d / "first_answer.json").read_text(encoding="utf-8")),
                    events=_jsonl(tel / "redfish_events.jsonl"), inventory=_jsonl(tel / "redfish_inventory_changes.jsonl"),
                    checks=_jsonl(tel / "health_checks.jsonl"), nmx=_jsonl(tel / "nmx_events.jsonl"),
                    sched=_jsonl(tel / "scheduler_node_states.jsonl"),
                    tickets=json.loads((s / "vendor" / "tickets.json").read_text(encoding="utf-8")), milestones=ms)


# ------------------------------------------------------------------------- the published logs, replayed
def unpolled(t: MgmtData) -> np.ndarray:
    out = np.zeros(t.M, dtype=bool)
    ev = sorted(t.collector, key=lambda e: e["timestamp"])
    a = None
    for e in ev:
        if e["event"] == "poller stopped":
            a = t.m_of(e["timestamp"])
        elif e["event"] == "poller started" and a is not None:
            out[a:t.m_of(e["timestamp"])] = True
            a = None
    return out


def endpoint_states(t: MgmtData) -> dict[str, np.ndarray]:
    """Per endpoint per minute, from the poll gap log, the first answers, and the collector log."""
    gap_by: dict[str, list[dict]] = {}
    for g in t.gaps:
        gap_by.setdefault(g["endpoint"], []).append(g)
    up = unpolled(t)
    out = {}
    for n in t.devices("bmc"):
        st = np.full(t.M, ANSWER, dtype=np.int8)
        for g in gap_by.get(n, []):
            st[t.m_of(g["from"]):t.m_of(g["to"]) if g["to"] else t.M] = FAIL
        st[up & (st == ANSWER)] = UNPOLLED
        if n in t.first:                     # null: never answered this month (a Hall B rack not yet built)
            st[:t.m_of(t.first[n]) if t.first[n] else t.M] = OFF
        out[n] = st
    return out


def replay_ports(t: MgmtData) -> dict[str, dict[str, Any]]:
    """Each switch's minutes up and per-port state from the trap log: a switch is up from its coldStart (or from the
    start, when the manifest lists its ports down at the start); it is down from the minute both aggregation switches
    report its uplink ports down until its next coldStart. Ports change at each linkDown or linkUp; at a coldStart
    every port is down until its own linkUp."""
    devs = t.manifest["devices"]
    by: dict[str, list[dict]] = {}
    for e in t.traps:
        by.setdefault(e["switch"], []).append(e)
    # aggregation ports by rack switch: two per rack, in rack order
    agg_port: dict[str, dict[str, int]] = {}
    for hall in sorted({x["hall"] for x in devs.values() if x["family"] == "rack"}):
        racks = sorted({x["rack"] for x in devs.values() if x["family"] == "rack" and x["hall"] == hall})
        for i, r in enumerate(racks):
            for k in (1, 2):
                agg_port.setdefault(hall, {})[f"{r.lower()}-mgmt{k}"] = 2 * i + k
    out: dict[str, dict[str, Any]] = {}
    for s, x in devs.items():
        if x["family"] not in ("rack", "agg"):
            continue
        up = np.ones(t.M, dtype=np.int8) if x["down_at_start"] is not None else np.zeros(t.M, dtype=np.int8)
        ports = {p: np.ones(t.M, dtype=np.int8) for p in x["ports"]}
        if x["down_at_start"] is None:
            for p in ports:
                ports[p][:] = 0
        else:
            for p in x["down_at_start"]:
                ports[p][:] = 0
        out[s] = {"up": up, "ports": ports}
    for s, o in out.items():
        for e in sorted(by.get(s, []), key=lambda e: e["timestamp"]):
            m = t.m_of(e["timestamp"])
            if e["trap"] == "coldStart":
                o["up"][m:] = 1
                for p in o["ports"]:
                    o["ports"][p][m:] = 0
            else:
                p = int(e["ifName"][3:])
                if p in o["ports"]:
                    o["ports"][p][m:] = 1 if e["trap"] == "linkUp" else 0
    # a rack switch is down while every aggregation switch of its hall sees its port down, until its coldStart
    for s, x in devs.items():
        if x["family"] != "rack":
            continue
        aggs = [a for a, y in devs.items() if y["family"] == "agg" and y["hall"] == x["hall"]]
        p = agg_port[x["hall"]][s]
        seen = np.ones(t.M, dtype=bool)
        for a in aggs:
            seen &= out[a]["ports"][p] == 0
        boots = sorted(t.m_of(e["timestamp"]) for e in by.get(s, []) if e["trap"] == "coldStart")
        dark = np.zeros(t.M, dtype=bool)
        edges = np.flatnonzero(np.diff(np.concatenate(([0], seen.astype(np.int8), [0]))))
        for a, b in zip(edges[::2].tolist(), edges[1::2].tolist()):
            if a == 0 and x["down_at_start"] is None:
                continue                     # not yet in service: a Hall B rack switch before its first boot
            nb = next((m for m in boots if m >= a), None)
            dark[a:nb if nb is not None else b] = True
        o = out[s]
        o["up"][dark] = 0
        for q in o["ports"]:
            o["ports"][q][dark] = 0
        o["dark"] = dark
    return out


def spans(mask: np.ndarray) -> list[tuple[int, int]]:
    e = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return list(zip(e[::2].tolist(), e[1::2].tolist()))


def power_losses(t: MgmtData) -> dict[str, tuple[int, int]]:
    """Per rack: the first minute the scheduler saw its trays NotResponding (rack input power lost), and the first
    minute one of them was returned to service after it."""
    out: dict[str, tuple[int, int]] = {}
    lost: dict[str, int] = {}
    for e in t.sched:
        if "rack input power lost" in e.get("reason", ""):
            r = e["node"][:3].upper()
            lost[r] = min(lost.get(r, t.M), t.m_of(e["timestamp"]))
    for r, a in lost.items():
        back = min((t.m_of(e["timestamp"]) for e in t.sched if e["node"][:3].upper() == r and e["state"] == "idle"
                    and t.m_of(e["timestamp"]) > a), default=t.M)
        out[r] = (a, back)
    return out


# ------------------------------------------------------------------------- agreements
def agreements(t: MgmtData, cfg: dict[str, Any]) -> list[Check]:
    rec_c = Check("records", "Every Redfish event and inventory change falls in a minute its BMC answered")
    pow_c = Check("power", "Each rack power loss stops its BMCs and switches; they answer again before the trays return")
    swap_c = Check("swaps", "Each replacement and reseat shows the part out of the rack, with the new serial at its first answer")
    nmx_c = Check("nmx", "Each NMX unreachable drops the switch tray's eth0 and BMC; each healthy finds them up")
    hand_c = Check("handover", "No Hall B BMC answers before its rack's leak test or before its switches boot")
    hour_c = Check("hourly", "The hourly BMC counts equal the poll gap log, the first answers, and the collector log")
    port_c = Check("ports", "The trap log gives every switch's hourly port and uplink counts and minutes up")
    wide_c = Check("rackwide", "Every rack-wide BMC loss is its power loss or its out-of-band switch down")
    st = endpoint_states(t)
    devs = t.manifest["devices"]
    rep = replay_ports(t)
    gap_by: dict[str, list[tuple[int, int]]] = {}
    for g in t.gaps:
        gap_by.setdefault(g["endpoint"], []).append((t.m_of(g["from"]), t.m_of(g["to"]) if g["to"] else t.M))
    # a record inside a rack power loss cannot be read from its BMC (a tray swapped or reseated while the rack had no power):
    # left out of the record and swap checks
    losses = power_losses(t)
    in_loss = lambda n, m: devs[n]["rack"] in losses and losses[devs[n]["rack"]][0] <= m <= losses[devs[n]["rack"]][1] + 10   # noqa: E731
    # 1: records
    for e in t.events:
        n = t.endpoint_of(e["resource"])
        if n and not in_loss(n, t.m_of(e["timestamp"])):
            m = t.m_of(e["timestamp"])
            rec_c(m >= t.M or st[n][m] == ANSWER, f"{e['timestamp']} {e['event_type']} on {n}: the BMC was not answering")
    for e in t.inventory:
        n = t.endpoint_of(e["resource"])
        if n and not in_loss(n, t.m_of(e["observed_at"])):
            m = t.m_of(e["observed_at"])
            rec_c(m >= t.M or st[n][m] == ANSWER, f"{e['observed_at']} serial change on {n}: the BMC was not answering")
    # 2: power
    for r, (a, back) in losses.items():
        eps = [n for n in t.devices("bmc") if devs[n]["rack"] == r]
        for n in eps:
            gs = [g for g in gap_by.get(n, []) if abs(g[0] - a) <= cfg["checks"]["power_match_min"]]
            pow_c(bool(gs), f"{n}: no gap starting at the rack's power loss {t.iso(a)}")
            if gs:
                pow_c(gs[0][1] <= back, f"{n}: answered again at {t.iso(gs[0][1])}, after the first tray returned at {t.iso(back)}")
        for k in (1, 2):
            s = f"{r.lower()}-mgmt{k}"
            if s in rep:
                pow_c(bool(rep[s]["dark"][a:a + 2].any()), f"{s}: still up at the rack's power loss {t.iso(a)}")
                boots = [t.m_of(e["timestamp"]) for e in t.traps if e["switch"] == s and e["trap"] == "coldStart" and a < t.m_of(e["timestamp"]) <= back]
                pow_c(bool(boots), f"{s}: no coldStart between the power loss and the trays' return")
    # 3: swaps and reseats
    traps_by: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for e in t.traps:
        traps_by.setdefault((e["switch"], e["ifName"]), []).append((t.m_of(e["timestamp"]), e["trap"]))
    for e in t.inventory:
        n = t.endpoint_of(e["resource"])
        if not n or "/PowerSubsystem/" in e["resource"] or e["property"] != "SerialNumber" or in_loss(n, t.m_of(e["observed_at"])):
            continue
        m = t.m_of(e["observed_at"])
        g = next((g for g in gap_by.get(n, []) if g[1] == m), None)
        swap_c(g is not None, f"{n}: no gap ending at its new serial {e['observed_at']}")
        if g:
            sw, port = devs[n]["switch"], f"swp{devs[n]['port']}"
            tl = traps_by.get((sw, port), [])
            swap_c((g[0], "linkDown") in tl and (g[1], "linkUp") in tl, f"{n}: {sw} {port} did not go down and up with the swap")
    for tk in t.tickets:
        if tk.get("close_code") != "Cleaned/reseated" or tk["configuration_item"] not in devs:
            continue
        note = next((w for w in tk["work_notes"] if "Reseated" in w["text"]), None)
        if note and not in_loss(tk["configuration_item"], t.m_of(note["at"])):
            m = t.m_of(note["at"])
            swap_c(any(m - 3 <= b <= m for _, b in gap_by.get(tk["configuration_item"], [])),
                   f"{tk['number']}: {tk['configuration_item']} shows no reseat before {note['at']}")
    # 4: NMX
    for e in t.nmx:
        mm = re.search(r"([a-c]\d{2}-nvsw\d)", e.get("unit", ""))
        if not mm or mm.group(1) not in devs:
            continue
        n, m = mm.group(1), t.m_of(e["timestamp"])
        sw2 = f"{devs[n]['rack'].lower()}-mgmt2"
        eth = rep.get(sw2, {}).get("ports", {}).get(devs[n]["inband"])
        if e["state"] == "failed":
            nmx_c(eth is not None and eth[min(m, t.M - 1)] == 0, f"{e['timestamp']} {n}: NMX unreachable but eth0 up")
            nmx_c(st[n][min(m, t.M - 1)] == FAIL, f"{e['timestamp']} {n}: NMX unreachable but the BMC answered")
        elif m < t.M:
            nmx_c(eth is not None and eth[m] == 1, f"{e['timestamp']} {n}: NMX healthy but eth0 down")
            nmx_c(st[n][m] == ANSWER, f"{e['timestamp']} {n}: NMX healthy but the BMC not answering")
    # 5: Hall B handover
    for n, ts in t.first.items():
        if not ts:
            continue
        r = devs[n]["rack"]
        m = t.m_of(ts)
        m3 = t.milestones.get(r, {}).get("M3")
        if m3:
            hand_c(m >= t.m_of(m3), f"{n}: first answered {ts}, before {r}'s leak test {m3}")
        sw = devs[n]["switch"]
        boot = [t.m_of(e["timestamp"]) for e in t.traps if e["switch"] == sw and e["trap"] == "coldStart"]
        hand_c(bool(boot) and min(boot) <= m, f"{n}: first answered {ts} before {sw} booted")
    # 6: hourly BMC counts
    up = unpolled(t)
    H = t.M // HOUR
    by_rack: dict[str, list[str]] = {}
    for n in t.devices("bmc"):
        by_rack.setdefault(devs[n]["rack"], []).append(n)
    want: dict[tuple[str, int], dict] = {}
    for r, eps in by_rack.items():
        a = np.stack([st[n] for n in eps])
        insvc = (a != OFF).sum(0).reshape(H, HOUR)
        cnt = (a == ANSWER).sum(0).reshape(H, HOUR)
        fail = (a == FAIL).sum(0).reshape(H, HOUR)
        pol = ~up.reshape(H, HOUR)
        for h in range(H):
            svc = int(insvc[h].max())
            ans = cnt[h][pol[h] & (insvc[h] > 0)]
            want[(r, h)] = {"endpoints": str(svc), "polled_min": str(int(pol[h].sum())),
                            "answering_min": str(int(ans.min())) if svc and ans.size else "",
                            "answering_max": str(int(ans.max())) if svc and ans.size else "", "failed_polls": str(int(fail[h].sum()))}
    for row in t.bmc_hourly:
        h = int((parse(row["hour"]) - t.start).total_seconds() // 3600)
        w = want.get((row["rack"], h))
        hour_c(w is not None and all(row[k] == v for k, v in w.items()), f"{row['rack']} {row['hour']}: hourly row {dict((k, row[k]) for k in (w or {}))}, log gives {w}")
    # 7: ports from the trap log
    for row in t.switch_hourly:
        s = row["switch"]
        if s not in rep:
            continue
        h = int((parse(row["hour"]) - t.start).total_seconds() // 3600)
        o, sl = rep[s], slice(h * HOUR, h * HOUR + HOUR)
        upm = int(o["up"][sl].sum())
        x = devs[s]
        upl = [p for p in (49, 50) if p in o["ports"]] if x["family"] == "rack" else []
        dn = [p for p in o["ports"] if p not in upl]
        on = o["up"][sl] == 1
        pu = np.stack([o["ports"][p][sl] for p in dn]).sum(0) if dn else np.zeros(HOUR, dtype=np.int64)
        got = {"up_min": str(upm), "ports_up_min": str(int(pu[on].min()) if upm else 0), "ports_up_max": str(int(pu[on].max()) if upm else 0)}
        if upl:
            uu = np.stack([o["ports"][p][sl] for p in upl]).sum(0)
            got["uplinks_up_min"] = str(int(uu[on].min()) if upm else 0)
        port_c(all(row[k] == v for k, v in got.items()), f"{s} {row['hour']}: hourly {dict((k, row[k]) for k in got)}, traps give {got}")
    # 8: rack-wide losses
    for r, eps in by_rack.items():
        a = np.stack([st[n] for n in eps])
        insvc = (a != OFF).sum(0)
        allbad = (insvc > 0) & ((a == FAIL) | (a == OFF)).all(0) & (a == FAIL).any(0)
        if not allbad.any():
            continue
        sw = f"{r.lower()}-mgmt1"
        dark = rep[sw]["up"] == 0
        pw = np.zeros(t.M, dtype=bool)
        if r in losses:
            pw[losses[r][0]:losses[r][1]] = True
        # a BMC answers the minute after its switch's ports come back, so a span may outlast the switch by a minute or two
        back = np.zeros(t.M, dtype=bool)
        for x, y in spans(dark):
            back[y:y + 2] = True
        for x, y in spans(allbad):
            wide_c(bool((dark[x:y] | pw[x:y] | back[x:y]).all()), f"{r}: every BMC failing {t.iso(x)} to {t.iso(y)} with the rack powered and {sw} up")
    return [rec_c, pow_c, swap_c, nmx_c, hand_c, hour_c, port_c, wide_c]


# ------------------------------------------------------------------------- findings
def _dur(n: int) -> str:
    return f"{n} min" if n < 120 else f"{n / 60:.1f} h"


def findings(t: MgmtData, cfg: dict[str, Any]) -> list[dict]:
    """Records that do not reconcile. Each: id, kind, title, summary, owner, contract, lines (facts), refs, devices,
    and from / to where it has a span."""
    ck = cfg["checks"]
    devs = t.manifest["devices"]
    st = endpoint_states(t)
    rep = replay_ports(t)
    losses = power_losses(t)
    out: list[dict] = []
    label_at = lambda con, port: t.ports.get(con, {}).get(str(port), "")   # noqa: E731
    # MP-OUT: an out-of-band switch down with its rack powered, no ticket
    for s in t.devices("rack"):
        if devs[s]["role"] != "oob":
            continue
        r = devs[s]["rack"]
        for a, b in spans(rep[s]["dark"]):
            if b - a < ck["outage_ticket_min"]:
                continue
            if r in losses and losses[r][0] - 2 <= a <= losses[r][1]:
                continue
            win = timedelta(hours=ck["ticket_window_h"])
            tks = [tk for tk in t.tickets if tk["rack"] == r and t.start + timedelta(minutes=a) - win <= parse(tk["opened_at"])
                   <= t.start + timedelta(minutes=b) + win]
            if tks:
                continue
            eps = [n for n in t.devices("bmc") if devs[n]["rack"] == r]
            con = devs[s]["console"]
            sess = [x for x in t.sessions if con and x["console"] == con[0] and int(x["port"]) == con[1]
                    and a - 30 <= t.m_of(x["opened_at"]) <= b + 30]
            back = next((tr["timestamp"] for tr in t.traps if tr["switch"] == s and tr["trap"] == "coldStart" and t.m_of(tr["timestamp"]) >= b), None)
            lines = [f"{s} dark from {t.iso(a)} to {t.iso(b)} ({_dur(b - a)}): both aggregation switches lost its uplinks, and it sent coldStart at {back or 'the end of the month'}",
                     f"All {len(eps)} BMCs in rack {r} stopped answering over the span; the rack stayed powered (no power loss on record)",
                     f"No IT Partner ticket on rack {r} opened within {ck['ticket_window_h']} h of the span"]
            for x in sess:
                lines.append(f"IT Partner console session on {x['console']} port {x['port']} ({x['prompt']}) from {x['opened_at']} to {x['closed_at']}, "
                             f"{max(0, b - t.m_of(x['opened_at']))} minutes before it came back")
            out.append({"kind": "unticketed_outage", "title": f"{s} down {_dur(b - a)} with no ticket",
                        "summary": f"Rack {r}'s out-of-band switch was down for {_dur(b - a)} while the rack ran, so none of its {len(eps)} BMCs "
                                   "could be read or reached; the IT Partner worked on it from the console, but no ticket records the outage, "
                                   "its cause, or its restoration.",
                        "owner": "IT Partner", "contract": "Interface Agreement RACI: BMC and out-of-band management network (physical); IT Partner SLA scope (OOB networks)",
                        "lines": lines, "refs": [], "devices": [s, r], "from": t.iso(a), "to": t.iso(b)})
    # MP-VAL: a Redfish validation check passing while its BMC was not answering
    for c in t.checks:
        if not str(c["target"]).startswith("/redfish/") or c.get("result") != "pass":
            continue
        n = t.endpoint_of(c["target"])
        if not n:
            continue
        a, b = t.m_of(c["started_at"]), t.m_of(c["completed_at"])
        seg = st[n][a:b + 1]
        if not seg.size or (seg == UNPOLLED).any():
            continue
        if seg[-1] != FAIL:
            continue
        g = next((g for g in t.gaps if g["endpoint"] == n and t.m_of(g["from"]) <= b and (g["to"] is None or t.m_of(g["to"]) > b)), None)
        rack = devs[n]["rack"]
        tk = next((tk for tk in t.tickets if tk["rack"] == rack and tk.get("validation_attached")
                   and parse(c["completed_at"]) <= parse(tk["resolved_at"]) <= parse(c["completed_at"]) + timedelta(days=1)
                   and n.split("_")[-1] in tk["configuration_item"]), None)
        lines = [f"{c['check']} on {c['target']}: started {c['started_at']}, passed {c['completed_at']} (health check record)",
                 f"{n} answered no Redfish poll from {g['from']} to {g['to'] or 'the end of the month'} ({g['minutes']} min), "
                 f"so the check's final read could not have reached it"]
        if tk:
            lines.append(f"{tk['number']} closed as '{tk['close_code']}' at {tk['resolved_at']} with validation attached")
        out.append({"kind": "validation_gap", "title": f"{c['check']} on {n} passed while its BMC was not answering",
                    "summary": "A return-to-service check that reads the shelf's redundancy through Redfish is recorded as passing at a time "
                               "the Telemetry of Record could not reach that shelf's controller. Ask for the check's raw output; until then the "
                               "validation does not reconcile with the management network.",
                    "owner": "IT Partner", "contract": "IT Partner SLA: PSU replacement clock stop (BMC reports redundancy restored); validation before return to service",
                    "lines": lines, "refs": [tk["number"]] if tk else [], "devices": [n, rack], "from": g["from"], "to": g["to"]})
    # MP-M4: Hall B BMCs first answering after M4 was reported complete
    late: dict[str, list[tuple[str, str]]] = {}
    for n, ts in t.first.items():
        if not ts:
            continue
        r = devs[n]["rack"]
        m4 = t.milestones.get(r, {}).get("M4")
        if m4 and parse(ts) > parse(m4) and parse(m4) >= t.start:
            late.setdefault(r, []).append((n, ts))
    for r, xs in sorted(late.items()):
        m4 = t.milestones[r]["M4"]
        last = max(ts for _, ts in xs)
        hrs = (parse(last) - parse(m4)).total_seconds() / 3600
        lines = [f"M4 (power-on and firmware baseline) for {r} reported complete at {m4} (deployment milestones)",
                 "Its checklist (DEP-B-RK-04) requires POST on every tray and every BMC reachable on the out-of-band network"]
        lines += [f"{n} first answered at {ts}" for n, ts in sorted(xs)]
        out.append({"kind": "late_bmc", "title": f"{r}: {len(xs)} BMCs first answered {hrs:.0f} h after M4",
                    "summary": f"M4 for {r} was reported complete while {len(xs)} of its compute tray BMCs had never answered on the out-of-band "
                               "network; their ports came up hours later, as when cables are landed after the fact.",
                    "owner": "IT Partner", "contract": "Deployment step R-M4 (DEP-B-RK-04); IT Partner SLA rack acceptance exit criteria (BMCs reachable on OOB)",
                    "lines": lines, "refs": [], "devices": [r] + [n for n, _ in sorted(xs)], "from": m4, "to": last})
    # MP-CON: a console session printing a different name than the port map
    wrong: dict[tuple[str, int], list[dict]] = {}
    for x in t.sessions:
        host = x["prompt"].split()[0]
        if label_at(x["console"], x["port"]) != host:
            wrong.setdefault((x["console"], int(x["port"])), []).append(x)
    by_con: dict[str, list[int]] = {}
    for con, port in sorted(wrong):
        by_con.setdefault(con, []).append(port)
    for con, ports in sorted(by_con.items()):
        lines, hosts, labs, first = [], [], [], None
        for port in ports:
            xs = wrong[(con, port)]
            lab, host = label_at(con, port), xs[0]["prompt"].split()[0]
            hosts.append(host)
            labs.append(lab)
            lines.append(f"{con} port map: port {port} is labelled {lab}")
            lines += [f"Session {x['opened_at']} to {x['closed_at']} on port {port} printed '{x['prompt']}'" for x in xs]
            first = min(first or xs[0]["opened_at"], xs[0]["opened_at"])
        swapped = len(ports) == 2 and hosts == labs[::-1]
        title = (f"{con} ports {ports[0]} and {ports[1]} labelled the wrong way round" if swapped
                 else "; ".join(f"{con} port {p_} labelled {lb} but answers as {h}" for p_, lb, h in zip(ports, labs, hosts)))
        named = sorted(ports)
        for h in hosts:                      # the port the map gives the device that answered: its label is wrong too
            other = next((int(q) for q, v in t.ports.get(con, {}).items() if v == h), None)
            if other is not None and other not in named:
                lines.append(f"The map puts {h} on port {other}, so that port's label is wrong too")
                named.append(other)
        ports = sorted(named)
        out.append({"kind": "console_swap", "title": title,
                    "summary": "The console server's port map does not match what is on the line. In an outage, the person on the console would "
                               "be working on the wrong switch.",
                    "owner": "IT Partner", "contract": "IT Partner SLA scope: cabling and labeling for back-end, front-end, and OOB networks",
                    "lines": lines, "refs": [], "devices": [con] + sorted(set(hosts + [lb for lb in labs if lb])), "ports": ports,
                    "from": first, "to": None})
    out.sort(key=lambda f: (f["from"] or "", f["kind"]))
    for i, f in enumerate(out, 1):
        f["id"] = f"MP-{i}"
    return out


def score(fs: list[dict], key: dict[str, Any]) -> dict[str, int]:
    """Planted cases found, and findings that match none (false positives)."""
    def hit(f: dict, p: dict) -> bool:
        if f["kind"] != p["kind"]:
            return False
        if p["kind"] == "unticketed_outage":
            return p["switch"] in f["devices"]
        if p["kind"] == "validation_gap":
            return p["endpoint"] in f["devices"]
        if p["kind"] == "late_bmc":
            return p["rack"] in f["devices"] and sorted(p["endpoints"]) == sorted(d for d in f["devices"][1:])
        if p["kind"] == "console_swap":
            return p["console"] == f["devices"][0] and sorted(p["ports"]) == sorted(f["ports"])
        return False
    planted = key.get("planted", [])
    found = sum(1 for p in planted if any(hit(f, p) for f in fs))
    fp = sum(1 for f in fs if not any(hit(f, p) for p in planted))
    return {"planted": len(planted), "found": found, "false_positives": fp}


# ------------------------------------------------------------------------- what the page and report list
def events(t: MgmtData, cfg: dict[str, Any], fs: list[dict]) -> list[dict]:
    """Every gap worth a line, every switch down, uplink flap, and collector restart, with what explains it."""
    devs = t.manifest["devices"]
    rep = replay_ports(t)
    losses = power_losses(t)
    ck = cfg["checks"]
    out: list[dict] = []
    inv = {}
    for e in t.inventory:
        n = t.endpoint_of(e["resource"])
        if n and "/PowerSubsystem/" not in e["resource"]:
            inv[(n, t.m_of(e["observed_at"]))] = e
    reseat = {}
    for tk in t.tickets:
        note = next((w for w in tk["work_notes"] if "Reseated" in w["text"]), None)
        if tk.get("close_code") == "Cleaned/reseated" and note:
            reseat[tk["configuration_item"]] = (t.m_of(note["at"]), tk["number"])
    nmxf = {}
    for e in t.nmx:
        mm = re.search(r"([a-c]\d{2}-nvsw\d)", e.get("unit", ""))
        if mm and e["state"] == "failed":
            nmxf[(mm.group(1), t.m_of(e["timestamp"]))] = e
    tk_of = {}
    for tk in t.tickets:
        for p in tk.get("parts_used") or []:
            tk_of[p.get("installed_serial")] = tk["number"]
    find_dev = {}
    for f in fs:
        for d in f["devices"]:
            find_dev.setdefault(d, []).append(f)
    by_rack_gap: dict[tuple[str, int], int] = {}
    for g in t.gaps:
        n, a = g["endpoint"], t.m_of(g["from"])
        b = t.m_of(g["to"]) if g["to"] else t.M
        r = devs[n]["rack"]
        if r in losses and abs(a - losses[r][0]) <= 1:
            by_rack_gap[(r, losses[r][0])] = by_rack_gap.get((r, losses[r][0]), 0) + 1
            continue
        sw = devs[n]["switch"]
        if rep[sw]["dark"][a:b].any():
            continue
        if (n, b) in inv:
            e = inv[(n, b)]
            failed = next((x for (nn, m), x in nmxf.items() if nn == n and m == a), None)
            refs = [tk_of.get(e["new_value"])]
            out.append({"t": g["from"], "end": g["to"], "device": n, "rack": r, "kind": "failed" if failed else "swap", "m": a,
                        "text": (f"Failed switch tray: NMX unreachable and the BMC silent for {_dur(b - a)} until the replacement answered "
                                 if failed else f"Out of the rack for {_dur(b - a)}: ") + f"new serial {e['new_value']} at its first answer",
                        "refs": [x for x in refs if x], "finding": None})
            continue
        if n in reseat and abs(reseat[n][0] - b) <= 3:
            out.append({"t": g["from"], "end": g["to"], "device": n, "rack": r, "kind": "reseat", "m": a,
                        "text": f"Reseated: the tray out of the rack for {_dur(b - a)}, port down and up", "refs": [reseat[n][1]], "finding": None})
            continue
        f = next((f for f in find_dev.get(n, []) if f["kind"] == "validation_gap"), None)
        if f:
            out.append({"t": g["from"], "end": g["to"], "device": n, "rack": r, "kind": "hang", "m": a,
                        "text": f"BMC not answering for {_dur(b - a)}, with its port up, while a validation check recorded a pass",
                        "refs": f["refs"], "finding": {"id": f["id"], "title": f["title"]}})
        elif b - a > ck["gap_min"]:
            out.append({"t": g["from"], "end": g["to"], "device": n, "rack": r, "kind": "hang", "m": a,
                        "text": f"BMC not answering for {_dur(b - a)}, with its port up; nothing on record was read through it meanwhile",
                        "refs": [], "finding": None})
    for (r, a), k in by_rack_gap.items():
        out.append({"t": t.iso(a), "end": t.iso(losses[r][1]), "device": r, "rack": r, "kind": "power", "m": a,
                    "text": f"Rack power lost: all {k} BMCs and both switches dark; switches booted (coldStart) and every BMC answered before the trays returned",
                    "refs": [], "finding": None})
    for s in t.devices("rack"):
        if devs[s]["role"] != "oob":
            continue
        r = devs[s]["rack"]
        for a, b in spans(rep[s]["dark"]):
            if r in losses and losses[r][0] - 2 <= a <= losses[r][1]:
                continue
            f = next((f for f in find_dev.get(s, []) if f["kind"] == "unticketed_outage"), None)
            out.append({"t": t.iso(a), "end": t.iso(b), "device": s, "rack": r, "kind": "switch", "m": a,
                        "text": f"Out-of-band switch down {_dur(b - a)}: every BMC in rack {r} unreachable while the rack ran",
                        "refs": [], "finding": {"id": f["id"], "title": f["title"]} if f else None})
    for s, o in rep.items():
        if devs[s]["family"] != "rack":
            continue
        for p in (49, 50):
            if p not in o["ports"]:
                continue
            down = (o["ports"][p] == 0) & (o["up"] == 1)
            for a, b in spans(down):
                out.append({"t": t.iso(a), "end": t.iso(b), "device": s, "rack": devs[s]["rack"], "kind": "uplink", "m": a,
                            "text": f"Uplink swp{p} down {_dur(b - a)}; the other uplink carried the switch, so no BMC was lost", "refs": [], "finding": None})
    up = unpolled(t)
    for a, b in spans(up):
        out.append({"t": t.iso(a), "end": t.iso(b), "device": "TOR", "rack": "", "kind": "collector", "m": a,
                    "text": f"The Telemetry of Record's poller restarted: no BMC polled for {_dur(b - a)} (its own log); not a BMC failure",
                    "refs": [], "finding": None})
    for f in fs:
        if f["kind"] == "late_bmc":
            out.append({"t": f["from"], "end": f["to"], "device": f["devices"][0], "rack": f["devices"][0], "kind": "late", "m": t.m_of(f["from"]),
                        "text": f"{len(f['devices']) - 1} BMCs still unanswered after M4 was reported complete", "refs": [],
                        "finding": {"id": f["id"], "title": f["title"]}})
    return sorted(out, key=lambda e: (e["t"], e["device"]))
