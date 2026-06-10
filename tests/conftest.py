"""Shared fixtures: throwaway sqlite databases built from DataFrames.

Everything under tests/ is deterministic and makes NO LLM calls — the LLM-dependent
checks live in eval/ and run manually (they cost API money).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def make_db(tmp_path):
    """Write a DataFrame to a fresh sqlite file and return its path."""

    def _make(df: pd.DataFrame, table: str = "data") -> Path:
        db = tmp_path / "test.sqlite"
        with sqlite3.connect(db) as conn:
            df.to_sql(table, conn, if_exists="replace", index=False)
        return db

    return _make


@pytest.fixture(scope="session")
def sales_db(tmp_path_factory):
    """The seeded sample sales dataset: (db_path, DataFrame).

    Built from scripts.gen_sales_data.generate() (fixed SEED), so tests can compute
    pandas ground truth from the exact same rows the SQL battery sees.
    """
    from scripts.gen_sales_data import generate

    df = generate()
    db = tmp_path_factory.mktemp("salesdb") / "sales.sqlite"
    with sqlite3.connect(db) as conn:
        df.to_sql("sales", conn, if_exists="replace", index=False)
    return db, df


@pytest.fixture(scope="session")
def sales_profile(sales_db):
    from src.data_tool import profile_dataset

    db, _ = sales_db
    return profile_dataset(db_path=db, table="sales")


@pytest.fixture(scope="session")
def sales_battery(sales_db, sales_profile):
    from src.analysis import compute_battery

    db, _ = sales_db
    return compute_battery(sales_profile, db_path=db)
