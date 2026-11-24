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
