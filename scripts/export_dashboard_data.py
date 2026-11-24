"""
CreditLens - Step 6: Export SQL-layer data into the dashboard bundle
=====================================================================

Reads sql/loans.db (NOT the CSV) and writes dashboard/data.js - a compact,
column-oriented dataset the HTML dashboard consumes. Keeping this hop in the
pipeline preserves the project's core idea: the dashboard reads from the SQL
layer, so what you see always matches the database.

Also merges reports/model_artifacts.json (written by scripts/risk_model.py:
ROC / KS curves, IV table, WOE tables, score bands) into the same bundle as
CL.model - chart geometry is a model output, not something the browser should
recompute.

Output format (window.CL):
    months   : ["2021-01", ...]            (index = month idx)
    purposes : ["car", ...]                (index = purpose idx)
    rows     : { field: [values...] }      (parallel arrays, 30k rows)
    model    : { metrics, roc, ksCurve, iv, woe, bands }
Every value is a number or a small index - keeps the file around 2 MB.

Usage
-----
    python scripts/export_dashboard_data.py

Reads : sql/loans.db, reports/model_artifacts.json
Writes: dashboard/data.js
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "sql" / "loans.db"
OUT = ROOT / "dashboard" / "data.js"
ARTIFACTS = ROOT / "reports" / "model_artifacts.json"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT l.loan_id, l.issue_month, l.loan_amount, l.term, l.int_rate,
               l.grade, l.sub_grade, l.purpose, l.annual_income, l.dti,
               l.state, l.default_flag, s.credit_score, s.pd_default
        FROM loans l JOIN loan_scores s ON s.loan_id = l.loan_id
        ORDER BY l.loan_id""").fetchall()
    conn.close()

    months = sorted({r[1] for r in rows})
    month_ix = {m: i for i, m in enumerate(months)}
    purposes = sorted({r[7] for r in rows})
    purpose_ix = {p: i for i, p in enumerate(purposes)}
    states = sorted({r[10] for r in rows})
    state_ix = {s: i for i, s in enumerate(states)}
    grades = list("ABCDEFG")
    grade_ix = {g: i for i, g in enumerate(grades)}

    data = {
        "months": months,
        "purposes": purposes,
        "states": states,
        "stateNames": [STATE_NAMES.get(s, s) for s in states],
        "grades": grades,
        "rows": {
            "id":     [r[0] for r in rows],
            "m":      [month_ix[r[1]] for r in rows],
            "amt":    [int(r[2]) for r in rows],
            "term":   [r[3] for r in rows],
            "rate":   [r[4] for r in rows],
            "g":      [grade_ix[r[5]] for r in rows],
            "sub":    [r[6] for r in rows],
            "p":      [purpose_ix[r[7]] for r in rows],
            "inc":    [int(r[8]) for r in rows],
            "dti":    [r[9] for r in rows],
            "s":      [state_ix[r[10]] for r in rows],
            "d":      [r[11] for r in rows],
            "score":  [r[12] for r in rows],
            "pd":     [r[13] for r in rows],
        },
        "n": len(rows),
    }

    # model chart artifacts (ROC / KS curves, IV + WOE tables, bands, metrics)
    if ARTIFACTS.exists():
        data["model"] = json.loads(ARTIFACTS.read_text())
    else:
        raise SystemExit("reports/model_artifacts.json not found - "
                         "run `python scripts/risk_model.py` first.")

    payload = "window.CL = " + json.dumps(data, separators=(",", ":")) + ";"
    OUT.write_text(payload)
    print(f"Rows exported : {data['n']:,}")
    print(f"Model bundle  : metrics + {len(data['model']['iv'])} IV rows, "
          f"{len(data['model']['woe'])} WOE tables")
    print(f"Written       : {OUT} ({OUT.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
