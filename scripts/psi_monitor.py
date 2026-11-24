#!/usr/bin/env python3
"""CreditLens - Population Stability Index (PSI) monitor.

Compares the development window (first 60% of issue months) against the
recent window (last 40%) and quantifies drift for the scorecard score and
every scorecard feature. Also recomputes AUC per month so you can see
discriminatory power trend over time, and checks PD calibration.

Reads directly from sql/loans.db (loans JOIN loan_scores) - no CSV needed.
Writes reports/psi_report.txt and prints the same text to stdout.

Usage:  python3 scripts/psi_monitor.py
Exit code is always 0; warnings live inside the report.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "sql" / "loans.db"
OUT = ROOT / "reports" / "psi_report.txt"

# Score bands used across the project (dashboard bands + classic FICO bands)
BINS = {
    "credit_score": {
        "edges": [-np.inf, 500, 525, 550, 575, 600, 625, np.inf],
        "labels": ["<500", "500-525", "525-550", "550-575",
                   "575-600", "600-625", "625+"],
    },
    "dti": {
        "edges": [-np.inf, 10, 20, 30, np.inf],
        "labels": ["<10", "10-20", "20-30", "30+"],
    },
    "annual_income": {
        "edges": [-np.inf, 40000, 60000, 80000, 100000, np.inf],
        "labels": ["<$40k", "$40-60k", "$60-80k", "$80-100k", "$100k+"],
    },
    "term": {
        "edges": [-np.inf, 40, np.inf],
        "labels": ["36 mo", "60 mo"],
    },
    "loan_amount": {
        "edges": [-np.inf, 10000, 20000, 30000, np.inf],
        "labels": ["<$10k", "$10-20k", "$20-30k", "$30k+"],
    },
    "fico_score": {
        "edges": [-np.inf, 600, 640, 680, 720, np.inf],
        "labels": ["<600", "600-640", "640-680", "680-720", "720+"],
    },
}

FEATURES = ["credit_score", "dti", "annual_income", "term", "loan_amount", "fico_score"]


def load() -> pd.DataFrame:
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        """SELECT l.issue_month, l.dti, l.annual_income, l.term, l.loan_amount,
                  l.fico_score, l.default_flag,
                  s.credit_score, s.pd_default
           FROM loans l JOIN loan_scores s ON s.loan_id = l.loan_id""",
        con,
    )
    con.close()
    return df


def split_window(df: pd.DataFrame):
    months = sorted(df["issue_month"].unique())
    k = max(1, int(round(len(months) * 0.6)))
    dev = df[df["issue_month"].isin(months[:k])]
    rec = df[df["issue_month"].isin(months[k:])]
    return months[:k], months[k:], dev, rec


def psi(expected_pct: np.ndarray, actual_pct: np.ndarray) -> float:
    """PSI = sum (actual% - expected%) * ln(actual% / expected%)."""
    eps = 1e-6
    e = np.clip(expected_pct, eps, None)
    a = np.clip(actual_pct, eps, None)
    return float(np.sum((a - e) * np.log(a / e)))


def var_psi(dev: pd.Series, rec: pd.Series, edges, labels):
    e_pct = pd.cut(dev, bins=edges, labels=labels).value_counts(
        normalize=True).reindex(labels).fillna(0.0) * 100
    a_pct = pd.cut(rec, bins=edges, labels=labels).value_counts(
        normalize=True).reindex(labels).fillna(0.0) * 100
    table = pd.DataFrame({"dev %": e_pct.round(2), "recent %": a_pct.round(2)})
    return psi(e_pct.to_numpy(), a_pct.to_numpy()), table


def auc(y_true: pd.Series, score: pd.Series) -> float:
    """AUC of the score for predicting default (higher score = safer).
    The Mann-Whitney U below gives P(score | defaulter > score | performer),
    so we invert it to get P(score | performer > score | defaulter)."""
    y = y_true.to_numpy().astype(float)
    r = score.rank(method="average").to_numpy()
    n_pos = y.sum()
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    p_bad_higher = (r[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(1.0 - p_bad_higher)


def main():
    lines = []
    say = lines.append

    df = load()
    dev_m, rec_m, dev, rec = split_window(df)
    months = dev_m + rec_m

    say("=" * 74)
    say("CREDITLENS - MODEL MONITORING REPORT (PSI / AUC / calibration)")
    say("=" * 74)
    say(f"rows            : {len(df):,} scored loans")
    say(f"window          : {months[0]} .. {months[-1]}  ({len(months)} issue months)")
    say(f"development     : {dev_m[0]} .. {dev_m[-1]}  ({len(dev):,} loans)")
    say(f"recent          : {rec_m[0]} .. {rec_m[-1]}  ({len(rec):,} loans)")
    say("")

    say("-" * 74)
    say("1) POPULATION STABILITY INDEX (development vs recent)")
    say("-" * 74)
    say("rule of thumb: PSI < 0.10 stable | 0.10-0.25 moderate shift | > 0.25 major shift")
    say("")
    worst = ""
    worst_v = -1.0
    for feat in FEATURES:
        cfg = BINS[feat]
        v, table = var_psi(dev[feat], rec[feat], cfg["edges"], cfg["labels"])
        flag = ("STABLE" if v < 0.10 else "MODERATE" if v < 0.25 else "MAJOR SHIFT")
        say(f"{feat:<14} PSI = {v:.4f}   [{flag}]")
        if v >= worst_v:
            worst_v, worst = v, feat
        for lbl, row in table.iterrows():
            say(f"    {lbl:>9}: dev {row['dev %']:6.2f}%   recent {row['recent %']:6.2f}%")
        say("")
    say(f"most shifted variable: {worst} (PSI {worst_v:.4f})")
    say("")

    say("-" * 74)
    say("2) DISCRIMINATION - AUC by issue month (scorecard score, inverted)")
    say("-" * 74)
    overall = auc(df["default_flag"], df["credit_score"])
    say(f"overall AUC     : {overall:.4f}")
    vals = []
    for m in months:
        sub = df[df["issue_month"] == m]
        a = auc(sub["default_flag"], sub["credit_score"])
        vals.append(a)
        say(f"    {m}: AUC {a:.4f}   (n={len(sub):,})")
    arr = np.array(vals, dtype=float)
    say(f"monthly AUC min/mean/max: {np.nanmin(arr):.4f} / {np.nanmean(arr):.4f} / {np.nanmax(arr):.4f}")
    say("")

    say("-" * 74)
    say("3) CALIBRATION - average predicted PD vs observed default rate")
    say("-" * 74)
    for name, w in (("development", dev), ("recent", rec)):
        pred = w["pd_default"].mean() * 100
        obs = w["default_flag"].mean() * 100
        gap = obs - pred
        say(f"{name:<12}: predicted {pred:6.2f}%   observed {obs:6.2f}%   gap {gap:+.2f} pp")
    say("")
    say("-" * 74)
    say("VERDICT")
    say("-" * 74)
    alerts = []
    if worst_v >= 0.25:
        alerts.append(f"PSI MAJOR shift on {worst} - consider re-binning or re-fitting the scorecard")
    elif worst_v >= 0.10:
        alerts.append(f"PSI moderate shift on {worst} - keep monitoring monthly")
    a1 = auc(rec["default_flag"], rec["credit_score"])
    if a1 < overall - 0.03:
        alerts.append(f"recent-window AUC {a1:.4f} is >3pp below overall {overall:.4f} - check discrimination decay")
    for name, w in (("development", dev), ("recent", rec)):
        gap = w["default_flag"].mean() * 100 - w["pd_default"].mean() * 100
        if abs(gap) > 2.0:
            alerts.append(f"{name} calibration gap {gap:+.2f} pp exceeds 2 pp - recalibrate PD scaling")
    if not alerts:
        say("No drift alerts - the scorecard is stable on the recent window.")
    else:
        for i, a in enumerate(alerts, 1):
            say(f"{i}. {a}")
    say("")
    say("generated by scripts/psi_monitor.py - deterministic, no randomness")

    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
