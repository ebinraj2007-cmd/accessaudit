"""pipeline.py — Orchestrates ingest -> audit -> store. This is what runs
when the user says "check"."""

from __future__ import annotations

from pathlib import Path

from . import ingest, storage
from .auditor import run_audit


def run_check(employees_path: str | Path, access_path: str | Path,
              db_path: Path | None = None) -> list[dict]:
    employees = ingest.load_employees(employees_path)
    access_records = ingest.load_access_records(access_path)
    return run_check_with_data(employees, access_records, db_path)


def run_check_with_data(employees, access_records, db_path: Path | None = None) -> list[dict]:
    """Same as run_check, but takes already-loaded Employee/AccessRecord lists —
    used by the upload flow, where data comes from a parsed file rather than a path."""
    findings = run_audit(employees, access_records)

    conn = storage.get_connection(db_path)
    storage.save_findings(conn, findings)
    conn.close()

    return [f.to_dict() for f in findings]
