"""
Unit and Integration Tests for ShellGuard Local Security Hardening,
OWASP Input Validation, Rate Limiting, LiveKit WebRTC Bridge, and CRISPE Prompt Classifier.
"""

import os
import sys
import time
import json
import base64
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from daemon.security import (
    SecurityManager,
    SlidingWindowRateLimiter,
    validate_command_payload,
    OSCredentialStore,
)
from daemon.livekit_bridge import LiveKitBridge, livekit_bridge
from daemon.classifier_prompt import build_crispe_prompt, CRISPE_FEW_SHOT_EXAMPLES
from daemon.server import app, engine


@pytest.fixture(scope="module")
def initialized_engine():
    if not engine.is_initialized:
        engine.initialize()
    return engine


class TestInputValidation:
    def test_valid_command_passes(self):
        cmd = "kubectl get pods -n kube-system"
        assert validate_command_payload(cmd) == cmd

    def test_null_byte_rejection(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            validate_command_payload("rm -rf / \x00 malicious_suffix")
        assert exc_info.value.status_code == 400
        assert "Null bytes" in exc_info.value.detail

    def test_oversized_payload_rejection(self):
        from fastapi import HTTPException
        huge_cmd = "echo " + ("A" * 5000)
        with pytest.raises(HTTPException) as exc_info:
            validate_command_payload(huge_cmd)
        assert exc_info.value.status_code == 413
        assert "exceeds maximum allowable length" in exc_info.value.detail


class TestSecurityManagerAndAuth:
    def test_token_generation_and_constant_time_verification(self, tmp_path):
        token_path = tmp_path / ".shellguard" / "test_token"
        sm = SecurityManager(token_path=token_path)
        token = sm.token
        assert len(token) >= 32
        assert token_path.exists()
        assert sm.verify_token(token) is True
        assert sm.verify_token("invalid-candidate-token") is False
        assert sm.verify_token("") is False
        assert sm.verify_token(None) is False

    def test_daemon_auth_enforcement_and_bypass(self, tmp_path, initialized_engine):
        token_path = tmp_path / "token"
        sm = SecurityManager(token_path=token_path)
        test_token = sm.token

        try:
            # Explicitly enable auth
            os.environ["SHELLGUARD_DISABLE_AUTH"] = "0"
            os.environ["SHELLGUARD_TOKEN"] = test_token

            with TestClient(app) as client:
                # 1. Missing token -> 401 Unauthorized
                res = client.post(
                    "/api/check",
                    json={"command": "kubectl get pods", "shell": "zsh"},
                    headers={},
                )
                assert res.status_code == 401
                assert "Unauthorized" in res.json()["detail"]

                # 2. Invalid token -> 401 Unauthorized
                res = client.post(
                    "/api/check",
                    json={"command": "kubectl get pods", "shell": "zsh"},
                    headers={"X-ShellGuard-Token": "bad-token-12345"},
                )
                assert res.status_code == 401

                # 3. Valid X-ShellGuard-Token -> 200 OK
                res = client.post(
                    "/api/check",
                    json={"command": "kubectl get pods", "shell": "zsh"},
                    headers={"X-ShellGuard-Token": test_token},
                )
                assert res.status_code == 200
                assert res.json()["status"] == "PASSED"

                # 4. Valid Authorization Bearer -> 200 OK
                res = client.post(
                    "/api/check",
                    json={"command": "kubectl get pods", "shell": "zsh"},
                    headers={"Authorization": f"Bearer {test_token}"},
                )
                assert res.status_code == 200
        finally:
            # Always reset for subsequent test suites
            os.environ["SHELLGUARD_DISABLE_AUTH"] = "1"
            os.environ.pop("SHELLGUARD_TOKEN", None)


class TestSlidingWindowRateLimiter:
    def test_rate_limiter_permits_and_throttles(self):
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=2)
        client_id = "test-client-127.0.0.1"

        # First 5 requests allowed
        for i in range(5):
            allowed, remaining, _ = limiter.is_allowed(client_id)
            assert allowed is True
            assert remaining == 4 - i

        # 6th request blocked
        allowed, remaining, retry_after = limiter.is_allowed(client_id)
        assert allowed is False
        assert remaining == 0
        assert retry_after > 0


class TestLiveKitBridge:
    def test_livekit_jwt_token_generation_and_claims(self):
        bridge = LiveKitBridge(
            url="wss://livekit.test.domain:7880",
            api_key="test-api-key",
            api_secret="test-secret-32-character-minimum-len",
        )
        token = bridge.create_room_token(
            room_name="shellguard-warroom-inc-402",
            participant_identity="sre-operator-1",
            participant_name="Senior SRE",
        )
        parts = token.split(".")
        assert len(parts) == 3, "JWT must contain 3 dot-separated segments"

        # Decode header and payload
        def b64_decode(seg: str) -> dict:
            padded = seg + "=" * ((4 - len(seg) % 4) % 4)
            return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))

        header = b64_decode(parts[0])
        payload = b64_decode(parts[1])

        assert header["alg"] == "HS256"
        assert header["typ"] == "JWT"
        assert payload["iss"] == "test-api-key"
        assert payload["sub"] == "sre-operator-1"
        assert payload["name"] == "Senior SRE"
        assert payload["video"]["room"] == "shellguard-warroom-inc-402"
        assert payload["video"]["roomJoin"] is True
        assert payload["video"]["canPublish"] is True
        assert payload["video"]["canSubscribe"] is True

    def test_incident_audio_alert_dispatch(self):
        bridge = LiveKitBridge()
        alert = bridge.dispatch_incident_audio_alert(
            incident_id="INC-402",
            title="Kubernetes Ingress Deletion",
            command="kubectl delete namespace ingress-nginx",
            severity="P0",
        )
        assert alert["status"] == "alert_dispatched"
        assert alert["incident_id"] == "INC-402"
        assert alert["severity"] == "P0"
        assert alert["audio_frequency_hz"] == 880
        assert "shellguard-warroom-inc-402" in alert["room_name"]
        assert len(alert["token"].split(".")) == 3

    def test_daemon_livekit_token_endpoint(self, initialized_engine):
        with TestClient(app) as client:
            res = client.post(
                "/api/livekit/token",
                json={"room_name": "incident-ops-warroom", "participant_identity": "sre-alice"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["room_name"] == "incident-ops-warroom"
            assert data["participant_identity"] == "sre-alice"
            assert "token" in data
            assert len(data["token"].split(".")) == 3

    def test_daemon_check_dispatches_livekit_alert_on_block(self, initialized_engine):
        with TestClient(app) as client:
            res = client.post(
                "/api/check",
                json={"command": "kubectl delete namespace ingress-nginx", "shell": "zsh"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "BLOCKED"
            assert "livekit_alert" in data
            assert data["livekit_alert"]["incident_id"] == "INC-402"
            assert "token" in data["livekit_alert"]


class TestCrispePromptClassifier:
    def test_crispe_prompt_generation_structure(self):
        prompt_data = build_crispe_prompt(
            command="terraform destroy -target=aws_db_instance.primary",
            cwd="/app/infra",
            shell_type="bash",
            context_badge="[ENV: prod-us-east-1 (aws)]",
            retrieved_incidents=[
                {
                    "id": "INC-105",
                    "title": "Terraform Destroy Primary RDS Outage",
                    "trigger_command": "terraform destroy",
                    "severity": "P0",
                    "blast_radius": "Production PostgreSQL RDS database.",
                    "safe_alternative_cmd": "terraform plan -target=aws_db_instance.primary",
                }
            ],
        )

        assert prompt_data["framework"] == "CRISPE"
        assert "Principal Site Reliability Engineer" in prompt_data["system_role"]
        assert "CAPACITY & ROLE" in prompt_data["instructions"]
        assert "terraform destroy" in prompt_data["candidate_command"]
        assert len(prompt_data["few_shot_examples"]) == len(CRISPE_FEW_SHOT_EXAMPLES)
        assert "INC-042" in prompt_data["formatted_prompt"]
        assert "INC-105" in prompt_data["formatted_prompt"]

    def test_daemon_crispe_prompt_endpoint(self, initialized_engine):
        with TestClient(app) as client:
            res = client.post(
                "/api/classify/prompt",
                json={"command": "aws s3 rm s3://prod-backups --recursive", "cwd": "/home/user"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["framework"] == "CRISPE"
            assert "aws s3 rm" in data["candidate_command"]
            assert "formatted_prompt" in data


class TestOpenTelemetryObservability:
    def test_opentelemetry_traces_endpoint(self, initialized_engine):
        with TestClient(app) as client:
            # Generate a check
            check_res = client.post(
                "/api/check",
                json={"command": "kubectl get nodes", "shell": "zsh"},
            )
            assert check_res.status_code == 200
            check_data = check_res.json()
            assert "trace_id" in check_data

            # Query traces
            trace_res = client.get("/api/telemetry/traces")
            assert trace_res.status_code == 200
            trace_data = trace_res.json()
            assert "resourceSpans" in trace_data
            resource_spans = trace_data["resourceSpans"]
            assert len(resource_spans) > 0
            spans = resource_spans[0]["scopeSpans"][0]["spans"]
            assert len(spans) > 0
            latest = spans[0]
            assert latest["name"] == "shellguard.evaluate"
            assert "traceId" in latest
            assert "spanId" in latest
            attrs = {a["key"]: a["value"] for a in latest["attributes"]}
            assert "command.raw" in attrs
            assert "moss.latency_ms" in attrs


class TestOSCredentialStoreAnd12Factor:
    def test_os_credential_store_dpapi_and_keyring(self, tmp_path):
        """Verify OS-level credential store preserves token and shreds legacy plaintext files."""
        token_dir = tmp_path / ".shellguard"
        test_token = "abc123def4567890abcdef1234567890"

        # 1. Store token
        stored = OSCredentialStore.store_token(test_token, target_dir=token_dir)
        assert stored is True

        # 2. Retrieve token
        retrieved = OSCredentialStore.retrieve_token(target_dir=token_dir)
        assert retrieved == test_token

        # 3. Verify plaintext ~/.shellguard/token does NOT exist
        plain_file = token_dir / "token"
        assert not plain_file.exists()

        # 4. Verify DPAPI file exists on Windows
        if sys.platform == "win32":
            dpapi_file = token_dir / "token.dpapi"
            assert dpapi_file.exists()
            assert dpapi_file.stat().st_size > 0

    def test_legacy_plaintext_migration(self, tmp_path):
        """Verify legacy plaintext token files are automatically migrated and shredded."""
        token_dir = tmp_path / ".shellguard"
        token_dir.mkdir(parents=True, exist_ok=True)
        plain_file = token_dir / "token"
        legacy_token = "legacy_token_to_migrate_9876543210"
        plain_file.write_text(legacy_token, encoding="utf-8")

        # Retrieving migrates it
        retrieved = OSCredentialStore.retrieve_token(target_dir=token_dir)
        assert retrieved == legacy_token
        assert not plain_file.exists()

    def test_pydantic_settings_loading(self, monkeypatch):
        """Verify 12-Factor App Factor III: environment-injected configuration."""
        monkeypatch.setenv("SHELLGUARD_DECISION_THRESHOLD", "0.88")
        monkeypatch.setenv("SHELLGUARD_FAIL_POLICY", "fail_closed")
        monkeypatch.setenv("SHELLGUARD_PORT", "9999")

        from daemon.config import ShellGuardSettings
        test_settings = ShellGuardSettings()
        assert test_settings.decision_threshold == 0.88
        assert test_settings.fail_policy == "fail_closed"
        assert test_settings.port == 9999

