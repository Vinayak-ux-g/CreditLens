"""
CreditLens - Step 1: Raw loan data creation
============================================

Creates a realistic, 30,000+ row personal-loan dataset modelled on the shape of
public lending-club style data (loan amounts, grades A-G, DTI, income, purpose,
state, issue date and a binary default flag).

The generator is seeded, so every run produces byte-identical output
(reproducibility is a real requirement in analytics, not a nice-to-have).

Realism features
----------------
* Default risk is driven by a logistic model over grade, interest rate, DTI,
  income, purpose, term and state - NOT random noise. That means the SQL
  analysis later finds genuine, explainable patterns.
* Grade mix improves slightly over the issue-date range, so the monthly trend
  analysis shows a slowly improving default rate (a realistic portfolio story).
* Income is log-normal, amounts correlate with income, rates follow grade.

Deliberate data-quality problems (for the cleaning step to fix)
---------------------------------------------------------------
1.  loan_amount / int_rate / term stored as text ("$12,500", "13.42%", "36 months")
2.  ~0.4% of rows missing the default target  -> must be dropped
3.  ~2.5% missing / "n/a" employment length   -> imputed
4.  ~1.2% missing annual income                -> imputed by grade median
5.  ~1.5% missing dti                          -> imputed by grade median
6.  ~180 duplicate rows (exact copies + re-issued rows)
7.  Income outliers (data-entry errors up to $6.5M)
8.  Impossible DTI values (negative, or > 100)
9.  Mixed date formats ("2021-03-15" vs "Mar-2021")
10. Inconsistent categories (grade lowercase / spaces, purpose with spaces vs
    underscores, full state names instead of codes)

Usage
-----
    python scripts/generate_loans.py

Writes: data/raw/loans_raw.csv
"""

import numpy as np
import pandas as pd
from pathlib import Path

RNG = np.random.default_rng(42)

ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data" / "raw" / "loans_raw.csv"

N_BASE = 30_500            # unique loan records
N_DUPES = 180              # injected duplicate rows
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)   # issue years, Jan 2021 - Oct 2026

# ---------------------------------------------------------------------------
# 1. Core portfolio structure
# ---------------------------------------------------------------------------

GRADES = ["A", "B", "C", "D", "E", "F", "G"]
# LendingClub-style grade mix (share of loans), slowly improving over time
GRADE_BASE = np.array([0.130, 0.250, 0.250, 0.180, 0.110, 0.055, 0.025])
GRADE_IMPROVE = np.array([0.020, 0.015, 0.005, -0.008, -0.014, -0.010, -0.008])  # drift over 6y

PURPOSES = [
    "debt_consolidation", "credit_card", "home_improvement", "other",
    "major_purchase", "medical", "small_business", "car", "wedding",
    "moving", "vacation", "house", "educational", "renewable_solar",
]
PURPOSE_P = np.array([0.452, 0.140, 0.080, 0.070, 0.050, 0.050, 0.040,
                      0.035, 0.025, 0.020, 0.020, 0.012, 0.004, 0.002])

# 50 states + DC, roughly population-weighted
STATES = ["CA","TX","FL","NY","PA","IL","OH","GA","NC","MI","NJ","VA","WA","AZ","MA",
          "TN","IN","MO","MD","WI","CO","MN","SC","AL","LA","KY","OR","OK","CT","UT",
          "IA","NV","AR","MS","KS","NM","NE","WV","ID","HI","NH","ME","MT","DE","SD",
          "ND","AK","VT","WY","DC"]
STATE_P = np.array([0.121,0.090,0.066,0.060,0.040,0.040,0.036,0.033,0.031,0.029,
                    0.028,0.027,0.025,0.023,0.021,0.021,0.020,0.019,0.018,0.017,
                    0.017,0.016,0.016,0.015,0.015,0.014,0.013,0.012,0.011,0.011,
                    0.010,0.009,0.009,0.009,0.008,0.008,0.007,0.006,0.005,0.005,
                    0.004,0.004,0.003,0.003,0.003,0.002,0.002,0.002,0.001,0.001])
STATE_P = STATE_P / STATE_P.sum()
# Some states carry structurally higher risk (odds multipliers on default)
STATE_RISK = {"NV": 1.35, "FL": 1.18, "AZ": 1.14, "TN": 1.12, "IN": 1.10, "GA": 1.08,
              "NM": 1.10, "AL": 1.09, "MI": 1.06, "OH": 1.05, "TX": 1.04, "CA": 1.03,
              "NY": 0.95, "MA": 0.90, "MN": 0.88, "VT": 0.85, "NH": 0.87, "IA": 0.90}

GRADE_RATE = {"A": (7.6, 1.0), "B": (10.6, 1.1), "C": (13.6, 1.2), "D": (16.6, 1.3),
              "E": (19.6, 1.5), "F": (23.0, 1.7), "G": (26.5, 1.8)}      # mean, sd
GRADE_DTI = {"A": (12.0, 4.0), "B": (15.0, 5.0), "C": (18.0, 5.5), "D": (21.0, 6.0),
             "E": (24.0, 6.0), "F": (27.0, 6.5), "G": (29.0, 6.5)}

MONTHS = []            # 2021-01 .. 2026-10
for y in YEARS:
    for m in range(1, 13):
        if y == 2026 and m > 10:
            break
        MONTHS.append((y, m))
N_MONTHS = len(MONTHS)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def main():
    # ------------------------------------------------------------------
    # 2. Issue dates: growing volume with mild seasonality + 2023 dip
    # ------------------------------------------------------------------
    t = np.arange(N_MONTHS)
    growth = 1.0 + 0.018 * t                                   # ~2%/month structural growth
    season = 1.0 + 0.05 * np.sin((np.array([m for _, m in MONTHS]) - 3) / 12 * 2 * np.pi)
    dip = np.where([(y == 2023 and m >= 4 and m <= 9) for y, m in MONTHS], 0.90, 1.0)
    weights = growth * season * dip
    weights = weights / weights.sum()
    month_idx = RNG.choice(N_MONTHS, size=N_BASE, p=weights)

    # ------------------------------------------------------------------
    # 3. Borrower + loan attributes
    # ------------------------------------------------------------------
    progress = month_idx / (N_MONTHS - 1)                       # 0 in 2021-01, 1 in 2026-10
    grade_p_today = GRADE_BASE + np.outer(progress, GRADE_IMPROVE)
    grade_p_today = np.clip(grade_p_today, 0.004, None)
    grade_p_today = grade_p_today / grade_p_today.sum(axis=1, keepdims=True)

    grade_idx = np.empty(N_BASE, dtype=int)
    for i in range(N_BASE):
        grade_idx[i] = RNG.choice(7, p=grade_p_today[i])
    grade = np.array(GRADES)[grade_idx]

    purpose = RNG.choice(PURPOSES, size=N_BASE, p=PURPOSE_P)
    state = RNG.choice(STATES, size=N_BASE, p=STATE_P)

    # Income: log-normal, median ~ $66k, long right tail
    income = np.exp(RNG.normal(np.log(66_000), 0.42, size=N_BASE))
    income = np.clip(income, 12_000, 1_400_000)

    rate = np.array([RNG.normal(*GRADE_RATE[g]) for g in grade])
    rate = np.clip(rate, 5.31, 30.95)
    dti = np.array([RNG.normal(*GRADE_DTI[g]) for g in grade])
    dti = np.clip(dti, 0.0, 45.0)

    fico = 795 - 21 * grade_idx - 0.9 * np.clip(dti - 15, 0, 30) + RNG.normal(0, 18, N_BASE)
    fico = np.clip(fico, 580, 835).round().astype(int)

    # Loan amount scales with income and purpose (small business / house larger)
    purpose_mult = {p: 1.0 for p in PURPOSES}
    purpose_mult.update({"small_business": 1.25, "house": 1.20, "debt_consolidation": 1.10,
                         "medical": 0.85, "vacation": 0.75, "wedding": 0.85, "car": 0.80})
    amt = income * 0.42 * np.array([purpose_mult[p] for p in purpose]) * RNG.lognormal(0, 0.25, N_BASE)
    amount = np.clip(amt, 1_000, 40_000) // 25 * 25

    # Term: 60-month share rises steeply with grade
    p60 = 0.14 + 0.085 * grade_idx
    term = np.where(RNG.random(N_BASE) < p60, 60, 36)

    emp_p = np.array([0.055, 0.075, 0.08, 0.085, 0.085, 0.09, 0.09, 0.09, 0.09, 0.085, 0.165])
    emp_p = emp_p / emp_p.sum()
    emp = RNG.choice(list(range(0, 11)), size=N_BASE, p=emp_p)
    home = RNG.choice(["MORTGAGE", "RENT", "OWN", "OTHER"], size=N_BASE,
                      p=[0.47, 0.44, 0.08, 0.01])

    # ------------------------------------------------------------------
    # 4. Default flag - logistic risk model (the "truth" the SQL will find)
    #    Intercept calibrated so the portfolio default rate lands ~13-15%,
    #    the range typical of public personal-loan data.
    # ------------------------------------------------------------------
    z = (-3.82
         + 0.42 * grade_idx                       # grade ladder: A -> G
         + 0.30 * (rate - 12.5) / 4               # price of risk
         + 0.34 * (dti - 16) / 8                  # leverage
         - 0.55 * (np.log(income) - np.log(66_000)) / 0.42   # income protection
         + 0.72 * (purpose == "small_business")   # small business is riskiest
         + 0.10 * (purpose == "medical")
         + 0.08 * (purpose == "moving")
         - 0.06 * (purpose == "wedding")
         + 0.28 * (term == 60)                    # longer term, more exposure
         + 0.30 * (emp == 0)                      # short employment history
         + np.array([np.log(STATE_RISK.get(s, 1.0)) for s in state])
         + RNG.normal(0, 0.35, N_BASE))           # unobserved factors
    default = (RNG.random(N_BASE) < sigmoid(z)).astype(int)

    # ------------------------------------------------------------------
    # 5. Assemble clean skeleton first, then inject realistic messiness
    #    (cast to string dtype first: a bank export arrives as text)
    # ------------------------------------------------------------------
    df = pd.DataFrame({
        "loan_id": np.arange(1, N_BASE + 1),
        "issue_date": [f"{MONTHS[i][0]}-{MONTHS[i][1]:02d}-15" for i in month_idx],
        "loan_amount": amount,
        "term": term,
        "int_rate": np.round(rate, 2),
        "grade": grade,
        "sub_grade": [f"{g}{RNG.integers(1, 6)}" for g in grade],
        "purpose": purpose,
        "annual_income": income.round(0),
        "emp_length": emp,
        "home_ownership": home,
        "dti": np.round(dti, 1),
        "state": state,
        "fico_score": fico,
        "default_flag": default,
    })

    n = len(df)
    for col in ("emp_length", "annual_income", "dti", "default_flag", "state",
                "grade", "purpose", "issue_date"):
        df[col] = df[col].astype("object")

    # 5a. String-typed numeric columns (as a bank export would deliver them)
    df["loan_amount"] = "$" + df["loan_amount"].map("{:,.0f}".format)
    df["int_rate"] = df["int_rate"].map("{:.2f}%".format)
    df["term"] = df["term"].astype(str) + " months"

    # 5b. Missing values
    miss_emp = RNG.random(n) < 0.025
    df.loc[miss_emp, "emp_length"] = RNG.choice(["n/a", ""], size=miss_emp.sum(), p=[0.6, 0.4])
    miss_inc = RNG.random(n) < 0.012
    df.loc[miss_inc, "annual_income"] = ""
    miss_dti = RNG.random(n) < 0.015
    df.loc[miss_dti, "dti"] = ""
    miss_target = RNG.random(n) < 0.004
    df.loc[miss_target, "default_flag"] = ""          # rows missing the target get dropped

    # 5c. Impossible / outlier values (entry errors)
    out_inc = RNG.choice(df.index[(df["annual_income"] != "")], size=14, replace=False)
    df.loc[out_inc, "annual_income"] = RNG.choice(
        ["$3,200,000", "$4,500,000", "$6,500,000", "$2,800,000"], size=14)
    bad_dti = RNG.choice(df.index[df["dti"] != ""], size=22, replace=False)
    df.loc[bad_dti, "dti"] = RNG.choice([-4.5, -1.0, 118.0, 165.0], size=22)

    # 5d. Inconsistent categories
    messy_grade = RNG.choice(df.index, size=60, replace=False)
    df.loc[messy_grade, "grade"] = df.loc[messy_grade, "grade"].str.lower().str.strip()
    messy_purpose = RNG.choice(df.index, size=90, replace=False)
    df.loc[messy_purpose, "purpose"] = (df.loc[messy_purpose, "purpose"]
                                        .str.replace("_", " ").str.title())
    full_state = {"California": "CA", "Texas": "TX", "Florida": "FL", "New York": "NY",
                  "Illinois": "IL", "Ohio": "OH", "Georgia": "GA"}
    messy_state = RNG.choice(df.index, size=45, replace=False)
    df.loc[messy_state, "state"] = RNG.choice(list(full_state), size=45)

    # 5e. Mixed date formats
    messy_date = RNG.choice(df.index, size=int(n * 0.03), replace=False)
    def to_mon_yyyy(s):
        y, m, _ = s.split("-")
        names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        return f"{names[int(m)-1]}-{y}"
    df.loc[messy_date, "issue_date"] = df.loc[messy_date, "issue_date"].map(to_mon_yyyy)

    # 5f. Duplicates: 120 exact copies + 60 re-issued rows
    dupes_exact = df.sample(120, random_state=7)
    dupes_fuzzy = df.sample(60, random_state=8).copy()
    dupes_fuzzy["loan_id"] = RNG.integers(90_000, 99_999, size=len(dupes_fuzzy))
    df = pd.concat([df, dupes_exact, dupes_fuzzy], ignore_index=True)
    df = df.sample(frac=1.0, random_state=9).reset_index(drop=True)   # shuffle rows

    # 5g. emp_length as wordy strings, like real exports
    emp_map = {0: "< 1 year", 10: "10+ years"}
    for k in range(1, 10):
        emp_map[k] = f"{k} years"
    df["emp_length"] = df["emp_length"].map(lambda v: emp_map.get(v, v) if v != "" else v)

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW_PATH, index=False)

    # ------------------------------------------------------------------
    # 6. Generation summary (for reports/cleaning_report.txt context)
    # ------------------------------------------------------------------
    print(f"Raw dataset written : {RAW_PATH}")
    print(f"Rows                : {len(df):,} (incl. {N_DUPES} injected duplicates)")
    print(f"Columns             : {len(df.columns)}")
    print(f"Issue dates         : Jan 2021 - Oct 2026 ({N_MONTHS} months)")
    true_rate = df.loc[df['default_flag'].astype(str).isin(['0', '1']), 'default_flag'].astype(int).mean()
    print(f"Default rate (base) : {true_rate:.1%}")


if __name__ == "__main__":
    main()
