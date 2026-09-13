"""
Unit tests for ShellGuard Core Engine and In-Memory Moss Runtime.
"""

import pytest
import time
from daemon.engine import ShellGuardEngine, INDEX_NAME


@pytest.fixture(scope="module")
def engine():
    eng = ShellGuardEngine()
    eng.initialize()
    return eng


def test_engine_initialization(engine):
    """Verify that the engine loads incidents and creates the Moss index."""
    assert engine.is_initialized is True
    assert len(engine.incidents) >= 6
    assert engine.total_docs_indexed >= 25
    assert engine.index_manager.has_index(INDEX_NAME) is True


def test_sub_10ms_retrieval_latency(engine):
    """
    CRITICAL SPRINTER REQUIREMENT:
    Warm in-memory retrieval latency must be under 10 milliseconds.
    """
    latencies = []
    query = "kubectl delete namespace ingress-nginx"

    # Warm-up query
    _ = engine.evaluate(query)

    for _ in range(20):
        t0 = time.perf_counter()
        res = engine.evaluate(query)
        lat = (time.perf_counter() - t0) * 1000
        latencies.append(lat)

    p50 = sorted(latencies)[len(latencies) // 2]
    avg = sum(latencies) / len(latencies)

    print(f"\n[Test Metrics] p50 Latency: {p50:.2f}ms | Avg Latency: {avg:.2f}ms")
    assert p50 < 10.0, f"Expected p50 latency < 10ms, got {p50:.2f}ms"
    assert res.status == "BLOCKED"
    assert res.matched_incident_id == "INC-402"


def test_fast_filter_bypass(engine):
    """Non-infrastructure commands must bypass in microseconds."""
    t0 = time.perf_counter()
    res = engine.evaluate("ls -la /tmp")
    latency = (time.perf_counter() - t0) * 1000

    assert res.status == "PASSED"
    assert res.is_intercepted is False
    assert latency < 1.0, f"Bypass should take < 1ms, took {latency:.2f}ms"
