"""Agreements between the network telemetry and every record already written for the month.

Like the GPU, CDU, and power sets, each check reads only what the network telemetry publishes
(``data/telemetry/network/`` and the files built at publish time) and the existing records, never the generator's
internals, and returns how many cases it checked and which ones disagree.

1. symbol_errors: every symbol-error count the fabric manager reported equals the port counter's rise over the
   report's interval (since the link's previous report, at most 90 minutes); a link with no report counts none.
2. link_state: each link is down exactly from each recorded link-down to its link-up, minute for minute, and
   LinkDownedCounter rises once per drop.
3. cabling: every link's far end (tray and NIC) is the one the device directory names, and the one every fabric
   event on that port names.
4. traffic: a link moves data in an hour only while its tray's GPUs report and the link is up; a busy tray's links
   all move data.
5. hall_b: each Hall B rack cabled this month has its 72 links, each up from its recorded "Link is Up" and never
   before, with no symbol errors; a rack not yet cabled has none.
6. optics: before each optic replacement on record, the link shows a failing optic's signature; a replacement that
   ended the errors clears it, and one followed by more errors leaves it; at each connector flap the receive power
   is below the module's warning.
7. uplinks: each leaf's uplinks carry their share of its downlink traffic, every hour.
8. nvlink: each NVLink switch tray reports while its rack's GPUs report, except exactly while the NMX records it
   failed, when the rack's other trays carry its share.
9. ranges: module temperature, receive power, and switch ASIC temperature stay inside the published ranges,
   except receive power at a recorded link drop.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from scorecard.fabric import peer_power_lost, power_loss_links
from scorecard.telemetry import Check, _csv, _jsonl, parse, unrle
from scorecard.telemetry_power import unpack

HOUR = 60
LINK_RE = re.compile(r"(leaf-[a-c]\d{2}-r\d):swp(\d+)")


@dataclass
class NetData:
    dir: Path
    minutes_dir: Path
    sample: Path
    gpu_hourly: dict[str, dict]
    manifest: dict
    fabric_hourly: list[dict]
    nvlink_hourly: list[dict]
    _leaf: dict[str, dict] = field(default_factory=dict)
    _win: dict[str, dict] = field(default_factory=dict)

    @property
    def start(self) -> datetime:
        return parse(self.manifest["window"]["start"])

    @property
    def end(self) -> datetime:
        return parse(self.manifest["window"]["end"])

    @property
    def M(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def H(self) -> int:
        return self.M // HOUR

    def devices(self, family: str) -> dict[str, dict]:
        return {k: v for k, v in self.manifest["devices"].items() if v["family"] == family}

    def leaf(self, name: str) -> dict:
        if name not in self._leaf:
            self._leaf[name] = json.loads((self.minutes_dir / f"{name}.json").read_text(encoding="utf-8"))
        return self._leaf[name]

    def port(self, lid: str) -> dict:
        sw, p = LINK_RE.match(lid).groups()
        return self.leaf(sw)["ports"][p]

    def nvl(self, rack: str) -> dict:
        return self.leaf(f"nvlink_{rack}")

    def m_of(self, t: datetime | str) -> int:
        t = parse(t) if isinstance(t, str) else t
        return max(0, min(self.M, math.ceil((t - self.start).total_seconds() / 60 - 1e-9)))

    def last_m(self, t: datetime | str) -> int:
        t = parse(t) if isinstance(t, str) else t
        return min(self.M - 1, int(math.floor((t - self.start).total_seconds() / 60 + 1e-9)))

    def windows(self, device: str) -> list[dict]:
        out = []
        for w in self.manifest["windows"]:
            if w["device"] == device:
                if w["file"] not in self._win:
                    self._win[w["file"]] = json.loads((self.dir / w["file"]).read_text(encoding="utf-8"))
                out.append(self._win[w["file"]])
        return out

    def minute(self, device: str, key: str, m: int) -> Any:
        """A field's value at minute m from the windows, or None when no window holds that minute."""
        for w in self.windows(device):
            i = m - w["m0"]
            if 0 <= i < w["minutes"]:
                return w["fields"][key][i]
        return None


def load(net_dir: str | Path, minutes_dir: str | Path, sample_dir: str | Path, gpu_hourly_dir: str | Path) -> NetData:
    d = Path(net_dir)
    hourly = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(gpu_hourly_dir).glob("*.json"))}
    return NetData(d, Path(minutes_dir), Path(sample_dir), hourly, json.loads((d / "manifest.json").read_text(encoding="utf-8")),
                   _csv(d / "fabric_hourly.csv"), _csv(d / "nvlink_hourly.csv"))


def tray_hours(t: NetData, host: str) -> tuple[np.ndarray, np.ndarray]:
    """(samples per hour summed over the tray's GPUs, minutes with all four GPUs reporting at util >= busy) from the
    published per-GPU hourly GPU telemetry: (samples, mean utilization weighted by samples)."""
    rack = host[:3].upper()
    n = np.zeros(t.H)
    u = np.zeros(t.H)
    for g in t.gpu_hourly.get(rack, {}).get("gpus", []):
        if g["host"] != host:
            continue
        gn = np.array(unrle(g["n"]), dtype=np.float64)
        gu = np.array([0.0 if v is None else v for v in g["util"]], dtype=np.float64)
        n += gn
        u += gu * gn
    return n, np.where(n > 0, u / np.maximum(n, 1), 0.0)


def _expected_state(t: NetData, events: list[dict], cabled_at_start: bool) -> tuple[np.ndarray, np.ndarray]:
    """(up per minute, link drops per minute) from the fabric events, the way the switch samples them."""
    up = np.ones(t.M, dtype=bool) if cabled_at_start else np.zeros(t.M, dtype=bool)
    drops = np.zeros(t.M, dtype=np.int64)
    cur = None if cabled_at_start else 0
    for e in events:
        m = t.m_of(e["timestamp"])
        if e["event"] == "link_down":
            if m < t.M:
                drops[m] += 1
            if cur is None:
                cur = m
        elif e["event"] == "link_up" and cur is not None:
            up[cur:m] = False
            up[m:] = True
            cur = None
    if cur is not None:
        up[cur:] = False
    return up, drops


def agreements(t: NetData, cfg: dict[str, Any], directory: dict[str, Any] | None = None) -> list[Check]:
    out: list[Check] = []
    H, M = t.H, t.M
    ufm = sorted(_jsonl(t.sample / "telemetry" / "ufm_port_events.jsonl"), key=lambda e: e["timestamp"])
    sched = _jsonl(t.sample / "telemetry" / "scheduler_node_states.jsonl")
    lost = power_loss_links(ufm, sched)
    ev_by: dict[str, list[dict]] = {}
    for e in ufm:
        ev_by.setdefault(f"{e['switch']}:swp{e['port']}", []).append(e)
    ports = t.devices("port")
    rmin = cfg["symbol_report_min"]

    # ---- 1. symbol errors
    c = Check("symbol_errors", "Every symbol-error count the fabric manager reported equals the port counter's rise over that report")
    for lid, evs in sorted(ev_by.items()):
        prev = None
        total = 0
        for e in evs:
            if e["event"] not in ("symbol_errors", "symbol_error_threshold"):
                continue
            tt = parse(e["timestamp"])
            a = max(tt - timedelta(minutes=rmin), prev) if prev else tt - timedelta(minutes=rmin)
            hi, lo = t.minute(lid, "sym", t.last_m(tt)), t.minute(lid, "sym", t.last_m(a))
            got = None if hi is None or lo is None else hi - lo
            c(got == int(e["count"]), f"{lid} report at {e['timestamp']}: fabric manager {e['count']}, counter rose {got}")
            total += int(e["count"])
            prev = tt
        if lid in ports:
            pub = int(unpack(t.port(lid)["sym"]).sum())
            c(pub == total, f"{lid}: {pub} symbol errors in the month, reports total {total}")
    quiet = [lid for lid in ports if not any(e["event"].startswith("symbol") for e in ev_by.get(lid, []))]
    bad = [lid for lid in quiet if unpack(t.port(lid)["sym"]).any()]
    c.checked += len(quiet) - len(bad)
    for lid in bad:
        c(False, f"{lid}: symbol errors with no report")
    out.append(c)

    # ---- 2. link state
    c = Check("link_state", "Each link is down exactly between its recorded link-down and link-up, and LinkDownedCounter rises once per drop")
    for lid, d in sorted(ports.items()):
        evs = ev_by.get(lid, [])
        up, drops = _expected_state(t, evs, d["cabled_at_start"])
        p = t.port(lid)
        want_up = up.reshape(H, HOUR).sum(axis=1)
        got_up = unpack(p["up_min"])
        c(np.array_equal(want_up, got_up), f"{lid}: up minutes per hour differ from the fabric events "
          f"(first at {int(np.flatnonzero(want_up != got_up)[0]) if len(got_up) == H and (want_up != got_up).any() else '?'})")
        want_d = drops.reshape(H, HOUR).sum(axis=1)
        c(np.array_equal(want_d, unpack(p["downs"])), f"{lid}: link drops per hour differ from the fabric events")
        for e in evs:
            if e["event"] == "link_down" and not peer_power_lost(e, lost):
                m = t.m_of(e["timestamp"])
                w_up, w_d = t.minute(lid, "up", m), t.minute(lid, "downs", m)
                prev_d = t.minute(lid, "downs", m - 1)
                c(w_up is not None and w_up == int(up[m]), f"{lid}: state {w_up} at {e['timestamp']} (link-down on record)")
                c(w_d is not None and prev_d is not None and w_d - prev_d == drops[m], f"{lid}: LinkDownedCounter at {e['timestamp']}")
    out.append(c)

    # ---- 3. cabling
    c = Check("cabling", "Every link's far end is the tray and NIC the device directory and the fabric events name")
    dports = {}
    if directory is not None:
        from scorecard import devices as D
        dports = D.ports(directory)
    for lid, d in sorted(ports.items()):
        key = f"{d['leaf']} port {d['port']}"
        if dports:
            c(dports.get(key) == [d["peer_host"], d["peer_hca"]], f"{lid}: telemetry {d['peer_host']} {d['peer_hca']}, directory {dports.get(key)}")
        for e in ev_by.get(lid, []):
            c([e["peer_host"], e["peer_hca"]] == [d["peer_host"], d["peer_hca"]], f"{lid} at {e['timestamp']}: event names {e['peer_host']}")
    for lid in ev_by:
        c(lid in ports, f"{lid}: fabric events on a link the telemetry does not publish")
    out.append(c)

    # ---- 4. traffic follows the GPUs
    c = Check("traffic", "A link moves data only while its tray's GPUs report and the link is up; a busy tray's links all move data")
    busy = cfg["checks"]["busy_util"]
    cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for lid, d in sorted(ports.items()):
        host = d["peer_host"]
        if host not in cache:
            cache[host] = tray_hours(t, host)
        n, u = cache[host]
        p = t.port(lid)
        tx, rx, upm = unpack(p["tx_gbps"]), unpack(p["rx_gbps"]), unpack(p["up_min"])
        moving = (tx > 0) | (rx > 0)
        stray = moving & ((n == 0) | (upm == 0))
        full = (n == 4 * HOUR) & (u >= busy) & (upm == HOUR)
        idle = full & ~((tx > 0) & (rx > 0))
        c(not stray.any(), f"{lid}: data in {int(stray.sum())} hours with its tray dark or the link down")
        c(not idle.any(), f"{lid}: no data in {int(idle.sum())} hours with its tray busy")
    out.append(c)

    # ---- 5. Hall B cabling
    c = Check("hall_b", "Each Hall B rack cabled this month has its 72 links, up from its recorded Link is Up, with no symbol errors")
    ms = _csv(t.sample / "vendor" / "deployment_milestones.csv")
    m5 = {r["rack"]: r["reported_complete_at"] for r in ms if r["milestone"] == "M5"}
    topo = json.loads((t.sample / "site" / "topology.json").read_text(encoding="utf-8"))
    for r in topo["racks"]:
        if r["state"] != "deployment":
            continue
        mine = [lid for lid, d in ports.items() if d["rack"] == r["rack"]]
        cabled = r["rack"] in m5 and t.start <= parse(m5[r["rack"]]) <= t.end
        c(len(mine) == (72 if cabled else 0), f"rack {r['rack']}: {len(mine)} links published, cabled this month: {cabled}")
        for lid in mine:
            first = next((e for e in ev_by.get(lid, []) if e["event"] == "link_up"), None)
            up = unpack(t.port(lid)["up_min"])
            h0 = int(np.flatnonzero(up)[0]) if up.any() else None
            c(first is not None and h0 == t.m_of(first["timestamp"]) // HOUR, f"{lid}: first up hour {h0}, Link is Up at {first and first['timestamp']}")
            c(first is not None and parse(first["timestamp"]) <= parse(m5[r["rack"]]), f"{lid}: up after the rack's M5 sign-off")
            c(not unpack(t.port(lid)["sym"]).any(), f"{lid}: symbol errors on a new link")
    out.append(c)

    # ---- 6. optics
    c = Check("optics", "Each optic replacement on record follows a failing optic's signature, and clears it only if it ended the errors")
    oc = cfg["optics"]
    tickets = [x for x in json.loads((t.sample / "vendor" / "tickets.json").read_text(encoding="utf-8")) if x["category"] == "optic_link"]
    stab = timedelta(hours=cfg["checks"].get("recur_hours", 24))

    def sig_at(lid: str, m: int) -> str | None:
        rx, snr = t.minute(lid, "rx_dbm", m), t.minute(lid, "snr", m)
        if rx is None:
            return None
        if rx < oc["signature_rx_dbm"] * 10:
            return "host"
        if snr is not None and snr < oc["signature_snr_db"] * 10:
            return "switch"
        return "clear"

    for tk in tickets:
        mm = LINK_RE.search(tk["short_description"])
        if not mm:
            continue
        lid = f"{mm.group(1)}:swp{mm.group(2)}"
        note = next((n for n in tk["work_notes"] if n["text"].startswith("Replaced")), None)
        if note is None:
            # a reseat: the receive power drops below the warning at every recorded drop of this incident
            for e in ev_by.get(lid, []):
                te = parse(e["timestamp"])
                if e["event"] == "link_down" and parse(tk["opened_at"]) - timedelta(hours=3) <= te <= parse(tk["opened_at"]) \
                        and not peer_power_lost(e, lost):
                    rx = t.minute(lid, "rx_dbm", t.m_of(e["timestamp"]))
                    c(rx is not None and rx < oc["warn_rx_dbm"] * 10, f"{lid}: receive power {rx} at the drop {e['timestamp']}")
            continue
        at = parse(note["at"])
        side = "switch" if "(switch side)" in note["text"] else "host"
        before = [sig_at(lid, m) for m in range(t.m_of(parse(tk["opened_at"]) - timedelta(hours=6)), t.last_m(at) - 15)]
        seen = [s for s in before if s in ("host", "switch")]
        c(bool(seen), f"{tk['number']} {lid}: no failing-optic signature before the replacement")
        more = [e for e in ev_by.get(lid, []) if at < parse(e["timestamp"]) <= at + stab and e["event"] != "link_up"]
        after = [s for s in (sig_at(lid, m) for m in range(t.m_of(at) + 15, t.m_of(at) + 90)) if s is not None]
        if more:
            c(any(s in ("host", "switch") for s in after), f"{tk['number']} {lid}: errors continued but the signature cleared")
            c(not seen or seen[-1] != side, f"{tk['number']} {lid}: the replaced {side} end was the failing one, yet errors continued")
        else:
            c(bool(after) and all(s == "clear" for s in after), f"{tk['number']} {lid}: signature remains after the replacement"
              + ("" if after else " (no minute published after it)"))
            c(bool(seen) and seen[-1] == side, f"{tk['number']} {lid}: replaced the {side} end, signature at the {seen[-1] if seen else None} end")
    out.append(c)

    # ---- 7. uplinks
    c = Check("uplinks", "Each leaf's uplinks carry their share of its downlink traffic, every hour")
    share = cfg["traffic"]["uplink_share"]
    for leaf, d in sorted(t.devices("leaf").items()):
        L = t.leaf(leaf)
        rx = sum(unpack(t.port(f"{leaf}:swp{p}")["rx_gbps"]) for p in d["ports"])
        tx = sum(unpack(t.port(f"{leaf}:swp{p}")["tx_gbps"]) for p in d["ports"])
        tol = 0.5 * share * len(d["ports"]) + 1
        ut, ur = unpack(L["uplink"]["tx_gbps"]), unpack(L["uplink"]["rx_gbps"])
        c(bool(np.all(np.abs(ut - share * rx) <= tol)), f"{leaf}: uplink out differs from {share:.0%} of its trays' traffic")
        c(bool(np.all(np.abs(ur - share * tx) <= tol)), f"{leaf}: uplink in differs from {share:.0%} of its trays' traffic")
    out.append(c)

    # ---- 8. NVLink trays
    c = Check("nvlink", "Each NVLink switch tray reports while its rack's GPUs report, except exactly while the NMX records it failed")
    nmx = sorted(_jsonl(t.sample / "telemetry" / "nmx_events.jsonl"), key=lambda e: e["timestamp"])
    failed: dict[str, list[tuple[int, int]]] = {}
    since: dict[str, int] = {}
    for e in nmx:
        tray = e["unit"].split()[-1]
        if e["state"] == "failed":
            since[tray] = t.m_of(e["timestamp"])
        elif tray in since:
            failed.setdefault(tray, []).append((since.pop(tray), t.m_of(e["timestamp"])))
    for tray, a in since.items():
        failed.setdefault(tray, []).append((a, M))
    for rack in sorted({d["rack"] for d in t.devices("nvlink").values()}):
        g = t.gpu_hourly.get(rack, {}).get("gpus", [])
        rack_n = sum(np.array(unrle(x["n"]), dtype=np.float64) for x in g) if g else np.zeros(H)
        trays = t.nvl(rack)["trays"]
        for name, x in trays.items():
            ok = unpack(x["ok_min"])
            want_on = rack_n > 0
            for a, b in failed.get(name, []):
                for h in range(a // HOUR, min(H, (b + HOUR - 1) // HOUR)):
                    lo, hi = max(a, h * HOUR), min(b, (h + 1) * HOUR)
                    c(ok[h] <= HOUR - (hi - lo), f"{name}: reports {ok[h]} minutes in hour {h}, NMX failed {hi - lo} of them")
                    if hi - lo == HOUR:
                        want_on[h] = False
                fm = [t.minute(name, "ok", m) for m in range(a, min(b, M))]
                c(all(v == 0 for v in fm if v is not None) and any(v is not None for v in fm), f"{name}: reported while the NMX records it failed")
                pre = [t.minute(name, "ok", m) for m in range(max(0, a - 20), a)]
                c(all(v == 1 for v in pre if v is not None), f"{name}: dark before the NMX recorded the failure")
            c(np.array_equal(ok > 0, want_on), f"{name}: reports in {int(((ok > 0) != want_on).sum())} hours its rack's GPUs do not (or the reverse)")
    out.append(c)

    # ---- 9. ranges
    c = Check("ranges", "Module temperature, receive power, and switch temperature stay inside the published ranges")
    th = cfg["optics"]["thresholds"]
    for lid, d in sorted(ports.items()):
        o = t.port(lid)["optics"]
        mod = unpack(o["mod_c_max"])
        rx = unpack(o["rx_dbm_min"])
        downs = unpack(t.port(lid)["downs"]) if o["per"] == "hour" else None
        upm = unpack(t.port(lid)["up_min"])
        c(bool(np.all((mod == -9999) | (mod < th["temp_c"][1]))), f"{lid}: module at {int(mod.max())} °C (alarm {th['temp_c'][1]} °C)")
        if o["per"] == "hour":
            ok = (rx == -9999) | (rx >= th["rx_dbm"][0] * 10) | (downs > 0) | (upm < HOUR)
        else:
            ok = (rx == -9999) | (rx >= th["rx_dbm"][0] * 10)
        c(bool(np.all(ok)), f"{lid}: receive power {int(rx.min()) / 10} dBm with the link up")
    for leaf in t.devices("leaf"):
        a = unpack(t.leaf(leaf)["chassis"]["asic_c"])
        c(bool(np.all((a > 20) & (a < 95))), f"{leaf}: ASIC at {int(a.max())} °C")
    out.append(c)
    return out


def summary(checks: list[Check]) -> dict[str, Any]:
    return {"checks": [{"name": c.name, "title": c.title, "checked": c.checked, "misses": len(c.misses)} for c in checks],
            "agree": sum(c.checked - len(c.misses) for c in checks), "total": sum(c.checked for c in checks),
            "misses": [m for c in checks for m in c.misses[:5]]}
