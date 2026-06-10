"""FastAPI entrypoint exposing the report-generation engine as an API.

Same engine as the Streamlit app, exposed as HTTP so the tool can be called
programmatically (the "production API" surface):

    GET  /health            -> liveness probe
    POST /generate          -> data file + intent  ->  a .pptx (or .pdf) download
    POST /chat              -> a question           ->  JSON answer + the SQL used

This surface is public, so it carries the same usage caps as the UI (a per-client
monthly allowance plus a global daily ceiling — src/limits.py) so a single caller
cannot run up the owner's OpenAI bill.

Run locally:
    uvicorn app.main:app --reload      # then open http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import sys
import tempfile
import uuid
from pathlib import Path

# Make the project root importable when uvicorn launches this file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from src.data_tool import answer_data_question, drop_table, load_file_to_sqlite  # noqa: E402
from src.limits import check, consume  # noqa: E402
from src.render import render_report  # noqa: E402
from src.report import build_report  # noqa: E402
from src.schemas import ReportRequest  # noqa: E402

app = FastAPI(title="AI Report Generator API", version="1.0.0")
log = logging.getLogger("ai-report-generator.api")

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_ALLOWED_SUFFIXES = {".csv", ".tsv", ".tab", ".xlsx", ".xlsm", ".xls", ".json"}
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB: generous for a tabular demo, bounds disk/DoS


def _client_id(request: Request) -> str:
    """Best-effort client id for fair-use caps. X-Forwarded-For is spoofable, so this
    is a soft gate; the global daily ceiling (src/limits.py) is the real backstop."""
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else ""
    if not ip and request.client:
        ip = request.client.host
    return ip or "anonymous"


def _gate(request: Request, kind: str) -> str:
    """Enforce the usage cap before doing any billable work. Returns the client id
    (used later to record consumption). Raises 429 when over the limit."""
    cid = _client_id(request)
    allowed, reason = check(cid, kind)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)
    return cid


def _ingest(file: UploadFile | None) -> str:
    """Load an uploaded file into a UNIQUE per-request table; fall back to the bundled
    'sales' sample. Returns the table name. The caller drops the table afterwards.

    A unique table per request is what stops two concurrent callers from overwriting
    each other's data (the API would otherwise share one 'data' table). The temp
    filename is generated here — NEVER derived from client-supplied file.filename
    (that would allow path traversal / overwriting app files)."""
    if file is None:
        return "sales"

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422,
                            detail=f"Unsupported file type. Allowed: {sorted(_ALLOWED_SUFFIXES)}")

    table = f"req_{uuid.uuid4().hex}"
    tmp = Path(tempfile.gettempdir()) / f"upload_{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with open(tmp, "wb") as fh:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_UPLOAD_BYTES:
                    limit_mb = _MAX_UPLOAD_BYTES // (1024 * 1024)
                    raise HTTPException(status_code=413,
                                        detail=f"File too large (limit {limit_mb} MB).")
                fh.write(chunk)
        load_file_to_sqlite(tmp, table=table)
    except HTTPException:
        raise
    except ValueError as e:               # bad/empty file — safe, specific message
        raise HTTPException(status_code=422, detail=f"Could not read the file: {e}")
    except Exception:                     # noqa: BLE001 — don't leak internals
        log.exception("ingest failed")
        raise HTTPException(status_code=422, detail="Could not read the uploaded file.")
    finally:
        tmp.unlink(missing_ok=True)       # raw upload no longer needed once in SQLite
    return table


@app.get("/")
def root():
    return {"service": "AI Report Generator", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate")
async def generate(request: Request, intent: str = Form(...), fmt: str = Form("pptx"),
                   file: UploadFile | None = File(None)):
    """Generate a board-ready report and return the .pptx (or .pdf) file."""
    cid = _gate(request, "report")
    table = _ingest(file)
    # Per-request output dir so two concurrent generations don't overwrite one file.
    out_dir = Path(tempfile.mkdtemp(prefix="report_"))
    try:
        report = build_report(ReportRequest(intent=intent, table=table))
        paths = render_report(report, out_dir=out_dir, charts_dir=out_dir)
    except ValueError as e:               # data has no numeric column, etc. — safe to show
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception:                     # noqa: BLE001 — don't leak internals to the client
        log.exception("report generation failed")
        raise HTTPException(status_code=500, detail="Report generation failed. Please try again.")
    finally:
        if table != "sales":
            drop_table(table)

    consume(cid, "report")
    if fmt == "pdf" and paths["pdf"]:
        return FileResponse(str(paths["pdf"]), media_type="application/pdf", filename="report.pdf")
    return FileResponse(str(paths["pptx"]), media_type=_PPTX_MIME, filename="report.pptx")


@app.post("/chat")
async def chat(request: Request, question: str = Form(...),
               file: UploadFile | None = File(None)):
    """Answer a natural-language question about the data with safe read-only SQL."""
    cid = _gate(request, "question")
    table = _ingest(file)
    try:
        res = answer_data_question(question, table=table)
    finally:
        if table != "sales":
            drop_table(table)

    consume(cid, "question")
    return JSONResponse({
        "sql": res.sql,
        "columns": res.columns,
        "rows": res.rows,
        "error": res.error,
    })
