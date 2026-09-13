"""
Integration tests for ShellGuard FastAPI Daemon Endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from daemon.server import app, engine


@pytest.fixture(scope="module")
def client():
    # Ensure engine is initialized
    if not engine.is_initialized:
        engine.initialize()
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["indexed_chunks"] >= 25


def test_check_endpoint_blocked(client):
    payload = {
        "command": "kubectl delete namespace ingress-nginx",
        "shell": "zsh"
    }
    res = client.post("/api/check", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "BLOCKED"
    assert data["matched_incident_id"] == "INC-402"
    assert data["latency_ms"] < 20.0
    assert "total_api_latency_ms" in data


def test_check_endpoint_passed(client):
    payload = {
        "command": "ls -la /var/log",
        "shell": "bash"
    }
    res = client.post("/api/check", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PASSED"
    assert data["is_intercepted"] is False


def test_incidents_list(client):
    res = client.get("/api/incidents")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 6
    ids = [i["id"] for i in data]
    assert "INC-402" in ids
    assert "INC-105" in ids


def test_stats_endpoint(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_checks" in data
    assert "p50_latency_ms" in data


def test_benchmark_endpoint(client):
    res = client.post("/api/benchmark", json={"sample_size": 5})
    assert res.status_code == 200
    data = res.json()
    assert data["sample_size"] == 5
    assert "speedup_factor" in data
    assert data["moss_avg_latency_ms"] < 15.0
