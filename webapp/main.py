"""webapp/main.py — FastAPI dashboard for AccessAudit.

Run with:  uvicorn webapp.main:app --reload --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from accessaudit import storage
from accessaudit.pipeline import run_check
from accessaudit.remediation import LocalConnector

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
SAMPLE_EMPLOYEES = ROOT_DIR / "sample_data" / "employees.json"
SAMPLE_ACCESS = ROOT_DIR / "sample_data" / "access_records.json"
INDEX_HTML = (BASE_DIR / "templates" / "index.html").read_text()

connector = LocalConnector()

app = FastAPI(title="AccessAudit", description="Orphaned access & offboarding auditor")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return INDEX_HTML


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


@app.post("/api/check")
def api_check():
    findings = run_check(SAMPLE_EMPLOYEES, SAMPLE_ACCESS)
    return JSONResponse({"checked": True, "findings_count": len(findings)})


@app.post("/api/findings/{finding_id}/revoke")
def api_revoke(finding_id: str):
    conn = storage.get_connection()
    finding = storage.get_finding(conn, finding_id)
    if finding is None:
        conn.close()
        return JSONResponse({"error": "finding not found"}, status_code=404)

    result = connector.revoke_access(finding["employee_email"], finding["system"])
    storage.log_action(conn, finding_id, result)
    storage.update_finding_status(conn, finding_id, "revoked")
    conn.close()
    return JSONResponse(result)


@app.post("/api/findings/{finding_id}/reset-password")
def api_reset(finding_id: str):
    conn = storage.get_connection()
    finding = storage.get_finding(conn, finding_id)
    if finding is None:
        conn.close()
        return JSONResponse({"error": "finding not found"}, status_code=404)

    result = connector.reset_password(finding["employee_email"], finding["system"])
    storage.log_action(conn, finding_id, result)
    storage.update_finding_status(conn, finding_id, "password_reset")
    conn.close()
    return JSONResponse(result)


@app.post("/api/findings/{finding_id}/dismiss")
def api_dismiss(finding_id: str):
    conn = storage.get_connection()
    storage.update_finding_status(conn, finding_id, "dismissed")
    conn.close()
    return JSONResponse({"dismissed": True})


@app.post("/api/clear")
def api_clear():
    conn = storage.get_connection()
    storage.clear_all(conn)
    conn.close()
    return JSONResponse({"cleared": True})
