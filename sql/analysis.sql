-- ============================================================================
--  CREDITLENS - SQL ANALYSIS
--  20 business questions on the loans + loan_scores tables (SQLite)
--
--  Convention: every query starts with the business question and one line on
--  WHY the question matters to a lender. A query without a reason is just
--  typing practice.
--
--  Queries 01-16: the portfolio questions (loans table)
--  Queries 17-20: the model questions   (JOIN loan_scores - the scorecard
--                 built by scripts/risk_model.py; NTILE, window frames and
--                 ROW_NUMBER PARTITION BY, the SQL of model monitoring)
--
--  Run all queries:      python scripts/run_analysis.py
--  Run one query here:   sqlite3 sql/loans.db
-- ============================================================================

-- @query:01|overall_default_rate
-- Q01. What is the overall default rate of the portfolio?
-- Why: the single headline number a credit risk committee starts every
--      meeting with - it is the baseline every segment below is compared to.
SELECT COUNT(*)                                        AS total_loans,
       SUM(loan_amount)                                AS total_funded_usd,
       ROUND(100.0 * AVG(default_flag), 2)             AS default_rate_pct,
       SUM(default_flag)                               AS defaulted_loans
FROM loans;

-- @query:02|default_rate_by_grade
-- Q02. How does the default rate move from grade A to grade G?
-- Why: grade is the bank's own risk rating. If default risk did not rise
--      with grade, the rating system itself would be broken.
SELECT grade,
       COUNT(*)                            AS loans,
       SUM(default_flag)                   AS defaults,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct
FROM loans
GROUP BY grade
ORDER BY grade;

-- @query:03|default_rate_by_purpose
-- Q03. Which loan purposes default most, and which are safest?
-- Why: purpose is a decision the borrower makes - some purposes
--      (small business) carry structural risk, others (wedding) do not.
--      Pricing and approval policy differ by purpose.
SELECT purpose,
       COUNT(*)                            AS loans,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct,
       ROUND(AVG(loan_amount), 0)          AS avg_amount_usd
FROM loans
GROUP BY purpose
ORDER BY default_rate_pct DESC;

-- @query:04|default_rate_by_income_band
-- Q04. How does default risk change across income bands?
-- Why: income is the primary repayment source. Lenders use banding to set
--      debt limits and to target marketing at segments that can afford credit.
SELECT CASE
           WHEN annual_income < 25000  THEN '0-25k'
           WHEN annual_income < 50000  THEN '25-50k'
           WHEN annual_income < 75000  THEN '50-75k'
           ELSE '75k+'
       END                                AS income_band,
       COUNT(*)                           AS loans,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct
FROM loans
GROUP BY income_band
ORDER BY CASE income_band
             WHEN '0-25k'  THEN 1
             WHEN '25-50k' THEN 2
             WHEN '50-75k' THEN 3
             ELSE 4
         END;

-- @query:05|loan_amount_default_vs_paid
-- Q05. Do defaulted loans borrow more than performing loans on average?
-- Why: if defaults are also the biggest loans, losses are compounded - risk
--      frequency AND severity move together. This drives expected-loss maths.
SELECT CASE default_flag WHEN 1 THEN 'Defaulted' ELSE 'Performed' END AS outcome,
       COUNT(*)                       AS loans,
       ROUND(AVG(loan_amount), 0)     AS avg_loan_amount_usd,
       ROUND(AVG(loan_amount) * COUNT(*), 0) AS total_amount_usd
FROM loans
GROUP BY default_flag
ORDER BY default_flag DESC;

-- @query:06|int_rate_default_vs_paid
-- Q06. Do defaulted loans carry higher interest rates?
-- Why: rate is the price of risk. A gap here shows the pricing ladder
--      working (riskier borrowers pay more) - and quantifies how much more
--      the bank charged on loans it still lost.
SELECT CASE default_flag WHEN 1 THEN 'Defaulted' ELSE 'Performed' END AS outcome,
       COUNT(*)                    AS loans,
       ROUND(AVG(int_rate), 2)     AS avg_rate_pct,
       ROUND(MIN(int_rate), 2)     AS min_rate_pct,
       ROUND(MAX(int_rate), 2)     AS max_rate_pct
FROM loans
GROUP BY default_flag
ORDER BY default_flag DESC;

-- @query:07|default_rate_by_dti_band
-- Q07. How does default risk change with debt-to-income (DTI)?
-- Why: DTI measures how stretched a borrower already is. Above ~30% the
--      borrower spends nearly a third of income on debt - a classic
--      stress threshold in consumer credit policy.
SELECT CASE
           WHEN dti < 10  THEN '0-10 (low)'
           WHEN dti < 20  THEN '10-20'
           WHEN dti < 30  THEN '20-30'
           ELSE '30+ (high)'
       END                                AS dti_band,
       COUNT(*)                           AS loans,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct
FROM loans
GROUP BY dti_band
ORDER BY CASE dti_band
             WHEN '0-10 (low)'  THEN 1
             WHEN '10-20'       THEN 2
             WHEN '20-30'       THEN 3
             ELSE 4
         END;

-- @query:08|top10_states_default_count
-- Q08. Which ten states have the highest number of defaulted loans?
-- Why: absolute counts show where the bank is actually losing money TODAY -
--      big states dominate counts even at average risk. Collections and
--      regional risk teams are staffed on counts, not percentages.
SELECT state,
       COUNT(*)                            AS total_loans,
       SUM(default_flag)                   AS defaults,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct,
       SUM(CASE WHEN default_flag = 1 THEN loan_amount ELSE 0 END) AS defaulted_usd
FROM loans
GROUP BY state
ORDER BY defaults DESC
LIMIT 10;

-- @query:09|loan_amount_distribution_by_grade
-- Q09. How is the loan amount distributed inside each grade?
-- Why: before comparing "average loan by grade" anyone sensible checks the
--      spread - ranges and tails expose skew that averages hide.
SELECT grade,
       COUNT(*)                                               AS loans,
       ROUND(MIN(loan_amount), 0)                             AS min_usd,
       ROUND(AVG(loan_amount), 0)                             AS avg_usd,
       ROUND(MAX(loan_amount), 0)                             AS max_usd,
       ROUND(100.0 * SUM(CASE WHEN loan_amount >= 25000
                              THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_loans_25k_plus
FROM loans
GROUP BY grade
ORDER BY grade;

-- @query:10|emp_length_default_vs_paid
-- Q10. Do borrowers with shorter employment history default more?
-- Why: employment length is a proxy for income stability. If it matters,
--      underwriting should weight it; if not, asking for it just adds friction.
SELECT CASE default_flag WHEN 1 THEN 'Defaulted' ELSE 'Performed' END AS outcome,
       COUNT(*)                                AS loans,
       ROUND(AVG(emp_length), 2)               AS avg_emp_years,
       ROUND(100.0 * SUM(CASE WHEN emp_length = 0 THEN 1 ELSE 0 END)
             / COUNT(*), 1)                    AS pct_under_1_year_job
FROM loans
GROUP BY default_flag
ORDER BY default_flag DESC;

-- @query:11|purpose_avg_loan_amount
-- Q11. Which purpose takes the largest average loan?
-- Why: exposure per loan differs by purpose. Two portfolios with the same
--      default rate can have very different loss severity if average tickets
--      differ - this feeds concentration limits.
SELECT purpose,
       COUNT(*)                        AS loans,
       ROUND(AVG(loan_amount), 0)      AS avg_amount_usd,
       ROUND(SUM(loan_amount), 0)      AS total_funded_usd
FROM loans
GROUP BY purpose
ORDER BY avg_amount_usd DESC;

-- @query:12|monthly_volume_and_default
-- Q12. How did monthly loan volume and default rate move over time?
-- Why: growth vs quality is the classic portfolio tension. If volume grows
--      while the default rate falls, credit policy is holding the line.
SELECT issue_month,
       COUNT(*)                            AS loans_funded,
       ROUND(SUM(loan_amount), 0)          AS funded_usd,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct
FROM loans
GROUP BY issue_month
ORDER BY issue_month;

-- @query:13|default_rate_by_term
-- Q13. Do 60-month loans default more than 36-month loans?
-- Why: longer terms mean smaller instalments (more affordable) but more time
--      for things to go wrong. Lenders need to know which effect wins.
SELECT term,
       COUNT(*)                            AS loans,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct,
       ROUND(AVG(loan_amount), 0)          AS avg_amount_usd
FROM loans
GROUP BY term
ORDER BY term;

-- @query:14|default_rate_by_sub_grade
-- Q14. Does risk rise smoothly across all 35 sub-grades (A1..G5)?
-- Why: a smooth ladder proves the rating is well-ordered. Steps or zig-zags
--      would mean two sub-grades are effectively the same risk - and priced
--      wrong.
SELECT sub_grade,
       COUNT(*)                            AS loans,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct
FROM loans
GROUP BY sub_grade
ORDER BY CASE sub_grade
             WHEN 'A1' THEN 1  WHEN 'A2' THEN 2  WHEN 'A3' THEN 3  WHEN 'A4' THEN 4  WHEN 'A5' THEN 5
             WHEN 'B1' THEN 6  WHEN 'B2' THEN 7  WHEN 'B3' THEN 8  WHEN 'B4' THEN 9  WHEN 'B5' THEN 10
             WHEN 'C1' THEN 11 WHEN 'C2' THEN 12 WHEN 'C3' THEN 13 WHEN 'C4' THEN 14 WHEN 'C5' THEN 15
             WHEN 'D1' THEN 16 WHEN 'D2' THEN 17 WHEN 'D3' THEN 18 WHEN 'D4' THEN 19 WHEN 'D5' THEN 20
             WHEN 'E1' THEN 21 WHEN 'E2' THEN 22 WHEN 'E3' THEN 23 WHEN 'E4' THEN 24 WHEN 'E5' THEN 25
             WHEN 'F1' THEN 26 WHEN 'F2' THEN 27 WHEN 'F3' THEN 28 WHEN 'F4' THEN 29 WHEN 'F5' THEN 30
             ELSE 31
         END;

-- @query:15|high_risk_segment
-- Q15. How big and how dangerous is the "grade E-G AND DTI >= 30" segment?
-- Why: this is the segment an underwriting tightening would hit first.
--      Sizing it (share of loans vs share of losses) turns a policy debate
--      into arithmetic.
SELECT COUNT(*)                                                   AS segment_loans,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM loans), 1)  AS pct_of_portfolio,
       ROUND(100.0 * AVG(default_flag), 2)                        AS segment_default_rate_pct,
       SUM(default_flag)                                          AS segment_defaults,
       ROUND(100.0 * SUM(default_flag) /
             (SELECT SUM(default_flag) FROM loans), 1)            AS pct_of_all_defaults,
       ROUND(SUM(loan_amount), 0)                                 AS segment_funded_usd,
       ROUND(100.0 * SUM(CASE WHEN default_flag = 1 THEN loan_amount ELSE 0 END) /
             (SELECT SUM(CASE WHEN default_flag = 1 THEN loan_amount ELSE 0 END)
              FROM loans), 1)                                     AS pct_of_defaulted_usd
FROM loans
WHERE grade IN ('E', 'F', 'G')
  AND dti >= 30;

-- @query:16|default_rate_by_home_ownership
-- Q16. Do homeowners default less than renters?
-- Why: a mortgage is collateral-adjacent - owners have equity to protect and
--      a stronger credit file. If OWN/MORTGAGE risk is visibly lower, the
--      variable earns its place in underwriting.
SELECT home_ownership,
       COUNT(*)                            AS loans,
       ROUND(100.0 * AVG(default_flag), 2) AS default_rate_pct,
       ROUND(AVG(annual_income), 0)        AS avg_income_usd
FROM loans
GROUP BY home_ownership
ORDER BY default_rate_pct DESC;

-- ============================================================================
--  MODEL QUERIES (17-20) - the credit scorecard, interrogated in SQL
--  These join `loans` to `loan_scores` (built by scripts/risk_model.py) and
--  showcase window functions: NTILE, running SUM() OVER, and ROW_NUMBER()
--  PARTITION BY - the SQL every model-monitoring pack is written in.
-- ============================================================================

-- @query:17|scorecard_decile_ranking
-- Q17. Does the scorecard actually rank risk? Decile analysis with NTILE().
-- Why: a score is only useful if the default rate rises monotonically from
--      the safest decile to the riskiest. NTILE(10) OVER (ORDER BY credit_score)
--      is the classic risk-ranking report; the predicted-vs-actual columns are
--      the calibration check a model must pass before deployment.
WITH ranked AS (
    SELECT l.default_flag, l.loan_amount, s.credit_score, s.pd_default,
           NTILE(10) OVER (ORDER BY s.credit_score) AS decile  -- 1 = lowest score
    FROM loans l JOIN loan_scores s ON s.loan_id = l.loan_id
)
SELECT decile,
       COUNT(*)                                          AS loans,
       MIN(credit_score)                                 AS score_from,
       MAX(credit_score)                                 AS score_to,
       ROUND(100.0 * AVG(default_flag), 2)               AS actual_default_pct,
       ROUND(100.0 * AVG(pd_default), 2)                 AS predicted_default_pct,
       ROUND(SUM(loan_amount), 0)                        AS funded_usd
FROM ranked
GROUP BY decile
ORDER BY decile;

-- @query:18|monthly_default_running_total
-- Q18. How did risk accumulate as the book grew? (running totals, no self-join)
-- Why: SUM() OVER (ORDER BY issue_month) turns monthly rows into the running
--      book size and running defaults in one pass - the SQL behind every
--      cumulative-loss / vintage-exposure chart a credit committee reads.
--      The final row's cumulative_default_pct is the all-in portfolio rate.
SELECT issue_month,
       COUNT(*)                          AS loans_in_month,
       SUM(COUNT(*))    OVER w           AS loans_cumulative,
       SUM(default_flag)                  AS defaults_in_month,
       SUM(SUM(default_flag)) OVER w     AS defaults_cumulative,
       ROUND(100.0 * SUM(SUM(default_flag)) OVER w
             / SUM(COUNT(*)) OVER w, 2)  AS cumulative_default_pct
FROM loans
GROUP BY issue_month
WINDOW w AS (ORDER BY issue_month)
ORDER BY issue_month;

-- @query:19|expected_vs_realized_loss_by_grade
-- Q19. Is the model's expected loss close to what actually happened?
-- Why: EL = PD x EAD x LGD is the number banks provision capital against.
--      With EAD = loan amount and LGD = 100% (unsecured personal loans: the
--      full principal is at risk), compare model-expected dollars to realized
--      defaulted dollars per grade. A model that systematically under-predicts
--      EL is a model that loses money - this is the calibration check that
--      matters in dollars, and it doubles as a deviation report by grade.
WITH el AS (
    SELECT l.grade,
           SUM(l.loan_amount * s.pd_default)                    AS expected_loss_usd,
           SUM(CASE WHEN l.default_flag = 1 THEN l.loan_amount
                    ELSE 0 END)                                 AS realized_loss_usd
    FROM loans l JOIN loan_scores s ON s.loan_id = l.loan_id
    GROUP BY l.grade
)
SELECT grade,
       ROUND(expected_loss_usd, 0)                                  AS expected_loss_usd,
       ROUND(realized_loss_usd, 0)                                  AS realized_loss_usd,
       ROUND(100.0 * realized_loss_usd / expected_loss_usd - 100.0, 1) AS realized_vs_expected_pct
FROM el
ORDER BY grade;

-- @query:20|riskiest_purpose_by_state
-- Q20. Which purpose is riskiest inside each state? (top-1 per group)
-- Why: ROW_NUMBER() OVER (PARTITION BY state ORDER BY ...) answers "the worst
--      X within each group" in one pass - no correlated subquery. Regional
--      pockets of purpose risk are exactly the finding a pricing review acts
--      on. Only purposes with 30+ loans per state count, and only states with
--      at least 3 qualifying purposes are ranked (tiny cells are noise).
WITH purpose_by_state AS (
    SELECT state, purpose, COUNT(*) AS loans,
           ROUND(100.0 * AVG(default_flag), 1) AS default_rate_pct
    FROM loans
    GROUP BY state, purpose
    HAVING COUNT(*) >= 30
),
ranked AS (
    SELECT state, purpose, loans, default_rate_pct,
           ROW_NUMBER() OVER (PARTITION BY state ORDER BY default_rate_pct DESC,
                              loans DESC)                    AS rn,
           COUNT(*)     OVER (PARTITION BY state)            AS qualifying_purposes
    FROM purpose_by_state
)
SELECT state, purpose, loans, default_rate_pct, qualifying_purposes
FROM ranked
WHERE rn = 1 AND qualifying_purposes >= 3
ORDER BY default_rate_pct DESC, state;
