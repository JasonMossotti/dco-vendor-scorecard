# CLAUDE.md: dco-vendor-scorecard

Portfolio project for a Data Center Operations Lead (partner-operated sites) application. Owner: Jason Mossotti.
Repo: https://github.com/JasonMossotti/dco-vendor-scorecard · Live: https://jasonmossotti.github.io/dco-vendor-scorecard/ (Unified Site Management overview), `/app/` (scorecard app), `/pir/` (post-incident review), `/weekly/` (weekly operations review), `/patterns/` (failure pattern review), `/energy/` (PUE report), `/gpu/` (GPU health), `/telemetry/` (GPU and CDU telemetry; power, network, and a site health dashboard to follow), `/alarms/` (Customer alarm board), `/tickets/` (Incident Portal: both partners' tickets, changes, and work orders), `/agreements/` (the three contracts), `/glossary/` (every code; popups on every page), `/devices/` (every named device and its connections), `/deployments/` (Hall B GB300 rollout: gates, steps, calculations, permits, work orders, record checks).

Fictional Site AUS-1 (Central Texas): the Customer leases halls from a Landlord (Caprock Critical Facilities: building, power, cooling, CDUs) and contracts an IT Partner (Ridgeline Site Services: data hall work). SLAs as code, synthetic telemetry with planted discrepancies, one engine per partner, cross-partner fault attribution, scorecards that compare self-reports with measurement. Everything synthetic; never imply knowledge of any real company's internal systems.

## Start of every session

1. Clone the repo and check the working copy against `origin/main`.
2. Read only these parts of `docs/PROJECT_GUIDE.md`: **Current status**, **Open items**, and the **last entry of Build history**. Read other sections only when the task needs them (use `grep -n` or `sed -n 'a,bp'`). The guide's "Where things live" table maps every concern to its file.
3. The job posting is in project knowledge (if this is a Claude Project); the guide's "How the project maps to the posting's duties" table summarizes it.

## The owner

Data center and NOC operations professional; expert in the domain, newer to Git and Python. Works on **Windows in Git Bash**, repo at `/c/Users/jmoss/Desktop/GitHubRepos/dco-vendor-scorecard`. Give exact commands and say what success looks like. Keep replies concise.

## Delivery loop

1. Build and verify in your own environment (regenerate everything, full test suite, robustness runs if engines or the generator changed).
2. Deliver the **whole repo as `dco-vendor-scorecard.zip`** (top folder `dco-vendor-scorecard/`), made from `git ls-files --cached --others --exclude-standard`, so hidden files and new files are included and `.git`, `node_modules`, and build output are not.
3. Owner applies it:
   ```bash
   cp -R ~/Downloads/dco-vendor-scorecard/. /c/Users/jmoss/Desktop/GitHubRepos/dco-vendor-scorecard/
   cd /c/Users/jmoss/Desktop/GitHubRepos/dco-vendor-scorecard
   git status
   git add .
   git commit -m "..."
   git push
   ```
   **Copying never deletes.** If a delivery removes or renames a file, give the exact `git rm <path>` lines to run before `git add .`. Say how many modified and new files `git status` should show.
4. Owner checks both Actions runs are green (CI, and "Deploy demo to GitHub Pages"), then reviews the live pages and sends screenshots.

## Rules that caught real bugs

- **Plan before building** anything larger than a fix; list the judgment calls the owner should be ready to defend, and get a yes.
- **Generated files are never edited by hand:** `docs/sla/`, `docs/site/`, `docs/pir/`, `docs/weekly/`, `data/sample/`, `data/history/`, `data/changes/`, `docs/glossary/`, `data/energy/`, `data/gpu_health/`, `data/deployments/`, `docs/deployments/`, `data/telemetry/`, `reports/` (the per-GPU hourly telemetry tier is built into git-ignored `build/`). Tests fail when they are stale.
- **Never ship untested UI.** The app is tested against `tests/fake_streamlit.py`; the PIR and weekly pages by jsdom (`tests/js/`, install with `cd tests/js && npm install --no-save jsdom@24`). For visual bugs, render the SVG and look at it.
- **Measure on months the code was not tuned on:** `python scripts/run_engine.py --robustness 60`, `python scripts/run_landlord.py --robustness 60`, `python scripts/check_facility_data.py`, `python scripts/render_patterns.py --robustness 60`, `python scripts/render_alarms.py --robustness 60`, `python scripts/render_energy.py --robustness 60`, `python scripts/render_gpu_health.py --robustness 60`, `python scripts/render_deployments.py --robustness 60`, `python scripts/render_telemetry.py --robustness 60`. Find the root cause of every miss before changing anything.
- **New synthetic data uses its own random stream**; prove existing records and every report are unchanged (snapshot and `diff -rq`).
- **Reconcile new views with existing results** (the weekly pack's month to date must equal the monthly scorecards).
- **Verify fast-changing facts** (library versions, GitHub Actions, standards editions) against current sources, not memory.
- **Facts come from the data; judgment comes from people.** Written reviews and notes live in YAML and are tested against the facts (every number and reference must match; no individual is named).
- **A finding means records do not reconcile, not that someone lied.** Keep that framing.
- **Portable code:** no `%-d` in `strftime` (Windows); LF line endings everywhere.

## Commands

```bash
pip install -r requirements-live.txt          # everything, including the live collector's tests
python scripts/render_sla.py && python scripts/render_site.py && python scripts/generate_data.py \
  && python scripts/run_engine.py && python scripts/build_scorecard.py && python scripts/run_landlord.py \
  && python scripts/render_pir.py && python scripts/render_weekly.py \
  && python scripts/generate_history.py && python scripts/render_patterns.py \
  && python scripts/generate_changes.py && python scripts/render_alarms.py \
  && python scripts/generate_energy.py && python scripts/render_energy.py \
  && python scripts/generate_gpu_health.py && python scripts/render_gpu_health.py && python scripts/render_glossary.py \
  && python scripts/generate_deployments.py && python scripts/render_deployments.py \
  && python scripts/generate_telemetry.py && python scripts/render_telemetry.py
pytest -q                                      # 552 tests as of 2026-10-09
python scripts/build_site.py --out _site       # the GitHub Pages build
```

Headline results that must not move unless a change intends it: IT 4 Minimum defaults, $188,700, engine 17/17 and 1,020/1,020; Landlord 4 defaults, $106,200, 8/8 and 480/480; facility evidence 60/60. Failure patterns: 3 found, 0 other flags; robustness lot 60/60, CDU drift 60/60, reseat 41/60, decoys 0/60. Change-aware alarms: sample 120 alarms, 11 expected, 4 flags (all MOP-310); robustness every case 60/60, decoys 0/60, 10 other flags (all real coincident faults), detail-sheet parts 7,926/7,926, device directory names 13,076/13,076 and leaf port cables 8,896/8,896. Energy: month PUE 1.353 (Landlord reported 1.313), 52-week 1.318, 2 of 2 planted; robustness 109/109, 0 false positives. GPU health: 4 findings, 7 of 7 planted, 3 of 10 memory XIDs warned ahead; robustness 548/548, 0 false positives. Deployments: 275 work orders, 123 complete, gates G1 closed (G0 6/7, G2 109/256); record checks 4 of 4 planted, 0 false positives; robustness 240/240, 0 false positives. GPU telemetry: 3,312 GPUs, 9 agreements, 60,257 of 60,257 cases; Hall B 63.9% of samples at the 1,200 W cap; robustness 8 agreements, 8,520,414/8,520,414. CDU telemetry: 8 CDUs (DMTF Redfish), 9 agreements, 664,024 of 664,024 cases; robustness ROBUST60.

## Saving tokens

- Do not print whole files or long diffs; use `grep -n`, `sed -n` ranges, `--stat`, and `tail` on test output.
- Run tests quietly (`pytest -q | tail -3`) and show failures only.
- One task per conversation. When a task is delivered, update the guide's Current status, Build history, and Open items so the next conversation starts from the repo, not from chat history.
