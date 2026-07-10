import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import pytest

from accessaudit import storage
from accessaudit.pipeline import run_check
from accessaudit.remediation import LocalConnector, OktaConnector

SAMPLE_EMPLOYEES = Path(__file__).resolve().parent.parent / "sample_data" / "employees.json"
SAMPLE_ACCESS = Path(__file__).resolve().parent.parent / "sample_data" / "access_records.json"


def test_pipeline_produces_expected_finding_count():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        findings = run_check(SAMPLE_EMPLOYEES, SAMPLE_ACCESS, db_path)
        assert len(findings) == 9

        conn = storage.get_connection(db_path)
        rows = storage.get_all_findings(conn)
        assert len(rows) == 9


def test_pipeline_is_idempotent_on_rerun():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        run_check(SAMPLE_EMPLOYEES, SAMPLE_ACCESS, db_path)
        run_check(SAMPLE_EMPLOYEES, SAMPLE_ACCESS, db_path)

        conn = storage.get_connection(db_path)
        rows = storage.get_all_findings(conn)
        assert len(rows) == 9


def test_critical_orphaned_access_present():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        findings = run_check(SAMPLE_EMPLOYEES, SAMPLE_ACCESS, db_path)
        critical = [f for f in findings if f["severity"] == 5]
        assert any(f["employee_name"] == "Fatima Al-Sayed" for f in critical)
        assert any(f["employee_name"] == "Grace Wong" for f in critical)


def test_local_connector_revoke_returns_real_result():
    connector = LocalConnector()
    result = connector.revoke_access("test@company.com", "Payroll System")
    assert result["action"] == "revoke_access"
    assert result["result"] == "revoked_in_accessaudit_records"
    assert "timestamp" in result


def test_local_connector_reset_returns_real_result():
    connector = LocalConnector()
    result = connector.reset_password("test@company.com", "VPN")
    assert result["action"] == "reset_password"
    assert "timestamp" in result


def test_okta_connector_raises_without_credentials():
    connector = OktaConnector()
    with pytest.raises(NotImplementedError):
        connector.revoke_access("test@company.com", "Payroll System")


def test_action_log_records_remediation():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        run_check(SAMPLE_EMPLOYEES, SAMPLE_ACCESS, db_path)

        conn = storage.get_connection(db_path)
        connector = LocalConnector()
        result = connector.revoke_access("fatima.alsayed@company.com", "Payroll System")
        storage.log_action(conn, "f_a001", result)
        storage.update_finding_status(conn, "f_a001", "revoked")

        log = storage.get_action_log(conn)
        assert len(log) == 1
        assert log[0]["user_email"] == "fatima.alsayed@company.com"

        finding = storage.get_finding(conn, "f_a001")
        assert finding["status"] == "revoked"


def test_stats_reflect_only_open_findings():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        run_check(SAMPLE_EMPLOYEES, SAMPLE_ACCESS, db_path)

        conn = storage.get_connection(db_path)
        storage.update_finding_status(conn, "f_a001", "revoked")

        stats = storage.get_stats(conn)
        assert stats["open_total"] == 8
