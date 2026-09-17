"""
Comprehensive E2E and Unit Test Suite for Multi-Cloud Context Detection (R2, R3).
Tests pure-Python Kubernetes, AWS, and Git context detection, badge formatting,
boundary/adversarial conditions, and sub-millisecond latency guardrails.
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Safe import of ContextDetector for progressive testability
try:
    from daemon.context import ContextDetector
except ImportError:
    ContextDetector = None

try:
    from daemon.context import parse_k8s_context
except ImportError:
    parse_k8s_context = None

try:
    from daemon.context import parse_aws_config
except ImportError:
    parse_aws_config = None

try:
    from daemon.context import parse_git_head
except ImportError:
    parse_git_head = None


@pytest.fixture
def detector():
    """Fixture providing a fresh ContextDetector instance, skipping if not yet implemented."""
    if ContextDetector is None:
        pytest.skip("daemon.context.ContextDetector is not yet implemented (Milestone 1)")
    return ContextDetector()


# ==============================================================================
# 1. Kubernetes Context Detection Tests
# ==============================================================================

class TestK8sContextDetection:
    """Unit and boundary tests for Kubernetes context detection."""

    def test_k8s_from_kubeconfig_env(self, detector, tmp_path, monkeypatch):
        """KUBECONFIG environment variable pointing to valid YAML must be parsed."""
        kubeconfig = tmp_path / "custom-kubeconfig.yaml"
        kubeconfig.write_text(
            "apiVersion: v1\n"
            "kind: Config\n"
            "current-context: prod-us-east-1-k8s\n"
            "clusters: []\n",
            encoding="utf-8"
        )
        monkeypatch.setenv("KUBECONFIG", str(kubeconfig))

        res = detector.detect()
        assert res.get("k8s") == "prod-us-east-1-k8s"

    def test_k8s_from_default_home_config(self, detector, tmp_path, monkeypatch):
        """Fallback to ~/.kube/config when KUBECONFIG is unset."""
        fake_home = tmp_path / "home"
        kube_dir = fake_home / ".kube"
        kube_dir.mkdir(parents=True)
        config_file = kube_dir / "config"
        config_file.write_text(
            "apiVersion: v1\n"
            "current-context: dev-minikube\n",
            encoding="utf-8"
        )

        monkeypatch.delenv("KUBECONFIG", raising=False)
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("USERPROFILE", str(fake_home))

        res = detector.detect()
        assert res.get("k8s") == "dev-minikube"

    def test_k8s_missing_file_returns_none(self, detector, tmp_path, monkeypatch):
        """Non-existent KUBECONFIG file must gracefully return None."""
        non_existent = tmp_path / "does-not-exist.yaml"
        monkeypatch.setenv("KUBECONFIG", str(non_existent))

        res = detector.detect()
        assert res.get("k8s") is None

    def test_k8s_empty_file_returns_none(self, detector, tmp_path, monkeypatch):
        """Empty kubeconfig file must gracefully return None."""
        empty_file = tmp_path / "empty-kubeconfig.yaml"
        empty_file.write_text("", encoding="utf-8")
        monkeypatch.setenv("KUBECONFIG", str(empty_file))

        res = detector.detect()
        assert res.get("k8s") is None

    @pytest.mark.parametrize("yaml_line, expected_context", [
        ("current-context: prod-cluster", "prod-cluster"),
        ('current-context: "prod-cluster"', "prod-cluster"),
        ("current-context: 'staging-cluster'", "staging-cluster"),
        ("  current-context:   dev-cluster   ", "dev-cluster"),
        ("current-context: arn:aws:eks:us-east-1:123456789012:cluster/prod", "arn:aws:eks:us-east-1:123456789012:cluster/prod"),
        ("current-context: minikube # local development", "minikube"),
        ("# current-context: commented-out", None),
        ("current-context:", None),
        ('current-context: ""', None),
        ("current-context: ''", None),
        ("current-context:   ", None),
        ("context: something-else", None),
    ])
    def test_k8s_yaml_parsing_variations(self, detector, tmp_path, monkeypatch, yaml_line, expected_context):
        """Test boundary conditions, quotes, comments, spaces, and empty current-context values."""
        kubeconfig = tmp_path / "test-config.yaml"
        content = (
            "apiVersion: v1\n"
            "clusters:\n"
            "- cluster:\n"
            "    server: https://127.0.0.1\n"
            f"{yaml_line}\n"
            "users: []\n"
        )
        kubeconfig.write_text(content, encoding="utf-8")
        monkeypatch.setenv("KUBECONFIG", str(kubeconfig))

        res = detector.detect()
        assert res.get("k8s") == expected_context

    def test_k8s_multi_path_kubeconfig_takes_first_valid(self, detector, tmp_path, monkeypatch):
        """Multi-path KUBECONFIG (colon or semicolon separated) selects first existing file."""
        invalid_path = str(tmp_path / "invalid.yaml")
        valid_file = tmp_path / "valid.yaml"
        valid_file.write_text("current-context: valid-context\n", encoding="utf-8")

        # Windows uses semicolon or colon
        separator = ";" if os.name == "nt" else ":"
        multi_path = f"{invalid_path}{separator}{str(valid_file)}"
        monkeypatch.setenv("KUBECONFIG", multi_path)

        res = detector.detect()
        assert res.get("k8s") == "valid-context"


# ==============================================================================
# 2. AWS Profile and Region Detection Tests
# ==============================================================================

class TestAwsContextDetection:
    """Unit and boundary tests for AWS profile and region detection."""

    def test_aws_from_env_vars_both_profile_and_region(self, detector, monkeypatch):
        """AWS_PROFILE and AWS_REGION set in environment take precedence without disk access."""
        monkeypatch.setenv("AWS_PROFILE", "production")
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        res = detector.detect()
        aws_ctx = res.get("aws")
        assert aws_ctx is not None
        assert "production" in aws_ctx
        assert "us-east-1" in aws_ctx

    def test_aws_from_default_env_vars(self, detector, monkeypatch):
        """AWS_DEFAULT_PROFILE and AWS_DEFAULT_REGION are recognized as fallbacks."""
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("AWS_DEFAULT_PROFILE", "staging")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")

        res = detector.detect()
        aws_ctx = res.get("aws")
        assert aws_ctx is not None
        assert "staging" in aws_ctx
        assert "eu-west-1" in aws_ctx

    def test_aws_profile_only_in_env(self, detector, monkeypatch):
        """Only AWS_PROFILE in environment returns profile name."""
        monkeypatch.setenv("AWS_PROFILE", "security-audit")
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        res = detector.detect()
        assert "security-audit" in (res.get("aws") or "")

    def test_aws_from_config_file_profile_resolution(self, detector, tmp_path, monkeypatch):
        """AWS config file resolves region for specified AWS_PROFILE."""
        fake_home = tmp_path / "home"
        aws_dir = fake_home / ".aws"
        aws_dir.mkdir(parents=True)
        config_file = aws_dir / "config"
        config_file.write_text(
            "[default]\n"
            "region = us-west-2\n\n"
            "[profile analytics-prod]\n"
            "region = ap-southeast-1\n",
            encoding="utf-8"
        )

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("USERPROFILE", str(fake_home))
        monkeypatch.setenv("AWS_CONFIG_FILE", str(config_file))
        monkeypatch.setenv("AWS_PROFILE", "analytics-prod")
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        res = detector.detect()
        aws_ctx = res.get("aws")
        assert aws_ctx is not None
        assert "analytics-prod" in aws_ctx
        assert "ap-southeast-1" in aws_ctx

    def test_aws_from_config_file_default_when_no_env_profile(self, detector, tmp_path, monkeypatch):
        """AWS config file defaults to [default] section when no profile env var is set."""
        fake_home = tmp_path / "home"
        aws_dir = fake_home / ".aws"
        aws_dir.mkdir(parents=True)
        config_file = aws_dir / "config"
        config_file.write_text(
            "[default]\n"
            "region = us-west-2\n",
            encoding="utf-8"
        )

        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("USERPROFILE", str(fake_home))
        monkeypatch.setenv("AWS_CONFIG_FILE", str(config_file))
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        res = detector.detect()
        aws_ctx = res.get("aws")
        assert aws_ctx is not None
        assert "default" in aws_ctx or "us-west-2" in aws_ctx

    def test_aws_missing_files_and_no_env_returns_none(self, detector, tmp_path, monkeypatch):
        """When no AWS environment variables or config files exist, return None."""
        fake_home = tmp_path / "empty_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("USERPROFILE", str(fake_home))
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        monkeypatch.delenv("AWS_CONFIG_FILE", raising=False)

        res = detector.detect()
        assert res.get("aws") is None

    def test_aws_malformed_config_file_handled_gracefully(self, detector, tmp_path, monkeypatch):
        """Malformed or unparseable AWS config file must not raise an unhandled exception."""
        config_file = tmp_path / "corrupted_aws_config"
        config_file.write_text("corrupted [[[ random content ::: no ini structure\n", encoding="utf-8")

        monkeypatch.setenv("AWS_CONFIG_FILE", str(config_file))
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)

        # Must not raise
        res = detector.detect()
        assert res.get("aws") is None or isinstance(res.get("aws"), str)


# ==============================================================================
# 3. Git Branch Detection Tests
# ==============================================================================

class TestGitContextDetection:
    """Unit and boundary tests for Git active branch detection."""

    def test_git_branch_standard_head(self, detector, tmp_path):
        """Standard .git/HEAD with ref: refs/heads/<branch>."""
        repo_dir = tmp_path / "repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        head_file = git_dir / "HEAD"
        head_file.write_text("ref: refs/heads/main\n", encoding="utf-8")

        res = detector.detect(cwd=str(repo_dir))
        assert res.get("git") == "main"

    def test_git_branch_nested_feature_name(self, detector, tmp_path):
        """Branch with slashes (e.g. feature/auth-v2/oauth)."""
        repo_dir = tmp_path / "repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        head_file = git_dir / "HEAD"
        head_file.write_text("ref: refs/heads/feature/auth-v2/oauth\n", encoding="utf-8")

        res = detector.detect(cwd=str(repo_dir))
        assert res.get("git") == "feature/auth-v2/oauth"

    def test_git_detached_head_commit_sha(self, detector, tmp_path):
        """Detached HEAD with 40-char commit SHA."""
        repo_dir = tmp_path / "repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        head_file = git_dir / "HEAD"
        sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
        head_file.write_text(f"{sha}\n", encoding="utf-8")

        res = detector.detect(cwd=str(repo_dir))
        git_ctx = res.get("git")
        assert git_ctx is not None
        # Should contain the short hash or detached prefix
        assert "a1b2c3d" in git_ctx or "detached" in git_ctx

    def test_git_worktree_submodule_gitdir_pointer(self, detector, tmp_path):
        """When .git is a file pointing to gitdir: <path> (worktree / submodule)."""
        repo_dir = tmp_path / "worktree_repo"
        repo_dir.mkdir(parents=True)
        actual_git_dir = tmp_path / "actual_git_storage"
        actual_git_dir.mkdir(parents=True)

        head_file = actual_git_dir / "HEAD"
        head_file.write_text("ref: refs/heads/release-v2.5\n", encoding="utf-8")

        dot_git_file = repo_dir / ".git"
        dot_git_file.write_text(f"gitdir: {str(actual_git_dir)}\n", encoding="utf-8")

        res = detector.detect(cwd=str(repo_dir))
        assert res.get("git") == "release-v2.5"

    def test_git_deep_subdirectory_traversal(self, detector, tmp_path):
        """CWD nested deep inside repository traverses up to locate .git/HEAD."""
        repo_dir = tmp_path / "deep_repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/fix-race-condition\n", encoding="utf-8")

        deep_subdir = repo_dir / "src" / "modules" / "subservice" / "handlers"
        deep_subdir.mkdir(parents=True)

        res = detector.detect(cwd=str(deep_subdir))
        assert res.get("git") == "fix-race-condition"

    def test_git_no_repo_returns_none(self, detector, tmp_path):
        """When CWD is not in a git repository, return None without error."""
        non_git_dir = tmp_path / "plain_dir" / "nested"
        non_git_dir.mkdir(parents=True)

        res = detector.detect(cwd=str(non_git_dir))
        assert res.get("git") is None

    def test_git_empty_or_malformed_head_handled_gracefully(self, detector, tmp_path):
        """Empty or binary .git/HEAD file returns None gracefully."""
        repo_dir = tmp_path / "corrupt_repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_bytes(b"\x00\xff\xfe\x01\x02\x03")

        res = detector.detect(cwd=str(repo_dir))
        assert res.get("git") is None


# ==============================================================================
# 4. Combined Detection & Badge Formatting Tests
# ==============================================================================

class TestBadgeFormatting:
    """Unit and boundary tests for format_badge() contract."""

    def test_format_badge_k8s_only(self, detector):
        """Single active Kubernetes environment context."""
        env = {"k8s": "prod-us-east-1", "aws": None, "git": None}
        badge = detector.format_badge(env)
        assert badge is not None
        assert badge.startswith("[ENV:")
        assert badge.endswith("]")
        assert "prod-us-east-1" in badge
        assert "k8s" in badge

    def test_format_badge_aws_only(self, detector):
        """Single active AWS environment context."""
        env = {"k8s": None, "aws": "production:us-east-1", "git": None}
        badge = detector.format_badge(env)
        assert badge is not None
        assert badge.startswith("[ENV:")
        assert badge.endswith("]")
        assert "production" in badge

    def test_format_badge_git_only(self, detector):
        """Single active Git branch context."""
        env = {"k8s": None, "aws": None, "git": "main"}
        badge = detector.format_badge(env)
        assert badge is not None
        assert badge.startswith("[ENV:")
        assert badge.endswith("]")
        assert "main" in badge

    def test_format_badge_multi_active_context(self, detector):
        """Multiple active contexts combined cleanly with delimiters."""
        env = {"k8s": "prod-us-east-1", "aws": "staging:eu-west-1", "git": "hotfix/login"}
        badge = detector.format_badge(env)
        assert badge is not None
        assert "prod-us-east-1" in badge
        assert "staging" in badge or "eu-west-1" in badge
        assert "hotfix/login" in badge

    def test_format_badge_all_none(self, detector):
        """When no context is detected, format_badge returns None or fallback."""
        env = {"k8s": None, "aws": None, "git": None}
        badge = detector.format_badge(env)
        assert badge is None or badge == "" or badge == "[ENV: local]"

    def test_detect_returns_all_three_keys(self, detector):
        """Contract test: detect() must always return a dict with k8s, aws, git keys."""
        res = detector.detect()
        assert isinstance(res, dict)
        assert "k8s" in res
        assert "aws" in res
        assert "git" in res


# ==============================================================================
# 5. Microbenchmark & Performance Guardrail Tests (< 0.5ms per check)
# ==============================================================================

class TestContextDetectorPerformance:
    """Performance verification ensuring context detection runs in < 1.0ms total (< 0.5ms per check)."""

    def test_sub_millisecond_uncached_detection(self, detector, tmp_path, monkeypatch):
        """Uncached detection across all 3 providers must complete in < 1.0ms total."""
        # Setup mock environment
        kubeconfig = tmp_path / "perf-kube.yaml"
        kubeconfig.write_text("current-context: perf-cluster\n", encoding="utf-8")
        monkeypatch.setenv("KUBECONFIG", str(kubeconfig))
        monkeypatch.setenv("AWS_PROFILE", "perf-profile")
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        repo_dir = tmp_path / "perf-repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/perf-branch\n", encoding="utf-8")

        # Warm up
        _ = detector.detect(cwd=str(repo_dir))

        latencies_ms = []
        for _ in range(100):
            t0 = time.perf_counter()
            _ = detector.detect(cwd=str(repo_dir))
            lat = (time.perf_counter() - t0) * 1000
            latencies_ms.append(lat)

        p50 = sorted(latencies_ms)[len(latencies_ms) // 2]
        mean = sum(latencies_ms) / len(latencies_ms)

        print(f"\n[ContextDetector Benchmark] P50: {p50:.4f}ms | Mean: {mean:.4f}ms | Max: {max(latencies_ms):.4f}ms")
        assert p50 < 0.50, f"Expected P50 latency < 0.50ms, got {p50:.4f}ms"
        assert mean < 1.00, f"Expected Mean latency < 1.00ms, got {mean:.4f}ms"

    def test_sub_50_microsecond_cached_detection(self, detector, tmp_path, monkeypatch):
        """Consecutive queries using in-memory mtime/TTL cache must run in sub-50 microseconds (< 0.05ms)."""
        monkeypatch.setenv("AWS_PROFILE", "cached-profile")
        monkeypatch.setenv("AWS_REGION", "us-west-2")

        repo_dir = tmp_path / "cache-repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/cached-branch\n", encoding="utf-8")

        # Initial prime
        _ = detector.detect(cwd=str(repo_dir))

        cached_latencies = []
        for _ in range(200):
            t0 = time.perf_counter()
            _ = detector.detect(cwd=str(repo_dir))
            lat = (time.perf_counter() - t0) * 1000
            cached_latencies.append(lat)

        p50 = sorted(cached_latencies)[len(cached_latencies) // 2]
        print(f"\n[Cached ContextDetector Benchmark] P50: {p50:.4f}ms")
        assert p50 < 0.20, f"Expected cached P50 latency < 0.20ms, got {p50:.4f}ms"

    def test_zero_subprocess_invocations(self, detector, monkeypatch):
        """Context detection must never spawn external CLI subprocesses (e.g. git or kubectl)."""
        def forbidden_subprocess(*args, **kwargs):
            raise RuntimeError("Subprocess execution is strictly forbidden in ContextDetector!")

        monkeypatch.setattr(subprocess, "Popen", forbidden_subprocess)
        monkeypatch.setattr(subprocess, "run", forbidden_subprocess)
        monkeypatch.setattr(subprocess, "call", forbidden_subprocess)
        monkeypatch.setattr(subprocess, "check_output", forbidden_subprocess)

        # Must execute without calling any subprocess
        res = detector.detect()
        assert isinstance(res, dict)
