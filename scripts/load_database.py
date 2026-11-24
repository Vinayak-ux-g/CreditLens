"""
CreditLens - Step 4: Load the clean CSV (and model scores) into SQLite
======================================================================

Creates sql/loans.db from data/clean/clean_loans.csv:
  * `loans`        - the analytical table (one row per loan)
  * `loan_scores`  - the credit scorecard output (credit_score, pd_default)
                     produced by scripts/risk_model.py, loaded from
                     data/clean/loans_scored.csv so the dashboard and the SQL
                     analysis read scores from the SQL layer - the same way a
                     BI tool would read a model results table from the warehouse.
plus indexes on the columns the analysis queries filter and group on.

Why SQLite? It is a real SQL engine, it is free, and the resulting .db file is
portable - a recruiter can open the repo and query it immediately with zero
setup. (In production the same SQL runs on MySQL/PostgreSQL/Redshift with
almost no changes.)

Usage
-----
    python scripts/risk_model.py      # 3. produce loans_scored.csv first
    python scripts/load_database.py   # 4. then build the database

Reads : data/clean/clean_loans.csv, data/clean/loans_scored.csv
Writes: sql/loans.db, sql/schema.sql
"""

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "clean_loans.csv"
SCORED = ROOT / "data" / "clean" / "loans_scored.csv"
DB = ROOT / "sql" / "loans.db"
SCHEMA = ROOT / "sql" / "schema.sql"

SCHEMA_SQL = """
DROP TABLE IF EXISTS loans;

CREATE TABLE loans (
    loan_id             INTEGER PRIMARY KEY,
    issue_date          TEXT,        -- ISO date, e.g. 2024-06-15
    issue_month         TEXT,        -- YYYY-MM, pre-computed for grouping
    loan_amount         REAL,        -- USD
    term                INTEGER,     -- 36 or 60 months
    int_rate            REAL,        -- annual interest rate, %
    grade               TEXT,        -- A (best) .. G (worst)
    sub_grade           TEXT,        -- A1 .. G5
    purpose             TEXT,        -- loan purpose category
    annual_income       REAL,        -- USD, capped at p99 in cleaning
    emp_length          REAL,        -- years (0-10), NaN-free after imputation
    home_ownership      TEXT,        -- MORTGAGE / RENT / OWN / OTHER
    dti                 REAL,        -- debt-to-income ratio, %
    state               TEXT,        -- 2-letter US state code
    fico_score          INTEGER,     -- credit score at origination
    default_flag        INTEGER      -- 1 = defaulted, 0 = performing
);

CREATE INDEX idx_loans_grade       ON loans (grade);
CREATE INDEX idx_loans_purpose     ON loans (purpose);
CREATE INDEX idx_loans_state       ON loans (state);
CREATE INDEX idx_loans_issue_month ON loans (issue_month);
CREATE INDEX idx_loans_default     ON loans (default_flag);

-- Model output table (from scripts/risk_model.py, the credit scorecard)
DROP TABLE IF EXISTS loan_scores;

CREATE TABLE loan_scores (
    loan_id      INTEGER PRIMARY KEY,
    credit_score INTEGER,      -- scorecard points, higher = safer (600 = 20:1 odds)
    pd_default   REAL          -- model probability of default, 0-1
);

CREATE INDEX idx_scores_score ON loan_scores (credit_score);
"""

INSERT_SQL = """
INSERT INTO loans (loan_id, issue_date, issue_month, loan_amount, term, int_rate,
                   grade, sub_grade, purpose, annual_income, emp_length,
                   home_ownership, dti, state, fico_score, default_flag)
VALUES (:loan_id, :issue_date, :issue_month, :loan_amount, :term, :int_rate,
        :grade, :sub_grade, :purpose, :annual_income, :emp_length,
        :home_ownership, :dti, :state, :fico_score, :default_flag)
"""


def main():
    if not SCORED.exists():
        raise SystemExit(
            f"{SCORED.name} not found - run `python scripts/risk_model.py` first.\n"
            "The database loads both the loan table and the scorecard output.")

    if DB.exists():
        DB.unlink()

    with CLEAN.open(newline="") as f:
        rows = list(csv.DictReader(f))

    # Keep only the columns the database needs (drop imputation flags - the
    # cleaning report already documents them; keep the analytical table lean).
    for r in rows:
        for num in ("loan_amount", "int_rate", "annual_income", "emp_length", "dti"):
            r[num] = float(r[num])
        for num in ("loan_id", "term", "fico_score", "default_flag"):
            r[num] = int(float(r[num]))

    with SCORED.open(newline="") as f:
        scored = [{"loan_id": int(r["loan_id"]),
                   "credit_score": int(r["credit_score"]),
                   "pd_default": float(r["pd_default"])} for r in csv.DictReader(f)]

    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA_SQL)
    conn.executemany(INSERT_SQL, rows)
    conn.executemany(
        "INSERT INTO loan_scores (loan_id, credit_score, pd_default) "
        "VALUES (:loan_id, :credit_score, :pd_default)", scored)
    conn.commit()

    n, = conn.execute("SELECT COUNT(*) FROM loans").fetchone()
    rate, = conn.execute("SELECT ROUND(100.0 * AVG(default_flag), 2) FROM loans").fetchone()
    ns, lo, hi = conn.execute(
        "SELECT COUNT(*), MIN(credit_score), MAX(credit_score) FROM loan_scores").fetchone()
    conn.close()

    SCHEMA.write_text(SCHEMA_SQL.lstrip() + "\n")

    print(f"Database written : {DB}")
    print(f"Schema saved     : {SCHEMA}")
    print(f"Rows loaded      : {n:,}")
    print(f"Default rate     : {rate}%")
    print(f"Scores loaded    : {ns:,} (range {lo}-{hi} points)")


if __name__ == "__main__":
    main()
