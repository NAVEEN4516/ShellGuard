# Original User Request

## 2026-09-13T13:21:42Z

Enhance ShellGuard with Dynamic Incident Learning and Multi-Cloud Context Awareness: implement runtime hot-reloading of disaster post-mortems via `shellguard learn` and `POST /api/incidents` without daemon downtime, coupled with active environment detection (Kubernetes cluster context, AWS account/profile, and Git branch) to decorate interception alerts with live environment badges across all shell hooks.

Working directory: c:/Users/LENOVO/OneDrive - PESUNIVERSITY/YC Fall 2026 × Moss
Integrity mode: benchmark

## Verification Resources
- Existing automated test suite: `tests/test_engine.py`, `tests/test_safety_matrix.py`, `tests/test_api.py` (54 tests currently passing).
- Run command: `pytest -v`

## Requirements

### R1. Dynamic Incident Ingestion & Hot-Reloading
Provide an API endpoint `POST /api/incidents` and a CLI command `shellguard learn <path-or-markdown>` that parses new incident markdown files, extracts executable safe alternatives, and adds document chunks directly to the active in-memory Moss runtime (`moss_core.LocalIndexManager`) without daemon restarts or dropping active terminal hook connections.

### R2. Sub-Millisecond Multi-Cloud Environment Context Detection
Implement a lightweight context detector that reads the active Kubernetes context (from `~/.kube/config` or `KUBECONFIG`), active AWS profile/region (`AWS_PROFILE` / `~/.aws/config`), and active Git branch (`.git/HEAD`) in less than 0.5ms per check. Ensure context extraction does not degrade the warm query latency budget (< 10ms).

### R3. Environment Badges & Decorated Interception Alerts
Decorate the interception output in `daemon/engine.py`, the shell hooks (`hooks/shellguard.zsh`, `hooks/shellguard.bash`, `hooks/shellguard.ps1`), the CLI (`cli.py`), and the Web Cockpit (`web/index.html`) with the detected environment badge (e.g. `[ENV: prod-us-east-1 (k8s)]`). Record environment metadata in the history telemetry.

## Acceptance Criteria

### Verification & Performance Guardrails
- [ ] Programmatic test suite `tests/test_dynamic_learning.py` passes: hot-adding a new incident dynamically enables immediate (< 10ms) blocking of its triggering command without restarting the server.
- [ ] Programmatic test suite `tests/test_context_detector.py` passes: environment detector parses mock Kubernetes, AWS, and Git environments accurately in under 1.0ms.
- [ ] All 54 existing regression tests in `tests/` continue to pass with zero regressions.
- [ ] End-to-end warm query latency (including context detection and Moss semantic search) maintains a p50 of < 10.0ms.
- [ ] Web Cockpit (`web/index.html`) updates its live radar feed and incident explorer dynamically when a new incident is ingested via the API.
