# Activate CI (one-time, 2 minutes)

CreditLens ships with a GitHub Actions workflow that rebuilds every generated
artifact - the loan-level dashboard data, the vendored chart libraries, the
dashboard screenshots and the SQLite database - straight from source, and
commits them back to `main`. The pipeline is seeded and deterministic, so
rebuilds are byte-identical.

The workflow text is already staged at [`docs/build.yml.txt`](docs/build.yml.txt).
It could not be placed at its live location by the automation account because
that credential lacks the `Workflows` permission (GitHub requires a special
scope to create or modify anything under `.github/workflows/`). Adding the
file yourself takes about two minutes and needs no local setup.

## Step-by-step

1. Open the repository on github.com and sign in as the owner.
2. Click **Add file > Create new file**.
3. In the file-name box type exactly:
   `.github/workflows/build.yml`
   (typing the `/` makes GitHub create the folder.)
4. Open [`docs/build.yml.txt`](docs/build.yml.txt), click **Raw**, select all,
   copy, and paste the YAML into the editor.
5. Commit straight to `main` ("Commit changes > Commit directly...").
6. Watch it run under the **Actions** tab (job name: `build`). It installs
   pinned dependencies, vendors ECharts / topojson / us-atlas, runs the full
   pipeline (generate > clean > score > load DB > 25 SQL analyses > export
   dashboard data > render screenshots) and commits the artifacts back.

## What lands after the first run

| Path | Contents |
| --- | --- |
| `dashboard/data.js` | full 30,366-loan dataset + model bundle (replaces any preview sample) |
| `dashboard/vendor/` | pinned `echarts.min.js`, `topojson-client.min.js`, `us-topo.js` |
| `dashboard/screenshots/` | the four PNG previews embedded in the README |
| `sql/loans.db` | rebuilt SQLite database |
| `sql/results/` | one CSV per analysis query (Q1-Q25) + `results_summary.txt` |
| `reports/` | `cleaning_report.txt`, `model_report.txt`, `psi_report.txt` |

Every later push to `main` re-runs the same pipeline automatically (and you
can trigger it manually via **Actions > build > Run workflow**).

## Alternative: manual artifact upload (no CI)

If you prefer not to enable Actions, the ready-made artifacts are in the
`creditlens-upload` folder distributed with this project. Upload each file
via **Add file > Upload files** (drag and drop, up to 25 MB per file) to the
matching path in the repo:

- `dashboard/data.js`
- `dashboard/creditlens_dashboard.html`
- `dashboard/vendor/echarts.min.js`, `dashboard/vendor/topojson-client.min.js`, `dashboard/vendor/us-topo.js`
- `dashboard/screenshots/page1_overview.png` ... `page4_model_scorecard.png`
- `sql/loans.db`

CI remains the recommended route: it keeps every artifact reproducible from
source and keeps the repo self-healing.
