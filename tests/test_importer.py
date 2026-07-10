import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from accessaudit.importer import (
    import_employees, import_access_records, preview_mapping, _normalize_date
)


def test_import_employees_from_csv_with_different_header_names():
    csv_content = (
        "Full Name,Work Email,Team,Job Title,Employment Status,Last Day\n"
        "Jane Doe,jane.doe@company.com,Finance,Analyst,Terminated,04/15/2026\n"
        "Bob Smith,bob.smith@company.com,Engineering,Engineer,Active,\n"
    ).encode("utf-8")

    employees = import_employees("export.csv", csv_content)
    assert len(employees) == 2

    jane = next(e for e in employees if e.email == "jane.doe@company.com")
    assert jane.status == "terminated"
    assert jane.termination_date == "2026-04-15"
    assert jane.department == "Finance"

    bob = next(e for e in employees if e.email == "bob.smith@company.com")
    assert bob.status == "active"


def test_import_employees_missing_required_column_raises_clear_error():
    csv_content = "Full Name,Team\nJane Doe,Finance\n".encode("utf-8")
    with pytest.raises(ValueError) as exc_info:
        import_employees("export.csv", csv_content)
    assert "email" in str(exc_info.value).lower()


def test_import_access_records_from_csv():
    csv_content = (
        "User Email,Application,Permission,Access Granted,Last Login\n"
        "jane.doe@company.com,AWS Console,admin,2024-01-15,2026-04-14\n"
        "bob.smith@company.com,CRM,standard,2024-02-01,2026-07-08\n"
    ).encode("utf-8")

    records = import_access_records("export.csv", csv_content)
    assert len(records) == 2
    aws_record = next(r for r in records if r.system == "AWS Console")
    assert aws_record.access_level == "admin"
    assert aws_record.granted_date == "2024-01-15"


def test_import_from_json_still_works():
    import json
    data = json.dumps([
        {"id": "u1", "name": "Jane Doe", "email": "jane@company.com", "department": "Finance",
         "role": "Analyst", "status": "active", "termination_date": None}
    ]).encode("utf-8")
    employees = import_employees("export.json", data)
    assert len(employees) == 1
    assert employees[0].name == "Jane Doe"


def test_preview_mapping_reports_detected_columns():
    csv_content = "Full Name,Work Email,Team,Job Title,Status\nJane,jane@co.com,Finance,Analyst,Active\n".encode("utf-8")
    preview = preview_mapping("export.csv", csv_content, "employees")
    assert preview["mapping"]["email"] == "Work Email"
    assert preview["mapping"]["name"] == "Full Name"
    assert preview["missing_required"] == []
    assert preview["row_count"] == 1


def test_preview_mapping_flags_missing_required_fields():
    csv_content = "Full Name,Team\nJane,Finance\n".encode("utf-8")
    preview = preview_mapping("export.csv", csv_content, "employees")
    assert "email" in preview["missing_required"]


def test_normalize_date_handles_multiple_formats():
    assert _normalize_date("2026-04-15") == "2026-04-15"
    assert _normalize_date("04/15/2026") == "2026-04-15"
    assert _normalize_date("15-Apr-2026") == "2026-04-15"
    assert _normalize_date(None) is None
    assert _normalize_date("") is None


def test_import_skips_incomplete_rows_instead_of_failing():
    csv_content = (
        "Full Name,Work Email,Status\n"
        "Jane Doe,jane@company.com,Active\n"
        ",missing-name@company.com,Active\n"   # missing name — should be skipped
        "No Email Person,,Active\n"              # missing email — should be skipped
    ).encode("utf-8")
    employees = import_employees("export.csv", csv_content)
    assert len(employees) == 1
    assert employees[0].email == "jane@company.com"


def test_unsupported_file_type_raises_clear_error():
    from accessaudit.importer import _read_rows
    with pytest.raises(ValueError) as exc_info:
        _read_rows("export.txt", b"some content")
    assert "Unsupported file type" in str(exc_info.value)


def test_import_employees_from_xlsx():
    import io
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Full Name", "Work Email", "Team", "Status"])
    ws.append(["Jane Doe", "jane@company.com", "Finance", "Active"])
    ws.append(["Bob Smith", "bob@company.com", "Engineering", "Terminated"])
    buf = io.BytesIO()
    wb.save(buf)

    employees = import_employees("export.xlsx", buf.getvalue())
    assert len(employees) == 2
    bob = next(e for e in employees if e.name == "Bob Smith")
    assert bob.status == "terminated"
