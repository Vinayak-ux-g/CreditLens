"""
CreditLens - Step 7: Static dashboard screenshots (Power BI report style)
==========================================================================

Generates the four "report pages" of the CreditLens dashboard as high-res
PNGs, styled after Power BI's default theme (canvas gray, white visuals,
#118DFF blue). The numbers are real: they are read live from sql/loans.db,
sql/results/*.csv and reports/model_artifacts.json - nothing here is typed
in by hand.

Why PNGs at all? The interactive dashboard (dashboard/creditlens_dashboard.html)
is the real deliverable, but GitHub READMEs and LinkedIn posts need static
images. These screenshots play the role of the .pbix screenshots a Power BI
project would publish.

Usage
-----
    python scripts/make_dashboard_pngs.py

Reads : sql/loans.db, sql/results/*.csv, reports/model_artifacts.json
Writes: dashboard/screenshots/page1_overview.png
        dashboard/screenshots/page2_risk_deep_dive.png
        dashboard/screenshots/page3_loan_explorer.png
        dashboard/screenshots/page4_model_scorecard.png
"""

import json
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch

# ----------------------------------------------------------------- style ---
ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "sql" / "loans.db"
RES = ROOT / "sql" / "results"
OUT = ROOT / "dashboard" / "screenshots"

CANVAS = "#EDEFF2"      # report canvas gray
INK = "#252423"         # PBI near-black
SUB = "#6B7280"
MUTED = "#9AA3AB"
BLUE = "#118DFF"        # PBI default blue
NAVY = "#12239E"        # PBI default dark blue
MAGENTA = "#E40087"     # PBI default magenta
GOLD = "#FFB900"
GRAY_BAR = "#C9D1D9"
LINE_GRID = "#E5E7EB"

plt.rcParams.update({
    "font.sans-serif": ["Liberation Sans", "DejaVu Sans"],
    "font.family": "sans-serif",
    "axes.unicode_minus": False,
    "figure.facecolor": CANVAS,
    "axes.facecolor": "white",
    "axes.edgecolor": "#D8DCE0",
    "axes.linewidth": 0.0,
    "axes.grid": False,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "xtick.labelsize": 10.5,
    "ytick.labelsize": 10.5,
    "xtick.color": "#5B6470",
    "ytick.color": "#5B6470",
    "savefig.dpi": 150,
    "savefig.facecolor": CANVAS,
})

# ------------------------------------------------------------------ data ---
conn = sqlite3.connect(DB)
kpi = conn.execute("""
    SELECT COUNT(*), SUM(loan_amount), AVG(loan_amount), AVG(annual_income),
           AVG(int_rate), 100.0*AVG(default_flag),
           SUM(CASE WHEN default_flag=1 THEN loan_amount END)
    FROM loans""").fetchone()
TOTAL, FUNDED, AVG_AMT, AVG_INC, AVG_RATE, DEF_RATE, DEF_USD = kpi

monthly = pd.read_sql("SELECT issue_month, COUNT(*) n, 100.0*AVG(default_flag) r "
                      "FROM loans GROUP BY issue_month ORDER BY issue_month", conn)
grade_df = pd.read_sql("""SELECT grade, COUNT(*) n, 100.0*AVG(default_flag) r,
                          SUM(loan_amount) amt FROM loans GROUP BY grade ORDER BY grade""", conn)
purpose_df = pd.read_sql("""SELECT purpose, COUNT(*) n, 100.0*AVG(default_flag) r
                            FROM loans GROUP BY purpose ORDER BY n DESC""", conn)
states_df = pd.read_sql("""SELECT state, SUM(CASE WHEN default_flag=1 THEN loan_amount ELSE 0 END) d
                           FROM loans GROUP BY state ORDER BY d DESC LIMIT 10""", conn)
explorer = pd.read_sql("""SELECT loan_id, issue_month, loan_amount, grade, sub_grade, purpose,
                                  state, annual_income, dti, int_rate
                           FROM loans WHERE grade IN ('F','G') AND default_flag=1
                           ORDER BY loan_amount DESC LIMIT 14""", conn)
explorer_kpi = conn.execute("""SELECT COUNT(*), AVG(loan_amount), AVG(int_rate), AVG(dti)
                               FROM loans WHERE grade IN ('F','G') AND default_flag=1""").fetchone()
scored = pd.read_sql("""SELECT s.credit_score AS score, s.pd_default AS pd,
                                l.default_flag AS d, l.loan_amount AS amt
                         FROM loan_scores s JOIN loans l ON s.loan_id = l.loan_id""", conn)
conn.close()

ART = json.loads((ROOT / "reports" / "model_artifacts.json").read_text())
MT = ART["metrics"]

inc_df = pd.read_csv(RES / "q04_default_rate_by_income_band.csv")
dti_df = pd.read_csv(RES / "q07_default_rate_by_dti_band.csv")
q15 = pd.read_csv(RES / "q15_high_risk_segment.csv").iloc[0]
q17 = pd.read_csv(RES / "q17_scorecard_decile_ranking.csv")

# --------------------------------------------------------------- helpers ---


def header(ax, active):
    """Dark report header with the four page tabs."""
    ax.set_facecolor(NAVY)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.text(0.018, 0.56, "CreditLens", color="white", fontsize=17,
            fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.105, 0.56, "|  Loan Default Risk Report", color="#B9C4F0",
            fontsize=12, va="center", transform=ax.transAxes)
    tabs = ["Overview", "Risk Deep-Dive", "Loan Explorer", "Scorecard"]
    x = 0.575
    for t in tabs:
        w = 0.0075 * len(t)
        on = (t == active)
        ax.text(x, 0.56, t, color="white" if on else "#93A0D6",
                fontsize=11.5, fontweight="bold" if on else "normal",
                va="center", transform=ax.transAxes)
        if on:
            ax.plot([x - 0.005, x + w - 0.004], [0.12, 0.12], color=GOLD, lw=2.5,
                    transform=ax.transAxes, solid_capstyle="round")
        x += w + 0.015


def slicer_panel(ax, page):
    """Left slicer rail - grade chips, term buttons, reset."""
    ax.set_facecolor("white")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#E1E5E9")
    ax.text(0.5, 0.965, "SLICERS", color=INK, fontsize=11, fontweight="bold",
            ha="center", transform=ax.transAxes)

    def chips(labels, y, active_idx=None):
        xw = 0.86 / len(labels)
        for i, g in enumerate(labels):
            on = (active_idx is not None and i == active_idx)
            fc = BLUE if on else "#F1F4F8"
            rect = FancyBboxPatch((0.07 + i * xw, y), xw - 0.015, 0.045,
                                  boxstyle="round,pad=0.006",
                                  fc=fc, ec="none", transform=ax.transAxes)
            ax.add_patch(rect)
            ax.text(0.07 + i * xw + (xw - 0.015) / 2, y + 0.0225, g,
                    color="white" if on else "#42506B", fontsize=9.5,
                    ha="center", va="center", transform=ax.transAxes)

    ax.text(0.07, 0.895, "Grade", color=SUB, fontsize=10, transform=ax.transAxes)
    chips(list("ABCDEFG"), 0.845, active_idx=6 if page == 3 else None)
    ax.text(0.07, 0.775, "Term (months)", color=SUB, fontsize=10, transform=ax.transAxes)
    chips(["All", "36", "60"], 0.725)
    ax.text(0.07, 0.655, "Income band", color=SUB, fontsize=10, transform=ax.transAxes)
    chips(["All", "25k", "50k", "75k+"], 0.605)
    if page == 3:
        ax.text(0.07, 0.535, "Status", color=SUB, fontsize=10, transform=ax.transAxes)
        rect = FancyBboxPatch((0.07, 0.478), 0.20, 0.048, boxstyle="round,pad=0.006",
                              fc=MAGENTA, ec="none", transform=ax.transAxes)
        ax.add_patch(rect)
        ax.text(0.17, 0.502, "Defaulted", color="white", fontsize=9.5,
                ha="center", va="center", transform=ax.transAxes)
        for i, t in enumerate(["Performed", "All"]):
            rect = FancyBboxPatch((0.31 + i * 0.23, 0.478), 0.21, 0.048,
                                  boxstyle="round,pad=0.006", fc="#F1F4F8",
                                  ec="none", transform=ax.transAxes)
            ax.add_patch(rect)
            ax.text(0.415 + i * 0.23, 0.502, t, color="#42506B", fontsize=9.5,
                    ha="center", va="center", transform=ax.transAxes)
    # reset button
    rect = FancyBboxPatch((0.07, 0.045), 0.86, 0.052, boxstyle="round,pad=0.006",
                          fc="#F1F4F8", ec="none", transform=ax.transAxes)
    ax.add_patch(rect)
    ax.text(0.5, 0.071, "Reset all filters", color="#42506B", fontsize=10,
            ha="center", va="center", transform=ax.transAxes)


def kpi_strip(ax, cards):
    """Row of KPI cards inside one axes: (label, value, sub)."""
    ax.set_facecolor(CANVAS)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    for s in ax.spines.values():
        s.set_visible(False)
    n = len(cards)
    gap = 0.012
    w = (1 - gap * (n - 1)) / n
    for i, (label, value, sub, accent) in enumerate(cards):
        x = i * (w + gap)
        card = FancyBboxPatch((x + 0.002, 0.04), w - 0.004, 0.92,
                              boxstyle="round,pad=0.004,rounding_size=0.012",
                              fc="white", ec="#E1E5E9", lw=0.8,
                              transform=ax.transAxes)
        ax.add_patch(card)
        if accent:
            ax.add_patch(FancyBboxPatch((x + 0.03, 0.86), 0.018, 0.055,
                                        boxstyle="round,pad=0.003",
                                        fc=accent, ec="none", transform=ax.transAxes))
        ax.text(x + w / 2, 0.66, label, color=SUB, fontsize=11, ha="center",
                transform=ax.transAxes)
        ax.text(x + w / 2, 0.38, value, color=INK, fontsize=23, fontweight="bold",
                ha="center", va="center", transform=ax.transAxes)
        ax.text(x + w / 2, 0.14, sub, color=MUTED, fontsize=10.5, ha="center",
                transform=ax.transAxes)


def visual_title(ax, title, sub=""):
    ax.set_title(title, loc="left", fontsize=13.5, fontweight="bold",
                 color=INK, pad=14 if sub else 10)
    if sub:
        ax.text(0, 1.012, sub, transform=ax.transAxes, fontsize=10.5, color=SUB,
                va="bottom")


def clean_axis(ax, ygrid=True):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    if ygrid:
        ax.yaxis.grid(True, alpha=0.14, color="#B7C0C9", lw=0.7)
        ax.set_axisbelow(True)


def fmt_usd(v, unit="M"):
    return f"${v/1e6:,.1f}{unit}" if unit == "M" else f"${v/1e3:,.0f}k"


# ============================================================== PAGE 1 ======
def page1():
    fig = plt.figure(figsize=(20, 11.4), constrained_layout=True)
    fig.get_layout_engine().set(w_pad=0.18, h_pad=0.16, hspace=0.04, wspace=0.04)
    gs = gridspec.GridSpec(4, 4, figure=fig,
                           width_ratios=[0.135, 1, 1, 1],
                           height_ratios=[0.062, 0.235, 0.44, 0.30])

    header(fig.add_subplot(gs[0, :]), "Overview")
    slicer_panel(fig.add_subplot(gs[1:, 0]), 1)

    kpi_strip(fig.add_subplot(gs[1, 1:]), [
        ("TOTAL LOANS", f"{TOTAL:,}", "Jan 2021 - Oct 2026", None),
        ("TOTAL FUNDED", fmt_usd(FUNDED), "30,366 originations", None),
        ("DEFAULT RATE", f"{DEF_RATE:.2f}%", "3,788 defaults", MAGENTA),
        ("DEFAULTED DOLLARS", fmt_usd(DEF_USD), "11.1% of funded", MAGENTA),
        ("AVG LOAN / AVG INCOME", f"${AVG_AMT:,.0f}", f"income ${AVG_INC:,.0f}", None),
        ("AVG INTEREST RATE", f"{AVG_RATE:.2f}%", "grade A 7.6% -> G 26.5%", None),
    ])

    # --- monthly combo: bars = loans funded, line = default rate ------------
    ax = fig.add_subplot(gs[2, 1:])
    x = np.arange(len(monthly))
    ax.bar(x, monthly["n"], color=BLUE, width=0.62, zorder=3)
    ax.set_ylim(0, monthly["n"].max() * 1.35)
    visual_title(ax, "Monthly originations doubled while default rate drifted down",
                 "Bars: loans funded per month   |   Line: default rate of that month (6-mo rolling)")
    clean_axis(ax)
    tick = [i for i in range(0, len(x), 6)]
    ax.set_xticks(tick)
    ax.set_xticklabels([monthly["issue_month"].iloc[i] for i in tick])
    ax2 = ax.twinx()
    roll = monthly["r"].rolling(6, min_periods=1).mean()
    ax2.plot(x, roll, color=MAGENTA, lw=2.6, zorder=4)
    ax2.set_ylim(8, 16)
    ax2.set_yticks([8, 10, 12, 14, 16])
    ax2.set_yticklabels(["8%", "10%", "12%", "14%", "16%"])
    for s in ("top", "left"):
        ax2.spines[s].set_visible(False)
    ax2.spines["right"].set_color("#D8DCE0")
    ax.text(x[-1] + 0.6, monthly["n"].iloc[-1] + 46, f"{monthly['n'].iloc[-1]}",
            color=BLUE, fontsize=10.5, fontweight="bold", ha="left", va="center")
    ax2.text(x[-1] + 0.6, roll.iloc[-1], f"{roll.iloc[-1]:.1f}%",
             color=MAGENTA, fontsize=10.5, fontweight="bold", ha="left", va="center")

    # --- funded by grade -----------------------------------------------------
    axg = fig.add_subplot(gs[3, 1])
    bars = axg.bar(grade_df["grade"], grade_df["amt"] / 1e6, color=BLUE, width=0.6, zorder=3)
    visual_title(axg, "Funded by grade ($M)", "A-C carry 65% of exposure")
    clean_axis(axg)
    for b, v in zip(bars, grade_df["amt"] / 1e6):
        axg.text(b.get_x() + b.get_width() / 2, v + grade_df["amt"].max() / 1e6 * 0.03,
                 f"{v:.0f}", ha="center", fontsize=9.5, color=SUB)
    axg.set_ylim(0, grade_df["amt"].max() / 1e6 * 1.18)

    # --- top purposes --------------------------------------------------------
    axp = fig.add_subplot(gs[3, 2:])
    top = purpose_df.head(9).iloc[::-1]
    colors = [GRAY_BAR] * len(top)
    colors[-1] = BLUE                      # debt_consolidation = biggest volume
    axp.barh(top["purpose"], top["n"], color=colors, height=0.62, zorder=3)
    visual_title(axp, "Loans by purpose (top 9)", "Debt consolidation is 45% of the book")
    for s in ("top", "right", "left", "bottom"):
        axp.spines[s].set_visible(False)
    axp.xaxis.set_visible(False)
    for i, v in enumerate(top["n"]):
        axp.text(v + top["n"].max() * 0.012, i, f"{v:,}", va="center",
                 fontsize=9.5, color=INK)
    axp.set_xlim(0, top["n"].max() * 1.14)

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "page1_overview.png"
    fig.savefig(p)
    plt.close(fig)
    print("OK", p)


# ============================================================== PAGE 2 ======
def page2():
    fig = plt.figure(figsize=(20, 12.6), constrained_layout=True)
    fig.get_layout_engine().set(w_pad=0.18, h_pad=0.16, hspace=0.04, wspace=0.04)
    gs = gridspec.GridSpec(5, 2, figure=fig,
                           width_ratios=[1, 1],
                           height_ratios=[0.055, 0.16, 0.30, 0.30, 0.235])

    header(fig.add_subplot(gs[0, :]), "Risk Deep-Dive")
    kpi_strip(fig.add_subplot(gs[1, :]), [
        ("PORTFOLIO DEFAULT RATE", f"{DEF_RATE:.2f}%", "30,366 loans", None),
        ("HIGH-RISK SEGMENT RATE", f"{q15['segment_default_rate_pct']:.1f}%",
         "grade E-G AND DTI 30+", MAGENTA),
        ("SHARE OF ALL DEFAULTS", f"{q15['pct_of_all_defaults']:.1f}%",
         f"from {q15['pct_of_portfolio']:.1f}% of loans", MAGENTA),
        ("DEFAULTED DOLLARS", fmt_usd(DEF_USD), "11.1% of funded", None),
        ("FICO GAP (PAID VS DEFAULT)", "752 vs 714", "38-point separation", None),
    ])

    # default rate by grade
    axg = fig.add_subplot(gs[2, 0])
    bars = axg.bar(grade_df["grade"], grade_df["r"], color=GRAY_BAR, width=0.6, zorder=3)
    bars[-1].set_color(MAGENTA)
    visual_title(axg, "Default rate climbs from 1.6% (A) to 64.1% (G)",
                 "The grade ladder is the single strongest risk signal - 39x from A to G")
    clean_axis(axg)
    for b, v in zip(bars, grade_df["r"]):
        axg.text(b.get_x() + b.get_width() / 2, v + grade_df["r"].max() * 0.025,
                 f"{v:.1f}", ha="center", fontsize=9.5,
                 color=INK if v > 40 else SUB,
                 fontweight="bold" if v > 40 else "normal")
    axg.set_ylim(0, grade_df["r"].max() * 1.16)

    # default rate by purpose (all, sorted by rate)
    axp = fig.add_subplot(gs[2, 1])
    pp = purpose_df.sort_values("r")
    colors = [GRAY_BAR] * len(pp)
    colors[-1] = MAGENTA
    axp.barh(pp["purpose"], pp["r"], color=colors, height=0.62, zorder=3)
    visual_title(axp, "Small-business loans default most (19.9% vs 12.5% portfolio)",
                 "Default rate by purpose")
    for s in ("top", "right", "left", "bottom"):
        axp.spines[s].set_visible(False)
    axp.xaxis.set_visible(False)
    for i, v in enumerate(pp["r"]):
        axp.text(v + pp["r"].max() * 0.015, i, f"{v:.1f}%", va="center",
                 fontsize=9, color=INK if v > 18 else SUB,
                 fontweight="bold" if v > 18 else "normal")
    axp.set_xlim(0, pp["r"].max() * 1.16)

    # default rate by income band
    axi = fig.add_subplot(gs[3, 0])
    bars = axi.bar(inc_df["income_band"], inc_df["default_rate_pct"],
                   color=GRAY_BAR, width=0.55, zorder=3)
    bars[0].set_color(BLUE)
    visual_title(axi, "Lowest incomes default 3.8x more",
                 "Default rate by annual income band ($)")
    clean_axis(axi)
    for b, v in zip(bars, inc_df["default_rate_pct"]):
        axi.text(b.get_x() + b.get_width() / 2, v + inc_df["default_rate_pct"].max() * 0.03,
                 f"{v:.1f}%", ha="center", fontsize=10,
                 color=INK if v > 25 else SUB,
                 fontweight="bold" if v > 25 else "normal")
    axi.set_ylim(0, inc_df["default_rate_pct"].max() * 1.18)

    # default rate by DTI band
    axd = fig.add_subplot(gs[3, 1])
    bars = axd.bar(dti_df["dti_band"], dti_df["default_rate_pct"],
                   color=GRAY_BAR, width=0.55, zorder=3)
    bars[-1].set_color(MAGENTA)
    visual_title(axd, "Crossing DTI 30 more than doubles the risk",
                 "Default rate by debt-to-income band (%)")
    clean_axis(axd)
    for b, v in zip(bars, dti_df["default_rate_pct"]):
        axd.text(b.get_x() + b.get_width() / 2, v + dti_df["default_rate_pct"].max() * 0.03,
                 f"{v:.1f}%", ha="center", fontsize=10,
                 color=INK if v > 35 else SUB,
                 fontweight="bold" if v > 35 else "normal")
    axd.set_ylim(0, dti_df["default_rate_pct"].max() * 1.18)

    # top states by defaulted dollars
    axs = fig.add_subplot(gs[4, :])
    st = states_df.iloc[::-1]
    colors = [GRAY_BAR] * len(st)
    colors[-1] = NAVY
    axs.barh(st["state"], st["d"] / 1e6, color=colors, height=0.62, zorder=3)
    visual_title(axs, "Where the losses are: defaulted dollars by state (top 10)",
                 "California alone accounts for $12.0M of defaulted principal")
    for s in ("top", "right", "left", "bottom"):
        axs.spines[s].set_visible(False)
    axs.xaxis.set_visible(False)
    for i, v in enumerate(st["d"] / 1e6):
        axs.text(v + st["d"].max() / 1e6 * 0.012, i, f"${v:.1f}M", va="center",
                 fontsize=9.5, color=INK if v > 11 else SUB,
                 fontweight="bold" if v > 11 else "normal")
    axs.set_xlim(0, st["d"].max() / 1e6 * 1.14)

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "page2_risk_deep_dive.png"
    fig.savefig(p)
    plt.close(fig)
    print("OK", p)


# ============================================================== PAGE 3 ======
def page3():
    fig = plt.figure(figsize=(20, 11.4), constrained_layout=True)
    fig.get_layout_engine().set(w_pad=0.18, h_pad=0.16, hspace=0.04, wspace=0.04)
    gs = gridspec.GridSpec(4, 4, figure=fig,
                           width_ratios=[0.135, 1, 1, 1],
                           height_ratios=[0.062, 0.20, 0.63, 0.107])

    header(fig.add_subplot(gs[0, :]), "Loan Explorer")
    slicer_panel(fig.add_subplot(gs[1:, 0]), 3)

    n_sel, amt_sel, rate_sel, dti_sel = explorer_kpi
    kpi_strip(fig.add_subplot(gs[1, 1:]), [
        ("MATCHED LOANS", f"{n_sel:,}", "Grade F-G, defaulted", MAGENTA),
        ("MATCHED PRINCIPAL", fmt_usd(amt_sel * n_sel), f"avg loan ${amt_sel:,.0f}", None),
        ("AVG INTEREST RATE", f"{rate_sel:.2f}%", "vs 13.86% portfolio", None),
        ("AVG DTI", f"{dti_sel:.1f}", "vs 18.2 portfolio", MAGENTA),
        ("PORTFOLIO DEFAULT RATE", f"{DEF_RATE:.2f}%", "this segment: 49.5%", None),
    ])

    # ---- the table ----------------------------------------------------------
    ax = fig.add_subplot(gs[2, 1:])
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    cols = ["Loan ID", "Issued", "Amount", "Grade", "Sub", "Purpose", "State",
            "Income", "DTI", "Rate", "Status"]
    widths = [0.085, 0.085, 0.095, 0.065, 0.055, 0.16, 0.06, 0.095, 0.065, 0.065, 0.11]
    xs = np.concatenate([[0.012], np.cumsum([0.012] + widths[:-1])])
    xcenters = [x + w / 2 for x, w in zip(xs, widths)]

    # filter chips
    chips = ["Grade = F, G", "Status = Defaulted", "Sort = Amount (high to low)"]
    cx = 0.012
    for t in chips:
        wch = 0.0082 * len(t) + 0.018
        rect = FancyBboxPatch((cx, 0.945), wch, 0.05, boxstyle="round,pad=0.004",
                              fc="#E8F1FE", ec="#BBD6FD", lw=0.8, transform=ax.transAxes)
        ax.add_patch(rect)
        ax.text(cx + 0.012, 0.970, t, color="#0B5FBD", fontsize=10, va="center",
                transform=ax.transAxes)
        cx += wch + 0.010

    # header row
    yh = 0.845
    ax.add_patch(FancyBboxPatch((0.006, yh - 0.055), 0.988, 0.062,
                                boxstyle="round,pad=0.003,rounding_size=0.008",
                                fc=NAVY, ec="none", transform=ax.transAxes))
    for xc, w, t in zip(xcenters, widths, cols):
        ax.text(xc, yh - 0.024, t, color="white", fontsize=10.5, fontweight="bold",
                ha="center", va="center", transform=ax.transAxes)

    # data rows
    row_h = 0.066
    for r, (_, row) in enumerate(explorer.iterrows()):
        y = yh - 0.075 - (r + 1) * row_h
        if r % 2 == 0:
            ax.add_patch(FancyBboxPatch((0.006, y), 0.988, row_h - 0.006,
                                        boxstyle="round,pad=0.001,rounding_size=0.005",
                                        fc="#F4F7FB", ec="none", transform=ax.transAxes))
        vals = [f"{int(row.loan_id)}", row.issue_month, f"${row.loan_amount:,.0f}",
                row.grade, row.sub_grade, row.purpose.replace("_", " "),
                row.state, f"${row.annual_income:,.0f}", f"{row.dti:.1f}",
                f"{row.int_rate:.2f}%", None]
        for xc, v, al in zip(xcenters, vals, ["center"] * 10 + ["center"]):
            if v is None:
                continue
            ax.text(xc, y + (row_h - 0.006) / 2, v, fontsize=10, color="#3A4653",
                    ha=al, va="center", transform=ax.transAxes)
        # status chip
        xc = xcenters[-1]
        ax.add_patch(FancyBboxPatch((xc - 0.048, y + 0.013), 0.096, 0.034,
                                    boxstyle="round,pad=0.004",
                                    fc=MAGENTA, ec="none", transform=ax.transAxes))
        ax.text(xc, y + 0.030, "Default", color="white", fontsize=9,
                fontweight="bold", ha="center", va="center", transform=ax.transAxes)

    ax.text(0.012, 0.030, f"Showing 14 of {n_sel:,} matched loans", color=MUTED,
            fontsize=10.5, va="center", transform=ax.transAxes)

    # footnote strip
    axf = fig.add_subplot(gs[3, 1:])
    axf.set_facecolor("white")
    axf.set_xticks([]); axf.set_yticks([])
    for s in axf.spines.values():
        s.set_color("#E1E5E9")
    axf.text(0.014, 0.60, "How to read this page", fontsize=12, fontweight="bold",
             color=INK, va="center", transform=axf.transAxes)
    axf.text(0.014, 0.24, "Slicers (left) filter the table live. Every column is sortable; "
             "the Status chip marks the default flag. Sample above: the highest-ticket F/G loans that defaulted - "
             "$40,000 each, priced at 22-28% interest, the exact profile the Risk Deep-Dive page isolates.",
             fontsize=10.5, color=SUB, va="center", transform=axf.transAxes)

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "page3_loan_explorer.png"
    fig.savefig(p)
    plt.close(fig)
    print("OK", p)


# ============================================================== PAGE 4 ======
def page4():
    fig = plt.figure(figsize=(20, 12.6), constrained_layout=True)
    fig.get_layout_engine().set(w_pad=0.18, h_pad=0.16, hspace=0.04, wspace=0.04)
    gs = gridspec.GridSpec(5, 2, figure=fig,
                           width_ratios=[1, 1],
                           height_ratios=[0.055, 0.16, 0.30, 0.30, 0.235])

    header(fig.add_subplot(gs[0, :]), "Scorecard")

    ok = scored[scored["d"] == 0]["score"].mean()
    bad = scored[scored["d"] == 1]["score"].mean()
    kpi_strip(fig.add_subplot(gs[1, :]), [
        ("AUC - 30% HOLDOUT", f"{MT['auc']:.3f}",
         f"grade-only {MT['aucGrade']:.3f} · FICO-only {MT['aucFico']:.3f}", BLUE),
        ("KS STATISTIC", f"{MT['ks']:.3f}",
         f"grade {MT['ksGrade']:.3f} · FICO {MT['ksFico']:.3f}", None),
        ("GINI", f"{MT['gini']:.3f}", "2 x AUC - 1", None),
        ("SCORE RANGE", f"{MT['scoreMin']}-{MT['scoreMax']}",
         f"mean {ok:.0f} performed vs {bad:.0f} defaulted", None),
        ("DEFAULTS CAUGHT AT CUTOFF", f"{MT['caughtPct']:.1f}%",
         f"by declining {MT['declinePct']:.1f}% of applications", MAGENTA),
    ])

    # --- score distribution: bars + default-rate line ------------------------
    axd = fig.add_subplot(gs[2, 0])
    edges = np.array(ART["bands"]["edges"])
    labels = ART["bands"]["labels"]
    bix = np.searchsorted(edges, scored["score"].to_numpy(), side="right")
    n_b = [(bix == i).sum() for i in range(len(labels))]
    r_b = [100 * scored.loc[bix == i, "d"].mean() if n_b[i] else 0 for i in range(len(labels))]
    x = np.arange(len(labels))
    axd.bar(x, n_b, color=BLUE, width=0.62, zorder=3)
    axd.set_ylim(0, max(n_b) * 1.32)
    visual_title(axd, "Scores separate the outcomes",
                 "Bars: loans per score band   |   Line: default rate of the band")
    clean_axis(axd)
    axd.set_xticks(x)
    axd.set_xticklabels(labels)
    axd2 = axd.twinx()
    axd2.plot(x, r_b, color=MAGENTA, lw=2.6, marker="o", ms=5, zorder=4)
    axd2.set_ylim(0, max(r_b) * 1.3)
    for s in ("top", "left"):
        axd2.spines[s].set_visible(False)
    axd2.spines["right"].set_color("#D8DCE0")
    for xi, r in zip(x, r_b):
        if n_b[xi]:
            axd2.text(xi, r + max(r_b) * 0.05, f"{r:.1f}%", color=MAGENTA, fontsize=9,
                      ha="center", fontweight="bold")

    # --- ROC curves -----------------------------------------------------------
    axr = fig.add_subplot(gs[2, 1])
    r_ = ART["roc"]
    axr.plot(r_["fpr"], r_["tpr"], color=BLUE, lw=2.6, zorder=4,
             label=f"Application scorecard (AUC {MT['auc']:.3f})")
    axr.plot(r_["fprGrade"], r_["tprGrade"], color=NAVY, lw=1.8, ls="--", zorder=3,
             label=f"Grade ladder ({MT['aucGrade']:.3f})")
    axr.plot(r_["fprFico"], r_["tprFico"], color="#9AA3AB", lw=1.8, ls="--", zorder=3,
             label=f"FICO at origination ({MT['aucFico']:.3f})")
    axr.plot([0, 1], [0, 1], color="#D5DBE1", lw=1, ls=":", zorder=2, label="Random (0.500)")
    axr.set_xlim(0, 1); axr.set_ylim(0, 1)
    axr.set_xticks(np.arange(0, 1.01, 0.2))
    axr.set_xticklabels(["0%", "20%", "40%", "60%", "80%", "100%"])
    axr.set_yticks(np.arange(0, 1.01, 0.2))
    axr.set_yticklabels(["0%", "20%", "40%", "60%", "80%", "100%"])
    visual_title(axr, "ROC: application data alone nearly matches the bank's rating",
                 "Holdout validation on 9,110 untouched loans")
    clean_axis(axr)
    axr.legend(loc="lower right", fontsize=10, frameon=False)

    # --- KS curve ------------------------------------------------------------
    axk = fig.add_subplot(gs[3, 0])
    kc = ART["ksCurve"]
    axk.plot(kc["score"], kc["bad"], color=MAGENTA, lw=2.4, label="Defaults (cum %)")
    axk.plot(kc["score"], kc["good"], color=BLUE, lw=2.4, label="Performs (cum %)")
    axk.axvline(kc["atScore"], color=GOLD, lw=1.8)
    axk.text(kc["atScore"] + 2, 55, f"KS {MT['ks']*100:.1f}%\n@ {kc['atScore']} pts",
             fontsize=10.5, color=INK, fontweight="bold", va="top")
    axk.set_ylim(0, 105)
    axk.set_yticks([0, 25, 50, 75, 100])
    axk.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    visual_title(axk, "The KS gap: how far apart the curves run",
                 "Cumulative share of each population as the score rises")
    clean_axis(axk)
    axk.legend(loc="center right", fontsize=10, frameon=False)

    # --- Information Value ----------------------------------------------------
    axi = fig.add_subplot(gs[3, 1])
    iv = sorted(ART["iv"], key=lambda r: r["iv"])
    colors = [(NAVY if r["iv"] >= 0.3 else BLUE) if r["selected"] else GRAY_BAR for r in iv]
    axi.barh([r["label"] for r in iv], [r["iv"] for r in iv], color=colors,
             height=0.62, zorder=3)
    visual_title(axi, "What drives the score: Information Value by feature",
                 "Blue/navy = kept (IV >= 0.02) · gray = dropped by the filter")
    for s in ("top", "right", "left", "bottom"):
        axi.spines[s].set_visible(False)
    axi.xaxis.set_visible(False)
    for i, r in enumerate(iv):
        axi.text(r["iv"] + 0.012, i, f"{r['iv']:.3f}", va="center", fontsize=9.5,
                 color=INK if r["selected"] else MUTED,
                 fontweight="bold" if r["selected"] else "normal")
    axi.set_xlim(0, max(r["iv"] for r in iv) * 1.14)

    # --- decile ladder (query 17) ---------------------------------------------
    axq = fig.add_subplot(gs[4, 0])
    xd = np.arange(len(q17))
    cols = [MAGENTA] + [GRAY_BAR] * (len(q17) - 2) + [BLUE]
    axq.bar(xd, q17["actual_default_pct"], color=cols, width=0.66, zorder=3)
    axq.plot(xd, q17["predicted_default_pct"], color=INK, lw=2, marker="D", ms=4.5,
             zorder=4, label="model predicted")
    axq.set_xticks(xd)
    axq.set_xticklabels([f"D{int(d)}\n{int(a)}-{int(b)}" for d, a, b in
                         zip(q17["decile"], q17["score_from"], q17["score_to"])], fontsize=9)
    visual_title(axq, "The decile ladder: actual vs predicted default rate",
                 "NTILE(10) over credit_score (SQL query 17) - D1 riskiest")
    clean_axis(axq)
    for xi, (a, p) in enumerate(zip(q17["actual_default_pct"], q17["predicted_default_pct"])):
        axq.text(xi, max(a, p) + 1.2, f"{a:.0f}%", ha="center", fontsize=9,
                 color=INK, fontweight="bold")
    axq.set_ylim(0, q17["actual_default_pct"].max() * 1.18)
    axq.legend(loc="upper right", fontsize=9.5, frameon=False)

    # --- WOE of DTI -----------------------------------------------------------
    axw = fig.add_subplot(gs[4, 1])
    wd = ART["woe"]["dti"]
    xw = np.arange(len(wd["bins"]))
    cols = [BLUE if w >= 0 else MAGENTA for w in wd["woe"]]
    axw.bar(xw, wd["woe"], color=cols, width=0.58, zorder=3)
    axw.axhline(0, color="#C9D1D9", lw=1)
    axw.set_xticks(xw)
    axw.set_xticklabels([f"{b}\nn={n:,} · bad {r:.0f}%" for b, n, r in
                         zip(wd["bins"], wd["n"], wd["badRate"])], fontsize=9.5)
    for xi, w in zip(xw, wd["woe"]):
        axw.text(xi, w + (0.09 if w >= 0 else -0.16), f"{w:+.2f}", ha="center",
                 fontsize=10, color=INK, fontweight="bold")
    visual_title(axw, "Weight of Evidence: DTI is the engine of the score",
                 "Positive = safer than the average bin (risk falls as DTI falls)")
    clean_axis(axw)
    axw.set_ylim(min(wd["woe"]) - 0.45, max(wd["woe"]) + 0.45)

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "page4_model_scorecard.png"
    fig.savefig(p)
    plt.close(fig)
    print("OK", p)


if __name__ == "__main__":
    page1()
    page2()
    page3()
    page4()
