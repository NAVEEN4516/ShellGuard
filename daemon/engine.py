"""
ShellGuard Engine
The core intelligence engine providing sub-10ms command evaluation,
semantic similarity scoring via Moss, safety classification, and latency telemetry.
"""

import time
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

import moss_core
from daemon.indexer import build_index, load_all_incidents, INDEX_NAME

logger = logging.getLogger("shellguard.engine")

# Commands with these prefixes undergo deep semantic evaluation.
INTERCEPTION_PREFIXES = (
    "kubectl",
    "terraform",
    "docker",
    "aws",
    "gcloud",
    "az",
    "rm",
    "git",
    "helm",
    "drop",
    "delete",
    "truncate",
)

# Read-only subcommands that are guaranteed non-destructive and bypass immediately
READ_ONLY_SUBCOMMANDS = {
    "kubectl": ("get", "describe", "logs", "explain", "cluster-info", "top", "version", "api-resources", "config view", "config current-context"),
    "terraform": ("plan", "show", "version", "validate", "output", "providers", "fmt -check"),
    "docker": ("ps", "images", "logs", "inspect", "stats", "version", "info", "top", "port"),
    "git": ("status", "log", "diff", "branch", "show", "remote", "fetch", "checkout", "switch", "stash list"),
    "aws": ("ls", "describe-", "get-", "list-"),
    "gcloud": ("list", "describe", "get-value"),
}

DESTRUCTIVE_SIGNALS = (
    "delete",
    "destroy",
    "drop",
    "truncate",
    "prune",
    "rm",
    "purge",
    "terminate",
    "wipe",
    "force",
    "--force",
    "-f",
    "--auto-approve",
    "-destroy",
    "--all",
    "--volumes",
    "public-read",
)

SIMILARITY_BLOCK_THRESHOLD = 0.70
SIMILARITY_WARN_THRESHOLD = 0.55


@dataclass
class CheckResult:
    command: str
    status: str  # "PASSED" | "WARNING" | "BLOCKED"
    is_intercepted: bool
    matched_incident_id: Optional[str] = None
    matched_incident_title: Optional[str] = None
    matched_pattern: Optional[str] = None
    severity: Optional[str] = None
    similarity_score: float = 0.0
    safe_alternative: Optional[str] = None
    blast_radius: Optional[str] = None
    recommendation: Optional[str] = None
    latency_ms: float = 0.0
    engine: str = "moss-in-process"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ShellGuardEngine:
    def __init__(self):
        self.index_manager = moss_core.LocalIndexManager()
        self.incidents: List[Dict[str, Any]] = []
        self.total_docs_indexed: int = 0
        self.history: List[CheckResult] = []
        self.latencies: List[float] = []
        self.is_initialized: bool = False

    def initialize(self):
        """Initialize engine, parse all incidents and hydrate in-memory Moss index."""
        t0 = time.perf_counter()
        self.incidents = load_all_incidents()
        self.total_docs_indexed = build_index(self.index_manager, self.incidents)
        self.is_initialized = True
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"ShellGuard Engine initialized in {elapsed_ms:.2f}ms with {self.total_docs_indexed} chunks.")

    def is_read_only(self, command: str) -> bool:
        """Check if command is an inherently safe read-only operation."""
        tokens = command.strip().split()
        if not tokens:
            return True
        root_cmd = tokens[0].lower()
        if root_cmd in READ_ONLY_SUBCOMMANDS:
            subcmds = READ_ONLY_SUBCOMMANDS[root_cmd]
            cmd_remainder = " ".join(tokens[1:]).lower()
            for sub in subcmds:
                if cmd_remainder.startswith(sub):
                    return True
        return False

    def has_destructive_intent(self, command: str) -> bool:
        """Check if command contains explicit or implicit destructive markers."""
        lowered = command.lower()
        return any(sig in lowered for sig in DESTRUCTIVE_SIGNALS)

    def should_evaluate(self, command: str) -> bool:
        """Quickly determine if command warrants semantic safety inspection."""
        clean_cmd = command.strip().lower()
        if not clean_cmd:
            return False
        return clean_cmd.startswith(INTERCEPTION_PREFIXES)

    def evaluate(self, command: str) -> CheckResult:
        """
        Evaluate a shell command in real-time.
        Target execution time: < 8ms for warm queries.
        """
        t0 = time.perf_counter()
        clean_cmd = command.strip()

        # Step 1: Fast filter check (sub-microsecond)
        if not self.should_evaluate(clean_cmd):
            elapsed_ms = (time.perf_counter() - t0) * 1000
            res = CheckResult(
                command=clean_cmd,
                status="PASSED",
                is_intercepted=False,
                latency_ms=round(elapsed_ms, 3),
                recommendation="Command bypassed safety filter (non-infrastructure category).",
            )
            self._record_telemetry(res)
            return res

        # Step 2: Safe read-only inspection check (sub-microsecond)
        if self.is_read_only(clean_cmd):
            elapsed_ms = (time.perf_counter() - t0) * 1000
            res = CheckResult(
                command=clean_cmd,
                status="PASSED",
                is_intercepted=False,
                latency_ms=round(elapsed_ms, 3),
                recommendation="Read-only diagnostic inspection command. Safe to execute.",
            )
            self._record_telemetry(res)
            return res

        # Step 3: In-Process Moss Semantic Query
        if not self.index_manager.has_index(INDEX_NAME):
            logger.warning("Index not found, re-initializing...")
            self.initialize()

        search_result = self.index_manager.query(INDEX_NAME, clean_cmd, top_k=3, alpha=0.85)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Step 4: Analyze top hit and cross-reference with destructive intent
        if search_result.docs:
            top_hit = search_result.docs[0]
            score = float(top_hit.score)
            payload = {}
            if top_hit.payload:
                try:
                    payload = json.loads(top_hit.payload)
                except Exception as e:
                    logger.error(f"Failed to parse payload: {e}")

            has_destructive = self.has_destructive_intent(clean_cmd)

            status = "PASSED"
            if score >= SIMILARITY_BLOCK_THRESHOLD and has_destructive:
                status = "BLOCKED"
            elif score >= SIMILARITY_WARN_THRESHOLD or (has_destructive and score >= 0.50):
                status = "WARNING"

            res = CheckResult(
                command=clean_cmd,
                status=status,
                is_intercepted=(status != "PASSED"),
                matched_incident_id=payload.get("incident_id"),
                matched_incident_title=payload.get("title"),
                matched_pattern=payload.get("matched_pattern"),
                severity=payload.get("severity"),
                similarity_score=round(score, 4),
                safe_alternative=payload.get("safe_alternative"),
                blast_radius=payload.get("blast_radius"),
                recommendation=payload.get("recommendation") or f"Matched past incident {payload.get('incident_id')}.",
                latency_ms=round(elapsed_ms, 3),
            )
        else:
            res = CheckResult(
                command=clean_cmd,
                status="PASSED",
                is_intercepted=False,
                similarity_score=0.0,
                latency_ms=round(elapsed_ms, 3),
                recommendation="No matching past incident identified.",
            )

        self._record_telemetry(res)
        return res

    def _record_telemetry(self, result: CheckResult):
        """Append to in-memory ring buffer for telemetry dashboard."""
        self.history.insert(0, result)
        if len(self.history) > 100:
            self.history.pop()
        self.latencies.append(result.latency_ms)
        if len(self.latencies) > 500:
            self.latencies.pop(0)

    def get_stats(self) -> Dict[str, Any]:
        """Compute performance metrics and telemetry."""
        total_evals = len(self.latencies)
        if total_evals == 0:
            return {
                "total_checks": 0,
                "blocked_count": 0,
                "warning_count": 0,
                "passed_count": 0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "p99_latency_ms": 0.0,
                "average_latency_ms": 0.0,
                "total_incidents_loaded": len(self.incidents),
                "total_chunks_indexed": self.total_docs_indexed,
            }

        sorted_lat = sorted(self.latencies)
        p50 = sorted_lat[int(total_evals * 0.50)]
        p95 = sorted_lat[int(total_evals * 0.95)] if total_evals >= 20 else sorted_lat[-1]
        p99 = sorted_lat[int(total_evals * 0.99)] if total_evals >= 100 else sorted_lat[-1]
        avg_lat = sum(self.latencies) / total_evals

        blocked = sum(1 for h in self.history if h.status == "BLOCKED")
        warned = sum(1 for h in self.history if h.status == "WARNING")
        passed = sum(1 for h in self.history if h.status == "PASSED")

        return {
            "total_checks": len(self.history),
            "blocked_count": blocked,
            "warning_count": warned,
            "passed_count": passed,
            "p50_latency_ms": round(p50, 2),
            "p95_latency_ms": round(p95, 2),
            "p99_latency_ms": round(p99, 2),
            "average_latency_ms": round(avg_lat, 2),
            "total_incidents_loaded": len(self.incidents),
            "total_chunks_indexed": self.total_docs_indexed,
        }
