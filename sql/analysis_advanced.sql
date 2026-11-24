-- ============================================================================
--  CREDITLENS - ADVANCED SQL ANALYSIS PACK
--  Queries 21-25: expert-level follow-ups to sql/analysis.sql (SQLite)
--
--  Same convention as analysis.sql: every query starts with the business
--  question and one line on WHY it matters to a lender, followed by ONE
--  statement. scripts/run_analysis.py executes this file right after
--  analysis.sql and saves qNN_<slug>.csv into sql/results/.
--
--  Queries 21-22: portfolio economics (vintage view, net money by grade)
--  Query  23    : loss concentration  (the Pareto of defaulted dollars)
--  Queries 24-25: model & policy      (scorecard lift over FICO, cutoff sweep)
--
--  Run: python scripts/run_analysis.py
-- ============================================================================

-- @query:21|vintage_year_by_grade
-- Q21. Does default risk inside each grade move with the origination year?
-- Why: the classic vintage view of a credit book. Each row is a origination
--      cohort, each column a grade. Reading down a column shows whether
--      underwriting in that grade got better or worse over time; reading
--      across a row shows whether the whole book was written in a riskier
--      year. A grade whose default rate doubles across cohorts is a
--      underwriting problem, not a macro problem.
SELECT substr(issue_month, 1, 4) AS issue_year,
       ROUND(SUM(CASE WHEN grade = 'A' THEN default_flag ELSE 0 END) * 100.0
             / SUM(CASE WHEN grade = 'A' THEN 1 ELSE 0 END), 2) AS grade_A_pct,
       ROUND(SUM(CASE WHEN grade = 'B' THEN default_flag ELSE 0 END) * 100.0
             / SUM(CASE WHEN grade = 'B' THEN 1 ELSE 0 END), 2) AS grade_B_pct,
       ROUND(SUM(CASE WHEN grade = 'C' THEN default_flag ELSE 0 END) * 100.0
             / SUM(CASE WHEN grade = 'C' THEN 1 ELSE 0 END), 2) AS grade_C_pct,
       ROUND(SUM(CASE WHEN grade = 'D' THEN default_flag ELSE 0 END) * 100.0
             / SUM(CASE WHEN grade = 'D' THEN 1 ELSE 0 END), 2) AS grade_D_pct,
       ROUND(SUM(CASE WHEN grade = 'E' THEN default_flag ELSE 0 END) * 100.0
             / SUM(CASE WHEN grade = 'E' THEN 1 ELSE 0 END), 2) AS grade_E_pct,
       ROUND(SUM(CASE WHEN grade = 'F' THEN default_flag ELSE 0 END) * 100.0
             / SUM(CASE WHEN grade = 'F' THEN 1 ELSE 0 END), 2) AS grade_F_pct,
       ROUND(SUM(CASE WHEN grade = 'G' THEN default_flag ELSE 0 END) * 100.0
             / SUM(CASE WHEN grade = 'G' THEN 1 ELSE 0 END), 2) AS grade_G_pct,
       COUNT(*)                                                 AS cohort_loans
FROM loans
GROUP BY substr(issue_month, 1, 4)
ORDER BY issue_year;

-- @query:22|net_economics_by_grade
-- Q22. After paying for its own defaults, does each grade still make money?
-- Why: default rate alone ignores interest income. A G-grade loan at 26.5%
--      can survive a higher default rate than a B-grade at 8%. Approximation
--      (stated openly): performing loans collect flat interest
--      amount * rate * years; defaulted loans lose the full principal, no
--      recoveries. Net margin per grade is what the pricing committee buys.
SELECT grade,
       COUNT(*)                                                   AS loans,
       ROUND(SUM(loan_amount), 0)                                 AS funded_usd,
       ROUND(SUM(CASE WHEN default_flag = 0
                      THEN loan_amount * int_rate / 100.0 * (term / 12.0)
                      ELSE 0 END), 0)                             AS interest_collected_usd,
       ROUND(SUM(CASE WHEN default_flag = 1
                      THEN loan_amount ELSE 0 END), 0)            AS lost_principal_usd,
       ROUND(SUM(CASE WHEN default_flag = 0
                      THEN loan_amount * int_rate / 100.0 * (term / 12.0)
                      ELSE 0 END)
             - SUM(CASE WHEN default_flag = 1
                        THEN loan_amount ELSE 0 END), 0)          AS net_usd,
       ROUND(100.0 * (SUM(CASE WHEN default_flag = 0
                              THEN loan_amount * int_rate / 100.0 * (term / 12.0)
                              ELSE 0 END)
                      - SUM(CASE WHEN default_flag = 1
                                 THEN loan_amount ELSE 0 END))
             / SUM(loan_amount), 2)                               AS net_margin_pct
FROM loans
GROUP BY grade
ORDER BY grade;

-- @query:23|loss_pareto_segments
-- Q23. Which purpose x grade segments burn the defaulted dollars - and how
--      concentrated are the losses?
-- Why: loss concentration drives capital planning. If a quarter of all
--      charge-offs sits in a handful of segments, a targeted policy change
--      (pricing or declining) removes far more risk than a portfolio-wide
--      rule. The running cumulative share is the classic Pareto read.
WITH seg AS (
    SELECT purpose || ' / grade ' || grade AS segment,
           SUM(default_flag)               AS defaults,
           SUM(CASE WHEN default_flag = 1
                    THEN loan_amount ELSE 0 END) AS default_usd
    FROM loans
    GROUP BY purpose || ' / grade ' || grade
),
ranked AS (
    SELECT segment,
           defaults,
           default_usd,
           ROUND(100.0 * default_usd
                 / SUM(default_usd) OVER (), 2)             AS share_pct,
           ROUND(100.0 * SUM(default_usd) OVER (ORDER BY default_usd DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                 / SUM(default_usd) OVER (), 2)             AS cum_share_pct
    FROM seg
    WHERE default_usd > 0
)
SELECT ROW_NUMBER() OVER (ORDER BY default_usd DESC) AS rank_no,
       segment,
       defaults,
       ROUND(default_usd, 0)                          AS default_usd,
       share_pct,
       cum_share_pct
FROM ranked
ORDER BY default_usd DESC
LIMIT 25;

-- @query:24|scorecard_lift_within_fico
-- Q24. Does the scorecard know something FICO does not?
-- Why: the scorecard only replaces FICO if it adds signal ON TOP of FICO.
--      Within identical FICO bands we split loans at the scorecard-score
--      median (NTILE(2), no hard-coded thresholds). If the below-median
--      half defaults clearly more than the above-median half in the SAME
--      FICO band, the scorecard carries incremental information and both
--      should run together.
WITH banded AS (
    SELECT CASE
               WHEN fico_score < 600 THEN 'a <600'
               WHEN fico_score < 640 THEN 'b 600-639'
               WHEN fico_score < 680 THEN 'c 640-679'
               WHEN fico_score < 720 THEN 'd 680-719'
               ELSE 'e 720+'
           END AS fico_band,
           default_flag,
           credit_score
    FROM loans
    JOIN loan_scores ON loan_scores.loan_id = loans.loan_id
),
halved AS (
    SELECT fico_band,
           default_flag,
           NTILE(2) OVER (PARTITION BY fico_band
                          ORDER BY credit_score) AS score_half,
           COUNT(*) OVER (PARTITION BY fico_band) AS band_loans
    FROM banded
)
SELECT fico_band,
       CASE WHEN score_half = 1 THEN 'below scorecard median'
            ELSE 'above scorecard median' END AS scorecard_half,
       COUNT(*)                               AS loans,
       ROUND(100.0 * SUM(default_flag) / COUNT(*), 2) AS default_rate_pct,
       band_loans
FROM halved
GROUP BY fico_band,
         CASE WHEN score_half = 1 THEN 'below scorecard median'
              ELSE 'above scorecard median' END,
         band_loans
ORDER BY fico_band, scorecard_half;

-- @query:25|cutoff_sweep_policy
-- Q25. What would a different approval cutoff do to the portfolio?
-- Why: the production cutoff (570) caught 72.7% of defaults on the holdout
--      test set while funding ~64.5% of applicants - but a cutoff is a
--      business choice, not a law. Sweeping 520 to 620 shows the whole
--      frontier on the full book: defaults declined (caught), defaults
--      that still slip into the approved zone (leaked), bad rate among
--      approved loans and funded dollars left on the table. This is the
--      portfolio-wide twin of the dashboard's What-If Simulator page.
--      "caught" follows the risk_model.py definition: default with score
--      BELOW the cutoff = declined before funding.
WITH joined AS (
    SELECT l.loan_amount,
           l.default_flag,
           s.credit_score
    FROM loans l
    JOIN loan_scores s ON s.loan_id = l.loan_id
),
cutoffs(c) AS (
    SELECT 520 UNION ALL SELECT 530 UNION ALL SELECT 540 UNION ALL SELECT 550
    UNION ALL SELECT 560 UNION ALL SELECT 570 UNION ALL SELECT 580
    UNION ALL SELECT 590 UNION ALL SELECT 600 UNION ALL SELECT 610
    UNION ALL SELECT 620
),
tot AS (
    SELECT COUNT(*)          AS n_all,
           SUM(loan_amount)  AS usd_all,
           SUM(default_flag) AS def_all
    FROM joined
)
SELECT c                                                                     AS cutoff,
       CASE WHEN c = 570 THEN 'production' ELSE '' END                       AS policy,
       ROUND(SUM(CASE WHEN credit_score >= c THEN 1 ELSE 0 END)
             * 100.0 / t.n_all, 1)                                           AS approval_pct,
       ROUND(SUM(CASE WHEN credit_score >= c
                      THEN loan_amount ELSE 0 END), 0)                       AS approved_usd,
       ROUND(SUM(CASE WHEN credit_score >= c
                      THEN default_flag ELSE 0 END) * 100.0
             / SUM(CASE WHEN credit_score >= c THEN 1 ELSE 0 END), 2)        AS bad_rate_approved_pct,
       ROUND(SUM(CASE WHEN credit_score < c
                      THEN default_flag ELSE 0 END) * 100.0
             / t.def_all, 1)                                                 AS defaults_caught_pct,
       ROUND(SUM(CASE WHEN credit_score >= c
                      THEN default_flag ELSE 0 END) * 100.0
             / t.def_all, 1)                                                 AS defaults_leaked_pct,
       ROUND(100.0 * (t.usd_all
             - SUM(CASE WHEN credit_score >= c
                        THEN loan_amount ELSE 0 END)) / t.usd_all, 1)         AS funded_left_pct
FROM cutoffs
CROSS JOIN joined
CROSS JOIN tot t
GROUP BY c, t.n_all, t.usd_all, t.def_all
ORDER BY c;
