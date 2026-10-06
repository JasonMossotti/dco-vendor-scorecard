#!/usr/bin/env python3
"""Render the Agreements tab: the Interface Agreement and both partner SLAs as readable pages.

The pages are rendered from the generated contracts in docs/sla/ (scripts/render_sla.py), so they
can never differ from them. Every code a contract defines gets an anchor where it is defined
(``agreements/it-partner-sla/#CSL-07``), which is where the code popups' "Defined in" links land.

Usage:
    python scripts/render_agreements.py --out DIR    # write DIR/index.html and one page per contract
                                                     # (scripts/build_site.py does this)
"""

from __future__ import annotations

import argparse
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scorecard import agreements as AG  # noqa: E402
from scorecard import glossary, sitenav  # noqa: E402
from scorecard.sla_model import load_interface_agreement, load_sla  # noqa: E402

TEMPLATE = ROOT / "templates" / "agreements.html"
ABOUT = {
    "interface": ("landing", "Joins the two partner contracts: where each party's equipment ends, who owns each component, "
                             "how an outage is attributed to exactly one party, handoffs, and change-aware alarm notification."),
    "it": ("it", "What the IT Partner owes for the data hall work: priorities, ticket and clock rules, service levels and "
                 "credits, return-to-service validation, staffing, safety, spares."),
    "landlord": ("landlord", "What the Landlord owes for the building, power, cooling, and CDUs: alarm priorities, work order "
                             "rules, service levels and credits against rent, maintenance, safety."),
}


def _doc_meta(key: str) -> dict:
    d = (load_interface_agreement(ROOT / "sla" / "interface_agreement.yaml") if key == "interface"
         else load_sla(ROOT / glossary.CONTRACT_FILES[key]))["document"]
    return d


def _doctabs(active: str | None, prefix: str) -> str:
    on = ' class="on" aria-current="page"'
    return "".join(f'<a href="{prefix}{slug}/"{on if key == active else ""}>{escape(title)}</a>'
                   for key, slug, title, _ in AG.DOCUMENTS)


def _page(title: str, body: str, active: str | None, prefix: str, toc: str = "", doc_title: str = "") -> str:
    tpl = sitenav.inject(TEMPLATE.read_text(encoding="utf-8"), "agreements", prefix=prefix, doc_title=doc_title)
    here = "" if active is None else "../"
    html = (tpl.replace("__TITLE__", escape(title)).replace("__DOCTABS__", _doctabs(active, here))
            .replace("__LAYOUT__", "" if toc else " single").replace("__TOC__", toc).replace("__BODY__", body))
    return sitenav.finish(html)


def doc_page(key: str) -> str:
    """One contract, with a contents rail and an anchor on every code it defines."""
    md = AG.read(key)
    anchors = {d.line: code for code, d in glossary.anchors()[key].items()}
    toc = ('<nav class="toc" aria-label="Contents"><b>Contents</b>'
           + "".join(f'<a href="#{escape(sid)}">{escape(t)}</a>' for t, sid in AG.sections(md)) + "</nav>")
    return _page(AG.DOC_TITLE[key], AG.to_html(md, anchors), key, "../../", toc, AG.DOC_TITLE[key])


def landing_page() -> str:
    cards = []
    for key, slug, title, _ in AG.DOCUMENTS:
        meta = _doc_meta(key)
        cls, about = ABOUT[key]
        cards.append(
            f'<section class="card {cls}"><h2><a href="{slug}/">{escape(title)}</a></h2>'
            f'<div class="meta">{escape(meta["id"])} · version {escape(str(meta["version"]))} · effective {escape(str(meta["effective_date"]))}</div>'
            f'<p><b>{escape(meta["title"])}</b></p><p class="meta">{escape(meta["subtitle"])}</p>'
            f'<p>{escape(about)}</p><div class="go"><a href="{slug}/">Read the {escape(title)}</a></div></section>')
    body = ('<h1>Agreements</h1><p class="sub">The three contracts behind Site AUS-1. Fictional and illustrative; '
            'generated from the same YAML the scorecards are scored against, so the text and the scoring always agree.</p>'
            f'<div class="cards">{"".join(cards)}</div>'
            '<div class="how">Every code in these contracts and on the other pages has a dotted underline: click it to see '
            'what it means and where it is defined. The <a href="../glossary/">Glossary</a> lists them all.</div>')
    return _page("Agreements", body, None, "../")


def write(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(landing_page(), encoding="utf-8", newline="\n")
    paths = [out / "index.html"]
    for key, slug, _, _ in AG.DOCUMENTS:
        (out / slug).mkdir(exist_ok=True)
        (out / slug / "index.html").write_text(doc_page(key), encoding="utf-8", newline="\n")
        paths.append(out / slug / "index.html")
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, metavar="DIR")
    args = ap.parse_args()
    for p in write(Path(args.out)):
        print(f"Wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
