"""Generate a matrix of deliberately varied / messy datasets to stress-test the pipeline.

Each dataset probes a different real-world data-quality issue the report engine must
survive: missing values, dirty headers, currency-as-text, no time column, no numeric
column, huge cardinality, unicode, tiny/empty files, negatives, mixed types.

    python scripts/torture_datasets.py        # writes CSVs to data/torture/

Used by scripts/run_torture.py, which builds a report from each and saves the decks.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "torture"

REGIONS = ["North America", "EMEA", "APAC", "LATAM", "UK & Ireland"]
DEPTS = ["Sales", "Marketing", "R&D", "Operations", "G&A", "Customer Success"]
MONTHS = [f"2026-{m:02d}" for m in range(1, 6)]


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def clean_sales(rng):
    """A normal, clean dataset — the baseline."""
    rows = []
    for mo in MONTHS:
        for r in REGIONS:
            for ch in ["Online", "In-store"]:
                rows.append({"date": f"{mo}-15", "region": r, "channel": ch,
                             "revenue": round(float(rng.uniform(5000, 40000)), 2),
                             "units": int(rng.integers(50, 500))})
    return pd.DataFrame(rows)


def missing_values(rng):
    """NaNs sprinkled across measure, date and dimension columns."""
    df = clean_sales(rng)
    df.loc[df.sample(frac=0.15, random_state=1).index, "revenue"] = np.nan
    df.loc[df.sample(frac=0.10, random_state=2).index, "region"] = np.nan
    df.loc[df.sample(frac=0.08, random_state=3).index, "date"] = np.nan
    return df


def currency_strings(rng):
    """Money stored as text with $ and thousands separators (very common in exports)."""
    df = clean_sales(rng)
    df["revenue"] = df["revenue"].map(lambda v: f"${v:,.0f}")
    df["budget"] = df["revenue"].map(lambda v: v.replace("$", "$ "))  # also messy spacing
    return df


def dirty_headers(rng):
    """Whitespace, duplicate, empty, unicode and quote-bearing column names."""
    df = clean_sales(rng).copy()
    df.columns = ["  Date ", "Région", "channel", 'rev"enue', "units"]
    df["channel2"] = df["channel"]
    df.columns = ["  Date ", "Région", "channel", 'rev"enue', "units", "channel"]  # dup 'channel'
    return df


def no_time_column(rng):
    """Pure cross-section: department spend, no date axis at all."""
    return pd.DataFrame({"department": DEPTS * 3,
                         "spend": [round(float(rng.uniform(20000, 150000)), 2)
                                   for _ in range(len(DEPTS) * 3)],
                         "headcount": [int(rng.integers(5, 80)) for _ in range(len(DEPTS) * 3)]})


def no_numeric_column(rng):
    """Only categorical columns — should yield a clean 'no measure' message, not a crash."""
    return pd.DataFrame({"date": MONTHS * 2,
                         "region": (REGIONS + REGIONS)[:len(MONTHS) * 2],
                         "status": ["open", "closed"] * len(MONTHS)})


def huge_cardinality(rng):
    """A near-unique text column that must NOT become a 1000-bar chart."""
    n = 1500
    return pd.DataFrame({"date": [MONTHS[i % len(MONTHS)] + "-15" for i in range(n)],
                         "transaction_id": [f"txn-{i:06d}" for i in range(n)],
                         "customer": [f"cust-{rng.integers(0, 1200)}" for _ in range(n)],
                         "amount": [round(float(rng.uniform(10, 900)), 2) for _ in range(n)]})


def unicode_and_emoji(rng):
    """Non-ASCII dimension values and column names."""
    regions = ["Zürich", "São Paulo", "Tōkyō", "México", "Köln"]
    rows = []
    for mo in MONTHS:
        for r in regions:
            rows.append({"date": f"{mo}-15", "région": r, "produit": "Café ☕",
                         "chiffre_d_affaires": round(float(rng.uniform(1000, 9000)), 2)})
    return pd.DataFrame(rows)


def negatives_and_zeros(rng):
    """Budget variance with negatives and exact zeros (sign + div-by-zero paths)."""
    rows = []
    for mo in MONTHS:
        for d in DEPTS:
            budget = float(rng.integers(40000, 120000))
            actual = budget + float(rng.normal(0, 15000))
            rows.append({"month": mo, "department": d, "budget": round(budget, 2),
                         "actual": round(actual, 2), "variance": round(actual - budget, 2)})
    rows.append({"month": "2026-05", "department": "New Unit", "budget": 0.0,
                 "actual": 0.0, "variance": 0.0})  # zero row
    return pd.DataFrame(rows)


def mixed_types(rng):
    """A measure column polluted with stray text and sentinels ('N/A')."""
    df = clean_sales(rng).copy()
    df["units"] = df["units"].astype(object)
    idx = df.sample(frac=0.1, random_state=5).index
    df.loc[idx, "units"] = "N/A"
    return df


def single_row(rng):
    return pd.DataFrame({"date": ["2026-05-15"], "region": ["EMEA"], "revenue": [12345.67]})


def wide_many_dims(rng):
    """Many low-cardinality categorical columns -> tests the dimension cap (cost)."""
    n = 300
    data = {"date": [MONTHS[i % len(MONTHS)] + "-15" for i in range(n)],
            "revenue": [round(float(rng.uniform(100, 9000)), 2) for _ in range(n)]}
    for d in range(20):  # 20 dimensions; only the first few should be reported
        data[f"attr_{d}"] = [f"v{rng.integers(0, 4)}" for _ in range(n)]
    return pd.DataFrame(data)


DATASETS = {
    "01_clean_sales": clean_sales,
    "02_missing_values": missing_values,
    "03_currency_strings": currency_strings,
    "04_dirty_headers": dirty_headers,
    "05_no_time_column": no_time_column,
    "06_no_numeric_column": no_numeric_column,
    "07_huge_cardinality": huge_cardinality,
    "08_unicode": unicode_and_emoji,
    "09_negatives_zeros": negatives_and_zeros,
    "10_mixed_types": mixed_types,
    "11_single_row": single_row,
    "12_wide_many_dims": wide_many_dims,
}

INTENTS = {
    "01_clean_sales": "Monthly sales review highlighting strong and weak regions",
    "02_missing_values": "Monthly sales review",
    "03_currency_strings": "Monthly revenue review by region and channel",
    "04_dirty_headers": "Monthly performance review",
    "05_no_time_column": "Departmental spend review",
    "06_no_numeric_column": "Status overview",
    "07_huge_cardinality": "Monthly transactions review",
    "08_unicode": "Revue mensuelle du chiffre d'affaires par region",
    "09_negatives_zeros": "Budget vs actuals review for May 2026",
    "10_mixed_types": "Monthly sales review",
    "11_single_row": "Sales snapshot",
    "12_wide_many_dims": "Monthly revenue review",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in DATASETS.items():
        df = fn(_rng(abs(hash(name)) % (2**31)))
        path = OUT / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"wrote {path.relative_to(ROOT)}  ({df.shape[0]} rows x {df.shape[1]} cols)")


if __name__ == "__main__":
    main()
