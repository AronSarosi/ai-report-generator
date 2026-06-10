"""answer_data_question: the unanswerable-question guard and normal flow.
LLM call is monkeypatched so these stay deterministic and free."""

import pandas as pd

import src.data_tool as dt


def _sales_db(make_db):
    df = pd.DataFrame({
        "date": ["2026-05-01", "2026-05-02", "2026-04-15"],
        "region": ["EMEA", "APAC", "EMEA"],
        "revenue": [100.0, 200.0, 50.0],
    })
    return make_db(df)


def test_unanswerable_question_returns_friendly_message(make_db, monkeypatch):
    db = _sales_db(make_db)
    monkeypatch.setattr(dt, "generate_sql", lambda q, p: dt._NOT_ANSWERABLE)
    res = dt.answer_data_question("What is the capital of France?", db_path=db, table="data")
    assert res.rows == []
    assert res.error and "couldn't answer" in res.error.lower()
    assert res.sql == ""  # no misleading query shown


def test_answerable_question_runs_the_sql(make_db, monkeypatch):
    db = _sales_db(make_db)
    monkeypatch.setattr(dt, "generate_sql",
                        lambda q, p: 'SELECT SUM("revenue") AS t FROM "data"')
    res = dt.answer_data_question("total revenue?", db_path=db, table="data")
    assert res.error is None
    assert res.rows[0][0] == 350.0


def test_not_answerable_sentinel_is_uppercase_token():
    # guard relies on a stable sentinel string
    assert dt._NOT_ANSWERABLE == "NOT_ANSWERABLE"
