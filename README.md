# AI Report Generator

**Turn a data file into a finished, board-ready report — charts and narrative grounded in the real numbers — and ask questions of the same data in plain English.**

Upload a CSV or Excel file, describe the report you want ("monthly sales review highlighting the winning products and regions"), and the app generates a consulting-grade PowerPoint + PDF: action-title slides, charts, and a written narrative where **every quoted number is pulled from the data and re-checked against it**. The same engine works on any tabular dataset — sales, budget-vs-actuals, inventory — because it discovers the schema at runtime instead of hardcoding it.

> Status: working local app (Phase A). Built for a finance-team use case; data-agnostic by design.

---

## Why it's different from "ask ChatGPT to write a report"

A language model asked to summarise a spreadsheet will happily **invent numbers**. This tool is built so it can't:

1. It **computes** the real figures with SQL (period-over-period change, trends, top/bottom by every dimension, biggest movers) — deterministically, before any text is written.
2. The model only ever **narrates those computed numbers**, and is given an explicit list of "approved figures" it is allowed to cite.
3. A **verify step** then scans the narrative for any `$`/`%` figure that isn't in the approved set and regenerates that section.

That grounding + verification loop is the whole point: a report a CFO can trust.

---

## What it does

| Capability | What it is |
|---|---|
| **Generate Report** | data + a prompt → a finished PPTX/PDF (charts + grounded narrative) |
| **Ask Your Data** | a plain-English question → safe read-only SQL → the answer (with the SQL one click away) |

---

## Architecture

```
            Streamlit UI  (upload data + prompt  ·  or ask a question)
                                   │
        ┌──────────────────────────┴───────────────────────────┐
        │                                                       │
   Generate Report                                         Ask Your Data
        │                                                       │
   LangGraph engine                                       Talk2Data
   analyze → plan → write → verify → assemble             (text-to-SQL)
        │                                                       │
        ├── profiler  (discovers time / measures / dimensions) ─┤
        ├── analytical battery  (the real numbers, in SQL)      │
        ├── writer  (LLM, structured Pydantic output)           │
        └── renderer (matplotlib charts + python-pptx → PDF)    │
                                   │                            │
                              SQLite (the uploaded data, loaded at runtime)
```

## How it works (the pipeline, end to end)

1. **Ingest** — the uploaded CSV/Excel/JSON is loaded into a **SQLite** table (`src/data_tool.py`).
2. **Profile** — a runtime profiler inspects the table and infers each column's *role*: which is the **time** axis, which are numeric **measures** (revenue, units, budget…), which are categorical **dimensions** (region, department…). Nothing is hardcoded — this is what makes the engine data-agnostic.
3. **Analytical battery** (`src/analysis.py`) — given only that profile, it computes a fixed set of real signals in SQL: headline total vs the prior period, the monthly trend, top/bottom breakdown by every dimension, and the biggest movers. Every value is a real query result.
4. **Report engine** (`src/report.py`) — a **LangGraph** state machine: `analyze → plan → write → verify → assemble`. `plan` turns the battery into a section list; `write` calls the LLM with **structured (Pydantic) output** so it returns typed sections (action title, narrative, bullets), grounded in the battery's numbers; `verify` checks no invented figures slipped in; `assemble` produces a typed `Report`.
5. **Talk2Data** (`src/data_tool.py`) — for the chat tab, the LLM writes a single read-only `SELECT` against the discovered schema. Safety is defense-in-depth: a **read-only SQLite connection**, single-statement + `SELECT`-only validation, a keyword denylist, a query timeout, and an enforced `LIMIT`.
6. **Render** (`src/render.py`) — the `Report` becomes **matplotlib** charts and a **python-pptx** deck (one design system in `src/style.py`), then exports to **PDF** via LibreOffice.

The design separates two responsibilities on purpose: **the system owns the numbers and charts; the model only writes prose.**

## Data-agnostic, proven

The repo ships two deliberately different synthetic datasets. The *same* engine produces a sales review from one and an FP&A spend report from the other:

- `scripts/gen_sales_data.py` → daily sales (date · region · channel · category · product · revenue · margin)
- `scripts/gen_budget_data.py` → monthly budget-vs-actuals (month · department · budget · actual · variance)

It also degrades gracefully: data with **no date column** drops the trend analysis and reports on totals + breakdowns; data with **no numeric column** returns a clear message instead of crashing.

## Tech stack

Python 3.12 · **LangChain / LangGraph** · **OpenAI** (`gpt-4o-mini`, `text-embedding-3-small`) · **Pydantic v2** (structured output) · **SQLite** · **pandas** · **matplotlib** · **python-pptx** + LibreOffice (PDF) · **Streamlit** · **Langfuse** (LLM tracing) · provider switch for **Azure OpenAI** (Phase B).

## Run it locally

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # then add your OPENAI_API_KEY
.\.venv\Scripts\python.exe scripts\gen_sales_data.py      # build the sample data
.\.venv\Scripts\streamlit run app/streamlit_app.py        # open http://localhost:8501
```

`.env` keys: `OPENAI_API_KEY` (required), `OPENAI_CHAT_MODEL`, `OPENAI_EMBED_MODEL`, optional `LANGFUSE_*`, and `AZURE_*` for Phase B. `.env` is gitignored and never committed.

## Tests and evals

```powershell
pip install -r requirements-dev.txt
pytest -q                            # deterministic suite, no LLM calls (also runs in CI)
python eval\run_all.py               # LLM evals (costs API money) -> eval/REPORT.md:
                                     #   Talk2Data golden-QA accuracy + full report-pipeline
                                     #   figure-grounding and structure checks
```

## Deploy to Azure

One command: `.\infra\deploy.ps1` — Bicep-defined Container Apps (UI + API from one image,
scale-to-zero), Azure OpenAI, Log Analytics, and a cost budget. Pushes to `main` redeploy
automatically via GitHub Actions (OIDC). Details in `docs/azure_deploy.md`.

## Project layout

```
app/      Streamlit UI (streamlit_app.py) + FastAPI service (main.py)
src/      config · schemas · style · data_tool (profile + Talk2Data) · analysis
          (battery) · report (LangGraph) · render (PPTX/PDF) · rag · obs
tests/    deterministic pytest suite (SQL guardrails, profiler, battery math, verifier)
eval/     LLM evals: Talk2Data golden QA + report-pipeline grounding -> REPORT.md
infra/    main.bicep (Container Apps, Azure OpenAI, budget) + deploy.ps1
docker/   entrypoint (APP_MODE=ui|api) + healthcheck
scripts/  synthetic data generators + favicon
data/     db/ docs/ charts/ out/   (runtime; gitignored)
docs/     report_design_spec.md · azure_deploy.md
```

## Roadmap

- **Talk2Document (RAG)** — answer questions from uploaded reference docs/templates
- **Azure AI Search** — swap Chroma for the managed vector store once RAG lands

## Notes

- Cost is tiny: `gpt-4o-mini` keeps a full report well under a cent of API usage.
- No secrets in the repo; the OpenAI key lives only in a local, gitignored `.env`.
