"""
ShellGuard Engine
The core intelligence engine providing sub-10ms command evaluation,
semantic similarity scoring via Moss, safety classification, and latency telemetry.
"""

import re
import time
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Set
from dataclasses import dataclass, field, asdict

import moss_core
from daemon.context import ContextDetector
from daemon.indexer import (
    build_index,
    load_all_incidents,
    parse_incident_markdown,
    create_incident_chunks,
    INDEX_NAME,
)

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
    "kubectl": ("get", "describe", "logs", "explain", "cluster-info", "top", "version", "api-resources", "config view", "config current-context", "diff"),
    "terraform": ("plan", "show", "version", "validate", "output", "providers", "fmt -check", "fmt --check", "state list", "state show"),
    "docker": ("ps", "images", "logs", "inspect", "stats", "version", "info", "top", "port"),
    "git": ("status", "log", "diff", "branch", "show", "remote", "fetch", "checkout", "switch", "stash list", "config --get", "config --list"),
    "helm": ("list", "ls", "status", "get", "show", "history", "version", "search", "diff"),
    "redis-cli": ("ping", "info", "echo", "cluster check", "cluster info", "cluster nodes"),
    "vault": ("status", "token lookup", "lease lookup", "read", "list"),
}

# Safe flag patterns that bypass semantic blockage (e.g. simulation or diff verification)
SAFE_FLAG_PATTERN = re.compile(
    r"(?:^|\s)(--dry-run(=[a-zA-Z0-9_\-]+)?|-detailed-exitcode)(?:\s|$)",
    re.IGNORECASE
)

import shlex

# Regex patterns for destructive signals with strict word boundaries
DESTRUCTIVE_WORD_PATTERN = re.compile(
    r"\b(delete|destroy|drop|truncate|prune|rm|purge|terminate|wipe|public-read|flushall|flushdb|revoke|reset)\b",
    re.IGNORECASE
)

DESTRUCTIVE_FLAGS_PATTERN = re.compile(
    r"(?:^|\s)(--force|-force|--auto-approve|-destroy|--volumes|--all|--no-preserve-root)(?:\s|$)",
    re.IGNORECASE
)

# -f is only destructive when explicitly used in force contexts (e.g. git push -f, rm -f),
# NOT in file-argument contexts like kubectl apply -f or docker build -f
FORCE_FLAG_PATTERN = re.compile(
    r"\bgit\s+push\b.*(?:\s|^)-[a-zA-Z]*f\b",
    re.IGNORECASE
)

# Target patterns for root filesystem destruction (INC-204)
ROOT_WIPE_PATTERN = re.compile(
    r"(?:^|\s)(?:-[a-zA-Z0-9_\-]+\s+)*(/(?:\*|\s|$)|/var(?:\s|$)|/etc(?:\s|$)|/usr(?:\s|$)|/bin(?:\s|$)|/lib(?:\s|$)|/boot(?:\s|$)|--no-preserve-root)",
    re.IGNORECASE
)

# Wrappers and env variable patterns
ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
WRAPPER_COMMANDS = {"sudo", "doas", "env", "nohup", "time", "builtin", "command", "sg", "busybox", "pkexec"}
WRAPPER_OPTION_WITH_ARG = {"-u", "-g", "-C", "-p", "-o", "-S", "--user"}


def unwrap_command(command: str) -> str:
    """
    Strip leading environment variable assignments (e.g. VAR=val)
    and execution wrappers (sudo, env, nohup, time, etc.) to expose
    the root executable command.
    """
    cmd_str = command.strip()
    if not cmd_str:
        return ""
    try:
        tokens = shlex.split(cmd_str, posix=True)
    except Exception:
        tokens = cmd_str.split()

    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if ENV_VAR_PATTERN.match(token):
            idx += 1
            continue
        if token.lower() in WRAPPER_COMMANDS:
            idx += 1
            while idx < len(tokens):
                t = tokens[idx]
                if t == "--":
                    idx += 1
                    break
                elif t in WRAPPER_OPTION_WITH_ARG and idx + 1 < len(tokens):
                    idx += 2
                elif t.startswith("-"):
                    idx += 1
                else:
                    break
            continue
        break

    if idx == 0:
        return cmd_str
    if idx >= len(tokens):
        return cmd_str
    return shlex.join(tokens[idx:])


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
    safe_alternative_cmd: Optional[str] = None
    safe_alternative_notes: Optional[str] = None
    blast_radius: Optional[str] = None
    recommendation: Optional[str] = None
    latency_ms: float = 0.0
    engine: str = "moss-in-process"
    env_context: Optional[Dict[str, Optional[str]]] = None
    env_badge: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ShellGuardEngine:
    def __init__(self):
        self.index_manager = moss_core.LocalIndexManager()
        self.context_detector = ContextDetector()
        self.interception_prefixes: Set[str] = set(INTERCEPTION_PREFIXES)
        self.incidents: List[Dict[str, Any]] = []
        self.total_docs_indexed: int = 0
        self.history: List[CheckResult] = []
        self.latencies: List[float] = []
        self.is_initialized: bool = False
        self.total_checks_count: int = 0
        self.blocked_count: int = 0
        self.warning_count: int = 0
        self.passed_count: int = 0

    def initialize(self):
        """Initialize engine, parse all incidents and hydrate in-memory Moss index."""
        t0 = time.perf_counter()
        self.incidents = load_all_incidents()
        self.total_docs_indexed = build_index(self.index_manager, self.incidents)
        for inc in self.incidents:
            for cmd in inc.get("commands", []):
                toks = cmd.strip().split()
                if toks:
                    self.interception_prefixes.add(toks[0].lower())
        self.is_initialized = True
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"ShellGuard Engine initialized in {elapsed_ms:.2f}ms with {self.total_docs_indexed} chunks.")

    def learn_incident(self, markdown_or_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Dynamically learn and index a new disaster post-mortem incident in-memory
        without restarting daemon or dropping terminal hook connections.
        """
        inc = parse_incident_markdown(markdown_or_path)
        chunks = create_incident_chunks(inc)

        if not self.index_manager.has_index(INDEX_NAME):
            self.initialize()

        self.index_manager.add_documents(INDEX_NAME, chunks)

        for cmd in inc.get("commands", []):
            tokens = cmd.strip().split()
            if tokens:
                self.interception_prefixes.add(tokens[0].lower())

        self.total_docs_indexed += len(chunks)

        # Update or append incident metadata
        existing_idx = next((i for i, existing in enumerate(self.incidents) if existing.get("id") == inc.get("id")), None)
        if existing_idx is not None:
            self.incidents[existing_idx] = inc
        else:
            self.incidents.append(inc)

        logger.info(f"Dynamically learned incident {inc.get('id')} ({inc.get('title')}) with {len(chunks)} chunks.")
        return {
            "status": "learned",
            "incident_id": inc.get("id"),
            "title": inc.get("title"),
            "chunks_added": len(chunks),
            "total_docs": self.total_docs_indexed,
        }

    def has_safe_bypass(self, command: str) -> bool:
        """Check if command contains explicit non-destructive bypass flags like --dry-run or -detailed-exitcode."""
        return bool(SAFE_FLAG_PATTERN.search(command))

    def is_read_only(self, command: str) -> bool:
        """Check if command is an inherently safe read-only operation."""
        unwrapped = unwrap_command(command)
        if self.has_destructive_intent(unwrapped):
            return False

        tokens = unwrapped.strip().split()
        if not tokens:
            return True
        root_cmd = tokens[0].lower()
        sub_tokens = [t.lower() for t in tokens[1:]]
        remainder = " ".join(tokens[1:]).lower()

        # Exact subcommand matching
        if root_cmd in READ_ONLY_SUBCOMMANDS:
            for sub in READ_ONLY_SUBCOMMANDS[root_cmd]:
                if remainder == sub or remainder.startswith(sub + " "):
                    return True
                if " " not in sub and sub in sub_tokens:
                    return True

        # Hierarchical multi-token read-only dictionary for Cloud CLIs and Helm
        if root_cmd == "aws":
            if ("s3" in sub_tokens and "ls" in sub_tokens) or remainder.startswith("s3 ls"):
                return True
            for t in sub_tokens:
                if t.startswith("describe-") or t.startswith("list-") or t.startswith("get-"):
                    return True

        elif root_cmd == "gcloud":
            for t in sub_tokens:
                if t in ("list", "describe", "get-value", "view", "info", "version"):
                    return True

        elif root_cmd == "az":
            for t in sub_tokens:
                if t in ("list", "show", "get", "version", "find"):
                    return True

        elif root_cmd == "helm":
            for t in sub_tokens:
                if t in ("list", "ls", "status", "get", "show", "history", "version", "search", "diff"):
                    return True

        return False

    def has_destructive_intent(self, command: str) -> bool:
        """
        Check if command contains explicit or implicit destructive markers.
        Uses word-boundary regex so 'rm' does not match inside 'terraform'
        and '-f' does not block 'kubectl apply -f'.
        """
        lowered = command.lower()
        if DESTRUCTIVE_WORD_PATTERN.search(lowered):
            return True
        if DESTRUCTIVE_FLAGS_PATTERN.search(lowered):
            return True
        if FORCE_FLAG_PATTERN.search(lowered):
            return True
        # Also check against triggering command patterns from all loaded/learned incidents
        for inc in self.incidents:
            for trig in inc.get("commands", []):
                clean_trig = trig.strip().lower()
                if clean_trig and (clean_trig == lowered or clean_trig in lowered):
                    return True
        return False

    def should_evaluate(self, command: str) -> bool:
        """Quickly determine if command warrants semantic safety inspection."""
        clean_cmd = unwrap_command(command).strip().lower()
        if not clean_cmd:
            return False
        return clean_cmd.startswith(tuple(self.interception_prefixes))

    def evaluate(self, command: str, cwd: Optional[str] = None) -> CheckResult:
        """
        Evaluate a shell command in real-time.
        Target execution time: < 8ms for warm queries.
        """
        t0 = time.perf_counter()
        clean_cmd = command.strip()
        target_cmd = unwrap_command(clean_cmd)

        # Environment context detection (< 0.05ms)
        env_dict = self.context_detector.detect(cwd=cwd)
        env_badge = self.context_detector.format_badge(env_dict)

        # Step 1: Safe simulation / dry-run flag bypass (sub-microsecond)
        if self.has_safe_bypass(target_cmd):
            elapsed_ms = (time.perf_counter() - t0) * 1000
            res = CheckResult(
                command=clean_cmd,
                status="PASSED",
                is_intercepted=False,
                latency_ms=round(elapsed_ms, 3),
                recommendation="Safe dry-run / simulation flag detected. Safe to execute.",
                env_context=env_dict,
                env_badge=env_badge,
            )
            self._record_telemetry(res)
            return res

        # Step 2: Fast filter check (sub-microsecond)
        if not self.should_evaluate(target_cmd):
            elapsed_ms = (time.perf_counter() - t0) * 1000
            res = CheckResult(
                command=clean_cmd,
                status="PASSED",
                is_intercepted=False,
                latency_ms=round(elapsed_ms, 3),
                recommendation="Command bypassed safety filter (non-infrastructure category).",
                env_context=env_dict,
                env_badge=env_badge,
            )
            self._record_telemetry(res)
            return res

        # Step 3: Safe read-only inspection check (sub-microsecond)
        if self.is_read_only(target_cmd):
            elapsed_ms = (time.perf_counter() - t0) * 1000
            res = CheckResult(
                command=clean_cmd,
                status="PASSED",
                is_intercepted=False,
                latency_ms=round(elapsed_ms, 3),
                recommendation="Read-only diagnostic inspection command. Safe to execute.",
                env_context=env_dict,
                env_badge=env_badge,
            )
            self._record_telemetry(res)
            return res

        # Step 4: In-Process Moss Semantic Query
        if not self.index_manager.has_index(INDEX_NAME):
            logger.warning("Index not found, re-initializing...")
            self.initialize()

        search_result = self.index_manager.query(INDEX_NAME, target_cmd, top_k=3, alpha=0.85)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Step 5: Analyze top hit and cross-reference with destructive intent
        if search_result.docs:
            top_hit = search_result.docs[0]
            score = float(top_hit.score)
            payload = {}
            if top_hit.payload:
                try:
                    payload = json.loads(top_hit.payload)
                except Exception as e:
                    logger.error(f"Failed to parse payload: {e}")

            incident_id = payload.get("incident_id")
            has_destructive = self.has_destructive_intent(target_cmd)

            # Specific disaster profile matching to eliminate false positives on benign operations
            if has_destructive and incident_id:
                low_cmd = target_cmd.lower()
                # INC-204: Only root/system filesystem wipe paths or --no-preserve-root
                if incident_id == "INC-204":
                    if not ROOT_WIPE_PATTERN.search(low_cmd):
                        has_destructive = False

                # INC-308: Only volume deletion or prune --volumes
                elif incident_id == "INC-308":
                    if not ("volume" in low_cmd or "--volumes" in low_cmd):
                        has_destructive = False

                # INC-402: Only ingress, namespace or --all deletion
                elif incident_id == "INC-402":
                    if not any(k in low_cmd for k in ("ingress", "namespace", "ns ", "ns/", "--all")):
                        has_destructive = False

            # Recalibrated decision thresholds:
            # Benign commands without destructive markers pass cleanly
            status = "PASSED"
            if has_destructive:
                if score >= SIMILARITY_BLOCK_THRESHOLD:
                    status = "BLOCKED"
                elif score >= SIMILARITY_WARN_THRESHOLD:
                    status = "WARNING"

            rec = payload.get("recommendation")
            if not has_destructive and status == "PASSED":
                rec = "Benign infrastructure command verified safe to execute."
            elif not rec:
                rec = f"Matched past incident {payload.get('incident_id')}."

            res = CheckResult(
                command=clean_cmd,
                status=status,
                is_intercepted=(status != "PASSED"),
                matched_incident_id=payload.get("incident_id") if status != "PASSED" else None,
                matched_incident_title=payload.get("title") if status != "PASSED" else None,
                matched_pattern=payload.get("matched_pattern") if status != "PASSED" else None,
                severity=payload.get("severity") if status != "PASSED" else None,
                similarity_score=round(score, 4),
                safe_alternative=payload.get("safe_alternative") if status != "PASSED" else None,
                safe_alternative_cmd=payload.get("safe_alternative_cmd") if status != "PASSED" else None,
                safe_alternative_notes=payload.get("safe_alternative_notes") if status != "PASSED" else None,
                blast_radius=payload.get("blast_radius") if status != "PASSED" else None,
                recommendation=rec,
                latency_ms=round(elapsed_ms, 3),
                env_context=env_dict,
                env_badge=env_badge,
            )
        else:
            res = CheckResult(
                command=clean_cmd,
                status="PASSED",
                is_intercepted=False,
                similarity_score=0.0,
                latency_ms=round(elapsed_ms, 3),
                recommendation="No matching past incident identified.",
                env_context=env_dict,
                env_badge=env_badge,
            )

        self._record_telemetry(res)
        return res

    def _record_telemetry(self, result: CheckResult):
        """Append to in-memory ring buffer for telemetry dashboard and increment persistent counters."""
        self.total_checks_count += 1
        if result.status == "BLOCKED":
            self.blocked_count += 1
        elif result.status == "WARNING":
            self.warning_count += 1
        else:
            self.passed_count += 1

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
                "total_checks": self.total_checks_count,
                "total_checks_count": self.total_checks_count,
                "blocked_count": self.blocked_count,
                "warning_count": self.warning_count,
                "passed_count": self.passed_count,
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

        return {
            "total_checks": self.total_checks_count,
            "total_checks_count": self.total_checks_count,
            "blocked_count": self.blocked_count,
            "warning_count": self.warning_count,
            "passed_count": self.passed_count,
            "p50_latency_ms": round(p50, 2),
            "p95_latency_ms": round(p95, 2),
            "p99_latency_ms": round(p99, 2),
            "average_latency_ms": round(avg_lat, 2),
            "total_incidents_loaded": len(self.incidents),
            "total_chunks_indexed": self.total_docs_indexed,
        }
