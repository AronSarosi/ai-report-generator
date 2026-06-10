"""_sanitize_sql: the gate in front of every LLM-written query."""

import pytest

from src.data_tool import _sanitize_sql


def test_accepts_plain_select():
    assert _sanitize_sql("SELECT * FROM sales") == "SELECT * FROM sales"


def test_accepts_with_cte():
    sql = "WITH t AS (SELECT 1 AS x) SELECT x FROM t"
    assert _sanitize_sql(sql) == sql


def test_strips_trailing_semicolon():
    assert _sanitize_sql("SELECT 1;") == "SELECT 1"
    assert _sanitize_sql("  SELECT 1 ;  ") == "SELECT 1"


@pytest.mark.parametrize("sql", [
    "DROP TABLE sales",
    "DELETE FROM sales",
    "INSERT INTO sales VALUES (1)",
    "UPDATE sales SET revenue = 0",
    "PRAGMA table_info(sales)",
    "ATTACH DATABASE 'x' AS other",
    "VACUUM",
])
def test_rejects_writes_and_admin(sql):
    with pytest.raises(ValueError):
        _sanitize_sql(sql)


def test_rejects_multiple_statements():
    with pytest.raises(ValueError, match="multiple statements"):
        _sanitize_sql("SELECT 1; SELECT 2")


def test_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        _sanitize_sql("   ;  ")


def test_rejects_non_select_prose():
    with pytest.raises(ValueError):
        _sanitize_sql("show me the revenue please")


def test_word_boundary_does_not_block_column_names():
    # "created"/"updated_at" contain forbidden words as substrings; \b must not match.
    assert _sanitize_sql('SELECT "created" FROM t')
    assert _sanitize_sql('SELECT "updated_at" FROM t')
