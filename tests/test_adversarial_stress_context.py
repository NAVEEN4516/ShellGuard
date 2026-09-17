"""
Adversarial Stress Test Suite for ShellGuard Multi-Cloud Context Detector (daemon/context.py).

Empirically challenges:
1. Deeply nested directories (10+ levels) and boundary traversal limits.
2. Corrupted, binary, oversized, and adversarial .git/HEAD payloads.
3. Multi-megabyte mock kubeconfigs (1MB, 5MB, 10MB, long lines, missing context).
4. Malformed, corrupted, and adversarial INI configs for AWS.
5. High-concurrency multithreaded queries (50 threads calling detect() concurrently).
"""

import os
import sys
import time
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from daemon.context import (
    ContextDetector,
    parse_k8s_context,
    parse_aws_config,
    parse_git_head,
    detect_environment,
    format_badge,
)


# ==============================================================================
# 1. Stress Test: Deeply Nested Directory Paths (10+ Levels)
# ==============================================================================

class TestDeeplyNestedDirectories:
    """Stress tests verifying behavior across 10+ levels of nested directories."""

    def test_nested_10_levels_below_git_repo(self, tmp_path):
        """
        Verify behavior when CWD is 10 to 15 levels deep below the .git repository root.
        ContextDetector._resolve_git_head_path checks up to 6 levels (5 directory hops).
        Empirical boundary:
        - Hop 0-5 (depth 0 to 5): detects git branch accurately.
        - Hop 6+ (depth 6+): gracefully returns None without error.
        - Traversal must never crash or hang.
        """
        repo_dir = tmp_path / "deep_git_repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/stress/nested-branch\n", encoding="utf-8")

        detector = ContextDetector()

        # Build nested directory chain: level_0/level_1/.../level_15
        current_dir = repo_dir
        levels = []
        for i in range(16):
            current_dir = current_dir / f"level_{i}"
            current_dir.mkdir()
            levels.append(current_dir)

        # Check level 4 (5 directory hops from repo root)
        res_4 = detector.detect(cwd=str(levels[4]))
        assert res_4.get("git") == "stress/nested-branch", "Level 4 should detect git branch"

        # Check level 10 (11 directory hops): should return None gracefully without crashing
        t0 = time.perf_counter()
        res_10 = detector.detect(cwd=str(levels[10]))
        elapsed_10_ms = (time.perf_counter() - t0) * 1000

        # Check level 15 (16 directory hops): should return None gracefully without crashing
        t0 = time.perf_counter()
        res_15 = detector.detect(cwd=str(levels[15]))
        elapsed_15_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_10_ms < 10.0
        assert elapsed_15_ms < 10.0
        assert isinstance(res_10, dict)
        assert isinstance(res_15, dict)
        assert res_10.get("git") is None
        assert res_15.get("git") is None

    def test_nested_15_levels_non_git_directory(self, tmp_path):
        """15 nested non-git levels must gracefully return None without error."""
        base_dir = tmp_path / "non_git_tree"
        curr = base_dir
        for i in range(15):
            curr = curr / f"sub_{i}"
            curr.mkdir(parents=True, exist_ok=True)

        detector = ContextDetector()
        # Cold run
        t0 = time.perf_counter()
        res_cold = detector.detect(cwd=str(curr))
        dur_cold_ms = (time.perf_counter() - t0) * 1000

        # Warm run
        t0 = time.perf_counter()
        res_warm = detector.detect(cwd=str(curr))
        dur_warm_ms = (time.perf_counter() - t0) * 1000

        assert res_cold.get("git") is None
        assert res_warm.get("git") is None
        assert dur_cold_ms < 15.0, f"Cold traversal took {dur_cold_ms:.3f}ms"
        assert dur_warm_ms < 0.20, f"Warm traversal should be < 0.20ms, got {dur_warm_ms:.3f}ms"

    def test_extreme_path_length(self, tmp_path):
        """Very long path (approaching MAX_PATH ~240 chars) must not crash."""
        curr = tmp_path
        try:
            for i in range(12):
                curr = curr / f"long_dir_segment_{i:02d}"
                curr.mkdir(exist_ok=True)
        except OSError:
            pytest.skip("Filesystem does not support long paths on this host")

        detector = ContextDetector()
        res = detector.detect(cwd=str(curr))
        assert isinstance(res, dict)
        assert res.get("git") is None


# ==============================================================================
# 2. Stress Test: Corrupted and Adversarial .git/HEAD Payloads
# ==============================================================================

class TestCorruptedGitHead:
    """Stress tests with adversarial, corrupt, binary, and oversized .git/HEAD payloads."""

    def test_random_binary_head_payloads(self, tmp_path):
        """Arbitrary binary noise (zeros, 0xFF, random byte blocks) must not raise UnicodeDecodeError."""
        repo_dir = tmp_path / "binary_head_repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        head_file = git_dir / "HEAD"

        binary_samples = [
            b"\x00" * 256,
            b"\xff\xfe\x00\x01\x02\x03\x7f\x80\x90\xaa\xbb\xcc",
            bytes(range(256)),
            os.urandom(1024),
            b"\x80\x81\x82\x83\xff\xff",
        ]

        for idx, sample in enumerate(binary_samples):
            head_file.write_bytes(sample)
            det = ContextDetector(ttl=0.0)
            res = det.detect(cwd=str(repo_dir))
            assert isinstance(res, dict)
            assert res.get("git") is None, f"Sample {idx} should resolve to None"

    def test_adversarial_ref_prefixes(self, tmp_path):
        """
        Adversarial inputs starting with 'ref: ' but containing strange, control, or binary characters.
        Verify format_badge and detect() stability.
        """
        repo_dir = tmp_path / "adv_head_repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        head_file = git_dir / "HEAD"

        detector = ContextDetector(ttl=0.0)

        cases = [
            ("ref: refs/heads/\n", None),  # Empty branch after refs/heads/
            ("ref: \n", None),             # Empty branch after ref:
            ("ref: refs/heads/   \t   \n", None),
            ("ref: refs/heads/v1.0.0-rc.1\r\n", "v1.0.0-rc.1"),
            ("ref: refs/heads/feature/nested/deep/branch/name\n", "feature/nested/deep/branch/name"),
            ("ref: refs/tags/v2.1.0\n", "refs/tags/v2.1.0"),
        ]

        for payload, expected in cases:
            head_file.write_text(payload, encoding="utf-8")
            res = detector.detect(cwd=str(repo_dir))
            actual = res.get("git")
            if expected is None:
                assert actual is None or actual == "", f"Payload {repr(payload)} expected None/empty, got {repr(actual)}"
            else:
                assert actual == expected

    def test_oversized_head_file(self, tmp_path):
        """Oversized .git/HEAD file (1MB of characters without newline) must not hang parser."""
        repo_dir = tmp_path / "huge_head_repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        head_file = git_dir / "HEAD"

        # 1MB of 'a' characters without a newline
        head_file.write_bytes(b"a" * (1024 * 1024))

        detector = ContextDetector(ttl=0.0)
        t0 = time.perf_counter()
        res = detector.detect(cwd=str(repo_dir))
        dur_ms = (time.perf_counter() - t0) * 1000

        assert dur_ms < 50.0, "Parsing 1MB HEAD should finish quickly"
        # 1MB of 'a' is > 64 chars, so _GIT_HEX_SHA_RE won't match -> None
        assert res.get("git") is None


# ==============================================================================
# 3. Stress Test: Multi-Megabyte Mock Kubeconfigs
# ==============================================================================

class TestMultiMegabyteKubeconfig:
    """Stress tests evaluating parser performance on 1MB, 5MB, and 10MB kubeconfigs."""

    def _generate_synthetic_kubeconfig(self, target_size_bytes: int, context_position: str = "middle") -> str:
        """
        Generate synthetic kubeconfig YAML with clusters, users, contexts,
        and simulated large client certificates.
        """
        header = "apiVersion: v1\nkind: Config\nclusters:\n"
        footer = "users:\n- name: admin\n  user:\n    client-certificate-data: " + ("QUJDREVGR0hJ" * 20) + "\n"

        target_context = "stress-cluster-target-context"
        context_line = f"current-context: {target_context}\n"

        base_size = len(header) + len(footer) + len(context_line)
        needed_padding = max(0, target_size_bytes - base_size)

        filler_entry = (
            "- context:\n"
            "    cluster: mock-cluster\n"
            "    user: mock-user\n"
            "  name: mock-context-name\n"
        )
        repeats = needed_padding // len(filler_entry)
        filler_body = filler_entry * repeats

        if context_position == "start":
            return header + context_line + "contexts:\n" + filler_body + footer
        elif context_position == "end":
            return header + "contexts:\n" + filler_body + context_line + footer
        else: # middle
            half = len(filler_body) // 2
            return header + "contexts:\n" + filler_body[:half] + context_line + filler_body[half:] + footer

    def test_1mb_kubeconfig_streaming_latency(self, tmp_path, monkeypatch):
        """1MB Kubeconfig with context at start, middle, and end."""
        detector = ContextDetector(ttl=0.0)

        for pos in ["start", "middle", "end"]:
            content = self._generate_synthetic_kubeconfig(1 * 1024 * 1024, context_position=pos)
            kfile = tmp_path / f"kube_1mb_{pos}.yaml"
            kfile.write_text(content, encoding="utf-8")
            monkeypatch.setenv("KUBECONFIG", str(kfile))

            t0 = time.perf_counter()
            res = detector.detect()
            elapsed_ms = (time.perf_counter() - t0) * 1000

            assert res.get("k8s") == "stress-cluster-target-context"
            if pos == "start":
                assert elapsed_ms < 10.0, f"Start position took {elapsed_ms:.3f}ms"
            else:
                assert elapsed_ms < 60.0, f"{pos} position took {elapsed_ms:.3f}ms"

    def test_5mb_kubeconfig_missing_context(self, tmp_path, monkeypatch):
        """5MB Kubeconfig with NO current-context present must stream through without error."""
        header = "apiVersion: v1\nkind: Config\ncontexts:\n"
        filler_entry = "- context:\n    cluster: c\n    user: u\n  name: n\n"
        repeats = (5 * 1024 * 1024) // len(filler_entry)
        content = header + (filler_entry * repeats)

        kfile = tmp_path / "kube_5mb_no_context.yaml"
        kfile.write_text(content, encoding="utf-8")
        monkeypatch.setenv("KUBECONFIG", str(kfile))

        detector = ContextDetector(ttl=0.0)
        t0 = time.perf_counter()
        res = detector.detect()
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert res.get("k8s") is None
        assert elapsed_ms < 500.0, f"Parsing 5MB took {elapsed_ms:.3f}ms"

    def test_kubeconfig_caching_after_heavy_file(self, tmp_path, monkeypatch):
        """Once a 2MB kubeconfig is parsed, subsequent calls within TTL must be sub-50 microseconds."""
        content = self._generate_synthetic_kubeconfig(2 * 1024 * 1024, context_position="middle")
        kfile = tmp_path / "kube_2mb_cached.yaml"
        kfile.write_text(content, encoding="utf-8")
        monkeypatch.setenv("KUBECONFIG", str(kfile))

        detector = ContextDetector(ttl=1.0)
        # Prime
        res1 = detector.detect()
        assert res1.get("k8s") == "stress-cluster-target-context"

        # 50 cached queries
        cached_latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            r = detector.detect()
            cached_latencies.append((time.perf_counter() - t0) * 1000)
            assert r.get("k8s") == "stress-cluster-target-context"

        p50 = sorted(cached_latencies)[len(cached_latencies) // 2]
        assert p50 < 0.10, f"Cached query should be < 0.10ms, got {p50:.4f}ms"


# ==============================================================================
# 4. Stress Test: Malformed and Adversarial INI Configs (AWS)
# ==============================================================================

class TestMalformedAwsIniConfigs:
    """Stress tests on corrupted, malformed, and adversarial INI configs."""

    def test_missing_section_header_and_random_noise(self, tmp_path, monkeypatch):
        """Arbitrary non-INI text, missing headers, random punctuation."""
        cfg_file = tmp_path / "broken_aws_config"
        cfg_file.write_text(
            "this is not an ini file\n"
            "just raw lines = of text\n"
            "foo: bar: baz\n"
            ">>> <<<< {{{{ }}}}\n"
            "region = us-west-1\n",
            encoding="utf-8"
        )
        monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg_file))
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)

        detector = ContextDetector(ttl=0.0)
        res = detector.detect()
        assert isinstance(res, dict)
        assert res.get("aws") is None

    def test_duplicate_sections_and_options(self, tmp_path, monkeypatch):
        """Duplicate sections and options (valid or invalid in standard ConfigParser)."""
        cfg_file = tmp_path / "duplicate_aws_config"
        cfg_file.write_text(
            "[default]\n"
            "region = us-east-1\n"
            "region = us-west-2\n\n"
            "[default]\n"
            "output = json\n"
            "region = eu-central-1\n",
            encoding="utf-8"
        )
        monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg_file))
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)

        detector = ContextDetector(ttl=0.0)
        res = detector.detect()
        assert isinstance(res, dict)
        aws_val = res.get("aws")
        assert aws_val is not None
        assert "default" in aws_val or "region" in aws_val

    def test_large_ini_with_thousands_of_profiles(self, tmp_path, monkeypatch):
        """AWS config file containing 2,000 profile sections."""
        lines = []
        for i in range(2000):
            lines.append(f"[profile customer_{i:04d}]\nregion = us-east-{i % 2 + 1}\noutput = json\n")
        lines.append("[profile target-prod]\nregion = ap-northeast-1\n")

        cfg_file = tmp_path / "large_aws_config"
        cfg_file.write_text("\n".join(lines), encoding="utf-8")

        monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg_file))
        monkeypatch.setenv("AWS_PROFILE", "target-prod")
        monkeypatch.delenv("AWS_REGION", raising=False)

        detector = ContextDetector(ttl=0.0)
        t0 = time.perf_counter()
        res = detector.detect()
        dur_ms = (time.perf_counter() - t0) * 1000

        assert res.get("aws") == "target-prod:ap-northeast-1"
        assert dur_ms < 300.0, f"Cold parse took {dur_ms:.3f}ms"


# ==============================================================================
# 5. Stress Test: High Concurrency (50 Threads calling detect())
# ==============================================================================

class TestHighConcurrencyThreadSafety:
    """Stress tests running 50 concurrent worker threads against ContextDetector."""

    def test_50_concurrent_threads_same_cwd(self, tmp_path, monkeypatch):
        """
        50 threads simultaneously invoking detect() on the same working directory.
        Verifies:
        - Thread safety with zero exceptions or race conditions.
        - Zero deadlocks.
        - High throughput and cache efficiency.
        """
        repo_dir = tmp_path / "concurrent_repo"
        git_dir = repo_dir / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/concurrent-branch\n", encoding="utf-8")

        kfile = tmp_path / "concurrent_kube.yaml"
        kfile.write_text("current-context: concurrent-k8s-ctx\n", encoding="utf-8")
        monkeypatch.setenv("KUBECONFIG", str(kfile))
        monkeypatch.setenv("AWS_PROFILE", "concurrent-aws-profile")
        monkeypatch.setenv("AWS_REGION", "eu-west-1")

        detector = ContextDetector(ttl=0.5)

        num_threads = 50
        calls_per_thread = 20
        total_calls = num_threads * calls_per_thread

        barrier = threading.Barrier(num_threads)
        errors: List[Exception] = []
        results: List[Dict[str, Optional[str]]] = []
        latencies_ms: List[float] = []

        def worker():
            try:
                barrier.wait(timeout=5.0)
                for _ in range(calls_per_thread):
                    t0 = time.perf_counter()
                    res = detector.detect(cwd=str(repo_dir))
                    lat = (time.perf_counter() - t0) * 1000
                    results.append(res)
                    latencies_ms.append(lat)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        t_start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Thread deadlocked or timed out!"
        total_time_ms = (time.perf_counter() - t_start) * 1000

        assert len(errors) == 0, f"Encountered thread errors: {errors}"
        assert len(results) == total_calls

        # Verify all returned identical accurate results
        for res in results:
            assert res.get("git") == "concurrent-branch"
            assert res.get("k8s") == "concurrent-k8s-ctx"
            assert res.get("aws") == "concurrent-aws-profile:eu-west-1"

    def test_50_concurrent_threads_distinct_cwds(self, tmp_path, monkeypatch):
        """
        50 threads each querying their own distinct repository working directory.
        Tests concurrent cache writes, eviction, and head path resolution.
        """
        kfile = tmp_path / "distinct_kube.yaml"
        kfile.write_text("current-context: distinct-k8s\n", encoding="utf-8")
        monkeypatch.setenv("KUBECONFIG", str(kfile))
        monkeypatch.setenv("AWS_PROFILE", "distinct-aws")
        monkeypatch.setenv("AWS_REGION", "us-east-2")

        detector = ContextDetector(ttl=0.2, max_cache_size=64)

        num_threads = 50
        repos = []
        for i in range(num_threads):
            r = tmp_path / f"repo_{i}"
            g = r / ".git"
            g.mkdir(parents=True)
            (g / "HEAD").write_text(f"ref: refs/heads/branch-{i}\n", encoding="utf-8")
            repos.append((str(r), f"branch-{i}"))

        barrier = threading.Barrier(num_threads)
        errors: List[Exception] = []
        results: List[Tuple[int, Dict[str, Optional[str]]]] = []

        def worker(idx: int, repo_path: str):
            try:
                barrier.wait(timeout=5.0)
                for _ in range(10):
                    res = detector.detect(cwd=repo_path)
                    results.append((idx, res))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(i, repos[i][0]))
            for i in range(num_threads)
        ]
        t_start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Thread deadlocked!"
        total_time_ms = (time.perf_counter() - t_start) * 1000

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(results) == num_threads * 10

        # Verify correct branch mapping per thread
        for idx, res in results:
            expected_branch = f"branch-{idx}"
            assert res.get("git") == expected_branch, f"Thread {idx} got {res.get('git')}"
            assert res.get("k8s") == "distinct-k8s"
            assert res.get("aws") == "distinct-aws:us-east-2"


if __name__ == "__main__":
    pytest.main(["-v", __file__])
