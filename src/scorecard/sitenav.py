"""The Unified Site Management tab bar, shared by every page of the demo.

One definition of the tabs and their look, injected into the hub, the app's wrapper,
and each static page (``__SITENAV_CSS__`` and ``__SITENAV__`` in the templates), so
the pages read as one product. Links are relative, so the site works under any base path.
"""

from __future__ import annotations

from html import escape

REPO = "https://github.com/JasonMossotti/dco-vendor-scorecard"

# (key, label, path from the site root)
TABS = [
    ("overview", "Overview", ""),
    ("scorecards", "Scorecards", "app/"),
    ("alarms", "Alarm Board", "alarms/"),
    ("pir", "Post-Incident Review", "pir/"),
    ("weekly", "Weekly Review", "weekly/"),
    ("patterns", "Failure Patterns", "patterns/"),
]
KEYS = [k for k, _, _ in TABS]

CSS = """
.usm { background:#1e2933; color:#fff; font:14px/1.4 "Inter","Segoe UI",Helvetica,Arial,sans-serif; }
.usm-in { display:flex; flex-wrap:wrap; align-items:center; gap:4px 22px; padding:0 20px; }
.usm-brand { display:flex; align-items:baseline; gap:10px; padding:10px 0; color:#fff; text-decoration:none; white-space:nowrap; }
.usm-brand b { font-size:16px; font-weight:700; letter-spacing:.01em; }
.usm-brand span { font-size:12px; color:#aab6c3; }
.usm-tabs { display:flex; flex-wrap:wrap; gap:2px; flex:1; }
.usm-tabs a { color:#cdd6df; text-decoration:none; padding:12px 12px 10px; border-bottom:3px solid transparent; white-space:nowrap; }
.usm-tabs a:hover { color:#fff; background:rgba(255,255,255,.06); }
.usm-tabs a.on { color:#fff; font-weight:600; border-bottom-color:#5b9cff; }
.usm-src { color:#aab6c3; font-size:12px; text-decoration:none; white-space:nowrap; }
.usm-src:hover { color:#fff; }
@media (max-width:700px) { .usm-in { padding:0 10px; gap:0 12px; } .usm-tabs a { padding:8px 8px 6px; font-size:13px; } .usm-src { display:none; } }
@media print { .usm { display:none !important; } }
"""


def nav_html(active: str, prefix: str = "../") -> str:
    """The tab bar with ``active`` marked; ``prefix`` leads from this page back to the site root."""
    if active not in KEYS:
        raise ValueError(f"unknown tab {active!r}")
    root = prefix or "./"
    on = ' class="on" aria-current="page"'
    links = "".join(
        f'<a href="{escape(prefix + path if path else root)}" data-tab="{key}"{on if key == active else ""}>{escape(label)}</a>'
        for key, label, path in TABS)
    return (f'<nav class="usm" aria-label="Site"><div class="usm-in">'
            f'<a class="usm-brand" href="{escape(root)}"><b>Unified Site Management</b><span>Site AUS-1 · fictional</span></a>'
            f'<div class="usm-tabs">{links}</div>'
            f'<a class="usm-src" href="{REPO}">Source on GitHub</a></div></nav>')


def inject(template: str, active: str, prefix: str = "../") -> str:
    """Fill a page template's tab bar placeholders."""
    if "__SITENAV__" not in template or "__SITENAV_CSS__" not in template:
        raise ValueError("template is missing the site tab bar placeholders")
    return template.replace("__SITENAV_CSS__", CSS.strip()).replace("__SITENAV__", nav_html(active, prefix))
