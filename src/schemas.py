"""Pydantic schemas: dataset profiling, the report request, and the report structure.

These are the typed contracts that flow through the pipeline. Using Pydantic means the
LLM is forced to return data in exactly this shape (structured output), which is what
keeps the report assembling deterministically instead of as free-form text.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Dataset profiling (what the data IS — discovered at runtime, never hardcoded)
# --------------------------------------------------------------------------- #
class ColumnRole(str, Enum):
    TIME = "time"            # a date/time axis
    MEASURE = "measure"      # a numeric value to aggregate (revenue, units, ...)
    DIMENSION = "dimension"  # a categorical to group by (region, category, ...)
    IDENTIFIER = "identifier"
    OTHER = "other"


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    role: ColumnRole
    n_unique: int
    examples: list[str] = Field(default_factory=list)
    min: Optional[str] = None
    max: Optional[str] = None


class DatasetProfile(BaseModel):
    table: str
    n_rows: int
    columns: list[ColumnProfile]
    time_col: Optional[str] = None
    measures: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)

    def schema_prompt(self) -> str:
        """Compact schema description injected into the text-to-SQL prompt."""
        lines = [f'Table "{self.table}" ({self.n_rows:,} rows). Columns:']
        for c in self.columns:
            rng = f", range {c.min}..{c.max}" if c.min is not None else ""
            ex = f", e.g. {', '.join(map(str, c.examples[:3]))}" if c.examples else ""
            lines.append(f'  - "{c.name}" {c.dtype} [{c.role.value}]{rng}{ex}')
        if self.time_col:
            lines.append(f"Time column: {self.time_col}")
        lines.append(f"Measures: {', '.join(self.measures)}")
        lines.append(f"Dimensions: {', '.join(self.dimensions)}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# SQL + analysis results
# --------------------------------------------------------------------------- #
class SQLResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list] = Field(default_factory=list)
    truncated: bool = False
    error: Optional[str] = None

    def to_markdown(self, limit: int = 25) -> str:
        if self.error:
            return f"_SQL error: {self.error}_"
        if not self.rows:
            return "_(no rows)_"
        head = "| " + " | ".join(self.columns) + " |"
        sep = "| " + " | ".join("---" for _ in self.columns) + " |"
        body = [
            "| " + " | ".join("" if v is None else str(v) for v in row) + " |"
            for row in self.rows[:limit]
        ]
        return "\n".join([head, sep, *body])


class AnalysisResult(BaseModel):
    """One computed analysis from the deterministic battery (grounding for narrative)."""

    key: str
    title: str
    sql: str
    columns: list[str]
    rows: list[list] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Report structure (the typed object the renderer turns into slides)
# --------------------------------------------------------------------------- #
class ChartSpec(BaseModel):
    kind: str = "bar"  # bar | line | stacked_bar | waterfall
    title: str = ""
    x: list[str] = Field(default_factory=list)
    series: dict[str, list[float]] = Field(default_factory=dict)
    highlight: Optional[str] = None     # which x-label/series to accent-color
    value_format: str = ",.0f"


class ReportSection(BaseModel):
    kicker: str = ""                    # ALL-CAPS section label
    action_title: str                   # the assertion (BCG action title)
    narrative: str = ""
    bullets: list[str] = Field(default_factory=list)
    so_what: Optional[str] = None       # callout takeaway
    chart: Optional[ChartSpec] = None
    citations: list[str] = Field(default_factory=list)


class KeyMessage(BaseModel):
    text: str
    status: str = "neutral"             # positive | neutral | negative (RAG chip)


class Report(BaseModel):
    title: str
    subtitle: str = ""
    period: str = ""
    governing_thought: str = ""
    key_messages: list[KeyMessage] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    generated_at: str = ""


class ReportRequest(BaseModel):
    """The three inputs: data (already loaded as `table`), intent, optional template."""

    table: str = "sales"
    intent: str = "monthly business review"
    period: Optional[str] = None        # e.g. "2026-05"; None = latest full month
    template_name: Optional[str] = None
