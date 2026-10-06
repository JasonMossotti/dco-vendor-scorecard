#!/usr/bin/env python3
"""Build the static GitHub Pages site that runs the app in the browser (stlite).

Output (default _site/):
    index.html          loads stlite from the CDN and mounts the app
    streamlit_app.py    the app entrypoint
    app_bundle.zip      Python package, SLA, generator config, and datasets

Usage:
    python scripts/build_site.py                 # -> _site/
    python -m http.server -d _site 8000          # preview at http://localhost:8000
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Pinned for reproducibility. To upgrade, change this one line and check the page loads.
STLITE_VERSION = "1.8.1"
REQUIREMENTS = ["pyyaml", "pandas"]

INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
    <title>DCO Vendor Scorecard: interactive demo</title>
    <meta name="description" content="Vendor SLA scorecard for partner-operated GPU data center sites. Synthetic data portfolio demo." />
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@{version}/build/stlite.css" />
    <style>
      .boot {{ font-family: system-ui, sans-serif; max-width: 40rem; margin: 15vh auto; color: #333; line-height: 1.5; }}
      .boot small {{ color: #777; }}
    </style>
  </head>
  <body>
    <div id="root">
      <div class="boot">
        <h2>DCO Vendor Scorecard</h2>
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
          streamlitConfig: {{ "client.toolbarMode": "viewer" }},
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
    files += sorted((root / "sla").glob("*.yaml")) + [root / "config" / "synthetic.yaml", root / "site" / "site.yaml"]
    for ds in ("sample", "latest"):
        d = root / "data" / ds
        if d.exists():
            files += [p for p in d.rglob("*") if p.is_file()]
    return sorted(files)


def build(out: Path, root: Path = ROOT) -> dict[str, int]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy2(root / "app" / "streamlit_app.py", out / "streamlit_app.py")
    members = bundle_members(root)
    with zipfile.ZipFile(out / "app_bundle.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in members:
            z.write(p, p.relative_to(root).as_posix())
    reqs = "[" + ", ".join(f'"{r}"' for r in REQUIREMENTS) + "]"
    (out / "index.html").write_text(INDEX_HTML.format(version=STLITE_VERSION, requirements=reqs),
                                    encoding="utf-8", newline="\n")
    # The interactive post-incident review page, served at /pir/ beside the app.
    sys.path.insert(0, str(root / "scripts"))
    import render_pir
    (out / "pir").mkdir(parents=True, exist_ok=True)
    (out / "pir" / "index.html").write_text(render_pir.html_page(), encoding="utf-8")
    # The weekly operations review, served at /weekly/.
    import render_weekly
    (out / "weekly").mkdir(parents=True, exist_ok=True)
    (out / "weekly" / "index.html").write_text(render_weekly.html_page(), encoding="utf-8")
    # The failure pattern review, served at /patterns/.
    import render_patterns
    (out / "patterns").mkdir(parents=True, exist_ok=True)
    (out / "patterns" / "index.html").write_text(render_patterns.html_page(), encoding="utf-8")
    return {"files_in_bundle": len(members), "bundle_bytes": (out / "app_bundle.zip").stat().st_size}


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
