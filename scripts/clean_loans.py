"""
CreditLens - Step 2: Data cleaning with Python / Pandas
========================================================

Reads the raw export (data/raw/loans_raw.csv) and produces an analysis-ready
table (data/clean/clean_loans.csv) plus a full audit trail
(reports/cleaning_report.txt).

Cleaning philosophy (the "why" interviewers ask about)
------------------------------------------------------
1.  Fix types first  - you cannot count missing money that is stored as text.
2.  Drop rows only when the target is missing - losing features is bad,
    losing the label is fatal (the row can never be used for risk analysis).
3.  Impute with group medians, not global ones - a grade-A borrower and a
    grade-G borrower have different income/DTI profiles; a global median
    would smear them together.
4.  Cap extreme outliers instead of deleting them - a $4.5M "income" is an
    entry error, but the loan itself is real. We keep the loan, we just do
    not let one typo distort averages.
5.  Log every decision with counts - a number you cannot justify in an
    interview is a number you should not publish.

Usage
-----
    python scripts/clean_loans.py

Reads : data/raw/loans_raw.csv
Writes: data/clean/clean_loans.csv, reports/cleaning_report.txt
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "loans_raw.csv"
CLEAN = ROOT / "data" / "clean" / "clean_loans.csv"
REPORT = ROOT / "reports" / "cleaning_report.txt"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

STATE_FIX = {"California": "CA", "Texas": "TX", "Florida": "FL", "New York": "NY",
             "Illinois": "IL", "Ohio": "OH", "Georgia": "GA"}

log_lines = []


def log(msg=""):
    print(msg)
    log_lines.append(str(msg))


def parse_money(s):
    """'$15,875' -> 15875.0 ; '' -> NaN"""
    if pd.isna(s) or str(s).strip() == "":
        return np.nan
    return float(re.sub(r"[$,]", "", str(s)))


def parse_pct(s):
    """'12.91%' -> 12.91"""
    if pd.isna(s) or str(s).strip() == "":
        return np.nan
    return float(str(s).replace("%", ""))


def parse_term(s):
    """'36 months' -> 36"""
    if pd.isna(s):
        return np.nan
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else np.nan


def parse_emp(s):
    """'< 1 year'->0, '3 years'->3, '10+ years'->10, 'n/a'/''->NaN"""
    s = str(s).strip().lower()
    if s in ("", "nan", "n/a"):
        return np.nan
    if s.startswith("<"):
        return 0
    if s.startswith("10+"):
        return 10
    m = re.search(r"\d+", s)
    return int(m.group()) if m else np.nan


def parse_date(s):
    """Accepts '2024-06-15' and 'Jun-2024' -> datetime (day=15 for Mon-YYYY)."""
    s = str(s).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return pd.Timestamp(s)
    m = re.match(r"^([A-Z][a-z]{2})-(\d{4})$", s)
    if m:
        return pd.Timestamp(int(m.group(2)), MONTHS[m.group(1)], 15)
    return pd.NaT


def main():
    df = pd.read_csv(RAW, dtype=str)
    log("=" * 74)
    log("CREDITLENS DATA CLEANING REPORT")
    log("=" * 74)
    log(f"\nInput               : {RAW}")
    log(f"Raw rows            : {len(df):,}")
    log(f"Raw columns         : {len(df.columns)}")

    # ------------------------------------------------------------------
    # 1. Type fixing - text -> proper numeric / datetime types
    # ------------------------------------------------------------------
    log("\n" + "-" * 74)
    log("STEP 1  Type fixing")
    log("-" * 74)
    df["loan_amount"] = df["loan_amount"].map(parse_money)
    df["int_rate"] = df["int_rate"].map(parse_pct)
    df["term"] = df["term"].map(parse_term)
    df["annual_income"] = df["annual_income"].map(parse_money)   # handles '$4,500,000'
    df["dti"] = pd.to_numeric(df["dti"], errors="coerce")
    df["fico_score"] = pd.to_numeric(df["fico_score"], errors="coerce")
    df["default_flag"] = pd.to_numeric(df["default_flag"], errors="coerce")
    df["emp_length"] = df["emp_length"].map(parse_emp)
    log("loan_amount  : stripped '$' and ','  -> float")
    log("int_rate     : stripped '%'          -> float")
    log("term         : '36 months'           -> 36 / 60")
    log("annual_income: stripped '$' and ','  -> float")
    log("emp_length   : '< 1 year'=0 ... '10+ years'=10, 'n/a'->NaN")
    log("issue_date   : mixed formats parsed  -> datetime")

    # ------------------------------------------------------------------
    # 2. Category standardisation
    # ------------------------------------------------------------------
    log("\n" + "-" * 74)
    log("STEP 2  Category standardisation")
    log("-" * 74)
    before = df["grade"].str.strip().str.upper().ne(df["grade"]).sum()
    df["grade"] = df["grade"].str.strip().str.upper()
    df["sub_grade"] = df["sub_grade"].str.strip().str.upper()
    log(f"grade        : {before} rows re-cased to upper (e.g. ' a ' -> 'A')")

    messy_purpose = ~df["purpose"].str.fullmatch(r"[a-z_]+")
    n_purpose = int(messy_purpose.sum())
    df["purpose"] = (df["purpose"].str.strip().str.lower()
                     .str.replace(r"[\s-]+", "_", regex=True))
    log(f"purpose      : {n_purpose} rows normalised (e.g. 'Debt Consolidation' -> 'debt_consolidation')")

    full_names = df["state"].isin(STATE_FIX)
    n_state = int(full_names.sum())
    df["state"] = df["state"].replace(STATE_FIX).str.strip().str.upper()
    log(f"state        : {n_state} full names mapped to codes (e.g. 'California' -> 'CA')")

    # ------------------------------------------------------------------
    # 3. Dates
    # ------------------------------------------------------------------
    df["issue_date"] = df["issue_date"].map(parse_date)
    n_dates = int(df["issue_date"].isna().sum())
    df = df.dropna(subset=["issue_date"])
    log(f"issue_date   : {n_dates} unparseable dates dropped (none expected)")

    # ------------------------------------------------------------------
    # 4. Rows missing the target are unusable - drop them
    # ------------------------------------------------------------------
    log("\n" + "-" * 74)
    log("STEP 3  Missing target")
    log("-" * 74)
    n_target = int(df["default_flag"].isna().sum())
    df = df.dropna(subset=["default_flag"])
    df["default_flag"] = df["default_flag"].astype(int)
    log(f"default_flag : {n_target} rows dropped (target unknown -> unusable for risk analysis)")

    # ------------------------------------------------------------------
    # 5. Duplicates - exact copies AND re-issued rows (same loan, new ID)
    # ------------------------------------------------------------------
    log("\n" + "-" * 74)
    log("STEP 4  Duplicates")
    log("-" * 74)
    n_exact = int(df.duplicated().sum())
    df = df.drop_duplicates()
    n_fuzzy = int(df.duplicated(subset=[c for c in df.columns if c != "loan_id"]).sum())
    df = df.drop_duplicates(subset=[c for c in df.columns if c != "loan_id"], keep="first")
    log(f"exact copies : {n_exact} rows dropped")
    log(f"re-issued    : {n_fuzzy} rows dropped (identical loan, different loan_id)")

    # ------------------------------------------------------------------
    # 6. Impossible values -> NaN (then imputed like other missing values)
    # ------------------------------------------------------------------
    log("\n" + "-" * 74)
    log("STEP 5  Impossible values")
    log("-" * 74)
    bad_dti = int(((df["dti"] < 0) | (df["dti"] > 100)).sum())
    df.loc[(df["dti"] < 0) | (df["dti"] > 100), "dti"] = np.nan
    log(f"dti          : {bad_dti} impossible values (negative or >100) set to NaN")

    # ------------------------------------------------------------------
    # 7. Income outliers - cap at the 99th percentile (keep the loan)
    # ------------------------------------------------------------------
    p99 = df["annual_income"].quantile(0.99)
    outliers = df["annual_income"] > p99
    n_out = int(outliers.sum())
    df.loc[outliers, "annual_income"] = p99
    log(f"annual_income: {n_out} outliers above p99 (${p99:,.0f}) capped at p99")
    log("              (an entry error like $4.5M must not distort grade medians)")

    # ------------------------------------------------------------------
    # 8. Missing-value report + group-median imputation
    # ------------------------------------------------------------------
    log("\n" + "-" * 74)
    log("STEP 6  Missing values and imputation")
    log("-" * 74)
    for col in ("emp_length", "annual_income", "dti"):
        log(f"{col:<12}: {int(df[col].isna().sum()):>4} missing "
            f"({df[col].isna().mean():.2%} of rows) -> imputed with grade median")

    df["emp_length_imputed"] = df["emp_length"].isna()
    df["income_imputed"] = df["annual_income"].isna()
    df["dti_imputed"] = df["dti"].isna()
    for col in ("emp_length", "annual_income", "dti"):
        df[col] = df[col].fillna(df.groupby("grade")[col].transform("median"))

    # ------------------------------------------------------------------
    # 9. Final shape + sanity checks
    # ------------------------------------------------------------------
    df = df.sort_values("loan_id").reset_index(drop=True)
    df["issue_month"] = df["issue_date"].dt.strftime("%Y-%m")

    log("\n" + "-" * 74)
    log("RESULT")
    log("-" * 74)
    log(f"Clean rows   : {len(df):,}  (from {30680:,} raw)")
    log(f"Columns      : {len(df.columns)} (added issue_month + 3 imputation flags)")
    log(f"Default rate : {df['default_flag'].mean():.2%}")
    log(f"Date range   : {df['issue_date'].min():%Y-%m} to {df['issue_date'].max():%Y-%m}")
    analysis_cols = ["loan_amount", "int_rate", "term", "grade", "purpose",
                     "annual_income", "emp_length", "dti", "state"]
    log(f"Missing cells: {int(df[analysis_cols].isna().sum().sum())} in analysis columns")

    CLEAN.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLEAN, index=False)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(log_lines) + "\n")
    print(f"\nClean dataset written : {CLEAN}")
    print(f"Report written        : {REPORT}")


if __name__ == "__main__":
    main()
