"""Synthetic network telemetry for Site AUS-1: the InfiniBand back-end fabric and the NVLink switch trays.

Portfolio demo; all data fictional. Runs on a finished month after its GPU telemetry, with its own random stream,
and writes beside it, never into it.

* **Links.** Every back-end link is one tray NIC (``mlx5_0`` to ``mlx5_3``, one per rail) to one leaf port, by the
  generator's cabling rule (``SiteGenerator.link_for``, the same rule the device directory reads). Hall A links are
  up from the start of the month; a Hall B link exists from the "Link is Up" the fabric manager logged when it was
  cabled at the rack's M5 milestone. A link is down exactly between each recorded ``link_down`` and its ``link_up``
  (``ufm_port_events``): single-link faults, and every link of a rack that lost power.
* **Traffic.** Each tray drives its four rail links in proportion to its GPUs' utilization in the GPU telemetry
  (``Published.tray_load``), so a link carries nothing while its tray is dark, drained, or idle. A leaf's uplinks
  carry the share of its downlink traffic bound for other rack pairs. Counters are the IBTA PortCountersExtended
  under UFM Telemetry's names; data counters are 4-octet words, as IBTA and the kernel define them.
* **Errors.** Symbol errors are exactly the counts the fabric manager reported: each report counts the errors since
  the link's previous report (at most ``symbol_report_min`` minutes), and a healthy link counts none.
  LinkDownedCounter rises once per recorded link drop.
* **Optics.** Every optic fault on record has a physical signature at the end the records name: a failing host-side
  optic's laser sags (the switch reads low receive power on one lane); a failing switch-side optic's receiver
  degrades (low SNR at normal power, a warmer module); a loose or dirty connector drops receive power through
  sensitivity at each flap. The signature starts before the first errors and clears at the swap that ended them,
  so a swap at the wrong end (PD-015) leaves it in place until the right end is replaced.
* **NVLink trays.** Nine per rack, each carrying a ninth of its rack's GPU-to-GPU traffic; a tray reports while its
  rack's GPUs report, except while the NMX records it failed, when the other eight carry its share.

Published tiers (see ``write_network``): per hall and rail hourly, per rack NVLink hourly, the states, and one-minute
windows around every fabric event, committed; every port's hourly series per leaf and every tray's hourly series per
rack built at publish time with checksums in the manifest. Settings: ``config/telemetry_network.yaml``.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from scorecard.fabric import peer_power_lost, power_loss_links
from scorecard.synthetic.generator import SiteGenerator
from scorecard.synthetic.telemetry import MIN, GpuTelemetry, Published, _csv, _dump, _jsonl, iso, parse
from scorecard.synthetic.telemetry_power import pack

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "telemetry_network.yaml"
HOUR_MIN = 60
RAILS = 4

FABRIC_HOURLY = ["hour", "hall", "rail", "leaves", "links_cabled", "links_up", "tx_tb", "rx_tb", "uplink_tb", "util_avg_pct",
                 "util_max_pct", "symbol_errors", "link_downs", "module_c_max", "asic_c_max", "switch_kw"]
NVLINK_HOURLY = ["hour", "rack", "hall", "trays_reporting", "tray_minutes", "tx_tb", "asic_c_max", "power_kw", "link_downs"]


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rng(seed: int, *parts: object) -> np.random.Generator:
    key = ":".join(str(p) for p in (seed, "telemetry", "network") + parts)
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def port_name(product: dict, port: int) -> str:
    """The switch's own name for a port: QM9700 ``IB1/<cage>/<port>``, Q3400 ``sw<cage>p<port>`` (two ports per cage)."""
    return product["port_name"].format(cage=(port + 1) // 2, port=2 - port % 2)


def guid(*parts: object) -> str:
    """A synthetic 64-bit GUID (NVIDIA's OUI prefix is not used: these are fictional)."""
    h = hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()
    return "0x" + "fa" + h[:14]


class NetworkTelemetry:
    """One-minute fabric readings for every link and leaf, and every NVLink switch tray, in halls with GPU telemetry."""

    def __init__(self, tel: GpuTelemetry, pub: Published, cfg: dict[str, Any] | None = None):
        self.tel, self.pub = tel, pub
        self.cfg = cfg or load_config()
        self.seed, self.start, self.end, self.M = tel.seed, tel.start, tel.end, tel.M
        self.H = self.M // HOUR_MIN
        d = tel.dir
        self.ufm = sorted(_jsonl(d / "telemetry" / "ufm_port_events.jsonl"), key=lambda e: e["timestamp"])
        self.nmx = sorted(_jsonl(d / "telemetry" / "nmx_events.jsonl"), key=lambda e: e["timestamp"])
        gt = d / "ground_truth" / "incidents.json"
        self.incidents = [i for i in json.loads(gt.read_text(encoding="utf-8")) if i["kind"] == "optic_link"] if gt.exists() else []
        topo = json.loads((d / "site" / "topology.json").read_text(encoding="utf-8"))
        self.racks = {r["rack"]: r for r in topo["racks"] if r["state"] in ("production", "deployment")}
        from scorecard import site_model as S
        site = S.load_site()
        self.fabric = {h["id"]: h["fabric"] for h in site["halls"]}
        self.conflicts: list[str] = []
        self.lost = power_loss_links(self.ufm, tel.sched)
        # every link the records know: Hall A cabled; Hall B from its first "Link is Up"
        ev_by: dict[str, list[dict]] = {}
        for e in self.ufm:
            ev_by.setdefault(f"{e['switch']}:swp{e['port']}", []).append(e)
        self.links: dict[str, dict] = {}
        for rack in sorted(self.racks.values(), key=lambda r: r["rack"]):
            for tray in rack["compute_trays"]:
                for rail in range(RAILS):
                    L = SiteGenerator.link_for(rack, tray["slot"], rail)
                    lid = f"{L['switch']}:swp{L['port']}"
                    evs = ev_by.get(lid, [])
                    if rack["state"] != "production" and not any(e["event"] == "link_up" for e in evs):
                        continue                                    # not cabled yet
                    prod = self.cfg["products"][self.fabric[rack["hall"]]]
                    self.links[lid] = {"switch": L["switch"], "port": L["port"], "host": L["host"], "hca": L["hca"],
                                       "rack": rack["rack"], "hall": rack["hall"], "rail": rail, "slot": tray["slot"],
                                       "product": self.fabric[rack["hall"]], "gbps": prod["gbps"],
                                       "name": port_name(prod, L["port"]), "events": evs,
                                       "cabled_at_start": rack["state"] == "production"}
                    for e in evs:
                        if e["peer_host"] != L["host"] or e["peer_hca"] != L["hca"]:
                            self.conflicts.append(f"{lid}: event names {e['peer_host']} {e['peer_hca']}, cabling says {L['host']} {L['hca']}")
        known = set(self.links)
        for lid in ev_by:
            if lid not in known:
                self.conflicts.append(f"{lid}: fabric events on a link that is not cabled")
        self.leaves: dict[str, dict] = {}
        for lid, x in self.links.items():
            lf = self.leaves.setdefault(x["switch"], {"hall": x["hall"], "rail": x["rail"], "product": x["product"], "ports": []})
            lf["ports"].append(lid)

    # ----------------------------------------------------------------- time helpers
    def m_of(self, t: datetime) -> int:
        """Index of the first sample at or after t."""
        return self.tel.m_of(t)

    def last_m(self, t: datetime) -> int:
        """Index of the last sample at or before t (-1 if none)."""
        return min(self.M - 1, int(math.floor((t - self.start).total_seconds() / 60 + 1e-9)))

    # ----------------------------------------------------------------- link state and counters from the records
    def link_state(self, x: dict) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
        """(up per minute, LinkDownedCounter per minute, down spans): down from each link_down to its link_up; a
        Hall B link is down until its first link_up."""
        up = np.ones(self.M, dtype=bool) if x["cabled_at_start"] else np.zeros(self.M, dtype=bool)
        downs = np.zeros(self.M, dtype=np.int64)
        spans = []
        cur = None if x["cabled_at_start"] else 0
        for e in x["events"]:
            t = parse(e["timestamp"])
            if e["event"] == "link_down":
                m = self.m_of(t)
                if m < self.M:
                    downs[m] += 1
                if cur is None:
                    cur = m
            elif e["event"] == "link_up" and cur is not None:
                m = self.m_of(t)
                up[cur:m] = False
                up[m:] = True
                spans.append((cur, m))
                cur = None
        if cur is not None:
            up[cur:] = False
            spans.append((cur, self.M))
        return up, np.cumsum(downs), spans

    def symbol_errors(self, x: dict, rng: np.random.Generator) -> tuple[np.ndarray, list[dict]]:
        """Errors per minute: each report's count spread over the minutes since the link's previous report (at most
        symbol_report_min), rising toward the report."""
        err = np.zeros(self.M, dtype=np.int64)
        reports, prev = [], None
        for e in x["events"]:
            if e["event"] not in ("symbol_errors", "symbol_error_threshold"):
                continue
            t = parse(e["timestamp"])
            a = t - timedelta(minutes=self.cfg["symbol_report_min"])
            if prev is not None and prev > a:
                a = prev
            m0, m1 = self.last_m(a) + 1, self.last_m(t)      # minutes with a < t_m <= t
            if m1 < m0 or m1 < 0:
                self.conflicts.append(f"{x['switch']} port {x['port']}: symbol report at {e['timestamp']} has no minute to count in")
                continue
            m0 = max(m0, 0)
            n = m1 - m0 + 1
            w = np.linspace(0.5, 1.5, n) * rng.uniform(0.6, 1.4, n)
            err[m0:m1 + 1] += _apportion(w, int(e["count"]))
            reports.append({"time": e["timestamp"], "from_m": m0, "to_m": m1, "count": int(e["count"])})
            prev = t
        return err, reports

    # ----------------------------------------------------------------- optic faults, from the records
    def episodes(self) -> dict[str, list[dict]]:
        """Per link, each optic fault: start, end, and the end at fault. A swap at the wrong end (its follow-up names
        it as parent) does not end the fault; the follow-up's swap does."""
        by_id = {i["gt_id"]: i for i in self.incidents}
        child = {i["parent_gt_id"]: i for i in self.incidents if i.get("parent_gt_id")}
        out: dict[str, list[dict]] = {}
        for i in sorted(self.incidents, key=lambda i: i["t0"]):
            if i.get("parent_gt_id") in by_id:
                continue                                        # folded into its parent's episode
            L = i["link"]
            lid = f"{L['switch']}:swp{L['port']}"
            chain = [i]
            while chain[-1]["gt_id"] in child:
                chain.append(child[chain[-1]["gt_id"]])
            last = chain[-1]
            evs = [e for e in self.links.get(lid, {}).get("events", []) if e["event"] != "link_up"
                   and parse(e["timestamp"]) <= parse(i["t0"]) + timedelta(minutes=1)
                   and parse(e["timestamp"]) >= parse(i["t0"]) - timedelta(hours=8)]
            first = min((parse(e["timestamp"]) for e in evs), default=parse(i["t0"]))
            kind = "connector" if last["optic_side"] is None else last["optic_side"]
            end = parse(last["swap_time"]) if last.get("swap") and last.get("swap_time") else parse(last["repair_done"])
            if kind != "connector":
                first = first - timedelta(minutes=self.cfg["symbol_report_min"])
            out.setdefault(lid, []).append({"gt": [c["gt_id"] for c in chain], "kind": kind, "first": first, "end": end,
                                            "swaps": [{"side": c["optic_side"], "at": c.get("swap_time"), "gt": c["gt_id"]}
                                                      for c in chain if c.get("swap")]})
        return out

    # ----------------------------------------------------------------- one link, the month
    def link(self, lid: str, eps: list[dict]) -> dict[str, Any]:
        x, cfg = self.links[lid], self.cfg
        oc, tc = cfg["optics"], cfg["traffic"]
        rng = _rng(self.seed, "link", lid)
        M, H = self.M, self.H
        up, downs, down_spans = self.link_state(x)
        err, reports = self.symbol_errors(x, rng)
        load = self.pub.tray_load.get(x["host"])
        # traffic: the tray's GPUs, scaled to the line rate, per rail, per hour
        line = x["gbps"] * 1e9
        if load is None:
            busy = np.zeros(M)
        else:
            busy = np.where(load["n"] > 0, curve(load["util"].astype(np.float64) / 100, tc["util_exponent"]), 0.0)
        rail_f = 1 + rng.normal(0, tc["rail_spread"], H)
        rx_f = rng.uniform(*tc["rx_over_tx"], H)
        bps = busy * line * tc["peak_line_fraction"] * np.repeat(rail_f, HOUR_MIN)
        bps = np.where(up, bps + tc["background_bps"], 0.0)
        tx_w = np.round(bps * 60 / 8 / 4).astype(np.int64)                      # 4-octet words per minute
        rx_w = np.round(bps * np.repeat(rx_f, HOUR_MIN) * 60 / 8 / 4).astype(np.int64)
        rx_w = np.where(up, rx_w, 0)
        wait = np.round(tx_w * tc["xmit_wait_per_util"] * busy).astype(np.int64)
        # optics: baselines, then each fault's signature
        tx_dbm = rng.uniform(*oc["tx_dbm"])
        loss = rng.uniform(*oc["link_loss_db"])
        rx0 = tx_dbm - loss
        rx = rx0 + _wander(rng, M, 0.12)
        snr = rng.uniform(*oc["snr_db"]) + _wander(rng, M, 0.15)
        mod = rng.uniform(*oc["module_c"]) + oc["module_c_at_load"] * busy + _wander(rng, M, 0.4)
        raw = rng.uniform(*cfg["ber"]["raw_log10"]) + _wander(rng, M, 0.08)
        ler = np.zeros(M, dtype=np.int64)
        sig = []
        for ep in eps:
            a = self.m_of(ep["first"])
            b = min(M, self.m_of(ep["end"]))
            if ep["kind"] == "connector":
                lo = max(0, a - int(rng.integers(20, 60)))
                prof = np.zeros(M)
                prof[lo:b] = rng.uniform(1.0, 4.0, b - lo)                       # a loose connector: unsteady loss
                for s0, s1 in down_spans:
                    if lo <= s0 < b:
                        prof[s0:max(s1, s0 + 1)] = rng.uniform(*oc["flap_rx_dip_db"])
                        ler[s0] += 1
                rx = rx - prof
                raw = raw + np.where(prof > 0, (cfg["ber"]["raw_log10_fault"] - raw) * np.minimum(prof / 6, 1), 0)
                sig.append({"kind": "connector", "from_m": lo, "to_m": b, "gt": ep["gt"]})
                continue
            lo = max(0, a - int(rng.integers(*oc["onset_before_errors_min"])))
            ramp = np.zeros(M)
            if b > lo:
                k = np.arange(b - lo)
                ramp[lo:b] = np.minimum(1.0, (k + 1) / max(1, a - lo + 30)) * (0.85 + 0.15 * rng.random(b - lo))
            if ep["kind"] == "host":
                rx = rx - ramp * rng.uniform(*oc["fault_tx_sag_db"])
            else:
                snr = snr - ramp * (snr - rng.uniform(*oc["fault_snr_db"]))
                mod = mod + ramp * rng.uniform(*oc["fault_warm_c"])
            raw = raw + ramp * (cfg["ber"]["raw_log10_fault"] - raw)
            ler[lo:b] += (rng.random(b - lo) < 0.004).astype(np.int64)
            sig.append({"kind": ep["kind"], "from_m": lo, "to_m": b, "gt": ep["gt"], "swaps": ep["swaps"]})
        # a swapped module brings its own baseline (the replacement's launch power)
        for ep in eps:
            for sw in ep["swaps"]:
                if sw["at"] and sw["side"] == "host":
                    m = self.m_of(parse(sw["at"]))
                    rx[m:] += rng.uniform(-0.4, 0.4)
        # down with the far end powered (a flap): the module still reads the low light; far end without power: no
        # light at all (CMIS floor, -40 dBm); before the cable is in: no module, no reading
        dark = np.zeros(M, dtype=bool)
        for e in x["events"]:
            if e["event"] == "link_down" and peer_power_lost(e, self.lost):
                a = self.m_of(parse(e["timestamp"]))
                b = next((s1 for s0, s1 in down_spans if s0 == a), a)
                dark[a:b] = True
        rx = np.where(dark, -40.0, rx)
        if not x["cabled_at_start"]:
            first = next((parse(e["timestamp"]) for e in x["events"] if e["event"] == "link_up"), self.end)
            rx[:self.m_of(first)] = np.nan
            snr[:self.m_of(first)] = np.nan
            mod[:self.m_of(first)] = np.nan
        raw5 = np.repeat(raw.reshape(-1, 5).max(axis=1), 5)[:M] if M % 5 == 0 else raw   # secondary fields every 5 minutes
        return {"lid": lid, "up": up, "downs": downs, "down_spans": down_spans, "err": err, "reports": reports,
                "tx": tx_w, "rx": rx_w, "wait": wait, "ler": np.cumsum(ler), "rx_dbm": rx, "snr": snr, "mod_c": mod,
                "raw_ber": raw5, "busy": busy, "sig": sig, "baseline": {"tx_dbm": round(tx_dbm, 1), "rx_dbm": round(rx0, 1)}}

    # ----------------------------------------------------------------- leaves
    def leaf_hourly(self, leaf: str, ports: dict[str, dict]) -> dict[str, Any]:
        lf, cfg = self.leaves[leaf], self.cfg
        prod = cfg["products"][lf["product"]]
        rng = _rng(self.seed, "leaf", leaf)
        H = self.H
        tx = sum(p["tx"] for p in ports.values())                       # each port's hourly words (reduced)
        rx = sum(p["rx"] for p in ports.values())
        share = cfg["traffic"]["uplink_share"]
        up_tx = np.round(rx * share).astype(np.int64)                    # tray traffic leaving the rack pair goes up
        up_rx = np.round(tx * share).astype(np.int64)                    # and traffic for its trays comes down
        cabled = np.zeros(H)
        for p in ports.values():
            cabled += p["up_min"] > 0
        cages = np.ceil(cabled / 2) + prod["uplinks"] // 2
        line_words_h = prod["gbps"] * 1e9 / 32 * 3600
        frac = np.clip(tx / np.maximum(cabled, 1) / line_words_h, 0, 1)
        cc = cfg["chassis"]
        inlet = rng.uniform(*cc["inlet_c"]) + 0.8 * np.sin(np.arange(H) * 2 * np.pi / 24 + rng.uniform(0, 6.3)) + _wander(rng, H, 0.2)
        asic = inlet + rng.uniform(*cc["asic_rise_c"]) + cc["asic_rise_at_full_c"] * frac
        fan = rng.uniform(*cc["fan_rpm"]) + cc["fan_rpm_per_c"] * (asic - asic.mean()) + _wander(rng, H, 60)
        pw = prod["power_w"]["base"] + prod["power_w"]["per_cage"] * cages + prod["power_w"]["at_full_traffic"] * frac + _wander(rng, H, 4)
        return {"up_tx": up_tx, "up_rx": up_rx, "asic_c": np.round(asic).astype(np.int64), "fan_rpm": np.round(fan, -1).astype(np.int64),
                "power_w": np.round(pw).astype(np.int64), "cabled": cabled.astype(np.int64)}

    # ----------------------------------------------------------------- NVLink trays
    def nvlink(self) -> dict[str, dict]:
        cfg = self.cfg["nvlink"]
        out = {}
        failed: dict[str, list[tuple[int, int]]] = {}
        since: dict[str, int] = {}
        for e in self.nmx:
            tray = e["unit"].split()[-1]
            m = self.m_of(parse(e["timestamp"]))
            if e["state"] == "failed":
                since[tray] = m
            elif tray in since:
                failed.setdefault(tray, []).append((since.pop(tray), m))
        for tray, m in since.items():
            failed.setdefault(tray, []).append((m, self.M))
        tc = self.cfg["traffic"]
        for rack, r in sorted(self.racks.items()):
            loads = [self.pub.tray_load[t["host"]] for t in r["compute_trays"] if t["host"] in self.pub.tray_load]
            if not loads:
                continue
            rng = _rng(self.seed, "nvlink", rack)
            n = sum(x["n"].astype(np.int64) for x in loads)
            util = sum(np.where(x["n"] > 0, curve(x["util"].astype(np.float64) / 100, tc["util_exponent"]) * x["n"], 0)
                       for x in loads)
            gb_s = util * 18 * cfg["link_gbyte_s"] * cfg["peak_fraction"]                 # the rack's GPUs, each way
            live = n > 0
            trays = {}
            ups = []
            for st in r["switch_trays"]:
                ok = live.copy()
                for a, b in failed.get(st["name"], []):
                    ok[a:b] = False
                ups.append(ok)
            k = np.maximum(sum(u.astype(np.int64) for u in ups), 1)
            for st, ok in zip(r["switch_trays"], ups):
                tx = np.where(ok, gb_s * 60 / k, 0.0)                                       # GB per minute
                frac = np.clip(gb_s / (72 * 18 * cfg["link_gbyte_s"]) * 9 / k, 0, 1)
                asic = rng.uniform(*cfg["asic_c"]) + cfg["asic_rise_at_full_c"] * frac + _wander(rng, self.M, 0.3)
                pw = cfg["power_w"]["idle"] + (cfg["power_w"]["at_full"] - cfg["power_w"]["idle"]) * frac + _wander(rng, self.M, 6)
                downs = np.zeros(self.M, dtype=np.int64)
                for a, b in failed.get(st["name"], []):
                    if a < self.M:
                        downs[a] += cfg["ports_per_tray"]
                trays[st["name"]] = {"ok": ok, "tx_gb": np.where(ok, tx, 0.0), "asic_c": np.where(ok, asic, np.nan),
                                     "power_w": np.where(ok, pw, np.nan), "downs": np.cumsum(downs),
                                     "up_ports": np.where(ok, cfg["ports_per_tray"], 0)}
            out[rack] = {"hall": r["hall"], "trays": trays, "failed": {t: failed[t] for t in trays if t in failed}}
        return out

    # ----------------------------------------------------------------- the month
    def run(self) -> dict[str, Any]:
        """The month, one link at a time: each link's minute arrays are reduced to what is published, then dropped."""
        eps = self.episodes()
        for lid in eps:
            if lid not in self.links:
                self.conflicts.append(f"{lid}: an optic fault on a link that is not cabled")
        notes: dict[str, list[dict]] = {}
        for s in self.ticket_states():
            notes.setdefault(s["device"], []).append(s)
        links = {}
        for lid in sorted(self.links):
            x = self.link(lid, eps.get(lid, []))
            links[lid] = self.reduce(x, self.link_states(lid, x["sig"]) + notes.get(lid, []))
        leaves = {}
        for leaf in sorted(self.leaves):
            leaves[leaf] = self.leaf_hourly(leaf, {lid: links[lid] for lid in self.leaves[leaf]["ports"]})
        return {"links": links, "leaves": leaves, "nvlink": self.nvlink(), "states": self.states(links)}

    def reduce(self, x: dict[str, Any], states: list[dict]) -> dict[str, Any]:
        """One link's minute arrays reduced to its hourly series, optics tier, totals, and minute windows."""
        lid, meta, M, H = x["lid"], self.links[x["lid"]], self.M, self.H
        sh = (H, HOUR_MIN)
        r = {"lid": lid, "sig": x["sig"], "reports": x["reports"], "baseline": x["baseline"],
             "tx": x["tx"].reshape(sh).sum(axis=1), "rx": x["rx"].reshape(sh).sum(axis=1),
             "up_min": x["up"].reshape(sh).sum(axis=1), "sym": np.diff(np.r_[0, np.cumsum(x["err"])[HOUR_MIN - 1::HOUR_MIN]]),
             "downs": np.diff(np.r_[0, x["downs"][HOUR_MIN - 1::HOUR_MIN]]), "line_h": meta["gbps"] * 1e9 / 32 * 3600,
             "mod_max": _hour(x["mod_c"], sh, "max"),
             "optics": optics(x, sh if x["sig"] or meta["events"] else (H // 24, 24 * HOUR_MIN)),
             "tx_words": int(x["tx"].sum()), "rx_words": int(x["rx"].sum()), "wait": int(x["wait"].sum()), "ler": int(x["ler"][-1])}
        # minute windows around each fault record and each symbol-error report (merged spans)
        tw = self.cfg["tiers"]
        spans = [(max(0, s["m"] - tw["window_before_min"]), min(M, s["m"] + tw["window_after_min"]))
                 for s in states if s.get("cause", "fault") == "fault"]
        spans += [(max(0, p["from_m"] - 1), min(M, p["to_m"] + 2)) for p in x["reports"]]
        merged: list[list[int]] = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        r["windows"] = []
        for a, b in merged:
            sl = slice(a, b)
            r["windows"].append((a, b, {"tx": np.cumsum(x["tx"])[sl].tolist(), "rx": np.cumsum(x["rx"])[sl].tolist(),
                                        "sym": np.cumsum(x["err"])[sl].tolist(), "downs": x["downs"][sl].tolist(),
                                        "ler": x["ler"][sl].tolist(), "wait": np.cumsum(x["wait"])[sl].tolist(),
                                        "up": x["up"][sl].astype(int).tolist(), "raw_ber": _i(x["raw_ber"][sl], 100).tolist(),
                                        "rx_dbm": [None if math.isnan(v) else int(round(v * 10)) for v in x["rx_dbm"][sl].tolist()],
                                        "snr": _i(x["snr"][sl], 10).tolist(), "mod_c": _i(x["mod_c"][sl]).tolist()}))
        return r

    def states(self, links: dict[str, dict]) -> list[dict]:
        """The fabric events a client sees, each with the record it comes from, plus each optic signature's span."""
        out = []
        for lid in self.links:
            out += self.link_states(lid, links[lid]["sig"])
        out += self.ticket_states()
        for e in self.nmx:
            out.append({"device": e["unit"].split()[-1], "family": "nvlink", "time": e["timestamp"], "m": self.m_of(parse(e["timestamp"])),
                        "point": "NVLink domain", "value": e["state"], "record": "telemetry/nmx_events.jsonl"})
        return sorted(out, key=lambda s: (s["time"], s["device"], s["point"]))

    def link_states(self, lid: str, sig: list[dict]) -> list[dict]:
        """One link's UFM events (each with its cause) and its optic signature's span."""
        out = []
        x = self.links[lid]
        ev_point = {"link_down": "Link is Down (329)", "link_up": "Link is Up (328)", "symbol_errors": "Symbol Error (110)",
                    "symbol_error_threshold": "Symbol Error (110), threshold"}
        first_up = not x["cabled_at_start"]
        for e in x["events"]:
            cause = "fault"
            if peer_power_lost(e, self.lost):
                cause = "rack power lost"
            elif e["event"] == "link_up" and first_up:
                cause = "cabled"
            if e["event"] == "link_up":
                first_up = False
            out.append({"device": lid, "family": "port", "time": e["timestamp"], "m": min(self.m_of(parse(e["timestamp"])), self.M - 1),
                        "point": ev_point[e["event"]], "value": e["count"], "record": "telemetry/ufm_port_events.jsonl", "cause": cause})
        for s in sig:
            out.append({"device": lid, "family": "port", "time": iso(self.start + s["from_m"] * MIN), "m": s["from_m"],
                        "point": "Optic signature", "value": f"{s['kind']} end: begins", "record": "ground_truth (signature)", "gt": s["gt"]})
            out.append({"device": lid, "family": "port", "time": iso(self.start + min(s["to_m"], self.M - 1) * MIN),
                        "m": min(s["to_m"], self.M - 1), "point": "Optic signature", "value": f"{s['kind']} end: clears",
                        "record": "ground_truth (signature)", "gt": s["gt"]})
        return out

    def ticket_states(self) -> list[dict]:
        """Each optic ticket's repair note in the month, on its link."""
        out = []
        tk = self.tel.dir / "vendor" / "tickets.json"
        for x in (json.loads(tk.read_text(encoding="utf-8")) if tk.exists() else []):
            if x["category"] != "optic_link":
                continue
            lid = x["short_description"].split(" <-> ")[-1]                # "Link a13-ct18:mlx5_1 <-> leaf-a07-r1:swp18"
            note = next((n for n in x["work_notes"] if n["text"].startswith(("Replaced", "Inspected"))), None)
            if lid not in self.links or note is None or not (self.start <= parse(note["at"]) < self.end):
                continue
            what = "host end replaced" if "(host side)" in note["text"] else "switch end replaced" if "(switch side)" in note["text"] \
                else "cleaned, no part replaced"
            out.append({"device": lid, "family": "port", "time": note["at"], "m": min(self.m_of(parse(note["at"])), self.M - 1),
                        "point": f"Optic ({x['number']})", "value": what, "record": "vendor/tickets.json", "cause": "fault"})
        return out


# --------------------------------------------------------------------- helpers
def _apportion(w: np.ndarray, total: int) -> np.ndarray:
    """Non-negative integers proportional to w summing to total."""
    w = np.maximum(np.asarray(w, dtype=np.float64), 0) + 1e-12
    want = w * total / w.sum()
    base = np.floor(want).astype(np.int64)
    short = total - int(base.sum())
    if short:
        base[np.argsort(-(want - base), kind="stable")[:short]] += 1
    return base


def _wander(rng: np.random.Generator, n: int, sd: float, rho: float = 0.98) -> np.ndarray:
    """A slow random wander with standard deviation sd: AR(1), stationary from the first value (pandas ewm, the same
    numbers on every CPU)."""
    import pandas as pd
    if n == 0:
        return np.zeros(0)
    e = rng.normal(0, sd * math.sqrt(1 - rho * rho), n)
    v = e / (1 - rho)
    v[0] = rng.normal(0, sd)                    # y[0] = v[0]; then y[t] = rho y[t-1] + e[t]
    return pd.Series(v).ewm(alpha=1 - rho, adjust=False).mean().to_numpy()


_CURVES: dict[float, tuple[np.ndarray, np.ndarray]] = {}


def curve(u: np.ndarray, exponent: float) -> np.ndarray:
    """u ** exponent on [0, 1] by table (no array power: the same numbers on every CPU, as in the GPU layer)."""
    if exponent not in _CURVES:
        x = np.linspace(0.0, 1.0, 20001)
        _CURVES[exponent] = (x, np.array([round(math.pow(v, exponent), 12) for v in x]))
    x, y = _CURVES[exponent]
    return np.interp(np.clip(u, 0.0, 1.0), x, y)


# --------------------------------------------------------------------- publish
NONE = -9999                     # an hour with no reading (no module yet)


def _hour(a: np.ndarray, sh: tuple[int, int], how: str) -> np.ndarray:
    """Hourly min or max ignoring missing minutes; NaN for an hour with none."""
    r = np.asarray(a, dtype=np.float64).reshape(sh)
    has = ~np.isnan(r).all(axis=1)
    fill = np.inf if how == "min" else -np.inf
    v = (np.min if how == "min" else np.max)(np.where(np.isnan(r), fill, r), axis=1)
    return np.where(has, v, np.nan)


def _fill(a: np.ndarray) -> np.ndarray:
    return np.where(np.isnan(a), NONE, np.round(np.nan_to_num(a, nan=0.0))).astype(np.int64)


def optics(x: dict, sh: tuple[int, int]) -> dict[str, Any]:
    """The switch-side module's readings per period: hourly on a link with any record, daily on a quiet one."""
    per = "hour" if sh[1] == HOUR_MIN else "day"
    return {"per": per, "rx_dbm_min": pack(_fill(_hour(x["rx_dbm"], sh, "min") * 10)), "snr_min": pack(_fill(_hour(x["snr"], sh, "min") * 10)),
            "mod_c_max": pack(_fill(_hour(x["mod_c"], sh, "max"))),
            "raw_ber_max": pack(_fill(_hour(np.where(np.isnan(x["rx_dbm"]), np.nan, x["raw_ber"]), sh, "max") * 100))}


def _i(a: np.ndarray, s: float = 1) -> np.ndarray:
    return np.round(np.nan_to_num(np.asarray(a, dtype=np.float64), nan=0.0) * s).astype(np.int64)


def write_network(layer: NetworkTelemetry, out: dict[str, Any], dest: str | Path, source: str = "",
                  minutes_dest: str | Path | None = None) -> dict[str, Any]:
    """Write the committed tiers to dest and the publish-time tier (per leaf and per rack hourly) to minutes_dest."""
    cfg = layer.cfg
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    win = dest / "windows"
    if win.exists():
        for p in win.glob("*.json"):
            p.unlink()
    win.mkdir(exist_ok=True)
    M, H, start = layer.M, layer.H, layer.start
    sh = (H, HOUR_MIN)
    hours = [iso(start + h * HOUR_MIN * MIN) for h in range(H)]
    links, leaves = out["links"], out["leaves"]
    # ---- per hall and rail, hourly
    rows = []
    groups: dict[tuple[str, int], list[str]] = {}
    for leaf, lf in layer.leaves.items():
        groups.setdefault((lf["hall"], lf["rail"]), []).append(leaf)
    per_port = links                                     # each link already reduced to its hourly series (run)
    for (hall, rail), lvs in sorted(groups.items()):
        lids = [lid for lf in lvs for lid in layer.leaves[lf]["ports"]]
        for h in range(H):
            cab = sum(1 for lid in lids if per_port[lid]["up_min"][h] > 0 or layer.links[lid]["cabled_at_start"]
                      or any(e["event"] == "link_up" and parse(e["timestamp"]) < start + (h + 1) * HOUR_MIN * MIN for e in layer.links[lid]["events"]))
            upn = sum(1 for lid in lids if per_port[lid]["up_min"][h] == HOUR_MIN)
            tx = sum(int(per_port[lid]["tx"][h]) for lid in lids)
            rx = sum(int(per_port[lid]["rx"][h]) for lid in lids)
            utils = [per_port[lid]["tx"][h] / per_port[lid]["line_h"] * 100 for lid in lids if per_port[lid]["up_min"][h] > 0]
            rows.append({"hour": hours[h], "hall": hall, "rail": rail, "leaves": len(lvs), "links_cabled": cab, "links_up": upn,
                         "tx_tb": round(tx * 4 / 1e12, 2), "rx_tb": round(rx * 4 / 1e12, 2),
                         "uplink_tb": round(sum(int(leaves[lf]["up_tx"][h]) for lf in lvs) * 4 / 1e12, 2),
                         "util_avg_pct": round(float(np.mean(utils)), 1) if utils else "",
                         "util_max_pct": round(float(np.max(utils)), 1) if utils else "",
                         "symbol_errors": sum(int(per_port[lid]["sym"][h]) for lid in lids),
                         "link_downs": sum(int(per_port[lid]["downs"][h]) for lid in lids),
                         "module_c_max": max((int(round(float(per_port[lid]["mod_max"][h]))) for lid in lids
                                             if not math.isnan(per_port[lid]["mod_max"][h])), default=""),
                         "asic_c_max": max(int(leaves[lf]["asic_c"][h]) for lf in lvs),
                         "switch_kw": round(sum(int(leaves[lf]["power_w"][h]) for lf in lvs) / 1000, 2)})
    (dest / "fabric_hourly.csv").write_text(_csv(rows, FABRIC_HOURLY), encoding="utf-8", newline="\n")
    # ---- NVLink per rack, hourly
    nrows = []
    for rack, r in out["nvlink"].items():
        tr = r["trays"]
        for h in range(H):
            sl = slice(h * HOUR_MIN, (h + 1) * HOUR_MIN)
            mins = sum(int(t["ok"][sl].sum()) for t in tr.values())
            rep = sum(1 for t in tr.values() if t["ok"][sl].any())
            asic = [float(np.nanmax(t["asic_c"][sl])) for t in tr.values() if t["ok"][sl].any()]
            pw = [float(np.nanmean(t["power_w"][sl])) for t in tr.values() if t["ok"][sl].any()]
            nrows.append({"hour": hours[h], "rack": rack, "hall": r["hall"], "trays_reporting": rep, "tray_minutes": mins,
                          "tx_tb": round(sum(float(t["tx_gb"][sl].sum()) for t in tr.values()) / 1000, 2),
                          "asic_c_max": int(round(max(asic))) if asic else "", "power_kw": round(sum(pw) / 1000, 2) if pw else "",
                          "link_downs": sum(int(t["downs"][min(M - 1, (h + 1) * HOUR_MIN - 1)] - (t["downs"][h * HOUR_MIN - 1] if h else 0))
                                            for t in tr.values())})
    (dest / "nvlink_hourly.csv").write_text(_csv(nrows, NVLINK_HOURLY), encoding="utf-8", newline="\n")
    states = out["states"]
    (dest / "states.jsonl").write_text("".join(json.dumps(s, sort_keys=True) + "\n" for s in states), encoding="utf-8", newline="\n")
    # ---- minute windows: each link with a record (merged spans, cut in run), each NMX event's tray
    tw = cfg["tiers"]
    index = []
    for lid in sorted(links):
        for a, b, fields in links[lid]["windows"]:
            w = {"device": lid, "family": "port", "from": iso(start + a * MIN), "minutes": b - a, "m0": a, "fields": fields,
                 "states": [s for s in states if s["device"] == lid and a <= s["m"] < b]}
            name = f"{lid.replace(':', '_')}_{w['from'][:16].replace('-', '').replace(':', '')}"
            (win / f"{name}.json").write_text(_dump(w), encoding="utf-8", newline="\n")
            index.append({"file": f"windows/{name}.json", "device": lid, "from": w["from"], "minutes": w["minutes"]})
    for rack, r in out["nvlink"].items():
        for tray, fs in r["failed"].items():
            t = r["trays"][tray]
            for fa, fb in fs:
                a, b = max(0, fa - tw["window_before_min"]), min(M, fb + tw["window_after_min"])
                sl = slice(a, b)
                w = {"device": tray, "family": "nvlink", "from": iso(start + a * MIN), "minutes": b - a, "m0": a,
                     "fields": {"ok": t["ok"][sl].astype(int).tolist(), "tx_gb": np.round(t["tx_gb"][sl], 1).tolist(),
                                "asic_c": [None if math.isnan(v) else int(round(v)) for v in t["asic_c"][sl].tolist()],
                                "up_ports": t["up_ports"][sl].tolist()},
                     "others_tx_gb": np.round(sum(o["tx_gb"][sl] for n, o in r["trays"].items() if n != tray), 1).tolist(),
                     "states": [s for s in states if s["device"] == tray and a <= s["m"] < b]}
                name = f"{tray}_{w['from'][:16].replace('-', '').replace(':', '')}"
                (win / f"{name}.json").write_text(_dump(w), encoding="utf-8", newline="\n")
                index.append({"file": f"windows/{name}.json", "device": tray, "from": w["from"], "minutes": w["minutes"]})
    # ---- publish-time tier: every port hourly, per leaf; every NVLink tray hourly, per rack
    minutes: dict[str, str] = {}
    for leaf, lf in sorted(layer.leaves.items()):
        L = leaves[leaf]
        ports = {}
        for lid in sorted(lf["ports"], key=lambda s: int(s.split("swp")[1])):
            x, p, meta = links[lid], per_port[lid], layer.links[lid]
            ports[str(meta["port"])] = {
                "tx_gbps": pack(np.round(p["tx"] * 32 / 3600 / 1e9).astype(np.int64)),
                "rx_gbps": pack(np.round(p["rx"] * 32 / 3600 / 1e9).astype(np.int64)),
                "up_min": pack(p["up_min"].astype(np.int64)), "sym": pack(p["sym"].astype(np.int64)), "downs": pack(p["downs"].astype(np.int64)),
                "optics": x["optics"], "tx_words": x["tx_words"], "rx_words": x["rx_words"], "wait": x["wait"], "ler": x["ler"]}
        minutes[f"{leaf}.json"] = _dump({"leaf": leaf, **{k: v for k, v in lf.items() if k != "ports"}, "start": iso(start), "hours": H,
                                          "encoding": "first value, then hour-to-hour steps; [n] is n hours unchanged; divide by the field's scale",
                                          "uplink": {"tx_gbps": pack(np.round(L["up_tx"] * 32 / 3600 / 1e9).astype(np.int64)),
                                                     "rx_gbps": pack(np.round(L["up_rx"] * 32 / 3600 / 1e9).astype(np.int64))},
                                          "chassis": {"asic_c": pack(L["asic_c"]), "fan_rpm": pack(L["fan_rpm"]), "power_w": pack(L["power_w"])},
                                          "ports": ports})
    for rack, r in sorted(out["nvlink"].items()):
        trays = {}
        for name, t in r["trays"].items():
            ok = t["ok"].reshape(sh)
            trays[name] = {"ok_min": pack(ok.sum(axis=1).astype(np.int64)),
                           "tx_gb": pack(np.round(t["tx_gb"].reshape(sh).sum(axis=1)).astype(np.int64)),
                           "asic_c": pack(np.where(ok.any(axis=1), np.round(np.nanmax(np.where(ok, t["asic_c"].reshape(sh), -99), axis=1)), -99).astype(np.int64)),
                           "power_w": pack(np.where(ok.any(axis=1), np.round(np.nansum(np.where(ok, t["power_w"].reshape(sh), 0), axis=1) / np.maximum(ok.sum(axis=1), 1)), 0).astype(np.int64)),
                           "downs": int(t["downs"][-1])}
        minutes[f"nvlink_{rack}.json"] = _dump({"rack": rack, "hall": r["hall"], "start": iso(start), "hours": H, "trays": trays,
                                                 "encoding": "first value, then hour-to-hour steps; [n] is n hours unchanged"})
    if minutes_dest is not None:
        md = Path(minutes_dest)
        md.mkdir(parents=True, exist_ok=True)
        for name, text in minutes.items():
            (md / name).write_text(text, encoding="utf-8", newline="\n")
    devices = {}
    for leaf, lf in sorted(layer.leaves.items()):
        prod = cfg["products"][lf["product"]]
        devices[leaf] = {"family": "leaf", "hall": lf["hall"], "rail": lf["rail"], "product": lf["product"], "gbps": prod["gbps"],
                         "os": prod["os"], "node_guid": guid(layer.seed, leaf), "uplinks": prod["uplinks"],
                         "ports": sorted(layer.links[lid]["port"] for lid in lf["ports"])}
    for lid, meta in sorted(layer.links.items()):
        x = links[lid]
        devices[lid] = {"family": "port", "hall": meta["hall"], "leaf": meta["switch"], "port": meta["port"], "name": meta["name"],
                        "peer_host": meta["host"], "peer_hca": meta["hca"], "rack": meta["rack"], "rail": meta["rail"], "gbps": meta["gbps"],
                        "port_guid": guid(layer.seed, meta["switch"], meta["port"]), "peer_guid": guid(layer.seed, meta["host"], meta["hca"]),
                        "cable_sn": "OP" + hashlib.sha256(f"{layer.seed}:{lid}:cable".encode()).hexdigest()[:8].upper(),
                        "cabled_at_start": meta["cabled_at_start"], "baseline": x["baseline"],
                        "signatures": [{"kind": s["kind"], "from": iso(start + s["from_m"] * MIN),
                                        "to": iso(start + min(s["to_m"], M) * MIN), "gt": s["gt"]} for s in x["sig"]]}
    for rack, r in sorted(out["nvlink"].items()):
        for name in r["trays"]:
            devices[name] = {"family": "nvlink", "hall": r["hall"], "rack": rack}
    man = {"disclaimer": "Synthetic network telemetry for a portfolio demonstration, under the published UFM Telemetry, "
                         "node_exporter, SNMP, gNMI, and NMX-T names. All names and readings are fictional.",
           "source": source, "window": {"start": iso(start), "end": iso(layer.end)},
           "devices": devices,
           "files": {"fabric_hourly.csv": len(rows), "nvlink_hourly.csv": len(nrows), "states.jsonl": len(states), "windows": len(index)},
           "windows": index,
           "minutes": {name: {"sha256": hashlib.sha256(t.encode()).hexdigest(), "bytes": len(t.encode())} for name, t in minutes.items()}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
