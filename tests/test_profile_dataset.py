"""profile_dataset: runtime role inference — the heart of being data-agnostic."""

import pandas as pd

from src.data_tool import profile_dataset
from src.schemas import ColumnRole


def _roles(profile):
    return {c.name: c.role for c in profile.columns}


def test_iso_date_strings_are_time(make_db):
    df = pd.DataFrame({"date": ["2026-01-01", "2026-01-02", "2026-02-01"],
                       "amount": [1.5, 2.5, 3.5]})
    p = profile_dataset(db_path=make_db(df), table="data")
    roles = _roles(p)
    assert roles["date"] == ColumnRole.TIME
    assert p.time_col == "date"
    col = next(c for c in p.columns if c.name == "date")
    assert col.min == "2026-01-01"
    assert col.max == "2026-02-01"


def test_numeric_strings_are_not_dates(make_db):
    df = pd.DataFrame({"code": ["1234", "5678", "9012"], "amount": [1.0, 2.0, 3.0]})
    p = profile_dataset(db_path=make_db(df), table="data")
    assert _roles(p)["code"] != ColumnRole.TIME


def test_contiguous_ints_are_identifier(make_db):
    df = pd.DataFrame({"row": [1, 2, 3, 4, 5], "amount": [10.0, 20.0, 30.0, 40.0, 50.0]})
    p = profile_dataset(db_path=make_db(df), table="data")
    assert _roles(p)["row"] == ColumnRole.IDENTIFIER


def test_id_by_name_is_identifier(make_db):
    df = pd.DataFrame({"customer_id": [7, 7, 12, 99], "amount": [1.0, 2.0, 3.0, 4.0]})
    p = profile_dataset(db_path=make_db(df), table="data")
    assert _roles(p)["customer_id"] == ColumnRole.IDENTIFIER
    assert "customer_id" not in p.measures


def test_non_contiguous_ints_are_measure(make_db):
    df = pd.DataFrame({"units": [3, 17, 3, 240], "dept": ["a", "b", "a", "c"]})
    p = profile_dataset(db_path=make_db(df), table="data")
    assert _roles(p)["units"] == ColumnRole.MEASURE
    assert "units" in p.measures


def test_floats_are_measure_with_range(make_db):
    df = pd.DataFrame({"spend": [10.5, 99.25, 4.0]})
    p = profile_dataset(db_path=make_db(df), table="data")
    col = next(c for c in p.columns if c.name == "spend")
    assert col.role == ColumnRole.MEASURE
    assert col.min == "4"        # _fmt collapses whole floats to ints
    assert col.max == "99.25"


def test_low_cardinality_strings_are_dimension(make_db):
    df = pd.DataFrame({"region": ["EMEA", "APAC"] * 10, "amount": [1.0] * 20})
    p = profile_dataset(db_path=make_db(df), table="data")
    assert _roles(p)["region"] == ColumnRole.DIMENSION
    assert "region" in p.dimensions


def test_high_cardinality_strings_are_other(make_db):
    # 120 unique values: n_unique > max(50, n_rows // 2) -> OTHER, not a dimension
    df = pd.DataFrame({"comment": [f"note-{i}" for i in range(120)], "amount": [1.0] * 120})
    p = profile_dataset(db_path=make_db(df), table="data")
    assert _roles(p)["comment"] == ColumnRole.OTHER
    assert "comment" not in p.dimensions


def test_summary_lists(sales_profile):
    assert sales_profile.time_col == "date"
    assert "revenue" in sales_profile.measures
    for dim in ("region", "channel", "category", "product"):
        assert dim in sales_profile.dimensions
    assert sales_profile.n_rows > 0
