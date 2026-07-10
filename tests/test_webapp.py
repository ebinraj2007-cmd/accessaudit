import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh app instance per test, pointed at a temp DB so tests don't
    interfere with each other or with real usage data."""
    monkeypatch.setattr("accessaudit.storage.DB_PATH", tmp_path / "test.db")
    from webapp import main as webapp_main
    webapp_main._staged["employees"] = None
    webapp_main._staged["access"] = None
    return TestClient(webapp_main.app)


def test_homepage_loads(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "AccessAudit" in res.text


def test_setup_status_initially_no_data(client):
    res = client.get("/api/setup-status")
    assert res.status_code == 200
    assert res.json()["has_data"] is False


def test_sample_data_flow(client):
    res = client.post("/api/use-sample-data")
    assert res.status_code == 200
    assert res.json()["findings_count"] == 9

    findings = client.get("/api/findings").json()
    assert len(findings) == 9


def test_upload_wizard_two_step_flow(client):
    employees_csv = (
        "Full Name,Work Email,Team,Status\n"
        "Jane Doe,jane@company.com,Finance,Terminated\n"
    )
    access_csv = (
        "User Email,Application,Permission\n"
        "jane@company.com,Payroll System,admin\n"
    )

    res1 = client.post(
        "/api/upload/employees",
        files={"file": ("hr.csv", io.BytesIO(employees_csv.encode()), "text/csv")},
    )
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["employees_staged"] is True
    assert body1["ready_to_check"] is False

    res2 = client.post(
        "/api/upload/access",
        files={"file": ("access.csv", io.BytesIO(access_csv.encode()), "text/csv")},
    )
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["ready_to_check"] is True
    assert body2["checked"] is True
    assert body2["findings_count"] == 1

    findings = client.get("/api/findings").json()
    assert findings[0]["employee_name"] == "Jane Doe"
    assert findings[0]["issue_type"] == "orphaned_access"


def test_upload_bad_file_returns_clear_error(client):
    bad_csv = "Random,Columns\nfoo,bar\n"
    res = client.post(
        "/api/upload/employees",
        files={"file": ("bad.csv", io.BytesIO(bad_csv.encode()), "text/csv")},
    )
    assert res.status_code == 400
    assert "email" in res.json()["error"].lower()


def test_revoke_action_updates_status_and_logs(client):
    client.post("/api/use-sample-data")
    findings = client.get("/api/findings").json()
    finding_id = findings[0]["id"]

    res = client.post(f"/api/findings/{finding_id}/revoke")
    assert res.status_code == 200
    assert res.json()["result"] == "revoked_in_accessaudit_records"

    log = client.get("/api/action-log").json()
    assert len(log) == 1
    assert log[0]["action"] == "revoke_access"


def test_clear_resets_everything_including_staged_uploads(client):
    client.post("/api/use-sample-data")
    assert client.get("/api/setup-status").json()["has_data"] is True

    client.post("/api/clear")
    status = client.get("/api/setup-status").json()
    assert status["has_data"] is False
    assert status["employees_staged"] is False
