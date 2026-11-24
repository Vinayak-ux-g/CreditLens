"""
CreditLens - Step 5: Run the SQL analysis and save results
===========================================================

Executes every query in sql/analysis.sql against sql/loans.db, prints the
result of each, and saves:
  * one CSV per query          -> sql/results/qNN_<slug>.csv
  * a combined text summary     -> sql/results/results_summary.txt

The query blocks are delimited by "-- @query:NN|slug" markers, so this runner
stays dumb and the .sql file stays readable - the business logic lives in SQL
where it belongs.

Usage
-----
    python scripts/run_analysis.py
"""

import csv
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_FILE = ROOT / "sql" / "analysis.sql"
DB = ROOT / "sql" / "loans.db"
OUT_DIR = ROOT / "sql" / "results"
SUMMARY = OUT_DIR / "results_summary.txt"

MARKER = re.compile(r"^--\s*@query:(\d+)\|(\w+)", re.M)


def split_queries(text):
    """Yield (num, slug, description_lines, sql) for each query block."""
    matches = list(MARKER.finditer(text))
    for i, m in enumerate(matches):
        block = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        lines = block.splitlines()
        desc, sql_lines, in_sql = [], [], False
        for ln in lines:
            if ln.strip().startswith("--"):
                if not in_sql:
                    desc.append(ln.replace("--", "").strip())
            else:
                in_sql = True
                if ln.strip():
                    sql_lines.append(ln)
        yield m.group(1), m.group(2), desc, "\n".join(sql_lines)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    text = SQL_FILE.read_text()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summary, n_run = [], 0
    for num, slug, desc, sql in split_queries(text):
        if not sql.strip():
            continue
        n_run += 1
        cur = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        cols = [d[0] for d in cur.description] if rows else []

        csv_path = OUT_DIR / f"q{num}_{slug}.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

        header = f"Q{num}  {' '.join(d for d in desc if d)}"
        summary.append("=" * 78)
        summary.append(header)
        summary.append("=" * 78)
        if cols:
            summary.append(" | ".join(cols))
            summary.append("-" * 78)
            for r in rows[:40]:
                summary.append(" | ".join(str(r[c]) for c in cols))
            if len(rows) > 40:
                summary.append(f"... ({len(rows) - 40} more rows - see {csv_path.name})")
        else:
            summary.append("(no rows)")
        summary.append("")
        print(f"Q{num} ok -> {csv_path.name}  ({len(rows)} rows)")

    conn.close()
    SUMMARY.write_text("\n".join(summary) + "\n")
    print(f"\n{n_run} queries executed. CSVs in {OUT_DIR}")
    print(f"Summary: {SUMMARY}")


if __name__ == "__main__":
    main()
