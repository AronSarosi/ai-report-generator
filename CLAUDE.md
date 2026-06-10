# CLAUDE.md

AI Report Generator: turns a tabular data file + a plain-English prompt (and an optional
PowerPoint brand template) into a board-ready PPTX/PDF report whose every quoted number is
computed from the data, never invented by the LLM. A second surface ("Ask Your Data")
answers questions via LLM-generated read-only SQL.

## Architecture: data flow from upload to final report

```
CSV/TSV/Excel/JSON  +  prompt  +  optional .pptx/.potx brand template
        │                              │
        │ load_file_to_sqlite()        │ extract_brand()  (src/branding.py:
        ▼ (src/data_tool.py)           │  accent/ink colors + fonts from theme1.xml)
   SQLite table (data/db/*.sqlite)     │
        │                              │
        ▼                              │
  LangGraph engine  src/report.py  —  analyze → plan → write → verify → assemble
    analyze   profile_dataset() infers column roles (time/measure/dimension/id),
              then compute_battery() (src/analysis.py) runs deterministic SQL:
              period vs prior total, monthly trend, top/bottom by every dimension, movers
    plan      pure Python: battery → section specs, each with an "approved figures" list
    write     LLM (structured Pydantic output: SectionDraft/ExecDraft/RecsDraft) writes
              prose grounded in the battery; may cite ONLY the approved figure strings
    verify    regex-scans every section for $/% figures outside the approved set;
              regenerates offending sections once
    assemble  typed Report (src/schemas.py), persisted to data/out/report.json
        │
        ▼
  render_report() (src/render.py) — matplotlib chart PNGs + python-pptx deck themed by
  src/style.py (overridden by the extracted brand), then PDF via headless LibreOffice
  (degrades to PPTX-only when LibreOffice is absent)
```

Key principle: **the system owns the numbers and charts; the model only writes prose.**

Second path — Talk2Data (`src/data_tool.py`): question → `generate_sql()` (LLM) →
`run_select()` with defense in depth (read-only `mode=ro` connection + `PRAGMA query_only`,
single-statement SELECT/WITH only, keyword denylist, enforced outer LIMIT, query timeout).

Entry points:
- `app/streamlit_app.py` — Streamlit UI (two tabs sharing one uploaded dataset); also
  applies per-IP monthly usage caps (`src/limits.py`) and footer legal pages (`src/legal.py`).
- `app/main.py` — FastAPI: `GET /health`, `POST /generate` (multipart: intent, fmt,
  optional file → PPTX/PDF download), `POST /chat` (question → JSON answer + SQL).
- `eval/run_all.py` — full LLM eval suite (costs API money): Talk2Data golden QA
  (`run_eval.py`) + report-pipeline figure-grounding/structure (`run_report_eval.py`).
- `tests/` — deterministic pytest suite, no LLM calls (runs in CI): SQL guardrails,
  profiler role inference, battery math vs pandas ground truth, verifier logic.
- `infra/deploy.ps1` + `infra/main.bicep` — one-command Azure deploy (Container Apps
  UI + API from one image via `APP_MODE`, Azure OpenAI, Log Analytics, cost budget).
- `.github/workflows/` — `ci.yml` (PR: ruff + pytest), `deploy.yml` (main: OIDC login,
  `az acr build`, update both container apps).

## Model client configuration

Everything provider-related funnels through **`src/config.py`**:
- `Settings(BaseSettings)` reads the project-root `.env` (pydantic-settings, case-insensitive).
- `get_chat_model()` / `get_embeddings()` return LangChain clients for the configured
  provider: `PROVIDER=openai` → `ChatOpenAI`/`OpenAIEmbeddings`; `PROVIDER=azure` →
  `AzureChatOpenAI`/`AzureOpenAIEmbeddings`. No other module instantiates an LLM client.
- Langfuse tracing lives in `src/obs.py` (`get_callbacks()`); it is passed as a LangChain
  callback into the report graph and the text-to-SQL call, and is a silent no-op when the
  Langfuse keys are unset.

## Run it locally

Use Python **3.12** (the system 3.14 lacks wheels for some pins):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env                                    # then set OPENAI_API_KEY
.\.venv\Scripts\python.exe scripts\gen_sales_data.py      # sample data (also gen_budget_data.py)
.\.venv\Scripts\streamlit run app/streamlit_app.py        # UI on http://localhost:8501
```

Other surfaces:

```powershell
.\.venv\Scripts\uvicorn app.main:app --reload             # API on http://localhost:8000/docs
.\.venv\Scripts\python.exe -m pytest tests -q             # deterministic tests (no LLM)
.\.venv\Scripts\python.exe -m ruff check .                # lint
.\.venv\Scripts\python.exe eval\run_all.py                # LLM evals -> eval/REPORT.md
.\.venv\Scripts\python.exe -m src.report                  # engine smoke test (prints a report)
docker build -t ai-report-generator . ; docker run -p 8501:8501 --env-file .env ai-report-generator
# the same image runs the API: docker run -e APP_MODE=api -e PORT=8000 -p 8000:8000 ...
```

PDF export requires LibreOffice on PATH (the Docker image installs `libreoffice-impress`);
without it you still get the PPTX.

Azure deployment (Container Apps + ACR cloud build) is documented step-by-step in
`docs/azure_deploy.md`.

## Environment variables (all read by `Settings` in src/config.py)

| Variable | Required | Default / notes |
|---|---|---|
| `PROVIDER` | no | `openai`; set `azure` to switch the whole app to Azure OpenAI |
| `OPENAI_API_KEY` | **yes** (when PROVIDER=openai) | — |
| `OPENAI_CHAT_MODEL` | no | `gpt-4o-mini` |
| `OPENAI_EMBED_MODEL` | no | `text-embedding-3-small` |
| `AZURE_OPENAI_API_KEY` | yes when PROVIDER=azure | — |
| `AZURE_OPENAI_ENDPOINT` | yes when PROVIDER=azure | — |
| `AZURE_OPENAI_API_VERSION` | no | `2024-10-21` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | yes when PROVIDER=azure | — |
| `AZURE_OPENAI_EMBED_DEPLOYMENT` | yes when PROVIDER=azure (embeddings only) | — |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | no | both set → tracing on, else off |
| `LANGFUSE_HOST` | no | `https://cloud.langfuse.com` |
| `DB_PATH` | no | `data/db/sales.sqlite` |
| `DOCS_DIR`, `CHROMA_DIR`, `CHARTS_DIR`, `OUT_DIR` | no | under `data/` |

`.env` is gitignored and excluded from the Docker build context (`.dockerignore`); never
commit secrets.

## Conventions

- Pydantic v2 everywhere; LLM responses are forced through `with_structured_output(...)`.
- Data-agnostic by design: nothing may hardcode column names — everything derives from
  `DatasetProfile` (roles discovered at runtime in `profile_dataset()`).
- All SQL executed on user data goes through `run_select()`; never open a writable
  connection for query answering.
- Visual design rules live in `docs/report_design_spec.md`, implemented once in
  `src/style.py` — change styling there, not in `render.py` call sites.
