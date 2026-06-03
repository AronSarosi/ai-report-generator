# ai-report-generator

A data-agnostic AI report generator: feed it a data file and a template, and it
produces a finished report — charts plus narrative grounded in the real numbers —
exported to PowerPoint and PDF. Demoed on synthetic sales data.

> Skeleton only — feature logic is not implemented yet.

## Layout

```
app/      Streamlit UI (streamlit_app.py) and FastAPI entrypoint (main.py)
src/      Core library: config, data tools, RAG, report orchestration, rendering,
          schemas, observability
scripts/  Data generation and document ingestion utilities
data/     db/ (SQLite), docs/ (source docs), charts/ (generated), out/ (reports)
eval/     QA pairs and the evaluation runner
```

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env   # then fill in your keys
```

## Stack

Python 3.12 · LangChain / LangGraph · OpenAI · ChromaDB · pandas · matplotlib ·
python-pptx · Streamlit · FastAPI · Langfuse
