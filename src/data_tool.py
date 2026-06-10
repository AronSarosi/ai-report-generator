"""Talk2Data: load any tabular file, profile it, and answer questions with safe SQL.

This is the data-agnostic core. Nothing here knows about "sales" specifically — it
discovers the schema of whatever table it is pointed at and reasons from that.

Pipeline:
    load_csv_to_sqlite()  ->  profile_dataset()  ->  generate_sql()  ->  run_select()

Safety model for SQL (defense in depth, since an LLM writes the query):
    1. The DB is opened with a READ-ONLY connection (file:...?mode=ro + PRAGMA query_only),
       so a write literally cannot execute even if one slipped through.
    2. The query must be a single statement starting with SELECT/WITH.
    3. A keyword denylist rejects INSERT/UPDATE/DELETE/DROP/etc.
    4. The query is wrapped in an outer LIMIT, and a progress handler aborts long queries.
"""

from __future__ import annotations

import re
import sqlite3
import time
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd

from src.config import get_chat_model, get_settings
from src.schemas import ColumnProfile, ColumnRole, DatasetProfile, SQLResult

# --------------------------------------------------------------------------- #
# Loading + profiling
# --------------------------------------------------------------------------- #
# Bound the work a single upload can create (cost + memory + readability).
MAX_ROWS = 200_000
_NUMERIC_JUNK = re.compile(r"[,$€£%\s]")
_NULL_TOKENS = {"", "na", "n/a", "nan", "none", "null", "-", "—", "."}


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Make column names safe SQL identifiers and chart labels: strip whitespace and
    double-quotes (which would break the quoted-identifier SQL), fill blanks, dedupe.
    A double-quote in a header is the SQL-injection vector, so it is removed here."""
    seen: dict[str, int] = {}
    names: list[str] = []
    for i, raw in enumerate(df.columns):
        name = re.sub(r"\s+", " ", str(raw).replace('"', "")).strip()
        if not name:
            name = f"col_{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        names.append(name)
    df = df.copy()
    df.columns = names
    return df


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Real-world exports store numbers as text: '$1,234', '12%', '1,000'. If a text
    column is overwhelmingly numeric once $/,/%/space are stripped, convert it so it
    can be used as a measure instead of being silently ignored."""
    for col in df.columns:
        ser = df[col]
        if not (ser.dtype == object):
            continue
        s = ser.dropna().astype(str).str.strip()
        if s.empty:
            continue
        non_null = s[~s.str.lower().isin(_NULL_TOKENS)]
        if non_null.empty:
            continue
        cleaned = non_null.str.replace(_NUMERIC_JUNK, "", regex=True)
        parsed = pd.to_numeric(cleaned, errors="coerce")
        if parsed.notna().mean() >= 0.95:  # almost all values are numeric-looking
            full = pd.to_numeric(
                ser.astype(str).str.strip()
                   .mask(ser.astype(str).str.strip().str.lower().isin(_NULL_TOKENS))
                   .str.replace(_NUMERIC_JUNK, "", regex=True),
                errors="coerce")
            df[col] = full
    return df


def load_file_to_sqlite(path, table: str = "data", db_path=None) -> int:
    """Load a CSV / TSV / Excel / JSON file into a SQLite table (replacing it).

    Cleans the data first (safe column names, numeric coercion, row cap) so messy
    real-world exports don't crash the loader or silently lose their metric columns.
    Returns the row count. Excel needs the openpyxl engine (in requirements).
    """
    s = get_settings()
    db_path = Path(db_path or s.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(path)               # first sheet
    elif ext in (".tsv", ".tab"):
        df = pd.read_csv(path, sep="\t")
    elif ext == ".json":
        df = pd.read_json(path)
    else:
        df = pd.read_csv(path)

    if df.shape[1] == 0:
        raise ValueError("The file has no columns to read.")
    if len(df) > MAX_ROWS:
        df = df.head(MAX_ROWS)
    df = _coerce_numeric(_clean_columns(df))

    with sqlite3.connect(db_path) as conn:
        df.to_sql(table, conn, if_exists="replace", index=False)
    return len(df)


def load_csv_to_sqlite(csv_path, table: str = "sales", db_path=None) -> int:
    """Back-compat wrapper around load_file_to_sqlite."""
    return load_file_to_sqlite(csv_path, table=table, db_path=db_path)


def drop_table(table: str, db_path=None) -> None:
    """Drop a per-request table once its report is built (keeps the shared DB tidy and
    stops one request's upload lingering for the next). Table name is double-quoted."""
    db_path = Path(db_path or get_settings().db_path)
    if not db_path.exists():
        return
    safe = '"' + str(table).replace('"', "") + '"'
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {safe}")


_DATE_NAME = re.compile(r"(date|month|day|period|time|year|week|quarter|_at$)", re.I)
_ID_NAME = re.compile(r"(^id$|_id$|^.*_?key$)", re.I)


def _parse_dates(series: pd.Series) -> pd.Series:
    """Coerce to datetime, silencing pandas' 'could not infer format' chatter."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(series, errors="coerce")


def _looks_like_date(series: pd.Series) -> bool:
    sample = series.dropna().astype(str).head(200)
    if sample.empty:
        return False
    if sample.str.fullmatch(r"-?\d+(\.\d+)?").all():  # pure numbers are not dates
        return False
    return _parse_dates(sample).notna().mean() > 0.9


def _fmt(x) -> str:
    try:
        f = float(x)
        return str(int(f)) if f == int(f) else f"{f:.2f}"
    except (TypeError, ValueError):
        return str(x)


def profile_dataset(db_path=None, table: str = "sales") -> DatasetProfile:
    """Introspect a table and infer each column's role (time/measure/dimension/id)."""
    s = get_settings()
    db_path = Path(db_path or s.db_path)
    uri = f"file:{db_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        df = pd.read_sql(f'SELECT * FROM "{table}"', conn)

    n_rows = len(df)
    cols: list[ColumnProfile] = []
    for name in df.columns:
        ser = df[name]
        dtype = str(ser.dtype)
        n_unique = int(ser.nunique(dropna=True))
        is_numeric = pd.api.types.is_numeric_dtype(ser)
        role, cmin, cmax = ColumnRole.OTHER, None, None

        if _looks_like_date(ser) and (not is_numeric or _DATE_NAME.search(name)):
            role = ColumnRole.TIME
            parsed = _parse_dates(ser)
            if parsed.notna().any():
                cmin, cmax = str(parsed.min().date()), str(parsed.max().date())
        elif is_numeric:
            # Treat an integer column as an identifier only by name, or when it is a
            # contiguous run of distinct values (a row index / auto-increment id) -- NOT
            # just because a measure happens to be all-distinct in a small file.
            is_int = pd.api.types.is_integer_dtype(ser)
            contiguous = bool(is_int and n_unique == n_rows and n_rows > 0 and ser.notna().all()
                              and int(ser.max()) - int(ser.min()) + 1 == n_rows)
            id_like = bool(_ID_NAME.search(name)) or contiguous
            if id_like:
                role = ColumnRole.IDENTIFIER
            else:
                role = ColumnRole.MEASURE
                cmin, cmax = _fmt(ser.min()), _fmt(ser.max())
        else:
            # A categorical to group by — but a near-unique text column (free-text notes,
            # ids) makes a useless 1000-bar breakdown, so cap the absolute cardinality too.
            is_dim = n_unique <= max(50, n_rows // 2) and n_unique <= 1000
            role = ColumnRole.DIMENSION if is_dim else ColumnRole.OTHER

        examples = [str(v) for v in ser.dropna().unique()[:5]]
        cols.append(ColumnProfile(name=name, dtype=dtype, role=role,
                                  n_unique=n_unique, examples=examples, min=cmin, max=cmax))

    return DatasetProfile(
        table=table, n_rows=n_rows, columns=cols,
        time_col=next((c.name for c in cols if c.role == ColumnRole.TIME), None),
        measures=[c.name for c in cols if c.role == ColumnRole.MEASURE],
        dimensions=[c.name for c in cols if c.role == ColumnRole.DIMENSION],
    )


# --------------------------------------------------------------------------- #
# Safe SQL execution
# --------------------------------------------------------------------------- #
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|"
    r"vacuum|reindex|truncate|grant|revoke|trigger)\b", re.I)


def _sanitize_sql(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise ValueError("empty query")
    if ";" in s:
        raise ValueError("multiple statements are not allowed")
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        raise ValueError("only SELECT/WITH queries are allowed")
    if _FORBIDDEN.search(s):
        raise ValueError("query contains a forbidden keyword")
    return s


def run_select(sql: str, db_path=None, limit: int = 1000, timeout_s: float = 5.0) -> SQLResult:
    """Validate and execute a read-only SELECT; never raises, returns SQLResult."""
    s = get_settings()
    db_path = Path(db_path or s.db_path)
    try:
        cleaned = _sanitize_sql(sql)
    except ValueError as e:
        return SQLResult(sql=sql, columns=[], error=f"refused: {e}")

    wrapped = f"SELECT * FROM (\n{cleaned}\n) AS _sub LIMIT {limit}"
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        start = time.monotonic()
        conn.set_progress_handler(lambda: 1 if time.monotonic() - start > timeout_s else 0, 10000)
        cur = conn.execute(wrapped)
        columns = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchall()]
        return SQLResult(sql=cleaned, columns=columns, rows=rows, truncated=len(rows) >= limit)
    except Exception as e:  # noqa: BLE001 - surface any DB error as data, not a crash
        return SQLResult(sql=cleaned, columns=[], error=str(e))
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Text-to-SQL
# --------------------------------------------------------------------------- #
_NOT_ANSWERABLE = "NOT_ANSWERABLE"

_SQL_SYS = f"""You are a meticulous data analyst who writes SQLite SQL.
Given a table schema and a question, write ONE read-only SELECT (or WITH ... SELECT)
that answers it. Rules:
- Output ONLY the SQL. No prose, no explanation, no markdown code fences.
- Use the exact column names, wrapped in double quotes.
- Dates are ISO text 'YYYY-MM-DD'; use substr("<date_col>",1,7) to group by month.
- Aggregate with SUM/COUNT/AVG and GROUP BY as needed; add ORDER BY and LIMIT for "top N".
- COMPARISONS / CHANGE OVER TIME: when the question asks which category grew/declined/
  changed the most, or about a rise/drop/mover "vs last month" or "between month A and B",
  compute the change between the two periods and order by it. Use a CTE so you can reference
  the computed columns (SQLite forbids using a SELECT alias inside the same SELECT list):
    WITH t AS (
      SELECT "<dim>" AS k,
             SUM(CASE WHEN substr("<date>",1,7)='<current>' THEN "<measure>" ELSE 0 END) AS cur,
             SUM(CASE WHEN substr("<date>",1,7)='<prior>'   THEN "<measure>" ELSE 0 END) AS prev
      FROM "<table>" GROUP BY "<dim>")
    SELECT k, cur, prev, cur - prev AS change FROM t ORDER BY change ASC LIMIT 1
  Use ORDER BY change ASC for "declined the most", DESC for "grew the most". Do NOT answer a
  "declined/grew the most" question with just the lowest/highest total — it is the change
  between the two periods.
- Never modify data.
- If the question cannot be answered from THIS schema (it is off-topic, general
  knowledge, or asks about a column/entity that does not exist), output exactly
  {_NOT_ANSWERABLE} and nothing else. Do NOT invent a substitute query."""


def _extract_sql(text: str) -> str:
    t = text.strip()
    if "```" in t:
        m = re.search(r"```(?:sql)?\s*(.*?)```", t, re.S | re.I)
        if m:
            t = m.group(1).strip()
    return t.strip()


def generate_sql(question: str, profile: DatasetProfile) -> str:
    """Ask the chat model to turn a natural-language question into SQL."""
    llm = get_chat_model(temperature=0)
    anchor = ""
    if profile.time_col:
        tcol = next((c for c in profile.columns if c.name == profile.time_col), None)
        if tcol and tcol.max:
            anchor = (f'\nNote: the latest value of "{profile.time_col}" is {tcol.max}. '
                      f"Resolve relative periods like 'last month' or 'latest' against this date.")
    user = f"Schema:\n{profile.schema_prompt()}\n\nQuestion: {question}{anchor}\n\nReturn only the SQL."
    from src.obs import get_callbacks
    msg = llm.invoke([{"role": "system", "content": _SQL_SYS},
                      {"role": "user", "content": user}],
                     config={"callbacks": get_callbacks()})
    return _extract_sql(msg.content if hasattr(msg, "content") else str(msg))


def answer_data_question(question: str, db_path=None, table: str = "sales",
                         profile: Optional[DatasetProfile] = None, limit: int = 1000) -> SQLResult:
    """Full Talk2Data: NL question -> SQL -> safe execution -> result (with the SQL)."""
    s = get_settings()
    db_path = Path(db_path or s.db_path)
    profile = profile or profile_dataset(db_path, table)
    sql = generate_sql(question, profile)
    # The model flags questions it cannot answer from this schema (off-topic / missing
    # column) instead of fabricating a plausible-but-wrong query.
    if sql.strip().upper().startswith(_NOT_ANSWERABLE):
        return SQLResult(
            sql="", columns=[],
            error="I couldn't answer that from this dataset. Try asking about its columns, "
                  "such as totals, breakdowns by a category, or trends over time.")
    return run_select(sql, db_path=db_path, limit=limit)


# --------------------------------------------------------------------------- #
# Smoke test:  python -m src.data_tool
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    prof = profile_dataset(table="sales")
    print("=== DISCOVERED SCHEMA (no hardcoding) ===")
    print(prof.schema_prompt())

    print("\n=== Talk2Data: 'top 5 products by revenue in the last full month' ===")
    res = answer_data_question("What are the top 5 products by revenue in the last full month?")
    print("SQL:\n" + res.sql + "\n")
    print(res.to_markdown())

    print("\n=== Safety guardrail test ===")
    bad = run_select("DROP TABLE sales;")
    print("Tried 'DROP TABLE sales;' ->", bad.error)
    bad2 = run_select("DELETE FROM sales")
    print("Tried 'DELETE FROM sales' ->", bad2.error)
