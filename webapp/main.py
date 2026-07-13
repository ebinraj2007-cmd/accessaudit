"""webapp/main.py — FastAPI dashboard for AccessAudit.

Run with:  uvicorn webapp.main:app --reload --port 8010
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from accessaudit import storage, importer
from accessaudit.pipeline import run_check, run_check_with_data
from accessaudit.remediation import LocalConnector

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
SAMPLE_EMPLOYEES = ROOT_DIR / "sample_data" / "employees.json"
SAMPLE_ACCESS = ROOT_DIR / "sample_data" / "access_records.json"
INDEX_HTML = (BASE_DIR / "templates" / "index.html").read_text()

connector = LocalConnector()

# Simple in-memory staging area: a real IAM/HR export usually arrives as two
# separate files (employee roster, access log). We hold whichever one arrived
# first until its pair shows up, then run the check. This is a local single-user
# tool (no auth, no multi-tenant concerns), so process memory is a reasonable
# place for this — no database migration needed for a two-step wizard.
_staged: dict[str, list] = {"employees": None, "access": None}

app = FastAPI(title="AccessAudit", description="Orphaned access & offboarding auditor")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


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


@app.post("/api/upload/preview")
async def api_upload_preview(kind: str, file: UploadFile = File(...)):
    content = await file.read()
    try:
        preview = importer.preview_mapping(file.filename, content, kind)
        return JSONResponse(preview)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/upload/{kind}")
async def api_upload(kind: str, file: UploadFile = File(...)):
    if kind not in ("employees", "access"):
        return JSONResponse({"error": "kind must be 'employees' or 'access'"}, status_code=400)

    content = await file.read()
    try:
        if kind == "employees":
            _staged["employees"] = importer.import_employees(file.filename, content)
        else:
            _staged["access"] = importer.import_access_records(file.filename, content)
    except Exception as e:
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


@app.post("/api/use-sample-data")
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
    _staged["employees"] = None
    _staged["access"] = None
    return JSONResponse({"cleared": True})
