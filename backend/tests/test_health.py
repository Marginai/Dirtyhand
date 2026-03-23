import os

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "sk-test-placeholder"))
    monkeypatch.setenv("ENVIRONMENT", "development")
    # Fresh settings cache after env change
    from app.settings import clear_settings_cache

    clear_settings_cache()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
    clear_settings_cache()


def test_health(client: TestClient):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_openapi_when_dev(client: TestClient):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "paths" in r.json()
