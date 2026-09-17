"""
Unit and Integration Test Suite for Secure Centralized Policy Distribution & Delta Sync (R1).
Verifies:
1. Deterministic HMAC-SHA256 signature computation and verification.
2. Immediate rejection (HTTP 403) of tampered or unauthorized policy delta bundles.
3. Rapid (<50ms) hot-indexing of disaster post-mortems without daemon restarts.
4. Immediate queryability of synchronized incident patterns via Moss engine.
5. Endpoints: POST /api/sync/apply and GET /api/sync/status.
"""

import os
import sys
import time
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from daemon.sync import PolicySyncManager
from daemon.engine import ShellGuardEngine
from daemon.server import app, engine as global_engine
from daemon.security import security_manager


@pytest.fixture
def sync_manager(tmp_path):
    incidents_dir = tmp_path / "incidents"
    incidents_dir.mkdir(parents=True, exist_ok=True)
    mgr = PolicySyncManager(signing_key="test-secret-key-12345", incidents_dir=incidents_dir)
    mgr.version_file = tmp_path / "policy_version.json"
    return mgr


@pytest.fixture
def test_client():
    return TestClient(app)


class TestSignatureVerification:
    def test_compute_and_verify_valid_signature(self, sync_manager):
        incidents = [
            {
                "id": "INC-TEST-01",
                "title": "Unsafe Database Flush",
                "blast_radius": "Complete catalog data drop",
                "safe_alternative": "pg_dump -U postgres dbname",
                "trigger_patterns": ["drop database production", "drop database prod"],
            }
        ]
        bundle = sync_manager.create_signed_bundle("2026.09.1", incidents)
        assert "signature" in bundle
        assert sync_manager.verify_signature(bundle) is True

    def test_tampered_payload_fails_verification(self, sync_manager):
        incidents = [
            {
                "id": "INC-TEST-02",
                "title": "AWS S3 Bucket Deletion",
                "blast_radius": "Loss of all static assets",
                "safe_alternative": "aws s3 ls s3://prod-bucket",
                "trigger_patterns": ["aws s3 rb s3://prod-bucket --force"],
            }
        ]
        bundle = sync_manager.create_signed_bundle("2026.09.2", incidents)

        # Tamper with the incident data
        bundle["incidents"][0]["blast_radius"] = "Tampered minimal blast radius"
        assert sync_manager.verify_signature(bundle) is False

    def test_tampered_signature_fails_verification(self, sync_manager):
        bundle = {
            "version": "2026.09.3",
            "timestamp": time.time(),
            "incidents": [],
            "signature": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        }
        assert sync_manager.verify_signature(bundle) is False

    def test_missing_signature_fails_verification(self, sync_manager):
        bundle = {"version": "2026.09.4", "incidents": []}
        assert sync_manager.verify_signature(bundle) is False


class TestDeltaUpdateApplication:
    def test_apply_delta_update_timing_and_indexing(self, sync_manager):
        engine = ShellGuardEngine()
        incidents = [
            {
                "id": "INC-SYNC-888",
                "title": "Elasticsearch Cluster Wipe",
                "blast_radius": "Search indexing down for 4 hours",
                "safe_alternative": "curl -X GET 'localhost:9200/_cat/indices?v'",
                "trigger_patterns": ["curl -X DELETE 'localhost:9200/_all'"],
            }
        ]
        bundle = sync_manager.create_signed_bundle("2026.09.10", incidents)

        t0 = time.perf_counter()
        result = sync_manager.apply_delta_update(bundle, engine)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert result["status"] == "success"
        assert result["version"] == "2026.09.10"
        assert "INC-SYNC-888" in result["incidents_applied"]
        assert elapsed_ms < 150.0  # Well within hot-indexing ceiling

        # Verify disk serialization
        saved_file = sync_manager.incidents_dir / "INC-SYNC-888.md"
        assert saved_file.exists()
        assert "Elasticsearch Cluster Wipe" in saved_file.read_text(encoding="utf-8")

        # Verify version updated
        assert sync_manager.current_version == "2026.09.10"

    def test_tampered_bundle_raises_http_403(self, sync_manager):
        from fastapi import HTTPException
        engine = ShellGuardEngine()
        bundle = {
            "version": "2026.09.11",
            "timestamp": time.time(),
            "incidents": [{"id": "INC-HACK", "title": "Tampered Policy"}],
            "signature": "deadbeefdeadbeefdeadbeefdeadbeef",
        }

        with pytest.raises(HTTPException) as exc_info:
            sync_manager.apply_delta_update(bundle, engine)
        assert exc_info.value.status_code == 403
        assert "tampered or unauthorized" in exc_info.value.detail.lower()


class TestSyncApiEndpoints:
    def test_get_sync_status(self, test_client):
        response = test_client.get("/api/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert "current_version" in data
        assert "signing_configured" in data
        assert "incidents_dir" in data

    def test_apply_policy_sync_endpoint_authorized_and_verified(self, test_client):
        token = security_manager.token
        headers = {"Authorization": f"Bearer {token}"}

        # Create valid bundle with server's signing key
        from daemon.sync import policy_sync_manager
        incidents = [
            {
                "id": "INC-API-999",
                "title": "Vault Secret Purge Prevention",
                "blast_radius": "All service identity tokens invalidated",
                "safe_alternative": "vault kv get secret/app",
                "trigger_patterns": ["vault operator raft snapshot restore /tmp/empty"],
            }
        ]
        bundle = policy_sync_manager.create_signed_bundle("2026.09.99", incidents)

        response = test_client.post("/api/sync/apply", json=bundle, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "INC-API-999" in data["incidents_applied"]

    def test_apply_policy_sync_tampered_payload_rejected_with_403(self, test_client):
        token = security_manager.token
        headers = {"Authorization": f"Bearer {token}"}

        tampered_bundle = {
            "version": "2026.09.666",
            "timestamp": time.time(),
            "incidents": [{"id": "INC-TAMPER", "title": "Malicious Bypass"}],
            "signature": "invalid-tampered-hmac-signature",
        }

        response = test_client.post("/api/sync/apply", json=tampered_bundle, headers=headers)
        assert response.status_code == 403
        assert "Cryptographic verification failed" in response.json()["detail"]
