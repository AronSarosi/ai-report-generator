# AI Report Generator

**Turn a data file into a finished, board-ready report - charts and narrative grounded in the real numbers.**

### Live demo: https://report-generator-zbibsntn5a-nw.a.run.app

(Hosted on Google Cloud Run with scale-to-zero, so the first request after an idle period takes a little while to cold-start, then it's quick.)

Upload a CSV or Excel file, describe the report you want ("monthly sales review highlighting the winning products and regions"), and the app generates a consulting-grade PowerPoint + PDF: action-title slides, charts, and a written narrative where **every quoted number is pulled from the data and re-checked against it**. The same engine works on any tabular dataset - sales, budget-vs-actuals, inventory - because it discovers the schema at runtime instead of hardcoding it.

> Status: live on Google Cloud Run. Built for a finance-team use case; data-agnostic by design.

---

## Why it's different from "ask ChatGPT to write a report"

A language model asked to summarise a spreadsheet will happily **invent numbers**. This tool is built so it can't:

1. It **computes** the real figures with SQL (period-over-period change, trends, top/bottom by every dimension, biggest movers) - deterministically, before any text is written.
2. The model only ever **narrates those computed numbers**, and is given an explicit list of "approved figures" it is allowed to cite.
3. A **verify step** then scans the narrative for any `$`/`%` figure that isn't in the approved set and regenerates that section.

That grounding + verification loop is the whole point: a report a CFO can trust.

---

## What it does

Upload a CSV/Excel/JSON file plus a plain-English prompt, and the app produces a finished PPTX/PDF report: action-title slides, charts, and a grounded narrative.

There is also a second, programmatic surface (not in the UI): a FastAPI `/chat` endpoint that answers plain-English questions against the same data via safe read-only SQL (Talk2Data, in `src/data_tool.py`), with an eval harness that scores it against a golden-QA set. The profiling and SQL engine it relies on is the same one that powers report generation.

---

## Architecture

```
            Streamlit UI  (upload data + prompt)
                                   |
                          LangGraph engine
              analyze -> plan -> write -> verify -> assemble
                                   |
        +--------------------------+---------------------------+
        |  profiler   (discovers time / measures / dimensions) |
        |  analytical battery   (the real numbers, in SQL)     |
        |  writer   (LLM, structured Pydantic output)          |
        |  renderer (matplotlib charts + python-pptx -> PDF)   |
        +--------------------------+---------------------------+
                                   |
                  SQLite (the uploaded data, loaded at runtime)
```

The same profiling + read-only SQL engine also backs a programmatic Talk2Data `/chat` API (text-to-SQL), exercised by the eval harness rather than the UI.

## How it works (the pipeline, end to end)

1. **Ingest** - the uploaded CSV/Excel/JSON is loaded into a **SQLite** table (`src/data_tool.py`).
2. **Profile** - a runtime profiler inspects the table and infers each column's *role*: which is the **time** axis, which are numeric **measures** (revenue, units, budget...), which are categorical **dimensions** (region, department...). Nothing is hardcoded - this is what makes the engine data-agnostic.
3. **Analytical battery** (`src/analysis.py`) - given only that profile, it computes a fixed set of real signals in SQL: headline total vs the prior period, the monthly trend, top/bottom breakdown by every dimension, and the biggest movers. Every value is a real query result.
4. **Report engine** (`src/report.py`) - a **LangGraph** state machine: `analyze -> plan -> write -> verify -> assemble`. `plan` turns the battery into a section list; `write` calls the LLM with **structured (Pydantic) output** so it returns typed sections (action title, narrative, bullets), grounded in the battery's numbers; `verify` checks no invented figures slipped in; `assemble` produces a typed `Report`.
5. **Render** (`src/render.py`) - the `Report` becomes **matplotlib** charts and a **python-pptx** deck (one design system in `src/style.py`), then exports to **PDF** via LibreOffice.

The same engine also powers **Talk2Data** (`src/data_tool.py`), the programmatic `/chat` surface: the LLM writes a single read-only `SELECT` against the discovered schema. Safety is defense-in-depth: a **read-only SQLite connection**, single-statement + `SELECT`-only validation, a keyword denylist, a query timeout, and an enforced `LIMIT`.

The design separates two responsibilities on purpose: **the system owns the numbers and charts; the model only writes prose.**

## Data-agnostic, proven

The repo ships two deliberately different synthetic datasets. The *same* engine produces a sales review from one and an FP&A spend report from the other:

- `scripts/gen_sales_data.py` -> daily sales (date, region, channel, category, product, revenue, margin)
- `scripts/gen_budget_data.py` -> monthly budget-vs-actuals (month, department, budget, actual, variance)

It also degrades gracefully: data with **no date column** drops the trend analysis and reports on totals + breakdowns; data with **no numeric column** returns a clear message instead of crashing.

## Tech stack

Python 3.12, **LangChain / LangGraph**, **OpenAI** (`gpt-4o-mini`), **Pydantic v2** (structured output), **SQLite**, **pandas**, **matplotlib**, **python-pptx** + LibreOffice (PDF), **Streamlit**, **FastAPI**, **Langfuse** (LLM tracing). Deployed on **Google Cloud Run**.

## Run it locally

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # then add your OPENAI_API_KEY
.\.venv\Scripts\python.exe scripts\gen_sales_data.py      # build the sample data
.\.venv\Scripts\streamlit run app/streamlit_app.py        # open http://localhost:8501
```

`.env` keys: `OPENAI_API_KEY` (required), `OPENAI_CHAT_MODEL`, and optional `LANGFUSE_*`. `.env` is gitignored and never committed.

## Tests and evals

```powershell
pip install -r requirements-dev.txt
pytest -q                            # deterministic suite, no LLM calls (also runs in CI)
python eval\run_all.py               # LLM evals (costs API money) -> eval/REPORT.md:
                                     #   Talk2Data golden-QA accuracy + full report-pipeline
                                     #   figure-grounding and structure checks
```

## Deploy

The repo ships a single `Dockerfile` (the same image runs the Streamlit UI or, with
`APP_MODE=api`, the FastAPI service). It is deployed to **Google Cloud Run** with
scale-to-zero.

## Project layout

```
app/      Streamlit UI (streamlit_app.py) + FastAPI service (main.py)
src/      config, schemas, style, data_tool (profile + Talk2Data), analysis
          (battery), report (LangGraph), render (PPTX/PDF), obs
tests/    deterministic pytest suite (SQL guardrails, profiler, battery math, verifier, render)
eval/     LLM evals: Talk2Data golden QA + report-pipeline grounding -> REPORT.md
docker/   entrypoint (APP_MODE=ui|api) + healthcheck
scripts/  synthetic data generators + favicon
data/     db/ docs/ charts/ out/   (runtime; gitignored)
docs/     report_design_spec.md
```

## Roadmap

- **Talk2Document (RAG)** - answer questions from uploaded reference docs/templates

## Notes

- Cost is tiny: `gpt-4o-mini` keeps a full report well under a cent of API usage.
- No secrets in the repo; the OpenAI key lives only in a local, gitignored `.env`.
