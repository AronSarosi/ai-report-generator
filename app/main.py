"""FastAPI entrypoint exposing the report-generation engine as an API.

Same engine as the Streamlit app, exposed as HTTP so the tool can be called
programmatically (the "production API" surface):

    GET  /health            -> liveness probe
    POST /generate          -> data file + intent  ->  a .pptx (or .pdf) download
    POST /chat              -> a question           ->  JSON answer + the SQL used

Run locally:
    uvicorn app.main:app --reload      # then open http://localhost:8000/docs
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

# Make the project root importable when uvicorn launches this file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from src.data_tool import answer_data_question, load_file_to_sqlite  # noqa: E402
from src.render import render_report  # noqa: E402
from src.report import build_report  # noqa: E402
from src.schemas import ReportRequest  # noqa: E402

app = FastAPI(title="AI Report Generator API", version="1.0.0")

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _ingest(file: UploadFile | None) -> str:
    """Load an uploaded file into a table; fall back to the bundled 'sales' sample."""
    if file is None:
        return "sales"
    tmp = Path(tempfile.gettempdir()) / file.filename
    with open(tmp, "wb") as fh:
        shutil.copyfileobj(file.file, fh)
    load_file_to_sqlite(tmp, table="data")
    return "data"


@app.get("/")
def root():
    return {"service": "AI Report Generator", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate")
async def generate(intent: str = Form(...), fmt: str = Form("pptx"),
                   file: UploadFile | None = File(None)):
    """Generate a board-ready report and return the .pptx (or .pdf) file."""
    table = _ingest(file)
    try:
        report = build_report(ReportRequest(intent=intent, table=table))
        paths = render_report(report)
    except ValueError as e:               # data has no numeric column, etc.
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:                # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    if fmt == "pdf" and paths["pdf"]:
        return FileResponse(str(paths["pdf"]), media_type="application/pdf", filename="report.pdf")
    return FileResponse(str(paths["pptx"]), media_type=_PPTX_MIME, filename="report.pptx")


@app.post("/chat")
async def chat(question: str = Form(...), file: UploadFile | None = File(None)):
    """Answer a natural-language question about the data with safe read-only SQL."""
    table = _ingest(file)
    res = answer_data_question(question, table=table)
    return JSONResponse({
        "sql": res.sql,
        "columns": res.columns,
        "rows": res.rows,
        "error": res.error,
    })
