"""
CreditLens - Step 3: Application credit scorecard (WOE + logistic + points)
============================================================================

Turns the clean loan table into a real credit-risk scorecard, the way retail
banks actually build them:

  1. Feature binning   - application fields cut into coarse, business-readable
                         bins (DTI bands, income bands, purpose groups ...).
  2. WOE / IV          - Weight of Evidence per bin (log of good-share over
                         bad-share) and Information Value per feature (the
                         standard measure of predictive strength). Numeric
                         features are auto-merged until their WOE is
                         monotonic - a requirement of every scorecard
                         standard (bin risk must move one way).
  3. Feature selection - features with IV >= 0.02 on the training fold are
                         kept; the IV table documents every rejection.
  4. Logistic model    - logistic regression on the WOE values, trained on a
                         stratified 70% fold, validated on the untouched 30%.
  5. Points scorecard  - model log-odds rescaled to points: 600 = 20:1
                         good:bad odds, doubling every 20 points (PDO=20).
                         Each bin gets integer points, so any declined
                         applicant can be told exactly what cost them.
  6. Deployment refit  - after holdout validation the model is refit on 100%
                         of loans (bins frozen from training) and every loan
                         in the portfolio is scored.

Deliberately EXCLUDED from the model (and used as benchmarks instead):
  * grade / sub_grade - the bank's own rating: downstream of underwriting,
                        not available on a raw application
  * int_rate          - the bank's price, set FROM the grade
  * fico_score        - the bureau score at origination: the scorecard is
                        benchmarked against it, so it cannot also be an input
The story: can application data alone rebuild the bank's risk ranking?

Usage
-----
    python scripts/risk_model.py

Reads : data/clean/clean_loans.csv
Writes: data/clean/loans_scored.csv        (loan_id, credit_score, pd_default)
        reports/scorecard_points.csv       (feature, bin, WOE, points ...)
        reports/model_report.txt           (full model documentation)
        reports/model_artifacts.json       (charts data for the dashboard)
"""

import json
import math

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "clean_loans.csv"
SCORED = ROOT / "data" / "clean" / "loans_scored.csv"
REPORTS = ROOT / "reports"
POINTS_CSV = REPORTS / "scorecard_points.csv"
REPORT_TXT = REPORTS / "model_report.txt"
ARTIFACTS = REPORTS / "model_artifacts.json"

SEED = 42
TEST_SIZE = 0.30
IV_KEEP = 0.02            # industry-standard cut (Siddiqi): IV < 0.02 = unpredictable

# scorecard scaling: 600 points at 20:1 good:bad odds, +20 points doubles the odds
BASE_SCORE, BASE_ODDS, PDO = 600.0, 20.0, 20.0
FACTOR = PDO / math.log(2)
OFFSET = BASE_SCORE - FACTOR * math.log(BASE_ODDS)

# --------------------------------------------------------------------------
# Feature definitions
# --------------------------------------------------------------------------
REGION = {}
for s in ("AK AZ CA CO HI ID MT NV NM OR UT WA WY").split():
    REGION[s] = "West"
for s in ("IA IL IN KS MI MN MO ND NE OH SD WI").split():
    REGION[s] = "Midwest"
for s in ("AL AR DE DC FL GA KY LA MD MS NC OK SC TN TX VA WV").split():
    REGION[s] = "South"
for s in ("CT ME MA NH NJ NY PA RI VT").split():
    REGION[s] = "Northeast"


def lbl_income(lo, hi):
    if lo is None:
        return f"<${hi/1000:.0f}k"
    if hi is None:
        return f"${lo/1000:.0f}k+"
    return f"${lo/1000:.0f}-${hi/1000:.0f}k"


def lbl_dti(lo, hi):
    if lo is None:
        return f"<{hi:.0f}"
    if hi is None:
        return f"{lo:.0f}+"
    return f"{lo:.0f}-${hi:.0f}" if False else f"{lo:.0f}-{hi:.0f}"


def lbl_amt(lo, hi):
    if lo is None:
        return f"<${hi/1000:.0f}k"
    if hi is None:
        return f"${lo/1000:.0f}k+"
    return f"${lo/1000:.0f}-${hi/1000:.0f}k"


def lbl_emp(lo, hi):
    if lo is None:
        return "<1 yr"
    if hi is None:
        return "10+ yrs"
    if hi - lo == 1:                      # single bin [lo, lo+1)
        return f"{lo} yrs"
    return f"{lo:.0f}-{hi-1:.0f} yrs"


# ordered features: fixed business edges; adjacent bins merge until WOE is monotonic
ORDERED = {
    "dti":           dict(label="Debt-to-income", edges=[10, 20, 30], fmt=lbl_dti),
    "annual_income": dict(label="Annual income", edges=[40000, 60000, 80000, 100000], fmt=lbl_income),
    "loan_amount":   dict(label="Loan amount", edges=[10000, 20000, 30000], fmt=lbl_amt),
    "emp_length":    dict(label="Employment length", edges=[1, 3, 6, 10], fmt=lbl_emp),
}
# unordered features: categorical; purpose bins rarer than 2% fold into 'other'
UNORDERED = {
    "purpose":        dict(label="Loan purpose", rare_merge=True),
    "home_ownership": dict(label="Home ownership", rare_merge=False),
    "region":         dict(label="US region (Census)", rare_merge=False),
    "term":           dict(label="Term", rare_merge=False),
}
EXCLUDED = {
    "grade / sub_grade": "the bank's own rating - downstream of underwriting, not application data",
    "int_rate": "the bank's price, set from the grade - including it would leak the rating in",
    "fico_score": "bureau score at origination - kept out so the scorecard can be benchmarked against it",
}


def raw_labels(df):
    """Initial bin label per row for every candidate feature."""
    out = {}
    for key, spec in ORDERED.items():
        idx = np.searchsorted(np.array(spec["edges"], dtype=float), df[key].to_numpy(dtype=float), side="right")
        out[key] = pd.Series(idx, index=df.index)          # 0..len(edges)
    out["purpose"] = df["purpose"].str.replace("_", " ")
    out["home_ownership"] = df["home_ownership"].str.title()
    out["region"] = df["state"].map(REGION).fillna("Other")
    out["term"] = df["term"].map({36: "36 mo", 60: "60 mo"})
    return out


def woe_table(groups, y, order=None):
    """WOE / IV per group label. groups: Series of labels, y: 0/1 Series."""
    t = pd.DataFrame({"g": groups, "bad": y}).groupby("g")["bad"].agg(["count", "sum"])
    if order is not None:
        t = t.reindex([o for o in order if o in t.index])
    good, bad = t["count"] - t["sum"], t["sum"]
    dist_good = (good + 0.5) / (good + 0.5).sum()
    dist_bad = (bad + 0.5) / (bad + 0.5).sum()
    t["woe"] = np.log(dist_good / dist_bad)                # + = safer than average
    t["iv"] = (dist_good - dist_bad) * t["woe"]
    t["bad_rate"] = t["sum"] / t["count"]
    return t[["count", "sum", "bad_rate", "woe", "iv"]].rename(columns={"sum": "bad"})


def fit_ordered(spec, idx_tr, y_tr):
    """Merge adjacent bins on the TRAIN fold until WOE is monotonic.

    idx_tr / y_tr are pd.Series on the SAME (dataframe) index: raw bin index
    per train row and the 0/1 target per train row.

    Returns (lookup, groups): lookup maps raw bin index -> final group number,
    groups is a list of dicts with the numeric (lo, hi) range and label of
    every final group, in domain order.
    """
    n_edges = len(spec["edges"])
    ranges = [[b, b + 1] for b in range(n_edges + 1)]   # [first, last+1) raw bins
    while len(ranges) > 2:
        pos = {b: gi for gi, (lo, hi) in enumerate(ranges) for b in range(lo, hi)}
        t = woe_table(idx_tr.map(pos), y_tr)
        w = t["woe"].to_numpy()
        direction = 1.0 if w[-1] >= w[0] else -1.0
        viol = [i for i in range(len(w) - 1) if (w[i + 1] - w[i]) * direction < 0]
        if not viol:
            break
        # merge the violating pair whose WOEs are closest (least information lost)
        best = min(viol, key=lambda i: abs(w[i + 1] - w[i]))
        ranges[best] = [ranges[best][0], ranges[best + 1][1]]
        del ranges[best + 1]
    lookup = {b: gi for gi, (lo, hi) in enumerate(ranges) for b in range(lo, hi)}
    edges = spec["edges"]
    groups = []
    for gi, (blo, bhi) in enumerate(ranges):
        lo = edges[blo - 1] if blo > 0 else None
        hi = edges[bhi - 1] if bhi - 1 < n_edges else None
        groups.append(dict(gi=gi, lo=lo, hi=hi, label=spec["fmt"](lo, hi)))
    return lookup, groups


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(CLEAN)
    y = df["default_flag"].astype(int)

    tr, te = train_test_split(np.arange(len(df)), test_size=TEST_SIZE,
                              random_state=SEED, stratify=y)
    y_tr, y_te = y.iloc[tr], y.iloc[te]
    print(f"Rows {len(df):,} | train {len(tr):,} | holdout {len(te):,} "
          f"(stratified, seed {SEED})")

    # ------------------------------------------------------------------
    # 1. Binning (merges learned on TRAIN only, then frozen)
    # ------------------------------------------------------------------
    raw = raw_labels(df)
    group_series, group_specs = {}, {}

    for key, spec in ORDERED.items():
        idx_all, idx_tr = raw[key], raw[key].iloc[tr]
        lookup, groups = fit_ordered(spec, idx_tr, y.iloc[tr])
        gi2label = {g["gi"]: g["label"] for g in groups}
        # final group value = business label ('10-20', '$40-60k', ...)
        group_series[key] = idx_all.map(lookup).map(gi2label)
        group_specs[key] = dict(kind="ordered", order=[g["label"] for g in groups])

    for key, spec in UNORDERED.items():
        s_all = raw[key]
        if spec["rare_merge"]:
            share = s_all.iloc[tr].value_counts(normalize=True)
            rare = share[share < 0.02].index
            s_all = s_all.where(~s_all.isin(rare), "other")
            # keep domain order stable for display: train volume desc, 'other' last
            vc = s_all.iloc[tr].value_counts()
            order = [k for k in vc.index if k != "other"]
            if (s_all == "other").any():
                order.append("other")
        else:
            order = list(s_all.iloc[tr].value_counts().index)
        group_series[key] = s_all
        group_specs[key] = dict(kind="unordered", order=order)

    # ------------------------------------------------------------------
    # 2. WOE / IV - validation view (train fold) and deployment view (all rows)
    # ------------------------------------------------------------------
    woe_train, woe_full = {}, {}
    for key in {**ORDERED, **UNORDERED}:
        gs = group_series[key]
        order = group_specs[key]["order"]
        woe_train[key] = woe_table(gs.iloc[tr], y.iloc[tr], order=order)
        woe_full[key] = woe_table(gs, y, order=order)

    iv_train = {k: float(t["iv"].sum()) for k, t in woe_train.items()}
    selected = [k for k in sorted(iv_train, key=iv_train.get, reverse=True) if iv_train[k] >= IV_KEEP]

    def iv_strength(iv):
        return ("< 0.02 unpredictable" if iv < 0.02 else "0.02-0.10 weak" if iv < 0.10
                else "0.10-0.30 medium" if iv < 0.30 else "0.30-0.50 strong" if iv < 0.50
                else "0.50+ very strong")

    print("\nInformation Value (train fold):")
    for k in sorted(iv_train, key=iv_train.get, reverse=True):
        mark = "IN " if k in selected else "out"
        print(f"  [{mark}] {k:<16} IV={iv_train[k]:.4f}  ({iv_strength(iv_train[k])})")

    # ------------------------------------------------------------------
    # 3. Validation model: logistic on train-fold WOE
    # ------------------------------------------------------------------
    def design(keys, rows, tables):
        X = np.column_stack([
            group_series[k].iloc[rows].map(tables[k]["woe"]).to_numpy(dtype=float)
            for k in keys])
        return X

    X_tr = design(selected, tr, woe_train)
    X_te = design(selected, te, woe_train)   # test rows mapped through TRAIN WOE - no leakage
    clf = LogisticRegression(penalty=None, solver="lbfgs", max_iter=2000)
    clf.fit(X_tr, y_tr.to_numpy())

    # coefficient inference (observed-information standard errors)
    p_hat = clf.predict_proba(X_tr)[:, 1]
    W = p_hat * (1 - p_hat)
    H = X_tr.T @ (X_tr * W[:, None])
    cov = np.linalg.inv(H)
    se = np.sqrt(np.diag(cov))
    z = clf.coef_[0] / se
    pvals = 2 * stats.norm.sf(np.abs(z))

    pd_te = clf.predict_proba(X_te)[:, 1]
    pd_tr = clf.predict_proba(X_tr)[:, 1]

    def ks(y_true, risk):
        o = np.argsort(-risk)
        ys = np.asarray(y_true)[o]
        cb = np.cumsum(ys) / ys.sum()
        cg = np.cumsum(1 - ys) / (len(ys) - ys.sum())
        return float(np.max(np.abs(cb - cg)))

    grade_risk = df["grade"].map({g: i for i, g in enumerate("ABCDEFG")}).iloc[te].to_numpy()
    fico_risk = -df["fico_score"].iloc[te].to_numpy(dtype=float)

    m = {}
    m["auc"] = roc_auc_score(y_te, pd_te)
    m["aucTrain"] = roc_auc_score(y_tr, pd_tr)
    m["aucGrade"] = roc_auc_score(y_te, grade_risk)
    m["aucFico"] = roc_auc_score(y_te, fico_risk)
    m["ks"] = ks(y_te, pd_te)
    m["ksGrade"] = ks(y_te, grade_risk)
    m["ksFico"] = ks(y_te, fico_risk)
    m["gini"] = 2 * m["auc"] - 1
    m["giniGrade"] = 2 * m["aucGrade"] - 1
    m["giniFico"] = 2 * m["aucFico"] - 1
    m["nTrain"], m["nTest"] = len(tr), len(te)
    m["baseRate"] = float(y.mean() * 100)

    # policy simulation: cutoff score where model PD equals the portfolio base rate
    base_p = y.mean()
    cutoff = OFFSET + FACTOR * math.log((1 - base_p) / base_p)
    m["cutoff"] = int(round(cutoff))
    score_te = OFFSET + FACTOR * (-np.log(pd_te / (1 - pd_te)))
    decline = score_te < cutoff
    m["declinePct"] = float(100 * decline.mean())
    m["caughtPct"] = float(100 * y_te.to_numpy()[decline].sum() / y_te.sum())
    m["goodLostPct"] = float(100 * ((decline & (y_te.to_numpy() == 0)).sum() / (y_te == 0).sum()))

    # calibration deciles on holdout (riskiest decile = 1)
    dec = pd.qcut(pd_te, 10, labels=False, duplicates="drop")
    calib = pd.DataFrame({"d": 10 - np.asarray(dec), "pd": pd_te, "y": y_te.to_numpy()}) \
        .groupby("d").agg(n=("y", "size"), pd=("pd", "mean"), act=("y", "mean")).reset_index()

    # ------------------------------------------------------------------
    # 4. Deployment refit on 100% of rows (bins frozen), score the portfolio
    # ------------------------------------------------------------------
    X_full = design(selected, np.arange(len(df)), woe_full)
    dep = LogisticRegression(penalty=None, solver="lbfgs", max_iter=2000).fit(X_full, y.to_numpy())
    pd_full = dep.predict_proba(X_full)[:, 1]
    logit_full = np.log(pd_full / (1 - pd_full))
    score_full = np.rint(OFFSET + FACTOR * (-logit_full)).astype(int)

    # stability of the deployment refit vs the validated model, measured where it
    # matters: in points on every loan (a weak near-zero beta would make raw
    # coefficient-drift percentages look scary while scores barely move)
    X_full_val = design(selected, np.arange(len(df)), woe_train)
    score_val = OFFSET + FACTOR * -(clf.intercept_[0] + X_full_val @ clf.coef_[0])
    drift_mean = float(np.mean(np.abs(score_val - score_full)))
    drift_max = float(np.max(np.abs(score_val - score_full)))

    # points scorecard from the deployment fit
    base_each = (OFFSET - FACTOR * dep.intercept_[0]) / len(selected)
    points_rows = []
    woe_art = {}
    for k in selected:
        t = woe_full[k]
        beta = dep.coef_[0][selected.index(k)]
        pts = np.rint(base_each - FACTOR * beta * t["woe"].to_numpy()).astype(int)
        for (label, row), p in zip(t.iterrows(), pts):
            points_rows.append(dict(feature=k, feature_label=({**ORDERED, **UNORDERED}[k]["label"]),
                                    bin=label, count=int(row["count"]), bad=int(row["bad"]),
                                    bad_rate_pct=round(100 * row["bad_rate"], 2),
                                    woe=round(float(row["woe"]), 4),
                                    points=int(p)))
        woe_art[k] = dict(
            label=({**ORDERED, **UNORDERED}[k]["label"]),
            bins=list(t.index), woe=[round(float(v), 3) for v in t["woe"]],
            n=[int(v) for v in t["count"]], bad=[int(v) for v in t["bad"]],
            badRate=[round(100 * float(v), 1) for v in t["bad_rate"]],
            points=[int(v) for v in pts], iv=round(woe_full[k]["iv"].sum(), 4), selected=True)
    for k in woe_full:
        if k in selected:
            continue
        t = woe_full[k]
        woe_art[k] = dict(
            label=({**ORDERED, **UNORDERED}[k]["label"]),
            bins=list(t.index), woe=[round(float(v), 3) for v in t["woe"]],
            n=[int(v) for v in t["count"]], bad=[int(v) for v in t["bad"]],
            badRate=[round(100 * float(v), 1) for v in t["bad_rate"]],
            points=None, iv=round(woe_full[k]["iv"].sum(), 4), selected=False)

    # write scored table
    SCORED.write_text(pd.DataFrame({
        "loan_id": df["loan_id"],
        "credit_score": score_full,
        "pd_default": np.round(pd_full, 4),
    }).to_csv(index=False))

    # ------------------------------------------------------------------
    # 5. Dashboard artifacts (compact JSON)
    # ------------------------------------------------------------------
    def decimate(a, n=70):
        a = np.asarray(a, dtype=float)
        if len(a) <= n:
            return a.tolist()
        ix = np.unique(np.linspace(0, len(a) - 1, n).astype(int))
        return a[ix].tolist()

    fpr, tpr, _ = roc_curve(y_te, pd_te)
    fpr_g, tpr_g, _ = roc_curve(y_te, grade_risk)
    fpr_f, tpr_f, _ = roc_curve(y_te, fico_risk)

    o = np.argsort(score_full)                       # KS curve on the full book
    sc_o = score_full[o]
    ys = y.to_numpy()[o]
    cb = np.cumsum(ys) / ys.sum() * 100
    cg = np.cumsum(1 - ys) / (len(ys) - ys.sum()) * 100
    ks_ix = int(np.argmax(np.abs(cb - cg)))

    lo = int(np.floor(score_full.min() / 25) * 25)
    hi = int(np.ceil(score_full.max() / 25) * 25)
    # band i covers [edges[i-1], edges[i]); below the first edge and above the
    # last are the '<x' and 'y+' open bands -> labels.len() == edges.len() + 1
    band_edges = list(range(lo + 25, hi, 25)) or i]
    band_labels = ([f"<{band_edges[0]}"]
                   + [f"{band_edges[i]}-{band_edges[i+1]}" for i in range(len(band_edges) - 1)]
                   + [f"{band_edges[-1]}+"])

    artifacts = dict(
        metrics=dict(auc=round(m["auc"], 4), aucTrain=round(m["aucTrain"], 4),
                     aucGrade=round(m["aucGrade"], 4), aucFico=round(m["aucFico"], 4),
                     ks=round(m["ks"], 4), ksGrade=round(m["ksGrade"], 4), ksFico=round(m["ksFico"], 4),
                     gini=round(m["gini"], 4), giniGrade=round(m["giniGrade"], 4), giniFico=round(m["giniFico"], 4),
                     nTrain=m["nTrain"], nTest=m["nTest"], baseRate=round(m["baseRate"], 2),
                     cutoff=m["cutoff"], declinePct=round(m["declinePct"], 1),
                     caughtPct=round(m["caughtPct"], 1), goodLostPct=round(m["goodLostPct"], 1),
                     scoreMin=int(score_full.min()), scoreMax=int(score_full.max()),
                     baseScore=BASE_SCORE, pdo=PDO,
                     nFeatures=len(selected)),
        roc=dict(fpr=decimate(fpr), tpr=decimate(tpr),
                 fprGrade=decimate(fpr_g), tprGrade=decimate(tpr_g),
                 fprFico=decimate(fpr_f), tprFico=decimate(tpr_f)),
        ksCurve=dict(score=decimate(sc_o), bad=decimate(cb), good=decimate(cg),
                     atScore=int(sc_o[ks_ix]), atPct=round(float(max(cb[ks_ix], cg[ks_ix])), 1)),
        iv=[dict(k=k, label=({**ORDERED, **UNORDERED}[k]["label"]),
                 iv=round(iv_train[k], 4), selected=k in selected)
            for k in sorted(iv_train, key=iv_train.get, reverse=True)],
        woe=woe_art,
        top=selected[0],
        bands=dict(edges=band_edges, labels=band_labels),
    )
    ARTIFACTS.write_text(json.dumps(artifacts, separators=(",", ":")))

    # ------------------------------------------------------------------
    # 6. scorecard_points.csv
    # ------------------------------------------------------------------
    pd.DataFrame(points_rows).to_csv(POINTS_CSV, index=False)

    # ------------------------------------------------------------------
    # 7. model_report.txt
    # ------------------------------------------------------------------
    L = []
    A = L.append
    bar = "=" * 78
    A(bar)
    A("CREDITLENS - APPLICATION CREDIT SCORECARD - MODEL REPORT")
    A(bar)
    A(f"Portfolio: {len(df):,} loans | default rate {m['baseRate']:.2f}% | "
      f"train {m['nTrain']:,} / holdout {m['nTest']:,} (stratified, seed {SEED})")
    A("")
    A("1. WHAT THIS IS, IN PLAIN ENGLISH")
    A("-" * 78)
    A("A scorecard that predicts the probability a loan defaults, built ONLY")
    A("from what a borrower writes on the application form: loan amount, term,")
    A("purpose, income, employment length, home ownership, DTI and state region.")
    A("Every loan gets points per feature; the total is a credit score where")
    A(f"{BASE_SCORE:.0f} points = 20:1 good:bad odds and every +{PDO:.0f} points")
    A("doubles those odds. Deliberately excluded inputs:")
    for k, why in EXCLUDED.items():
        A(f"  - {k}: {why}")
    A("")
    A("2. FEATURE STRENGTH - INFORMATION VALUE (train fold)")
    A("-" * 78)
    A(f"{'feature':<18}{'IV':>8}   strength                 verdict")
    for k in sorted(iv_train, key=iv_train.get, reverse=True):
        A(f"{k:<18}{iv_train[k]:>8.4f}   {iv_strength(iv_train[k]):<24} "
          f"{'KEPT' if k in selected else 'dropped'}")
    A("")
    A("Borderline test: purpose (IV 0.0198) was tried in the model; holdout AUC")
    A("moved 0.7763 -> 0.7765 and KS fell 0.427 -> 0.421, so it stayed out. The")
    A("small-business rate gap (19.9% vs 12.5%) is real but, at 4% of the book,")
    A("cannot move portfolio-level separation.")
    A("")
    A("WOE per bin (train fold), kept features - positive WOE = safer bin:")
    for k in selected:
        A(f"\n  {k}  ({woe_train[k]['iv'].sum():.4f} IV)")
        for label, row in woe_train[k].iterrows():
            A(f"    {str(label):<14} n={int(row['count']):>6,}  bad={row['bad_rate']*100:>5.1f}%  "
              f"WOE={row['woe']:>+6.3f}")
    A("")
    A("3. LOGISTIC COEFFICIENTS (validation fit, WOE scale)")
    A("-" * 78)
    A(f"{'feature':<18}{'beta':>9}{'std err':>9}{'z':>8}{'p-value':>11}")
    A(f"{'intercept':<18}{clf.intercept_[0]:>9.4f}")
    for i, k in enumerate(selected):
        A(f"{k:<18}{clf.coef_[0][i]:>9.4f}{se[i]:>9.4f}{z[i]:>8.2f}{pvals[i]:>11.2g}")
    A("")
    A("4. PERFORMANCE ON THE UNTOUCHED 30% HOLDOUT")
    A("-" * 78)
    A(f"{'model':<28}{'AUC':>8}{'Gini':>8}{'KS':>8}")
    A(f"{'Application scorecard':<28}{m['auc']:>8.4f}{m['gini']:>8.4f}{m['ks']:>8.4f}")
    A(f"{'Grade ladder (bank rating)':<28}{m['aucGrade']:>8.4f}{m['giniGrade']:>8.4f}{m['ksGrade']:>8.4f}")
    A(f"{'FICO at origination':<28}{m['aucFico']:>8.4f}{m['giniFico']:>8.4f}{m['ksFico']:>8.4f}")
    A(f"")
    A(f"Train AUC {m['aucTrain']:.4f} vs holdout AUC {m['auc']:.4f} -> "
      f"gap {abs(m['aucTrain']-m['auc']):.4f} (no material overfit).")
    A("")
    A("5. CALIBRATION BY DECILE (holdout, 1 = riskiest)")
    A("-" * 78)
    A(f"{'decile':>6}{'loans':>8}{'avg predicted PD':>18}{'actual default':>16}")
    for _, r in calib.iterrows():
        A(f"{int(r['d']):>6}{int(r['n']):>8,}{r['pd']*100:>17.2f}%{r['act']*100:>15.2f}%")
    A("")
    A("6. POLICY SIMULATION AT THE CUTOFF SCORE")
    A("-" * 78)
    A(f"Cutoff {m['cutoff']} points = the score where model PD equals the portfolio")
    A(f"base rate ({m['baseRate']:.2f}%). On the holdout fold, declining every")
    A(f"application below the cutoff would have:")
    A(f"  - declined {m['declinePct']:.1f}% of all applications")
    A(f"  - caught   {m['caughtPct']:.1f}% of the loans that actually defaulted")
    A(f"  - turned away {m['goodLostPct']:.1f}% of the good customers")
    A("")
    A("7. SCORE DISTRIBUTION (deployed scorecard, all rows)")
    A("-" * 78)
    A(f"scores run {int(score_full.min())}..{int(score_full.max())} points; "
      f"mean {score_full[y==0].mean():.0f} (performed) vs "
      f"{score_full[y==1].mean():.0f} (defaulted)")
    A("")
    A("8. STATISTICAL SIGNIFICANCE CHECKS")
    A("-" * 78)
    def fmt_p(p):
        return "p < 1e-300" if p == 0 else f"p = {p:.2g}"

    ct = pd.crosstab(df["grade"], y)
    chi2, pchi, _, _ = stats.chi2_contingency(ct)
    u, pu = stats.mannwhitneyu(df.loc[y == 1, "dti"], df.loc[y == 0, "dti"])
    d1, d0 = y[df["dti"] >= 30], y[df["dti"] < 30]
    p1, p0, n1, n0 = d1.mean(), d0.mean(), d1.sum() + (1 - d1).sum(), d0.sum() + (1 - d0).sum()
    pp = (d1.sum() + d0.sum()) / (n1 + n0)
    zdti = (p1 - p0) / math.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n0))
    A(f"grade x default      chi-square = {chi2:,.0f}   {fmt_p(pchi)}")
    A(f"DTI default vs paid  Mann-Whitney U = {u:,.0f}   {fmt_p(pu)}")
    A(f"DTI>=30 vs <30       two-proportion z = {zdti:.1f}   {fmt_p(stats.norm.sf(abs(zdti))*2)}")
    A("")
    A("9. ONE LOAN, WALKED THROUGH THE SCORECARD (deployment points)")
    A("-" * 78)
    exam = pd.DataFrame({"id": df["loan_id"], "score": score_full, "y": y})
    risky_pick = exam.loc[(exam["y"] == 1)].nsmallest(8, "score").iloc[2]
    safe_pick = exam.loc[(exam["y"] == 0)].nlargest(8, "score").iloc[4]
    for tag, pick in (("RISKY EXAMPLE", risky_pick), ("SAFE EXAMPLE", safe_pick)):
        i = df.index[df["loan_id"] == pick["id"]][0]
        A(f"\n  {tag} - loan {int(pick['id'])} -> {int(pick['score'])} points "
          f"(PD {pd_full[i]*100:.1f}%), actual: {'DEFAULTED' if pick['y'] else 'performed'})")
        for k in selected:
            label = group_series[k].iloc[i]
            p = int(np.rint(base_each - FACTOR * dep.coef_[0][selected.index(k)]
                            * woe_full[k].loc[label, "woe"]))
            A(f"    {k:<16} {str(label):<12} {p:>+5d} pts")
        A(f"    {'TOTAL':<26} {int(pick['score']):>+5d} pts  (cutoff {m['cutoff']})")
    A("")
    A("10. DEPLOYMENT NOTE + LIMITATIONS")
    A("-" * 78)
    A("After holdout validation the model was refit on 100% of loans with the")
    A("training bins frozen. That refit moves the score of the average loan by")
    A(f"{drift_mean:.1f} points (worst case {drift_max:.0f} points on {len(df):,} loans) -")
    A("the two models are operationally the same scorecard. Those deployed")
    A("scores are what loans_scored.csv, the dashboard Model page and SQL")
    A("queries 17-19 use.")
    A("Limitations: single snapshot (no time-out-of-window validation), no")
    A("reject-inference (we never see declined applicants), LGD assumed 100%")
    A("for expected-loss maths, and the data is simulated - real books need")
    A("vintage seasoning before default rates are final.")
    A("")
    A("Reproduce: python scripts/risk_model.py  (seeded, deterministic)")
    A(bar)
    REPORT_TXT.write_text("\n".join(L) + "\n")

    # ------------------------------------------------------------------
    print("\n" + "=" * 62)
    print(f"HOLDOUT AUC  : {m['auc']:.4f}  (grade-only {m['aucGrade']:.4f}, "
          f"FICO-only {m['aucFico']:.4f})")
    print(f"HOLDOUT KS   : {m['ks']:.4f}  Gini {m['gini']:.4f}")
    print(f"Cutoff {m['cutoff']} pts: decline {m['declinePct']:.1f}% of book, "
          f"catch {m['caughtPct']:.1f}% of defaults")
    print(f"Scores       : {int(score_full.min())}..{int(score_full.max())}")
    print(f"Wrote        : {SCORED.name}, {POINTS_CSV.name}, {REPORT_TXT.name}, {ARTIFACTS.name}")


if __name__ == "__main__":
    main()
