"""Pre-deployment hardening tests: auth, rate limit, upload cap, error safety."""
import io
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("accessaudit.storage.DB_PATH", tmp_path / "test.db")
    monkeypatch.setenv("ACCESSAUDIT_RATE", "100000")
    monkeypatch.setenv("ACCESSAUDIT_RATE_STRICT", "100000")
    from webapp import security
    security.reset_rate_limits()
    from webapp import main as webapp_main
    webapp_main._staged["employees"] = None
    webapp_main._staged["access"] = None
    return TestClient(webapp_main.app)


def test_token_required_when_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("accessaudit.storage.DB_PATH", tmp_path / "t.db")
    monkeypatch.setenv("ACCESSAUDIT_TOKEN", "s3cret")
    from webapp import security
    security.reset_rate_limits()
    from webapp import main as webapp_main
    c = TestClient(webapp_main.app)
    assert c.post("/api/clear").status_code == 401
    assert c.post("/api/clear", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert c.post("/api/clear", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    # reads stay open
    assert c.get("/api/findings").status_code == 200


def test_healthz_ok(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_upload_too_large_rejected(client, monkeypatch):
    monkeypatch.setenv("ACCESSAUDIT_MAX_UPLOAD", "10")  # read dynamically per call
    big = io.BytesIO(b"x" * 5000)
    r = client.post("/api/upload/employees", files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413


def test_rate_limit_kicks_in(tmp_path, monkeypatch):
    monkeypatch.setattr("accessaudit.storage.DB_PATH", tmp_path / "t.db")
    monkeypatch.setenv("ACCESSAUDIT_RATE_STRICT", "3")
    from webapp import security
    security.reset_rate_limits()
    from webapp import main as webapp_main
    c = TestClient(webapp_main.app)
    codes = [c.post("/api/use-sample-data").status_code for _ in range(6)]
    assert 429 in codes


def test_invalid_kind_rejected(client):
    r = client.post("/api/upload/bogus", files={"file": ("x.csv", io.BytesIO(b"a,b"), "text/csv")})
    assert r.status_code == 400
