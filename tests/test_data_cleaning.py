"""Data-cleaning at load time: safe headers, numeric coercion, row cap, drop_table.
These guard the messy-real-world-data path (dirty headers, currency strings, NaNs)."""

import sqlite3

import pandas as pd

from src.data_tool import (
    MAX_ROWS,
    _clean_columns,
    _coerce_numeric,
    drop_table,
    profile_dataset,
    run_select,
)
from src.schemas import ColumnRole


def test_clean_columns_dedupes_and_strips():
    df = pd.DataFrame([[1, 2, 3, 4]], columns=["  Region ", "Region", "", "a\nb"])
    out = _clean_columns(df)
    assert out.columns.tolist() == ["Region", "Region_2", "col_3", "a b"]


def test_clean_columns_strips_doublequote_injection_vector():
    # a double-quote in a header is the SQL identifier-breakout vector - must be removed
    df = pd.DataFrame([[1]], columns=['x" FROM data--'])
    assert '"' not in _clean_columns(df).columns[0]


def test_duplicate_headers_do_not_crash_load(make_db, tmp_path):
    # pandas allows dup columns in memory; cleaning must make them loadable into SQLite
    csv = tmp_path / "dup.csv"
    csv.write_text("region,region,amount\nEMEA,APAC,5\n", encoding="utf-8")
    from src.data_tool import load_file_to_sqlite
    db = tmp_path / "d.sqlite"
    n = load_file_to_sqlite(csv, table="data", db_path=db)
    assert n == 1
    res = run_select("SELECT * FROM data", db_path=db)
    assert res.error is None


def test_coerce_numeric_currency_strings():
    df = pd.DataFrame({"revenue": ["$1,234", "$2,000", "$3,500.50"],
                       "region": ["EMEA", "APAC", "EMEA"]})
    out = _coerce_numeric(df)
    assert pd.api.types.is_numeric_dtype(out["revenue"])
    assert out["revenue"].tolist() == [1234.0, 2000.0, 3500.50]
    assert out["region"].dtype == object  # genuine categorical left alone


def test_coerce_numeric_leaves_categoricals():
    df = pd.DataFrame({"dept": ["Sales", "R&D", "Ops"]})
    assert _coerce_numeric(df)["dept"].dtype == object


def test_currency_strings_become_a_measure(tmp_path):
    csv = tmp_path / "money.csv"
    csv.write_text("month,dept,spend\n2026-01,Sales,\"$1,000\"\n2026-01,Ops,\"$2,500\"\n",
                   encoding="utf-8")
    from src.data_tool import load_file_to_sqlite
    db = tmp_path / "m.sqlite"
    load_file_to_sqlite(csv, table="data", db_path=db)
    prof = profile_dataset(db_path=db, table="data")
    assert "spend" in prof.measures
    spend_col = next(c for c in prof.columns if c.name == "spend")
    assert spend_col.role == ColumnRole.MEASURE


def test_drop_table(tmp_path):
    db = tmp_path / "d.sqlite"
    with sqlite3.connect(db) as conn:
        pd.DataFrame({"a": [1]}).to_sql("req_x", conn, index=False)
    drop_table("req_x", db_path=db)
    res = run_select("SELECT * FROM req_x", db_path=db)
    assert res.error is not None  # table is gone


def test_max_rows_is_sane():
    assert MAX_ROWS >= 10_000
