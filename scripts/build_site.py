#!/usr/bin/env python3
"""Build the static GitHub Pages site: Unified Site Management.

Output (default _site/):
    index.html              the Unified Site Management overview (scripts/render_hub.py)
    app/index.html          the site tab bar above the scorecard app, run in the browser by stlite
    app/streamlit_app.py    the app entrypoint
    app/app_bundle.zip      Python package, SLA, generator config, and datasets
    alarms/ pir/ weekly/ patterns/   the static pages, each with the same tab bar
    agreements/             the Interface Agreement and both SLAs, readable (scripts/render_agreements.py)
    glossary/               every code, acronym, and record ID (scripts/render_glossary.py)
    devices/                every named device and what it connects to (scripts/render_devices.py)
    site/                   the site drawings (docs/site/*.svg), which the location popups open

Usage:
    python scripts/build_site.py                 # -> _site/
    python -m http.server -d _site 8000          # preview at http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Pinned for reproducibility. To upgrade, change this one line and check the page loads.
STLITE_VERSION = "1.8.1"
REQUIREMENTS = ["pyyaml", "pandas"]
# The light theme every page shares (the same values as .streamlit/config.toml for local runs).
STREAMLIT_CONFIG = {
    "client.toolbarMode": "viewer",
    "theme.base": "light",
    "theme.primaryColor": "#1f5fbf",
    "theme.backgroundColor": "#ffffff",
    "theme.secondaryBackgroundColor": "#f5f7f9",
    "theme.textColor": "#1e2933",
}

INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
    <title>Scorecards · Unified Site Management</title>
    <meta name="description" content="Vendor SLA scorecards for partner-operated GPU data center sites. Synthetic data portfolio demo." />
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@{version}/build/stlite.css" />
    <style>
      {nav_css}
      /* One scroll bar: the page itself never scrolls; the app scrolls inside the space under the tab bar.
         The transform makes the app's fixed-position header sit inside that space instead of over the tab bar. */
      html, body {{ height: 100%; margin: 0; overflow: hidden; background: #ffffff; }}
      body {{ display: flex; flex-direction: column; }}
      .usm {{ flex: none; }}
      #root {{ flex: 1; min-height: 0; position: relative; overflow: hidden; transform: translateZ(0); }}
      #root [data-testid="stMainBlockContainer"] {{ padding-top: 3.5rem; }}
      .boot {{ font-family: "Inter", "Segoe UI", Helvetica, Arial, sans-serif; max-width: 40rem; margin: 12vh auto; padding: 0 16px; color: #1e2933; line-height: 1.5; }}
      .boot small {{ color: #5b6774; }}
    </style>
  </head>
  <body>
    {nav}
    <div id="root">
      <div class="boot">
        <h2>Scorecards</h2>
        <p>Starting Python in your browser. The first visit takes about 20 to 40 seconds while the runtime downloads;
        after that it is cached.</p>
        <p><small>Everything runs locally in this tab. Synthetic data only; all names and events are fictional.</small></p>
        <noscript>This demo needs JavaScript enabled.</noscript>
      </div>
    </div>
    <script type="module">
      import {{ mount }} from "https://cdn.jsdelivr.net/npm/@stlite/browser@{version}/build/stlite.js";
      mount(
        {{
          requirements: {requirements},
          entrypoint: "streamlit_app.py",
          files: {{ "streamlit_app.py": {{ url: "./streamlit_app.py" }} }},
          archives: [{{ url: "./app_bundle.zip", format: "zip", options: {{}} }}],
          streamlitConfig: {streamlit_config},
        }},
        document.getElementById("root"),
      );
    </script>
  </body>
</html>
"""


def bundle_members(root: Path) -> list[Path]:
    # The live collector is not part of the browser app.
    files = [p for p in (root / "src" / "scorecard").rglob("*.py") if "live" not in p.relative_to(root / "src" / "scorecard").parts]
    files += sorted((root / "sla").glob("*.yaml")) + [root / "config" / "synthetic.yaml", root / "site" / "site.yaml",
                                                   root / "site" / "details.yaml"]   # the lookup panel draws the detail sheets
    # The code lookup: the glossary and the generated contracts it points into.
    files += [root / "config" / "glossary.yaml"] + sorted((root / "docs" / "sla").glob("*.md"))
    for ds in ("sample", "latest"):
        d = root / "data" / ds
        if d.exists():
            files += [p for p in d.rglob("*") if p.is_file()]
    return sorted(files)


def build(out: Path, root: Path = ROOT) -> dict[str, int]:
    sys.path.insert(0, str(root / "src"))
    sys.path.insert(0, str(root / "scripts"))
    from scorecard import sitenav
    if out.exists():
        shutil.rmtree(out)
    app = out / "app"
    app.mkdir(parents=True)
    shutil.copy2(root / "app" / "streamlit_app.py", app / "streamlit_app.py")
    members = bundle_members(root)
    with zipfile.ZipFile(app / "app_bundle.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in members:
            z.write(p, p.relative_to(root).as_posix())
    reqs = "[" + ", ".join(f'"{r}"' for r in REQUIREMENTS) + "]"
    (app / "index.html").write_text(
        INDEX_HTML.format(version=STLITE_VERSION, requirements=reqs, streamlit_config=json.dumps(STREAMLIT_CONFIG),
                          nav_css=sitenav.CSS.strip(), nav=sitenav.nav_html("scorecards")),
        encoding="utf-8", newline="\n")
    # The Unified Site Management overview, at the site root.
    import render_hub
    (out / "index.html").write_text(render_hub.html_page(), encoding="utf-8", newline="\n")
    # The static pages beside the app: post-incident review, weekly review, failure patterns, alarm board.
    import render_alarms
    import render_patterns
    import render_pir
    import render_weekly
    for path, mod in (("pir", render_pir), ("weekly", render_weekly), ("patterns", render_patterns), ("alarms", render_alarms)):
        (out / path).mkdir(parents=True, exist_ok=True)
        (out / path / "index.html").write_text(mod.html_page(), encoding="utf-8", newline="\n")
    # The reference tabs: the contracts, the glossary, and the device directory.
    import render_agreements
    import render_devices
    import render_glossary
    render_agreements.write(out / "agreements")
    (out / "glossary").mkdir(parents=True, exist_ok=True)
    (out / "glossary" / "index.html").write_text(render_glossary.html_page(), encoding="utf-8", newline="\n")
    (out / "devices").mkdir(parents=True, exist_ok=True)
    (out / "devices" / "index.html").write_text(render_devices.html_page(), encoding="utf-8", newline="\n")
    # The site drawings, which the location popups open (highlighted) on every page.
    (out / "site").mkdir(parents=True, exist_ok=True)
    for svg in sorted((root / "docs" / "site").glob("*.svg")):
        shutil.copy2(svg, out / "site" / svg.name)
    return {"files_in_bundle": len(members), "bundle_bytes": (app / "app_bundle.zip").stat().st_size}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "_site"))
    args = ap.parse_args()
    info = build(Path(args.out))
    print(f"Site -> {args.out}: {info['files_in_bundle']} files bundled ({info['bundle_bytes'] / 1024:.0f} KB), "
          f"stlite {STLITE_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
