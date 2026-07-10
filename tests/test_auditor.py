import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date
from unittest.mock import patch, MagicMock

from accessaudit.models import Employee, AccessRecord
from accessaudit.auditor import run_audit, _rule_based_finding

TODAY = date(2026, 7, 10)


def make_employee(**overrides):
    base = dict(id="u1", name="Test User", email="test@company.com",
                department="Sales", role="Rep", status="active", termination_date=None)
    base.update(overrides)
    return Employee(**base)


def make_record(**overrides):
    base = dict(id="a1", user_email="test@company.com", system="CRM",
                access_level="standard", granted_date="2024-01-01", last_used_date="2026-07-01")
    base.update(overrides)
    return AccessRecord(**base)


def test_terminated_employee_with_access_is_critical():
    emp = make_employee(status="terminated", termination_date="2026-06-01")
    rec = make_record(access_level="admin", system="Payroll System")
    finding = _rule_based_finding(emp, rec, TODAY)
    assert finding is not None
    assert finding.issue_type == "orphaned_access"
    assert finding.severity == 5


def test_terminated_employee_standard_access_is_high_not_critical():
    emp = make_employee(status="terminated", termination_date="2026-06-01")
    rec = make_record(access_level="standard")
    finding = _rule_based_finding(emp, rec, TODAY)
    assert finding.severity == 4


def test_active_employee_clean_access_no_finding():
    emp = make_employee(status="active")
    rec = make_record(last_used_date="2026-07-09")  # used yesterday
    finding = _rule_based_finding(emp, rec, TODAY)
    assert finding is None


def test_dormant_access_detected():
    emp = make_employee(status="active")
    rec = make_record(last_used_date="2026-01-01")  # >90 days before TODAY
    finding = _rule_based_finding(emp, rec, TODAY)
    assert finding is not None
    assert finding.issue_type == "dormant_access"


def test_never_used_access_is_dormant():
    emp = make_employee(status="active")
    rec = make_record(last_used_date=None)
    finding = _rule_based_finding(emp, rec, TODAY)
    assert finding is not None
    assert finding.issue_type == "dormant_access"


def test_excessive_privilege_flagged_for_wrong_department():
    emp = make_employee(status="active", department="Sales")
    rec = make_record(access_level="admin", system="AWS Console", last_used_date="2026-07-09")
    finding = _rule_based_finding(emp, rec, TODAY)
    assert finding is not None
    assert finding.issue_type == "excessive_privilege"


def test_excessive_privilege_not_flagged_for_it_department():
    emp = make_employee(status="active", department="IT")
    rec = make_record(access_level="admin", system="AWS Console", last_used_date="2026-07-09")
    finding = _rule_based_finding(emp, rec, TODAY)
    assert finding is None


def test_run_audit_skips_access_records_for_unknown_users():
    employees = [make_employee(email="known@company.com")]
    records = [make_record(user_email="unknown@company.com")]
    findings = run_audit(employees, records, today=TODAY)
    assert findings == []


def test_run_audit_sorts_by_severity_descending():
    employees = [
        make_employee(email="a@company.com", status="terminated", termination_date="2026-06-01"),
        make_employee(email="b@company.com", status="active"),
    ]
    records = [
        make_record(user_email="a@company.com", access_level="admin"),  # severity 5
        make_record(user_email="b@company.com", last_used_date=None),   # severity 2 (dormant)
    ]
    findings = run_audit(employees, records, today=TODAY)
    severities = [f.severity for f in findings]
    assert severities == sorted(severities, reverse=True)


def test_llm_reasoning_used_when_key_present_and_succeeds():
    emp = make_employee(status="terminated", termination_date="2026-06-01")
    rec = make_record(access_level="admin")

    fake_response = MagicMock()
    fake_block = MagicMock()
    fake_block.type = "text"
    fake_block.text = "Fatima's admin payroll access poses a financial fraud risk if left active."
    fake_response.content = [fake_block]

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
        with patch("anthropic.Anthropic") as mock_client_cls:
            mock_client_cls.return_value.messages.create.return_value = fake_response
            findings = run_audit([emp], [rec], today=TODAY)

    assert findings[0].engine == "llm"
    assert "fraud" in findings[0].reasoning


def test_llm_failure_falls_back_to_rule_reasoning():
    emp = make_employee(status="terminated", termination_date="2026-06-01")
    rec = make_record(access_level="admin")

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
        with patch("anthropic.Anthropic") as mock_client_cls:
            mock_client_cls.return_value.messages.create.side_effect = Exception("network error")
            findings = run_audit([emp], [rec], today=TODAY)

    assert findings[0].engine == "rules"
    assert findings[0].severity == 5  # decision never depends on the LLM call
