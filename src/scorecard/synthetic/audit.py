"""Quality audit layer: the Customer's sample draw, walk-down readings, and RMA cage scan for one month (data/audit/).
Own random stream ("<seed>:audit").

Reads, never writes, the month's dataset: its window, the IT Partner's tickets, the Landlord's work orders and PM
records, the BMC inventory, and the RMA ledger. The contract's audit clause (``sla/common.yaml``) sets the sample
size; ``config/audit.yaml`` the checklist and the planted defects.

What the month holds:

- The sample: drawn the morning after the month closes, from a published seed, 5% of each partner's closed
  records with a minimum of 10 (``scorecard.audit.draw``, the same function the checks use).
- The walk-down of each sampled record over the next four days: for every checklist item that applies, what the
  inspector read (a serial at the location, the cable label, a maintenance tag's date, a nameplate) or observed
  (pass or fail, with a note). What is read is what is physically there: a tracked part's serial is the one the
  BMC inventory shows now at that location, so a ticket whose swap the inventory never saw reads the old part.
- The RMA cage scan at the start of the walk-downs: every failed part removed this month that the ledger had not
  yet shipped.
- Planted (the answer key): a failed part the ledger shipped found on the cage shelf; a cable label naming the next
  tray; a wet-mate with no witness marks; a maintenance tag older than its PM record.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scorecard import audit as AU
from scorecard.audit import INSPECTOR, WALK_COLS, CAGE_COLS, iso, parse

FRAMING = "Synthetic quality audit sample, walk-down readings, and RMA cage scan for a portfolio demonstration. All records are fictional."

FAIL_NOTES = {
    "qd": "No witness marks on the supply and return quick-disconnects of the replaced part; fittings dry, drip tray clean.",
    "label": "Cable label at the replaced optic reads {reading}.",
    "pm_tag": "Maintenance tag on {asset} is dated {reading}.",
    "custody": "Found on the RMA cage shelf during the scan.",
}


class AuditLayer:
    def __init__(self, sample_dir: str | Path, seed: int, cfg: dict[str, Any] | None = None, rule: dict[str, Any] | None = None):
        self.dir = Path(sample_dir)
        self.cfg, self.rule = cfg or AU.config(), rule or AU.rule()
        self.m = AU.load_month(self.dir)
        self.window = self.m.window
        self.rng = random.Random(f"{seed}:audit")

    def run(self) -> dict[str, Any]:
        m, rng, cfg = self.m, self.rng, self.cfg
        close_day = m.end.replace(hour=0, minute=0, second=0)
        drawn_at = close_day + timedelta(hours=rng.uniform(*cfg["drawn_hours_after_close"]))
        seed = rng.randrange(100000, 1000000)
        pool = AU.pools(m)
        records = {p: AU.draw(pool[p], seed, p, self.rule) for p in AU.PARTNERS}
        idx = AU.record_index(m)

        # Walk-down slots: each sampled record on one of the next days, in working hours, in a shuffled order
        days = [close_day + timedelta(days=d) for d in range(cfg["walkdown_days"])]
        visits = [(p, rid) for p in AU.PARTNERS for rid in records[p]]
        rng.shuffle(visits)
        at: dict[str, datetime] = {}
        for k, (_, rid) in enumerate(visits):
            day = days[k * len(days) // len(visits)]
            lo, hi = cfg["walkdown_utc_hours"]
            at[rid] = (day + timedelta(hours=rng.uniform(lo, hi))).replace(microsecond=0)
        cage_at = (drawn_at + timedelta(minutes=10)).replace(second=0, microsecond=0)

        # The plan of planted defects: a sampled record each applies to, chosen before any reading is written
        shipped = {x["serial"]: parse(x["shipped_at"]) for x in m.rma if x["shipped_at"]}
        eligible = {
            "custody": [rid for rid in records["it"] if any(
                x["removed_serial"] and not AU.still_installed(x, m.inventory) and x["removed_serial"] in shipped
                and shipped[x["removed_serial"]] <= cage_at for x in idx[rid][2]["parts_used"])],
            "label": [rid for rid in records["it"] if any("optic" in x["part"] for x in idx[rid][2]["parts_used"])],
            "qd": [rid for rid in records["it"] if any(x["part"] in AU.WET for x in idx[rid][2]["parts_used"])],
            "pm_tag": [rid for rid in records["landlord"] if idx[rid][1] == "pm"],
        }
        planted: dict[tuple[str, str], dict[str, Any]] = {}
        key = []
        for kind, n in cfg["planted"].items():
            cands = sorted(set(eligible[kind]) - {r for (r, _) in planted})
            for rid in rng.sample(cands, min(n, len(cands))):
                planted[(rid, kind)] = {}
                key.append({"kind": kind, "record": rid})

        walk, cage = [], []
        for p, rid in sorted(visits, key=lambda v: at[v[1]]):
            partner, kind, rec = idx[rid]
            for n, item in enumerate(AU.items_for(partner, rec, kind, cfg)):
                row = {"record": rid, "partner": partner, "item": item, "result": "", "reading": "", "note": "",
                       "inspected_at": iso(at[rid] + timedelta(minutes=3 * n)), "inspector": INSPECTOR}
                bad = (rid, item) in planted
                if item == "serial":
                    x = next(x for x in rec["parts_used"] if x["part"] in AU.TRACKED and x["installed_serial"] and x["removed_serial"])
                    row["reading"] = AU.current_serial(x["removed_serial"], m.inventory)
                    row["note"] = f"Scanned the label of the {x['part']} at {x['location']}."
                elif item == "custody":
                    gone = [x["removed_serial"] for x in rec["parts_used"] if x["removed_serial"]]
                    row["reading"] = ", ".join(gone)
                    row["note"] = FAIL_NOTES["custody"] if bad else "Checked against the RMA ledger and the cage scan."
                    if bad:
                        planted[(rid, item)]["serial"] = gone[0]
                elif item == "label":
                    x = next(x for x in rec["parts_used"] if "optic" in x["part"])
                    host, label = AU.host_of(x["location"]), AU.link_label(rec, x["location"])
                    row["reading"] = label.replace(host, _neighbour(host)) if bad else label
                    row["note"] = FAIL_NOTES["label"].format(reading=row["reading"]) if bad else "Label at both ends of the cable names the link."
                elif item == "pm_tag":
                    done = parse(rec["completed_at"])
                    row["reading"] = iso(done - timedelta(days=rng.randint(27, 35)))[:10] if bad else rec["completed_at"][:10]
                    row["note"] = FAIL_NOTES["pm_tag"].format(asset=rec["asset"], reading=row["reading"]) if bad else "Tag present and dated."
                elif item == "nameplate":
                    row["reading"] = AU.wo_serial(rec)
                    row["note"] = "Read from the replaced part's nameplate."
                else:
                    row["result"] = "fail" if bad else "pass"
                    row["note"] = FAIL_NOTES[item] if bad else rng.choice(cfg["pass_notes"][item])
                walk.append(row)

        # The cage scan: every failed part removed this month that the ledger had not shipped by the scan, plus the planted one
        for t in m.tickets:
            for x in t["parts_used"]:
                s = x["removed_serial"]
                if not s or AU.still_installed(x, m.inventory):
                    continue
                if s not in shipped or shipped[s] > cage_at:
                    cage.append({"serial": s, "scanned_at": iso(cage_at), "shelf": f"RMA-{rng.randint(1, 6)}"})
        for (rid, item), extra in planted.items():
            if item == "custody":
                cage.append({"serial": extra["serial"], "scanned_at": iso(cage_at), "shelf": f"RMA-{rng.randint(1, 6)}"})
        cage.sort(key=lambda c: (c["shelf"], c["serial"]))
        return {"sample": {"seed": seed, "drawn_at": iso(drawn_at.replace(microsecond=0)), "drawn_by": INSPECTOR,
                           "rule": {"sample_pct": self.rule["sample_pct"], "min_records": self.rule["min_records"]},
                           "pools": {p: len(pool[p]) for p in AU.PARTNERS}, "records": records},
                "walkdown": walk, "cage": cage, "key": sorted(key, key=lambda k: (k["kind"], k["record"]))}


def _neighbour(host: str) -> str:
    """The next tray in the same rack ("a23-ct07" -> "a23-ct08"; the last tray reads the one before)."""
    rack, ct = host.split("-ct")
    n = int(ct)
    return f"{rack}-ct{n + 1 if n < 18 else n - 1:02d}"


def _dump(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_audit(layer: AuditLayer, out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, Any]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "sample.json").write_text(json.dumps(out["sample"], indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _dump(dest / "walkdown.csv", out["walkdown"], WALK_COLS)
    _dump(dest / "rma_cage_scan.csv", out["cage"], CAGE_COLS)
    (dest / "answer_key.json").write_text(json.dumps(out["key"], indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    man = {"disclaimer": FRAMING, "source": source, "window": layer.window,
           "files": {"sample.json": sum(len(v) for v in out["sample"]["records"].values()), "walkdown.csv": len(out["walkdown"]),
                     "rma_cage_scan.csv": len(out["cage"])}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
