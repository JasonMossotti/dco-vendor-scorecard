#!/usr/bin/env python3
"""Render the glossary: the Glossary tab, the code popups every page shares, and docs/glossary/GLOSSARY.md.

The glossary itself lives in src/scorecard/glossary.py (contract codes read from the SLA YAML, the
rest from config/glossary.yaml). This script scans every page and document for code-like tokens,
records where each entry is used, and fails ``--check`` when a token is neither explained nor listed
as plain text on purpose.

Usage:
    python scripts/render_glossary.py            # write docs/glossary/GLOSSARY.md
    python scripts/render_glossary.py --check    # fail if it is stale or a code is unexplained (CI)
    python scripts/render_glossary.py --html OUT.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from html import escape, unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from scorecard import agreements, sitenav  # noqa: E402
from scorecard import glossary as G  # noqa: E402

OUT = ROOT / "docs" / "glossary" / "GLOSSARY.md"

# Where a document's text appears on the site (label, link from the site root).
PLACES = {
    "docs/sla/INTERFACE_AGREEMENT.md": ("Interface Agreement", "agreements/interface-agreement/"),
    "docs/sla/IT_PARTNER_SLA.md": ("IT Partner SLA", "agreements/it-partner-sla/"),
    "docs/sla/LANDLORD_SLA.md": ("Landlord SLA", "agreements/landlord-sla/"),
    "reports/scorecard.md": ("Scorecards", "app/"),
    "reports/discrepancy_report.md": ("Scorecards", "app/"),
    "reports/landlord_scorecard.md": ("Scorecards", "app/"),
    "reports/landlord_discrepancy_report.md": ("Scorecards", "app/"),
    "reports/attribution_report.md": ("Scorecards", "app/"),
    "reports/site_summary.md": ("Scorecards", "app/"),
    "reports/change_alarms.md": ("Alarm Board", "alarms/"),
    "reports/failure_patterns.md": ("Failure Patterns", "patterns/"),
    "docs/site/SITE.md": ("Site model document", ""),
}
PAGES = [("hub", "Overview", ""), ("alarms", "Alarm Board", "alarms/"), ("tickets", "Incident Portal", "tickets/"),
         ("pir", "Post-Incident Review", "pir/"), ("weekly", "Weekly Review", "weekly/"), ("patterns", "Failure Patterns", "patterns/")]


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def _no_interpolation(s: str) -> str:
    """Drop ``${...}`` (with nested braces) from a template literal, keeping its prose."""
    out, depth, i = [], 0, 0
    while i < len(s):
        if s.startswith("${", i):
            depth += 1
            i += 2
            continue
        if depth and s[i] == "{":
            depth += 1
        elif depth and s[i] == "}":
            depth -= 1
            if not depth:
                out.append(" ")
        elif not depth:
            out.append(s[i])
        i += 1
    return "".join(out)


def page_text(html: str) -> str:
    """What a page can show: its embedded data, the text in its markup, and the string literals its script writes."""
    out = []
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    if m:
        out += list(_strings(json.loads(m.group(1).replace("<\\/", "</"))))
    for js in re.findall(r"<script>(.*?)</script[^>]*>", html, re.S | re.I):
        for lit in re.findall(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', js):
            s = re.sub(r"<[^>]+>", " ", _no_interpolation(lit[0] or lit[1]))
            if " " in s.strip():   # prose, not an identifier, selector, or tag name
                out.append(s)
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    body = re.sub(r"<nav class=\"usm\".*?</nav>", " ", body, flags=re.S)
    out.append(unescape(re.sub(r"<[^>]+>", " ", body)))
    return "\n".join(out)


def corpus() -> dict[str, tuple[str, str, str]]:
    """source -> (label, link, text) for every page and document the site shows."""
    import render_alarms
    import render_hub
    import render_patterns
    import render_pir
    import render_tickets
    import render_weekly
    mods = {"hub": render_hub, "alarms": render_alarms, "tickets": render_tickets, "pir": render_pir, "weekly": render_weekly,
            "patterns": render_patterns}
    out = {}
    for rel, (label, link) in PLACES.items():
        out[rel] = (label, link, (ROOT / rel).read_text(encoding="utf-8"))
    for d, label, link in (("docs/pir", "Post-Incident Review", "pir/"), ("docs/weekly", "Weekly Review", "weekly/")):
        for p in sorted((ROOT / d).glob("*.md")):
            out[p.relative_to(ROOT).as_posix()] = (label, link, p.read_text(encoding="utf-8"))
    for key, label, link in PAGES:
        out[f"page:{key}"] = (label, link, page_text(mods[key].html_page()))
    return out


def page_key(src: str) -> str:
    """The tab a source's text appears on, for page-specific meanings."""
    if src.startswith("page:"):
        return {"hub": "overview"}.get(src[5:], src[5:])
    if src.startswith("docs/sla/"):
        return "agreements"
    if src.startswith("docs/site/"):
        return "site"
    return {"Alarm Board": "alarms", "Failure Patterns": "patterns", "Post-Incident Review": "pir",
            "Weekly Review": "weekly", "Scorecards": "scorecards"}[PLACES[src][0] if src in PLACES else
                                                                  ("Post-Incident Review" if "/pir/" in src else "Weekly Review")]


def scan(gl: G.Glossary | None = None, texts: dict | None = None) -> dict:
    """Every token on the site: which entry explains it, where it is used, and what is unexplained."""
    gl = gl or G.load()
    texts = texts if texts is not None else corpus()
    used: dict[str, set[tuple[str, str]]] = defaultdict(set)
    unexplained: dict[str, set[str]] = defaultdict(set)
    plain: dict[str, set[str]] = defaultdict(set)
    for src, (label, link, text) in texts.items():
        page = page_key(src)
        for tok in G.tokens(text):
            found = gl.lookup(tok, page)
            for e in found:
                used[e.key].add((label, link))
            if found:
                continue
            if gl.ignored(tok, page):
                plain[tok].add(src)
            else:
                unexplained[tok].add(src)
    return {"used": used, "unexplained": unexplained, "plain": plain}


def published(gl: G.Glossary, used: dict) -> list[G.Entry]:
    """The entries the Glossary tab lists: every one the site uses (contract codes no page shows are left out),
    and every GPU XID code in the catalog addendum, used or not. XID codes sort by number (XID 8 before XID 13)."""
    items = [e for e in gl.entries() if e.key in used or e.type == "xid"]
    return sorted(items, key=lambda e: f"XID {int(e.term.split()[1]):03d}" if e.type == "xid" else e.term.upper().lstrip("-"))


def xid_source_html() -> str:
    src = G.xid_catalog()["source"]
    return f'<a href="{escape(src["url"])}" target="_blank" rel="noopener">Xid catalog</a> (updated {escape(src["updated"])}, retrieved {escape(src["retrieved"])})'


def _type_labels() -> dict[str, str]:
    return {t["key"]: t["label"] for t in G.config()["types"]}


def _letter(e: G.Entry) -> str:
    c = next((ch for ch in e.term.upper() if ch.isalnum()), "#")
    return c if c.isalpha() else "#"


def _places(used: set[tuple[str, str]]) -> list[tuple[str, str]]:
    order = [label for label, _ in PLACES.values()] + [p[1] for p in PAGES]
    best: dict[str, str] = {}
    for label, link in used:
        best[label] = best.get(label) or link
    return sorted(best.items(), key=lambda x: (order.index(x[0]) if x[0] in order else 99, x[0]))


def entry_html(e: G.Entry, used: set[tuple[str, str]], labels: dict[str, str], prefix: str = "../") -> str:
    d = G.entry_data(e)
    parts = []
    if e.expansion:
        parts.append(f'<div class="title">{escape(e.expansion)}</div>')
    for s in d["senses"]:
        h = '<div class="sense">'
        if s["title"] and s["title"] != e.expansion:
            h += f'<div class="title">{escape(s["title"])}</div>'
        if s["text"]:
            h += f'<p>{escape(s["text"])}</p>'
        if s["where"]:
            h += '<div class="meta">Defined in ' + "; ".join(
                f'{escape(w["doc"])}, <a href="{escape(prefix + w["href"])}">{escape(w["section"])}</a>' for w in s["where"]) + "</div>"
        parts.append(h + "</div>")
    if e.pattern:
        parts.append(f'<div class="meta">Format: {escape(e.term)}' + (f", for example {escape(e.example)}" if e.example else "") + "</div>")
    if e.on:
        pages = [label for key, label, _ in sitenav.TABS + sitenav.REFERENCE_TABS if key in e.on] + (["site model"] if "site" in e.on else [])
        parts.append(f'<div class="scope">This meaning applies on: {escape(", ".join(pages))}</div>')
    if e.see:
        parts.append(f'<div class="meta">Records: <a href="{escape(prefix + e.see)}">open the page that holds them</a></div>')
    if e.source:
        parts.append(f'<div class="meta">Source: <a href="{escape(e.source["href"])}" target="_blank" rel="noopener">{escape(e.source["label"])}</a></div>')
    where = ", ".join(f'<a href="{escape(prefix + link)}">{escape(label)}</a>' if link else escape(label) for label, link in _places(used))
    parts.append(f'<div class="meta">Used on: {where}</div>' if where else '<div class="meta">Not seen in this site\'s records.</div>')
    search = " ".join([e.term, e.expansion, e.example] + [s.title + " " + s.text for s in e.senses]).lower()
    return (f'<div class="entry" id="{escape(e.key)}" data-type="{escape(e.type)}" data-letter="{_letter(e)}" data-search="{escape(search)}">'
            f'<div data-gl-skip><span class="term">{escape(e.term)}</span><span class="kind">{escape(labels.get(e.type, e.type))}</span></div>'
            f'<div>{"".join(parts)}</div></div>')


def html_page(s: dict | None = None) -> str:
    gl = G.load()
    s = s or scan(gl)
    labels = _type_labels()
    items = published(gl, s["used"])
    body = "".join(entry_html(e, s["used"][e.key], labels) for e in items)
    data = {"types": [t for t in G.config()["types"] if any(e.type == t["key"] for e in items)]}
    tpl = sitenav.inject((ROOT / "templates" / "glossary.html").read_text(encoding="utf-8"), "glossary")
    return sitenav.finish(tpl.replace("__XID_SOURCE__", xid_source_html()).replace("__ENTRIES__", body).replace("__DATA__", json.dumps(data, sort_keys=True).replace("</", "<\\/")))


def markdown(s: dict | None = None) -> str:
    gl = G.load()
    s = s or scan(gl)
    labels = _type_labels()
    items = published(gl, s["used"])
    cell = lambda t: t.replace("|", "/").replace("\n", " ")
    lines = ["<!--", "  GENERATED FILE. DO NOT EDIT BY HAND.",
             "  Source: config/glossary.yaml and the contract YAML in sla/  |  Generator: scripts/render_glossary.py",
             "  Edit the YAML and re-run: python scripts/render_glossary.py", "-->", "",
             "# Glossary: Site AUS-1", "",
             f"Every acronym, contract code, and record ID the site's pages and documents use: {len(items)} entries. "
             "Contract codes quote the contract that defines them. On the live site, each code on every page opens this "
             "meaning in a popup, and the Glossary tab lists them alphabetically and by type. Synthetic site; all names are fictional.", ""]
    for t in G.config()["types"]:
        group = [e for e in items if e.type == t["key"]]
        if not group:
            continue
        lines += [f"## {t['label']}", ""]
        if t["key"] == "xid":
            cat = G.xid_catalog()
            lines += [f"Every code NVIDIA's public [Xid catalog]({cat['source']['url']}) (updated {cat['source']['updated']}, "
                      f"retrieved {cat['source']['retrieved']}) marks as applying to GB200 and not unused: {len(group)} codes. "
                      "The name and the two recommended actions are NVIDIA's; the meaning is this project's plain reading, and the "
                      "catalog is the authority. The catalog also lists " + ", ".join(f"XID {n}" for n in cat["not_gb200"])
                      + ", which do not apply to GB200.", ""]
        lines += ["| Code | Meaning | Defined in | Used on |", "|---|---|---|---|"]
        for e in group:
            d = G.entry_data(e)
            meaning = "<br>".join(
                ("**" + cell(x["title"]) + ".** " if x["title"] and x["title"] != e.expansion else "") + cell(x["text"])
                for x in d["senses"])
            if e.expansion:
                meaning = f"**{cell(e.expansion)}.** " + meaning
            if e.on:
                meaning += f" *(On: {', '.join(e.on)}.)*"
            defined = "<br>".join(f'{w["doc"]}, {cell(w["section"])}' for x in d["senses"] for w in x["where"]) or "-"
            used = ", ".join(label for label, _ in _places(s["used"][e.key])) or "-"
            lines.append(f"| {cell(e.term)} | {meaning} | {defined} | {used} |")
        lines.append("")
    plain = sorted(s["plain"])
    lines += ["## Left plain on purpose", "",
              "Capitalised text that is not a code (banners, emphasis) and rack positions such as A07, which the site drawings explain: "
              + ", ".join(plain) + ".", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--html", metavar="OUT")
    args = ap.parse_args()
    s = scan()
    if s["unexplained"]:
        print("Codes no glossary entry explains (add them to config/glossary.yaml, or list them as plain):")
        for tok, srcs in sorted(s["unexplained"].items()):
            print(f"  {tok:24} {', '.join(sorted(srcs))[:100]}")
        return 1
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(html_page(s), encoding="utf-8", newline="\n")
        print(f"Wrote {args.html}")
        return 0
    text = markdown(s)
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date. Run: python scripts/render_glossary.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(published(G.load(), s['used']))} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
