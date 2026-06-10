"""The analytical battery: deterministic, data-agnostic analyses computed in SQL.

This is the antidote to "LLM, tell me what's interesting" (which hallucinates and can't
be verified). Given only a DatasetProfile, it picks a primary measure and computes a
fixed set of real signals for the reporting period:

    - headline total vs the prior period (and % change)
    - the monthly trend
    - top/bottom breakdown by every dimension
    - the biggest movers by every dimension (period vs prior period)

Every number here comes from a real SQL query (run read-only via data_tool.run_select),
so the report narrative can be grounded in — and later verified against — these results.
"""

from __future__ import annotations

from typing import Optional

from src.data_tool import run_select
from src.schemas import AnalysisResult, DatasetProfile

# Preference order when guessing the headline measure of an arbitrary dataset.
_MEASURE_PRIORITY = ["revenue", "sales", "turnover", "amount", "net", "gross_profit",
                     "profit", "total", "value", "spend", "actual", "units"]


def _prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def _scalar(sql: str, db_path=None) -> float:
    res = run_select(sql, db_path=db_path, limit=1)
    if res.error or not res.rows or res.rows[0][0] is None:
        return 0.0
    return float(res.rows[0][0])


def pick_primary_measure(profile: DatasetProfile, db_path=None) -> str:
    """Choose the headline measure: prefer additive money-like columns, else largest sum."""
    additive = [m for m in profile.measures
                if not m.lower().startswith("unit_") and "price" not in m.lower()]
    candidates = additive or profile.measures
    if not candidates:
        raise ValueError("No numeric measure to report on. The dataset needs at least one "
                         "numeric column (for example revenue, amount, or units).")
    for key in _MEASURE_PRIORITY:
        for m in candidates:
            if key in m.lower():
                return m
    # fall back to the measure with the largest total magnitude
    best, best_sum = candidates[0], -1.0
    for m in candidates:
        total = abs(_scalar(f'SELECT SUM("{m}") FROM "{profile.table}"', db_path))
        if total > best_sum:
            best, best_sum = m, total
    return best


def resolve_period(profile: DatasetProfile, period: Optional[str] = None) -> tuple[str, str]:
    """Return (period, prior_period) as 'YYYY-MM'. Defaults to the latest month in data."""
    tcol = profile.time_col
    col = next((c for c in profile.columns if c.name == tcol), None)
    latest = (col.max or "")[:7] if col else ""
    period = period or latest or "1970-01"
    return period, _prev_month(period)


def _month_filter(tcol: str, ym: str) -> str:
    return f"substr(\"{tcol}\",1,7) = '{ym}'"


def compute_battery(profile: DatasetProfile, period: Optional[str] = None,
                    measure: Optional[str] = None, db_path=None) -> dict:
    """Compute the grounded analysis bundle. Degrades gracefully when the data has no
    time column (then there is no trend / prior-period comparison, just totals + breakdowns)."""
    table, tcol = profile.table, profile.time_col
    measure = measure if measure is not None else pick_primary_measure(profile, db_path)
    has_time = bool(tcol)

    if has_time:
        period, prior = resolve_period(profile, period)
        cur_filter = _month_filter(tcol, period)
        period_total = _scalar(f'SELECT SUM("{measure}") FROM "{table}" WHERE {cur_filter}', db_path)
        prior_total = _scalar(
            f'SELECT SUM("{measure}") FROM "{table}" WHERE {_month_filter(tcol, prior)}', db_path)
        trend_res = run_select(
            f'SELECT substr("{tcol}",1,7) AS month, SUM("{measure}") AS total '
            f'FROM "{table}" GROUP BY month ORDER BY month', db_path=db_path, limit=1000)
        trend = AnalysisResult(key="trend", title=f"Monthly {measure} (last 12 months)",
                               sql=trend_res.sql, columns=trend_res.columns, rows=trend_res.rows[-12:])
    else:
        period, prior, cur_filter = "the full dataset", None, "1=1"
        period_total = _scalar(f'SELECT SUM("{measure}") FROM "{table}"', db_path)
        prior_total, trend = None, None

    delta = (period_total - prior_total) if prior_total is not None else None
    delta_pct = (delta / prior_total) if prior_total else None

    dimensions: dict[str, dict] = {}
    for dim in profile.dimensions:
        breakdown = run_select(
            f'SELECT "{dim}", SUM("{measure}") AS total FROM "{table}" '
            f'WHERE {cur_filter} GROUP BY "{dim}" ORDER BY total DESC', db_path=db_path, limit=1000)
        if has_time:
            mv = run_select(
                f'WITH cur AS (SELECT "{dim}" v, SUM("{measure}") t FROM "{table}" '
                f'  WHERE {cur_filter} GROUP BY v), '
                f'prev AS (SELECT "{dim}" v, SUM("{measure}") t FROM "{table}" '
                f'  WHERE {_month_filter(tcol, prior)} GROUP BY v) '
                f'SELECT cur.v, ROUND(cur.t,2) cur_total, ROUND(COALESCE(prev.t,0),2) prev_total, '
                f'  ROUND(cur.t - COALESCE(prev.t,0),2) delta '
                f'FROM cur LEFT JOIN prev ON cur.v = prev.v '
                f'ORDER BY ABS(cur.t - COALESCE(prev.t,0)) DESC', db_path=db_path, limit=1000)
            movers = AnalysisResult(key=f"movers_{dim}", title=f"{dim} movers ({prior} -> {period})",
                                    sql=mv.sql, columns=mv.columns, rows=mv.rows)
        else:
            movers = AnalysisResult(key=f"movers_{dim}", title=f"{dim} movers", sql="", columns=[], rows=[])
        dimensions[dim] = {
            "breakdown": AnalysisResult(key=f"breakdown_{dim}", title=f"{measure} by {dim}",
                                        sql=breakdown.sql, columns=breakdown.columns, rows=breakdown.rows),
            "movers": movers,
        }

    return {
        "table": table, "time_col": tcol, "primary_measure": measure, "has_time": has_time,
        "period": period, "prior": prior,
        "period_total": period_total, "prior_total": prior_total,
        "delta": delta, "delta_pct": delta_pct,
        "trend": trend, "dimensions": dimensions,
    }


def battery_to_markdown(b: dict) -> str:
    """Render the battery as compact markdown to feed the writer LLM (grounding context)."""
    m, period, prior = b["primary_measure"], b["period"], b["prior"]
    header = f"PRIMARY MEASURE: {m}  |  PERIOD: {period}" + (f" (vs prior {prior})" if prior else "")
    if b["prior_total"] is not None:
        pct = f"{b['delta_pct']:+.1%}" if b["delta_pct"] is not None else "n/a"
        head_line = (f"Total {m}: {b['period_total']:,.0f} vs {b['prior_total']:,.0f} prior "
                     f"(change {b['delta']:+,.0f}, {pct})")
    else:
        head_line = f"Total {m}: {b['period_total']:,.0f}"
    out = [header, head_line]
    if b["trend"] is not None:
        out += ["", f"### {b['trend'].title}", _ar_md(b["trend"])]
    for dim, d in b["dimensions"].items():
        out.append(f"\n### {d['breakdown'].title}")
        out.append(_ar_md(d["breakdown"]))
        if d["movers"].rows:
            out.append(f"\n### {d['movers'].title}")
            out.append(_ar_md(d["movers"], limit=6))
    return "\n".join(out)


def _ar_md(ar: AnalysisResult, limit: int = 20) -> str:
    if not ar.rows:
        return "_(no rows)_"
    head = "| " + " | ".join(ar.columns) + " |"
    sep = "| " + " | ".join("---" for _ in ar.columns) + " |"
    body = ["| " + " | ".join("" if v is None else str(v) for v in row) + " |"
            for row in ar.rows[:limit]]
    return "\n".join([head, sep, *body])


if __name__ == "__main__":
    from src.data_tool import profile_dataset

    prof = profile_dataset(table="sales")
    bundle = compute_battery(prof)
    print(battery_to_markdown(bundle))
