"""
Unit and Integration Test Suite for Tiered Indexing & LRU Memory Manager (R3).
Verifies:
1. Native process RSS memory measurement without external psutil dependency.
2. Strict adherence to < 250MB RSS memory ceiling in isolated engine run (~34MB).
3. LRU eviction of non-P0 chunks into compressed Tier 2 disk storage (.json.gz) when hot capacity is reached.
4. Active memory pressure (>90% RSS ceiling) triggering eviction before capacity limit.
5. Protection of P0 incident chunks from eviction over non-P0 chunks.
6. Promotion of cold incident archives back into Tier 1 hot in-memory index.
7. LRU access reordering via record_access().
8. Endpoint: GET /api/memory/stats returns live operational metrics and compliance status.
"""

import os
import sys
import gzip
import time
import json
import subprocess
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from daemon.lru import TieredIndexManager
from daemon.server import app


@pytest.fixture
def tiered_manager(tmp_path):
    cold_dir = tmp_path / "cold_incidents"
    return TieredIndexManager(
        max_hot_chunks=3,
        max_rss_mb=250,
        cold_storage_dir=cold_dir,
        rss_provider=lambda: 35.0,  # Standalone daemon operates at ~34MB RSS
    )


@pytest.fixture
def test_client():
    return TestClient(app)


class TestTieredIndexManagerUnit:
    def test_native_process_rss_measurement_call(self):
        rss_mb = TieredIndexManager.get_process_rss_mb()
        assert isinstance(rss_mb, float)
        assert rss_mb > 0.0

    def test_standalone_engine_rss_strictly_under_250mb(self):
        """Validates that ShellGuard engine running standalone strictly obeys the < 250MB limit."""
        cmd = [
            sys.executable,
            "-c",
            "from daemon.engine import ShellGuardEngine; e = ShellGuardEngine(); from daemon.lru import TieredIndexManager; print(TieredIndexManager.get_process_rss_mb())",
        ]
        out = subprocess.check_output(cmd, text=True, cwd=str(PROJECT_ROOT)).strip()
        standalone_rss = float(out)
        assert standalone_rss < 250.0
        # Typically around 33MB-45MB, well under the 250MB limit
        assert standalone_rss < 100.0

    def test_hot_chunk_registration_within_limit(self, tiered_manager):
        tiered_manager.register_incident("INC-01", "Title 1", "Content 1", is_p0=False)
        tiered_manager.register_incident("INC-02", "Title 2", "Content 2", is_p0=False)

        stats = tiered_manager.get_stats()
        assert stats["tier1_hot_chunks"] == 2
        assert stats["tier2_cold_chunks"] == 0
        assert stats["total_evictions"] == 0

    def test_lru_eviction_when_capacity_exceeded(self, tiered_manager):
        # max_hot_chunks is 3
        tiered_manager.register_incident("INC-01", "Title 1", "Content 1", is_p0=False)
        tiered_manager.register_incident("INC-02", "Title 2", "Content 2", is_p0=False)
        tiered_manager.register_incident("INC-03", "Title 3", "Content 3", is_p0=False)

        assert tiered_manager.get_stats()["tier1_hot_chunks"] == 3
        assert tiered_manager.get_stats()["tier2_cold_chunks"] == 0

        # Adding 4th should evict the oldest (INC-01)
        tiered_manager.register_incident("INC-04", "Title 4", "Content 4", is_p0=False)

        stats = tiered_manager.get_stats()
        assert stats["tier1_hot_chunks"] == 3
        assert stats["tier2_cold_chunks"] == 1
        assert stats["total_evictions"] == 1
        assert "INC-01" not in tiered_manager._hot_registry
        assert "INC-01" in tiered_manager._cold_registry

        # Verify cold archive is gzip-compressed
        cold_file = tiered_manager._cold_registry["INC-01"]
        assert cold_file.exists()
        assert cold_file.suffix == ".gz"
        with gzip.open(cold_file, "rt", encoding="utf-8") as gz:
            data = json.load(gz)
            assert data["id"] == "INC-01"
            assert data["title"] == "Title 1"

    def test_memory_pressure_triggers_proactive_eviction(self, tmp_path):
        """Validates that simulated RSS exceeding 90% threshold triggers eviction even below max_hot_chunks."""
        high_rss = 235.0  # > 250 * 0.90 = 225MB
        mgr = TieredIndexManager(
            max_hot_chunks=10,
            max_rss_mb=250,
            cold_storage_dir=tmp_path / "cold",
            rss_provider=lambda: high_rss,
        )

        mgr.register_incident("INC-01", "Title 1", "Content 1", is_p0=False)
        # Registering 2nd item under memory pressure should proactively evict the first item
        mgr.register_incident("INC-02", "Title 2", "Content 2", is_p0=False)

        assert mgr.total_evictions == 1
        assert "INC-01" in mgr._cold_registry

    def test_p0_chunk_protection_during_eviction(self, tiered_manager):
        # Register P0 incident first, then two non-P0
        tiered_manager.register_incident("INC-P0-ROOT", "P0 Disaster", "Critical Content", is_p0=True)
        tiered_manager.register_incident("INC-NORM-1", "Normal 1", "Content", is_p0=False)
        tiered_manager.register_incident("INC-NORM-2", "Normal 2", "Content", is_p0=False)

        # Register 4th incident. INC-NORM-1 should be evicted, NOT INC-P0-ROOT
        tiered_manager.register_incident("INC-NORM-3", "Normal 3", "Content", is_p0=False)

        assert "INC-P0-ROOT" in tiered_manager._hot_registry
        assert "INC-NORM-1" not in tiered_manager._hot_registry
        assert "INC-NORM-1" in tiered_manager._cold_registry

    def test_cold_incident_promotion(self, tiered_manager):
        # Register 4 incidents to force INC-01 into cold storage
        tiered_manager.register_incident("INC-01", "Title 1", "Content 1", is_p0=False)
        tiered_manager.register_incident("INC-02", "Title 2", "Content 2", is_p0=False)
        tiered_manager.register_incident("INC-03", "Title 3", "Content 3", is_p0=False)
        tiered_manager.register_incident("INC-04", "Title 4", "Content 4", is_p0=False)

        assert "INC-01" in tiered_manager._cold_registry

        # Promote INC-01 back to hot tier
        promoted = tiered_manager.promote_cold_incident("INC-01")
        assert promoted is not None
        assert promoted["id"] == "INC-01"
        assert "INC-01" in tiered_manager._hot_registry
        assert "INC-01" not in tiered_manager._cold_registry
        assert tiered_manager.total_promotions == 1

    def test_record_access_updates_lru_order(self, tiered_manager):
        tiered_manager.register_incident("INC-01", "Title 1", "Content 1", is_p0=False)
        tiered_manager.register_incident("INC-02", "Title 2", "Content 2", is_p0=False)
        tiered_manager.register_incident("INC-03", "Title 3", "Content 3", is_p0=False)

        # Touch INC-01 to move it to most recently used
        tiered_manager.record_access("INC-01")

        # Now registering INC-04 should evict INC-02 (the new oldest non-P0)
        tiered_manager.register_incident("INC-04", "Title 4", "Content 4", is_p0=False)

        assert "INC-01" in tiered_manager._hot_registry
        assert "INC-02" not in tiered_manager._hot_registry
        assert "INC-02" in tiered_manager._cold_registry


class TestTieredMemoryEndpoint:
    def test_memory_stats_endpoint(self, test_client):
        # Temporarily mock realistic daemon RSS memory (34.5MB)
        os.environ["SHELLGUARD_OVERRIDE_RSS_MB"] = "34.5"
        try:
            response = test_client.get("/api/memory/stats")
            assert response.status_code == 200
            data = response.json()

            assert "tier1_hot_chunks" in data
            assert "tier2_cold_chunks" in data
            assert "total_evictions" in data
            assert "total_promotions" in data
            assert "current_rss_mb" in data
            assert "max_rss_mb" in data
            assert "memory_headroom_mb" in data
            assert "is_memory_compliant" in data

            assert data["is_memory_compliant"] is True
            assert data["max_rss_mb"] == 250
            assert data["current_rss_mb"] == 34.5
            assert data["memory_headroom_mb"] > 200.0
        finally:
            os.environ.pop("SHELLGUARD_OVERRIDE_RSS_MB", None)
