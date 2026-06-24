"""Generate a synthetic but believable sales dataset for the demo.

The dataset is deliberately given a *story* so the generated report has real
findings to surface (this is what separates a convincing demo from random noise):

  - Overall revenue grows over the ~2-year window.
  - One category (Beauty & Wellness) is surging; one (Media & Entertainment) is
    structurally declining; the rest are mild/flat.
  - The Online channel steadily takes share from In-store.
  - One region (LATAM) underperforms and is trending down.
  - Clear seasonality: a Q4 holiday spike, a summer dip, and weekend uplift.

Everything is driven by a fixed seed so the data is fully reproducible. Money
columns let the report talk about revenue, margin, and gross profit (finance-y).

Outputs:
  data/out/sales_sample.csv   one flat table - this is the file a user "uploads"
  data/db/sales.sqlite        the same rows loaded into a `sales` table for dev

Run:  python scripts/gen_sales_data.py
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Reproducibility + window
# --------------------------------------------------------------------------- #
SEED = 42
# Fixed (not "today") so the dataset is deterministic. Ends on a full month so
# "last full month" demos cleanly land on May 2026.
END_DATE = date(2026, 5, 31)
START_DATE = date(2024, 6, 1)

# --------------------------------------------------------------------------- #
# Dimensions and the "story" knobs
# --------------------------------------------------------------------------- #
REGIONS = {                   # base demand multiplier per region (board-level regions)
    "North America": 1.25,    # the star region
    "EMEA": 1.05,
    "APAC": 1.00,
    "LATAM": 0.85,            # the underperformer (also given a downward trend below)
    "UK & Ireland": 0.95,
}
CHANNELS = ["In-store", "Online"]

# Category revenue trend across the window, expressed as (start_mult -> end_mult).
CATEGORY_TREND = {
    "Electronics": (1.00, 1.30),            # mild growth
    "Home & Kitchen": (1.00, 1.05),         # flat
    "Apparel": (1.12, 0.90),                # mild decline
    "Beauty & Wellness": (0.65, 1.75),      # strong growth (the winner)
    "Media & Entertainment": (1.55, 0.55),  # strong decline (the loser)
}

# product: (category, unit_price, gross_margin, base_daily_units_per_region)
PRODUCTS = {
    "Wireless Earbuds": ("Electronics", 79.99, 0.35, 11),
    "Smart Speaker": ("Electronics", 49.99, 0.30, 8),
    "USB-C Charger": ("Electronics", 19.99, 0.45, 14),
    "Air Fryer": ("Home & Kitchen", 89.99, 0.30, 9),
    "Cookware Set": ("Home & Kitchen", 129.99, 0.35, 5),
    "Coffee Grinder": ("Home & Kitchen", 39.99, 0.40, 7),
    "Running Tee": ("Apparel", 24.99, 0.55, 12),
    "Denim Jacket": ("Apparel", 69.99, 0.50, 6),
    "Wool Socks 3-pack": ("Apparel", 14.99, 0.60, 10),
    "Vitamin C Serum": ("Beauty & Wellness", 29.99, 0.65, 9),
    "Electric Toothbrush": ("Beauty & Wellness", 59.99, 0.45, 7),
    "Collagen Powder": ("Beauty & Wellness", 34.99, 0.60, 8),
    "Blu-ray Box Set": ("Media & Entertainment", 39.99, 0.25, 7),
    "Vinyl Record": ("Media & Entertainment", 27.99, 0.40, 6),
    "Board Game": ("Media & Entertainment", 34.99, 0.45, 8),
}

# Month-of-year seasonality (holiday spike in Nov/Dec, summer dip).
ANNUAL = {1: 0.90, 2: 0.85, 3: 0.95, 4: 1.00, 5: 1.00, 6: 0.95,
          7: 0.88, 8: 0.90, 9: 1.00, 10: 1.08, 11: 1.30, 12: 1.45}

# Day-of-week seasonality (Mon=0 .. Sun=6); weekends lift in-store retail.
WEEKDAY = [0.90, 0.90, 0.95, 1.00, 1.15, 1.32, 1.10]


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b for t in [0, 1]."""
    return a + (b - a) * t


def generate() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    n_days = (END_DATE - START_DATE).days + 1
    rows: list[dict] = []

    for d in range(n_days):
        day = START_DATE + timedelta(days=d)
        t = d / (n_days - 1)                 # 0.0 at start -> 1.0 at end
        annual = ANNUAL[day.month]
        weekday = WEEKDAY[day.weekday()]
        online_share = _lerp(0.25, 0.55, t)  # Online takes share over time

        for product, (category, price, margin, base) in PRODUCTS.items():
            c0, c1 = CATEGORY_TREND[category]
            cat_factor = _lerp(c0, c1, t)
            unit_cost = round(price * (1.0 - margin), 2)

            for region, region_base in REGIONS.items():
                region_factor = region_base
                if region == "LATAM":        # extra downward drift for the laggard
                    region_factor *= _lerp(1.05, 0.65, t)

                for channel in CHANNELS:
                    channel_share = online_share if channel == "Online" else 1.0 - online_share
                    # Online is less weekend-peaky than in-store.
                    wk = weekday if channel == "In-store" else 1.0 + (weekday - 1.0) * 0.4

                    expected = (base * cat_factor * annual * wk
                                * region_factor * channel_share)
                    expected *= rng.lognormal(0.0, 0.22)   # multiplicative noise
                    units = int(rng.poisson(max(expected, 0.0)))
                    if units == 0:
                        continue             # mimic real exports: only rows with sales

                    # Occasional promotion.
                    discount = float(rng.choice([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                                 0.10, 0.15, 0.20, 0.25]))
                    revenue = round(units * price * (1.0 - discount), 2)
                    cost = round(units * unit_cost, 2)
                    rows.append({
                        "date": day.isoformat(),
                        "region": region,
                        "channel": channel,
                        "category": category,
                        "product": product,
                        "units": units,
                        "unit_price": price,
                        "discount_pct": round(discount, 2),
                        "revenue": revenue,
                        "unit_cost": unit_cost,
                        "cost": cost,
                        "gross_profit": round(revenue - cost, 2),
                    })

    df = pd.DataFrame(rows)
    return df.sort_values(["date", "region", "channel", "category", "product"]).reset_index(drop=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    csv_path = root / "data" / "out" / "sales_sample.csv"
    db_path = root / "data" / "db" / "sales.sqlite"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    df = generate()

    df.to_csv(csv_path, index=False)
    with sqlite3.connect(db_path) as conn:
        df.to_sql("sales", conn, if_exists="replace", index=False)

    # ----- summary so you can sanity-check the story -------------------------
    def money(x):
        return f"${x:,.0f}"
    print(f"Rows: {len(df):,}   Date range: {df['date'].min()} -> {df['date'].max()}")
    print(f"Total revenue: {money(df['revenue'].sum())}   "
          f"Gross profit: {money(df['gross_profit'].sum())}   "
          f"Margin: {df['gross_profit'].sum() / df['revenue'].sum():.1%}")
    print(f"Wrote {csv_path.relative_to(root)} and {db_path.relative_to(root)}")

    print("\nRevenue by category:")
    by_cat = df.groupby("category")["revenue"].sum().sort_values(ascending=False)
    for name, val in by_cat.items():
        print(f"  {name:24} {money(val)}")

    print("\nRevenue by region:")
    by_region = df.groupby("region")["revenue"].sum().sort_values(ascending=False)
    for name, val in by_region.items():
        print(f"  {name:24} {money(val)}")

    print("\nOnline channel share (first vs last full month):")
    df["_month"] = df["date"].str.slice(0, 7)
    months = sorted(df["_month"].unique())
    for m in (months[0], months[-1]):
        sub = df[df["_month"] == m]
        share = sub.loc[sub["channel"] == "Online", "revenue"].sum() / sub["revenue"].sum()
        print(f"  {m}: {share:.1%} online")

    print("\nTop 5 products by revenue:")
    top = df.groupby("product")["revenue"].sum().sort_values(ascending=False).head(5)
    for name, val in top.items():
        print(f"  {name:24} {money(val)}")


if __name__ == "__main__":
    main()
