"""Certification layer: every person's credentials and each partner's monthly credential report (data/certs/).
Own random stream ("<seed>:certs").

Reads, never writes, the month's dataset, the security layer, and the EHS layer (whose training records the register
reads beside these). ``config/certifications.yaml`` says what each role holds.

What the month holds:

- Every person's role credentials: one completion each, on file before the month and current through it, so their
  expiry dates fall naturally across the months after it (the renewal notices). Credentials that do not expire (EPA
  608, the Level III course, the MMPI) were earned years ago.
- GB300 authorization for every IT Partner person who worked a Hall B tray incident, and for a share of the others.
- Each partner's monthly credential report as of the month end, listing what it shows lapsed.
- Planted (the answer key): a shift lead working with no NCP-AII on file; a Landlord engineer on
  CDU work after the CDU training lapsed; a guard on armed posts after the SA requalification lapsed (the guard file
  still says current); a technician whose ESD training lapsed mid-month while the IT Partner's report says 100% current.
- Also in the answer key, as found: the EHS layer's planted NFPA 70E lapse, which the register reads.
"""

from __future__ import annotations

import csv
import json
import random
from datetime import timedelta
from pathlib import Path
from typing import Any

from scorecard import certifications as C
from scorecard import ehs as E
from scorecard.change_calendar import iso, parse

FRAMING = "Synthetic certification records and credential reports for a portfolio demonstration. All records are fictional."


def _dump(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


class CertsLayer:
    def __init__(self, sample_dir: str | Path, seed: int, security_dir: Path | None, ehs_dir: Path | None,
                 cfg: dict[str, Any] | None = None):
        self.cfg = cfg or C.config()
        self.ehs_cfg = E.config()
        self.site = C.load_site(sample_dir, security_dir)
        self.window = self.site.m.window
        self.ehs_dir = ehs_dir
        self.rng = random.Random(f"{seed}:certs")

    def _row(self, person: str, partner: str, role: str, cred: str) -> dict[str, Any]:
        rng, m, c = self.rng, self.site.m, self.cfg["credentials"][cred]
        g = self.cfg["generate"]
        hi = m.start - timedelta(days=g["issued_before_start_days"])
        if c["months"] is None:
            done = hi - timedelta(days=365 * rng.uniform(*g["never_expires_years"]))
            exp = ""
        else:
            lo = E.add_months(m.end + timedelta(days=5), -c["months"])
            done = lo + (hi - lo) * rng.random()
            exp = None
        done = done.replace(hour=14, minute=0, second=0, microsecond=0)
        return {"person": person, "partner": partner, "role": role, "credential": cred,
                "completed": iso(done), "expires": exp if exp is not None else iso(E.add_months(done, c["months"]))}

    def _lapse(self, row: dict[str, Any], at) -> None:
        row["expires"] = iso(at.replace(hour=14, minute=0, second=0, microsecond=0))
        row["completed"] = iso(E.add_months(parse(row["expires"]), -self.cfg["credentials"][row["credential"]]["months"]))

    def run(self) -> dict[str, Any]:
        cfg, rng, site, m = self.cfg, self.rng, self.site, self.site.m
        who = C.people(site)
        items = C.work(site, cfg, self.ehs_cfg)
        hall_b = {x["person"] for x in items if x["source"] == "incident" and "oem_gb300" in x["needs"]}
        rows: list[dict[str, Any]] = []
        for person, (partner, role) in sorted(who.items()):
            for cred in cfg["roles"].get(partner, {}).get(role, []):
                rows.append(self._row(person, partner, role, cred))
            if partner == "it" and (person in hall_b or rng.random() < cfg["generate"]["gb300_share"]):
                rows.append(self._row(person, partner, role, "oem_gb300"))
        ehs_key = json.loads((self.ehs_dir / "answer_key.json").read_text(encoding="utf-8")) \
            if self.ehs_dir and (self.ehs_dir / "answer_key.json").exists() else []
        key: list[dict[str, Any]] = [{"kind": "lapsed", "ref": k["ref"], "credential": k["course"], "source": "ehs"}
                                     for k in ehs_key if k["kind"] == "untrained"]
        taken = {k["ref"] for k in key}
        P = cfg["planted"]
        row_of = lambda p, c: next(r for r in rows if r["person"] == p and r["credential"] == c)
        mid_lo, mid_hi = m.start + timedelta(days=5), m.end - timedelta(days=7)

        # 1. a shift lead working with no NCP-AII on file (moved up to lead; the credential never recorded)
        if P.get("never_held"):
            cands = sorted({x["person"] for x in items if x["source"] == "it_shift" and x["role"] == "shift_lead"} - taken)
            if cands:
                p = rng.choice(cands)
                rows = [r for r in rows if not (r["person"] == p and r["credential"] == "ncp_aii")]
                key.append({"kind": "never_held", "ref": p, "credential": "ncp_aii", "source": "planted"})
                taken.add(p)
        # 2. Landlord work after the credential it needs lapsed (CDU work first)
        if P.get("lapsed_landlord"):
            jobs = [x for x in items if x["source"] in ("work_order", "pm") and x["person"] not in taken
                    and x["person"] in who and mid_lo <= parse(x["at"]) < mid_hi]
            cdu = [x for x in jobs if "chx2000" in x["needs"]]
            pool = cdu or jobs
            if pool:
                x = rng.choice(pool)
                cred = "chx2000" if cdu else next(c for c in x["needs"] if cfg["credentials"][c]["months"])
                at = parse(x["at"])
                self._lapse(row_of(x["person"], cred), at - timedelta(days=rng.uniform(0.5, 4)))
                key.append({"kind": "lapsed", "ref": x["person"], "credential": cred, "source": "planted"})
                taken.add(x["person"])
        # 3. a guard on armed posts after the SA requalification lapsed
        if P.get("lapsed_guard"):
            posts = [x for x in items if x["source"] == "post_shift" and x["person"] not in taken and mid_lo <= parse(x["at"]) < mid_hi]
            if posts:
                x = rng.choice(posts)
                self._lapse(row_of(x["person"], "firearm_sa"), parse(x["at"]) - timedelta(days=rng.uniform(0.5, 4)))
                key.append({"kind": "lapsed", "ref": x["person"], "credential": "firearm_sa", "source": "planted"})
                taken.add(x["person"])
        # 4. a technician's ESD training lapses mid-month; the IT Partner's report leaves it out
        hidden: set[str] = set()
        if P.get("lapsed_report"):
            shifts = [x for x in items if x["source"] == "it_shift" and x["person"] not in taken and x["role"] == "technician"
                      and mid_lo <= parse(x["at"]) < mid_hi]
            if shifts:
                x = rng.choice(shifts)
                self._lapse(row_of(x["person"], "esd"), parse(x["at"]) - timedelta(days=rng.uniform(0.5, 4)))
                key.append({"kind": "lapsed", "ref": x["person"], "credential": "esd", "source": "planted"})
                key.append({"kind": "report", "ref": "report:it", "credential": "", "source": "planted"})
                hidden.add(f"{x['person']}:esd")
                taken.add(x["person"])

        # Each partner's monthly report, as of the month end: what it shows lapsed (all of it, except what is hidden)
        reg = C.Register(rows=[dict(r, source="register") for r in rows] + (C.ehs_rows(self.ehs_dir) if self.ehs_dir else []),
                         reported=[], manifest={})
        as_of = m.end - timedelta(seconds=1)
        lapsed = C.lapsed_at(reg, who, cfg, self.ehs_cfg, as_of)
        reported = []
        for partner in C.PARTNERS:
            ppl = [p for p, (pt, _) in who.items() if pt == partner]
            if not ppl:
                continue
            req = sum(len(C.role_needs(cfg, self.ehs_cfg, partner, who[p][1])) for p in ppl)
            said = [x for x in lapsed.get(partner, []) if x not in hidden]
            reported.append({"partner": partner, "as_of": iso(as_of), "people": len(ppl), "required": req,
                             "current": req - len(said), "current_pct": f"{100 * (req - len(said)) / req:.1f}",
                             "lapsed": ";".join(said)})
        rows.sort(key=lambda r: (list(C.PARTNERS).index(r["partner"]), r["person"], r["credential"]))
        return {"credentials": rows, "reported": reported, "key": key}


def write_certs(layer: CertsLayer, out: dict[str, Any], dest: str | Path, source: str = "") -> dict[str, Any]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _dump(dest / "credentials.csv", out["credentials"], C.CRED_COLS)
    _dump(dest / "reported.csv", out["reported"], C.REPORT_COLS)
    (dest / "answer_key.json").write_text(json.dumps(out["key"], indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    man = {"disclaimer": FRAMING, "source": source, "window": layer.window,
           "files": {"credentials.csv": len(out["credentials"]), "reported.csv": len(out["reported"])}}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return man
