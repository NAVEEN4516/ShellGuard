# Project: ShellGuard Dynamic Incident Learning and Multi-Cloud Context Awareness

## Architecture
ShellGuard enhances command-line execution safety with real-time vector similarity interception powered by Moss in-memory vector index.
This project extends ShellGuard with:
1. **Multi-Cloud Context Awareness (`daemon/context.py`)**: Sub-millisecond, pure-Python active environment detection reading Kubernetes context, AWS profile/region, and Git branch with mtime caching.
2. **Dynamic Incident Hot-Reloading (`daemon/engine.py`, `daemon/indexer.py`, `daemon/server.py`)**: Zero-downtime runtime ingestion of disaster post-mortem markdown via `POST /api/incidents` and CLI `shellguard learn`, injecting chunks directly into `moss_core.LocalIndexManager.add_documents()` and dynamically expanding interception prefixes.
3. **Environment Badging & Decorated Alerts**: Decorating interception outputs across engine, shell hooks (`.zsh`, `.bash`, `.ps1`), CLI, telemetry, and the Web Cockpit (`web/index.html`).
4. **Web Cockpit Live Radar Synchronization**: Real-time event streaming (`/api/events`) and dynamic incident explorer updates without page reload.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Pure-Python Sub-Millisecond Context Detector | Pure-Python K8s, AWS, and Git context detection with mtime caching (<0.5ms uncached, <0.02ms cached, zero yaml/boto3 deps) | M1 | survey |
| F2 | Engine Context Awareness & Environment Badging | `CheckResult` with `env_badge` and `environment`, `engine.evaluate(..., cwd=...)`, telemetry logging with environment | M2 | survey |
| F3 | Incident Parser & Recommendation Regex Fix | Fix `parse_incident_markdown` regex `[-*]` to extract safe alternatives and generate Moss document chunks | M2 | survey |
| F4 | Dynamic Incident Hot-Reloading & Prefix Expansion | `engine.learn_incident()` using `LocalIndexManager.add_documents()` and dynamic `interception_prefixes` expansion | M2 | survey |
| F5 | Daemon API Server & Live Events Stream | `POST /api/incidents` (HTTP 201), `req.cwd` forwarding in `/api/check`, and SSE `/api/events` broadcast | M3 | survey |
| F6 | Shell Hooks & CLI Integration | Update `.zsh`, `.bash`, `.ps1` hooks with `cwd` and `[ENV: <badge>]`; implement `shellguard learn <path-or-markdown>` CLI command | M4 | survey |
| F7 | Web Cockpit Live Dynamic Updates | Dynamic SSE/polling radar feed with environment badges and incident explorer updates in `web/index.html` | M3 | survey |
| F8 | E2E Test Suite & Latency Benchmarks | `tests/test_dynamic_learning.py`, `tests/test_context_detector.py`, 54 regression tests pass, warm latency p50 < 10ms | M5 / E2E Track | survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Sub-Millisecond Multi-Cloud Context Detector | `daemon/context.py` pure Python detector for K8s, AWS, Git (<0.5ms) | none | IN_PROGRESS |
| M2 | Engine Incident Learning & Environment Badging | `daemon/engine.py`, `daemon/indexer.py`: incident hot-reloading, regex fix, dynamic prefixes, badging | M1 | PLANNED |
| M3 | Daemon API Server & Live Web Cockpit | `daemon/server.py`, `web/index.html`: `POST /api/incidents`, `/api/events` SSE, radar feed & incident explorer | M2 | PLANNED |
| M4 | Shell Hooks & CLI Client | `hooks/shellguard.*`, `cli.py`: pass `cwd`, render badges, `shellguard learn` command | M3 | PLANNED |
| M5 | Final Milestone: E2E Test Suite Pass & Adversarial Hardening | Pass 100% E2E tests (`test_dynamic_learning.py`, `test_context_detector.py`, 54 regression tests, latency p50 < 10ms), Tier 5 hardening | M4, TEST_READY.md | PLANNED |

## Interface Contracts

### `daemon/context.py`
```python
class ContextDetector:
    def detect(self, cwd: Optional[str] = None) -> Dict[str, Optional[str]]:
        """Returns {"k8s": str|None, "aws": str|None, "git": str|None}"""
    def format_badge(self, env: Dict[str, Optional[str]]) -> Optional[str]:
        """Returns e.g. '[ENV: prod-us-east-1 (k8s)]' or None if all null"""
```

### `daemon/indexer.py`
```python
def parse_incident_markdown(content: str) -> Incident:
    """Parses markdown with regex fix r'[-*]\s+\*\*Recommendation:\*\*\s+(.*?)$' and extracts safe alternatives."""

def incident_to_chunks(incident: Incident) -> List[Dict[str, Any]]:
    """Converts incident into chunks formatted for moss_core.LocalIndexManager."""
```

### `daemon/engine.py`
```python
@dataclass
class CheckResult:
    status: str
    match_type: Optional[str]
    similarity_score: float
    matched_incident_id: Optional[str]
    matched_incident_title: Optional[str]
    safe_alternative: Optional[str]
    explanation: Optional[str]
    latency_ms: float
    risk_level: str
    env_badge: Optional[str] = None
    environment: Optional[Dict[str, Optional[str]]] = None

class ShellGuardEngine:
    def evaluate(self, command: str, cwd: Optional[str] = None) -> CheckResult:
        ...
    def learn_incident(self, incident_content: str, incident_path: Optional[str] = None) -> Dict[str, Any]:
        """Dynamically indexes incident into active in-memory LocalIndexManager, expands interception_prefixes, returns summary."""
```

### `daemon/server.py`
```python
# Endpoints:
POST /api/check       # Accepts CommandCheckRequest(command, cwd, shell), returns CheckResult dict
POST /api/incidents   # Accepts IncidentLearnRequest(path, markdown), returns 201 {"status": "learned", "incident_id": ..., "chunks_added": ...}
GET  /api/events      # SSE stream broadcasting CheckResult and IncidentLearned events
```

### `cli.py`
```bash
shellguard check "<command>"
shellguard learn <path-or-markdown>
```

## Code Layout
- `daemon/context.py`: Multi-cloud context detector (M1)
- `daemon/engine.py`: Engine evaluation, incident learning, badging (M2)
- `daemon/indexer.py`: Incident markdown parsing and chunk generation (M2)
- `daemon/server.py`: FastAPI endpoints and SSE event streaming (M3)
- `web/index.html`: Web Cockpit live radar feed and incident explorer (M3)
- `hooks/shellguard.zsh`: Zsh preexec hook sending `cwd` and displaying badges (M4)
- `hooks/shellguard.bash`: Bash preexec hook sending `cwd` and displaying badges (M4)
- `hooks/shellguard.ps1`: PowerShell prompt hook sending `cwd` and displaying badges (M4)
- `cli.py`: ShellGuard CLI client (M4)
- `tests/test_context_detector.py`: Context detector unit and benchmark tests (E2E Track / M5)
- `tests/test_dynamic_learning.py`: Dynamic incident hot-reloading tests (E2E Track / M5)
- `tests/test_engine.py`, `tests/test_safety_matrix.py`, `tests/test_api.py`: Regression test suite (54 tests)
