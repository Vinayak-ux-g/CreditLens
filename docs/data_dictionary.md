# CreditLens Data Dictionary

## Table `loans` (SQLite: `sql/loans.db`), 30,366 rows, one row per loan

| Column | Type | Description |
|--------|------|-------------|
| `loan_id` | INTEGER | Unique loan identifier (primary key) |
| `issue_date` | TEXT | Origination date, ISO format (2024-06-15) |
| `issue_month` | TEXT | Pre-computed YYYY-MM for monthly grouping |
| `loan_amount` | REAL | Principal funded, USD ($1,000-$40,000, multiples of 25) |
| `term` | INTEGER | Loan term in months (36 or 60) |
| `int_rate` | REAL | Annual interest rate at origination, % (5.3-31.0) |
| `grade` | TEXT | Lender risk grade, A (best) -> G (worst) |
| `sub_grade` | TEXT | Finer rating step, A1 -> G5 |
| `purpose` | TEXT | Stated purpose (14 categories: debt_consolidation, small_business, ...) |
| `annual_income` | REAL | Borrower annual income, USD (capped at p99 = $178,084 during cleaning) |
| `emp_length` | REAL | Employment length in years, 0-10 (imputed with grade median when missing) |
| `home_ownership` | TEXT | MORTGAGE / RENT / OWN / OTHER |
| `dti` | REAL | Debt-to-income ratio, % (0-45 after cleaning) |
| `state` | TEXT | 2-letter US state code (50 states + DC) |
| `fico_score` | INTEGER | FICO credit score at origination (580-835) |
| `default_flag` | INTEGER | **Target.** 1 = loan defaulted, 0 = performing |

## Table `loan_scores` (same database), 30,366 rows, one row per loan

Output of the credit scorecard built by `scripts/risk_model.py`
(WOE/IV binning + logistic regression, holdout AUC 0.776).

| Column | Type | Description |
|--------|------|-------------|
| `loan_id` | INTEGER | Primary key, joins to `loans.loan_id` |
| `credit_score` | INTEGER | Scorecard points (489-643). Higher = safer. 600 = 20:1 good:bad odds, +20 pts doubles the odds (PDO=20) |
| `pd_default` | REAL | Model probability of default (0-1) for this loan |

Model inputs: DTI band, income band, term, loan-amount band (all application
data - grade, interest rate and FICO are deliberately excluded; the model is
benchmarked against them instead). Full methodology, coefficients, calibration
and policy simulation: `reports/model_report.txt`. Human-readable points table:
`reports/scorecard_points.csv`.

## Notes on the target

`default_flag` marks whether the loan was charged off during its life. It is known for
every row in the clean table (rows with a missing flag were dropped during cleaning -
see `reports/cleaning_report.txt`).

## Data lineage

```
scripts/generate_loans.py        -> data/raw/loans_raw.csv     (30,680 rows, messy on purpose)
scripts/clean_loans.py           -> data/clean/clean_loans.csv
scripts/risk_model.py            -> data/clean/loans_scored.csv + reports/model_*
scripts/load_database.py         -> sql/loans.db (both tables above)
scripts/run_analysis.py          -> sql/results/*.csv (20 queries)
scripts/export_dashboard_data.py -> dashboard/data.js
```

The dataset is simulated with a documented, seeded risk model. See the README section
"A note on the data" for how to swap in a real Kaggle credit-risk dataset.
