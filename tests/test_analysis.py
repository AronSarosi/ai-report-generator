"""compute_battery: every battery number must match pandas ground truth computed
from the exact same seeded rows."""

import pandas as pd
import pytest

from src.analysis import _prev_month, compute_battery, pick_primary_measure, resolve_period
from src.data_tool import profile_dataset


def test_prev_month():
    assert _prev_month("2026-01") == "2025-12"
    assert _prev_month("2024-06") == "2024-05"
    assert _prev_month("2025-12") == "2025-11"


def test_resolve_period_defaults_to_latest(sales_profile):
    assert resolve_period(sales_profile) == ("2026-05", "2026-04")


def test_resolve_period_explicit(sales_profile):
    assert resolve_period(sales_profile, "2025-11") == ("2025-11", "2025-10")


def test_pick_primary_measure_prefers_revenue(sales_db, sales_profile):
    db, _ = sales_db
    assert pick_primary_measure(sales_profile, db_path=db) == "revenue"


def test_pick_primary_measure_units_only(make_db):
    df = pd.DataFrame({"date": ["2026-01-01", "2026-01-02"], "units": [3, 240]})
    db = make_db(df)
    p = profile_dataset(db_path=db, table="data")
    assert pick_primary_measure(p, db_path=db) == "units"


def test_pick_primary_measure_no_numeric_raises(make_db):
    df = pd.DataFrame({"region": ["EMEA", "APAC"], "owner": ["a", "b"]})
    db = make_db(df)
    p = profile_dataset(db_path=db, table="data")
    with pytest.raises(ValueError, match="numeric"):
        pick_primary_measure(p, db_path=db)


def test_headline_totals_match_pandas(sales_db, sales_battery):
    _, df = sales_db
    b = sales_battery
    may = df[df["date"].str[:7] == "2026-05"]["revenue"].sum()
    apr = df[df["date"].str[:7] == "2026-04"]["revenue"].sum()
    assert b["period"] == "2026-05"
    assert b["prior"] == "2026-04"
    assert b["period_total"] == pytest.approx(may, rel=1e-6)
    assert b["prior_total"] == pytest.approx(apr, rel=1e-6)
    assert b["delta"] == pytest.approx(may - apr, rel=1e-6)
    assert b["delta_pct"] == pytest.approx((may - apr) / apr, rel=1e-6)


def test_trend_is_last_12_months(sales_db, sales_battery):
    _, df = sales_db
    trend = sales_battery["trend"]
    assert len(trend.rows) <= 12
    assert trend.rows[-1][0] == "2026-05"
    may = df[df["date"].str[:7] == "2026-05"]["revenue"].sum()
    assert trend.rows[-1][1] == pytest.approx(may, rel=1e-6)
    months = [r[0] for r in trend.rows]
    assert months == sorted(months)


def test_breakdown_matches_pandas(sales_db, sales_battery):
    _, df = sales_db
    may = df[df["date"].str[:7] == "2026-05"]
    truth = may.groupby("region")["revenue"].sum().sort_values(ascending=False)
    rows = sales_battery["dimensions"]["region"]["breakdown"].rows
    assert [r[0] for r in rows] == list(truth.index)
    for (name, total), row in zip(truth.items(), rows):
        assert row[1] == pytest.approx(total, rel=1e-6)


def test_movers_delta_is_cur_minus_prev(sales_battery):
    rows = sales_battery["dimensions"]["category"]["movers"].rows
    assert rows, "movers should not be empty for the sales data"
    for value, cur, prev, delta in rows:
        assert delta == pytest.approx(cur - prev, abs=0.02)  # each column rounded to 2dp
    # ordered by |delta| descending
    deltas = [abs(r[3]) for r in rows]
    assert deltas == sorted(deltas, reverse=True)


def test_no_time_column_degrades_gracefully(make_db):
    df = pd.DataFrame({"dept": ["ops", "it", "hr", "ops"],
                       "spend": [100.0, 250.0, 75.0, 25.0]})
    db = make_db(df)
    p = profile_dataset(db_path=db, table="data")
    b = compute_battery(p, db_path=db)
    assert b["has_time"] is False
    assert b["period"] == "the full dataset"
    assert b["prior_total"] is None
    assert b["trend"] is None
    assert b["period_total"] == pytest.approx(450.0)
    assert b["dimensions"]["dept"]["movers"].rows == []
