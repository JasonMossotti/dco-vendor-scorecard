"""The site's three contracts as readable web pages, and where each code is defined in them.

The contracts are generated as Markdown (``scripts/render_sla.py``). This module turns that
Markdown into HTML for the Agreements tab with a small renderer for exactly the subset the
generator writes (headings, paragraphs, tables, lists, block quotes, rules, bold, italics,
code, links, ``<br>``), so the site needs no extra dependency and every line keeps its place.

``definitions()`` finds the line where a contract defines each code (a heading such as
``### CSL-07: ...``, a table row whose first cell is the code, or a list item ``- **CF-1:**``).
The Agreements page puts an anchor there, and the glossary uses the same function for the
"defined in" link, so a popup always lands on the clause it quotes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# key, page slug, short title, generated Markdown file
DOCUMENTS = [
    ("interface", "interface-agreement", "Interface Agreement", "docs/sla/INTERFACE_AGREEMENT.md"),
    ("it", "it-partner-sla", "IT Partner SLA", "docs/sla/IT_PARTNER_SLA.md"),
    ("landlord", "landlord-sla", "Landlord SLA", "docs/sla/LANDLORD_SLA.md"),
]
DOC_KEYS = [d[0] for d in DOCUMENTS]
DOC_SLUG = {d[0]: d[1] for d in DOCUMENTS}
DOC_TITLE = {d[0]: d[2] for d in DOCUMENTS}

CODE_TOKEN = r"[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)*"
_HEADING_DEF = re.compile(rf"^(#{{2,4}}) ({CODE_TOKEN}):")
_ROW_DEF = re.compile(rf"^\| *(?:\*\*|`)?({CODE_TOKEN})(?:\*\*|`)?(?: [^|]*)? *\|")
_ITEM_DEF = re.compile(rf"^- \*\*({CODE_TOKEN}):\*\*")
_TERM_DEF = re.compile(rf"^\| \*\*[^|*]*\((?:[A-Z][a-z]+ )?({CODE_TOKEN})\)\*\* \|")   # | **Fault Detection Time (T0)** |


def read(key: str, root: Path = ROOT) -> str:
    return (root / dict((d[0], d[3]) for d in DOCUMENTS)[key]).read_text(encoding="utf-8")


def slug(text: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens (the documents' own contents links use it)."""
    t = re.sub(r"<[^>]+>", "", text).lower()
    t = re.sub(r"[^\w\- ]", "", t)
    return t.replace(" ", "-")


def _plain(md: str) -> str:
    return re.sub(r"\*\*|`|\*", "", re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)).strip()


@dataclass(frozen=True)
class Definition:
    line: int          # 0-based line in the Markdown
    section: str       # the enclosing "## " heading, as written
    section_id: str


def definitions(md: str) -> dict[str, Definition]:
    """Where each code is defined. A heading wins over a table row, which wins over a list item or a
    defined term's abbreviation; the first of each kind counts (a summary table can precede the full clause)."""
    found: dict[str, tuple[int, Definition]] = {}
    section, section_id = "", ""
    fence = False
    for i, line in enumerate(md.split("\n")):
        if line.startswith("<!--"):
            fence = True
        if fence:
            fence = "-->" not in line
            continue
        if line.startswith("## "):
            section = _plain(line[3:])
            section_id = slug(section)
        for rank, rx in ((0, _HEADING_DEF), (1, _ROW_DEF), (1, _TERM_DEF), (2, _ITEM_DEF)):
            m = rx.match(line)
            if not m:
                continue
            code = m.group(2) if rx is _HEADING_DEF else m.group(1)
            if not re.fullmatch(CODE_TOKEN, code) or len(code) < 2:
                continue
            if code not in found or rank < found[code][0]:
                found[code] = (rank, Definition(i, section, section_id))
            break
    return {c: d for c, (_, d) in found.items()}


# --------------------------------------------------------------------------- #
# Markdown subset -> HTML
# --------------------------------------------------------------------------- #
def inline(md: str) -> str:
    """Bold, italics, code, internal links and <br> on already-safe text."""
    parts = re.split(r"(`[^`]*`)", md)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(f"<code>{escape(p[1:-1])}</code>")
            continue
        t = escape(p, quote=False).replace("&lt;br&gt;", "<br>")
        t = re.sub(r"\[([^\]]+)\]\((#[^)\s]*)\)", lambda m: f'<a href="{escape(m.group(2))}">{m.group(1)}</a>', t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
        out.append(t)
    return "".join(out)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def to_html(md: str, anchors: dict[int, str] | None = None) -> str:
    """Render the generator's Markdown. ``anchors`` maps a line number to an element id
    (the line where a code is defined); the element there gets that id and ``data-gl-def``."""
    anchors = anchors or {}
    lines = md.split("\n")
    out: list[str] = []
    i = 0

    def attr(n: int) -> str:
        return f' id="{escape(anchors[n])}" data-gl-def="{escape(anchors[n])}"' if n in anchors else ""

    while i < len(lines):
        line = lines[i]
        if line.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,4}) (.*)$", line)
        if m:
            level, text = len(m.group(1)), m.group(2)
            if i in anchors:   # the code's anchor, plus the heading's own anchor for the contents links
                out.append(f'<h{level}{attr(i)}><span id="{escape(slug(text))}"></span>{inline(text)}</h{level}>')
            else:
                out.append(f'<h{level} id="{escape(slug(text))}">{inline(text)}</h{level}>')
            i += 1
            continue
        if line.strip() == "---":
            out.append("<hr>")
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(i)
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", lines[r].strip())]
            h = "".join(f"<th>{inline(c)}</th>" for c in _cells(lines[head]))
            b = "".join(f"<tr{attr(r)}>" + "".join(f"<td>{inline(c)}</td>" for c in _cells(lines[r])) + "</tr>" for r in body)
            out.append(f'<div class="wide"><table><thead><tr{attr(head)}>{h}</tr></thead><tbody>{b}</tbody></table></div>')
            continue
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(buf))}</p></blockquote>")
            continue
        if re.match(r"^(\s*)([-*]|\d+\.) ", line):
            out.append(_list(lines, i, attr))
            while i < len(lines) and re.match(r"^(\s*)([-*]|\d+\.) ", lines[i]):
                i += 1
            continue
        buf = [i]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||>|---$|\s*([-*]|\d+\.) )", lines[i]):
            buf.append(i)
            i += 1
        text = " ".join(lines[n].strip() for n in buf)
        out.append(f"<p{attr(buf[0])}>{inline(text)}</p>")
    return "\n".join(out)


def _list(lines: list[str], start: int, attr) -> str:
    """A (possibly nested) list starting at ``start``; indentation of two or more spaces nests."""
    items: list[tuple[int, str, str, int]] = []   # indent, kind, text, line
    i = start
    while i < len(lines):
        m = re.match(r"^(\s*)([-*]|\d+\.) (.*)$", lines[i])
        if not m:
            break
        items.append((len(m.group(1)), "ol" if m.group(2)[0].isdigit() else "ul", m.group(3), i))
        i += 1
    html: list[str] = []
    stack: list[tuple[int, str]] = []
    for indent, kind, text, n in items:
        while stack and indent < stack[-1][0]:
            html.append(f"</li></{stack.pop()[1]}>")
        if not stack or indent > stack[-1][0]:
            html.append(f"<{kind}>")
            stack.append((indent, kind))
        else:
            html.append("</li>")
        box = re.match(r"^\[( |x)\] (.*)$", text)
        if box:
            text = ("☑ " if box.group(1) == "x" else "☐ ") + box.group(2)
        html.append(f"<li{attr(n)}>{inline(text)}")
    while stack:
        html.append(f"</li></{stack.pop()[1]}>")
    return "".join(html)


def sections(md: str) -> list[tuple[str, str]]:
    """The document's "## " headings (title, id) for the contents rail."""
    out, fence = [], False
    for line in md.split("\n"):
        if line.startswith("<!--"):
            fence = True
        if fence:
            fence = "-->" not in line
            continue
        if line.startswith("## ") and _plain(line[3:]) != "Contents":
            out.append((_plain(line[3:]), slug(line[3:])))
    return out


def title(md: str) -> str:
    m = re.search(r"^# (.+)$", md, re.M)
    return _plain(m.group(1)) if m else ""
