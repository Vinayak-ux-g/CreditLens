# CreditLens — CI activation & deployment guide

This file is the click-by-click version of "Turn everything on" in the README.
It covers the two switches that make the repo fully self-updating and public:
the GitHub Actions rebuild and the Vercel deployment.

---

## 0. Current state of the repository

| Piece | State |
|---|---|
| Pipeline code (`scripts/`, `sql/`, docs, dashboard HTML) | committed on `main` |
| `dashboard/data.js` | committed, but **stub** (model bundle only, loan rows empty) |
| `dashboard/vendor/` (ECharts, topojson, US map) | **not yet committed** (large files) |
| `dashboard/screenshots/` (4 PNGs) | **not yet committed** |
| `sql/loans.db` (SQLite, 30,366 loans + scores) | **not yet committed** |
| `.github/workflows/build.yml` | **not yet committed** — the workflow text is staged at `docs/build.yml.txt` |

Why the split: the files above are produced by the pipeline, and the plan was
always "let CI generate and commit them". The workflow file itself could not be
pushed by the tooling that committed the rest (writing to
`.github/workflows/` needs the `workflows` permission), so its exact text sits
at [`docs/build.yml.txt`](build.yml.txt) — 2,085 bytes, valid YAML, ready to
paste. Everything below is the two-step activation.

---

## 1. Activate the CI rebuild (2 minutes, web UI only)

1. Open <https://github.com/Vinayak-ux-g/CreditLens> (logged in as the owner).
2. Click **Add file → Create new file**.
3. Type the file name exactly: `.github/workflows/build.yml`
   (typing the `/` creates the folder automatically).
4. Open <https://github.com/Vinayak-ux-g/CreditLens/blob/main/docs/build.yml.txt>,
   click **Raw**, select all, copy.
5. Paste into the new file editor. Commit directly to `main`
   (suggested message: `Activate CI: add build workflow`).
6. Open the **Actions** tab. A run named **build** starts by itself
   (the push just triggered it).

What the run does (all steps are pinned, deterministic, ~5–8 minutes):

1. checkout → setup Python 3.12 → install pinned deps
2. vendor the dashboard libraries from pinned CDN builds (ECharts 5.6.0,
   topojson-client 3.1.0, US-atlas topology)
3. run the full pipeline: `generate_loans.py` → `clean_loans.py` →
   `risk_model.py` → `load_database.py` → `run_analysis.py`
   (all **25** queries) → `export_dashboard_data.py` → `psi_monitor.py` →
   `make_dashboard_pngs.py`
4. commit the rebuilt artifacts back to `main`: `data/`, `sql/loans.db`,
   `sql/results/`, `reports/`, `dashboard/data.js` (now with all 30,366 rows),
   `dashboard/vendor/`, `dashboard/screenshots/`

After the bot commit lands, the repo is complete: fresh clones contain the
database, the filled dashboard bundle and the screenshots, and re-running any
script locally leaves `git status` clean.

Troubleshooting:

- **No run appears** → make sure the file path is exactly
  `.github/workflows/build.yml` (plural `workflows`).
- **Run failed** → open the failed step, re-run after fixing; every step is
  idempotent, so re-running the whole job is always safe.
- **Want to rebuild without a push** → Actions → **build** → **Run workflow**
  (the workflow has `workflow_dispatch` enabled).

---

## 2. Deploy the dashboard to Vercel (3 minutes)

The dashboard is a pure static site, so Vercel serves it free.

### Option A — one click

Use the **Deploy with Vercel** button at the top of the README. It imports the
repo with *Root Directory* preset to `dashboard/`. Click through, wait for the
build, done.

### Option B — manual import (more control)

1. <https://vercel.com/new> → **Import** the `CreditLens` repository.
2. Framework Preset: **Other** (no build step needed).
3. **Root Directory**: `dashboard` — this is the important one; it makes the
   dashboard itself the site root, so `dashboard/vercel.json` applies and
   `index.html`-style routing works on refresh.
4. Deploy. You get a permanent `*.vercel.app` URL; every push to `main`
   redeploys automatically.

### Option C — landing page at the root (alternative shape)

Deploy the **repo root** instead (leave Root Directory empty). Visitors get the
project landing page (`index.html`), and the dashboard lives at `/dashboard/`.
Pick this shape if you want a portfolio landing page and the dashboard one
click deeper.

### When to deploy relative to step 1

Any time. Before the CI commit lands, the deployed dashboard shows a blue
"rebuild in progress" banner on the four data pages — and the **What-If
Simulator page is already fully interactive**, because it runs on the model
bundle that ships inside the stub `data.js`. After the CI commit, the same URL
serves the complete 30,366-row dashboard. No re-deploy needed: Vercel picks up
the bot commit automatically.

---

## 3. Verify everything works (checklist)

- [ ] Actions tab: latest **build** run green; a bot commit
      `Add rebuilt artifacts` exists on `main`
- [ ] `dashboard/data.js` is ~1.8 MB (not 13 KB) and `vendor/echarts.min.js`
      exists
- [ ] Open the Vercel URL: **no blue banner**, five tabs render:
      Overview / Risk Deep-Dive / Loan Explorer / Model & Scorecard /
      What-If Simulator
- [ ] Loan Explorer shows rows; the US map draws; ROC/KS/IV/WOE charts draw
- [ ] What-If Simulator: click the three presets — scores must read
      643 (Prime, APPROVE), 568 (Near-miss, DECLINE by 2), 489 (Subprime, DECLINE)
- [ ] README screenshots render on GitHub (they are committed by CI)

---

## 4. Local fallback (no CI at all)

You can produce every artifact locally and commit them yourself:

```bash
pip install -r requirements.txt
python scripts/generate_loans.py
python scripts/clean_loans.py
python scripts/risk_model.py
python scripts/load_database.py
python scripts/run_analysis.py        # 25 queries -> sql/results/
python scripts/export_dashboard_data.py
python scripts/psi_monitor.py         # -> reports/psi_report.txt
python scripts/make_dashboard_pngs.py # needs playwright + chromium
git add data sql/loans.db sql/results reports dashboard/data.js \
        dashboard/vendor dashboard/screenshots
git commit -m "Rebuild artifacts locally"
```

Everything is seeded — the outputs are byte-identical to what CI produces.
