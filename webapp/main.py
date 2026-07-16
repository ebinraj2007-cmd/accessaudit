"""webapp/main.py — FastAPI dashboard for AccessAudit.

Run with:  uvicorn webapp.main:app --port 8010

Hardened against the standard pre-deployment checklist:
  1. Authorization  - state-changing endpoints require ACCESSAUDIT_TOKEN when set.
  3. Input validation - upload size cap, kind whitelist, parameterised SQL.
  4. CORS           - restricted to ACCESSAUDIT_ORIGINS (not '*').
  5. Rate limiting  - per-IP, stricter on uploads / sample-load / clear.
  6. Error handling - safe validation messages only; internals logged, not leaked.
  8. Logging/health - structured request logging + /healthz.
  9. Rollback       - see DEPLOY.md.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, UploadFile, File, Depends, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from accessaudit import storage, importer
from accessaudit.pipeline import run_check, run_check_with_data
from accessaudit.remediation import LocalConnector
from webapp.security import (
    require_token, rate_check, reset_rate_limits, token_configured, max_upload_bytes,
)

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
SAMPLE_EMPLOYEES = ROOT_DIR / "sample_data" / "employees.json"
SAMPLE_ACCESS = ROOT_DIR / "sample_data" / "access_records.json"
INDEX_HTML = (BASE_DIR / "templates" / "index.html").read_text()

logging.basicConfig(
    level=os.environ.get("ACCESSAUDIT_LOG_LEVEL", "INFO"),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("accessaudit")

connector = LocalConnector()
_staged: dict[str, list] = {"employees": None, "access": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not token_configured():
        log.warning("ACCESSAUDIT_TOKEN not set - trusted local mode; set it before "
                    "exposing AccessAudit beyond 127.0.0.1")
    yield


app = FastAPI(title="AccessAudit", description="Orphaned access & offboarding auditor",
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

_origins = os.environ.get(
    "ACCESSAUDIT_ORIGINS", "http://localhost:8010,http://127.0.0.1:8010",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def _guard(request: Request, call_next):
    if request.url.path.startswith("/api/") and not rate_check(request):
        log.warning("rate limit exceeded path=%s", request.url.path)
        return JSONResponse(status_code=429, content={"error": "Too many requests. Slow down."})
    start = time.monotonic()
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        log.info("request path=%s status=%s ms=%.1f",
                 request.url.path, response.status_code, (time.monotonic() - start) * 1000)
    return response


@app.exception_handler(HTTPException)
async def _http_err(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("unhandled error path=%s", request.url.path)  # detail server-side only
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/healthz")
def healthz():
    try:
        conn = storage.get_connection()
        conn.close()
        return {"status": "ok", "auth": "on" if token_configured() else "local"}
    except Exception:
        raise HTTPException(status_code=503, detail="storage unavailable")


async def _read_capped(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > max_upload_bytes():
        raise HTTPException(status_code=413, detail="File too large")
    return content


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return INDEX_HTML


@app.get("/api/setup-status")
def api_setup_status():
    conn = storage.get_connection()
    has_findings = len(storage.get_all_findings(conn)) > 0
    conn.close()
    return JSONResponse({
        "has_data": has_findings,
        "employees_staged": _staged["employees"] is not None,
        "access_staged": _staged["access"] is not None,
    })


@app.post("/api/upload/preview", dependencies=[Depends(require_token)])
async def api_upload_preview(kind: str, file: UploadFile = File(...)):
    if kind not in ("employees", "access"):
        raise HTTPException(status_code=400, detail="kind must be 'employees' or 'access'")
    content = await _read_capped(file)
    try:
        return JSONResponse(importer.preview_mapping(file.filename, content, kind))
    except (ValueError, KeyError) as e:
        # importer raises human-readable validation messages that are safe to show
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/upload/{kind}", dependencies=[Depends(require_token)])
async def api_upload(kind: str, file: UploadFile = File(...)):
    if kind not in ("employees", "access"):
        raise HTTPException(status_code=400, detail="kind must be 'employees' or 'access'")
    content = await _read_capped(file)
    try:
        if kind == "employees":
            _staged["employees"] = importer.import_employees(file.filename, content)
        else:
            _staged["access"] = importer.import_access_records(file.filename, content)
    except (ValueError, KeyError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    ready = _staged["employees"] is not None and _staged["access"] is not None
    result = {
        "uploaded": kind,
        "row_count": len(_staged[kind]),
        "employees_staged": _staged["employees"] is not None,
        "access_staged": _staged["access"] is not None,
        "ready_to_check": ready,
    }
    if ready:
        findings = run_check_with_data(_staged["employees"], _staged["access"])
        result["checked"] = True
        result["findings_count"] = len(findings)
    return JSONResponse(result)


@app.post("/api/use-sample-data", dependencies=[Depends(require_token)])
def api_use_sample_data():
    findings = run_check(SAMPLE_EMPLOYEES, SAMPLE_ACCESS)
    return JSONResponse({"checked": True, "findings_count": len(findings)})


@app.get("/api/findings")
def api_findings():
    conn = storage.get_connection()
    rows = storage.get_all_findings(conn)
    conn.close()
    return JSONResponse([dict(row) for row in rows])


@app.get("/api/stats")
def api_stats():
    conn = storage.get_connection()
    stats = storage.get_stats(conn)
    conn.close()
    return JSONResponse(stats)


@app.get("/api/action-log")
def api_action_log():
    conn = storage.get_connection()
    rows = storage.get_action_log(conn)
    conn.close()
    return JSONResponse([dict(row) for row in rows])


@app.post("/api/findings/{finding_id}/revoke", dependencies=[Depends(require_token)])
def api_revoke(finding_id: str):
    conn = storage.get_connection()
    finding = storage.get_finding(conn, finding_id)
    if finding is None:
        conn.close()
        raise HTTPException(status_code=404, detail="finding not found")
    result = connector.revoke_access(finding["employee_email"], finding["system"])
    storage.log_action(conn, finding_id, result)
    storage.update_finding_status(conn, finding_id, "revoked")
    conn.close()
    return JSONResponse(result)


@app.post("/api/findings/{finding_id}/reset-password", dependencies=[Depends(require_token)])
def api_reset(finding_id: str):
    conn = storage.get_connection()
    finding = storage.get_finding(conn, finding_id)
    if finding is None:
        conn.close()
        raise HTTPException(status_code=404, detail="finding not found")
    result = connector.reset_password(finding["employee_email"], finding["system"])
    storage.log_action(conn, finding_id, result)
    storage.update_finding_status(conn, finding_id, "password_reset")
    conn.close()
    return JSONResponse(result)


@app.post("/api/findings/{finding_id}/dismiss", dependencies=[Depends(require_token)])
def api_dismiss(finding_id: str):
    conn = storage.get_connection()
    storage.update_finding_status(conn, finding_id, "dismissed")
    conn.close()
    return JSONResponse({"dismissed": True})


@app.post("/api/clear", dependencies=[Depends(require_token)])
def api_clear():
    conn = storage.get_connection()
    storage.clear_all(conn)
    conn.close()
    _staged["employees"] = None
    _staged["access"] = None
    return JSONResponse({"cleared": True})
