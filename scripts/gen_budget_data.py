"""Generate a synthetic Budget-vs-Actuals dataset.

This is a *different shape* from the sales data (monthly, two measures + variance, no
product/region dimensions) on purpose: it demonstrates that the report engine is truly
data-agnostic. Upload this through the app and you get an FP&A-style spend report from
the exact same pipeline.

Story baked in: Sales and R&D run consistently over budget (growth / project overruns),
Marketing and G&A run under, Operations is on plan.

Run:  python scripts/gen_budget_data.py   ->   data/out/budget_vs_actuals.csv
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 7
START = date(2024, 6, 1)
N_MONTHS = 24

# department: (base monthly budget, mean actual/budget ratio, ratio drift over the window)
DEPARTMENTS = {
    "Sales": (120_000, 1.08, 0.06),             # over budget, drifting further over (growth)
    "Marketing": (80_000, 0.92, -0.02),         # under budget
    "R&D": (60_000, 1.12, 0.05),                # over budget (project overruns)
    "Operations": (95_000, 1.01, 0.00),         # on plan
    "G&A": (40_000, 0.97, -0.01),               # slightly under
    "Customer Success": (50_000, 1.06, 0.04),   # over (scaling)
}

# Budget line items within each department, with the share of the department's budget
# and a cost-pressure multiplier (so e.g. Software/Cloud runs hot). Splitting the budget
# into line items takes the dataset from ~150 to a few thousand realistic rows.
COST_CATEGORIES = {
    "Salaries & Wages": (0.46, 1.00),
    "Software & Cloud": (0.16, 1.15),
    "Contractors": (0.12, 1.08),
    "Travel & Events": (0.08, 0.92),
    "Marketing Programs": (0.07, 0.97),
    "Facilities": (0.06, 1.00),
    "Training": (0.03, 0.95),
    "Other": (0.02, 1.00),
}


def _months(n: int) -> list[date]:
    out, y, m = [], START.year, START.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows = []
    months = _months(N_MONTHS)
    for i, mo in enumerate(months):
        t = i / (N_MONTHS - 1)
        annual_growth = 1 + 0.04 * (mo.year - START.year)   # budgets grow ~4%/yr
        for dept, (base, ratio0, drift) in DEPARTMENTS.items():
            dept_budget = base * annual_growth
            for cat, (share, pressure) in COST_CATEGORIES.items():
                budget = round(dept_budget * share)
                actual = round(budget * (ratio0 + drift * t) * pressure
                               * float(rng.lognormal(0, 0.06)))
                rows.append({"month": mo.isoformat(), "department": dept, "category": cat,
                             "budget": budget, "actual": actual, "variance": actual - budget})
    return pd.DataFrame(rows)


def main() -> None:
    df = generate()
    root = Path(__file__).resolve().parents[1]
    out = root / "data" / "out" / "budget_vs_actuals.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    print(f"Rows: {len(df)}   Months: {df['month'].min()} -> {df['month'].max()}")
    print(f"Total budget: ${df['budget'].sum():,.0f}   Total actual: ${df['actual'].sum():,.0f}   "
          f"Net variance: ${df['variance'].sum():,.0f}")
    print("\nVariance by department (actual - budget, full period):")
    for d, v in df.groupby("department")["variance"].sum().sort_values(ascending=False).items():
        print(f"  {d:18} ${v:>12,.0f}")
    print(f"\nWrote {out.relative_to(root)}")


if __name__ == "__main__":
    main()
