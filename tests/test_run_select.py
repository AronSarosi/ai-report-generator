"""run_select: read-only execution that returns errors as data, never raises."""

import pandas as pd

from src.data_tool import run_select


def _df():
    return pd.DataFrame({
        "region": ["EMEA", "APAC", "EMEA", "LATAM"],
        "revenue": [100.0, 200.0, 50.0, 25.0],
    })


def test_happy_path(make_db):
    db = make_db(_df())
    res = run_select('SELECT "region", SUM("revenue") AS total FROM data GROUP BY "region" '
                     "ORDER BY total DESC", db_path=db)
    assert res.error is None
    assert res.columns == ["region", "total"]
    assert res.rows[0] == ["APAC", 200.0]
    assert res.rows[1] == ["EMEA", 150.0]


def test_limit_and_truncated_flag(make_db):
    db = make_db(pd.DataFrame({"n": range(10)}))
    res = run_select("SELECT n FROM data", db_path=db, limit=5)
    assert len(res.rows) == 5
    assert res.truncated is True
    res_all = run_select("SELECT n FROM data", db_path=db, limit=100)
    assert len(res_all.rows) == 10
    assert res_all.truncated is False


def test_write_is_refused_not_raised(make_db):
    db = make_db(_df())
    res = run_select("DELETE FROM data", db_path=db)
    assert res.error is not None
    assert res.error.startswith("refused:")
    assert res.rows == []
    # the table is untouched
    check = run_select("SELECT COUNT(*) FROM data", db_path=db)
    assert check.rows[0][0] == 4


def test_broken_sql_returns_error_not_exception(make_db):
    db = make_db(_df())
    res = run_select("SELECT * FROM does_not_exist", db_path=db)
    assert res.error is not None
    assert "does_not_exist" in res.error
