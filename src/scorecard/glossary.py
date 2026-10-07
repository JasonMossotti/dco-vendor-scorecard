"""One glossary for every code, acronym, and record ID the site uses.

Two sources, never retyped:

* **Contract terms** (CSL-07, TR-1, NT-2, FA-5, DS-BADGE, ...) are read from the SLA and
  Interface Agreement YAML, so a popup quotes the contract. ``config/glossary.yaml`` only says
  which YAML lists hold codes and which fields to quote. A code two contracts define differently
  (TR-1 in each partner SLA) keeps one sense per contract; identical senses are merged.
* **Everything else** (acronyms, record and equipment ID formats, product names) is written by
  hand in ``config/glossary.yaml``. A family such as ``INC\\d{7}`` explains a format once instead
  of listing every ticket.

``Matcher`` finds codes in text with one regular expression that the browser popups reuse, and
``tokens()`` finds every code-like token, so the tests can prove each one the site shows is
explained or deliberately left plain.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import agreements
from .sla_model import load_interface_agreement, load_sla

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "glossary.yaml"
CONTRACT_FILES = {"interface": None, "it": "sla/it_partner.yaml", "landlord": "sla/ot_partner.yaml"}
DIRECTION = {"higher_is_better": "at least", "lower_is_better": "at most"}

# A code-like token: hyphenated capitals and digits (CSL-07, BW-A-R1-PG-A2-A), capitals with digits
# (INC3100816, P1, GB200), or a capitalised acronym of two or more letters (CDU, XID).
# Underscores join words in controlled codes (IN_PROGRESS, CUST_HOLD). A plural "s" may follow (CDUs).
_EDGE_L, _EDGE_R = r"(?<![A-Za-z0-9_-])", r"(?=s?(?![A-Za-z0-9_-]))"
TOKEN = re.compile(_EDGE_L + r"(?:[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)+|[A-Z]+[0-9][A-Z0-9_]*|[A-Z][A-Z0-9_]*[A-Z][A-Z0-9_]*)" + _EDGE_R)
# Device names TOKEN cannot see: host-style names in lower case (leaf-a07-r1 port 18, a13-ct18, a15-nvsw3),
# Redfish names (A06_PowerShelf_1), and a rack written with its word (Rack A07; a bare A07 stays plain).
DEVICE_NAME = re.compile(r"(?<![A-Za-z0-9_-])(?:leaf-[a-c]\d{2}-r\d(?: port \d{1,3}|:swp\d{1,3})?|[a-c]\d{2}-(?:ct\d{2}|nvsw\d)"
                         r"|[A-C]\d{2}_PowerShelf_\d|[Rr]ack [A-C]\d{2})(?![A-Za-z0-9_-])")


@dataclass
class Sense:
    title: str
    text: str
    docs: list[str] = field(default_factory=list)   # contract keys that define it this way

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "text": self.text, "docs": list(self.docs)}


@dataclass
class Entry:
    term: str                 # the code as written, or a family's label ("INC + 7 digits")
    type: str
    senses: list[Sense]
    key: str = ""             # anchor on the Glossary page
    expansion: str = ""       # acronyms: what the letters stand for
    pattern: str = ""         # families: the regular expression for one ID
    example: str = ""
    on: list[str] = field(default_factory=list)   # pages where this meaning applies (empty: everywhere)
    link: bool = True         # underline it on the pages (everyday acronyms are listed but not underlined)
    code_only: bool = False   # underline only inside code formatting (ticket states such as NEW)
    see: str = ""             # a page that holds these records

    @property
    def title(self) -> str:
        return self.expansion or self.senses[0].title

    def as_dict(self) -> dict[str, Any]:
        d = {"key": self.key, "term": self.term, "type": self.type, "title": self.title,
             "senses": [s.as_dict() for s in self.senses]}
        for k in ("expansion", "pattern", "example", "see", "on"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        if not self.link:
            d["link"] = False
        if self.code_only:
            d["code_only"] = True
        return d


def config(path: Path = CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _contracts(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    return {"interface": load_interface_agreement(root / "sla" / "interface_agreement.yaml"),
            "it": load_sla(root / CONTRACT_FILES["it"]),
            "landlord": load_sla(root / CONTRACT_FILES["landlord"])}


def _get(d: Any, path: str) -> list[dict[str, Any]]:
    for part in path.split("."):
        if not isinstance(d, dict) or part not in d:
            return []
        d = d[part]
    return d if isinstance(d, list) else [d]


def _num(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (int, float)):
        return f"{v:,}"
    return str(v)


def _fmt(template: str, item: dict[str, Any]) -> str:
    """Fill ``{field}`` from a contract item. Lists join with commas; a missing or empty field
    drops the sentence that holds it, so templates can name optional fields."""
    out = []
    for sentence in re.split(r"(?<=[.;])\s+", template.strip()):
        names = re.findall(r"\{(\w+)\}", sentence)
        vals = {}
        for n in names:
            v = item.get(n)
            if v in (None, "", []):
                break
            if n == "direction":
                v = DIRECTION.get(v, v)
            elif n == "unit":
                v = v if v == "%" else f" {v}"
            elif isinstance(v, list):
                v = ", ".join(_num(x) for x in v) if all(len(str(x)) < 30 for x in v) else " ".join(_num(x) for x in v)
            else:
                v = _num(v)
            vals[n] = v
        else:
            out.append(re.sub(r"\{(\w+)\}", lambda m: vals[m.group(1)], sentence))
    return " ".join(out)


def contract_entries(cfg: dict[str, Any] | None = None, root: Path = ROOT) -> dict[str, Entry]:
    cfg = cfg or config(root / "config" / "glossary.yaml")
    docs = _contracts(root)
    out: dict[str, Entry] = {}
    for spec in cfg["contract_terms"]:
        for key in agreements.DOC_KEYS:
            for item in _get(docs[key], spec["path"]):
                if "id_from" in spec:   # a defined term with its abbreviation in brackets: "Fault Detection Time (T0)"
                    m = re.search(r"\(([^)]*)\)", str(item.get(spec["id_from"], "")))
                    t = TOKEN.search(m.group(1)) if m else None
                    if not t:
                        continue
                    code, item = t.group(), {**item, spec["id_from"]: item[spec["id_from"]][:m.start()].strip()}
                else:
                    code = item.get(spec.get("id_field", "id"))
                if not isinstance(code, str) or not TOKEN.fullmatch(code):
                    continue
                title = _fmt(spec.get("title", "{name}"), item)
                text = _fmt(spec.get("text", ""), item)
                e = out.setdefault(code, Entry(code, spec["type"], [], code_only=spec.get("code_only", False)))
                same = next((s for s in e.senses if s.title == title and s.text == text), None)
                if same:
                    same.docs.append(key)
                else:
                    e.senses.append(Sense(title, text, [key]))
    return out


def hand_entries(cfg: dict[str, Any] | None = None) -> tuple[dict[str, Entry], list[Entry]]:
    """Hand-written terms (exact) and families (patterns) from config/glossary.yaml."""
    cfg = cfg or config()
    exact: dict[str, Entry] = {}
    for t in cfg.get("terms", []):
        exact[t["term"]] = Entry(t["term"], t["type"], [Sense(t.get("title", t.get("expansion", "")), t.get("text", ""))],
                                 expansion=t.get("expansion", ""), link=t.get("link", True), see=t.get("see", ""),
                                 code_only=t.get("code_only", False))
    fams = [Entry(f["label"], f["type"], [Sense(f["title"], f.get("text", ""))], key=f["key"], pattern=f["pattern"],
                  example=f.get("example", ""), link=f.get("link", True), see=f.get("see", ""), on=f.get("pages", []))
            for f in cfg.get("families", [])]
    return exact, fams


@dataclass
class Glossary:
    exact: dict[str, Entry]
    families: list[Entry]
    ignore: dict[str, str]                                   # exact token -> why it stays plain
    ignore_patterns: list[tuple[re.Pattern, str, list[str]]]  # pattern, why, pages (empty: everywhere)

    def lookup(self, token: str, page: str | None = None) -> list[Entry]:
        """Every meaning of ``token`` on ``page``: a page's own meaning first, then the site-wide one.
        A plural "s" is dropped when only the singular is known (CDUs)."""
        found = [f for f in self.families if page in f.on and re.fullmatch(f.pattern, token)]
        if token in self.exact:
            found.append(self.exact[token])
        else:
            fam = next((f for f in self.families if not f.on and re.fullmatch(f.pattern, token)), None)
            if fam:
                found.append(fam)
        if not found and token.endswith("s") and len(token) > 2:
            return self.lookup(token[:-1], page)
        return found

    def ignored(self, token: str, page: str | None = None) -> str | None:
        if token in self.ignore:
            return self.ignore[token]
        for rx, why, on in self.ignore_patterns:
            if (not on or page in on) and rx.fullmatch(token):
                return why
        return None

    def entries(self) -> list[Entry]:
        return sorted(list(self.exact.values()) + self.families, key=lambda e: (e.term.upper().lstrip("-"), e.type, e.key))

    def link_pattern(self, page: str | None = None, code_only: bool = False, keys: set[str] | None = None) -> str:
        """One regular expression for the codes to underline on ``page`` (Python and JavaScript read it the
        same way). ``keys`` limits it to those entries."""
        terms = sorted((t for t, e in self.exact.items() if e.link and e.code_only == code_only and (keys is None or e.key in keys)),
                       key=lambda t: (-len(t), t))
        alts = [re.escape(t).replace("\\-", "-") for t in terms]
        if not code_only:
            alts += [f"(?:{f.pattern})" for f in self.families
                     if f.link and (not f.on or page in f.on) and (keys is None or f.key in keys)]
        if not alts:
            return ""
        return _EDGE_L + "(?:" + "|".join(alts) + ")" + _EDGE_R


@lru_cache(maxsize=4)
def load(root: Path = ROOT) -> Glossary:
    cfg = config(root / "config" / "glossary.yaml")
    exact = contract_entries(cfg, root)
    hand, fams = hand_entries(cfg)
    clash = sorted(set(exact) & set(hand))
    if clash:
        raise ValueError(f"config/glossary.yaml repeats terms the contracts define: {clash}")
    exact.update(hand)
    for t, e in exact.items():
        e.key = e.key or t
    ign = cfg.get("plain", {})
    return Glossary(exact, fams,
                    {t: g["why"] for g in ign.get("words", []) for t in g["terms"]},
                    [(re.compile(p["pattern"]), p["why"], p.get("pages", [])) for p in ign.get("patterns", [])])


def tokens(text: str) -> Counter:
    return Counter(m.group() for rx in (TOKEN, DEVICE_NAME) for m in rx.finditer(text))


# --------------------------------------------------------------------------- #
# What the pages need: the popups' data and the Glossary tab's list
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=4)
def anchors(root: Path = ROOT) -> dict[str, dict[str, agreements.Definition]]:
    """Where each contract defines each glossary code: {doc: {code: Definition}}, limited to codes the
    glossary says that contract defines (a "T0 rule" table row in the Landlord SLA is not T0's definition)."""
    gl = load(root)
    out: dict[str, dict[str, agreements.Definition]] = {}
    for doc in agreements.DOC_KEYS:
        defs = agreements.definitions(agreements.read(doc, root))
        out[doc] = {c: d for c, d in defs.items() if c in gl.exact and any(doc in s.docs for s in gl.exact[c].senses)}
    return out


def doc_link(doc: str, code: str | None = None) -> str:
    """Link to a contract on the Agreements tab, from the site root."""
    return f"agreements/{agreements.DOC_SLUG[doc]}/" + (f"#{code}" if code else "")


def entry_data(e: Entry, root: Path = ROOT) -> dict[str, Any]:
    """An entry for the pages, with each sense's "defined in" links resolved to the Agreements tab."""
    d = e.as_dict()
    anc = anchors(root)
    for s, sd in zip(e.senses, d["senses"]):
        sd["where"] = [{"doc": agreements.DOC_TITLE[doc], "section": anc[doc][e.term].section, "href": doc_link(doc, e.term)}
                       for doc in s.docs if e.term in anc.get(doc, {})]
    return d


def keys_in(text: str, page: str | None = None, root: Path = ROOT) -> set[str]:
    """The entries the codes in ``text`` resolve to on ``page``."""
    gl = load(root)
    return {e.key for tok in tokens(text) for e in gl.lookup(tok, page)}


def popup_data(page: str, text: str | None = None, root: Path = ROOT) -> dict[str, Any]:
    """The data the popup script needs on one page: the two link patterns, the lookup tables, and
    the entries. With ``text`` (the finished page), only the entries its codes need."""
    gl = load(root)
    used = keys_in(text, page, root) if text is not None else None
    dev, dev_kinds = device_data(text, root) if text is not None else ({}, {})
    if used is not None and dev:     # a card's connections are codes too: their meanings come along
        used |= keys_in(" ".join(dev), page, root)
    entries = [e for e in gl.entries() if used is None or e.key in used]
    idx = {e.key: i for i, e in enumerate(entries)}
    cfg = config(root / "config" / "glossary.yaml")
    return {
        "dev": dev, "dev_kinds": dev_kinds,
        "page": page,
        "re": gl.link_pattern(page, keys=used),
        "re_code": gl.link_pattern(page, code_only=True, keys=used),
        "exact": {t: idx[e.key] for t, e in gl.exact.items() if e.key in idx},
        "fam": [[f.pattern, idx[f.key], 1 if f.on else 0] for f in gl.families if f.key in idx and (not f.on or page in f.on)],
        "types": {t["key"]: t["label"] for t in cfg["types"]},
        "entries": [entry_data(e, root) for e in entries],
    }


def device_data(text: str, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, str]]:
    """The device directory entries a page needs (``scorecard.devices``): every device named in its text, and
    the devices their connections name, so a card's connections open their own cards."""
    from . import devices
    data = devices.load() if root == ROOT else json.loads((root / "docs" / "site" / "devices.json").read_text(encoding="utf-8"))
    names = {t for t in tokens(text) if devices.lookup(data, t) is not None}
    return devices.subset(data, names), data["kinds"]
