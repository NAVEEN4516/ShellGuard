# Technical Architecture & Exploration Analysis: Context Detection, Badging & Incident Learning

**Target Modules:** `daemon/context.py` (New), `daemon/engine.py`, `daemon/indexer.py`, `daemon/server.py`, `cli.py`, `hooks/shellguard.{zsh,bash,ps1}`, `web/index.html`  
**Requirements Covered:** R1 (Dynamic Learning CLI), R2 (Sub-Millisecond Multi-Cloud Context Detection), R3 (Environment Badges & Interception Alerts)  
**Author:** Survey Explorer 2  
**Timestamp:** 2026-09-13T13:30:00Z  

---

## 1. Executive Summary

This investigation analyzed technical requirements, architecture, and performance characteristics for extending ShellGuard with:
1. **R2: Sub-Millisecond Multi-Cloud Environment Context Detection** — Pure Python (< 0.01ms warm, < 0.5ms cold) parsing of active Kubernetes cluster context, AWS profile/region, and Git branch. Zero external dependencies (`pyyaml` and `boto3` are neither installed nor needed).
2. **R3: Environment Badges & Decorated Interception Alerts** — Consistent visual environment badging (`[ENV: prod-us-east-1 (k8s)]`) across engine check results, all three shell hooks (`.zsh`, `.bash`, `.ps1`), the CLI (`cli.py`), telemetry history, and the Web Cockpit radar feed.
3. **CLI Command `shellguard learn <path-or-markdown>`** — Dynamic incident ingestion invoking `POST /api/incidents` to hot-add documents into the active in-memory `moss_core.LocalIndexManager` without restarting the server or dropping connections, backed by local file fallback when the daemon is offline.

All 54 existing tests in `tests/` currently pass (11.06s execution). Live benchmarking confirms context detection requires **8.8 microseconds (0.0088ms)** per check with TTL-mtime caching, well below the 0.5ms/check budget and preserving the < 10ms end-to-end warm query budget.

---

## 2. Current Codebase Baseline

### 2.1 Dependencies & Runtime Environment
Inspection of `requirements.txt` and the virtual environment (`.venv`):
- `moss>=1.7.0` (compiled Rust native extension `moss_core`)
- `fastapi>=0.115.0`, `uvicorn>=0.30.0`, `pydantic>=2.8.0`
- `pytest>=8.0.0`, `httpx>=0.27.0`, `rich>=13.7.0`
- **Neither `pyyaml` nor `boto3` are installed.** Any context detection solution must rely strictly on the Python standard library (`os`, `re`, `time`, `pathlib`, `configparser`).

### 2.2 Existing In-Process Moss Runtime
- `daemon/engine.py`: Uses `moss_core.LocalIndexManager` for sub-10ms semantic vector retrieval over disaster chunks.
- Verification via Python introspection confirms `LocalIndexManager` exposes:
  `add_documents(index_name: str, docs: List[DocumentInfo], options=None)`
- Testing proves calling `add_documents` on an active index takes ~19ms for chunk embedding and immediately affects subsequent `index_manager.query()` calls without needing `delete_index` or re-indexing!

---

## 3. Sub-Millisecond Multi-Cloud Environment Context Detection (R2)

### 3.1 Kubernetes Context Detection
- **Source Paths:**
  1. `$KUBECONFIG` environment variable (highest precedence). If colon/semicolon separated, take the first valid existing path.
  2. Fallback: `~/.kube/config` (`os.path.expanduser("~/.kube/config")`).
- **Parsing Strategy (Zero-PyYAML):**
  Standard kubeconfig YAML places `current-context: <name>` at the root level.
  A streaming line scan or regex search:
  `re.compile(r"^\s*current-context:\s*['\"]?([^'\"#\r\n\s]+)['\"]?", re.MULTILINE)`
  locates the active context without loading the entire document into an AST.
- **Caching Mechanism:**
  Cache key: `kubeconfig_path`. Store `(last_check_timestamp, file_mtime, cached_context)`.
  With a 0.5s check-throttling TTL, repeated terminal commands execute in **< 0.002ms**. Even when mtime is re-verified, `os.stat` completes in 0.06ms.

### 3.2 AWS Profile & Region Detection
- **Precedence Order:**
  1. Environment variables:
     - Profile: `AWS_PROFILE` or `AWS_DEFAULT_PROFILE`
     - Region: `AWS_REGION` or `AWS_DEFAULT_REGION`
     - If both are set via env (typical in CI/CD or aws-vault), disk access is 100% avoided (lookup time: **0.001ms**).
  2. Config File: `~/.aws/config` (or `$AWS_CONFIG_FILE`):
     - INI file containing `[default]` and `[profile <name>]` sections.
     - Fast INI scanner parses sections into a dict `sections[profile_name] = {'region': ...}`.
     - Look up profile (defaults to `"default"` if not in env) and read `region`.
- **Caching Mechanism:**
  Store parsed INI dict keyed by file path and mtime. Once parsed, profile and region resolution is a direct dict lookup (< 0.001ms).

### 3.3 Git Branch Detection
- **Source Path:**
  Traverse upward from `cwd` (up to 5 directory levels) looking for `.git`.
  - If `.git` is a directory: read `.git/HEAD`.
  - If `.git` is a file (git worktree or submodule): parse `gitdir: <path>` and read `<path>/HEAD`.
- **Parsing Strategy:**
  - Branch ref: `ref: refs/heads/<branch>` -> extract `<branch>` (e.g. `main`, `feature/auth`).
  - Detached HEAD: 40-char SHA -> extract `detached:<sha[:7]>`.
- **Caching Mechanism:**
  Keyed by `cwd` and `head_path`. Check `mtime` with 0.5s TTL. Mean lookup: **0.008ms**.

### 3.4 Micro-Benchmark Results
Empirical benchmarking conducted on the local Windows system (`test_bench2.py`, 10,000 warm iterations):
| Metric | Benchmark Result | Requirement Budget | Margin |
| :--- | :--- | :--- | :--- |
| **P50 Latency** | **0.0083 ms (8.3 μs)** | < 0.50 ms | **60x faster** |
| **Mean Latency** | **0.0088 ms (8.8 μs)** | < 0.50 ms | **56x faster** |
| **P95 Latency** | **0.0122 ms (12.2 μs)** | < 0.50 ms | **40x faster** |
| **Max Latency** | **0.1810 ms (181 μs)** | < 1.00 ms | **5.5x faster** |

Total impact on warm query budget: adding 0.01ms leaves over 9.9ms for Moss vector search, easily maintaining the **< 10ms end-to-end p50 budget**.

---

## 4. Environment Badges & Decorated Interception Alerts (R3)

### 4.1 Badge Formatting Specification
The badge string succinctly conveys active cloud context without cluttering developer consoles:
- Single Active Context:
  - Kubernetes: `[ENV: prod-us-east-1 (k8s)]`
  - AWS: `[ENV: prod:us-east-1 (aws)]` or `[ENV: production (aws)]`
  - Git: `[ENV: main (git)]`
- Multi-Active Context:
  - If multiple environments are detected:
    `[ENV: prod-us-east-1 (k8s) | main (git)]`
    `[ENV: prod-us-east-1 (k8s) | prod:us-east-1 (aws) | master (git)]`
- Default fallback when no cloud/git context is present:
  - `[ENV: local]` or `None`

### 4.2 Engine Integration (`daemon/engine.py`)
- `CheckResult` data model updated:
  ```python
  @dataclass
  class CheckResult:
      ...
      env_badge: Optional[str] = None
      environment: Optional[Dict[str, Any]] = None
  ```
- `engine.evaluate(command, cwd=None, env=None)`:
  1. Invokes `self.context_detector.detect(cwd=cwd, env=env)` at the beginning of evaluation.
  2. Includes `env_badge` and `environment` in all returned `CheckResult` instances (PASSED, WARNING, BLOCKED).
  3. `_record_telemetry` preserves environment metadata in `self.history`.

### 4.3 Shell Hook Decoration
All three shell hooks forward `cwd` to the daemon and render the badge on interception:
1. **Zsh (`hooks/shellguard.zsh`)**:
   - Sends: `{"command":"...","shell":"zsh","cwd":"${PWD}"}`
   - Parses: `re_badge='"env_badge"[[:space:]]*:[[:space:]]*"([^"]*)"'`
   - Outputs:
     ```
     🛑 [SHELLGUARD BLOCKED] EXECUTION HALTED
     Environment:      [ENV: prod-us-east-1 (k8s)]
     Incident Match:   INC-402 — Production Ingress Namespace Deletion
     ```
2. **Bash (`hooks/shellguard.bash`)**:
   - Sends: `{"command":"...","shell":"bash","cwd":"${PWD}"}`
   - Parses `env_badge` via native regex.
   - Outputs `Environment: [ENV: prod-us-east-1 (k8s)]` in alerts.
3. **PowerShell (`hooks/shellguard.ps1`)**:
   - Sends: `cwd = (Get-Location).Path` in JSON body.
   - Outputs `Write-Host "Environment:      $($response.env_badge)" -ForegroundColor Magenta`.

### 4.4 CLI Decoration (`cli.py`)
In `check_command`:
- Passes `cwd=os.getcwd()` to daemon HTTP POST and in-process fallback.
- In `BLOCKED` panel: Displays `[magenta]Active Environment:[/magenta] [bold magenta]{env_badge}[/bold magenta]`.
- In `WARNING` panel: Displays environment tag.
- In `PASSED` line: `PASSED (1.2 ms) [ENV: prod-us-east-1 (k8s)] - Command verified safe to execute.`

### 4.5 Web Cockpit Radar Feed (`web/index.html`)
- In `renderResult(data)`: Appends an `#res-env` pill with `.badge.env-badge`.
- In `prependFeed(data)`: Includes `<span class="badge env-tag">${escapeHtml(data.env_badge)}</span>` in the feed item meta header.
- In `GET /api/history`: Returns `env_badge` and `environment` in historical entries.

---

## 5. CLI Command `shellguard learn <path-or-markdown>` & API

### 5.1 Command Interface
`shellguard learn <path-or-markdown> [--url DAEMON_URL]`
- **Argument handling:**
  - If argument is an existing file path (`Path(arg).is_file()`): reads content from disk.
  - If argument is raw markdown text: uses the string directly.
  - If argument is `-`: reads markdown from `sys.stdin`.

### 5.2 Server API Endpoint `POST /api/incidents`
- **Request Body:**
  ```python
  class IncidentIngestRequest(BaseModel):
      markdown: Optional[str] = Field(default=None, description="Raw incident markdown")
      file_path: Optional[str] = Field(default=None, description="Path to incident markdown file")
  ```
- **Execution Flow in Engine:**
  1. `parsed = parse_incident_markdown(source)` (enhanced to accept string or Path).
  2. Generates chunk documents (`DocumentInfo`) for triggering commands and incident summary.
  3. Executes `engine.index_manager.add_documents(INDEX_NAME, docs)`.
  4. Appends `parsed` incident to `engine.incidents`.
  5. Updates `engine.total_docs_indexed += len(docs)`.
  6. Dynamically updates `engine.interception_prefixes`: extracts root commands from `parsed["commands"]` (e.g. `redis-cli`, `vault`) and adds them to the fast-filter set so newly learned tools undergo semantic inspection without restarts.
  7. Returns 200 OK with `incident_id`, `title`, `chunks_added`, and `total_chunks_indexed`.

### 5.3 Offline Local Fallback
When daemon is offline (`urllib.request.urlopen` raises ConnectionRefused):
- Validates markdown syntax locally using `parse_incident_markdown`.
- Saves file to `data/incidents/<incident_id>.md`.
- Prints confirmation to engineer:
  `[dim]ShellGuard daemon offline. Verified incident and saved to data/incidents/<id>.md. Will be indexed on next daemon startup.[/dim]`

---

## 6. Contract & Affected Files Matrix

| File Path | Change Type | Responsibilities & Affected Interfaces |
| :--- | :--- | :--- |
| `daemon/context.py` | **NEW** | `ContextDetector`, `EnvironmentContext`. Fast k8s, AWS, and Git parser with TTL-mtime caching. Zero non-standard dependencies. |
| `daemon/engine.py` | Modify | Add `env_badge` & `environment` to `CheckResult`. Instantiate `ContextDetector`. Add `learn_incident()` method. Dynamic `interception_prefixes` expansion. |
| `daemon/indexer.py` | Modify | Update `parse_incident_markdown()` to accept `Union[Path, str]`. Extract `create_incident_chunks()` helper. |
| `daemon/server.py` | Modify | Add `POST /api/incidents`. Update `CommandCheckRequest` with `cwd` and `env`. Pass `cwd` to `engine.evaluate()`. Expose environment in `/api/history`. |
| `cli.py` | Modify | Add `learn` subparser. Implement `learn_command()`. Update `check_command()` to send `cwd` and display `env_badge`. |
| `hooks/shellguard.zsh` | Modify | Add `cwd` in payload. Parse and display `env_badge` in blocked/warning messages. |
| `hooks/shellguard.bash` | Modify | Add `cwd` in payload. Parse and display `env_badge` in blocked/warning messages. |
| `hooks/shellguard.ps1` | Modify | Add `cwd` in payload. Parse and display `env_badge` in blocked/warning messages. |
| `web/index.html` | Modify | Display environment badges in radar feed and interception cards. Dynamically refresh incident list upon ingestion. |
| `tests/test_context_detector.py` | **NEW** | Unit & latency tests (< 1.0ms) for k8s, AWS, and Git context detection. |
| `tests/test_dynamic_learning.py` | **NEW** | Integration tests for `POST /api/incidents` and `shellguard learn`, verifying immediate blocking of new commands. |

---

## 7. Verification Strategy for Implementers

1. **Context Detector Benchmark:**
   Run `pytest tests/test_context_detector.py -v`. Verify k8s context extraction, AWS profile/region extraction, Git branch extraction, and execution time < 1.0ms (target < 0.05ms).
2. **Dynamic Ingestion Verification:**
   Run `pytest tests/test_dynamic_learning.py -v`. Verify that posting a new incident markdown immediately causes `POST /api/check` to return `BLOCKED` with similarity > 0.70 in < 10ms.
3. **Regression Suite:**
   Run `pytest -v` across all test files. Ensure all 54 existing tests continue to pass without degradation.
4. **Shell Hook & CLI Verification:**
   Verify `python cli.py check "kubectl delete namespace ingress-nginx"` prints `[ENV: ... (k8s)]` in the Rich alert panel.
