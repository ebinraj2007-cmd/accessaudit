"""importer.py — Turns arbitrary company exports (CSV, Excel, JSON) into
AccessAudit's Employee / AccessRecord records, by auto-detecting which
column is which.

This is the "simple setup" path: a real company's HR export or IAM access
log will never match our internal field names exactly ("Employee Email" vs
"email", "Last Login" vs "last_used_date") — so instead of asking the user to
reformat their file, we fuzzy-match their headers against a synonym list and
build the mapping automatically. If a required field genuinely can't be
found, we say exactly what's missing instead of silently guessing wrong.
"""

from __future__ import annotations

import csv
import json
import io
import re
from typing import Optional

try:
    import openpyxl
except ImportError:
    openpyxl = None

from .models import Employee, AccessRecord

try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None


def _normalize_date(raw: Optional[str]) -> Optional[str]:
    """Real-world exports use all sorts of date formats (04/15/2026, 15-Apr-2026,
    2026-04-15T00:00:00Z, ...). Normalizes anything parseable to ISO YYYY-MM-DD;
    returns None if it can't be confidently parsed (better than crashing later)."""
    if not raw:
        return None
    if dateutil_parser is None:
        return raw  # best effort — fall back to passing it through as-is
    try:
        return dateutil_parser.parse(raw).date().isoformat()
    except (ValueError, OverflowError):
        return None

EMPLOYEE_SYNONYMS = {
    "id": ["id", "employee id", "emp id", "userid", "user id"],
    "name": ["name", "full name", "employee name", "display name"],
    "email": ["email", "email address", "user email", "work email", "account email"],
    "department": ["department", "dept", "team", "division"],
    "role": ["role", "title", "job title", "position"],
    "status": ["status", "employment status", "account status"],
    "termination_date": ["termination date", "end date", "last day", "departure date",
                          "leave date", "offboarding date"],
}

ACCESS_SYNONYMS = {
    "id": ["id", "record id", "access id"],
    "user_email": ["email", "user email", "account email", "employee email"],
    "system": ["system", "application", "app", "service", "subscription", "tool", "resource"],
    "access_level": ["access level", "permission", "privilege", "role", "level"],
    "granted_date": ["granted date", "access granted", "start date", "added date", "created date"],
    "last_used_date": ["last used", "last login", "last active", "last activity", "last used date"],
}

REQUIRED_EMPLOYEE_FIELDS = ["name", "email", "status"]
REQUIRED_ACCESS_FIELDS = ["user_email", "system"]


def _normalize(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def _auto_map(headers: list[str], synonyms: dict[str, list[str]]) -> dict[str, str]:
    """Returns {canonical_field: actual_header} for whatever it can confidently match."""
    normalized = {h: _normalize(h) for h in headers}
    mapping = {}
    for field, options in synonyms.items():
        for header, norm in normalized.items():
            if norm in options:
                mapping[field] = header
                break
    return mapping


def _read_rows(filename: str, content: bytes) -> list[dict]:
    """Reads CSV, XLSX, or JSON bytes into a list of plain dicts."""
    lower = filename.lower()

    if lower.endswith(".json"):
        data = json.loads(content.decode("utf-8"))
        return data if isinstance(data, list) else [data]

    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    if lower.endswith(".xlsx"):
        if openpyxl is None:
            raise RuntimeError("openpyxl is required to read .xlsx files (pip install openpyxl)")
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
        rows = []
        for row in rows_iter:
            if all(v is None for v in row):
                continue
            rows.append({headers[i]: row[i] for i in range(len(headers))})
        return rows

    raise ValueError(f"Unsupported file type: {filename}. Use .csv, .xlsx, or .json")


def _clean_value(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    return s


def preview_mapping(filename: str, content: bytes, kind: str) -> dict:
    """Returns the detected column mapping + any missing required fields,
    without committing anything — used so the setup wizard can show the user
    what was detected before importing."""
    rows = _read_rows(filename, content)
    if not rows:
        return {"headers": [], "mapping": {}, "missing_required": ["file appears empty"], "row_count": 0}

    headers = list(rows[0].keys())
    synonyms = EMPLOYEE_SYNONYMS if kind == "employees" else ACCESS_SYNONYMS
    required = REQUIRED_EMPLOYEE_FIELDS if kind == "employees" else REQUIRED_ACCESS_FIELDS

    mapping = _auto_map(headers, synonyms)
    missing = [f for f in required if f not in mapping]

    return {
        "headers": headers,
        "mapping": mapping,
        "missing_required": missing,
        "row_count": len(rows),
    }


def import_employees(filename: str, content: bytes) -> list[Employee]:
    rows = _read_rows(filename, content)
    headers = list(rows[0].keys()) if rows else []
    mapping = _auto_map(headers, EMPLOYEE_SYNONYMS)

    missing = [f for f in REQUIRED_EMPLOYEE_FIELDS if f not in mapping]
    if missing:
        raise ValueError(
            f"Could not confidently detect column(s) for: {', '.join(missing)}. "
            f"Found headers: {headers}. Rename the relevant column(s) and re-upload."
        )

    employees = []
    for i, row in enumerate(rows):
        email = _clean_value(row.get(mapping.get("email", "")))
        name = _clean_value(row.get(mapping.get("name", "")))
        status_raw = (_clean_value(row.get(mapping.get("status", ""))) or "active").lower()
        status = "terminated" if status_raw in {"terminated", "inactive", "offboarded", "left", "disabled"} else "active"

        if not email or not name:
            continue  # skip incomplete rows rather than failing the whole import

        employees.append(Employee(
            id=_clean_value(row.get(mapping.get("id", ""))) or f"row_{i}",
            name=name,
            email=email,
            department=_clean_value(row.get(mapping.get("department", ""))) or "Unknown",
            role=_clean_value(row.get(mapping.get("role", ""))) or "Unknown",
            status=status,
            termination_date=_normalize_date(_clean_value(row.get(mapping.get("termination_date", "")))),
        ))
    return employees


def import_access_records(filename: str, content: bytes) -> list[AccessRecord]:
    rows = _read_rows(filename, content)
    headers = list(rows[0].keys()) if rows else []
    mapping = _auto_map(headers, ACCESS_SYNONYMS)

    missing = [f for f in REQUIRED_ACCESS_FIELDS if f not in mapping]
    if missing:
        raise ValueError(
            f"Could not confidently detect column(s) for: {', '.join(missing)}. "
            f"Found headers: {headers}. Rename the relevant column(s) and re-upload."
        )

    records = []
    for i, row in enumerate(rows):
        user_email = _clean_value(row.get(mapping.get("user_email", "")))
        system = _clean_value(row.get(mapping.get("system", "")))
        if not user_email or not system:
            continue

        records.append(AccessRecord(
            id=_clean_value(row.get(mapping.get("id", ""))) or f"row_{i}",
            user_email=user_email,
            system=system,
            access_level=(_clean_value(row.get(mapping.get("access_level", ""))) or "standard").lower(),
            granted_date=_normalize_date(_clean_value(row.get(mapping.get("granted_date", "")))) or "unknown",
            last_used_date=_normalize_date(_clean_value(row.get(mapping.get("last_used_date", "")))),
        ))
    return records
