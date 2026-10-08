"""The Unified Site Management tab bar, shared by every page of the demo.

One definition of the tabs and their look, injected into the hub, the app's wrapper,
and each static page (``__SITENAV_CSS__`` and ``__SITENAV__`` in the templates), so
the pages read as one product. Links are relative, so the site works under any base path.

``inject`` also adds the code popups (``templates/partials/glossary_popup.html``) to every
static page: each code, acronym, and record ID opens a small card with its meaning.
The Scorecards app gets none, because Streamlit owns that page's markup.

Pages that mark fields with ``data-loc`` also get the location pins
(``templates/partials/location_popup.html``): a pin beside the field opens the site
drawing with that rack, room, or piece of equipment outlined.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REPO = "https://github.com/JasonMossotti/dco-vendor-scorecard"

# (key, label, path from the site root); the reference tabs sit on the right of the bar
TABS = [
    ("overview", "Overview", ""),
    ("scorecards", "Scorecards", "app/"),
    ("alarms", "Alarm Board", "alarms/"),
    ("tickets", "Incident Portal", "tickets/"),
    ("pir", "Post-Incident Review", "pir/"),
    ("weekly", "Weekly Review", "weekly/"),
    ("patterns", "Failure Patterns", "patterns/"),
    ("energy", "Energy", "energy/"),
    ("gpu", "GPU Health", "gpu/"),
    ("deployments", "Deployments", "deployments/"),
]
REFERENCE_TABS = [
    ("agreements", "Agreements", "agreements/"),
    ("glossary", "Glossary", "glossary/"),
    ("devices", "Devices", "devices/"),
]
KEYS = [k for k, _, _ in TABS + REFERENCE_TABS]

CSS = """
.usm { background:#1e2933; color:#fff; font:14px/1.4 "Inter","Segoe UI",Helvetica,Arial,sans-serif; }
.usm-in { display:flex; flex-wrap:wrap; align-items:center; gap:4px 14px; padding:0 20px; }
.usm-brand { display:flex; align-items:baseline; gap:10px; padding:10px 0; color:#fff; text-decoration:none; white-space:nowrap; }
.usm-brand b { font-size:16px; font-weight:700; letter-spacing:.01em; }
.usm-brand span { font-size:12px; color:#aab6c3; }
.usm-tabs { display:flex; flex-wrap:wrap; gap:2px; flex:1; }
.usm-ref { flex:none; }
.usm-tabs a { color:#cdd6df; text-decoration:none; padding:12px 10px 10px; border-bottom:3px solid transparent; white-space:nowrap; }
.usm-tabs a:hover { color:#fff; background:rgba(255,255,255,.06); }
.usm-tabs a.on { color:#fff; font-weight:600; border-bottom-color:#5b9cff; }
.usm-src { color:#aab6c3; font-size:12px; text-decoration:none; white-space:nowrap; }
.usm-src:hover { color:#fff; }
@media (max-width:1700px) { .usm-brand span { display:none; } }
@media (max-width:1640px) { .usm-src { display:none; } .usm-tabs a { padding:12px 7px 10px; } .usm-in { gap:4px 10px; } }
@media (max-width:1480px) { .usm-tabs a { padding:12px 5px 10px; font-size:13px; } .usm-brand b { font-size:15px; } }
@media (max-width:1300px) { .usm-tabs a { padding:12px 4px 10px; font-size:12.5px; } .usm-tabs { gap:0; } }
@media (max-width:700px) { .usm-in { padding:0 10px; gap:0 12px; } .usm-tabs a { padding:8px 8px 6px; font-size:13px; } .usm-src { display:none; } }
@media print { .usm { display:none !important; } }
"""


def nav_html(active: str, prefix: str = "../") -> str:
    """The tab bar with ``active`` marked; ``prefix`` leads from this page back to the site root."""
    if active not in KEYS:
        raise ValueError(f"unknown tab {active!r}")
    root = prefix or "./"
    on = ' class="on" aria-current="page"'
    links = lambda tabs: "".join(
        f'<a href="{escape(prefix + path if path else root)}" data-tab="{key}"{on if key == active else ""}>{escape(label)}</a>'
        for key, label, path in tabs)
    return (f'<nav class="usm" aria-label="Site"><div class="usm-in">'
            f'<a class="usm-brand" href="{escape(root)}"><b>Unified Site Management</b><span>Site AUS-1 · fictional</span></a>'
            f'<div class="usm-tabs">{links(TABS)}</div>'
            f'<div class="usm-tabs usm-ref">{links(REFERENCE_TABS)}</div>'
            f'<a class="usm-src" href="{REPO}">Source on GitHub</a></div></nav>')


_POPUP_MARK = re.compile(r"<!--GLOSSARY_POPUPS (\{.*?\})-->")
_SKIP_DATA = re.compile(r'<script type="application/json" data-gl-skip[^>]*>.*?</script>', re.S)


def inject(template: str, active: str, prefix: str = "../", page: str | None = None, doc_title: str = "") -> str:
    """Fill a page template's tab bar placeholders and mark where the code popups go (before ``</body>``).
    ``page`` names the page for page-specific meanings (default: the active tab). Call ``finish`` on the
    filled page to add the popups with just the entries its codes need."""
    if "__SITENAV__" not in template or "__SITENAV_CSS__" not in template:
        raise ValueError("template is missing the site tab bar placeholders")
    out = template.replace("__SITENAV_CSS__", CSS.strip()).replace("__SITENAV__", nav_html(active, prefix))
    if "</body>" not in out:
        raise ValueError("template has no </body> for the code popups")
    i = out.rindex("</body>")
    mark = json.dumps({"page": page or active, "root": prefix, "doc_title": doc_title}, sort_keys=True)
    return out[:i] + f"<!--GLOSSARY_POPUPS {mark}-->\n" + out[i:]


def finish(html: str) -> str:
    """Add the code popups to a finished page: their style, the data for the codes on this page, and the script."""
    from . import glossary
    m = _POPUP_MARK.search(html)
    if not m:
        raise ValueError("page has no code popup mark; build it with sitenav.inject")
    opts = json.loads(m.group(1))
    # A page's own copy of a whole data set (the Devices page's directory) is not text it shows.
    page_text = _SKIP_DATA.sub(" ", html[:m.start()] + html[m.end():])
    data = glossary.popup_data(opts["page"], text=page_text)
    data.update(root=opts["root"], doc_title=opts["doc_title"])
    # Record numbers the Incident Portal holds link to it (tickets/#INC3100017); others stay plain.
    from . import tickets
    data.update(tk=sorted(set(tickets.ID_RE.findall(page_text)) & set(tickets.ids())), tk_re=tickets.ID_PATTERN)
    tpl = (ROOT / "templates" / "partials" / "glossary_popup.html").read_text(encoding="utf-8")
    pop = tpl.replace("__GLOSSARY__", json.dumps(data, sort_keys=True, separators=(",", ":")).replace("</", "<\\/"))
    if "data-loc" in page_text:
        pop += location_popups(page_text, opts["root"], every="data-loc-all" in page_text)
    return html[:m.start()] + pop + html[m.end():]


def location_popups(page_text: str, root: str, every: bool = False) -> str:
    """The location pins' style, script, and the locations this page's text names (see ``scorecard.locations``).
    Pages opt in field by field with ``data-loc``; prose never gets a pin. ``every``: all of them (the Devices page)."""
    from . import locations
    data = dict(locations.load()) if every else locations.subset(locations.load(), page_text)
    data.update(root=root, kinds=locations.KIND_LABEL)
    tpl = (ROOT / "templates" / "partials" / "location_popup.html").read_text(encoding="utf-8")
    return tpl.replace("__LOCATIONS__", json.dumps(data, sort_keys=True, separators=(",", ":")).replace("</", "<\\/"))
